// =====================================================================
// Lot 163 — Rubrique des Paramètres « 🧩 Offre du client — Liluvine » : refus d'assistance quand le contrat du client n'est
// pas à jour.   GET / PUT /api/admin/offre-client/reglages  { actif, message }
// - L'offre de chaque client se saisit sur sa fiche (SMART Communications) ; Liluvine l'utilise toujours (sans effet si vide).
// - Le refus est DÉSACTIVÉ par défaut. Activé : un contact lié à un client dont le contrat n'est pas à jour (orange / rouge ;
//   pseudo-contrat compris) et qui demande assistance, maintenance, dépannage… reçoit le texte ci-dessous, signé par l'assistant IA ;
//   un ticket est ouvert (ou la demande rattachée au ticket ouvert) et l'administrateur est alerté.
// =====================================================================
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

export default function OffreClientSection() {
  const [etat, setEtat] = useState(null);        // réponse du serveur
  const [actif, setActif] = useState(false);
  const [message, setMessage] = useState("");
  const [occupe, setOccupe] = useState(false);

  useEffect(() => {
    apiClient.get("/admin/offre-client/reglages").then((r) => { setEtat(r.data); setActif(!!r.data.actif); setMessage(r.data.message || ""); })
      .catch(() => toast.error("Réglages de l'offre du client illisibles"));
  }, []);

  // Enregistre l'activation et le texte (le texte doit contenir {objet})
  const enregistrer = async () => {
    setOccupe(true);
    try {
      const { data } = await apiClient.put("/admin/offre-client/reglages", { actif, message });
      setEtat(data); setMessage(data.message || ""); toast.success("Réglages enregistrés");
    } catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible"); } finally { setOccupe(false); }
  };

  if (!etat) return <p className="text-sm text-slate-500">Chargement…</p>;
  return (
    <div className="space-y-3 text-sm text-slate-700" data-testid="offre-client-section">
      <p>
        Chaque client a sa liste de <b>logiciels, produits et services</b> (fiche client → SMART Communications ; {etat.clients_avec_offre} client(s) renseigné(s)).
        Liluvine s'en sert pour ne plus poser de questions sur nos produits, mieux orienter ses réponses, demander des précisions si elle ne
        comprend pas, sinon escalader vers un humain.
      </p>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={actif} onChange={(e) => setActif(e.target.checked)} data-testid="offre-refus-actif" />
        <span>Refuser l'assistance aux clients dont le contrat n'est pas à jour (ticket + escalade)</span>
      </label>
      <label className="block text-xs font-medium text-slate-700">
        Texte du refus — <code>{"{objet}"}</code> = ce que Liluvine a détecté (ex. « la maintenance de SAWALI CRM »). Signé par l'assistant IA.
        <textarea rows={2} maxLength={500} value={message} onChange={(e) => setMessage(e.target.value)} placeholder={etat.message_defaut}
          className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm" data-testid="offre-refus-message" />
      </label>
      <button type="button" onClick={enregistrer} disabled={occupe} className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-700 disabled:opacity-50" data-testid="offre-refus-enregistrer">
        {occupe ? "Patientez…" : "Enregistrer"}
      </button>
    </div>
  );
}
