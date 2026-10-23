# B站 AI 内容筛选与评论推荐助手 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Bilibili AI curator that scores videos in five configured topics and posts at most five targeted recommendation comments per day.

**Architecture:** A Python scheduler invokes the installed `bili` CLI for all Bilibili reads and writes. SQLite stores candidates, scores, quotas, deduplication and audit state; DeepSeek ranks videos and writes video-specific comments. The service never sends private messages and stops all writes on risk-control, balance, or authentication failures.

**Tech Stack:** Python 3.11, `requests`, SQLite, `bili-agent==0.7.0` (command `bili`), pytest, Windows PowerShell.

**Spec:** `docs/superpowers/specs/2026-10-23-bili-ai-curator-design.md`

## Global Constraints

- Bilibili only.
- No Bilibili desktop client dependency.
- No likes, coins, favorites, follows, direct messages, uploads, or profile edits.
- At most five successful recommendation comments per day.
- Comments must use `bili comment post <BV> "<text>" --at owner`.
- Every recommendation comment must mention the configured owner.
- The first recommendation of the day includes a time-appropriate greeting.
- The fifth recommendation ends with `今天的大白饭吃完了，等明天有饭吃再给主人推`.
- Ten consecutive DeepSeek-evaluated low-quality candidates stop the day and create one status comment on the latest commentable candidate.
- Insufficient DeepSeek balance stops the day and attempts one status comment on the latest commentable candidate.
- Stop all writes on `risk_control`, `captcha_required`, authentication expiry, or comment visibility failure.
- New-account sequence: 48 hours read-only, then daily comment caps of 1, 3, and 5.
- Do not store Bilibili cookies, DeepSeek keys, generated user data, or SQLite files in Git.
- No real Bilibili write operation may run in tests or dry-run mode.

---

### Task 1: Project Scaffold and Typed Configuration

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/bili_ai_curator/__init__.py`
- Create: `src/bili_ai_curator/config.py`
- Create: `config.example.json`
- Create: `tests/test_config.py`

**Interfaces:**
- Consumes: none.
- Produces: `load_config(path: Path) -> AppConfig`.
- Produces: dataclasses `TopicConfig`, `DeepSeekConfig`, `ScheduleConfig`, `QualityConfig`, `WarmupConfig`, `AppConfig`.

- [ ] **Step 1: Write the failing configuration test**

```python
from pathlib import Path
import json
from bili_ai_curator.config import load_config


def test_load_config_has_five_topics(tmp_path: Path):
    raw = {
        "owner_uid": 123,
        "deepseek": {"api_base": "https://api.deepseek.com/v1", "api_key_env": "DEEPSEEK_API_KEY", "model": "deepseek-flash"},
        "schedule": {"active_start": "09:00", "active_end": "23:30", "poll_minutes_min": 10, "poll_minutes_max": 20, "comment_gap_minutes_min": 20, "comment_gap_minutes_max": 45},
        "quality": {"threshold": 0.72, "absolute_floor": 0.62, "low_quality_limit": 10, "daily_limit": 5},
        "warmup": {"read_only_hours": 48, "daily_caps": [1, 3, 5]},
        "topics": {
            key: {"enabled": True, "keywords": [key], "exclude": [], "max_age_days": 7}
            for key in ["ai_knowledge", "ai_derivative", "zzz", "hsr", "valorant"]
        },
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    config = load_config(path)
    assert config.owner_uid == 123
    assert set(config.topics) == {"ai_knowledge", "ai_derivative", "zzz", "hsr", "valorant"}
    assert config.quality.daily_limit == 5
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `python -m pytest tests/test_config.py -q`

Expected: FAIL because `bili_ai_curator.config` does not exist.

- [ ] **Step 3: Create package metadata and configuration loader**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "bili-ai-curator"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "bili-agent==0.7.0",
  "requests>=2.32",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-cov>=5"]

[project.scripts]
bili-curator = "bili_ai_curator.cli:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

```python
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


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


def load_config(path: Path) -> AppConfig:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    api_key = os.environ.get(raw["deepseek"]["api_key_env"], "").strip()
    if not api_key:
        raise ValueError("DeepSeek API key environment variable is not set")
    topics = {
        name: TopicConfig(
            enabled=bool(value.get("enabled", True)),
            keywords=tuple(value.get("keywords", [])),
            exclude=tuple(value.get("exclude", [])),
            max_age_days=int(value["max_age_days"]),
        )
        for name, value in raw["topics"].items()
    }
    if set(topics) != {"ai_knowledge", "ai_derivative", "zzz", "hsr", "valorant"}:
        raise ValueError("config must define exactly the five supported topics")
    return AppConfig(
        owner_uid=int(raw["owner_uid"]),
        deepseek=DeepSeekConfig(raw["deepseek"]["api_base"].rstrip("/"), api_key, raw["deepseek"]["model"]),
        schedule=ScheduleConfig(**raw["schedule"]),
        quality=QualityConfig(**raw["quality"]),
        warmup=WarmupConfig(raw["warmup"]["read_only_hours"], tuple(raw["warmup"]["daily_caps"])),
        topics=topics,
        dry_run=bool(raw.get("dry_run", True)),
    )
```

- [ ] **Step 4: Add the example config and environment-only secret handling**

`config.example.json` must include all five topic blocks, `owner_uid: 0`, the schedule and quality values from the design, `"dry_run": true`, and `"api_key_env": "DEEPSEEK_API_KEY"`. Remove `owner_uid: 0` validation from `load_config` only if the CLI onboarding flow has not yet configured it; production startup must reject zero.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/test_config.py -q`

Expected: PASS.

```bash
git add pyproject.toml .gitignore src/bili_ai_curator/__init__.py src/bili_ai_curator/config.py config.example.json tests/test_config.py
git commit -m "feat: add project configuration"
```

### Task 2: Candidate Models and SQLite State

**Files:**
- Create: `src/bili_ai_curator/models.py`
- Create: `src/bili_ai_curator/db.py`
- Create: `tests/test_db.py`

**Interfaces:**
- Consumes: `AppConfig`.
- Produces: `VideoCandidate`, `Evaluation`, `CommentRecord`, `DailyState`.
- Produces: `CuratorStore` with `is_seen()`, `save_video()`, `save_evaluation()`, `record_comment()`, `daily_state()`, `set_daily_state()`, `record_event()`.

- [ ] **Step 1: Write failing database tests**

```python
from pathlib import Path
from bili_ai_curator.db import CuratorStore
from bili_ai_curator.models import Evaluation, VideoCandidate


def test_video_is_deduplicated_and_quota_persists(tmp_path: Path):
    store = CuratorStore(tmp_path / "state.db")
    video = VideoCandidate(bvid="BV123", title="AI news", author_mid=1, author_name="up", pubdate="2026-10-23T10:00:00+08:00", views=1000, likes=20, comments=5, duration=300, topic="ai_knowledge", raw={})
    store.save_video(video)
    store.save_evaluation(video.bvid, Evaluation(total=0.8, relevant=0.9, interesting=0.8, popularity=0.7, quality=0.85, reason="useful", model="deepseek-flash"))
    store.record_comment(video.bvid, "hello @owner", rpid=10, status="visible")
    assert store.is_seen(video.bvid)
    assert store.daily_state("2026-10-23").comments_sent == 1
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_db.py -q`

Expected: FAIL because the modules do not exist.

- [ ] **Step 3: Implement dataclasses and schema**

Create SQLite tables `videos`, `evaluations`, `comments`, `daily_state`, and `events`. Use `bvid TEXT PRIMARY KEY`, JSON text only for raw evidence, and atomically update `daily_state` in the same transaction as successful comments. The public methods must be:

```python
class CuratorStore:
    def is_seen(self, bvid: str) -> bool: ...
    def save_video(self, video: VideoCandidate) -> None: ...
    def save_evaluation(self, bvid: str, evaluation: Evaluation) -> None: ...
    def record_comment(self, bvid: str, text: str, rpid: int | None, status: str) -> None: ...
    def daily_state(self, day: str) -> DailyState: ...
    def set_daily_state(self, day: str, **changes) -> None: ...
    def record_event(self, kind: str, payload: dict, day: str | None = None) -> None: ...
```

`record_comment()` must use `BEGIN IMMEDIATE`, insert the comment, increment `comments_sent`, and commit together. It must never exceed five.

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/test_db.py -q`

Expected: PASS.

```bash
git add src/bili_ai_curator/models.py src/bili_ai_curator/db.py tests/test_db.py
git commit -m "feat: persist candidates and daily quota"
```

### Task 3: JSON-Only Bilibili CLI Adapter

**Files:**
- Create: `src/bili_ai_curator/bili_cli.py`
- Create: `tests/test_bili_cli.py`

**Interfaces:**
- Consumes: executable name `bili`.
- Produces: `BiliCLIError(code: str, message: str, hint: str | None, retry_after: int | None)`.
- Produces: `BiliCLI.run(args)`, `recommend(page)`, `rank(zone)`, `search(keyword)`, `watch(bvid)`, `post_comment(bvid, text, dry_run)`, `check_comment(bvid, rpid)`, `set_owner(uid)`, `owner()`.

- [ ] **Step 1: Write adapter tests with a fake command runner**

```python
import json
from bili_ai_curator.bili_cli import BiliCLI, BiliCLIError


def test_comment_command_uses_owner_mention_and_dry_run():
    calls = []
    cli = BiliCLI(runner=lambda args: calls.append(args) or {"ok": True, "data": {"dry_run": True}})
    cli.post_comment("BV123", "这个视频不错 @主人", dry_run=True)
    assert calls[0][:4] == ["comment", "post", "BV123", "这个视频不错 @主人"]
    assert "--at" in calls[0] and "owner" in calls[0]
    assert "--dry-run" in calls[0]
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_bili_cli.py -q`

Expected: FAIL because `BiliCLI` does not exist.

- [ ] **Step 3: Implement the subprocess adapter**

Use `subprocess.run(..., capture_output=True, text=True, encoding="utf-8", errors="strict", timeout=180, shell=False)`. Parse exactly one JSON object from stdout. Map nonzero exit or `ok=false` to `BiliCLIError`. Implement these exact command arrays:

```python
["feed", "recommend", "--count", "30", "--page", str(page), "--unseen"]
["hot", "rank", "--zone", zone, "--limit", "50", "--unseen"]
["search", "video", keyword, "--order", "views", "--size", "30"]
["video", "watch", bvid, "--frames", "9", "--comments", "5", "--transcript", "auto", "--max-chars", "6000"]
["comment", "post", bvid, text, "--at", "owner"] + (["--dry-run"] if dry_run else [])
["comment", "check", bvid, str(rpid)]
["owner", "set", str(uid)]
["owner", "show"]
```

All writes except owner setup must support dry-run at the adapter boundary.

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/test_bili_cli.py -q`

Expected: PASS.

```bash
git add src/bili_ai_curator/bili_cli.py tests/test_bili_cli.py
git commit -m "feat: add JSON bilibili CLI adapter"
```

### Task 4: Topic Filtering and Popularity Scoring

**Files:**
- Create: `src/bili_ai_curator/scoring.py`
- Create: `tests/test_scoring.py`

**Interfaces:**
- Consumes: `VideoCandidate`, `TopicConfig`.
- Produces: `matches_topic(video, topic) -> bool`.
- Produces: `score_popularity(age_hours, views, peer_views) -> float`.
- Produces: `final_score(evaluation, popularity, freshness, source_diversity) -> float`.

- [ ] **Step 1: Write failing score tests**

```python
from bili_ai_curator.scoring import percentile_rank, score_popularity


def test_relative_popularity_prefers_early_breakout():
    peers = [100, 200, 300, 400, 500]
    young = score_popularity(age_hours=6, views=450, peer_views=peers)
    old = score_popularity(age_hours=720, views=450, peer_views=peers)
    assert young > old


def test_percentile_rank():
    assert percentile_rank(300, [100, 200, 300, 400, 500]) == 0.6
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_scoring.py -q`

Expected: FAIL because the scoring module does not exist.

- [ ] **Step 3: Implement deterministic scoring**

Normalize keyword matches, excluded words, age window, peer percentile, engagement rates, and source count into `[0, 1]`. `final_score` must use exactly `0.30 relevance + 0.25 interest + 0.20 popularity + 0.10 engagement + 0.10 freshness + 0.05 diversity`.

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/test_scoring.py -q`

Expected: PASS.

```bash
git add src/bili_ai_curator/scoring.py tests/test_scoring.py
git commit -m "feat: add relative popularity scoring"
```

### Task 5: DeepSeek Evaluation and Comment Generation

**Files:**
- Create: `src/bili_ai_curator/deepseek.py`
- Create: `tests/test_deepseek.py`

**Interfaces:**
- Consumes: `DeepSeekConfig`, `VideoCandidate`, video `watch` data.
- Produces: `DeepSeekClient.evaluate(video, watch_data) -> Evaluation`.
- Produces: `DeepSeekClient.comment(video, evaluation, greeting, fifth) -> str`.
- Produces: `DeepSeekClient.insufficient_balance(error_payload) -> bool`.

- [ ] **Step 1: Write response parser and balance tests**

```python
from bili_ai_curator.deepseek import parse_json_content, is_insufficient_balance


def test_json_fence_is_removed():
    assert parse_json_content('```json\n{"score": 0.8}\n```') == {"score": 0.8}


def test_insufficient_balance_detection():
    assert is_insufficient_balance({"error": {"code": "insufficient_balance"}})
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_deepseek.py -q`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement the API client**

Use `requests.Session` with `trust_env=False`. Send JSON to `{api_base}/chat/completions`, disable thinking for `deepseek-flash`, cap evaluation output at 700 tokens and comment output at 180 tokens. Treat HTTP 401/402 and error codes containing `insufficient`, `balance`, or `quota` as balance/auth stop conditions. Prompt input data as untrusted content and require a JSON object with:

```json
{"relevant":0.0,"interesting":0.0,"quality":0.0,"reason":"one concrete sentence","comment":"one or two natural sentences"}
```

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/test_deepseek.py -q`

Expected: PASS.

```bash
git add src/bili_ai_curator/deepseek.py tests/test_deepseek.py
git commit -m "feat: add DeepSeek evaluation"
```

### Task 6: Comment Policy and Stop Conditions

**Files:**
- Create: `src/bili_ai_curator/comments.py`
- Create: `tests/test_comments.py`

**Interfaces:**
- Consumes: generated comment text, owner display name, sequence number, current time.
- Produces: `compose_comment(content, owner_name, sequence, now, finished_day=False) -> str`.
- Produces: `status_comment(kind, owner_name) -> str`.

- [ ] **Step 1: Write failing policy tests**

```python
from datetime import datetime
from zoneinfo import ZoneInfo
from bili_ai_curator.comments import compose_comment, status_comment


def test_first_and_fifth_comments():
    now = datetime(2026, 10, 23, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    first = compose_comment("这个模型测试很详细", "主人", 1, now, False)
    fifth = compose_comment("这个二创很有意思", "主人", 5, now, True)
    assert first.startswith("早上好，新的一天又开始了。")
    assert "@主人" in first
    assert fifth.endswith("今天的大白饭吃完了，等明天有饭吃再给主人推")


def test_status_comments():
    assert "今天的视频都太一般了" in status_comment("low_quality", "主人")
    assert "DeepSeek 余额不足" in status_comment("insufficient_balance", "主人")
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_comments.py -q`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement normalization and policy**

Strip Markdown, remove links, collapse whitespace, cap body length at 120 Chinese characters before suffixing. Ensure exactly one `@owner_name`. Use `早上好`/`下午好`/`晚上好` by Asia/Shanghai hour. The quota sentence is appended only when `sequence == 5 and finished_day=True`.

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/test_comments.py -q`

Expected: PASS.

```bash
git add src/bili_ai_curator/comments.py tests/test_comments.py
git commit -m "feat: enforce comment policy"
```

### Task 7: Curator Service and Safety State Machine

**Files:**
- Create: `src/bili_ai_curator/service.py`
- Create: `tests/test_service.py`

**Interfaces:**
- Consumes: config, store, BiliCLI, DeepSeek client.
- Produces: `CuratorService.run_once(now) -> CycleResult`.
- Produces: `CuratorService.run_forever(stop_event)`.

- [ ] **Step 1: Write failing service tests**

```python
def test_ten_low_quality_videos_stop_day_and_post_status(fake_deps):
    fake_deps.deepseek.scores = [0.1] * 10
    result = fake_deps.service.run_once(fake_deps.now)
    assert result.stop_reason == "low_quality"
    assert fake_deps.bili.comments[-1].kind == "status"
    assert fake_deps.bili.comments[-1].dry_run is True


def test_quota_stops_after_five(fake_deps):
    fake_deps.store.mark_comments_sent("2026-10-23", 5)
    result = fake_deps.service.run_once(fake_deps.now)
    assert result.stop_reason == "quota_complete"
    assert fake_deps.bili.comments == []
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_service.py -q`

Expected: FAIL because the service does not exist.

- [ ] **Step 3: Implement the cycle**

The cycle must:

1. Check login and owner configuration.
2. Return immediately outside active hours or after five successes.
3. Collect candidates from recommendation, ranking, search, and latest UP uploads.
4. Apply topic, age, comment-availability, dedupe, and same-author rules.
5. Call `bili video watch` only for at most the configured daily evaluation budget.
6. Ask DeepSeek for evaluation and content-specific comment text.
7. Apply the 10-low-quality and insufficient-balance stop states.
8. Dry-run comment composition before any live comment.
9. Post only when `config.dry_run` is false and warmup permits it.
10. Verify comment visibility with `bili comment check`; hidden/folded comments stop writes.

Store the exact stop reason: `low_quality`, `insufficient_balance`, `risk_control`, `captcha_required`, `auth_expired`, `quota_complete`, `outside_active_hours`, or `ok`.

- [ ] **Step 4: Add resumable daily state**

`daily_state` must store `day`, `evaluated_count`, `consecutive_low_quality`, `comments_sent`, `status_comment_sent`, `stop_reason`, and `warmup_day`. Reset at Asia/Shanghai midnight. A status comment sets `status_comment_sent=1` and never consumes the five recommendation slots.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/test_service.py -q`

Expected: PASS.

```bash
git add src/bili_ai_curator/service.py tests/test_service.py
git commit -m "feat: orchestrate guarded recommendation cycles"
```

### Task 8: CLI, Windows Launcher and Documentation

**Files:**
- Create: `src/bili_ai_curator/cli.py`
- Create: `start.ps1`
- Create: `README.md`
- Modify: `config.example.json`
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: `load_config`, `CuratorStore`, `BiliCLI`, `CuratorService`.
- Produces: commands `check`, `login`, `owner`, `once`, and `run`.

- [ ] **Step 1: Write failing CLI tests**

```python
def test_dry_run_is_default(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    from bili_ai_curator.config import load_config
    path = tmp_path / "config.json"
    path.write_text('{"owner_uid":1,"deepseek":{"api_base":"https://api.deepseek.com/v1","api_key_env":"DEEPSEEK_API_KEY","model":"deepseek-flash"},"schedule":{"active_start":"09:00","active_end":"23:30","poll_minutes_min":10,"poll_minutes_max":20,"comment_gap_minutes_min":20,"comment_gap_minutes_max":45},"quality":{"threshold":0.72,"absolute_floor":0.62,"low_quality_limit":10,"daily_limit":5},"warmup":{"read_only_hours":48,"daily_caps":[1,3,5]},"topics":{"ai_knowledge":{"keywords":[],"exclude":[],"max_age_days":7},"ai_derivative":{"keywords":[],"exclude":[],"max_age_days":30},"zzz":{"keywords":[],"exclude":[],"max_age_days":14},"hsr":{"keywords":[],"exclude":[],"max_age_days":14},"valorant":{"keywords":[],"exclude":[],"max_age_days":7}}}', encoding="utf-8")
    assert load_config(path).dry_run is True
```

- [ ] **Step 2: Implement CLI and startup**

`check` verifies Python, `bili --version`, `bili auth status`, owner UID, DeepSeek configuration and config schema without writes. `login` invokes `bili auth login`. `owner UID` invokes `bili owner set UID`. `once` runs one dry-run cycle. `run` runs the scheduler and refuses to start when authentication or owner setup is missing.

`start.ps1` must activate the project's venv, load `.env` without printing secrets, and run `python -m bili_ai_curator run`. It must not use `Start-Process` or graphical tools.

- [ ] **Step 3: Document setup**

README must document:

- `python -m venv .venv`
- `pip install -e .[dev]`
- `bili auth login`
- `bili owner set <UID>`
- `$env:DEEPSEEK_API_KEY='...'`
- `python -m bili_ai_curator check`
- `python -m bili_ai_curator once`
- `.\start.ps1`
- Credential locations and the warning that new Bilibili accounts are especially sensitive to risk control.

- [ ] **Step 4: Run the complete test suite and commit**

Run: `python -m pytest -q`

Expected: all tests pass.

```bash
git add src/bili_ai_curator/cli.py start.ps1 README.md config.example.json tests/test_cli.py
git commit -m "feat: add CLI and Windows launcher"
```

### Task 9: End-to-End Dry Run and Repository Publication

**Files:**
- Modify: `README.md`
- Verify: all source and test files

**Interfaces:**
- Consumes: the complete local application.
- Produces: a verified dry-run report and a GitHub repository without secrets.

- [ ] **Step 1: Verify secrets are ignored**

Run: `git status --ignored --short`

Expected: `.env`, `config.json`, `data/`, and credentials are ignored; no API key or Cookie appears in tracked files.

- [ ] **Step 2: Run local quality checks**

Run: `python -m pytest -q`

Run: `python -m compileall -q src`

Run: `python -m bili_ai_curator check`

Expected: tests pass, compilation succeeds, and check reports missing login/owner explicitly if not yet configured.

- [ ] **Step 3: Run a live read-only dry run**

Run: `python -m bili_ai_curator once`

Expected: real Bilibili candidates may be read, but no comment is published. The report must include candidate count, highest score, evaluated count, and `dry_run=true`.

- [ ] **Step 4: Verify no external writes occurred**

Confirm the state database has zero `comments` rows and no `comment.post` command without `--dry-run` was executed.

- [ ] **Step 5: Publish the repository**

Create the GitHub repository only after the local checks pass. Push `main`, verify the remote URL, and confirm the repository does not contain `config.json`, `.env`, cookies, databases, logs, or generated frames.
