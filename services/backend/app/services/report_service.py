"""Team analytics / reports. Manager+ only — enforced by the caller's RBAC."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


async def team_summary(db: AsyncSession, user: User) -> dict:
    """Completion %, overdue and throughput per team member.

    Authorization: routes pass only after principal.require('report.view.team').
    Managers are scoped to their own team_id.
    """
    rows = (
        await db.execute(
            text(
                """
                SELECT u.full_name,
                       count(*) FILTER (WHERE t.status='done')                          AS done,
                       count(*) FILTER (WHERE t.status<>'done' AND t.status<>'cancelled') AS open,
                       count(*) FILTER (WHERE t.due_at < now() AND t.status<>'done')     AS overdue
                FROM users u
                LEFT JOIN task_assignments ta ON ta.assignee_id = u.id
                LEFT JOIN tasks t ON t.id = ta.task_id
                WHERE u.team_id = :team
                GROUP BY u.full_name
                ORDER BY overdue DESC
                """
            ),
            {"team": user.team_id},
        )
    ).mappings().all()
    return {"team_id": str(user.team_id), "members": [dict(r) for r in rows]}
