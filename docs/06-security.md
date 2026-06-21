# 06 — Security Architecture & Threat Model

## 1. Controls overview

| Domain | Control |
|--------|---------|
| Transport | TLS 1.2+ everywhere public (Nginx + Let's Encrypt/cert-manager). HSTS. Internal traffic on a private Docker network. |
| AuthN | Keycloak OIDC (Authorization Code + PKCE for portal). Backend validates RS256 JWT against JWKS, checks `iss`/`aud`/`exp`. |
| AuthZ | RBAC permission matrix enforced server-side on every endpoint and every AI write-tool. Default-deny. |
| Gateway trust | Internal endpoints require `X-Internal-Token` and are bound to the internal network only (never proxied publicly). |
| WhatsApp identity | Inbound `wa_id` mapped to a user via opt-in enroll code; unknown numbers cannot read anyone's data. |
| Secrets | Vault / Docker secrets; no secrets in images or git; `*_FILE` indirection. |
| Encryption at rest | Postgres on LUKS-encrypted volume; per-user OAuth tokens AES-256-GCM encrypted at app layer (`oauth_tokens.access_token` is ciphertext). Backups encrypted (`age`/GPG). |
| Rate limiting | Nginx (per-IP) + app-layer (per-user/per-wa_id) token buckets in Redis. Throttles brute force and WhatsApp abuse/spam-ban risk. |
| Input safety | Pydantic validation; parameterized queries (SQLAlchemy); LLM output never executed — only mapped to a fixed tool registry. |
| Audit | All mutations and AI actions → `audit_logs` + `message_logs` (immutable, append-only; shipped to Loki). |
| Headers | CSP, X-Frame-Options DENY, X-Content-Type-Options nosniff, Referrer-Policy. |
| Dependency hygiene | Pinned versions, `pip-audit`/`npm audit`/Trivy image scans in CI. |
| Network | UFW: only 80/443 open; SSH key-only + fail2ban; DB/Redis/Ollama never published to host. |

## 2. RBAC permission matrix

| Capability | Employee | Manager | Admin |
|------------|:-------:|:-------:|:-----:|
| View own tasks/meetings/reminders/jira | ✅ | ✅ | ✅ |
| Create own tasks & reminders | ✅ | ✅ | ✅ |
| Update own/assigned tasks | ✅ | ✅ | ✅ |
| View team tasks/progress | ❌ | ✅ (own team) | ✅ (all) |
| Assign tasks to others | ❌ | ✅ | ✅ |
| Create reminders for team members | ❌ | ✅ | ✅ |
| Create/edit meetings | ❌ | ✅ | ✅ |
| Send broadcasts | ❌ | ✅ (own team) | ✅ (all) |
| View reports/analytics | ❌ | ✅ (team) | ✅ (org) |
| Manage users/teams/roles | ❌ | ❌ | ✅ |
| Configure integrations | ❌ | ❌ | ✅ |
| View audit logs | ❌ | ❌ | ✅ |

Scope rule: managers are constrained to their `team_id`; the backend resolves the
target's team and rejects cross-team actions (checked in service layer, not the LLM).

## 3. Threat model (STRIDE)

| Threat | Vector | Mitigation |
|--------|--------|-----------|
| **Spoofing** | Attacker messages from an unknown/forged WhatsApp number to read someone's data | Enroll-code binding; unknown `wa_id` gets no data; one number ↔ one user; impersonation of E.164 is hard on WhatsApp |
| **Spoofing** | Forged JWT to the API | RS256 signature verified vs Keycloak JWKS; reject on bad `iss/aud/exp`; short token TTL + refresh |
| **Spoofing** | Direct call to `/internal/wa/inbound` to act as the gateway | Endpoint not publicly routable + `X-Internal-Token` + network policy |
| **Tampering** | SQL injection / mass-assignment | Parameterized ORM queries; Pydantic schemas with explicit allow-lists |
| **Tampering** | Modify reminders/tasks of others | Ownership + RBAC checks in service layer on every mutation |
| **Repudiation** | User denies sending a command | `message_logs` + `audit_logs` append-only with timestamps, shipped to Loki |
| **Info disclosure** | LLM leaks another employee's data | Two-call design: model never queries DB; data fetched by user-scoped services; RAG store excludes personal data |
| **Info disclosure** | OAuth/integration tokens stolen from DB | AES-256-GCM app-layer encryption; LUKS at rest; least-priv DB role |
| **Info disclosure** | Secrets in logs | Log redaction filter (tokens/PII scrubbed); structured logging allow-list |
| **DoS** | Flood the WhatsApp number / API | Per-IP (Nginx) + per-user (Redis) rate limits; queue backpressure; Celery concurrency caps |
| **DoS** | LLM resource exhaustion | Request timeouts, circuit breaker → template fallback, concurrency limit on Ollama |
| **Elevation of privilege** | Employee invokes manager-only AI action ("assign task to X") | Write tools re-check RBAC for resolved user before executing; default-deny |
| **Elevation of privilege** | Prompt injection in message/task text steering the model | Model output constrained to fixed intent enum + tool registry; no shell/db/network access from model; injected instructions can't widen permissions |
| **Supply chain** | Malicious dependency / base image | Pinned deps, Trivy/`pip-audit`/`npm audit` in CI, minimal images, no `:latest` |

## 4. WhatsApp-specific risk

`whatsapp-web.js` is unofficial automation. Risks: **number ban**, session breakage on
WhatsApp updates. Mitigations: human-like send pacing + jitter, per-recipient rate limits
on broadcasts, opt-in only, a dedicated number, alerting on disconnect, and a documented
migration path to the official **WhatsApp Cloud API/BSP** behind the same internal interface.

## 5. Privacy / compliance posture

- Data minimization: cache only what's needed from Jira/Zoom/Calendar; TTL stale rows.
- Right to erasure: `users` soft-delete cascades; provide a purge job for `message_logs`/`audit_logs` per retention policy.
- Self-hosted inference means message content never leaves your infrastructure.
- Document a retention policy (e.g. message_logs 90d, audit_logs 1y) and enforce via scheduled purge jobs.
