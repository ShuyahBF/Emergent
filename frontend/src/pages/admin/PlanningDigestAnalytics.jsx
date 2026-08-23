// 2026-02 fork (analytics) — Digest médecin WhatsApp analytics widget.
// Affiche : totaux envois / ouvertures / taux d'engagement, breakdown journalier
// simple, et audit stream des 20 derniers événements.
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { CalendarClock, TrendingUp, Send, MousePointerClick } from "lucide-react";

const RANGE_OPTIONS = [
  { days: 7, label: "7 j" },
  { days: 30, label: "30 j" },
  { days: 90, label: "90 j" },
];

export default function PlanningDigestAnalytics() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    apiClient.get(`/admin/planning-digest/analytics`, { params: { days } })
      .then((r) => { if (alive) setData(r.data); })
      .catch(() => { if (alive) setData(null); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [days]);

  const totals = data?.totals || { sent: 0, opened: 0 };
  const rate = data?.engagement_rate_pct;
  const breakdown = data?.breakdown || [];
  const recent = data?.recent || [];

  return (
    <section
      className="rounded-xl border border-slate-200 bg-white p-5 space-y-4"
      data-testid="planning-digest-analytics"
    >
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-sky-500/10 flex items-center justify-center">
            <CalendarClock className="h-5 w-5 text-sky-600" />
          </div>
          <div>
            <h2 className="font-display font-bold text-lg">Planning médecin — Digest WhatsApp</h2>
            <p className="text-xs text-slate-500">Envois automatiques et ouvertures via le lien de connexion rapide.</p>
          </div>
        </div>
        <div className="flex items-center gap-1 rounded-lg ring-1 ring-slate-200 bg-slate-50 p-1" data-testid="digest-range-picker">
          {RANGE_OPTIONS.map((opt) => (
            <button
              key={opt.days}
              type="button"
              onClick={() => setDays(opt.days)}
              className={`text-xs px-3 py-1 rounded-md transition ${days === opt.days ? "bg-sky-500 text-white shadow-sm" : "text-slate-600 hover:bg-slate-100"}`}
              data-testid={`digest-range-${opt.days}`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="text-xs text-slate-500 italic" data-testid="digest-analytics-loading">Chargement des métriques…</div>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-3" data-testid="digest-analytics-totals">
            <MetricTile icon={Send} label="Envois" value={totals.sent} accent="#0ea5e9" testid="digest-metric-sent" />
            <MetricTile icon={MousePointerClick} label="Ouvertures" value={totals.opened} accent="#22c55e" testid="digest-metric-opened" />
            <MetricTile icon={TrendingUp} label="Taux d'engagement" value={rate === null || rate === undefined ? "—" : `${rate}%`} accent="#f97316" testid="digest-metric-rate" />
          </div>

          {breakdown.length > 0 && (
            <div className="rounded-lg ring-1 ring-slate-200 overflow-hidden" data-testid="digest-analytics-breakdown">
              <table className="w-full text-xs">
                <thead className="bg-slate-50 text-slate-500">
                  <tr>
                    <th className="text-left px-3 py-2 font-medium">Jour</th>
                    <th className="text-right px-3 py-2 font-medium">Envois</th>
                    <th className="text-right px-3 py-2 font-medium">Ouvertures</th>
                    <th className="text-right px-3 py-2 font-medium">Taux</th>
                  </tr>
                </thead>
                <tbody>
                  {breakdown.slice(-14).reverse().map((row) => (
                    <tr key={row.day} className="border-t border-slate-100" data-testid={`digest-row-${row.day}`}>
                      <td className="px-3 py-2 font-mono text-slate-700">{row.day}</td>
                      <td className="text-right px-3 py-2 tabular-nums">{row.sent}</td>
                      <td className="text-right px-3 py-2 tabular-nums">{row.opened}</td>
                      <td className="text-right px-3 py-2 tabular-nums">{row.rate === null ? "—" : `${row.rate}%`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {recent.length > 0 && (
            <details className="rounded-lg ring-1 ring-slate-200 bg-slate-50" data-testid="digest-analytics-recent">
              <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-slate-700">
                20 derniers événements
              </summary>
              <ul className="px-3 pb-3 text-xs text-slate-600 space-y-1">
                {recent.map((ev) => (
                  <li key={ev.id} className="flex items-center gap-2 truncate">
                    <span className={`inline-block h-2 w-2 rounded-full ${ev.kind === "sent" ? "bg-sky-500" : "bg-emerald-500"}`} />
                    <span className="font-mono text-[10px] text-slate-400">{ev.at?.slice(0, 19)?.replace("T", " ")}</span>
                    <span className="font-semibold">{ev.kind === "sent" ? "Envoi" : "Ouverture"}</span>
                    <span className="text-slate-500 truncate">{ev.email}</span>
                    {ev.rdv_count !== undefined && <span className="text-slate-400">({ev.rdv_count} RDV)</span>}
                  </li>
                ))}
              </ul>
            </details>
          )}

          {breakdown.length === 0 && !loading && (
            <p className="text-xs italic text-slate-500" data-testid="digest-analytics-empty">
              Aucun envoi ni ouverture sur la période. Les métriques apparaîtront ici dès que les cronjobs et deep-links auront été utilisés.
            </p>
          )}
        </>
      )}
    </section>
  );
}

function MetricTile({ icon: Icon, label, value, accent, testid }) {
  return (
    <div className="rounded-lg bg-slate-50 p-3 flex items-center gap-3" data-testid={testid}>
      <div className="h-9 w-9 rounded-md flex items-center justify-center" style={{ background: `${accent}18` }}>
        <Icon className="h-4 w-4" style={{ color: accent }} />
      </div>
      <div>
        <p className="text-[10px] uppercase tracking-widest text-slate-500">{label}</p>
        <p className="text-2xl font-display font-bold text-slate-900 leading-tight">{value}</p>
      </div>
    </div>
  );
}
