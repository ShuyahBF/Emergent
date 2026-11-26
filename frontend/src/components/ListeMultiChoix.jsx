// ============================================================================
// Lot 466 — LISTE DÉROULANTE À CHOIX MULTIPLES réutilisable (recherche, cases à cocher, tout cocher / tout décocher).
// Règle du propriétaire : au-delà d'une dizaine de choix, une liste déroulante (jamais tous les éléments affichés d'un coup, qui allongeraient la page).
// `options` = [{ id, label, detail? }] ; `valeur` = liste des id cochés (SANS DOUBLON : on travaille sur un ensemble) ; `onChange(ids)` reçoit la nouvelle liste.
// « Tout cocher » ne coche que les éléments VISIBLES (filtrés par la recherche).
// ============================================================================
import React, { useMemo, useState } from "react";
import { Check, ChevronDown, Search, X } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export default function ListeMultiChoix({ options, valeur, onChange, vide = "Aucun choisi", pluriel = "choisis", disabled = false, testid = "liste-multi" }) {
  const [ouvert, setOuvert] = useState(false);
  const [q, setQ] = useState("");
  const coches = useMemo(() => new Set(valeur || []), [valeur]);
  const filtres = useMemo(() => {
    const t = q.trim().toLowerCase();
    return t ? options.filter((o) => `${o.label} ${o.detail || ""}`.toLowerCase().includes(t)) : options;
  }, [options, q]);
  const bascule = (id) => { const e = new Set(coches); if (e.has(id)) e.delete(id); else e.add(id); onChange([...e]); };
  const toutCocher = () => onChange([...new Set([...coches, ...filtres.map((o) => o.id)])]);
  const resume = coches.size === 0 ? vide : coches.size === 1 ? (options.find((o) => o.id === [...coches][0])?.label || "1 choisi") : `${coches.size} ${pluriel}`;
  return (
    <Popover open={ouvert} onOpenChange={setOuvert}>
      <PopoverTrigger asChild>
        <button type="button" disabled={disabled} data-testid={testid} className="inline-flex w-full items-center justify-between gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-left text-sm disabled:opacity-50 sm:w-80">
          <span className="truncate">{resume}</span><ChevronDown className="h-4 w-4 shrink-0" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-96 max-w-[92vw] space-y-2 p-3">
        <label className="flex items-center gap-1 rounded border border-slate-300 px-2"><Search className="h-4 w-4 text-slate-500" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Rechercher" className="w-full p-1 text-sm outline-none" data-testid={`${testid}-recherche`} /></label>
        <ul className="max-h-64 space-y-1 overflow-y-auto text-sm">
          {filtres.map((o) => (
            <li key={o.id}>
              <label className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 hover:bg-slate-100">
                <input type="checkbox" checked={coches.has(o.id)} onChange={() => bascule(o.id)} data-testid={`${testid}-case`} />
                <span className="truncate">{o.label}</span>{o.detail && <span className="ml-auto shrink-0 text-xs text-slate-500">{o.detail}</span>}
              </label>
            </li>))}
          {filtres.length === 0 && <li className="text-slate-500">Aucun résultat.</li>}
        </ul>
        <div className="flex flex-wrap items-center justify-between gap-2 boutons-distincts">
          <span className="text-xs text-slate-600">{coches.size} coché(s) sur {options.length}</span>
          <span className="flex gap-1">
            <button type="button" onClick={toutCocher} disabled={!filtres.length} data-testid={`${testid}-tout`} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-0.5 text-xs disabled:opacity-50"><Check className="h-3 w-3" /> Tout cocher</button>
            <button type="button" onClick={() => onChange([])} disabled={!coches.size} data-testid={`${testid}-rien`} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-0.5 text-xs disabled:opacity-50"><X className="h-3 w-3" /> Tout décocher</button>
          </span>
        </div>
      </PopoverContent>
    </Popover>
  );
}
