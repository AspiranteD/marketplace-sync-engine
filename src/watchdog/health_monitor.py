"""Job health monitoring with stall detection, missed-schedule checks, and auto-restart."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class IssueType(str, Enum):
    STALLED = "stalled"
    MISSED_SCHEDULE = "missed_schedule"
    CRASHED = "crashed"


@dataclass
class HealthIssue:
    job_name: str
    issue_type: IssueType
    detail: str
    detected_at: float = field(default_factory=time.time)


@dataclass
class _HeartbeatRecord:
    last_beat: float = 0.0
    expected_interval: float = 60.0
    started_at: float | None = None
    max_runtime: float = 300.0
    is_running: bool = False
    consecutive_misses: int = 0


class HealthMonitor:
    """Monitors job health via heartbeats and schedules, with optional auto-restart."""

    def __init__(
        self,
        check_interval: float = 30.0,
        auto_restart: bool = False,
        stall_threshold: float = 300.0,
        miss_tolerance: int = 2,
    ):
        self.check_interval = check_interval
        self.auto_restart = auto_restart
        self.stall_threshold = stall_threshold
        self.miss_tolerance = miss_tolerance

        self._heartbeats: dict[str, _HeartbeatRecord] = {}
        self._restart_callbacks: dict[str, Callable[[], Any]] = {}
        self._issues: list[HealthIssue] = []
        self._monitor_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # -- registration -----------------------------------------------------

    def register_job(
        self,
        name: str,
        expected_interval: float = 60.0,
        max_runtime: float = 300.0,
        restart_callback: Callable[[], Any] | None = None,
    ) -> None:
        self._heartbeats[name] = _HeartbeatRecord(
            expected_interval=expected_interval,
            max_runtime=max_runtime,
        )
        if restart_callback:
            self._restart_callbacks[name] = restart_callback

    def unregister_job(self, name: str) -> None:
        self._heartbeats.pop(name, None)
        self._restart_callbacks.pop(name, None)

    # -- heartbeat API ----------------------------------------------------

    def heartbeat(self, name: str) -> None:
        rec = self._heartbeats.get(name)
        if rec:
            rec.last_beat = time.time()
            rec.consecutive_misses = 0

    def mark_started(self, name: str) -> None:
        rec = self._heartbeats.get(name)
        if rec:
            rec.started_at = time.time()
            rec.is_running = True

    def mark_finished(self, name: str) -> None:
        rec = self._heartbeats.get(name)
        if rec:
            rec.started_at = None
            rec.is_running = False

    def mark_crashed(self, name: str) -> None:
        rec = self._heartbeats.get(name)
        if rec:
            rec.is_running = False
            rec.started_at = None

    # -- health checks ----------------------------------------------------

    def check_health(self) -> list[HealthIssue]:
        """Run all health checks and return newly detected issues."""
        now = time.time()
        new_issues: list[HealthIssue] = []

        for name, rec in self._heartbeats.items():
            if rec.is_running and rec.started_at:
                runtime = now - rec.started_at
                if runtime > rec.max_runtime:
                    issue = HealthIssue(name, IssueType.STALLED, f"Running for {runtime:.0f}s (max {rec.max_runtime:.0f}s)")
                    new_issues.append(issue)

            if rec.last_beat > 0:
                silence = now - rec.last_beat
                if silence > rec.expected_interval * self.miss_tolerance:
                    rec.consecutive_misses += 1
                    issue = HealthIssue(name, IssueType.MISSED_SCHEDULE, f"No heartbeat for {silence:.0f}s (expected every {rec.expected_interval:.0f}s)")
                    new_issues.append(issue)

            if not rec.is_running and rec.started_at is None and rec.consecutive_misses > self.miss_tolerance:
                issue = HealthIssue(name, IssueType.CRASHED, f"{rec.consecutive_misses} consecutive misses")
                new_issues.append(issue)
                if self.auto_restart and name in self._restart_callbacks:
                    logger.info("Auto-restarting job '%s'", name)
                    try:
                        self._restart_callbacks[name]()
                        rec.consecutive_misses = 0
                    except Exception:
                        logger.exception("Failed to restart '%s'", name)

        self._issues.extend(new_issues)
        return new_issues

    @property
    def all_issues(self) -> list[HealthIssue]:
        return list(self._issues)

    @property
    def registered_jobs(self) -> list[str]:
        return list(self._heartbeats.keys())

    # -- background monitoring --------------------------------------------

    def start(self) -> None:
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(target=self._run_loop, daemon=True, name="health-monitor")
        self._monitor_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
            self._monitor_thread = None

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self.check_health()
            self._stop_event.wait(self.check_interval)
