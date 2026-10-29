// RecalculKbSection.jsx — Lot 348 : recalculer la base de connaissances de Liluvine avec le modèle de Qdrant.
//
// Sur un petit serveur (offre 512 Mo), le modèle de recherche local est suspendu : Liluvine ne cherche plus dans la base.
// Qdrant peut calculer lui-même les vecteurs (modèle multilingue gratuit). Méthode sans risque :
//   1. « Recalculer » copie la collection dans « <nom>-e5 » (l'originale n'est jamais modifiée) ;
//   2. « Basculer » donne la copie à Liluvine à la place de l'originale ; « Annuler la bascule » remet l'originale.
import React, { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const bouton = "text-xs font-semibold px-3 py-1.5 rounded-md bg-blue-700 text-white hover:bg-blue-800 disabled:opacity-50";
// Accord « 1 point » / « N points »
const points = (n) => `${n ?? "?"} point${n > 1 ? "s" : ""}`;
const libelles = { jamais: "Pas encore recalculée", en_cours: "Recalcul en cours…", copie_prete: "Copie prête", erreur: "Erreur" };

export default function RecalculKbSection() {
  const [etat, setEtat] = useState(null);
  const [occupe, setOccupe] = useState(false);
  const minuteur = useRef(null);
  // Panneau « Voir le contenu » : une seule collection ouverte à la fois ; on peut regarder l'originale ou la copie recalculée
  const [vue, setVue] = useState(null);   // { nom, points: [] | null, total, erreur, question, resultats }

  const ouvrir = async (nom) => {
    setVue({ nom, points: null, total: null, erreur: null, question: "", resultats: null });
    try {
      const r = await apiClient.get(`/admin/qdrant/collections/${encodeURIComponent(nom)}/points`, { params: { limit: 20 } });
      setVue((v) => (v && v.nom === nom ? { ...v, points: r.data.items || [], total: r.data.total } : v));
    } catch (err) {
      setVue((v) => (v && v.nom === nom ? { ...v, points: [], erreur: err?.response?.data?.detail || "Lecture impossible" } : v));
    }
  };
  const tester = async () => {
    if (!vue || vue.question.trim().length < 2) { toast.error("Saisissez une question"); return; }
    try {
      const r = await apiClient.post(`/admin/qdrant/collections/${encodeURIComponent(vue.nom)}/search`, { query: vue.question, top_k: 5 });
      setVue((v) => ({ ...v, resultats: r.data.items || [], erreur: null }));
    } catch (err) {
      const detail = err?.response?.data?.detail || "Recherche impossible";
      setVue((v) => ({ ...v, resultats: null, erreur: /m[ée]moire du serveur/i.test(detail)
        ? "La recherche sur cette collection est suspendue (serveur trop petit pour son modèle). Utilisez la copie « -e5 »." : detail }));
    }
  };

  // Lecture de l'état ; tant qu'un recalcul tourne, on relit toutes les 5 secondes
  const charger = useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/qdrant/recalcul-e5/etat");
      setEtat(r.data);
      clearTimeout(minuteur.current);
      if (r.data.en_cours) minuteur.current = setTimeout(charger, 5000);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Base de connaissances indisponible");
    }
  }, []);
  useEffect(() => { charger(); return () => clearTimeout(minuteur.current); }, [charger]);

  const action = async (chemin, corps, message) => {
    setOccupe(true);
    try {
      await apiClient.post(`/admin/qdrant/recalcul-e5/${chemin}`, corps);
      toast.success(message);
      await charger();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Action impossible");
    } finally {
      setOccupe(false);
    }
  };

  if (!etat) return <p className="text-xs text-slate-500">Patientez…</p>;
  return (
    <div className="space-y-3" data-testid="recalcul-kb">
      <p className="text-xs text-slate-600">
        Recalculez une collection avec le modèle de Qdrant pour que Liluvine puisse la consulter même sur un petit serveur, et pour y ajouter
        les questions / réponses validées. L'originale n'est <strong>jamais modifiée ni supprimée</strong> : le recalcul crée une copie « -e5 »,
        puis vous basculez quand vous avez vérifié ; « Annuler la bascule » remet l'originale.
      </p>
      {etat.collections.length === 0 && <p className="text-xs text-slate-500">Aucune collection à recalculer.</p>}
      {etat.collections.map((c) => (
        <div key={c.collection} className="rounded-md border border-slate-200 p-3 text-sm space-y-1">
          <div className="font-semibold">{c.collection} <span className="font-normal text-slate-500">— {points(c.points)}{c.utilisee_par_liluvine ? " · utilisée par Liluvine" : ""}</span></div>
          <div className="text-xs">
            {libelles[c.statut] || c.statut}
            {c.statut === "en_cours" && c.total ? ` : ${c.faits || 0} / ${c.total}` : ""}
            {c.statut === "copie_prete" && c.copie ? ` : « ${c.copie} » contient ${points(c.points_copie)}${c.saute ? ` (${c.saute} sans texte non recopiés)` : ""}` : ""}
            {c.erreur && <span className="text-red-700"> — {c.erreur}</span>}
            {c.bascule && <strong className="text-green-700"> · Liluvine utilise la copie</strong>}
          </div>
          <div className="flex flex-wrap gap-2 pt-1">
            <button type="button" className={bouton} disabled={occupe || c.statut === "en_cours"} data-testid={`recalculer-${c.collection}`}
              onClick={() => action("demarrer", { collection: c.collection }, "Recalcul lancé en arrière-plan")}>
              {c.statut === "copie_prete" || c.statut === "erreur" ? "Relancer le recalcul" : "Recalculer"}
            </button>
            {c.statut === "copie_prete" && !c.bascule && (
              <button type="button" className={bouton} disabled={occupe} onClick={() => action("basculer", { collection: c.collection, actif: true }, "Liluvine utilise la copie")}>Basculer</button>
            )}
            <button type="button" className="text-xs font-semibold px-3 py-1.5 rounded-md border border-slate-300 hover:bg-slate-50" data-testid={`voir-${c.collection}`}
              onClick={() => (vue?.nom === c.collection ? setVue(null) : ouvrir(c.collection))}>
              {vue?.nom === c.collection ? "Masquer le contenu" : "Voir le contenu"}
            </button>
            {c.copie && (
              <button type="button" className="text-xs font-semibold px-3 py-1.5 rounded-md border border-slate-300 hover:bg-slate-50" data-testid={`voir-copie-${c.collection}`}
                onClick={() => (vue?.nom === c.copie ? setVue(null) : ouvrir(c.copie))}>
                {vue?.nom === c.copie ? "Masquer la copie" : "Voir la copie (-e5)"}
              </button>
            )}
            {c.bascule && (
              <button type="button" className="text-xs font-semibold px-3 py-1.5 rounded-md border border-slate-300 hover:bg-slate-50" disabled={occupe}
                onClick={() => action("basculer", { collection: c.collection, actif: false }, "L'originale est remise")}>Annuler la bascule</button>
            )}
          </div>
          {vue && (vue.nom === c.collection || vue.nom === c.copie) && (
            <div className="mt-2 rounded-md bg-slate-50 border border-slate-200 p-2 space-y-2" data-testid="contenu-collection">
              <div className="text-xs font-semibold">Contenu de « {vue.nom} » {vue.total != null ? `— ${points(vue.total)}` : ""}{vue.points && vue.total > vue.points.length ? ` (les ${vue.points.length} premiers)` : ""}</div>
              {!vue.points && <p className="text-xs text-slate-500">Patientez…</p>}
              {vue.points && vue.points.length === 0 && !vue.erreur && <p className="text-xs text-slate-500">Cette collection est vide.</p>}
              <ul className="space-y-1 max-h-72 overflow-auto">
                {(vue.points || []).map((p) => (
                  <li key={p.id} className="text-xs border-b border-slate-200 pb-1">
                    <strong>{p.title}</strong> {p.kind === "image" && <span className="text-slate-500">(image)</span>}
                    <div className="whitespace-pre-wrap text-slate-700">{p.text_preview}</div>
                    {p.image_url && <a className="text-blue-700 underline" href={p.image_url} target="_blank" rel="noreferrer">Voir l'image</a>}
                  </li>
                ))}
              </ul>
              <div className="flex flex-wrap gap-2">
                <input className="flex-1 min-w-[12rem] rounded-md border border-slate-300 px-2 py-1 text-sm" placeholder="Tester une question sur ce contenu…" value={vue.question}
                  onChange={(e) => setVue((v) => ({ ...v, question: e.target.value }))} onKeyDown={(e) => e.key === "Enter" && tester()} data-testid="tester-question" />
                <button type="button" className={bouton} onClick={tester}>Tester</button>
              </div>
              {vue.erreur && <p className="text-xs text-red-700">{vue.erreur}</p>}
              {vue.resultats && (vue.resultats.length === 0 ? <p className="text-xs text-slate-500">Aucun résultat.</p> : (
                <ul className="space-y-1">
                  {vue.resultats.map((h) => (
                    <li key={h.id} className="text-xs"><strong>{h.title}</strong> · score {Number(h.score).toFixed(3)}<div className="whitespace-pre-wrap text-slate-700">{(h.text || "").slice(0, 280)}</div></li>
                  ))}
                </ul>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
