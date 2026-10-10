// ConsommationIaSection.jsx — Lot 98 : rubrique « 🧮 Consommation de l'IA (requêtes à Claude) » des Paramètres.
// Demande du propriétaire (10/10/2026) : « Y a-t-il un tableau de synthèse de ces requêtes à Claude ? Le projet étant
// vaste avec beaucoup de paramètres, je dois souvent poser des questions pour m'en rappeler. »
//   - par fonction de SAWALI qui utilise l'IA : nom en clair, à quoi elle sert, où elle se règle ;
//   - nombre d'appels, jetons (entrée / sortie), coût ESTIMÉ en dollars, dernier appel ;
//   - période au choix ; en bas, les fonctions qui n'ont pas servi sur la période (aide-mémoire complet).
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";

const nombre = (n) => (n || 0).toLocaleString("fr-FR");
const dollars = (n) => `${(n || 0).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} $`;

export default function ConsommationIaSection() {
  const [jours, setJours] = useState(30);
  const [donnees, setDonnees] = useState(null);

  // Lecture de la synthèse pour la période choisie (« Patientez… » pendant la lecture)
  useEffect(() => {
    setDonnees(null);
    apiClient.get(`/admin/ia/consommation?jours=${jours}`).then((r) => setDonnees(r.data)).catch(() => setDonnees({ erreur: true }));
  }, [jours]);

  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-consommation-ia">
      <p className="text-xs text-slate-600">
        Chaque appel à l'IA (Claude et les autres modèles) est noté ici, fonction par fonction. Le coût est une
        <b> estimation</b> d'après les tarifs publics ; la facture réelle est sur <b>console.anthropic.com</b> (clé
        ANTHROPIC_API_KEY). Ce tableau sert aussi d'aide-mémoire : à quoi sert chaque fonction et où elle se règle.
      </p>
      <label className="text-sm">Période :{" "}
        <select value={jours} onChange={(e) => setJours(Number(e.target.value))} className="rounded border border-slate-300 px-2 py-1 text-sm">
          <option value={1}>24 heures</option><option value={7}>7 jours</option>
          <option value={30}>30 jours</option><option value={90}>90 jours</option><option value={365}>1 an</option>
        </select>
      </label>

      {!donnees ? <p className="text-sm text-slate-500">Patientez…</p> : donnees.erreur ? (
        <p className="text-sm text-red-700">Synthèse indisponible.</p>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs text-slate-500">
                <tr><th className="px-3 py-2">Fonction</th><th className="px-3 py-2 text-right">Appels</th>
                  <th className="px-3 py-2 text-right">Jetons entrée</th><th className="px-3 py-2 text-right">Jetons sortie</th>
                  <th className="px-3 py-2 text-right">Coût estimé</th><th className="px-3 py-2">Dernier appel</th></tr>
              </thead>
              <tbody>
                {donnees.lignes.length === 0 && (
                  <tr><td colSpan={6} className="px-3 py-3 text-slate-500">Aucun appel à l'IA sur la période (le journal démarre avec le lot 98).</td></tr>
                )}
                {donnees.lignes.map((l) => (
                  <tr key={l.fonction} className="border-t border-slate-100 align-top">
                    <td className="px-3 py-2">
                      <b>{l.nom}</b>
                      <div className="text-xs text-slate-500">{l.description}</div>
                      {l.ou && <div className="text-xs text-slate-400">Réglage : {l.ou}</div>}
                    </td>
                    <td className="px-3 py-2 text-right">{nombre(l.appels)}</td>
                    <td className="px-3 py-2 text-right">{nombre(l.entree)}</td>
                    <td className="px-3 py-2 text-right">{nombre(l.sortie)}</td>
                    <td className="px-3 py-2 text-right">{dollars(l.cout)}{l.cout_partiel && <span title="Tarif inconnu pour un modèle"> *</span>}</td>
                    <td className="px-3 py-2 text-xs text-slate-500">{l.dernier ? new Date(l.dernier).toLocaleString("fr-FR") : "—"}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot className="border-t-2 border-slate-200 bg-slate-50 font-semibold">
                <tr><td className="px-3 py-2">Total ({donnees.jours} j)</td><td className="px-3 py-2 text-right">{nombre(donnees.total.appels)}</td>
                  <td className="px-3 py-2 text-right">{nombre(donnees.total.entree)}</td><td className="px-3 py-2 text-right">{nombre(donnees.total.sortie)}</td>
                  <td className="px-3 py-2 text-right">{dollars(donnees.total.cout)}</td><td /></tr>
              </tfoot>
            </table>
          </div>
          {donnees.inutilisees.length > 0 && (
            <details className="text-xs text-slate-600">
              <summary className="cursor-pointer">Fonctions sans appel sur la période ({donnees.inutilisees.length})</summary>
              <ul className="mt-2 space-y-1">
                {donnees.inutilisees.map((f) => (
                  <li key={f.fonction}><b>{f.nom}</b> — {f.description} {f.ou && <span className="text-slate-400">(Réglage : {f.ou})</span>}</li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </div>
  );
}
