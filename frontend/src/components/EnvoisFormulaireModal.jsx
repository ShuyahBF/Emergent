/*
  Lot 42 — « Envoyer » un formulaire public : historique des envois du lien et nouvel envoi.
  - liste des envois (programmé, en attente de la plage horaire, en cours, terminé, annulé),
    avec le nombre envoyé / échecs et les premières erreurs ;
  - « Nouvel envoi » : même fenêtre que pour un sondage (SurveySendModal, kind="form") :
    destinataires, WhatsApp (modèle Meta / message libre) ou SMS, maintenant ou programmé.
  API : /me/forms/{id}/envois (backend/routes/envois_formulaires.py).
*/
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Send, X, RefreshCw } from "lucide-react";
import { apiClient } from "@/lib/api";
import SurveySendModal from "@/components/SurveySendModal";
import SuiviEnvois, { STATUTS_ENVOI } from "@/components/SuiviEnvois";
import { dateHeure } from "@/components/EnvoiProgrammation";
import { siVisible } from "@/lib/visibilite";   // lot 79.6 : relectures en pause onglet masqué

export default function EnvoisFormulaireModal({ form, onClose }) {
  const [envois, setEnvois] = useState([]);
  const [nouvel, setNouvel] = useState(false);

  const charger = useCallback(async () => {
    try { const r = await apiClient.get(`/me/forms/${form.id}/envois`); setEnvois(r.data?.items || []); }
    catch (e) { toast.error(e?.response?.data?.detail || "Envois indisponibles"); }
  }, [form.id]);
  useEffect(() => { charger(); }, [charger]);

  // Envoi en cours : actualisation toutes les 4 s
  const enCours = envois.some((e) => e.status === "running");
  useEffect(() => {
    if (!enCours) return undefined;
    const t = setInterval(siVisible(charger), 4000);   // lot 79.6 : relecture en pause onglet masqué
    return () => clearInterval(t);
  }, [enCours, charger]);

  const annuler = async (eid) => {
    try { await apiClient.delete(`/me/forms/${form.id}/envois/${eid}`); toast.success("Envoi annulé"); charger(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Annulation impossible"); }
  };

  if (nouvel) {
    return <SurveySendModal survey={form} kind="form" onClose={() => setNouvel(false)}
      onSent={() => { setNouvel(false); charger(); }} />;
  }
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40" data-testid="envois-formulaire-modal"
      onClick={(e) => e.target === e.currentTarget && onClose?.()}>
      <div className="w-full max-w-2xl max-h-[90vh] overflow-auto rounded-2xl bg-white shadow-2xl">
        <div className="sticky top-0 flex items-center gap-2 border-b border-slate-200 bg-white px-5 py-3">
          <div className="min-w-0">
            <p className="text-xs uppercase tracking-wider text-slate-500">Envois du lien du formulaire</p>
            <h2 className="font-semibold text-slate-900 truncate">{form.title}</h2>
          </div>
          <button onClick={charger} className="ml-auto p-1.5 rounded hover:bg-slate-100" title="Actualiser">
            <RefreshCw className={`h-4 w-4 ${enCours ? "animate-spin" : ""}`} />
          </button>
          <button onClick={onClose} className="p-1.5 rounded hover:bg-slate-100" title="Fermer"><X className="h-5 w-5" /></button>
        </div>
        <div className="p-5 space-y-4">
          <button onClick={() => setNouvel(true)} data-testid="envoi-formulaire-nouveau"
            className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 text-white px-4 py-2 text-sm font-semibold hover:bg-emerald-700">
            <Send className="h-4 w-4" /> Nouvel envoi (WhatsApp ou SMS)
          </button>
          <SuiviEnvois items={envois} onAnnuler={annuler} />
          <div className="divide-y divide-slate-100 rounded-xl ring-1 ring-slate-200">
            {envois.map((e) => {
              const [libelle, cls] = STATUTS_ENVOI[e.status] || STATUTS_ENVOI.done;
              return (
                <div key={e.id} className="px-3 py-2 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-slate-500 text-xs">{dateHeure(e.created_at)}</span>
                    <span className={`text-[11px] rounded-full px-2 py-0.5 ${cls}`}>{libelle}</span>
                    <span className="text-xs text-slate-500">{e.channel === "sms" ? "SMS" : "WhatsApp"}{e.template_name ? ` · ${e.template_name}` : ""}</span>
                    <span className="ml-auto text-xs tabular-nums text-slate-700">
                      {e.sent_ok} envoyé(s) / {e.total} · {e.sent_ko} échec(s) · {e.skipped} non envoyé(s)
                    </span>
                  </div>
                  {e.status === "running" && (
                    <div className="mt-1 h-1.5 rounded-full bg-sky-100 overflow-hidden">
                      <div className="h-full bg-sky-500" style={{ width: `${e.total ? (100 * e.done) / e.total : 0}%` }} />
                    </div>
                  )}
                  {e.echecs?.length > 0 && (
                    <ul className="mt-1 text-[11px] text-rose-600 list-disc pl-4">
                      {e.echecs.slice(0, 5).map((x, i) => <li key={i}>{x.name} : {x.error}</li>)}
                    </ul>
                  )}
                </div>
              );
            })}
            {!envois.length && <p className="px-3 py-4 text-sm text-slate-500">Aucun envoi pour l'instant.</p>}
          </div>
        </div>
      </div>
    </div>
  );
}
