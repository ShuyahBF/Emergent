/*
  Lot 43 — Actions d'une fiche de maintenance (fiche déjà enregistrée) :
  - PHOTOS de l'équipement ou des pièces : ajout (JPEG / PNG), annotation avant l'envoi avec
    l'outil déjà utilisé dans la discussion WhatsApp (ImageAnnotator : flèches, cercles,
    texte, flou…), téléchargement, suppression ;
  - ENVOI PAR WHATSAPP au numéro de la fiche : texte de la fiche + photos si le client a écrit
    dans les 24 h, sinon modèle Meta (1re photo en en-tête image si le modèle en prévoit une) ;
  - LIEN DE PAIEMENT Mobile Money (montant du diagnostic par défaut), payé ou non ;
  - FACTURER : facture (ou proforma) dans la Caisse, diagnostic + lignes ajoutées.
  API : /me/maintenance/{id}/photos | whatsapp | lien-paiement | facturer.
*/
import React, { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Camera, Copy, Download, FileText, Loader2, MessageCircle, Plus, Trash2, Wallet, X } from "lucide-react";
import { apiClient } from "@/lib/api";
import { Button } from "@/components/ui/button";
import ImageAnnotator from "@/components/ImageAnnotator";
import { parseTemplate, buildButtonSpecs } from "@/lib/waTemplate";

const erreur = (e, d) => { const x = e?.response?.data?.detail; return Array.isArray(x) ? x.map((i) => i.msg).join(" ; ") : x || d; };
const fcfa = (n) => `${Number(n || 0).toLocaleString("fr-FR")} FCFA`;
const champ = "w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm";

// ---- Photos -------------------------------------------------------------------------------
function Photos({ fiche, onChange }) {
  const [aAnnoter, setAAnnoter] = useState(null);      // File choisi, en cours d'annotation
  const [envoi, setEnvoi] = useState(false);
  const entree = useRef(null);

  const televerser = async (fichier) => {
    setEnvoi(true);
    try {
      const fd = new FormData();
      fd.append("fichier", fichier);
      await apiClient.post(`/me/maintenance/${fiche.id}/photos`, fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success("Photo ajoutée");
      onChange();
    } catch (e) { toast.error(erreur(e, "Photo refusée")); }
    finally { setEnvoi(false); }
  };
  const supprimer = async (p) => {
    if (!window.confirm("Supprimer cette photo ?")) return;
    try { await apiClient.delete(`/me/maintenance/${fiche.id}/photos/${p.id}`); onChange(); }
    catch (e) { toast.error(erreur(e, "Suppression impossible")); }
  };

  return (
    <section className="space-y-2" data-testid="maintenance-photos">
      <p className="text-sm font-semibold text-slate-800 flex items-center gap-1.5"><Camera className="h-4 w-4" /> Photos de l'équipement / des pièces</p>
      <div className="flex flex-wrap gap-2">
        {(fiche.photos || []).map((p) => (
          <div key={p.id} className="relative group w-24">
            <a href={p.url} target="_blank" rel="noreferrer"><img src={p.url} alt={p.nom} className="h-24 w-24 rounded-md object-cover ring-1 ring-slate-200" /></a>
            <div className="mt-0.5 flex justify-between">
              {/* Téléchargement de la photo (annotée) */}
              <a href={p.url} download={p.nom} className="p-0.5 text-slate-500 hover:text-slate-800" title="Télécharger"><Download className="h-3.5 w-3.5" /></a>
              <button type="button" onClick={() => supprimer(p)} className="p-0.5 text-rose-500 hover:text-rose-700" title="Supprimer"><Trash2 className="h-3.5 w-3.5" /></button>
            </div>
          </div>
        ))}
        <button type="button" onClick={() => entree.current?.click()} disabled={envoi}
          className="h-24 w-24 rounded-md border-2 border-dashed border-slate-300 text-slate-500 flex flex-col items-center justify-center text-xs hover:border-indigo-400"
          data-testid="maintenance-photo-ajouter">
          {envoi ? <Loader2 className="h-5 w-5 animate-spin" /> : <><Plus className="h-5 w-5" /> Photo</>}
        </button>
        <input ref={entree} type="file" accept="image/jpeg,image/png" className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) setAAnnoter(f); }} />
      </div>
      <p className="text-[11px] text-slate-500">JPEG ou PNG, 5 Mo au plus. Vous pouvez annoter la photo (flèches, cercles, texte, flou) avant de l'ajouter.</p>
      {aAnnoter && (
        <ImageAnnotator file={aAnnoter} onCancel={() => { const f = aAnnoter; setAAnnoter(null); if (window.confirm("Ajouter la photo sans annotation ?")) televerser(f); }}
          onDone={(annotee) => { setAAnnoter(null); televerser(annotee); }} />
      )}
    </section>
  );
}

// ---- Envoi par WhatsApp -------------------------------------------------------------------
function EnvoiWhatsApp({ fiche, onClose, onEnvoye }) {
  const [modeles, setModeles] = useState([]);
  const [nomModele, setNomModele] = useState("");
  const [variables, setVariables] = useState([]);
  const [enTete, setEnTete] = useState("");
  const [boutons, setBoutons] = useState([]);
  const [message, setMessage] = useState("");
  const [photos, setPhotos] = useState(true);
  const [lienPaiement, setLienPaiement] = useState(true);
  const [occupe, setOccupe] = useState(false);

  useEffect(() => { apiClient.get("/me/whatsapp/templates").then((r) => setModeles(r.data?.items || [])).catch(() => {}); }, []);
  const modele = useMemo(() => modeles.find((t) => t.name === nomModele) || null, [modeles, nomModele]);
  const analyse = useMemo(() => (modele ? parseTemplate(modele) : null), [modele]);
  // Valeurs proposées : numéro de fiche, matériel, statut, prix, lien de paiement
  useEffect(() => {
    if (!analyse) { setVariables([]); setEnTete(""); setBoutons([]); return; }
    const proposees = ["{{numero}}", "{{materiel}}", "{{statut}}", "{{prix}}", "{{lien_paiement}}"];
    setVariables(Array.from({ length: analyse.body.varCount || 0 }, (_, i) => proposees[i] || ""));
    setEnTete(analyse.header?.format === "TEXT" && analyse.header.varCount > 0 ? "{{numero}}" : "");
    setBoutons((analyse.buttons || []).map((b) => Array.from({ length: b.urlVarCount || 0 }, () => "")));
  }, [analyse]);

  // Modèle à en-tête image choisi alors qu'aucune photo ne part avec la fiche
  const sansPhoto = analyse?.header?.format === "IMAGE" && (!photos || !(fiche.photos || []).length);

  const envoyer = async (mode) => {
    setOccupe(true);
    try {
      const r = await apiClient.post(`/me/maintenance/${fiche.id}/whatsapp`, {
        mode, message: message || null, photos, inclure_lien_paiement: lienPaiement,
        template_name: nomModele || null, language_code: modele?.language || "fr", variables,
        header_text: enTete || null, header_image: analyse?.header?.format === "IMAGE",
        button_specs: analyse ? buildButtonSpecs(analyse, boutons) : null,
      });
      const d = r.data;
      toast.success(`Fiche envoyée (${d.mode === "text" ? "message libre" : "modèle Meta"}) — ${d.photos_envoyees} photo(s)`
        + (d.photos_non_envoyees ? `, ${d.photos_non_envoyees} photo(s) à renvoyer quand le client aura répondu` : ""));
      if (d.erreurs?.length) toast.warning(d.erreurs.join(" · "));
      onEnvoye?.();
      onClose();
    } catch (e) { toast.error(erreur(e, "Envoi impossible")); }
    finally { setOccupe(false); }
  };

  return (
    <div className="fixed inset-0 z-[85] bg-black/40 flex items-center justify-center p-3" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="bg-white rounded-xl w-full max-w-xl max-h-[90vh] overflow-y-auto p-5 space-y-3 text-sm" data-testid="maintenance-envoi-wa">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-slate-800 flex items-center gap-1.5"><MessageCircle className="h-4 w-4 text-emerald-600" /> Envoyer la fiche {fiche.numero}</h3>
          <button type="button" onClick={onClose}><X className="h-5 w-5" /></button>
        </div>
        <p className="text-slate-600">À : <b>{fiche.client_nom}</b> · {fiche.client_telephone || <span className="text-rose-600">numéro manquant</span>}</p>
        <label className="flex items-center gap-2"><input type="checkbox" checked={photos} onChange={(e) => setPhotos(e.target.checked)} /> Joindre les photos ({(fiche.photos || []).length})</label>
        {fiche.lien_paiement && (
          <label className="flex items-center gap-2"><input type="checkbox" checked={lienPaiement} onChange={(e) => setLienPaiement(e.target.checked)} /> Ajouter le lien de paiement</label>
        )}
        <section className="rounded-lg ring-1 ring-slate-200 p-3 space-y-1">
          <p className="font-semibold text-slate-800">Message libre (le client vous a écrit dans les 24 h)</p>
          <textarea rows={4} value={message} onChange={(e) => setMessage(e.target.value)} className={champ}
            placeholder="Vide = résumé complet de la fiche (matériel, motif, diagnostic, pièces, équipe, prix…)" />
        </section>
        <section className="rounded-lg ring-1 ring-slate-200 p-3 space-y-2">
          <p className="font-semibold text-slate-800">Modèle Meta (hors fenêtre de 24 h)</p>
          <select value={nomModele} onChange={(e) => setNomModele(e.target.value)} className={champ} data-testid="maintenance-modele">
            <option value="">— Aucun —</option>
            {modeles.map((t) => <option key={`${t.name}-${t.language}`} value={t.name}>{t.name} · {t.language}</option>)}
          </select>
          {analyse && (
            <>
              {analyse.header?.format === "IMAGE" && (
                // Modèle à en-tête image : il faut au moins une photo jointe, sinon Meta refuse l'envoi
                sansPhoto
                  ? <p className="rounded bg-rose-50 p-2 text-xs text-rose-700" data-testid="maintenance-modele-sans-photo">
                      Ce modèle a un en-tête image, mais la fiche n'a aucune photo{(fiche.photos || []).length ? " jointe (cochez « Joindre les photos »)" : ""}.
                      Ajoutez une photo, ou choisissez un modèle sans en-tête image (ex. sawali_fiche_maintenance_texte).
                    </p>
                  : <p className="text-[11px] text-slate-500">En-tête image : la 1re photo de la fiche.</p>
              )}
              {analyse.header?.format === "TEXT" && analyse.header.varCount > 0 && (
                <input value={enTete} onChange={(e) => setEnTete(e.target.value)} className={champ} placeholder="En-tête {{1}}" />
              )}
              <p className="rounded bg-emerald-50 p-2 text-xs whitespace-pre-line">{analyse.body.text}</p>
              {variables.map((v, i) => (
                <label key={i} className="flex items-center gap-2 text-xs"><span className="w-10 font-mono">{`{{${i + 1}}}`}</span>
                  <input value={v} onChange={(e) => setVariables(variables.map((x, k) => (k === i ? e.target.value : x)))} className={champ} /></label>
              ))}
              {analyse.buttons.map((b, bi) => (b.urlVarCount > 0 ? (
                <label key={bi} className="flex items-center gap-2 text-xs"><span className="shrink-0">Bouton « {b.text} »</span>
                  <input value={boutons[bi]?.[0] || ""} onChange={(e) => setBoutons(boutons.map((x, k) => (k === bi ? [e.target.value] : x)))} className={champ} /></label>
              ) : null))}
              <p className="text-[11px] text-slate-500">
                Jetons : {"{{numero}} {{client}} {{materiel}} {{motif}} {{statut}} {{diagnostic}} {{equipe}} {{prix}} {{lien_paiement}}"}.
                Hors 24 h, WhatsApp n'accepte pas d'autres photos que l'en-tête : renvoyez-les quand le client aura répondu.
              </p>
            </>
          )}
        </section>
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Annuler</Button>
          <Button onClick={() => envoyer("auto")} disabled={occupe || !fiche.client_telephone || sansPhoto} data-testid="maintenance-envoyer-wa">
            {occupe && <Loader2 className="h-4 w-4 mr-1 animate-spin" />} Envoyer
          </Button>
        </div>
        <p className="text-[11px] text-slate-500 text-right">« Envoyer » choisit seul : message libre si le client a écrit dans les 24 h, sinon le modèle.</p>
      </div>
    </div>
  );
}

// ---- Facturer ---------------------------------------------------------------------------
function Facturer({ fiche, onClose, onFacture }) {
  const [kind, setKind] = useState("invoice");
  const [lignes, setLignes] = useState([]);
  const [occupe, setOccupe] = useState(false);
  const total = (fiche.prix_diagnostic || 0) + lignes.reduce((s, l) => s + (Number(l.quantity) || 0) * (Number(l.unit_price_ht) || 0), 0);

  const valider = async () => {
    setOccupe(true);
    try {
      const r = await apiClient.post(`/me/maintenance/${fiche.id}/facturer`, {
        kind, lignes: lignes.filter((l) => l.label.trim()).map((l) => ({ ...l, quantity: Number(l.quantity) || 1, unit_price_ht: Number(l.unit_price_ht) || 0 })) });
      toast.success(`${kind === "invoice" ? "Facture" : "Proforma"} ${r.data.numero} créée dans la Caisse`);
      onFacture?.();
      onClose();
    } catch (e) { toast.error(erreur(e, "Facturation impossible")); }
    finally { setOccupe(false); }
  };

  return (
    <div className="fixed inset-0 z-[85] bg-black/40 flex items-center justify-center p-3" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="bg-white rounded-xl w-full max-w-lg p-5 space-y-3 text-sm" data-testid="maintenance-facturer">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-slate-800 flex items-center gap-1.5"><FileText className="h-4 w-4" /> Facturer la fiche {fiche.numero}</h3>
          <button type="button" onClick={onClose}><X className="h-5 w-5" /></button>
        </div>
        <div className="flex gap-3">
          <label className="flex items-center gap-1"><input type="radio" checked={kind === "invoice"} onChange={() => setKind("invoice")} /> Facture</label>
          <label className="flex items-center gap-1"><input type="radio" checked={kind === "proforma"} onChange={() => setKind("proforma")} /> Proforma</label>
        </div>
        <p className="rounded bg-slate-50 p-2">Diagnostic — {fiche.type_materiel} : <b>{fcfa(fiche.prix_diagnostic)}</b></p>
        {lignes.map((l, i) => (
          <div key={i} className="flex gap-1">
            <input className={champ} placeholder="Libellé (pièce, main-d'œuvre…)" value={l.label} onChange={(e) => setLignes(lignes.map((x, k) => (k === i ? { ...x, label: e.target.value } : x)))} />
            <input className={`${champ} w-16`} type="number" min={1} value={l.quantity} onChange={(e) => setLignes(lignes.map((x, k) => (k === i ? { ...x, quantity: e.target.value } : x)))} />
            <input className={`${champ} w-28`} type="number" min={0} placeholder="Prix" value={l.unit_price_ht} onChange={(e) => setLignes(lignes.map((x, k) => (k === i ? { ...x, unit_price_ht: e.target.value } : x)))} />
            <button type="button" onClick={() => setLignes(lignes.filter((_, k) => k !== i))} className="text-rose-500"><Trash2 className="h-4 w-4" /></button>
          </div>
        ))}
        <button type="button" onClick={() => setLignes([...lignes, { label: "", quantity: 1, unit_price_ht: "" }])} className="text-xs text-indigo-600 hover:underline inline-flex items-center gap-1"><Plus className="h-3.5 w-3.5" /> Ajouter une ligne</button>
        <p className="text-right font-semibold">Total : {fcfa(total)}</p>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Annuler</Button>
          <Button onClick={valider} disabled={occupe || total <= 0} data-testid="maintenance-facturer-valider">{occupe && <Loader2 className="h-4 w-4 mr-1 animate-spin" />} Créer</Button>
        </div>
      </div>
    </div>
  );
}

// ---- Barre d'actions de la fiche -----------------------------------------------------------
export default function MaintenanceActions({ fiche, onChange }) {
  const [envoiWa, setEnvoiWa] = useState(false);
  const [facturer, setFacturer] = useState(false);
  const [occupe, setOccupe] = useState(false);

  const creerLien = async () => {
    setOccupe(true);
    try { await apiClient.post(`/me/maintenance/${fiche.id}/lien-paiement`, {}); toast.success("Lien de paiement créé"); onChange(); }
    catch (e) { toast.error(erreur(e, "Lien de paiement impossible")); }
    finally { setOccupe(false); }
  };
  const lien = fiche.lien_paiement;

  return (
    <div className="space-y-3 rounded-lg bg-slate-50 p-3" data-testid="maintenance-actions">
      <Photos fiche={fiche} onChange={onChange} />
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700" onClick={() => setEnvoiWa(true)} data-testid="maintenance-wa">
          <MessageCircle className="h-4 w-4 mr-1" /> Envoyer par WhatsApp
        </Button>
        {!lien ? (
          <Button size="sm" variant="outline" onClick={creerLien} disabled={occupe} data-testid="maintenance-lien-paiement">
            <Wallet className="h-4 w-4 mr-1" /> Lien de paiement ({fcfa(fiche.prix_diagnostic)})
          </Button>
        ) : (
          <span className="inline-flex items-center gap-1 rounded-md bg-white ring-1 ring-slate-200 px-2 py-1 text-xs">
            <Wallet className="h-3.5 w-3.5" /> {fcfa(lien.montant)}
            <span className={`rounded-full px-1.5 ${lien.paye ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>{lien.paye ? "payé" : "en attente"}</span>
            <button type="button" title="Copier le lien" onClick={() => { navigator.clipboard?.writeText(lien.url); toast.success("Lien copié"); }}><Copy className="h-3.5 w-3.5" /></button>
          </span>
        )}
        {fiche.facture ? (
          <span className="text-xs rounded-md bg-indigo-100 text-indigo-700 px-2 py-1">{fiche.facture.kind === "invoice" ? "Facturé" : "Proforma"} : {fiche.facture.numero}</span>
        ) : null}
        {(!fiche.facture || fiche.facture.kind !== "invoice") && (
          <Button size="sm" variant="outline" onClick={() => setFacturer(true)} data-testid="maintenance-facturer-btn"><FileText className="h-4 w-4 mr-1" /> Facturer</Button>
        )}
      </div>
      {envoiWa && <EnvoiWhatsApp fiche={fiche} onClose={() => setEnvoiWa(false)} onEnvoye={onChange} />}
      {facturer && <Facturer fiche={fiche} onClose={() => setFacturer(false)} onFacture={onChange} />}
    </div>
  );
}
