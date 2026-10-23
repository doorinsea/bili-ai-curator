from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .bili_cli import BiliCLI, BiliCLIError
from .config import load_config
from .db import CuratorStore
from .deepseek import DeepSeekClient
from .service import CuratorService


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config.json"
DEFAULT_DB = ROOT / "data" / "state.db"


def load_dotenv_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bili-curator")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check", help="check login, owner and configuration")
    subparsers.add_parser("login", help="show the Bilibili login QR code")
    owner = subparsers.add_parser("owner", help="set the owner UID")
    owner.add_argument("uid", type=int)
    subparsers.add_parser("once", help="run one cycle")
    subparsers.add_parser("run", help="run continuously")
    return parser


def _runtime(config_path: Path) -> tuple[CuratorService, CuratorStore]:
    config = load_config(config_path)
    store = CuratorStore(DEFAULT_DB)
    bili = BiliCLI()
    deepseek = DeepSeekClient(config.deepseek)
    return CuratorService(config, store, bili, deepseek), store


def _check(config_path: Path) -> dict:
    config = load_config(config_path)
    bili = BiliCLI()
    auth = bili.auth_status()
    owner = bili.owner()
    return {
        "config": str(config_path.resolve()),
        "owner_uid": config.owner_uid,
        "model": config.deepseek.model,
        "dry_run": config.dry_run,
        "auth": auth,
        "owner": owner,
    }


def main() -> None:
    load_dotenv_file(ROOT / ".env")
    args = make_parser().parse_args()
    try:
        if args.command == "login":
            print(json.dumps(BiliCLI().run(["auth", "login"]), ensure_ascii=False))
            return
        if args.command == "owner":
            print(json.dumps(BiliCLI().set_owner(args.uid), ensure_ascii=False))
            return
        if args.command == "check":
            print(json.dumps(_check(args.config), ensure_ascii=False, indent=2))
            return

        service, store = _runtime(args.config)
        try:
            if args.command == "once":
                result = service.run_once()
                print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
                return
            service.run_forever()
        finally:
            store.close()
    except (BiliCLIError, ValueError, RuntimeError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "type": type(exc).__name__,
                        "code": getattr(exc, "code", "startup_error"),
                        "message": str(exc),
                    },
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
