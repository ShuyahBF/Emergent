// LibererEspaceSection.jsx — Lot 113 : rubrique « 🧹 Libérer l'Espace » des Paramètres (administrateur).
//
// Demande du propriétaire (12/10/2026) : un SEUL bouton pour faire de la place, au lieu des nombreux boutons
// des rubriques de sauvegarde. Déroulement :
//   1. « 🧹 Libérer l'Espace » → analyse en lecture seule (GET /api/admin/liberer-espace/analyse) ;
//   2. plan en 3 blocs (sauvegardes R2 de migration, sauvegardes quotidiennes, bases du cluster Atlas) avec
//      cases pré-cochées selon les règles de rétention, éléments protégés grisés avec la raison ;
//   3. « Libérer maintenant » → saisie de LIBERER → POST /api/admin/liberer-espace/executer
//      (le serveur re-vérifie toutes les protections) → rapport final avec la jauge APRÈS.
// Backend : backend/routes/liberer_espace.py.
// Lot 116 : 4e bloc « Collections les moins utilisées (base SAWALI) » (backend/routes/collections_inutilisees.py) :
//   « Mesurer » → tableau du moins utilisé au plus utilisé → « Sauvegarder, désactiver et supprimer » (LIBERER)
//   → rapport ; liste des « Collections archivées » avec « Restaurer ».
import React, { useMemo, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

// Ancre de la rubrique dans les Paramètres (utilisée par les encadrés-renvois des autres rubriques)
export const ANCRE_LIBERER_ESPACE = "s-liberer-espace";

// Aller à la rubrique « Libérer l'Espace » : on demande d'abord son chargement (rubriques chargées à l'approche,
// lot 108), puis on s'y place, et on se recale car les rubriques voisines changent la hauteur de la page.
export function allerALibererEspace() {
  window.dispatchEvent(new CustomEvent("sawali:monter-rubrique", { detail: ANCRE_LIBERER_ESPACE }));
  const placer = () => document.getElementById(ANCRE_LIBERER_ESPACE)?.scrollIntoView({ behavior: "smooth", block: "start" });
  setTimeout(placer, 30);
  setTimeout(placer, 600);
  setTimeout(placer, 1400);
}

// Encadré-renvoi affiché dans les autres rubriques (sauvegardes, jauge Atlas) : un seul endroit pour faire de la place
export function RenvoiLibererEspace({ texte }) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900"
      data-testid="renvoi-liberer-espace">
      <span className="flex-1">{texte || <>Pour faire de la place, utilisez <b>🧹 Libérer l'Espace</b> : il applique les règles de rétention et protège ce qui doit l'être.</>}</span>
      <button type="button" onClick={allerALibererEspace}
        className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700">
        🧹 Aller à « Libérer l'Espace »
      </button>
    </div>
  );
}

// Octets -> texte lisible (Go au-delà de 1 Go)
const taille = (o) => (o >= 1073741824 ? `${(o / 1073741824).toFixed(2)} Go` : o >= 1048576 ? `${(o / 1048576).toFixed(1)} Mo`
  : o >= 1024 ? `${Math.round(o / 1024)} Ko` : `${o || 0} o`);
// Date ISO -> « 30/09/2026 14:05 »
const dateHeure = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");

// Petite jauge circulaire transparente (attente), comme ailleurs dans SAWALI
const Attente = () => (
  <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-emerald-300 border-t-transparent align-middle" />
);

// Couleurs de la jauge des collections (mêmes niveaux que la rubrique « Base Atlas », lot 79.9)
const COULEUR_NIVEAU = { ok: "#059669", attention: "#d97706", plein: "#dc2626" };

// Jauge circulaire des collections du cluster (avant ou après la libération)
function JaugeCollections({ jauge, titre }) {
  if (!jauge || jauge.total === undefined) {
    return <p className="text-xs text-slate-500">{titre} : {jauge?.erreur || "mesure indisponible"}</p>;
  }
  const rayon = 34;
  const circonference = 2 * Math.PI * rayon;
  const part = Math.min(1, jauge.limite ? jauge.total / jauge.limite : 0);
  return (
    <div className="flex items-center gap-3" data-testid="jauge-liberer-espace">
      <svg viewBox="0 0 90 90" className="h-20 w-20 shrink-0" role="img" aria-label={`${jauge.total} collections sur ${jauge.limite}`}>
        <circle cx="45" cy="45" r={rayon} fill="none" stroke="#e2e8f0" strokeWidth="10" />
        <circle cx="45" cy="45" r={rayon} fill="none" stroke={COULEUR_NIVEAU[jauge.niveau] || COULEUR_NIVEAU.ok} strokeWidth="10"
          strokeLinecap="round" strokeDasharray={`${circonference * part} ${circonference}`} transform="rotate(-90 45 45)" />
        <text x="45" y="49" textAnchor="middle" className="fill-slate-900" style={{ fontSize: 16, fontWeight: 700 }}>{jauge.total}</text>
      </svg>
      <div className="text-xs text-slate-600">
        <p className="font-semibold text-slate-800">{titre}</p>
        <p><b>{jauge.total}</b> collections sur <b>{jauge.limite}</b> ({jauge.pourcentage} %)</p>
        <p>encore <b>{jauge.restantes}</b> avant le blocage</p>
      </div>
    </div>
  );
}

// Un bloc du plan : tableau avec case à cocher en première cellule (la règle CSS globale colore la ligne
// sélectionnée en orange #f6a35b, police blanche, et la ligne survolée en bleu clair transparent).
// Les éléments protégés sont grisés, avec un cadenas et la raison : jamais cochables.
function BlocPlan({ titre, aide, bloc, cle, colonnes, choix, basculer, toutCocher, sansDefaut }) {
  if (!bloc) return null;
  const elements = bloc.elements || [];
  const supprimables = elements.filter((e) => e.classe !== "protege");
  return (
    <div className="space-y-2 rounded-xl border border-slate-200 p-3" data-testid={`bloc-${cle}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-semibold text-slate-800">{titre}</p>
        {supprimables.length > 0 && (
          <span className="flex gap-2 text-xs">
            {!sansDefaut && <button type="button" onClick={() => toutCocher(cle, "regle")} className="text-sky-700 hover:underline">Sélection par défaut</button>}
            <button type="button" onClick={() => toutCocher(cle, "aucun")} className="text-slate-600 hover:underline">Tout décocher</button>
          </span>
        )}
      </div>
      {aide && <p className="text-xs text-slate-500">{aide}</p>}
      {bloc.message && <p className="rounded bg-amber-50 px-2 py-1 text-xs text-amber-800">{bloc.message}</p>}
      {elements.length === 0 && !bloc.message && <p className="text-xs text-slate-500">Rien à libérer ici.</p>}
      {elements.length > 0 && (
        <div className="max-h-80 overflow-auto">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-white text-slate-500">
              <tr>
                <th className="w-8 px-2 py-1.5" />
                {colonnes.map((c) => <th key={c.cle} className={`px-2 py-1.5 ${c.droite ? "text-right" : ""}`}>{c.libelle}</th>)}
                <th className="px-2 py-1.5">Règle</th>
              </tr>
            </thead>
            <tbody>
              {elements.map((e) => {
                const id = e.id;
                const protege = e.classe === "protege";
                const coche = choix.includes(id);
                return (
                  <tr key={id} className={`border-t border-slate-100 ${protege ? "text-slate-400" : ""}`}
                    aria-selected={coche} title={protege ? `Protégé : ${e.raison}` : e.raison}>
                    <td className="px-2 py-1.5">
                      {protege
                        ? <span aria-label={`Protégé : ${e.raison}`}>🔒</span>
                        : <input type="checkbox" checked={coche} onChange={() => basculer(cle, id)} aria-label={`Choisir ${e.libelle}`} />}
                    </td>
                    {colonnes.map((c) => (
                      <td key={c.cle} className={`px-2 py-1.5 ${c.droite ? "text-right tabular-nums whitespace-nowrap" : ""} ${c.mono ? "font-mono" : ""}`}>
                        {c.rendu ? c.rendu(e) : e[c.cle]}
                      </td>
                    ))}
                    <td className="px-2 py-1.5">
                      {protege ? <span className="italic">protégé — {e.raison}</span>
                        : e.classe === "a_supprimer" ? <span className="text-red-700">à supprimer — {e.raison}</span>
                          : <span className="text-slate-600">{e.raison}</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {bloc.regle && <p className="text-[11px] text-slate-500">Règle appliquée : {bloc.regle}{bloc.bucket ? ` · bucket ${bloc.bucket}` : ""}</p>}
    </div>
  );
}

// Colonnes de chaque bloc
const COL_MIGRATION = [
  { cle: "libelle", libelle: "Sauvegarde", mono: true },
  { cle: "date", libelle: "Date", rendu: (e) => dateHeure(e.date) },
  { cle: "statut", libelle: "Statut", rendu: (e) => e.statut || "inconnu" },
  { cle: "objets", libelle: "Fichiers", droite: true, rendu: (e) => (e.objets || 0).toLocaleString("fr-FR") },
  { cle: "octets", libelle: "Taille", droite: true, rendu: (e) => taille(e.octets) },
];
const COL_QUOTIDIENNES = [
  { cle: "libelle", libelle: "Sauvegarde", mono: true },
  { cle: "date", libelle: "Date", rendu: (e) => dateHeure(e.date) },
  { cle: "octets", libelle: "Taille", droite: true, rendu: (e) => taille(e.octets) },
];
const COL_BASES = [
  { cle: "libelle", libelle: "Base", mono: true },
  { cle: "collections", libelle: "Collections", droite: true },
  { cle: "documents", libelle: "Documents", droite: true, rendu: (e) => (e.documents == null ? "—" : e.documents.toLocaleString("fr-FR")) },
];

// Met chaque élément au même format (id + libellé) quel que soit le bloc
const normaliser = (analyse) => ({
  migration: { ...analyse.migration, elements: (analyse.migration?.elements || []).map((e) => ({ ...e, id: e.prefixe, libelle: e.prefixe })) },
  quotidiennes: { ...analyse.quotidiennes, elements: (analyse.quotidiennes?.elements || []).map((e) => ({ ...e, id: e.cle, libelle: e.nom })) },
  atlas: {
    ...analyse.atlas,
    // Bases en service : affichées grisées, jamais cochables
    elements: [
      ...(analyse.atlas?.bases || []).map((b) => ({ ...b, id: b.nom, libelle: b.nom })),
      ...(analyse.atlas?.protegees || []).map((b) => ({ ...b, id: b.nom, libelle: b.nom, classe: "protege", documents: null })),
    ],
  },
});

// Sélection par défaut d'un bloc : les éléments que la règle de rétention supprimerait (jamais les bases Atlas)
const parDefaut = (bloc) => (bloc?.elements || []).filter((e) => e.coche && e.classe !== "protege").map((e) => e.id);

// ===========================================================================================================
// Lot 116 — Bloc « Collections les moins utilisées (base SAWALI) »
// Le cluster Atlas est limité à 500 collections. Ce bloc mesure chaque collection de la base de SAWALI
// (documents, taille, dernière activité, fonction qui l'utilise), puis, pour les collections cochées :
// sauvegarde dans R2 → désactivation de la fonction → suppression → registre. Restauration possible.
// ===========================================================================================================

// Libellé et couleur de l'état d'une collection
const ETATS_COLLECTION = {
  vide: { texte: "vide", classe: "text-emerald-700" },
  inactive: { texte: "inactive", classe: "text-amber-700" },
  active: { texte: "active", classe: "text-slate-700" },
};

function BlocCollections() {
  const [mesure, setMesure] = useState(null);       // réponse de GET /admin/collections-inutilisees/analyse
  const [choix, setChoix] = useState([]);           // noms des collections cochées
  const [jours, setJours] = useState(90);           // seuil « inactive » (jours sans activité)
  const [occupe, setOccupe] = useState("");         // "mesure" | "liberation" | "restauration:<nom>" | ""
  const [erreur, setErreur] = useState("");
  const [rapport, setRapport] = useState(null);     // rapport de la dernière libération
  const [archivees, setArchivees] = useState(null); // registre des collections archivées

  // Registre des collections archivées (relu après chaque libération ou restauration)
  const chargerArchivees = async () => {
    try {
      const r = await apiClient.get("/admin/collections-inutilisees/archivees");
      setArchivees(r.data.archivees || []);
    } catch (e) {
      setArchivees([]);
    }
  };

  // 1. Mesure (lecture seule) : toast « Patientez… » + jauge circulaire
  const mesurer = async () => {
    setOccupe("mesure"); setErreur(""); setRapport(null);
    const attente = toast.loading("Patientez… mesure des collections de la base SAWALI");
    try {
      const r = await apiClient.get("/admin/collections-inutilisees/analyse", { params: { jours } });
      setMesure(r.data);
      // Sélection par défaut : seulement les collections VIDES non protégées (cochées par le serveur)
      setChoix(r.data.collections.filter((c) => c.coche && !c.protegee).map((c) => c.nom));
      toast.success(`Mesure terminée : ${r.data.synthese.total} collection(s), ${r.data.synthese.proposees} proposée(s)`, { id: attente });
      chargerArchivees();
    } catch (e) {
      setErreur(e?.response?.data?.detail || "Mesure impossible");
      toast.error(e?.response?.data?.detail || "Mesure impossible", { id: attente });
    } finally { setOccupe(""); }
  };

  // Cocher / décocher une collection ; sélection par défaut / tout décocher
  const basculer = (nom) => setChoix((c) => (c.includes(nom) ? c.filter((x) => x !== nom) : [...c, nom]));
  const selectionDefaut = () => setChoix((mesure?.collections || []).filter((c) => c.coche && !c.protegee).map((c) => c.nom));

  // 2. Exécution : confirmation LIBERER, puis rapport final
  const liberer = async () => {
    const lignes = (mesure?.collections || []).filter((c) => choix.includes(c.nom));
    const pleines = lignes.filter((c) => c.documents > 0);
    const avert = pleines.length ? `\n⚠️ ${pleines.length} collection(s) NON vide(s) : ${pleines.map((c) => c.nom).join(", ")}` : "";
    const mot = window.prompt(`Sauvegarder dans R2, désactiver la fonction puis SUPPRIMER ${lignes.length} collection(s) ?${avert}`
      + "\nUne restauration reste possible depuis « Collections archivées ».\nTapez LIBERER pour confirmer.");
    if (!mot) return;
    setOccupe("liberation"); setErreur("");
    const attente = toast.loading("Patientez… sauvegarde puis suppression des collections");
    try {
      const r = await apiClient.post("/admin/collections-inutilisees/liberer", { collections: choix, confirmation: mot, jours });
      setRapport(r.data); setMesure(null); setChoix([]);
      if (r.data.erreurs) toast.warning(`${r.data.liberees} collection(s) libérée(s), ${r.data.erreurs} erreur(s)`, { id: attente });
      else toast.success(`${r.data.liberees} collection(s) libérée(s)`, { id: attente });
      chargerArchivees();
    } catch (e) {
      setErreur(e?.response?.data?.detail || "Libération impossible");
      toast.error(e?.response?.data?.detail || "Libération impossible", { id: attente });
    } finally { setOccupe(""); }
  };

  // 3. Restauration d'une collection archivée (documents + index depuis R2, fonction réactivée)
  const restaurer = async (nom) => {
    if (!window.confirm(`Restaurer la collection « ${nom} » depuis sa sauvegarde R2 et réactiver sa fonction ?`)) return;
    setOccupe(`restauration:${nom}`);
    const attente = toast.loading(`Patientez… restauration de ${nom}`);
    try {
      const r = await apiClient.post("/admin/collections-inutilisees/restaurer", { nom });
      toast.success(`${nom} restaurée : ${r.data.documents} document(s), ${r.data.index} index`, { id: attente });
      chargerArchivees();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Restauration impossible", { id: attente });
    } finally { setOccupe(""); }
  };

  const lignes = mesure?.collections || [];
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 p-3" data-testid="bloc-collections-inutilisees">
      {/* Titre, explication, seuil et bouton « Mesurer » */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-semibold text-slate-800">🗂️ Collections les moins utilisées (base SAWALI)</p>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <label className="text-slate-600">Inactive après
            <input type="number" min={1} max={3650} value={jours} onChange={(e) => setJours(Number(e.target.value) || 90)}
              className="mx-1 w-16 rounded border border-slate-300 px-1 py-0.5" /> jours</label>
          <button type="button" onClick={mesurer} disabled={!!occupe} data-testid="bouton-mesurer-collections"
            className="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-3 py-1.5 font-semibold text-white hover:bg-sky-700 disabled:opacity-60">
            {occupe === "mesure" && <Attente />} Mesurer
          </button>
          <button type="button" onClick={chargerArchivees} disabled={!!occupe}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-slate-700 hover:bg-slate-50">Collections archivées</button>
        </div>
      </div>
      <p className="text-xs text-slate-500">
        Chaque collection compte dans la limite de 500 du cluster. Les collections <b>vides</b> sont cochées d'office ;
        les <b>inactives</b> sont proposées sans être cochées ; les collections vitales (comptes, messages, paiements,
        contrats, sauvegardes, sécurité…) et celles dont la fonction est inconnue sont <b>protégées</b>. Chaque collection
        supprimée est d'abord <b>sauvegardée dans R2</b> et peut être restaurée ; elle n'est pas recréée au démarrage.
      </p>
      {erreur && <p className="text-sm text-red-700">{erreur}</p>}

      {/* Synthèse + jauge du cluster */}
      {mesure && (
        <div className="grid gap-3 sm:grid-cols-2">
          <JaugeCollections jauge={mesure.jauge} titre="Collections du cluster (avant)" />
          <div className="rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
            <p>Base <b>{mesure.base}</b> : <b>{mesure.synthese.total}</b> collection(s)</p>
            <p>Proposées : <b>{mesure.synthese.proposees}</b> · protégées : {mesure.synthese.protegees}</p>
            <p>Vides : {mesure.synthese.vides} · inactives (&gt; {mesure.jours} j) : {mesure.synthese.inactives}</p>
            <p>Sélection par défaut : <b>{mesure.synthese.liberables_par_defaut}</b> collection(s) libérable(s)</p>
          </div>
        </div>
      )}

      {/* Tableau trié du moins utilisé au plus utilisé (case à cocher en 1re cellule : règle CSS des tableaux) */}
      {mesure && (
        <>
          <div className="flex justify-end gap-2 text-xs">
            <button type="button" onClick={selectionDefaut} className="text-sky-700 hover:underline">Sélection par défaut</button>
            <button type="button" onClick={() => setChoix([])} className="text-slate-600 hover:underline">Tout décocher</button>
          </div>
          <div className="max-h-96 overflow-auto">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-white text-slate-500">
                <tr>
                  <th className="w-8 px-2 py-1.5" />
                  <th className="px-2 py-1.5">Collection</th>
                  <th className="px-2 py-1.5">Fonction</th>
                  <th className="px-2 py-1.5 text-right">Documents</th>
                  <th className="px-2 py-1.5 text-right">Taille</th>
                  <th className="px-2 py-1.5">Dernière activité</th>
                  <th className="px-2 py-1.5">État</th>
                </tr>
              </thead>
              <tbody>
                {lignes.map((c) => {
                  const coche = choix.includes(c.nom);
                  const etat = ETATS_COLLECTION[c.etat] || ETATS_COLLECTION.active;
                  return (
                    <tr key={c.nom} className={`border-t border-slate-100 ${c.protegee ? "text-slate-400" : ""}`}
                      aria-selected={coche} title={c.protegee ? `Protégée : ${c.raison}` : c.action_fonction?.texte}>
                      <td className="px-2 py-1.5">
                        {c.protegee
                          ? <span aria-label={`Protégée : ${c.raison}`}>🔒</span>
                          : <input type="checkbox" checked={coche} onChange={() => basculer(c.nom)} aria-label={`Choisir ${c.nom}`} />}
                      </td>
                      <td className="px-2 py-1.5 font-mono">{c.nom}</td>
                      <td className="px-2 py-1.5">{c.fonction}</td>
                      <td className="px-2 py-1.5 text-right tabular-nums">{c.documents == null ? "—" : c.documents.toLocaleString("fr-FR")}</td>
                      <td className="whitespace-nowrap px-2 py-1.5 text-right tabular-nums">{c.octets == null ? "—" : taille(c.octets)}</td>
                      <td className="px-2 py-1.5">{dateHeure(c.derniere_activite)}</td>
                      <td className="px-2 py-1.5">
                        {c.protegee
                          ? <span className="italic">protégée — {c.raison}</span>
                          : <span className={etat.classe}>{etat.texte}{c.action_fonction?.desactiver ? ` · ${c.action_fonction.texte}` : ""}</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {/* Total en direct + bouton d'exécution */}
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-emerald-300 bg-emerald-50 p-3">
            <p className="text-sm text-emerald-900" data-testid="total-collections-liberees">
              <b>{choix.length}</b> collection(s) libérée(s) sur le cluster
            </p>
            <button type="button" onClick={liberer} disabled={!!occupe || choix.length === 0}
              className="inline-flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50">
              {occupe === "liberation" && <Attente />} Sauvegarder, désactiver et supprimer
            </button>
          </div>
        </>
      )}

      {/* Rapport final de la libération */}
      {rapport && (
        <div className="space-y-2 rounded-lg border border-slate-200 p-3" data-testid="rapport-collections">
          <p className="font-semibold text-slate-800">
            Rapport : {rapport.liberees} collection(s) libérée(s)
            {rapport.erreurs > 0 && <span className="text-red-700"> · {rapport.erreurs} erreur(s)</span>}
          </p>
          <JaugeCollections jauge={rapport.jauge_apres} titre="Collections du cluster (après)" />
          <div className="max-h-64 overflow-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-slate-500"><tr>
                <th className="px-2 py-1">Collection</th><th className="px-2 py-1">Fonction</th>
                <th className="px-2 py-1 text-right">Documents</th><th className="px-2 py-1">Résultat</th>
              </tr></thead>
              <tbody>
                {rapport.elements.map((e) => (
                  <tr key={e.nom} className="border-t border-slate-100">
                    <td className="px-2 py-1 font-mono">{e.nom}</td>
                    <td className="px-2 py-1">{e.fonction}</td>
                    <td className="px-2 py-1 text-right tabular-nums">{e.documents}</td>
                    <td className={`px-2 py-1 ${e.ok ? "text-emerald-700" : "font-semibold text-red-700"}`}>
                      {e.ok ? `✅ ${e.etapes.join(" → ")}` : `❌ ${e.erreur || "erreur"}`}
                      {e.avertissement && <span className="text-amber-700"> · {e.avertissement}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[11px] text-slate-500">Sauvegardes déposées dans R2 : {rapport.dossier_r2}/</p>
        </div>
      )}

      {/* Registre des collections archivées, avec « Restaurer » */}
      {archivees && (
        <div className="space-y-2 rounded-lg border border-slate-200 p-3" data-testid="collections-archivees">
          <p className="font-semibold text-slate-800">📦 Collections archivées ({archivees.length})</p>
          {archivees.length === 0 ? <p className="text-xs text-slate-500">Aucune collection archivée.</p> : (
            <div className="max-h-64 overflow-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-slate-500"><tr>
                  <th className="px-2 py-1">Collection</th><th className="px-2 py-1">Fonction</th>
                  <th className="px-2 py-1 text-right">Documents</th><th className="px-2 py-1">Archivée le</th>
                  <th className="px-2 py-1">Par</th><th className="px-2 py-1" />
                </tr></thead>
                <tbody>
                  {archivees.map((a) => (
                    <tr key={a.nom} className="border-t border-slate-100">
                      <td className="px-2 py-1 font-mono">{a.nom}{a.recreee && <span className="ml-1 text-amber-700">(recréée depuis)</span>}</td>
                      <td className="px-2 py-1">{a.fonction}{a.fonction_desactivee && <span className="text-slate-500"> · désactivée</span>}</td>
                      <td className="px-2 py-1 text-right tabular-nums">{a.documents}</td>
                      <td className="px-2 py-1">{dateHeure(a.archivee_le)}</td>
                      <td className="px-2 py-1">{a.par}</td>
                      <td className="px-2 py-1 text-right">
                        <button type="button" onClick={() => restaurer(a.nom)} disabled={!!occupe}
                          className="inline-flex items-center gap-1 rounded border border-sky-300 px-2 py-0.5 text-sky-700 hover:bg-sky-50 disabled:opacity-50">
                          {occupe === `restauration:${a.nom}` && <Attente />} Restaurer
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function LibererEspaceSection() {
  const [analyse, setAnalyse] = useState(null);     // réponse de l'analyse (jauge, synthèse…)
  const [plan, setPlan] = useState(null);           // blocs normalisés
  const [choix, setChoix] = useState({ migration: [], quotidiennes: [], atlas: [] });
  const [occupe, setOccupe] = useState("");         // "analyse" | "execution" | ""
  const [erreur, setErreur] = useState("");
  const [rapport, setRapport] = useState(null);     // rapport de la dernière exécution

  // 1. Analyse (lecture seule) : toast « Patientez… » + jauge circulaire pendant le parcours
  const analyser = async () => {
    setOccupe("analyse"); setErreur(""); setRapport(null);
    const attente = toast.loading("Patientez… analyse de l'espace (R2 et cluster Atlas)");
    try {
      const r = await apiClient.get("/admin/liberer-espace/analyse");
      const p = normaliser(r.data);
      setAnalyse(r.data); setPlan(p);
      setChoix({ migration: parDefaut(p.migration), quotidiennes: parDefaut(p.quotidiennes), atlas: [] });
      toast.success("Analyse terminée : vérifiez le plan puis cliquez sur « Libérer maintenant »", { id: attente });
    } catch (e) {
      setErreur(e?.response?.data?.detail || "Analyse impossible");
      toast.error(e?.response?.data?.detail || "Analyse impossible", { id: attente });
    } finally { setOccupe(""); }
  };

  // Cocher / décocher un élément ; « Sélection par défaut » / « Tout décocher » pour un bloc
  const basculer = (bloc, id) => setChoix((c) => ({ ...c, [bloc]: c[bloc].includes(id) ? c[bloc].filter((x) => x !== id) : [...c[bloc], id] }));
  const toutCocher = (bloc, mode) => setChoix((c) => ({ ...c, [bloc]: mode === "regle" ? parDefaut(plan[bloc]) : [] }));

  // Total de la sélection, recalculé en direct à chaque case cochée
  const total = useMemo(() => {
    if (!plan) return { octets: 0, collections: 0, nombre: 0 };
    const somme = (bloc, champ) => plan[bloc].elements.filter((e) => choix[bloc].includes(e.id)).reduce((t, e) => t + (e[champ] || 0), 0);
    return {
      octets: somme("migration", "octets") + somme("quotidiennes", "octets"),
      collections: somme("atlas", "collections"),
      nombre: choix.migration.length + choix.quotidiennes.length + choix.atlas.length,
    };
  }, [plan, choix]);

  // 2. Exécution : confirmation LIBERER (comme le lot 107), puis rapport final
  const liberer = async () => {
    const bases = choix.atlas.length ? `\n⚠️ ${choix.atlas.length} BASE(S) ATLAS supprimée(s) : ${choix.atlas.join(", ")}` : "";
    const mot = window.prompt(`Supprimer DÉFINITIVEMENT ${total.nombre} élément(s) : ${taille(total.octets)} dans R2`
      + ` et ${total.collections} collection(s) Atlas ?${bases}\nTapez LIBERER pour confirmer.`);
    if (!mot) return;
    setOccupe("execution"); setErreur("");
    const attente = toast.loading("Patientez… libération de l'espace en cours");
    try {
      const r = await apiClient.post("/admin/liberer-espace/executer", {
        r2_prefixes: choix.migration, quotidiennes: choix.quotidiennes, bases: choix.atlas, confirmation: mot,
      });
      setRapport(r.data); setPlan(null);
      if (r.data.erreurs) toast.warning(`Libération terminée avec ${r.data.erreurs} erreur(s)`, { id: attente });
      else toast.success(`Espace libéré : ${taille(r.data.octets_liberes)} · ${r.data.collections_liberees} collection(s)`, { id: attente });
    } catch (e) {
      setErreur(e?.response?.data?.detail || "Libération impossible");
      toast.error(e?.response?.data?.detail || "Libération impossible", { id: attente });
    } finally { setOccupe(""); }
  };

  return (
    <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-liberer-espace">
      {/* Explication + le gros bouton unique */}
      <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center">
        <p className="flex-1 text-sm text-slate-700">
          Un seul bouton pour faire de la place : il parcourt les <b>sauvegardes Cloudflare R2</b> (migration et quotidiennes)
          et les <b>bases du cluster Atlas</b>, puis propose un plan. Ce que les règles de rétention suppriment est
          <b> pré-coché</b> ; les sauvegardes protégées (en cours, dernière réussie, plus récente) ne peuvent pas l'être ;
          les bases Atlas ne sont <b>jamais</b> cochées d'office. Rien n'est supprimé avant « Libérer maintenant ».
        </p>
        <button type="button" onClick={analyser} disabled={!!occupe} data-testid="bouton-liberer-espace"
          className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-6 py-3 text-base font-bold text-white shadow hover:bg-emerald-700 disabled:opacity-60">
          {occupe === "analyse" ? <Attente /> : "🧹"} Libérer l'Espace
        </button>
      </div>
      {analyse?.derniere_execution && !plan && !rapport && (
        <p className="text-xs text-slate-500">
          Dernière libération : {dateHeure(analyse.derniere_execution.le)} par {analyse.derniere_execution.par} ·{" "}
          {taille(analyse.derniere_execution.octets_liberes)} · {analyse.derniere_execution.collections_liberees} collection(s)
        </p>
      )}
      {erreur && <p className="text-sm text-red-700">{erreur}</p>}

      {/* Plan de nettoyage */}
      {plan && (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <JaugeCollections jauge={analyse.jauge} titre="Collections du cluster (avant)" />
            <div className="rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
              <p>Occupé dans R2 : <b>{taille(analyse.synthese.octets_r2)}</b></p>
              <p>Sélection par défaut : <b>{taille(analyse.synthese.octets_liberes)}</b> ({analyse.synthese.elements_coches} élément(s))</p>
              <p>Bases Atlas libérables (à vérifier) : <b>{analyse.synthese.collections_liberables}</b> collection(s)</p>
            </div>
          </div>
          <BlocPlan titre="☁️ Sauvegardes R2 de migration" cle="migration" bloc={plan.migration} colonnes={COL_MIGRATION}
            choix={choix.migration} basculer={basculer} toutCocher={toutCocher}
            aide="Pré-cochées : celles que la purge programmée supprimerait avec le réglage enregistré." />
          <BlocPlan titre="🗓️ Sauvegardes quotidiennes" cle="quotidiennes" bloc={plan.quotidiennes} colonnes={COL_QUOTIDIENNES}
            choix={choix.quotidiennes} basculer={basculer} toutCocher={toutCocher}
            aide="Pré-cochées : celles au-delà de la rotation (7 quotidiennes, 4 hebdomadaires, 12 mensuelles)." />
          <BlocPlan titre="🗄️ Bases du cluster Atlas" cle="atlas" bloc={plan.atlas} colonnes={COL_BASES}
            choix={choix.atlas} basculer={basculer} toutCocher={toutCocher} sansDefaut
            aide="Copies, essais, restes de migration : jamais cochées d'office. Cochez une base seulement si vous êtes sûr qu'elle ne sert plus (suppression définitive). Les bases en service sont protégées." />

          {/* Total en direct + bouton d'exécution */}
          <div className="sticky bottom-2 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-emerald-300 bg-emerald-50 p-3">
            <p className="text-sm text-emerald-900" data-testid="total-liberer-espace">
              Espace libéré : <b>{taille(total.octets)}</b> · <b>{total.collections}</b> collection(s)
              <span className="text-emerald-700"> ({total.nombre} élément(s) sélectionné(s))</span>
            </p>
            <button type="button" onClick={liberer} disabled={!!occupe || total.nombre === 0}
              className="inline-flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50">
              {occupe === "execution" && <Attente />} Libérer maintenant
            </button>
          </div>
        </>
      )}

      {/* Rapport final */}
      {rapport && (
        <div className="space-y-3 rounded-xl border border-slate-200 p-3" data-testid="rapport-liberer-espace">
          <p className="font-semibold text-slate-800">
            Rapport : {taille(rapport.octets_liberes)} libéré(s) dans R2 · {rapport.collections_liberees} collection(s) Atlas libérée(s)
            {rapport.erreurs > 0 && <span className="text-red-700"> · {rapport.erreurs} erreur(s)</span>}
          </p>
          <JaugeCollections jauge={rapport.jauge_apres} titre="Collections du cluster (après)" />
          <div className="max-h-72 overflow-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-slate-500"><tr>
                <th className="px-2 py-1">Élément</th><th className="px-2 py-1">Type</th><th className="px-2 py-1 text-right">Libéré</th><th className="px-2 py-1">Résultat</th>
              </tr></thead>
              <tbody>
                {rapport.elements.map((e) => (
                  <tr key={`${e.type}-${e.libelle}`} className="border-t border-slate-100">
                    <td className="px-2 py-1 font-mono">{e.libelle}</td>
                    <td className="px-2 py-1">{e.type === "base" ? "Base Atlas" : e.type === "quotidienne" ? "Sauvegarde quotidienne" : "Sauvegarde de migration"}</td>
                    <td className="px-2 py-1 text-right tabular-nums">{e.type === "base" ? `${e.collections || 0} coll.` : taille(e.octets || 0)}</td>
                    <td className={`px-2 py-1 ${e.ok ? "text-emerald-700" : "text-red-700 font-semibold"}`}>{e.ok ? "✅ supprimé" : `❌ ${e.erreur || "erreur"}`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[11px] text-slate-500">
            Rapport {rapport.rapport?.envoye ? "envoyé à l'administrateur (Liluvine / e-mail)" : "non envoyé (voir le journal du serveur)"}.
            Les sauvegardes supprimées restent dans l'historique avec le badge « purgée ».
          </p>
        </div>
      )}

      {/* Lot 116 — 4e bloc : collections les moins utilisées de la base de SAWALI (indépendant du plan ci-dessus) */}
      <BlocCollections />
    </div>
  );
}
