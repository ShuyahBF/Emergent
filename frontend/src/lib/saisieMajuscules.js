// Saisie en MAJUSCULES sans que le curseur saute à la fin (constat du propriétaire, 23/11/2026 : « quand on modifie une valeur dans le champ motif ou complément d'information,
// le curseur est systématiquement ramené à la fin »).
// Cause : un champ contrôlé dont la valeur est transformée (minuscule tapée -> majuscule rangée) est réécrit par React, qui replace le curseur à la fin.
// Remède : on range la valeur en majuscules IMMÉDIATEMENT (flushSync) puis on remet le curseur (ou la sélection) exactement où il était.
import { flushSync } from "react-dom";

/** À appeler dans onChange : `onChange={(e) => saisieMajuscules(e, (v) => setForm({ ...form, notes: v }))}`. */
export function saisieMajuscules(e, appliquer) {
  const champ = e.target;
  const debut = champ.selectionStart;
  const fin = champ.selectionEnd;
  flushSync(() => appliquer(champ.value.toUpperCase()));
  // Après le rendu synchrone : le curseur retrouve sa place (sans effet sur les types de champ qui n'ont pas de curseur)
  try { if (debut != null && fin != null) champ.setSelectionRange(debut, fin); } catch { /* type de champ sans sélection */ }
}
