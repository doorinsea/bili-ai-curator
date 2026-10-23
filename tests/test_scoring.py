import pytest

from bili_ai_curator.models import VideoCandidate
from bili_ai_curator.scoring import (
    final_score,
    matches_topic,
    percentile_rank,
    score_popularity,
)


def test_percentile_rank():
    assert percentile_rank(300, [100, 200, 300, 400, 500]) == 0.6


def test_relative_popularity_prefers_early_breakout():
    peers = [100, 200, 300, 400, 500]
    young = score_popularity(age_hours=6, views=450, peer_views=peers)
    old = score_popularity(age_hours=720, views=450, peer_views=peers)
    assert young > old


def test_final_score_uses_approved_weights():
    score = final_score(
        relevance=1.0,
        interest=1.0,
        popularity=0.0,
        engagement=0.0,
        freshness=0.0,
        diversity=0.0,
    )
    assert score == pytest.approx(0.55)


def test_topic_match_uses_title_and_exclude_words():
    video = VideoCandidate(
        bvid="BV1",
        title="DeepSeek 新模型实测",
        author_mid=1,
        author_name="up",
        pubdate="2026-10-23T09:00:00+08:00",
        views=1000,
        likes=100,
        comments=20,
        duration=300,
        topic="ai_knowledge",
        raw={"desc": "大模型教程"},
    )
    assert matches_topic(video, ("DeepSeek", "新模型"), ())
    assert not matches_topic(video, ("DeepSeek",), ("教程",))
