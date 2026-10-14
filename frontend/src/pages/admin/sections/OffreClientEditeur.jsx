// =====================================================================
// Lot 163 — « Logiciels, produits et services » d'un client (fiche client → SMART Communications).
// Liluvine lit cette liste pour ne plus poser de questions sur nos produits au contact lié à ce client, et pour savoir
// quelle assistance est visée quand le contrat n'est pas à jour.
//   GET / PUT /api/admin/clients/{id}/offre   { lignes: [{ id, type, nom, description, version, actif }] }
// Aucune nouvelle collection : la liste est enregistrée sur la fiche du client.
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

  // Lecture de l'offre enregistrée
  useEffect(() => {
    apiClient.get(`/admin/clients/${clientId}/offre`).then((r) => { setLignes(r.data.lignes); setMaj(r.data.maj); })
      .catch(() => toast.error("Offre du client illisible"));
  }, [clientId]);

  // Modifie un champ d'une ligne
  const changer = (i, champ, valeur) => setLignes(lignes.map((l, k) => (k === i ? { ...l, [champ]: valeur } : l)));
  // Ajoute une ligne vide
  const ajouter = () => setLignes([...lignes, { id: "", type: "logiciel", nom: "", description: "", version: "", actif: true }]);
  // Enregistre toute la liste (les lignes sans nom sont ignorées par le serveur)
  const enregistrer = async () => {
    setOccupe(true);
    try {
      const { data } = await apiClient.put(`/admin/clients/${clientId}/offre`, { lignes });
      setLignes(data.lignes); setMaj(data.maj); toast.success("Offre du client enregistrée");
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
        {maj && <span className="text-xs text-slate-500">Dernière mise à jour : {new Date(maj.le).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}{maj.par ? ` · ${maj.par}` : ""}</span>}
      </div>
    </div>
  );
}
