// ============================================================================
// Lot 371 — Formulaire « Spécifications de votre automate » : création, logo, liens et réponses depuis les Paramètres.
//   - une clinique = un formulaire PUBLIC (le lien se partage à tous les propriétaires et fournisseurs d'automates) ;
//   - le formulaire porte le LOGO et le NOM de la clinique qui demande les informations ;
//   - les réponses (interface USB / série / TCP, protocole, tests, documents PDF…) se lisent ici, avec export CSV.
// Backend : /api/admin/formulaire-automates(/logo|/{id}|/{id}/reponses).
// ============================================================================
import React, { useCallback, useEffect, useState } from "react";
import { ClipboardList, Copy, ExternalLink, FileDown, ImagePlus, Plus, Save, Paperclip } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const dateHeure = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");
const erreur = (e, defaut) => e?.response?.data?.detail || defaut;

export default function FormulaireAutomatesSection() {
  const [formulaires, setFormulaires] = useState(null);   // null = chargement en cours
  const [selection, setSelection] = useState(null);       // formulaire en cours d'édition (null = nouveau)
  const [organisation, setOrganisation] = useState("");
  const [logo, setLogo] = useState("");
  const [message, setMessage] = useState("");
  const [enCours, setEnCours] = useState(false);
  const [reponses, setReponses] = useState(null);         // { titre, champs, reponses } du formulaire consulté
  const [ouvertId, setOuvertId] = useState(null);

  // Lecture de la liste des formulaires
  const charger = useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/formulaire-automates");
      setFormulaires(r.data.formulaires || []);
    } catch (e) {
      toast.error(erreur(e, "Lecture impossible"));
      setFormulaires([]);
    }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  // Remplit le formulaire de saisie avec une clinique existante (ou le vide pour une nouvelle)
  const editer = (f) => {
    setSelection(f);
    setOrganisation(f?.branding?.organisation || "");
    setLogo(f?.branding?.logo_url || "");
    setMessage(f?.branding?.message || "");
  };

  // Envoi du logo (PNG, JPEG ou WebP, 1 Mo au plus) : le serveur renvoie l'adresse à enregistrer
  const choisirLogo = async (e) => {
    const fichier = e.target.files?.[0];
    e.target.value = "";
    if (!fichier) return;
    const corps = new FormData();
    corps.append("file", fichier);
    const t = toast.loading("Patientez… envoi du logo");
    try {
      const r = await apiClient.post("/admin/formulaire-automates/logo", corps);
      setLogo(r.data.logo_url);
      toast.success("Logo reçu : pensez à enregistrer.", { id: t });
    } catch (err) { toast.error(erreur(err, "Logo refusé"), { id: t }); }
  };

  // Création ou mise à jour
  const enregistrer = async () => {
    setEnCours(true);
    try {
      const corps = { organisation, logo_url: logo, message };
      const r = selection
        ? await apiClient.put(`/admin/formulaire-automates/${selection.id}`, corps)
        : await apiClient.post("/admin/formulaire-automates", corps);
      toast.success(selection ? "Clinique mise à jour." : "Formulaire créé : copiez son lien ci-dessous.");
      editer(selection ? r.data : null);
      await charger();
    } catch (e) { toast.error(erreur(e, "Enregistrement impossible")); }
    finally { setEnCours(false); }
  };

  const basculerPublic = async (f) => {
    try {
      await apiClient.put(`/admin/formulaire-automates/${f.id}`, { is_public: !f.is_public });
      toast.success(f.is_public ? "Lien désactivé." : "Lien réactivé.");
      await charger();
    } catch (e) { toast.error(erreur(e, "Opération impossible")); }
  };

  const copier = async (lien) => {
    try { await navigator.clipboard.writeText(lien); toast.success("Lien copié."); }
    catch { toast.error("Copie impossible : sélectionnez le lien et copiez-le."); }
  };

  // Lecture des réponses d'un formulaire
  const voirReponses = async (f) => {
    if (ouvertId === f.id) { setOuvertId(null); setReponses(null); return; }
    const t = toast.loading("Patientez…");
    try {
      const r = await apiClient.get(`/admin/formulaire-automates/${f.id}/reponses`);
      setReponses(r.data); setOuvertId(f.id);
      toast.dismiss(t);
    } catch (e) { toast.error(erreur(e, "Lecture impossible"), { id: t }); }
  };

  // Export CSV (toutes les colonnes) : fichier enregistré par le navigateur
  const exporterCsv = async (f) => {
    try {
      const r = await apiClient.get(`/admin/formulaire-automates/${f.id}/reponses`, { params: { format: "csv" }, responseType: "blob" });
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url; a.download = `automates_${f.number || f.id}.csv`; a.click();
      URL.revokeObjectURL(url);
    } catch (e) { toast.error(erreur(e, "Export impossible")); }
  };

  const cls = "w-full rounded-lg border border-slate-300 dark:border-white/20 bg-white dark:bg-white/10 px-3 py-2 text-sm";

  return (
    <div className="space-y-5" data-testid="formulaire-automates-section">
      <p className="text-sm text-slate-600 dark:text-slate-300">
        Envoyez un seul lien aux propriétaires et fournisseurs d'automates : ils indiquent la marque, le modèle, la connexion (USB, série ou réseau),
        le protocole, les tests et joignent les documents du constructeur. Le formulaire porte le logo et le nom de la clinique qui demande ces informations.
      </p>

      {/* Saisie : nouvelle clinique ou modification */}
      <div className="rounded-xl border border-slate-200 dark:border-white/10 p-4 grid gap-3 max-w-xl">
        <h4 className="font-semibold text-sm flex items-center gap-2"><ClipboardList className="h-4 w-4" /> {selection ? `Modifier : ${selection.branding?.organisation}` : "Nouveau formulaire pour une clinique"}</h4>
        <label className="grid gap-1 text-xs font-semibold">Nom de la clinique
          <input value={organisation} onChange={(e) => setOrganisation(e.target.value)} maxLength={120} className={cls} placeholder="ex. Clinique Philadelphie" data-testid="fa-organisation" />
        </label>
        <div className="grid gap-1 text-xs font-semibold">Logo de la clinique (PNG, JPEG ou WebP, 1 Mo au plus)
          <div className="flex items-center gap-3">
            <span className="h-14 w-14 rounded-lg border border-slate-300 dark:border-white/20 bg-white flex items-center justify-center overflow-hidden">
              {logo ? <img src={logo} alt="Logo" className="max-h-full max-w-full object-contain" /> : <ImagePlus className="h-5 w-5 text-slate-400" />}
            </span>
            <label className="inline-flex items-center gap-2 rounded-lg border border-slate-300 dark:border-white/20 px-3 py-2 text-sm font-normal cursor-pointer">
              <ImagePlus className="h-4 w-4" /> Choisir le logo
              <input type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" onChange={choisirLogo} data-testid="fa-logo-input" />
            </label>
            {logo && <button type="button" onClick={() => setLogo("")} className="text-xs font-normal underline">Retirer</button>}
          </div>
        </div>
        <label className="grid gap-1 text-xs font-semibold">Message d'accueil (facultatif)
          <textarea rows={3} maxLength={600} value={message} onChange={(e) => setMessage(e.target.value)} className={cls} placeholder="ex. Merci de nous aider à relier vos automates à notre logiciel." />
        </label>
        <div className="flex gap-2 flex-wrap boutons-distincts">
          <button onClick={enregistrer} disabled={enCours || !organisation.trim()} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm disabled:opacity-50" data-testid="fa-enregistrer">
            {selection ? <Save className="h-4 w-4" /> : <Plus className="h-4 w-4" />} {selection ? "Enregistrer" : "Créer le formulaire"}
          </button>
          {selection && <button onClick={() => editer(null)} className="rounded-lg border px-4 py-2 text-sm">Nouvelle clinique</button>}
        </div>
      </div>

      {/* Liste des formulaires créés */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm tableau">
          <thead>
            <tr className="text-left">
              <th className="py-2 pr-3">Clinique</th><th className="py-2 pr-3">Lien à envoyer</th>
              <th className="py-2 pr-3 text-right">Réponses</th><th className="py-2 pr-3">Lien</th><th className="py-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {formulaires === null && <tr><td colSpan={5} className="py-3 text-slate-500">Patientez…</td></tr>}
            {formulaires?.length === 0 && <tr><td colSpan={5} className="py-3 text-slate-500">Aucun formulaire : créez-en un ci-dessus.</td></tr>}
            {(formulaires || []).map((f) => (
              <tr key={f.id} aria-selected={ouvertId === f.id} className="border-t border-slate-200 dark:border-white/10">
                <td className="py-2 pr-3">
                  <span className="inline-flex items-center gap-2">
                    {f.branding?.logo_url && <img src={f.branding.logo_url} alt="" className="h-6 w-6 object-contain rounded bg-white" />}
                    <button onClick={() => editer(f)} className="underline text-left">{f.branding?.organisation || f.title}</button>
                  </span>
                </td>
                <td className="py-2 pr-3 max-w-[18rem]"><code className="text-xs break-all select-all">{f.lien}</code></td>
                <td className="py-2 pr-3 text-right tabular-nums">{f.reponses}</td>
                <td className="py-2 pr-3">{f.is_public ? "Actif" : "Désactivé"}</td>
                <td className="py-2">
                  <div className="flex gap-1.5 flex-wrap boutons-distincts">
                    <button onClick={() => copier(f.lien)} className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs"><Copy className="h-3.5 w-3.5" /> Copier</button>
                    <a href={f.lien} target="_blank" rel="noreferrer" role="button" className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs"><ExternalLink className="h-3.5 w-3.5" /> Ouvrir</a>
                    <button onClick={() => voirReponses(f)} className="rounded-md border px-2 py-1 text-xs">{ouvertId === f.id ? "Masquer" : "Réponses"}</button>
                    <button onClick={() => exporterCsv(f)} className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs"><FileDown className="h-3.5 w-3.5" /> CSV</button>
                    <button onClick={() => basculerPublic(f)} className="rounded-md border px-2 py-1 text-xs">{f.is_public ? "Désactiver" : "Réactiver"}</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Réponses reçues : une carte par réponse, avec les documents joints */}
      {reponses && (
        <div className="space-y-3" data-testid="fa-reponses">
          <h4 className="font-semibold text-sm">{reponses.titre} — {reponses.reponses.length} réponse(s)</h4>
          {reponses.reponses.length === 0 && <p className="text-sm text-slate-500">Aucune réponse pour le moment.</p>}
          {reponses.reponses.map((l) => (
            <details key={l.id} className="rounded-xl border border-slate-200 dark:border-white/10 p-3">
              <summary className="cursor-pointer text-sm font-medium">
                {l.valeurs.f_fournisseur || l.repondant || "Réponse"} — {l.valeurs.f_constructeur} {l.valeurs.f_modele} <span className="text-xs text-slate-500">({dateHeure(l.date)})</span>
              </summary>
              <dl className="mt-3 grid gap-x-4 gap-y-1.5 sm:grid-cols-[minmax(0,16rem)_1fr] text-sm">
                {reponses.champs.filter((c) => l.valeurs[c.id]).map((c) => (
                  <React.Fragment key={c.id}>
                    <dt className="text-slate-500 text-xs sm:text-sm">{c.label}</dt>
                    <dd className="min-w-0 break-words whitespace-pre-line">{String(l.valeurs[c.id]).startsWith("http") && l.documents.some((d) => d.url === l.valeurs[c.id]) ? "Document joint (voir ci-dessous)" : l.valeurs[c.id]}</dd>
                  </React.Fragment>
                ))}
              </dl>
              {l.documents.length > 0 && (
                <div className="mt-3 flex gap-2 flex-wrap boutons-distincts">
                  {l.documents.map((d) => (
                    <a key={d.url} href={d.url} target="_blank" rel="noreferrer" role="button" className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs">
                      <Paperclip className="h-3.5 w-3.5" /> {d.nom} <span className="text-slate-500">({d.champ})</span>
                    </a>
                  ))}
                </div>
              )}
            </details>
          ))}
        </div>
      )}
    </div>
  );
}
