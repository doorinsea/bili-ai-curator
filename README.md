# Bili AI Curator

Local Bilibili AI curator for Windows. It scans five configured topic groups,
uses DeepSeek to rank videos, and can post at most five recommendation comments
per day that mention the configured owner account.

The first default mode is `dry_run=true`: it reads and scores Bilibili content
but never publishes a comment.

## Requirements

- Windows 10/11
- Python 3.11+
- A Bilibili experiment account
- A DeepSeek API key
- The owner's numeric Bilibili UID

## Install

```powershell
cd "C:\Users\lenovo\Desktop\project\wechat and pad-interaction\bili-ai-curator"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .\config.example.json .\config.json
```

Set the DeepSeek key without writing it into the repository:

```powershell
"DEEPSEEK_API_KEY=your-key" | Set-Content -Encoding UTF8 .env
```

Edit `config.json` and set:

- `owner_uid` to the main account's numeric Bilibili UID
- `dry_run` remains `true` for the first read-only run
- the five topic keyword lists and thresholds if needed

## Login and Owner Setup

```powershell
.\.venv\Scripts\bili.exe auth login
.\.venv\Scripts\bili.exe owner set <owner-uid>
.\.venv\Scripts\python.exe -m bili_ai_curator check
```

The Bilibili credential is stored by `bili-cli` in `%APPDATA%\bili-cli`.
This repository never stores that credential.

## Dry Run

```powershell
.\.venv\Scripts\python.exe -m bili_ai_curator once
```

The command reads real Bilibili content but passes `--dry-run` to comments.
No external write is expected, and the local database must show zero
recommendation comments after the test.

## Continuous Run

```powershell
.\start.ps1
```

The service checks login, owner configuration, active hours, warm-up state,
and the daily quota before browsing. It stops on Bilibili risk control,
CAPTCHA, authentication expiry, a folded comment, or insufficient DeepSeek
balance.

## Safety Behavior

- Bilibili only.
- No private messages, likes, coins, favorites, follows, uploads, or profile edits.
- One distinct video per recommendation.
- Maximum five successful recommendation comments per day.
- Twenty to forty-five minutes between recommendation comments.
- First recommendation of the day contains a time-appropriate greeting.
- Fifth recommendation ends with the configured white-rice message.
- Ten consecutive low-quality evaluated candidates trigger one status comment.
- New accounts remain read-only for 48 hours, then progress through 1, 3, and 5 comments per day.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests never contact Bilibili or DeepSeek. Real API access occurs only through
explicit `check`, `once`, or `run` commands.

## Account Safety

Bilibili automation is non-official and can change without notice. New
accounts are especially likely to encounter comment restrictions. Keep the
experiment account bio marked as AI-operated, use a real human browsing
history before enabling comments, and stop immediately if Bilibili asks for a
CAPTCHA or returns a risk-control error.
