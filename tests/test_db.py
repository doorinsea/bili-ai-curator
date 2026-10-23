from pathlib import Path

import pytest

from bili_ai_curator.db import CuratorStore
from bili_ai_curator.models import Evaluation, VideoCandidate


def make_video(bvid: str = "BV123") -> VideoCandidate:
    return VideoCandidate(
        bvid=bvid,
        title="AI news",
        author_mid=1,
        author_name="up",
        pubdate="2026-10-23T10:00:00+08:00",
        views=1000,
        likes=20,
        comments=5,
        duration=300,
        topic="ai_knowledge",
        source_count=2,
        raw={"bvid": bvid},
    )


def test_video_is_deduplicated_and_quota_persists(tmp_path: Path):
    store = CuratorStore(tmp_path / "state.db")
    video = make_video()
    store.save_video(video)
    store.save_evaluation(
        video.bvid,
        Evaluation(
            total=0.8,
            relevant=0.9,
            interesting=0.8,
            popularity=0.7,
            quality=0.85,
            reason="useful",
            model="deepseek-flash",
        ),
    )
    store.record_comment(
        video.bvid,
        "hello @owner",
        rpid=10,
        status="visible",
        comment_type="recommendation",
        day="2026-10-23",
    )
    assert store.is_seen(video.bvid)
    assert store.daily_state("2026-10-23").comments_sent == 1


def test_sixth_comment_is_rejected(tmp_path: Path):
    store = CuratorStore(tmp_path / "state.db")
    for index in range(5):
        bvid = f"BV{index}"
        store.save_video(make_video(bvid))
        store.record_comment(
            bvid,
            "comment",
            rpid=index,
            status="visible",
            comment_type="recommendation",
            day="2026-10-23",
            daily_limit=5,
        )
    with pytest.raises(ValueError, match="daily comment limit"):
        store.record_comment(
            "BV5",
            "comment",
            rpid=5,
            status="visible",
            comment_type="recommendation",
            day="2026-10-23",
            daily_limit=5,
        )


def test_daily_state_can_be_updated(tmp_path: Path):
    store = CuratorStore(tmp_path / "state.db")
    store.set_daily_state(
        "2026-10-23",
        evaluated_count=3,
        consecutive_low_quality=2,
        stop_reason="ok",
    )
    state = store.daily_state("2026-10-23")
    assert state.evaluated_count == 3
    assert state.consecutive_low_quality == 2
    assert state.stop_reason == "ok"
