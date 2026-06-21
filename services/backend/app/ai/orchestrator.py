"""AI Orchestrator: the core inbound-message pipeline.

detect intent -> route to a trusted tool -> fetch user-scoped data -> render reply.

Safety boundary: the LLM only ever emits a structured intent. All data access goes
through domain services that enforce RBAC for the *resolved* user. The model never
touches the database and its output is never executed.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.ollama_client import ollama
from app.ai.prompts import INTENT_SYSTEM, INTENT_USER, RENDER_SYSTEM, RENDER_USER
from app.core.config import settings
from app.models import User
from app.services import meeting_service, reminder_service, task_service

log = logging.getLogger("waint.ai")

# only these intents may trigger a write; each tool re-checks permissions itself
WRITE_INTENTS = {"create_task", "create_reminder"}


async def handle_inbound(db: AsyncSession, user: User, text: str, context: str = "") -> dict:
    started = datetime.now(timezone.utc)
    now_iso = started.isoformat()

    # ---- 1. intent detection ----
    try:
        intent_obj = await ollama.chat_json(
            model=settings.llm_intent_model,
            system=INTENT_SYSTEM.format(
                now_iso=now_iso, tz=user.timezone, today=started.date().isoformat()
            ),
            user=INTENT_USER.format(context=context or "(none)", text=text),
        )
    except Exception as exc:  # noqa: BLE001 — degrade gracefully, never drop the user
        log.warning("intent detection failed: %s", exc)
        intent_obj = {"intent": "unknown", "entities": {}, "confidence": 0.0}

    intent = intent_obj.get("intent", "unknown")
    entities = intent_obj.get("entities", {}) or {}
    confidence = float(intent_obj.get("confidence", 0))

    if confidence < 0.55 and intent not in ("help", "smalltalk"):
        return _finalize(intent, entities, "🤔 I didn't quite catch that. You can ask things like "
                         "*\"What do I have today?\"* or *\"Remind me in 1 hour to call Rajesh\"*.", started)

    # ---- 2/3/4. tool routing + user-scoped data fetch ----
    entities["_raw_text"] = text  # deterministic fallback for time/NL parsing in services
    data = await _route(db, user, intent, entities)

    # Writes + empty reads: answer deterministically so a small model can't
    # hallucinate items or garble exact times/dates.
    det = _deterministic_reply(intent, data, user)
    if det is not None:
        return _finalize(intent, entities, det, started)

    # ---- 5. response rendering (with deterministic fallback) ----
    try:
        reply = await ollama.chat_text(
            model=settings.llm_render_model,
            system=RENDER_SYSTEM.format(full_name=user.full_name, tz=user.timezone),
            user=RENDER_USER.format(intent=intent, data=json.dumps(data, default=str)),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("render failed, using template: %s", exc)
        reply = _template_fallback(intent, data)

    return _finalize(intent, entities, reply, started)


async def _route(db: AsyncSession, user: User, intent: str, entities: dict) -> dict:
    match intent:
        case "daily_schedule":
            return await task_service.get_daily_agenda(db, user)
        case "weekly_schedule":
            return await task_service.get_weekly_agenda(db, user)
        case "task_lookup":
            return await task_service.list_for_user(
                db, user, status=entities.get("status"),
                overdue=bool(entities.get("overdue")), priority=entities.get("priority"),
            )
        case "task_status":
            return await task_service.resolve_and_status(db, user, entities.get("task_ref", ""))
        case "create_task":
            return await task_service.create_from_ai(db, user, entities)  # perm-checked inside
        case "create_reminder":
            return await reminder_service.create_nl(db, user, entities)   # own-only inside
        case "meeting_lookup":
            return await meeting_service.list_for_user(db, user, entities.get("range", "week"))
        case "next_meeting":
            return await meeting_service.next_for_user(db, user)
        case "jira_lookup":
            from app.services import jira_service
            return await jira_service.list_for_user(db, user, entities)
        case "team_summary":
            from app.services import report_service
            return await report_service.team_summary(db, user)  # manager+ enforced inside
        case "help":
            return {"help": True}
        case _:
            return {}


def _fmt_local(iso: str, tz: str) -> str:
    from zoneinfo import ZoneInfo
    dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(ZoneInfo(tz))
    return dt.strftime("%a %d %b, %I:%M %p")


def _deterministic_reply(intent: str, data: dict, user) -> str | None:
    """Reply deterministically for writes and empty reads (no LLM, no hallucination)."""
    # --- writes ---
    if intent == "create_reminder":
        if data.get("created"):
            when = _fmt_local(data["fire_at"], user.timezone)
            tail = " (repeating)" if data.get("recurring") else ""
            return f"👍 Reminder set for *{when}*{tail}: {data['body']}"
        if data.get("error") == "could_not_parse_time":
            return "I couldn't work out *when* to remind you. Try e.g. \"in 2 hours\" or \"tomorrow 9am\"."
        if data.get("error"):
            return "I couldn't create that reminder — please rephrase."
    if intent == "create_task":
        if data.get("created"):
            due = f" (due {_fmt_local(data['due_at'], user.timezone)})" if data.get("due_at") else ""
            return f"✅ Task created: *{data['title']}*{due}"
        if data.get("error"):
            return "I couldn't create that task — what's the title?"
    # --- empty reads ---
    if intent == "next_meeting" and not data.get("next"):
        return "You have no upcoming meetings on your calendar. 🎉"
    if intent in ("daily_schedule", "weekly_schedule") and not data.get("items"):
        return "You're all clear — nothing scheduled. 🎉"
    if intent in ("task_lookup", "meeting_lookup") and not data.get("items"):
        return "Nothing matching found. 🎉"
    if intent == "jira_lookup" and not data.get("count"):
        return "No Jira issues assigned to you right now."
    return None


def _template_fallback(intent: str, data: dict) -> str:
    """Deterministic reply if the LLM render call fails — user always gets something."""
    if intent in ("daily_schedule", "weekly_schedule"):
        items = data.get("items", [])
        if not items:
            return "You're all clear — nothing scheduled. 🎉"
        lines = [f"• {i.get('time', '')} {i.get('title', '')}".strip() for i in items]
        return "*Your agenda*\n" + "\n".join(lines)
    if intent == "create_reminder":
        return f"👍 Reminder set: {data.get('body', '')} at {data.get('fire_at', '')}."
    return "Done. Ask me about your tasks, meetings or reminders anytime."


def _finalize(intent: str, entities: dict, reply: str, started: datetime) -> dict:
    latency = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    return {"reply": reply, "intent": intent, "entities": entities, "latency_ms": latency}
