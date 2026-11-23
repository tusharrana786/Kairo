import os
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .graph import Task, validate_graph


def connect():
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


def migrate() -> None:
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    with connect() as connection:
        connection.execute(schema)


def submit_workflow(name: str, tasks: list[Task]) -> UUID:
    validate_graph(tasks)
    workflow_id = uuid4()
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO workflow_executions (id, name, status) VALUES (%s, %s, 'pending')",
            (workflow_id, name),
        )
        cursor.executemany(
            """INSERT INTO task_executions (workflow_id, task_key, task_type, input, status)
               VALUES (%s, %s, %s, %s, %s)""",
            [(workflow_id, task.key, task.type, Jsonb(task.input), task.initial_status)
             for task in tasks],
        )
        cursor.executemany(
            """INSERT INTO task_dependencies (workflow_id, task_key, depends_on)
               VALUES (%s, %s, %s)""",
            [(workflow_id, task.key, parent) for task in tasks for parent in task.depends_on],
        )
    return workflow_id


def get_workflow(workflow_id: UUID) -> dict | None:
    with connect() as connection:
        return connection.execute(
            """SELECT w.*, COALESCE((
                   SELECT jsonb_agg(jsonb_build_object(
                       'key', t.task_key, 'type', t.task_type, 'status', t.status,
                       'input', t.input, 'depends_on', ARRAY(
                           SELECT d.depends_on FROM task_dependencies d
                           WHERE d.workflow_id = t.workflow_id AND d.task_key = t.task_key
                           ORDER BY d.depends_on
                       )
                   ) ORDER BY t.task_key)
                   FROM task_executions t WHERE t.workflow_id = w.id
               ), '[]'::jsonb) AS tasks
               FROM workflow_executions w WHERE w.id = %s""",
            (workflow_id,),
        ).fetchone()


if __name__ == "__main__":
    migrate()
