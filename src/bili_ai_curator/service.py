from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, time as clock_time
from zoneinfo import ZoneInfo

from .bili_cli import BiliCLI, BiliCLIError
from .comments import compose_comment, status_comment
from .config import AppConfig
from .db import CuratorStore
from .deepseek import DeepSeekClient, DeepSeekError
from .models import VideoCandidate
from .scoring import (
    engagement_score,
    final_score,
    matches_topic,
    score_popularity,
    source_diversity_score,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
WRITE_STOP_CODES = {
    "risk_control",
    "captcha_required",
    "auth_expired",
    "not_logged_in",
}


@dataclass(frozen=True)
class CycleResult:
    evaluated: int = 0
    posted: int = 0
    stop_reason: str = "ok"
    dry_run: bool = True


def _parse_pubdate(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(SHANGHAI)


def parse_duration(value: object) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = str(value).strip()
    if not text:
        return 0
    if ":" not in text:
        try:
            return max(0, int(text))
        except ValueError:
            return 0
    total = 0
    for part in text.split(":"):
        if not part.strip().isdigit():
            return 0
        total = total * 60 + int(part)
    return total


def _active_time(now: datetime, start: str, end: str) -> bool:
    start_time = clock_time.fromisoformat(start)
    end_time = clock_time.fromisoformat(end)
    current = now.timetz().replace(tzinfo=None)
    return start_time <= current <= end_time


class CuratorService:
    def __init__(
        self,
        config: AppConfig,
        store: CuratorStore,
        bili: BiliCLI,
        deepseek: DeepSeekClient,
        *,
        sleeper=time.sleep,
    ) -> None:
        self.config = config
        self.store = store
        self.bili = bili
        self.deepseek = deepseek
        self.sleeper = sleeper

    def _daily_cap(self, day: str, now: datetime) -> tuple[int, str | None]:
        state = self.store.daily_state(day)
        if not state.warmup_started_at:
            persisted_start = self.store.earliest_warmup_started_at()
            state = self.store.set_daily_state(
                day, warmup_started_at=persisted_start or now.isoformat()
            )
        started = datetime.fromisoformat(state.warmup_started_at).astimezone(SHANGHAI)
        elapsed_hours = max(0.0, (now - started).total_seconds() / 3600)
        if elapsed_hours < self.config.warmup.read_only_hours:
            return 0, "warmup_read_only"
        active_hours = elapsed_hours - self.config.warmup.read_only_hours
        stage = min(int(active_hours // 24), len(self.config.warmup.daily_caps) - 1)
        return self.config.warmup.daily_caps[stage], None

    def _collect(self) -> dict[str, VideoCandidate]:
        cards_by_bvid: dict[str, dict] = {}

        def merge(items: list[dict]) -> None:
            for item in items:
                bvid = str(item.get("bvid") or "")
                if not bvid:
                    continue
                if bvid in cards_by_bvid:
                    cards_by_bvid[bvid]["source_count"] = min(
                        3, int(cards_by_bvid[bvid].get("source_count", 1)) + 1
                    )
                else:
                    cards_by_bvid[bvid] = {**item, "source_count": 1}

        merge(self.bili.recommend().get("items") or [])
        for zone in ("tech", "knowledge", "game"):
            try:
                merge(self.bili.rank(zone).get("items") or [])
            except BiliCLIError as exc:
                if exc.code in WRITE_STOP_CODES:
                    raise
        for topic in self.config.topics.values():
            if not topic.enabled:
                continue
            for keyword in topic.keywords[:3]:
                try:
                    merge(self.bili.search(keyword).get("items") or [])
                except BiliCLIError as exc:
                    if exc.code in WRITE_STOP_CODES:
                        raise

        candidates: dict[str, VideoCandidate] = {}
        ordered_topics = ["ai_derivative", "ai_knowledge", "zzz", "hsr", "valorant"]
        for bvid, card in cards_by_bvid.items():
            stat = card.get("stat") or {}
            author = card.get("author") or {}
            raw = card
            base = VideoCandidate(
                bvid=bvid,
                title=str(card.get("title") or ""),
                author_mid=int(author.get("mid") or 0),
                author_name=str(author.get("name") or ""),
                pubdate=str(card.get("pubdate") or ""),
                views=int(stat.get("view") or 0),
                likes=int(stat.get("like") or 0),
                comments=int(stat.get("reply") or 0),
                duration=parse_duration(card.get("duration")),
                topic="",
                source_count=int(card.get("source_count") or 1),
                raw=raw,
            )
            for topic_name in ordered_topics:
                topic = self.config.topics[topic_name]
                if topic.enabled and matches_topic(
                    base, topic.keywords, topic.exclude
                ):
                    age_hours = max(
                        0.0, (datetime.now(SHANGHAI) - _parse_pubdate(base.pubdate)).total_seconds() / 3600
                    )
                    if age_hours <= topic.max_age_days * 24:
                        candidates[bvid] = replace(base, topic=topic_name)
                    break
        return candidates

    def _status_comment(
        self,
        kind: str,
        owner_name: str,
        candidates: list[VideoCandidate],
        day: str,
    ) -> None:
        state = self.store.daily_state(day)
        if state.status_comment_sent:
            return
        text = status_comment(kind, owner_name)
        for candidate in reversed(candidates):
            try:
                result = self.bili.post_comment(
                    candidate.bvid, text, dry_run=self.config.dry_run
                )
            except BiliCLIError:
                continue
            if not self.config.dry_run and result.get("rpid"):
                visible = self.bili.check_comment(
                    candidate.bvid, int(result["rpid"])
                )
                if not visible.get("visible"):
                    self.store.record_event(
                        "comment_not_visible", {"bvid": candidate.bvid}
                    )
                    return
                self.store.record_comment(
                    candidate.bvid,
                    text,
                    rpid=int(result["rpid"]),
                    status="visible",
                    comment_type="status",
                    day=day,
                )
            return

    def run_once(self, now: datetime | None = None) -> CycleResult:
        now = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
        day = now.date().isoformat()
        state = self.store.daily_state(day)
        if state.stop_reason and state.stop_reason not in {"ok"}:
            return CycleResult(stop_reason=state.stop_reason, dry_run=self.config.dry_run)
        if not _active_time(
            now, self.config.schedule.active_start, self.config.schedule.active_end
        ):
            return CycleResult(stop_reason="outside_active_hours", dry_run=self.config.dry_run)

        cap, warmup_reason = self._daily_cap(day, now)
        can_post = warmup_reason is None
        if can_post and state.comments_sent >= cap:
            self.store.set_daily_state(day, stop_reason="quota_complete")
            return CycleResult(stop_reason="quota_complete", dry_run=self.config.dry_run)

        owner = self.bili.owner().get("owner") or {}
        owner_name = str(owner.get("name") or "").strip()
        if not owner_name:
            raise RuntimeError("Bilibili owner nickname is unavailable")

        try:
            all_candidates = list(self._collect().values())
        except BiliCLIError as exc:
            stop = exc.code if exc.code in WRITE_STOP_CODES else "api_error"
            self.store.set_daily_state(day, stop_reason=stop)
            self.store.record_event("bili_error", {"code": exc.code, "hint": exc.hint}, day)
            return CycleResult(stop_reason=stop, dry_run=self.config.dry_run)

        candidates = [item for item in all_candidates if not self.store.is_seen(item.bvid)]
        peer_views: dict[str, list[float]] = {}
        peer_videos: dict[str, list[VideoCandidate]] = {}
        for item in candidates:
            peer_views.setdefault(item.topic, []).append(float(item.views))
            peer_videos.setdefault(item.topic, []).append(item)

        evaluated = 0
        posted = 0
        low_streak = state.consecutive_low_quality
        ordered = sorted(
            candidates,
            key=lambda item: (
                score_popularity(
                    age_hours=max(
                        0.1,
                        (now - _parse_pubdate(item.pubdate)).total_seconds() / 3600,
                    ),
                    views=item.views,
                    peer_views=peer_views.get(item.topic, []),
                ),
                item.source_count,
            ),
            reverse=True,
        )[: self.config.quality.max_evaluations_per_cycle]

        for candidate in ordered:
            age_hours = max(
                0.1, (now - _parse_pubdate(candidate.pubdate)).total_seconds() / 3600
            )
            try:
                watch = self.bili.watch(candidate.bvid)
                evaluation = self.deepseek.evaluate(candidate, watch)
            except DeepSeekError as exc:
                if exc.code in {"insufficient_balance", "auth_error"}:
                    self.store.set_daily_state(day, stop_reason="insufficient_balance")
                    if can_post:
                        self._status_comment(
                            "insufficient_balance", owner_name, ordered, day
                        )
                    return CycleResult(
                        evaluated=evaluated,
                        posted=posted,
                        stop_reason="insufficient_balance",
                        dry_run=self.config.dry_run,
                    )
                self.store.record_event("deepseek_error", {"code": exc.code}, day)
                continue
            except BiliCLIError as exc:
                if exc.code in WRITE_STOP_CODES:
                    self.store.set_daily_state(day, stop_reason=exc.code)
                    return CycleResult(
                        evaluated=evaluated,
                        stop_reason=exc.code,
                        dry_run=self.config.dry_run,
                    )
                continue

            popularity = score_popularity(
                age_hours=age_hours,
                views=candidate.views,
                peer_views=peer_views.get(candidate.topic, []),
            )
            engagement = engagement_score(
                candidate, peer_videos.get(candidate.topic, [])
            )
            freshness = max(0.0, 1.0 - age_hours / (30 * 24))
            evaluation = replace(
                evaluation,
                popularity=popularity,
                total=final_score(
                    relevance=evaluation.relevant,
                    interest=evaluation.interesting,
                    popularity=popularity,
                    engagement=engagement,
                    freshness=freshness,
                    diversity=source_diversity_score(candidate.source_count),
                ),
            )
            self.store.save_video(candidate)
            self.store.save_evaluation(candidate.bvid, evaluation)
            evaluated += 1

            if evaluation.total < self.config.quality.absolute_floor:
                low_streak += 1
                self.store.set_daily_state(
                    day,
                    evaluated_count=state.evaluated_count + evaluated,
                    consecutive_low_quality=low_streak,
                )
                if low_streak >= self.config.quality.low_quality_limit:
                    self.store.set_daily_state(day, stop_reason="low_quality")
                    if can_post:
                        self._status_comment("low_quality", owner_name, ordered, day)
                    return CycleResult(
                        evaluated=evaluated,
                        posted=posted,
                        stop_reason="low_quality",
                        dry_run=self.config.dry_run,
                    )
                continue

            low_streak = 0
            self.store.set_daily_state(
                day,
                evaluated_count=state.evaluated_count + evaluated,
                consecutive_low_quality=0,
            )
            if evaluation.total < self.config.quality.threshold:
                continue

            if not can_post:
                return CycleResult(
                    evaluated=evaluated,
                    posted=0,
                    stop_reason="warmup_read_only",
                    dry_run=self.config.dry_run,
                )

            sequence = self.store.daily_state(day).comments_sent + 1
            body = self.deepseek.generate_comment(
                candidate,
                reason=evaluation.reason,
                greeting=sequence == 1,
            )
            text = compose_comment(
                body,
                owner_name,
                sequence,
                now,
                finished_day=sequence == 5,
            )
            dry_run = self.config.dry_run
            try:
                result = self.bili.post_comment(
                    candidate.bvid, text, dry_run=dry_run
                )
            except BiliCLIError as exc:
                if exc.code in WRITE_STOP_CODES:
                    self.store.set_daily_state(day, stop_reason=exc.code)
                    return CycleResult(
                        evaluated=evaluated,
                        stop_reason=exc.code,
                        dry_run=dry_run,
                    )
                self.store.record_event(
                    "comment_error", {"bvid": candidate.bvid, "code": exc.code}, day
                )
                continue

            if not dry_run:
                rpid = result.get("rpid")
                if not rpid:
                    self.store.record_event(
                        "comment_missing_rpid", {"bvid": candidate.bvid}, day
                    )
                    continue
                visible = self.bili.check_comment(candidate.bvid, int(rpid))
                if not visible.get("visible"):
                    self.store.set_daily_state(day, stop_reason="comment_not_visible")
                    return CycleResult(
                        evaluated=evaluated,
                        stop_reason="comment_not_visible",
                        dry_run=False,
                    )
                self.store.record_comment(
                    candidate.bvid,
                    text,
                    rpid=int(rpid),
                    status="visible",
                    comment_type="recommendation",
                    day=day,
                    daily_limit=cap,
                )
            posted = 1
            return CycleResult(
                evaluated=evaluated,
                posted=posted,
                stop_reason="ok",
                dry_run=dry_run,
            )

        return CycleResult(
            evaluated=evaluated,
            posted=posted,
            stop_reason="warmup_read_only" if not can_post else "ok",
            dry_run=self.config.dry_run,
        )

    def run_forever(self, stop_event: threading.Event | None = None) -> None:
        stop_event = stop_event or threading.Event()
        while not stop_event.is_set():
            result = self.run_once()
            if result.stop_reason in WRITE_STOP_CODES | {"low_quality", "insufficient_balance"}:
                break
            if result.stop_reason == "warmup_read_only":
                delay_minutes = random.uniform(60, 120)
            else:
                delay_minutes = random.uniform(
                    self.config.schedule.poll_minutes_min,
                    self.config.schedule.poll_minutes_max,
                )
            stop_event.wait(delay_minutes * 60)
