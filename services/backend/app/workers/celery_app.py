"""Celery app + beat schedule. Durable scheduler for prod (replaces APScheduler)."""
from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "waint",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
    task_routes={
        "app.workers.tasks.fire_due_reminders": {"queue": "reminders"},
        "app.workers.tasks.sync_jira": {"queue": "sync"},
        "app.workers.tasks.send_broadcast": {"queue": "broadcast"},
    },
    beat_schedule={
        "fire-due-reminders": {
            "task": "app.workers.tasks.fire_due_reminders",
            "schedule": 30.0,  # every 30s scan the partial index
        },
        "sync-jira": {
            "task": "app.workers.tasks.sync_jira",
            "schedule": 600.0,  # every 10 min
        },
        "sweep-escalations": {
            "task": "app.workers.tasks.sweep_escalations",
            "schedule": crontab(minute="*/15"),
        },
        "morning-digest": {
            "task": "app.workers.tasks.send_morning_digests",
            "schedule": crontab(hour=3, minute=30),  # 09:00 IST in UTC
        },
    },
)
