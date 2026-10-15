// =====================================================================
// Lot 170 — Rubrique des Paramètres « 💳 Services à renouveler — coûts » : les services à surveiller et renouveler (MongoDB Atlas,
// Render, Cloudflare R2, domaines…) avec le MONTANT à la date de lecture, par service et formule, par PLATEFORME et par CLUSTER.
//   GET  /api/admin/services-renouveler          lignes, totaux (par devise, plateforme, cluster), lectures automatiques
//   PUT  /api/admin/services-renouveler          { services, clusters } (liste complète)
//   POST /api/admin/services-renouveler/lire     relit Atlas et Cloudflare tout de suite
//   POST /api/admin/services-renouveler/{id}/renouveler   l'échéance avance d'une période
// Origine du montant (pastille) : « saisi » par vous, « lu Atlas » (facture en cours, une ligne par cluster) ou « estimé R2 ».
// Une ligne qui sert plusieurs plateformes est répartie à PARTS ÉGALES entre elles dans la vue « par plateforme ».
// Les clés d'API (Atlas, Cloudflare) se saisissent sur Render, jamais ici.
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const PERIODES = [["mensuel", "Mensuel"], ["trimestriel", "Trimestriel"], ["semestriel", "Semestriel"], ["annuel", "Annuel"], ["unique", "Unique"]];
const SOURCES = [["saisi", "Montant saisi"], ["atlas", "Lu chez Atlas (facture en cours)"], ["r2", "Estimé (Cloudflare R2)"]];
// Couleur de la pastille d'échéance
const NIVEAUX = { echu: "bg-rose-100 text-rose-800", urgent: "bg-orange-100 text-orange-800", bientot: "bg-amber-100 text-amber-800", ok: "bg-emerald-100 text-emerald-800", inconnu: "bg-slate-100 text-slate-600", inactif: "bg-slate-100 text-slate-500" };
const ORIGINES = { saisi: ["saisi", "bg-slate-100 text-slate-700"], atlas: ["lu Atlas", "bg-emerald-100 text-emerald-800"], r2: ["estimé R2", "bg-sky-100 text-sky-800"] };
// Services habituels proposés quand la liste est vide (montants et dates à compléter)
const HABITUELS = [
  { nom: "MongoDB Atlas", fournisseur: "MongoDB", source: "atlas", periodicite: "mensuel", lien_paiement: "https://cloud.mongodb.com" },
  { nom: "Render — SAWALI", fournisseur: "Render", plateformes: ["SAWALI"], lien_paiement: "https://dashboard.render.com" },
  { nom: "Cloudflare R2", fournisseur: "Cloudflare", source: "r2", periodicite: "mensuel", lien_paiement: "https://dash.cloudflare.com" },
  { nom: "Nom de domaine", fournisseur: "", periodicite: "annuel" },
  { nom: "SMS (OVH)", fournisseur: "OVH", periodicite: "mensuel" },
];

const argent = (n, devise) => `${Number(n || 0).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${devise === "USD" ? "$" : devise === "EUR" ? "€" : devise}`;
const dateHeure = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");
const dateJour = (iso) => (iso ? new Date(`${iso}T00:00:00`).toLocaleDateString("fr-FR") : "—");
const montants = (m) => Object.entries(m || {}).map(([d, v]) => argent(v, d)).join(" + ") || "—";

export default function ServicesRenouvelerSection() {
  const [vue, setVue] = useState(null);                 // réponse du serveur
  const [onglet, setOnglet] = useState("service");      // service | plateforme | cluster
  const [edition, setEdition] = useState(false);        // éditeur de la liste ouvert
  const [services, setServices] = useState([]);         // lignes en cours d'édition
  const [clusters, setClusters] = useState([]);         // [{nom, plateformes}] en cours d'édition
  const [occupe, setOccupe] = useState(false);

  // Charge (ou recharge) la vue ; `ouvrirEditeur` recopie la liste dans l'éditeur
  const charger = useCallback(async (relire = false) => {
    const attente = relire ? toast.loading("Patientez… lecture chez Atlas et Cloudflare") : null;
    try {
      const { data } = relire ? await apiClient.post("/admin/services-renouveler/lire", {}, { timeout: 90000 }) : await apiClient.get("/admin/services-renouveler", { timeout: 90000 });
      setVue(data);
      if (attente) toast.success("Lecture terminée", { id: attente });
    } catch (e) {
      const m = e?.response?.data?.detail || "Services à renouveler illisibles";
      attente ? toast.error(m, { id: attente }) : toast.error(m);
    }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  // Ouvre l'éditeur avec la liste enregistrée
  const ouvrir = () => {
    setServices((vue?.services || []).map((s) => ({ ...s, plateformes_texte: (s.plateformes || []).join(", ") })));
    setClusters(Object.entries(vue?.clusters || {}).map(([nom, p]) => ({ nom, plateformes_texte: p.join(", ") })));
    setEdition(true);
  };
  const changer = (i, champ, v) => setServices(services.map((s, k) => (k === i ? { ...s, [champ]: v } : s)));
  const ajouter = (modele = {}) => setServices((l) => [...l, { id: "", nom: "", fournisseur: "", formule: "", montant: 0, devise: "USD", periodicite: "mensuel", prochaine_echeance: "", lien_paiement: "",
    plateformes_texte: (modele.plateformes || []).join(", "), cluster: "", source: "saisi", actif: true, ...modele }]);
  const liste = (t) => String(t || "").split(",").map((x) => x.trim()).filter(Boolean);

  // Enregistre la liste complète et la répartition des clusters
  const enregistrer = async () => {
    setOccupe(true);
    try {
      const corps = {
        services: services.map(({ plateformes_texte, ...s }) => ({ ...s, montant: Number(String(s.montant).replace(",", ".")) || 0, prochaine_echeance: s.prochaine_echeance || null, plateformes: liste(plateformes_texte) })),
        clusters: Object.fromEntries(clusters.filter((c) => c.nom.trim()).map((c) => [c.nom.trim(), liste(c.plateformes_texte)])),
      };
      const { data } = await apiClient.put("/admin/services-renouveler", corps, { timeout: 90000 });
      setVue(data); setEdition(false); toast.success("Services enregistrés");
    } catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible"); } finally { setOccupe(false); }
  };
  // « Renouvelé » : l'échéance avance d'une période
  const renouveler = async (idService) => {
    const racine = String(idService).split(":")[0];
    if (!window.confirm("Marquer ce service comme renouvelé ? Son échéance avance d'une période.")) return;
    try { const { data } = await apiClient.post(`/admin/services-renouveler/${racine}/renouveler`); setVue(data); toast.success("Échéance mise à jour"); }
    catch (e) { toast.error(e?.response?.data?.detail || "Mise à jour impossible"); }
  };

  if (!vue) return <p className="text-sm text-slate-500">Chargement…</p>;
  const lectures = Object.entries(vue.lectures || {});
  const champ = "rounded border border-slate-300 px-2 py-1 text-xs";
  return (
    <div className="space-y-3 text-sm text-slate-700" data-testid="services-renouveler-section">
      <p>
        Les services à surveiller et à renouveler, avec le <b>montant à la date de lecture</b>, par service et formule, par <b>plateforme</b> et par <b>cluster</b>.
        Atlas (facture en cours, une ligne par cluster) et Cloudflare R2 (estimation d'après le stockage et les opérations) sont lus automatiquement ;
        les autres montants sont ceux que vous saisissez. Un rappel WhatsApp part 30, 7 et 1 jour avant l'échéance, puis le jour même.
      </p>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <button type="button" onClick={() => charger(true)} className="rounded-md bg-slate-900 px-3 py-1.5 font-semibold text-white hover:bg-slate-700" data-testid="services-lire">Lire maintenant</button>
        <button type="button" onClick={edition ? () => setEdition(false) : ouvrir} className="rounded-md bg-slate-100 px-3 py-1.5 font-semibold text-slate-800 hover:bg-slate-200" data-testid="services-modifier">{edition ? "Fermer l'éditeur" : "Modifier la liste"}</button>
        <span className="text-slate-500">Lecture du {dateHeure(vue.le)}</span>
        {lectures.map(([nom, l]) => (
          <span key={nom} className={`rounded-full px-2 py-0.5 ${l.erreur ? "bg-rose-100 text-rose-800" : "bg-emerald-100 text-emerald-800"}`} title={l.erreur || `Lu le ${dateHeure(l.le)}`}>
            {nom === "atlas" ? "Atlas" : "R2"} : {l.erreur ? "lecture impossible" : `lu le ${dateHeure(l.le)}`}
          </span>
        ))}
      </div>
      {lectures.filter(([, l]) => l.erreur).map(([nom, l]) => <p key={nom} className="rounded-md bg-rose-50 p-2 text-xs text-rose-800 ring-1 ring-rose-200">⚠ {nom === "atlas" ? "Atlas" : "Cloudflare R2"} : {l.erreur}. Le montant saisi reste affiché.</p>)}

      {/* Totaux du mois et de l'année (lignes actives) */}
      <div className="grid gap-2 sm:grid-cols-2">
        <div className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200"><p className="text-xs text-slate-500">Coût mensuel (lignes actives)</p><p className="text-lg font-semibold tabular-nums" data-testid="services-total-mensuel">{montants(vue.totaux.mensuel)}</p></div>
        <div className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200"><p className="text-xs text-slate-500">Soit par an</p><p className="text-lg font-semibold tabular-nums">{montants(vue.totaux.annuel)}</p></div>
      </div>

      <div className="flex gap-1 text-xs" role="tablist">
        {[["service", "Par service"], ["plateforme", "Par plateforme"], ["cluster", "Par cluster"]].map(([k, t]) => (
          <button key={k} type="button" role="tab" aria-selected={onglet === k} onClick={() => setOnglet(k)} data-testid={`services-onglet-${k}`}
                  className={`rounded-full px-3 py-1 font-semibold ${onglet === k ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"}`}>{t}</button>
        ))}
      </div>

      {onglet === "service" && (
        <div className="overflow-x-auto">
          <table className="tableau w-full text-left text-xs" data-testid="services-tableau">
            <thead><tr><th>Service / formule</th><th className="text-right">Montant</th><th>Périodicité</th><th className="text-right">Par mois</th><th>Échéance</th><th>Plateformes</th><th>Cluster</th><th /></tr></thead>
            <tbody>
              {vue.lignes.length === 0 && <tr><td colSpan={8} className="py-3 text-slate-500">Aucun service. Cliquez sur « Modifier la liste » pour ajouter les vôtres.</td></tr>}
              {vue.lignes.map((l) => (
                <tr key={l.id} className={l.actif ? "" : "opacity-50"}>
                  <td><b>{l.nom}</b>{l.formule && <span className="text-slate-500"> · {l.formule}</span>}{l.fournisseur && <div className="text-slate-400">{l.fournisseur}</div>}</td>
                  <td className="text-right tabular-nums">
                    {argent(l.montant, l.devise)}
                    <div><span className={`rounded-full px-1.5 py-0.5 text-[10px] ${ORIGINES[l.origine]?.[1]}`} title={l.erreur || l.detail || ""}>{ORIGINES[l.origine]?.[0]}{l.erreur ? " ⚠" : ""}</span></div>
                    {l.lu_le && <div className="text-[10px] text-slate-400">lu le {dateHeure(l.lu_le)}</div>}
                  </td>
                  <td>{PERIODES.find(([v]) => v === l.periodicite)?.[1]}</td>
                  <td className="text-right tabular-nums">{argent(l.mensuel, l.devise)}</td>
                  <td>{l.prochaine_echeance ? <>{dateJour(l.prochaine_echeance)} <span className={`rounded-full px-1.5 py-0.5 text-[10px] ${NIVEAUX[l.niveau]}`}>{l.niveau === "echu" ? `échu depuis ${-l.jours} j` : l.niveau === "inactif" ? "inactif" : `dans ${l.jours} j`}</span></> : "—"}</td>
                  <td>{(l.plateformes || []).join(", ") || <span className="text-slate-400">{"Commun"}</span>}</td>
                  <td>{l.cluster || "—"}</td>
                  <td className="whitespace-nowrap space-x-2">
                    {l.lien_paiement && <a href={l.lien_paiement} target="_blank" rel="noreferrer" className="text-sky-700 underline">Payer</a>}
                    {l.prochaine_echeance && l.actif && <button type="button" onClick={() => renouveler(l.id)} className="text-emerald-700 underline">Renouvelé</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {onglet !== "service" && (
        <div className="overflow-x-auto">
          <p className="mb-1 text-xs text-slate-500">{onglet === "plateforme" ? "Une ligne qui sert plusieurs plateformes est répartie à parts égales. « Commun » = ligne sans plateforme." : "Coût mensuel par cluster (lignes qui indiquent un cluster ; Atlas : une ligne par cluster)."}</p>
          <table className="tableau w-full text-left text-xs" data-testid={`services-tableau-${onglet}`}>
            <thead><tr><th>{onglet === "plateforme" ? "Plateforme" : "Cluster"}</th><th className="text-right">Par mois</th><th className="text-right">Par an</th></tr></thead>
            <tbody>
              {Object.entries(onglet === "plateforme" ? vue.totaux.plateformes : vue.totaux.clusters).length === 0 && <tr><td colSpan={3} className="py-3 text-slate-500">Rien à afficher : indiquez {onglet === "plateforme" ? "les plateformes" : "le cluster"} de chaque service dans « Modifier la liste ».</td></tr>}
              {Object.entries(onglet === "plateforme" ? vue.totaux.plateformes : vue.totaux.clusters)
                .sort((a, b) => Object.values(b[1]).reduce((x, y) => x + y, 0) - Object.values(a[1]).reduce((x, y) => x + y, 0))
                .map(([nom, m]) => (
                  <tr key={nom}><td className="font-medium">{nom}</td><td className="text-right tabular-nums">{montants(m)}</td>
                    <td className="text-right tabular-nums">{montants(Object.fromEntries(Object.entries(m).map(([d, v]) => [d, v * 12])))}</td></tr>
                ))}
            </tbody>
          </table>
        </div>
      )}

      {edition && (
        <div className="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-3" data-testid="services-editeur">
          <div className="space-y-2">
            {services.map((s, i) => (
              <div key={s.id || i} className="grid grid-cols-1 gap-2 rounded-lg border border-slate-200 bg-white p-2 md:grid-cols-6">
                <input className={champ} placeholder="Service (ex. Render — ZandGo)" maxLength={120} value={s.nom} onChange={(e) => changer(i, "nom", e.target.value)} />
                <input className={champ} placeholder="Formule (ex. Starter, Flex)" maxLength={80} value={s.formule} onChange={(e) => changer(i, "formule", e.target.value)} />
                <div className="flex gap-1"><input className={`${champ} w-full`} placeholder="Montant" inputMode="decimal" value={s.montant} onChange={(e) => changer(i, "montant", e.target.value)} />
                  <input className={`${champ} w-16`} placeholder="Devise" maxLength={6} value={s.devise} onChange={(e) => changer(i, "devise", e.target.value.toUpperCase())} /></div>
                <select className={champ} value={s.periodicite} onChange={(e) => changer(i, "periodicite", e.target.value)} aria-label="Périodicité">{PERIODES.map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select>
                <input className={champ} type="date" value={s.prochaine_echeance || ""} onChange={(e) => changer(i, "prochaine_echeance", e.target.value)} aria-label="Prochaine échéance" />
                <select className={champ} value={s.source} onChange={(e) => changer(i, "source", e.target.value)} aria-label="Origine du montant">{SOURCES.map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select>
                <input className={`${champ} md:col-span-2`} placeholder="Plateformes, séparées par des virgules (ex. ZandGo, adLyn)" value={s.plateformes_texte} onChange={(e) => changer(i, "plateformes_texte", e.target.value)} />
                <input className={champ} placeholder="Cluster (ex. Cluster0)" maxLength={60} value={s.cluster} onChange={(e) => changer(i, "cluster", e.target.value)} />
                <input className={champ} placeholder="Fournisseur" maxLength={60} value={s.fournisseur} onChange={(e) => changer(i, "fournisseur", e.target.value)} />
                <input className={champ} placeholder="Lien pour payer" maxLength={300} value={s.lien_paiement} onChange={(e) => changer(i, "lien_paiement", e.target.value)} />
                <div className="flex items-center gap-3 text-xs"><label className="flex items-center gap-1"><input type="checkbox" checked={s.actif !== false} onChange={(e) => changer(i, "actif", e.target.checked)} /> Actif</label>
                  <button type="button" className="text-rose-700 hover:underline" onClick={() => setServices(services.filter((_, k) => k !== i))}>Retirer</button></div>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap gap-2 text-xs">
            <button type="button" onClick={() => ajouter()} className="rounded-md bg-white px-3 py-1.5 font-semibold ring-1 ring-slate-300 hover:bg-slate-100" data-testid="services-ajouter">+ Ajouter un service</button>
            {services.length === 0 && <button type="button" onClick={() => HABITUELS.forEach((h) => ajouter(h))} className="rounded-md bg-white px-3 py-1.5 font-semibold ring-1 ring-slate-300 hover:bg-slate-100">Pré-remplir avec les services habituels</button>}
          </div>
          <div className="space-y-1 text-xs">
            <p className="font-semibold">Clusters Atlas → plateformes <span className="font-normal text-slate-500">(la facture d'Atlas donne un montant par cluster ; dites quelles plateformes il porte, ex. Cluster0 → SAWALI, ZandGo, adLyn, Ster)</span></p>
            {clusters.map((c, i) => (
              <div key={i} className="flex flex-wrap gap-2">
                <input className={`${champ} w-40`} placeholder="Nom du cluster" value={c.nom} onChange={(e) => setClusters(clusters.map((x, k) => (k === i ? { ...x, nom: e.target.value } : x)))} />
                <input className={`${champ} min-w-0 flex-1`} placeholder="Plateformes, séparées par des virgules" value={c.plateformes_texte} onChange={(e) => setClusters(clusters.map((x, k) => (k === i ? { ...x, plateformes_texte: e.target.value } : x)))} />
                <button type="button" className="text-rose-700 hover:underline" onClick={() => setClusters(clusters.filter((_, k) => k !== i))}>Retirer</button>
              </div>
            ))}
            <button type="button" onClick={() => setClusters([...clusters, { nom: "", plateformes_texte: "" }])} className="rounded-md bg-white px-3 py-1 font-semibold ring-1 ring-slate-300 hover:bg-slate-100">+ Ajouter un cluster</button>
          </div>
          <button type="button" onClick={enregistrer} disabled={occupe} className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-700 disabled:opacity-50" data-testid="services-enregistrer">{occupe ? "Patientez…" : "Enregistrer"}</button>
        </div>
      )}
      <p className="text-xs text-slate-500">
        Clés à saisir sur Render (jamais ici) — Atlas : <code>ATLAS_API_PUBLIC_KEY</code>, <code>ATLAS_API_PRIVATE_KEY</code>, <code>ATLAS_ORG_ID</code> (droit « Organization Billing Viewer ») ;
        Cloudflare : <code>CLOUDFLARE_API_TOKEN</code>, <code>CLOUDFLARE_ACCOUNT_ID</code> (droit de lecture des analyses). L'estimation R2 suit les tarifs publics (10 Go gratuits, 0,015 $/Go/mois).
      </p>
    </div>
  );
}
