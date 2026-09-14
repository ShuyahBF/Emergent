// Portage site-meetafrican (PR#7 "Journal des appels API VIDAL") — Suivi
// des logs : journal des appels API VIDAL réels (voir backend/routes/
// vidal_audit.py) + historique des synchronisations du référentiel produits
// (backend/routes/vidal_sync.py). Filtre par période, impression.
//
// Note MAC address (voir PORTAGE-SAWALI-VIDAL.md) : l'adresse MAC du poste
// n'est PAS capturable depuis un navigateur — jamais affichée ni fabriquée
// ici, uniquement documentée en avertissement ci-dessous.
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { History, Printer, RefreshCw } from "lucide-react";

export default function VidalApiLogs() {
  const [calls, setCalls] = useState([]);
  const [syncLog, setSyncLog] = useState([]);
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const params = {};
      if (since) params.since = new Date(since).toISOString();
      if (until) params.until = new Date(until).toISOString();
      const [r1, r2] = await Promise.all([
        apiClient.get("/vidal/admin/api-calls-log", { params }),
        apiClient.get("/vidal/admin/sync-log", { params: { limit: 20 } }),
      ]);
      setCalls(r1.data?.entries || []);
      setSyncLog(r2.data?.entries || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Chargement du journal VIDAL impossible");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-4" data-testid="vidal-api-logs-page">
      <div className="flex items-center gap-3 print:hidden">
        <div className="w-10 h-10 rounded-lg bg-slate-100 ring-1 ring-slate-200 flex items-center justify-center">
          <History className="h-5 w-5 text-slate-600" />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-slate-800">Suivi des logs VIDAL</h1>
          <p className="text-xs text-slate-500">Journal des appels API réels et des synchronisations du référentiel produits.</p>
        </div>
      </div>

      <div className="text-xs text-amber-800 bg-amber-50 ring-1 ring-amber-200 p-3 rounded print:hidden">
        L'adresse MAC du poste appelant n'est pas capturable depuis un navigateur — elle n'apparaît donc jamais dans ce journal.
      </div>

      <div className="flex flex-wrap items-end gap-3 print:hidden">
        <div>
          <label className="block text-[10px] font-semibold text-slate-600 mb-0.5">Depuis</label>
          <input type="datetime-local" value={since} onChange={(e) => setSince(e.target.value)} className="px-2 py-1.5 rounded ring-1 ring-slate-300 text-sm" data-testid="vidal-logs-since" />
        </div>
        <div>
          <label className="block text-[10px] font-semibold text-slate-600 mb-0.5">Jusqu'à</label>
          <input type="datetime-local" value={until} onChange={(e) => setUntil(e.target.value)} className="px-2 py-1.5 rounded ring-1 ring-slate-300 text-sm" data-testid="vidal-logs-until" />
        </div>
        <button onClick={load} disabled={loading} className="text-sm px-3 py-1.5 rounded ring-1 ring-slate-300 hover:bg-slate-50 inline-flex items-center gap-1.5" data-testid="vidal-logs-filter">
          <RefreshCw className="h-3.5 w-3.5" /> {loading ? "Chargement…" : "Filtrer"}
        </button>
        <button onClick={() => window.print()} className="text-sm px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-900 text-white inline-flex items-center gap-1.5" data-testid="vidal-logs-print">
          <Printer className="h-3.5 w-3.5" /> Imprimer
        </button>
      </div>

      <div className="ring-1 ring-slate-200 rounded-lg p-3 bg-white">
        <h4 className="text-xs font-semibold text-slate-700 mb-2">
          Appels API VIDAL ({calls.length})
          <span className="font-normal text-slate-400 ml-1">— nouveaux endpoints uniquement (Fiche produit, Posologie, recherche)</span>
        </h4>
        <div className="overflow-x-auto">
          <table className="w-full text-xs" data-testid="vidal-logs-calls-table">
            <thead>
              <tr className="text-left text-slate-500 border-b border-slate-200">
                <th className="py-1 pr-2">Date/heure</th>
                <th className="py-1 pr-2">Mode</th>
                <th className="py-1 pr-2">Méthode</th>
                <th className="py-1 pr-2">Endpoint</th>
                <th className="py-1 pr-2">Statut</th>
                <th className="py-1 pr-2">Durée</th>
                <th className="py-1 pr-2">Utilisateur</th>
              </tr>
            </thead>
            <tbody>
              {calls.length === 0 && (
                <tr><td colSpan={7} className="py-2 text-slate-400 italic">Aucun appel journalisé sur cette période.</td></tr>
              )}
              {calls.map((c, i) => (
                <tr key={i} className="border-b border-slate-100">
                  <td className="py-1.5 pr-2">{c.ts ? new Date(c.ts).toLocaleString("fr-FR") : "—"}</td>
                  <td className="py-1.5 pr-2">{c.mode}</td>
                  <td className="py-1.5 pr-2 font-mono">{c.method}</td>
                  <td className="py-1.5 pr-2 font-mono">{c.path}</td>
                  <td className="py-1.5 pr-2">
                    <span className={c.status === "ok" ? "text-emerald-600" : "text-rose-600"}>{c.status}</span>
                  </td>
                  <td className="py-1.5 pr-2">{c.elapsed_ms != null ? `${c.elapsed_ms} ms` : "—"}</td>
                  <td className="py-1.5 pr-2">{c.user_email || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="ring-1 ring-slate-200 rounded-lg p-3 bg-white">
        <h4 className="text-xs font-semibold text-slate-700 mb-2">Synchronisations du référentiel produits ({syncLog.length})</h4>
        <div className="overflow-x-auto">
          <table className="w-full text-xs" data-testid="vidal-logs-sync-table">
            <thead>
              <tr className="text-left text-slate-500 border-b border-slate-200">
                <th className="py-1 pr-2">Date/heure</th>
                <th className="py-1 pr-2">Déclenché par</th>
                <th className="py-1 pr-2">Statut</th>
                <th className="py-1 pr-2">Résultat</th>
              </tr>
            </thead>
            <tbody>
              {syncLog.length === 0 && (
                <tr><td colSpan={4} className="py-2 text-slate-400 italic">Aucune synchronisation pour le moment.</td></tr>
              )}
              {syncLog.map((entry, i) => (
                <tr key={i} className="border-b border-slate-100">
                  <td className="py-1.5 pr-2">{entry.ts ? new Date(entry.ts).toLocaleString("fr-FR") : "—"}</td>
                  <td className="py-1.5 pr-2">{entry.triggered_by}</td>
                  <td className="py-1.5 pr-2">{entry.status}</td>
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
