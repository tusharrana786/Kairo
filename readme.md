# Durable Workflow Engine

Build and run durable workflows as directed acyclic graphs (DAGs). The engine is written in Python. PostgreSQL stores execution state, Redis is planned for scheduling and worker delivery, and React is planned for the dashboard.

## Phase 1

Submit a workflow over HTTP and retrieve its initial execution graph by UUID. A submission creates one workflow execution, its tasks, and their dependency edges in a single PostgreSQL transaction. The workflow starts as `pending`. Root tasks start as `ready`, and tasks with prerequisites start as `blocked`. Task types identify handlers for the future worker pool.

## Run locally

Use Python 3.11 or newer and Docker Compose. If you already have PostgreSQL, skip the Compose command and set `DATABASE_URL` to your database connection string. Run these PowerShell commands from the repository root.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
docker compose up -d --wait postgres
$env:DATABASE_URL = 'postgresql://workflow:workflow@127.0.0.1:5432/workflow'
.\.venv\Scripts\python.exe -m engine.store
.\.venv\Scripts\python.exe -m uvicorn engine.api:app
```

Compose starts PostgreSQL 16 and stores its data in a named volume. The schema bootstrap runs separately from API startup. The local API exposes [interactive documentation](http://127.0.0.1:8000/docs).

## Submit and inspect a workflow

This example creates a graph that branches after `fetch` and joins at `publish`. Run it in a second PowerShell terminal.

```powershell
$body = @{
    name = 'report'
    tasks = @(
        @{ key = 'fetch'; type = 'load'; input = @{ report_id = 42 } }
        @{ key = 'analyze'; type = 'transform'; depends_on = @('fetch') }
        @{ key = 'format'; type = 'render'; depends_on = @('fetch') }
        @{ key = 'publish'; type = 'save'; depends_on = @('analyze', 'format') }
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

## Verify Phase 1

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Graph tests run without PostgreSQL. To include the persistence and rollback tests, set `TEST_DATABASE_URL` to a dedicated PostgreSQL test database and run the same command. The suite creates its schema in that database. To check restart durability, submit the example, restart Uvicorn, and retrieve the same UUID.

The initial implementation still needs a recorded test run and API smoke test. See the [agent handoff](agent.md) for verification details and the implementation map.

## Roadmap

| Phase | Scope | Acceptance check |
| --- | --- | --- |
| 1 · Weeks 1–2 | DAG validation, execution schemas, atomic submission, and readback | A graph survives an API restart, and a failed write leaves no partial execution. |
| 2 | Redis scheduling, Python workers, and dependency transitions | Independent tasks can run concurrently, and a join becomes runnable after all prerequisites succeed. |
| 3 | Attempt history, retries, timeouts, task idempotency, and dead-letter handling | Transient failures retry, duplicate delivery is safe, and exhausted attempts can be inspected. |
| 4 | Worker leases, crash recovery, and checkpoint-based resume | A replacement worker can resume from durable progress after a crash. |
| 5 | React dashboard for execution lists, graph status, and history | A user can follow a workflow and inspect task attempts and failures. |
