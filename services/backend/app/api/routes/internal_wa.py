"""Internal endpoint: WhatsApp gateway -> backend -> AI pipeline -> reply.

Not exposed publicly (Nginx blocks /api/v1/internal/*); guarded by X-Internal-Token.
"""
from __future__ import annotations

import json
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import handle_inbound
from app.core.config import settings
from app.core.security import require_internal_token
from app.db.session import get_db
from app.models import MessageLog
from app.schemas import WAInbound
from app.services.user_service import get_by_whatsapp

router = APIRouter(prefix="/internal", tags=["internal"])
redis = aioredis.from_url(settings.redis_url, decode_responses=True)

CONTEXT_TURNS = 6


@router.post("/wa/inbound", dependencies=[Depends(require_internal_token)])
async def wa_inbound(payload: WAInbound, db: Annotated[AsyncSession, Depends(get_db)]):
    user = await get_by_whatsapp(db, payload.wa_id)

    # unknown number -> enrollment prompt, no data access
    if user is None:
        return {
            "reply": "👋 I don't recognize this number yet. Ask your admin for a one-time "
                     "enrollment code, then reply: *enroll <code>*.",
            "intent": "enroll_required",
        }

    # load short conversation context from Redis
    ctx_key = f"wa:ctx:{user.id}"
    raw = await redis.lrange(ctx_key, 0, CONTEXT_TURNS - 1)
    context = "\n".join(reversed(raw))

    result = await handle_inbound(db, user, payload.text, context=context)

    # log inbound + outbound
    db.add(MessageLog(user_id=user.id, wa_id=payload.wa_id, direction="inbound",
                      body=payload.text, intent=result["intent"],
                      entities=result["entities"], latency_ms=result["latency_ms"]))
    db.add(MessageLog(user_id=user.id, wa_id=payload.wa_id, direction="outbound",
                      body=result["reply"], model=settings.llm_render_model))
    await db.commit()

    # update rolling context
    await redis.lpush(ctx_key, f"user: {payload.text}", f"assistant: {result['reply']}")
    await redis.ltrim(ctx_key, 0, CONTEXT_TURNS * 2)
    await redis.expire(ctx_key, 3600)

    return {"reply": result["reply"], "intent": result["intent"]}
