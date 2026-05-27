"""
REST API for scheduler control.

Endpoints:
  GET  /scheduler/status          - scheduler state + all jobs status
  POST /scheduler/start           - start scheduler
  POST /scheduler/stop            - stop scheduler
  POST /scheduler/jobs/{id}/run   - execute a job immediately
  PUT  /scheduler/jobs/{id}/interval - change a job's interval at runtime
  GET  /scheduler/jobs            - list all jobs with status

Schemas:
  SchedulerStatusResponse: running + jobs dict
  JobRunResponse: status + message + job_id
  IntervalUpdateRequest: hours + minutes (validated: no negatives, no zero)
  IntervalUpdateResponse: status + message + job_id + interval
"""
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class IntervalUpdateRequest:
    """Validated request for changing job interval."""

    def __init__(self, hours: int = 1, minutes: int = 0):
        if hours < 0:
            raise ValueError("hours cannot be negative")
        if minutes < 0 or minutes > 59:
            raise ValueError("minutes must be between 0 and 59")
        if hours == 0 and minutes == 0:
            raise ValueError("interval cannot be 0")
        self.hours = hours
        self.minutes = minutes


class SchedulerAPI:
    """
    Scheduler REST API handler.

    Wraps ExtractionScheduler to provide HTTP-like responses
    without coupling to a specific web framework.
    """

    def __init__(self, scheduler):
        self.scheduler = scheduler

    def get_status(self) -> Dict[str, Any]:
        """GET /scheduler/status"""
        return {
            "running": self.scheduler.is_running(),
            "jobs": self.scheduler.get_jobs_status(),
        }

    def start(self) -> Dict[str, Any]:
        """POST /scheduler/start"""
        if self.scheduler.is_running():
            return {
                "status": "warning",
                "message": "Scheduler already running",
                "jobs": self.scheduler.get_jobs_status(),
            }
        self.scheduler.start()
        return {
            "status": "success",
            "message": "Scheduler started",
            "jobs": self.scheduler.get_jobs_status(),
        }

    def stop(self) -> Dict[str, Any]:
        """POST /scheduler/stop"""
        if not self.scheduler.is_running():
            return {
                "status": "warning",
                "message": "Scheduler is not running",
            }
        self.scheduler.stop()
        return {
            "status": "success",
            "message": "Scheduler stopped",
        }

    def run_job(self, job_id: str) -> Dict[str, Any]:
        """POST /scheduler/jobs/{job_id}/run"""
        if job_id not in self.scheduler.valid_job_ids:
            return {
                "status": "error",
                "message": f"Invalid job ID: '{job_id}'. Valid: {sorted(self.scheduler.valid_job_ids)}",
                "job_id": job_id,
            }
        if not self.scheduler.is_running():
            return {
                "status": "error",
                "message": "Scheduler is not running. Start it first.",
                "job_id": job_id,
            }

        success = self.scheduler.run_job_now(job_id)
        if not success:
            return {
                "status": "error",
                "message": f"Job '{job_id}' not found",
                "job_id": job_id,
            }

        return {
            "status": "success",
            "message": f"Job '{job_id}' scheduled for immediate execution",
            "job_id": job_id,
        }

    def set_interval(self, job_id: str, request: IntervalUpdateRequest) -> Dict[str, Any]:
        """PUT /scheduler/jobs/{job_id}/interval"""
        if job_id not in self.scheduler.valid_job_ids:
            return {
                "status": "error",
                "message": f"Invalid job ID: '{job_id}'. Valid: {sorted(self.scheduler.valid_job_ids)}",
                "job_id": job_id,
                "interval": "",
            }

        if not self.scheduler.is_running():
            return {
                "status": "error",
                "message": "Scheduler is not running. Start it first.",
                "job_id": job_id,
                "interval": "",
            }

        try:
            self.scheduler.set_job_interval(job_id, hours=request.hours, minutes=request.minutes)
        except ValueError as e:
            return {
                "status": "error",
                "message": str(e),
                "job_id": job_id,
                "interval": "",
            }

        interval_str = f"{request.hours}h {request.minutes}m"
        return {
            "status": "success",
            "message": f"Interval for {job_id} changed to {interval_str}",
            "job_id": job_id,
            "interval": interval_str,
        }

    def list_jobs(self) -> Dict[str, Any]:
        """GET /scheduler/jobs"""
        jobs_status = self.scheduler.get_jobs_status()
        return {
            "scheduler_running": self.scheduler.is_running(),
            "jobs": jobs_status,
            "valid_job_ids": sorted(self.scheduler.valid_job_ids),
            "total": len(jobs_status),
        }
