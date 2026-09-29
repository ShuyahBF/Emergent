/*
  Lot 41 — Grille d'une semaine façon Google Calendar : une colonne par jour, une ligne par
  heure (horaires d'ouverture de la plateforme), les moments OCCUPÉS en grisé.
  Utilisée par la modale « Calendrier » de la discussion WhatsApp (avec détails, créneaux
  bloqués supprimables) et par la page publique /disponibilites/:jeton (sans détail).
*/
import React from "react";

const SOURCES = {
  rdv: ["Rendez-vous", "bg-slate-400/80"],
  planning: ["Planning", "bg-slate-500/80"],
  google: ["Google Calendar", "bg-slate-600/70"],
  manuel: ["Bloqué", "bg-slate-700/70"],
};

const heure = (hhmm, defaut) => {
  const [h] = String(hhmm || "").split(":");
  const n = parseInt(h, 10);
  return Number.isFinite(n) ? n : defaut;
};

export default function CalendrierSemaine({ debut, jours = 7, horaires, occupations = [], details = false, onBloc }) {
  const h0 = Math.min(heure(horaires?.ouverture, 7), 7);
  const h1 = Math.max(heure(horaires?.fermeture, 19), 19);
  const heures = Array.from({ length: h1 - h0 }, (_, i) => h0 + i);
  const t0 = new Date(debut);
  const colonnes = Array.from({ length: jours }, (_, i) => new Date(t0.getTime() + i * 86400000));
  const hauteurHeure = 36;                               // px par heure

  // Blocs d'un jour, placés en % de la plage horaire affichée
  const blocsDuJour = (jour) => {
    const debutJour = new Date(jour); debutJour.setHours(h0, 0, 0, 0);
    const finJour = new Date(jour); finJour.setHours(h1, 0, 0, 0);
    return occupations
      .map((o) => ({ ...o, d: new Date(o.debut), f: new Date(o.fin) }))
      .filter((o) => o.f > debutJour && o.d < finJour)
      .map((o) => {
        const d = Math.max(o.d, debutJour), f = Math.min(o.f, finJour);
        return { ...o, top: ((d - debutJour) / 3600000) * hauteurHeure, haut: Math.max(10, ((f - d) / 3600000) * hauteurHeure) };
      });
  };

  return (
    <div className="overflow-x-auto" data-testid="calendrier-semaine">
      <div className="grid min-w-[560px]" style={{ gridTemplateColumns: `44px repeat(${jours}, minmax(70px, 1fr))` }}>
        <div />
        {colonnes.map((j) => (
          <div key={j.toISOString()} className="text-center text-[11px] font-semibold text-slate-600 pb-1 border-b border-slate-200">
            {j.toLocaleDateString("fr-FR", { weekday: "short", day: "2-digit", month: "2-digit" })}
          </div>
        ))}
        <div className="relative">
          {heures.map((h) => (
            <div key={h} className="text-[10px] text-slate-400 text-right pr-1" style={{ height: hauteurHeure }}>{`${h}h`}</div>
          ))}
        </div>
        {colonnes.map((j) => (
          <div key={j.toISOString()} className="relative border-l border-slate-100" style={{ height: heures.length * hauteurHeure }}>
            {heures.map((h) => <div key={h} className="border-b border-slate-100" style={{ height: hauteurHeure }} />)}
            {blocsDuJour(j).map((o, i) => {
              const [libSource, couleur] = SOURCES[o.source] || ["Occupé", "bg-slate-400/80"];
              const plage = `${o.d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })} – ${o.f.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}`;
              return (
                <button key={i} type="button" disabled={!onBloc || o.source !== "manuel"} onClick={() => onBloc?.(o)}
                  className={`absolute left-0.5 right-0.5 rounded px-1 text-left text-[10px] leading-tight text-white overflow-hidden ${details ? couleur : "bg-slate-400/80"} ${o.source === "manuel" && onBloc ? "cursor-pointer hover:ring-2 hover:ring-rose-400" : "cursor-default"}`}
                  style={{ top: o.top, height: o.haut }}
                  title={details ? `${libSource} · ${o.libelle || ""} · ${plage}${o.source === "manuel" && onBloc ? " (cliquer pour libérer)" : ""}` : `Occupé · ${plage}`}>
                  {details ? (o.libelle || libSource) : "Occupé"}
                </button>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
