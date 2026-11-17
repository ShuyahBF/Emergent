/*
  Diagramme de GANTT des demandes NON terminées (lots 118 puis 429) — même principe qu'un logiciel de planification :
    - à GAUCHE un tableau (demande, durée, début, fin) ; à DROITE l'échelle des jours (semaines, week-ends grisés, trait orange = aujourd'hui) ;
    - une barre par demande, du DÉBUT PRÉVU à la FIN PRÉVUE ; la partie plus foncée de la barre = temps écoulé (avancement estimé) ;
    - des FLÈCHES relient chaque demande à celle qu'elle suit (l'enchaînement vient de la DURÉE ESTIMÉE saisie par SAWALI) ;
    - une ligne de SYNTHÈSE par plateforme (barre sombre) qu'on peut replier ;
    - rouge = date dépassée, bleu = en cours, jaune = en attente (planifiée), noir hachuré = point mort, gris hachuré = pas de durée / pas de date.
  Jamais la couleur seule : chaque état a aussi un pictogramme et un texte (infobulle, légende).
*/
import React, { useMemo, useState } from "react";
import { AlertTriangle, CalendarClock, ChevronDown, ChevronRight, HelpCircle, OctagonAlert, Play, Send } from "lucide-react";
import { avecPredecesseurs, bornesEnchainement, demandesOuvertes, pointsMorts, resume } from "@/lib/enchainementDemandes";

const JOUR = 86400000;
const L = 26;          // largeur d'un jour (px)
const H = 30;          // hauteur d'une ligne (px)
const ENTETE = 44;     // hauteur de l'en-tête de l'échelle (2 rangées)

const STYLE = {
  en_cours: { fond: "#0369a1", Picto: Play, texte: "En cours" },
  prevue: { fond: "#facc15", Picto: CalendarClock, texte: "En attente (début et fin prévus par la durée estimée)", sombre: true },
  en_retard: { fond: "#dc2626", Picto: AlertTriangle, texte: "Date prévue dépassée" },
  sans_date: { fond: "#9ca3af", Picto: HelpCircle, texte: "Pas encore de date ni de durée estimée", hachure: true },
  point_mort_declare: { fond: "#1e293b", Picto: OctagonAlert, texte: "Point mort déclaré (travail arrêté)", hachure: true },
  point_mort: { fond: "#334155", Picto: OctagonAlert, texte: "Point mort (sans réponse depuis plus de 14 j)", hachure: true },
  a_remonter: { fond: "#d1d5db", Picto: Send, texte: "Pas encore envoyée à SAWALI", sombre: true },
};
const HACHURE = "repeating-linear-gradient(45deg, rgba(255,255,255,.55) 0 4px, transparent 4px 8px)";
const jourFr = (t) => new Date(t).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit", year: "2-digit" });
const debutDeJour = (t) => { const d = new Date(t); d.setHours(0, 0, 0, 0); return d.getTime(); };
const INITIALES = ["D", "L", "M", "M", "J", "V", "S"];

export default function GanttEnchainement({ demandes, maintenant = Date.now() }) {
  const [replies, setReplies] = useState({});                    // plateformes repliées
  const { lignes, trous, b, r } = useMemo(() => {
    const ouvertes = demandesOuvertes(demandes, maintenant);
    const trous = pointsMorts(ouvertes);
    return { lignes: avecPredecesseurs(ouvertes), trous, b: bornesEnchainement(ouvertes, maintenant), r: resume(ouvertes, trous) };
  }, [demandes, maintenant]);

  // Échelle : un jour de marge avant, au moins 4 semaines, 400 jours au plus
  const debutAxe = debutDeJour(b.debut) - JOUR;
  const nbJours = Math.min(400, Math.max(28, Math.ceil((b.fin - debutAxe) / JOUR) + 2));
  const x = (t) => ((t - debutAxe) / JOUR) * L;
  const largeur = nbJours * L;
  const jours = useMemo(() => Array.from({ length: nbJours }, (_, i) => { const d = new Date(debutAxe + i * JOUR); return { i, d, we: d.getDay() === 0 || d.getDay() === 6, lundi: d.getDay() === 1 }; }), [debutAxe, nbJours]);

  // Lignes affichées : une synthèse par plateforme, puis ses demandes (sauf si repliée)
  const rangees = useMemo(() => {
    const groupes = new Map();
    for (const l of lignes) { const k = l.plateforme || "Demandes"; if (!groupes.has(k)) groupes.set(k, []); groupes.get(k).push(l); }
    const sortie = [];
    for (const [nom, items] of groupes) {
      sortie.push({ type: "synthese", nom, debut: Math.min(...items.map((i) => i.debut)), fin: Math.max(...items.map((i) => i.fin)), nb: items.length });
      if (!replies[nom]) items.forEach((it) => sortie.push({ type: "tache", ...it }));
    }
    return sortie;
  }, [lignes, replies]);

  if (lignes.length === 0) return <p className="text-sm text-muted-foreground" data-testid="enchainement-vide">Aucune demande en cours : tout est terminé.</p>;
  const indexDe = new Map(rangees.map((g, i) => [g.id, i]));
  const hauteur = rangees.length * H;
  const yCentre = (i) => i * H + H / 2;
  const pc = (l) => Math.min(100, Math.max(0, ((maintenant - l.debut) / Math.max(l.fin - l.debut, JOUR)) * 100));   // avancement estimé (temps écoulé)

  return (
    <div className="space-y-3" data-testid="gantt-enchainement">
      {/* Chiffres clés */}
      <div className="flex flex-wrap gap-2 text-sm">
        <span className="rounded-full bg-blue-100 px-3 py-1 text-blue-900">{r.ouvertes} non terminée(s)</span>
        {r.en_cours > 0 && <span className="rounded-full bg-sky-100 px-3 py-1 text-sky-900">{r.en_cours} en cours</span>}
        {r.en_retard > 0 && <span className="rounded-full bg-red-100 px-3 py-1 text-red-800">{r.en_retard} date(s) dépassée(s)</span>}
        {r.points_morts > 0 && <span className="rounded-full bg-slate-200 px-3 py-1 text-slate-900">{r.points_morts} point(s) mort(s)</span>}
        {r.sans_date > 0 && <span className="rounded-full bg-gray-100 px-3 py-1 text-gray-800">{r.sans_date} sans date</span>}
        {r.trous > 0 && <span className="rounded-full bg-amber-100 px-3 py-1 text-amber-900">{r.trous} période(s) sans aucune demande en cours ({r.jours_a_l_arret} j)</span>}
      </div>

      <div className="overflow-x-auto rounded-lg border bg-white" style={{ maxHeight: "70vh" }}>
        <div className="flex" style={{ width: "max-content" }}>
          {/* ---- Tableau de gauche (reste visible pendant le défilement horizontal) ---- */}
          <div className="sticky left-0 z-20 border-r bg-white" style={{ width: 372 }}>
            <div className="grid items-end border-b bg-slate-100 px-2 text-[11px] font-semibold text-slate-700" style={{ height: ENTETE, gridTemplateColumns: "1fr 58px 62px 62px" }}>
              <span>Demande</span><span className="text-right">Durée</span><span className="text-right">Début</span><span className="text-right">Fin</span>
            </div>
            {rangees.map((g, i) => g.type === "synthese" ? (
              <button key={`s-${g.nom}`} type="button" onClick={() => setReplies({ ...replies, [g.nom]: !replies[g.nom] })} aria-expanded={!replies[g.nom]}
                className="grid w-full items-center border-b bg-sky-50 px-2 text-left text-xs font-bold text-slate-900" style={{ height: H, gridTemplateColumns: "1fr 58px 62px 62px" }}>
                <span className="flex items-center gap-1 truncate">{replies[g.nom] ? <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" /> : <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />}{g.nom} <span className="font-normal text-slate-500">({g.nb})</span></span>
                <span className="text-right tabular-nums">{Math.max(1, Math.round((g.fin - g.debut) / JOUR))} j</span>
                <span className="text-right tabular-nums">{jourFr(g.debut)}</span><span className="text-right tabular-nums">{jourFr(g.fin)}</span>
              </button>
            ) : (
              <div key={g.id} className="grid items-center border-b border-slate-100 px-2 text-xs" style={{ height: H, gridTemplateColumns: "1fr 58px 62px 62px" }} data-testid={`ligne-enchainement-${g.id}`} data-etat={g.etat}>
                <span className="min-w-0 pl-4" title={g.texte}><span className="font-mono text-[10px] text-sky-800">{g.numero}</span> <span className="text-slate-700">{g.texte.slice(0, 20)}{g.texte.length > 20 ? "…" : ""}</span></span>
                <span className="text-right tabular-nums">{Math.max(1, Math.round((g.fin - g.debut) / JOUR))} j</span>
                <span className="text-right tabular-nums">{jourFr(g.debut)}</span><span className="text-right tabular-nums">{jourFr(g.fin)}</span>
              </div>
            ))}
          </div>

          {/* ---- Échelle et barres ---- */}
          <div className="relative" style={{ width: largeur }}>
            {/* En-tête : semaines puis jours */}
            <div className="sticky top-0 z-10 border-b bg-slate-100" style={{ height: ENTETE }}>
              <div className="relative" style={{ height: 22 }}>
                {jours.filter((j) => j.lundi || j.i === 0).map((j) => <div key={j.i} className="absolute top-0 border-l border-slate-300 px-1 text-[10px] font-semibold text-slate-700" style={{ left: j.i * L, height: 22, lineHeight: "22px" }}>Sem. du {j.d.toLocaleDateString("fr-FR", { day: "2-digit", month: "short" })}</div>)}
              </div>
              <div className="flex" style={{ height: 22 }}>
                {jours.map((j) => <div key={j.i} className={`border-l border-slate-200 text-center text-[10px] ${j.we ? "bg-slate-300 text-slate-700" : "text-slate-600"}`} style={{ width: L, lineHeight: "22px" }}>{INITIALES[j.d.getDay()]}</div>)}
              </div>
            </div>
            {/* Corps : grille des jours (week-ends grisés), périodes sans demande, barres, flèches, aujourd'hui */}
            <div className="relative" style={{ height: hauteur }}>
              {jours.map((j) => <div key={j.i} className={`absolute top-0 border-l ${j.we ? "bg-slate-100 border-slate-200" : "border-slate-100"}`} style={{ left: j.i * L, width: L, height: hauteur }} />)}
              {trous.map((t, i) => <div key={i} className="absolute top-0 bg-amber-200/50" style={{ left: x(t.debut), width: x(t.fin) - x(t.debut), height: hauteur, backgroundImage: HACHURE }} title={`Aucune demande en cours pendant ${t.jours} j`} />)}
              {rangees.map((g, i) => g.type === "synthese" ? (
                <div key={`s-${g.nom}`} className="absolute rounded-sm bg-slate-800" style={{ left: x(g.debut), width: Math.max(x(g.fin) - x(g.debut), 4), top: i * H + 10, height: 8 }} title={`${g.nom} : ${jourFr(g.debut)} → ${jourFr(g.fin)}`} />
              ) : (() => {
                const s = STYLE[g.etat] || STYLE.prevue; const P = s.Picto; const w = Math.max(x(g.fin) - x(g.debut), 6);
                return (
                  <div key={g.id} role="img" aria-label={`${s.texte}, du ${jourFr(g.debut)} au ${jourFr(g.fin)}`} title={`${g.numero} · ${s.texte} · ${jourFr(g.debut)} → ${jourFr(g.fin)}`}
                    className="absolute overflow-hidden rounded" style={{ left: x(g.debut), width: w, top: i * H + 5, height: H - 10, background: s.fond, backgroundImage: s.hachure ? HACHURE : undefined }}>
                    {/* avancement estimé : temps écoulé depuis le début (partie plus foncée) */}
                    {g.etat !== "prevue" && g.etat !== "a_remonter" && <div className="absolute inset-y-0 left-0 bg-black/25" style={{ width: `${pc(g)}%` }} />}
                    <span className={`relative flex h-full items-center gap-1 px-1 text-[10px] ${s.sombre ? "text-slate-900" : "text-white"}`}><P className="h-3 w-3 shrink-0" aria-hidden="true" />{w > 90 && <span className="truncate">{g.numero.replace(/^DEM-/, "")}</span>}</span>
                  </div>
                );
              })())}
              {/* Flèches d'enchaînement : de la fin de la demande précédente au début de celle qui la suit */}
              <svg className="pointer-events-none absolute left-0 top-0" width={largeur} height={hauteur} aria-hidden="true">
                <defs><marker id="fleche-gantt" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#475569" /></marker></defs>
                {rangees.filter((g) => g.type === "tache" && g.suit != null && indexDe.has(g.suit)).map((g) => {
                  const p = rangees[indexDe.get(g.suit)]; const x1 = x(p.fin), y1 = yCentre(indexDe.get(g.suit)), x2 = x(g.debut), y2 = yCentre(indexDe.get(g.id));
                  const xm = Math.max(x1 + 6, Math.min(x2 - 6, x1 + 6));
                  const d = x2 >= x1 + 6 ? `M${x1},${y1} H${xm} V${y2} H${x2}` : `M${x1},${y1} H${x1 + 6} V${y2 - H / 2 + 2} H${x2 - 6} V${y2} H${x2}`;
                  return <path key={g.id} d={d} fill="none" stroke="#475569" strokeWidth="1.2" markerEnd="url(#fleche-gantt)" />;
                })}
              </svg>
              <div className="absolute top-0 w-0.5 bg-orange-500" style={{ left: x(maintenant), height: hauteur }} title="Aujourd'hui" />
            </div>
          </div>
        </div>
      </div>

      {/* Légende */}
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" data-testid="legende-enchainement">
        {Object.entries(STYLE).map(([k, s]) => <li key={k} className="flex items-center gap-1"><span className="inline-block h-3 w-5 rounded" style={{ background: s.fond, backgroundImage: s.hachure ? HACHURE : undefined }} />{s.texte}</li>)}
        <li className="flex items-center gap-1"><span className="inline-block h-2 w-5 rounded-sm bg-slate-800" />Synthèse d'une plateforme (cliquer pour replier)</li>
        <li className="flex items-center gap-1"><span className="inline-block h-3 w-5 rounded bg-amber-200" style={{ backgroundImage: HACHURE }} />Période sans aucune demande en cours</li>
        <li className="flex items-center gap-1"><span className="inline-block h-3 w-0.5 bg-orange-500" />Aujourd'hui</li>
      </ul>
      <p className="text-xs text-muted-foreground">Les flèches montrent l'enchaînement : chaque demande commence quand la précédente se termine, selon la DURÉE ESTIMÉE saisie par SAWALI (une demande sans durée ne peut pas être placée). Un point mort sort la demande de la file. La partie foncée d'une barre est le temps écoulé depuis son début.</p>
    </div>
  );
}
