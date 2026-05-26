"""ThreadPoolExecutor wrapper with task tracking, statistics, and graceful shutdown."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class TaskRecord:
    name: str
    submitted_at: float
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None


@dataclass
class PoolStats:
    tasks_submitted: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_duration: float = 0.0

    @property
    def avg_duration(self) -> float:
        done = self.tasks_completed + self.tasks_failed
        return self.total_duration / done if done else 0.0


class ManagedThreadPool:
    """ThreadPoolExecutor with named tasks, stats, and active-task introspection."""

    def __init__(self, max_workers: int = 4, thread_name_prefix: str = "sync-pool"):
        self.max_workers = max_workers
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=thread_name_prefix)
        self._stats = PoolStats()
        self._active: dict[str, TaskRecord] = {}
        self._completed: list[TaskRecord] = []
        self._lock = threading.Lock()
        self._shutdown = False

    # -- public API -------------------------------------------------------

    def submit_task(self, name: str, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Future[Any]:
        if self._shutdown:
            raise RuntimeError("Pool is shut down")

        record = TaskRecord(name=name, submitted_at=time.time())
        with self._lock:
            self._stats.tasks_submitted += 1
            self._active[name] = record

        def _wrapped() -> Any:
            record.started_at = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as exc:
                record.error = str(exc)
                raise
            finally:
                record.finished_at = time.time()
                duration = record.finished_at - (record.started_at or record.finished_at)
                with self._lock:
                    self._stats.total_duration += duration
                    if record.error:
                        self._stats.tasks_failed += 1
                    else:
                        self._stats.tasks_completed += 1
                    self._active.pop(name, None)
                    self._completed.append(record)

        future = self._executor.submit(_wrapped)
        return future

    def get_active_tasks(self) -> dict[str, float]:
        """Return active task names with their current duration in seconds."""
        now = time.time()
        with self._lock:
            return {
                name: now - (rec.started_at or rec.submitted_at)
                for name, rec in self._active.items()
            }

    @property
    def stats(self) -> PoolStats:
        return self._stats

    @property
    def is_shutdown(self) -> bool:
        return self._shutdown

    def shutdown(self, wait: bool = True, timeout: float | None = None) -> None:
        self._shutdown = True
        self._executor.shutdown(wait=wait)
        logger.info("ManagedThreadPool shut down (wait=%s)", wait)
