import React, { useEffect, useRef, useState } from "react";
import { empreinteChargee, empreinteHtml, nouvelleVersionDisponible } from "@/lib/versionSite";

import { Clock as Ico15Clock, RefreshCw as Ico15RefreshCw } from "lucide-react";
/*
  Lot 264 — Bandeau « Une nouvelle version de SAWALI est disponible ».
  Toutes les minutes (et quand l'onglet redevient visible ou reprend le focus), on télécharge la page d'accueil sans cache
  et on compare ses fichiers principaux à ceux de la page ouverte. S'ils diffèrent, un bandeau propose
  d'actualiser. Réglable dans Paramètres → « Version affichée (pied de page) » (company-info : version_stamp.avertir_maj).
  Aucun effet en développement. La vérification est en arrière-plan : elle ne bloque jamais l'écran.
*/
// Lot 437 : vérification chaque MINUTE (au lieu de 5), dès que la fenêtre reprend le focus, au retour du réseau, et en contournant le cache du CDN de Render
// (la page d'accueil y est gardée jusqu'à 5 minutes) : le bandeau n'attend plus qu'on réduise puis restaure le navigateur.
const INTERVALLE_MS = 60 * 1000;

// Lot 448.2 : « Actualiser » doit RAMENER la nouvelle version. Un simple rechargement peut être servi par le CDN de Render avec l'ANCIENNE page
// (gardée jusqu'à 5 minutes) : le bandeau réapparaissait alors à chaque rechargement. On recharge donc la même adresse avec un paramètre unique
// (« maj ») : le CDN la voit comme une adresse nouvelle et va chercher la page à jour. Le paramètre est retiré de la barre d'adresse au chargement.
export function adresseSansCache(href, instant = Date.now()) {
  const u = new URL(href);
  u.searchParams.set("maj", String(instant));
  return u.toString();
}
export function adresseSansParametreMaj(href) {
  const u = new URL(href);
  u.searchParams.delete("maj");
  return u.toString();
}
const actualiserSansCache = () => window.location.replace(adresseSansCache(window.location.href));

export default function NouvelleVersionBandeau() {
  const [dispo, setDispo] = useState(false);
  const [masque, setMasque] = useState(false);
  const actif = useRef(true);   // réglage du superviseur (par défaut : actif)
  const chargee = useRef("");

  useEffect(() => {
    let vivant = true;
    try {   // adresse propre : on retire le paramètre « maj » ajouté par « Actualiser » (sans recharger la page)
      if (new URL(window.location.href).searchParams.has("maj")) window.history.replaceState(window.history.state, "", adresseSansParametreMaj(window.location.href));
    } catch (e) { /* navigateur sans history : sans importance */ }
    chargee.current = empreinteChargee(document);
    if (!chargee.current) return undefined;   // développement : rien à surveiller

    // Lit le réglage du superviseur (actif sauf si désactivé explicitement).
    fetch("/api/company-info").then((r) => r.json()).then((j) => {
      if (vivant && j?.version_stamp?.avertir_maj === false) actif.current = false;
    }).catch(() => {});

    // Compare la page ouverte à la page d'accueil actuellement en ligne.
    const verifier = () => {
      if (!actif.current || document.hidden) return;
      fetch(`/?verif=${Date.now()}`, { cache: "no-store" })   // paramètre unique : le CDN ne peut pas répondre avec une ancienne copie
        .then((r) => r.text())
        .then((html) => {
          if (vivant && nouvelleVersionDisponible(chargee.current, empreinteHtml(html))) setDispo(true);
        })
        .catch(() => {});
    };
    const id = setInterval(verifier, INTERVALLE_MS);
    document.addEventListener("visibilitychange", verifier);
    window.addEventListener("focus", verifier);       // retour sur la fenêtre (clic, alt-tab) sans l'avoir réduite
    window.addEventListener("online", verifier);      // réseau revenu
    const premier = setTimeout(verifier, 15000);      // une vérification peu après l'ouverture de la page
    return () => { vivant = false; clearInterval(id); clearTimeout(premier); document.removeEventListener("visibilitychange", verifier); window.removeEventListener("focus", verifier); window.removeEventListener("online", verifier); };
  }, []);

  if (!dispo || masque) return null;
  return (
    <div
      role="status"
      data-testid="bandeau-nouvelle-version"
      className="fixed bottom-4 left-1/2 -translate-x-1/2 z-[9999] flex items-center gap-3 rounded-xl bg-slate-900 text-white shadow-lg px-4 py-3 text-sm max-w-[92vw]"
    >
      <span>Une nouvelle version de SAWALI est disponible.</span>
      <button
        type="button"
        onClick={actualiserSansCache}
        className="rounded-lg bg-sky-500 hover:bg-sky-400 px-3 py-1 font-semibold"
        data-testid="bandeau-nouvelle-version-actualiser"
      >
        <Ico15RefreshCw className="inline-block h-4 w-4 shrink-0 mr-1" aria-hidden="true" />Actualiser</button>
      <button type="button" onClick={() => setMasque(true)} className="text-slate-300 hover:text-white">
        <Ico15Clock className="inline-block h-4 w-4 shrink-0 mr-1" aria-hidden="true" />Plus tard</button>
    </div>
  );
}
