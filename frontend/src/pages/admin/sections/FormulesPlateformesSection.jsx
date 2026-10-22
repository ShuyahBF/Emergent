/*
  Lot 227 — Paramètres : « Formules des plateformes » — abonnements vendus aux utilisateurs des plateformes (Paiement Mobile…).
    - Vitrine : plateforme (liste), nom, description, prix en FCFA, durée en jours (30 par défaut), fonction débloquée (liste), active.
    - Chaque paiement (page PawaPay hébergée) active la formule pour sa durée ; un nouveau paiement avant l'échéance S'AJOUTE au temps restant.
    - Parrainage : jours offerts à CHACUN (parrain et filleul) quand le filleul paie sa première formule (0 = désactivé).
    - Suivi : abonnés actifs, ventes et chiffre d'affaires par formule ; une formule déjà vendue n'est jamais supprimée, elle est désactivée.
  Lot 228 : la fonction « OCR » de la formule débloque les lectures de plaques de marchands et d'ordonnances ; refusées sans abonnement actif
  (message avec le nom et le prix de la formule) ; limite de lectures par jour réglable ici.
  Lot 229 : fonction « Transcription vocale » (notes de 30 s au plus, limite par jour réglable), cumulable avec l'OCR sur une même formule.
  Lot 233 : fonction « Archives en ligne chiffrées » (documents chiffrés par le site de l'utilisateur, gardés dans R2 : SAWALI ne peut pas les lire) ;
  espace par utilisateur réglable ici (200 Mo au départ).
  Lot 232 : paiement PI-SPI manuel des abonnements — l'utilisateur paie avec le QR de la banque (réglages « Encaissement PI-SPI »),
  déclare la référence bancaire, et l'administrateur CONFIRME ici (la formule s'active alors, l'encaissement entre au registre PI-SPI).
  Lot 246 : tableau « Cartes virtuelles — coût de chaque génération » (GET /admin/cartes-plateformes/generations, export CSV).
  API : GET/POST/PUT/DELETE /admin/formules-plateformes, GET /admin/formules-plateformes/pispi, POST …/pispi/{reference}/confirmer|refuser, PUT /admin/formules-plateformes-reglages (backend/routes/formules_plateformes.py).
*/
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const fcfa = (n) => `${Number(n || 0).toLocaleString("fr-FR")} FCFA`;
const VIDE = { plateforme: "", nom: "", description: "", prix: "", duree_jours: 30, fonctions: ["ocr_ordonnances"], actif: true, ordre: 0 };

// Demandes de paiement PI-SPI à traiter (en haut de la rubrique : ce sont des actions à faire). « À vérifier » = référence bancaire déclarée.
function DemandesPispi({ rafraichir }) {
  const [demandes, setDemandes] = useState(null);
  const charger = useCallback(() => apiClient.get("/admin/formules-plateformes/pispi").then((r) => setDemandes(r.data.demandes)).catch(() => setDemandes([])), []);
  useEffect(() => { charger(); }, [charger]);
  const traiter = async (x, action) => {
    const verbe = action === "confirmer" ? "Confirmer la réception du paiement" : "Refuser la demande";
    if (!window.confirm(`${verbe} de ${x.utilisateur || "l'utilisateur"} (${fcfa(x.montant)}, formule « ${x.formule || "?"} ») ?`)) return;
    try {
      await apiClient.post(`/admin/formules-plateformes/pispi/${x.reference}/${action}`, action === "confirmer" ? {} : undefined);
      toast.success(action === "confirmer" ? "Paiement confirmé : formule activée" : "Demande refusée");
      charger();
      rafraichir();
    } catch (err) { toast.error(err?.response?.data?.detail || "Action impossible"); }
  };
  if (!demandes?.length) return null;
  return (
    <div className="rounded-lg bg-sky-50 p-3 ring-1 ring-sky-200" data-testid="pispi-demandes">
      <p className="text-sm font-semibold text-sky-900">🏦 Paiements PI-SPI à traiter ({demandes.length})</p>
      <p className="mb-2 text-xs text-sky-900">Vérifiez la référence bancaire dans le relevé de la banque avant de confirmer.</p>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead><tr className="text-left text-slate-500"><th className="p-1">Utilisateur</th><th>Formule</th><th>Montant</th><th>Référence</th><th>Réf. bancaire déclarée</th><th>État</th><th /></tr></thead>
          <tbody>
            {demandes.map((x) => (
              <tr key={x.reference} className="border-t border-sky-100">
                <td className="p-1">{x.utilisateur}<span className="block text-slate-500">{x.plateforme}</span></td>
                <td>{x.formule}</td><td>{fcfa(x.montant)}</td><td className="font-mono">{x.reference}</td>
                <td className="font-mono">{x.reference_bancaire || "—"}</td>
                <td>{x.statut === "pispi_verification" ? <b className="text-emerald-700">À vérifier</b> : <span className="text-slate-500">Virement attendu</span>}</td>
                <td className="boutons-distincts flex gap-1 p-1">
                  <button type="button" onClick={() => traiter(x, "confirmer")} className="rounded bg-emerald-600 px-2 py-1 text-white">Confirmer</button>
                  <button type="button" onClick={() => traiter(x, "refuser")} className="rounded border border-slate-300 px-2 py-1">Refuser</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// Lot 246 — Coût de chaque génération de carte virtuelle (lu dans le journal de l'IA) : tableau sur 7/30/90 jours + export CSV.
function CoutCartes() {
  const [jours, setJours] = useState(30);
  const [d, setD] = useState(null);
  useEffect(() => {
    setD(null);
    apiClient.get(`/admin/cartes-plateformes/generations?jours=${jours}`).then((r) => setD(r.data)).catch(() => setD({ generations: [], total: { generations: 0, cout_usd: 0 } }));
  }, [jours]);
  // Export CSV : téléchargement par le navigateur (le fichier est construit par le serveur)
  const exporter = async () => {
    try {
      const r = await apiClient.get(`/admin/cartes-plateformes/generations?jours=${jours}&format=csv`, { responseType: "blob" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(r.data); a.download = "cartes-generations.csv"; a.click();
    } catch { toast.error("Export impossible"); }
  };
  return (
    <div className="rounded-lg bg-white p-3 ring-1 ring-slate-200" data-testid="cout-cartes">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm font-semibold">🎨 Cartes virtuelles — coût de chaque génération</p>
        <select value={jours} onChange={(e) => setJours(Number(e.target.value))} className="rounded border border-slate-300 px-2 py-1 text-xs" data-testid="cout-cartes-jours">
          <option value={7}>7 jours</option><option value={30}>30 jours</option><option value={90}>90 jours</option>
        </select>
        <button type="button" onClick={exporter} className="rounded border border-slate-300 px-2 py-1 text-xs">Exporter en CSV</button>
      </div>
      {!d ? <p className="mt-2 text-xs text-slate-500">Chargement…</p> : (
        <>
          <p className="mt-2 text-xs text-slate-700" data-testid="cout-cartes-total">
            {d.total.generations} génération(s) · coût estimé total : <b>{Number(d.total.cout_usd).toLocaleString("fr-FR", { minimumFractionDigits: 2 })} $</b>
            {" "}(tarifs publics d'OpenAI ; la facture réelle est sur platform.openai.com)
          </p>
          <div className="mt-2 max-h-72 overflow-auto">
            <table className="w-full text-xs">
              <thead><tr className="text-left text-slate-500"><th className="p-1">Date (UTC)</th><th>Plateforme</th><th>Utilisateur</th><th>Thème</th><th>Forme</th><th>Moteur</th><th className="text-right">Coût</th></tr></thead>
              <tbody>
                {d.generations.map((g, i) => (
                  <tr key={i} className="border-t border-slate-100">
                    <td className="p-1 whitespace-nowrap">{(g.date || "").replace("T", " ").replace("Z", "")}</td><td>{g.plateforme}</td><td>{g.utilisateur}</td>
                    <td>{g.theme}</td><td>{g.style}</td><td>{g.moteur}</td><td className="text-right">{Number(g.cout_usd).toFixed(3)} $</td>
                  </tr>
                ))}
                {!d.generations.length && <tr><td colSpan={7} className="p-2 text-slate-500">Aucune carte générée sur cette période.</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

export default function FormulesPlateformesSection() {
  const [d, setD] = useState(null);
  const [edition, setEdition] = useState(null);       // formule en cours de saisie (id absent = nouvelle)
  const [jours, setJours] = useState(7);
  const [ocrJour, setOcrJour] = useState(30);        // lot 228 : lectures OCR par jour et par utilisateur
  const [voixJour, setVoixJour] = useState(10);      // lot 229 : notes vocales transcrites par jour et par utilisateur
  const [cartesJour, setCartesJour] = useState(9);  // lot 242 : images de cartes virtuelles générées par jour et par utilisateur
  const [archivesMo, setArchivesMo] = useState(200); // lot 233 : espace d'archives en ligne (chiffrées) par utilisateur, en Mo
  const [gratuitMo, setGratuitMo] = useState(50);       // lot 277 : espace en ligne OFFERT sans abonnement, en Mo
  const [gratuitNombre, setGratuitNombre] = useState(30); // lot 277 : documents en ligne offerts sans abonnement
  const [envoi, setEnvoi] = useState(false);

  const charger = useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/formules-plateformes");
      setD(r.data);
      setJours(r.data.parrainage_jours);
      setOcrJour(r.data.ocr_par_jour);
      setVoixJour(r.data.voix_par_jour);
      setCartesJour(r.data.cartes_par_jour);
      setArchivesMo(r.data.archives_mo);
      setGratuitMo(r.data.archives_gratuit_mo ?? 50);
      setGratuitNombre(r.data.archives_gratuit_nombre ?? 30);
    } catch (e) { toast.error(e?.response?.data?.detail || "Formules indisponibles (réservé à l'administrateur principal)"); }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  const enregistrer = async (e) => {
    e.preventDefault();
    setEnvoi(true);
    const corps = { plateforme: edition.plateforme, nom: edition.nom, description: edition.description, prix: Number(edition.prix),
      duree_jours: Number(edition.duree_jours), fonctions: edition.fonctions, actif: edition.actif, ordre: Number(edition.ordre || 0) };
    try {
      if (edition.id) await apiClient.put(`/admin/formules-plateformes/${edition.id}`, corps);
      else await apiClient.post("/admin/formules-plateformes", corps);
      toast.success("Formule enregistrée");
      setEdition(null);
      charger();
    } catch (err) { toast.error(err?.response?.data?.detail || "Enregistrement impossible"); } finally { setEnvoi(false); }
  };
  const supprimer = async (f) => {
    if (!window.confirm(`Supprimer la formule « ${f.nom} » ? (désactivée seulement si elle a déjà été vendue)`)) return;
    try {
      const r = await apiClient.delete(`/admin/formules-plateformes/${f.id}`);
      toast.success(r.data.desactivee ? "Formule déjà vendue : désactivée" : "Formule supprimée");
      charger();
    } catch (err) { toast.error(err?.response?.data?.detail || "Suppression impossible"); }
  };
  const enregistrerParrainage = async () => {
    try { await apiClient.put("/admin/formules-plateformes-reglages", { parrainage_jours: Number(jours), ocr_par_jour: Number(ocrJour), voix_par_jour: Number(voixJour), cartes_par_jour: Number(cartesJour), archives_mo: Number(archivesMo), archives_gratuit_mo: Number(gratuitMo), archives_gratuit_nombre: Number(gratuitNombre) }); toast.success("Réglages enregistrés"); charger(); }
    catch (err) { toast.error(err?.response?.data?.detail || "Enregistrement impossible"); }
  };

  if (!d) return <p className="text-xs text-slate-500">Chargement des formules…</p>;
  const champ = (cle) => (e) => setEdition({ ...edition, [cle]: e.target.value });
  return (
    <div className="space-y-4" data-testid="formules-plateformes">
      <DemandesPispi rafraichir={charger} />
      <CoutCartes />
      <p className="text-xs text-slate-600">
        Formules vendues aux utilisateurs des plateformes (ex. « OCR Ordonnances » dans Paiement Mobile). Le paiement passe par la page PawaPay
        hébergée et active la formule tout seul ; le paiement PI-SPI (QR de la banque, réglé dans « Encaissement PI-SPI ») se confirme à la main
        ci-dessus. Payer avant l'échéance <b>ajoute</b> la durée au temps restant.
      </p>
      {!d.pawapay_actif && <p className="rounded-lg bg-amber-50 p-2 text-xs text-amber-900 ring-1 ring-amber-200">PawaPay n'est pas activé : les achats sont refusés tant qu'il ne l'est pas (rubrique PawaPay).</p>}

      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 text-center text-xs">
        <div className="rounded-lg ring-1 ring-slate-200 p-2"><p className="text-slate-500">Utilisateurs suivis</p><p className="text-lg font-bold">{d.membres}</p></div>
        <div className="rounded-lg ring-1 ring-slate-200 p-2"><p className="text-slate-500">Abonnés actifs</p><p className="text-lg font-bold">{d.formules.reduce((n, f) => n + f.abonnes_actifs, 0)}</p></div>
        <div className="rounded-lg ring-1 ring-slate-200 p-2 col-span-2 md:col-span-1"><p className="text-slate-500">Chiffre d'affaires</p><p className="text-lg font-bold">{fcfa(d.formules.reduce((n, f) => n + f.chiffre, 0))}</p></div>
      </div>

      <div className="flex flex-wrap items-end gap-2 rounded-lg ring-1 ring-slate-200 p-3 text-xs">
        <label className="flex flex-col gap-1">Parrainage : jours offerts à chacun (parrain et filleul)
          <input type="number" min={0} max={90} value={jours} onChange={(e) => setJours(e.target.value)} className="w-28 rounded border border-slate-300 px-2 py-1" data-testid="parrainage-jours" />
        </label>
        <label className="flex flex-col gap-1">OCR : lectures par jour et par utilisateur
          <input type="number" min={1} max={500} value={ocrJour} onChange={(e) => setOcrJour(e.target.value)} className="w-28 rounded border border-slate-300 px-2 py-1" data-testid="ocr-par-jour" />
        </label>
        <label className="flex flex-col gap-1">Voix : notes transcrites par jour et par utilisateur
          <input type="number" min={1} max={200} value={voixJour} onChange={(e) => setVoixJour(e.target.value)} className="w-28 rounded border border-slate-300 px-2 py-1" data-testid="voix-par-jour" />
        </label>
        <label className="flex flex-col gap-1">Cartes virtuelles : images générées par jour et par utilisateur
          <input type="number" min={1} max={100} value={cartesJour} onChange={(e) => setCartesJour(e.target.value)} className="w-28 rounded border border-slate-300 px-2 py-1" data-testid="cartes-par-jour" />
        </label>
        <label className="flex flex-col gap-1">Archives en ligne : espace par utilisateur (Mo)
          <input type="number" min={10} max={5000} value={archivesMo} onChange={(e) => setArchivesMo(e.target.value)} className="w-28 rounded border border-slate-300 px-2 py-1" data-testid="archives-mo" />
        </label>
        {/* Lot 277 : espace en ligne OFFERT à tout utilisateur sans abonnement (ses papiers ne dépendent plus de son navigateur) */}
        <label className="flex flex-col gap-1">Archives en ligne offertes (sans abonnement) : espace (Mo)
          <input type="number" min={0} max={1000} value={gratuitMo} onChange={(e) => setGratuitMo(e.target.value)} className="w-28 rounded border border-slate-300 px-2 py-1" data-testid="archives-gratuit-mo" />
        </label>
        <label className="flex flex-col gap-1">Archives en ligne offertes : nombre de documents
          <input type="number" min={0} max={1000} value={gratuitNombre} onChange={(e) => setGratuitNombre(e.target.value)} className="w-28 rounded border border-slate-300 px-2 py-1" data-testid="archives-gratuit-nombre" />
        </label>
        <button type="button" onClick={enregistrerParrainage} className="rounded bg-slate-800 px-3 py-1.5 text-white">Enregistrer</button>
        <span className="text-slate-500">Parrainage : 0 = pas de récompense (donnés à la première formule payée du filleul). OCR et voix : protègent le coût de l'IA ; refusés sans abonnement.</span>
      </div>

      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold">Formules ({d.formules.length})</p>
        <button type="button" onClick={() => setEdition({ ...VIDE, plateforme: d.plateformes[0]?.code || "" })} className="rounded bg-emerald-600 px-3 py-1.5 text-xs text-white" data-testid="formule-ajouter">+ Nouvelle formule</button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead><tr className="text-left text-slate-500"><th className="p-1">Plateforme</th><th>Formule</th><th>Prix</th><th>Durée</th><th>Abonnés</th><th>Ventes</th><th>CA</th><th>État</th><th /></tr></thead>
          <tbody>
            {d.formules.length === 0 && <tr><td colSpan={9} className="p-3 text-slate-500">Aucune formule. Créez « OCR Ordonnances » pour Paiement Mobile.</td></tr>}
            {d.formules.map((f) => (
              <tr key={f.id} className="border-t border-slate-100">
                <td className="p-1">{f.plateforme}</td>
                <td><b>{f.nom}</b><br /><span className="text-slate-500">{(f.fonctions || []).map((x) => d.fonctions[x] || x).join(", ")}</span></td>
                <td>{fcfa(f.prix)}</td><td>{f.duree_jours} j</td><td>{f.abonnes_actifs}</td><td>{f.ventes}</td><td>{fcfa(f.chiffre)}</td>
                <td>{f.actif ? <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-emerald-800">Active</span> : <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">Inactive</span>}</td>
                <td className="whitespace-nowrap text-right">
                  <button type="button" onClick={() => setEdition({ ...f, prix: String(f.prix), description: f.description || "" })} className="px-1" aria-label={`Modifier ${f.nom}`}>✏️</button>
                  <button type="button" onClick={() => supprimer(f)} className="px-1" aria-label={`Supprimer ${f.nom}`}>🗑</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {edition && (
        <form onSubmit={enregistrer} className="space-y-2 rounded-lg ring-1 ring-slate-300 bg-slate-50 p-3 text-xs" data-testid="formule-form">
          <p className="text-sm font-semibold">{edition.id ? "Modifier la formule" : "Nouvelle formule"}</p>
          <div className="grid gap-2 md:grid-cols-2">
            <label className="flex flex-col gap-1">Plateforme
              <select required value={edition.plateforme} onChange={champ("plateforme")} className="rounded border border-slate-300 px-2 py-1.5">
                <option value="" disabled>Choisir…</option>
                {d.plateformes.map((p) => <option key={p.code} value={p.code}>{p.nom} ({p.code})</option>)}
              </select></label>
            <label className="flex flex-col gap-1">Nom affiché
              <input required minLength={2} maxLength={60} value={edition.nom} onChange={champ("nom")} placeholder="OCR Ordonnances" className="rounded border border-slate-300 px-2 py-1.5" /></label>
            <label className="flex flex-col gap-1">Prix (FCFA)
              <input required type="number" min={100} value={edition.prix} onChange={champ("prix")} className="rounded border border-slate-300 px-2 py-1.5" /></label>
            <label className="flex flex-col gap-1">Durée (jours)
              <input required type="number" min={1} max={366} value={edition.duree_jours} onChange={champ("duree_jours")} className="rounded border border-slate-300 px-2 py-1.5" /></label>
            <fieldset className="flex flex-col gap-1">
              <legend>Fonctions débloquées (une ou plusieurs)</legend>
              {Object.entries(d.fonctions).map(([k, n]) => (
                <label key={k} className="flex items-center gap-2 rounded border border-slate-300 bg-white px-2 py-1.5">
                  <input type="checkbox" checked={edition.fonctions.includes(k)}
                    onChange={(e) => setEdition({ ...edition, fonctions: e.target.checked ? [...edition.fonctions, k] : edition.fonctions.filter((x) => x !== k) })} />{n}
                </label>
              ))}
            </fieldset>
            <label className="flex flex-col gap-1">Ordre d'affichage
              <input type="number" min={0} max={999} value={edition.ordre} onChange={champ("ordre")} className="rounded border border-slate-300 px-2 py-1.5" /></label>
          </div>
          <label className="flex flex-col gap-1">Description (affichée à l'utilisateur)
            <input maxLength={300} value={edition.description} onChange={champ("description")} className="rounded border border-slate-300 px-2 py-1.5" /></label>
          <label className="flex items-center gap-2"><input type="checkbox" checked={edition.actif} onChange={(e) => setEdition({ ...edition, actif: e.target.checked })} />Formule active (proposée à l'achat)</label>
          <div className="flex gap-2">
            <button type="submit" disabled={envoi} className="rounded bg-emerald-600 px-3 py-1.5 text-white">{envoi ? "Patientez…" : "Enregistrer"}</button>
            <button type="button" onClick={() => setEdition(null)} className="rounded border border-slate-300 px-3 py-1.5">Annuler</button>
          </div>
        </form>
      )}
    </div>
  );
}
