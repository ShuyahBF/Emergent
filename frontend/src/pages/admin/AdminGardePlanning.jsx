// Iter43-fix22 (2026-06) — Planning hebdomadaire des Groupes de Garde.
// Affiche les 52/53 semaines de l'année avec leur groupe affecté.
// Permet override manuel + génération auto (séquentielle).
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Calendar, RefreshCcw, Lock, Unlock, Wand2 } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

export default function AdminGardePlanning() {
  const [year, setYear] = useState(() => new Date().getFullYear());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [startGroup, setStartGroup] = useState(1);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get(`/admin/officines-registry/garde-planning?year=${year}`);
      setData(r.data);
      if (r.data?.groups?.length) setStartGroup(r.data.groups[0]);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur chargement planning");
    } finally { setLoading(false); }
  }, [year]);
  useEffect(() => { load(); }, [load]);

  const generate = async () => {
    if (!data?.groups?.length) {
      toast.error("Aucun groupe défini sur les officines");
      return;
    }
    if (!window.confirm(
      `Générer le planning auto-séquentiel de ${year} en partant du groupe ${startGroup} ?\n\n`
      + "Les semaines en override manuel seront préservées."
    )) return;
    setGenerating(true);
    try {
      const r = await apiClient.post("/admin/officines-registry/garde-planning/generate", {
        year, start_group: startGroup,
      });
      toast.success(`${r.data.weeks_generated} semaines générées, ${r.data.weeks_kept_manual} overrides conservés`);
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec génération");
    } finally { setGenerating(false); }
  };

  const overrideWeek = async (week, newGroup) => {
    try {
      await apiClient.put(`/admin/officines-registry/garde-planning/${year}/${week}`, {
        groupe_garde: Number(newGroup),
      });
      toast.success(`Semaine ${week} forcée sur Groupe ${newGroup}`);
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec override");
    }
  };

  const resetWeek = async (week) => {
    if (!window.confirm(`Réinitialiser la semaine ${week} en mode automatique ?`)) return;
    try {
      await apiClient.delete(`/admin/officines-registry/garde-planning/${year}/${week}`);
      toast.success(`Semaine ${week} réinitialisée`);
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec");
    }
  };

  const stats = useMemo(() => {
    if (!data?.weeks) return { total: 0, manual: 0, auto: 0, suggested: 0 };
    let manual = 0, auto = 0, suggested = 0;
    data.weeks.forEach((w) => {
      if (w.is_suggestion) suggested++;
      else if (w.manual_override) manual++;
      else if (w.auto_generated) auto++;
    });
    return { total: data.weeks.length, manual, auto, suggested };
  }, [data]);

  if (loading) return <div className="p-8 text-slate-500">Chargement…</div>;

  return (
    <div className="p-6 max-w-6xl mx-auto" data-testid="garde-planning-page">
      <header className="flex items-center gap-3 mb-4">
        <Calendar className="h-6 w-6 text-sawali-blue" />
        <h1 className="text-2xl font-display font-bold">Planning des gardes</h1>
      </header>

      <div className="rounded-xl ring-1 ring-slate-200 bg-white p-4 mb-5 flex flex-wrap items-end gap-3">
        <label className="text-sm">
          <span className="block text-xs font-semibold text-slate-700 mb-1">Année</span>
          <select value={year} onChange={(e) => setYear(Number(e.target.value))}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm bg-white"
                  data-testid="garde-year-select">
            {[2025, 2026, 2027, 2028].map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </label>
        <label className="text-sm">
          <span className="block text-xs font-semibold text-slate-700 mb-1">Groupe en semaine 1</span>
          <select value={startGroup} onChange={(e) => setStartGroup(Number(e.target.value))}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm bg-white"
                  data-testid="garde-start-group">
            {(data?.groups || []).map((g) => <option key={g} value={g}>Groupe {g}</option>)}
          </select>
        </label>
        <button onClick={generate} disabled={generating || !data?.groups?.length}
                className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 text-white px-4 py-2 text-sm font-semibold hover:bg-emerald-700 disabled:opacity-50"
                data-testid="garde-generate-btn">
          <Wand2 className="h-4 w-4" />
          {generating ? "Génération…" : "Générer rotation séquentielle"}
        </button>
        <button onClick={load} className="text-xs px-3 py-2 rounded bg-white ring-1 ring-slate-300 hover:bg-slate-50">
          <RefreshCcw className="h-3 w-3 inline mr-1" /> Rafraîchir
        </button>
        <div className="ml-auto flex gap-3 text-xs text-slate-600">
          <span><strong className="text-emerald-700">{stats.auto}</strong> auto</span>
          <span><strong className="text-amber-700">{stats.manual}</strong> manuel</span>
          <span><strong className="text-slate-400">{stats.suggested}</strong> suggérées</span>
        </div>
      </div>

      <div className="rounded-xl ring-1 ring-slate-200 bg-white overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-600">
            <tr>
              <th className="text-left px-3 py-2">Semaine</th>
              <th className="text-left px-3 py-2">Du lundi</th>
              <th className="text-left px-3 py-2">Au dimanche</th>
              <th className="text-left px-3 py-2">Groupe</th>
              <th className="text-left px-3 py-2">Statut</th>
              <th className="text-right px-3 py-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {(data?.weeks || []).map((w) => {
              const isCurrent = data.current_iso_year === w.year && data.current_iso_week === w.week_number;
              return (
                <tr key={w.week_number}
                    className={`border-t ${isCurrent ? "bg-sawali-blue/5 ring-2 ring-sawali-blue/20" : ""}`}
                    data-testid={`garde-week-${w.week_number}`}>
                  <td className="px-3 py-2 font-mono">
                    S{String(w.week_number).padStart(2, "0")}
                    {isCurrent && <span className="ml-2 text-[10px] bg-sawali-blue text-white px-1.5 py-0.5 rounded uppercase">en cours</span>}
                  </td>
                  <td className="px-3 py-2 text-slate-600">{w.monday}</td>
                  <td className="px-3 py-2 text-slate-600">{w.sunday}</td>
                  <td className="px-3 py-2">
                    {data.groups?.length > 0 ? (
                      <select value={w.groupe_garde ?? ""}
                              onChange={(e) => overrideWeek(w.week_number, e.target.value)}
                              className={`rounded border px-2 py-1 text-sm ${w.manual_override ? "border-amber-500 bg-amber-50 font-semibold" : "border-slate-300 bg-white"}`}
                              data-testid={`garde-week-${w.week_number}-select`}>
                        <option value="">—</option>
                        {data.groups.map((g) => <option key={g} value={g}>Groupe {g}</option>)}
                      </select>
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {w.manual_override ? (
                      <span className="inline-flex items-center gap-1 text-xs text-amber-700 bg-amber-50 ring-1 ring-amber-200 px-2 py-0.5 rounded">
                        <Lock className="h-3 w-3" /> Manuel
                      </span>
                    ) : w.auto_generated ? (
                      <span className="inline-flex items-center gap-1 text-xs text-emerald-700 bg-emerald-50 ring-1 ring-emerald-200 px-2 py-0.5 rounded">
                        <Unlock className="h-3 w-3" /> Auto
                      </span>
                    ) : (
                      <span className="text-xs text-slate-400 italic">non généré</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {w.manual_override && (
                      <button onClick={() => resetWeek(w.week_number)}
                              className="text-xs text-slate-500 hover:text-rose-600"
                              data-testid={`garde-week-${w.week_number}-reset`}>
                        Réinitialiser
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
