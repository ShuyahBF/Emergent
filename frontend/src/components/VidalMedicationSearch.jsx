// Portage site-meetafrican — recherche médicament réutilisable, branchée sur
// le vrai backend VIDAL (`GET /api/vidal/search/parsed`, voir
// backend/routes/vidal_fiche.py). Remplace la simple saisie manuelle d'un ID
// VIDAL (Sécurisation) et alimente le choix de produit de Posologie / Fiche
// produit : affiche la liste filtrée en direct, sélection → remonte
// {vidal_id, title, vmp_id} au parent.
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
}) {
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const debounceRef = useRef(null);
  const blurTimeoutRef = useRef(null);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const q = (query || "").trim();
    if (q.length < 2) {
      setResults([]);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const r = await apiClient.get("/vidal/search/parsed", { params: { q } });
        setResults(r.data?.results || []);
        setOpen(true);
      } catch {
        setResults([]);
      }
      setLoading(false);
    }, DEBOUNCE_MS);
    return () => clearTimeout(debounceRef.current);
  }, [query]);

  const pick = (item) => {
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
          onChange={(e) => onQueryChange?.(e.target.value)}
          onFocus={() => results.length > 0 && setOpen(true)}
          onBlur={() => {
            // Petit délai pour laisser le onMouseDown d'un item s'exécuter
            // avant qu'on referme la liste (sinon le clic ne "prend" jamais).
            blurTimeoutRef.current = setTimeout(() => setOpen(false), 150);
          }}
          placeholder={placeholder}
          className="w-full text-xs pl-8 pr-7 py-1.5 rounded ring-1 ring-slate-300 dark:ring-slate-700 dark:bg-slate-900 dark:text-slate-100 disabled:opacity-60"
          data-testid={`${testId}-input`}
        />
        {loading && <Loader2 className="absolute right-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 animate-spin text-slate-400" />}
        {!loading && query && (
          <button
            type="button"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => { onClear?.(); setResults([]); setOpen(false); }}
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
                <span className="truncate text-slate-800 dark:text-slate-100">{highlightMatch(item.title, query)}</span>
                {item.vidal_id && (
                  <span className="shrink-0 font-mono text-[10px] text-slate-400">#{item.vidal_id}</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
      {open && !loading && (query || "").trim().length >= 2 && results.length === 0 && (
        <div
          className="absolute z-20 mt-1 w-full rounded ring-1 ring-slate-200 dark:ring-slate-700 bg-white dark:bg-slate-900 shadow-lg text-xs px-3 py-2 text-slate-400"
          data-testid={`${testId}-empty`}
        >
          Aucun médicament VIDAL trouvé.
        </div>
      )}
    </div>
  );
}
