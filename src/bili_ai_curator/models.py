from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VideoCandidate:
    bvid: str
    title: str
    author_mid: int
    author_name: str
    pubdate: str
    views: int
    likes: int
    comments: int
    duration: int
    topic: str
    source_count: int = 1
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Evaluation:
    total: float
    relevant: float
    interesting: float
    popularity: float
    quality: float
    reason: str
    model: str


@dataclass(frozen=True)
class DailyState:
    day: str
    evaluated_count: int = 0
    consecutive_low_quality: int = 0
    comments_sent: int = 0
    status_comment_sent: bool = False
    stop_reason: str | None = None
    last_comment_at: str | None = None
    warmup_started_at: str | None = None
