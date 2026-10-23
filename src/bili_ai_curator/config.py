from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TOPIC_NAMES = {
    "ai_knowledge",
    "ai_derivative",
    "zzz",
    "hsr",
    "valorant",
}


@dataclass(frozen=True)
class TopicConfig:
    enabled: bool
    keywords: tuple[str, ...]
    exclude: tuple[str, ...]
    max_age_days: int


@dataclass(frozen=True)
class DeepSeekConfig:
    api_base: str
    api_key: str
    model: str


@dataclass(frozen=True)
class ScheduleConfig:
    active_start: str
    active_end: str
    poll_minutes_min: int
    poll_minutes_max: int
    comment_gap_minutes_min: int
    comment_gap_minutes_max: int


@dataclass(frozen=True)
class QualityConfig:
    threshold: float
    absolute_floor: float
    low_quality_limit: int
    daily_limit: int
    max_evaluations_per_cycle: int


@dataclass(frozen=True)
class WarmupConfig:
    read_only_hours: int
    daily_caps: tuple[int, ...]


@dataclass(frozen=True)
class AppConfig:
    owner_uid: int
    deepseek: DeepSeekConfig
    schedule: ScheduleConfig
    quality: QualityConfig
    warmup: WarmupConfig
    topics: dict[str, TopicConfig]
    dry_run: bool


def _topic_config(name: str, raw: dict[str, Any]) -> TopicConfig:
    keywords = tuple(str(value).strip() for value in raw.get("keywords", []) if str(value).strip())
    if not keywords:
        raise ValueError(f"{name}.keywords must not be empty")
    max_age_days = int(raw.get("max_age_days", 0))
    if max_age_days <= 0:
        raise ValueError(f"{name}.max_age_days must be positive")
    return TopicConfig(
        enabled=bool(raw.get("enabled", True)),
        keywords=keywords,
        exclude=tuple(
            str(value).strip() for value in raw.get("exclude", []) if str(value).strip()
        ),
        max_age_days=max_age_days,
    )


def load_config(path: Path, *, allow_unconfigured_owner: bool = False) -> AppConfig:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("config must contain a JSON object")

    owner_uid = int(raw.get("owner_uid", 0))
    dry_run = bool(raw.get("dry_run", True))
    if owner_uid <= 0 and not (dry_run and allow_unconfigured_owner):
        raise ValueError("owner_uid must be configured before live operation")

    deepseek_raw = raw["deepseek"]
    api_key_env = str(deepseek_raw.get("api_key_env", "DEEPSEEK_API_KEY"))
    api_key = os.environ.get(api_key_env, "").strip()
    if not api_key:
        raise ValueError(f"missing environment variable {api_key_env}")

    topics_raw = raw.get("topics")
    if not isinstance(topics_raw, dict):
        raise ValueError("topics must be an object")
    if set(topics_raw) != TOPIC_NAMES:
        raise ValueError("config must define exactly the five supported topics")

    schedule = ScheduleConfig(**raw["schedule"])
    quality = QualityConfig(**raw["quality"])
    warmup = WarmupConfig(
        read_only_hours=int(raw["warmup"]["read_only_hours"]),
        daily_caps=tuple(int(value) for value in raw["warmup"]["daily_caps"]),
    )
    if not warmup.daily_caps or max(warmup.daily_caps) > quality.daily_limit:
        raise ValueError("warmup daily caps must not exceed daily_limit")
    if schedule.poll_minutes_min > schedule.poll_minutes_max:
        raise ValueError("poll_minutes_min must not exceed poll_minutes_max")
    if schedule.comment_gap_minutes_min > schedule.comment_gap_minutes_max:
        raise ValueError("comment gap range is invalid")
    if quality.absolute_floor > quality.threshold:
        raise ValueError("absolute_floor must not exceed threshold")

    return AppConfig(
        owner_uid=owner_uid,
        deepseek=DeepSeekConfig(
            api_base=str(deepseek_raw["api_base"]).rstrip("/"),
            api_key=api_key,
            model=str(deepseek_raw["model"]),
        ),
        schedule=schedule,
        quality=quality,
        warmup=warmup,
        topics={
            name: _topic_config(name, value)
            for name, value in topics_raw.items()
        },
        dry_run=dry_run,
    )
