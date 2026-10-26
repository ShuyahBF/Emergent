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
import { CalendarDays, ChevronLeft, ChevronRight, Image as ImageIcon, Loader2, Minimize2, Maximize2, RefreshCw, Share2, X } from "lucide-react";
import { apiClient } from "@/lib/api";
import CalendrierSemaine from "@/components/CalendrierSemaine";
import { genererImageDisponibilites } from "@/lib/calendrierImage";
import { genererImageNiveaux } from "@/lib/niveauxImage";

const jourIso = (d) => d.toISOString().slice(0, 10);
const lundi = (d) => { const x = new Date(d); const n = (x.getDay() + 6) % 7; x.setDate(x.getDate() - n); return x; };

// Lot 313 : `onPartagerImage(file)` (facultatif) — envoie les disponibilités sous forme d'IMAGE lisible d'un coup d'œil
// Lot 314 : `onPartagerNiveaux(file)` (facultatif) — image « Niveaux de service » (contrat / standard / EXPRESS), les mêmes niveaux pour tous les contacts ;
// lot 315 : `contactId` sert à lire le « Forfait par intervention » du client du contact (tarif EXPRESS, 0 = précisé avant l'intervention)
export default function CalendrierModal({ contactNom, contactId, onPartager, onPartagerImage, onPartagerNiveaux, onClose }) {
  const [debut, setDebut] = useState(() => lundi(new Date()));
  const [donnees, setDonnees] = useState(null);
  const [reduit, setReduit] = useState(false);
  const [bloc, setBloc] = useState({ jour: jourIso(new Date()), de: "09:00", a: "10:00", libelle: "" });
  const [occupe, setOccupe] = useState(false);
  const [synchro, setSynchro] = useState(false);       // resynchronisation en cours (l'icône tourne)

  const charger = useCallback(async () => {
    try {
      const r = await apiClient.get("/me/calendrier/occupations", { params: { debut: jourIso(debut), jours: 7 } });
      setDonnees(r.data);
      return r.data;
    } catch (e) { toast.error(e?.response?.data?.detail || "Calendrier indisponible"); return null; }
  }, [debut]);
  useEffect(() => { charger(); }, [charger]);

  // Lot 291 : à CHAQUE appui, le calendrier est relu auprès du compte Google puis on dit si Google a répondu
  const resynchroniser = async () => {
    setSynchro(true);
    const d = await charger();
    setSynchro(false);
    if (!d) return;
    const heure = new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    if (!d.google) toast.success(`Calendrier actualisé à ${heure}`);
    else if (d.google_etat?.ok) toast.success(`Calendrier resynchronisé avec Google à ${heure}`);
    else toast.warning(`Google Calendar : ${d.google_etat?.erreur || "pas de réponse"}`);
  };

  // Lot 314 : réglages des niveaux de service (Paramètres → « Niveaux de service »)
  const [niveaux, setNiveaux] = useState(null);
  useEffect(() => {
    if (!onPartagerNiveaux) return;
    apiClient.get("/me/niveaux-service").then((r) => setNiveaux(r.data)).catch(() => setNiveaux(null));
  }, [onPartagerNiveaux]);
  const partagerNiveaux = async () => {
    if (!niveaux?.configure) return;
    setOccupe(true);
    try {
      let forfaitExpress = null;
      if (contactId) {
        try { forfaitExpress = (await apiClient.post("/me/contact-forfait", { contact_id: contactId })).data?.forfait ?? null; }
        catch { /* forfait inconnu : « Tarif précisé avant l'intervention » */ }
      }
      const fichier = await genererImageNiveaux({ config: niveaux, forfaitExpress });
      onPartagerNiveaux?.(fichier);
      toast.success("Image des niveaux de service jointe au message : relisez puis envoyez");
      onClose?.();
    } catch (e) { toast.error(e?.message || "Image impossible à générer"); }
    finally { setOccupe(false); }
  };

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

  // Lot 313 : image PNG des disponibilités de la semaine affichée (vert = libre, gris = occupé) jointe au message du contact
  const partagerImage = async () => {
    if (!donnees) return;
    setOccupe(true);
    try {
      const fichier = await genererImageDisponibilites({ debut: donnees.debut, jours: 7, horaires: donnees.horaires, occupations: donnees.occupations });
      onPartagerImage?.(fichier);
      toast.success("Image des disponibilités jointe au message : relisez puis envoyez");
      onClose?.();
    } catch (e) { toast.error(e?.message || "Image impossible à générer"); }
    finally { setOccupe(false); }
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
            <button type="button" onClick={resynchroniser} disabled={synchro} data-testid="calendrier-resynchroniser"
              title="Resynchroniser avec le compte Google (relit le calendrier à chaque appui)"
              className="p-1.5 rounded border border-slate-300 hover:bg-slate-50 disabled:opacity-60">
              <RefreshCw className={`h-4 w-4 text-indigo-600 ${synchro ? "animate-spin" : ""}`} />
            </button>
            <span className="text-xs text-slate-500">
              Grisé = occupé (rendez-vous, planning{donnees?.google ? ", Google Calendar" : ""}, créneaux bloqués)
            </span>
            {onPartagerNiveaux && (
              <button type="button" onClick={partagerNiveaux} disabled={occupe || !niveaux?.configure} data-testid="calendrier-partager-niveaux"
                title={niveaux?.configure ? "Joindre au message l'image des niveaux de service (contrat, standard, EXPRESS)" : "À régler d'abord : Paramètres → Niveaux de service (activer et renseigner les trois délais)"}
                className="ml-auto inline-flex items-center gap-1 rounded-lg bg-amber-500 text-white px-3 py-1.5 text-xs hover:bg-amber-600 disabled:opacity-50">
                ⚡ Niveaux de service
              </button>
            )}
            {onPartagerImage && (
              <button type="button" onClick={partagerImage} disabled={occupe || !donnees} data-testid="calendrier-partager-image"
                title="Joindre au message une image des créneaux libres (plus lisible qu'un lien)"
                className={`${onPartagerNiveaux ? "" : "ml-auto "}inline-flex items-center gap-1 rounded-lg bg-indigo-600 text-white px-3 py-1.5 text-xs hover:bg-indigo-700 disabled:opacity-50`}>
                <ImageIcon className="h-3.5 w-3.5" /> Envoyer en image
              </button>
            )}
            <button type="button" onClick={partager} disabled={occupe || !onPartager} data-testid="calendrier-partager"
              className={`${onPartagerImage ? "" : "ml-auto "}inline-flex items-center gap-1 rounded-lg bg-emerald-600 text-white px-3 py-1.5 text-xs hover:bg-emerald-700 disabled:opacity-50`}>
              <Share2 className="h-3.5 w-3.5" /> Partager le lien
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
