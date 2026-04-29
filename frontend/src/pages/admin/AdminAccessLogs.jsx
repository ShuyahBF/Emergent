import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { Search, Download, RefreshCw } from "lucide-react";
import { toast } from "sonner";

export default function AdminAccessLogs() {
  const [items, setItems] = useState([]);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/access-logs", { params: { q: q || undefined, limit: 1000 } });
      setItems(r.data);
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setLoading(false); }
  };

  useEffect(() => { load().catch(() => {}); /* eslint-disable-next-line */ }, []);

  const exportCsv = async () => {
    try {
      const r = await apiClient.get("/admin/access-logs/export.csv", { params: { q: q || undefined } });
      const blob = new Blob([r.data?.csv || ""], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `access-logs-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur export"); }
  };

  const stats = useMemo(() => {
    const users = new Set();
    const modules = new Map();
    for (const it of items) {
      users.add(it.user_email);
      const m = it.module || "(autre)";
      modules.set(m, (modules.get(m) || 0) + 1);
    }
    const topModules = [...modules.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5);
    return { total: items.length, users: users.size, topModules };
  }, [items]);

  return (
    <div className="space-y-6" data-testid="admin-access-logs-page">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-display font-bold">Logs d'accès portail</h1>
          <p className="text-sm text-slate-500">Trace de chaque page consultée par les utilisateurs connectés. Réservé aux rôles Administrateur / Superviseur.</p>
        </div>
        <div className="flex gap-2">
          <button onClick={load} disabled={loading} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3.5 py-2 text-sm hover:border-sawali-blue hover:text-sawali-blue disabled:opacity-50" data-testid="logs-refresh">
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Actualiser
          </button>
          <button onClick={exportCsv} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-3.5 py-2 text-sm hover:bg-sawali-blue-light" data-testid="logs-export">
            <Download className="h-4 w-4" /> Exporter CSV
          </button>
        </div>
      </div>

      <div className="grid sm:grid-cols-3 gap-4">
        <Stat label="Événements" value={stats.total} testid="logs-stat-total" />
        <Stat label="Utilisateurs uniques" value={stats.users} testid="logs-stat-users" />
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Top modules</p>
          <ul className="mt-2 space-y-1 text-sm">
            {stats.topModules.length === 0 && <li className="text-slate-400">—</li>}
            {stats.topModules.map(([m, c]) => (
              <li key={m} className="flex justify-between"><span className="truncate pr-2">{m}</span><span className="text-slate-500 tabular-nums">{c}</span></li>
            ))}
          </ul>
        </div>
      </div>

      <form onSubmit={(e) => { e.preventDefault(); load(); }} className="flex items-center gap-2">
        <div className="flex-1 relative">
          <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Rechercher par email, nom, module ou page…"
            className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-slate-300 focus:border-sawali-blue focus:outline-none"
            data-testid="logs-search-input"
          />
        </div>
        <button type="submit" className="rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light">Rechercher</button>
      </form>

      <div className="rounded-xl border border-slate-200 bg-white overflow-x-auto">
        <table className="w-full text-sm min-w-[860px]">
          <thead className="bg-slate-50 text-xs uppercase tracking-widest text-slate-600">
            <tr>
              <th className="text-left px-4 py-3">Date</th>
              <th className="text-left px-4 py-3">Utilisateur</th>
              <th className="text-left px-4 py-3">Rôle</th>
              <th className="text-left px-4 py-3">Module</th>
              <th className="text-left px-4 py-3">Page</th>
              <th className="text-left px-4 py-3">IP</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-500">Aucun événement.</td></tr>}
            {items.map((it) => (
              <tr key={it.id} className="border-t border-slate-100" data-testid={`log-${it.id}`}>
                <td className="px-4 py-2 whitespace-nowrap text-slate-600">{new Date(it.created_at).toLocaleString("fr-FR")}</td>
                <td className="px-4 py-2">
                  <div className="font-medium">{it.user_name || "—"}</div>
                  <div className="text-xs text-slate-500">{it.user_email}</div>
                </td>
                <td className="px-4 py-2 text-xs">
                  <span className="bg-slate-100 px-2 py-0.5 rounded">{it.tracked_role || it.role || "—"}</span>
                </td>
                <td className="px-4 py-2">{it.module}</td>
                <td className="px-4 py-2 font-mono text-xs text-slate-500">{it.page}</td>
                <td className="px-4 py-2 font-mono text-xs text-slate-500">{it.ip || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const Stat = ({ label, value, testid }) => (
  <div className="rounded-xl border border-slate-200 bg-white p-5" data-testid={testid}>
    <p className="text-xs uppercase tracking-[0.2em] text-slate-500">{label}</p>
    <p className="text-3xl font-display font-bold text-slate-900 mt-1 tabular-nums">{value}</p>
  </div>
);
