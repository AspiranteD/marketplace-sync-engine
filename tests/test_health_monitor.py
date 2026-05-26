"""Tests for HealthMonitor – stall detection, missed schedule, heartbeat, auto-restart."""

import time

import pytest

from src.watchdog.health_monitor import HealthMonitor, IssueType


@pytest.fixture
def monitor():
    return HealthMonitor(check_interval=1, stall_threshold=0.5, miss_tolerance=1)


class TestRegistration:
    def test_register_and_list(self, monitor):
        monitor.register_job("j1", expected_interval=10)
        assert "j1" in monitor.registered_jobs

    def test_unregister(self, monitor):
        monitor.register_job("j1")
        monitor.unregister_job("j1")
        assert "j1" not in monitor.registered_jobs


class TestStallDetection:
    def test_stalled_job_detected(self, monitor):
        monitor.register_job("j1", max_runtime=0.01)
        monitor.mark_started("j1")
        time.sleep(0.05)
        issues = monitor.check_health()
        stalled = [i for i in issues if i.issue_type == IssueType.STALLED]
        assert len(stalled) == 1
        assert stalled[0].job_name == "j1"

    def test_no_stall_within_threshold(self, monitor):
        monitor.register_job("j1", max_runtime=999)
        monitor.mark_started("j1")
        issues = monitor.check_health()
        stalled = [i for i in issues if i.issue_type == IssueType.STALLED]
        assert len(stalled) == 0


class TestMissedSchedule:
    def test_missed_heartbeat(self, monitor):
        monitor.register_job("j1", expected_interval=0.01)
        monitor.heartbeat("j1")
        time.sleep(0.05)
        issues = monitor.check_health()
        missed = [i for i in issues if i.issue_type == IssueType.MISSED_SCHEDULE]
        assert len(missed) == 1

    def test_heartbeat_resets_misses(self, monitor):
        monitor.register_job("j1", expected_interval=999)
        monitor.heartbeat("j1")
        issues = monitor.check_health()
        missed = [i for i in issues if i.issue_type == IssueType.MISSED_SCHEDULE]
        assert len(missed) == 0


class TestCrashDetection:
    def test_crashed_job_after_many_misses(self):
        mon = HealthMonitor(miss_tolerance=1)
        mon.register_job("j1", expected_interval=0.001)
        mon.heartbeat("j1")
        time.sleep(0.01)
        mon.check_health()
        time.sleep(0.01)
        mon.check_health()
        time.sleep(0.01)
        issues = mon.check_health()
        crashed = [i for i in issues if i.issue_type == IssueType.CRASHED]
        assert len(crashed) >= 1


class TestAutoRestart:
    def test_auto_restart_callback(self):
        restarted = []
        mon = HealthMonitor(auto_restart=True, miss_tolerance=1)
        mon.register_job("j1", expected_interval=0.001, restart_callback=lambda: restarted.append(True))
        mon.heartbeat("j1")
        time.sleep(0.01)
        mon.check_health()
        time.sleep(0.01)
        mon.check_health()
        time.sleep(0.01)
        mon.check_health()
        assert len(restarted) >= 1


class TestAllIssuesTracking:
    def test_all_issues_accumulated(self, monitor):
        monitor.register_job("j1", max_runtime=0.01)
        monitor.mark_started("j1")
        time.sleep(0.05)
        monitor.check_health()
        monitor.check_health()
        assert len(monitor.all_issues) >= 2
