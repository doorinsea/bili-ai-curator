import json

import pytest

from bili_ai_curator.config import DeepSeekConfig
from bili_ai_curator.deepseek import (
    DeepSeekClient,
    DeepSeekError,
    is_insufficient_balance,
    parse_json_content,
)
from bili_ai_curator.models import VideoCandidate


def make_video() -> VideoCandidate:
    return VideoCandidate(
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
        raw={},
    )


def test_json_fence_is_removed():
    assert parse_json_content('```json\n{"score": 0.8}\n```') == {"score": 0.8}


def test_insufficient_balance_detection():
    assert is_insufficient_balance({"error": {"code": "insufficient_balance"}})
    assert is_insufficient_balance({"message": "Balance is not enough"})
    assert not is_insufficient_balance({"message": "rate limited"})


def test_evaluate_maps_model_json():
    calls = []

    def post(payload):
        calls.append(payload)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "relevant": 0.9,
                                "interesting": 0.8,
                                "quality": 0.85,
                                "reason": "讲清楚了新模型差异",
                                "comment": "这个对比很清楚，重点终于说明白了",
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }

    client = DeepSeekClient(
        DeepSeekConfig("https://api.deepseek.com/v1", "key", "deepseek-flash"),
        post=post,
    )
    evaluation = client.evaluate(make_video(), {"transcript": {"text": "正文"}})
    assert evaluation.relevant == 0.9
    assert evaluation.reason == "讲清楚了新模型差异"
    assert calls[0]["thinking"] == {"type": "disabled"}


def test_http_402_is_balance_stop():
    def post(_payload):
        raise DeepSeekError("insufficient_balance", status_code=402)

    client = DeepSeekClient(
        DeepSeekConfig("https://api.deepseek.com/v1", "key", "deepseek-flash"),
        post=post,
    )
    with pytest.raises(DeepSeekError) as raised:
        client.evaluate(make_video(), {})
    assert raised.value.code == "insufficient_balance"


def test_generate_comment_returns_plain_short_text():
    def post(_payload):
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"comment": "这个模型的实测部分挺有意思"},
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }

    client = DeepSeekClient(
        DeepSeekConfig("https://api.deepseek.com/v1", "key", "deepseek-flash"),
        post=post,
    )
    comment = client.generate_comment(
        make_video(),
        reason="实测充分",
        greeting=False,
    )
    assert comment == "这个模型的实测部分挺有意思"
