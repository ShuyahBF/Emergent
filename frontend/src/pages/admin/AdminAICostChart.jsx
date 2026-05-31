// Iter38r-fix9z5 — Cross-tenant AI monthly cost chart for the admin dashboard.
// Plots last 12 months of total AI spend (sum across all tenants).
import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { Brain, TrendingUp, AlertCircle } from "lucide-react";

const MONTH_LABELS_FR = {
  "01": "Jan", "02": "Fév", "03": "Mar", "04": "Avr", "05": "Mai", "06": "Juin",
  "07": "Juil", "08": "Août", "09": "Sep", "10": "Oct", "11": "Nov", "12": "Déc",
};

export default function AdminAICostChart() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [range, setRange] = useState(12);

  useEffect(() => {
    let cancelled = false;
    apiClient
      .get(`/admin/ai-costs/monthly?months=${range}`)
      .then((r) => { if (!cancelled) { setData(r.data); setErr(null); } })
      .catch((e) => { if (!cancelled) setErr(e?.response?.data?.detail || "Erreur"); });
    return () => { cancelled = true; };
  }, [range]);

  const series = data?.series || [];
  const maxVal = useMemo(() => Math.max(1, ...series.map((s) => s.total_xof || 0)), [series]);
  const totals = data?.totals || { period_xof: 0, average_monthly_xof: 0 };

  if (err) {
    return (
      <section className="rounded-xl border border-slate-200 bg-white p-5" data-testid="admin-ai-cost-chart">
        <div className="flex items-center gap-2 text-rose-600 text-sm">
          <AlertCircle className="h-4 w-4" /> Impossible de charger les coûts IA : {err}
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5" data-testid="admin-ai-cost-chart">
      <div className="flex items-center justify-between flex-wrap gap-3 mb-3">
        <div className="flex items-center gap-2">
          <div className="h-10 w-10 rounded-lg bg-fuchsia-50 flex items-center justify-center">
            <Brain className="h-5 w-5 text-fuchsia-600" />
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Coûts IA</p>
            <h2 className="font-display font-bold text-slate-900">Consommation mensuelle — tous tenants</h2>
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs">
          {[3, 6, 12, 24].map((m) => (
            <button
              key={m}
              onClick={() => setRange(m)}
              className={`px-2.5 py-1 rounded ring-1 transition ${
                range === m
                  ? "bg-fuchsia-600 text-white ring-fuchsia-700"
                  : "bg-white text-slate-700 ring-slate-300 hover:ring-fuchsia-400"
              }`}
              data-testid={`ai-cost-range-${m}`}
            >
              {m} mois
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs mb-4">
        <div className="rounded-lg bg-slate-50 p-3">
          <p className="uppercase tracking-wider text-slate-500 text-[10px]">Total période</p>
          <p className="font-display font-bold text-slate-900 text-lg tabular-nums">
            {Math.round(totals.period_xof).toLocaleString("fr-FR")} {data?.currency || "XOF"}
          </p>
        </div>
        <div className="rounded-lg bg-slate-50 p-3">
          <p className="uppercase tracking-wider text-slate-500 text-[10px]">Moyenne mensuelle</p>
          <p className="font-display font-bold text-slate-900 text-lg tabular-nums">
            {Math.round(totals.average_monthly_xof).toLocaleString("fr-FR")} {data?.currency || "XOF"}
          </p>
        </div>
        <div className="rounded-lg bg-slate-50 p-3 col-span-2 sm:col-span-1">
          <p className="uppercase tracking-wider text-slate-500 text-[10px] inline-flex items-center gap-1">
            <TrendingUp className="h-3 w-3" /> Mois en cours
          </p>
          <p className="font-display font-bold text-slate-900 text-lg tabular-nums">
            {series.length > 0 ? Math.round(series[series.length - 1].total_xof).toLocaleString("fr-FR") : "0"} {data?.currency || "XOF"}
          </p>
        </div>
      </div>

      {/* Bar chart */}
      <div className="flex items-end gap-1.5 h-32" data-testid="ai-cost-bars">
        {series.map((s, i) => {
          const v = s.total_xof || 0;
          const h = maxVal > 0 ? Math.max(3, (v / maxVal) * 100) : 3;
          const [, mm] = (s.year_month || "").split("-");
          const isCurrent = i === series.length - 1;
          return (
            <div key={s.year_month} className="flex-1 flex flex-col items-center gap-1 min-w-0" title={`${s.year_month} · ${Math.round(v).toLocaleString("fr-FR")} XOF · ${s.tenant_count} tenants`}>
              <div
                className={`w-full rounded-t transition-all ${
                  isCurrent
                    ? "bg-gradient-to-t from-fuchsia-600 to-fuchsia-400 ring-1 ring-fuchsia-700"
                    : "bg-gradient-to-t from-sky-500 to-sky-300"
                }`}
                style={{ height: `${h}%` }}
                data-testid={`ai-cost-bar-${s.year_month}`}
              />
              <span className="text-[9px] text-slate-500 truncate w-full text-center">{MONTH_LABELS_FR[mm] || mm}</span>
            </div>
          );
        })}
        {series.length === 0 && (
          <p className="text-xs text-slate-400 italic mx-auto">Pas encore de consommation IA enregistrée.</p>
        )}
      </div>
    </section>
  );
}
