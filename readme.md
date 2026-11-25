# Kairo

Build and run durable workflows as directed acyclic graphs (DAGs). The engine is written in Python. PostgreSQL stores execution state, Redis delivers runnable tasks to workers, and React is planned for the dashboard.

## Phase 1

Submit a workflow over HTTP and retrieve its execution graph by UUID. A submission creates one workflow execution, its tasks, and their dependency edges in a single PostgreSQL transaction. The workflow starts as `pending`. Root tasks start as `ready`, and tasks with prerequisites start as `blocked`.

## Phase 2

The scheduler publishes ready tasks to Redis queues by task type, including ready tasks from Phase 1. Workers register their supported types in Redis with expiring presence records and claim matching tasks atomically in PostgreSQL. Each worker runs one task at a time, so multiple workers can run independent tasks concurrently. A child becomes ready after every parent succeeds.

When a handler raises an exception, the task fails and its descendants stay blocked. Independent branches can finish, and the workflow becomes `failed` once no tasks are ready or running. A workflow becomes `succeeded` when all tasks succeed.

The scheduler republishes still-ready tasks after five seconds, which recovers deliveries lost before a claim. Duplicate deliveries cannot claim a task twice. If a worker exits after claiming a task, it can remain `running` until worker recovery is implemented in Phase 4.

## Run locally

Use Python 3.11 or newer and Docker Compose. You can also use existing PostgreSQL and Redis services by setting `DATABASE_URL` and `REDIS_URL`. Run these PowerShell commands from the repository root.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
docker compose up -d --wait postgres redis
$env:DATABASE_URL = 'postgresql://workflow:workflow@127.0.0.1:5432/workflow'
.\.venv\Scripts\python.exe -m engine.store
.\.venv\Scripts\python.exe -m uvicorn engine.api:app
```

Compose starts PostgreSQL 16 and stores its data in a named volume. The schema bootstrap runs separately from API startup. The local API exposes [interactive documentation](http://127.0.0.1:8000/docs).

Start the scheduler in another terminal and a worker in each of two more terminals. Set `DATABASE_URL` as above in each terminal. The scheduler and workers default to `REDIS_URL=redis://127.0.0.1:6379/0`.

```powershell
# Scheduler terminal
.\.venv\Scripts\python.exe -m engine.scheduler

# Run in each worker terminal
.\.venv\Scripts\python.exe -m engine.worker
```

The default worker handles `noop`. To run application tasks, pass `--handlers your_module`. The module must export a `HANDLERS` dictionary mapping task types to synchronous callables that accept the task's JSON input. A normal return marks the task successful.

## Submit and inspect a workflow

This example creates a graph that branches after `fetch` and joins at `publish`. Run it in a second PowerShell terminal.

```powershell
$body = @{
    name = 'report'
    tasks = @(
        @{ key = 'fetch'; type = 'noop'; input = @{ report_id = 42 } }
        @{ key = 'analyze'; type = 'noop'; depends_on = @('fetch') }
        @{ key = 'format'; type = 'noop'; depends_on = @('fetch') }
        @{ key = 'publish'; type = 'noop'; depends_on = @('analyze', 'format') }
    )
} | ConvertTo-Json -Depth 8

$api = 'http://127.0.0.1:8000'
$run = Invoke-RestMethod "$api/workflows" -Method Post -ContentType 'application/json' -Body $body
Invoke-RestMethod "$api/workflows/$($run.id)" | ConvertTo-Json -Depth 8
```

| Endpoint | Result |
| --- | --- |
| `POST /workflows` | Returns HTTP 201 with the execution UUID and `pending` status. Invalid payloads or DAGs return HTTP 422. |
| `GET /workflows/{workflow_id}` | Returns the workflow, creation timestamp, tasks, inputs, and dependency keys. An unknown UUID returns HTTP 404. |

Task keys are unique within a workflow. Tasks can appear in any order in the submission. Duplicate edges, missing prerequisites, self-dependencies, and cycles are rejected. Omitted `depends_on` and `input` default to an empty list and object, respectively. Each successful submission creates a new execution UUID.

## Run tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Graph tests run without services. Set `TEST_DATABASE_URL` to a dedicated PostgreSQL test database to include the persistence and task transition tests. Also set `TEST_REDIS_URL` to a dedicated Redis test database to verify worker registration, concurrent execution, join eligibility, and duplicate delivery. The suite creates its schema in the test database.

## Roadmap

| Phase | Scope | Acceptance check |
| --- | --- | --- |
| 1 · Weeks 1–2 | DAG validation, execution schemas, atomic submission, and readback | A graph survives an API restart, and a failed write leaves no partial execution. |
| 2 | Redis scheduling, Python workers, and dependency transitions | Independent tasks can run concurrently, and a join becomes runnable after all prerequisites succeed. |
| 3 | Attempt history, retries, timeouts, task idempotency, and dead-letter handling | Transient failures retry, duplicate delivery is safe, and exhausted attempts can be inspected. |
| 4 | Worker leases, crash recovery, and checkpoint-based resume | A replacement worker can resume from durable progress after a crash. |
| 5 | React dashboard for execution lists, graph status, and history | A user can follow a workflow and inspect task attempts and failures. |
