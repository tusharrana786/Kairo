import os
import unittest
from uuid import uuid4

from engine.graph import Task


class DatabaseTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from unittest.mock import patch

        from engine import store

        environment = patch.dict(os.environ, {"DATABASE_URL": os.environ["TEST_DATABASE_URL"]})
        environment.start()
        cls.addClassCleanup(environment.stop)
        cls.store = store
        store.migrate()

    def delete_workflow(self, workflow_id):
        with self.store.connect() as connection:
            connection.execute("DELETE FROM workflow_executions WHERE id = %s", (workflow_id,))


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "Set TEST_DATABASE_URL to a test database")
class StoreTests(DatabaseTestCase):
    def test_persists_graph_and_initial_states(self):
        workflow_id = self.store.submit_workflow(
            "example", [Task("child", "process", ("root",)), Task("root", "load", input=None)]
        )
        self.addCleanup(self.delete_workflow, workflow_id)
        workflow = self.store.get_workflow(workflow_id)
        self.assertEqual(workflow["status"], "pending")
        tasks = {task["key"]: task for task in workflow["tasks"]}
        self.assertEqual(tasks["child"]["depends_on"], ["root"])
        self.assertEqual(tasks["child"]["status"], "blocked")
        self.assertEqual(tasks["root"]["status"], "ready")
        self.assertIsNone(tasks["root"]["input"])

    def test_rolls_back_workflow_when_task_insert_fails(self):
        from psycopg.errors import NotNullViolation

        name = f"rollback-{uuid4()}"
        with self.assertRaises(NotNullViolation):
            self.store.submit_workflow(name, [Task("root", "load"), Task("child", None)])
        with self.store.connect() as connection:
            row = connection.execute(
                "SELECT id FROM workflow_executions WHERE name = %s", (name,)
            ).fetchone()
        self.assertIsNone(row)
