// ============================================================================
// Lot 454 — Paramètres → « 💬 Consignes à Liluvine — numéros WhatsApp autorisés ».
// L'administrateur règle QUI peut donner des consignes à Liluvine par WhatsApp (utilisé par le lot « consignes par WhatsApp »), client / tenant par client.
// Une ligne = un numéro WhatsApp (reconnu par ses 8 derniers chiffres), un nom, le client concerné (vide = SAWALI) et « actif ».
// Le partage de l'écran « Consignes » aux superviseurs se règle dans « Liluvine — partage avec les superviseurs » (élément « Consignes à Liluvine »).
// Backend : GET/PUT /api/admin/liluvine-consignes-acces (administrateur seul). Enregistrement explicite (règle 15).
// ============================================================================
import React, { useCallback, useEffect, useState } from "react";
import { Ban, Check, ChevronDown, Copy, Plus, RefreshCw, Save, Search, Send, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";


// Lot 456.1 — modèle Meta des envois en masse HORS fenêtre de 24 h : le texte à soumettre à Meta (avec le bouton « Bien reçu ») et le nom du modèle une fois approuvé.
// Lot 460 — le modèle se SOUMET à Meta d'ici (bouton « Soumettre à Meta ») et son STATUT se suit d'ici (« Vérifier le statut chez Meta »). Meta n'est interrogé que par ces deux boutons.
const COULEUR_STATUT = { APPROVED: "bg-emerald-100 text-emerald-800", PENDING: "bg-amber-100 text-amber-800", IN_APPEAL: "bg-amber-100 text-amber-800", REJECTED: "bg-red-100 text-red-800", PAUSED: "bg-red-100 text-red-800", DISABLED: "bg-red-100 text-red-800", ABSENT: "bg-slate-200 text-slate-700" };
const quand = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "");

function ModeleMasse() {
  const [info, setInfo] = useState(null);
  const [sou, setSou] = useState(null);                  // dernière soumission connue : { statut, libelle, raison, alerte, envoye_le, verifie_le, active, active_auto_le }
  const [nom, setNom] = useState("");                    // UN SEUL champ : le nom du modèle (soumis à Meta, puis activé sous ce même nom — lot 463, plus de second champ)
  const [occupe, setOccupe] = useState(false);
  const charger = useCallback(async () => {
    try { const r = await apiClient.get("/admin/liluvine-consignes/masse/modele"); setInfo(r.data.a_soumettre); setSou(r.data.soumission); setNom((n) => n || r.data.soumission?.nom || r.data.a_soumettre.nom); }
    catch (e) { toast.error(e?.response?.data?.detail || "Lecture du modèle impossible"); }
  }, []);
  useEffect(() => { charger(); }, [charger]);
  const copier = (t) => { navigator.clipboard?.writeText(t); toast.success("Copié."); };
  // Lot 463 : à l'approbation, SAWALI active le modèle TOUT SEUL (à la vérification, manuelle ou horaire) ; on le dit clairement.
  const apresMeta = (v, avertir) => { setSou(v); if (avertir && v.active_auto_le && v.active) toast.success("Modèle approuvé par Meta : activé automatiquement pour les envois en masse."); };
  const soumettre = async () => {
    setOccupe(true); toast("Patientez… envoi du modèle à Meta en cours");
    try { const r = await apiClient.post("/admin/liluvine-consignes/masse/modele/soumettre", { nom }); apresMeta(r.data.soumission, true); toast.success(r.data.soumission.deja ? `Ce modèle existe déjà chez Meta : ${r.data.soumission.libelle}.` : "Modèle envoyé à Meta : en attente d'examen."); }
    catch (e) { toast.error(e?.response?.data?.detail || "Soumission impossible"); }
    finally { setOccupe(false); }
  };
  const verifier = async () => {
    setOccupe(true); toast("Patientez… lecture du statut chez Meta en cours");
    try { const r = await apiClient.get("/admin/liluvine-consignes/masse/modele/statut", { params: { nom } }); apresMeta(r.data.soumission, true); toast.success(`Statut chez Meta : ${r.data.soumission.libelle}.`); }
    catch (e) { toast.error(e?.response?.data?.detail || "Lecture du statut impossible"); }
    finally { setOccupe(false); }
  };
  // Activer / désactiver à la main (le modèle approuvé reste utilisable ou non pour les envois en masse hors fenêtre de 24 h)
  const regler = async (activer) => {
    setOccupe(true); toast(activer ? "Activation du modèle en cours…" : "Désactivation du modèle en cours…");
    try { await apiClient.put("/admin/liluvine-consignes/masse/modele", { nom: activer ? sou.nom : "", langue: "fr" }); await charger();
      toast.success(activer ? "Modèle activé : les envois en masse l'utiliseront hors fenêtre de 24 h." : "Modèle désactivé : les contacts hors fenêtre resteront « non envoyé »."); }
    catch (e) { toast.error(e?.response?.data?.detail || "Réglage impossible"); }
    finally { setOccupe(false); }
  };
  if (!info) return null;
  return (
    <div className="mt-4 space-y-2 rounded-xl border border-slate-200 p-3" data-testid="modele-masse">
      <h4 className="font-semibold">📣 Modèle Meta des envois en masse (personnes qui n'ont pas écrit depuis 24 h)</h4>
      <p className="text-xs text-slate-600">Catégorie « {info.categorie} », langue « {info.langue} », corps ci-dessous, bouton de réponse rapide « {info.bouton} ». Exemples envoyés à Meta : {info.exemples.map((e) => `« ${e} »`).join(" et ")}.</p>
      <p className="rounded-lg bg-slate-50 p-2 text-sm">{info.corps}</p>
      <button type="button" onClick={() => copier(info.corps)} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1 text-sm"><Copy className="w-4 h-4" /> Copier le corps</button>
      <div className="space-y-2 rounded-lg border border-sky-200 bg-sky-50 p-3" data-testid="modele-masse-soumission">
        <h5 className="font-semibold">📤 Soumission à Meta, suivi du statut et activation</h5>
        <label className="block text-sm font-semibold">Nom du modèle<input value={nom} onChange={(e) => setNom(e.target.value)} placeholder={info.nom} data-testid="modele-masse-nom" className="mt-1 w-full rounded-lg border border-slate-300 p-2 text-sm font-normal sm:w-80" /></label>
        <div className="flex flex-wrap items-center gap-2 boutons-distincts">
          <button type="button" onClick={soumettre} disabled={occupe} data-testid="modele-masse-soumettre" className="inline-flex items-center gap-1 rounded-full bg-sky-700 px-3 py-1 text-sm font-semibold text-white disabled:opacity-50"><Send className="w-4 h-4" /> Soumettre à Meta</button>
          <button type="button" onClick={verifier} disabled={occupe} data-testid="modele-masse-verifier" className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1 text-sm disabled:opacity-50"><RefreshCw className="w-4 h-4" /> Vérifier le statut chez Meta</button>
          {sou?.statut === "APPROVED" && !sou.active && <button type="button" onClick={() => regler(true)} disabled={occupe} data-testid="modele-masse-activer" className="inline-flex items-center gap-1 rounded-full bg-emerald-700 px-3 py-1 text-sm font-semibold text-white disabled:opacity-50"><Check className="w-4 h-4" /> Activer pour les envois en masse</button>}
          {sou?.active && <button type="button" onClick={() => regler(false)} disabled={occupe} data-testid="modele-masse-desactiver" className="inline-flex items-center gap-1 rounded-full border border-red-300 px-3 py-1 text-sm text-red-700 disabled:opacity-50"><Ban className="w-4 h-4" /> Désactiver</button>}
        </div>
        {sou && (
          <p className="text-sm" data-testid="modele-masse-statut">
            Statut chez Meta : <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${COULEUR_STATUT[sou.statut] || "bg-slate-200 text-slate-700"}`}>{sou.libelle}</span>
            {sou.active && <span className="ml-2 rounded-full bg-emerald-700 px-2 py-0.5 text-xs font-semibold text-white">activé pour les envois en masse{sou.active_auto_le ? ` automatiquement le ${quand(sou.active_auto_le)}` : ""}</span>}
            {sou.envoye_le && <span className="ml-2 text-xs text-slate-600">envoyé le {quand(sou.envoye_le)}</span>}
            {sou.verifie_le && <span className="ml-2 text-xs text-slate-600">vérifié le {quand(sou.verifie_le)}</span>}
            {sou.raison && <span className="block text-red-700">Motif du refus : {sou.raison}</span>}
            {sou.alerte && <span className="block text-amber-700">{sou.alerte}</span>}
          </p>)}
        <p className="text-[11px] text-slate-500">Tant que Meta n'a pas répondu, le statut est relu automatiquement toutes les heures ; dès l'approbation, le modèle est activé tout seul. Sans modèle actif, les contacts hors fenêtre de 24 h restent « non envoyé ».</p>
      </div>
    </div>
  );
}

// Lot 462 — LISTE DÉROULANTE à choix multiples des clients (tenants) d'un numéro autorisé.
// Chaque case cochée ajoute le code du client ; la liste des codes est SANS DOUBLON (ensemble). Aucune case cochée = tout SAWALI.
// `clients` = [{ id, nom }] ; `ligne` = { tenants: [codes], tenants_noms: [noms] } ; `onChange(codes, noms)` renvoie les deux listes alignées.
function ListeClients({ clients, ligne, onChange }) {
  const [ouvert, setOuvert] = useState(false);
  const [q, setQ] = useState("");
  const codes = ligne.tenants || [];
  const noms = ligne.tenants_noms || [];
  const nomDe = (id, i) => clients.find((c) => c.id === id)?.nom || noms[i] || "client inconnu";
  const filtres = clients.filter((c) => `${c.nom} ${c.email || ""}`.toLowerCase().includes(q.trim().toLowerCase()));
  const bascule = (c) => {
    const ensemble = new Set(codes);                         // un ensemble : jamais deux fois le même code
    if (ensemble.has(c.id)) ensemble.delete(c.id); else ensemble.add(c.id);
    const nouveaux = [...ensemble];
    onChange(nouveaux, nouveaux.map((id) => clients.find((x) => x.id === id)?.nom || noms[codes.indexOf(id)] || ""));
  };
  const resume = codes.length === 0 ? "SAWALI (tous les clients)" : codes.length === 1 ? nomDe(codes[0], 0) : `${codes.length} clients`;
  return (
    <Popover open={ouvert} onOpenChange={setOuvert}>
      <PopoverTrigger asChild>
        <button type="button" data-testid="liste-clients" title={codes.map(nomDe).join(", ") || "Tout SAWALI"} className="inline-flex w-56 items-center justify-between gap-1 rounded border border-slate-300 bg-white p-1 text-left">
          <span className="truncate">{resume}</span><ChevronDown className="w-4 h-4 shrink-0" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 space-y-2 p-3">
        <label className="flex items-center gap-1 rounded border border-slate-300 px-2"><Search className="w-4 h-4 text-slate-500" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Rechercher un client" className="w-full p-1 text-sm outline-none" /></label>
        <ul className="max-h-60 space-y-1 overflow-y-auto text-sm">
          {filtres.map((c) => (
            <li key={c.id}><label className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 hover:bg-slate-100"><input type="checkbox" checked={codes.includes(c.id)} onChange={() => bascule(c)} /><span className="truncate">{c.nom}</span></label></li>))}
          {codes.filter((id) => !clients.some((c) => c.id === id)).map((id) => (
            <li key={id}><label className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 hover:bg-slate-100"><input type="checkbox" checked onChange={() => bascule({ id })} /><span className="truncate text-amber-700">{nomDe(id, codes.indexOf(id))} (absent de la liste)</span></label></li>))}
          {filtres.length === 0 && <li className="text-slate-500">Aucun client trouvé.</li>}
        </ul>
        <div className="flex items-center justify-between gap-2 boutons-distincts">
          <span className="text-xs text-slate-600">{codes.length === 0 ? "Aucun client coché : tout SAWALI." : `${codes.length} client(s) coché(s)`}</span>
          <button type="button" onClick={() => onChange([], [])} disabled={codes.length === 0} className="rounded-full border border-slate-300 px-3 py-0.5 text-xs disabled:opacity-50">Tout décocher</button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

export default function ConsignesLiluvineAccesSection() {
  const [lignes, setLignes] = useState(null);
  const [initial, setInitial] = useState("");
  const [max, setMax] = useState(100);
  const [clients, setClients] = useState([]);            // lot 462 : clients proposés dans la liste déroulante : [{ id, nom, email }]
  const modifie = lignes !== null && JSON.stringify(lignes) !== initial;

  const charger = useCallback(async () => {
    toast("Lecture des numéros autorisés en cours…");
    try { const r = await apiClient.get("/admin/liluvine-consignes-acces"); setLignes(r.data.acces); setInitial(JSON.stringify(r.data.acces)); setMax(r.data.maximum); toast.success(`${r.data.acces.length} numéro(s) autorisé(s).`); }
    catch (e) { setLignes([]); toast.error(e?.response?.data?.detail || "Lecture impossible"); }
  }, []);
  useEffect(() => { charger(); }, [charger]);
  // Les clients (tenants) = les comptes « admin » et « superviseur » (un client = le compte racine de son établissement) ; triés par nom.
  useEffect(() => {
    apiClient.get("/me/access-clients-list")
      .then((r) => setClients((Array.isArray(r.data) ? r.data : []).filter((u) => ["admin", "superviseur"].includes(u.role))
        .map((u) => ({ id: u.id, nom: u.company || u.full_name || u.email, email: u.email })).sort((a, b) => String(a.nom).localeCompare(String(b.nom)))))
      .catch(() => setClients([]));
  }, []);

  const maj = (i, champ, v) => setLignes((l) => l.map((x, k) => (k === i ? { ...x, [champ]: v } : x)));
  const majClients = (i, codes, noms) => setLignes((l) => l.map((x, k) => (k === i ? { ...x, tenants: codes, tenants_noms: noms, tenant: codes[0] || "", tenant_nom: noms.filter(Boolean).join(", ") } : x)));
  const enregistrer = async () => {
    toast("Enregistrement en cours…");
    try { const r = await apiClient.put("/admin/liluvine-consignes-acces", { acces: lignes }); setLignes(r.data.acces); setInitial(JSON.stringify(r.data.acces)); toast.success(`Enregistré : ${r.data.acces.length} numéro(s) autorisé(s).`); }
    catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible"); }
  };

  if (lignes === null) return <p className="text-sm text-slate-500">Chargement…</p>;
  return (
    <div className="space-y-3" data-testid="consignes-acces">
      <p className="text-xs text-slate-600">Numéros WhatsApp autorisés à donner des consignes à Liluvine. Colonne « Clients » : cochez un ou plusieurs clients dans la liste déroulante (aucun coché = tout SAWALI) ; un numéro lié à des clients ne peut pas faire d'envoi en masse. Un numéro inconnu ou désactivé est ignoré. Le superviseur ouvre l'écran « Consignes » (menu Liluvine) si l'élément lui est partagé dans « Liluvine — partage avec les superviseurs ».</p>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead><tr className="text-left text-slate-600"><th className="px-1">Numéro WhatsApp</th><th className="px-1">Nom</th><th className="px-1">Clients (liste déroulante, plusieurs possibles)</th><th className="px-1">Actif</th><th /></tr></thead>
          <tbody>
            {lignes.map((l, i) => (
              <tr key={i} className="border-t">
                <td className="px-1 py-1"><input value={l.numero || ""} onChange={(e) => maj(i, "numero", e.target.value)} placeholder="+226 70 12 34 56" className="w-40 rounded border border-slate-300 p-1" /></td>
                <td className="px-1 py-1"><input value={l.nom || ""} onChange={(e) => maj(i, "nom", e.target.value)} placeholder="BADINI Awa" className="w-40 rounded border border-slate-300 p-1" /></td>
                <td className="px-1 py-1"><ListeClients clients={clients} ligne={l} onChange={(codes, noms) => majClients(i, codes, noms)} /></td>
                <td className="px-1 py-1 text-center"><input type="checkbox" checked={l.actif !== false} onChange={(e) => maj(i, "actif", e.target.checked)} aria-label="Actif" /></td>
                <td className="px-1 py-1"><button type="button" onClick={() => setLignes((x) => x.filter((_, k) => k !== i))} aria-label="Retirer ce numéro" title="Retirer ce numéro" className="text-red-700"><Trash2 className="w-4 h-4" /></button></td>
              </tr>))}
            {lignes.length === 0 && <tr><td colSpan={5} className="px-1 py-2 text-slate-500">Aucun numéro autorisé.</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" disabled={lignes.length >= max} onClick={() => setLignes((l) => [...l, { numero: "", nom: "", tenants: [], tenants_noms: [], tenant: "", tenant_nom: "", actif: true }])} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1 text-sm"><Plus className="w-4 h-4" /> Ajouter un numéro</button>
        <button type="button" onClick={enregistrer} disabled={!modifie} data-testid="consignes-acces-enregistrer" className="inline-flex items-center gap-1 rounded-full bg-emerald-700 px-3 py-1 text-sm font-semibold text-white disabled:opacity-50"><Save className="w-4 h-4" /> Enregistrer</button>
        <button type="button" onClick={charger} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1 text-sm"><RefreshCw className="w-4 h-4" /> Actualiser</button>
        {modifie && <span className="text-xs text-amber-700">modifié, non enregistré</span>}
      </div>
      <ModeleMasse />
    </div>
  );
}
