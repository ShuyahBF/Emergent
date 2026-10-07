// SanteServeurSection.jsx — Lot 71.3 : rubrique « ⚡ Santé du serveur — blocages » des Paramètres.
// La sentinelle (lots 71.1 / 71.2) note chaque fois que le serveur reste figé plus de 1,5 s, avec le code en cause.
// Cette rubrique affiche les 20 derniers blocages depuis le dernier démarrage du serveur.
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";

export default function SanteServeurSection() {
  const [etat, setEtat] = useState(null);

  // Lecture de l'état de la sentinelle (rafraîchi à la demande)
  const charger = () => apiClient.get("/admin/sentinelle").then((r) => setEtat(r.data)).catch(() => setEtat({ erreur: true }));
  useEffect(() => { charger(); }, []);

  if (!etat) return <p className="text-sm text-slate-500">Patientez…</p>;
  if (etat.erreur) return <p className="text-sm text-red-700">État du serveur indisponible.</p>;
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-sante-serveur">
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-semibold text-slate-900">⚡ Blocages du serveur depuis le dernier démarrage</h3>
        <button type="button" onClick={charger} className="rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50">⟳ Actualiser</button>
      </div>
      <p className="text-xs text-slate-600">
        Sentinelle {etat.active ? <b className="text-emerald-700">active</b> : <b className="text-amber-700">inactive (SENTINELLE_BOUCLE=0)</b>} :
        tout blocage de plus de {etat.seuil_s} s est noté ici et dans les journaux Render (« [boucle-bloquee] » avec la pile d'appels).
      </p>
      {etat.blocages.length === 0 ? (
        <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">✅ Aucun blocage depuis le dernier démarrage.</p>
      ) : (
        <table className="w-full text-xs">
          <thead><tr className="text-left text-slate-500"><th className="py-1">Heure</th><th>Durée</th><th>Code en cause</th></tr></thead>
          <tbody>
            {etat.blocages.map((b, i) => (
              <tr key={i} className="border-t border-slate-100">
                <td className="py-1 pr-2 whitespace-nowrap">{new Date(b.le).toLocaleString("fr-FR")}</td>
                <td className="pr-2">{b.duree_s == null ? "en cours…" : `${b.duree_s} s`}</td>
                <td className="font-mono text-[11px] text-slate-700">{b.lieu}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
