// Champ « Client lié » avec RECHERCHE sur tout ou partie d'une valeur (demande du propriétaire, 23/11/2026) :
// on tape un morceau du code, du nom ou de la société (sans tenir compte des majuscules ni des accents), la liste se réduit, un clic (ou Entrée) choisit.
// Modifier le texte après un choix efface le choix (il faut en reprendre un dans la liste) : le client lié est toujours un client RÉEL de la liste.
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Search, X } from "lucide-react";
import { filtrerClients, libelleClient } from "@/lib/rechercheClients";

export default function ChampClientRecherche({ clients, valeur, onChoisir, testId = "client-recherche", libelle: libelleDe = libelleClient }) {
  const choisi = useMemo(() => clients.find((c) => c.id === valeur) || null, [clients, valeur]);
  const [saisie, setSaisie] = useState("");
  const [ouvert, setOuvert] = useState(false);
  const [actif, setActif] = useState(0);
  const zone = useRef(null);

  // Le texte affiché suit le choix. Sans choix, le texte tapé n'est JAMAIS effacé (la fenêtre est refermée puis recréée après l'envoi d'un ticket : champ vide au départ).
  useEffect(() => { if (choisi) setSaisie(libelleDe(choisi)); }, [choisi]);
  // Un clic en dehors referme la liste
  useEffect(() => {
    const dehors = (e) => { if (zone.current && !zone.current.contains(e.target)) setOuvert(false); };
    document.addEventListener("mousedown", dehors);
    return () => document.removeEventListener("mousedown", dehors);
  }, []);

  // Si un client est choisi et que le texte est inchangé, on montre toute la liste ; sinon on filtre sur ce qui est tapé
  const filtre = choisi && saisie === libelleDe(choisi) ? "" : saisie;
  const trouves = useMemo(() => filtrerClients(clients, filtre, 50), [clients, filtre]);

  const choisir = (c) => { onChoisir(c.id); setSaisie(libelleDe(c)); setOuvert(false); };
  const surSaisie = (e) => { setSaisie(e.target.value); setOuvert(true); setActif(0); if (valeur) onChoisir(""); };
  const surTouche = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setOuvert(true); setActif((i) => Math.min(i + 1, trouves.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActif((i) => Math.max(i - 1, 0)); }
    else if (e.key === "Enter" && ouvert && trouves[actif]) { e.preventDefault(); choisir(trouves[actif]); }
    else if (e.key === "Escape") setOuvert(false);
  };

  return (
    <div ref={zone} className="relative">
      <div className="mt-1 flex items-center rounded-lg border border-slate-300 bg-white focus-within:ring-2 focus-within:ring-slate-400">
        <Search className="ml-2 h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
        <input type="text" value={saisie} onChange={surSaisie} onFocus={() => setOuvert(true)} onKeyDown={surTouche} autoComplete="off" role="combobox" aria-expanded={ouvert}
          placeholder="Tapez une partie du code ou du nom…" className="w-full rounded-lg bg-transparent px-2 py-2 text-sm outline-none" data-testid={testId} />
        {saisie && <button type="button" aria-label="Effacer le client" title="Effacer" onClick={() => { setSaisie(""); onChoisir(""); setOuvert(true); }} className="mr-2 text-slate-400 hover:text-slate-700"><X className="h-4 w-4" aria-hidden="true" /></button>}
      </div>
      {ouvert && (
        <ul role="listbox" className="absolute z-10 mt-1 max-h-56 w-full overflow-y-auto rounded-lg border border-slate-200 bg-white text-sm shadow-lg" data-testid={`${testId}-liste`}>
          {trouves.length === 0 && <li className="px-3 py-2 text-slate-500">Aucun client ne correspond.</li>}
          {trouves.map((c, i) => (
            <li key={c.id} role="option" aria-selected={c.id === valeur}>
              <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => choisir(c)}
                className={`block w-full px-3 py-1.5 text-left hover:bg-sky-50 ${i === actif ? "bg-sky-50" : ""} ${c.id === valeur ? "font-semibold" : ""}`}>{libelleDe(c)}</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
