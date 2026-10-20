// majContact.js — Lot 263 : met à jour UNE fiche dans une liste de contacts, sans toucher aux autres.
//
// Utilisé par le Centre de messagerie : quand on clique « Prospect » (ou qu'on corrige un numéro WhatsApp), seule la ligne
// concernée change. Les autres fiches gardent EXACTEMENT le même objet (même identité) : rien d'autre n'est redessiné et la
// liste n'est ni relue ni remplacée par « Chargement… ».
export function majFiche(liste, id, champs) {
  return (liste || []).map((fiche) => (fiche.id === id ? { ...fiche, ...champs } : fiche));
}
