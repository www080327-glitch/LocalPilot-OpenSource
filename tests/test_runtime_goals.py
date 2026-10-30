import unittest

from agent.goals import GoalStatus, GoalStore


class RuntimeGoalTests(unittest.TestCase):
    def test_create_update_and_list(self):
        store = GoalStore()
        goal = store.create("Finish the task")
        self.assertEqual(goal.status, GoalStatus.PENDING.value)
        self.assertEqual(store.list(), [goal])
        updated = store.update(goal.id, status="in_progress", description="Keep working")
        self.assertEqual(updated.description, "Keep working")
        self.assertEqual(updated.status, GoalStatus.IN_PROGRESS.value)
        self.assertTrue(updated.updated_at)

    def test_split_links_children_and_parent(self):
        store = GoalStore()
        parent = store.create("Prepare release")
        children = store.split(parent.id, ["Review changes", "Write notes"])
        self.assertEqual(parent.subgoals, [child.id for child in children])
        self.assertEqual([child.parent_id for child in children], [parent.id, parent.id])

    def test_create_accepts_initial_status_and_subgoals_atomically(self):
        store = GoalStore()
        parent = store.create("Ship fix", status="in_progress", subgoals=["Inspect", "Validate"])
        self.assertEqual(parent.status, GoalStatus.IN_PROGRESS.value)
        self.assertEqual([goal.description for goal in store.list()[1:]], ["Inspect", "Validate"])
        self.assertEqual(parent.subgoals, [goal.id for goal in store.list()[1:]])
        count = len(store.list())
        with self.assertRaises(ValueError):
            store.create("Bad", status="invalid", subgoals=["Child"])
        with self.assertRaises(ValueError):
            store.create("Bad", subgoals=["  "])
        self.assertEqual(len(store.list()), count)

    def test_events_include_created_updated_and_completed(self):
        events = []
        store = GoalStore(event_callback=events.append)
        goal = store.create("Do work")
        store.update(goal.id, status="done")
        self.assertEqual([event["type"] for event in events], ["GoalCreated", "GoalCompleted"])
        self.assertIs(events[-1]["goal"], goal)

    def test_rejects_invalid_inputs(self):
        store = GoalStore()
        with self.assertRaises(ValueError):
            store.create("  ")
        goal = store.create("A goal")
        with self.assertRaises(ValueError):
            store.update(goal.id, status="unknown")
        with self.assertRaises(ValueError):
            store.split(goal.id, [])
        with self.assertRaises(KeyError):
            store.update("missing", status="done")

    def test_goal_and_child_limits_are_checked_before_split(self):
        store = GoalStore(max_goals=3)
        parent = store.create("Parent")
        store.split(parent.id, ["One"])
        with self.assertRaises(ValueError):
            store.split(parent.id, ["Two", "Three"])
        self.assertEqual(len(store.list()), 2)
        self.assertEqual(len(parent.subgoals), 1)

        limited = GoalStore(max_goals=2)
        parent = limited.create("Parent")
        limited.create("Child", parent_id=parent.id)
        with self.assertRaises(ValueError):
            limited.create("Too many")
        with self.assertRaises(ValueError):
            GoalStore(max_goals=True)


if __name__ == "__main__":
    unittest.main()
