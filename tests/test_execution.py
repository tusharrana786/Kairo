import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from time import monotonic, sleep
from uuid import uuid4

from engine.graph import Task
from test_store import DatabaseTestCase


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "Set TEST_DATABASE_URL to a test database")
class ExecutionTests(DatabaseTestCase):
    def submit(self, tasks):
        workflow_id = self.store.submit_workflow("execution test", tasks)
        self.addCleanup(self.delete_workflow, workflow_id)
        return workflow_id

    def states(self, workflow_id):
        workflow = self.store.get_workflow(workflow_id)
        return workflow["status"], {task["key"]: task["status"] for task in workflow["tasks"]}

    def test_failure_keeps_descendants_blocked_and_independent_tasks_can_finish(self):
        from engine.execution import claim_task, finish_task

        workflow_id = self.submit([
            Task("parent", "work"), Task("child", "work", ("parent",)), Task("sibling", "work")
        ])
        self.assertIsNone(claim_task(workflow_id, "child", "work"))
        self.assertIsNotNone(claim_task(workflow_id, "parent", "work"))
        finish_task(workflow_id, "parent", succeeded=False)
        self.assertEqual(self.states(workflow_id)[0], "running")
        self.assertIsNotNone(claim_task(workflow_id, "sibling", "work"))
        finish_task(workflow_id, "sibling", succeeded=True)
        self.assertEqual(self.states(workflow_id), (
            "failed", {"parent": "failed", "child": "blocked", "sibling": "succeeded"}
        ))

    @unittest.skipUnless(os.getenv("TEST_REDIS_URL"), "Set TEST_REDIS_URL to a test Redis database")
    def test_parallel_workers_join_and_duplicate_delivery(self):
        from redis import Redis

        from engine.dispatch import queue_key
        from engine.scheduler import dispatch_ready
        from engine.worker import run_worker

        task_type = str(uuid4())
        queue = queue_key(task_type)
        workflow_id = self.submit([
            Task("a", task_type, input="a"), Task("b", task_type, input="b"),
            Task("join", task_type, ("a", "b"), "join"),
        ])
        parents_started = Barrier(3, timeout=10)
        release_a, release_b, joined, stop = (Event() for _ in range(4))
        calls = []

        def handle(value):
            calls.append(value)
            if value == "join":
                joined.set()
                return
            parents_started.wait()
            release = release_a if value == "a" else release_b
            if not release.wait(10):
                raise TimeoutError(value)

        with Redis.from_url(os.environ["TEST_REDIS_URL"], decode_responses=True) as redis:
            self.addCleanup(self.delete_queue, queue)
            while dispatch_ready(redis) == 100:
                pass
            # Simulate a consumer disappearing after delivery and before claim.
            self.assertIsNotNone(redis.zpopmin(queue))
            deadline = monotonic() + 10
            while redis.zcard(queue) < 2 and monotonic() < deadline:
                dispatch_ready(redis)
                sleep(0.05)
            self.assertEqual(redis.zcard(queue), 2)
            with ThreadPoolExecutor(max_workers=2) as workers:
                futures = [workers.submit(run_worker, redis, {task_type: handle}, stop) for _ in range(2)]
                try:
                    parents_started.wait()
                    self.assertEqual(self.states(workflow_id), (
                        "running", {"a": "running", "b": "running", "join": "blocked"}
                    ))
                    registrations = [
                        redis.get(key) for key in redis.scan_iter("workflow:worker:*")
                    ]
                    self.assertEqual(sum(
                        value is not None and json.loads(value)["task_types"] == [task_type]
                        for value in registrations
                    ), 2)
                    release_a.set()
                    self.wait_for_state(workflow_id, "a", "succeeded")
                    self.assertEqual(self.states(workflow_id)[1]["join"], "blocked")
                    release_b.set()
                    self.wait_for_state(workflow_id, "join", "ready")
                    member = json.dumps([str(workflow_id), "a"])
                    redis.zadd(queue, {member: 0})
                    while dispatch_ready(redis) == 100:
                        pass
                    self.assertTrue(joined.wait(10))
                finally:
                    release_a.set()
                    release_b.set()
                    stop.set()
                    for future in futures:
                        future.result(timeout=10)
        self.assertCountEqual(calls, ["a", "b", "join"])
        self.assertEqual(self.states(workflow_id)[0], "succeeded")

    def delete_queue(self, queue):
        from redis import Redis

        with Redis.from_url(os.environ["TEST_REDIS_URL"]) as redis:
            redis.delete(queue)

    def wait_for_state(self, workflow_id, task_key, status):
        deadline = monotonic() + 10
        while monotonic() < deadline:
            actual = self.states(workflow_id)[1][task_key]
            if actual == status:
                return
            sleep(0.05)
        self.assertEqual(actual, status)
