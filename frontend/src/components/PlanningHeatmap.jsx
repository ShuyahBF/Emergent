// Iter43-fix24az-ad (2026-07-22) — Mini heatmap 30 jours pour le planning.
// Grille compacte (5×6 par défaut pour 30 jours) où chaque cellule est teintée
// selon la densité (RDV + walk-ins). Clic → saute au jour sélectionné.
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Loader2 } from "lucide-react";

function densityClass(total) {
  if (total <= 0) return "bg-slate-100 text-slate-400";
  if (total <= 2) return "bg-indigo-100 text-indigo-700";
  if (total <= 5) return "bg-indigo-300 text-white";
  if (total <= 10) return "bg-indigo-500 text-white";
  return "bg-indigo-700 text-white";
}

function shortDay(iso) {
  const [, m, d] = iso.split("-");
  return `${d}/${m}`;
}

export default function PlanningHeatmap({ fromDate, medecinId, days = 30, onSelectDate }) {
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const params = new URLSearchParams({ days: String(days) });
        if (fromDate) params.append("from_date", fromDate);
        if (medecinId) params.append("medecin_id", medecinId);
        const r = await apiClient.get(`/me/planning/heatmap?${params.toString()}`);
        if (!cancelled) setItems(r.data?.items || []);
      } catch (e) {
        if (!cancelled) setItems([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [fromDate, medecinId, days]);

  const busyDays = items.filter((i) => i.total > 0).length;
  const totalPatients = items.reduce((s, i) => s + i.total, 0);
  const peak = items.reduce((m, i) => Math.max(m, i.total), 0);

  return (
    <div
      className="rounded-lg ring-1 ring-slate-200 bg-white p-3 space-y-2"
      data-testid="planning-heatmap"
    >
      <div className="flex items-center justify-between text-xs">
        <span className="font-semibold text-slate-700">Charge {days}j à venir</span>
        {loading && <Loader2 className="h-3 w-3 animate-spin text-slate-400" />}
      </div>
      <div className="grid grid-cols-6 gap-1">
        {items.map((entry) => (
          <button
            key={entry.date}
            type="button"
            onClick={() => onSelectDate?.(entry.date)}
            className={`text-[9px] font-medium rounded transition-transform hover:scale-105 hover:ring-1 hover:ring-indigo-400 aspect-square flex flex-col items-center justify-center ${densityClass(entry.total)}`}
            title={`${shortDay(entry.date)} — ${entry.rdv_count} RDV, ${entry.walk_in_count} sans RDV`}
            data-testid={`heatmap-cell-${entry.date}`}
          >
            <span className="text-[9px] leading-tight opacity-70">{shortDay(entry.date)}</span>
            {entry.total > 0 && (
              <span className="text-[10px] font-bold leading-tight">{entry.total}</span>
            )}
          </button>
        ))}
      </div>
      {!loading && items.length > 0 && (
        <div className="pt-2 border-t border-slate-100 space-y-1 text-[10px] text-slate-500">
          <div className="flex items-center justify-between">
            <span>Jours chargés</span>
            <span className="font-semibold text-slate-700">{busyDays}/{items.length}</span>
          </div>
          <div className="flex items-center justify-between">
            <span>Total patients</span>
            <span className="font-semibold text-slate-700">{totalPatients}</span>
          </div>
          <div className="flex items-center justify-between">
            <span>Pic journalier</span>
            <span className="font-semibold text-slate-700">{peak}</span>
          </div>
        </div>
      )}
      {/* Légende densité */}
      <div className="flex items-center gap-1 pt-2 border-t border-slate-100 text-[9px] text-slate-500">
        <span>Moins</span>
        <span className="w-3 h-3 rounded bg-slate-100 ring-1 ring-slate-200"></span>
        <span className="w-3 h-3 rounded bg-indigo-100"></span>
        <span className="w-3 h-3 rounded bg-indigo-300"></span>
        <span className="w-3 h-3 rounded bg-indigo-500"></span>
        <span className="w-3 h-3 rounded bg-indigo-700"></span>
        <span>Plus</span>
      </div>
    </div>
  );
}
