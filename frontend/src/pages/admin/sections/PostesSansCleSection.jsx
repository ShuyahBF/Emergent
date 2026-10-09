// PostesSansCleSection.jsx — Lot 89 : rubrique « 🔑 Postes Loois sans clé client (alerte) » des Paramètres.
// Réglage de l'alerte (administrateur), tableau des postes Loois vus depuis 7 jours sans clé client valable (aucune
// clé, clé commune seulement, clé inconnue ou révoquée), bouton vers l'onglet « Clés clients » pour créer les clés.
// Règle des tableaux : survol bleu clair, ligne sélectionnée orange (CSS global, attribut aria-selected).
import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";

// Date ISO → « JJ/MM/AAAA HH:MM » (heure de Ouagadougou = UTC)
const dateHeure = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("fr-FR", { timeZone: "Africa/Ouagadougou", dateStyle: "short", timeStyle: "short" });
};
// Couleur de la pastille selon l'état de la clé
const COULEURS = { refusee: "bg-rose-100 text-rose-800", absente: "bg-amber-100 text-amber-800", commune: "bg-sky-100 text-sky-800" };

export default function PostesSansCleSection() {
  const { user } = useAuth();
  const [donnees, setDonnees] = useState(null);
  const [selection, setSelection] = useState(null);
  const [enreg, setEnreg] = useState(false);

  // Lecture de la liste et du réglage
  const charger = useCallback(async () => {
    try { setDonnees((await apiClient.get("/admin/loois-postes-sans-cle")).data); }
    catch (e) { setDonnees({ erreur: e?.response?.data?.detail || "Liste indisponible" }); }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  // Activation / désactivation de l'alerte (administrateur)
  const basculer = async () => {
    setEnreg(true);
    try {
      await apiClient.put("/admin/loois-postes-sans-cle/reglage", { actif: !donnees.actif });
      toast.success(!donnees.actif ? "Alerte activée" : "Alerte désactivée");
      await charger();
    } catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible"); }
    finally { setEnreg(false); }
  };

  if (!donnees) return <p className="text-sm text-slate-500">Patientez…</p>;
  if (donnees.erreur) return <p className="text-sm text-rose-600">{donnees.erreur}</p>;
  const postes = donnees.postes || [];
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-postes-sans-cle">
      <p className="text-xs text-slate-600">
        Loois n'affiche <b>aucun message</b> sur un poste dont la clé client manque ou est refusée (les utilisateurs
        pourraient se croire suivis). SAWALI le repère grâce au signal de présence (toutes les 5 min) et alerte
        l'<b>administrateur</b> et le <b>superviseur</b> par un toast dans le portail. Postes vus depuis {donnees.jours_suivi} jours.
      </p>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${donnees.actif ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-600"}`}>
          Alerte {donnees.actif ? "activée" : "désactivée"}
        </span>
        {user?.role === "admin" && (
          <button onClick={basculer} disabled={enreg} className="rounded-lg bg-sky-700 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50">
            {enreg ? "Patientez…" : donnees.actif ? "Désactiver l'alerte" : "Activer l'alerte"}
          </button>
        )}
        <button onClick={charger} className="text-xs text-slate-600 underline">Actualiser</button>
        <Link to="/admin/loois-synchro" className="rounded-lg bg-violet-600 px-3 py-1.5 text-sm font-semibold text-white">
          Créer les clés clients (onglet « Clés clients »)
        </Link>
      </div>
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs text-slate-500">
            <tr>
              <th className="px-2 py-2">Poste</th><th className="px-2">Site</th><th className="px-2">Utilisateur</th>
              <th className="px-2">État de la clé</th><th className="px-2">Depuis</th><th className="px-2">Dernier signal</th>
            </tr>
          </thead>
          <tbody>
            {postes.length === 0 && (
              <tr><td colSpan={6} className="px-2 py-4 text-center text-slate-500">✅ Tous les postes Loois ont une clé client valable.</td></tr>
            )}
            {postes.map((p) => (
              <tr key={p.machine} onClick={() => setSelection(p.machine)} aria-selected={selection === p.machine}
                  className={`cursor-pointer border-t border-slate-100 ${selection === p.machine ? "ligne-selectionnee" : ""}`}>
                <td className="px-2 py-1.5 font-semibold">{p.machine}</td>
                <td className="px-2">{p.site || "—"}</td>
                <td className="px-2">{p.utilisateur || "—"}</td>
                <td className="px-2"><span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${COULEURS[p.statut] || ""}`}>{p.libelle}</span></td>
                <td className="px-2 whitespace-nowrap">{dateHeure(p.depuis)}</td>
                <td className="px-2 whitespace-nowrap">{dateHeure(p.vu_le)}{p.en_ligne ? " · en ligne" : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
