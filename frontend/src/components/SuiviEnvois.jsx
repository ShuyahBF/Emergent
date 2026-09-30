/*
  Lot 42 — Envois programmés ou en attente d'une plage horaire (sondages et formulaires).
  Affiche l'état de chaque envoi non terminé et permet de l'annuler (les messages déjà
  partis restent envoyés). `items` : campagnes / envois renvoyés par l'API ; `onAnnuler(id)`.
*/
import React from "react";
import { CalendarClock, PauseCircle, XCircle } from "lucide-react";
import { dateHeure } from "@/components/EnvoiProgrammation";

export const STATUTS_ENVOI = {
  scheduled: ["Programmé", "bg-violet-100 text-violet-700"],
  waiting: ["En attente de la plage horaire", "bg-amber-100 text-amber-700"],
  running: ["En cours", "bg-sky-100 text-sky-700"],
  done: ["Terminé", "bg-emerald-100 text-emerald-700"],
  cancelled: ["Annulé", "bg-slate-100 text-slate-500"],
};

export default function SuiviEnvois({ items, onAnnuler }) {
  // Seuls les envois programmés ou en attente de plage sont listés ici
  const attente = (items || []).filter((c) => c.status === "scheduled" || c.status === "waiting");
  if (!attente.length) return null;
  return (
    <div className="space-y-2" data-testid="suivi-envois">
      {attente.map((c) => {
        const [libelle, cls] = STATUTS_ENVOI[c.status];
        const Icone = c.status === "scheduled" ? CalendarClock : PauseCircle;
        return (
          <div key={c.id} className="flex flex-wrap items-center gap-2 rounded-xl bg-white ring-1 ring-slate-200 px-3 py-2 text-sm">
            <Icone className="h-4 w-4 text-slate-500" />
            <span className={`text-[11px] rounded-full px-2 py-0.5 ${cls}`}>{libelle}</span>
            <span className="text-slate-700">
              {c.status === "scheduled" ? <>Départ le <b>{dateHeure(c.reprise_a)}</b></> : <>Reprise le <b>{dateHeure(c.reprise_a)}</b></>}
              {" · "}{c.done || 0} / {c.total} envoyé(s)
            </span>
            {onAnnuler && (
              <button type="button" onClick={() => window.confirm("Annuler cet envoi ? Les messages déjà partis restent envoyés.") && onAnnuler(c.id)}
                className="ml-auto inline-flex items-center gap-1 text-xs text-rose-600 hover:underline" data-testid={`annuler-envoi-${c.id}`}>
                <XCircle className="h-3.5 w-3.5" /> Annuler
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
