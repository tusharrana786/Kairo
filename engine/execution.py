from uuid import UUID

from .store import connect


def claim_task(workflow_id: UUID, task_key: str, task_type: str) -> dict | None:
    with connect() as connection:
        # All transitions in one workflow serialize on this row. Handlers run
        # outside the transaction, so sibling tasks can execute concurrently.
        connection.execute(
            "SELECT id FROM workflow_executions WHERE id = %s FOR UPDATE", (workflow_id,)
        )
        task = connection.execute(
            """UPDATE task_executions SET status = 'running'
               WHERE workflow_id = %s AND task_key = %s AND task_type = %s AND status = 'ready'
               RETURNING input""",
            (workflow_id, task_key, task_type),
        ).fetchone()
        if task is not None:
            connection.execute(
                "UPDATE workflow_executions SET status = 'running' WHERE id = %s AND status = 'pending'",
                (workflow_id,),
            )
        return task


def finish_task(workflow_id: UUID, task_key: str, *, succeeded: bool) -> None:
    with connect() as connection:
        connection.execute(
            "SELECT id FROM workflow_executions WHERE id = %s FOR UPDATE", (workflow_id,)
        )
        result = connection.execute(
            """UPDATE task_executions SET status = %s
               WHERE workflow_id = %s AND task_key = %s AND status = 'running'""",
            ("succeeded" if succeeded else "failed", workflow_id, task_key),
        )
        if not result.rowcount:
            return
        if succeeded:
            connection.execute(
                """UPDATE task_executions AS child SET status = 'ready'
                   FROM task_dependencies AS edge
                   WHERE edge.workflow_id = %s AND edge.depends_on = %s
                     AND (child.workflow_id, child.task_key) = (edge.workflow_id, edge.task_key)
                     AND child.status = 'blocked'
                     AND NOT EXISTS (
                         SELECT 1 FROM task_dependencies AS dependency
                         JOIN task_executions AS parent
                           ON (parent.workflow_id, parent.task_key) =
                              (dependency.workflow_id, dependency.depends_on)
                         WHERE (dependency.workflow_id, dependency.task_key) =
                               (child.workflow_id, child.task_key)
                           AND parent.status <> 'succeeded'
                     )""",
                (workflow_id, task_key),
            )
        connection.execute(
            """UPDATE workflow_executions AS workflow
               SET status = (
                   SELECT CASE WHEN bool_and(task.status = 'succeeded') THEN 'succeeded' ELSE 'failed' END
                   FROM task_executions AS task WHERE task.workflow_id = workflow.id
               )
               WHERE workflow.id = %s AND NOT EXISTS (
                   SELECT 1 FROM task_executions AS task
                   WHERE task.workflow_id = workflow.id AND task.status IN ('ready', 'running')
               )""",
            (workflow_id,),
        )
