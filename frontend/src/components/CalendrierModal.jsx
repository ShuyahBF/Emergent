/*
  Lot 41 — Modale réduite « Calendrier » ouverte depuis la discussion WhatsApp.
  - Semaine affichée comme Google Calendar, moments occupés en grisé : rendez-vous du portail,
    planning des médecins, Google Calendar de la plateforme (Admin / Superviseur) et créneaux
    bloqués à la main (ajout ici, clic sur un créneau bloqué pour le libérer) ;
  - « Partager au contact » : crée un lien public (14 jours, « occupé » seulement, aucun
    détail) et place le message dans la zone de saisie de la conversation (onPartager).
  API : /me/calendrier/* (backend/routes/calendrier_partage.py).
*/
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { CalendarDays, ChevronLeft, ChevronRight, Loader2, Minimize2, Maximize2, Share2, X } from "lucide-react";
import { apiClient } from "@/lib/api";
import CalendrierSemaine from "@/components/CalendrierSemaine";

const jourIso = (d) => d.toISOString().slice(0, 10);
const lundi = (d) => { const x = new Date(d); const n = (x.getDay() + 6) % 7; x.setDate(x.getDate() - n); return x; };

export default function CalendrierModal({ contactNom, onPartager, onClose }) {
  const [debut, setDebut] = useState(() => lundi(new Date()));
  const [donnees, setDonnees] = useState(null);
  const [reduit, setReduit] = useState(false);
  const [bloc, setBloc] = useState({ jour: jourIso(new Date()), de: "09:00", a: "10:00", libelle: "" });
  const [occupe, setOccupe] = useState(false);

  const charger = useCallback(async () => {
    try {
      const r = await apiClient.get("/me/calendrier/occupations", { params: { debut: jourIso(debut), jours: 7 } });
      setDonnees(r.data);
    } catch (e) { toast.error(e?.response?.data?.detail || "Calendrier indisponible"); }
  }, [debut]);
  useEffect(() => { charger(); }, [charger]);

  const semaine = (n) => setDebut((d) => new Date(d.getTime() + n * 7 * 86400000));

  const bloquer = async () => {
    setOccupe(true);
    try {
      await apiClient.post("/me/calendrier/creneaux", {
        debut: new Date(`${bloc.jour}T${bloc.de}`).toISOString(), fin: new Date(`${bloc.jour}T${bloc.a}`).toISOString(),
        libelle: bloc.libelle || null });
      toast.success("Créneau bloqué");
      charger();
    } catch (e) { toast.error(e?.response?.data?.detail || "Créneau refusé"); }
    finally { setOccupe(false); }
  };

  const liberer = async (o) => {
    if (!window.confirm(`Libérer le créneau « ${o.libelle} » ?`)) return;
    try { await apiClient.delete(`/me/calendrier/creneaux/${o.id}`); charger(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Impossible de libérer"); }
  };

  const partager = async () => {
    setOccupe(true);
    try {
      const r = await apiClient.post("/me/calendrier/partages", { debut: jourIso(debut), jours: 14 });
      onPartager?.(r.data.texte);
      toast.success("Lien de disponibilités ajouté au message : relisez puis envoyez");
      onClose?.();
    } catch (e) { toast.error(e?.response?.data?.detail || "Partage impossible"); }
    finally { setOccupe(false); }
  };

  return (
    <div className={`fixed z-[70] ${reduit ? "bottom-4 right-4 w-72" : "inset-x-2 bottom-2 sm:inset-x-auto sm:right-4 sm:bottom-4 sm:w-[720px]"} rounded-xl bg-white shadow-2xl ring-1 ring-slate-300`}
      data-testid="calendrier-modal">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-200">
        <CalendarDays className="h-4 w-4 text-indigo-600" />
        <span className="text-sm font-semibold text-slate-800 truncate">Calendrier{contactNom ? ` — ${contactNom}` : ""}</span>
        <div className="ml-auto flex items-center gap-1">
          <button type="button" onClick={() => setReduit(!reduit)} className="p-1 rounded hover:bg-slate-100" title={reduit ? "Agrandir" : "Réduire"}>
            {reduit ? <Maximize2 className="h-4 w-4" /> : <Minimize2 className="h-4 w-4" />}
          </button>
          <button type="button" onClick={onClose} className="p-1 rounded hover:bg-slate-100" title="Fermer"><X className="h-4 w-4" /></button>
        </div>
      </div>
      {!reduit && (
        <div className="p-3 space-y-3 max-h-[75vh] overflow-y-auto">
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={() => semaine(-1)} className="p-1.5 rounded border border-slate-300 hover:bg-slate-50"><ChevronLeft className="h-4 w-4" /></button>
            <button type="button" onClick={() => setDebut(lundi(new Date()))} className="px-2 py-1 rounded border border-slate-300 text-xs hover:bg-slate-50">Cette semaine</button>
            <button type="button" onClick={() => semaine(1)} className="p-1.5 rounded border border-slate-300 hover:bg-slate-50"><ChevronRight className="h-4 w-4" /></button>
            <span className="text-xs text-slate-500">
              Grisé = occupé (rendez-vous, planning{donnees?.google ? ", Google Calendar" : ""}, créneaux bloqués)
            </span>
            <button type="button" onClick={partager} disabled={occupe || !onPartager} data-testid="calendrier-partager"
              className="ml-auto inline-flex items-center gap-1 rounded-lg bg-emerald-600 text-white px-3 py-1.5 text-xs hover:bg-emerald-700 disabled:opacity-50">
              <Share2 className="h-3.5 w-3.5" /> Partager au contact
            </button>
          </div>
          {!donnees ? <Loader2 className="h-5 w-5 animate-spin text-slate-400 mx-auto" /> : (
            <CalendrierSemaine debut={donnees.debut} jours={7} horaires={donnees.horaires} occupations={donnees.occupations}
              details onBloc={liberer} />
          )}
          {/* Bloquer un créneau à la main */}
          <div className="flex flex-wrap items-end gap-2 rounded-lg bg-slate-50 p-2 text-xs">
            <label>Jour<input type="date" value={bloc.jour} onChange={(e) => setBloc({ ...bloc, jour: e.target.value })}
              className="block rounded border border-slate-300 px-1.5 py-1" /></label>
            <label>De<input type="time" value={bloc.de} onChange={(e) => setBloc({ ...bloc, de: e.target.value })}
              className="block rounded border border-slate-300 px-1.5 py-1" /></label>
            <label>À<input type="time" value={bloc.a} onChange={(e) => setBloc({ ...bloc, a: e.target.value })}
              className="block rounded border border-slate-300 px-1.5 py-1" /></label>
            <label className="flex-1 min-w-[120px]">Motif (visible par vous seul)<input value={bloc.libelle} maxLength={120}
              onChange={(e) => setBloc({ ...bloc, libelle: e.target.value })} className="block w-full rounded border border-slate-300 px-1.5 py-1" /></label>
            <button type="button" onClick={bloquer} disabled={occupe} data-testid="calendrier-bloquer"
              className="rounded bg-slate-700 text-white px-3 py-1.5 disabled:opacity-50">Bloquer ce créneau</button>
          </div>
        </div>
      )}
    </div>
  );
}
