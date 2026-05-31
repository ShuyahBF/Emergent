// Iter38r-fix9p — Velocity chart for sawali-portal project (super-admin only).
// Reads /admin/roadmap-actions, groups by iter prefix (= "Iter38r-fix9o" etc.)
// and aggregates duration_h + cost_xof per iter. Shows a stacked bar chart
// AND a per-project pie of total cost.
//
// Visible only when the logged-in admin email == "admin@sawalismartsystems.com"
// to avoid leaking internal velocity to other tenants.
import React, { useEffect, useMemo, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from "recharts";
import { Clock, Coins, TrendingUp } from "lucide-react";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";

const SAWALI_OWNER = "admin@sawalismartsystems.com";


export default function VelocityChart() {
  const { user } = useAuth() || {};
  const [items, setItems] = useState([]);
  const [totals, setTotals] = useState(null);
  const [loading, setLoading] = useState(true);
  const allowed = (user?.email || "").toLowerCase() === SAWALI_OWNER;

  useEffect(() => {
    if (!allowed) return;
    apiClient.get("/admin/roadmap-actions?limit=2000")
      .then((r) => {
        setItems(r.data?.items || []);
        setTotals(r.data?.totals || null);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [allowed]);

  // Group items by iter-code prefix (e.g. "Iter38r-fix9o", "Iter38n")
  const byIter = useMemo(() => {
    const map = new Map();
    for (const it of items) {
      const code = it.code || "";
      // Extract the leading iter-fix prefix: "Iter38r-fix9o-01" → "Iter38r-fix9o"
      const m = code.match(/^(Iter\d+[a-z]*(?:-fix\d+[a-z]*)?)/i);
      const key = m ? m[1] : "Other";
      const row = map.get(key) || { iter: key, h: 0, xof: 0, count: 0 };
      row.h += Number(it.duration_h || 0);
      row.xof += Number(it.cost_xof || 0);
      row.count += 1;
      map.set(key, row);
    }
    return Array.from(map.values())
      .filter((r) => r.h > 0 || r.xof > 0)
      .sort((a, b) => a.iter.localeCompare(b.iter));
  }, [items]);

  if (!allowed) return null;
  if (loading) {
    return (
      <div className="rounded-xl ring-1 ring-slate-200 bg-white p-4">
        <p className="text-xs text-slate-500">Chargement vélocité…</p>
      </div>
    );
  }
  if (byIter.length === 0) return null;

  const fmtXOF = (n) => `${Math.round(n).toLocaleString("fr-FR")} XOF`;
  const fmtH = (n) => `${Math.round(n * 10) / 10} h`;

  return (
    <section className="rounded-xl ring-1 ring-indigo-200 bg-gradient-to-br from-indigo-50/40 via-white to-fuchsia-50/30 p-5 space-y-4" data-testid="velocity-section">
      <header className="flex items-center gap-3">
        <div className="rounded-full bg-indigo-100 ring-1 ring-indigo-200 p-2">
          <TrendingUp className="h-5 w-5 text-indigo-700" />
        </div>
        <div>
          <h2 className="font-display font-bold text-slate-900">Vélocité — projet « sawali-portal »</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Visible uniquement pour <code className="bg-slate-100 px-1 rounded">{SAWALI_OWNER}</code>. Stats par itération / projet, extraites de l'historique de travail.
          </p>
        </div>
      </header>

      {totals && (
        <div className="grid sm:grid-cols-4 gap-3">
          <KpiCard icon={Clock} color="text-indigo-700" bg="bg-indigo-50" label="Heures totales" value={fmtH(totals.duration_h || 0)} />
          <KpiCard icon={Coins} color="text-emerald-700" bg="bg-emerald-50" label="Coût total" value={fmtXOF(totals.cost_xof || 0)} />
          <KpiCard icon={TrendingUp} color="text-fuchsia-700" bg="bg-fuchsia-50" label="Itérations" value={byIter.length} />
          <KpiCard icon={Clock} color="text-amber-700" bg="bg-amber-50" label="Actions" value={totals.count || items.length} />
        </div>
      )}

      <div className="rounded-lg bg-white ring-1 ring-slate-200 p-3">
        <h3 className="text-xs font-semibold text-slate-700 uppercase tracking-wider mb-2">Heures par itération</h3>
        <ResponsiveContainer width="100%" height={Math.max(220, byIter.length * 22)}>
          <BarChart data={byIter} layout="vertical" margin={{ left: 0, right: 30, top: 5, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 10 }} />
            <YAxis type="category" dataKey="iter" tick={{ fontSize: 10 }} width={130} />
            <Tooltip
              formatter={(v, name) => name === "h" ? [fmtH(v), "Heures"] : [fmtXOF(v), "Coût"]}
              labelStyle={{ fontSize: 11, fontWeight: 600 }}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar dataKey="h" name="Heures" fill="#6366f1" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="rounded-lg bg-white ring-1 ring-slate-200 p-3">
        <h3 className="text-xs font-semibold text-slate-700 uppercase tracking-wider mb-2">Détail par itération</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-xs" data-testid="velocity-table">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                <th className="text-left px-2 py-1.5">Itération</th>
                <th className="text-right px-2 py-1.5">Actions</th>
                <th className="text-right px-2 py-1.5">Heures</th>
                <th className="text-right px-2 py-1.5">Coût (XOF)</th>
              </tr>
            </thead>
            <tbody>
              {byIter.map((r) => (
                <tr key={r.iter} className="border-t border-slate-100">
                  <td className="px-2 py-1.5 font-mono text-[11px] text-indigo-900">{r.iter}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-slate-700">{r.count}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-slate-700">{fmtH(r.h)}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-emerald-700 font-medium">{fmtXOF(r.xof)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function KpiCard({ icon: Icon, color, bg, label, value }) {
  return (
    <div className={`rounded-lg ring-1 ring-slate-200 ${bg} p-3`}>
      <div className="flex items-center gap-2">
        <Icon className={`h-4 w-4 ${color}`} />
        <span className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">{label}</span>
      </div>
      <p className={`text-xl font-display font-bold tabular-nums mt-1 ${color}`}>{value}</p>
    </div>
  );
}
