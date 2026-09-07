# shatun

Local orchestrator for Grok Build: poll labeled GitHub issues, queue tasks, run named agents over ACP, and stream a full chat/tool history to a Vue UI.

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

Copy `config.example.toml` to `config.toml` and set `repo` / `label`. Postgres is `127.0.0.1:5432`, Valkey is `127.0.0.1:6380`.

## Run

```bash
uv run shatun
```

Open http://127.0.0.1:8765

Default agent is **Bob**. Add more from the Agents panel. Each agent runs at most one Grok process. Tasks are `queued → running → succeeded | failed | stopped`.

Chat history (thoughts, tool calls, results, plans, stderr) is stored in Postgres `messages` and mirrored to `var/logs/<run_id>.jsonl`.
