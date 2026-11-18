// LooisDossiersHospitalisationSection.jsx — Lot 448 : rubrique « 🏥 Loois — Dossiers d'hospitalisation (web) » des Paramètres.
//
// Explique la page web « Loois SQL distant → Dossiers d'hospitalisation » (même liste que l'écran Loois, lue chez le client par le canal SQL Distant),
// l'état de la fonction (accès administrateur, lecture seule, rien de conservé dans SAWALI) et ouvre la page.
import React from "react";
import { Link } from "react-router-dom";
import { ExternalLink, Eye, ShieldCheck, Smartphone } from "lucide-react";

export default function LooisDossiersHospitalisationSection() {
  return (
    <div className="space-y-3">
      <h3 className="font-semibold text-slate-900">🏥 Loois — Dossiers d'hospitalisation (web)</h3>
      <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
        <li><Smartphone className="mr-1 inline h-4 w-4 text-sky-600" aria-hidden="true" />La page <b>Loois SQL distant → Dossiers d'hospitalisation</b> s'ouvre dans le navigateur du téléphone : choisissez le client et la période, puis « Afficher ».</li>
        <li><Eye className="mr-1 inline h-4 w-4 text-violet-600" aria-hidden="true" />Colonnes : n° de dossier, libellé, date de dépôt, patient ; du plus récent au plus ancien ; le bouton « Voir » ouvre le détail (montant, réglé, modifié par).</li>
        <li><ShieldCheck className="mr-1 inline h-4 w-4 text-emerald-600" aria-hidden="true" />Réservée aux <b>administrateurs</b> ; lecture seule ; les données de patients sont lues chez le client et <b>ne sont pas conservées</b> dans SAWALI.</li>
        <li>Elle utilise le canal « SQL distant » (une machine du client doit être en ligne) : la liste se lit par tranches de 200 numéros (environ 2 secondes chacune), 80 au plus (environ 3 mois chez IPM), 3 minutes au plus. Période proposée : 7 jours au départ, puis 30, 60 ou 90 jours. Au-delà, la page signale une lecture PARTIELLE.</li>
        <li>Un clic sur « Afficher » ne relance jamais une lecture en cours : le bouton se grise, la durée et l'avancement s'affichent, et « Arrêter » interrompt la lecture.</li>
      </ul>
      <Link to="/admin/loois-dossiers-hospitalisation" className="inline-flex items-center gap-2 rounded bg-sky-700 px-4 py-2 text-sm font-semibold text-white">
        <ExternalLink className="h-4 w-4" aria-hidden="true" />Ouvrir la page Dossiers d'hospitalisation
      </Link>
    </div>
  );
}
