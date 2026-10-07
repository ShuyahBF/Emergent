// PostesServeursSection.jsx — Lot 71.3 : rubrique « 🖥️ Postes et serveurs — signal de présence » des Paramètres.
// Rappel du fonctionnement (règle 4 : chaque application déclare sa présence à SAWALI toutes les 5 minutes)
// et accès à l'écran de suivi (versions, inventaire « Détails », fiches du Parc).
import React from "react";
import { Link } from "react-router-dom";

export default function PostesServeursSection() {
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-postes-serveurs">
      <h3 className="font-semibold text-slate-900">🖥️ Postes et serveurs — signal de présence</h3>
      <p className="text-xs text-slate-600">
        Loois, les services Windows et les serveurs (Ster, adLyn, beAuthentik, ALBARKA…) envoient leur signal à
        <code className="mx-1 rounded bg-slate-100 px-1">POST /api/presence-logiciel</code> au démarrage puis toutes les 5 minutes
        (application, version, poste, utilisateur, site). Un poste est « en ligne » si son dernier signal a moins de 12 minutes.
      </p>
      <ul className="list-disc space-y-0.5 pl-5 text-xs text-slate-600">
        <li>Clé facultative <code className="rounded bg-slate-100 px-1">X-Cle-Loois</code> (LOOIS_SUPPORT_CLE) : poste « vérifié ».</li>
        <li>« Détails » d'un poste Loois : système, mémoire, disques, réseau, tâches ; fiche du Parc créée automatiquement.</li>
        <li>Version à mettre à jour signalée quand un poste n'a pas la dernière version publiée.</li>
      </ul>
      <div className="flex justify-end">
        <Link to="/admin/plateformes-temps-reel" className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">
          Plateformes en temps réel ↗
        </Link>
      </div>
    </div>
  );
}
