"""A small in-memory goal list with optional event notifications."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4


class GoalStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


def _timestamp():
    return datetime.now(timezone.utc).isoformat()


def _description(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("description must be a non-empty string")
    value = value.strip()
    if len(value) > 1000:
        raise ValueError("description must be at most 1000 characters")
    return value


@dataclass
class Goal:
    id: str
    description: str
    status: str = GoalStatus.PENDING.value
    subgoals: list = field(default_factory=list)
    created_at: str = field(default_factory=_timestamp)
    updated_at: str = field(default_factory=_timestamp)
    parent_id: str | None = None


class GoalStore:
    """In-memory goal storage. Callback receives one event dictionary."""

    def __init__(self, event_callback=None, max_goals=100):
        if isinstance(max_goals, bool) or not isinstance(max_goals, int) or max_goals < 1:
            raise ValueError("max_goals must be a positive integer")
        self._goals = {}
        self._event_callback = event_callback
        self.max_goals = max_goals

    def _emit(self, event_type, goal):
        if self._event_callback is not None:
            self._event_callback({"type": event_type, "goal": goal})

    def create(self, description, parent_id=None, *, status=None, subgoals=None):
        description = _description(description)
        parent = self._get(parent_id) if parent_id is not None else None
        children = [] if subgoals is None else subgoals
        if not isinstance(children, (list, tuple)) or len(children) > 20:
            raise ValueError("subgoals must be a list of at most 20 descriptions")
        children = [_description(child) for child in children]
        try:
            initial_status = GoalStatus(status).value if status is not None else GoalStatus.PENDING.value
        except ValueError as error:
            raise ValueError(f"Unknown goal status: {status}") from error
        if len(self._goals) + 1 + len(children) > self.max_goals:
            raise ValueError("goal limit reached")
        if parent is not None and len(parent.subgoals) >= 20:
            raise ValueError("a goal can have at most 20 subgoals")
        goal = Goal(id=str(uuid4()), description=description, status=initial_status, parent_id=parent_id)
        self._goals[goal.id] = goal
        if parent is not None:
            parent.subgoals.append(goal.id)
            parent.updated_at = _timestamp()
            self._emit("GoalUpdated", parent)
        self._emit("GoalCreated", goal)
        for child in children:
            self.create(child, parent_id=goal.id)
        return goal

    def update(self, goal_id, status=None, description=None):
        goal = self._get(goal_id)
        new_status = goal.status
        if status is not None:
            try:
                new_status = GoalStatus(status).value
            except ValueError as error:
                raise ValueError(f"Unknown goal status: {status}") from error
        new_description = _description(description) if description is not None else goal.description
        goal.status, goal.description = new_status, new_description
        goal.updated_at = _timestamp()
        self._emit("GoalCompleted" if goal.status == GoalStatus.DONE.value else "GoalUpdated", goal)
        return goal

    def split(self, goal_id, descriptions):
        parent = self._get(goal_id)
        if not isinstance(descriptions, (list, tuple)) or not descriptions:
            raise ValueError("descriptions must be a non-empty list")
        if len(parent.subgoals) + len(descriptions) > 20:
            raise ValueError("a goal can have at most 20 subgoals")
        if len(self._goals) + len(descriptions) > self.max_goals:
            raise ValueError("goal limit reached")
        clean_descriptions = [_description(description) for description in descriptions]
        return [self.create(description, parent_id=goal_id) for description in clean_descriptions]

    def list(self):
        return list(self._goals.values())

    def _get(self, goal_id):
        try:
            return self._goals[goal_id]
        except KeyError as error:
            raise KeyError(f"Unknown goal id: {goal_id}") from error
