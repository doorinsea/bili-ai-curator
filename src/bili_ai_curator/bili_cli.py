from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    stderr: str
    returncode: int


class BiliCLIError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        hint: str | None = None,
        retry_after: int | None = None,
        detail: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.retry_after = retry_after
        self.detail = detail or {}


def resolve_default_executable(python_executable: str | None = None) -> str:
    python_path = Path(python_executable or sys.executable)
    sibling = python_path.with_name("bili.exe" if sys.platform == "win32" else "bili")
    if sibling.is_file():
        return str(sibling)
    return shutil.which("bili") or "bili"


class BiliCLI:
    def __init__(
        self,
        executable: str | None = None,
        runner: Callable[[list[str]], CommandResult] | None = None,
        timeout: int = 180,
    ) -> None:
        self.executable = executable or resolve_default_executable()
        self.timeout = timeout
        self._runner = runner or self._subprocess_runner

    def _subprocess_runner(self, args: list[str]) -> CommandResult:
        try:
            completed = subprocess.run(
                [self.executable, *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
                timeout=self.timeout,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise BiliCLIError(
                "command_timeout",
                "bili command timed out after "
                f"{self.timeout} seconds: {' '.join(args[:3])}",
            ) from exc
        return CommandResult(
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
        )

    def run(self, args: list[str]) -> dict:
        result = self._runner(args)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            message = result.stderr.strip() or result.stdout.strip() or "empty output"
            raise BiliCLIError(
                "internal_error",
                f"bili returned invalid JSON: {message[:500]}",
            ) from exc

        if not isinstance(payload, dict):
            raise BiliCLIError("internal_error", "bili JSON output is not an object")
        if payload.get("ok") is True:
            return payload.get("data")
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        detail = error.get("detail") if isinstance(error.get("detail"), dict) else {}
        retry_after = detail.get("retry_after")
        if retry_after is None:
            retry_after = error.get("retry_after")
        raise BiliCLIError(
            str(error.get("code") or "api_error"),
            str(error.get("message") or result.stderr.strip() or "bili command failed"),
            hint=str(error["hint"]) if error.get("hint") else None,
            retry_after=int(retry_after) if retry_after is not None else None,
            detail=detail,
        )

    def recommend(self, page: int = 1) -> dict:
        return self.run(
            [
                "feed",
                "recommend",
                "--count",
                "30",
                "--page",
                str(page),
                "--unseen",
            ]
        )

    def rank(self, zone: str) -> dict:
        return self.run(
            ["hot", "rank", "--zone", zone, "--limit", "50", "--unseen"]
        )

    def search(self, keyword: str) -> dict:
        return self.run(
            ["search", "video", keyword, "--order", "views", "--size", "30"]
        )

    def watch(self, bvid: str) -> dict:
        return self.run(
            [
                "video",
                "watch",
                bvid,
                "--frames",
                "9",
                "--comments",
                "5",
                "--transcript",
                "auto",
                "--max-chars",
                "6000",
            ]
        )

    def post_comment(self, bvid: str, text: str, *, dry_run: bool) -> dict:
        if not bvid.strip() or not text.strip():
            raise ValueError("bvid and comment text must not be empty")
        args = ["comment", "post", bvid, text, "--at", "owner"]
        if dry_run:
            args.append("--dry-run")
        return self.run(args)

    def check_comment(self, bvid: str, rpid: int) -> dict:
        return self.run(["comment", "check", bvid, str(rpid)])

    def owner(self) -> dict:
        return self.run(["owner", "show"])

    def set_owner(self, uid: int) -> dict:
        return self.run(["owner", "set", str(uid)])

    def auth_status(self) -> dict:
        return self.run(["auth", "status"])
