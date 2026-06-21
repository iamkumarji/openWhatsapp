"""User resolution: WhatsApp identity binding + principal/permission resolution."""
from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Principal
from app.db.session import SessionLocal
from app.models import User


async def get_by_whatsapp(db: AsyncSession, wa_id: str) -> User | None:
    q = select(User).where(User.whatsapp_number == wa_id)
    return (await db.execute(q)).scalar_one_or_none()


async def resolve_principal_by_keycloak_id(keycloak_id: str) -> Principal | None:
    """Resolve a token subject to a local user + effective permission set."""
    async with SessionLocal() as db:
        row = (
            await db.execute(
                text(
                    """
                    SELECT u.id, u.email, u.team_id, r.name AS role,
                           array_agg(p.code) AS perms
                    FROM users u
                    JOIN roles r ON r.id = u.role_id
                    LEFT JOIN role_permissions rp ON rp.role_id = r.id
                    LEFT JOIN permissions p ON p.id = rp.permission_id
                    WHERE u.keycloak_id = :kc AND u.status = 'active'
                    GROUP BY u.id, u.email, u.team_id, r.name
                    """
                ),
                {"kc": keycloak_id},
            )
        ).first()
    if row is None:
        return None
    perms = {p for p in (row.perms or []) if p}
    return Principal(
        user_id=str(row.id), email=row.email, role=row.role,
        permissions=perms, team_id=str(row.team_id) if row.team_id else None,
    )
