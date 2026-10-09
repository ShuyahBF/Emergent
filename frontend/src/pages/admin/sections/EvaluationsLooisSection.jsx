// EvaluationsLooisSection.jsx — Lot 88 : rubrique « 📋 Évaluations Loois (sondages du support) » des Paramètres.
// Phrase de remerciement de Liluvine (après la réponse d'un poste), état des sondages envoyés, lien vers la fenêtre
// d'évaluation. {numero} dans la phrase est remplacé par le numéro du sondage (ex. EVL-2026-0001).
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

export default function EvaluationsLooisSection() {
  const [reg, setReg] = useState(null);
  const [phrase, setPhrase] = useState("");
  const [enreg, setEnreg] = useState(false);

  // Lecture des réglages et de l'état
  useEffect(() => {
    apiClient.get("/admin/support-loois/reglages").then((r) => { setReg(r.data); setPhrase(r.data.remerciement_sondage || ""); })
      .catch(() => setReg({ erreur: true }));
  }, []);

  // Enregistrement de la phrase de remerciement
  const enregistrer = async () => {
    setEnreg(true);
    try {
      const r = await apiClient.put("/admin/support-loois/reglages", { remerciement_sondage: phrase });
      setReg(r.data);
      toast.success("Phrase de remerciement enregistrée");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Enregistrement impossible");
    } finally { setEnreg(false); }
  };

  if (!reg) return <p className="text-sm text-slate-500">Patientez…</p>;
  if (reg.erreur) return <p className="text-sm text-rose-600">Réglages indisponibles (équipe du support seulement).</p>;
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-evaluations-loois">
      <p className="text-xs text-slate-600">
        Dans le fil d'un poste du <b>Support Loois</b>, « 📋 Envoyer le sondage » adresse un sondage dont le titre commence par
        <b> « Evaluation Loois »</b> (menu Sondages). Il s'affiche tel quel dans la fenêtre de Loois, numéroté (EVL-AAAA-NNNN).
        Tant qu'il n'est pas rempli, le poste <b>ne peut plus faire de nouvelle demande</b>. À la réponse, Liluvine remercie avec
        la phrase ci-dessous. Un message écrit par le support à un poste sans session ouvre une session et un ticket ; l'icône
        de Loois ouvre alors la fenêtre de conversation.
      </p>
      <label className="block text-sm font-semibold text-slate-700">
        Phrase de remerciement de Liluvine
        <textarea value={phrase} onChange={(e) => setPhrase(e.target.value)} rows={3} maxLength={1000}
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal"
                  data-testid="evaluations-remerciement" />
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <button onClick={enregistrer} disabled={enreg} className="rounded-lg bg-sky-700 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50">
          {enreg ? "Patientez…" : "Enregistrer"}
        </button>
        <button onClick={() => setPhrase(reg.remerciement_defaut)} className="text-xs text-slate-600 underline">Phrase par défaut</button>
        <span className="text-[11px] text-slate-500">{"{numero}"} = numéro du sondage</span>
      </div>
      <div className="grid gap-2 text-sm sm:grid-cols-3">
        <div className="rounded-lg bg-slate-50 p-2"><p className="text-[11px] text-slate-500">Sondages envoyés</p><p className="font-semibold">{reg.stats?.envoyes ?? 0}</p></div>
        <div className="rounded-lg bg-emerald-50 p-2"><p className="text-[11px] text-slate-500">Répondus</p><p className="font-semibold">{reg.stats?.repondus ?? 0}</p></div>
        <div className="rounded-lg bg-amber-50 p-2"><p className="text-[11px] text-slate-500">En attente (postes bloqués)</p><p className="font-semibold">{reg.stats?.en_attente ?? 0}</p></div>
      </div>
      <Link to="/admin/evaluations-loois" className="inline-block rounded-lg bg-violet-600 px-3 py-1.5 text-sm font-semibold text-white">
        Ouvrir la fenêtre d'évaluation
      </Link>
    </div>
  );
}
