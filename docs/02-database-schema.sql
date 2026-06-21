-- =====================================================================
-- WAINT — PostgreSQL schema (DDL)
-- Target: PostgreSQL 16+. Run as the application owner role.
-- Conventions: UUID PKs, created_at/updated_at on all tables, soft FKs to
-- Keycloak via keycloak_id. Timestamps are timestamptz (store UTC).
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "pg_trgm";     -- fuzzy search
CREATE EXTENSION IF NOT EXISTS "citext";      -- case-insensitive email
CREATE EXTENSION IF NOT EXISTS "vector";      -- optional: RAG embeddings (pgvector)

-- ---------- enums ----------
CREATE TYPE user_status      AS ENUM ('active','invited','suspended','deleted');
CREATE TYPE task_status      AS ENUM ('todo','in_progress','blocked','done','cancelled');
CREATE TYPE task_priority    AS ENUM ('low','medium','high','urgent');
CREATE TYPE reminder_status  AS ENUM ('scheduled','firing','sent','failed','cancelled');
CREATE TYPE reminder_kind    AS ENUM ('one_off','recurring');
CREATE TYPE meeting_source   AS ENUM ('internal','zoom','google','outlook');
CREATE TYPE notif_channel    AS ENUM ('whatsapp','portal','email');
CREATE TYPE notif_status     AS ENUM ('queued','sent','delivered','failed');
CREATE TYPE msg_direction    AS ENUM ('inbound','outbound');

-- ---------- trigger fn: keep updated_at fresh ----------
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

-- =====================================================================
-- IDENTITY, RBAC
-- =====================================================================

CREATE TABLE roles (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT NOT NULL UNIQUE,                 -- admin | manager | employee
  description TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE permissions (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code        TEXT NOT NULL UNIQUE,                 -- e.g. task.create, broadcast.send
  description TEXT
);

CREATE TABLE role_permissions (
  role_id       UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  permission_id UUID NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
  PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE teams (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT NOT NULL,
  manager_id  UUID,                                 -- FK added after users
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  keycloak_id      TEXT UNIQUE,                      -- OIDC subject
  email            CITEXT UNIQUE NOT NULL,
  full_name        TEXT NOT NULL,
  whatsapp_number  TEXT UNIQUE,                      -- E.164, e.g. +919812345678
  team_id          UUID REFERENCES teams(id) ON DELETE SET NULL,
  role_id          UUID NOT NULL REFERENCES roles(id),
  status           user_status NOT NULL DEFAULT 'invited',
  timezone         TEXT NOT NULL DEFAULT 'Asia/Kolkata',
  locale           TEXT NOT NULL DEFAULT 'en',
  -- external account links
  jira_account_id  TEXT,
  zoom_user_id     TEXT,
  google_sub       TEXT,
  ms_oid           TEXT,
  enroll_code      TEXT,                             -- one-time WA enrollment code
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE teams ADD CONSTRAINT fk_team_manager
  FOREIGN KEY (manager_id) REFERENCES users(id) ON DELETE SET NULL;

CREATE INDEX idx_users_wa      ON users(whatsapp_number);
CREATE INDEX idx_users_team    ON users(team_id);
CREATE INDEX idx_users_name_trgm ON users USING gin (full_name gin_trgm_ops);

-- =====================================================================
-- TASKS
-- =====================================================================

CREATE TABLE tasks (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title        TEXT NOT NULL,
  description  TEXT,
  status       task_status   NOT NULL DEFAULT 'todo',
  priority     task_priority NOT NULL DEFAULT 'medium',
  created_by   UUID NOT NULL REFERENCES users(id),
  team_id      UUID REFERENCES teams(id) ON DELETE SET NULL,
  due_at       TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  -- recurrence (RFC 5545 RRULE subset, null = non-recurring)
  rrule        TEXT,
  parent_id    UUID REFERENCES tasks(id) ON DELETE CASCADE,  -- recurring instance link
  -- escalation
  escalate_after_hours INT,                         -- overdue grace before escalation
  escalated_at TIMESTAMPTZ,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_tasks_status   ON tasks(status);
CREATE INDEX idx_tasks_due      ON tasks(due_at);
CREATE INDEX idx_tasks_team     ON tasks(team_id);

CREATE TABLE task_assignments (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id     UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  assignee_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  assigned_by UUID NOT NULL REFERENCES users(id),
  assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (task_id, assignee_id)
);
CREATE INDEX idx_assign_assignee ON task_assignments(assignee_id);

CREATE TABLE task_comments (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id    UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  author_id  UUID NOT NULL REFERENCES users(id),
  body       TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_comments_task ON task_comments(task_id);

CREATE TABLE task_attachments (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id     UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  uploaded_by UUID NOT NULL REFERENCES users(id),
  filename    TEXT NOT NULL,
  storage_key TEXT NOT NULL,                         -- object key (MinIO/disk)
  mime_type   TEXT,
  size_bytes  BIGINT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =====================================================================
-- MEETINGS (internal + aggregated external)
-- =====================================================================

CREATE TABLE meetings (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source       meeting_source NOT NULL DEFAULT 'internal',
  external_id  TEXT,                                 -- zoom/google/outlook id
  title        TEXT NOT NULL,
  description  TEXT,
  organizer_id UUID REFERENCES users(id),
  join_url     TEXT,
  location     TEXT,
  starts_at    TIMESTAMPTZ NOT NULL,
  ends_at      TIMESTAMPTZ,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source, external_id)
);
CREATE INDEX idx_meetings_start ON meetings(starts_at);

CREATE TABLE meeting_attendees (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  meeting_id  UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
  email       CITEXT,                                -- for non-users
  response    TEXT,                                  -- accepted/declined/tentative
  UNIQUE (meeting_id, user_id)
);
CREATE INDEX idx_attendee_user ON meeting_attendees(user_id);

-- =====================================================================
-- REMINDERS
-- =====================================================================

CREATE TABLE reminders (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_by  UUID NOT NULL REFERENCES users(id),
  body        TEXT NOT NULL,
  kind        reminder_kind NOT NULL DEFAULT 'one_off',
  rrule       TEXT,                                  -- for recurring
  fire_at     TIMESTAMPTZ NOT NULL,                  -- next firing (UTC)
  status      reminder_status NOT NULL DEFAULT 'scheduled',
  channel     notif_channel NOT NULL DEFAULT 'whatsapp',
  -- linkage (optional): reminder about a task/meeting
  task_id     UUID REFERENCES tasks(id) ON DELETE SET NULL,
  meeting_id  UUID REFERENCES meetings(id) ON DELETE SET NULL,
  last_fired_at TIMESTAMPTZ,
  attempts    INT NOT NULL DEFAULT 0,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- partial index = the hot path the scheduler scans every 30s
CREATE INDEX idx_reminders_due ON reminders(fire_at)
  WHERE status = 'scheduled';
CREATE INDEX idx_reminders_user ON reminders(user_id);

-- =====================================================================
-- JIRA (local cache / mirror)
-- =====================================================================

CREATE TABLE jira_projects (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  jira_key    TEXT NOT NULL UNIQUE,                  -- e.g. ENG
  name        TEXT NOT NULL,
  board_id    TEXT,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE jira_issues (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  jira_id         TEXT NOT NULL UNIQUE,              -- internal jira id
  issue_key       TEXT NOT NULL UNIQUE,             -- e.g. ENG-1234
  project_id      UUID REFERENCES jira_projects(id) ON DELETE CASCADE,
  summary         TEXT,
  status          TEXT,                              -- raw jira status name
  status_category TEXT,                              -- todo/indeterminate/done
  priority        TEXT,
  issue_type      TEXT,
  assignee_id     UUID REFERENCES users(id),         -- mapped local user
  assignee_account_id TEXT,                          -- jira accountId
  sprint_id       TEXT,
  sprint_name     TEXT,
  due_date        DATE,
  url             TEXT,
  jira_updated_at TIMESTAMPTZ,
  synced_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_jira_assignee ON jira_issues(assignee_id);
CREATE INDEX idx_jira_status   ON jira_issues(status_category);

-- sync bookkeeping (also reused by zoom/calendar)
CREATE TABLE sync_state (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  connector   TEXT NOT NULL,                         -- jira|zoom|google|outlook
  scope       TEXT NOT NULL,                         -- user_id / project / 'global'
  cursor      TEXT,                                  -- updated-since token / page
  last_run_at TIMESTAMPTZ,
  last_status TEXT,
  UNIQUE (connector, scope)
);

-- =====================================================================
-- CALENDAR (Google / Outlook mirror)
-- =====================================================================

CREATE TABLE calendar_events (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  source       meeting_source NOT NULL,              -- google|outlook
  external_id  TEXT NOT NULL,
  title        TEXT,
  description  TEXT,
  location     TEXT,
  join_url     TEXT,
  starts_at    TIMESTAMPTZ NOT NULL,
  ends_at      TIMESTAMPTZ,
  is_all_day   BOOLEAN NOT NULL DEFAULT false,
  status       TEXT,
  synced_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, source, external_id)
);
CREATE INDEX idx_calevents_user_start ON calendar_events(user_id, starts_at);

-- OAuth tokens for per-user calendar/zoom access (encrypted at app layer)
CREATE TABLE oauth_tokens (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider      TEXT NOT NULL,                       -- google|outlook|zoom
  access_token  BYTEA NOT NULL,                      -- AES-GCM ciphertext
  refresh_token BYTEA,
  scope         TEXT,
  expires_at    TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, provider)
);

-- =====================================================================
-- NOTIFICATIONS, MESSAGE LOGS, AUDIT
-- =====================================================================

CREATE TABLE notifications (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  channel     notif_channel NOT NULL DEFAULT 'whatsapp',
  title       TEXT,
  body        TEXT NOT NULL,
  status      notif_status NOT NULL DEFAULT 'queued',
  ref_type    TEXT,                                  -- reminder|task|broadcast|escalation
  ref_id      UUID,
  error       TEXT,
  sent_at     TIMESTAMPTZ,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_notif_user ON notifications(user_id);
CREATE INDEX idx_notif_status ON notifications(status);

CREATE TABLE broadcasts (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_by   UUID NOT NULL REFERENCES users(id),
  audience     JSONB NOT NULL,                       -- {type:team|all|users, ids:[...]}
  body         TEXT NOT NULL,
  scheduled_at TIMESTAMPTZ,
  sent_count   INT NOT NULL DEFAULT 0,
  fail_count   INT NOT NULL DEFAULT 0,
  status       TEXT NOT NULL DEFAULT 'draft',        -- draft|scheduled|sending|done
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE message_logs (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      UUID REFERENCES users(id) ON DELETE SET NULL,
  wa_id        TEXT,                                 -- raw WhatsApp number
  direction    msg_direction NOT NULL,
  body         TEXT,
  intent       TEXT,                                 -- detected intent (inbound)
  entities     JSONB,
  latency_ms   INT,
  model        TEXT,                                 -- which LLM answered
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_msglog_user_time ON message_logs(user_id, created_at DESC);

CREATE TABLE audit_logs (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_id    UUID REFERENCES users(id) ON DELETE SET NULL,
  action      TEXT NOT NULL,                         -- task.create, broadcast.send...
  entity_type TEXT,
  entity_id   UUID,
  metadata    JSONB,
  ip          INET,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_actor_time ON audit_logs(actor_id, created_at DESC);

-- optional: RAG store for knowledge-base answers (pgvector)
CREATE TABLE kb_chunks (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source     TEXT,
  content    TEXT NOT NULL,
  embedding  VECTOR(768),
  metadata   JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_kb_embedding ON kb_chunks USING ivfflat (embedding vector_cosine_ops);

-- =====================================================================
-- updated_at triggers
-- =====================================================================
DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'teams','users','tasks','meetings','reminders','oauth_tokens'
  ] LOOP
    EXECUTE format(
      'CREATE TRIGGER trg_%1$s_updated BEFORE UPDATE ON %1$s
       FOR EACH ROW EXECUTE FUNCTION set_updated_at();', t);
  END LOOP;
END $$;

-- =====================================================================
-- seed: roles + permission matrix  (see docs/06 for the full matrix)
-- =====================================================================
INSERT INTO roles (name, description) VALUES
  ('admin','Full system access'),
  ('manager','Team management + reporting'),
  ('employee','Self-service assistant');

INSERT INTO permissions (code, description) VALUES
  ('task.create','Create tasks'),
  ('task.assign','Assign tasks to others'),
  ('task.update.any','Update any task'),
  ('task.update.own','Update own/assigned tasks'),
  ('task.view.team','View team tasks'),
  ('task.view.own','View own tasks'),
  ('reminder.manage.own','Manage own reminders'),
  ('reminder.manage.team','Create reminders for team'),
  ('meeting.view.own','View own meetings'),
  ('meeting.manage','Create/edit meetings'),
  ('broadcast.send','Send broadcasts'),
  ('report.view.team','View team reports'),
  ('report.view.all','View org-wide reports'),
  ('user.manage','Manage users/teams/roles'),
  ('jira.view.own','View own Jira issues'),
  ('integration.manage','Configure integrations');

-- admin: all permissions
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p WHERE r.name='admin';

-- manager
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p
  ON p.code IN ('task.create','task.assign','task.update.any','task.view.team',
                'task.view.own','reminder.manage.own','reminder.manage.team',
                'meeting.view.own','meeting.manage','broadcast.send',
                'report.view.team','jira.view.own')
WHERE r.name='manager';

-- employee
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p
  ON p.code IN ('task.create','task.update.own','task.view.own',
                'reminder.manage.own','meeting.view.own','jira.view.own')
WHERE r.name='employee';
