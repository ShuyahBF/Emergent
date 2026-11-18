// LooisSqlDistantSection.jsx — Lot 446 : rubrique « 🧾 Loois — SQL distant (téléphone) » des Paramètres.
//
// Rappelle comment fonctionne la page « Loois → SQL Distant » (utilisable depuis le navigateur du téléphone), l'état de la fonction
// (clé « SQL à distance » de Loois : seulement pour Loois sous Windows ; la page du téléphone utilise le COMPTE administrateur) et ouvre la page.
import React from "react";
import { Link } from "react-router-dom";
import { Ban, Smartphone, ShieldCheck, ExternalLink } from "lucide-react";

export default function LooisSqlDistantSection() {
  return (
    <div className="space-y-3">
      <h3 className="font-semibold text-slate-900">🧾 Loois — SQL distant (téléphone)</h3>
      <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
        <li><Smartphone className="mr-1 inline h-4 w-4 text-sky-600" aria-hidden="true" />La page <b>Plateformes → Loois → SQL Distant</b> s'ouvre dans le navigateur du téléphone : choisissez le client, tapez la requête, une seule machine du client l'exécute et vous voyez laquelle.</li>
        <li><ShieldCheck className="mr-1 inline h-4 w-4 text-emerald-600" aria-hidden="true" />Elle utilise votre compte SAWALI (code à usage unique) : <b>aucune clé n'est gardée sur le téléphone</b>. Réservée à l'administrateur.</li>
        <li>Toute <b>modification</b> (INSERT, UPDATE, DELETE) demande une confirmation renforcée : rappel du client et de la requête, puis saisie du mot « MODIFIER ». Aucune modification de structure n'est possible.</li>
        <li><Ban className="mr-1 inline h-4 w-4 text-red-600" aria-hidden="true" /><b>Machines interdites</b> : pour chaque client, le bouton « Machines du client » permet d'interdire des noms de machines. Une machine interdite ne reçoit jamais de requête distante ; les autres machines du client continuent de répondre. Même réglage dans Loois (Requête SQL distante).</li>
        <li>La clé <code>LOOIS_SQL_DISTANT_CLE</code> (Render) ne sert plus qu'à Loois sous Windows ; elle n'est pas nécessaire pour la page du téléphone.</li>
      </ul>
      <Link to="/admin/loois-sql-distant" className="inline-flex items-center gap-2 rounded bg-sky-700 px-4 py-2 text-sm font-semibold text-white">
        <ExternalLink className="h-4 w-4" aria-hidden="true" />Ouvrir la page SQL Distant
      </Link>
    </div>
  );
}
