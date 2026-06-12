// Iter43-fix (2026-03) — Mapping des sévérités logiciel → plateforme.
// L'admin liste les valeurs StatutEnCours envoyées par ses logiciels métier
// (Aizenta, Biolog…) et les associe aux sévérités internes
// (low / medium / high / critical) pour piloter les badges + notifications.
import React, { useEffect, useMemo, useState } from "react";
import { Plus, Trash2, AlertTriangle, RefreshCw, Save } from "lucide-react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";

const SEVERITY_OPTIONS = [
  { value: "low", label: "Low — Info / log", chip: "bg-slate-100 text-slate-700 ring-slate-300" },
  { value: "medium", label: "Medium — Warning", chip: "bg-amber-100 text-amber-800 ring-amber-300" },
  { value: "high", label: "High — Exception", chip: "bg-orange-100 text-orange-800 ring-orange-300" },
  { value: "critical", label: "Critical — Fatale / crash", chip: "bg-rose-100 text-rose-800 ring-rose-300" },
];

export default function ErrorSeverityMappingSection({ settings, onChange }) {
  const [rows, setRows] = useState([]);
  const [distinctStatuses, setDistinctStatuses] = useState([]);
  const [loadingStatuses, setLoadingStatuses] = useState(false);

  // Initial load depuis settings
  useEffect(() => {
    const m = settings?.error_severity_mapping || {};
    const items = Object.entries(m).map(([statut, severity]) => ({ statut, severity }));
    if (items.length === 0) {
      // Pré-remplissage avec quelques valeurs typiques
      items.push(
        { statut: "exception", severity: "high" },
        { statut: "fatale", severity: "critical" },
        { statut: "warning", severity: "medium" },
      );
    }
    setRows(items);
  }, [settings?.error_severity_mapping]);

  // Découvre dynamiquement les StatutEnCours présents dans le Registre
  const loadDistinctStatuses = async () => {
    setLoadingStatuses(true);
    try {
      const r = await apiClient.get("/me/errors/stats");
      const list = r.data?.by_status || [];
      setDistinctStatuses(list);
    } catch {
      /* noop */
    } finally { setLoadingStatuses(false); }
  };
  useEffect(() => { loadDistinctStatuses(); }, []);

  const addRow = () => setRows((r) => [...r, { statut: "", severity: "medium" }]);
  const removeRow = (i) => setRows((r) => r.filter((_, idx) => idx !== i));
  const setRow = (i, patch) => setRows((r) => r.map((row, idx) => idx === i ? { ...row, ...patch } : row));

  const persist = () => {
    const m = {};
    for (const row of rows) {
      const k = (row.statut || "").trim();
      if (!k) continue;
      m[k] = row.severity;
    }
    onChange?.("error_severity_mapping", m);
    toast.success(`${Object.keys(m).length} équivalence(s) enregistrée(s) — n'oubliez pas de cliquer sur « Enregistrer les paramètres »`);
  };

  const knownStatuses = useMemo(() => new Set(rows.map((r) => (r.statut || "").trim().toLowerCase())), [rows]);
  const unmappedStatuses = (distinctStatuses || []).filter((s) => !knownStatuses.has((s.value || "").toLowerCase()));

  return (
    <div className="space-y-3" data-testid="error-severity-mapping-section">
      <p className="text-xs text-slate-500">
        Associez chaque valeur <code className="bg-slate-100 px-1 rounded">StatutEnCours</code> envoyée par vos logiciels métier
        à une sévérité interne. Sert au calcul des badges, au filtrage et aux notifications du Registre des Erreurs.
        <br />
        Recherche <strong>insensible à la casse</strong>. Si une valeur n'est pas mappée, une heuristique de secours s'applique (exception → High, fatale → Critical, warning → Medium, sinon Low).
      </p>

      <div className="space-y-1.5">
        {rows.map((row, i) => {
          const sev = SEVERITY_OPTIONS.find((s) => s.value === row.severity) || SEVERITY_OPTIONS[0];
          return (
            <div key={i} className="flex items-center gap-2" data-testid={`severity-row-${i}`}>
              <input
                value={row.statut}
                onChange={(e) => setRow(i, { statut: e.target.value })}
                placeholder="ex: exception, fatale, warning…"
                className="flex-1 text-sm rounded ring-1 ring-slate-300 px-2 py-1.5 font-mono"
                data-testid={`severity-row-${i}-statut`}
              />
              <span className="text-slate-400 text-xs">→</span>
              <select
                value={row.severity}
                onChange={(e) => setRow(i, { severity: e.target.value })}
                className="text-sm rounded ring-1 ring-slate-300 px-2 py-1.5 bg-white min-w-[200px]"
                data-testid={`severity-row-${i}-severity`}
              >
                {SEVERITY_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
              <span className={`text-[10px] uppercase tracking-wider font-medium px-2 py-0.5 rounded ring-1 ${sev.chip}`}>
                {sev.value}
              </span>
              <button onClick={() => removeRow(i)} className="text-rose-600 hover:text-rose-700" data-testid={`severity-row-${i}-delete`}>
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          );
        })}
        {rows.length === 0 && (
          <p className="text-xs text-slate-400 italic">Aucune équivalence définie — l'heuristique de secours sera utilisée.</p>
        )}
      </div>

      <div className="flex gap-2 flex-wrap">
        <button onClick={addRow} className="text-xs px-3 py-1.5 rounded ring-1 ring-slate-300 bg-white hover:bg-slate-50 inline-flex items-center gap-1" data-testid="severity-add">
          <Plus className="h-3.5 w-3.5" /> Ajouter une équivalence
        </button>
        <button onClick={persist} className="text-xs px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-700 text-white inline-flex items-center gap-1" data-testid="severity-stage">
          <Save className="h-3.5 w-3.5" /> Mettre à jour
        </button>
        <button onClick={loadDistinctStatuses} disabled={loadingStatuses}
                className="text-xs px-3 py-1.5 rounded ring-1 ring-slate-300 bg-white hover:bg-slate-50 inline-flex items-center gap-1 disabled:opacity-60"
                data-testid="severity-refresh-statuses">
          <RefreshCw className={`h-3.5 w-3.5 ${loadingStatuses ? "animate-spin" : ""}`} />
          Rafraîchir les statuts détectés
        </button>
      </div>

      {/* Statuts non mappés détectés dans le Registre actuel */}
      {unmappedStatuses.length > 0 && (
        <div className="rounded-lg ring-1 ring-amber-200 bg-amber-50 p-3" data-testid="severity-unmapped">
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle className="h-4 w-4 text-amber-700" />
            <p className="text-xs font-medium text-amber-900">
              {unmappedStatuses.length} valeur(s) détectée(s) dans le Registre sans équivalence définie
            </p>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {unmappedStatuses.map((s, idx) => (
              <button
                key={s.value || idx}
                onClick={() => setRows((r) => [...r, { statut: s.value, severity: "medium" }])}
                className="text-[11px] rounded-full bg-white ring-1 ring-amber-300 text-amber-900 px-2 py-0.5 hover:bg-amber-100 inline-flex items-center gap-1"
                title="Cliquer pour ajouter à la liste"
                data-testid={`severity-add-detected-${idx}`}
              >
                <Plus className="h-3 w-3" />
                <code className="font-mono">{s.value || "(vide)"}</code>
                {s.count != null && <span className="text-amber-700">({s.count})</span>}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
