"""Tests for ExtractionScheduler."""
import pytest
from unittest.mock import MagicMock

from src.scheduler.scheduler import (
    ExtractionScheduler, JobConfig,
    STARTUP_DELAY_SECONDS, WATCHDOG_INTERVAL_MINUTES,
    EXTRACTION_TIMEOUT_MINUTES,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_job_fn():
    return MagicMock()


@pytest.fixture
def scheduler():
    return ExtractionScheduler()


@pytest.fixture
def scheduler_with_jobs(scheduler, mock_job_fn):
    scheduler.register_job(JobConfig(
        job_id="extract_orders", name="Orders",
        run_fn=mock_job_fn, interval_minutes=30,
    ))
    scheduler.register_job(JobConfig(
        job_id="extract_chats", name="Chats",
        run_fn=mock_job_fn, interval_hours=4,
    ))
    scheduler.register_job(JobConfig(
        job_id="extract_listings", name="Listings",
        run_fn=mock_job_fn, interval_hours=4,
    ))
    return scheduler


# ─── Constants ───────────────────────────────────────────────────────────────

def test_startup_delay_is_30():
    assert STARTUP_DELAY_SECONDS == 30


def test_watchdog_interval_is_5():
    assert WATCHDOG_INTERVAL_MINUTES == 5


def test_extraction_timeouts():
    assert EXTRACTION_TIMEOUT_MINUTES["orders"] == 20
    assert EXTRACTION_TIMEOUT_MINUTES["chats"] == 60
    assert EXTRACTION_TIMEOUT_MINUTES["listings"] == 45


# ─── Initialization ─────────────────────────────────────────────────────────

def test_scheduler_init(scheduler):
    assert not scheduler.is_running()
    assert scheduler.get_jobs_status() == {}
    assert scheduler.valid_job_ids == set()


def test_register_job(scheduler, mock_job_fn):
    scheduler.register_job(JobConfig(
        job_id="test_job", name="Test", run_fn=mock_job_fn,
    ))
    assert "test_job" in scheduler.valid_job_ids
    status = scheduler.get_jobs_status()
    assert "test_job" in status
    assert status["test_job"]["name"] == "Test"
    assert status["test_job"]["last_status"] == "never_run"


def test_register_multiple_jobs(scheduler_with_jobs):
    assert len(scheduler_with_jobs.valid_job_ids) == 3
    assert "extract_orders" in scheduler_with_jobs.valid_job_ids
    assert "extract_chats" in scheduler_with_jobs.valid_job_ids
    assert "extract_listings" in scheduler_with_jobs.valid_job_ids


# ─── Start / Stop ────────────────────────────────────────────────────────────

def test_start(scheduler_with_jobs):
    scheduler_with_jobs.start()
    assert scheduler_with_jobs.is_running()


def test_stop(scheduler_with_jobs):
    scheduler_with_jobs.start()
    scheduler_with_jobs.stop()
    assert not scheduler_with_jobs.is_running()


def test_double_start(scheduler_with_jobs):
    scheduler_with_jobs.start()
    scheduler_with_jobs.start()
    assert scheduler_with_jobs.is_running()


def test_stop_when_not_running(scheduler):
    scheduler.stop()
    assert not scheduler.is_running()


# ─── Jobs Status ─────────────────────────────────────────────────────────────

def test_jobs_status_format(scheduler_with_jobs):
    status = scheduler_with_jobs.get_jobs_status()
    assert len(status) == 3

    required = {"name", "next_run_time", "last_run_time", "last_status",
                "last_error", "last_skip_reason", "run_count", "skip_count"}

    for job_id, info in status.items():
        missing = required - set(info.keys())
        assert not missing, f"Missing fields in {job_id}: {missing}"
        assert info["last_status"] == "never_run"
        assert info["run_count"] == 0
        assert info["skip_count"] == 0


def test_jobs_status_after_run(scheduler_with_jobs):
    scheduler_with_jobs.start()
    scheduler_with_jobs.run_job_now("extract_orders")
    status = scheduler_with_jobs.get_jobs_status()
    assert status["extract_orders"]["last_status"] == "success"
    assert status["extract_orders"]["run_count"] == 1


def test_jobs_status_after_error(scheduler):
    fail_fn = MagicMock(side_effect=RuntimeError("boom"))
    scheduler.register_job(JobConfig(
        job_id="failing_job", name="Fail", run_fn=fail_fn,
    ))
    scheduler.start()

    with pytest.raises(RuntimeError):
        scheduler.run_job_now("failing_job")

    status = scheduler.get_jobs_status()
    assert status["failing_job"]["last_status"] == "error"
    assert status["failing_job"]["last_error"] == "boom"
    assert status["failing_job"]["run_count"] == 1


# ─── Run Job Now ─────────────────────────────────────────────────────────────

def test_run_job_now_invalid(scheduler_with_jobs):
    result = scheduler_with_jobs.run_job_now("nonexistent")
    assert result is False


def test_run_job_now_valid(scheduler_with_jobs, mock_job_fn):
    scheduler_with_jobs.start()
    result = scheduler_with_jobs.run_job_now("extract_orders")
    assert result is True
    mock_job_fn.assert_called()


def test_run_job_now_all_jobs(scheduler_with_jobs, mock_job_fn):
    scheduler_with_jobs.start()
    for job_id in ("extract_orders", "extract_chats", "extract_listings"):
        assert scheduler_with_jobs.run_job_now(job_id) is True


# ─── Set Job Interval ────────────────────────────────────────────────────────

def test_set_interval_valid(scheduler_with_jobs):
    scheduler_with_jobs.set_job_interval("extract_orders", hours=2, minutes=30)


def test_set_interval_invalid_job(scheduler_with_jobs):
    with pytest.raises(ValueError, match="Invalid job ID"):
        scheduler_with_jobs.set_job_interval("nonexistent", hours=1)


def test_set_interval_zero(scheduler_with_jobs):
    with pytest.raises(ValueError, match="cannot be 0"):
        scheduler_with_jobs.set_job_interval("extract_orders", hours=0, minutes=0)


def test_set_interval_negative(scheduler_with_jobs):
    with pytest.raises(ValueError, match="cannot be negative"):
        scheduler_with_jobs.set_job_interval("extract_orders", hours=-1)


# ─── Record Skip ─────────────────────────────────────────────────────────────

def test_record_skip(scheduler_with_jobs):
    scheduler_with_jobs._record_skip("extract_orders", "No valid cookies")
    status = scheduler_with_jobs.get_jobs_status()
    assert status["extract_orders"]["last_status"] == "skipped"
    assert status["extract_orders"]["skip_count"] == 1
    assert status["extract_orders"]["last_skip_reason"] == "No valid cookies"


def test_record_skip_increments(scheduler_with_jobs):
    scheduler_with_jobs._record_skip("extract_orders", "reason1")
    scheduler_with_jobs._record_skip("extract_orders", "reason2")
    status = scheduler_with_jobs.get_jobs_status()
    assert status["extract_orders"]["skip_count"] == 2
    assert status["extract_orders"]["last_skip_reason"] == "reason2"


# ─── Account Validation Gating ──────────────────────────────────────────────

def test_skip_when_no_valid_accounts(mock_job_fn):
    validate = MagicMock(return_value={"all_valid": False, "results": []})
    sched = ExtractionScheduler(validate_accounts=validate)
    sched.register_job(JobConfig(
        job_id="orders", name="Orders", run_fn=mock_job_fn,
        requires_valid_accounts=True,
    ))
    sched.start()
    sched.run_job_now("orders")
    mock_job_fn.assert_not_called()
    status = sched.get_jobs_status()
    assert status["orders"]["last_status"] == "skipped"


def test_run_when_accounts_valid(mock_job_fn):
    validate = MagicMock(return_value={"all_valid": True, "results": [{"valid": True}]})
    sched = ExtractionScheduler(validate_accounts=validate)
    sched.register_job(JobConfig(
        job_id="orders", name="Orders", run_fn=mock_job_fn,
        requires_valid_accounts=True,
    ))
    sched.start()
    sched.run_job_now("orders")
    mock_job_fn.assert_called_once()


def test_skip_when_already_running(mock_job_fn):
    check_running = MagicMock(return_value=True)
    sched = ExtractionScheduler(check_running=check_running)
    sched.register_job(JobConfig(
        job_id="orders", name="Orders", run_fn=mock_job_fn,
        requires_valid_accounts=False,
    ))
    sched.start()
    sched.run_job_now("orders")
    mock_job_fn.assert_not_called()
    status = sched.get_jobs_status()
    assert status["orders"]["last_status"] == "skipped"
    assert "already running" in status["orders"]["last_skip_reason"]


# ─── Startup Sequence ───────────────────────────────────────────────────────

def test_startup_runs_startup_jobs():
    fn1 = MagicMock()
    fn2 = MagicMock()
    fn3 = MagicMock()
    sched = ExtractionScheduler()
    sched.register_job(JobConfig("orders", "Orders", fn1, run_on_startup=True, requires_valid_accounts=False))
    sched.register_job(JobConfig("chats", "Chats", fn2, run_on_startup=True, requires_valid_accounts=False))
    sched.register_job(JobConfig("relist", "Relist", fn3, run_on_startup=False, requires_valid_accounts=False))

    sched.run_startup_sequence()

    fn1.assert_called_once()
    fn2.assert_called_once()
    fn3.assert_not_called()


def test_startup_continues_on_error():
    fn1 = MagicMock(side_effect=RuntimeError("fail"))
    fn2 = MagicMock()
    sched = ExtractionScheduler()
    sched.register_job(JobConfig("j1", "J1", fn1, run_on_startup=True, requires_valid_accounts=False))
    sched.register_job(JobConfig("j2", "J2", fn2, run_on_startup=True, requires_valid_accounts=False))

    sched.run_startup_sequence()
    fn2.assert_called_once()


def test_startup_with_failed_validation():
    validate = MagicMock(return_value={"all_valid": False, "results": []})
    fn = MagicMock()
    sched = ExtractionScheduler(validate_accounts=validate)
    sched.register_job(JobConfig("j1", "J1", fn, run_on_startup=True, requires_valid_accounts=False))

    sched.run_startup_sequence()
    fn.assert_not_called()


def test_startup_with_validation_error():
    validate = MagicMock(side_effect=RuntimeError("DB down"))
    fn = MagicMock()
    sched = ExtractionScheduler(validate_accounts=validate)
    sched.register_job(JobConfig("j1", "J1", fn, run_on_startup=True, requires_valid_accounts=False))

    sched.run_startup_sequence()
    fn.assert_not_called()


# ─── Watchdog ────────────────────────────────────────────────────────────────

def test_watchdog_calls_mark_zombie():
    mark_zombie = MagicMock(return_value=[])
    sched = ExtractionScheduler(mark_zombie=mark_zombie)
    sched.run_watchdog()

    assert mark_zombie.call_count == len(EXTRACTION_TIMEOUT_MINUTES)
    mark_zombie.assert_any_call("orders", 20)
    mark_zombie.assert_any_call("chats", 60)
    mark_zombie.assert_any_call("listings", 45)


def test_watchdog_logs_stale():
    mark_zombie = MagicMock(side_effect=[
        ["2026-01-01T00:00:00"],
        [],
        [],
    ])
    sched = ExtractionScheduler(mark_zombie=mark_zombie)
    sched.run_watchdog()


def test_watchdog_continues_on_error():
    mark_zombie = MagicMock(side_effect=[
        RuntimeError("DB error"),
        [],
        [],
    ])
    sched = ExtractionScheduler(mark_zombie=mark_zombie)
    sched.run_watchdog()
    assert mark_zombie.call_count == 3


def test_watchdog_no_callback():
    sched = ExtractionScheduler()
    sched.run_watchdog()


# ─── Valid Job IDs ───────────────────────────────────────────────────────────

def test_valid_job_ids_immutable(scheduler_with_jobs):
    ids = scheduler_with_jobs.valid_job_ids
    ids.add("hacked")
    assert "hacked" not in scheduler_with_jobs.valid_job_ids


# ─── JobConfig ───────────────────────────────────────────────────────────────

def test_job_config_defaults():
    fn = MagicMock()
    cfg = JobConfig("test", "Test", fn)
    assert cfg.job_id == "test"
    assert cfg.name == "Test"
    assert cfg.interval_minutes == 0
    assert cfg.interval_hours == 0
    assert cfg.misfire_grace_time == 300
    assert cfg.run_on_startup is True
    assert cfg.requires_valid_accounts is True


def test_job_config_custom():
    fn = MagicMock()
    cfg = JobConfig(
        "relist", "Relist", fn,
        interval_hours=72, misfire_grace_time=3600,
        run_on_startup=False, requires_valid_accounts=False,
    )
    assert cfg.interval_hours == 72
    assert cfg.misfire_grace_time == 3600
    assert cfg.run_on_startup is False
    assert cfg.requires_valid_accounts is False
