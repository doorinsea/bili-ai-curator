from datetime import datetime
from zoneinfo import ZoneInfo

from bili_ai_curator.comments import compose_comment, sanitize_comment, status_comment


def test_first_and_fifth_comments():
    now = datetime(2026, 10, 23, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    first = compose_comment("这个模型测试很详细", "主人", 1, now, False)
    fifth = compose_comment("这个二创很有意思", "主人", 5, now, True)
    assert first.startswith("早上好，新的一天又开始了。")
    assert "@主人" in first
    assert fifth.endswith("今天的大白饭吃完了，等明天有饭吃再给主人推")


def test_later_comments_do_not_repeat_greeting():
    now = datetime(2026, 10, 23, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    comment = compose_comment("配队思路讲得很清楚", "主人", 2, now, False)
    assert "下午好" not in comment
    assert comment.startswith("配队思路讲得很清楚")


def test_mentions_links_and_markdown_are_normalized():
    raw = "**太强了**，看看 https://example.com 吧 @主人 @主人"
    assert sanitize_comment(raw, "主人") == "太强了，看看 吧 @主人"


def test_status_comments():
    assert "今天刷到的视频都太一般了" in status_comment("low_quality", "主人")
    assert "DeepSeek 余额不足" in status_comment("insufficient_balance", "主人")
