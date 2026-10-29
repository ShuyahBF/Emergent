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
const libelles = { jamais: "Pas encore recalculée", en_cours: "Recalcul en cours…", copie_prete: "Copie prête", erreur: "Erreur" };

export default function RecalculKbSection() {
  const [etat, setEtat] = useState(null);
  const [occupe, setOccupe] = useState(false);
  const minuteur = useRef(null);

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
          <div className="font-semibold">{c.collection} <span className="font-normal text-slate-500">— {c.points ?? "?"} points{c.utilisee_par_liluvine ? " · utilisée par Liluvine" : ""}</span></div>
          <div className="text-xs">
            {libelles[c.statut] || c.statut}
            {c.statut === "en_cours" && c.total ? ` : ${c.faits || 0} / ${c.total}` : ""}
            {c.statut === "copie_prete" && c.copie ? ` : « ${c.copie} » contient ${c.points_copie ?? "?"} points${c.saute ? ` (${c.saute} sans texte non recopiés)` : ""}` : ""}
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
            {c.bascule && (
              <button type="button" className="text-xs font-semibold px-3 py-1.5 rounded-md border border-slate-300 hover:bg-slate-50" disabled={occupe}
                onClick={() => action("basculer", { collection: c.collection, actif: false }, "L'originale est remise")}>Annuler la bascule</button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
