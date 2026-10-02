// =====================================================================
// Lot 50 — D. Date de la dernière sauvegarde, visible par chaque utilisateur
// (« Mon compte » et, discrètement, en pied de page de l'espace de gestion).
//   « Dernière sauvegarde générale : JJ/MM/AAAA HH:MM » (sauvegarde quotidienne
//   chiffrée vers Cloudflare R2, lot 49) ; « Aucune sauvegarde enregistrée » en orange.
// Les clients SAWALI n'ont pas de sauvegarde propre : seule la sauvegarde générale existe.
// Backend : GET /api/me/derniere-sauvegarde.
// =====================================================================
import React, { useEffect, useState } from "react";
import { DatabaseBackup } from "lucide-react";
import { apiClient } from "@/lib/api";

const DUREE_CACHE_MS = 10 * 60 * 1000;
let cache = { lu_a: 0, donnees: null };

export const formatDateHeure = (iso) => {
  try {
    return new Date(iso).toLocaleString("fr-FR", {
      day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
    }).replace(",", "");
  } catch { return iso; }
};

function useDerniereSauvegarde() {
  const [donnees, setDonnees] = useState(cache.donnees);
  useEffect(() => {
    if (cache.donnees && Date.now() - cache.lu_a < DUREE_CACHE_MS) return undefined;
    let arret = false;
    apiClient.get("/me/derniere-sauvegarde", { headers: { "X-Requete-Fond": "1" } })
      .then((r) => { cache = { lu_a: Date.now(), donnees: r.data }; if (!arret) setDonnees(r.data); })
      .catch(() => { /* silencieux */ });
    return () => { arret = true; };
  }, []);
  return donnees;
}

/** variante « pied » : une ligne discrète ; variante « carte » : bloc de « Mon compte ». */
export default function DerniereSauvegarde({ variante = "pied" }) {
  const d = useDerniereSauvegarde();
  if (!d) return null;
  const le = d.generale?.le;
  const texte = le ? `Dernière sauvegarde générale : ${formatDateHeure(le)}` : "Aucune sauvegarde enregistrée";
  if (variante === "pied") {
    return (
      <p className={`px-3 pb-3 text-center text-[10px] ${le ? "text-slate-400" : "text-orange-600"}`} data-testid="pied-derniere-sauvegarde">
        {texte}
      </p>
    );
  }
  return (
    <section className="rounded-2xl bg-white p-5 ring-1 ring-slate-200" data-testid="carte-derniere-sauvegarde">
      <h2 className="mb-2 flex items-center gap-2 font-display text-sm font-semibold text-slate-700">
        <DatabaseBackup className="h-4 w-4 text-sawali-blue" /> Sauvegardes
      </h2>
      <p className={`text-sm ${le ? "text-slate-700" : "font-semibold text-orange-600"}`}>{texte}</p>
      {d.propre?.le && (
        <p className="mt-1 text-sm text-slate-700">Dernière sauvegarde de votre espace : {formatDateHeure(d.propre.le)}</p>
      )}
    </section>
  );
}
