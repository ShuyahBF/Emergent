// ============================================================================
// Lot 115 — Historique des incidents de la page publique /uptime : gestion depuis les Paramètres
// (rubrique « Bandeau d'incident »). Demande du propriétaire (12/10/2026) : « Comment réinitialiser
// l'historique des incidents ? » — avant ce lot, aucun écran ne permettait de le faire.
//   - liste des incidents (date, sévérité, statut, message, nombre de mises à jour) ;
//   - « Résoudre » : passe un incident « en cours » à « résolu » ;
//   - « Supprimer » : retire un incident de l'historique ;
//   - « Réinitialiser l'historique » : efface tout (il faut taper REINITIALISER).
// Rappel : un bandeau de sévérité « Info » est une ANNONCE, il ne crée plus d'incident (lot 115).
// ============================================================================
import React, { useCallback, useEffect, useState } from "react";
import { CheckCircle2, RefreshCw, RotateCcw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

// Libellés et couleurs des sévérités / statuts
const SEVERITES = {
  info: ["Annonce (info)", "bg-sky-100 text-sky-800"],
  warning: ["Avertissement", "bg-amber-100 text-amber-800"],
  critical: ["Critique", "bg-red-100 text-red-800"],
};
const dateHeure = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");

export default function HistoriqueIncidentsSection() {
  const [incidents, setIncidents] = useState(null);   // null = chargement en cours

  // Lecture de l'historique complet (y compris les annonces « info » d'avant le lot 115)
  const charger = useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/incidents", { params: { limit: 500 } });
      setIncidents(Array.isArray(r.data) ? r.data : []);
    } catch (e) {
      setIncidents([]);
      toast.error(e?.response?.data?.detail || "Lecture des incidents impossible");
    }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  // Action sur le serveur avec toast « Patientez… », puis relecture de la liste
  const agir = async (promesse, succes) => {
    const id = toast.loading("Patientez…");
    try {
      await promesse;
      toast.success(succes, { id });
      charger();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Action impossible", { id });
    }
  };

  const resoudre = (inc) => agir(apiClient.post(`/admin/incidents/${inc.id}/resoudre`), "Incident résolu");
  const supprimer = (inc) => {
    if (!window.confirm(`Supprimer définitivement l'incident du ${dateHeure(inc.started_at)} ?`)) return;
    agir(apiClient.delete(`/admin/incidents/${inc.id}`), "Incident supprimé");
  };
  const reinitialiser = () => {
    const mot = window.prompt(`Effacer TOUT l'historique des incidents (${incidents?.length || 0}) de la page /uptime ?\nTapez REINITIALISER pour confirmer.`);
    if (mot === null) return;
    agir(apiClient.post("/admin/incidents/reinitialiser", { confirmation: mot }), "Historique des incidents réinitialisé");
  };

  return (
    <div className="mt-4 space-y-2 rounded-lg border border-slate-200 bg-white p-3" data-testid="historique-incidents">
      {/* En-tête : titre + boutons Actualiser / Réinitialiser */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold">Historique des incidents (page /uptime)</p>
        <div className="flex gap-2">
          <button type="button" onClick={charger} className="inline-flex items-center gap-1 rounded-md border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50">
            <RefreshCw className="h-3.5 w-3.5" /> Actualiser
          </button>
          <button type="button" onClick={reinitialiser} disabled={!incidents?.length}
                  className="inline-flex items-center gap-1 rounded-md bg-red-600 px-2 py-1 text-xs font-semibold text-white hover:bg-red-700 disabled:opacity-40"
                  data-testid="incidents-reinitialiser">
            <RotateCcw className="h-3.5 w-3.5" /> Réinitialiser l'historique
          </button>
        </div>
      </div>
      <p className="text-[11px] text-slate-500">
        Un bandeau « Info » est une annonce : il n'apparaît plus dans cet historique ni sur /uptime. Seuls les bandeaux
        « Avertissement » et « Critique » ouvrent un incident, résolu automatiquement quand vous désactivez le bandeau.
      </p>

      {/* Liste des incidents */}
      {incidents === null ? <p className="text-xs text-slate-500">Patientez…</p>
        : incidents.length === 0 ? <p className="text-xs text-slate-500">Aucun incident dans l'historique.</p>
        : (
          <table className="w-full text-xs">
            <thead><tr className="text-left text-slate-500"><th>Début</th><th>Sévérité</th><th>Statut</th><th>Message</th><th>Mises à jour</th><th /></tr></thead>
            <tbody>
              {incidents.map((inc) => {
                const [libelle, couleur] = SEVERITES[inc.severity] || [inc.severity || "—", "bg-slate-100 text-slate-700"];
                const enCours = inc.status !== "resolved";
                return (
                  <tr key={inc.id} className="border-t border-slate-100 align-top">
                    <td className="whitespace-nowrap py-1">{dateHeure(inc.started_at)}</td>
                    <td><span className={`rounded-full px-2 py-0.5 font-semibold ${couleur}`}>{libelle}</span></td>
                    <td className="whitespace-nowrap">{enCours ? <b className="text-amber-700">En cours</b>
                      : <span className="text-emerald-700">Résolu {dateHeure(inc.resolved_at)}</span>}</td>
                    <td className="max-w-[18rem] truncate" title={inc.message}>{inc.message || "—"}</td>
                    <td className="text-center">{(inc.updates || []).length}</td>
                    <td className="whitespace-nowrap text-right">
                      {enCours && (
                        <button type="button" onClick={() => resoudre(inc)} className="mr-2 inline-flex items-center gap-1 font-semibold text-emerald-700 hover:underline">
                          <CheckCircle2 className="h-3.5 w-3.5" /> Résoudre
                        </button>
                      )}
                      <button type="button" onClick={() => supprimer(inc)} className="inline-flex items-center gap-1 font-semibold text-red-700 hover:underline">
                        <Trash2 className="h-3.5 w-3.5" /> Supprimer
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
    </div>
  );
}
