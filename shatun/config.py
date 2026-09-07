"""Runtime process config from environment. Product config lives in the database."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PACKAGE_DIR = Path(__file__).resolve().parent
ROOT_DIR = PACKAGE_DIR.parent

DEFAULT_DATABASE_URL = "postgresql+asyncpg://shatun:shatun@127.0.0.1:5432/shatun"
DEFAULT_REDIS_URL = "redis://127.0.0.1:6380/0"
DEFAULT_GROK_ARGS = ["agent", "--always-approve", "--no-leader", "stdio"]
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _path(value: str) -> Path:
    p = Path(value).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    return p.resolve()


@dataclass(slots=True)
class RuntimeConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    work_root: Path = Path("./var/runs")
    log_root: Path = Path("./var/logs")
    database_url: str = DEFAULT_DATABASE_URL
    redis_url: str = DEFAULT_REDIS_URL


def load_runtime() -> RuntimeConfig:
    env = os.environ
    return RuntimeConfig(
        host=(env.get("SHATUN_HOST") or "127.0.0.1").strip() or "127.0.0.1",
        port=int(env.get("SHATUN_PORT") or 8765),
        work_root=_path(env.get("SHATUN_WORK_ROOT") or "./var/runs"),
        log_root=_path(env.get("SHATUN_LOG_ROOT") or "./var/logs"),
        database_url=(env.get("SHATUN_DATABASE_URL") or DEFAULT_DATABASE_URL).strip() or DEFAULT_DATABASE_URL,
        redis_url=(env.get("SHATUN_REDIS_URL") or DEFAULT_REDIS_URL).strip() or DEFAULT_REDIS_URL,
    )


def ensure_dirs(cfg: RuntimeConfig) -> None:
    cfg.work_root.mkdir(parents=True, exist_ok=True)
    cfg.log_root.mkdir(parents=True, exist_ok=True)


def normalize_repo(value: str) -> str:
    raw = (value or "").strip().rstrip("/")
    raw = re.sub(r"^https?://github\.com/", "", raw, flags=re.I)
    raw = re.sub(r"^github\.com/", "", raw, flags=re.I)
    if raw.endswith(".git"):
        raw = raw[:-4]
    if not REPO_RE.fullmatch(raw):
        raise ValueError("repo must be owner/name")
    return raw


def read_legacy_toml(path: Path | None = None) -> dict[str, Any] | None:
    """Optional one-time import from a leftover config.toml."""
    cfg_path = path or Path.cwd() / "config.toml"
    if not cfg_path.is_file():
        return None
    with cfg_path.open("rb") as fh:
        raw = tomllib.load(fh)
    args = raw.get("grok_args") or list(DEFAULT_GROK_ARGS)
    repo = str(raw.get("repo") or "").strip()
    if repo in {"", "OWNER/REPO"}:
        repo = ""
    return {
        "grok_bin": str(raw.get("grok_bin") or "grok").strip() or "grok",
        "grok_args": list(args),
        "xai_api_key": str(raw.get("xai_api_key") or "").strip(),
        "poll_seconds": int(raw.get("poll_seconds") or 60),
        "scheduler_seconds": int(raw.get("scheduler_seconds") or 5),
        "run_timeout_sec": int(raw.get("run_timeout_sec") or 2700),
        "default_agent_name": str(raw.get("default_agent_name") or "Bob").strip() or "Bob",
        "repo": repo,
        "label": str(raw.get("label") or "agent").strip() or "agent",
    }
