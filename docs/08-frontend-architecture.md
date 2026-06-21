# 08 — Web Portal Architecture

Next.js 14 (App Router) + React + TypeScript + Tailwind. Auth via Keycloak
(OIDC Authorization Code + PKCE). Data via the typed `lib/api.ts` client (Bearer JWT).
Server Components for read-heavy pages; Client Components for interactive forms.

## Page hierarchy (role-gated)

```
/(public)
  /login                      → Keycloak redirect

/(app)  [requires auth; nav items hidden by role]
  /dashboard                  → role-aware widgets (all roles)
  /tasks
    /tasks                    → list + filters (own / team for managers)
    /tasks/new                → create (assign others = manager+)
    /tasks/[id]               → detail, comments, attachments, status
  /meetings                   → internal + Zoom + calendar aggregated
    /meetings/[id]            → detail + join link
  /reminders                  → own reminders; create one-off/recurring
  /reports        [manager+]  → team summary, overdue, throughput, export
  /calendar                   → daily/weekly schedule, availability
  /jira                       → mirrored issues, sprint board overview
  /broadcast      [manager+]  → compose, audience picker, delivery stats
  /admin          [admin]
    /admin/users              → users CRUD, WA enrollment codes
    /admin/teams              → teams & manager assignment
    /admin/roles              → roles & permission matrix
    /admin/integrations       → Jira/Zoom/Google/Outlook config
    /admin/audit              → audit log viewer
```

## Component structure

```
src/
  app/                        # routes (above)
  components/
    layout/   AppShell, Sidebar, Topbar, RoleGate
    data/     DataTable, Pagination, FilterBar, EmptyState
    tasks/    TaskCard, TaskForm, TaskStatusBadge, AssigneePicker, CommentThread
    meetings/ MeetingList, MeetingCard, JoinButton
    reminders/ ReminderForm (NL time input), ReminderList, RRuleBuilder
    reports/  StatCard, CompletionChart, OverdueTable, ExportMenu
    broadcast/ AudiencePicker, BroadcastComposer, DeliveryStats
    ui/       Button, Input, Select, Dialog, Toast (Tailwind primitives)
  lib/
    api.ts    typed REST client (Bearer JWT)
    auth.ts   keycloak-js init, token refresh, hasRole()
    rbac.ts   client-side permission helpers (UI gating only; server is source of truth)
    hooks/    useDashboard, useTasks, useReminders (SWR/React Query)
```

## State & data

- **Server state:** React Query / SWR with the `api` client; cache keyed per resource.
- **Auth state:** `keycloak-js` singleton; silent token refresh 30s before expiry.
- **RBAC in UI:** `RoleGate`/`rbac.ts` only *hide* controls for UX. Every action is
  re-authorized server-side — the UI is never the security boundary.
- **Realtime (phase 3):** SSE/WebSocket channel for live task/broadcast updates.

## Accessibility & UX
- Keyboard-navigable tables and dialogs, focus traps, ARIA labels.
- Mobile-first (managers often approve on phones); sidebar collapses under `md`.
- Optimistic updates on status changes with toast rollback on failure.
