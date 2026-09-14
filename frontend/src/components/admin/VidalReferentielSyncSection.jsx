// Cache local du référentiel produits VIDAL (portage site-meetafrican).
// Recherche instantanée (mode "cache") vs temps réel à chaque frappe
// (mode "temps_reel", par défaut). Voir backend/routes/vidal_sync.py.
import React, { useEffect, useState } from "react";
import { apiClient } from "../../lib/api";
import { toast } from "sonner";

const FREQUENCY_PRESETS = [
  { value: 0, label: "Désactivée (sync manuelle uniquement)" },
  { value: 1, label: "Quotidienne" },
  { value: 7, label: "Hebdomadaire" },
  { value: 30, label: "Mensuelle" },
  { value: 90, label: "Trimestrielle" },
];

export default function VidalReferentielSyncSection() {
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [log, setLog] = useState([]);

  const load = async () => {
    try {
      const r = await apiClient.get("/vidal/admin/sync-config");
      setConfig(r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Chargement de la config référentiel impossible");
    } finally {
      setLoading(false);
    }
  };

  const loadLog = async () => {
    try {
      const r = await apiClient.get("/vidal/admin/sync-log", { params: { limit: 10 } });
      setLog(r.data?.entries || []);
    } catch { /* best effort */ }
  };

  useEffect(() => { load(); loadLog(); }, []);

  // Polling toutes les 5s pendant qu'une synchronisation est en cours (628
  // appels VIDAL, plusieurs minutes) — permet de voir le statut évoluer.
  useEffect(() => {
    if (!config?.sync_in_progress) return;
    const t = setInterval(() => { load(); loadLog(); }, 5000);
    return () => clearInterval(t);
  }, [config?.sync_in_progress]);

  const saveField = async (patch) => {
    setSaving(true);
    try {
      const r = await apiClient.put("/vidal/admin/sync-config", patch);
      setConfig(r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Sauvegarde impossible");
    } finally {
      setSaving(false);
    }
  };

  const syncNow = async () => {
    try {
      const r = await apiClient.post("/vidal/admin/sync-now");
      if (r.data?.status === "already_running") {
        toast.info("Une synchronisation est déjà en cours");
      } else {
        toast.success("Synchronisation lancée (~628 appels VIDAL, plusieurs minutes)");
      }
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec du déclenchement");
    }
  };

  if (loading || !config) {
    return <p className="text-sm text-slate-500 italic">Chargement…</p>;
  }

  return (
    <div className="space-y-4" data-testid="vidal-referentiel-sync-section">
      <div className="text-sm text-slate-700 bg-sky-50 ring-1 ring-sky-200 p-3 rounded leading-relaxed">
        <p className="font-semibold mb-1">🗂️ Référentiel produits VIDAL — cache local</p>
        <p className="text-xs">
          En mode <strong>cache</strong>, la recherche médicament (Fiche produit, Posologie, Sécurisation)
          se fait sur une copie locale du catalogue VIDAL (15 680 produits, ~628 appels API pour un sync
          complet) au lieu d&apos;un appel réseau à chaque frappe. La fiche produit elle-même reste toujours
          en temps réel, quel que soit ce réglage.
        </p>
      </div>

      <div className="grid sm:grid-cols-2 gap-3 max-w-lg">
        <div>
          <label className="block text-[10px] font-semibold text-slate-600 mb-0.5">Mode de recherche</label>
          <select
            value={config.mode}
            onChange={(e) => saveField({ mode: e.target.value })}
            disabled={saving}
            className="w-full px-2 py-1.5 rounded ring-1 ring-slate-300 text-sm"
            data-testid="vidal-sync-mode"
          >
            <option value="temps_reel">Temps réel (par défaut)</option>
            <option value="cache">Cache local</option>
          </select>
        </div>
        <div>
          <label className="block text-[10px] font-semibold text-slate-600 mb-0.5">Fréquence de synchronisation</label>
          <select
            value={config.frequency_days}
            onChange={(e) => saveField({ frequency_days: Number(e.target.value) })}
            disabled={saving}
            className="w-full px-2 py-1.5 rounded ring-1 ring-slate-300 text-sm"
            data-testid="vidal-sync-frequency"
          >
            {FREQUENCY_PRESETS.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button" onClick={syncNow} disabled={config.sync_in_progress}
          className="text-sm px-4 py-1.5 rounded bg-sky-600 hover:bg-sky-700 text-white font-semibold disabled:opacity-50"
          data-testid="vidal-sync-now"
        >
          {config.sync_in_progress ? "Synchronisation en cours…" : "🔄 Synchroniser maintenant"}
        </button>
        <p className="text-xs text-slate-500">
          Dernière synchronisation :{" "}
          {config.last_sync_at ? new Date(config.last_sync_at).toLocaleString("fr-FR") : "jamais"}
        </p>
      </div>

      <div className="pt-3 border-t border-slate-200">
        <p className="text-xs font-semibold text-slate-600 mb-1.5">Historique des synchronisations</p>
        <div className="overflow-x-auto">
          <table className="w-full text-xs" data-testid="vidal-sync-log-table">
            <thead>
              <tr className="text-left text-slate-500 border-b border-slate-200">
                <th className="py-1 pr-2">Date</th>
                <th className="py-1 pr-2">Déclenché par</th>
                <th className="py-1 pr-2">Statut</th>
                <th className="py-1 pr-2">Résultat</th>
              </tr>
            </thead>
            <tbody>
              {log.length === 0 && (
                <tr><td colSpan={4} className="py-2 text-slate-400 italic">Aucune synchronisation pour le moment.</td></tr>
              )}
              {log.map((entry, i) => (
                <tr key={i} className="border-b border-slate-100">
                  <td className="py-1.5 pr-2">{entry.ts ? new Date(entry.ts).toLocaleString("fr-FR") : "—"}</td>
                  <td className="py-1.5 pr-2">{entry.triggered_by}</td>
                  <td className="py-1.5 pr-2">
                    <span className={
                      entry.status === "success" ? "text-emerald-600"
                      : entry.status === "error" ? "text-rose-600" : "text-amber-600"
                    }>
                      {entry.status}
                    </span>
                  </td>
                  <td className="py-1.5 pr-2">{entry.result}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
