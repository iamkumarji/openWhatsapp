"""Reads the locally-mirrored Jira issues (fast, offline, user-scoped)."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


async def list_for_user(db: AsyncSession, user: User, entities: dict | None = None) -> dict:
    entities = entities or {}
    rows = (
        await db.execute(
            text(
                """
                SELECT issue_key, summary, status, status_category, priority, url, due_date
                FROM jira_issues
                WHERE assignee_id = :uid
                  AND (:cat IS NULL OR status_category = :cat)
                ORDER BY due_date NULLS LAST, jira_updated_at DESC
                LIMIT 25
                """
            ),
            {"uid": str(user.id), "cat": entities.get("status_category")},
        )
    ).mappings().all()
    return {
        "count": len(rows),
        "items": [dict(r) for r in rows],
    }
