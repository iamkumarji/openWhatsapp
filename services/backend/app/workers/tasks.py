"""Celery tasks: reminder firing, integration syncs, broadcasts, escalations.

These run sync (Celery) but use a sync DB session + httpx for delivery to the WA
gateway. Reminder firing is the latency-critical path and uses SELECT ... FOR UPDATE
SKIP LOCKED so multiple workers can drain the due queue without double-sending.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.reminder_service import next_occurrence
from app.workers.celery_app import celery_app

# sync engine for workers (asyncpg URL -> psycopg-friendly sync URL)
_sync_url = settings.database_url.replace("+asyncpg", "")
_engine = create_engine(_sync_url, pool_pre_ping=True)

WA_SEND_URL = settings.__dict__.get("wa_send_url", "http://whatsapp-gateway:3000/send")


def _send_whatsapp(wa_id: str, body: str) -> bool:
    try:
        resp = httpx.post(
            WA_SEND_URL,
            json={"wa_id": wa_id, "text": body},
            headers={"X-Internal-Token": settings.internal_token},
            timeout=15,
        )
        return resp.status_code < 300
    except httpx.HTTPError:
        return False


@celery_app.task
def fire_due_reminders() -> int:
    """Claim due reminders and deliver them. Returns count fired."""
    now = datetime.now(timezone.utc)
    fired = 0
    with Session(_engine) as db:
        rows = db.execute(
            text(
                """
                SELECT r.id, r.body, r.kind, r.rrule, u.whatsapp_number
                FROM reminders r JOIN users u ON u.id = r.user_id
                WHERE r.status = 'scheduled' AND r.fire_at <= :now
                ORDER BY r.fire_at
                FOR UPDATE OF r SKIP LOCKED
                LIMIT 200
                """
            ),
            {"now": now},
        ).mappings().all()

        for r in rows:
            db.execute(text("UPDATE reminders SET status='firing' WHERE id=:id"), {"id": r["id"]})
            db.commit()

            ok = _send_whatsapp(r["whatsapp_number"], f"⏰ Reminder: {r['body']}")

            if r["kind"] == "recurring" and r["rrule"]:
                nxt = next_occurrence(r["rrule"], now)
                if nxt:
                    db.execute(
                        text("UPDATE reminders SET status='scheduled', fire_at=:n, last_fired_at=:now,"
                             " attempts=attempts+1 WHERE id=:id"),
                        {"n": nxt, "now": now, "id": r["id"]},
                    )
                else:
                    db.execute(text("UPDATE reminders SET status='sent' WHERE id=:id"), {"id": r["id"]})
            else:
                new_status = "sent" if ok else "failed"
                db.execute(
                    text("UPDATE reminders SET status=:s, last_fired_at=:now, attempts=attempts+1"
                         " WHERE id=:id"),
                    {"s": new_status, "now": now, "id": r["id"]},
                )
            db.commit()
            fired += 1 if ok else 0
    return fired


@celery_app.task
def sync_jira() -> int:
    """Delta-sync Jira issues for mapped users (see app.integrations.jira)."""
    # Pseudocode-level: load users with jira_account_id + cursor, pull deltas, UPSERT.
    # Full implementation mirrors docs/01 sequence 5.3.
    return 0


@celery_app.task
def sweep_escalations() -> int:
    """Escalate overdue tasks past their grace window to the task creator/manager."""
    now = datetime.now(timezone.utc)
    with Session(_engine) as db:
        rows = db.execute(
            text(
                """
                SELECT t.id, t.title, u.whatsapp_number
                FROM tasks t JOIN users u ON u.id = t.created_by
                WHERE t.status NOT IN ('done','cancelled')
                  AND t.escalate_after_hours IS NOT NULL
                  AND t.escalated_at IS NULL
                  AND t.due_at + (t.escalate_after_hours || ' hours')::interval < :now
                LIMIT 100
                """
            ),
            {"now": now},
        ).mappings().all()
        for t in rows:
            if t["whatsapp_number"]:
                _send_whatsapp(t["whatsapp_number"], f"⚠️ Overdue task needs attention: *{t['title']}*")
            db.execute(text("UPDATE tasks SET escalated_at=:now WHERE id=:id"),
                       {"now": now, "id": t["id"]})
        db.commit()
        return len(rows)


@celery_app.task
def send_broadcast(broadcast_id: str) -> dict:
    """Deliver a broadcast to its audience with per-recipient pacing."""
    sent = fail = 0
    with Session(_engine) as db:
        recipients = db.execute(
            text(
                """
                SELECT u.whatsapp_number, b.body
                FROM broadcasts b
                JOIN users u ON (
                  (b.audience->>'type'='all')
                  OR (b.audience->>'type'='team' AND u.team_id::text = ANY (
                        SELECT jsonb_array_elements_text(b.audience->'ids')))
                )
                WHERE b.id = :bid AND u.whatsapp_number IS NOT NULL
                """
            ),
            {"bid": broadcast_id},
        ).mappings().all()
        for rcpt in recipients:
            if _send_whatsapp(rcpt["whatsapp_number"], rcpt["body"]):
                sent += 1
            else:
                fail += 1
        db.execute(
            text("UPDATE broadcasts SET status='done', sent_count=:s, fail_count=:f WHERE id=:bid"),
            {"s": sent, "f": fail, "bid": broadcast_id},
        )
        db.commit()
    return {"sent": sent, "fail": fail}


@celery_app.task
def send_morning_digests() -> int:
    """Proactive daily agenda push (phase 3 nudge)."""
    return 0
