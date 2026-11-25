import argparse
import json
import logging
import time
from collections import deque
from collections.abc import Callable, Mapping
from importlib import import_module
from threading import Event, Thread
from uuid import UUID, uuid4

import psycopg
from redis import Redis
from redis.exceptions import RedisError

from .dispatch import connect_redis, queue_key
from .execution import claim_task, finish_task

logger = logging.getLogger(__name__)
Handler = Callable[[object], None]
REGISTRATION_TTL = 30


def noop(task_input: object) -> None:
    pass


HANDLERS = {"noop": noop}


def heartbeat(redis: Redis, key: str, registration: str, stop: Event) -> None:
    while not stop.wait(REGISTRATION_TTL / 3):
        try:
            redis.set(key, registration, ex=REGISTRATION_TTL)
        except RedisError:
            logger.exception("Could not refresh worker registration")


def execute_next(
    redis: Redis, queues: deque[str], handlers: Mapping[str, Handler], *, timeout: int = 1
) -> bool:
    delivery = redis.bzpopmin(list(queues), timeout=timeout)
    queues.rotate(-1)
    if delivery is None:
        return False
    queue, member, _ = delivery
    task_type = queue.removeprefix(queue_key(""))
    try:
        payload = json.loads(member)
        if not isinstance(payload, list) or len(payload) != 2 or not all(
            isinstance(value, str) for value in payload
        ):
            raise ValueError("Expected a workflow ID and task key")
        raw_id, task_key = payload
        workflow_id = UUID(raw_id)
    except ValueError:
        logger.warning("Discarding malformed task delivery from %s", queue)
        return False
    task = claim_task(workflow_id, task_key, task_type)
    if task is None:
        return False
    try:
        handlers[task_type](task["input"])
    except Exception:
        logger.exception("Task %s/%s failed", workflow_id, task_key)
        succeeded = False
    else:
        succeeded = True
    while True:
        try:
            finish_task(workflow_id, task_key, succeeded=succeeded)
            return True
        except psycopg.OperationalError:
            logger.exception("Could not record completion for %s/%s", workflow_id, task_key)
            time.sleep(1)


def run_worker(redis: Redis, handlers: Mapping[str, Handler], stop: Event) -> None:
    if not handlers or any(not isinstance(key, str) or not key or not callable(handler)
                           for key, handler in handlers.items()):
        raise ValueError("Register at least one task type with a callable handler")
    worker_id = uuid4()
    key = f"workflow:worker:{worker_id}"
    registration = json.dumps({"id": str(worker_id), "task_types": sorted(handlers)})
    redis.set(key, registration, ex=REGISTRATION_TTL)
    logger.info("Registered worker %s for %s", worker_id, ", ".join(sorted(handlers)))
    refresher = Thread(target=heartbeat, args=(redis, key, registration, stop), daemon=True)
    refresher.start()
    queues = deque(map(queue_key, handlers))
    try:
        while not stop.is_set():
            try:
                execute_next(redis, queues, handlers)
            except (psycopg.OperationalError, RedisError):
                logger.exception("Could not receive or claim a task")
                stop.wait(1)
    finally:
        stop.set()
        refresher.join()
        try:
            redis.delete(key)
        except RedisError:
            logger.exception("Could not remove worker registration")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a workflow worker")
    parser.add_argument("--handlers", metavar="MODULE", default=__name__,
                        help="Import HANDLERS from this Python module")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    handlers = HANDLERS if args.handlers == __name__ else import_module(args.handlers).HANDLERS
    with connect_redis() as redis:
        run_worker(redis, handlers, Event())


if __name__ == "__main__":
    main()
