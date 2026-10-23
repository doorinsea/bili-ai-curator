from pathlib import Path

from bili_ai_curator.cli import load_dotenv_file, make_parser


def test_dry_run_is_default_config(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    from bili_ai_curator.config import load_config

    path = tmp_path / "config.json"
    path.write_text(
        '{"owner_uid":1,'
        '"deepseek":{"api_base":"https://api.deepseek.com/v1",'
        '"api_key_env":"DEEPSEEK_API_KEY","model":"deepseek-flash"},'
        '"schedule":{"active_start":"09:00","active_end":"23:30",'
        '"poll_minutes_min":10,"poll_minutes_max":20,'
        '"comment_gap_minutes_min":20,"comment_gap_minutes_max":45},'
        '"quality":{"threshold":0.72,"absolute_floor":0.62,'
        '"low_quality_limit":10,"daily_limit":5,'
        '"max_evaluations_per_cycle":12},'
        '"warmup":{"read_only_hours":48,"daily_caps":[1,3,5]},'
        '"topics":{'
        '"ai_knowledge":{"keywords":["AI"],"exclude":[],"max_age_days":7},'
        '"ai_derivative":{"keywords":["AI"],"exclude":[],"max_age_days":30},'
        '"zzz":{"keywords":["绝区零"],"exclude":[],"max_age_days":14},'
        '"hsr":{"keywords":["星铁"],"exclude":[],"max_age_days":14},'
        '"valorant":{"keywords":["无畏契约"],"exclude":[],"max_age_days":7}}}',
        encoding="utf-8",
    )
    assert load_config(path).dry_run is True


def test_dotenv_does_not_override_existing_environment(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "existing")
    dotenv = tmp_path / ".env"
    dotenv.write_text("DEEPSEEK_API_KEY=new\nOTHER_VALUE=ok\n", encoding="utf-8")
    load_dotenv_file(dotenv)
    import os

    assert os.environ["DEEPSEEK_API_KEY"] == "existing"
    assert os.environ["OTHER_VALUE"] == "ok"


def test_parser_has_commands():
    parser = make_parser()
    assert parser.parse_args(["once"]).command == "once"
    assert parser.parse_args(["owner", "123"]).uid == 123
