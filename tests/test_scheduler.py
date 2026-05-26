"""Tests for JobScheduler – add/remove/pause, duplicate prevention, status."""

import time

import pytest

from src.scheduler.job_scheduler import JobScheduler


def _noop():
    pass


@pytest.fixture
def scheduler():
    s = JobScheduler()
    yield s
    if s.is_running:
        s.shutdown(wait=False)


class TestJobRegistration:
    def test_add_job_returns_true(self, scheduler):
        assert scheduler.add_job("j1", _noop, "interval", seconds=60) is True

    def test_add_duplicate_returns_false(self, scheduler):
        scheduler.add_job("j1", _noop, "interval", seconds=60)
        assert scheduler.add_job("j1", _noop, "interval", seconds=60) is False

    def test_job_names_after_add(self, scheduler):
        scheduler.add_job("a", _noop, "interval", seconds=10)
        scheduler.add_job("b", _noop, "interval", seconds=10)
        assert set(scheduler.job_names) == {"a", "b"}

    def test_remove_job(self, scheduler):
        scheduler.add_job("j1", _noop, "interval", seconds=60)
        assert scheduler.remove_job("j1") is True
        assert "j1" not in scheduler.job_names

    def test_remove_nonexistent_returns_false(self, scheduler):
        assert scheduler.remove_job("ghost") is False


class TestPauseResume:
    def test_pause_job(self, scheduler):
        scheduler.add_job("j1", _noop, "interval", seconds=60)
        assert scheduler.pause_job("j1") is True

    def test_pause_nonexistent(self, scheduler):
        assert scheduler.pause_job("ghost") is False

    def test_resume_job(self, scheduler):
        scheduler.add_job("j1", _noop, "interval", seconds=60)
        scheduler.pause_job("j1")
        assert scheduler.resume_job("j1") is True

    def test_resume_nonexistent(self, scheduler):
        assert scheduler.resume_job("ghost") is False


class TestStatus:
    def test_status_contains_keys(self, scheduler):
        scheduler.add_job("j1", _noop, "interval", seconds=60)
        status = scheduler.get_job_status()
        assert "j1" in status
        info = status["j1"]
        assert "state" in info
        assert "next_run" in info
        assert "run_count" in info

    def test_paused_state_reported(self, scheduler):
        scheduler.add_job("j1", _noop, "interval", seconds=60)
        scheduler.pause_job("j1")
        status = scheduler.get_job_status()
        assert status["j1"]["state"] == "paused"


class TestLifecycle:
    def test_start_and_shutdown(self, scheduler):
        scheduler.add_job("j1", _noop, "interval", seconds=60)
        scheduler.start()
        assert scheduler.is_running is True
        scheduler.shutdown()
        assert scheduler.is_running is False

    def test_double_start_is_safe(self, scheduler):
        scheduler.start()
        scheduler.start()
        assert scheduler.is_running is True
