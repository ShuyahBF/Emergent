// 2026-02 — Monthly presence card for /portal/users (admin & tracked users).
// Top 10 employees by accumulated hours for the selected month. Bar chart.
import React, { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { BarChart3, RefreshCw, ChevronLeft, ChevronRight, Loader2 } from "lucide-react";

function _now() { return new Date(); }
function _currentMonth() {
  const d = _now();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
function _formatMonth(yyyymm) {
  if (!yyyymm) return "";
  const [y, m] = yyyymm.split("-");
  const d = new Date(Number(y), Number(m) - 1, 1);
  return d.toLocaleDateString("fr-FR", { month: "long", year: "numeric" });
}
function _shiftMonth(yyyymm, delta) {
  const [y, m] = yyyymm.split("-").map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default function MonthlyPresenceCard() {
  const [month, setMonth] = useState(_currentMonth());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [unavailable, setUnavailable] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setUnavailable(false);
    try {
      const r = await apiClient.get("/hr/dashboard/monthly-presence", { params: { month } });
      setData(r.data);
    } catch (err) {
      if (err?.response?.status === 403) {
        setUnavailable(true);
      } else {
        setData(null);
      }
    } finally {
      setLoading(false);
    }
  }, [month]);

  useEffect(() => { refresh(); }, [refresh]);

  if (unavailable) return null; // Hide the card when HR module isn't accessible

  const top = data?.top || [];
  const maxHours = Math.max(1, ...top.map((t) => t.hours));
  const isCurrentMonth = month === _currentMonth();

  return (
    <div
      className="bg-gradient-to-br from-blue-50 to-emerald-50 border border-blue-100 rounded-xl p-4"
      data-testid="monthly-presence-card"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <h3 className="text-sm font-semibold text-slate-700 flex items-center gap-2">
          <BarChart3 size={16} className="text-blue-600" />
          Présence ce mois
          <span className="text-xs text-slate-400 font-normal capitalize">
            · {_formatMonth(month)}
          </span>
        </h3>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setMonth(_shiftMonth(month, -1))}
            className="rounded-md ring-1 ring-slate-300 hover:bg-slate-50 px-1.5 py-1 text-slate-600"
            title="Mois précédent"
            data-testid="monthly-prev-btn"
          >
            <ChevronLeft size={14} />
          </button>
          <input
            type="month"
            value={month}
            onChange={(e) => setMonth(e.target.value || _currentMonth())}
            className="rounded-md ring-1 ring-slate-300 bg-white px-2 py-1 text-xs font-mono"
            data-testid="monthly-month-input"
          />
          <button
            onClick={() => setMonth(_shiftMonth(month, +1))}
            disabled={isCurrentMonth}
            className="rounded-md ring-1 ring-slate-300 hover:bg-slate-50 px-1.5 py-1 text-slate-600 disabled:opacity-40 disabled:cursor-not-allowed"
            title="Mois suivant"
            data-testid="monthly-next-btn"
          >
            <ChevronRight size={14} />
          </button>
          <button
            onClick={refresh}
            className="rounded-md ring-1 ring-slate-300 hover:bg-slate-50 px-1.5 py-1 text-slate-600"
            title="Rafraîchir"
            data-testid="monthly-refresh-btn"
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          </button>
        </div>
      </div>
      {loading && top.length === 0 ? (
        <div className="text-xs text-slate-500 py-6 text-center" data-testid="monthly-loading">Chargement…</div>
      ) : top.length === 0 ? (
        <div className="text-xs text-slate-500 py-6 text-center" data-testid="monthly-empty">
          Aucune activité enregistrée sur {_formatMonth(month)}.
        </div>
      ) : (
        <div className="space-y-2">
          {top.map((t, idx) => {
            const pct = Math.round((t.hours / maxHours) * 100);
            return (
              <div key={t.employee_id || idx} className="flex items-center gap-3" data-testid={`monthly-bar-${idx}`}>
                <div className="w-32 text-xs text-slate-600 truncate" title={t.name}>{t.name || "—"}</div>
                <div className="flex-1 bg-slate-200 rounded-full h-2.5 overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-blue-500 to-emerald-500 transition-all"
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <div className="w-20 text-xs text-slate-700 font-medium text-right tabular-nums">{t.hours} h</div>
                <div className="w-12 text-xs text-slate-500 text-right tabular-nums">{t.days}j</div>
              </div>
            );
          })}
        </div>
      )}
      <p className="text-xs text-slate-400 mt-3">
        Top 10 des employés par heures cumulées sur le mois sélectionné. Source : access_logs.
      </p>
    </div>
  );
}
