"""Local agent activity for the screen-edge “working” indicator."""
from __future__ import annotations

import time

from .job_kinds import JOB_KINDS
from .entitlements import EXEMPT_KINDS

HEARTBEAT_TTL_S = 45
OBJECTIVE_IDLE_OFF_S = 60

# Jobs that drive the computer; status/signin never turn the border on.
COMPUTER_USE_KINDS = frozenset(JOB_KINDS - EXEMPT_KINDS)


class AgentSession:
    """Tracks whether the agent is actively using the machine."""

    def __init__(self) -> None:
        self._last_beat = 0.0
        self._last_objective_beat = 0.0
        self._running_kind: str | None = None
        self._computer_jobs = 0
        self._queued = 0
        self._objective_jobs = 0
        self._approval_wait = False

    def heartbeat(self) -> None:
        self._last_beat = time.monotonic()

    def track_objective(self, on: bool) -> None:
        if on:
            self._objective_jobs += 1
            self._last_objective_beat = time.monotonic()
            self.heartbeat()
        else:
            self._objective_jobs = max(0, self._objective_jobs - 1)
            if self._objective_jobs == 0:
                self._last_objective_beat = 0.0
            self.heartbeat()

    def job_enqueued(self) -> None:
        self._queued += 1
        self.heartbeat()

    def job_dequeued(self) -> None:
        self._queued = max(0, self._queued - 1)
        self.heartbeat()

    def job_started(self, kind: str) -> None:
        self._running_kind = kind
        if kind in COMPUTER_USE_KINDS:
            self._computer_jobs += 1
        self.heartbeat()

    def job_finished(self, kind: str) -> None:
        if kind in COMPUTER_USE_KINDS:
            self._computer_jobs = max(0, self._computer_jobs - 1)
        self._running_kind = None
        self.heartbeat()

    def set_approval_wait(self, waiting: bool) -> None:
        self._approval_wait = waiting
        self.heartbeat()

    def reset(self) -> None:
        self._last_beat = 0.0
        self._last_objective_beat = 0.0
        self._running_kind = None
        self._computer_jobs = 0
        self._queued = 0
        self._objective_jobs = 0
        self._approval_wait = False

    @property
    def active(self) -> bool:
        now = time.monotonic()
        if self._computer_jobs > 0 or self._running_kind in COMPUTER_USE_KINDS:
            return True
        if self._queued > 0:
            return True
        if self._objective_jobs > 0:
            if self._last_beat and (now - self._last_beat) < HEARTBEAT_TTL_S:
                return True
            if self._last_objective_beat and (now - self._last_objective_beat) < OBJECTIVE_IDLE_OFF_S:
                return True
        return False

    @property
    def pulse(self) -> bool:
        """Slow opacity pulse while executing; static while waiting on approval."""
        if not self.active:
            return False
        if self._approval_wait:
            return False
        return self._computer_jobs > 0 or self._running_kind in COMPUTER_USE_KINDS or self._queued > 0

    def public(self) -> dict:
        return {
            "agent_active": self.active,
            "agent_pulse": self.pulse,
            "approval_wait": self._approval_wait,
            "computer_jobs": self._computer_jobs,
            "queued": self._queued,
        }
