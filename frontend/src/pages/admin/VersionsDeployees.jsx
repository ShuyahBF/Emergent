// VersionsDeployees.jsx — Lot 65 : solutions WINDOWS déployées chez les clients (Loois, LooisSyncService,
// et toute application WinDev qui envoie le même signal), en bas de la page « Plateformes en temps réel ».
// Lot 65.1 : section recentrée sur les postes Windows (suivi des postes clients), tableau des plateformes
// web retiré ; colonne « Lancé le » (heure de démarrage du logiciel sur le poste).
//
// Lot 66 : lien « Détails » sur chaque ligne de machine → fenêtre DetailsPoste.jsx (inventaire du poste :
// système, mémoire, disques, réseau, tâches en cours, fiche du parc informatique), relue chaque minute.
//
// - logiciels de bureau : un tableau des postes qui les exécutent, avec
//   la version de chacun, l'utilisateur Windows, le site, et une pastille verte s'il a donné signe
//   de vie il y a moins de 12 minutes. Les postes qui n'ont pas la dernière version sont signalés.
import React, { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import DetailsPoste from "./DetailsPoste";

const INTERVALLE_MS = 60000;

// « 06/10/2026 10:44 » (vide si la date est absente ou illisible)
function dateCourte(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }).replace(",", "");
}

// « Version X · déployée le JJ/MM/AAAA HH:MM » (format commun à toutes les plateformes)
function libelleVersion(version, deployeLe) {
  if (!version) return null;
  const d = dateCourte(deployeLe);
  return d ? `Version ${version} · déployée le ${d}` : `Version ${version}`;
}

// « il y a 3 min » / « il y a 2 h » / date complète au-delà d'un jour
function depuis(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const min = Math.round((Date.now() - d.getTime()) / 60000);
  if (min < 1) return "à l'instant";
  if (min < 60) return `il y a ${min} min`;
  if (min < 24 * 60) return `il y a ${Math.round(min / 60)} h`;
  return dateCourte(iso);
}

export default function VersionsDeployees() {
  const [donnees, setDonnees] = useState(null);
  const [erreur, setErreur] = useState("");
  const [selection, setSelection] = useState(null);   // ligne sélectionnée (règle des tableaux)
  const [details, setDetails] = useState(null);       // poste affiché dans la fenêtre « Détails » ({machine, application})

  // Lecture des versions (SAWALI, plateformes, postes)
  const lire = useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/versions-deployees");
      setDonnees(r.data); setErreur("");
    } catch (err) {
      setErreur(err?.response?.data?.detail || "Versions déployées indisponibles");
    }
  }, []);

  // Relecture toutes les minutes, seulement quand l'onglet est visible
  useEffect(() => {
    lire();
    const t = setInterval(() => { if (!document.hidden) lire(); }, INTERVALLE_MS);
    return () => clearInterval(t);
  }, [lire]);

  return (
    <section className="space-y-3" data-testid="versions-deployees">
      <h2 className="text-xl font-display font-bold">🖥️ Postes et serveurs — versions déployées</h2>
      <p className="text-xs text-slate-500">
        Chaque poste client (Loois, service de synchronisation, applications WinDev) et chaque serveur de plateforme (Ster, adLyn, beAuthentik, ALBARKA) envoie un signal toutes les 5 minutes (règle 4) :
        pastille verte = en cours d'exécution, badge orange = version à mettre à jour.
      </p>
      {erreur && <p className="rounded-lg bg-rose-50 p-3 text-sm text-rose-800">{erreur}</p>}
      {!donnees && !erreur && <p className="text-sm text-slate-500">Patientez…</p>}

      {donnees && (
        <>
          {/* Logiciels de bureau : une carte par application, un tableau de ses postes */}
          {(donnees.logiciels || []).length === 0 && (
            <p className="text-sm text-slate-500">Aucun poste Windows n'a encore envoyé de signal : publiez la nouvelle version de Loois (pspub.ps1) ; chaque poste apparaît ici dans les 6 minutes qui suivent l'ouverture de Loois.</p>
          )}
          {(donnees.logiciels || []).map((app) => (
            <div key={app.application} className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200" data-testid={`logiciel-${app.application}`}>
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-lg font-semibold">🖥️ {app.application}</h3>
                <span className="text-xs text-slate-600">
                  Dernière version : <strong>{libelleVersion(app.derniere_version, app.deploye_le)}</strong>
                  {" · "}{app.en_ligne} / {app.postes.length} poste(s) en ligne · {app.a_jour} / {app.postes.length} à jour
                </span>
              </div>
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-2 py-1.5">Machine</th><th className="px-2 py-1.5">Composant</th><th className="px-2 py-1.5">Version</th>
                      <th className="px-2 py-1.5">Utilisateur</th><th className="px-2 py-1.5">Site</th><th className="px-2 py-1.5">Lancé le</th><th className="px-2 py-1.5">Dernier signal</th>
                      <th className="px-2 py-1.5" />
                    </tr>
                  </thead>
                  <tbody>
                    {app.postes.map((p) => {
                      const cle = `${app.application}:${p.machine}:${p.composant}`;
                      return (
                        <tr key={cle} className={selection === cle ? "ligne-selectionnee" : ""} onClick={() => setSelection(cle)}>
                          <td className="px-2 py-1.5 font-medium">
                            {/* Pastille verte = signal reçu depuis moins de 12 minutes */}
                            <span className={`mr-2 inline-block h-2.5 w-2.5 rounded-full ${p.en_ligne ? "bg-emerald-500" : "bg-slate-300"}`}
                              title={p.en_ligne ? "En cours d'exécution" : "Aucun signal récent"} />
                            {p.machine}
                            {!p.verifie && <span className="ml-1 text-[10px] text-slate-400" title="Signal envoyé sans la clé du support">(non vérifié)</span>}
                          </td>
                          <td className="px-2 py-1.5">{p.composant}</td>
                          <td className="px-2 py-1.5">
                            {libelleVersion(p.version, p.deploye_le)}
                            {!p.a_jour && <span className="ml-1 rounded bg-amber-100 px-1.5 text-[11px] font-semibold text-amber-800">à mettre à jour</span>}
                          </td>
                          <td className="px-2 py-1.5">{p.utilisateur || "—"}</td>
                          <td className="px-2 py-1.5">{p.site || "—"}</td>
                          {/* Heure de démarrage du logiciel sur ce poste (connexion en cours) */}
                          <td className="px-2 py-1.5">{dateCourte(p.demarre_le) || "—"}</td>
                          <td className="px-2 py-1.5 text-slate-500" title={p.systeme || ""}>{depuis(p.vu_le)}</td>
                          {/* Lot 66 : inventaire complet du poste (système, disques, réseau, tâches…) */}
                          <td className="px-2 py-1.5 text-right">
                            <button type="button" className="text-sky-700 underline hover:text-sky-900" data-testid={`details-${p.machine}`}
                              onClick={(e) => { e.stopPropagation(); setSelection(cle); setDetails({ machine: p.machine, application: app.application }); }}>
                              Détails
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </>
      )}
      {details && <DetailsPoste machine={details.machine} application={details.application} onClose={() => setDetails(null)} />}
    </section>
  );
}
