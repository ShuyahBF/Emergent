// PastilleLigneWa.jsx — Lot 59.1 : pastille colorée indiquant la ligne WhatsApp de Liluvine
// (ex. « Liluvine Standard » texte noir sur fond blanc, « Liluvine VIP » sur fond or…).
// Couleurs définies dans Administration → Paramètres → WhatsApp Business API.
// Utilisée dans le Centre de messagerie (liste des contacts, messages reçus) et l'Inbox unifiée.
import React from "react";

export default function PastilleLigneWa({ libelle, fond, texte, testid, className = "" }) {
  // Rien à afficher si la ligne est inconnue (une seule ligne configurée)
  if (!libelle) return null;
  return (
    <span
      className={`shrink-0 inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold ring-1 ring-slate-300 ${className}`}
      // Couleurs choisies par l'administrateur (par défaut : texte noir sur fond blanc)
      style={{ backgroundColor: fond || "#ffffff", color: texte || "#000000" }}
      title={`Ligne WhatsApp : ${libelle}`}
      data-testid={testid}
    >
      {libelle}
    </span>
  );
}
