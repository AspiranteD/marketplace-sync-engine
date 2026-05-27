"""Tests for SchedulerAPI."""
import pytest
from unittest.mock import MagicMock

from src.scheduler.api import SchedulerAPI, IntervalUpdateRequest
from src.scheduler.scheduler import ExtractionScheduler, JobConfig


@pytest.fixture
def scheduler():
    sched = ExtractionScheduler()
    fn = MagicMock()
    sched.register_job(JobConfig("extract_orders", "Orders", fn, interval_minutes=30))
    sched.register_job(JobConfig("extract_chats", "Chats", fn, interval_hours=4))
    return sched


@pytest.fixture
def api(scheduler):
    return SchedulerAPI(scheduler)


# ─── IntervalUpdateRequest ───────────────────────────────────────────────────

def test_interval_request_valid():
    req = IntervalUpdateRequest(hours=2, minutes=30)
    assert req.hours == 2
    assert req.minutes == 30


def test_interval_request_defaults():
    req = IntervalUpdateRequest()
    assert req.hours == 1
    assert req.minutes == 0


def test_interval_request_negative_hours():
    with pytest.raises(ValueError, match="negative"):
        IntervalUpdateRequest(hours=-1)


def test_interval_request_minutes_over_59():
    with pytest.raises(ValueError, match="between 0 and 59"):
        IntervalUpdateRequest(hours=0, minutes=60)


def test_interval_request_negative_minutes():
    with pytest.raises(ValueError, match="between 0 and 59"):
        IntervalUpdateRequest(hours=0, minutes=-5)


def test_interval_request_zero():
    with pytest.raises(ValueError, match="cannot be 0"):
        IntervalUpdateRequest(hours=0, minutes=0)


# ─── GET /scheduler/status ──────────────────────────────────────────────────

def test_get_status_not_running(api):
    result = api.get_status()
    assert result["running"] is False
    assert "extract_orders" in result["jobs"]
    assert "extract_chats" in result["jobs"]


def test_get_status_running(api, scheduler):
    scheduler.start()
    result = api.get_status()
    assert result["running"] is True


# ─── POST /scheduler/start ──────────────────────────────────────────────────

def test_start(api, scheduler):
    result = api.start()
    assert result["status"] == "success"
    assert scheduler.is_running()


def test_start_already_running(api, scheduler):
    scheduler.start()
    result = api.start()
    assert result["status"] == "warning"
    assert "already running" in result["message"]


# ─── POST /scheduler/stop ───────────────────────────────────────────────────

def test_stop(api, scheduler):
    scheduler.start()
    result = api.stop()
    assert result["status"] == "success"
    assert not scheduler.is_running()


def test_stop_not_running(api):
    result = api.stop()
    assert result["status"] == "warning"
    assert "not running" in result["message"]


# ─── POST /scheduler/jobs/{id}/run ──────────────────────────────────────────

def test_run_job_valid(api, scheduler):
    scheduler.start()
    result = api.run_job("extract_orders")
    assert result["status"] == "success"
    assert result["job_id"] == "extract_orders"


def test_run_job_invalid_id(api, scheduler):
    scheduler.start()
    result = api.run_job("nonexistent")
    assert result["status"] == "error"
    assert "Invalid job ID" in result["message"]


def test_run_job_scheduler_not_running(api):
    result = api.run_job("extract_orders")
    assert result["status"] == "error"
    assert "not running" in result["message"]


# ─── PUT /scheduler/jobs/{id}/interval ──────────────────────────────────────

def test_set_interval_valid(api, scheduler):
    scheduler.start()
    req = IntervalUpdateRequest(hours=2, minutes=30)
    result = api.set_interval("extract_orders", req)
    assert result["status"] == "success"
    assert result["interval"] == "2h 30m"


def test_set_interval_invalid_job(api, scheduler):
    scheduler.start()
    req = IntervalUpdateRequest(hours=1)
    result = api.set_interval("nonexistent", req)
    assert result["status"] == "error"


def test_set_interval_not_running(api):
    req = IntervalUpdateRequest(hours=1)
    result = api.set_interval("extract_orders", req)
    assert result["status"] == "error"
    assert "not running" in result["message"]


# ─── GET /scheduler/jobs ────────────────────────────────────────────────────

def test_list_jobs(api, scheduler):
    scheduler.start()
    result = api.list_jobs()
    assert result["scheduler_running"] is True
    assert result["total"] == 2
    assert "extract_orders" in result["valid_job_ids"]
    assert "extract_chats" in result["valid_job_ids"]


def test_list_jobs_not_running(api):
    result = api.list_jobs()
    assert result["scheduler_running"] is False
    assert result["total"] == 2
