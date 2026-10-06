/*
  Lot 47 — « Parc informatique » : équipements des comptes clients et interventions.
  Onglet « Équipements » : numéro d'inventaire automatique (PARC-<CODE>-0001), catégorie
  (liste extensible par client), fabricant, modèle, n° de série, IP, MAC, nom d'hôte, système,
  utilisateur affecté, lieu (site / service / bureau), achat, garantie, fournisseur, état,
  notes, photos ; recherche, filtres, compteurs, export et import CSV ; fiche avec l'historique
  des interventions. Onglet « Interventions » : components/ParcInterventions.jsx (rapport à
  signer par le responsable du client, envoi du lien par WhatsApp ou e-mail).
  Admin / Superviseur : choix du compte client ; un compte client : son parc.
  Fonction activable « Parc informatique » (Outils+).
  API : /me/parc/…, /me/parc-clients, /me/parc-categories (backend/routes/parc_informatique.py).
  Lot 66 : fiches créées automatiquement par Loois (inventaire des postes, sans client : « À affecter ») ;
  l'Admin / le Superviseur les affecte à un compte client depuis le formulaire ; la fiche affiche le
  résumé technique envoyé par Loois ; « ?equipement=<id> » dans l'adresse ouvre directement une fiche
  (lien « Ouvrir la fiche de l'équipement » des détails d'un poste).
*/
import React, { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Download, Loader2, Monitor, Plus, Search, Trash2, Upload, Wrench, X } from "lucide-react";
import { apiClient } from "@/lib/api";
import { Button } from "@/components/ui/button";
import ParcInterventions, { BadgeSignature, ETATS, FormulaireIntervention, PhotosParc, TYPES, champ, dateHeureFr, erreur, telecharger } from "@/components/ParcInterventions";

const dateFr = (d) => (d ? new Date(d).toLocaleDateString("fr-FR", { timeZone: "UTC" }) : "—");
const VIDE = { categorie: "", fabricant: "", modele: "", numero_serie: "", adresse_ip: "", adresse_mac: "", nom_hote: "",
  systeme_exploitation: "", utilisateur_affecte: "", site: "", service: "", bureau: "", date_achat: "", fin_garantie: "",
  fournisseur: "", etat: "en_service", notes: "" };
const CHAMPS = [["fabricant", "Fabricant"], ["modele", "Modèle"], ["numero_serie", "N° de série"], ["adresse_ip", "Adresse IP", "ex. 192.168.1.20"],
  ["adresse_mac", "Adresse MAC", "AA:BB:CC:DD:EE:FF"], ["nom_hote", "Nom d'hôte"], ["systeme_exploitation", "Système d'exploitation"],
  ["utilisateur_affecte", "Utilisateur affecté"], ["site", "Site"], ["service", "Service"], ["bureau", "Bureau"], ["fournisseur", "Fournisseur"]];
const lieu = (e) => [e.site, e.service, e.bureau].filter(Boolean).join(" / ");

const Etat = ({ etat }) => <span className={`rounded-full px-2 py-0.5 text-[11px] ${ETATS[etat]?.[1] || ""}`}>{ETATS[etat]?.[0] || etat}</span>;

// Formulaire d'un équipement (nouveau ou existant)
function FormulaireEquipement({ equipement, categories, compteClientId, clients, onAjoutCategorie, onClose, onEnregistre }) {
  const [f, setF] = useState(() => (equipement ? { ...VIDE, ...Object.fromEntries(Object.keys(VIDE).map((k) => [k, equipement[k] ?? VIDE[k]])) } : { ...VIDE }));
  const [occupe, setOccupe] = useState(false);
  // Lot 66 : fiche créée par Loois sans client → l'Admin / le Superviseur choisit le compte client
  const aAffecter = Boolean(equipement && !equipement.tenant_id && clients?.admin);
  const [affectation, setAffectation] = useState("");
  const maj = (x) => setF((p) => ({ ...p, ...x }));
  const enregistrer = async () => {
    setOccupe(true);
    const corps = { ...f, compte_client_id: equipement ? (aAffecter && affectation ? affectation : undefined) : compteClientId || null,
      date_achat: f.date_achat || null, fin_garantie: f.fin_garantie || null };
    try {
      const r = equipement ? await apiClient.put(`/me/parc/equipements/${equipement.id}`, corps) : await apiClient.post("/me/parc/equipements", corps);
      toast.success(equipement ? "Équipement mis à jour" : `Équipement ${r.data.numero_inventaire} ajouté`);
      onEnregistre(r.data);
    } catch (e) { toast.error(erreur(e, "Enregistrement impossible")); }
    finally { setOccupe(false); }
  };
  return (
    <div className="fixed inset-0 z-[75] flex items-center justify-center bg-black/40 p-2 sm:p-3">
      <div className="max-h-[94vh] w-full max-w-3xl space-y-3 overflow-y-auto rounded-xl bg-white p-4 sm:p-5" data-testid="parc-equipement-form">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-slate-800">{equipement ? `Équipement ${equipement.numero_inventaire}` : "Nouvel équipement"}</h2>
          <button type="button" onClick={onClose}><X className="h-5 w-5" /></button>
        </div>
        {aAffecter && (
          <label className="block rounded-lg bg-amber-50 p-2 text-xs text-amber-900">
            Fiche créée automatiquement par Loois : choisissez le compte client de cet équipement
            <select className={champ} value={affectation} onChange={(e) => setAffectation(e.target.value)} data-testid="parc-affectation">
              <option value="">— À affecter plus tard —</option>
              {(clients.items || []).map((c) => <option key={c.id} value={c.id}>{c.nom}{c.code ? ` · ${c.code}` : ""}</option>)}
            </select>
          </label>
        )}
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="text-xs text-slate-600">Catégorie *
            <div className="flex gap-1">
              <select className={champ} value={f.categorie} onChange={(e) => maj({ categorie: e.target.value })} data-testid="parc-categorie">
                <option value="">— Choisir —</option>
                {categories.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <button type="button" title="Ajouter une catégorie" className="rounded border border-slate-300 px-2"
                onClick={async () => { const c = await onAjoutCategorie(); if (c) maj({ categorie: c }); }}><Plus className="h-4 w-4" /></button>
            </div>
          </label>
          {CHAMPS.map(([k, l, ph]) => (
            <label key={k} className="text-xs text-slate-600">{l}
              <input className={`${champ} ${["adresse_ip", "adresse_mac", "numero_serie"].includes(k) ? "font-mono" : ""}`} value={f[k] || ""} placeholder={ph || ""}
                onChange={(e) => maj({ [k]: e.target.value })} data-testid={`parc-${k}`} />
            </label>
          ))}
          <label className="text-xs text-slate-600">Date d'achat
            <input type="date" className={champ} value={f.date_achat || ""} onChange={(e) => maj({ date_achat: e.target.value })} />
          </label>
          <label className="text-xs text-slate-600">Fin de garantie
            <input type="date" className={champ} value={f.fin_garantie || ""} onChange={(e) => maj({ fin_garantie: e.target.value })} />
          </label>
          <label className="text-xs text-slate-600">État
            <select className={champ} value={f.etat} onChange={(e) => maj({ etat: e.target.value })}>
              {Object.entries(ETATS).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </label>
          <label className="text-xs text-slate-600 sm:col-span-3">Notes
            <textarea rows={2} className={champ} value={f.notes || ""} onChange={(e) => maj({ notes: e.target.value })} />
          </label>
        </div>
        {equipement?.id
          ? <div className="space-y-1"><p className="text-xs font-semibold text-slate-700">Photos</p>
              <PhotosParc base={`/me/parc/equipements/${equipement.id}`} photos={equipement.photos} onChange={() => onEnregistre(null)} /></div>
          : <p className="text-[11px] text-slate-500">Enregistrez l'équipement pour ajouter des photos.</p>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Annuler</Button>
          <Button onClick={enregistrer} disabled={occupe || !f.categorie} data-testid="parc-equipement-enregistrer">
            {occupe && <Loader2 className="mr-1 h-4 w-4 animate-spin" />} Enregistrer
          </Button>
        </div>
      </div>
    </div>
  );
}

// Fiche d'un équipement : détails, photos, historique des interventions (plus récente d'abord)
function FicheEquipement({ id, equipements, onClose, onModifier, onChange }) {
  const [e, setE] = useState(null);
  const [intervention, setIntervention] = useState(null);   // null | "nouvelle" | intervention
  const charger = useCallback(() => apiClient.get(`/me/parc/equipements/${id}`).then((r) => setE(r.data)).catch((x) => toast.error(erreur(x, "Équipement introuvable"))), [id]);
  useEffect(() => { charger(); }, [charger]);
  if (!e) return null;
  const lignes = [["Catégorie", e.categorie], ["Fabricant / modèle", [e.fabricant, e.modele].filter(Boolean).join(" ")], ["N° de série", e.numero_serie],
    ["Adresse IP", e.adresse_ip], ["Adresse MAC", e.adresse_mac], ["Nom d'hôte", e.nom_hote], ["Système", e.systeme_exploitation],
    ["Utilisateur affecté", e.utilisateur_affecte], ["Lieu", lieu(e)], ["Client", e.tenant_id ? e.client_nom : "À affecter (fiche créée par Loois)"], ["Achat", dateFr(e.date_achat)],
    ["Fin de garantie", dateFr(e.fin_garantie)], ["Fournisseur", e.fournisseur], ["Notes", e.notes]];
  // Lot 66 : résumé technique envoyé par Loois (mis à jour automatiquement, au plus toutes les 30 minutes)
  const lo = e.loois;
  if (lo) {
    lignes.push(["Processeur", [lo.processeur, lo.coeurs_logiques ? `${lo.coeurs_logiques} cœurs logiques` : ""].filter(Boolean).join(" · ")],
      ["Mémoire vive", lo.ram_go ? `${lo.ram_go.toLocaleString("fr-FR")} Go` : ""],
      ["Disques", (lo.disques || []).map((d) => `${d.lettre} ${d.libre_go ?? "?"} Go libres / ${d.total_go ?? "?"} Go`).join("\n")],
      ["Cartes réseau (MAC)", (lo.macs || []).join("\n")],
      ["Dernier inventaire Loois", lo.inventaire_le ? new Date(lo.inventaire_le).toLocaleString("fr-FR") : ""]);
  }
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 p-2 sm:p-3">
      <div className="max-h-[94vh] w-full max-w-3xl space-y-3 overflow-y-auto rounded-xl bg-white p-4 sm:p-5" data-testid="parc-fiche">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 font-semibold text-slate-800"><Monitor className="h-5 w-5 text-indigo-600" /> {e.numero_inventaire} <Etat etat={e.etat} /></h2>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => onModifier(e)}>Modifier</Button>
            <Button size="sm" onClick={() => setIntervention("nouvelle")}><Wrench className="mr-1 h-4 w-4" /> Nouvelle intervention</Button>
            <button type="button" onClick={onClose}><X className="h-5 w-5" /></button>
          </div>
        </div>
        <table className="w-full text-sm"><tbody>
          {lignes.filter(([, v]) => v && v !== "—").map(([l, v]) => (
            <tr key={l} className="border-b border-slate-100 align-top"><td className="w-40 py-1 pr-3 text-xs font-semibold text-slate-500">{l}</td>
              <td className={`py-1 whitespace-pre-line ${["Adresse IP", "Adresse MAC", "N° de série"].includes(l) ? "font-mono" : ""}`}>{v}</td></tr>
          ))}
        </tbody></table>
        {(e.photos || []).length > 0 && <PhotosParc base={`/me/parc/equipements/${e.id}`} photos={e.photos} verrouille onChange={charger} />}
        <section className="space-y-1">
          <p className="text-sm font-semibold text-slate-800">Historique des interventions ({(e.interventions || []).length})</p>
          {(e.interventions || []).length === 0 && <p className="text-xs text-slate-400">Aucune intervention.</p>}
          {(e.interventions || []).map((iv) => (
            <button key={iv.id} type="button" onClick={() => setIntervention(iv)} className="block w-full rounded-lg border border-slate-200 p-2 text-left text-xs hover:bg-slate-50">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono font-semibold">{iv.numero}</span>
                <span>{dateHeureFr(iv.debut || iv.cree_le)}</span>
                <span className="text-slate-500">{TYPES[iv.type_intervention]}</span>
                <span className="ml-auto"><BadgeSignature iv={iv} /></span>
              </div>
              {iv.probleme && <p className="mt-0.5 text-slate-600">Problème : {iv.probleme}</p>}
              {iv.actions && <p className="text-slate-600">Actions : {iv.actions}</p>}
              {(iv.equipe || []).length > 0 && <p className="text-slate-500">Équipe : {iv.equipe.map((m) => m.nom).join(", ")}</p>}
            </button>
          ))}
        </section>
        {intervention && (
          <FormulaireIntervention key={intervention === "nouvelle" ? "nouvelle" : intervention.id} intervention={intervention === "nouvelle" ? null : intervention}
            equipements={equipements.filter((x) => x.tenant_id === e.tenant_id)} compteClientId={e.tenant_id}
            equipementsInitiaux={[e.id]} onClose={() => { setIntervention(null); charger(); }} onEnregistre={() => { charger(); onChange(); }} />
        )}
      </div>
    </div>
  );
}

// Import CSV : colonnes documentées, rapport des lignes rejetées
function ImportCsv({ compteClientId, onClose, onImporte }) {
  const [fichier, setFichier] = useState(null);
  const [resultat, setResultat] = useState(null);
  const [occupe, setOccupe] = useState(false);
  const importer = async () => {
    setOccupe(true);
    try {
      const fd = new FormData();
      fd.append("fichier", fichier);
      if (compteClientId) fd.append("compte_client_id", compteClientId);
      const r = await apiClient.post("/me/parc/equipements/import", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setResultat(r.data);
      if (r.data.importes) { toast.success(`${r.data.importes} équipement(s) importé(s)`); onImporte(); }
    } catch (e) { toast.error(erreur(e, "Import impossible")); }
    finally { setOccupe(false); }
  };
  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 p-3" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="max-h-[90vh] w-full max-w-xl space-y-3 overflow-y-auto rounded-xl bg-white p-5 text-sm" data-testid="parc-import">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-1.5 font-semibold text-slate-800"><Upload className="h-4 w-4" /> Importer des équipements (CSV)</h3>
          <button type="button" onClick={onClose}><X className="h-5 w-5" /></button>
        </div>
        <p className="text-xs text-slate-600">Fichier CSV (séparateur « ; » ou « , », UTF-8 ou Excel), 1re ligne = en-têtes. Colonnes reconnues (accents et majuscules indifférents) :
          <b> Catégorie</b> (obligatoire), Fabricant, Modèle, N° de série, Adresse IP, Adresse MAC, Nom d'hôte, Système d'exploitation, Utilisateur affecté, Site, Service, Bureau,
          Date d'achat, Fin de garantie (AAAA-MM-JJ ou JJ/MM/AAAA), Fournisseur, État (En service, En panne, En réparation, En stock, Réformé), Notes.
          Le n° d'inventaire est attribué automatiquement. Astuce : exportez le parc pour obtenir un modèle.</p>
        <input type="file" accept=".csv,text/csv" onChange={(e) => { setFichier(e.target.files?.[0] || null); setResultat(null); }} />
        {resultat && (
          <div className="space-y-1 rounded bg-slate-50 p-2 text-xs">
            <p><b>{resultat.importes}</b> importé(s){resultat.rejets.length ? `, ${resultat.rejets.length} ligne(s) rejetée(s) :` : "."}</p>
            <ul className="max-h-40 overflow-y-auto">{resultat.rejets.map((x) => <li key={x.ligne} className="text-rose-700">Ligne {x.ligne} : {x.motif}</li>)}</ul>
          </div>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Fermer</Button>
          <Button onClick={importer} disabled={occupe || !fichier}>{occupe && <Loader2 className="mr-1 h-4 w-4 animate-spin" />} Importer</Button>
        </div>
      </div>
    </div>
  );
}

export default function ParcInformatique() {
  const [clients, setClients] = useState({ admin: false, items: [] });
  const [compte, setCompte] = useState("");                 // Admin : compte client choisi ("" = tous)
  const [onglet, setOnglet] = useState("equipements");
  const [categories, setCategories] = useState([]);
  const [donnees, setDonnees] = useState(null);
  const [refus, setRefus] = useState("");
  const [q, setQ] = useState("");
  const [categorie, setCategorie] = useState("");
  const [etat, setEtat] = useState("");
  const [site, setSite] = useState("");
  const [edition, setEdition] = useState(null);             // null | "nouveau" | équipement
  const [fiche, setFiche] = useState(null);                 // id de l'équipement affiché
  const [importer, setImporter] = useState(false);
  const [parametres, setParametres] = useSearchParams();

  // Lot 66 : « ?equipement=<id> » (lien des détails d'un poste) → la fiche s'ouvre directement
  useEffect(() => {
    const id = parametres.get("equipement");
    if (id) {
      setFiche(id);
      parametres.delete("equipement");
      setParametres(parametres, { replace: true });
    }
  }, [parametres, setParametres]);

  useEffect(() => {
    apiClient.get("/me/parc-clients").then((r) => setClients(r.data)).catch((e) => setRefus(erreur(e, "Module indisponible")));
  }, []);
  const chargerCategories = useCallback(() => apiClient.get("/me/parc-categories", { params: { compte_client_id: compte || undefined } })
    .then((r) => setCategories(r.data.toutes || [])).catch(() => {}), [compte]);
  useEffect(() => { chargerCategories(); }, [chargerCategories]);
  const filtres = { q: q || undefined, categorie: categorie || undefined, etat: etat || undefined, site: site || undefined, compte_client_id: compte || undefined };
  const charger = useCallback(async () => {
    try { setDonnees((await apiClient.get("/me/parc/equipements", { params: { q: q || undefined, categorie: categorie || undefined, etat: etat || undefined, site: site || undefined, compte_client_id: compte || undefined } })).data); }
    catch (e) { setRefus(erreur(e, "Module indisponible")); }
  }, [q, categorie, etat, site, compte]);
  useEffect(() => { const t = setTimeout(charger, 250); return () => clearTimeout(t); }, [charger]);

  const ajouterCategorie = async () => {
    const libelle = window.prompt("Nouvelle catégorie d'équipement :");
    if (!libelle?.trim()) return null;
    try { await apiClient.post("/me/parc-categories", { libelle: libelle.trim(), compte_client_id: compte || null }); await chargerCategories(); return libelle.trim(); }
    catch (e) { toast.error(erreur(e, "Catégorie refusée")); return null; }
  };
  const supprimer = async (e) => {
    if (!window.confirm(`Supprimer l'équipement ${e.numero_inventaire} ?`)) return;
    try { await apiClient.delete(`/me/parc/equipements/${e.id}`); toast.success("Équipement supprimé"); charger(); }
    catch (x) { toast.error(erreur(x, "Suppression impossible")); }
  };
  // L'Admin / le Superviseur crée dans le parc du client choisi
  const doitChoisir = clients.admin && !compte;
  const equipements = donnees?.equipements || [];

  if (refus) return <div className="m-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-amber-900">{refus}</div>;
  return (
    <div className="mx-auto max-w-6xl space-y-4 p-3 sm:p-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="flex items-center gap-2 text-xl font-bold text-slate-800 sm:text-2xl"><Monitor className="h-6 w-6 text-indigo-600" /> Parc informatique</h1>
        {clients.admin && (
          <select className={`${champ} w-auto sm:ml-auto`} value={compte} onChange={(e) => setCompte(e.target.value)} data-testid="parc-client">
            <option value="">Tous les clients</option>
            {clients.items.map((c) => <option key={c.id} value={c.id}>{c.nom}{c.code ? ` · ${c.code}` : ""}</option>)}
          </select>
        )}
      </div>
      <div className="flex gap-1 border-b border-slate-200">
        {[["equipements", `Équipements (${donnees?.total ?? "…"})`], ["interventions", "Interventions"]].map(([k, l]) => (
          <button key={k} type="button" onClick={() => setOnglet(k)} data-testid={`parc-onglet-${k}`}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${onglet === k ? "border-indigo-600 font-semibold text-indigo-700" : "border-transparent text-slate-500"}`}>{l}</button>
        ))}
      </div>

      {onglet === "interventions" ? (
        <ParcInterventions compteClientId={compte} equipements={equipements} onChange={charger} />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={() => setEtat("")} className={`rounded-full px-3 py-1 text-xs ring-1 ${!etat ? "bg-slate-800 text-white ring-slate-800" : "bg-white ring-slate-300"}`}>Tous ({donnees?.total ?? 0})</button>
            {Object.entries(ETATS).map(([k, [l, cls]]) => (
              <button key={k} type="button" onClick={() => setEtat(etat === k ? "" : k)}
                className={`rounded-full px-3 py-1 text-xs ring-1 ${etat === k ? "ring-2 ring-indigo-500" : "ring-transparent"} ${cls}`}>{l} ({donnees?.compte?.[k] ?? 0})</button>
            ))}
            <div className="flex w-full flex-wrap gap-2 sm:ml-auto sm:w-auto">
              <Button size="sm" variant="outline" onClick={() => telecharger("/me/parc/equipements/export.csv", "parc-informatique.csv", filtres)}><Download className="mr-1 h-4 w-4" /> Export CSV</Button>
              <Button size="sm" variant="outline" onClick={() => setImporter(true)} disabled={doitChoisir} title={doitChoisir ? "Choisissez d'abord le client" : ""}><Upload className="mr-1 h-4 w-4" /> Import CSV</Button>
              <Button size="sm" onClick={() => setEdition("nouveau")} disabled={doitChoisir} title={doitChoisir ? "Choisissez d'abord le client" : ""} data-testid="parc-equipement-nouveau"><Plus className="mr-1 h-4 w-4" /> Équipement</Button>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <div className="relative min-w-[200px] flex-1">
              <Search className="absolute left-2 top-2 h-4 w-4 text-slate-400" />
              <input className={`${champ} pl-8`} placeholder="Inventaire, modèle, série, IP, MAC, utilisateur, lieu…" value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            <select className={`${champ} w-auto`} value={categorie} onChange={(e) => setCategorie(e.target.value)}>
              <option value="">Toutes les catégories</option>
              {categories.map((c) => <option key={c} value={c}>{c}{donnees?.par_categorie?.[c] ? ` (${donnees.par_categorie[c]})` : ""}</option>)}
            </select>
            <select className={`${champ} w-auto`} value={site} onChange={(e) => setSite(e.target.value)}>
              <option value="">Tous les sites</option>
              {(donnees?.sites || []).map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs text-slate-500">
                <tr><th className="p-2">Inventaire</th><th className="p-2">Équipement</th><th className="p-2">Série / MAC / IP</th><th className="p-2">Lieu · utilisateur</th>
                  <th className="p-2">État</th><th className="p-2">Dernière intervention</th><th className="p-2" /></tr>
              </thead>
              <tbody>
                {!donnees && <tr><td colSpan={7} className="p-4 text-center"><Loader2 className="inline h-4 w-4 animate-spin" /></td></tr>}
                {donnees && equipements.length === 0 && <tr><td colSpan={7} className="p-4 text-center text-slate-400">Aucun équipement.{doitChoisir ? " Choisissez un client pour en ajouter ou en importer." : ""}</td></tr>}
                {equipements.map((e) => (
                  <tr key={e.id} className="cursor-pointer border-t border-slate-100 align-top hover:bg-slate-50" onClick={() => setFiche(e.id)}>
                    <td className="p-2 font-mono text-xs">{e.numero_inventaire}{clients.admin && !compte && <span className="block font-sans text-[11px] text-slate-500">{e.tenant_id ? e.client_nom : <span className="text-amber-700">À affecter (Loois)</span>}</span>}</td>
                    <td className="p-2">{e.categorie}<span className="block text-[11px] text-slate-500">{[e.fabricant, e.modele].filter(Boolean).join(" ")}{e.nom_hote ? ` · ${e.nom_hote}` : ""}</span></td>
                    <td className="p-2 font-mono text-[11px]">{e.numero_serie || "—"}<span className="block">{e.adresse_mac || ""}</span><span className="block">{e.adresse_ip || ""}</span></td>
                    <td className="p-2 text-xs">{lieu(e) || "—"}<span className="block text-slate-500">{e.utilisateur_affecte || ""}</span></td>
                    <td className="p-2"><Etat etat={e.etat} /></td>
                    <td className="p-2 text-xs">{e.derniere_intervention ? <>{e.derniere_intervention.numero}<span className="block text-slate-500">{dateFr(e.derniere_intervention.date)}</span></> : "—"}</td>
                    <td className="p-2" onClick={(x) => x.stopPropagation()}>
                      <button type="button" title="Supprimer" onClick={() => supprimer(e)} className="p-1 text-rose-500 hover:text-rose-700"><Trash2 className="h-4 w-4" /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {edition && (
        <FormulaireEquipement key={edition === "nouveau" ? "nouveau" : edition.id} equipement={edition === "nouveau" ? null : edition}
          categories={categories} compteClientId={compte} clients={clients} onAjoutCategorie={ajouterCategorie} onClose={() => setEdition(null)}
          onEnregistre={async (e) => {
            // e = null : photo ajoutée / supprimée -> équipement relu, formulaire gardé ouvert
            if (!e && edition?.id) { try { setEdition((await apiClient.get(`/me/parc/equipements/${edition.id}`)).data); } catch { /* supprimé */ } charger(); return; }
            setEdition(null); charger(); if (e?.id) setFiche(e.id);
          }} />
      )}
      {fiche && !edition && <FicheEquipement id={fiche} equipements={equipements} onClose={() => setFiche(null)} onModifier={(e) => setEdition(e)} onChange={charger} />}
      {importer && <ImportCsv compteClientId={compte} onClose={() => setImporter(false)} onImporte={charger} />}
    </div>
  );
}
