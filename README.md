# WAINT — WhatsApp AI Team Assistant

A self-hosted, open-source **Team Assistant Platform** that turns a single company
WhatsApp number into an AI-powered personal assistant for every employee.

Employees chat naturally ("What do I have today?", "Remind me in 1 hour to call Rajesh",
"What Jira tasks are assigned to me?") and get answers built from their tasks, meetings,
reminders, Jira issues, Zoom meetings and calendars. Managers get a web portal to create
and assign work, track progress, broadcast announcements and run reports.

Everything runs on your own Ubuntu servers. No OpenAI, no Anthropic, no paid AI APIs —
all inference is local via **Ollama (Qwen3 / Llama 3)**.

---

## Why this design

| Concern            | Decision                                                                 |
|--------------------|--------------------------------------------------------------------------|
| Data sovereignty   | 100% self-hosted; LLM inference local via Ollama                         |
| Cost               | Only open-source components; no per-message or per-token fees            |
| WhatsApp           | `whatsapp-web.js` gateway (OpenWA as fallback) — no Cloud API fees       |
| Extensibility      | Service-oriented FastAPI backend + n8n for low-code workflow glue        |
| Observability      | Prometheus + Grafana metrics, Loki + Promtail logs                       |
| Security           | Keycloak (OIDC), JWT, RBAC, audit logs, encryption at rest, rate limits  |

---

## Documentation

| Doc | Contents |
|-----|----------|
| [docs/01-architecture.md](docs/01-architecture.md) | HLD, LLD, service breakdown, message flow, sequence diagrams |
| [docs/02-database-schema.sql](docs/02-database-schema.sql) | Full PostgreSQL DDL |
| [docs/03-api-spec.md](docs/03-api-spec.md) | REST API specification |
| [docs/04-ai-orchestration.md](docs/04-ai-orchestration.md) | Intent detection, prompt templates, RAG, tool-calling |
| [docs/05-deployment.md](docs/05-deployment.md) | Docker, env vars, secrets, backup, DR, monitoring |
| [docs/06-security.md](docs/06-security.md) | Security architecture + threat model (STRIDE) |
| [docs/07-roadmap-and-scaling.md](docs/07-roadmap-and-scaling.md) | Roadmap, MVP/Prod phases, scaling 100→5000 users |

## Sample source code

| Path | Service |
|------|---------|
| `services/backend/` | FastAPI core API: auth, tasks, reminders, meetings, Jira, AI orchestrator, scheduler |
| `services/whatsapp-gateway/` | Node.js `whatsapp-web.js` gateway |
| `services/frontend/` | Next.js 14 + TypeScript + Tailwind admin portal |
| `infra/` | Nginx, Prometheus, Grafana, Loki, Promtail configs |
| `docker-compose.yml` | Full local/prod stack |

---

## Quick start (dev)

```bash
cp .env.example .env          # fill in secrets
docker compose up -d postgres redis ollama keycloak
docker compose exec ollama ollama pull qwen2.5:7b-instruct
docker compose exec ollama ollama pull llama3.1:8b-instruct
docker compose up -d backend whatsapp-gateway frontend nginx
# Scan the QR code printed by the whatsapp-gateway container logs:
docker compose logs -f whatsapp-gateway
```

Web portal: `https://localhost` · Keycloak: `https://localhost/auth` · Grafana: `https://localhost/grafana`

---

## High-level topology

```
                       ┌────────────────────────── Ubuntu Server(s) ──────────────────────────┐
 Employee's phone      │                                                                       │
   (WhatsApp)          │   ┌─────────────┐   ┌──────────┐   ┌───────────────┐                  │
        │              │   │  whatsapp-  │   │  Nginx   │   │   Next.js     │                  │
        │  WA protocol │   │  gateway    │   │ (TLS/RP) │◄──┤  Admin Portal │                  │
        ├──────────────┼──►│ (whatsapp-  │   └────┬─────┘   └───────────────┘                  │
        │              │   │  web.js)    │        │                                            │
        │◄─────────────┼───┤             │        ▼                                            │
                       │   └─────┬───────┘   ┌──────────────┐   ┌──────────┐   ┌────────────┐  │
                       │         │           │  FastAPI     │   │ Keycloak │   │   n8n      │  │
                       │         └──────────►│  Backend     │◄─►│  (OIDC)  │   │ workflows  │  │
                       │                     │  (REST+AI)   │   └──────────┘   └────────────┘  │
                       │                     └──┬───┬───┬───┘                                   │
                       │            ┌───────────┘   │   └───────────┐                          │
                       │       ┌────▼────┐    ┌──────▼─────┐   ┌─────▼──────┐                   │
                       │       │ Ollama  │    │ PostgreSQL │   │   Redis    │                   │
                       │       │ Qwen3/  │    │            │   │ cache+queue│                   │
                       │       │ Llama3  │    └────────────┘   └────────────┘                   │
                       │       └─────────┘                                                      │
                       │   Observability: Prometheus · Grafana · Loki · Promtail               │
                       └───────────────────────────────────────────────────────────────────────┘
       External (egress only): Jira Cloud REST · Zoom API · Google/Microsoft Calendar
```

> ⚠️ **WhatsApp note:** `whatsapp-web.js` automates WhatsApp Web and is not an official
> WhatsApp API. It is excellent for internal/pilot deployments but can break on WhatsApp
> updates and may risk number bans under heavy automation. For regulated enterprise scale,
> plan a migration path to the **WhatsApp Cloud API / BSP** — the gateway is isolated behind
> an internal interface (`POST /internal/wa/inbound` + `sendMessage`) precisely so it can be
> swapped without touching the rest of the system. See docs/07 scaling notes.
