// =====================================================================
// Lot 131 — Rubrique des Paramètres « 🖥️ Contrôle à distance Loois » :
// fonctionnement, conditions et journal des prises en main (qui, quel poste, quand, durée, issue).
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { RefreshCw, MonitorSmartphone, UserX } from "lucide-react";
// Lot 131.1 — prise en main directe depuis la liste des postes
import ControleDistance from "@/components/ControleDistance";

// Libellés et couleurs des statuts d'une session
const STATUTS = {
  demandee: ["En attente d'accord", "bg-amber-100 text-amber-800"],
  acceptee: ["Acceptée", "bg-sky-100 text-sky-800"],
  en_cours: ["En cours", "bg-emerald-100 text-emerald-800"],
  terminee: ["Terminée", "bg-slate-100 text-slate-700"],
  refusee: ["Refusée", "bg-rose-100 text-rose-700"],
  expiree: ["Sans réponse", "bg-slate-100 text-slate-500"],
};

// Date lisible « 12/10/2026 14:05 »
const dateLisible = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");

// Durée lisible « 12 min » / « 1 h 05 »
function dureeLisible(s) {
  if (s === null || s === undefined) return "—";
  const m = Math.max(1, Math.round(s / 60));
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")}`;
}

export default function ControleDistanceSection() {
  const [sessions, setSessions] = useState([]);
  const [chargement, setChargement] = useState(false);
  const [erreur, setErreur] = useState("");
  // Lot 131.1 — postes Loois munis d'une clé client, et poste ouvert dans la visionneuse
  const [postes, setPostes] = useState([]);
  const [superAdmin, setSuperAdmin] = useState(false);
  const [posteOuvert, setPosteOuvert] = useState(null);

  // ---- Lecture du journal (réservé au support SAWALI) ----
  const lire = useCallback(async () => {
    setChargement(true);
    try {
      const [r, p] = await Promise.all([
        apiClient.get("/controle-distance/journal", { params: { limite: 50 } }),
        apiClient.get("/controle-distance/postes"),
      ]);
      setSessions(r.data.sessions || []);
      setPostes(p.data.postes || []);
      setSuperAdmin(Boolean(p.data.super_admin));
      setErreur("");
    } catch (e) {
      setErreur(e?.response?.status === 403 ? "Journal réservé au support SAWALI." : "Journal indisponible.");
    } finally {
      setChargement(false);
    }
  }, []);
  useEffect(() => { lire(); }, [lire]);

  return (
    <div className="space-y-3 text-sm text-slate-700" data-testid="controle-distance-section">
      <p>
        Le support SAWALI peut <b>voir l'écran</b> d'un poste Loois ou <b>en prendre le contrôle</b> (souris, clavier,
        plusieurs écrans, presse-papiers), directement depuis le navigateur.
      </p>
      <ul className="list-disc space-y-1 pl-5">
        <li>Où : chat du support, fil du poste, session acceptée → bouton <b>« Prendre la main »</b>.</li>
        <li>Accord obligatoire : l'utilisateur du poste accepte (ou réduit à « Voir seulement »), voit un bandeau rouge et peut <b>arrêter</b> à tout moment.</li>
        <li>Seuls les postes munis d'une <b>clé client</b> Loois peuvent être pris en main ; une session dure au plus 4 h.</li>
        <li>Les jetons de connexion servent une seule fois ; le mode « Voir seulement » est imposé par le serveur.</li>
        <li>Côté poste : Loois à jour (icône de la zone de notification lancée).</li>
        <li>
          <UserX className="inline h-4 w-4 text-indigo-600" aria-hidden="true" /> <b>Poste sans surveillance</b> : poste
          installé avec la clé « LKS-… » (Plateformes → Loois → Synchro → Clés clients). Le super-admin seul en prend la main,
          sans accord ni bandeau ; une notification discrète s'affiche sur le poste à chaque accès. La session Windows doit
          rester ouverte et déverrouillée.
        </li>
      </ul>

      {posteOuvert && (
        <ControleDistance posteId={posteOuvert.id} posteNom={posteOuvert.nom} onClose={() => { setPosteOuvert(null); lire(); }} />
      )}
      <h4 className="font-semibold text-slate-800">Postes Loois</h4>
      {postes.length === 0 && !chargement && <p className="text-xs text-slate-500">Aucun poste muni d'une clé client pour l'instant.</p>}
      {postes.length > 0 && (
        <div className="max-h-72 overflow-auto">
          <table className="min-w-full text-xs">
            <thead className="text-left text-slate-500">
              <tr><th className="px-2 py-1">Poste</th><th className="px-2 py-1">Client</th><th className="px-2 py-1">Dernier signal</th><th className="px-2 py-1"></th></tr>
            </thead>
            <tbody>
              {postes.map((p) => {
                const signal = p.signal_controle_distance || p.dernier_contact;
                const enLigne = signal && Date.now() - new Date(signal).getTime() < 2 * 60 * 1000;   // signal toutes les 5 s
                const interdit = p.sans_surveillance && !superAdmin;
                return (
                  <tr key={p.id} className="border-t border-slate-100">
                    <td className="px-2 py-1">
                      <span className={`mr-1 inline-block h-2 w-2 rounded-full ${enLigne ? "bg-emerald-500" : "bg-slate-300"}`} title={enLigne ? "En ligne" : "Hors ligne"} />
                      {p.nom}
                      {p.sans_surveillance && (
                        <span className="ml-1 inline-flex items-center gap-0.5 rounded-full bg-indigo-100 px-1.5 text-[10px] font-semibold text-indigo-700" title="Clé sans surveillance : prise en main sans accord">
                          <UserX className="h-3 w-3" aria-hidden="true" />sans surveillance
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-1">{p.cle_client_libelle || p.cle_client_code}</td>
                    <td className="px-2 py-1 whitespace-nowrap">{dateLisible(signal)}</td>
                    <td className="px-2 py-1">
                      <button type="button" disabled={interdit} onClick={() => setPosteOuvert(p)}
                              title={interdit ? "Poste sans surveillance : réservé au super-admin" : "Prendre la main"}
                              className="grid h-7 w-7 place-items-center rounded-full bg-sky-600 text-white hover:bg-sky-700 disabled:opacity-30">
                        <MonitorSmartphone className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center gap-2">
        <h4 className="font-semibold text-slate-800">Journal des prises en main</h4>
        <button type="button" onClick={lire} disabled={chargement} title="Actualiser"
                className="rounded-md p-1 text-slate-600 hover:bg-slate-100 disabled:opacity-50">
          <RefreshCw className={`h-4 w-4 ${chargement ? "animate-spin" : ""}`} />
        </button>
      </div>
      {erreur && <p className="text-xs text-rose-600">{erreur}</p>}
      {!erreur && sessions.length === 0 && !chargement && (
        <p className="text-xs text-slate-500">Aucune prise en main pour l'instant.</p>
      )}
      {sessions.length > 0 && (
        <div className="overflow-x-auto">
          <table className="min-w-full text-xs">
            <thead className="text-left text-slate-500">
              <tr>
                <th className="px-2 py-1">Date</th>
                <th className="px-2 py-1">Poste</th>
                <th className="px-2 py-1">Technicien</th>
                <th className="px-2 py-1">Mode</th>
                <th className="px-2 py-1">Statut</th>
                <th className="px-2 py-1">Durée</th>
                <th className="px-2 py-1">Motif</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => {
                const [libelle, couleur] = STATUTS[s.statut] || [s.statut, "bg-slate-100 text-slate-600"];
                return (
                  <tr key={s.id} className="border-t border-slate-100">
                    <td className="px-2 py-1 whitespace-nowrap">{dateLisible(s.cree_le)}</td>
                    <td className="px-2 py-1">{s.poste_nom || "—"}</td>
                    <td className="px-2 py-1">{s.technicien_nom || "—"}</td>
                    <td className="px-2 py-1">
                      {s.mode === "voir" ? "Voir seulement" : "Contrôle"}
                      {s.sans_surveillance && <UserX className="ml-1 inline h-3.5 w-3.5 text-indigo-600" title="Sans surveillance (accord automatique)" />}
                    </td>
                    <td className="px-2 py-1"><span className={`rounded-full px-2 py-0.5 ${couleur}`}>{libelle}</span></td>
                    <td className="px-2 py-1">{dureeLisible(s.duree_s)}</td>
                    <td className="px-2 py-1 text-slate-500">{[s.motif, s.motif_fin].filter(Boolean).join(" · ") || "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
