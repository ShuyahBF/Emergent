// AgendaPasserelleSection.jsx — Lot 403 : réglages de la passerelle « Agenda Google » par utilisateur (auRor, Concentration, Personnel Maison).
// Rien de secret ici : l'adresse de retour à DÉCLARER chez Google, les autorisations demandées, l'état (Google configuré ?) et le NOMBRE de liaisons par plateforme.
// Les agendas des utilisateurs ne sont jamais lisibles depuis SAWALI : seul chaque utilisateur voit le sien (voir backend/routes/agenda_passerelle.py).
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { CalendarDays, Copy, RefreshCw, Loader2, CheckCircle2, AlertTriangle } from "lucide-react";
import { apiClient } from "@/lib/api";

export default function AgendaPasserelleSection() {
  const [etat, setEtat] = useState(null);
  const [chargement, setChargement] = useState(false);

  const charger = useCallback(async () => {
    setChargement(true);
    toast.info("Actualisation de l'état de l'agenda en cours…");          // règle 17 : jamais d'actualisation silencieuse
    try {
      const { data } = await apiClient.get("/admin/agenda-passerelle/etat");
      setEtat(data);
      toast.success(`État relu : ${data.total} liaison(s) d'agenda.`);
    } catch (e) { toast.error(e?.response?.data?.detail || "Lecture impossible"); }
    finally { setChargement(false); }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  const copier = (texte) => { navigator.clipboard?.writeText(texte).then(() => toast.success("Copié")).catch(() => toast.error("Copie impossible")); };

  return (
    <div className="space-y-3" data-testid="agenda-passerelle">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-sky-100"><CalendarDays className="h-4 w-4 text-sky-700" /></div>
        <div className="flex-1">
          <h3 className="text-sm font-semibold text-slate-800">Agenda Google des utilisateurs des plateformes</h3>
          <p className="text-xs text-slate-500">
            SAWALI sert de passerelle : chaque utilisateur d'auRor, de Concentration ou de Personnel Maison lie SON compte Google (une fois) puis consulte son agenda et crée des rendez-vous,
            y compris par note vocale (« samedi 8h15 rdv chez le dentiste »), avec confirmation avant création. Chacun ne voit que son propre agenda : ni vous, ni les autres utilisateurs ne pouvez le lire.
          </p>
        </div>
        <button type="button" onClick={charger} disabled={chargement} title="Actualiser l'état" aria-label="Actualiser l'état de l'agenda"
                className="inline-flex items-center gap-1 rounded-lg border border-sky-300 px-3 py-1.5 text-xs font-semibold text-sky-800 hover:bg-sky-50" data-testid="agenda-actualiser">
          {chargement ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}Actualiser
        </button>
      </div>
      {etat && (<>
        <p className={`flex items-center gap-2 text-sm ${etat.google_configure ? "text-emerald-700" : "text-amber-700"}`}>
          {etat.google_configure ? <CheckCircle2 className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
          {etat.google_configure ? "Google configuré (Client ID et Secret du bloc « Google Calendar »)." : "Google non configuré : renseignez le Client ID et le Secret dans le bloc « Google Calendar »."}
        </p>
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
          <div className="font-semibold text-slate-800">À déclarer chez Google (Google Auth Platform → Clients → votre client Web → URI de redirection autorisés)</div>
          <div className="mt-1 flex items-center gap-2">
            <code className="break-all rounded bg-white px-2 py-1 text-xs" data-testid="agenda-adresse-retour">{etat.adresse_retour}</code>
            <button type="button" onClick={() => copier(etat.adresse_retour)} title="Copier l'adresse" aria-label="Copier l'adresse de retour"
                    className="inline-flex items-center gap-1 rounded border border-slate-300 px-2 py-1 text-xs"><Copy className="h-3.5 w-3.5" />Copier</button>
          </div>
          <div className="mt-2 font-semibold text-slate-800">Autorisations demandées aux utilisateurs (Accès aux données)</div>
          <ul className="list-disc pl-5 text-xs text-slate-700">{etat.autorisations.map((a) => <li key={a}><code>{a}</code></li>)}</ul>
        </div>
        <div className="text-sm text-slate-700" data-testid="agenda-liaisons">
          <span className="font-semibold">{etat.total}</span> agenda(s) lié(s)
          {Object.entries(etat.liaisons_par_plateforme).map(([p, n]) => <span key={p} className="ml-2 rounded-full bg-sky-100 px-2 py-0.5 text-xs font-semibold text-sky-800">{p} : {n}</span>)}
        </div>
      </>)}
    </div>
  );
}
