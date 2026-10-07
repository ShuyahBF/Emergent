// ToggleAlerteProprietaire.jsx — Lot 67 : interrupteur « Appeler le propriétaire à chaque message »
// affiché dans l'en-tête de la conversation WhatsApp d'un contact.
//
// Quand il est activé (valeur par défaut, même si le champ n'existe pas encore sur la fiche),
// chaque message de ce client est relayé au propriétaire sur WhatsApp, puis Liluvine l'appelle
// (au plus un appel par client toutes les 30 minutes). Désactivé : rien n'est relayé pour ce client.
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { Bell, BellOff } from "lucide-react";   // Lot 71.1 : version pictogramme

// compact (lot 71.1) : simple pictogramme cloche (violette = alerte active, barrée grise = coupée), le libellé passe en infobulle
export default function ToggleAlerteProprietaire({ contact, onChange, compact = false }) {
  // Absent ou vrai = autorisé ; seule la valeur false désactive l'alerte
  const [actif, setActif] = useState(contact?.appel_proprietaire !== false);
  const [enCours, setEnCours] = useState(false);

  // Nouvelle fiche affichée : on relit sa valeur
  useEffect(() => { setActif(contact?.appel_proprietaire !== false); }, [contact?.id, contact?.appel_proprietaire]);

  if (!contact?.id) return null;

  // Bascule enregistrée immédiatement sur la fiche du contact
  const basculer = async () => {
    const valeur = !actif;
    setEnCours(true);
    try {
      await apiClient.put(`/me/contacts/${contact.id}`, { appel_proprietaire: valeur });
      setActif(valeur);
      if (onChange) onChange(valeur);
      toast.success(valeur ? "Liluvine vous préviendra à chaque message de ce client"
        : "Plus d'alerte (relais et appel) pour ce client");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Modification impossible");
    } finally {
      setEnCours(false);
    }
  };

  // Version pictogramme : même action, moins de place dans l'en-tête de la conversation
  if (compact) {
    return (
      <button
        type="button"
        onClick={basculer}
        disabled={enCours}
        className={`inline-flex h-8 w-8 items-center justify-center rounded-lg ring-1 disabled:opacity-50 ${
          actif ? "bg-violet-50 text-violet-700 ring-violet-200 hover:bg-violet-100" : "bg-slate-50 text-slate-400 ring-slate-200 hover:bg-slate-100"}`}
        title={actif ? "Alerte propriétaire active : relais WhatsApp puis appel de Liluvine à chaque message (cliquer pour couper)"
          : "Alerte propriétaire coupée pour ce client (cliquer pour la réactiver)"}
        aria-label={actif ? "Alerte propriétaire active" : "Alerte propriétaire coupée"}
        aria-pressed={actif}
        data-testid="toggle-alerte-proprietaire"
      >
        {actif ? <Bell className="h-4 w-4" /> : <BellOff className="h-4 w-4" />}
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={basculer}
      disabled={enCours}
      className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-semibold ring-1 disabled:opacity-50 ${
        actif ? "bg-violet-50 text-violet-800 ring-violet-200 hover:bg-violet-100" : "bg-slate-50 text-slate-500 ring-slate-200 hover:bg-slate-100"}`}
      title="Appeler le propriétaire à chaque message de ce client (relais WhatsApp puis appel de Liluvine)"
      aria-pressed={actif}
      data-testid="toggle-alerte-proprietaire"
    >
      {actif ? "🔔 Alerte propriétaire" : "🔕 Alerte coupée"}
    </button>
  );
}
