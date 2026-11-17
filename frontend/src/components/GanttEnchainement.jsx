/*
  Lot 118 — Vue d'ENSEMBLE des demandes NON terminées sur un axe du temps commun : une ligne par demande, barres colorées (couleur + pictogramme + texte), liaison « suit … »
  (enchaînement déduit des dates), bandes grises hachurées = POINTS MORTS (aucune demande en cours), ligne orange = aujourd'hui.
  États : bleu = prévue, rouge = date dépassée, gris hachuré = pas encore de date (< 14 j), noir hachuré = POINT MORT (sans date depuis plus de 14 j), tiret = pas encore envoyée.
*/
import React, { useMemo } from "react";
import { AlertTriangle, CalendarClock, HelpCircle, OctagonAlert, Send } from "lucide-react";
import { avecPredecesseurs, bornesEnchainement, demandesOuvertes, pointsMorts, resume } from "@/lib/enchainementDemandes";

const STYLE = {
  prevue: { fond: "bg-blue-500", Picto: CalendarClock, texte: "Prévue" },
  en_retard: { fond: "bg-red-600", Picto: AlertTriangle, texte: "Date dépassée" },
  sans_date: { fond: "bg-gray-400", Picto: HelpCircle, texte: "Pas encore de date", hachure: true },
  point_mort: { fond: "bg-slate-800", Picto: OctagonAlert, texte: "Point mort (sans réponse depuis plus de 14 j)", hachure: true },
  a_remonter: { fond: "bg-gray-300", Picto: Send, texte: "Pas encore envoyée à SAWALI" },
};
const HACHURE = { backgroundImage: "repeating-linear-gradient(45deg, rgba(255,255,255,.65) 0 4px, transparent 4px 8px)" };
const jour = (t) => new Date(t).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" });

export default function GanttEnchainement({ demandes, maintenant = Date.now() }) {
  const { lignes, trous, b, r } = useMemo(() => {
    const ouvertes = demandesOuvertes(demandes, maintenant);
    const trous = pointsMorts(ouvertes);
    return { lignes: avecPredecesseurs(ouvertes), trous, b: bornesEnchainement(ouvertes, maintenant), r: resume(ouvertes, trous) };
  }, [demandes, maintenant]);
  const pct = (t) => Math.min(100, Math.max(0, ((t - b.debut) / (b.fin - b.debut)) * 100));
  if (lignes.length === 0) return <p className="text-sm text-muted-foreground" data-testid="enchainement-vide">Aucune demande en cours : tout est terminé.</p>;
  const num = (id) => lignes.find((l) => l.id === id)?.numero;
  return (
    <div className="space-y-3" data-testid="gantt-enchainement">
      {/* Chiffres clés */}
      <div className="flex flex-wrap gap-2 text-sm">
        <span className="rounded-full bg-blue-100 px-3 py-1 text-blue-900">{r.ouvertes} en cours</span>
        {r.en_retard > 0 && <span className="rounded-full bg-red-100 px-3 py-1 text-red-800">{r.en_retard} date(s) dépassée(s)</span>}
        {r.points_morts > 0 && <span className="rounded-full bg-slate-200 px-3 py-1 text-slate-900">{r.points_morts} point(s) mort(s) : sans réponse depuis plus de 14 j</span>}
        {r.sans_date > 0 && <span className="rounded-full bg-gray-100 px-3 py-1 text-gray-800">{r.sans_date} sans date</span>}
        {r.trous > 0 && <span className="rounded-full bg-amber-100 px-3 py-1 text-amber-900">{r.trous} période(s) sans aucune demande en cours ({r.jours_a_l_arret} j)</span>}
      </div>
      {/* Axe + lignes */}
      <div className="overflow-x-auto rounded-lg border bg-white p-3">
        <div className="min-w-[640px] space-y-1.5">
          {lignes.map((l) => {
            const s = STYLE[l.etat]; const P = s.Picto;
            const gauche = pct(l.debut), largeur = Math.max(pct(l.fin) - gauche, 1.5);
            return (
              <div key={l.id} className="grid grid-cols-[170px_1fr] items-center gap-2 text-xs" data-testid={`ligne-enchainement-${l.id}`} data-etat={l.etat}>
                <div className="min-w-0">
                  <div className="truncate font-mono">{l.plateforme ? `${l.plateforme} · ` : ""}{l.numero}</div>
                  <div className="truncate text-muted-foreground" title={l.texte}>{l.texte.slice(0, 20)}{l.texte.length > 20 ? "…" : ""}</div>
                </div>
                <div className="relative h-6 rounded bg-slate-100" role="img" aria-label={`${s.texte} du ${jour(l.debut)} au ${jour(l.fin)}`}>
                  {/* Points morts : bandes hachurées grises sur toutes les lignes */}
                  {trous.map((t, i) => <div key={i} className="absolute top-0 bottom-0 bg-amber-200/60" style={{ left: `${pct(t.debut)}%`, width: `${pct(t.fin) - pct(t.debut)}%`, ...HACHURE }} title={`Aucune demande en cours pendant ${t.jours} j`} />)}
                  <div className={`absolute top-0.5 bottom-0.5 rounded flex items-center gap-1 px-1 text-[10px] text-white overflow-hidden ${s.fond}`}
                    style={{ left: `${gauche}%`, width: `${largeur}%`, ...(s.hachure ? HACHURE : {}) }} title={`${s.texte} · ${jour(l.debut)} → ${jour(l.fin)}`}>
                    <P className="w-3 h-3 shrink-0" aria-hidden="true" />
                    {l.suit && <span className="truncate">suit {num(l.suit)}</span>}
                  </div>
                  <div className="absolute top-0 bottom-0 w-px bg-orange-500" style={{ left: `${pct(maintenant)}%` }} title="Aujourd'hui" />
                </div>
              </div>
            );
          })}
        </div>
        <div className="mt-2 flex justify-between text-[10px] text-muted-foreground"><span>{jour(b.debut)}</span><span>aujourd'hui : trait orange</span><span>{jour(b.fin)}</span></div>
      </div>
      {/* Légende */}
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" data-testid="legende-enchainement">
        {Object.entries(STYLE).map(([k, s]) => <li key={k} className="flex items-center gap-1"><span className={`inline-block h-3 w-5 rounded ${s.fond}`} style={s.hachure ? HACHURE : undefined} />{s.texte}</li>)}
        <li className="flex items-center gap-1"><span className="inline-block h-3 w-5 rounded bg-amber-200" style={HACHURE} />Période sans aucune demande en cours</li>
      </ul>
      <p className="text-xs text-muted-foreground">« suit … » : enchaînement déduit des dates (aucune dépendance n'est saisie). Les reprises (demande rouverte) ne sont pas encore suivies : l'historique des changements de statut n'est pas conservé.</p>
    </div>
  );
}
