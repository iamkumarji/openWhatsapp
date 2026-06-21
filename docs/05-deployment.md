# 05 — Deployment, Ops, Backup & Monitoring

Target: **Ubuntu Server 22.04/24.04 LTS**, Docker + Docker Compose.

## 1. Repository / folder structure

```
waint/
├── README.md
├── docker-compose.yml
├── docker-compose.prod.yml          # overrides: replicas, GPU, resource limits
├── .env.example
├── docs/                            # this documentation set
├── infra/
│   ├── nginx/                       # reverse proxy + TLS
│   ├── postgres/                    # init, tuning
│   ├── prometheus/                  # prometheus.yml + alert rules
│   ├── grafana/                     # provisioning + dashboards
│   ├── loki/                        # loki-config.yml
│   └── promtail/                    # promtail-config.yml
├── scripts/
│   ├── backup.sh                    # pg_dump + volume snapshot
│   ├── restore.sh
│   └── bootstrap.sh                 # one-shot server prep
└── services/
    ├── backend/                     # FastAPI
    │   ├── app/
    │   │   ├── main.py
    │   │   ├── core/                # config, security, logging, deps
    │   │   ├── api/routes/          # routers
    │   │   ├── db/                  # session, base
    │   │   ├── models/              # SQLAlchemy models
    │   │   ├── schemas/             # Pydantic
    │   │   ├── services/            # domain logic
    │   │   ├── integrations/        # jira, zoom, google, outlook clients
    │   │   ├── ai/                  # orchestrator, ollama client, prompts
    │   │   └── workers/             # celery app, tasks, beat schedule
    │   ├── alembic/                 # migrations
    │   ├── pyproject.toml
    │   └── Dockerfile
    ├── whatsapp-gateway/            # Node whatsapp-web.js
    │   ├── src/index.js
    │   ├── package.json
    │   └── Dockerfile
    └── frontend/                    # Next.js 14
        ├── src/app/
        ├── package.json
        └── Dockerfile
```

## 2. Environment variables (`.env.example`)

```dotenv
# --- core ---
ENV=production
SECRET_KEY=change-me
INTERNAL_TOKEN=change-me-gateway-secret
PUBLIC_BASE_URL=https://assistant.company.com

# --- postgres ---
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=waint
POSTGRES_USER=waint
POSTGRES_PASSWORD=change-me
DATABASE_URL=postgresql+asyncpg://waint:change-me@postgres:5432/waint

# --- redis ---
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2

# --- keycloak (OIDC) ---
KEYCLOAK_URL=https://assistant.company.com/auth
KEYCLOAK_REALM=waint
KEYCLOAK_CLIENT_ID=waint-backend
KEYCLOAK_CLIENT_SECRET=change-me
OIDC_JWKS_URL=https://assistant.company.com/auth/realms/waint/protocol/openid-connect/certs

# --- ollama ---
OLLAMA_URL=http://ollama:11434
LLM_INTENT_MODEL=qwen2.5:7b-instruct
LLM_RENDER_MODEL=qwen2.5:7b-instruct
LLM_EMBED_MODEL=nomic-embed-text

# --- whatsapp gateway ---
WA_BACKEND_INBOUND_URL=http://backend:8000/api/v1/internal/wa/inbound
WA_SESSION_PATH=/data/wa-session

# --- encryption (AES-GCM key for oauth_tokens, base64 32 bytes) ---
ENCRYPTION_KEY=base64:...

# --- integrations ---
JIRA_BASE_URL=https://yourorg.atlassian.net
JIRA_EMAIL=svc@company.com
JIRA_API_TOKEN=change-me
ZOOM_ACCOUNT_ID=...
ZOOM_CLIENT_ID=...
ZOOM_CLIENT_SECRET=...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
MS_CLIENT_ID=...
MS_CLIENT_SECRET=...
MS_TENANT_ID=...
```

## 3. Secrets management

- **Dev:** `.env` (git-ignored).
- **Prod:** Docker secrets or HashiCorp **Vault** (open-source). Mount secrets as files; the backend reads `*_FILE` env vars first, falling back to plain env. Never bake secrets into images.
- Rotate `INTERNAL_TOKEN`, DB and integration credentials quarterly; `ENCRYPTION_KEY` rotation requires re-encrypting `oauth_tokens` (provide both old+new during rotation window).

## 4. Bring-up (production)

```bash
# 1. server prep
sudo bash scripts/bootstrap.sh          # docker, ufw, fail2ban, swap, sysctls
# 2. config
cp .env.example .env && $EDITOR .env
# 3. data + identity first
docker compose up -d postgres redis keycloak ollama
docker compose exec ollama ollama pull qwen2.5:7b-instruct
docker compose exec ollama ollama pull nomic-embed-text
# 4. migrate
docker compose run --rm backend alembic upgrade head
docker compose run --rm backend python -m app.scripts.seed   # roles/permissions
# 5. app + edge
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
# 6. bind WhatsApp (scan QR once)
docker compose logs -f whatsapp-gateway
```

## 5. Backup strategy

| Asset | Method | Frequency | Retention |
|-------|--------|-----------|-----------|
| PostgreSQL | `pg_dump -Fc` (logical) + WAL archiving (PITR) | dump hourly, WAL continuous | 7d hourly, 30d daily, 12m monthly |
| Redis | RDB snapshot (ephemeral; not source of truth) | 6h | 2d |
| WhatsApp session volume | tar snapshot | daily | 7d |
| Keycloak DB | included in PG dump (separate DB) | with PG | with PG |
| Object storage (attachments) | rsync/MinIO mirror to offsite | daily | 30d |
| Configs/secrets | Vault snapshot / encrypted git | on change | ∞ |

`scripts/backup.sh` runs via cron, encrypts (`age`/GPG), uploads offsite (S3-compatible / rsync), and verifies the dump restores into a throwaway container weekly.

## 6. Disaster recovery

- **RPO:** ≤ 1h (hourly dumps + continuous WAL → near-zero with PITR).
- **RTO:** ≤ 1h for full stack rebuild from IaC + latest backup.
- **Runbook:** provision Ubuntu host → `bootstrap.sh` → restore PG (`restore.sh`) → `docker compose up` → re-scan WhatsApp QR (session is the only non-replayable piece; document the re-pairing step). Keep a warm standby Postgres replica (streaming replication) for hot failover at 1000+ users.

## 7. Monitoring & logging

**Metrics (Prometheus → Grafana):**
- Backend: request rate/latency/errors (per route), AI intent latency, Ollama call duration, reminder queue depth, Celery task success/failure, DB pool usage.
- Infra: node-exporter (CPU/mem/disk), postgres-exporter, redis-exporter, cAdvisor (containers), Ollama GPU utilization.

**Logs (Promtail → Loki → Grafana):** structured JSON logs from all services, correlated by `request_id` / `wa_message_id`.

**Alerting rules (examples):**
- p95 inbound→reply latency > 6s for 5m
- reminder queue depth > 500 or oldest due reminder age > 2m (delivery lagging)
- Ollama error rate > 5% (→ template fallback engaged)
- WhatsApp gateway disconnected / QR re-auth required
- Celery worker down, DB connections > 80% pool, disk > 80%

**Healthchecks:** `/healthz` (liveness), `/readyz` (db+redis+ollama). Docker `healthcheck` blocks dependents until ready.
