"""Task domain service. The only layer (besides other services) that touches task tables.

All functions are user-scoped: an employee only ever sees/affects their own or
assigned tasks; managers/admins are widened via RBAC checks at the route/tool layer.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task, TaskAssignment, TaskPriority, TaskStatus, User


async def _tasks_for(db: AsyncSession, user: User):
    """Base query: tasks created by or assigned to the user."""
    return (
        select(Task)
        .outerjoin(TaskAssignment, TaskAssignment.task_id == Task.id)
        .where(
            or_(Task.created_by == user.id, TaskAssignment.assignee_id == user.id),
            Task.status != TaskStatus.cancelled,
        )
        .distinct()
    )


async def list_for_user(
    db: AsyncSession,
    user: User,
    status: str | None = None,
    priority: str | None = None,
    overdue: bool = False,
    limit: int = 50,
) -> dict:
    q = await _tasks_for(db, user)
    if status:
        q = q.where(Task.status == TaskStatus(status))
    if priority:
        q = q.where(Task.priority == TaskPriority(priority))
    if overdue:
        q = q.where(
            and_(Task.due_at < datetime.now(timezone.utc), Task.status != TaskStatus.done)
        )
    q = q.order_by(Task.due_at.asc().nullslast()).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return {
        "count": len(rows),
        "items": [
            {
                "id": str(t.id),
                "title": t.title,
                "status": t.status.value,
                "priority": t.priority.value,
                "due_at": t.due_at.isoformat() if t.due_at else None,
            }
            for t in rows
        ],
    }


async def get_daily_agenda(db: AsyncSession, user: User) -> dict:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    q = (await _tasks_for(db, user)).where(
        and_(Task.due_at >= start, Task.due_at < end)
    ).order_by(Task.due_at.asc())
    tasks = (await db.execute(q)).scalars().all()

    from app.services import meeting_service

    meetings = await meeting_service.list_between(db, user, start, end)
    items = [
        {"time": t.due_at.strftime("%I:%M %p") if t.due_at else "", "title": f"📋 {t.title}",
         "kind": "task", "priority": t.priority.value}
        for t in tasks
    ] + [
        {"time": m["starts_at"], "title": f"📅 {m['title']}", "kind": "meeting"}
        for m in meetings
    ]
    return {"date": start.date().isoformat(), "items": items}


async def get_weekly_agenda(db: AsyncSession, user: User) -> dict:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)
    q = (await _tasks_for(db, user)).where(
        and_(Task.due_at >= start, Task.due_at < end)
    ).order_by(Task.due_at.asc())
    tasks = (await db.execute(q)).scalars().all()
    return {
        "range": "week",
        "items": [
            {"time": t.due_at.isoformat() if t.due_at else "", "title": t.title,
             "status": t.status.value} for t in tasks
        ],
    }


async def resolve_and_status(db: AsyncSession, user: User, task_ref: str) -> dict:
    if not task_ref:
        return {"error": "no_reference"}
    q = (await _tasks_for(db, user)).where(Task.title.ilike(f"%{task_ref}%")).limit(5)
    rows = (await db.execute(q)).scalars().all()
    if not rows:
        return {"matched": 0}
    return {
        "matched": len(rows),
        "items": [{"title": t.title, "status": t.status.value,
                   "due_at": t.due_at.isoformat() if t.due_at else None} for t in rows],
    }


async def create_from_ai(db: AsyncSession, user: User, entities: dict) -> dict:
    """Create a task from AI-extracted entities. Self-assigned by default.

    Permission note: creating a task for *oneself* requires task.create (all roles
    have it). Assigning to *others* requires task.assign and is rejected here for
    safety — assignment-to-others goes through the authenticated REST route where
    the manager's RBAC scope is checked.
    """
    title = (entities.get("title") or "").strip()
    if not title:
        return {"error": "missing_title"}
    due = _parse_dt(entities.get("due"))
    task = Task(
        title=title,
        description=entities.get("description"),
        priority=TaskPriority(entities.get("priority", "medium")),
        created_by=user.id,
        team_id=user.team_id,
        due_at=due,
    )
    db.add(task)
    await db.flush()
    db.add(TaskAssignment(task_id=task.id, assignee_id=user.id, assigned_by=user.id))
    await db.commit()
    return {"created": True, "id": str(task.id), "title": title,
            "due_at": due.isoformat() if due else None}


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
