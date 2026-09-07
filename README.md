# shatun

Local orchestrator for Grok Build: projects on GitHub repos, named agents, queued tasks, ACP runs, and a live Vue UI.

## Stack

- Python 3.14, Litestar, SQLAlchemy 2 via Advanced Alchemy
- Postgres + Alembic
- Valkey (Redis protocol) pub/sub
- Socket.IO live updates
- Vue 3 + Tailwind
- Official [`agent-client-protocol`](https://pypi.org/project/agent-client-protocol/) SDK
- Grok Build owns tools (no client-side terminal/fs). Auto-approve via `grok agent --always-approve` and session `autoMode`

Do not run two orchestrators against the same database.

## Install

```bash
docker compose up -d
uv sync
npm --prefix frontend install
npm --prefix frontend run build
uv run alembic upgrade head
gh auth status
grok --version
```

Postgres is `127.0.0.1:5432`, Valkey is `127.0.0.1:6380`. Product configuration (Grok, poll interval, API key, projects) lives in the database. There is no config file.

Process bind/paths can be overridden with environment variables:

| Variable | Default |
| --- | --- |
| `SHATUN_HOST` | `127.0.0.1` |
| `SHATUN_PORT` | `8765` |
| `SHATUN_DATABASE_URL` | `postgresql+asyncpg://shatun:shatun@127.0.0.1:5432/shatun` |
| `SHATUN_REDIS_URL` | `redis://127.0.0.1:6380/0` |
| `SHATUN_WORK_ROOT` | `./var/runs` |
| `SHATUN_LOG_ROOT` | `./var/logs` |

## Run

```bash
uv run shatun
```

Open http://127.0.0.1:8765

Create a project (title + `owner/repo`). Each project gets a default agent (**Bob**) and polls issues with the project label (`agent` by default). Agents run at most one Grok process. Tasks are `queued → running → succeeded | failed | stopped`.

Chat history (thoughts, tool calls, results, plans, stderr) is stored in Postgres `messages` and mirrored to `var/logs/<run_id>.jsonl`.
