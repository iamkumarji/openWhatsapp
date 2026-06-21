"""Reminder engine service: NL time parsing, one-off + recurring scheduling.

Firing/delivery is done by the Celery worker (app.workers.tasks.fire_due_reminders),
which scans the `idx_reminders_due` partial index. This service only creates/edits.
"""
from __future__ import annotations

from datetime import datetime, timezone

import dateparser
from dateutil.rrule import rrulestr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Reminder, ReminderKind, ReminderStatus, User


def parse_natural_time(text: str, tz: str) -> datetime | None:
    """Parse 'in 1 hour', 'tomorrow at 10am', 'next Monday 9am' -> aware UTC datetime."""
    dt = dateparser.parse(
        text,
        settings={
            "TIMEZONE": tz,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DATES_FROM": "future",
        },
    )
    if dt is None:
        return None
    return dt.astimezone(timezone.utc)


async def create_nl(db: AsyncSession, user: User, entities: dict) -> dict:
    """Create a reminder from AI-extracted entities (always for the requesting user)."""
    body = (entities.get("body") or "").strip()
    if not body:
        return {"error": "missing_body"}

    when = entities.get("when")
    fire_at = _to_dt(when) if when else parse_natural_time(entities.get("when_text", ""), user.timezone)
    if fire_at is None:
        return {"error": "could_not_parse_time"}

    recurrence = entities.get("recurrence")
    kind = ReminderKind.recurring if recurrence else ReminderKind.one_off

    reminder = Reminder(
        user_id=user.id,
        created_by=user.id,
        body=body,
        kind=kind,
        rrule=recurrence,
        fire_at=fire_at,
        status=ReminderStatus.scheduled,
        channel="whatsapp",
    )
    db.add(reminder)
    await db.commit()
    return {"created": True, "id": str(reminder.id), "body": body,
            "fire_at": fire_at.isoformat(), "recurring": bool(recurrence)}


async def list_for_user(db: AsyncSession, user: User, status: str = "scheduled") -> dict:
    q = select(Reminder).where(
        Reminder.user_id == user.id, Reminder.status == ReminderStatus(status)
    ).order_by(Reminder.fire_at.asc())
    rows = (await db.execute(q)).scalars().all()
    return {"items": [{"id": str(r.id), "body": r.body, "fire_at": r.fire_at.isoformat(),
                       "recurring": r.kind == ReminderKind.recurring} for r in rows]}


def next_occurrence(rrule: str, after: datetime) -> datetime | None:
    """Compute the next firing for a recurring reminder after `after`."""
    try:
        rule = rrulestr(rrule, dtstart=after)
        return rule.after(after)
    except (ValueError, TypeError):
        return None


def _to_dt(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
