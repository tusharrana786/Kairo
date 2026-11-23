import unittest

from engine.graph import InvalidGraph, Task, validate_graph


class GraphTests(unittest.TestCase):
    def test_fan_out_and_fan_in_in_any_order(self):
        tasks = [
            Task("join", "merge", ("left", "right")),
            Task("left", "transform", ("root",)),
            Task("right", "transform", ("root",)),
            Task("root", "load"),
            Task("independent", "load"),
        ]
        validate_graph(tasks)
        self.assertEqual([task.initial_status for task in tasks],
                         ["blocked", "blocked", "blocked", "ready", "ready"])

    def test_invalid_graphs(self):
        cases = [
            ([], "at least one task"),
            ([Task("a", "x"), Task("a", "x")], "Duplicate task"),
            ([Task("a", "x", ("b",))], "Unknown dependency"),
            ([Task("a", "x", ("a",))], "depends on itself"),
            ([Task("a", "x"), Task("b", "x", ("a", "a"))], "Duplicate dependency"),
            ([Task("a", "x", ("b",)), Task("b", "x", ("a",)), Task("root", "x")], "cycle"),
        ]
        for tasks, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(InvalidGraph, message):
                validate_graph(tasks)
