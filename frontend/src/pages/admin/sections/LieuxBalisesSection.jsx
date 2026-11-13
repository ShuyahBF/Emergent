// LieuxBalisesSection.jsx — Lot 388 : rubrique « 📍 Lieux — Vous êtes ici » (Paramètres) et page « Lieux (balises) » du menu superviseur.
// Une balise Bluetooth FIXE marque un lieu (rayon, couloir, salle…). Le superviseur crée le lieu, rédige ce que le visiteur y trouve (texte + liens)
// et obtient un QR code à imprimer. Le visiteur scanne le QR (ou l'application « Où suis-je ? » repère la balise la plus proche) et la page PUBLIQUE
// du lieu s'ouvre. Les visites sont comptées par jour et par provenance (QR / application). Voir backend/routes/lieux_balises.py.
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, X, Save, Pencil, Trash2, Copy, ExternalLink, QrCode } from "lucide-react";   // règle 15 : un pictogramme sur chaque action
import { apiClient, API } from "@/lib/api";

const VIDE = { nom: "", texte: "", balise: "", liens: [] };

export default function LieuxBalisesSection() {
  const [lieux, setLieux] = useState([]);
  const [total, setTotal] = useState(0);
  const [form, setForm] = useState(VIDE);          // formulaire de création / modification
  const [code, setCode] = useState(null);          // code du lieu en cours de modification (null = création)
  const [selection, setSelection] = useState(null); // lieu sélectionné (QR affiché)
  const [occupe, setOccupe] = useState(false);

  const charger = useCallback(async () => {
    const { data } = await apiClient.get("/admin/lieux-balises");
    setLieux(data.lieux);
    setTotal(data.total_visites);
  }, []);
  useEffect(() => { charger().catch(() => toast.error("Chargement impossible")); }, [charger]);

  const erreur = (e) => toast.error(e?.response?.data?.detail || "Action impossible");
  const champ = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const lien = (i, k, v) => setForm((f) => ({ ...f, liens: f.liens.map((l, j) => (j === i ? { ...l, [k]: v } : l)) }));
  const nouveau = () => { setForm(VIDE); setCode(null); };

  // Enregistre : création si aucun lieu n'est en modification, sinon mise à jour
  const enregistrer = async () => {
    setOccupe(true);
    try {
      const { data } = code ? await apiClient.put(`/admin/lieux-balises/${code}`, form) : await apiClient.post("/admin/lieux-balises", form);
      toast.success(code ? "Lieu modifié" : "Lieu créé : imprimez son QR code");
      await charger();
      setSelection(data.code);
      nouveau();
    } catch (e) { erreur(e); } finally { setOccupe(false); }
  };
  const modifier = (l) => { setForm({ nom: l.nom, texte: l.texte, balise: l.balise || "", liens: l.liens }); setCode(l.code); setSelection(l.code); };
  const supprimer = async (l) => {
    if (!window.confirm(`Supprimer le lieu « ${l.nom} » ? Son QR code ne fonctionnera plus.`)) return;
    try { await apiClient.delete(`/admin/lieux-balises/${l.code}`); if (code === l.code) nouveau(); if (selection === l.code) setSelection(null); await charger(); } catch (e) { erreur(e); }
  };
  const copier = (adresse) => navigator.clipboard?.writeText(adresse).then(() => toast.success("Adresse copiée"), () => toast.error("Copie impossible"));

  const choisi = lieux.find((l) => l.code === selection);

  return (
    <div className="space-y-4" data-testid="lieux-balises">
      <p className="text-sm text-slate-600">
        Une balise posée dans un lieu (rayon, couloir, salle) marque ce lieu. Créez ici le lieu, écrivez ce que le visiteur y trouve,
        puis imprimez le QR code à coller près de la balise : le visiteur le scanne avec son téléphone, sans rien installer.
        L'application « Où suis-je ? » (Personnel de maison, Android) ouvre la même page en repérant la balise la plus proche.
      </p>

      {/* Formulaire : création ou modification d'un lieu */}
      <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
        <h3 className="text-sm font-semibold">{code ? "Modifier le lieu" : "Nouveau lieu"}</h3>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-sm">Nom du lieu
            <input className="mt-1 w-full rounded border border-slate-300 px-2 py-1" value={form.nom} maxLength={80}
              placeholder="Ex. Rayon frais" onChange={(e) => champ("nom", e.target.value)} data-testid="lieu-nom" />
          </label>
          <label className="text-sm">Identifiant de la balise (facultatif)
            <input className="mt-1 w-full rounded border border-slate-300 px-2 py-1 font-mono" value={form.balise} maxLength={80}
              placeholder="ib:… / mac:… / ed:…  (voir « Test balises Bluetooth »)" onChange={(e) => champ("balise", e.target.value)} data-testid="lieu-balise" />
          </label>
        </div>
        <label className="block text-sm">Ce que le visiteur voit (texte d'accueil, conseils, horaires…)
          <textarea className="mt-1 w-full rounded border border-slate-300 px-2 py-1" rows={3} value={form.texte} maxLength={2000}
            onChange={(e) => champ("texte", e.target.value)} data-testid="lieu-texte" />
        </label>
        <div className="space-y-2">
          <div className="text-sm font-medium">Liens utiles (10 au plus)</div>
          {form.liens.map((l, i) => (
            <div key={i} className="flex flex-wrap gap-2">
              <input className="w-40 rounded border border-slate-300 px-2 py-1 text-sm" placeholder="Libellé" value={l.libelle} onChange={(e) => lien(i, "libelle", e.target.value)} />
              <input className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1 text-sm" placeholder="https://…" value={l.url} onChange={(e) => lien(i, "url", e.target.value)} />
              <button type="button" className="rounded border border-slate-300 px-2 text-sm" aria-label="Retirer ce lien"
                onClick={() => setForm((f) => ({ ...f, liens: f.liens.filter((_, j) => j !== i) }))}><X className="mr-1 inline h-4 w-4" />Retirer</button>
            </div>
          ))}
          {form.liens.length < 10 && (
            <button type="button" className="rounded border border-slate-300 px-2 py-1 text-sm" onClick={() => setForm((f) => ({ ...f, liens: [...f.liens, { libelle: "", url: "" }] }))}><Plus className="mr-1 inline h-4 w-4" />Ajouter un lien</button>
          )}
        </div>
        {/* Boutons côte à côte : mince filet de couleur (règle 8) */}
        <div className="boutons-distincts flex flex-wrap gap-2">
          <button type="button" disabled={occupe || form.nom.trim().length < 2} onClick={enregistrer}
            className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-50" data-testid="lieu-enregistrer">{code ? <><Save className="mr-1 inline h-4 w-4" />Enregistrer les modifications</> : <><Plus className="mr-1 inline h-4 w-4" />Créer le lieu</>}</button>
          {code && <button type="button" onClick={nouveau} className="rounded border border-slate-300 px-3 py-1.5 text-sm"><X className="mr-1 inline h-4 w-4" />Annuler</button>}
        </div>
      </div>

      {/* Liste des lieux : nombres alignés à droite (règle 3), ligne sélectionnée = fond orange */}
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table className="tableau w-full text-sm">
          <thead>
            <tr className="text-left">
              <th className="p-2">Lieu</th><th className="p-2">Balise</th>
              <th className="p-2 text-right">Visites (total)</th><th className="p-2 text-right">7 derniers jours</th>
              <th className="p-2 text-right">Par QR</th><th className="p-2 text-right">Par l'application</th><th className="p-2" />
            </tr>
          </thead>
          <tbody>
            {lieux.length === 0 && <tr><td colSpan={7} className="p-3 text-slate-500">Aucun lieu : créez le premier ci-dessus.</td></tr>}
            {lieux.map((l) => (
              <tr key={l.code} aria-selected={selection === l.code} className="cursor-pointer border-t border-slate-100" onClick={() => setSelection(l.code)}>
                <td className="p-2 font-medium">{l.nom}</td>
                <td className="p-2 font-mono text-xs">{l.balise || "—"}</td>
                <td className="p-2 text-right tabular-nums">{l.visites_total}</td>
                <td className="p-2 text-right tabular-nums">{l.visites_7j}</td>
                <td className="p-2 text-right tabular-nums">{l.visites_sources?.qr || 0}</td>
                <td className="p-2 text-right tabular-nums">{l.visites_sources?.app || 0}</td>
                <td className="p-2 text-right whitespace-nowrap">
                  <button type="button" className="mr-2 underline" onClick={(e) => { e.stopPropagation(); modifier(l); }}><Pencil className="mr-1 inline h-4 w-4" />Modifier</button>
                  <button type="button" className="underline" onClick={(e) => { e.stopPropagation(); supprimer(l); }}><Trash2 className="mr-1 inline h-4 w-4" />Supprimer</button>
                </td>
              </tr>
            ))}
          </tbody>
          {lieux.length > 0 && <tfoot><tr className="border-t border-slate-200 font-semibold"><td className="p-2" colSpan={2}>Total</td><td className="p-2 text-right tabular-nums">{total}</td><td colSpan={4} /></tr></tfoot>}
        </table>
      </div>

      {/* QR code du lieu sélectionné : à imprimer et à coller près de la balise */}
      {choisi && (
        <div className="flex flex-wrap items-center gap-4 rounded-xl border border-slate-200 bg-white p-4" data-testid="lieu-qr">
          <img src={`${API}/lieux-balises/${choisi.code}/qr.png`} alt={`QR code du lieu ${choisi.nom}`} className="h-40 w-40" />
          <div className="min-w-0 space-y-2 text-sm">
            <div className="font-semibold">{choisi.nom}</div>
            <div className="break-all font-mono text-xs text-slate-600">{choisi.adresse}</div>
            <div className="boutons-distincts flex flex-wrap gap-2">
              <button type="button" className="rounded border border-slate-300 px-2 py-1" onClick={() => copier(choisi.adresse)}><Copy className="mr-1 inline h-4 w-4" />Copier l'adresse</button>
              <a className="rounded border border-slate-300 px-2 py-1" href={choisi.adresse} target="_blank" rel="noreferrer"><ExternalLink className="mr-1 inline h-4 w-4" />Voir la page du visiteur</a>
              <a className="rounded border border-slate-300 px-2 py-1" href={`${API}/lieux-balises/${choisi.code}/qr.png`} target="_blank" rel="noreferrer"><QrCode className="mr-1 inline h-4 w-4" />Ouvrir le QR (à imprimer)</a>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
