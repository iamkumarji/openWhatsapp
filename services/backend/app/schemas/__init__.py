"""Pydantic request/response schemas (input validation = first line of defense)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class WAInbound(BaseModel):
    wa_id: str
    message_id: str | None = None
    text: str = Field(min_length=1, max_length=4000)
    timestamp: int | None = None


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    priority: str = "medium"
    due_at: datetime | None = None
    assignee_ids: list[str] = []
    rrule: str | None = None
    escalate_after_hours: int | None = None


class TaskOut(BaseModel):
    id: str
    title: str
    status: str
    priority: str
    due_at: datetime | None = None


class ReminderCreate(BaseModel):
    body: str = Field(min_length=1, max_length=1000)
    fire_at: datetime | None = None
    natural_time: str | None = None
    kind: str = "one_off"
    recurrence: str | None = None


class BroadcastCreate(BaseModel):
    audience: dict
    body: str = Field(min_length=1, max_length=4000)
    scheduled_at: datetime | None = None
