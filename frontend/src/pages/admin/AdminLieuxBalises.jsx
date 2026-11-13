// AdminLieuxBalises.jsx — Lot 388 : page « Lieux (balises) » du menu, pour l'administrateur ET le superviseur.
// Même contenu que la rubrique « 📍 Lieux — Vous êtes ici » des Paramètres (un seul composant).
import React from "react";
import LieuxBalisesSection from "@/pages/admin/sections/LieuxBalisesSection";

export default function AdminLieuxBalises() {
  return (
    <div className="space-y-4 p-4 md:p-6">
      <h1 className="font-display text-xl font-bold">Lieux (balises) — « Vous êtes ici »</h1>
      <LieuxBalisesSection />
    </div>
  );
}
