"""Meeting service: aggregates internal meetings + mirrored Zoom/Calendar events."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Meeting, User


async def list_between(db: AsyncSession, user: User, start: datetime, end: datetime) -> list[dict]:
    # In production also UNION calendar_events + zoom-mirrored meetings for this user.
    q = select(Meeting).where(
        and_(Meeting.starts_at >= start, Meeting.starts_at < end)
    ).order_by(Meeting.starts_at.asc())
    rows = (await db.execute(q)).scalars().all()
    return [
        {"id": str(m.id), "title": m.title, "source": m.source,
         "starts_at": m.starts_at.strftime("%I:%M %p"), "join_url": m.join_url}
        for m in rows
    ]


async def list_for_user(db: AsyncSession, user: User, range_: str = "week") -> dict:
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=7 if range_ == "week" else 1)
    return {"items": await list_between(db, user, now, end)}


async def next_for_user(db: AsyncSession, user: User) -> dict:
    now = datetime.now(timezone.utc)
    q = select(Meeting).where(Meeting.starts_at >= now).order_by(Meeting.starts_at.asc()).limit(1)
    m = (await db.execute(q)).scalar_one_or_none()
    if not m:
        return {"next": None}
    return {"next": {"title": m.title, "starts_at": m.starts_at.isoformat(),
                     "join_url": m.join_url, "source": m.source}}
