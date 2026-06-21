# 04 — AI Orchestration (Intent, Prompts, Tools, RAG)

All inference is **local via Ollama**. No external AI APIs.

- **Default model:** `qwen2.5:7b-instruct` (strong at structured/JSON output, multilingual incl. Hinglish).
- **Fallback / larger:** `llama3.1:8b-instruct`.
- **Embeddings (RAG):** `nomic-embed-text` (768-dim → matches `kb_chunks.embedding`).

## 1. Pipeline

```
inbound text
   │
   ▼
[1] Pre-process  → trim, language hint, load Redis conversation context (last N turns)
   │
   ▼
[2] Intent detection (LLM, JSON mode)  → {intent, entities, confidence}
   │
   ├─ confidence < 0.55 ─▶ clarify ("Did you mean your tasks or meetings?")
   ▼
[3] Tool routing  → map intent → domain service call(s) with validated entities
   │
   ▼
[4] Data fetch    → Task/Reminder/Meeting/Jira/Zoom/Calendar services
   │
   ▼
[5] Response render (LLM)  → concise, WhatsApp-formatted reply (user locale + tz)
   │
   ▼
[6] Persist context + message_logs, return reply
```

Why a **two-call** design (detect → render) instead of one free-form call: it keeps the LLM
off the database. The model only ever emits a structured intent; real data is fetched by
trusted code; the model then only *phrases* the answer. This is the core safety boundary.

## 2. Intent taxonomy

| Intent | Entities | Service |
|--------|----------|---------|
| `daily_schedule` | `date` | aggregate today (tasks+meetings+reminders) |
| `weekly_schedule` | `week_offset` | aggregate week |
| `task_lookup` | `status?, priority?, overdue?` | TaskService |
| `task_status` | `task_ref` | TaskService |
| `create_task` | `title, due, assignee?, priority?` | TaskService (perm-checked) |
| `create_reminder` | `body, when, recurrence?` | ReminderService |
| `meeting_lookup` | `range` | Meeting/Zoom/Calendar |
| `next_meeting` | — | Meeting aggregate |
| `jira_lookup` | `status_category?, sprint?` | JiraService |
| `team_summary` | `team?, range` | Reports (manager+) |
| `focus_suggestion` | — | TaskService + LLM ranking |
| `smalltalk` / `help` / `unknown` | — | static/help text |

## 3. Prompt templates

### 3.1 Intent detection (system)

```text
You are the intent classifier for WAINT, a WhatsApp work assistant.
Return ONLY a JSON object, no prose, matching this schema:
{
  "intent": one of [daily_schedule, weekly_schedule, task_lookup, task_status,
            create_task, create_reminder, meeting_lookup, next_meeting,
            jira_lookup, team_summary, focus_suggestion, help, smalltalk, unknown],
  "entities": { ... only keys relevant to the intent ... },
  "confidence": 0.0-1.0
}
Rules:
- Resolve relative time using NOW={now_iso} and TIMEZONE={tz}. Output absolute ISO-8601 (UTC) in entities when a time is implied.
- For reminders, extract entities.body (the action), entities.when (ISO-8601 UTC), entities.recurrence (RRULE or null).
- Never invent task IDs or names. If a referenced task is ambiguous, set intent=task_status and entities.task_ref to the literal text.
- The user may write in English, Hindi, or Hinglish.
Conversation context (most recent last):
{context}
User message: "{text}"
```

Few-shot examples are appended (3–5) to stabilize JSON output. Calls use Ollama
`format: "json"` and `temperature: 0.1`.

### 3.2 Response rendering (system)

```text
You are WAINT, a friendly, concise WhatsApp work assistant for {full_name}.
Compose a reply from the DATA below. Constraints:
- WhatsApp formatting only: *bold*, _italic_, bullet lines with "•". No markdown tables/headers.
- Keep it short and scannable. Use the user's timezone {tz} and 12-hour clock.
- Never fabricate items not present in DATA. If DATA is empty, say so cheerfully.
- End with at most one helpful follow-up suggestion.
INTENT: {intent}
DATA (JSON): {data}
```

### 3.3 Example rendered outputs

```
*Today — Sat, Jun 21*
• ⏰ 10:15 AM  Call Rajesh (reminder)
• 📋 2 tasks due: "Review Q3 proposal" (high), "Update tracker"
• 📅 11:00 AM  Sprint planning (Zoom)
Want me to set a heads-up before the meeting?
```

## 4. Tool/function registry (the only actions the AI can trigger)

```python
TOOLS = {
  "get_daily_agenda":  TaskService.get_daily_agenda,     # read
  "get_weekly_agenda": TaskService.get_weekly_agenda,    # read
  "list_tasks":        TaskService.list_for_user,        # read
  "get_task_status":   TaskService.resolve_and_status,   # read
  "create_task":       TaskService.create,               # write — perm checked
  "create_reminder":   ReminderService.create_nl,        # write — own only
  "list_meetings":     MeetingService.list_for_user,     # read
  "next_meeting":      MeetingService.next_for_user,     # read
  "list_jira":         JiraService.list_for_user,        # read
  "team_summary":      ReportService.team_summary,       # read — manager+
}
```

Every write tool re-checks RBAC for the resolved WhatsApp user **before** executing —
the LLM's classification is never trusted as authorization.

## 5. RAG (optional, phase 2)

Used only for "knowledge" questions (policies, how-tos), not for personal data
(personal data is always fetched via services, never embedded).

```
ingest:  docs → chunk (≈500 tok) → nomic-embed-text → kb_chunks(embedding)
query:   question → embed → pgvector cosine top-k → stuff into render prompt as CONTEXT
```

Keep RAG and personal-data paths separate so a retrieval bug can never leak one
employee's tasks into another's answer.

## 6. Reliability

- **Timeouts:** 8s intent, 12s render; on timeout fall back to a deterministic template (e.g. raw agenda list) so the user always gets a reply.
- **Circuit breaker:** if Ollama errors > N in a window, switch to template-only mode and alert.
- **Caching:** identical (intent, entities, data-hash) render results cached in Redis 60s.
- **Cost/perf:** keep prompts short; pin `num_ctx` modest; warm the model with a keep-alive ping.
