// Portage site-meetafrican — recherche médicament réutilisable, branchée sur
// le vrai backend VIDAL (`GET /api/vidal/search/parsed`, voir
// backend/routes/vidal_fiche.py). Remplace la simple saisie manuelle d'un ID
// VIDAL (Sécurisation) et alimente le choix de produit de Posologie / Fiche
// produit : affiche la liste filtrée en direct, sélection → remonte
// {vidal_id, title, vmp_id} au parent.
//
// Lot 56 (Sécurisation VIDAL v2, repris de Ster) :
//   - la recherche part UNIQUEMENT d'une frappe dans le champ (et non plus
//     d'un `useEffect` sur la prop `query`) : un libellé reçu du parent
//     (sélection, traitement en cours rechargé...) n'ouvre plus jamais la
//     liste par-dessus la ligne — même correctif que dans Ster ;
//   - prop `forme` (code ou identifiant de forme galénique, filtre
//     « Forme recherchée ») transmise au backend ;
//   - prop `rechercheAutomatique` : lance UNE recherche au montage (ligne
//     ajoutée volontairement depuis une prescription de test) ;
//   - la forme galénique renvoyée par VIDAL est affichée à côté du nom ;
//   - un refus (403 / 429 : module non activé, quota atteint) est affiché.
// Les autres pages (Fiche produit, Posologie, Analyse prescription)
// utilisent ce composant exactement comme avant.
import React, { useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api";
import { Loader2, Search, X } from "lucide-react";
import { highlightMatch } from "@/lib/highlightMatch";

const DEBOUNCE_MS = 350;

export default function VidalMedicationSearch({
  query,
  onQueryChange,
  onSelect,
  onClear,
  placeholder = "Nom du médicament (ex : Doliprane 1000)…",
  testId = "vidal-med-search",
  disabled = false,
  forme = null,
  rechercheAutomatique = false,
}) {
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [refus, setRefus] = useState("");
  const debounceRef = useRef(null);
  // `requestIdRef` identifie la requête "courante" : toute réponse qui arrive
  // alors qu'elle n'est plus la plus récente (nouvelle frappe OU sélection
  // entre-temps) est ignorée — sinon une réponse en vol rouvrirait la liste
  // par-dessus le médicament tout juste choisi.
  const requestIdRef = useRef(0);

  // Nettoyage du minuteur quand le composant disparaît.
  useEffect(() => () => clearTimeout(debounceRef.current), []);

  // Recherche automatique UNE fois au montage (prescription de test ajoutée volontairement).
  useEffect(() => {
    if (rechercheAutomatique && (query || "").trim().length >= 2) lancerRecherche(query);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function lancerRecherche(texteSaisi) {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const q = (texteSaisi || "").trim();
    if (q.length < 2) {
      requestIdRef.current += 1;
      setResults([]);
      setOpen(false);
      return;
    }
    const myRequestId = ++requestIdRef.current;
    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const r = await apiClient.get("/vidal/search/parsed", { params: { q, forme: forme || undefined } });
        if (requestIdRef.current !== myRequestId) return; // réponse obsolète
        setRefus("");
        setResults(r.data?.results || []);
        setOpen(true);
      } catch (err) {
        if (requestIdRef.current === myRequestId) {
          setResults([]);
          const statut = err?.response?.status;
          setRefus(statut === 403 || statut === 429 ? (err.response?.data?.detail || "Accès refusé.") : "");
        }
      }
      if (requestIdRef.current === myRequestId) setLoading(false);
    }, DEBOUNCE_MS);
  }

  const pick = (item) => {
    requestIdRef.current += 1; // invalide toute recherche encore en vol au moment du clic
    if (debounceRef.current) clearTimeout(debounceRef.current);
    onSelect?.(item);
    setOpen(false);
    setResults([]);
  };

  return (
    <div className="relative" data-testid={testId}>
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400 dark:text-slate-500" />
        <input
          type="text"
          value={query || ""}
          disabled={disabled}
          onChange={(e) => {
            const v = e.target.value;
            onQueryChange?.(v);
            lancerRecherche(v);
          }}
          onFocus={() => results.length > 0 && setOpen(true)}
          // Petit délai pour laisser le onMouseDown d'un item s'exécuter avant de refermer la liste.
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder={placeholder}
          className="w-full text-xs pl-8 pr-7 py-1.5 rounded ring-1 ring-slate-300 dark:ring-slate-700 bg-white dark:bg-slate-900 dark:text-slate-100 disabled:opacity-60"
          data-testid={`${testId}-input`}
        />
        {loading && <Loader2 className="absolute right-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 animate-spin text-slate-400" />}
        {!loading && query && (
          <button
            type="button"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => {
              onClear?.(); setResults([]); setOpen(false);
              requestIdRef.current += 1;
              if (debounceRef.current) clearTimeout(debounceRef.current);
            }}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
            data-testid={`${testId}-clear`}
          >
            <X className="h-3 w-3" />
          </button>
        )}
      </div>
      {open && results.length > 0 && (
        <ul
          className="absolute z-20 mt-1 w-full max-h-56 overflow-auto rounded ring-1 ring-slate-200 dark:ring-slate-700 bg-white dark:bg-slate-900 shadow-lg text-xs"
          data-testid={`${testId}-results`}
        >
          {results.map((item, i) => (
            <li key={`${item.vidal_id || i}-${i}`}>
              <button
                type="button"
                onMouseDown={(e) => { e.preventDefault(); pick(item); }}
                className="w-full text-left px-3 py-2 hover:bg-slate-50 dark:hover:bg-slate-800 flex items-center justify-between gap-2"
                data-testid={`${testId}-result-${i}`}
              >
                <span className="truncate text-slate-800 dark:text-slate-100">
                  {highlightMatch(item.title, query)}
                  {item.galenic_form ? <span className="text-slate-400"> — {item.galenic_form}</span> : null}
                </span>
                {item.vidal_id && (
                  <span className="shrink-0 font-mono text-[10px] text-slate-400">#{item.vidal_id}</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
      {refus && <div className="mt-1 text-xs text-red-600 dark:text-red-400">{refus}</div>}
      {open && !loading && !refus && (query || "").trim().length >= 2 && results.length === 0 && (
        <div
          className="absolute z-20 mt-1 w-full rounded ring-1 ring-slate-200 dark:ring-slate-700 bg-white dark:bg-slate-900 shadow-lg text-xs px-3 py-2 text-slate-400"
          data-testid={`${testId}-empty`}
        >
          {forme ? "Aucun médicament VIDAL trouvé pour cette forme." : "Aucun médicament VIDAL trouvé."}
        </div>
      )}
    </div>
  );
}
