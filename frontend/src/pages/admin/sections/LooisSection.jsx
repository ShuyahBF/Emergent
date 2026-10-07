// LooisSection.jsx — Lot 71.3 : rubrique « 🔄 Loois — synchronisation des tables et clés clients » des Paramètres.
// État de la configuration (poivre, clé commune, clés par client) et réglage de transition « accepter encore la
// clé commune » ; la gestion détaillée (tables, clés, données) reste sur l'écran Loois → Synchro.
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

export default function LooisSection() {
  const [donnees, setDonnees] = useState(null);
  const [occupe, setOccupe] = useState(false);

  // Lecture des clés (sans empreinte) et des réglages
  const charger = () => apiClient.get("/admin/loois-cles-clients").then((r) => setDonnees(r.data)).catch(() => setDonnees({ erreur: true }));
  useEffect(() => { charger(); }, []);

  // Bascule du réglage de transition (clé commune acceptée pour la synchro)
  const basculer = async (valeur) => {
    setOccupe(true);
    try {
      await apiClient.put("/admin/loois-cles-clients-reglages", { accepter_cle_commune_synchro: valeur });
      toast.success(valeur ? "Clé commune acceptée pour la synchro (transition)" : "Synchro réservée aux clés par client");
      await charger();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Modification impossible");
    } finally {
      setOccupe(false);
    }
  };

  if (!donnees) return <p className="text-sm text-slate-500">Patientez…</p>;
  if (donnees.erreur) return <p className="text-sm text-red-700">Réglages Loois indisponibles (droits administrateur nécessaires).</p>;
  const actives = (donnees.cles || []).filter((c) => c.actif).length;
  const sansCle = (donnees.sites_connus || []).filter((s) => !s.a_une_cle).length;
  // Petite pastille d'état (vert = OK, orange = à faire)
  const etat = (ok, texte) => (
    <li className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${ok ? "bg-emerald-500" : "bg-amber-500"}`} />{texte}</li>
  );
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-loois">
      <h3 className="font-semibold text-slate-900">🔄 Loois — synchronisation des tables HFSQL et clés clients</h3>
      <ul className="space-y-1 text-xs text-slate-700">
        {etat(actives > 0, `${actives} clé(s) client active(s)`)}
        {etat(sansCle === 0, sansCle ? `${sansCle} site(s) vu(s) par la synchro sans clé client` : "Tous les sites connus ont leur clé")}
        {etat(donnees.poivre_configure, donnees.poivre_configure ? "Poivre des clés configuré (LOOIS_CLES_PEPPER)" : "Poivre facultatif non configuré (LOOIS_CLES_PEPPER)")}
        {etat(true, donnees.cle_commune_configuree ? "Clé commune du support configurée (LOOIS_SUPPORT_CLE)" : "Clé commune du support non configurée")}
      </ul>
      <label className="flex items-center gap-2 text-xs">
        <input type="checkbox" disabled={occupe} checked={!!donnees.reglages?.accepter_cle_commune_synchro}
          onChange={(e) => basculer(e.target.checked)} />
        Transition : accepter encore la clé commune pour la synchro des tables (déconseillé une fois les clés par client saisies)
      </label>
      <div className="flex justify-end">
        <Link to="/admin/loois-synchro" className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">
          Tables, clés et données : Loois → Synchro ↗
        </Link>
      </div>
    </div>
  );
}
