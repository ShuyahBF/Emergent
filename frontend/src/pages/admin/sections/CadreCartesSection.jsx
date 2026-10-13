// =====================================================================
// Lot 136 — Rubrique des Paramètres « 🖼️ Cadre des cartes » : couleur du mince filet qui encadre les cartes d'information
// (du gris sur du gris se distinguait mal). Réglage commun à tout SAWALI, appliqué aussitôt et à chaque démarrage via
// GET /api/public/ui-flags (champ ui_carte_filet). Enregistrement direct : PUT /api/admin/settings { ui_carte_filet }.
// =====================================================================
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";

// Choix proposés : valeur enregistrée → libellé et couleur d'aperçu (mêmes couleurs que index.css)
const CHOIX = [
  ["noir", "Noir", "#111827"],
  ["gris", "Gris foncé", "#475569"],
  ["bleu", "Bleu", "#1d4ed8"],
  ["aucun", "Aucun (gris clair d'origine)", "#e2e8f0"],
];

export default function CadreCartesSection() {
  const [valeur, setValeur] = useState("noir");
  const [occupe, setOccupe] = useState(false);

  // Valeur actuellement enregistrée
  useEffect(() => {
    apiClient.get("/public/ui-flags").then((r) => setValeur(r.data?.ui_carte_filet || "noir")).catch(() => {});
  }, []);

  // Enregistre et applique tout de suite (sans recharger la page)
  const choisir = async (v) => {
    setOccupe(true);
    try {
      await apiClient.put("/admin/settings", { ui_carte_filet: v });
      setValeur(v);
      document.documentElement.setAttribute("data-carte-filet", v);
      try { window.dispatchEvent(new CustomEvent("ui-flags-updated")); } catch { /* sans conséquence */ }
      toast.success("Cadre des cartes enregistré");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Enregistrement impossible");
    } finally { setOccupe(false); }
  };

  return (
    <div className="space-y-3 text-sm text-slate-700" data-testid="cadre-cartes-section">
      <p>Couleur du mince filet qui encadre les cartes d'information (réglage commun à tous les écrans de SAWALI).</p>
      <div className="flex flex-wrap gap-3">
        {CHOIX.map(([cle, libelle, couleur]) => (
          <label key={cle} className={`flex cursor-pointer items-center gap-2 rounded-lg bg-white px-3 py-2 ring-1 ring-slate-200 ${valeur === cle ? "outline outline-2 outline-sky-500" : ""}`}>
            <input type="radio" name="cadre-cartes" checked={valeur === cle} disabled={occupe} onChange={() => choisir(cle)} data-testid={`cadre-cartes-${cle}`} />
            <span className="inline-block h-6 w-10 rounded-md bg-white" style={{ border: `1px solid ${couleur}` }} aria-hidden="true" />
            {libelle}
          </label>
        ))}
      </div>
    </div>
  );
}
