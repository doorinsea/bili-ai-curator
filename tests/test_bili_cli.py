import json

import pytest

from bili_ai_curator.bili_cli import BiliCLI, BiliCLIError, CommandResult


def ok(data):
    return CommandResult(stdout=json.dumps({"ok": True, "data": data}), stderr="", returncode=0)


def test_comment_command_uses_owner_mention_and_dry_run():
    calls = []

    def runner(args):
        calls.append(args)
        return ok({"dry_run": True, "action": "comment.send"})

    cli = BiliCLI(runner=runner)
    result = cli.post_comment("BV123", "这个视频不错 @主人", dry_run=True)
    assert result["dry_run"] is True
    assert calls == [
        [
            "comment",
            "post",
            "BV123",
            "这个视频不错 @主人",
            "--at",
            "owner",
            "--dry-run",
        ]
    ]


def test_error_response_becomes_typed_exception():
    payload = {
        "ok": False,
        "error": {
            "code": "risk_control",
            "message": "blocked",
            "hint": "stop",
            "detail": {"retry_after": 600},
        },
    }
    cli = BiliCLI(
        runner=lambda _args: CommandResult(
            stdout=json.dumps(payload), stderr="", returncode=5
        )
    )
    with pytest.raises(BiliCLIError) as raised:
        cli.run(["feed", "recommend"])
    assert raised.value.code == "risk_control"
    assert raised.value.retry_after == 600
    assert raised.value.hint == "stop"


def test_watch_uses_bounded_context_options():
    calls = []

    def runner(args):
        calls.append(args)
        return ok({"bvid": "BV123"})

    BiliCLI(runner=runner).watch("BV123")
    assert calls[0] == [
        "video",
        "watch",
        "BV123",
        "--frames",
        "9",
        "--comments",
        "5",
        "--transcript",
        "auto",
        "--max-chars",
        "6000",
    ]


def test_check_comment_returns_visibility():
    cli = BiliCLI(
        runner=lambda _args: ok(
            {"rpid": 9, "found": True, "visible": True, "folded": False}
        )
    )
    result = cli.check_comment("BV123", 9)
    assert result["visible"] is True
