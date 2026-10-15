// =====================================================================
// Lot 163 — « Logiciels, produits et services » d'un client (fiche client → SMART Communications).
// Liluvine lit cette liste pour ne plus poser de questions sur nos produits au contact lié à ce client, et pour savoir
// quelle assistance est visée quand le contrat n'est pas à jour.
//   GET / PUT /api/admin/clients/{id}/offre   { lignes: [{ id, type, nom, description, version, actif }] }
// Aucune nouvelle collection : la liste est enregistrée sur la fiche du client.
// Lot 169 — COPIE d'un client à un autre :
//   GET  /api/admin/offre-client/clients                         liste des clients et nombre de lignes de leur offre
//   POST /api/admin/offre-client/copier {source_id, cible_ids, mode}   mode « remplacer » ou « ajouter » (sans doublon)
//   - « Reprendre la liste d'un autre client » : charge la liste de l'autre client DANS L'ÉDITEUR (rien n'est enregistré
//     tant qu'on ne clique pas sur « Enregistrer ») ;
//   - « Copier cette liste vers d'autres clients » : applique tout de suite (confirmation demandée) la liste ENREGISTRÉE.
// =====================================================================
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const TYPES = [["logiciel", "Logiciel"], ["produit", "Produit"], ["service", "Service / prestation"]];

export default function OffreClientEditeur({ clientId }) {
  const [lignes, setLignes] = useState(null);         // lignes en cours d'édition
  const [maj, setMaj] = useState(null);               // dernière mise à jour { le, par }
  const [occupe, setOccupe] = useState(false);
  const [enregistre, setEnregistre] = useState("");     // lot 169 : liste enregistrée (texte JSON) pour repérer les modifications non enregistrées
  const [copie, setCopie] = useState(false);            // lot 169 : panneau de copie ouvert
  const [clients, setClients] = useState([]);           // lot 169 : autres clients et nombre de lignes de leur offre
  const [mode, setMode] = useState("ajouter");          // lot 169 : « ajouter » (sans doublon) ou « remplacer »
  const [source, setSource] = useState("");             // lot 169 : client dont on reprend la liste
  const [cibles, setCibles] = useState(() => new Set()); // lot 169 : clients qui reçoivent la liste de celui-ci
  const [filtre, setFiltre] = useState("");

  // Lecture de l'offre enregistrée
  useEffect(() => {
    apiClient.get(`/admin/clients/${clientId}/offre`).then((r) => { setLignes(r.data.lignes); setMaj(r.data.maj); setEnregistre(JSON.stringify(r.data.lignes)); })
      .catch(() => toast.error("Offre du client illisible"));
  }, [clientId]);

  // Lot 169 — ouvre le panneau de copie et lit la liste des clients (une seule fois)
  const ouvrirCopie = () => {
    setCopie((o) => !o);
    if (!clients.length) apiClient.get("/admin/offre-client/clients").then((r) => setClients(r.data.clients.filter((c) => c.id !== clientId))).catch(() => toast.error("Liste des clients illisible"));
  };
  // Lot 169 — charge la liste d'un autre client dans l'éditeur (même règle que le serveur : « ajouter » = lignes absentes seulement)
  const reprendre = async () => {
    if (!source) return;
    try {
      const { data } = await apiClient.get(`/admin/clients/${source}/offre`);
      const neuves = data.lignes.map((l) => ({ ...l, id: "" }));          // identifiants neufs : listes indépendantes
      if (mode === "remplacer") {
        if (lignes.length && !window.confirm("Remplacer la liste affichée par celle de l'autre client ? (rien n'est enregistré avant « Enregistrer »)")) return;
        setLignes(neuves);
      } else {
        const cle = (l) => `${l.type}|${(l.nom || "").trim().toLowerCase()}`;
        const deja = new Set(lignes.map(cle));
        setLignes([...lignes, ...neuves.filter((l) => !deja.has(cle(l)))]);
      }
      toast.success("Liste reprise dans l'éditeur : vérifiez-la puis cliquez sur « Enregistrer ».");
    } catch (e) { toast.error(e?.response?.data?.detail || "Lecture de la liste de l'autre client impossible"); }
  };
  // Lot 169 — copie la liste ENREGISTRÉE de ce client vers les clients cochés
  const envoyerVers = async () => {
    if (JSON.stringify(lignes) !== enregistre) { toast.error("Enregistrez d'abord vos modifications : la copie part de la liste enregistrée."); return; }
    if (!cibles.size) { toast.info("Cochez au moins un client."); return; }
    const verbe = mode === "remplacer" ? "REMPLACERA" : "sera ajoutée à";
    if (!window.confirm(`La liste de ce client (${lignes.length} ligne(s)) ${verbe} la liste de ${cibles.size} client(s)${mode === "remplacer" ? "" : " (lignes déjà présentes ignorées)"}. Continuer ?`)) return;
    setOccupe(true);
    try {
      const { data } = await apiClient.post("/admin/offre-client/copier", { source_id: clientId, cible_ids: [...cibles], mode });
      toast.success(`${data.copiees} ligne(s) copiée(s) vers ${data.clients} client(s)`);
      const echecs = data.resultat.filter((r) => !r.ok);
      if (echecs.length) toast.error(`${echecs.length} client(s) non mis à jour : ${echecs.map((r) => r.erreur).join(", ")}`);
      setCibles(new Set());
      apiClient.get("/admin/offre-client/clients").then((r) => setClients(r.data.clients.filter((c) => c.id !== clientId))).catch(() => {});
    } catch (e) { toast.error(e?.response?.data?.detail || "Copie impossible"); } finally { setOccupe(false); }
  };

  // Modifie un champ d'une ligne
  const changer = (i, champ, valeur) => setLignes(lignes.map((l, k) => (k === i ? { ...l, [champ]: valeur } : l)));
  // Ajoute une ligne vide
  const ajouter = () => setLignes([...lignes, { id: "", type: "logiciel", nom: "", description: "", version: "", actif: true }]);
  // Enregistre toute la liste (les lignes sans nom sont ignorées par le serveur)
  const enregistrer = async () => {
    setOccupe(true);
    try {
      const { data } = await apiClient.put(`/admin/clients/${clientId}/offre`, { lignes });
      setLignes(data.lignes); setMaj(data.maj); setEnregistre(JSON.stringify(data.lignes)); toast.success("Offre du client enregistrée");
    } catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible"); } finally { setOccupe(false); }
  };

  if (!lignes) return <p className="text-sm text-slate-500">Chargement…</p>;
  return (
    <div className="rounded-2xl bg-white p-5 ring-1 ring-slate-200 space-y-3" data-testid="offre-client-editeur">
      <div>
        <h3 className="text-sm font-semibold text-slate-900">🧩 Logiciels, produits et services du client</h3>
        <p className="text-xs text-slate-600">
          Liluvine connaît ainsi la relation SAWALI–client : elle ne pose plus de questions sur nos produits, adapte ses réponses et,
          si le contrat n'est pas à jour, refuse l'assistance (réglages dans <Link to="/admin/settings#s-offre-client" className="underline">Paramètres → Offre du client</Link>).
        </p>
      </div>
      {lignes.length === 0 && <p className="text-xs text-slate-500">Aucune ligne. Ajoutez les logiciels (CRM…), produits et services fournis à ce client.</p>}
      <div className="space-y-2">
        {lignes.map((l, i) => (
          <div key={l.id || i} className="grid grid-cols-1 gap-2 rounded-lg border border-slate-200 p-2 md:grid-cols-[9rem_1fr_6rem_2fr_auto_auto]" data-testid={`offre-ligne-${i}`}>
            <select className="rounded border border-slate-300 px-2 py-1 text-xs" value={l.type} onChange={(e) => changer(i, "type", e.target.value)} aria-label="Type">
              {TYPES.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
            </select>
            <input className="rounded border border-slate-300 px-2 py-1 text-xs" placeholder="Nom (ex. SAWALI CRM)" maxLength={120} value={l.nom} onChange={(e) => changer(i, "nom", e.target.value)} />
            <input className="rounded border border-slate-300 px-2 py-1 text-xs" placeholder="Version" maxLength={40} value={l.version} onChange={(e) => changer(i, "version", e.target.value)} />
            <input className="rounded border border-slate-300 px-2 py-1 text-xs" placeholder="Précision utile à Liluvine (modules, site…)" maxLength={300} value={l.description} onChange={(e) => changer(i, "description", e.target.value)} />
            <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={l.actif !== false} onChange={(e) => changer(i, "actif", e.target.checked)} /> Actif</label>
            <button type="button" className="text-xs text-rose-700 hover:underline" onClick={() => setLignes(lignes.filter((_, k) => k !== i))}>Retirer</button>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={ajouter} className="rounded-md bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-800 hover:bg-slate-200" data-testid="offre-ajouter">+ Ajouter une ligne</button>
        <button type="button" onClick={enregistrer} disabled={occupe} className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-700 disabled:opacity-50" data-testid="offre-enregistrer">
          {occupe ? "Patientez…" : "Enregistrer"}
        </button>
        <button type="button" onClick={ouvrirCopie} className="rounded-md bg-sky-100 px-3 py-1.5 text-xs font-semibold text-sky-900 hover:bg-sky-200" data-testid="offre-copier" aria-expanded={copie}>📋 Copier la liste d'un client à un autre</button>
        {maj && <span className="text-xs text-slate-500">Dernière mise à jour : {new Date(maj.le).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}{maj.par ? ` · ${maj.par}` : ""}{maj.copie_de ? ` · copiée depuis ${maj.copie_de}` : ""}</span>}
      </div>
      {/* Lot 169 — copie d'une liste d'un client à un autre */}
      {copie && (
        <div className="space-y-3 rounded-lg border border-sky-200 bg-sky-50/50 p-3 text-xs text-slate-700" data-testid="offre-copie-panneau">
          <div className="flex flex-wrap items-center gap-3">
            <span className="font-semibold">Si le client a déjà une liste :</span>
            <label className="flex items-center gap-1"><input type="radio" name="mode-copie" checked={mode === "ajouter"} onChange={() => setMode("ajouter")} /> ajouter les lignes absentes</label>
            <label className="flex items-center gap-1"><input type="radio" name="mode-copie" checked={mode === "remplacer"} onChange={() => setMode("remplacer")} /> remplacer sa liste</label>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold">Reprendre la liste d'un autre client :</span>
            <select className="rounded border border-slate-300 px-2 py-1" value={source} onChange={(e) => setSource(e.target.value)} aria-label="Client source">
              <option value="">Choisir un client…</option>
              {clients.filter((c) => c.nb_lignes > 0).map((c) => <option key={c.id} value={c.id}>{c.nom} ({c.nb_lignes} ligne{c.nb_lignes > 1 ? "s" : ""})</option>)}
            </select>
            <button type="button" onClick={reprendre} disabled={!source} className="rounded-md bg-slate-900 px-3 py-1 font-semibold text-white disabled:opacity-40">Charger dans l'éditeur</button>
            <span className="text-slate-500">(rien n'est enregistré avant « Enregistrer »)</span>
          </div>
          <div className="space-y-1">
            <p className="font-semibold">Copier la liste enregistrée de ce client vers d'autres clients :</p>
            <input className="w-full max-w-xs rounded border border-slate-300 px-2 py-1" placeholder="Rechercher un client" value={filtre} onChange={(e) => setFiltre(e.target.value)} />
            <div className="max-h-40 overflow-y-auto rounded border border-slate-200 bg-white p-2">
              {clients.filter((c) => !filtre || c.nom.toLowerCase().includes(filtre.toLowerCase())).map((c) => (
                <label key={c.id} className="flex items-center gap-2 py-0.5">
                  <input type="checkbox" checked={cibles.has(c.id)} onChange={() => setCibles((s) => { const n = new Set(s); if (n.has(c.id)) n.delete(c.id); else n.add(c.id); return n; })} />
                  <span>{c.nom}</span><span className="text-slate-400">({c.nb_lignes} ligne{c.nb_lignes > 1 ? "s" : ""})</span>
                </label>
              ))}
              {!clients.length && <span className="text-slate-400">Chargement…</span>}
            </div>
            <button type="button" onClick={envoyerVers} disabled={occupe || !cibles.size} className="rounded-md bg-sky-700 px-3 py-1 font-semibold text-white disabled:opacity-40" data-testid="offre-copier-vers">
              {occupe ? "Patientez…" : `Copier vers ${cibles.size || ""} client${cibles.size > 1 ? "s" : ""}`}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
