from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bili_ai_curator.config import (
    AppConfig,
    DeepSeekConfig,
    QualityConfig,
    ScheduleConfig,
    TopicConfig,
    WarmupConfig,
)
from bili_ai_curator.db import CuratorStore
from bili_ai_curator.deepseek import DeepSeekError
from bili_ai_curator.models import Evaluation
from bili_ai_curator.service import CuratorService


def make_config(dry_run: bool = True) -> AppConfig:
    topics = {
        name: TopicConfig(True, ("AI",), (), 30)
        for name in ["ai_knowledge", "ai_derivative", "zzz", "hsr", "valorant"]
    }
    return AppConfig(
        owner_uid=1,
        deepseek=DeepSeekConfig("https://api.deepseek.com/v1", "key", "deepseek-flash"),
        schedule=ScheduleConfig("00:00", "23:59", 1, 1, 1, 1),
        quality=QualityConfig(0.72, 0.62, 10, 5, 12),
        warmup=WarmupConfig(0, (5,)),
        topics=topics,
        dry_run=dry_run,
    )


def cards(count: int = 10):
    return {
        "items": [
            {
                "bvid": f"BV{index}",
                "title": f"AI 视频 {index}",
                "author": {"mid": index, "name": "up"},
                "pubdate": "2026-10-23T09:00:00+08:00",
                "stat": {"view": 1000, "like": 20, "reply": 5},
                "duration": 300,
            }
            for index in range(count)
        ]
    }


class FakeBili:
    def __init__(self):
        self.comments = []
        self.checked = []

    def owner(self):
        return {"owner": {"mid": 1, "name": "主人"}}

    def recommend(self, page=1):
        return cards()

    def rank(self, zone):
        return {"items": []}

    def search(self, keyword):
        return {"items": []}

    def watch(self, bvid):
        return {"bvid": bvid, "transcript": {"text": "AI 内容"}}

    def post_comment(self, bvid, text, dry_run):
        self.comments.append((bvid, text, dry_run))
        return {"dry_run": dry_run, "rpid": None if dry_run else 100 + len(self.comments)}

    def check_comment(self, bvid, rpid):
        self.checked.append((bvid, rpid))
        return {"visible": True, "folded": False}


class FakeDeepSeek:
    def __init__(self, score=0.1, error=None):
        self.score = score
        self.error = error

    def evaluate(self, video, watch):
        if self.error:
            raise self.error
        return Evaluation(
            total=self.score,
            relevant=self.score,
            interesting=self.score,
            popularity=0,
            quality=self.score,
            reason="no",
            model="deepseek-flash",
        )

    def generate_comment(self, video, reason, greeting):
        return f"这个视频的第{video.bvid}点很有意思"


def test_ten_low_quality_videos_stop_day_and_post_status(tmp_path: Path):
    store = CuratorStore(tmp_path / "state.db")
    bili = FakeBili()
    service = CuratorService(
        make_config(), store, bili, FakeDeepSeek(0.1), sleeper=lambda _: None
    )
    result = service.run_once(
        datetime(2026, 10, 23, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    assert result.stop_reason == "low_quality"
    assert bili.comments[-1][0] == "BV9"
    assert bili.comments[-1][2] is True
    assert "没有值得推荐" in bili.comments[-1][1]


def test_quota_stops_before_discovery(tmp_path: Path):
    store = CuratorStore(tmp_path / "state.db")
    store.set_daily_state("2026-10-23", comments_sent=5)
    bili = FakeBili()
    service = CuratorService(
        make_config(), store, bili, FakeDeepSeek(0.9), sleeper=lambda _: None
    )
    result = service.run_once(
        datetime(2026, 10, 23, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    assert result.stop_reason == "quota_complete"
    assert bili.comments == []


def test_insufficient_balance_posts_status(tmp_path: Path):
    store = CuratorStore(tmp_path / "state.db")
    bili = FakeBili()
    service = CuratorService(
        make_config(),
        store,
        bili,
        FakeDeepSeek(error=DeepSeekError("insufficient_balance", 402)),
        sleeper=lambda _: None,
    )
    result = service.run_once(
        datetime(2026, 10, 23, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    assert result.stop_reason == "insufficient_balance"
    assert "余额不足" in bili.comments[-1][1]


def test_warmup_start_persists_across_days(tmp_path: Path):
    store = CuratorStore(tmp_path / "state.db")
    config = make_config()
    config = AppConfig(
        owner_uid=config.owner_uid,
        deepseek=config.deepseek,
        schedule=config.schedule,
        quality=config.quality,
        warmup=WarmupConfig(48, (1, 3, 5)),
        topics=config.topics,
        dry_run=True,
    )
    store.set_daily_state(
        "2026-10-20", warmup_started_at="2026-10-20T00:00:00+08:00"
    )
    service = CuratorService(
        config, store, FakeBili(), FakeDeepSeek(0.9), sleeper=lambda _: None
    )
    cap, reason = service._daily_cap(
        "2026-10-22",
        datetime(2026, 10, 22, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert reason is None
    assert cap == 1
