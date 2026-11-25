import os

from redis import Redis


def connect_redis() -> Redis:
    return Redis.from_url(
        os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=5,
    )


def queue_key(task_type: str) -> str:
    return f"workflow:queue:{task_type}"
