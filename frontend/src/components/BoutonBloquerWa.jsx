// BoutonBloquerWa.jsx — Lot 453 : « ⛔ Bloquer » un contact (liste noire WhatsApp, TOUTES lignes) depuis l'en-tête de sa conversation.
// Un contact bloqué ne reçoit plus aucun message de SAWALI (donc aucun « distribué » ni « lu »), aucun agent IA ne lui répond et ses messages sont retenus.
// Réservé à l'administrateur et au superviseur. La LISTE des contacts bloqués n'est visible que dans Paramètres → « ⛔ Liste noire WhatsApp » (où l'on débloque aussi) :
// ici on ne sait que si CE contact est bloqué.
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Ban, Check, X } from "lucide-react";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

// verifierEtat=false (liste des contacts) : pas de lecture par ligne — le bouton reste « Bloquer » (idempotent) et passe à « Bloqué » après le blocage.
export default function BoutonBloquerWa({ contact, compact = false, verifierEtat = true }) {
  const { user } = useAuth();
  // Administrateur ET superviseur (le Centre de Messagerie est celui du superviseur) ; la liste et le déblocage restent dans les Paramètres (administrateur)
  const admin = ["admin", "super_admin", "superviseur"].includes(user?.role) || ["Administrateur", "Superviseur"].includes(user?.tracked_role);
  const numero = contact?.whatsapp || contact?.phone || "";
  const [bloque, setBloque] = useState(false);
  const [ouvert, setOuvert] = useState(false);
  const [motif, setMotif] = useState("");
  const [enCours, setEnCours] = useState(false);

  // Nouvelle fiche affichée : on relit si ce numéro est bloqué
  useEffect(() => {
    setBloque(false);
    if (!admin || !numero || !verifierEtat) return;
    let actif = true;
    apiClient.get("/me/wa/liste-noire/etat", { params: { telephone: numero } }).then((r) => { if (actif) setBloque(!!r.data?.bloque); }).catch(() => {});
    return () => { actif = false; };
  }, [admin, numero, contact?.id, verifierEtat]);

  if (!admin || !numero) return null;

  const confirmer = async () => {
    setEnCours(true);
    toast("Blocage du contact en cours…");
    try {
      await apiClient.post("/me/wa/liste-noire", { telephone: numero, nom: contact?.name || "", contact_id: contact?.id || null, motif });
      setBloque(true); setOuvert(false); setMotif("");
      toast.success("Contact bloqué sur toutes les lignes. Il se débloque dans Paramètres → Liste noire WhatsApp.");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Blocage impossible");
    } finally { setEnCours(false); }
  };

  if (bloque) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-1 text-xs font-semibold text-red-800" title="Contact bloqué : aucun message, aucune réponse IA. Déblocage : Paramètres → Liste noire WhatsApp." data-testid="contact-bloque-wa">
        <Ban className="h-3.5 w-3.5" aria-hidden="true" />Bloqué
      </span>
    );
  }
  return (
    <>
      <button type="button" onClick={() => setOuvert(true)} title="Bloquer ce contact (liste noire, toutes lignes)" aria-label="Bloquer ce contact"
        className={compact ? "rounded-full p-1.5 text-red-700 hover:bg-red-50" : "inline-flex items-center gap-1 rounded-lg border border-red-300 px-2 py-1 text-sm text-red-700 hover:bg-red-50"}
        data-testid="bloquer-contact-wa">
        <Ban className="h-4 w-4" aria-hidden="true" />{!compact && "Bloquer"}
      </button>
      <Dialog open={ouvert} onOpenChange={setOuvert}>
        <DialogContent className="max-w-md max-h-[85dvh] overflow-y-auto">
          <DialogHeader><DialogTitle>⛔ Bloquer ce contact ?</DialogTitle></DialogHeader>
          <div className="space-y-3 text-sm">
            <p><b>{contact?.name || numero}</b> ({numero}) ne recevra plus <b>aucun message WhatsApp</b> de SAWALI, sur aucune ligne (donc aucun « distribué » ni « lu »). Aucun agent IA ne lui répondra et ses messages seront retenus, sans notification.</p>
            <label className="block text-xs text-slate-600" htmlFor="motif-blocage">Motif (facultatif, visible dans Paramètres seulement)</label>
            <input id="motif-blocage" className="w-full rounded-lg border border-slate-300 px-3 py-2" maxLength={300} value={motif} onChange={(e) => setMotif(e.target.value)} />
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={confirmer} disabled={enCours} className="inline-flex items-center gap-2 rounded-lg bg-red-600 px-3 py-2 text-white disabled:opacity-60"><Check className="h-4 w-4" />Bloquer</button>
              <button type="button" onClick={() => setOuvert(false)} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2"><X className="h-4 w-4" />Annuler</button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
