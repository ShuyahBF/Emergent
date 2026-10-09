// SyntheseSupport.jsx — Lot 92 : synthèse du support pour l'administrateur et le superviseur.
// Demande du propriétaire (09/10/2026) : « avoir les synthèses des demandes au support non répondues, le nombre total
// et les requêtes assistance transmises à Claude ».
//   - compteurs de la période (reçues, terminées, non répondues, transmises à Claude) ;
//   - tableau des demandes NON RÉPONDUES (en attente d'un agent, ou dernier message du client sans réponse), la plus
//     ancienne en premier, avec l'attente ; « Ouvrir » ouvre le fil dans le chat ;
//   - totaux par espace (Support Loois, sTer - Support…) ;
//   - demandes de fonctionnalités transmises à Claude (verdict, complexité, durée, état).
// Utilisé par la page « Synthèse du support » et par la rubrique du même nom des Paramètres.
// Règle des tableaux : survol bleu, sélection orange (CSS global, classe « ligne-selectionnee »).
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

// Périodes proposées (jours)
const PERIODES = [{ jours: 1, libelle: "Aujourd'hui" }, { jours: 7, libelle: "7 jours" }, { jours: 30, libelle: "30 jours" }, { jours: 90, libelle: "90 jours" }];

// États des demandes transmises à Claude (mêmes libellés que la rubrique « Avis Claude »)
const ETATS_CLAUDE = {
  analyse: "⏳ Analyse en cours", a_decider: "✅ À décider", a_preciser: "❓ À préciser", non_faisable: "⛔ Non faisable",
  acceptee: "👍 Acceptée", refusee: "👎 Refusée", erreur: "⚠️ Analyse impossible",
};

// Attente lisible : « 12 min », « 3 h 05 », « 2 j 4 h »
const attenteLisible = (min) => {
  if (min === null || min === undefined) return "—";
  if (min < 60) return `${min} min`;
  if (min < 1440) return `${Math.floor(min / 60)} h ${String(min % 60).padStart(2, "0")}`;
  return `${Math.floor(min / 1440)} j ${Math.floor((min % 1440) / 60)} h`;
};

// Date courte « 09/10/2026 14:05 »
const dateCourte = (iso) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
};

// Pavé de compteur
function Compteur({ libelle, valeur, couleur = "text-slate-900", detail }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
      <p className="text-xs text-slate-500">{libelle}</p>
      <p className={`font-display text-2xl font-bold ${couleur}`}>{valeur}</p>
      {detail && <p className="text-[11px] text-slate-500">{detail}</p>}
    </div>
  );
}

export default function SyntheseSupport() {
  const [jours, setJours] = useState(30);
  const [donnees, setDonnees] = useState(null);
  const [selection, setSelection] = useState(null);
  const [selectionClaude, setSelectionClaude] = useState(null);

  // Lecture de la synthèse (toast « Patientez… » au premier chargement et au changement de période)
  const charger = useCallback(async (silencieux = false) => {
    const t = silencieux ? null : toast.loading("Patientez… synthèse du support");
    try {
      setDonnees((await apiClient.get("/support/synthese", { params: { jours } })).data);
      if (t) toast.dismiss(t);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Synthèse indisponible", t ? { id: t } : undefined);
    }
  }, [jours]);
  useEffect(() => { charger(); }, [charger]);
  // Rafraîchissement discret toutes les 60 s (les attentes évoluent)
  useEffect(() => { const t = setInterval(() => charger(true), 60_000); return () => clearInterval(t); }, [charger]);

  // Ouvre le fil dans le chat du support (événement écouté par le chat interne)
  const ouvrir = (ligne) => window.dispatchEvent(new CustomEvent("sawali:ouvrir-fil-support", { detail: { espace: ligne.espace, fil: ligne.fil } }));

  if (!donnees) return <p className="text-sm text-slate-500">Patientez…</p>;
  const t = donnees.totaux || {};
  const c = donnees.claude || {};
  return (
    <div className="space-y-4" data-testid="synthese-support">
      {/* Période */}
      <div className="flex flex-wrap items-center gap-2">
        {PERIODES.map((p) => (
          <button key={p.jours} onClick={() => setJours(p.jours)}
                  className={`rounded-full px-3 py-1 text-xs font-semibold ${jours === p.jours ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"}`}>
            {p.libelle}
          </button>
        ))}
        <button onClick={() => charger()} className="ml-auto rounded-md border border-slate-300 px-2 py-1 text-xs">Actualiser</button>
      </div>

      {/* Compteurs */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Compteur libelle="Demandes reçues" valeur={t.recues ?? 0} detail={`${t.terminees ?? 0} terminée(s)`} />
        <Compteur libelle="Non répondues (maintenant)" valeur={t.non_repondues ?? 0} couleur={(t.non_repondues || 0) > 0 ? "text-rose-600" : "text-emerald-600"}
                  detail={`${t.en_attente ?? 0} en attente · ${t.sans_reponse ?? 0} sans réponse`} />
        <Compteur libelle="Transmises à Claude" valeur={c.total ?? 0} detail={`${c.par_statut?.non_faisable ?? 0} non faisable(s)`} />
        <Compteur libelle="À décider (approuvées par Claude)" valeur={c.a_decider ?? 0} couleur={(c.a_decider || 0) > 0 ? "text-orange-600" : "text-slate-900"} />
      </div>

      {/* Demandes non répondues */}
      <section>
        <h3 className="mb-2 font-display text-sm font-bold">Demandes non répondues</h3>
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs text-slate-500">
              <tr><th className="px-2 py-2">Espace</th><th className="px-2">Demandeur</th><th className="px-2">N°</th><th className="px-2">État</th>
                <th className="px-2">Attente</th><th className="px-2">Dernier message du client</th><th className="px-2"></th></tr>
            </thead>
            <tbody>
              {(donnees.non_repondues || []).length === 0 && (
                <tr><td colSpan={7} className="px-2 py-4 text-center text-emerald-700">Aucune demande en souffrance : toutes ont une réponse.</td></tr>
              )}
              {(donnees.non_repondues || []).map((l) => {
                const cle = `${l.espace}|${l.fil}`;
                return (
                  <tr key={cle} onClick={() => setSelection(cle)} aria-selected={selection === cle}
                      className={`cursor-pointer border-t border-slate-100 ${selection === cle ? "ligne-selectionnee" : ""}`}>
                    <td className="px-2 py-1.5 font-semibold">{l.espace_nom}</td>
                    <td className="px-2">{l.nom}</td>
                    <td className="px-2 font-mono text-xs">{l.numero || "—"}</td>
                    <td className="px-2">{l.etat === "attente" ? "⏳ En attente d'un agent" : "💬 Sans réponse"}</td>
                    <td className={`px-2 font-semibold ${(l.attente_min || 0) >= 30 ? "text-rose-600" : ""}`}>{attenteLisible(l.attente_min)}</td>
                    <td className="max-w-[320px] truncate px-2" title={l.dernier_message}>{l.dernier_message || "—"}</td>
                    <td className="px-2">
                      <button onClick={(e) => { e.stopPropagation(); ouvrir(l); }} className="rounded bg-slate-900 px-2 py-0.5 text-xs font-semibold text-white">Ouvrir</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* Totaux par espace */}
      <section>
        <h3 className="mb-2 font-display text-sm font-bold">Par espace — {PERIODES.find((p) => p.jours === jours)?.libelle || `${jours} jours`}</h3>
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs text-slate-500">
              <tr><th className="px-2 py-2">Espace</th><th className="px-2 text-right">Reçues</th><th className="px-2 text-right">Terminées</th><th className="px-2 text-right">Non répondues</th></tr>
            </thead>
            <tbody>
              {(t.par_espace || []).length === 0 && <tr><td colSpan={4} className="px-2 py-4 text-center text-slate-500">Aucune demande sur la période.</td></tr>}
              {(t.par_espace || []).map((e) => (
                <tr key={e.espace_nom} className="border-t border-slate-100">
                  <td className="px-2 py-1.5">{e.espace_nom}</td>
                  <td className="px-2 text-right">{e.recues}</td>
                  <td className="px-2 text-right">{e.terminees}</td>
                  <td className={`px-2 text-right font-semibold ${e.non_repondues > 0 ? "text-rose-600" : ""}`}>{e.non_repondues}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Demandes transmises à Claude */}
      <section>
        <h3 className="mb-2 font-display text-sm font-bold">Demandes transmises à Claude</h3>
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs text-slate-500">
              <tr><th className="px-2 py-2">N°</th><th className="px-2">Reçue le</th><th className="px-2">Plateforme</th><th className="px-2">Client</th>
                <th className="px-2">Demande</th><th className="px-2">Complexité</th><th className="px-2">Durée</th><th className="px-2">État</th></tr>
            </thead>
            <tbody>
              {(c.demandes || []).length === 0 && <tr><td colSpan={8} className="px-2 py-4 text-center text-slate-500">Aucune demande transmise à Claude sur la période.</td></tr>}
              {(c.demandes || []).map((d) => (
                <tr key={d.id} onClick={() => setSelectionClaude(d.id)} aria-selected={selectionClaude === d.id}
                    className={`cursor-pointer border-t border-slate-100 ${selectionClaude === d.id ? "ligne-selectionnee" : ""}`}>
                  <td className="px-2 py-1.5 font-mono text-xs">{d.numero}</td>
                  <td className="px-2 text-xs">{dateCourte(d.creee_le)}</td>
                  <td className="px-2">{d.plateforme_nom}</td>
                  <td className="px-2">{d.demandeur_nom}</td>
                  <td className="max-w-[280px] truncate px-2" title={d.texte}>{d.avis?.resume || d.texte}</td>
                  <td className="px-2">{d.avis?.complexite || "—"}</td>
                  <td className="px-2">{d.avis?.duree_estimee || "—"}</td>
                  <td className="px-2 whitespace-nowrap">{ETATS_CLAUDE[d.statut] || d.statut}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-1 text-[11px] text-slate-500">Décision sur les demandes approuvées : Paramètres → « 🧠 Avis Claude sur les demandes » (administrateur).</p>
      </section>
    </div>
  );
}
