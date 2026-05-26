"""Tests for ManagedThreadPool – submit, stats, active tasks, shutdown."""

import time

import pytest

from src.workers.thread_pool import ManagedThreadPool


@pytest.fixture
def pool():
    p = ManagedThreadPool(max_workers=2)
    yield p
    if not p.is_shutdown:
        p.shutdown(wait=True)


class TestSubmitAndComplete:
    def test_submit_returns_future(self, pool):
        future = pool.submit_task("t1", lambda: 42)
        assert future.result(timeout=2) == 42

    def test_stats_after_success(self, pool):
        pool.submit_task("t1", lambda: 1).result(timeout=2)
        assert pool.stats.tasks_submitted == 1
        assert pool.stats.tasks_completed == 1
        assert pool.stats.tasks_failed == 0

    def test_stats_after_failure(self, pool):
        def boom():
            raise ValueError("test error")

        future = pool.submit_task("t1", boom)
        with pytest.raises(ValueError):
            future.result(timeout=2)
        assert pool.stats.tasks_failed == 1


class TestActiveTasks:
    def test_active_tasks_during_run(self, pool):
        started = __import__("threading").Event()
        release = __import__("threading").Event()

        def slow():
            started.set()
            release.wait(timeout=5)

        pool.submit_task("slow_task", slow)
        started.wait(timeout=2)
        active = pool.get_active_tasks()
        assert "slow_task" in active
        release.set()

    def test_no_active_after_completion(self, pool):
        pool.submit_task("fast", lambda: None).result(timeout=2)
        time.sleep(0.05)
        assert pool.get_active_tasks() == {}


class TestPoolStats:
    def test_avg_duration(self, pool):
        pool.submit_task("t1", lambda: time.sleep(0.05)).result(timeout=2)
        pool.submit_task("t2", lambda: time.sleep(0.05)).result(timeout=2)
        assert pool.stats.avg_duration > 0

    def test_multiple_tasks(self, pool):
        futures = [pool.submit_task(f"t{i}", lambda: i) for i in range(5)]
        for f in futures:
            f.result(timeout=2)
        assert pool.stats.tasks_submitted == 5
        assert pool.stats.tasks_completed == 5


class TestShutdown:
    def test_graceful_shutdown(self, pool):
        pool.submit_task("t1", lambda: 1).result(timeout=2)
        pool.shutdown(wait=True)
        assert pool.is_shutdown is True

    def test_submit_after_shutdown_raises(self, pool):
        pool.shutdown()
        with pytest.raises(RuntimeError):
            pool.submit_task("t1", lambda: 1)
