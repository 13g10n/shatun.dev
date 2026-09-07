"""Poll GitHub issues via `gh`. Publishes events; does not start work."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess

from shatun.config import Config
from shatun.store import Store

log = logging.getLogger("shatun.poller")


def fetch_issues(cfg: Config) -> list[dict]:
    cmd = [
        "gh",
        "issue",
        "list",
        "--repo",
        cfg.repo,
        "--label",
        cfg.label,
        "--state",
        "open",
        "--limit",
        "100",
        "--json",
        "number,title,body,url,labels,updatedAt,state",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "gh issue list failed").strip())
    data = json.loads(proc.stdout or "[]")
    if not isinstance(data, list):
        raise RuntimeError("unexpected gh issue list payload")
    return data


async def poll_once(cfg: Config, store: Store) -> int:
    issues = await asyncio.to_thread(fetch_issues, cfg)
    seen: list[int] = []
    for item in issues:
        seen.append(int(item["number"]))
        await store.upsert_issue(cfg.repo, item)
    await store.mark_missing_closed(cfg.repo, seen)
    log.info("polled %s issues from %s", len(seen), cfg.repo)
    await store.bus.publish("issues.polled", {"count": len(seen)}, wake=True)
    return len(seen)


async def poller_loop(cfg: Config, store: Store, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await poll_once(cfg, store)
        except Exception:
            log.exception("poll failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=cfg.poll_seconds)
        except TimeoutError:
            continue
