// Iter43-fix22 (2026-06) — Planning hebdomadaire des Groupes de Garde.
// Affiche les 52/53 semaines de l'année avec leur groupe affecté.
// Permet override manuel + génération auto (séquentielle).
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Calendar, RefreshCcw, Lock, Unlock, Wand2, Clock } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

export default function AdminGardePlanning() {
  const [year, setYear] = useState(() => new Date().getFullYear());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [startGroup, setStartGroup] = useState(1);
  // Iter43-fix24az-d — Rotation mode toggle (saturday_noon vs monday_midnight)
  const [rotationMode, setRotationMode] = useState("saturday_noon");
  const [savingMode, setSavingMode] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r, sr] = await Promise.all([
        apiClient.get(`/admin/officines-registry/garde-planning?year=${year}`),
        apiClient.get("/admin/settings").catch(() => ({ data: {} })),
      ]);
      setData(r.data);
      if (r.data?.groups?.length) setStartGroup(r.data.groups[0]);
      const mode = (sr.data?.garde_rotation_mode || "saturday_noon").toLowerCase();
      setRotationMode(mode);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur chargement planning");
    } finally { setLoading(false); }
  }, [year]);
  useEffect(() => { load(); }, [load]);

  const toggleRotationMode = async (nextMode) => {
    if (nextMode === rotationMode) return;
    setSavingMode(true);
    try {
      await apiClient.put("/admin/settings", { garde_rotation_mode: nextMode });
      setRotationMode(nextMode);
      toast.success(
        nextMode === "saturday_noon"
          ? "Mode : rotation Samedi 12h00 activée"
          : "Mode : rotation Lundi 00h00 (legacy) activée"
      );
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec changement de mode");
    } finally { setSavingMode(false); }
  };

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

  // Iter43-fix24az-r (2026-07-22) — Groupe d'assistance hebdo. Sélection null/"" désactive l'appui.
  const overrideAssistGroup = async (week, newAssist) => {
    try {
      const payload = { assist_group: newAssist === "" || newAssist == null ? null : Number(newAssist) };
      await apiClient.put(`/admin/officines-registry/garde-planning/${year}/${week}`, payload);
      if (payload.assist_group === null) {
        toast.success(`Semaine ${week} : groupe d'appui retiré`);
      } else {
        toast.success(`Semaine ${week} : Groupe ${payload.assist_group} désigné comme appui`);
      }
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec — groupe d'appui invalide");
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

  // Iter43-fix24az-e — Réinitialiser TOUTES les semaines de l'année
  const resetYear = async () => {
    if (!window.confirm(
      `⚠️ RÉINITIALISER TOUT LE PLANNING ${year} ?\n\n`
      + "Cette action supprime TOUTES les semaines de l'année "
      + "(manuelles ET automatiques) et le planning retombera sur la rotation séquentielle calculée.\n\n"
      + "Continuer ?"
    )) return;
    try {
      const r = await apiClient.delete(`/admin/officines-registry/garde-planning/year/${year}`);
      toast.success(`${r.data?.weeks_deleted ?? 0} semaines réinitialisées`);
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

      {/* Iter43-fix24az-d — Rotation mode toggle (Saturday noon vs legacy) */}
      <div className="rounded-xl ring-2 ring-rose-400 bg-rose-50/40 p-3 mb-5" data-testid="garde-rotation-mode-card">
        <div className="flex items-start gap-3 flex-wrap">
          <Clock className="h-5 w-5 text-rose-600 shrink-0 mt-0.5" />
          <div className="flex-1 min-w-[280px]">
            <p className="text-sm font-semibold text-rose-900">Cycle de rotation des groupes</p>
            <p className="text-[11px] text-rose-700 mt-0.5">
              Détermine le moment précis où le groupe en garde change. La durée d&apos;une garde reste de 7 jours dans les 2 modes.
            </p>
          </div>
          <div className="flex gap-2 ml-auto">
            <button
              onClick={() => toggleRotationMode("saturday_noon")}
              disabled={savingMode}
              className={`text-xs px-3 py-1.5 rounded font-semibold ring-1 transition ${rotationMode === "saturday_noon" ? "bg-rose-600 text-white ring-rose-600" : "bg-white text-slate-700 ring-slate-300 hover:bg-slate-50"} disabled:opacity-50`}
              data-testid="garde-rotation-saturday-noon"
            >
              Samedi 12h00 {rotationMode === "saturday_noon" && "(actif)"}
            </button>
            <button
              onClick={() => toggleRotationMode("monday_midnight")}
              disabled={savingMode}
              className={`text-xs px-3 py-1.5 rounded font-semibold ring-1 transition ${rotationMode === "monday_midnight" ? "bg-slate-700 text-white ring-slate-700" : "bg-white text-slate-700 ring-slate-300 hover:bg-slate-50"} disabled:opacity-50`}
              data-testid="garde-rotation-monday-midnight"
            >
              Lundi 00h00 (legacy) {rotationMode === "monday_midnight" && "(actif)"}
            </button>
          </div>
        </div>
      </div>

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
        <button onClick={resetYear}
                className="inline-flex items-center gap-2 rounded-lg bg-rose-50 text-rose-700 ring-1 ring-rose-300 px-3 py-2 text-xs font-semibold hover:bg-rose-100"
                data-testid="garde-reset-year-btn"
                title={`Supprime toutes les semaines (manuelles + auto) de l'année ${year}`}>
          <RefreshCcw className="h-3 w-3" /> Réinitialiser tout {year}
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
              <th className="text-left px-3 py-2">Début</th>
              <th className="text-left px-3 py-2">Fin</th>
              <th className="text-left px-3 py-2">Groupe</th>
              <th className="text-left px-3 py-2" title="Groupe d'appui (venir en appui au groupe standard cette semaine)">
                Assist
              </th>
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
                  {/* Iter43-fix24az-r — Colonne ASSIST : groupe d'appui hebdomadaire */}
                  <td className="px-3 py-2">
                    {data.groups?.length > 1 ? (
                      <select value={w.assist_group ?? ""}
                              onChange={(e) => overrideAssistGroup(w.week_number, e.target.value)}
                              className={`rounded border px-2 py-1 text-sm ${w.assist_group ? "border-purple-500 bg-purple-50 italic font-semibold text-purple-800" : "border-slate-200 bg-slate-50 text-slate-500"}`}
                              data-testid={`garde-week-${w.week_number}-assist-select`}
                              title="Groupe d'appui pour cette semaine (facultatif). Ne peut pas être identique au groupe standard.">
                        <option value="">— aucun —</option>
                        {data.groups
                          .filter((g) => g !== w.groupe_garde)
                          .map((g) => <option key={g} value={g}>Groupe {g}</option>)}
                      </select>
                    ) : (
                      <span className="text-slate-400 text-xs italic" title="Il faut au moins 2 groupes pour désigner un appui">
                        {data.groups?.length === 1 ? "1 seul groupe" : "—"}
                      </span>
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
