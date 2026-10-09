// SondagesLoois.jsx — Lot 88 : sondages « Evaluation Loois » dans le Support Loois.
//   - EnvoiSondageLoois : dans le fil d'un poste, choisir un sondage « Evaluation Loois… » et l'envoyer (numéroté) ;
//   - CarteSondage      : carte affichée dans la bulle (numéro, titre, statut : à remplir / répondu / annulé).
// Tant que le poste n'a pas répondu, il ne peut plus faire de nouvelle demande d'assistance (règle du serveur).
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

// Libellé et couleur de chaque statut d'un sondage envoyé
export const STATUTS_SONDAGE = {
  en_attente: { libelle: "⏳ À remplir", classe: "bg-amber-100 text-amber-800" },
  repondu: { libelle: "✅ Répondu", classe: "bg-emerald-100 text-emerald-800" },
  annule: { libelle: "Annulé", classe: "bg-slate-100 text-slate-600" },
};

// Date ISO → « JJ/MM/AAAA HH:MM »
export const dateCourte = (iso) => {
  try { return iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : ""; } catch { return ""; }
};

/** Carte d'un sondage dans une bulle du fil (chat SAWALI). */
export function CarteSondage({ sondage, mine }) {
  const s = STATUTS_SONDAGE[sondage.statut] || STATUTS_SONDAGE.en_attente;
  return (
    <div className={`mb-1 rounded-lg p-2 text-xs ring-1 ${mine ? "bg-white/15 ring-white/30" : "bg-violet-50 ring-violet-200"}`}
         data-testid={`carte-sondage-${sondage.numero}`}>
      <p className="font-semibold">📋 Sondage {sondage.numero}</p>
      <p className="opacity-90">{sondage.titre}</p>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${s.classe}`}>{s.libelle}</span>
        {sondage.repondu_le && <span className="text-[10px] opacity-80">le {dateCourte(sondage.repondu_le)}</span>}
        <a href={`/admin/evaluations-loois?numero=${encodeURIComponent(sondage.numero || "")}`}
           className="text-[10px] underline opacity-90">Voir les réponses</a>
      </div>
    </div>
  );
}

/** Barre « 📋 Envoyer un sondage d'évaluation » du fil d'un poste Loois (équipe du support). */
export function EnvoiSondageLoois({ posteId }) {
  const [sondages, setSondages] = useState(null);   // sondages « Evaluation Loois… » proposés
  const [choix, setChoix] = useState("");
  const [envoi, setEnvoi] = useState(false);
  const [attente, setAttente] = useState(0);         // sondages de ce poste encore sans réponse

  // Liste des sondages proposés et sondages en attente du poste
  useEffect(() => {
    apiClient.get("/support-loois/sondages-disponibles").then((r) => {
      setSondages(r.data.sondages || []);
      setChoix((c) => c || r.data.sondages?.[0]?.id || "");
    }).catch(() => setSondages([]));
  }, []);
  useEffect(() => {
    if (!posteId) return;
    apiClient.get("/support-loois/sondages-envois", { params: { poste_id: posteId, statut: "en_attente" } })
      .then((r) => setAttente(r.data.envois?.length || 0)).catch(() => setAttente(0));
  }, [posteId, envoi]);

  // Envoi du sondage choisi (carte numérotée dans le fil du poste)
  const envoyer = async () => {
    if (!choix) return;
    setEnvoi(true);
    const t = toast.loading("Patientez… envoi du sondage");
    try {
      const r = await apiClient.post(`/support-loois/postes/${posteId}/sondages`, { survey_id: choix });
      toast.success(`Sondage ${r.data.envoi.numero} envoyé : le poste doit y répondre avant toute nouvelle demande`, { id: t });
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Envoi du sondage impossible", { id: t });
    } finally {
      setEnvoi(false);
    }
  };

  if (sondages === null) return null;
  return (
    <div className="mx-4 mt-2 flex flex-wrap items-center gap-2 rounded-lg bg-violet-50 px-3 py-1.5 text-xs ring-1 ring-violet-200"
         data-testid="envoi-sondage-loois">
      <span className="font-semibold text-violet-800">📋 Évaluation</span>
      {sondages.length === 0 ? (
        <span className="text-slate-500">Créez un sondage dont le titre commence par « Evaluation Loois » (menu Sondages).</span>
      ) : (
        <>
          <select value={choix} onChange={(e) => setChoix(e.target.value)} className="max-w-[220px] rounded border border-slate-300 px-1.5 py-0.5"
                  data-testid="envoi-sondage-choix">
            {sondages.map((s) => <option key={s.id} value={s.id}>{s.titre} ({s.questions} q.)</option>)}
          </select>
          <button onClick={envoyer} disabled={envoi || !choix}
                  className="rounded bg-violet-600 px-2 py-0.5 font-semibold text-white hover:bg-violet-700 disabled:opacity-40"
                  data-testid="envoi-sondage-bouton">
            {envoi ? "Patientez…" : "Envoyer le sondage"}
          </button>
        </>
      )}
      {attente > 0 && (
        <span className="ml-auto rounded-full bg-amber-100 px-2 py-0.5 font-semibold text-amber-800"
              title="Le poste ne peut plus faire de nouvelle demande tant qu'il n'a pas répondu">
          ⏳ {attente} sondage(s) sans réponse — demandes bloquées
        </span>
      )}
    </div>
  );
}
