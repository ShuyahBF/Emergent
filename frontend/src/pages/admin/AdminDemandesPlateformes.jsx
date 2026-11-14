// AdminDemandesPlateformes.jsx — Lot 393 : option du menu « Plateformes » → « Demandes des plateformes » (plus dans les Paramètres : ce n'est pas un paramétrage).
// Les plateformes clientes (ALBARKA…) remontent leurs corrections et nouvelles fonctionnalités ; SAWALI leur attribue un numéro DEM-… et leur retourne le statut.
// Le traitement lui-même (en attente, réalisée, refusée) reste dans DemandesPlateformesSection ; cette page ajoute le titre et le bouton « Actualiser » (règle 17).
import React, { useState } from "react";
import { toast } from "sonner";
import { RefreshCw } from "lucide-react";
import DemandesPlateformesSection from "@/pages/admin/sections/DemandesPlateformesSection";

export default function AdminDemandesPlateformes() {
  const [relecture, setRelecture] = useState(0);        // changer la clé relit la liste depuis le serveur
  const actualiser = () => {
    toast.info("Actualisation des demandes en cours…");
    setRelecture((n) => n + 1);
    setTimeout(() => toast.success("Demandes relues depuis le serveur."), 600);
  };
  return (
    <div className="space-y-4" data-testid="page-demandes-plateformes">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex-1">
          <h1 className="text-2xl font-bold">📮 Demandes des plateformes</h1>
          <p className="text-sm text-slate-600">Corrections et nouvelles fonctionnalités demandées par ALBARKA et les autres plateformes : numéro, statut, commentaire, dates.</p>
        </div>
        <button type="button" onClick={actualiser} className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-50"
          title="Relire les demandes depuis le serveur" data-testid="demandes-actualiser"><RefreshCw className="h-4 w-4" />Actualiser</button>
      </div>
      <DemandesPlateformesSection key={relecture} />
    </div>
  );
}
