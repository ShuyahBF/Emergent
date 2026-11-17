// DemandesPlateformesSection.jsx — Lot 384 : contenu de la page « 📮 Demandes des plateformes » (menu Plateformes ; lot 393 : plus dans les Paramètres).
// Les plateformes clientes (ALBARKA…) remontent leurs corrections et nouvelles fonctionnalités ; SAWALI leur attribue un numéro
// (DEM-…) et le leur retourne avec un commentaire et la date de réalisation (ou la date prévue). Ici l'administrateur traite
// chaque demande : en attente (date prévue), réalisée (date + commentaire) ou refusée (raison). Recherche libre en haut.
import React, { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import DetailDemandeModal, { PiecesLecture } from "@/components/DetailDemandeModal";   // lot 427 : 20 premiers caractères + « Détails » (modale)
import GanttEnchainement from "@/components/GanttEnchainement";       // lot 427 : enchaînement, points morts des demandes non terminées

import { Clock, OctagonAlert, Play, Save as Ico15Save, X as Ico15X } from "lucide-react";
const jour = (d) => (d ? String(d).slice(0, 10).split("-").reverse().join("/") : "—");
const COULEUR = { remontee: "text-amber-700", en_cours: "text-sky-700", point_mort: "text-slate-900", realisee: "text-emerald-700", refusee: "text-rose-700" };
// Lot 429 : statuts « En cours » et « Point mort » (jamais la couleur seule : pictogramme + libellé)
const LIBELLE = { remontee: "En attente", en_cours: "En cours", point_mort: "Point mort", realisee: "Réalisée", refusee: "Refusée" };
const PICTO = { remontee: Clock, en_cours: Play, point_mort: OctagonAlert };
// Durée estimée : liste finie → liste déroulante (règle 10)
const UNITES = [["jour", "Jour(s)"], ["semaine", "Semaine(s)"], ["mois", "Mois"], ["annee", "Année(s)"]];
const duree = (d) => (d.duree_valeur && d.duree_unite ? `${d.duree_valeur} ${{ jour: "jour(s)", semaine: "semaine(s)", mois: "mois", annee: "an(s)" }[d.duree_unite] || ""}` : "");

export default function DemandesPlateformesSection() {
  const [q, setQ] = useState("");
  const [demandes, setDemandes] = useState(null);
  const [edition, setEdition] = useState(null);   // { plateforme, numero, statut, commentaire, realisee_le, prevue_le, duree_valeur, duree_unite, debut_le, demande }
  const blocEdition = useRef(null);
  // Pièces jointes (lot 430) : le contenu est lu À LA DEMANDE, avec la session de l'administrateur (jamais d'adresse publique)
  const chargerPiece = (d, p) => apiClient.get(`/admin/plateformes/${d.plateforme}/demandes/${d.numero}/pieces/${p.id}`, { responseType: "blob" })
    .then((r) => r.data).catch((e) => { toast.error(e?.response?.status === 404 ? "Pièce introuvable" : "Pièce illisible"); throw e; });

  const charger = useCallback(() => apiClient.get("/admin/plateformes/demandes", { params: { q } })
    .then((r) => setDemandes(r.data.demandes)).catch(() => setDemandes([])), [q]);
  useEffect(() => { const t = setTimeout(charger, 250); return () => clearTimeout(t); }, [charger]);   // recherche en direct

  // Enregistre le traitement de la demande ouverte
  const enregistrer = async () => {
    try {
      await apiClient.put(`/admin/plateformes/${edition.plateforme}/demandes/${edition.numero}`, {
        statut: edition.statut, commentaire: edition.commentaire, realisee_le: edition.realisee_le || null, prevue_le: edition.prevue_le || null,
        duree_valeur: edition.duree_valeur || null, duree_unite: edition.duree_valeur ? edition.duree_unite : null, debut_le: edition.debut_le || null });
      toast.success("Demande mise à jour : la plateforme la relira à son prochain échange");
      setEdition(null);
      charger();
    } catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible"); }
  };

  // Ouvre le bloc de traitement : il reprend le détail de la demande, la ligne reste sélectionnée et le bloc vient à l'écran
  const ouvrir = (d) => {
    setEdition({ plateforme: d.plateforme, numero: d.numero, statut: d.statut, commentaire: d.commentaire || "", realisee_le: d.realisee_le || "", prevue_le: d.prevue_le || "",
      duree_valeur: d.duree_valeur || "", duree_unite: d.duree_unite || "semaine", debut_le: d.debut_le || "", demande: d });
    setTimeout(() => blocEdition.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }), 50);
  };

  if (!demandes) return <p className="text-sm text-slate-500">Patientez…</p>;
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-demandes-plateformes">
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Rechercher une demande (texte, numéro DEM-…, commentaire, « refusée »…)"
        className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="demandes-plateformes-recherche" />
      <p className="text-xs text-slate-600">
        Les plateformes (ALBARKA…) remontent leurs demandes de corrections et de nouvelles fonctionnalités ; chacune reçoit ici un numéro
        <b> DEM-…</b> retourné à la plateforme avec votre commentaire et la date de réalisation (ou la date prévue).
      </p>
      {/* Lot 427 : vue d'ensemble des demandes NON terminées de toutes les plateformes (enchaînement, points morts, retards) — repliée par défaut */}
      <details className="rounded-lg border border-slate-200 p-3" data-testid="vue-enchainement">
        <summary className="cursor-pointer text-sm font-semibold">📈 Enchaînement des demandes non terminées (points morts, retards)</summary>
        <div className="mt-3"><GanttEnchainement demandes={demandes.map((d) => ({ ...d, id: d.numero, numero_sawali: d.numero, plateforme: d.plateforme_nom, demandee_le: d.demandee_le || d.recue_le, prevue_le: d.fin_prevue_le || d.prevue_le }))} /></div>
      </details>
      <table className="w-full text-xs">
        <thead className="text-left text-slate-500"><tr><th className="py-1">N°</th><th>Plateforme</th><th>Type</th><th>Demande</th><th>Statut</th><th>Durée / Planning</th><th>Suivi</th><th /></tr></thead>
        <tbody>
          {demandes.map((d) => (
            <tr key={d.numero} aria-selected={edition?.numero === d.numero} data-testid={`demande-${d.numero}`}
              className={`border-t border-slate-100 align-top ${edition?.numero === d.numero ? "bg-red-600 text-white [&_*]:!text-white" : ""}`}>
              <td className="py-1 font-mono">{d.numero}</td><td>{d.plateforme_nom}</td>
              <td>{d.type === "correction" ? "Correction" : "Nouveauté"}</td><td className="max-w-xs"><DetailDemandeModal chargerPiece={(_, p) => chargerPiece(d, p)} d={{ ...d, id: d.numero, numero_sawali: d.numero, type_libelle: d.type === "correction" ? "Correction" : "Nouveauté", statut_libelle: LIBELLE[d.statut] || d.statut, plateforme: d.plateforme_nom }} /></td>
              <td className={`font-semibold ${COULEUR[d.statut] || ""}`}>{(() => { const P = PICTO[d.statut]; return <>{P && <P className="mr-1 inline-block h-3.5 w-3.5" aria-hidden="true" />}{LIBELLE[d.statut] || d.statut}</>; })()}</td>
              <td className="tabular-nums">{duree(d)}{d.debut_prevu_le && d.fin_prevue_le && <div>{jour(d.debut_prevu_le)} → {jour(d.fin_prevue_le)}</div>}
                {d.retard_jours > 0 && <div className="font-semibold">⚠ en retard de {d.retard_jours} j</div>}</td>
              <td>{d.statut === "realisee" ? `Réalisée le ${jour(d.realisee_le)}` : d.statut === "remontee" && !d.fin_prevue_le && d.prevue_le ? `Prévue le ${jour(d.prevue_le)}` : ""}
                {d.commentaire && <div className="text-slate-500">{d.commentaire}</div>}</td>
              <td><button type="button" className="rounded bg-sky-700 px-2 py-1 text-white"
                onClick={() => ouvrir(d)}>Traiter</button></td>
            </tr>
          ))}
          {demandes.length === 0 && <tr><td colSpan={8} className="py-3 text-center text-slate-500">Aucune demande{q ? " pour cette recherche" : ""}.</td></tr>}
        </tbody>
      </table>
      {edition && (
        <div ref={blocEdition} className="space-y-2 rounded-lg border border-sky-200 bg-sky-50 p-3" data-testid="demandes-plateformes-edition">
          <div className="text-sm font-semibold">Traiter {edition.numero}</div>
          {/* Détail repris de la demande sélectionnée : on traite sans quitter le bloc */}
          <div className="rounded border border-sky-200 bg-white p-2 text-xs" data-testid="edition-detail">
            <div className="text-slate-600">{edition.demande.plateforme_nom} · {edition.demande.type === "correction" ? "Correction" : "Nouveauté"} · demandée le {jour(edition.demande.demandee_le || edition.demande.recue_le)}{edition.demande.demandee_par ? ` par ${edition.demande.demandee_par}` : ""}</div>
            <div className="mt-1 max-h-40 overflow-y-auto whitespace-pre-wrap text-sm">{edition.demande.texte}</div>
            {(edition.demande.pieces || []).length > 0 && <div className="mt-2"><PiecesLecture d={edition.demande} chargerPiece={(_, p) => chargerPiece(edition.demande, p)} /></div>}
          </div>
          <select value={edition.statut} onChange={(e) => setEdition({ ...edition, statut: e.target.value })} className="rounded border border-slate-300 px-2 py-1 text-sm">
            <option value="remontee">En attente</option>
            <option value="en_cours">En cours</option>
            <option value="point_mort">Point mort (travail arrêté)</option>
            <option value="realisee">Réalisée</option>
            <option value="refusee">Refusée</option>
          </select>
          {["remontee", "en_cours", "point_mort"].includes(edition.statut) && (
            <div className="flex flex-wrap items-center gap-2 text-xs" data-testid="edition-duree">
              <label>Durée estimée <input type="number" min={1} max={999} value={edition.duree_valeur} onChange={(e) => setEdition({ ...edition, duree_valeur: e.target.value })} className="ml-1 w-16 rounded border border-slate-300 px-2 py-1 tabular-nums" /></label>
              <select value={edition.duree_unite} onChange={(e) => setEdition({ ...edition, duree_unite: e.target.value })} className="rounded border border-slate-300 px-2 py-1" aria-label="Unité de durée">
                {UNITES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
              <span className="text-slate-600">La durée place la demande dans le diagramme : elle commence quand la précédente se termine.</span>
            </div>
          )}
          {edition.statut === "remontee" && edition.duree_valeur && <label className="block text-xs">Début imposé (facultatif) <input type="date" value={edition.debut_le} onChange={(e) => setEdition({ ...edition, debut_le: e.target.value })} className="ml-1 rounded border border-slate-300 px-2 py-1" /> vide = la demande suit la précédente ; une date la place EN PARALLÈLE (chevauchement)</label>}
          {["en_cours", "point_mort"].includes(edition.statut) && <label className="block text-xs">Commencée le <input type="date" value={edition.debut_le} onChange={(e) => setEdition({ ...edition, debut_le: e.target.value })} className="ml-1 rounded border border-slate-300 px-2 py-1" /> (vide = aujourd'hui)</label>}
          {edition.statut === "remontee" && !edition.duree_valeur && <label className="block text-xs">Prévue le <input type="date" value={edition.prevue_le} onChange={(e) => setEdition({ ...edition, prevue_le: e.target.value })} className="ml-1 rounded border border-slate-300 px-2 py-1" /> (sans durée estimée)</label>}
          {edition.statut === "realisee" && <label className="block text-xs">Réalisée le <input type="date" value={edition.realisee_le} onChange={(e) => setEdition({ ...edition, realisee_le: e.target.value })} className="ml-1 rounded border border-slate-300 px-2 py-1" /> (vide = aujourd'hui)</label>}
          <textarea value={edition.commentaire} onChange={(e) => setEdition({ ...edition, commentaire: e.target.value })} rows={2}
            placeholder={edition.statut === "refusee" ? "Raison du refus (obligatoire)" : edition.statut === "point_mort" ? "Raison du point mort (obligatoire)" : "Commentaire pour la plateforme"} className="w-full rounded border border-slate-300 px-2 py-1 text-sm" />
          <div className="flex gap-2">
            <button type="button" onClick={enregistrer} className="rounded bg-emerald-700 px-3 py-1.5 text-sm font-semibold text-white"><Ico15Save className="inline-block h-4 w-4 shrink-0 mr-1" aria-hidden="true" />Enregistrer</button>
            <button type="button" onClick={() => setEdition(null)} className="rounded border border-slate-300 px-3 py-1.5 text-sm"><Ico15X className="inline-block h-4 w-4 shrink-0 mr-1" aria-hidden="true" />Annuler</button>
          </div>
        </div>
      )}
    </div>
  );
}
