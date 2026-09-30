/*
  Lot 42 — Bloc « Quand envoyer ? » des fenêtres d'envoi (sondages et formulaires).
  - rappelle les plages horaires autorisées fixées par l'Admin (Paramètres) ;
  - date et heure d'envoi facultatives (heure de la plateforme) : vide = tout de suite.
  Hors plage, l'envoi attend l'ouverture suivante et reprend seul le lendemain si besoin.
  API : GET /me/plages-envoi (backend/routes/plages_envoi.py).
*/
import React, { useEffect, useState } from "react";
import { CalendarClock, Clock } from "lucide-react";
import { apiClient } from "@/lib/api";

// Affichage d'un instant ISO en date et heure françaises
export const dateHeure = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "");

export default function EnvoiProgrammation({ value, onChange }) {
  const [plages, setPlages] = useState(null);
  useEffect(() => {
    apiClient.get("/me/plages-envoi").then((r) => setPlages(r.data)).catch(() => setPlages(null));
  }, []);

  return (
    <section className="rounded-xl ring-1 ring-slate-200 p-3 space-y-2" data-testid="envoi-programmation">
      <p className="text-sm font-semibold text-slate-800 flex items-center gap-1.5"><CalendarClock className="h-4 w-4" /> Quand envoyer ?</p>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label className="inline-flex items-center gap-2">
          <input type="radio" checked={!value} onChange={() => onChange("")} /> Maintenant
        </label>
        <label className="inline-flex items-center gap-2">
          <input type="radio" checked={!!value} onChange={() => onChange(value || new Date(Date.now() + 3600000).toISOString().slice(0, 16))} />
          Programmer le
        </label>
        {/* Heure de la plateforme (Ouagadougou, UTC+0) */}
        <input type="datetime-local" value={value || ""} onChange={(e) => onChange(e.target.value)} disabled={!value}
          className="rounded border border-slate-300 px-2 py-1 text-sm disabled:opacity-40" data-testid="envoi-programme-le" />
      </div>
      {plages && (
        <p className={`text-[11px] flex items-start gap-1 ${plages.actif ? "text-slate-600" : "text-slate-400"}`}>
          <Clock className="h-3.5 w-3.5 mt-0.5 shrink-0" />
          {plages.actif ? (
            <span>
              Envois autorisés : <b>{plages.resume}</b> ({plages.fuseau}). Hors de ces plages, l'envoi attend et reprend
              automatiquement à l'ouverture suivante.
              {!plages.ouvert_maintenant && plages.prochaine_ouverture && (
                <> Prochaine ouverture : <b>{dateHeure(plages.prochaine_ouverture)}</b>.</>
              )}
            </span>
          ) : <span>Aucune restriction horaire fixée par l'administrateur.</span>}
        </p>
      )}
    </section>
  );
}
