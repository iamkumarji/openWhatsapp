"use client";
import { useEffect, useState } from "react";
import { api, DashboardData } from "@/lib/api";
import { initAuth } from "@/lib/auth";

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <p className="text-sm text-slate-500">{label}</p>
      <p className="mt-1 text-3xl font-semibold text-slate-900">{value}</p>
    </div>
  );
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        await initAuth();
        setData(await api.dashboard());
      } catch (e) {
        setErr((e as Error).message);
      }
    })();
  }, []);

  if (err) return <p className="p-8 text-red-600">Error: {err}</p>;
  if (!data) return <p className="p-8 text-slate-500">Loading…</p>;

  return (
    <main className="mx-auto max-w-5xl p-8">
      <h1 className="mb-6 text-2xl font-bold text-slate-900">Dashboard</h1>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard label="Items today" value={data.today.items} />
        <StatCard label="Overdue tasks" value={data.overdue_tasks} />
        <StatCard label="Open Jira issues" value={data.jira_open} />
        <StatCard label="Role" value={data.role} />
      </div>

      {data.next_meeting && (
        <section className="mt-8 rounded-2xl border border-slate-200 bg-white p-5">
          <h2 className="text-lg font-semibold">Next meeting</h2>
          <p className="mt-1 text-slate-700">{data.next_meeting.title}</p>
          <p className="text-sm text-slate-500">{new Date(data.next_meeting.starts_at).toLocaleString()}</p>
          {data.next_meeting.join_url && (
            <a className="mt-2 inline-block text-blue-600 hover:underline" href={data.next_meeting.join_url}>
              Join →
            </a>
          )}
        </section>
      )}
    </main>
  );
}
