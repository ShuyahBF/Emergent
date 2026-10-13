// =====================================================================
// Lot 135 — FICHE CLIENT : historique des prises en main à distance (item 9).
// Chaque prise en main a son numéro « CD-AAAA-NNNNN », son ticket (ouvert au début, clôturé à la fin) et son
// intervention ; on retrouve ici, pour le client, le poste, le technicien, la durée, les délais mesurés et la vidéo.
// Visible seulement du support SAWALI (la route renvoie 403 aux autres comptes : la carte ne s'affiche pas).
// =====================================================================
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { MonitorSmartphone, Ticket, PlayCircle } from "lucide-react";
import { dateLisible, dureeLisible } from "./outils";
import { ouvrirPriseEnMain } from "@/components/ControleDistanceOnglets";

export default function HistoriqueClient({ clientId }) {
  const [sessions, setSessions] = useState(null);

  useEffect(() => {
    if (!clientId) return;
    apiClient.get(`/controle-distance/clients/${encodeURIComponent(clientId)}/sessions`)
      .then((r) => setSessions(r.data.sessions || []))
      .catch(() => setSessions(null));   // pas du support SAWALI : rien n'est affiché
  }, [clientId]);

  if (!sessions) return null;

  // Lecture de la vidéo dans un nouvel onglet (lien signé de 15 minutes)
  const voirVideo = async (sid) => {
    try {
      const r = await apiClient.get(`/controle-distance/sessions/${sid}/video/lien`);
      window.open(`${process.env.REACT_APP_BACKEND_URL || ""}${r.data.url}`, "_blank", "noopener");
    } catch { /* vidéo indisponible */ }
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4" data-testid="client-prises-en-main">
      <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-800">
        <MonitorSmartphone className="h-4 w-4 text-sky-600" />
        Prises en main à distance ({sessions.length})
      </h3>
      {sessions.length === 0 && <p className="text-xs text-slate-500">Aucune prise en main pour ce client.</p>}
      {sessions.length > 0 && (
        <div className="max-h-72 overflow-auto">
          <table className="min-w-full text-xs">
            <thead className="text-left text-slate-500">
              <tr>
                <th className="px-2 py-1">N°</th><th className="px-2 py-1">Date</th><th className="px-2 py-1">Poste</th>
                <th className="px-2 py-1">Technicien</th><th className="px-2 py-1">Durée</th><th className="px-2 py-1">Ticket</th>
                <th className="px-2 py-1">Intervention</th><th className="px-2 py-1"></th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr key={s.id} className="border-t border-slate-100">
                  <td className="px-2 py-1 font-mono whitespace-nowrap">{s.numero || "—"}</td>
                  <td className="px-2 py-1 whitespace-nowrap">{dateLisible(s.cree_le)}</td>
                  <td className="px-2 py-1">{s.poste_nom || "—"}</td>
                  <td className="px-2 py-1">{s.technicien_nom || "—"}</td>
                  <td className="px-2 py-1">{dureeLisible(s.duree_s)}</td>
                  <td className="px-2 py-1 whitespace-nowrap">
                    {s.ticket_number ? <span className="inline-flex items-center gap-0.5"><Ticket className="h-3 w-3" />{s.ticket_number}</span> : "—"}
                  </td>
                  <td className="px-2 py-1">{s.intervention_number || "—"}</td>
                  <td className="px-2 py-1">
                    <span className="flex gap-1">
                      {s.video && (
                        <button type="button" onClick={() => voirVideo(s.id)} title="Voir la vidéo" className="text-rose-600 hover:text-rose-700">
                          <PlayCircle className="h-4 w-4" />
                        </button>
                      )}
                      <button type="button" onClick={() => ouvrirPriseEnMain({ id: s.poste_id, nom: s.poste_nom })} title="Reprendre la main sur ce poste"
                              className="text-sky-600 hover:text-sky-700">
                        <MonitorSmartphone className="h-4 w-4" />
                      </button>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
