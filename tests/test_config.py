import json
from pathlib import Path

import pytest

from bili_ai_curator.config import load_config


def make_config(tmp_path: Path) -> Path:
    raw = {
        "owner_uid": 123,
        "dry_run": True,
        "deepseek": {
            "api_base": "https://api.deepseek.com/v1",
            "api_key_env": "DEEPSEEK_API_KEY",
            "model": "deepseek-flash",
        },
        "schedule": {
            "active_start": "09:00",
            "active_end": "23:30",
            "poll_minutes_min": 10,
            "poll_minutes_max": 20,
            "comment_gap_minutes_min": 20,
            "comment_gap_minutes_max": 45,
        },
        "quality": {
            "threshold": 0.72,
            "absolute_floor": 0.62,
            "low_quality_limit": 10,
            "daily_limit": 5,
            "max_evaluations_per_cycle": 12,
        },
        "warmup": {"read_only_hours": 48, "daily_caps": [1, 3, 5]},
        "topics": {
            key: {
                "enabled": True,
                "keywords": [key],
                "exclude": [],
                "max_age_days": 7,
            }
            for key in [
                "ai_knowledge",
                "ai_derivative",
                "zzz",
                "hsr",
                "valorant",
            ]
        },
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_load_config_has_five_topics(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    config = load_config(make_config(tmp_path))
    assert config.owner_uid == 123
    assert set(config.topics) == {
        "ai_knowledge",
        "ai_derivative",
        "zzz",
        "hsr",
        "valorant",
    }
    assert config.quality.daily_limit == 5
    assert config.deepseek.api_key == "test-key"
    assert config.dry_run is True


def test_load_config_rejects_missing_api_key(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        load_config(make_config(tmp_path))


def test_load_config_rejects_zero_owner_in_production_mode(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    path = make_config(tmp_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["owner_uid"] = 0
    raw["dry_run"] = False
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="owner_uid"):
        load_config(path)
