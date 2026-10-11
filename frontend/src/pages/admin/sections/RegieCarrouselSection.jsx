// RegieCarrouselSection.jsx — Lot 111 : rubrique « 📣 Régie publicitaire — carrousels WhatsApp sponsorisés »
// des Paramètres.
// - Réglage : fenêtre de déduplication des clics facturables et des vues / « Je suis intéressé » (24 h par défaut) ;
// - État : campagnes de régie « Carrousel WhatsApp », carrousels sponsorisés, clics bruts et facturés, montant
//   consommé, vues des pages de présentation et « Je suis intéressé » ;
// - Tableau des campagnes de régie (motif quand l'envoi est bloqué : budget épuisé, expirée, en pause…) ;
// - Boutons vers les écrans d'utilisation : Régie publicitaire et Carrousel WhatsApp.
// Règle des tableaux : survol bleu clair, ligne sélectionnée orange (CSS global, classe ligne-selectionnee + aria-selected).
import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const nf = (n) => (Number(n) || 0).toLocaleString("fr-FR");

export default function RegieCarrouselSection() {
  const [etat, setEtat] = useState(null);         // chiffres de la rubrique (GET /admin/whatsapp/carrousel/regie/etat)
  const [regies, setRegies] = useState([]);       // campagnes de régie « Carrousel WhatsApp »
  const [heures, setHeures] = useState(24);       // fenêtre de déduplication saisie
  const [selection, setSelection] = useState(null);
  const [enreg, setEnreg] = useState(false);

  // Lecture de l'état et de la liste des campagnes
  const charger = useCallback(async () => {
    try {
      const [e, r] = await Promise.all([
        apiClient.get("/admin/whatsapp/carrousel/regie/etat"),
        apiClient.get("/admin/whatsapp/carrousel/regies"),
      ]);
      setEtat(e.data);
      setHeures(e.data.dedup_heures || 24);
      setRegies(r.data.regies || []);
    } catch (err) {
      setEtat({ erreur: err?.response?.data?.detail || "État indisponible" });
    }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  // Enregistrement de la fenêtre de déduplication (1 à 168 h) dans les paramètres globaux
  const enregistrer = async () => {
    const valeur = Math.min(168, Math.max(1, Number(heures) || 24));
    setEnreg(true);
    const attente = toast.loading("Patientez… enregistrement");
    try {
      await apiClient.put("/admin/settings", { carrousel_regie_dedup_heures: valeur });
      toast.success(`Déduplication réglée sur ${valeur} h`, { id: attente });
      await charger();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Enregistrement impossible", { id: attente });
    } finally {
      setEnreg(false);
    }
  };

  if (!etat) return <p className="text-sm text-slate-500">Patientez…</p>;
  if (etat.erreur) return <p className="text-sm text-rose-600">{etat.erreur}</p>;
  const tuiles = [
    ["Campagnes de régie", etat.campagnes_regie], ["Envoyables maintenant", etat.actives],
    ["Carrousels sponsorisés", etat.carrousels_sponsorises], ["Clics bruts", etat.clics_bruts],
    ["Clics facturés", etat.clics_factures], ["Montant consommé", etat.montant_consomme],
    ["Vues des présentations", etat.vues_presentation], ["« Je suis intéressé »", etat.interesses],
  ];
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-regie-carrousel">
      <p className="text-xs text-slate-600">
        Le bouton d'une carte de carrousel peut ouvrir la <b>page de présentation</b> de tout le carrousel, directement
        sur la carte (<code>/presentation/c/…#carte-n</code>) avec « Je suis intéressé » (WhatsApp). Un carrousel de
        l'administration peut être <b>sponsorisé</b> par une campagne de la régie publicitaire (type « Carrousel
        WhatsApp ») : chaque clic sur un bouton est facturé au coût par clic, <b>une seule fois par appareil et par
        carte</b> sur la fenêtre ci-dessous ; chaque message accepté par WhatsApp peut être facturé au coût par envoi.
        Budget épuisé ou campagne expirée : le carrousel n'est plus envoyable, les liens déjà envoyés fonctionnent mais
        les clics ne sont plus facturés.
      </p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {tuiles.map(([libelle, v]) => (
          <div key={libelle} className="rounded-lg bg-slate-50 px-3 py-2 ring-1 ring-slate-200">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{libelle}</p>
            <p className="text-base font-bold tabular-nums text-slate-900">{nf(v)}</p>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap items-end gap-2 text-sm">
        <label className="block">
          <span className="text-[11px] font-semibold uppercase text-slate-500">Déduplication des clics et vues (heures)</span>
          <input type="number" min={1} max={168} value={heures} onChange={(e) => setHeures(e.target.value)}
                 className="mt-1 block w-32 rounded-lg px-3 py-2 ring-1 ring-slate-300" data-testid="regie-dedup-heures" />
        </label>
        <button onClick={enregistrer} disabled={enreg} className="rounded-lg bg-sky-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">
          {enreg ? "Patientez…" : "Enregistrer"}
        </button>
        <button onClick={charger} className="text-xs text-slate-600 underline">Actualiser</button>
        <Link to="/admin/ad-banners" className="rounded-lg bg-fuchsia-600 px-3 py-2 text-sm font-semibold text-white">
          Ouvrir la régie publicitaire
        </Link>
        <Link to="/admin/whatsapp-carrousel" className="rounded-lg bg-emerald-600 px-3 py-2 text-sm font-semibold text-white">
          Ouvrir le carrousel WhatsApp
        </Link>
      </div>
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs text-slate-500">
            <tr>
              <th className="px-2 py-2">Campagne</th><th className="px-2">Annonceur</th>
              <th className="px-2 text-right">Coût / clic</th><th className="px-2 text-right">Coût / envoi</th>
              <th className="px-2 text-right">Budget restant</th><th className="px-2">État</th>
            </tr>
          </thead>
          <tbody>
            {regies.length === 0 && (
              <tr><td colSpan={6} className="px-2 py-4 text-center text-slate-500">
                Aucune campagne « Carrousel WhatsApp » : créez-la dans la régie publicitaire (« Nouveau carrousel WhatsApp sponsorisé »).
              </td></tr>
            )}
            {regies.map((r) => (
              <tr key={r.id} onClick={() => setSelection(r.id)} aria-selected={selection === r.id}
                  className={`cursor-pointer border-t border-slate-100 ${selection === r.id ? "ligne-selectionnee" : ""}`}>
                <td className="px-2 py-1.5 font-medium">{r.nom}</td>
                <td className="px-2">{r.annonceur || "—"}</td>
                <td className="px-2 text-right tabular-nums">{nf(r.cout_par_clic)} {r.devise}</td>
                <td className="px-2 text-right tabular-nums">{nf(r.cout_par_envoi)} {r.devise}</td>
                <td className="px-2 text-right tabular-nums">{r.reste == null ? "sans plafond" : `${nf(r.reste)} ${r.devise}`}</td>
                <td className="px-2 text-xs">{r.motif ? <span className="text-rose-700">{r.motif}</span> : <span className="text-emerald-700">envoyable</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
