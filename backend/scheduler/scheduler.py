"""
Task Scheduler (F43-F47)
APScheduler-based cron job manager for scans, exports, and price checks.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.database.db import session_scope
from backend.database.models import ScheduledJob

logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None
_app_ref: Any = None   # FastAPI app reference for triggering API calls internally


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


def start_scheduler(app=None):
    global _app_ref
    _app_ref = app
    sched = get_scheduler()
    if not sched.running:
        sched.start()
        logger.info("Scheduler started")
        _reload_jobs_from_db()


def stop_scheduler():
    sched = get_scheduler()
    if sched.running:
        sched.shutdown(wait=False)
        logger.info("Scheduler stopped")


def _reload_jobs_from_db():
    """Load all active scheduled jobs from DB and register them."""
    with session_scope() as db:
        jobs = db.query(ScheduledJob).filter(ScheduledJob.is_active == True).all()
        for job in jobs:
            try:
                _register_job(job)
            except Exception as exc:
                logger.warning(f"Failed to register job {job.name}: {exc}")


def _register_job(job: ScheduledJob):
    sched = get_scheduler()
    job_id = f"job_{job.id}"

    # Remove existing job with same ID (for updates)
    try:
        sched.remove_job(job_id)
    except Exception:
        pass

    trigger = _build_trigger(job.schedule_type, job.schedule_value)
    if trigger is None:
        logger.warning(f"Cannot build trigger for job {job.name}")
        return

    sched.add_job(
        _execute_job,
        trigger=trigger,
        id=job_id,
        name=job.name,
        args=[job.id],
        replace_existing=True,
        misfire_grace_time=300,
    )
    logger.info(f"Registered scheduled job: {job.name} ({job.schedule_type})")


def _build_trigger(schedule_type: str, schedule_value: str):
    try:
        if schedule_type == "cron":
            # schedule_value is a cron expression: "0 9 * * 1" = Monday 9am
            parts = schedule_value.split()
            if len(parts) == 5:
                minute, hour, day, month, day_of_week = parts
                return CronTrigger(
                    minute=minute, hour=hour, day=day,
                    month=month, day_of_week=day_of_week
                )
        elif schedule_type == "daily":
            # schedule_value = "09:00" (HH:MM UTC)
            h, m = schedule_value.split(":")
            return CronTrigger(hour=int(h), minute=int(m))
        elif schedule_type == "weekly":
            # schedule_value = "mon:09:00"
            parts = schedule_value.split(":")
            return CronTrigger(day_of_week=parts[0], hour=int(parts[1]), minute=int(parts[2]))
        elif schedule_type == "monthly":
            # schedule_value = "1:09:00" (day:HH:MM)
            parts = schedule_value.split(":")
            return CronTrigger(day=int(parts[0]), hour=int(parts[1]), minute=int(parts[2]))
        elif schedule_type == "one_time":
            run_at = datetime.fromisoformat(schedule_value)
            return DateTrigger(run_date=run_at)
        elif schedule_type == "interval_minutes":
            return IntervalTrigger(minutes=int(schedule_value))
    except Exception as exc:
        logger.error(f"Trigger build error for {schedule_type!r} / {schedule_value!r}: {exc}")
    return None


async def _execute_job(job_id: int):
    """Execute a scheduled job."""
    with session_scope() as db:
        job = db.get(ScheduledJob, job_id)
        if not job or not job.is_active:
            return

        job.last_run_at = datetime.utcnow()
        job.run_count = (job.run_count or 0) + 1
        job_type = job.job_type
        target = job.target
        config_data = {}
        if job.config_json:
            try:
                config_data = json.loads(job.config_json)
            except Exception:
                pass

    logger.info(f"Executing scheduled job: {job_id} type={job_type}")

    try:
        if job_type == "source_scan":
            from backend.scrapers.source_scraper import run_source_scan
            await run_source_scan(site_filter=target or None)

        elif job_type == "competitor_scan":
            from backend.competitor.scraper import run_competitor_scan
            competitor_ids = json.loads(target) if target and target.startswith("[") else []
            session_name = f"Scheduled {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
            for cid in competitor_ids:
                await run_competitor_scan(
                    competitor_id=cid,
                    session_name=session_name,
                    criteria_dict=config_data.get("criteria"),
                )

        elif job_type == "price_check":
            from backend.competitor.scraper import run_competitor_scan
            from backend.database.db import session_scope
            with session_scope() as db:
                from backend.database.models import Competitor
                competitors = db.query(Competitor).filter(Competitor.is_active == True).all()
                comp_ids = [c.id for c in competitors]
            session_name = f"Price Check {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
            for cid in comp_ids:
                await run_competitor_scan(competitor_id=cid, session_name=session_name)

        elif job_type == "export":
            from backend.export.exporter import export_products
            fmt = config_data.get("format", "xlsx")
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, lambda: export_products(fmt=fmt, triggered_by="scheduler")
            )

        elif job_type == "dedup":
            from backend.database.db import session_scope
            from backend.dedup.engine import DeduplicationEngine
            def _run_dedup():
                with session_scope() as db:
                    DeduplicationEngine().run(db)
            await asyncio.get_running_loop().run_in_executor(None, _run_dedup)

        with session_scope() as db:
            job = db.get(ScheduledJob, job_id)
            if job:
                job.last_status = "completed"

    except Exception as exc:
        logger.exception(f"Scheduled job {job_id} failed: {exc}")
        with session_scope() as db:
            job = db.get(ScheduledJob, job_id)
            if job:
                job.last_status = f"failed: {str(exc)[:200]}"

    # Update next_run_at
    sched = get_scheduler()
    apjob = sched.get_job(f"job_{job_id}")
    if apjob and apjob.next_run_time:
        with session_scope() as db:
            job = db.get(ScheduledJob, job_id)
            if job:
                job.next_run_at = apjob.next_run_time.replace(tzinfo=None)


def create_job(
    name: str,
    job_type: str,
    target: Optional[str],
    schedule_type: str,
    schedule_value: str,
    config_json: Optional[str] = None,
) -> dict:
    """Create and register a new scheduled job."""
    with session_scope() as db:
        existing = db.query(ScheduledJob).filter(ScheduledJob.name == name).first()
        if existing:
            raise ValueError(f"Job named '{name}' already exists")

        job = ScheduledJob(
            name=name,
            job_type=job_type,
            target=target,
            schedule_type=schedule_type,
            schedule_value=schedule_value,
            is_active=True,
            config_json=config_json,
        )
        db.add(job)
        db.flush()
        job_id = job.id

    with session_scope() as db:
        job = db.get(ScheduledJob, job_id)
        _register_job(job)

    # Compute next run
    sched = get_scheduler()
    apjob = sched.get_job(f"job_{job_id}")
    next_run = apjob.next_run_time.isoformat() if apjob and apjob.next_run_time else None

    with session_scope() as db:
        job = db.get(ScheduledJob, job_id)
        if job and next_run:
            try:
                job.next_run_at = datetime.fromisoformat(next_run.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                pass

    return {"id": job_id, "name": name, "next_run": next_run}


def delete_job(job_id: int):
    """Remove a scheduled job."""
    sched = get_scheduler()
    try:
        sched.remove_job(f"job_{job_id}")
    except Exception:
        pass
    with session_scope() as db:
        job = db.get(ScheduledJob, job_id)
        if job:
            job.is_active = False


def toggle_job(job_id: int, active: bool):
    with session_scope() as db:
        job = db.get(ScheduledJob, job_id)
        if not job:
            raise ValueError("Job not found")
        job.is_active = active
        if active:
            _register_job(job)
        else:
            try:
                get_scheduler().remove_job(f"job_{job_id}")
            except Exception:
                pass


def run_job_now(job_id: int):
    """Trigger a job to run immediately (outside its schedule)."""
    sched = get_scheduler()
    sched.add_job(
        _execute_job,
        trigger=DateTrigger(run_date=datetime.utcnow()),
        args=[job_id],
        id=f"job_{job_id}_manual_{datetime.utcnow().timestamp()}",
        replace_existing=False,
    )


def list_jobs() -> list:
    with session_scope() as db:
        jobs = db.query(ScheduledJob).order_by(ScheduledJob.name).all()
        result = []
        for j in jobs:
            apjob = get_scheduler().get_job(f"job_{j.id}")
            next_run = None
            if apjob and apjob.next_run_time:
                next_run = apjob.next_run_time.isoformat()
            result.append({
                "id": j.id,
                "name": j.name,
                "job_type": j.job_type,
                "target": j.target,
                "schedule_type": j.schedule_type,
                "schedule_value": j.schedule_value,
                "is_active": j.is_active,
                "last_run_at": j.last_run_at.isoformat() if j.last_run_at else None,
                "next_run_at": next_run or (j.next_run_at.isoformat() if j.next_run_at else None),
                "last_status": j.last_status,
                "run_count": j.run_count or 0,
            })
        return result
