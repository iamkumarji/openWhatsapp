import "./globals.css";
import type { ReactNode } from "react";

export const metadata = { title: "WAINT Portal", description: "WhatsApp AI Team Assistant" };

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/tasks", label: "Tasks" },
  { href: "/meetings", label: "Meetings" },
  { href: "/reminders", label: "Reminders" },
  { href: "/reports", label: "Reports" },
  { href: "/broadcast", label: "Broadcast" },
  { href: "/admin", label: "Admin" },
];

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50 text-slate-900">
        <div className="flex">
          <aside className="hidden w-56 shrink-0 border-r border-slate-200 bg-white p-4 md:block">
            <p className="mb-6 text-lg font-bold">WAINT</p>
            <nav className="space-y-1">
              {NAV.map((n) => (
                <a key={n.href} href={n.href} className="block rounded-lg px-3 py-2 text-sm hover:bg-slate-100">
                  {n.label}
                </a>
              ))}
            </nav>
          </aside>
          <div className="flex-1">{children}</div>
        </div>
      </body>
    </html>
  );
}
