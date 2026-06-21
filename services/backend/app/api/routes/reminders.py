"""Reminder REST endpoints."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentPrincipal
from app.db.session import get_db
from app.models import Reminder, ReminderKind, ReminderStatus, User
from app.schemas import ReminderCreate
from app.services import reminder_service

router = APIRouter(prefix="/reminders", tags=["reminders"])


@router.post("", status_code=201)
async def create_reminder(
    body: ReminderCreate,
    principal: CurrentPrincipal,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    principal.require("reminder.manage.own")
    user = await db.get(User, uuid.UUID(principal.user_id))

    fire_at = body.fire_at
    if fire_at is None and body.natural_time:
        fire_at = reminder_service.parse_natural_time(body.natural_time, user.timezone)
    if fire_at is None:
        raise HTTPException(422, "could_not_determine_time")

    reminder = Reminder(
        user_id=user.id, created_by=user.id, body=body.body,
        kind=ReminderKind(body.kind), rrule=body.recurrence,
        fire_at=fire_at, status=ReminderStatus.scheduled,
    )
    db.add(reminder)
    await db.commit()
    return {"id": str(reminder.id), "fire_at": fire_at.isoformat()}


@router.get("")
async def list_reminders(
    principal: CurrentPrincipal,
    db: Annotated[AsyncSession, Depends(get_db)],
    status: str = "scheduled",
):
    user = await db.get(User, uuid.UUID(principal.user_id))
    return await reminder_service.list_for_user(db, user, status=status)


@router.delete("/{reminder_id}")
async def cancel_reminder(
    reminder_id: uuid.UUID,
    principal: CurrentPrincipal,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    reminder = await db.get(Reminder, reminder_id)
    if reminder is None or str(reminder.user_id) != principal.user_id:
        raise HTTPException(404, "reminder_not_found")  # also blocks editing others'
    reminder.status = ReminderStatus.cancelled
    await db.commit()
    return {"ok": True}
