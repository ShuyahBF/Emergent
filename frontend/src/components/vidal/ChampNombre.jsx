// components/vidal/ChampNombre.jsx
// -----------------------------------
// Lot 56.4 — champ numérique « spin » commun aux pages VIDAL (Sécurisation et
// Analyse prescription), demande du propriétaire :
//   - <input type="number"> avec ses flèches haut / bas ;
//   - `min` JAMAIS en dessous de 0 (0 par défaut, ou la borne métier si elle est
//     plus haute : clairance 1, durée 1...) ; `step` adapté (1, 0.1, 0.5...) ;
//   - un nombre NÉGATIF ne peut pas être saisi : la touche « - » (et « e », « + »,
//     qui permettent d'écrire « 1e-3 ») est bloquée au clavier, un collage
//     négatif est refusé, et une valeur négative éventuelle est effacée en
//     quittant le champ (blur).
// Le composant se branche comme un <input> classique : `onChange` reçoit
// l'événement (e.target.value), comme avant, ce qui évite de modifier les
// gestionnaires existants des pages.

import React from "react";

// Touches refusées dans un champ de nombre positif.
const TOUCHES_INTERDITES = ["-", "+", "e", "E"];

/** Vrai si le texte représente un nombre strictement négatif. */
function estNegatif(texte) {
  const n = Number(String(texte ?? "").replace(",", "."));
  return String(texte ?? "").trim().startsWith("-") || (!Number.isNaN(n) && n < 0);
}

export default function ChampNombre({ min = 0, step = "any", onChange, onKeyDown, onBlur, onPaste, value, ...reste }) {
  // Borne basse affichée : jamais négative (une borne métier plus haute est conservée).
  const minimum = Math.max(0, Number(min) || 0);

  // Clavier : on bloque le signe moins et la notation scientifique.
  function surTouche(e) {
    if (TOUCHES_INTERDITES.includes(e.key)) e.preventDefault();
    if (onKeyDown) onKeyDown(e);
  }

  // Collage : un nombre négatif (ou en notation « e ») est refusé.
  function surCollage(e) {
    const texte = e.clipboardData?.getData("text") || "";
    if (estNegatif(texte) || /e/i.test(texte)) e.preventDefault();
    if (onPaste) onPaste(e);
  }

  // Saisie : une valeur négative n'est jamais transmise au parent.
  function surChangement(e) {
    if (estNegatif(e.target.value)) return;
    if (onChange) onChange(e);
  }

  // Sortie du champ : correction de sécurité (valeur négative -> champ vidé).
  function surSortie(e) {
    if (estNegatif(e.target.value) && onChange) onChange({ target: { value: "" } });
    if (onBlur) onBlur(e);
  }

  return (
    <input
      type="number"
      inputMode="decimal"
      min={minimum}
      step={step}
      value={value ?? ""}
      onChange={surChangement}
      onKeyDown={surTouche}
      onPaste={surCollage}
      onBlur={surSortie}
      {...reste}
    />
  );
}
