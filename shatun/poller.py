"""Poll GitHub issues via `gh`. Publishes events; does not start work."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess

from shatun.models import Project
from shatun.store import Store

log = logging.getLogger("shatun.poller")


def fetch_issues(repo: str, label: str) -> list[dict]:
    cmd = [
        "gh",
        "issue",
        "list",
        "--repo",
        repo,
        "--label",
        label,
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


async def poll_project(project: Project, store: Store) -> int:
    issues = await asyncio.to_thread(fetch_issues, project.repo, project.label)
    seen: list[int] = []
    for item in issues:
        seen.append(int(item["number"]))
        await store.upsert_issue(project, item)
    await store.mark_missing_closed(project, seen)
    log.info("polled %s issues from %s", len(seen), project.repo)
    await store.bus.publish(
        "issues.polled",
        {"count": len(seen), "project_id": str(project.id), "repo": project.repo},
        wake=True,
    )
    return len(seen)


async def poll_once(store: Store, project_id=None) -> int:
    total = 0
    if project_id is not None:
        project = await store.get_project(project_id)
        projects = [project] if project else []
    else:
        projects = await store.list_projects()
    for project in projects:
        try:
            total += await poll_project(project, store)
        except Exception:
            log.exception("poll failed for %s", project.repo)
    return total


async def poller_loop(store: Store, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await poll_once(store)
        except Exception:
            log.exception("poll failed")
        try:
            settings = await store.get_settings()
            timeout = max(5, int(settings.poll_seconds or 60))
        except Exception:
            timeout = 60
        try:
            await asyncio.wait_for(stop.wait(), timeout=timeout)
        except TimeoutError:
            continue
