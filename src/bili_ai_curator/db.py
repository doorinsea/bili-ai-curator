from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import DailyState, Evaluation, VideoCandidate


class CuratorStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def close(self) -> None:
        self._connection.close()

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS videos (
                bvid TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                author_mid INTEGER NOT NULL,
                author_name TEXT NOT NULL,
                pubdate TEXT NOT NULL,
                views INTEGER NOT NULL,
                likes INTEGER NOT NULL,
                comments INTEGER NOT NULL,
                duration INTEGER NOT NULL,
                topic TEXT NOT NULL,
                source_count INTEGER NOT NULL,
                raw_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS evaluations (
                bvid TEXT PRIMARY KEY,
                total REAL NOT NULL,
                relevant REAL NOT NULL,
                interesting REAL NOT NULL,
                popularity REAL NOT NULL,
                quality REAL NOT NULL,
                reason TEXT NOT NULL,
                model TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bvid TEXT NOT NULL,
                text TEXT NOT NULL,
                rpid INTEGER,
                status TEXT NOT NULL,
                comment_type TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS daily_state (
                day TEXT PRIMARY KEY,
                evaluated_count INTEGER NOT NULL DEFAULT 0,
                consecutive_low_quality INTEGER NOT NULL DEFAULT 0,
                comments_sent INTEGER NOT NULL DEFAULT 0,
                status_comment_sent INTEGER NOT NULL DEFAULT 0,
                stop_reason TEXT,
                last_comment_at TEXT,
                warmup_started_at TEXT
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        self._connection.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def is_seen(self, bvid: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM videos WHERE bvid=? LIMIT 1", (bvid,)
        ).fetchone()
        return row is not None

    def save_video(self, video: VideoCandidate) -> None:
        self._connection.execute(
            """
            INSERT INTO videos
                (bvid, title, author_mid, author_name, pubdate, views, likes,
                 comments, duration, topic, source_count, raw_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(bvid) DO UPDATE SET
                title=excluded.title,
                author_mid=excluded.author_mid,
                author_name=excluded.author_name,
                pubdate=excluded.pubdate,
                views=excluded.views,
                likes=excluded.likes,
                comments=excluded.comments,
                duration=excluded.duration,
                topic=excluded.topic,
                source_count=excluded.source_count,
                raw_json=excluded.raw_json
            """,
            (
                video.bvid,
                video.title,
                video.author_mid,
                video.author_name,
                video.pubdate,
                video.views,
                video.likes,
                video.comments,
                video.duration,
                video.topic,
                video.source_count,
                json.dumps(video.raw, ensure_ascii=False),
                self._now(),
            ),
        )
        self._connection.commit()

    def save_evaluation(self, bvid: str, evaluation: Evaluation) -> None:
        self._connection.execute(
            """
            INSERT INTO evaluations
                (bvid, total, relevant, interesting, popularity, quality,
                 reason, model, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(bvid) DO UPDATE SET
                total=excluded.total,
                relevant=excluded.relevant,
                interesting=excluded.interesting,
                popularity=excluded.popularity,
                quality=excluded.quality,
                reason=excluded.reason,
                model=excluded.model,
                created_at=excluded.created_at
            """,
            (
                bvid,
                evaluation.total,
                evaluation.relevant,
                evaluation.interesting,
                evaluation.popularity,
                evaluation.quality,
                evaluation.reason,
                evaluation.model,
                self._now(),
            ),
        )
        self._connection.commit()

    def record_comment(
        self,
        bvid: str,
        text: str,
        *,
        rpid: int | None,
        status: str,
        comment_type: str,
        day: str,
        daily_limit: int = 5,
    ) -> None:
        now = self._now()
        with self._connection:
            self._connection.execute("BEGIN IMMEDIATE")
            self._ensure_daily_state(day)
            if comment_type == "recommendation":
                row = self._connection.execute(
                    "SELECT comments_sent FROM daily_state WHERE day=?", (day,)
                ).fetchone()
                if int(row["comments_sent"]) >= daily_limit:
                    raise ValueError("daily comment limit reached")
            self._connection.execute(
                """
                INSERT INTO comments
                    (bvid, text, rpid, status, comment_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (bvid, text, rpid, status, comment_type, now),
            )
            if comment_type == "recommendation":
                self._connection.execute(
                    """
                    UPDATE daily_state
                    SET comments_sent=comments_sent+1, last_comment_at=?
                    WHERE day=?
                    """,
                    (now, day),
                )
            elif comment_type == "status":
                self._connection.execute(
                    "UPDATE daily_state SET status_comment_sent=1 WHERE day=?",
                    (day,),
                )

    def _ensure_daily_state(self, day: str) -> None:
        self._connection.execute(
            "INSERT OR IGNORE INTO daily_state(day) VALUES (?)", (day,)
        )

    def daily_state(self, day: str) -> DailyState:
        with self._connection:
            self._ensure_daily_state(day)
        row = self._connection.execute(
            "SELECT * FROM daily_state WHERE day=?", (day,)
        ).fetchone()
        return DailyState(
            day=row["day"],
            evaluated_count=row["evaluated_count"],
            consecutive_low_quality=row["consecutive_low_quality"],
            comments_sent=row["comments_sent"],
            status_comment_sent=bool(row["status_comment_sent"]),
            stop_reason=row["stop_reason"],
            last_comment_at=row["last_comment_at"],
            warmup_started_at=row["warmup_started_at"],
        )

    def set_daily_state(self, day: str, **changes: Any) -> DailyState:
        allowed = {
            "evaluated_count",
            "consecutive_low_quality",
            "comments_sent",
            "status_comment_sent",
            "stop_reason",
            "last_comment_at",
            "warmup_started_at",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unsupported daily state fields: {sorted(unknown)}")
        with self._connection:
            self._ensure_daily_state(day)
            if changes:
                assignments = ", ".join(f"{key}=?" for key in changes)
                values = [
                    int(value) if isinstance(value, bool) else value
                    for value in changes.values()
                ]
                self._connection.execute(
                    f"UPDATE daily_state SET {assignments} WHERE day=?",
                    (*values, day),
                )
        return self.daily_state(day)

    def record_event(
        self, kind: str, payload: dict[str, Any], day: str | None = None
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO events(day, kind, payload_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (day, kind, json.dumps(payload, ensure_ascii=False), self._now()),
        )
        self._connection.commit()
