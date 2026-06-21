// Typed API client. Attaches the Keycloak JWT to every request.
import { getToken } from "./auth";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api/v1";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await getToken();
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers ?? {}),
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.error?.message ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export interface DashboardData {
  today: { items: number };
  overdue_tasks: number;
  next_meeting: { title: string; starts_at: string; join_url?: string } | null;
  jira_open: number;
  role: "admin" | "manager" | "employee";
}

export interface TaskOut {
  id: string;
  title: string;
  status: string;
  priority: string;
  due_at: string | null;
}

export const api = {
  dashboard: () => request<DashboardData>("/dashboard"),
  listTasks: (q = "") => request<{ count: number; items: TaskOut[] }>(`/tasks${q}`),
  createTask: (body: Partial<TaskOut> & { title: string }) =>
    request<{ id: string }>("/tasks", { method: "POST", body: JSON.stringify(body) }),
  createReminder: (body: { body: string; natural_time?: string; fire_at?: string }) =>
    request<{ id: string }>("/reminders", { method: "POST", body: JSON.stringify(body) }),
  broadcast: (body: { audience: object; body: string }) =>
    request<{ id: string }>("/broadcasts", { method: "POST", body: JSON.stringify(body) }),
};
