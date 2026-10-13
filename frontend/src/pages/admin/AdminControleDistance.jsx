// =====================================================================
// Lot 135.1 — Barre latérale : Plateformes → « Contrôle à distance ».
// Même contenu que la rubrique des Paramètres « 🖥️ Contrôle à distance Loois » (réglages, postes Loois, identifiants
// Windows, journal des prises en main, vidéos), accessible en un clic depuis le menu « Plateformes ».
// Le composant est PARTAGÉ avec la rubrique (ControleDistanceSection) : une seule source, rien en double.
// =====================================================================
import React from "react";
import { MonitorSmartphone } from "lucide-react";
import ControleDistanceSection from "@/pages/admin/sections/ControleDistanceSection";

export default function AdminControleDistance() {
  return (
    <div className="max-w-6xl space-y-4" data-testid="page-controle-distance">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-display font-bold">
          <MonitorSmartphone className="h-6 w-6 text-sky-600" />Contrôle à distance des postes Loois
        </h1>
        <p className="text-xs text-slate-500">Prendre la main, postes, identifiants Windows, journal et vidéos des prises en main.</p>
      </div>
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <ControleDistanceSection lienPage={false} />
      </div>
    </div>
  );
}
