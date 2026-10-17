/*
  Lot 235 — Paramètres : « Annonceurs des plateformes » — un abonné de Paiement Mobile peut devenir annonceur.
    - TARIFS (ici seulement, administrateur principal) : formats avec prix par jour, options en %, remises selon la durée,
      durée minimale / maximale, tailles maximales des médias (image en Ko, vidéo en Mo).
    - Le site de l'annonceur affiche son devis en direct (calcul fait par SAWALI, jamais par le navigateur).
    - Campagnes : montant calculé, CORRECTION DU MONTANT (avant paiement seulement, motif conservé), suspension / réactivation,
      confirmation des paiements PI-SPI (vérifier la référence bancaire dans le relevé avant de confirmer).
    - Les médias sont chiffrés (AES-256) ; une campagne payée est publiée dans la régie (emplacement « Paiement Mobile »).
  API : GET/PUT /admin/annonceurs-plateformes/tarifs, GET /admin/annonceurs-plateformes/campagnes, PUT …/campagnes/{id}/montant,
  POST …/campagnes/{id}/suspendre|reactiver|pispi/confirmer|pispi/refuser (backend/routes/annonceurs_plateformes.py).
*/
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const fcfa = (n) => `${Number(n || 0).toLocaleString("fr-FR")} FCFA`;
const ETATS = { devis: "Devis", paiement_en_cours: "Paiement en cours", pispi_attente: "Virement attendu", pispi_verification: "À vérifier",
  active: "Active", suspendue: "Suspendue", terminee: "Terminée" };

export default function AnnonceursPlateformesSection() {
  const [t, setT] = useState(null);                 // tarifs en cours de saisie
  const [campagnes, setCampagnes] = useState(null);
  const [montants, setMontants] = useState({});      // correction de montant saisie, par campagne

  const charger = useCallback(async () => {
    try {
      const [a, b] = await Promise.all([apiClient.get("/admin/annonceurs-plateformes/tarifs"), apiClient.get("/admin/annonceurs-plateformes/campagnes")]);
      setT(a.data.tarifs);
      setCampagnes(b.data.campagnes);
    } catch (e) { toast.error(e?.response?.data?.detail || "Annonceurs indisponibles (réservé à l'administrateur principal)"); }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  // Enregistre les tarifs (SAWALI vérifie tout : codes uniques, prix positifs, durées cohérentes)
  const enregistrer = async () => {
    try { const r = await apiClient.put("/admin/annonceurs-plateformes/tarifs", t); setT(r.data.tarifs); toast.success("Tarifs enregistrés"); }
    catch (err) { toast.error(err?.response?.data?.detail || "Enregistrement impossible"); }
  };
  const agir = async (c, action, corps, confirmation) => {
    if (confirmation && !window.confirm(confirmation)) return;
    try {
      if (action === "montant") await apiClient.put(`/admin/annonceurs-plateformes/campagnes/${c.id}/montant`, corps);
      else await apiClient.post(`/admin/annonceurs-plateformes/campagnes/${c.id}/${action}`, corps);
      toast.success("Fait");
      charger();
    } catch (err) { toast.error(err?.response?.data?.detail || "Action impossible"); }
  };
  const maj = (liste, i, cle, valeur) => setT({ ...t, [liste]: t[liste].map((x, j) => (j === i ? { ...x, [cle]: valeur } : x)) });

  if (!t) return <p className="text-xs text-slate-500">Chargement…</p>;
  const aVerifier = (campagnes || []).filter((c) => c.statut === "pispi_verification");
  return (
    <div className="space-y-4" data-testid="annonceurs-plateformes">
      {aVerifier.length > 0 && (
        <p className="rounded-lg bg-sky-50 p-3 text-sm font-semibold text-sky-900 ring-1 ring-sky-200">🏦 {aVerifier.length} paiement(s) PI-SPI d'annonce à vérifier (tableau ci-dessous).</p>
      )}
      <div className="space-y-2 rounded-lg border border-slate-200 p-3">
        <p className="text-sm font-semibold">Tarifs des annonces</p>
        <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={t.actif} onChange={(e) => setT({ ...t, actif: e.target.checked })} /> Annonces ouvertes aux abonnés</label>
        <table className="w-full text-xs">
          <thead><tr className="text-left text-slate-500"><th>Format</th><th>Média</th><th>Prix par jour (FCFA)</th></tr></thead>
          <tbody>{t.formats.map((f, i) => (
            <tr key={f.code}><td>{f.libelle}</td><td>{f.media === "video" ? "Vidéo" : "Image"}</td>
              <td><input type="number" min="1" value={f.prix_jour} onChange={(e) => maj("formats", i, "prix_jour", Number(e.target.value))} className="w-28 rounded border border-slate-300 px-2 py-1" /></td></tr>
          ))}</tbody>
        </table>
        <table className="w-full text-xs">
          <thead><tr className="text-left text-slate-500"><th>Option</th><th>Majoration (%)</th></tr></thead>
          <tbody>{t.options.map((o, i) => (
            <tr key={o.code}><td>{o.libelle}</td>
              <td><input type="number" min="0" value={o.majoration_pct} onChange={(e) => maj("options", i, "majoration_pct", Number(e.target.value))} className="w-24 rounded border border-slate-300 px-2 py-1" /></td></tr>
          ))}</tbody>
        </table>
        <table className="w-full text-xs">
          <thead><tr className="text-left text-slate-500"><th>Remise à partir de (jours)</th><th>Remise (%)</th></tr></thead>
          <tbody>{t.remises.map((r, i) => (
            <tr key={i}>
              <td><input type="number" min="2" value={r.jours_min} onChange={(e) => maj("remises", i, "jours_min", Number(e.target.value))} className="w-24 rounded border border-slate-300 px-2 py-1" /></td>
              <td><input type="number" min="1" max="90" value={r.remise_pct} onChange={(e) => maj("remises", i, "remise_pct", Number(e.target.value))} className="w-24 rounded border border-slate-300 px-2 py-1" /></td></tr>
          ))}</tbody>
        </table>
        <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-5">
          {[["duree_min", "Durée min (jours)"], ["duree_max", "Durée max (jours)"], ["avance_max_jours", "Début dans … jours au plus"], ["image_max_ko", "Image max (Ko)"], ["video_max_mo", "Vidéo max (Mo)"]].map(([cle, lib]) => (
            <label key={cle} className="space-y-1">{lib}<input type="number" min="1" value={t[cle]} onChange={(e) => setT({ ...t, [cle]: Number(e.target.value) })} className="w-full rounded border border-slate-300 px-2 py-1" /></label>
          ))}
        </div>
        <button type="button" onClick={enregistrer} className="rounded bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white">Enregistrer les tarifs</button>
      </div>

      <div className="space-y-2">
        <p className="text-sm font-semibold">Annonces des abonnés ({campagnes?.length || 0})</p>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead><tr className="text-left text-slate-500"><th>Annonce</th><th>Période</th><th>Devis</th><th>Montant dû</th><th>État</th><th>Vues / clics</th><th /></tr></thead>
            <tbody>
              {(campagnes || []).map((c) => (
                <tr key={c.id} className="border-t border-slate-100 align-top">
                  <td className="p-1">{c.nom}<span className="block text-slate-500">{c.annonceur} · {c.format}</span></td>
                  <td>{c.debut} → {c.fin}<span className="block text-slate-500">{c.jours} j</span></td>
                  <td>{fcfa(c.montant_calcule)}</td>
                  <td>{fcfa(c.montant)}{c.montant_corrige && <span className="block text-amber-700">corrigé</span>}</td>
                  <td>{ETATS[c.statut] || c.statut}{c.reference_bancaire && <span className="block font-mono text-slate-500">{c.reference_bancaire}</span>}</td>
                  <td>{c.impressions} / {c.clics}</td>
                  <td className="boutons-distincts flex flex-wrap gap-1 p-1">
                    {["devis", "paiement_en_cours", "pispi_attente", "pispi_verification"].includes(c.statut) && (
                      <span className="flex items-center gap-1">
                        <input type="number" min="0" placeholder="Nouveau montant" value={montants[c.id] ?? ""} onChange={(e) => setMontants({ ...montants, [c.id]: e.target.value })} className="w-28 rounded border border-slate-300 px-2 py-1" />
                        <button type="button" disabled={montants[c.id] === undefined || montants[c.id] === ""} className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40"
                          onClick={() => agir(c, "montant", { montant: Number(montants[c.id]), motif: "Correction par SAWALI" }, `Corriger le montant de « ${c.nom} » à ${fcfa(montants[c.id])} ? Toute demande de paiement en cours sera annulée.`)}>Corriger</button>
                      </span>
                    )}
                    {c.statut === "pispi_verification" && (<>
                      <button type="button" onClick={() => agir(c, "pispi/confirmer", {}, `Confirmer la réception de ${fcfa(c.montant)} (référence ${c.reference_bancaire || "?"}) ?`)} className="rounded bg-emerald-600 px-2 py-1 text-white">Confirmer</button>
                      <button type="button" onClick={() => agir(c, "pispi/refuser", undefined, "Refuser ce paiement ?")} className="rounded border border-slate-300 px-2 py-1">Refuser</button>
                    </>)}
                    {c.statut === "active" && <button type="button" onClick={() => agir(c, "suspendre", undefined, `Suspendre l'annonce « ${c.nom} » ?`)} className="rounded border border-slate-300 px-2 py-1">Suspendre</button>}
                    {c.statut === "suspendue" && <button type="button" onClick={() => agir(c, "reactiver")} className="rounded border border-slate-300 px-2 py-1">Réactiver</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {campagnes && campagnes.length === 0 && <p className="p-2 text-xs text-slate-500">Aucune annonce pour le moment.</p>}
        </div>
      </div>
    </div>
  );
}
