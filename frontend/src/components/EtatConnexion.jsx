import React, { useEffect, useState, useCallback } from "react";

/*
  État de connexion + version du déploiement (page de connexion et barre latérale).

  - Pastille verte  : le serveur répond (temps de réponse affiché).
  - Pastille orange : le serveur répond lentement (plus de 2 s).
  - Pastille rouge  : pas de réseau sur l'appareil, ou serveur injoignable.
  - Version (lue sur /api/version, sans aucune donnée sensible) — règle du
    propriétaire du 04/10/2026 :
      * connexion et barre latérale : « Version X · déployée le JJ/MM/AAAA HH:MM » ;
      * pages d'administration / paramétrage (prop `detaille`) :
        « Version X · Lot N · commit · déployée le JJ/MM/AAAA HH:MM ».

  Vérification toutes les 30 s, et immédiatement quand l'appareil retrouve
  ou perd le réseau. `tone` : "dark" (barre latérale) ou "light" (connexion).
*/
const LENT_MS = 2000;      // au-delà : connexion lente (orange)
const INTERVALLE_MS = 30000;

/*
  libelleVersion(version, detaille) — construit le texte de version à afficher.
  `version` : objet renvoyé par /api/version ({ version, lot, git_sha, started_at }).
  `detaille` : false (défaut) → « Version X · déployée le JJ/MM/AAAA HH:MM »
               true           → « Version X · Lot N · commit · déployée le JJ/MM/AAAA HH:MM ».
  Renvoie "" si l'objet est absent. Fonction exportée pour être réutilisée
  (bandeau des pages d'administration, tampon de version).
*/
export function libelleVersion(version, detaille = false) {
  if (!version) return "";
  // Date/heure de mise en ligne au format français court (ex. « 04/10/2026 01:35 »)
  const misEnLigne = version.started_at
    ? new Date(version.started_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })
    : null;
  const morceaux = [`Version ${version.version}`];
  if (detaille) {
    // Libellé complet réservé à l'administration : lot puis commit court
    if (version.lot) morceaux.push(`Lot ${version.lot}`);
    if (version.git_sha && version.git_sha !== "unknown") morceaux.push(version.git_sha);
  }
  if (misEnLigne) morceaux.push(`déployée le ${misEnLigne}`);
  return morceaux.join(" · ");
}

/*
  BandeauVersion — petit bandeau discret affichant le libellé DÉTAILLÉ de la
  version (pages d'administration / paramétrage). Lit /api/version une fois
  au chargement ; n'affiche rien tant que la réponse n'est pas arrivée.
*/
export function BandeauVersion({ className = "" }) {
  const [version, setVersion] = useState(null);
  useEffect(() => {
    let actif = true;   // évite une mise à jour d'état après fermeture de la page
    fetch("/api/version", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => { if (actif && j) setVersion(j); })
      .catch(() => {});
    return () => { actif = false; };
  }, []);
  if (!version) return null;
  return (
    <p className={`text-[11px] text-slate-500 font-mono ${className}`} data-testid="bandeau-version-detaillee">
      {libelleVersion(version, true)}
    </p>
  );
}

export default function EtatConnexion({ tone = "light", className = "", compact = false, detaille = false }) {
  const [etat, setEtat] = useState({ statut: "verif", ms: null });
  const [version, setVersion] = useState(null);

  // Test de joignabilité du serveur (route publique /api/health)
  const verifier = useCallback(async () => {
    if (typeof navigator !== "undefined" && navigator.onLine === false) {
      setEtat({ statut: "hors_ligne", ms: null });
      return;
    }
    const debut = performance.now();
    try {
      const ctrl = new AbortController();
      const minuterie = setTimeout(() => ctrl.abort(), 10000);
      const r = await fetch("/api/health", { cache: "no-store", signal: ctrl.signal });
      clearTimeout(minuterie);
      const ms = Math.round(performance.now() - debut);
      if (!r.ok) throw new Error(String(r.status));
      setEtat({ statut: ms > LENT_MS ? "lent" : "ok", ms });
    } catch {
      setEtat({ statut: "injoignable", ms: null });
    }
  }, []);

  // Version du déploiement (rafraîchie toutes les 5 min : un redéploiement est visible sans recharger)
  const lireVersion = useCallback(() => {
    fetch("/api/version", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => j && setVersion(j))
      .catch(() => {});
  }, []);

  useEffect(() => {
    verifier();
    lireVersion();
    const t1 = setInterval(verifier, INTERVALLE_MS);
    const t2 = setInterval(lireVersion, 5 * 60 * 1000);
    window.addEventListener("online", verifier);
    window.addEventListener("offline", verifier);
    return () => {
      clearInterval(t1);
      clearInterval(t2);
      window.removeEventListener("online", verifier);
      window.removeEventListener("offline", verifier);
    };
  }, [verifier, lireVersion]);

  // Libellé et couleur de la pastille selon l'état
  const AFFICHAGE = {
    verif: { couleur: "bg-slate-400", texte: "Vérification…" },
    ok: { couleur: "bg-emerald-500", texte: "Connecté au serveur" },
    lent: { couleur: "bg-amber-500", texte: "Connexion lente" },
    injoignable: { couleur: "bg-red-500", texte: "Serveur injoignable" },
    hors_ligne: { couleur: "bg-red-500", texte: "Pas de réseau" },
  };
  const a = AFFICHAGE[etat.statut] || AFFICHAGE.verif;

  const sombre = tone === "dark";
  return (
    <div
      // compact (barre latérale) : police réduite (11 → 8 px) pour rester lisible
      className={`${compact ? "text-[8px]" : "text-[11px]"} leading-tight ${sombre ? "text-slate-300" : "text-slate-500"} ${className}`}
      data-testid="etat-connexion"
    >
      <div className="flex items-center gap-1.5">
        <span className={`inline-block ${compact ? "h-1.5 w-1.5" : "h-2 w-2"} rounded-full shrink-0 ${a.couleur} ${etat.statut === "ok" ? "animate-pulse" : ""}`} />
        <span data-testid="etat-connexion-statut">{a.texte}</span>
        {etat.ms != null && <span className="opacity-70">· {etat.ms} ms</span>}
        <button
          type="button"
          onClick={verifier}
          className={`ml-auto underline-offset-2 hover:underline ${sombre ? "text-slate-400" : "text-slate-400"}`}
          title="Vérifier maintenant"
        >
          ↻
        </button>
      </div>
      {version && (
        <div className="mt-0.5 opacity-80" data-testid="etat-connexion-version">
          {/* Connexion / barre latérale : « Version X · déployée le … » ;
              libellé complet (lot + commit) seulement si `detaille` */}
          {libelleVersion(version, detaille)}
        </div>
      )}
    </div>
  );
}
