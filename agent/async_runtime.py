"""Opt-in dispatch and resource admission; AgentSession owns all durable state.

No executor state is recovered. Queues are reconstructed from child records.
The shared condition protects state and checkpoint snapshots, never inference.
"""
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from functools import wraps
import threading
import time


@dataclass(frozen=True)
class AsyncPolicy:
    max_running_children: int = 4
    max_running_per_session: int = 2
    max_children_per_turn: int = 8
    max_queued_children: int = 64
    max_model_requests: int = 2
    cpu_slots: int = 4
    ram_budget_mib: int = 1024
    child_reservation_mib: int = 64
    max_local_model_requests: int | None = None
    max_cloud_model_requests: int | None = None

    def __post_init__(self):
        if any(v is not None and (type(v) is not int or v <= 0) for v in vars(self).values()):
            raise ValueError("Async resource limits must be positive integers")
        if any(getattr(self, k) is None for k in ('max_running_children', 'max_running_per_session', 'max_children_per_turn',
                'max_queued_children', 'max_model_requests', 'cpu_slots', 'ram_budget_mib', 'child_reservation_mib')):
            raise ValueError('Only model category limits may be omitted')
        if self.ram_budget_mib < self.child_reservation_mib:
            raise ValueError("RAM admission must fit at least one child reservation")


def policy_snapshot(policy):
    # Optional admission limits preserve the previous fingerprint when absent.
    return {k: v for k, v in asdict(policy).items() if v is not None}


def serialized(function):
    @wraps(function)
    def wrapped(self, *args, **kwargs):
        if self._async_enabled:
            with self._state_condition:
                return function(self, *args, **kwargs)
        return function(self, *args, **kwargs)
    return wrapped


@contextmanager
def external(condition):
    # Same RLock protocol used by threading.Condition.wait: release *all*
    # recursive acquisitions, then restore them. Host callbacks can reenter.
    saved = condition._release_save()
    try:
        yield
    finally:
        condition._acquire_restore(saved)


class AsyncScheduler:
    def __init__(self, policy, condition=None):
        self.policy = policy
        self.condition = condition or threading.Condition(threading.RLock())
        self.queue = deque()
        self.running = defaultdict(int)
        self.running_workers = set()
        self.models = 0
        self.backend_models = defaultdict(int)
        self.model_queue = deque()
        self.last_owner = self.last_model_owner = None
        self.closed = False
        self.threads = []

    def submit(self, parent, worker_id, operation):
        with self.condition:
            if self.closed or len(self.queue) >= self.policy.max_queued_children:
                raise RuntimeError("Async dispatch backpressure: queue full or closed")
            if any(p is parent and w == worker_id for p, w, _ in self.queue):
                return
            record = next(r for r in parent.subagents if r['id'] == worker_id)
            record['status'] = 'queued'
            self.queue.append((parent, worker_id, operation))
            if not self.threads:
                slots = min(self.policy.max_running_children, self.policy.cpu_slots,
                            self.policy.ram_budget_mib // self.policy.child_reservation_mib)
                for n in range(slots):
                    thread = threading.Thread(target=self._worker, name=f"localpilot-child-{n}", daemon=True)
                    self.threads.append(thread)
                    thread.start()
            self.condition.notify_all()

    def _pick(self):
        eligible = [item for item in self.queue if self.running[item[0]._scheduler_owner] < self.policy.max_running_per_session
                    and (item[0], item[1]) not in self.running_workers]
        if not eligible:
            return None
        item = next((x for x in eligible if x[0]._scheduler_owner != self.last_owner), eligible[0])
        self.queue.remove(item)
        self.last_owner = item[0]._scheduler_owner
        self.running[self.last_owner] += 1
        self.running_workers.add((item[0], item[1]))
        return item

    def owns_worker(self, parent, worker_id):
        with self.condition:
            return (parent, worker_id) in self.running_workers or any(p is parent and w == worker_id for p, w, _ in self.queue)

    def _worker(self):
        while True:
            with self.condition:
                item = self._pick()
                while item is None and not self.closed:
                    self.condition.wait()
                    item = self._pick()
                if item is None:
                    return
            parent, worker_id, operation = item
            try:
                parent._run_async_child(worker_id, operation)
            finally:
                with self.condition:
                    self.running[parent._scheduler_owner] -= 1
                    self.running_workers.discard((parent, worker_id))
                    self.condition.notify_all()

    @contextmanager
    def model_slot(self, runtime, backend=None):
        backend = backend or runtime.current_backend
        local = getattr(backend, 'is_local', None) is True
        limit = self.policy.max_local_model_requests if local else self.policy.max_cloud_model_requests
        key = (local, getattr(backend, 'base_url', None) or id(backend), runtime._model_name(backend))
        ticket = (runtime._scheduler_owner, object(), key, limit)
        with self.condition:
            self.model_queue.append(ticket)
            try:
                while True:
                    runtime._check_cancel()
                    if self.closed:
                        raise RuntimeError("Scheduler closed")
                    eligible = [x for x in self.model_queue if x[3] is None or self.backend_models[x[2]] < x[3]]
                    selected = next((x for x in eligible if x[0] != self.last_model_owner), eligible[0] if eligible else None)
                    if selected == ticket and self.models < self.policy.max_model_requests:
                        self.model_queue.remove(ticket)
                        self.models += 1
                        self.backend_models[key] += 1
                        self.last_model_owner = ticket[0]
                        break
                    self.condition.wait(0.05)
            except BaseException:
                self.model_queue.remove(ticket)
                self.condition.notify_all()
                raise
        try:
            yield
        finally:
            with self.condition:
                self.models -= 1
                self.backend_models[key] -= 1
                self.condition.notify_all()

    def close(self):
        with self.condition:
            if self.queue or any(self.running.values()) or self.models:
                raise RuntimeError("Scheduler close requires drained children and requests")
            self.closed = True
            self.condition.notify_all()
        if self.condition._is_owned():
            with external(self.condition):
                for thread in self.threads:
                    thread.join()
        else:
            for thread in self.threads:
                thread.join()
