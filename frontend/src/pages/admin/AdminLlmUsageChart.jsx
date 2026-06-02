// S-iter39n — Universal Key daily consumption chart (S032 sister).
// Plots last N days of LLM usage from `llm_usage_log` in USD.
// Mounted on the AdminDashboard so the admin sees the burn pattern at
// a glance — complements the existing AdminAICostChart (XOF/tenant cost).
import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { Brain, AlertCircle, TrendingUp } from "lucide-react";

const CONTEXT_COLORS = {
  liluvine_chat: "bg-fuchsia-500",
  liluvine_wa_autoreply: "bg-indigo-500",
  kb_enrich: "bg-emerald-500",
  kb_ocr: "bg-teal-500",
  campaign_plan: "bg-amber-500",
  ai_media: "bg-orange-500",
  health_probe: "bg-slate-300",
  default: "bg-slate-400",
};

const CONTEXT_LABELS = {
  liluvine_chat: "Chat Liluvine",
  liluvine_wa_autoreply: "Auto-réponse WA",
  kb_enrich: "Enrichissement KB",
  kb_ocr: "OCR KB",
  campaign_plan: "Plan IA campagnes",
  ai_media: "Génération média",
  health_probe: "Sonde santé",
  default: "Divers",
};

export default function AdminLlmUsageChart() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [days, setDays] = useState(30);

  useEffect(() => {
    let cancelled = false;
    apiClient
      .get(`/admin/llm-health/usage-chart?days=${days}`)
      .then((r) => { if (!cancelled) { setData(r.data); setErr(null); } })
      .catch((e) => { if (!cancelled) setErr(e?.response?.data?.detail || "Erreur"); });
    return () => { cancelled = true; };
  }, [days]);

  const series = data?.series || [];
  const maxVal = useMemo(() => Math.max(0.0001, data?.max_cost_usd || 0), [data]);

  // Aggregate per-context totals over the period
  const ctxTotals = useMemo(() => {
    const out = {};
    for (const row of series) {
      const by = row.by_context || {};
      for (const [k, v] of Object.entries(by)) out[k] = (out[k] || 0) + Number(v);
    }
    return Object.entries(out)
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => ({ context: k, cost_usd: v }));
  }, [series]);

  if (err) {
    return (
      <section className="rounded-xl border border-slate-200 bg-white p-5" data-testid="admin-llm-usage-chart">
        <div className="flex items-center gap-2 text-rose-600 text-sm">
          <AlertCircle className="h-4 w-4" /> Impossible de charger la consommation IA : {err}
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5" data-testid="admin-llm-usage-chart">
      <div className="flex items-center justify-between flex-wrap gap-3 mb-3">
        <div className="flex items-center gap-2">
          <div className="h-10 w-10 rounded-lg bg-indigo-50 flex items-center justify-center">
            <Brain className="h-5 w-5 text-indigo-600" />
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Universal Key Emergent</p>
            <h2 className="font-display font-bold text-slate-900">Consommation IA — {days} derniers jours</h2>
          </div>
        </div>
        <select
          value={days}
          onChange={(e) => setDays(parseInt(e.target.value, 10))}
          className="text-xs rounded-lg ring-1 ring-slate-300 px-2.5 py-1.5"
          data-testid="llm-usage-chart-range"
        >
          <option value={7}>7 jours</option>
          <option value={14}>14 jours</option>
          <option value={30}>30 jours</option>
          <option value={60}>60 jours</option>
          <option value={90}>90 jours</option>
        </select>
      </div>

      {/* KPI cards */}
      <div className="grid sm:grid-cols-3 gap-3 mb-4">
        <div className="rounded-lg bg-indigo-50 ring-1 ring-indigo-100 p-3">
          <p className="text-[11px] uppercase text-indigo-700 font-semibold">Total période</p>
          <p className="text-xl font-bold text-indigo-900 mt-1" data-testid="llm-usage-chart-total">
            ${(data?.totals?.cost_usd ?? 0).toFixed(4)} USD
          </p>
        </div>
        <div className="rounded-lg bg-fuchsia-50 ring-1 ring-fuchsia-100 p-3">
          <p className="text-[11px] uppercase text-fuchsia-700 font-semibold">Appels IA</p>
          <p className="text-xl font-bold text-fuchsia-900 mt-1" data-testid="llm-usage-chart-calls">
            {data?.totals?.calls ?? 0}
          </p>
        </div>
        <div className="rounded-lg bg-emerald-50 ring-1 ring-emerald-100 p-3">
          <p className="text-[11px] uppercase text-emerald-700 font-semibold">Pic journalier</p>
          <p className="text-xl font-bold text-emerald-900 mt-1 inline-flex items-center gap-1">
            <TrendingUp className="h-4 w-4" />
            ${maxVal.toFixed(4)}
          </p>
        </div>
      </div>

      {/* Bar chart (CSS only, no chart lib dependency) */}
      <div className="relative">
        {series.length === 0 || maxVal <= 0.0001 ? (
          <p className="text-xs text-slate-400 italic py-8 text-center">
            Pas encore de consommation IA enregistrée sur cette période.
          </p>
        ) : (
          <div className="flex items-end gap-0.5 h-40 border-b border-slate-200 pb-1" data-testid="llm-usage-chart-bars">
            {series.map((row) => {
              const h = Math.max(2, (row.cost_usd / maxVal) * 100);
              const isToday = row.date === new Date().toISOString().slice(0, 10);
              return (
                <div
                  key={row.date}
                  className="flex-1 flex flex-col items-center group relative"
                  data-testid={`llm-usage-bar-${row.date}`}
                >
                  <div
                    className={`w-full rounded-t ${isToday ? "bg-fuchsia-600" : "bg-indigo-500"} hover:bg-indigo-700 transition`}
                    style={{ height: `${h}%` }}
                  />
                  {/* Tooltip on hover */}
                  <div className="absolute bottom-full mb-1 left-1/2 -translate-x-1/2 hidden group-hover:block bg-slate-900 text-white text-[10px] rounded px-2 py-1 whitespace-nowrap z-10 shadow-lg">
                    <strong>{row.date}</strong> : ${row.cost_usd.toFixed(4)} ({row.calls} appels)
                  </div>
                </div>
              );
            })}
          </div>
        )}
        <div className="flex justify-between text-[10px] text-slate-400 mt-1 px-0.5">
          <span>{series[0]?.date}</span>
          <span className="hidden sm:inline">{series[Math.floor(series.length / 2)]?.date}</span>
          <span>{series[series.length - 1]?.date}</span>
        </div>
      </div>

      {/* Per-context breakdown */}
      {ctxTotals.length > 0 && (
        <div className="mt-4 pt-4 border-t border-slate-100">
          <p className="text-xs font-semibold text-slate-700 mb-2">Répartition par fonctionnalité</p>
          <div className="space-y-1.5">
            {ctxTotals.map((c) => (
              <div key={c.context} className="flex items-center gap-2 text-xs">
                <div className={`h-3 w-3 rounded ${CONTEXT_COLORS[c.context] || CONTEXT_COLORS.default}`} />
                <span className="flex-1 text-slate-700">{CONTEXT_LABELS[c.context] || c.context}</span>
                <span className="font-mono text-slate-900 font-semibold">${c.cost_usd.toFixed(4)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
