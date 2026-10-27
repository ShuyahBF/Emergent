/*
  Lot 329 — Alertes de la page patient /suivi-rdv (bip + vibration + notification), uniquement si le patient les a activées.
  Règle pure (testée) : quelle alerte émettre quand l'état de son rendez-vous passe de `avant` à `apres` ?
  Deux moments seulement : « vous êtes le prochain » (personne devant lui) puis « c'est à vous » (consultation en cours).
*/
export function alerteAEmettre(avant, apres) {
  if (!apres) return null;
  if (apres.etat === "en_cours") {
    return avant && avant.etat === "en_cours" ? null : { cle: "en_cours", titre: "C'est à vous", texte: "Votre consultation commence : présentez-vous à la porte indiquée." };
  }
  if (apres.etat === "attente" && apres.devant === 0) {
    const dejaProchain = avant && avant.etat === "attente" && avant.devant === 0;
    return dejaProchain ? null : { cle: "prochain", titre: "Vous êtes le prochain", texte: "Préparez-vous : votre tour arrive, restez près de la porte." };
  }
  return null;
}
