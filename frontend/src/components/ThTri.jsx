// ThTri.jsx — en-tête de colonne TRIABLE (règle 19) : un clic trie croissant, un second décroissant, un troisième revient à l'ordre d'origine.
// Pictogramme ▲ / ▼ sur la colonne triée (jamais la couleur seule), ⇅ discret sur les autres ; l'en-tête trié passe en orange (comme sur e-Kol).
import React from "react";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";

/**
 * cle : identifiant de la colonne ; tri : { cle, sens } courant (ou null) ; onTri(cle) : appelé au clic.
 * droite : colonne de nombres (alignée à droite, en-tête compris — règle des tableaux).
 */
export default function ThTri({ cle, tri, onTri, droite = false, children, className = "" }) {
  const actif = tri?.cle === cle;
  const Icone = !actif ? ArrowUpDown : tri.sens === "asc" ? ArrowUp : ArrowDown;
  return (
    <th className={`p-2 ${droite ? "text-right" : ""} ${className}`} aria-sort={actif ? (tri.sens === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" onClick={() => onTri(cle)} data-testid={`tri-${cle}`}
              title={actif ? (tri.sens === "asc" ? "Trié du plus petit au plus grand : cliquer pour inverser" : "Trié du plus grand au plus petit : cliquer pour annuler le tri") : "Trier cette colonne"}
              className={`inline-flex items-center gap-1 font-semibold ${actif ? "text-orange-600" : ""}`}>
        {children}<Icone className={`h-3.5 w-3.5 ${actif ? "" : "opacity-40"}`} aria-hidden="true" />
      </button>
    </th>
  );
}
