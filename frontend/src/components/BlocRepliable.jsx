// ============================================================================
// BlocRepliable.jsx — Lot 467 : bloc dont on peut replier / déplier le contenu d'un clic sur son titre (pictogramme chevron + libellé d'accessibilité).
// L'état (ouvert / replié) est retenu dans le navigateur de la personne (commodité seulement : si le stockage est indisponible, le bloc s'ouvre normalement).
// Le contenu reste MONTÉ quand le bloc est replié (sélections et résultats conservés) : il est seulement masqué.
// ============================================================================
import React, { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

export default function BlocRepliable({ id, titre, icone: Icone, resume = "", ouvertParDefaut = true, classe = "", children }) {
  const cle = `bloc-replie:${id}`;
  const [ouvert, setOuvert] = useState(() => {
    try { const v = window.localStorage.getItem(cle); return v === null ? ouvertParDefaut : v === "0" ? false : true; } catch { return ouvertParDefaut; }
  });
  const basculer = () => {
    setOuvert((o) => { const n = !o; try { window.localStorage.setItem(cle, n ? "1" : "0"); } catch { /* sans stockage : l'état n'est pas retenu */ } return n; });
  };
  return (
    <section className={`rounded-xl border bg-white ${classe}`} data-testid={`bloc-${id}`}>
      <button type="button" onClick={basculer} aria-expanded={ouvert} aria-label={`${ouvert ? "Replier" : "Déplier"} : ${titre}`} data-testid={`bloc-${id}-titre`}
        className="flex w-full items-center gap-2 rounded-xl px-4 py-3 text-left">
        {ouvert ? <ChevronDown className="h-5 w-5 text-slate-600" /> : <ChevronRight className="h-5 w-5 text-slate-600" />}
        {Icone && <Icone className="h-5 w-5 text-slate-700" />}
        <span className="text-lg font-bold text-slate-900">{titre}</span>
        {!ouvert && resume && <span className="ml-2 truncate text-sm text-slate-500">{resume}</span>}
        <span className="ml-auto text-xs font-semibold text-slate-500">{ouvert ? "Replier" : "Déplier"}</span>
      </button>
      <div className={ouvert ? "space-y-4 px-4 pb-4" : "hidden"} data-testid={`bloc-${id}-contenu`}>{children}</div>
    </section>
  );
}
