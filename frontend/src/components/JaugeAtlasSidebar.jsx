// JaugeAtlasSidebar.jsx — Lot 79.9 : jauge des collections du cluster Atlas dans la barre latérale (administrateur),
// juste sous l'encart « Alerte WhatsApp ».
// Un cluster Atlas Flex accepte au plus 500 collections pour toutes les bases réunies (SAWALI, ALBARKA, DentalCare,
// adLyn…). Couleurs (demande du propriétaire) : vert sous 45 % · orange à partir de 45 % · rouge quand il ne reste
// que 10 % ou moins. Tout se lit ici, sans entrer dans les Paramètres : un clic déplie le détail par base.
import React, { useCallback, useEffect, useState } from "react";
import { Database } from "lucide-react";
import { apiClient } from "@/lib/api";
import { siVisible } from "@/lib/visibilite";   // pas de relecture quand l'onglet est masqué

// Couleurs de la barre et du libellé selon le niveau renvoyé par le serveur
const STYLES = {
  ok: { barre: "bg-emerald-400", texte: "text-emerald-200", anneau: "ring-white/10" },
  attention: { barre: "bg-amber-400", texte: "text-amber-200", anneau: "ring-amber-400/40" },
  plein: { barre: "bg-rose-500", texte: "text-rose-200", anneau: "ring-rose-500/60" },
};

export default function JaugeAtlasSidebar() {
  const [mesure, setMesure] = useState(null);
  const [ouvert, setOuvert] = useState(false);   // détail par base déplié ou non

  // Lecture de la dernière mesure (moins de 15 min) : le serveur ne recompte pas à chaque affichage
  const lire = useCallback(() => {
    apiClient.get("/admin/atlas/quota", { params: { recente: true } })
      .then((r) => setMesure(r.data)).catch(() => setMesure(null));
  }, []);
  useEffect(() => {
    lire();
    const t = setInterval(siVisible(lire), 15 * 60 * 1000);   // toutes les 15 minutes
    return () => clearInterval(t);
  }, [lire]);

  if (!mesure) return null;   // mesure indisponible : rien n'est affiché (pas de bruit dans la barre latérale)
  const st = STYLES[mesure.niveau] || STYLES.ok;
  const part = Math.min(100, mesure.limite ? (100 * mesure.total) / mesure.limite : 0);

  return (
    <button type="button" onClick={() => setOuvert((o) => !o)} aria-expanded={ouvert}
      className={`w-full text-left px-3 py-2 mt-1 rounded-lg bg-white/5 ring-1 ${st.anneau} hover:bg-white/10 transition space-y-1.5`}
      title={`${mesure.total} collections sur ${mesure.limite} — il en reste ${mesure.restantes}. Cliquez pour le détail par base.`}
      data-testid="jauge-atlas-sidebar">
      <p className="text-[10px] uppercase tracking-wider text-slate-400 inline-flex items-center gap-1.5">
        <Database className="h-3 w-3" /> Base Atlas
        <span className="ml-auto text-slate-500">{ouvert ? "▲" : "▼"}</span>
      </p>
      {/* Barre d'occupation */}
      <div className="h-1.5 rounded-full bg-white/10 overflow-hidden">
        <div className={`h-full rounded-full ${st.barre} transition-all`} style={{ width: `${part}%` }} />
      </div>
      <p className={`text-[11px] tabular-nums ${st.texte}`}>
        {mesure.total} / {mesure.limite} collections · {mesure.pourcentage} %
        {mesure.niveau === "plein" && " · presque plein !"}
      </p>
      {/* Détail par base (déplié au clic) : la base de SAWALI en clair */}
      {ouvert && (
        <div className="space-y-0.5 pt-1 border-t border-white/10" data-testid="jauge-atlas-detail">
          {(mesure.bases || []).map((b) => (
            <p key={b.nom} className="flex justify-between text-[10px] tabular-nums">
              <span className={`truncate ${b.sawali ? "text-white font-semibold" : "text-slate-400"}`}>{b.nom}</span>
              <span className="text-slate-300 pl-2">{b.collections}</span>
            </p>
          ))}
          <p className="text-[10px] text-slate-500 pt-0.5">Il en reste {mesure.restantes} · mesuré le {new Date(mesure.le).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</p>
        </div>
      )}
    </button>
  );
}
