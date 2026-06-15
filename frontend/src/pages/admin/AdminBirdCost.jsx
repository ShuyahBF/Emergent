// Iter43-fix24f (2026-06) — Dashboard de coût Bird SMS avec graphique temporel
import React, { useCallback, useEffect, useState } from "react";
import { CircleDollarSign, RefreshCcw, Smartphone, TrendingUp, Calendar } from "lucide-react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";

const fmtMoney = (v, currency) => {
  try {
    return new Intl.NumberFormat("fr-FR", { style: "currency", currency: currency || "XOF", maximumFractionDigits: 0 }).format(v);
  } catch {
    return `${v} ${currency || ""}`.trim();
  }
};

export default function AdminBirdCost() {
  const [summary, setSummary] = useState(null);
  const [series, setSeries] = useState(null);
  const [daysWindow, setDaysWindow] = useState(30);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [a, b] = await Promise.all([
        apiClient.get("/admin/bird/cost-summary"),
        apiClient.get(`/admin/bird/cost-daily-series?days=${daysWindow}`),
      ]);
      setSummary(a.data);
      setSeries(b.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur de chargement");
    } finally { setLoading(false); }
  }, [daysWindow]);
  useEffect(() => { load(); }, [load]);

  const maxCount = series?.series?.reduce((m, d) => Math.max(m, d.count), 0) || 1;
  const currency = summary?.currency || "XOF";

  return (
    <div className="p-6 max-w-7xl mx-auto" data-testid="bird-cost-page">
      <header className="flex items-center gap-3 mb-4">
        <CircleDollarSign className="h-6 w-6 text-sky-600" />
        <div>
          <h1 className="text-2xl font-display font-bold">Coût SMS Bird</h1>
          <p className="text-xs text-slate-500">
            Suivi du nombre de SMS Bird envoyés et coût estimé. Le coût unitaire est configuré dans
            <code className="mx-1 px-1 bg-slate-100 rounded">Paramètres → Bird.com</code>.
          </p>
        </div>
        <button onClick={load} className="ml-auto text-xs px-3 py-2 rounded bg-white ring-1 ring-slate-300 hover:bg-slate-50">
          <RefreshCcw className="h-3 w-3 inline mr-1" /> Rafraîchir
        </button>
      </header>

      {loading && !summary ? (
        <div className="text-center py-12 text-slate-400">Chargement…</div>
      ) : (
        <>
          {/* KPIs */}
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 mb-6">
            <Kpi label="Aujourd'hui" count={summary?.today?.count || 0} cost={summary?.today?.cost || 0} currency={currency} highlight />
            <Kpi label="Hier" count={summary?.yesterday?.count || 0} cost={summary?.yesterday?.cost || 0} currency={currency} />
            <Kpi label="7 derniers jours" count={summary?.last_7_days?.count || 0} cost={summary?.last_7_days?.cost || 0} currency={currency} />
            <Kpi label="30 derniers jours" count={summary?.last_30_days?.count || 0} cost={summary?.last_30_days?.cost || 0} currency={currency} />
            <Kpi label="Total" count={summary?.total?.count || 0} cost={summary?.total?.cost || 0} currency={currency} />
          </div>

          {/* Bar chart */}
          <div className="bg-white ring-1 ring-slate-200 rounded-lg p-5 mb-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <TrendingUp className="h-4 w-4 text-sky-600" />
                <h2 className="text-sm font-semibold">Évolution journalière</h2>
              </div>
              <select
                value={daysWindow}
                onChange={(e) => setDaysWindow(parseInt(e.target.value, 10))}
                className="px-2 py-1 border rounded text-xs bg-white"
                data-testid="window-select"
              >
                <option value="7">7 jours</option>
                <option value="14">14 jours</option>
                <option value="30">30 jours</option>
                <option value="90">90 jours</option>
              </select>
            </div>
            {series && series.total_count === 0 ? (
              <div className="py-12 text-center text-slate-400 text-sm">
                <Smartphone className="h-8 w-8 mx-auto opacity-40" />
                <p className="mt-3">Aucun SMS Bird envoyé sur cette période.</p>
                <p className="text-xs mt-1">Coût unitaire configuré : {fmtMoney(series?.unit_cost || 0, currency)} / SMS</p>
              </div>
            ) : (
              <div className="space-y-1" data-testid="bar-chart">
                {series?.series?.map((d) => {
                  const widthPct = Math.max(2, (d.count / maxCount) * 100);
                  const isToday = d.date === new Date().toISOString().slice(0, 10);
                  return (
                    <div key={d.date} className="flex items-center gap-2 text-xs">
                      <span className={`w-20 text-slate-500 ${isToday ? "font-bold text-sky-700" : ""}`}>
                        {d.date.slice(5)} {isToday && "·"}
                      </span>
                      <div className="flex-1 flex items-center gap-2">
                        <div className="flex-1 bg-slate-100 rounded h-5 overflow-hidden relative">
                          <div
                            className={`h-full transition-all ${isToday ? "bg-sky-600" : "bg-sky-400"}`}
                            style={{ width: `${widthPct}%` }}
                          />
                        </div>
                        <span className="w-12 text-right font-medium tabular-nums">{d.count}</span>
                        <span className="w-24 text-right text-slate-500 tabular-nums">
                          {d.count > 0 ? fmtMoney(d.cost, currency) : "—"}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Footer info */}
          <div className="text-xs text-slate-500 bg-slate-50 rounded p-3">
            💡 <strong>Coût unitaire</strong> : {fmtMoney(series?.unit_cost || 25, currency)} par SMS ({currency}).
            Modifiable dans <code className="mx-1 px-1 bg-white rounded">Paramètres → Bird.com</code>.
            Les coûts sont des <strong>estimations basées sur ce taux fixe</strong> ; les coûts réels facturés par
            Bird peuvent varier selon l'opérateur destination et la taille du message.
          </div>
        </>
      )}
    </div>
  );
}

function Kpi({ label, count, cost, currency, highlight }) {
  return (
    <div className={`rounded-lg p-4 ${highlight ? "bg-sky-50 ring-1 ring-sky-200" : "bg-white ring-1 ring-slate-200"}`} data-testid={`kpi-${label.toLowerCase().replace(/\s/g, "-")}`}>
      <p className="text-[10px] uppercase tracking-wider text-slate-500 flex items-center gap-1">
        <Calendar className="h-3 w-3" /> {label}
      </p>
      <p className="mt-2 text-2xl font-display font-bold text-slate-900">
        {fmtMoney(cost, currency)}
      </p>
      <p className="text-xs text-slate-500 mt-0.5">
        {count} SMS
      </p>
    </div>
  );
}
