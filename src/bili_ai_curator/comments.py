from __future__ import annotations

import re
from datetime import datetime


QUOTA_SENTENCE = "今天的大白饭吃完了，等明天有饭吃再给主人推"


def _mention(owner_name: str) -> str:
    name = owner_name.strip().lstrip("@")
    if not name:
        raise ValueError("owner_name must not be empty")
    return f"@{name}"


def sanitize_comment(text: str, owner_name: str) -> str:
    value = re.sub(r"https?://\S+", "", text)
    value = re.sub(r"[*_`#>]+", "", value)
    value = re.sub(r"\s+", " ", value).strip(" ，,。")
    mention = _mention(owner_name)
    value = value.replace(mention, "")
    value = re.sub(r"\s+", " ", value).strip(" ，,。")
    return f"{value} {mention}".strip()


def greeting_for(now: datetime) -> str:
    if now.hour < 12:
        return "早上好，新的一天又开始了。"
    if now.hour < 18:
        return "下午好。"
    return "晚上好。"


def compose_comment(
    content: str,
    owner_name: str,
    sequence: int,
    now: datetime,
    finished_day: bool,
) -> str:
    body = re.sub(r"\s+", " ", content).strip()
    if len(body) > 120:
        body = body[:119].rstrip() + "…"
    if sequence == 1:
        body = f"{greeting_for(now)}{body}"
    result = sanitize_comment(body, owner_name)
    if finished_day:
        if sequence != 5:
            raise ValueError("finished_day is only valid for the fifth comment")
        result = f"{result}，{QUOTA_SENTENCE}"
    return result


def status_comment(kind: str, owner_name: str) -> str:
    mention = _mention(owner_name)
    if kind == "low_quality":
        return f"今天刷到的视频都太一般了，没有值得推荐的 {mention}"
    if kind == "insufficient_balance":
        return f"今天没饭吃了，DeepSeek 余额不足，我先停止找视频了 {mention}"
    raise ValueError(f"unknown status comment kind: {kind}")
