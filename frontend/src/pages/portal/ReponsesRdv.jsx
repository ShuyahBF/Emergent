/*
 * Lot 303 — « Réponses WA aux RDV » : page en LECTURE SEULE pour les utilisateurs suivis « Médecin » et « Secrétaire médicale ».
 * Elle réutilise l'écran « Suivi des RDV » du Centre de Messagerie (liste des patients rappelés + conversation WhatsApp avec
 * les réponses du patient et celles de Liluvine). Le serveur limite le contenu : un médecin ne voit que ses patients, le
 * secrétariat ceux de sa société.
 */
import React from "react";
import SuiviRdv from "@/components/SuiviRdv";

export default function ReponsesRdv() {
  return (
    <div className="p-4 space-y-3" data-testid="reponses-rdv">
      <div>
        <h1 className="text-xl font-semibold text-slate-800">Réponses WA aux RDV</h1>
        <p className="text-sm text-slate-500">Réponses des patients aux rappels de rendez-vous envoyés par WhatsApp (lecture seule).</p>
      </div>
      <SuiviRdv portail />
    </div>
  );
}
