// OptionsNotifWa.jsx — Lot 453 : deux interrupteurs « Notifications WhatsApp » d'un ticket ou d'une intervention.
//   - « au contact concerné » ;
//   - « à son responsable » : le contact décisionnaire (Responsable / DG / Directeur) de l'entreprise à laquelle ce contact est lié.
// Activés par défaut ; décochés, aucune notification WhatsApp n'est envoyée à cette personne pour cet élément.
// Les interrupteurs sont enregistrés avec le formulaire (bouton Enregistrer / Créer) : rien n'est modifié en silence.
import React from "react";
import { BellOff, BellRing } from "lucide-react";

export default function OptionsNotifWa({ contact, responsable, onChange }) {
  const ligne = (cle, valeur, libelle, aide) => (
    <label className="flex items-start gap-2 text-sm" key={cle}>
      <input type="checkbox" className="mt-1" checked={valeur !== false} onChange={(e) => onChange({ notifier_contact: contact, notifier_responsable: responsable, [cle]: e.target.checked })} data-testid={`notif-wa-${cle}`} />
      <span>
        <span className="font-semibold">{libelle}</span>
        <span className="block text-xs text-slate-500">{aide}</span>
      </span>
    </label>
  );
  const toutCoupe = contact === false && responsable === false;
  return (
    <fieldset className="space-y-2 rounded-lg border border-slate-200 p-3" data-testid="options-notif-wa">
      <legend className="flex items-center gap-1 px-1 text-xs font-semibold text-slate-600">
        {toutCoupe ? <BellOff className="h-3.5 w-3.5" aria-hidden="true" /> : <BellRing className="h-3.5 w-3.5" aria-hidden="true" />}Notifications WhatsApp
      </legend>
      {ligne("notifier_contact", contact, "Notifier le contact concerné", "Le rapporteur de la demande reçoit les messages WhatsApp de cet élément.")}
      {ligne("notifier_responsable", responsable, "Notifier son responsable", "Le contact décisionnaire de l'entreprise liée reçoit aussi les notifications.")}
    </fieldset>
  );
}
