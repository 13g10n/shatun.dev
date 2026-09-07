"""Clone the repo and run Grok Build via the official ACP SDK."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from uuid import UUID

from jinja2 import Environment, FileSystemLoader

from shatun.acp import ShatunACPClient, connect_grok, handshake
from shatun.config import PACKAGE_DIR, Config
from shatun.models import AGENT_IDLE, PHASE_CLONING, PHASE_DONE, PHASE_HANDSHAKE, PHASE_PROMPTING
from shatun.runtime import Runtime, kill_proc
from shatun.store import Store, utcnow

log = logging.getLogger("shatun.runner")
PR_LINE = re.compile(r"^PR:\s*(\S+)", re.MULTILINE)
PR_URL = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/pull/\d+")
PROMPT_ENV = Environment(
    loader=FileSystemLoader(str(PACKAGE_DIR / "prompts")),
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_prompt(issue, cfg: Config, cwd: Path, extra_context: str | None = None) -> str:
    return PROMPT_ENV.get_template("issue.md.j2").render(
        repo=cfg.repo,
        number=issue.number,
        title=issue.title,
        body=issue.body or "",
        html_url=issue.html_url or "",
        branch=f"agent/issue-{issue.number}",
        cwd=str(cwd),
        extra_context=extra_context or "",
    )


class Runner:
    def __init__(self, cfg: Config, store: Store, runtime: Runtime) -> None:
        self.cfg = cfg
        self.store = store
        self.runtime = runtime

    async def execute(self, run_id: UUID, agent_id: UUID) -> None:
        live = self.runtime.claim(agent_id, run_id)
        run = await self.store.get_run(run_id)
        if run is None or run.issue is None:
            await self.store.update_run(run_id, status="failed", last_error="run or issue missing", phase=PHASE_DONE)
            await self.store.set_agent_status(agent_id, AGENT_IDLE, None)
            self.runtime.clear(agent_id)
            return
        issue = run.issue
        log_path = self.cfg.log_root / f"{run_id}.jsonl"
        cwd = self.cfg.work_root / str(run_id) / "repo"
        finished = False

        async def note(**event):
            await self.store.add_message(run_id, event)

        async def finish(status: str, exit_code: int | None = None, error: str | None = None) -> None:
            nonlocal finished
            if finished:
                return
            finished = True
            pr_url = self.store.parse_pr_url(run_id)
            await self.store.update_run(
                run_id,
                status=status,
                phase=PHASE_DONE,
                finished_at=utcnow(),
                exit_code=exit_code,
                last_error=error,
                pr_url=pr_url,
            )

        try:
            await self.store.update_run(
                run_id, cwd=str(cwd), log_path=str(log_path), started_at=utcnow(),
                status="running", phase=PHASE_CLONING, agent_id=agent_id,
            )
            await note(kind="status", title="cloning", text=f"cloning {self.cfg.repo}")
            cwd.parent.mkdir(parents=True, exist_ok=True)
            clone = await asyncio.create_subprocess_exec(
                "gh", "repo", "clone", self.cfg.repo, str(cwd), "--", "--depth", "1",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            out, err = await clone.communicate()
            if clone.returncode != 0:
                raise RuntimeError((err or out).decode("utf-8", "replace").strip() or "clone failed")
            if live.stop.is_set():
                await finish("stopped")
                return
            prompt = render_prompt(issue, self.cfg, cwd)
            await self.store.update_run(run_id, prompt=prompt)
            env = os.environ.copy()
            if self.cfg.xai_api_key:
                env["XAI_API_KEY"] = self.cfg.xai_api_key
            await self.store.update_run(run_id, phase=PHASE_HANDSHAKE)
            proc = await asyncio.create_subprocess_exec(
                self.cfg.grok_bin,
                *self.cfg.grok_args,
                cwd=str(cwd),
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            self.runtime.attach(agent_id, run_id, proc)
            live = self.runtime.get(agent_id) or live
            await self.store.update_run(run_id, pid=proc.pid)
            await note(kind="status", title="spawned", text=f"pid={proc.pid}")

            async def drain_stderr() -> None:
                if proc.stderr is None:
                    return
                while True:
                    line = await proc.stderr.readline()
                    if not line:
                        return
                    await note(kind="stderr", text=line.decode("utf-8", "replace").rstrip())

            stderr_task = asyncio.create_task(drain_stderr())
            client = ShatunACPClient(on_event=lambda event: self.store.add_message(run_id, event))
            conn = await connect_grok(client, proc)
            await note(kind="status", title="handshake", text="acp initialize")
            session_id = await handshake(conn, cwd=str(cwd), api_key=self.cfg.xai_api_key)
            await note(kind="status", title="session", text=session_id)
            if live.stop.is_set():
                await finish("stopped")
                return
            await self.store.update_run(run_id, phase=PHASE_PROMPTING)
            from acp import text_block

            result = await asyncio.wait_for(
                conn.prompt(session_id=session_id, prompt=[text_block(prompt)]),
                timeout=self.cfg.run_timeout_sec,
            )
            await note(kind="status", title="acp done", text=str(getattr(result, "stop_reason", result)))
            code = await kill_proc(proc, grace=5)
            stderr_task.cancel()
            if live.stop.is_set():
                await finish("stopped", exit_code=code)
            else:
                await finish("succeeded", exit_code=code)
        except TimeoutError:
            await note(kind="status", title="timeout", text="run_timeout_sec exceeded")
            code = await kill_proc(live.proc)
            await finish("failed", exit_code=code, error="timeout")
        except Exception as exc:
            log.exception("run %s failed", run_id)
            await note(kind="status", title="error", text=str(exc))
            code = await kill_proc(live.proc)
            await finish("stopped" if live.stop.is_set() else "failed", exit_code=code, error=str(exc))
        finally:
            await self.store.set_agent_status(agent_id, AGENT_IDLE, None)
            self.runtime.clear(agent_id)
            await self.store.bus.publish("scheduler.wake", {}, wake=True)

    async def stop(self, run_id: UUID) -> bool:
        live = self.runtime.find_run(run_id)
        if live is None:
            return False
        live.stop.set()
        await kill_proc(live.proc, grace=8)
        return True
