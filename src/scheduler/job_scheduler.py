"""APScheduler wrapper with job registry, duplicate prevention, and graceful lifecycle."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)


class JobState(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"
    PENDING = "pending"


@dataclass
class JobInfo:
    name: str
    func: Callable
    trigger: str
    trigger_args: dict[str, Any] = field(default_factory=dict)
    max_instances: int = 1
    misfire_grace_time: int = 30
    last_run: datetime | None = None
    last_error: str | None = None
    run_count: int = 0
    error_count: int = 0


class JobScheduler:
    """Wraps APScheduler BackgroundScheduler with a named job registry."""

    def __init__(self, misfire_grace_time: int = 30, max_instances: int = 1):
        self._default_misfire = misfire_grace_time
        self._default_max_instances = max_instances
        self._registry: dict[str, JobInfo] = {}
        self._scheduler = BackgroundScheduler()
        self._scheduler.add_listener(self._on_job_event, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED)
        self._started = False

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        if not self._started:
            self._scheduler.start()
            self._started = True
            logger.info("JobScheduler started")

    def shutdown(self, wait: bool = True) -> None:
        if self._started:
            self._scheduler.shutdown(wait=wait)
            self._started = False
            logger.info("JobScheduler shut down")

    @property
    def is_running(self) -> bool:
        return self._started

    # -- job management ---------------------------------------------------

    def add_job(
        self,
        name: str,
        func: Callable,
        trigger: str,
        max_instances: int | None = None,
        misfire_grace_time: int | None = None,
        **trigger_args: Any,
    ) -> bool:
        """Register and schedule a named job. Returns False if name already exists."""
        if name in self._registry:
            logger.warning("Job '%s' already registered – skipping", name)
            return False

        max_inst = max_instances or self._default_max_instances
        grace = misfire_grace_time or self._default_misfire

        self._scheduler.add_job(
            func,
            trigger=trigger,
            id=name,
            name=name,
            max_instances=max_inst,
            misfire_grace_time=grace,
            **trigger_args,
        )

        self._registry[name] = JobInfo(
            name=name,
            func=func,
            trigger=trigger,
            trigger_args=trigger_args,
            max_instances=max_inst,
            misfire_grace_time=grace,
        )
        logger.info("Job '%s' added with trigger '%s'", name, trigger)
        return True

    def remove_job(self, name: str) -> bool:
        if name not in self._registry:
            return False
        self._scheduler.remove_job(name)
        del self._registry[name]
        logger.info("Job '%s' removed", name)
        return True

    def pause_job(self, name: str) -> bool:
        if name not in self._registry:
            return False
        self._scheduler.pause_job(name)
        logger.info("Job '%s' paused", name)
        return True

    def resume_job(self, name: str) -> bool:
        if name not in self._registry:
            return False
        self._scheduler.resume_job(name)
        logger.info("Job '%s' resumed", name)
        return True

    # -- introspection ----------------------------------------------------

    def get_job_status(self) -> dict[str, dict[str, Any]]:
        """Return a dict keyed by job name with scheduling and runtime info."""
        result: dict[str, dict[str, Any]] = {}
        for name, info in self._registry.items():
            ap_job = self._scheduler.get_job(name)
            next_run = getattr(ap_job, "next_run_time", None) if ap_job else None
            state = JobState.PAUSED if (ap_job and next_run is None) else JobState.PENDING
            if self._started:
                state = JobState.RUNNING if state != JobState.PAUSED else state

            result[name] = {
                "state": state.value,
                "next_run": next_run.isoformat() if next_run else None,
                "last_run": info.last_run.isoformat() if info.last_run else None,
                "run_count": info.run_count,
                "error_count": info.error_count,
                "last_error": info.last_error,
            }
        return result

    @property
    def job_names(self) -> list[str]:
        return list(self._registry.keys())

    # -- internal ---------------------------------------------------------

    def _on_job_event(self, event: Any) -> None:
        job_id: str = event.job_id
        info = self._registry.get(job_id)
        if info is None:
            return
        info.last_run = datetime.now()
        if event.code == EVENT_JOB_EXECUTED:
            info.run_count += 1
        elif event.code == EVENT_JOB_ERROR:
            info.error_count += 1
            info.last_error = str(event.exception)
        elif event.code == EVENT_JOB_MISSED:
            info.error_count += 1
            info.last_error = "missed"
