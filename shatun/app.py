"""Litestar app, Socket.IO, and process entrypoint."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

import socketio
import uvicorn
from advanced_alchemy.extensions.litestar import (
    AlembicAsyncConfig,
    AsyncSessionConfig,
    SQLAlchemyAsyncConfig,
    SQLAlchemyPlugin,
)
from litestar import Litestar, delete, get, post
from litestar.datastructures import State
from litestar.exceptions import HTTPException, NotFoundException
from litestar.static_files import create_static_files_router
from msgspec import Struct
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from shatun.config import ROOT_DIR, Config, ensure_dirs, load_config
from shatun.events import EventBus
from shatun.models import Base
from shatun.poller import poller_loop
from shatun.runner import Runner
from shatun.runtime import Runtime
from shatun.scheduler import Scheduler
from shatun.serialize import agent_view, issue_view, message_view, run_view
from shatun.store import Store

log = logging.getLogger("shatun")
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")


class AgentCreate(Struct):
    name: str


def check_tools(cfg: Config) -> None:
    if shutil.which("gh") is None:
        raise SystemExit("gh CLI not found on PATH")
    grok = cfg.grok_bin
    if Path(grok).name == grok and shutil.which(grok) is None:
        raise SystemExit(f"{grok} not found on PATH")
    if Path(grok).name != grok and not Path(grok).is_file():
        raise SystemExit(f"grok binary not found: {grok}")
    for argv, label in ((["gh", "--version"], "gh"), ([cfg.grok_bin, "--version"], "grok")):
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=10)
        except FileNotFoundError:
            raise SystemExit(f"missing required binary: {argv[0]}") from None
        line = (result.stdout or result.stderr or "").strip().splitlines()
        print(f"{label}: {line[0] if line else 'ok'}", flush=True)


def alchemy_config(cfg: Config) -> SQLAlchemyAsyncConfig:
    return SQLAlchemyAsyncConfig(
        connection_string=cfg.database_url,
        metadata=Base.metadata,
        session_config=AsyncSessionConfig(expire_on_commit=False),
        before_send_handler="autocommit",
        create_all=False,
        alembic_config=AlembicAsyncConfig(script_location=str(ROOT_DIR / "migrations")),
    )


def create_app(cfg: Config | None = None) -> Litestar:
    cfg = cfg or load_config()
    ensure_dirs(cfg)
    db_config = alchemy_config(cfg)
    frontend_dist = ROOT_DIR / "frontend" / "dist"

    @asynccontextmanager
    async def lifespan(app: Litestar) -> AsyncIterator[None]:
        engine = create_async_engine(cfg.database_url, pool_pre_ping=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        redis = Redis.from_url(cfg.redis_url, decode_responses=True)
        try:
            await redis.ping()
        except Exception as exc:
            raise SystemExit(f"redis/valkey not reachable at {cfg.redis_url}: {exc}") from exc
        bus = EventBus(redis)
        store = Store(sessions, bus, cfg.log_root)
        runtime = Runtime()
        runner = Runner(cfg, store, runtime)
        scheduler = Scheduler(cfg, store, bus, runner)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await store.recover_stale()
        await store.seed_agent(cfg.default_agent_name)
        stop = asyncio.Event()
        app.state.cfg = cfg
        app.state.store = store
        app.state.runtime = runtime
        app.state.scheduler = scheduler
        app.state.runner = runner
        app.state.bus = bus

        async def forward() -> None:
            pubsub = await bus.subscribe_events()
            try:
                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    try:
                        data = json.loads(message["data"])
                    except (TypeError, json.JSONDecodeError):
                        continue
                    await sio.emit(data.get("type") or "event", data.get("payload") or {})
            finally:
                await pubsub.aclose()

        poller_task = asyncio.create_task(poller_loop(cfg, store, stop), name="poller")
        sched_task = asyncio.create_task(scheduler.loop(stop), name="scheduler")
        forward_task = asyncio.create_task(forward(), name="redis-forward")
        log.info("listening on http://%s:%s", cfg.host, cfg.port)
        try:
            yield
        finally:
            stop.set()
            await bus.publish("shutdown", {}, wake=True)
            for live in list(runtime.live.values()):
                await runner.stop(live.run_id)
            poller_task.cancel()
            sched_task.cancel()
            forward_task.cancel()
            await asyncio.gather(poller_task, sched_task, forward_task, return_exceptions=True)
            await redis.aclose()
            await engine.dispose()

    @get("/api/status")
    async def api_status(store: Store) -> dict:
        agents = await store.list_agents()
        return {
            "repo": cfg.repo,
            "label": cfg.label,
            "agents": [agent_view(a) for a in agents],
            "running": sum(1 for a in agents if a.status == "running"),
        }

    @get("/api/agents")
    async def api_agents(store: Store) -> dict:
        return {"agents": [agent_view(a) for a in await store.list_agents()]}

    @post("/api/agents")
    async def api_add_agent(data: AgentCreate, store: Store) -> dict:
        name = data.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        try:
            agent = await store.add_agent(name)
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return agent_view(agent)

    @delete("/api/agents/{agent_id:uuid}", status_code=200)
    async def api_delete_agent(agent_id: UUID, store: Store) -> dict:
        try:
            await store.delete_agent(agent_id)
        except KeyError as exc:
            raise NotFoundException(detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"ok": True}

    @get("/api/issues")
    async def api_issues(store: Store) -> dict:
        issues = await store.list_issues(cfg.repo)
        views = []
        for issue in issues:
            active = await store.active_run_for_issue(issue.id)
            views.append(issue_view(issue, label=cfg.label, active_run=active))
        return {"issues": views}

    @get("/api/runs")
    async def api_runs(store: Store) -> dict:
        return {"runs": [run_view(r) for r in await store.list_runs()]}

    @get("/api/runs/{run_id:uuid}")
    async def api_run(run_id: UUID, store: Store) -> dict:
        run = await store.get_run(run_id)
        if run is None:
            raise NotFoundException(detail="run not found")
        return run_view(run)

    @get("/api/runs/{run_id:uuid}/messages")
    async def api_messages(run_id: UUID, store: Store) -> dict:
        run = await store.get_run(run_id)
        if run is None:
            raise NotFoundException(detail="run not found")
        return {"messages": [message_view(m) for m in await store.list_messages(run_id)]}

    @post("/api/issues/{number:int}/run")
    async def api_run_issue(number: int, scheduler: Scheduler, store: Store) -> dict:
        try:
            run_id = await scheduler.enqueue_issue(number)
        except KeyError as exc:
            raise NotFoundException(detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        run = await store.get_run(run_id)
        return run_view(run) if run else {"id": str(run_id), "status": "queued"}

    @post("/api/runs/{run_id:uuid}/stop")
    async def api_stop(run_id: UUID, store: Store, runner: Runner) -> dict:
        run = await store.get_run(run_id)
        if run is None:
            raise NotFoundException(detail="run not found")
        if run.status != "running":
            raise HTTPException(status_code=409, detail="run is not running")
        await runner.stop(run_id)
        return {"id": str(run_id), "status": "stopping"}

    @post("/api/runs/{run_id:uuid}/requeue")
    async def api_requeue(run_id: UUID, scheduler: Scheduler, store: Store) -> dict:
        try:
            new_id = await scheduler.requeue(run_id)
        except KeyError as exc:
            raise NotFoundException(detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        run = await store.get_run(new_id)
        return run_view(run) if run else {"id": str(new_id), "status": "queued"}

    handlers: list = [
        api_status,
        api_agents,
        api_add_agent,
        api_delete_agent,
        api_issues,
        api_runs,
        api_run,
        api_messages,
        api_run_issue,
        api_stop,
        api_requeue,
    ]
    if frontend_dist.is_dir():
        handlers.append(
            create_static_files_router(path="/", directories=[frontend_dist], html_mode=True, name="frontend")
        )

    async def provide_store(state: State) -> Store:
        return state.store

    async def provide_scheduler(state: State) -> Scheduler:
        return state.scheduler

    async def provide_runner(state: State) -> Runner:
        return state.runner

    return Litestar(
        route_handlers=handlers,
        lifespan=[lifespan],
        plugins=[SQLAlchemyPlugin(config=db_config)],
        dependencies={"store": provide_store, "scheduler": provide_scheduler, "runner": provide_runner},
        openapi_config=None,
    )


def build_asgi(cfg: Config | None = None):
    app = create_app(cfg)
    return socketio.ASGIApp(sio, app)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    if not cfg.repo or cfg.repo == "OWNER/REPO":
        print('Set repo = "OWNER/REPO" in config.toml before starting.', file=sys.stderr)
    ensure_dirs(cfg)
    check_tools(cfg)
    uvicorn.run(build_asgi(cfg), host=cfg.host, port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()
