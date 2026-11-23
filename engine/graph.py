from collections import deque
from dataclasses import dataclass, field


class InvalidGraph(ValueError):
    pass


@dataclass(frozen=True)
class Task:
    key: str
    type: str
    depends_on: tuple[str, ...] = ()
    input: object = field(default_factory=dict)

    @property
    def initial_status(self) -> str:
        return "blocked" if self.depends_on else "ready"


def validate_graph(tasks: list[Task]) -> None:
    if not tasks:
        raise InvalidGraph("A workflow must have at least one task")

    children: dict[str, list[str]] = {}
    remaining = {}
    for task in tasks:
        if task.key in children:
            raise InvalidGraph(f"Duplicate task key: {task.key}")
        children[task.key] = []
        remaining[task.key] = len(task.depends_on)

    for task in tasks:
        if len(set(task.depends_on)) != len(task.depends_on):
            raise InvalidGraph(f"Duplicate dependency for {task.key}")
        for parent in task.depends_on:
            if parent == task.key:
                raise InvalidGraph(f"Task {task.key} depends on itself")
            if parent not in children:
                raise InvalidGraph(f"Unknown dependency {parent} for {task.key}")
            children[parent].append(task.key)

    ready = deque(key for key, count in remaining.items() if count == 0)
    visited = 0
    while ready:
        visited += 1
        for child in children[ready.popleft()]:
            remaining[child] -= 1
            if remaining[child] == 0:
                ready.append(child)
    if visited != len(tasks):
        raise InvalidGraph("Workflow contains a dependency cycle")
