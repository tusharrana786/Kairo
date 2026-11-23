# Durable Workflow Engine agent handoff

## Project state

The user chose Python for the engine and React for the frontend and dashboard. Phase 1 covers DAG modeling, validation, PostgreSQL persistence, and HTTP submission and readback. Redis scheduling, workers, automatic state transitions, attempt history, recovery, and the React app are future phases.

The repository contains the Phase 1 implementation and tests. The original development environment had no accessible Python interpreter or PostgreSQL service, so runtime verification is pending. See [the README](readme.md) for setup and an API smoke test.

## Where to work

| Path | Responsibility |
| --- | --- |
| [engine/api.py](engine/api.py) | FastAPI app at `engine.api:app`, Pydantic request and response models, and HTTP error mapping. |
| [engine/graph.py](engine/graph.py) | Immutable task records, initial task status, and iterative topological validation. This module uses only the Python standard library. |
| [engine/store.py](engine/store.py) | Psycopg connection using `DATABASE_URL`, schema bootstrap, atomic inserts, and execution readback. |
| [engine/schema.sql](engine/schema.sql) | Initial PostgreSQL tables, constraints, and dependent-task index. |
| [compose.yaml](compose.yaml) | Local PostgreSQL 16 service, readiness check, loopback port, and persistent volume. |
| [tests/test_graph.py](tests/test_graph.py) | Branch and join validation, input order independence, initial states, and invalid graph cases. |
| [tests/test_store.py](tests/test_store.py) | PostgreSQL tests for graph readback and rollback after a task insert failure. |

## Contracts and invariants

- `POST /workflows` accepts a `name` and a nonempty `tasks` list. Each task has `key`, `type`, optional `depends_on`, and optional JSON `input`. The API validates the request shape, then the store validates the graph before opening a connection. Invalid requests return HTTP 422.
- The workflow execution UUID is generated per submission. The task identity is `(workflow_id, task_key)`. A dependency row means `task_key` depends on `depends_on`. Both foreign keys include `workflow_id`, so every link stays inside one execution.
- Submission writes the workflow, tasks, and edges on one connection. The connection context commits on success and rolls back on error. The API returns HTTP 201 after that transaction exits.
- `GET /workflows/{workflow_id}` returns a graph snapshot in a single query. Task keys and dependency keys are sorted for readback. A valid UUID with no matching execution returns HTTP 404.
- Submission currently writes workflow status `pending` and task status `ready` or `blocked`. The schema and response models also allow later states such as `running`, `succeeded`, and `failed`. Introducing transitions requires updating the store and any affected schema and API types together.
- PostgreSQL is the durable record of execution state. The initial SQL is a repeatable bootstrap for a fresh database. Future changes to existing tables need an explicit migration because `CREATE TABLE IF NOT EXISTS` leaves existing table definitions in place.

## Verification to pick up

1. Install the dependencies from `requirements.txt` and run `python -m unittest discover -s tests -v` from the repository root.
2. Set `TEST_DATABASE_URL` to a dedicated PostgreSQL test database and rerun. The persistence tests skip when that variable is absent, even if `DATABASE_URL` is set.
3. Bootstrap the API database with `python -m engine.store`, start the API, and submit the example in the README. Confirm that `fetch` is ready and the other tasks are blocked. Restart Uvicorn and retrieve the same UUID.

## Next development milestone

Phase 2 should build on the stored graph. Define atomic task claiming and completion in PostgreSQL, then add durable dispatch to Redis and a Python handler registry. Keep delivery recoverable across a database commit or Redis publish failure. Verify that two independent tasks run concurrently, a join becomes ready only once after all parents succeed, and repeated delivery cannot claim an already-completed task. Existing Phase 1 executions can already contain ready tasks, so include them when defining scheduler startup behavior.

Later phases add attempt records, retries and timeouts, task idempotency and dead-letter handling, worker leases and checkpoints, and finally the React dashboard. Add list and history APIs when the dashboard needs them. Update this handoff as execution contracts and verification results change.
