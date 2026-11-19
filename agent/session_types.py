"""Public Session states, budgets and control exceptions."""
from dataclasses import asdict, dataclass
from enum import Enum


class SessionState(str, Enum):
    SESSION_IDLE = "session_idle"
    TURN_RUNNING = "turn_running"
    PLANNING = "planning"
    PLAN_AWAITING_APPROVAL = "plan_awaiting_approval"
    EXECUTING = "executing"
    TOOL_AWAITING_APPROVAL = "tool_awaiting_approval"
    MODEL_SWITCH_AWAITING_APPROVAL = "model_switch_awaiting_approval"
    WAITING_SUBAGENT = "waiting_subagent"
    FINALIZING = "finalizing"
    TURN_FINISHED = "turn_finished"
    SESSION_FINISHED = "session_finished"
    COMPUTER_PAUSED = "computer_paused"


@dataclass(frozen=True)
class SessionBudgets:
    max_steps: int = 8
    max_tool_calls: int = 12
    max_token_units: int = 262144
    max_output_tokens: int = 2048
    max_primary_switches_per_turn: int = 1
    max_subagent_depth: int = 1
    max_subagents_per_turn: int = 2
    max_worker_steps: int = 3
    max_worker_tool_calls: int = 4
    max_worker_token_units: int = 131072
    max_worker_output_tokens: int = 512

    def __post_init__(self):
        for name, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if not all((self.max_steps, self.max_token_units, self.max_output_tokens,
                    self.max_worker_steps, self.max_worker_token_units, self.max_worker_output_tokens)):
            raise ValueError("Step, token and output budgets must be positive")


class PartialStreamError(RuntimeError):
    retryable = False


class SessionCancelled(RuntimeError):
    """Cooperative host stop; never retry a model request after this signal."""
    retryable = False
