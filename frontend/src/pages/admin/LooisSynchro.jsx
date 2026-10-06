// LooisSynchro.jsx — Lot 68 : page « Plateformes → Loois → Synchro » (administrateur).
//
// Demande du propriétaire (06/10/2026) : « Sur SAWALI / Plateforme / Loois / Synchro j'édite la liste des tables que
// je veux remonter. Pour un client il remonte les données du fichier en JSON pour remplir une base MongoDB de même
// structure que le fichier HFSQL. »
//
// La page comporte trois parties :
//   1. LISTE DES TABLES à remonter, par application (onglets e-Kol / Aizenta / Biolog) : liste COMMUNE à tous les
//      clients (toutes les bases ont la même structure, schéma de référence publié sur GitHub par Loois), avec
//      possibilité de SURCHARGE pour un client. Cases à cocher + recherche ; pour chaque table cochée : clé (détectée
//      d'après le schéma, modifiable) et colonnes à ne pas remonter ;
//   2. CLIENTS : pour chaque client vu par Loois, poste désigné, et pour chaque table : documents dans MongoDB,
//      dernière synchro, lignes en attente sur le poste, dernière erreur ; boutons « Voir » et « Resynchroniser tout » ;
//   3. DONNÉES (lecture seule) : grille paginée des documents d'une table, recherche et export CSV.
// Lot 68.1 : onglet « Clés clients » (une clé par client, voir LooisClesClients.jsx) à côté de l'onglet des tables.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { RefreshCw } from "lucide-react";
import { apiClient } from "@/lib/api";
import LooisClesClients from "./LooisClesClients";

const BASE = "/admin/loois-synchro";
const APPLICATIONS = [["eKol", "e-Kol"], ["Aizenta", "Aizenta"], ["Biolog", "Biolog"]];
const COMMUNE = "*";   // code de la liste commune à tous les clients

// Jauge circulaire transparente (attente), comme sur le reste de SAWALI
const Jauge = () => (
  <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-sky-300 border-t-transparent align-middle" />
);

// Date ISO → « JJ/MM/AAAA HH:MM » (heure de Ouagadougou = UTC)
const dateHeure = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("fr-FR", { timeZone: "Africa/Ouagadougou", dateStyle: "short", timeStyle: "short" });
};

// Valeur d'une cellule de la grille des données (dates ISO raccourcies, booléens en Oui/Non)
const cellule = (v) => {
  if (v === null || v === undefined) return "";
  if (typeof v === "boolean") return v ? "Oui" : "Non";
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T00:00:00/.test(v)) return v.slice(0, 10).split("-").reverse().join("/");
  return String(v);
};

// Liste « a, b » ↔ tableau
const versListe = (texte) => (texte || "").split(",").map((s) => s.trim()).filter(Boolean);

export default function LooisSynchro() {
  const [onglet, setOnglet] = useState("tables");       // lot 68.1 : « tables » (synchro) ou « cles » (clés clients)
  const [application, setApplication] = useState("eKol");
  const [catalogue, setCatalogue] = useState(null);     // schéma de référence (tables, clé détectée)
  const [vue, setVue] = useState(null);                 // configuration commune + clients
  const [cible, setCible] = useState(COMMUNE);          // liste éditée : commune ou code d'un client
  const [nouveauClient, setNouveauClient] = useState("");
  const [brouillon, setBrouillon] = useState(null);     // {actif, intervalle, tables: {nom: {cle, ignorees}}}
  const [recherche, setRecherche] = useState("");
  const [seulementCochees, setSeulementCochees] = useState(false);
  const [occupe, setOccupe] = useState(false);
  const [selection, setSelection] = useState(null);     // {site, table} affichée dans la grille des données
  const [ligneClient, setLigneClient] = useState(null); // ligne surlignée (orange) dans le tableau des clients

  // Lecture du schéma de référence et de la vue d'ensemble de l'application
  const charger = useCallback(async (visible = false) => {
    const t = visible ? toast.loading("Patientez…") : null;
    setOccupe(true);
    try {
      const [cat, v] = await Promise.all([
        apiClient.get(`${BASE}/catalogue`, { params: { application } }),
        apiClient.get(`${BASE}/vue`, { params: { application } }),
      ]);
      setCatalogue(cat.data); setVue(v.data);
      if (t) toast.dismiss(t);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Synchro Loois indisponible", t ? { id: t } : undefined);
    } finally {
      setOccupe(false);
    }
  }, [application]);

  useEffect(() => { setCible(COMMUNE); setSelection(null); charger(true); }, [charger]);

  // Configuration affichée pour la cible choisie (surcharge du client, sinon liste commune)
  const configCible = useMemo(() => {
    if (!vue) return null;
    if (cible === COMMUNE) return vue.defaut;
    const client = vue.clients.find((c) => c.site === cible);
    return client?.surcharge || { ...vue.defaut, origine: "application" };
  }, [vue, cible]);

  // Brouillon modifiable reconstruit à chaque changement de cible
  useEffect(() => {
    if (!configCible) return;
    const tables = {};
    (configCible.tables || []).forEach((t) => {
      tables[t.nom] = { cle: (t.cle || []).join(", "), ignorees: (t.colonnes_ignorees || []).join(", ") };
    });
    setBrouillon({ actif: configCible.actif !== false, intervalle: configCible.intervalle_sondage_minutes || 5, tables });
  }, [configCible]);

  // Tables du catalogue filtrées (recherche sans accents, « seulement cochées »)
  const tablesAffichees = useMemo(() => {
    const sansAccents = (s) => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
    const cle = sansAccents(recherche.trim());
    return (catalogue?.tables || []).filter((t) =>
      (!seulementCochees || brouillon?.tables?.[t.nom]) && (!cle || sansAccents(t.nom).includes(cle)));
  }, [catalogue, recherche, seulementCochees, brouillon]);

  // Coche / décoche une table
  const basculer = (nom) => setBrouillon((b) => {
    const tables = { ...b.tables };
    if (tables[nom]) delete tables[nom]; else tables[nom] = { cle: "", ignorees: "" };
    return { ...b, tables };
  });

  // Enregistrement de la liste (commune ou du client)
  const enregistrer = async () => {
    const t = toast.loading("Patientez… enregistrement");
    try {
      await apiClient.put(`${BASE}/config`, {
        application, site: cible, actif: brouillon.actif, intervalle_sondage_minutes: Number(brouillon.intervalle) || 5,
        tables: Object.entries(brouillon.tables).map(([nom, v]) => ({ nom, cle: versListe(v.cle), colonnes_ignorees: versListe(v.ignorees) })),
      });
      toast.success(cible === COMMUNE ? "Liste commune enregistrée" : `Liste du client ${cible} enregistrée`, { id: t });
      charger(false);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Enregistrement impossible", { id: t });
    }
  };

  // Retrait de la surcharge d'un client (ou retour à la liste intégrée pour la liste commune)
  const retirer = async () => {
    const message = cible === COMMUNE ? "Revenir à la liste intégrée (e-Kol : Paiements, ElèveEdu) ?" : `Le client ${cible} reprendra la liste commune. Continuer ?`;
    if (!window.confirm(message)) return;
    const t = toast.loading("Patientez…");
    try {
      await apiClient.delete(`${BASE}/config`, { params: { application, site: cible } });
      toast.success("Fait", { id: t });
      charger(false);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Action impossible", { id: t });
    }
  };

  // « Resynchroniser tout » : Loois renverra la table (ou toutes les tables du client) au prochain passage
  const resynchroniser = async (site, table) => {
    if (!window.confirm(`Renvoyer ${table ? `la table ${table}` : "toutes les tables"} du client ${site} en entier ?`)) return;
    const t = toast.loading("Patientez…");
    try {
      await apiClient.post(`${BASE}/resynchroniser`, { application, site, table });
      toast.success("Demande enregistrée : Loois renverra les données dans les prochaines minutes", { id: t });
      charger(false);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Action impossible", { id: t });
    }
  };

  const nbCochees = brouillon ? Object.keys(brouillon.tables).length : 0;
  const clients = vue?.clients || [];

  return (
    <div className="space-y-4" data-testid="loois-synchro">
      {/* En-tête : titre, onglets d'application, actualisation */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-display font-bold">🔄 Plateformes → Loois → Synchro</h1>
          <p className="text-xs text-slate-500">
            Tables HFSQL remontées par Loois dans MongoDB (une collection par client et par table, mêmes noms de colonnes).
            Schéma de référence : {catalogue ? `${catalogue.source || "—"}${catalogue.genere_le ? ` · généré le ${catalogue.genere_le}` : ""}` : "…"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {/* Lot 68.1 : onglets de la page (tables / clés clients) */}
          {[["tables", "📋 Tables et données"], ["cles", "🔑 Clés clients"]].map(([code, libelle]) => (
            <button key={code} type="button" onClick={() => setOnglet(code)}
              className={`rounded-lg px-3 py-1.5 text-sm font-semibold ${onglet === code ? "bg-slate-800 text-white" : "border border-slate-300 bg-white hover:bg-slate-50"}`}
              data-testid={`onglet-page-${code}`}>
              {libelle}
            </button>
          ))}
          {onglet === "tables" && <span className="mx-1 h-6 w-px bg-slate-300" />}
          {onglet === "tables" && APPLICATIONS.map(([code, libelle]) => (
            <button key={code} type="button" onClick={() => setApplication(code)}
              className={`rounded-lg px-3 py-1.5 text-sm ${application === code ? "bg-sky-600 text-white" : "border border-slate-300 bg-white hover:bg-slate-50"}`}
              data-testid={`onglet-${code}`}>
              {libelle}
            </button>
          ))}
          {onglet === "tables" && (
            <button type="button" onClick={() => charger(true)} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50">
              <RefreshCw className={`h-4 w-4 ${occupe ? "animate-spin" : ""}`} /> Actualiser
            </button>
          )}
        </div>
      </div>

      {/* Lot 68.1 : onglet « Clés clients » */}
      {onglet === "cles" && <LooisClesClients />}

      {onglet === "tables" && <>
      {!vue && <p className="text-sm text-slate-500"><Jauge /> Patientez…</p>}

      {/* 1. Liste des tables à remonter */}
      {vue && brouillon && (
        <section className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200" data-testid="liste-tables">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="space-y-1">
              <h2 className="text-lg font-semibold">1. Tables à remonter</h2>
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <label htmlFor="cible">Liste de :</label>
                <select id="cible" value={cible} onChange={(e) => setCible(e.target.value)} className="rounded border border-slate-300 px-2 py-1">
                  <option value={COMMUNE}>Tous les clients (liste commune)</option>
                  {clients.map((c) => <option key={c.site} value={c.site}>{c.site}{c.surcharge ? " (liste propre)" : ""}</option>)}
                </select>
                <input value={nouveauClient} onChange={(e) => setNouveauClient(e.target.value)} placeholder="Autre code client…"
                  className="w-40 rounded border border-slate-300 px-2 py-1" />
                <button type="button" disabled={!nouveauClient.trim()} onClick={() => { setCible(nouveauClient.trim().toUpperCase()); setNouveauClient(""); }}
                  className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-50 disabled:opacity-50">Choisir</button>
              </div>
              <p className="text-xs text-slate-500">
                {cible === COMMUNE
                  ? `Liste appliquée à tous les clients ${vue.libelle} qui n'ont pas de liste propre${vue.defaut?.origine === "integree" ? " (liste intégrée, jamais modifiée)" : ""}.`
                  : `Liste propre au client ${cible} (remplace la liste commune pour lui seul).`}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <label className="inline-flex items-center gap-1.5">
                <input type="checkbox" checked={brouillon.actif} onChange={(e) => setBrouillon({ ...brouillon, actif: e.target.checked })} /> Synchro active
              </label>
              <label className="inline-flex items-center gap-1.5" title="Vérification des tables quand Loois ne voit pas les fichiers .fic (HFSQL Client/Serveur)">
                Sondage toutes les
                <input type="number" min={1} max={120} value={brouillon.intervalle} onChange={(e) => setBrouillon({ ...brouillon, intervalle: e.target.value })}
                  className="w-16 rounded border border-slate-300 px-2 py-1" /> min
              </label>
              <button type="button" onClick={enregistrer} className="rounded-lg bg-sky-600 px-3 py-1.5 text-white hover:bg-sky-700" data-testid="enregistrer-liste">
                💾 Enregistrer ({nbCochees} table{nbCochees > 1 ? "s" : ""})
              </button>
              <button type="button" onClick={retirer} className="rounded-lg border border-slate-300 px-3 py-1.5 hover:bg-slate-50">
                {cible === COMMUNE ? "↺ Liste intégrée" : "↺ Reprendre la liste commune"}
              </button>
            </div>
          </div>

          {/* Recherche dans le catalogue */}
          <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
            <input value={recherche} onChange={(e) => setRecherche(e.target.value)} placeholder="Rechercher une table…" className="w-64 rounded border border-slate-300 px-2 py-1" />
            <label className="inline-flex items-center gap-1.5">
              <input type="checkbox" checked={seulementCochees} onChange={(e) => setSeulementCochees(e.target.checked)} /> Seulement les tables cochées
            </label>
            <span className="text-xs text-slate-500">{tablesAffichees.length} / {catalogue?.tables?.length || 0} table(s) du schéma de référence</span>
          </div>

          {/* Liste à cocher : la case de la 1re cellule cochée = ligne sélectionnée (orange, règle des tableaux) */}
          <div className="mt-2 max-h-96 overflow-auto rounded ring-1 ring-slate-200">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-slate-50 text-left text-xs text-slate-500">
                <tr><th className="w-10 p-2"></th><th className="p-2">Table</th><th className="p-2">Colonnes</th><th className="p-2">Clé (détectée si vide)</th><th className="p-2">Colonnes à ne pas remonter</th></tr>
              </thead>
              <tbody>
                {tablesAffichees.map((t) => {
                  const choix = brouillon.tables[t.nom];
                  return (
                    <tr key={t.nom} className="border-t border-slate-100">
                      <td className="p-2"><input type="checkbox" checked={!!choix} onChange={() => basculer(t.nom)} aria-label={`Remonter ${t.nom}`} /></td>
                      <td className="p-2 font-medium">{t.nom}</td>
                      <td className="p-2">{t.nb_colonnes || "?"}{t.binaires?.length ? ` · ${t.binaires.length} binaire(s) jamais remontée(s)` : ""}</td>
                      <td className="p-2">
                        {choix ? (
                          <input value={choix.cle} placeholder={t.cle_detectee?.join(", ") || "empreinte de la ligne"}
                            onChange={(e) => setBrouillon((b) => ({ ...b, tables: { ...b.tables, [t.nom]: { ...choix, cle: e.target.value } } }))}
                            className="w-48 rounded border border-slate-300 px-2 py-0.5 text-slate-800" />
                        ) : <span>{t.cle_detectee?.join(", ") || "—"}</span>}
                      </td>
                      <td className="p-2">
                        {choix && (
                          <input value={choix.ignorees} placeholder="ex. Photo, Observations"
                            onChange={(e) => setBrouillon((b) => ({ ...b, tables: { ...b.tables, [t.nom]: { ...choix, ignorees: e.target.value } } }))}
                            className="w-56 rounded border border-slate-300 px-2 py-0.5 text-slate-800" />
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* 2. Clients et état des tables */}
      {vue && (
        <section className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200" data-testid="clients-synchro">
          <h2 className="text-lg font-semibold">2. Clients {vue.libelle}</h2>
          <p className="text-xs text-slate-500">
            Un client apparaît dès que Loois (icône de la zone de notification, clé client Loois saisie — onglet « Clés clients ») a demandé sa liste.
            Un seul poste synchronise un client ; un autre prend le relais après {vue.poste_bail_minutes} min de silence.
          </p>
          {clients.length === 0 ? (
            <p className="mt-2 text-sm text-slate-500">Aucun client pour l'instant.</p>
          ) : (
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left text-xs text-slate-500">
                  <tr>
                    <th className="p-2">Client</th><th className="p-2">Table</th><th className="p-2">Documents</th><th className="p-2">Dernière synchro</th>
                    <th className="p-2">En attente</th><th className="p-2">Détection</th><th className="p-2">Dernière erreur</th><th className="p-2">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {clients.flatMap((c) => (c.tables.length ? c.tables : [{ table: "—", vide: true }]).map((t, i) => {
                    const cleLigne = `${c.site}|${t.table}`;
                    return (
                      <tr key={cleLigne} className={`border-t border-slate-100 ${ligneClient === cleLigne ? "ligne-selectionnee" : ""}`} onClick={() => setLigneClient(cleLigne)}>
                        <td className="p-2 align-top">
                          {i === 0 && (
                            <div>
                              <strong>{c.site}</strong>
                              <div className="text-xs text-slate-500">
                                {c.origine === "client" ? "liste propre" : "liste commune"} · {c.actif ? "active" : "désactivée"}
                                {c.poste && ` · poste ${c.poste.machine} (vu ${dateHeure(c.poste.vu_le)})`}
                              </div>
                            </div>
                          )}
                        </td>
                        <td className="p-2">{t.table}{t.configuree === false && <span className="ml-1 text-xs text-amber-600">(retirée de la liste)</span>}</td>
                        <td className="p-2">{t.nb_documents ?? "—"}{t.lignes_source ? <span className="text-xs text-slate-500"> / {t.lignes_source} sur le poste</span> : null}</td>
                        <td className="p-2">{dateHeure(t.derniere_synchro)}</td>
                        <td className="p-2">{t.en_attente ?? "—"}</td>
                        <td className="p-2 text-xs">{t.mode_detection === "fichiers" ? "fichiers .fic" : t.mode_detection === "sondage" ? "sondage" : "—"}</td>
                        <td className="p-2 text-xs text-rose-700">{t.erreur_poste || t.derniere_erreur || ""}</td>
                        <td className="p-2 whitespace-nowrap">
                          {!t.vide && (
                            <>
                              <button type="button" onClick={(e) => { e.stopPropagation(); setSelection({ site: c.site, table: t.table }); }}
                                className="mr-1 rounded border border-slate-300 bg-white px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-50">Voir</button>
                              <button type="button" onClick={(e) => { e.stopPropagation(); resynchroniser(c.site, t.table); }}
                                className="rounded border border-slate-300 bg-white px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-50">Resynchroniser tout</button>
                            </>
                          )}
                        </td>
                      </tr>
                    );
                  }))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {/* 3. Données d'une table (lecture seule) */}
      {selection && <GrilleDonnees application={application} site={selection.site} table={selection.table} onFermer={() => setSelection(null)} />}
      </>}
    </div>
  );
}

// Grille des documents d'une table d'un client : pagination, recherche, export CSV (lecture seule)
function GrilleDonnees({ application, site, table, onFermer }) {
  const [page, setPage] = useState(1);
  const [recherche, setRecherche] = useState("");
  const [appliquee, setAppliquee] = useState("");      // recherche réellement envoyée (bouton / Entrée)
  const [donnees, setDonnees] = useState(null);
  const [chargement, setChargement] = useState(false);
  const [ligne, setLigne] = useState(null);            // ligne sélectionnée (orange)

  // Lecture d'une page (avec « Patientez… »)
  const lire = useCallback(async () => {
    const t = toast.loading("Patientez…");
    setChargement(true);
    try {
      const r = await apiClient.get(`${BASE}/donnees`, { params: { application, site, table, page, par_page: 50, recherche: appliquee } });
      setDonnees(r.data);
      toast.dismiss(t);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Données indisponibles", { id: t });
    } finally {
      setChargement(false);
    }
  }, [application, site, table, page, appliquee]);

  useEffect(() => { lire(); }, [lire]);
  useEffect(() => { setPage(1); setAppliquee(""); setRecherche(""); }, [application, site, table]);

  // Export CSV (fichier téléchargé par le navigateur)
  const exporter = async () => {
    const t = toast.loading("Patientez… préparation du CSV");
    try {
      const r = await apiClient.get(`${BASE}/export-csv`, { params: { application, site, table, recherche: appliquee }, responseType: "blob" });
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url; a.download = `${donnees?.collection || table}.csv`; a.click();
      URL.revokeObjectURL(url);
      toast.success("CSV prêt", { id: t });
    } catch {
      toast.error("Export impossible", { id: t });
    }
  };

  const pages = donnees ? Math.max(1, Math.ceil(donnees.total / donnees.par_page)) : 1;
  return (
    <section className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200" data-testid="grille-donnees">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">3. Données — {site} · {table} {chargement && <Jauge />}</h2>
          <p className="text-xs text-slate-500">Collection MongoDB : {donnees?.collection || "…"} · {donnees?.total ?? "…"} document(s) · lecture seule</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <form onSubmit={(e) => { e.preventDefault(); setPage(1); setAppliquee(recherche); }} className="flex items-center gap-1">
            <input value={recherche} onChange={(e) => setRecherche(e.target.value)} placeholder="Rechercher…" className="w-48 rounded border border-slate-300 px-2 py-1" />
            <button type="submit" className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-50">🔍</button>
          </form>
          <button type="button" onClick={exporter} className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-50">⬇ CSV</button>
          <button type="button" onClick={onFermer} className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-50">Fermer</button>
        </div>
      </div>
      <div className="mt-2 max-h-[32rem] overflow-auto rounded ring-1 ring-slate-200">
        <table className="w-full whitespace-nowrap text-xs">
          <thead className="sticky top-0 bg-slate-50 text-left text-slate-500">
            <tr>{(donnees?.colonnes || []).map((c) => <th key={c} className="p-2">{c}</th>)}<th className="p-2">Mis à jour (SAWALI)</th></tr>
          </thead>
          <tbody>
            {(donnees?.documents || []).map((d) => (
              <tr key={d._hf_cle} className={`border-t border-slate-100 ${ligne === d._hf_cle ? "ligne-selectionnee" : ""}`} onClick={() => setLigne(d._hf_cle)}>
                {donnees.colonnes.map((c) => <td key={c} className="max-w-xs truncate p-2" title={cellule(d[c])}>{cellule(d[c])}</td>)}
                <td className="p-2">{dateHeure(d._hf_maj)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-2 flex items-center gap-2 text-sm">
        <button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)} className="rounded border border-slate-300 px-2 py-1 disabled:opacity-50">◀</button>
        <span>Page {page} / {pages}</span>
        <button type="button" disabled={page >= pages} onClick={() => setPage(page + 1)} className="rounded border border-slate-300 px-2 py-1 disabled:opacity-50">▶</button>
      </div>
    </section>
  );
}
