/*
  Lot 325 — Planning des consultations sur 3 jours ou la semaine (liste groupée par jour, adaptée au téléphone).
  Réservé au portail connecté (noms et téléphones EN CLAIR, contrairement à la télé du hall qui reste masquée).
  Chaque jour est lu avec la route existante `/me/planning/appointments?date=…` (mêmes droits et même périmètre que la vue d'un jour),
  les jours étant lus EN PARALLÈLE ; la liste se rafraîchit toute seule toutes les 30 secondes.
*/
import React, { useCallback, useEffect, useState } from "react";
import { Loader2, User } from "lucide-react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { trierJour } from "@/lib/planningPlage";

const addJours = (iso, n) => { const d = new Date(`${iso}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
const heure = (iso) => (iso ? new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) : "");
const titreJour = (iso) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("fr-FR", { weekday: "long", day: "2-digit", month: "2-digit", timeZone: "UTC" });

export default function PlanningPlage({ debut, jours, medecinId }) {
  const [donnees, setDonnees] = useState(null);                // [{ date, items }]
  const [maintenant, setMaintenant] = useState(Date.now());

  const charger = useCallback(async () => {
    const dates = Array.from({ length: jours }, (_, i) => addJours(debut, i));
    const lectures = await Promise.allSettled(dates.map((d) => apiClient.get("/me/planning/appointments", { params: { date: d, ...(medecinId ? { medecin_id: medecinId } : {}) } })));
    if (lectures.every((r) => r.status === "rejected")) toast.error(lectures[0].reason?.response?.data?.detail || "Erreur chargement des RDV");
    setDonnees(dates.map((date, i) => ({ date, items: lectures[i].status === "fulfilled" ? lectures[i].value.data?.items || [] : [] })));
  }, [debut, jours, medecinId]);

  useEffect(() => { setDonnees(null); charger(); }, [charger]);
  useEffect(() => {
    const t = setInterval(() => { charger(); setMaintenant(Date.now()); }, 30000);
    return () => clearInterval(t);
  }, [charger]);

  if (donnees === null) return <div className="bg-white border border-slate-200 rounded-2xl p-8 flex justify-center"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>;
  const total = donnees.reduce((n, j) => n + j.items.length, 0);
  return (
    <div className="space-y-3" data-testid="planning-plage">
      <p className="text-xs text-slate-500">{total} patient(s) du {titreJour(donnees[0].date)} au {titreJour(donnees[donnees.length - 1].date)}</p>
      {donnees.map((j) => {
        const liste = trierJour(j.items);
        return (
          <section key={j.date} className="bg-white border border-slate-200 rounded-2xl overflow-hidden" data-testid={`planning-plage-jour-${j.date}`}>
            <h3 className="px-4 py-2.5 text-sm font-semibold text-slate-700 bg-slate-50 border-b border-slate-100 capitalize">{titreJour(j.date)} <span className="font-normal text-slate-400">({liste.length})</span></h3>
            {liste.length === 0 ? <p className="px-4 py-4 text-sm text-slate-400">Aucun rendez-vous</p> : (
              <ul className="divide-y divide-slate-100">
                {liste.map((a) => {
                  const passe = a.is_rdv !== 0 && a.end_at && new Date(a.end_at).getTime() < maintenant;
                  return (
                    <li key={a.id} className={`px-4 py-2.5 ${passe ? "opacity-50" : ""}`} data-testid={`planning-plage-item-${a.id}`}>
                      <div className="flex items-start gap-2 flex-wrap">
                        <span className="inline-flex px-2 py-0.5 rounded-md text-[11px] font-semibold border border-slate-200 bg-slate-50 shrink-0">
                          {a.is_rdv === 0 ? `#${a.numero_ordre ?? "?"}` : `${heure(a.start_at)}–${heure(a.end_at)}`}
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium text-slate-800 flex items-center gap-1.5 flex-wrap">
                            <User className="h-3.5 w-3.5 text-slate-400 shrink-0" />
                            <span className={a.is_rdv === 0 ? "" : "underline underline-offset-2"}>{a.patient}</span>
                            {a.etat_consult === "en_cours" && <span className="text-[10px] uppercase tracking-wide text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-1 py-0.5">En consultation</span>}
                            {a.etat_consult === "fait" && <span className="text-[10px] uppercase tracking-wide text-slate-400 border border-slate-200 rounded px-1 py-0.5">Terminé</span>}
                          </div>
                          <div className="text-xs text-slate-500">{a.medecin}{a.motif ? ` · ${a.motif}` : ""}{a.patient_phone ? ` · ${a.patient_phone}` : ""}</div>
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}
