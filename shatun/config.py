"""Load config.toml from the process cwd."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
ROOT_DIR = PACKAGE_DIR.parent


def _path(value: str) -> Path:
    p = Path(value).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    return p.resolve()


@dataclass
class Config:
    repo: str
    label: str = "agent"
    poll_seconds: int = 60
    scheduler_seconds: int = 5
    run_timeout_sec: int = 2700
    host: str = "127.0.0.1"
    port: int = 8765
    work_root: Path = Path("./var/runs")
    log_root: Path = Path("./var/logs")
    database_url: str = "postgresql+asyncpg://shatun:shatun@127.0.0.1:5432/shatun"
    redis_url: str = "redis://127.0.0.1:6380/0"
    grok_bin: str = "grok"
    grok_args: list[str] = field(default_factory=lambda: ["agent", "--always-approve", "--no-leader", "stdio"])
    xai_api_key: str = ""
    default_agent_name: str = "Bob"


def load_config(path: str | Path | None = None) -> Config:
    cfg_path = Path(path) if path else Path.cwd() / "config.toml"
    if not cfg_path.is_file():
        raise SystemExit(f"config.toml not found: {cfg_path}")
    with cfg_path.open("rb") as fh:
        raw = tomllib.load(fh)
    return Config(
        repo=str(raw.get("repo") or "").strip(),
        label=str(raw.get("label") or "agent").strip(),
        poll_seconds=int(raw.get("poll_seconds") or 60),
        scheduler_seconds=int(raw.get("scheduler_seconds") or 5),
        run_timeout_sec=int(raw.get("run_timeout_sec") or 2700),
        host=str(raw.get("host") or "127.0.0.1"),
        port=int(raw.get("port") or 8765),
        work_root=_path(str(raw.get("work_root") or "./var/runs")),
        log_root=_path(str(raw.get("log_root") or "./var/logs")),
        database_url=str(raw.get("database_url") or "postgresql+asyncpg://shatun:shatun@127.0.0.1:5432/shatun"),
        redis_url=str(raw.get("redis_url") or "redis://127.0.0.1:6380/0"),
        grok_bin=str(raw.get("grok_bin") or "grok"),
        grok_args=list(raw.get("grok_args") or ["agent", "--always-approve", "--no-leader", "stdio"]),
        xai_api_key=str(raw.get("xai_api_key") or "").strip(),
        default_agent_name=str(raw.get("default_agent_name") or "Bob").strip() or "Bob",
    )


def ensure_dirs(cfg: Config) -> None:
    cfg.work_root.mkdir(parents=True, exist_ok=True)
    cfg.log_root.mkdir(parents=True, exist_ok=True)
