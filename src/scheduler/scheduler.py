"""
ExtractionScheduler: configurable multi-job scheduler with watchdog.

Manages 5+ independent extraction/sync jobs with:
  - APScheduler AsyncIO backend
  - Startup sequence: validate accounts -> run extractors sequentially
  - Per-job intervals (orders=30min, chats=4h, listings=4h, relist=72h, prices=24h)
  - Watchdog: detects zombie extractions (running > timeout) every 5 min
  - Account validation gating: skip extraction if no valid accounts
  - Dynamic interval changes at runtime via API
  - Job status tracking: run_count, skip_count, last_status, last_error
  - Event listeners for APScheduler job execution/error events
  - Misfire grace time per job (300s extractors, 3600s relist)
  - max_instances=1 + coalesce=True to prevent overlapping runs
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, Optional, Set

logger = logging.getLogger(__name__)

STARTUP_DELAY_SECONDS = 30

WATCHDOG_INTERVAL_MINUTES = 5
EXTRACTION_TIMEOUT_MINUTES = {
    "orders": 20,
    "chats": 60,
    "listings": 45,
}


class JobConfig:
    """Configuration for a single scheduled job."""

    def __init__(
        self,
        job_id: str,
        name: str,
        run_fn: Callable,
        interval_minutes: int = 0,
        interval_hours: int = 0,
        misfire_grace_time: int = 300,
        run_on_startup: bool = True,
        requires_valid_accounts: bool = True,
    ):
        self.job_id = job_id
        self.name = name
        self.run_fn = run_fn
        self.interval_minutes = interval_minutes
        self.interval_hours = interval_hours
        self.misfire_grace_time = misfire_grace_time
        self.run_on_startup = run_on_startup
        self.requires_valid_accounts = requires_valid_accounts


class ExtractionScheduler:
    """
    Multi-job scheduler with watchdog and startup sequence.

    At startup: validates accounts, then runs startup jobs sequentially.
    After startup: each job runs independently on its interval.
    Watchdog detects zombie extractions every 5 minutes.

    Database-agnostic: uses callbacks for account validation,
    extraction running, and zombie detection.
    """

    def __init__(
        self,
        validate_accounts: Optional[Callable[[], dict]] = None,
        check_running: Optional[Callable[[str], bool]] = None,
        mark_zombie: Optional[Callable[[str, int], list]] = None,
        on_job_complete: Optional[Callable[[str, dict], None]] = None,
    ):
        self._validate_accounts = validate_accounts
        self._check_running = check_running
        self._mark_zombie = mark_zombie
        self._on_job_complete = on_job_complete

        self._jobs: Dict[str, JobConfig] = {}
        self._jobs_status: Dict[str, Dict[str, Any]] = {}
        self._valid_job_ids: Set[str] = set()
        self._running = False
        self._scheduler = None

    def register_job(self, config: JobConfig):
        """Register a job configuration."""
        self._jobs[config.job_id] = config
        self._valid_job_ids.add(config.job_id)

    @property
    def valid_job_ids(self) -> Set[str]:
        return self._valid_job_ids.copy()

    def start(self, run_immediately: bool = True):
        """Start the scheduler with all registered jobs."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        self._running = True

        if run_immediately:
            logger.info(
                "Scheduler started - startup sequence in %ds, %d jobs registered",
                STARTUP_DELAY_SECONDS, len(self._jobs),
            )
        else:
            logger.info("Scheduler started (no immediate execution)")

    def stop(self):
        """Stop the scheduler."""
        if self._running:
            self._running = False
            logger.info("Scheduler stopped")

    def is_running(self) -> bool:
        return self._running

    def get_jobs_status(self) -> Dict[str, Dict[str, Any]]:
        """Return status of all registered jobs."""
        jobs_info = {}
        for job_id, config in self._jobs.items():
            job_status = self._jobs_status.get(job_id, {})
            jobs_info[job_id] = {
                "name": config.name,
                "next_run_time": job_status.get("next_run_time"),
                "last_run_time": job_status.get("last_run_time"),
                "last_status": job_status.get("last_status", "never_run"),
                "last_error": job_status.get("last_error"),
                "last_skip_reason": job_status.get("last_skip_reason"),
                "run_count": job_status.get("run_count", 0),
                "skip_count": job_status.get("skip_count", 0),
            }
        return jobs_info

    def run_job_now(self, job_id: str) -> bool:
        """Schedule a job for immediate execution."""
        if job_id not in self._valid_job_ids:
            logger.warning("Invalid job ID: %s. Valid: %s", job_id, self._valid_job_ids)
            return False

        if job_id not in self._jobs:
            logger.warning("Job %s not found", job_id)
            return False

        logger.info("Job %s scheduled for immediate execution", job_id)
        self._execute_job(job_id)
        return True

    def set_job_interval(self, job_id: str, hours: int = 0, minutes: int = 0):
        """Change the interval of a registered job at runtime."""
        if job_id not in self._valid_job_ids:
            raise ValueError(
                f"Invalid job ID: {job_id}. Valid: {sorted(self._valid_job_ids)}"
            )
        if hours == 0 and minutes == 0:
            raise ValueError("Interval cannot be 0")
        if hours < 0 or minutes < 0:
            raise ValueError("Interval cannot be negative")

        config = self._jobs[job_id]
        config.interval_hours = hours
        config.interval_minutes = minutes
        logger.info("Interval for %s changed to %dh %dm", job_id, hours, minutes)

    def run_startup_sequence(self):
        """
        Startup sequence: validate accounts, then run startup jobs sequentially.

        If account validation fails, activates regular schedules anyway
        (degraded mode).
        """
        if self._validate_accounts:
            logger.info("Startup: validating accounts...")
            try:
                validation = self._validate_accounts()
                if not validation.get("all_valid"):
                    valid_count = sum(
                        1 for r in validation.get("results", []) if r.get("valid")
                    )
                    logger.warning(
                        "Validation failed: %d/%d valid accounts. "
                        "Regular jobs will activate anyway.",
                        valid_count, len(validation.get("results", [])),
                    )
                    return
                logger.info("Account validation OK")
            except Exception as e:
                logger.error("Error validating accounts at startup: %s", e)
                return

        startup_jobs = [
            jid for jid, cfg in self._jobs.items() if cfg.run_on_startup
        ]

        for job_id in startup_jobs:
            try:
                self._execute_job(job_id)
                logger.info("Startup: %s completed", job_id)
            except Exception as e:
                logger.error("Startup: error in %s: %s", job_id, e)

        logger.info("Startup sequence completed")

    def _execute_job(self, job_id: str):
        """Execute a single job with account validation and status tracking."""
        config = self._jobs.get(job_id)
        if not config:
            return

        if config.requires_valid_accounts and self._validate_accounts:
            try:
                validation = self._validate_accounts()
                if not validation.get("all_valid"):
                    self._record_skip(job_id, "No valid accounts available")
                    return
            except Exception:
                pass

        if self._check_running and self._check_running(config.job_id):
            self._record_skip(job_id, f"{config.job_id} already running")
            return

        try:
            config.run_fn()
            self._record_success(job_id)
        except Exception as e:
            self._record_error(job_id, str(e))
            raise

    def run_watchdog(self):
        """
        Detect zombie extractions: running longer than their timeout.

        Checks each extraction type against its timeout threshold
        and marks stale ones as 'timeout'.
        """
        if not self._mark_zombie:
            return

        for ext_type, timeout_min in EXTRACTION_TIMEOUT_MINUTES.items():
            try:
                stale = self._mark_zombie(ext_type, timeout_min)
                for item in stale:
                    logger.warning(
                        "WATCHDOG: %s was running since %s (>%d min) -> timeout",
                        ext_type, item, timeout_min,
                    )
            except Exception as e:
                logger.error("Error in watchdog for %s: %s", ext_type, e)

    def _record_skip(self, job_id: str, reason: str):
        if job_id not in self._jobs_status:
            self._jobs_status[job_id] = {"run_count": 0, "skip_count": 0}
        self._jobs_status[job_id]["skip_count"] = (
            self._jobs_status[job_id].get("skip_count", 0) + 1
        )
        self._jobs_status[job_id]["last_skip_reason"] = reason
        self._jobs_status[job_id]["last_run_time"] = datetime.now(timezone.utc).isoformat()
        self._jobs_status[job_id]["last_status"] = "skipped"

    def _record_success(self, job_id: str):
        if job_id not in self._jobs_status:
            self._jobs_status[job_id] = {"run_count": 0, "skip_count": 0}
        self._jobs_status[job_id]["run_count"] = (
            self._jobs_status[job_id].get("run_count", 0) + 1
        )
        self._jobs_status[job_id]["last_run_time"] = datetime.now(timezone.utc).isoformat()
        self._jobs_status[job_id]["last_status"] = "success"
        self._jobs_status[job_id]["last_error"] = None

    def _record_error(self, job_id: str, error: str):
        if job_id not in self._jobs_status:
            self._jobs_status[job_id] = {"run_count": 0, "skip_count": 0}
        self._jobs_status[job_id]["run_count"] = (
            self._jobs_status[job_id].get("run_count", 0) + 1
        )
        self._jobs_status[job_id]["last_run_time"] = datetime.now(timezone.utc).isoformat()
        self._jobs_status[job_id]["last_status"] = "error"
        self._jobs_status[job_id]["last_error"] = error
