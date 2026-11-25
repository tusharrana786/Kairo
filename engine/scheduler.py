import json
import logging
import time

import psycopg
from redis import Redis
from redis.exceptions import RedisError

from .dispatch import connect_redis, queue_key
from .store import connect

logger = logging.getLogger(__name__)


def dispatch_ready(redis: Redis) -> int:
    with connect() as connection:
        tasks = connection.execute(
            """WITH due AS (
                   SELECT workflow_id, task_key FROM task_executions
                   WHERE status = 'ready' AND redis_dispatch_after <= now()
                   ORDER BY redis_dispatch_after, workflow_id, task_key
                   LIMIT 100 FOR UPDATE SKIP LOCKED
               )
               UPDATE task_executions AS task
               SET redis_dispatch_after = now() + interval '5 seconds'
               FROM due WHERE (task.workflow_id, task.task_key) = (due.workflow_id, due.task_key)
               RETURNING task.workflow_id, task.task_key, task.task_type""",
        ).fetchall()
        if tasks:
            with redis.pipeline(transaction=False) as pipeline:
                score = time.time()
                for task in tasks:
                    member = json.dumps([str(task["workflow_id"]), task["task_key"]])
                    pipeline.zadd(queue_key(task["task_type"]), {member: score}, nx=True)
                pipeline.execute()
        return len(tasks)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    with connect_redis() as redis:
        while True:
            try:
                if dispatch_ready(redis) == 100:
                    continue
            except (psycopg.OperationalError, RedisError):
                logger.exception("Dispatch failed")
            time.sleep(0.5)


if __name__ == "__main__":
    main()
