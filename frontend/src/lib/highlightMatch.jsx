// Met en évidence (rouge, gras) la portion d'un résultat qui correspond au
// texte tapé par l'utilisateur dans une liste filtrée au fur et à mesure de
// la saisie (recherche médicament, allergie, pathologie, molécule...).
// Comportement de la maquette d'origine (site-meetafrican) qui manquait
// depuis le portage initial — repéré par l'utilisateur en test réel.
import React from "react";

export function highlightMatch(text, query) {
  const full = text == null ? "" : String(text);
  const q = (query || "").trim();
  if (!q) return full;
  const idx = full.toLowerCase().indexOf(q.toLowerCase());
  if (idx === -1) return full;
  return (
    <>
      {full.slice(0, idx)}
      <mark className="bg-transparent text-red-600 dark:text-red-400 font-bold">
        {full.slice(idx, idx + q.length)}
      </mark>
      {full.slice(idx + q.length)}
    </>
  );
}
