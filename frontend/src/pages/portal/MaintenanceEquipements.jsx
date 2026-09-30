/*
  Lot 41 — « Maintenance des équipements » : matériel confié par un client pour réparation.
  Chaque dépôt est une fiche : numéro automatique (MNT-<CODE>-<AAAA>-0001), client, date de
  réception, type de matériel (liste extensible), état (mauvais, moyen, bon), motif, diagnostic,
  remplacement de pièces, dates d'entrée et de sortie, statut (reçu → rendu).
  Bon de dépôt / de restitution imprimable. Fonction activable (SMART Communications).
  Lot 43 — client choisi parmi les COMPTES CLIENTS (Admin / Superviseur ; les autres comptes :
  leurs contacts), téléphone = numéro qui reçoit les alertes de la société ; prix du
  diagnostic (10 000 F par défaut) et équipe ; photos annotées, envoi WhatsApp, lien de
  paiement et « Facturer » (components/MaintenanceActions.jsx).
  Lot 47 — intervention en cours / arrêtée / terminée (badges, boutons dans la liste et la
  fiche, historique), filtre et compteur « Prêtes à facturer », état et durée sur le bon.
  API : /me/maintenance, /me/maintenance-types, /me/maintenance-clients (backend/routes/maintenance_equipements.py).
*/
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Loader2, Plus, Printer, Search, Trash2, Wrench, X } from "lucide-react";
import { apiClient } from "@/lib/api";
import { Button } from "@/components/ui/button";
import MaintenanceActions, { BadgesIntervention, BoutonsIntervention, INTERVENTIONS, dateHeureFr, dureeFr } from "@/components/MaintenanceActions";   // lots 43 et 47

const STATUTS = {
  recu: ["Reçu", "bg-slate-100 text-slate-700"],
  diagnostic: ["En diagnostic", "bg-sky-100 text-sky-700"],
  reparation: ["En réparation", "bg-amber-100 text-amber-800"],
  pret: ["Prêt à rendre", "bg-emerald-100 text-emerald-700"],
  rendu: ["Rendu", "bg-indigo-100 text-indigo-700"],
};
const ETATS = { mauvais: ["Mauvais", "text-rose-700"], moyen: ["Moyen", "text-amber-700"], bon: ["Bon", "text-emerald-700"] };
const champ = "w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500";
const erreur = (e, d) => { const x = e?.response?.data?.detail; return Array.isArray(x) ? x.map((i) => i.msg).join(" ; ") : x || d; };
const dateFr = (d) => (d ? new Date(d).toLocaleDateString("fr-FR") : "—");
const aujourdhui = () => new Date().toISOString().slice(0, 10);
const fcfa = (n) => `${Number(n || 0).toLocaleString("fr-FR")} FCFA`;
const VIDE = { compte_client_id: "", contact_id: "", client_nom: "", client_telephone: "", date_reception: aujourdhui(), type_materiel: "",
  marque_modele: "", numero_serie: "", etat_materiel: "moyen", motif: "", diagnostic: "", remplacement_pieces: false,
  pieces: "", observations: "", date_entree: aujourdhui(), date_sortie: "", statut: "recu",
  prix_diagnostic: 10000, equipe: "" };   // lot 43 : prix du diagnostic par défaut, noms de l'équipe

// Bon de dépôt / de restitution (imprimé avec le navigateur)
function Bon({ fiche, onClose }) {
  return (
    <div className="fixed inset-0 z-[80] bg-black/40 flex items-center justify-center p-4 print:bg-white print:p-0">
      <div className="bg-white rounded-xl w-full max-w-2xl p-6 space-y-3 text-sm print:shadow-none" id="bon-maintenance">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-lg font-bold">{fiche.date_sortie ? "Bon de restitution" : "Bon de dépôt"} — {fiche.numero}</h2>
            <p className="text-xs text-slate-500">Maintenance des équipements</p>
          </div>
          <div className="flex gap-2 print:hidden">
            <Button size="sm" onClick={() => window.print()}><Printer className="h-4 w-4 mr-1" /> Imprimer</Button>
            <Button size="sm" variant="outline" onClick={onClose}><X className="h-4 w-4" /></Button>
          </div>
        </div>
        <table className="w-full text-sm">
          <tbody>
            {[["Client", `${fiche.client_nom}${fiche.client_telephone ? ` · ${fiche.client_telephone}` : ""}`],
              ["Reçu le", dateFr(fiche.date_reception)], ["Matériel", `${fiche.type_materiel}${fiche.marque_modele ? ` — ${fiche.marque_modele}` : ""}`],
              ["N° de série", fiche.numero_serie || "—"], ["État à la réception", ETATS[fiche.etat_materiel]?.[0]],
              ["Motif", fiche.motif], ["Diagnostic", fiche.diagnostic || "—"],
              ["Remplacement de pièces", fiche.remplacement_pieces ? `Oui — ${fiche.pieces || ""}` : "Non"],
              ["Entrée en atelier", dateFr(fiche.date_entree)], ["Sortie", dateFr(fiche.date_sortie)],
              ["Équipe", fiche.equipe || "—"], ["Prix du diagnostic", fcfa(fiche.prix_diagnostic)],
              ["Observations", fiche.observations || "—"],
              // Lot 47 — état de l'intervention et durée totale, s'il y en a eu
              ...(fiche.etat_intervention ? [["Intervention", INTERVENTIONS[fiche.etat_intervention]?.[0]]] : []),
              ...(fiche.duree_totale_minutes > 0 ? [["Durée d'intervention", dureeFr(fiche.duree_totale_minutes)]] : [])].map(([l, v]) => (
              <tr key={l} className="border-b border-slate-100 align-top"><td className="py-1.5 pr-3 font-semibold w-48">{l}</td><td className="py-1.5 whitespace-pre-line">{v}</td></tr>
            ))}
          </tbody>
        </table>
        {/* Lot 47 — historique des interventions */}
        {(fiche.interventions || []).length > 0 && (
          <table className="w-full text-xs">
            <thead className="text-left text-slate-500"><tr><th className="py-1">Début</th><th>Fin</th><th>Durée</th><th>Équipe</th></tr></thead>
            <tbody>
              {fiche.interventions.map((i) => (
                <tr key={i.id} className="border-t border-slate-100">
                  <td className="py-1">{dateHeureFr(i.debut)}</td>
                  <td>{i.fin ? `${dateHeureFr(i.fin)} (${INTERVENTIONS[i.etat_fin]?.[0] || ""})` : "en cours"}</td>
                  <td>{i.fin ? dureeFr(i.duree_minutes) : "—"}</td><td>{i.equipe || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {/* Lot 43 — photos de l'équipement ou des pièces */}
        {(fiche.photos || []).length > 0 && (
          <div className="flex flex-wrap gap-2">{fiche.photos.map((p) => <img key={p.id} src={p.url} alt="" className="h-24 w-24 object-cover rounded" />)}</div>
        )}
        <div className="grid grid-cols-2 gap-6 pt-6 text-xs text-slate-500">
          <p>Signature du client :</p><p>Signature du technicien :</p>
        </div>
      </div>
    </div>
  );
}

function FormulaireFiche({ fiche, types, clients, onAjoutType, onClose, onEnregistre, onRafraichir }) {
  const [f, setF] = useState(() => (fiche ? { ...VIDE, ...fiche, contact_id: fiche.contact_id || "",
    compte_client_id: fiche.compte_client_id || "", equipe: fiche.equipe || "",
    prix_diagnostic: fiche.prix_diagnostic ?? 10000,
    date_reception: (fiche.date_reception || "").slice(0, 10), date_entree: (fiche.date_entree || "").slice(0, 10),
    date_sortie: (fiche.date_sortie || "").slice(0, 10) } : { ...VIDE }));
  const [occupe, setOccupe] = useState(false);
  const maj = (x) => setF((p) => ({ ...p, ...x }));

  const enregistrer = async () => {
    setOccupe(true);
    const corps = { ...f, contact_id: f.contact_id || null, compte_client_id: f.compte_client_id || null,
      prix_diagnostic: Number(f.prix_diagnostic) || 0, date_sortie: f.date_sortie || null, date_entree: f.date_entree || null };
    delete corps.photos; delete corps.lien_paiement; delete corps.facture; delete corps.envois_whatsapp;
    // Lot 47 — l'intervention se change par ses boutons, jamais par l'enregistrement de la fiche
    ["etat_intervention", "interventions", "intervention_ouverte", "duree_totale_minutes", "prete_a_facturer"].forEach((k) => delete corps[k]);
    try {
      const r = fiche ? await apiClient.put(`/me/maintenance/${fiche.id}`, corps) : await apiClient.post("/me/maintenance", corps);
      toast.success(fiche ? "Fiche mise à jour" : `Fiche ${r.data.numero} créée`);
      onEnregistre(r.data);
    } catch (e) { toast.error(erreur(e, "Enregistrement impossible")); }
    finally { setOccupe(false); }
  };

  return (
    <div className="fixed inset-0 z-[75] bg-black/40 flex items-center justify-center p-3">
      <div className="bg-white rounded-xl w-full max-w-3xl max-h-[92vh] overflow-y-auto p-5 space-y-3" data-testid="maintenance-form">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-slate-800">{fiche ? `Fiche ${fiche.numero}` : "Nouvelle fiche de dépôt"}</h2>
          <button type="button" onClick={onClose}><X className="h-5 w-5" /></button>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {/* Lot 43 — comptes clients (tenants) pour l'Admin / le Superviseur, contacts sinon ;
              le téléphone repris est celui qui reçoit les alertes et messages de la société */}
          <label className="text-xs text-slate-600">{clients.type === "compte" ? "Client (compte SAWALI)" : "Client (annuaire)"}
            <select className={champ} value={f.compte_client_id ? `compte:${f.compte_client_id}` : f.contact_id ? `contact:${f.contact_id}` : ""}
              onChange={(e) => {
                const [t, id] = e.target.value.split(":");
                const c = clients.items.find((x) => x.type === t && x.id === id);
                maj({ compte_client_id: t === "compte" ? id : "", contact_id: t === "contact" ? id : "",
                  client_telephone: c?.telephone || "", client_nom: c ? c.nom : f.client_nom });
              }} data-testid="maintenance-client">
              <option value="">— Saisir le client à la main —</option>
              {clients.items.map((c) => <option key={`${c.type}:${c.id}`} value={`${c.type}:${c.id}`}>{c.nom}{c.code ? ` · ${c.code}` : ""}</option>)}
            </select>
          </label>
          {!f.contact_id && !f.compte_client_id && (
            <label className="text-xs text-slate-600">Nom du client *
              <input className={champ} value={f.client_nom} onChange={(e) => maj({ client_nom: e.target.value })} />
            </label>
          )}
          <label className="text-xs text-slate-600">Téléphone
            <input className={champ} value={f.client_telephone} onChange={(e) => maj({ client_telephone: e.target.value })}
              placeholder={f.compte_client_id ? "numéro des alertes de la société" : f.contact_id ? "celui de l'annuaire par défaut" : ""} />
            {f.compte_client_id && <span className="text-[10px] text-slate-400">Numéro qui reçoit les alertes et messages de la société</span>}
          </label>
          <label className="text-xs text-slate-600">Date de réception
            <input type="date" className={champ} value={f.date_reception} onChange={(e) => maj({ date_reception: e.target.value })} />
          </label>
          <label className="text-xs text-slate-600">Type de matériel *
            <div className="flex gap-1">
              <select className={champ} value={f.type_materiel} onChange={(e) => maj({ type_materiel: e.target.value })}>
                <option value="">— Choisir —</option>
                {types.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              <button type="button" title="Ajouter un type de matériel" className="px-2 rounded border border-slate-300"
                onClick={async () => { const t = await onAjoutType(); if (t) maj({ type_materiel: t }); }}><Plus className="h-4 w-4" /></button>
            </div>
          </label>
          <label className="text-xs text-slate-600">Marque / modèle
            <input className={champ} value={f.marque_modele || ""} onChange={(e) => maj({ marque_modele: e.target.value })} />
          </label>
          <label className="text-xs text-slate-600">N° de série
            <input className={champ} value={f.numero_serie || ""} onChange={(e) => maj({ numero_serie: e.target.value })} />
          </label>
          <div className="text-xs text-slate-600">État du matériel
            <div className="flex gap-2 mt-1">
              {Object.entries(ETATS).map(([k, [l, cls]]) => (
                <label key={k} className={`flex items-center gap-1 rounded-md border px-2 py-1 cursor-pointer ${f.etat_materiel === k ? "border-indigo-500 bg-indigo-50" : "border-slate-300"}`}>
                  <input type="radio" name="etat" checked={f.etat_materiel === k} onChange={() => maj({ etat_materiel: k })} />
                  <span className={cls}>{l}</span>
                </label>
              ))}
            </div>
          </div>
          <label className="text-xs text-slate-600 sm:col-span-2">Motif du dépôt *
            <textarea className={champ} rows={2} value={f.motif} onChange={(e) => maj({ motif: e.target.value })} />
          </label>
          <label className="text-xs text-slate-600 sm:col-span-2">Diagnostic
            <textarea className={champ} rows={3} value={f.diagnostic || ""} onChange={(e) => maj({ diagnostic: e.target.value })} />
          </label>
          <label className="text-xs text-slate-600 flex items-center gap-2">
            <input type="checkbox" checked={!!f.remplacement_pieces} onChange={(e) => maj({ remplacement_pieces: e.target.checked })} />
            Nécessite le remplacement de pièces
          </label>
          {f.remplacement_pieces && (
            <label className="text-xs text-slate-600">Pièces à remplacer
              <input className={champ} value={f.pieces || ""} onChange={(e) => maj({ pieces: e.target.value })} />
            </label>
          )}
          <label className="text-xs text-slate-600">Date d'entrée en atelier
            <input type="date" className={champ} value={f.date_entree || ""} onChange={(e) => maj({ date_entree: e.target.value })} />
          </label>
          <label className="text-xs text-slate-600">Date de sortie (restitution)
            <input type="date" className={champ} value={f.date_sortie || ""} onChange={(e) => maj({ date_sortie: e.target.value })} />
          </label>
          <label className="text-xs text-slate-600">Statut
            <select className={champ} value={f.date_sortie ? "rendu" : f.statut} disabled={!!f.date_sortie}
              onChange={(e) => maj({ statut: e.target.value })}>
              {Object.entries(STATUTS).filter(([k]) => k !== "rendu" || f.date_sortie).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </label>
          <label className="text-xs text-slate-600">Prix du diagnostic (FCFA)
            <input type="number" min={0} step={500} className={champ} value={f.prix_diagnostic}
              onChange={(e) => maj({ prix_diagnostic: e.target.value })} data-testid="maintenance-prix" />
          </label>
          <label className="text-xs text-slate-600">Équipe (noms)
            <input className={champ} value={f.equipe || ""} maxLength={300} placeholder="ex. Issa, Awa"
              onChange={(e) => maj({ equipe: e.target.value })} data-testid="maintenance-equipe" />
          </label>
          <label className="text-xs text-slate-600 sm:col-span-2">Observations
            <textarea className={champ} rows={2} value={f.observations || ""} onChange={(e) => maj({ observations: e.target.value })} />
          </label>
        </div>
        {/* Lot 43 — photos, WhatsApp, lien de paiement, facturation (fiche enregistrée) */}
        {fiche?.id ? <MaintenanceActions fiche={fiche} onChange={onRafraichir} />
          : <p className="text-[11px] text-slate-500">Enregistrez la fiche pour ajouter des photos, l'envoyer par WhatsApp, créer un lien de paiement ou la facturer.</p>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Annuler</Button>
          <Button onClick={enregistrer} disabled={occupe || !f.type_materiel || !f.motif.trim() || (!f.contact_id && !f.compte_client_id && !f.client_nom.trim())}
            data-testid="maintenance-enregistrer">
            {occupe && <Loader2 className="h-4 w-4 mr-1 animate-spin" />} Enregistrer
          </Button>
        </div>
      </div>
    </div>
  );
}

export default function MaintenanceEquipements() {
  const [donnees, setDonnees] = useState(null);
  const [refus, setRefus] = useState("");
  const [types, setTypes] = useState([]);
  const [clients, setClients] = useState({ type: "contact", items: [] });   // lot 43
  const [q, setQ] = useState("");
  const [statut, setStatut] = useState("");
  const [type, setType] = useState("");
  const [prete, setPrete] = useState(false);          // lot 47 : filtre « Prêtes à facturer »
  const [edition, setEdition] = useState(null);       // null | "nouvelle" | fiche
  const [bon, setBon] = useState(null);

  const charger = useCallback(async () => {
    try {
      const r = await apiClient.get("/me/maintenance", { params: { q: q || undefined, statut: statut || undefined, type_materiel: type || undefined, prete: prete || undefined } });
      setDonnees(r.data);
    } catch (e) { setRefus(erreur(e, "Module indisponible")); }
  }, [q, statut, type, prete]);
  useEffect(() => { const t = setTimeout(charger, 250); return () => clearTimeout(t); }, [charger]);
  const chargerTypes = () => apiClient.get("/me/maintenance-types").then((r) => setTypes(r.data.tous || [])).catch(() => {});
  useEffect(() => {
    chargerTypes();
    apiClient.get("/me/maintenance-clients").then((r) => setClients(r.data)).catch(() => {});
  }, []);

  const ajouterType = async () => {
    const libelle = window.prompt("Nouveau type de matériel :");
    if (!libelle?.trim()) return null;
    try { await apiClient.post("/me/maintenance-types", { libelle: libelle.trim() }); await chargerTypes(); return libelle.trim(); }
    catch (e) { toast.error(erreur(e, "Type refusé")); return null; }
  };
  const supprimer = async (f) => {
    if (!window.confirm(`Supprimer la fiche ${f.numero} ?`)) return;
    try { await apiClient.delete(`/me/maintenance/${f.id}`); toast.success("Fiche supprimée"); charger(); }
    catch (e) { toast.error(erreur(e, "Suppression impossible")); }
  };
  const compte = donnees?.compte || {};
  const compteIntervention = donnees?.compte_intervention || {};   // lot 47
  // Lot 43 — fiche ouverte relue après une action (photo, lien de paiement, facture, envoi)
  const rafraichirFiche = async () => {
    if (!edition?.id) return;
    try { const r = await apiClient.get(`/me/maintenance/${edition.id}`); setEdition(r.data); } catch { /* fiche supprimée */ }
    charger();
  };

  if (refus) return <div className="m-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-amber-900">{refus}</div>;
  return (
    <div className="mx-auto max-w-6xl space-y-4 p-4 sm:p-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-800"><Wrench className="h-6 w-6 text-indigo-600" /> Maintenance des équipements</h1>
        <Button className="ml-auto" onClick={() => setEdition("nouvelle")} data-testid="maintenance-nouvelle"><Plus className="h-4 w-4 mr-1" /> Nouvelle fiche</Button>
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => setStatut("")} className={`rounded-full px-3 py-1 text-xs ring-1 ${!statut ? "bg-slate-800 text-white ring-slate-800" : "bg-white ring-slate-300"}`}>Toutes</button>
        {Object.entries(STATUTS).map(([k, [l, cls]]) => (
          <button key={k} type="button" onClick={() => setStatut(statut === k ? "" : k)}
            className={`rounded-full px-3 py-1 text-xs ring-1 ${statut === k ? "ring-indigo-500 ring-2" : "ring-transparent"} ${cls}`}>
            {l}{compte[k] != null && !statut ? ` (${compte[k]})` : ""}
          </button>
        ))}
        {/* Lot 47 — fiches dont l'intervention est fermée et non encore facturées */}
        <button type="button" onClick={() => setPrete(!prete)} data-testid="maintenance-filtre-prete"
          className={`rounded-full px-3 py-1 text-xs ring-1 bg-violet-100 text-violet-700 ${prete ? "ring-2 ring-violet-500" : "ring-transparent"}`}>
          Prêtes à facturer ({compteIntervention.prete_a_facturer ?? 0})
        </button>
        {compteIntervention.en_cours > 0 && (
          <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-3 py-1 text-xs text-blue-700">
            <span className="h-1.5 w-1.5 rounded-full bg-blue-600 animate-pulse" /> {compteIntervention.en_cours} intervention(s) en cours
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-2 top-2 h-4 w-4 text-slate-400" />
          <input className={`${champ} pl-8`} placeholder="N°, client, téléphone, modèle, n° de série…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <select className={`${champ} w-auto`} value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">Tous les matériels</option>
          {types.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs text-slate-500">
            <tr><th className="p-2">N°</th><th className="p-2">Client</th><th className="p-2">Matériel</th><th className="p-2">État</th>
              <th className="p-2">Reçu</th><th className="p-2">Entrée / sortie</th><th className="p-2">Pièces</th><th className="p-2">Statut</th><th className="p-2">Intervention</th><th className="p-2" /></tr>
          </thead>
          <tbody>
            {!donnees && <tr><td colSpan={10} className="p-4 text-center"><Loader2 className="h-4 w-4 animate-spin inline" /></td></tr>}
            {donnees?.fiches.length === 0 && <tr><td colSpan={10} className="p-4 text-center text-slate-400">Aucune fiche.</td></tr>}
            {(donnees?.fiches || []).map((f) => (
              <tr key={f.id} className="border-t border-slate-100 hover:bg-slate-50 cursor-pointer" onClick={() => setEdition(f)}>
                <td className="p-2 font-mono text-xs">{f.numero}</td>
                <td className="p-2">{f.client_nom}<span className="block text-[11px] text-slate-500">{f.client_telephone}</span></td>
                <td className="p-2">{f.type_materiel}<span className="block text-[11px] text-slate-500">{f.marque_modele}</span></td>
                <td className={`p-2 ${ETATS[f.etat_materiel]?.[1] || ""}`}>{ETATS[f.etat_materiel]?.[0]}</td>
                <td className="p-2">{dateFr(f.date_reception)}</td>
                <td className="p-2 text-xs">{dateFr(f.date_entree)} → {dateFr(f.date_sortie)}</td>
                <td className="p-2 text-xs">{f.remplacement_pieces ? <span className="text-amber-700">Oui{f.pieces ? ` : ${f.pieces}` : ""}</span> : "Non"}</td>
                <td className="p-2">
                  <span className={`rounded-full px-2 py-0.5 text-[11px] ${STATUTS[f.statut]?.[1]}`}>{STATUTS[f.statut]?.[0]}</span>
                  {/* Lot 43 — paiement et facture */}
                  {f.lien_paiement && <span className={`block mt-0.5 text-[10px] ${f.lien_paiement.paye ? "text-emerald-700" : "text-amber-700"}`}>{f.lien_paiement.paye ? "Payé" : "Paiement en attente"}</span>}
                  {f.facture && <span className="block text-[10px] text-indigo-700">{f.facture.numero}</span>}
                </td>
                {/* Lot 47 — état, durée et bouton de l'intervention */}
                <td className="p-2" onClick={(e) => e.stopPropagation()}>
                  <div className="flex flex-wrap gap-1"><BadgesIntervention fiche={f} /></div>
                  {f.duree_totale_minutes > 0 && <span className="block text-[10px] text-slate-500">{dureeFr(f.duree_totale_minutes)}</span>}
                  <div className="mt-1"><BoutonsIntervention fiche={f} compact onChange={charger} /></div>
                </td>
                <td className="p-2 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                  <button type="button" title="Bon de dépôt / de restitution" onClick={() => setBon(f)} className="p-1 text-slate-500 hover:text-slate-800"><Printer className="h-4 w-4" /></button>
                  <button type="button" title="Supprimer" onClick={() => supprimer(f)} className="p-1 text-rose-500 hover:text-rose-700"><Trash2 className="h-4 w-4" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {edition && (
        <FormulaireFiche key={edition === "nouvelle" ? "nouvelle" : edition.id} fiche={edition === "nouvelle" ? null : edition}
          types={types} clients={clients} onRafraichir={rafraichirFiche}
          onAjoutType={ajouterType} onClose={() => setEdition(null)}
          onEnregistre={(f) => { setEdition(null); charger(); if (!edition?.id) setBon(f); }} />
      )}
      {bon && <Bon fiche={bon} onClose={() => setBon(null)} />}
    </div>
  );
}
