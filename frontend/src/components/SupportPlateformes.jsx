// SupportPlateformes.jsx — Lot 90 : support SAWALI des plateformes web dans le chat de l'équipe du support.
//   - RequetesEnAttente : barre « ⏳ N autre(s) requête(s) en attente » affichée PENDANT une conversation (demande du
//     propriétaire : « pendant une conversation le support doit savoir qu'il y a d'autres requêtes en attente »).
//     Regroupe toutes les demandes en attente : sTer - Support, adLyn - Support… et Support Loois. Un clic ouvre le fil.
//   - SupportPlateformeBandeau : bandeau du fil d'un utilisateur de plateforme (n° de requête, état, agent, Terminer).
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const INTERVALLE_MS = 15_000;   // relecture des demandes en attente

// « il y a 3 min » à partir d'une date ISO
const depuis = (iso) => {
  const d = new Date(iso);
  if (!iso || Number.isNaN(d.getTime())) return "";
  const min = Math.max(0, Math.round((Date.now() - d.getTime()) / 60000));
  if (min < 1) return "à l'instant";
  if (min < 60) return `il y a ${min} min`;
  return `il y a ${Math.round(min / 60)} h`;
};

export function RequetesEnAttente({ lastEvent, espaceActif, filActif, onAller }) {
  const [elements, setElements] = useState([]);
  const [ouvert, setOuvert] = useState(false);

  // Lecture des demandes en attente (silencieuse : rien affiché en cas d'erreur)
  const lire = useCallback(async () => {
    try { setElements((await apiClient.get("/support/en-attente")).data.elements || []); } catch { /* hors équipe */ }
  }, []);
  useEffect(() => { lire(); const t = setInterval(lire, INTERVALLE_MS); return () => clearInterval(t); }, [lire]);
  // Relecture immédiate à chaque événement du chat (nouveau message, nouvelle demande…)
  useEffect(() => { if (lastEvent) lire(); }, [lastEvent, lire]);

  // Les AUTRES demandes : le fil ouvert n'est pas compté
  const autres = elements.filter((e) => !(e.espace === espaceActif && e.fil === filActif));
  if (!autres.length) return null;
  return (
    <div className="border-b border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-900" data-testid="requetes-en-attente">
      <button onClick={() => setOuvert((v) => !v)} className="flex w-full items-center gap-2 font-semibold">
        <span className="inline-flex h-2 w-2 animate-pulse rounded-full bg-amber-500" />
        ⏳ {autres.length} {filActif ? "autre(s) " : ""}requête(s) en attente
        <span className="ml-auto font-normal underline">{ouvert ? "masquer" : "voir"}</span>
      </button>
      {ouvert && (
        <ul className="mt-1 max-h-40 space-y-0.5 overflow-y-auto">
          {autres.map((e) => (
            <li key={`${e.espace}|${e.fil}`}>
              <button onClick={() => { setOuvert(false); onAller(e.espace, e.fil); }}
                      className="w-full rounded px-1 py-0.5 text-left hover:bg-amber-100">
                <b>{e.espace_nom}</b> · {e.nom}{e.numero ? ` · ${e.numero}` : ""} <span className="opacity-70">({depuis(e.depuis)})</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// Couleurs de l'état de la requête
const ETATS = {
  attente: { libelle: "⏳ En attente", classe: "bg-amber-100 text-amber-800" },
  active: { libelle: "💬 En cours", classe: "bg-emerald-100 text-emerald-800" },
  terminee: { libelle: "✅ Terminée", classe: "bg-slate-100 text-slate-700" },
};

export function SupportPlateformeBandeau({ espaceId, filKey, lastEvent }) {
  const code = espaceId.replace(/^support-plat-/, "");
  const [donnees, setDonnees] = useState(null);
  const [enCours, setEnCours] = useState(false);

  // Requête du fil ouvert (relue à chaque événement du chat)
  const lire = useCallback(async () => {
    try { setDonnees((await apiClient.get(`/support-plateformes/${code}/fils/${filKey}/requete`)).data); }
    catch { setDonnees(null); }
  }, [code, filKey]);
  useEffect(() => { lire(); }, [lire, lastEvent]);

  // Clôture de la requête (message système envoyé à l'utilisateur)
  const terminer = async () => {
    if (!window.confirm("Terminer cette requête ? L'utilisateur pourra en ouvrir une nouvelle en écrivant.")) return;
    setEnCours(true);
    try {
      const r = await apiClient.post(`/support-plateformes/${code}/fils/${filKey}/terminer`);
      toast.success(`Requête ${r.data.numero} terminée`);
      await lire();
    } catch (e) { toast.error(e?.response?.data?.detail || "Clôture impossible"); }
    finally { setEnCours(false); }
  };

  const r = donnees?.requete;
  const d = donnees?.demandeur;
  if (!d) return null;
  const etat = ETATS[r?.statut] || null;
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-white px-3 py-1.5 text-xs" data-testid="bandeau-support-plateforme">
      {r ? <span className="font-mono font-semibold">{r.numero}</span> : <span className="text-slate-500">Aucune requête</span>}
      {etat && <span className={`rounded-full px-2 py-0.5 font-semibold ${etat.classe}`}>{etat.libelle}</span>}
      {r?.prise_par && <span className="text-slate-600">par {r.prise_par}</span>}
      {(d.email || d.telephone) && <span className="text-slate-500">{[d.email, d.telephone].filter(Boolean).join(" · ")}</span>}
      {r && r.statut !== "terminee" && (
        <button onClick={terminer} disabled={enCours}
                className="ml-auto rounded bg-slate-800 px-2 py-0.5 font-semibold text-white disabled:opacity-50">
          {enCours ? "Patientez…" : "Terminer la requête"}
        </button>
      )}
    </div>
  );
}
