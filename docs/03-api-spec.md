# 03 — REST API Specification

Base URL: `https://<host>/api/v1`
Auth: `Authorization: Bearer <JWT>` (Keycloak-issued, RS256). Internal gateway
endpoints use a separate shared secret (`X-Internal-Token`) and are not exposed
through Nginx publicly.

Conventions:
- JSON request/response. `snake_case` fields. Timestamps ISO-8601 UTC.
- Pagination: `?limit=50&cursor=<opaque>`; responses include `next_cursor`.
- Errors: `{ "error": { "code": "task_not_found", "message": "...", "request_id": "..." } }`.
- Every mutating call is authorized against the RBAC permission matrix (docs/06) and audit-logged.

---

## Auth

| Method | Path | Permission | Notes |
|--------|------|-----------|-------|
| GET  | `/auth/me` | authenticated | Current user profile + role + permissions |
| POST | `/auth/whatsapp/enroll` | authenticated | Issue one-time enroll code to bind a WA number |
| POST | `/auth/logout` | authenticated | Revoke refresh token (Keycloak) |

> Login/refresh are handled by Keycloak's OIDC endpoints (`/auth/realms/waint/protocol/openid-connect/token`). The frontend uses Authorization Code + PKCE.

---

## Tasks

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| POST   | `/tasks` | task.create | Create a task |
| GET    | `/tasks` | task.view.own / team | List tasks (filters below) |
| GET    | `/tasks/{id}` | view scope | Get one task |
| PATCH  | `/tasks/{id}` | task.update.own/any | Update fields/status |
| DELETE | `/tasks/{id}` | task.update.any | Soft-cancel a task |
| POST   | `/tasks/{id}/assign` | task.assign | Assign to user(s) |
| POST   | `/tasks/{id}/comments` | view scope | Add comment |
| GET    | `/tasks/{id}/comments` | view scope | List comments |
| POST   | `/tasks/{id}/attachments` | view scope | Upload (multipart) |

Filters for `GET /tasks`: `assignee_id`, `status`, `priority`, `team_id`,
`due_before`, `due_after`, `overdue=true`, `q` (full-text).

```jsonc
// POST /tasks
{
  "title": "Review Q3 proposal",
  "description": "Check pricing section",
  "priority": "high",
  "due_at": "2026-06-22T04:30:00Z",
  "assignee_ids": ["<uuid>"],
  "rrule": null,
  "escalate_after_hours": 24
}
// 201 → { "id": "<uuid>", "status": "todo", ... }
```

---

## Reminders

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| POST   | `/reminders` | reminder.manage.own | Create reminder (absolute or natural-language time) |
| GET    | `/reminders` | reminder.manage.own | List own reminders (`?status=scheduled`) |
| PATCH  | `/reminders/{id}` | own | Reschedule / edit |
| DELETE | `/reminders/{id}` | own | Cancel |

```jsonc
// POST /reminders  — two accepted forms:
{ "body": "Call Rajesh", "fire_at": "2026-06-21T10:15:00Z" }       // absolute
{ "body": "Call Rajesh", "natural_time": "in 1 hour" }              // parsed server-side
{ "body": "Standup", "natural_time": "every Monday at 9am", "kind": "recurring" }
```

---

## Meetings

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| GET  | `/meetings` | meeting.view.own | List meetings (`?from=&to=&source=`) |
| GET  | `/meetings/next` | meeting.view.own | Next upcoming meeting |
| GET  | `/meetings/{id}` | view scope | Meeting detail + join_url |
| POST | `/meetings` | meeting.manage | Create internal meeting |

---

## Jira (read-only mirror)

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| GET  | `/jira/issues` | jira.view.own | Issues assigned to caller (`?status_category=&sprint=`) |
| GET  | `/jira/issues/{key}` | jira.view.own | Single issue |
| GET  | `/jira/sprints/active` | jira.view.own | Active sprint(s) for caller's boards |
| POST | `/jira/sync` | integration.manage | Trigger manual sync |

---

## Zoom & Calendar

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| GET  | `/zoom/meetings` | meeting.view.own | Upcoming Zoom meetings |
| POST | `/calendar/google/connect` | meeting.view.own | Start Google OAuth (returns auth URL) |
| POST | `/calendar/outlook/connect` | meeting.view.own | Start MS Graph OAuth |
| GET  | `/calendar/events` | meeting.view.own | Calendar events (`?from=&to=`) |
| POST | `/calendar/sync` | integration.manage | Force calendar sync |

---

## Dashboard & Reports

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| GET | `/dashboard` | authenticated | Role-aware widgets (today, overdue, next meeting, jira counts) |
| GET | `/reports/team-summary` | report.view.team | Completion %, overdue, throughput by member |
| GET | `/reports/overdue` | report.view.team | Overdue tasks across team |
| GET | `/reports/export` | report.view.team | CSV/PDF export (`?format=csv&type=team_summary`) |

```jsonc
// GET /dashboard  (employee)
{
  "today": { "tasks": 3, "meetings": 2, "reminders": 1 },
  "next_meeting": { "title": "Sprint planning", "starts_at": "...", "join_url": "..." },
  "overdue_tasks": 1,
  "jira": { "in_progress": 4, "todo": 7 }
}
```

---

## Broadcasts (manager/admin)

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| POST | `/broadcasts` | broadcast.send | Send/schedule announcement |
| GET  | `/broadcasts` | broadcast.send | List with delivery stats |

```jsonc
// POST /broadcasts
{ "audience": {"type":"team","ids":["<team_uuid>"]},
  "body": "All-hands moved to 4 PM.", "scheduled_at": null }
```

---

## Admin: users / teams / roles

| Method | Path | Permission |
|--------|------|-----------|
| GET/POST | `/users` | user.manage |
| PATCH/DELETE | `/users/{id}` | user.manage |
| GET/POST | `/teams` | user.manage |
| GET | `/roles` | user.manage |
| GET | `/audit-logs` | user.manage |

---

## Internal (gateway ↔ backend, not public)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/internal/wa/inbound` | `X-Internal-Token` | Inbound WhatsApp message → AI pipeline → reply |
| POST | `/internal/wa/status` | `X-Internal-Token` | Delivery/read receipts |
| GET  | `/internal/health` | none | Liveness/readiness |

```jsonc
// POST /internal/wa/inbound
{ "wa_id": "+919812345678", "message_id": "wamid...", "text": "What do I have today?", "timestamp": 1718950000 }
// 200 → { "reply": "Good morning! Today you have...", "intent": "daily_schedule" }
```

---

## Health & metrics

| Method | Path | Description |
|--------|------|-------------|
| GET | `/healthz` | liveness |
| GET | `/readyz`  | readiness (db + redis + ollama checks) |
| GET | `/metrics` | Prometheus exposition (scraped internally) |
