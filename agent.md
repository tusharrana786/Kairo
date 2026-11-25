# Durable Workflow Engine agent handoff

## Project state

The user chose Python for the engine and React for the frontend and dashboard. Phase 1 covers DAG modeling, validation, PostgreSQL persistence, and HTTP submission and readback. Phase 2 adds dependency transitions, Redis dispatch, worker registration, and parallel task execution. See [the README](readme.md) for setup and verification commands.

## Where to work

| Path | Responsibility |
| --- | --- |
| [engine/api.py](engine/api.py) | FastAPI app at `engine.api:app`, Pydantic request and response models, and HTTP error mapping. |
| [engine/graph.py](engine/graph.py) | Immutable task records, initial task status, and iterative topological validation. This module uses only the Python standard library. |
| [engine/store.py](engine/store.py) | Psycopg connection using `DATABASE_URL`, schema bootstrap, atomic inserts, and execution readback. |
| [engine/schema.sql](engine/schema.sql) | PostgreSQL schema and repeatable dispatch migration. |
| [engine/execution.py](engine/execution.py) | Atomic claims, task completion, dependency transitions, and workflow status updates. |
| [engine/scheduler.py](engine/scheduler.py) | Batches and republishes ready tasks in Redis. |
| [engine/worker.py](engine/worker.py) | Redis registration and delivery, handler loading, and task execution. |
| [compose.yaml](compose.yaml) | Local PostgreSQL and Redis services. |
| [tests/test_graph.py](tests/test_graph.py) | Branch and join validation, input order independence, initial states, and invalid graph cases. |
| [tests/test_store.py](tests/test_store.py) | PostgreSQL tests for graph readback and rollback after a task insert failure. |
| [tests/test_execution.py](tests/test_execution.py) | Dependency, failure, parallel worker, registration, and duplicate and lost delivery integration coverage. |

## Contracts and invariants

- `POST /workflows` accepts a `name` and a nonempty `tasks` list. Each task has `key`, `type`, optional `depends_on`, and optional JSON `input`. The API validates the request shape, then the store validates the graph before opening a connection. Invalid requests return HTTP 422.
- The workflow execution UUID is generated per submission. The task identity is `(workflow_id, task_key)`. A dependency row means `task_key` depends on `depends_on`. Both foreign keys include `workflow_id`, so every link stays inside one execution.
- Submission writes the workflow, tasks, and edges on one connection. The connection context commits on success and rolls back on error. The API returns HTTP 201 after that transaction exits.
- `GET /workflows/{workflow_id}` returns a graph snapshot in a single query. Task keys and dependency keys are sorted for readback. A valid UUID with no matching execution returns HTTP 404.
- Claim and completion transactions lock the workflow row before writing task state. This prevents concurrent parent completions from missing a join. Handlers execute outside those transactions.
- PostgreSQL is the durable record of execution state. A delivery can be published more than once. The scheduler revisits ready rows after the dispatch interval, and only a conditional PostgreSQL claim changes a ready task to running.
- A failed task leaves its descendants blocked. Other branches can run until the workflow reaches its terminal state.

## Verification to pick up

1. Install the dependencies from `requirements.txt` and run `python -m unittest discover -s tests -v` from the repository root.
2. Set `TEST_DATABASE_URL` and `TEST_REDIS_URL` to dedicated test services and rerun. The integration tests skip without their required variables.
3. Bootstrap the API database with `python -m engine.store`, start the API, scheduler, and two workers, then submit the example in the README. Poll the execution until it reaches `succeeded`.

## Next development milestone

Phase 3 adds attempt records, retries and timeouts, task idempotency, and dead-letter handling. Phase 4 adds worker leases and checkpoints. A worker process that exits after claiming a task can currently leave it running. Add list and history APIs when the React dashboard needs them.
