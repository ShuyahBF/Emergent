// AgendaPasserelleSection.jsx — Lot 403 : réglages de la passerelle « Agenda Google » par utilisateur (auRor, Concentration, Personnel Maison).
// Rien de secret ici : l'adresse de retour à DÉCLARER chez Google, les autorisations demandées, l'état (Google configuré ?) et le NOMBRE de liaisons par plateforme.
// Les agendas des utilisateurs ne sont jamais lisibles depuis SAWALI : seul chaque utilisateur voit le sien (voir backend/routes/agenda_passerelle.py).
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { CalendarDays, Copy, RefreshCw, Loader2, CheckCircle2, AlertTriangle, Check, X, ShieldCheck } from "lucide-react";
import { apiClient } from "@/lib/api";
import ThTri from "@/components/ThTri";            // règle 19 : toutes les colonnes triables
import { useTri } from "@/lib/tri";

export default function AgendaPasserelleSection() {
  const [etat, setEtat] = useState(null);
  const [chargement, setChargement] = useState(false);
  const triDemandes = useTri(etat?.demandes || [], {
    quand: (d) => d.cree_le, plateforme: (d) => d.plateforme, utilisateur: (d) => d.nom || d.utilisateur, gmail: (d) => d.gmail, etat: (d) => d.etat }, { cle: "quand", sens: "desc" });

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

  // Accepter / refuser une demande, activer / désactiver l'approbation : chaque action annonce « en cours » puis son résultat
  const decider = async (d, decision) => {
    toast.info(decision === "accepte" ? "Acceptation en cours…" : "Refus en cours…");
    try { await apiClient.post(`/admin/agenda-passerelle/demandes/${d.id}`, { decision }); toast.success(decision === "accepte" ? `Accès accepté pour ${d.gmail}` : `Accès refusé pour ${d.gmail}`); await charger(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Décision non enregistrée"); }
  };
  const reglerApprobation = async (actif) => {
    toast.info("Enregistrement du réglage en cours…");
    try { await apiClient.put("/admin/agenda-passerelle/approbation", { actif }); toast.success(actif ? "Approbation ACTIVÉE : les utilisateurs doivent demander l'accès" : "Approbation DÉSACTIVÉE : tout utilisateur peut lier son agenda"); await charger(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Réglage non enregistré"); }
  };
  const ETATS = { attente: ["⏳ En attente", "bg-amber-100 text-amber-800"], accepte: ["✅ Acceptée", "bg-emerald-100 text-emerald-800"], refuse: ["⛔ Refusée", "bg-red-100 text-red-700"] };
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
        {/* Approbation : responsabiliser les utilisateurs (compte Google indiqué, accepté par l'administrateur avant la liaison) */}
        <div className="space-y-2 rounded-lg border border-slate-200 p-3" data-testid="agenda-approbation">
          <div className="flex flex-wrap items-center gap-3">
            <span className="flex items-center gap-1 text-sm font-semibold text-slate-800"><ShieldCheck className="h-4 w-4 text-sky-700" />Approbation des comptes Google</span>
            <button type="button" role="switch" aria-checked={etat.approbation} onClick={() => reglerApprobation(!etat.approbation)} data-testid="agenda-approbation-interrupteur"
                    className={`rounded-full border px-3 py-1 text-xs font-semibold ${etat.approbation ? "border-emerald-300 bg-emerald-50 text-emerald-800" : "border-slate-300 bg-slate-100 text-slate-600"}`}>
              {etat.approbation ? "Activée" : "Désactivée"}
            </button>
            <span className="text-xs text-slate-500">enregistré automatiquement</span>
          </div>
          <p className="text-xs text-slate-500">Activée : chaque utilisateur indique d'abord son compte Google ; vous l'acceptez ou le refusez ; seul ce compte pourra ensuite être lié. Cela décide aussi qui occupe les places du plafond d'utilisateurs de Google.</p>
          {triDemandes.lignes.length === 0 ? <p className="text-sm text-slate-500">Aucune demande pour l'instant.</p> : (
            <div className="max-h-72 overflow-auto"><table className="tableau w-full text-sm" data-testid="agenda-demandes">
              <thead><tr className="text-left">
                <ThTri cle="quand" tri={triDemandes.tri} onTri={triDemandes.basculer}>Demande</ThTri><ThTri cle="plateforme" tri={triDemandes.tri} onTri={triDemandes.basculer}>Plateforme</ThTri>
                <ThTri cle="utilisateur" tri={triDemandes.tri} onTri={triDemandes.basculer}>Utilisateur</ThTri><ThTri cle="gmail" tri={triDemandes.tri} onTri={triDemandes.basculer}>Compte Google</ThTri>
                <ThTri cle="etat" tri={triDemandes.tri} onTri={triDemandes.basculer}>État</ThTri><th className="p-2" /></tr></thead>
              <tbody>{triDemandes.lignes.map((d) => (
                <tr key={d.id} className="border-t border-slate-100">
                  <td className="whitespace-nowrap p-2 text-xs">{d.cree_le ? new Date(d.cree_le).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—"}</td>
                  <td className="p-2">{d.plateforme}</td><td className="p-2">{d.nom || d.utilisateur}</td><td className="p-2 font-mono text-xs text-sky-800">{d.gmail}</td>
                  <td className="p-2"><span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${ETATS[d.etat]?.[1] || ""}`}>{ETATS[d.etat]?.[0] || d.etat}</span></td>
                  <td className="whitespace-nowrap p-2 text-right">
                    {d.etat !== "accepte" && <button type="button" onClick={() => decider(d, "accepte")} className="mr-2 inline-flex items-center gap-1 rounded bg-emerald-600 px-2 py-1 text-xs font-semibold text-white" title="Accepter" aria-label={`Accepter ${d.gmail}`}><Check className="h-3.5 w-3.5" />Accepter</button>}
                    {d.etat !== "refuse" && <button type="button" onClick={() => decider(d, "refuse")} className="inline-flex items-center gap-1 rounded border border-red-300 px-2 py-1 text-xs font-semibold text-red-700" title="Refuser" aria-label={`Refuser ${d.gmail}`}><X className="h-3.5 w-3.5" />Refuser</button>}
                  </td></tr>))}</tbody>
            </table></div>
          )}
        </div>
        <div className="text-sm text-slate-700" data-testid="agenda-liaisons">
          <span className="font-semibold">{etat.total}</span> agenda(s) lié(s)
          {Object.entries(etat.liaisons_par_plateforme).map(([p, n]) => <span key={p} className="ml-2 rounded-full bg-sky-100 px-2 py-0.5 text-xs font-semibold text-sky-800">{p} : {n}</span>)}
        </div>
      </>)}
    </div>
  );
}
