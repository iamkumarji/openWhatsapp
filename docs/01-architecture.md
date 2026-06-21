# 01 — Architecture

- [1. High-Level Architecture](#1-high-level-architecture)
- [2. Low-Level Architecture](#2-low-level-architecture)
- [3. Service Breakdown](#3-service-breakdown)
- [4. Message Flow](#4-message-flow)
- [5. Sequence Diagrams](#5-sequence-diagrams)

---

## 1. High-Level Architecture

```mermaid
flowchart LR
  subgraph Phone["Employee / Manager"]
    WA["WhatsApp app"]
    BR["Web browser"]
  end

  subgraph Edge["Edge"]
    NGINX["Nginx\nTLS termination · reverse proxy · rate limit"]
  end

  subgraph Apps["Application tier"]
    GW["WhatsApp Gateway\n(whatsapp-web.js)"]
    API["FastAPI Backend\nREST + AI orchestration"]
    FE["Next.js Admin Portal"]
    N8N["n8n\nworkflow automation"]
    KC["Keycloak\nOIDC / RBAC"]
  end

  subgraph AI["AI tier"]
    OLL["Ollama\nQwen3 / Llama 3"]
  end

  subgraph Data["Data tier"]
    PG[("PostgreSQL")]
    RD[("Redis\ncache + Celery broker")]
  end

  subgraph Obs["Observability"]
    PROM["Prometheus"]
    GRAF["Grafana"]
    LOKI["Loki"]
    PT["Promtail"]
  end

  subgraph Ext["External SaaS (egress)"]
    JIRA["Jira REST"]
    ZOOM["Zoom API"]
    GCAL["Google Calendar"]
    MCAL["MS Graph Calendar"]
  end

  WA <--> GW
  BR --> NGINX --> FE
  NGINX --> API
  NGINX --> KC
  NGINX --> GRAF
  GW <--> API
  FE --> API
  API <--> KC
  API --> OLL
  API --> PG
  API --> RD
  N8N --> API
  API --> JIRA
  API --> ZOOM
  API --> GCAL
  API --> MCAL
  PT --> LOKI
  PROM --> GRAF
  LOKI --> GRAF
  API -.metrics.-> PROM
  GW -.metrics.-> PROM
```

**Tiers**

1. **Edge** — Nginx terminates TLS, reverse-proxies, applies global rate limits and WAF-style rules.
2. **Application** — stateless FastAPI backend (horizontally scalable), the WhatsApp gateway (stateful, holds the WA session), the Next.js portal, n8n, and Keycloak.
3. **AI** — Ollama serving local models; GPU node(s) at scale.
4. **Data** — PostgreSQL (source of truth) + Redis (cache, rate-limit counters, Celery broker, conversation state).
5. **Observability** — Prometheus/Grafana metrics, Loki/Promtail logs.

---

## 2. Low-Level Architecture (Backend internals)

```mermaid
flowchart TB
  subgraph FastAPI["FastAPI Backend (uvicorn workers)"]
    direction TB
    MW["Middleware\nJWT verify · request-id · rate-limit · audit"]
    ROUT["API Routers\n/auth /tasks /reminders /meetings\n/jira /zoom /calendar /dashboard\n/broadcast /internal/wa"]
    ORCH["AI Orchestrator\nintent detect → tool routing → response render"]
    SVC["Domain Services\nTaskSvc · ReminderSvc · MeetingSvc\nJiraSvc · ZoomSvc · CalendarSvc · UserSvc"]
    REPO["Repositories (SQLAlchemy async)"]
    SCHED["Scheduler\nAPScheduler (MVP) / Celery beat (prod)"]
    WORK["Celery workers\nreminder.fire · jira.sync · calendar.sync · broadcast.send"]
  end

  MW --> ROUT --> ORCH
  ROUT --> SVC
  ORCH --> SVC
  SVC --> REPO --> PG[("PostgreSQL")]
  ORCH --> OLL["Ollama"]
  SVC --> RD[("Redis")]
  SCHED --> RD
  RD --> WORK
  WORK --> SVC
  WORK --> GW["WhatsApp Gateway\nsendMessage"]
```

**Key internal contracts**

- The **AI Orchestrator** never talks to the database directly; it calls **Domain Services** through a tool registry. This keeps the LLM sandboxed to a finite, validated set of actions.
- **Domain Services** are the only layer that uses **Repositories**. Integrations (Jira/Zoom/Calendar) are wrapped as services so the orchestrator treats local data and remote data uniformly.
- **Scheduler → Redis → Celery workers** decouples "when to fire" from "deliver via WhatsApp," so reminder delivery survives backend restarts.

---

## 3. Service Breakdown

| # | Layer / Service | Tech | Responsibility | State |
|---|-----------------|------|----------------|-------|
| 1 | **WhatsApp Gateway** | Node 20, whatsapp-web.js | Maintain WA session, normalize inbound messages → backend, send outbound | Stateful (LocalAuth session on volume) |
| 2 | **API Gateway/Edge** | Nginx | TLS, routing, rate limiting, gzip, security headers | Stateless |
| 3 | **Backend API** | Python 3.12, FastAPI, SQLAlchemy 2 async | REST endpoints, business logic, AI orchestration entrypoint | Stateless |
| 4 | **AI Orchestrator** | (module in backend) Ollama client | Intent detection, tool routing, NL response generation | Stateless (conv. state in Redis) |
| 5 | **Task Service** | (module) | CRUD, assignment, status, priority, comments, attachments, recurrence, escalation | — |
| 6 | **Reminder Engine** | (module) + Celery beat | Parse NL time, schedule one-off/recurring reminders, deliver via WA | Schedule in PG, jobs in Redis |
| 7 | **Meeting Service** | (module) | Internal meetings + aggregation of Zoom/Calendar meetings | — |
| 8 | **Jira Integration** | (module) httpx | Pull assigned issues/sprints/boards, map users, periodic sync, local cache | Cache in PG |
| 9 | **Zoom Integration** | (module) httpx, S2S OAuth | Fetch meetings, links, reminders | Cache in PG |
| 10 | **Calendar Integration** | (module) Google API + MS Graph | Daily/weekly schedule, availability, sync | Cache in PG |
| 11 | **Notification Engine** | (module) + Celery | Fan-out reminders, broadcasts, escalations to WhatsApp/portal | Queue in Redis |
| 12 | **Web Admin Portal** | Next.js 14, React, TS, Tailwind | Dashboards, management UIs for all roles | Client + SSR |
| 13 | **Auth & RBAC** | Keycloak (OIDC) + backend policy | SSO, token issuance; backend enforces permission matrix | Keycloak DB |
| 14 | **Workflow Automation** | n8n | Low-code glue: report schedules, custom integrations, alert routing | n8n DB |
| 15 | **Reporting** | (module) + Grafana | Aggregations, exports (CSV/PDF), team analytics | — |
| 16 | **Scheduler** | APScheduler (MVP) → Celery beat (prod) | Cron + interval jobs: syncs, reminders, escalation sweeps, digests | Redis |

---

## 4. Message Flow

```
User ──▶ WhatsApp ──▶ WhatsApp Gateway ──▶ Backend API (/internal/wa/inbound)
                                                  │
                                                  ▼
                                          AI Orchestrator
                                          (intent + entities)
                                                  │
                          ┌───────────────────────┼───────────────────────┐
                          ▼                        ▼                        ▼
                    Task Service            Reminder Engine          Jira/Zoom/Calendar
                          │                        │                        │
                          └───────────────────────┼───────────────────────┘
                                                  ▼
                                       Response renderer (LLM)
                                                  │
                          Backend ──▶ Gateway.sendMessage ──▶ WhatsApp ──▶ User
```

**Identity binding:** the gateway sends the sender's WhatsApp number (`wa_id`). The backend looks up `users.whatsapp_number` to resolve the employee. Unknown numbers get an enrollment prompt (one-time link code issued in the portal). All inbound/outbound messages are written to `message_logs`.

---

## 5. Sequence Diagrams

### 5.1 "What do I have today?" (daily schedule)

```mermaid
sequenceDiagram
  actor U as Employee (WhatsApp)
  participant GW as WA Gateway
  participant API as Backend API
  participant RD as Redis
  participant AI as Orchestrator+Ollama
  participant TS as Task/Meeting/Cal Services
  participant PG as PostgreSQL

  U->>GW: "What do I have today?"
  GW->>API: POST /internal/wa/inbound {wa_id, text}
  API->>PG: resolve user by whatsapp_number
  API->>RD: load conversation context
  API->>AI: detect_intent(text, context)
  AI-->>API: intent=daily_schedule, entities={date:today}
  API->>TS: get_today(user_id)
  TS->>PG: query tasks due today + meetings + reminders
  PG-->>TS: rows
  TS-->>API: aggregated agenda
  API->>AI: render_response(agenda, locale)
  AI-->>API: friendly summary text
  API->>RD: persist context + write message_logs
  API-->>GW: 200 {reply}
  GW-->>U: formatted daily agenda
```

### 5.2 "Remind me in 1 hour to call Rajesh" (reminder creation + firing)

```mermaid
sequenceDiagram
  actor U as Employee
  participant GW as WA Gateway
  participant API as Backend API
  participant AI as Orchestrator
  participant RS as Reminder Service
  participant PG as PostgreSQL
  participant CB as Celery beat
  participant CW as Celery worker

  U->>GW: "Remind me in 1 hour to call Rajesh"
  GW->>API: POST /internal/wa/inbound
  API->>AI: detect_intent
  AI-->>API: intent=create_reminder, entities={offset:1h, text:"call Rajesh"}
  API->>RS: create_reminder(user, fire_at=now+1h, body)
  RS->>PG: INSERT reminders (status=scheduled)
  RS-->>API: reminder #id
  API-->>GW: "👍 I'll remind you at 3:45 PM to call Rajesh."
  Note over CB: every 30s scan due reminders
  CB->>PG: SELECT due reminders (fire_at<=now, status=scheduled)
  CB->>CW: enqueue reminder.fire(reminder_id)
  CW->>PG: lock row, mark firing
  CW->>GW: sendMessage(wa_id, "⏰ Reminder: call Rajesh")
  CW->>PG: mark sent / compute next_fire if recurring
  GW-->>U: ⏰ Reminder: call Rajesh
```

### 5.3 Periodic Jira sync

```mermaid
sequenceDiagram
  participant CB as Celery beat
  participant CW as Worker (jira.sync)
  participant JIRA as Jira REST
  participant PG as PostgreSQL

  CB->>CW: every 10 min → jira.sync
  CW->>PG: load mapped users + last_sync cursor
  loop per project/user
    CW->>JIRA: GET /search?jql=assignee=...&updated>cursor
    JIRA-->>CW: issues page (paginated)
    CW->>PG: UPSERT jira_issues, jira_projects
  end
  CW->>PG: update sync cursor + audit_log
```

### 5.4 Manager broadcast

```mermaid
sequenceDiagram
  actor M as Manager (Portal)
  participant FE as Next.js
  participant API as Backend
  participant KC as Keycloak
  participant CW as Worker (broadcast.send)
  participant GW as WA Gateway
  actor T as Team

  M->>FE: compose broadcast → target=team_id
  FE->>API: POST /broadcasts (Bearer JWT)
  API->>KC: validate token + role=manager/admin
  API->>API: authorize: manager owns team?
  API->>CW: enqueue broadcast.send(audience)
  loop per recipient (rate-limited)
    CW->>GW: sendMessage(wa_id, body)
    GW-->>T: announcement
  end
  CW->>API: write delivery report + audit_log
```
