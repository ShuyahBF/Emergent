/*
  Lot 47 — Parc informatique : interventions (onglet « Interventions » de
  pages/portal/ParcInformatique.jsx et historique de la fiche d'un équipement).
  - Formulaire : un ou plusieurs équipements, type, début / fin (ou Démarrer / Terminer),
    équipe en étiquettes (noms libres ou comptes de la plateforme), problème, actions, pièces
    remplacées, résultat, recommandations, état des équipements après intervention, responsable
    du client, photos (annotables, comme la maintenance) ;
  - Rapport : lien public à lire et signer par le responsable, Copier le lien, PDF, envoi par
    WhatsApp (message libre dans les 24 h, sinon modèle Meta) ou par e-mail ;
  - Badges « Signé » / « En attente de signature » ; intervention verrouillée une fois signée.
  API : /me/parc/interventions…, /me/parc-equipe, /me/parc-responsable (backend/routes/parc_informatique.py).
*/
import React, { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { CheckCircle2, Clock, Copy, Download, ExternalLink, Loader2, Lock, MessageCircle, Play, Plus, Search, Trash2, X } from "lucide-react";
import { apiClient } from "@/lib/api";
import { Button } from "@/components/ui/button";
import ImageAnnotator from "@/components/ImageAnnotator";
import { parseTemplate, buildButtonSpecs } from "@/lib/waTemplate";

export const champ = "w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500";
export const erreur = (e, d) => { const x = e?.response?.data?.detail; return Array.isArray(x) ? x.map((i) => i.msg).join(" ; ") : x || d; };
export const dateHeureFr = (d) => (d ? new Date(d).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short", timeZone: "UTC" }) : "—");
export const dureeFr = (m) => { const n = Number(m || 0); return n >= 60 ? `${Math.floor(n / 60)} h ${String(n % 60).padStart(2, "0")} min` : `${n} min`; };
export const ETATS = {
  en_service: ["En service", "bg-emerald-100 text-emerald-700"],
  en_panne: ["En panne", "bg-rose-100 text-rose-700"],
  en_reparation: ["En réparation", "bg-amber-100 text-amber-800"],
  en_stock: ["En stock", "bg-sky-100 text-sky-700"],
  reforme: ["Réformé", "bg-slate-200 text-slate-600"],
};
export const TYPES = { preventive: "Préventive", curative: "Curative", installation: "Installation", mise_a_jour: "Mise à jour", audit: "Audit", autre: "Autre" };
const STATUTS = { planifiee: ["Planifiée", "bg-slate-100 text-slate-700"], en_cours: ["En cours", "bg-blue-100 text-blue-700"], terminee: ["Terminée", "bg-emerald-100 text-emerald-700"] };
// ISO UTC -> valeur d'un champ datetime-local (heure de Ouagadougou = UTC)
const versChamp = (iso) => (iso ? iso.slice(0, 16) : "");

// Badge de signature du rapport
export function BadgeSignature({ iv }) {
  if (iv.etat_signature === "signe") {
    return <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] text-emerald-700" data-testid="parc-badge-signe"><CheckCircle2 className="h-3 w-3" /> Signé</span>;
  }
  if (iv.etat_signature === "en_attente") {
    return <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] text-amber-800" data-testid="parc-badge-attente"><Clock className="h-3 w-3" /> En attente de signature</span>;
  }
  return <span className="text-[11px] text-slate-400">Rapport non émis</span>;
}

// Télécharge un fichier renvoyé par l'API (PDF, CSV) avec le jeton de connexion
export async function telecharger(url, nom, params) {
  try {
    const r = await apiClient.get(url, { params, responseType: "blob" });
    const lien = document.createElement("a");
    lien.href = URL.createObjectURL(r.data);
    lien.download = nom;
    lien.click();
    setTimeout(() => URL.revokeObjectURL(lien.href), 5000);
  } catch { toast.error("Téléchargement impossible"); }
}

// Photos (équipement ou intervention) : ajout annotable, téléchargement, suppression
export function PhotosParc({ base, photos, verrouille, onChange }) {
  const [aAnnoter, setAAnnoter] = useState(null);
  const [envoi, setEnvoi] = useState(false);
  const entree = useRef(null);
  const televerser = async (fichier) => {
    setEnvoi(true);
    try {
      const fd = new FormData();
      fd.append("fichier", fichier);
      await apiClient.post(`${base}/photos`, fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success("Photo ajoutée");
      onChange();
    } catch (e) { toast.error(erreur(e, "Photo refusée")); }
    finally { setEnvoi(false); }
  };
  const supprimer = async (p) => {
    if (!window.confirm("Supprimer cette photo ?")) return;
    try { await apiClient.delete(`${base}/photos/${p.id}`); onChange(); } catch (e) { toast.error(erreur(e, "Suppression impossible")); }
  };
  return (
    <div className="flex flex-wrap gap-2">
      {(photos || []).map((p) => (
        <div key={p.id} className="w-20">
          <a href={p.url} target="_blank" rel="noreferrer"><img src={p.url} alt={p.nom} className="h-20 w-20 rounded object-cover ring-1 ring-slate-200" /></a>
          <div className="flex justify-between">
            <a href={p.url} download={p.nom} className="p-0.5 text-slate-500" title="Télécharger"><Download className="h-3.5 w-3.5" /></a>
            {!verrouille && <button type="button" onClick={() => supprimer(p)} className="p-0.5 text-rose-500" title="Supprimer"><Trash2 className="h-3.5 w-3.5" /></button>}
          </div>
        </div>
      ))}
      {!verrouille && (
        <button type="button" onClick={() => entree.current?.click()} disabled={envoi}
          className="flex h-20 w-20 flex-col items-center justify-center rounded border-2 border-dashed border-slate-300 text-xs text-slate-500 hover:border-indigo-400">
          {envoi ? <Loader2 className="h-5 w-5 animate-spin" /> : <><Plus className="h-5 w-5" /> Photo</>}
        </button>
      )}
      <input ref={entree} type="file" accept="image/jpeg,image/png" className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) setAAnnoter(f); }} />
      {aAnnoter && (
        <ImageAnnotator file={aAnnoter} onCancel={() => { const f = aAnnoter; setAAnnoter(null); if (window.confirm("Ajouter la photo sans annotation ?")) televerser(f); }}
          onDone={(annotee) => { setAAnnoter(null); televerser(annotee); }} />
      )}
    </div>
  );
}

// Équipe : étiquettes (Entrée ou virgule pour ajouter), suggestions = comptes de la plateforme
function EquipeTags({ valeur, onChange, suggestions }) {
  const [saisie, setSaisie] = useState("");
  const ajouter = (texte) => {
    const nom = texte.trim().replace(/,$/, "").trim();
    if (!nom || valeur.some((m) => m.nom.toLowerCase() === nom.toLowerCase())) { setSaisie(""); return; }
    const compte = suggestions.find((s) => s.nom.toLowerCase() === nom.toLowerCase());
    onChange([...valeur, { nom: compte?.nom || nom, user_id: compte?.user_id || null }]);
    setSaisie("");
  };
  return (
    <div className="flex flex-wrap items-center gap-1 rounded-md border border-slate-300 px-2 py-1" data-testid="parc-equipe">
      {valeur.map((m) => (
        <span key={m.nom} className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs ${m.user_id ? "bg-indigo-100 text-indigo-700" : "bg-slate-100 text-slate-700"}`}>
          {m.nom}
          <button type="button" onClick={() => onChange(valeur.filter((x) => x !== m))}><X className="h-3 w-3" /></button>
        </span>
      ))}
      <input list="parc-equipe-comptes" className="min-w-[120px] flex-1 border-0 p-1 text-sm focus:outline-none" value={saisie}
        placeholder={valeur.length ? "" : "Nom puis Entrée"} onChange={(e) => (e.target.value.endsWith(",") ? ajouter(e.target.value) : setSaisie(e.target.value))}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); ajouter(saisie); } }} onBlur={() => saisie && ajouter(saisie)} />
      <datalist id="parc-equipe-comptes">{suggestions.map((s) => <option key={s.user_id} value={s.nom} />)}</datalist>
    </div>
  );
}

const VIDE = { equipement_ids: [], type_intervention: "curative", debut: "", fin: "", equipe: [], probleme: "", actions: "",
  pieces: [], resultat: "", recommandations: "", etat_apres: "", responsable: { nom: "", fonction: "", telephone: "", email: "" } };

// Formulaire d'intervention (nouvelle ou existante) ; `equipementsInitiaux` : ids présélectionnés
export function FormulaireIntervention({ intervention, equipements, compteClientId, equipementsInitiaux, onClose, onEnregistre }) {
  const [iv, setIv] = useState(intervention);
  const [f, setF] = useState(() => (intervention ? {
    ...VIDE, ...intervention, debut: versChamp(intervention.debut), fin: versChamp(intervention.fin),
    etat_apres: intervention.etat_apres || "", responsable: { ...VIDE.responsable, ...(intervention.responsable || {}) },
    probleme: intervention.probleme || "", actions: intervention.actions || "", resultat: intervention.resultat || "",
    recommandations: intervention.recommandations || "",
  } : { ...VIDE, equipement_ids: equipementsInitiaux || [] }));
  const [suggestions, setSuggestions] = useState([]);
  const [filtre, setFiltre] = useState("");
  const [occupe, setOccupe] = useState(false);
  const verrouille = !!iv?.signee;
  const maj = (x) => setF((p) => ({ ...p, ...x }));

  useEffect(() => {
    apiClient.get("/me/parc-equipe").then((r) => setSuggestions(r.data.items || [])).catch(() => {});
    // Responsable du client proposé pour une nouvelle intervention
    if (!intervention) {
      apiClient.get("/me/parc-responsable", { params: { compte_client_id: compteClientId || undefined } })
        .then((r) => setF((p) => ({ ...p, responsable: { ...p.responsable, ...r.data } }))).catch(() => {});
    }
  }, [intervention, compteClientId]);

  const visibles = useMemo(() => {
    const t = filtre.trim().toLowerCase();
    return equipements.filter((e) => !t || [e.numero_inventaire, e.categorie, e.fabricant, e.modele, e.numero_serie, e.site, e.utilisateur_affecte]
      .some((x) => (x || "").toLowerCase().includes(t)));
  }, [equipements, filtre]);
  const basculer = (id) => maj({ equipement_ids: f.equipement_ids.includes(id) ? f.equipement_ids.filter((x) => x !== id) : [...f.equipement_ids, id] });

  const recharger = async () => { const r = await apiClient.get(`/me/parc/interventions/${iv.id}`); setIv(r.data); return r.data; };
  const enregistrer = async () => {
    setOccupe(true);
    const corps = { equipement_ids: f.equipement_ids, type_intervention: f.type_intervention, debut: f.debut || null, fin: f.fin || null,
      equipe: f.equipe, probleme: f.probleme, actions: f.actions, resultat: f.resultat, recommandations: f.recommandations,
      pieces: f.pieces.filter((p) => p.designation.trim()).map((p) => ({ ...p, quantite: Number(p.quantite) || 1 })),
      etat_apres: f.etat_apres || null, responsable: f.responsable };
    try {
      const r = iv ? await apiClient.put(`/me/parc/interventions/${iv.id}`, corps) : await apiClient.post("/me/parc/interventions", corps);
      toast.success(iv ? "Intervention mise à jour" : `Intervention ${r.data.numero} créée`);
      setIv(r.data);
      onEnregistre?.(r.data);
    } catch (e) { toast.error(erreur(e, "Enregistrement impossible")); }
    finally { setOccupe(false); }
  };
  const etape = async (action) => {
    try {
      const r = await apiClient.post(`/me/parc/interventions/${iv.id}/${action}`);
      setIv(r.data); maj({ debut: versChamp(r.data.debut), fin: versChamp(r.data.fin) }); onEnregistre?.(r.data);
      toast.success(action === "demarrer" ? "Intervention démarrée" : "Intervention terminée");
    } catch (e) { toast.error(erreur(e, "Action impossible")); }
  };

  return (
    <div className="fixed inset-0 z-[75] flex items-center justify-center bg-black/40 p-2 sm:p-3">
      <div className="max-h-[94vh] w-full max-w-3xl space-y-3 overflow-y-auto rounded-xl bg-white p-4 sm:p-5" data-testid="parc-intervention-form">
        <div className="flex items-center justify-between gap-2">
          <h2 className="font-semibold text-slate-800">{iv ? `Intervention ${iv.numero}` : "Nouvelle intervention"}</h2>
          <div className="flex items-center gap-2">
            {iv && <BadgeSignature iv={iv} />}
            <button type="button" onClick={onClose}><X className="h-5 w-5" /></button>
          </div>
        </div>
        {verrouille && (
          <p className="flex items-center gap-1.5 rounded bg-emerald-50 p-2 text-xs text-emerald-800"><Lock className="h-3.5 w-3.5" />
            Rapport signé par {iv.signature?.nom} le {dateHeureFr(iv.signature?.signe_le)} : intervention verrouillée. Créez une nouvelle intervention pour tout complément.</p>
        )}
        <fieldset disabled={verrouille} className="grid gap-3 sm:grid-cols-2">
          <div className="sm:col-span-2 text-xs text-slate-600">Équipements concernés * ({f.equipement_ids.length})
            <div className="relative mt-1"><Search className="absolute left-2 top-2 h-4 w-4 text-slate-400" />
              <input className={`${champ} pl-8`} placeholder="Filtrer : inventaire, modèle, série, site…" value={filtre} onChange={(e) => setFiltre(e.target.value)} /></div>
            <div className="mt-1 max-h-40 overflow-y-auto rounded border border-slate-200">
              {visibles.map((e) => (
                <label key={e.id} className="flex cursor-pointer items-center gap-2 border-b border-slate-100 px-2 py-1 text-xs hover:bg-slate-50">
                  <input type="checkbox" checked={f.equipement_ids.includes(e.id)} onChange={() => basculer(e.id)} />
                  <span className="font-mono">{e.numero_inventaire}</span>
                  <span className="truncate">{[e.categorie, e.fabricant, e.modele].filter(Boolean).join(" ")}</span>
                  <span className="ml-auto hidden text-slate-400 sm:inline">{e.numero_serie || ""}</span>
                </label>
              ))}
              {!visibles.length && <p className="p-2 text-xs text-slate-400">Aucun équipement{compteClientId ? "" : " (choisissez le client)"}.</p>}
            </div>
          </div>
          <label className="text-xs text-slate-600">Type d'intervention
            <select className={champ} value={f.type_intervention} onChange={(e) => maj({ type_intervention: e.target.value })}>
              {Object.entries(TYPES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </label>
          <label className="text-xs text-slate-600">État des équipements après
            <select className={champ} value={f.etat_apres} onChange={(e) => maj({ etat_apres: e.target.value })} data-testid="parc-etat-apres">
              <option value="">— Inchangé —</option>
              {Object.entries(ETATS).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </label>
          <label className="text-xs text-slate-600">Début
            <input type="datetime-local" className={champ} value={f.debut} onChange={(e) => maj({ debut: e.target.value })} />
          </label>
          <label className="text-xs text-slate-600">Fin
            <input type="datetime-local" className={champ} value={f.fin} onChange={(e) => maj({ fin: e.target.value })} />
          </label>
          <div className="sm:col-span-2 text-xs text-slate-600">Équipe (personnes)
            <EquipeTags valeur={f.equipe} onChange={(equipe) => maj({ equipe })} suggestions={suggestions} />
          </div>
          <label className="sm:col-span-2 text-xs text-slate-600">Problème constaté
            <textarea rows={2} className={champ} value={f.probleme} onChange={(e) => maj({ probleme: e.target.value })} />
          </label>
          <label className="sm:col-span-2 text-xs text-slate-600">Actions réalisées
            <textarea rows={3} className={champ} value={f.actions} onChange={(e) => maj({ actions: e.target.value })} />
          </label>
          <div className="sm:col-span-2 space-y-1 text-xs text-slate-600">Pièces remplacées
            {f.pieces.map((p, i) => (
              <div key={i} className="flex gap-1">
                <input className={champ} placeholder="Désignation" value={p.designation} onChange={(e) => maj({ pieces: f.pieces.map((x, k) => (k === i ? { ...x, designation: e.target.value } : x)) })} />
                <input className={`${champ} w-16`} type="number" min={1} value={p.quantite} onChange={(e) => maj({ pieces: f.pieces.map((x, k) => (k === i ? { ...x, quantite: e.target.value } : x)) })} />
                <input className={`${champ} w-28`} placeholder="Référence" value={p.reference || ""} onChange={(e) => maj({ pieces: f.pieces.map((x, k) => (k === i ? { ...x, reference: e.target.value } : x)) })} />
                <button type="button" onClick={() => maj({ pieces: f.pieces.filter((_, k) => k !== i) })} className="text-rose-500"><Trash2 className="h-4 w-4" /></button>
              </div>
            ))}
            <button type="button" onClick={() => maj({ pieces: [...f.pieces, { designation: "", quantite: 1, reference: "" }] })} className="inline-flex items-center gap-1 text-indigo-600 hover:underline"><Plus className="h-3.5 w-3.5" /> Ajouter une pièce</button>
          </div>
          <label className="text-xs text-slate-600">Résultat
            <textarea rows={2} className={champ} value={f.resultat} onChange={(e) => maj({ resultat: e.target.value })} />
          </label>
          <label className="text-xs text-slate-600">Recommandations
            <textarea rows={2} className={champ} value={f.recommandations} onChange={(e) => maj({ recommandations: e.target.value })} />
          </label>
          <div className="sm:col-span-2 grid gap-2 rounded-lg bg-slate-50 p-2 sm:grid-cols-4">
            <p className="sm:col-span-4 text-xs font-semibold text-slate-700">Responsable côté client (reçoit le rapport à signer)</p>
            {[["nom", "Nom"], ["fonction", "Fonction"], ["telephone", "Téléphone WhatsApp"], ["email", "E-mail"]].map(([k, l]) => (
              <label key={k} className="text-xs text-slate-600">{l}
                <input className={champ} value={f.responsable[k] || ""} onChange={(e) => maj({ responsable: { ...f.responsable, [k]: e.target.value } })} />
              </label>
            ))}
          </div>
        </fieldset>
        {iv?.id ? (
          <div className="space-y-2 rounded-lg bg-slate-50 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className={`rounded-full px-2 py-0.5 text-[11px] ${STATUTS[iv.statut]?.[1]}`}>{STATUTS[iv.statut]?.[0]}</span>
              {iv.duree_minutes != null && <span className="text-xs text-slate-600">Durée : <b>{dureeFr(iv.duree_minutes)}</b></span>}
              {!verrouille && !iv.debut && <Button size="sm" className="h-7 bg-blue-600 px-2 text-xs" onClick={() => etape("demarrer")}><Play className="mr-1 h-3.5 w-3.5" /> Démarrer</Button>}
              {!verrouille && iv.debut && !iv.fin && <Button size="sm" className="h-7 bg-emerald-600 px-2 text-xs" onClick={() => etape("terminer")}><CheckCircle2 className="mr-1 h-3.5 w-3.5" /> Terminer</Button>}
            </div>
            <p className="text-xs font-semibold text-slate-700">Photos</p>
            <PhotosParc base={`/me/parc/interventions/${iv.id}`} photos={iv.photos} verrouille={verrouille} onChange={recharger} />
            <ActionsRapport iv={iv} onChange={recharger} />
          </div>
        ) : <p className="text-[11px] text-slate-500">Enregistrez l'intervention pour ajouter des photos et émettre le rapport.</p>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Fermer</Button>
          {!verrouille && (
            <Button onClick={enregistrer} disabled={occupe || !f.equipement_ids.length} data-testid="parc-intervention-enregistrer">
              {occupe && <Loader2 className="mr-1 h-4 w-4 animate-spin" />} Enregistrer
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

// Rapport : ouvrir, copier le lien, PDF, envoyer
export function ActionsRapport({ iv, onChange, compact = false }) {
  const [envoi, setEnvoi] = useState(false);
  const lien = async () => {
    if (iv.rapport?.url && !iv.rapport.expire) return iv.rapport.url;
    try { const r = await apiClient.post(`/me/parc/interventions/${iv.id}/rapport`, {}); onChange?.(); return r.data.rapport.url; }
    catch (e) { toast.error(erreur(e, "Rapport impossible")); return null; }
  };
  const taille = compact ? "h-7 px-2 text-xs" : "";
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="parc-actions-rapport">
      <Button size="sm" variant="outline" className={taille} onClick={async () => { const u = await lien(); if (u) window.open(u, "_blank", "noopener"); }}>
        <ExternalLink className="mr-1 h-3.5 w-3.5" /> Rapport
      </Button>
      <Button size="sm" className={`bg-emerald-600 hover:bg-emerald-700 ${taille}`} onClick={() => setEnvoi(true)} data-testid="parc-envoyer">
        <MessageCircle className="mr-1 h-3.5 w-3.5" /> Envoyer le lien
      </Button>
      <Button size="sm" variant="outline" className={taille} title="Copier le lien"
        onClick={async () => { const u = await lien(); if (u) { navigator.clipboard?.writeText(u); toast.success("Lien copié"); } }}>
        <Copy className="h-3.5 w-3.5" />
      </Button>
      <Button size="sm" variant="outline" className={taille} title="PDF du rapport" onClick={() => telecharger(`/me/parc/interventions/${iv.id}/pdf`, `${iv.numero}.pdf`)}>
        <Download className="h-3.5 w-3.5" />
      </Button>
      {envoi && <EnvoiRapport iv={iv} onClose={() => setEnvoi(false)} onEnvoye={onChange} />}
    </div>
  );
}

// Envoi du lien : WhatsApp (libre dans les 24 h, sinon modèle Meta) ou e-mail
function EnvoiRapport({ iv, onClose, onEnvoye }) {
  const [canal, setCanal] = useState("whatsapp");
  const [telephone, setTelephone] = useState(iv.responsable?.telephone || "");
  const [email, setEmail] = useState(iv.responsable?.email || "");
  const [message, setMessage] = useState("");
  const [modeles, setModeles] = useState([]);
  const [nomModele, setNomModele] = useState("");
  const [variables, setVariables] = useState([]);
  const [enTete, setEnTete] = useState("");
  const [boutons, setBoutons] = useState([]);
  const [occupe, setOccupe] = useState(false);

  useEffect(() => { apiClient.get("/me/whatsapp/templates").then((r) => setModeles(r.data?.items || [])).catch(() => {}); }, []);
  const modele = useMemo(() => modeles.find((t) => t.name === nomModele) || null, [modeles, nomModele]);
  const analyse = useMemo(() => (modele ? parseTemplate(modele) : null), [modele]);
  // Valeurs proposées dans l'ordre du modèle conseillé : numéro, client, date, lien
  useEffect(() => {
    if (!analyse) { setVariables([]); setEnTete(""); setBoutons([]); return; }
    const proposees = ["{{numero}}", "{{client}}", "{{date}}", "{{lien}}"];
    setVariables(Array.from({ length: analyse.body.varCount || 0 }, (_, i) => proposees[i] || ""));
    setEnTete(analyse.header?.format === "TEXT" && analyse.header.varCount > 0 ? "{{numero}}" : "");
    setBoutons((analyse.buttons || []).map((b) => Array.from({ length: b.urlVarCount || 0 }, () => "{{jeton}}")));
  }, [analyse]);

  const envoyer = async () => {
    setOccupe(true);
    try {
      const r = await apiClient.post(`/me/parc/interventions/${iv.id}/envoyer`, {
        canal, mode: "auto", message: message || null, telephone: telephone || null, email: email || null,
        template_name: nomModele || null, language_code: modele?.language || "fr", variables, header_text: enTete || null,
        button_specs: analyse ? buildButtonSpecs(analyse, boutons) : null });
      toast.success(canal === "email" ? `Lien envoyé à ${r.data.a}` : `Lien envoyé par WhatsApp (${r.data.mode === "text" ? "message libre" : "modèle Meta"})`);
      onEnvoye?.();
      onClose();
    } catch (e) { toast.error(erreur(e, "Envoi impossible")); }
    finally { setOccupe(false); }
  };

  return (
    <div className="fixed inset-0 z-[85] flex items-center justify-center bg-black/40 p-3" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="max-h-[90vh] w-full max-w-xl space-y-3 overflow-y-auto rounded-xl bg-white p-5 text-sm" data-testid="parc-envoi">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-1.5 font-semibold text-slate-800"><MessageCircle className="h-4 w-4 text-emerald-600" /> Envoyer le rapport {iv.numero}</h3>
          <button type="button" onClick={onClose}><X className="h-5 w-5" /></button>
        </div>
        <p className="text-slate-600">Le responsable reçoit le lien pour lire et signer le rapport (valable 30 jours).</p>
        <div className="flex gap-3">
          <label className="flex items-center gap-1"><input type="radio" checked={canal === "whatsapp"} onChange={() => setCanal("whatsapp")} /> WhatsApp</label>
          <label className="flex items-center gap-1"><input type="radio" checked={canal === "email"} onChange={() => setCanal("email")} /> E-mail</label>
        </div>
        {canal === "email" ? (
          <label className="block text-xs text-slate-600">E-mail du responsable
            <input className={champ} value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
        ) : (
          <label className="block text-xs text-slate-600">Numéro WhatsApp du responsable
            <input className={champ} value={telephone} onChange={(e) => setTelephone(e.target.value)} />
          </label>
        )}
        <section className="space-y-1 rounded-lg p-3 ring-1 ring-slate-200">
          <p className="font-semibold text-slate-800">{canal === "email" ? "Message" : "Message libre (le responsable vous a écrit dans les 24 h)"}</p>
          <textarea rows={3} value={message} onChange={(e) => setMessage(e.target.value)} className={champ}
            placeholder="Vide = résumé du rapport (numéro, client, date, équipements, équipe) et lien de signature" />
        </section>
        {canal === "whatsapp" && (
          <section className="space-y-2 rounded-lg p-3 ring-1 ring-slate-200">
            <p className="font-semibold text-slate-800">Modèle Meta (hors fenêtre de 24 h)</p>
            <select value={nomModele} onChange={(e) => setNomModele(e.target.value)} className={champ} data-testid="parc-modele">
              <option value="">— Aucun —</option>
              {modeles.map((t) => <option key={`${t.name}-${t.language}`} value={t.name}>{t.name} · {t.language}</option>)}
            </select>
            {analyse && (
              <>
                {analyse.header?.format === "TEXT" && analyse.header.varCount > 0 && (
                  <input value={enTete} onChange={(e) => setEnTete(e.target.value)} className={champ} placeholder="En-tête {{1}}" />
                )}
                <p className="whitespace-pre-line rounded bg-emerald-50 p-2 text-xs">{analyse.body.text}</p>
                {variables.map((v, i) => (
                  <label key={i} className="flex items-center gap-2 text-xs"><span className="w-10 font-mono">{`{{${i + 1}}}`}</span>
                    <input value={v} onChange={(e) => setVariables(variables.map((x, k) => (k === i ? e.target.value : x)))} className={champ} /></label>
                ))}
                {analyse.buttons.map((b, bi) => (b.urlVarCount > 0 ? (
                  <label key={bi} className="flex items-center gap-2 text-xs"><span className="shrink-0">Bouton « {b.text} »</span>
                    <input value={boutons[bi]?.[0] || ""} onChange={(e) => setBoutons(boutons.map((x, k) => (k === bi ? [e.target.value] : x)))} className={champ} /></label>
                ) : null))}
                <p className="text-[11px] text-slate-500">Jetons : {"{{numero}} {{client}} {{date}} {{lien}} {{responsable}} {{type}} {{equipements}} {{equipe}} {{jeton}}"} ({"{{jeton}}"} : fin de l'adresse pour un bouton lien).</p>
              </>
            )}
          </section>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Annuler</Button>
          <Button onClick={envoyer} disabled={occupe || (canal === "email" ? !email : !telephone)} data-testid="parc-envoyer-valider">
            {occupe && <Loader2 className="mr-1 h-4 w-4 animate-spin" />} Envoyer
          </Button>
        </div>
        {canal === "whatsapp" && <p className="text-right text-[11px] text-slate-500">« Envoyer » choisit seul : message libre si le responsable a écrit dans les 24 h, sinon le modèle.</p>}
      </div>
    </div>
  );
}

// Onglet « Interventions » : liste, filtres, badges, actions
export default function ParcInterventions({ compteClientId, equipements, onChange }) {
  const [donnees, setDonnees] = useState(null);
  const [q, setQ] = useState("");
  const [signe, setSigne] = useState("");
  const [edition, setEdition] = useState(null);      // null | "nouvelle" | intervention

  const charger = React.useCallback(async () => {
    try {
      const r = await apiClient.get("/me/parc/interventions", { params: { q: q || undefined, signe: signe || undefined, compte_client_id: compteClientId || undefined } });
      setDonnees(r.data);
    } catch (e) { toast.error(erreur(e, "Interventions indisponibles")); }
  }, [q, signe, compteClientId]);
  useEffect(() => { const t = setTimeout(charger, 250); return () => clearTimeout(t); }, [charger]);

  const supprimer = async (iv) => {
    if (!window.confirm(`Supprimer l'intervention ${iv.numero} ?`)) return;
    try { await apiClient.delete(`/me/parc/interventions/${iv.id}`); toast.success("Intervention supprimée"); charger(); }
    catch (e) { toast.error(erreur(e, "Suppression impossible")); }
  };
  const compte = donnees?.compte || {};
  const filtres = [["", "Toutes"], ["en_attente", `En attente de signature (${compte.en_attente ?? 0})`], ["signe", `Signées (${compte.signe ?? 0})`], ["sans_rapport", `Sans rapport (${compte.sans_rapport ?? 0})`]];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {filtres.map(([k, l]) => (
          <button key={k || "toutes"} type="button" onClick={() => setSigne(k)}
            className={`rounded-full px-3 py-1 text-xs ring-1 ${signe === k ? "bg-slate-800 text-white ring-slate-800" : "bg-white ring-slate-300"}`}>{l}</button>
        ))}
        <Button className="ml-auto" onClick={() => setEdition("nouvelle")} disabled={!equipements.length} title={equipements.length ? "" : "Ajoutez d'abord des équipements"} data-testid="parc-intervention-nouvelle">
          <Plus className="mr-1 h-4 w-4" /> Nouvelle intervention
        </Button>
      </div>
      <div className="relative"><Search className="absolute left-2 top-2 h-4 w-4 text-slate-400" />
        <input className={`${champ} pl-8`} placeholder="N°, client, problème, équipe, inventaire, n° de série…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs text-slate-500">
            <tr><th className="p-2">N°</th><th className="p-2">Date</th><th className="p-2">Client</th><th className="p-2">Équipements</th><th className="p-2">Type</th><th className="p-2">Équipe</th><th className="p-2">Rapport</th><th className="p-2" /></tr>
          </thead>
          <tbody>
            {!donnees && <tr><td colSpan={8} className="p-4 text-center"><Loader2 className="inline h-4 w-4 animate-spin" /></td></tr>}
            {donnees?.interventions.length === 0 && <tr><td colSpan={8} className="p-4 text-center text-slate-400">Aucune intervention.</td></tr>}
            {(donnees?.interventions || []).map((iv) => (
              <tr key={iv.id} className="cursor-pointer border-t border-slate-100 align-top hover:bg-slate-50" onClick={() => setEdition(iv)}>
                <td className="p-2 font-mono text-xs">{iv.numero}<span className={`mt-0.5 block w-fit rounded-full px-1.5 text-[10px] ${STATUTS[iv.statut]?.[1]}`}>{STATUTS[iv.statut]?.[0]}</span></td>
                <td className="p-2 text-xs">{dateHeureFr(iv.debut || iv.cree_le)}{iv.duree_minutes != null && <span className="block text-slate-500">{dureeFr(iv.duree_minutes)}</span>}</td>
                <td className="p-2">{iv.client_nom}</td>
                <td className="p-2 text-xs">{(iv.equipements || []).map((e) => <span key={e.id} className="block font-mono">{e.numero_inventaire}</span>)}</td>
                <td className="p-2 text-xs">{TYPES[iv.type_intervention]}</td>
                <td className="p-2"><div className="flex flex-wrap gap-1">{(iv.equipe || []).map((m) => <span key={m.nom} className="rounded-full bg-slate-100 px-1.5 text-[11px]">{m.nom}</span>)}</div></td>
                <td className="p-2"><BadgeSignature iv={iv} /></td>
                <td className="p-2" onClick={(e) => e.stopPropagation()}>
                  <div className="flex items-center gap-1">
                    <ActionsRapport iv={iv} onChange={charger} compact />
                    {!iv.signee && <button type="button" title="Supprimer" onClick={() => supprimer(iv)} className="p-1 text-rose-500 hover:text-rose-700"><Trash2 className="h-4 w-4" /></button>}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {edition && (
        <FormulaireIntervention key={edition === "nouvelle" ? "nouvelle" : edition.id} intervention={edition === "nouvelle" ? null : edition}
          equipements={equipements} compteClientId={compteClientId} onClose={() => { setEdition(null); charger(); }}
          onEnregistre={() => { charger(); onChange?.(); }} />
      )}
    </div>
  );
}
