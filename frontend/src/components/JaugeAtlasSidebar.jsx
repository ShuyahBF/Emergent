// JaugeAtlasSidebar.jsx — Lots 79.9 / 79.10 : jauge des collections du cluster Atlas dans la barre latérale
// (administrateur).
// Un cluster Atlas Flex accepte au plus 500 collections pour toutes les bases réunies (SAWALI, ALBARKA, DentalCare,
// adLyn…). Couleurs (demande du propriétaire) : vert sous 45 % · orange à partir de 45 % · rouge quand il ne reste
// que 10 % ou moins.
// Lot 79.10 — bas de la barre latérale compact : la jauge devient une PASTILLE dans la ligne d'icônes (couleur + %),
// et son DÉTAIL (barre, total, bases) se déplie dans le panneau commun, au clic sur la pastille.
import React, { useCallback, useEffect, useState } from "react";
import { Database } from "lucide-react";
import { apiClient } from "@/lib/api";
import { siVisible } from "@/lib/visibilite";   // pas de relecture quand l'onglet est masqué

// Couleurs selon le niveau renvoyé par le serveur (ok < 45 % ≤ attention < 90 % ≤ plein)
const STYLES = {
  ok: { barre: "bg-emerald-400", point: "bg-emerald-400", texte: "text-emerald-200" },
  attention: { barre: "bg-amber-400", point: "bg-amber-400", texte: "text-amber-200" },
  plein: { barre: "bg-rose-500", point: "bg-rose-500 animate-pulse", texte: "text-rose-200" },
};

// Lecture de la dernière mesure (moins de 15 min côté serveur), relue toutes les 15 min onglet visible
export function useMesureAtlas(actif = true) {
  const [mesure, setMesure] = useState(null);
  const lire = useCallback(() => {
    apiClient.get("/admin/atlas/quota", { params: { recente: true } })
      .then((r) => setMesure(r.data)).catch(() => setMesure(null));
  }, []);
  useEffect(() => {
    if (!actif) return undefined;
    lire();
    const t = setInterval(siVisible(lire), 15 * 60 * 1000);
    return () => clearInterval(t);
  }, [actif, lire]);
  return mesure;
}

// Pastille de la ligne d'icônes : point de couleur + pourcentage
export function PastilleAtlas({ mesure, ouvert, onClick }) {
  if (!mesure) return null;
  const st = STYLES[mesure.niveau] || STYLES.ok;
  return (
    <button type="button" onClick={onClick} aria-expanded={ouvert}
      className={`flex-1 inline-flex items-center justify-center gap-1 text-[10px] rounded px-1.5 py-1 ring-1 transition-colors tabular-nums ${ouvert ? "bg-white/15 text-white ring-white/30" : "bg-white/5 text-slate-300 ring-white/10 hover:bg-white/10"}`}
      title={`Base Atlas : ${mesure.total} collections sur ${mesure.limite} (${mesure.pourcentage} %) — cliquez pour le détail`}
      data-testid="pastille-atlas">
      <Database className="h-3 w-3" />
      <span className={`inline-block h-2 w-2 rounded-full ${st.point}`} />
      {Math.round(mesure.pourcentage)} %
    </button>
  );
}

// Détail affiché dans le panneau : barre d'occupation, total, bases
export function DetailAtlas({ mesure }) {
  if (!mesure) return null;
  const st = STYLES[mesure.niveau] || STYLES.ok;
  const part = Math.min(100, mesure.limite ? (100 * mesure.total) / mesure.limite : 0);
  return (
    <div className="space-y-1.5" data-testid="jauge-atlas-detail">
      <p className="text-[10px] uppercase tracking-wider text-slate-400 inline-flex items-center gap-1.5">
        <Database className="h-3 w-3" /> Base Atlas
      </p>
      <div className="h-1.5 rounded-full bg-white/10 overflow-hidden">
        <div className={`h-full rounded-full ${st.barre} transition-all`} style={{ width: `${part}%` }} />
      </div>
      <p className={`text-[11px] tabular-nums ${st.texte}`}>
        {mesure.total} / {mesure.limite} collections · {mesure.pourcentage} %
        {mesure.niveau === "plein" && " · presque plein !"}
      </p>
      <div className="space-y-0.5 pt-1 border-t border-white/10">
        {(mesure.bases || []).map((b) => (
          <p key={b.nom} className="flex justify-between text-[10px] tabular-nums">
            <span className={`truncate ${b.sawali ? "text-white font-semibold" : "text-slate-400"}`}>{b.nom}</span>
            <span className="text-slate-300 pl-2">{b.collections}</span>
          </p>
        ))}
        <p className="text-[10px] text-slate-500 pt-0.5">
          Il en reste {mesure.restantes} · mesuré le {new Date(mesure.le).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}
        </p>
      </div>
    </div>
  );
}
