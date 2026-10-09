// AdminEvaluationsLoois.jsx — Lot 88 : fenêtre d'évaluation des sondages « Evaluation Loois » envoyés aux postes.
// Liste numérotée (EVL-AAAA-NNNN) : poste, école, ticket, sondage, statut, réponses détaillées ; filtres (statut,
// sondage, numéro), taux de réponse ; « Analyse » ouvre la page Résultats du sondage (graphiques, export CSV) ;
// « Annuler » un sondage sans réponse débloque le poste. Règle des tableaux : survol bleu, sélection orange.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { STATUTS_SONDAGE, dateCourte } from "@/components/SondagesLoois";

// Réponse lisible selon le type de question (étoiles, liste, texte)
const reponseLisible = (r) => {
  if (r.reponse === null || r.reponse === undefined) return "—";
  if (r.type === "rating") return `${"★".repeat(Number(r.reponse))}${"☆".repeat(5 - Number(r.reponse))} (${r.reponse}/5)`;
  if (r.type === "nps") return `${r.reponse}/10`;
  if (Array.isArray(r.reponse)) return r.reponse.join(", ");
  return String(r.reponse);
};

export default function AdminEvaluationsLoois() {
  const [params] = useSearchParams();
  const [donnees, setDonnees] = useState(null);
  const [statut, setStatut] = useState("");
  const [sondage, setSondage] = useState("");
  const [recherche, setRecherche] = useState(params.get("numero") || "");
  const [selection, setSelection] = useState(null);   // ligne sélectionnée (détail des réponses)
  // Lot 90.2 — sondages « Evaluation Loois… » du module Sondages, MÊME s'ils n'ont encore jamais été envoyés
  const [disponibles, setDisponibles] = useState([]);

  // Chargement de la liste (toast « Patientez… » pendant l'attente)
  const charger = useCallback(async () => {
    const t = toast.loading("Patientez… chargement des évaluations");
    try {
      const r = await apiClient.get("/support-loois/sondages-envois", { params: { statut: statut || undefined, survey_id: sondage || undefined } });
      setDonnees(r.data);
      toast.dismiss(t);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Évaluations indisponibles", { id: t });
      setDonnees({ envois: [], resume: {} });
    }
  }, [statut, sondage]);
  useEffect(() => { charger(); }, [charger]);
  // Lot 90.2 — lecture des sondages disponibles (avant : un sondage jamais envoyé n'apparaissait nulle part)
  useEffect(() => {
    apiClient.get("/support-loois/sondages-disponibles").then((r) => setDisponibles(r.data?.sondages || [])).catch(() => setDisponibles([]));
  }, []);

  // Filtre texte (numéro, poste, école, ticket)
  const lignes = useMemo(() => {
    const q = recherche.trim().toLowerCase();
    return (donnees?.envois || []).filter((e) => !q ||
      [e.numero, e.poste, e.ecole, e.ticket_number, e.titre].some((v) => (v || "").toLowerCase().includes(q)));
  }, [donnees, recherche]);
  // Sondages du filtre : tous les sondages « Evaluation Loois » disponibles + ceux déjà envoyés (même clôturés)
  const sondages = useMemo(() => {
    const m = new Map();
    disponibles.forEach((d) => m.set(d.id, d.titre));
    (donnees?.envois || []).forEach((e) => m.set(e.survey_id, e.titre));
    return [...m.entries()];
  }, [donnees, disponibles]);
  // Nombre d'envois et de réponses par sondage (cartes des sondages disponibles)
  const compteurs = useMemo(() => {
    const c = {};
    (donnees?.envois || []).forEach((e) => {
      c[e.survey_id] = c[e.survey_id] || { envoyes: 0, repondus: 0 };
      c[e.survey_id].envoyes += 1;
      if (e.statut === "repondu") c[e.survey_id].repondus += 1;
    });
    return c;
  }, [donnees]);
  // Sélection automatique quand on arrive avec ?numero=
  useEffect(() => {
    if (params.get("numero") && lignes.length === 1) setSelection(lignes[0].envoi_id);
  }, [lignes, params]);

  const annuler = async (e) => {
    if (!window.confirm(`Annuler le sondage ${e.numero} ? Le poste pourra de nouveau faire des demandes.`)) return;
    try {
      await apiClient.post(`/support-loois/sondages-envois/${e.envoi_id}/annuler`);
      toast.success("Sondage annulé : le poste est débloqué");
      charger();
    } catch (err) { toast.error(err?.response?.data?.detail || "Annulation impossible"); }
  };

  const r = donnees?.resume || {};
  const choisie = lignes.find((e) => e.envoi_id === selection);
  return (
    <div className="space-y-4 p-4" data-testid="page-evaluations-loois">
      <div>
        <h1 className="text-xl font-bold text-slate-900">📋 Évaluations Loois</h1>
        <p className="text-sm text-slate-600">
          Sondages « Evaluation Loois » envoyés aux postes depuis le Support Loois, numérotés ; leurs réponses s'analysent aussi
          dans la page Résultats de chaque sondage (graphiques, export CSV).
        </p>
      </div>

      {/* Lot 90.2 — sondages « Evaluation Loois » disponibles (créés dans le menu Sondages), envoyés ou non */}
      <div className="rounded-xl border border-violet-200 bg-white p-3" data-testid="evaluations-disponibles">
        <p className="text-sm font-semibold text-violet-900">Sondages « Evaluation Loois » disponibles ({disponibles.length})</p>
        {disponibles.length === 0 ? (
          <p className="mt-1 text-xs text-slate-500">
            Aucun sondage dont le titre commence par « Evaluation Loois » (menu Sondages ; un sondage clôturé n'est pas proposé).
          </p>
        ) : (
          <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {disponibles.map((d) => {
              const c = compteurs[d.id] || { envoyes: 0, repondus: 0 };
              return (
                <div key={d.id} className="rounded-lg border border-slate-200 p-2 text-xs">
                  <p className="font-semibold text-slate-800">{d.titre}</p>
                  <p className="text-slate-500">{d.questions} question(s) · {c.envoyes ? `${c.envoyes} envoi(s), ${c.repondus} réponse(s)` : "jamais envoyé"}</p>
                  <div className="mt-1 flex gap-3">
                    <button onClick={() => setSondage(d.id)} className="text-violet-700 underline">Filtrer</button>
                    <Link to={`/admin/surveys/${d.id}/results`} className="text-violet-700 underline">📊 Analyse</Link>
                  </div>
                </div>
              );
            })}
          </div>
        )}
        <p className="mt-2 text-[11px] text-slate-500">
          Pour l'envoyer : chat → « Support Loois » → fil du poste → « 📋 Envoyer le sondage ». Il apparaît alors dans le tableau ci-dessous, numéroté (EVL-AAAA-NNNN).
        </p>
      </div>

      {/* Indicateurs */}
      <div className="grid gap-2 text-sm sm:grid-cols-4">
        <div className="rounded-lg bg-slate-50 p-2"><p className="text-[11px] text-slate-500">Sondages envoyés</p><p className="font-semibold">{r.total ?? "—"}</p></div>
        <div className="rounded-lg bg-emerald-50 p-2"><p className="text-[11px] text-slate-500">Répondus</p><p className="font-semibold">{r.repondus ?? "—"}</p></div>
        <div className="rounded-lg bg-amber-50 p-2"><p className="text-[11px] text-slate-500">En attente (postes bloqués)</p><p className="font-semibold">{r.en_attente ?? "—"}</p></div>
        <div className="rounded-lg bg-violet-50 p-2"><p className="text-[11px] text-slate-500">Taux de réponse</p><p className="font-semibold">{r.taux != null ? `${r.taux} %` : "—"}</p></div>
      </div>

      {/* Filtres */}
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <input value={recherche} onChange={(e) => setRecherche(e.target.value)} placeholder="N° EVL, poste, école, ticket…"
               className="rounded border border-slate-300 px-2 py-1" data-testid="evaluations-recherche" />
        <select value={statut} onChange={(e) => setStatut(e.target.value)} className="rounded border border-slate-300 px-2 py-1">
          <option value="">Tous les statuts</option>
          <option value="en_attente">À remplir</option>
          <option value="repondu">Répondus</option>
          <option value="annule">Annulés</option>
        </select>
        <select value={sondage} onChange={(e) => setSondage(e.target.value)} className="rounded border border-slate-300 px-2 py-1">
          <option value="">Tous les sondages</option>
          {sondages.map(([id, titre]) => <option key={id} value={id}>{titre}</option>)}
        </select>
        {sondage && (
          <Link to={`/admin/surveys/${sondage}/results`} className="rounded bg-violet-600 px-3 py-1 font-semibold text-white">📊 Analyse du sondage</Link>
        )}
      </div>

      {/* Tableau des sondages envoyés */}
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs text-slate-500">
            <tr>
              <th className="px-2 py-2">N°</th><th className="px-2">Envoyé le</th><th className="px-2">Poste</th><th className="px-2">École</th>
              <th className="px-2">Ticket</th><th className="px-2">Sondage</th><th className="px-2">Statut</th><th className="px-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {lignes.length === 0 && (
              <tr><td colSpan={8} className="px-2 py-4 text-center text-slate-500">Aucun sondage envoyé pour ces critères.</td></tr>
            )}
            {lignes.map((e) => {
              const st = STATUTS_SONDAGE[e.statut] || STATUTS_SONDAGE.en_attente;
              return (
                <tr key={e.envoi_id} onClick={() => setSelection(e.envoi_id)}
                    className={`cursor-pointer border-t border-slate-100 ${selection === e.envoi_id ? "ligne-selectionnee" : ""}`}
                    aria-selected={selection === e.envoi_id}>
                  <td className="px-2 py-1.5 font-mono text-xs font-semibold">{e.numero}</td>
                  <td className="px-2 whitespace-nowrap">{dateCourte(e.envoye_le)}</td>
                  <td className="px-2">{e.poste}</td>
                  <td className="px-2">{e.ecole}</td>
                  <td className="px-2">{e.ticket_number || "—"}</td>
                  <td className="px-2">{e.titre}</td>
                  <td className="px-2"><span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${st.classe}`}>{st.libelle}</span>
                    {e.repondu_le && <span className="ml-1 text-[11px] opacity-80">{dateCourte(e.repondu_le)}</span>}</td>
                  <td className="px-2 whitespace-nowrap">
                    <Link to={`/admin/surveys/${e.survey_id}/results`} onClick={(ev) => ev.stopPropagation()} className="text-xs text-violet-700 underline">Analyse</Link>
                    {e.statut === "en_attente" && (
                      <button onClick={(ev) => { ev.stopPropagation(); annuler(e); }} className="ml-2 text-xs text-rose-700 underline">Annuler</button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Détail des réponses du sondage sélectionné */}
      {choisie && (
        <div className="rounded-xl border border-violet-200 bg-violet-50/40 p-3 text-sm" data-testid="evaluations-detail">
          <p className="font-semibold text-violet-900">Réponses au sondage {choisie.numero} — {choisie.poste}</p>
          {choisie.reponses?.length ? (
            <ul className="mt-2 space-y-1">
              {choisie.reponses.map((x, i) => (
                <li key={i}><span className="text-slate-600">{x.question} :</span> <b>{reponseLisible(x)}</b></li>
              ))}
            </ul>
          ) : <p className="mt-1 text-slate-500">Pas encore de réponse.</p>}
          {choisie.revisions > 0 && <p className="mt-1 text-[11px] text-slate-500">Réponse modifiée {choisie.revisions} fois par le poste.</p>}
        </div>
      )}
    </div>
  );
}
