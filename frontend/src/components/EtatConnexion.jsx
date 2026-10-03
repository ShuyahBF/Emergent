import React, { useEffect, useState, useCallback } from "react";

/*
  État de connexion + version du déploiement (page de connexion et barre latérale).

  - Pastille verte  : le serveur répond (temps de réponse affiché).
  - Pastille orange : le serveur répond lentement (plus de 2 s).
  - Pastille rouge  : pas de réseau sur l'appareil, ou serveur injoignable.
  - Version : numéro de déploiement, commit et date/heure de mise en ligne
    (lus sur /api/version, sans aucune donnée sensible).

  Vérification toutes les 30 s, et immédiatement quand l'appareil retrouve
  ou perd le réseau. `tone` : "dark" (barre latérale) ou "light" (connexion).
*/
const LENT_MS = 2000;      // au-delà : connexion lente (orange)
const INTERVALLE_MS = 30000;

export default function EtatConnexion({ tone = "light", className = "", compact = false }) {
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

  const misEnLigne = version?.started_at
    ? new Date(version.started_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })
    : null;

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
          Version {version.version}
          {/* Règle permanente : le numéro de lot accompagne toujours la version */}
          {version.lot ? ` · Lot ${version.lot}` : ""}
          {version.git_sha && version.git_sha !== "unknown" ? ` · ${version.git_sha}` : ""}
          {misEnLigne ? ` · déployée le ${misEnLigne}` : ""}
        </div>
      )}
    </div>
  );
}
