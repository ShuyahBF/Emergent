// BandeauContrat.jsx — Lot 123 : bandeau « contrat » au-dessus de la zone des Tickets, dans la fenêtre de
// conversation WhatsApp (Centre de messagerie → discussion d'un contact).
// Même source et mêmes règles que la puce de la liste des contacts (lot 120) : POST /api/me/contacts-contrats,
// réservé à l'équipe SAWALI, AUCUN montant. On n'affiche rien pour un contact interne (réponse null) ou pour
// un utilisateur qui n'a pas le droit de voir les contrats (actif = false).
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import PuceContrat from "@/components/PuceContrat";

// Couleurs du bandeau selon l'état (vert valide, orange retard, rouge aucun contrat)
const FONDS = {
  valide: "bg-emerald-50/70 border-emerald-200 text-emerald-900",
  retard: "bg-orange-50/80 border-orange-200 text-orange-900",
  aucun: "bg-red-50/70 border-red-200 text-red-900",
};

// « 2026-10-15 » → « 15/10/2026 »
const dateFr = (iso) => {
  if (!iso) return null;
  const [a, m, j] = String(iso).slice(0, 10).split("-");
  return a && m && j ? `${j}/${m}/${a}` : String(iso);
};

export default function BandeauContrat({ contactId }) {
  const [contrat, setContrat] = useState(undefined);   // undefined = en lecture ; null = rien à afficher

  // Lecture du contrat de CE contact (une requête à l'ouverture de la conversation)
  useEffect(() => {
    let annule = false;
    setContrat(undefined);
    if (!contactId) return undefined;
    apiClient.post("/me/contacts-contrats", { contact_ids: [contactId] })
      .then((r) => { if (!annule) setContrat(r.data?.actif ? (r.data.contrats || {})[contactId] || null : null); })
      .catch(() => { if (!annule) setContrat(null); });     // facultatif : une erreur n'affiche simplement rien
    return () => { annule = true; };
  }, [contactId]);

  if (!contrat) return null;
  // Éléments du résumé (seulement ceux qui sont connus ; jamais de montant)
  const morceaux = [
    contrat.numero ? `Contrat n° ${contrat.numero}` : "Aucun contrat",
    contrat.statut_libelle,
    contrat.client ? `Client : ${contrat.client}` : null,
    contrat.fin ? `fin le ${dateFr(contrat.fin)}` : null,
    contrat.mois_restants != null ? `reste ${contrat.mois_restants} mois` : null,
    contrat.jours_retard ? `retard ${contrat.jours_retard} j` : null,
    contrat.echeance_prochaine ? `échéance ${dateFr(contrat.echeance_prochaine)}` : null,
  ].filter(Boolean);

  return (
    <div className={`px-5 py-1.5 border-b text-xs flex items-center gap-2 flex-wrap ${FONDS[contrat.etat] || FONDS.aucun}`}
         data-testid="conversation-contrat-bar">
      {/* Puce carrée : survol / focus / appui = détail complet (lot 120) */}
      <PuceContrat contrat={contrat} testid="conversation-contrat-puce" />
      <span className="truncate">{morceaux.join(" · ")}</span>
    </div>
  );
}
