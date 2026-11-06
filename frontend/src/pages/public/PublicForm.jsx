import React, { useEffect, useRef, useState } from "react";
import axios from "axios";
import { useParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, ArrowRight, Send, RotateCcw, CheckCircle2, MapPin, Paperclip, Loader2, X } from "lucide-react";
import { LOGO_URL } from "@/lib/brand";
// Lot 36 — tableaux et signature : même rendu que le formulaire du portail
import { FieldInput } from "@/pages/portal/FormRunner";
import { EXEMPLE_NOM, EXEMPLE_EMAIL } from "@/lib/exemplesIdentite";   // exemples locaux (règle du 06/11/2026)

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Public anonymous form filler — served from /f/{formId}. Used for campaigns,
// QR codes, shared links. Respondent name & email are requested before submit
// so the form owner knows who filled it.
// Lot 36 — aussi servi par /fr/{jeton} : formulaire PRIVÉ ouvert par un lien crypté
// (Liluvine « !formulaire »), sans identifiant en clair dans l'adresse.
export default function PublicForm() {
  const { fid, jeton } = useParams();
  const source = jeton ? `${API}/public/forms/jeton/${jeton}` : `${API}/public/forms/${fid}`;
  const [form, setForm] = useState(null);
  const [data, setData] = useState({});
  const [activePage, setActivePage] = useState(0);
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);
  const [geo, setGeo] = useState(null);
  const [meta, setMeta] = useState({ respondent_name: "", respondent_email: "" });
  const [error, setError] = useState(null);
  // Lot 371 — identité de la clinique qui demande les informations (logo + nom + message) ; vide pour un formulaire ordinaire
  const [identite, setIdentite] = useState(null);
  // Lot 372 — brouillon : tout ce que le visiteur saisit est gardé sur son appareil (localStorage) et revient s'il rouvre le lien
  // (onglet fermé, connexion coupée, téléphone qui redémarre). Effacé après l'envoi ou la réinitialisation. Aucune donnée n'est envoyée au serveur.
  const cleBrouillon = `sawali-brouillon-formulaire:${jeton || fid}`;
  const [brouillonRestaure, setBrouillonRestaure] = useState(false);
  const brouillonPret = useRef(false);   // vrai une fois le brouillon lu : évite d'écraser le brouillon par un état vide au chargement

  useEffect(() => {
    axios.get(source)
      .then((r) => setForm(r.data))
      .catch((e) => setError(e?.response?.data?.detail || (jeton ? "Lien invalide ou expiré" : "Formulaire introuvable ou non public")));
    if (fid && !jeton) {
      axios.get(`${API}/public/forms/${fid}/identite`)
        .then((r) => { if (r.data?.organisation || r.data?.logo_url) setIdentite(r.data); })
        .catch(() => {});
    }
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (p) => setGeo({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy }),
        () => {}, { timeout: 4000 }
      );
    }
  }, [source, jeton, fid]);

  // Lecture du brouillon (une seule fois, quand le formulaire est chargé)
  useEffect(() => {
    if (!form || brouillonPret.current) return;
    try {
      const brut = window.localStorage.getItem(cleBrouillon);
      if (brut) {
        const b = JSON.parse(brut);
        if (b && typeof b === "object" && b.data && Object.keys(b.data).length + Object.values(b.meta || {}).filter(Boolean).length > 0) {
          setData(b.data);
          setMeta({ respondent_name: b.meta?.respondent_name || "", respondent_email: b.meta?.respondent_email || "" });
          setActivePage(Math.min(Math.max(0, b.page || 0), form.pages.length - 1));
          setBrouillonRestaure(true);
        }
      }
    } catch { /* stockage indisponible ou brouillon illisible : on repart d'un formulaire vide */ }
    brouillonPret.current = true;
  }, [form, cleBrouillon]);

  // Écriture du brouillon à chaque changement (après la lecture ci-dessus)
  useEffect(() => {
    if (!brouillonPret.current || done) return;
    try {
      window.localStorage.setItem(cleBrouillon, JSON.stringify({ data, meta, page: activePage, enregistre_le: new Date().toISOString() }));
    } catch { /* stockage plein ou refusé : le formulaire reste utilisable */ }
  }, [data, meta, activePage, done, cleBrouillon]);

  const effacerBrouillon = () => { try { window.localStorage.removeItem(cleBrouillon); } catch { /* sans effet */ } };

  const reset = () => { if (window.confirm("Effacer toutes les saisies ?")) { setData({}); setMeta({ respondent_name: "", respondent_email: "" }); setBrouillonRestaure(false); effacerBrouillon(); } };

  const submit = async () => {
    // Validate required fields (all pages)
    const missing = form.pages.flatMap((p) => p.fields).filter((f) => f.required && (data[f.id] === undefined || data[f.id] === null || data[f.id] === ""));
    if (missing.length) { toast.error(`Champs obligatoires manquants : ${missing.map((m) => m.label).join(", ").slice(0, 100)}`); return; }
    setSending(true);
    try {
      await axios.post(`${source}/submission`, { data, geo, ...meta });
      effacerBrouillon();   // la réponse est enregistrée sur le serveur : le brouillon n'a plus lieu d'être
      setDone(true);
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur d'envoi"); }
    finally { setSending(false); }
  };

  if (error) {
    return (
      <div className="min-h-screen bg-[#0E1F3D] text-white flex items-center justify-center p-6">
        <div className="max-w-md text-center">
          <img src={LOGO_URL} alt="SAWALI" className="h-12 w-12 mx-auto mb-4 rounded-lg ring-1 ring-white/20" />
          <h1 className="text-lg font-display font-bold mb-2">Formulaire non accessible</h1>
          <p className="text-sm text-slate-300">{error}</p>
        </div>
      </div>
    );
  }

  if (!form) return <div className="min-h-screen bg-[#0E1F3D] text-white flex items-center justify-center text-sm">Chargement…</div>;
  if (done) {
    return (
      <div className="min-h-screen bg-[#0E1F3D] text-white flex items-center justify-center p-6" data-testid="public-form-done">
        <div className="max-w-md text-center rounded-2xl bg-emerald-500/10 ring-2 ring-emerald-400 p-8">
          <CheckCircle2 className="h-12 w-12 mx-auto mb-4 text-emerald-300" />
          <h1 className="text-2xl font-display font-bold mb-2 text-emerald-200">Réponse enregistrée</h1>
          <p className="text-sm text-slate-200">Merci pour votre participation ! Vos réponses ont bien été transmises.</p>
        </div>
      </div>
    );
  }

  const page = form.pages[activePage] || { fields: [] };
  const isLastPage = activePage === form.pages.length - 1;

  return (
    <div className="min-h-screen bg-[#0E1F3D] text-white" data-testid="public-form-page">
      <header className="border-b border-white/10 bg-black/20">
        <div className="max-w-3xl mx-auto px-6 py-4 flex items-center gap-3" data-testid="public-form-header">
          {/* Lot 371 : logo de la clinique (sur fond blanc pour rester lisible) ; à défaut, logo SAWALI */}
          {identite?.logo_url ? (
            <span className="h-12 w-12 shrink-0 rounded-lg bg-white p-1 flex items-center justify-center">
              <img src={identite.logo_url} alt={identite.organisation || "Logo"} className="max-h-full max-w-full object-contain" data-testid="public-form-logo" />
            </span>
          ) : (
            <img src={LOGO_URL} alt="SAWALI" className="h-9 w-9 rounded-md ring-1 ring-white/20" />
          )}
          <div className="flex-1 min-w-0">
            {identite?.organisation
              ? <p className="text-xs font-semibold text-sawali-blue-light truncate" data-testid="public-form-organisation">{identite.organisation}</p>
              : <p className="text-[10px] uppercase tracking-[0.3em] text-sawali-blue-light">{jeton ? "Formulaire" : "Formulaire public"}</p>}
            <h1 className="text-base font-display font-bold truncate">{form.title}</h1>
          </div>
          <code className="text-[10px] font-mono bg-white/10 px-2 py-0.5 rounded">{form.number}</code>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-8 space-y-5">
        {form.description && <p className="text-sm text-slate-300 whitespace-pre-line">{form.description}</p>}
        {brouillonRestaure && (
          <div className="rounded-xl bg-sky-500/10 ring-1 ring-sky-400/40 px-4 py-2 text-xs text-sky-100 flex items-center gap-3 flex-wrap" data-testid="public-form-brouillon">
            <span className="flex-1 min-w-0">Votre saisie précédente a été retrouvée sur cet appareil. Vos réponses sont gardées automatiquement tant que vous n'avez pas cliqué sur « Envoyer ».</span>
            <button type="button" onClick={() => setBrouillonRestaure(false)} className="underline">Compris</button>
          </div>
        )}

        {/* Respondent info */}
        <div className="rounded-xl bg-white/5 ring-1 ring-white/10 p-5 grid sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-[11px] font-semibold uppercase text-slate-400 mb-1">Votre nom (optionnel)</label>
            <input value={meta.respondent_name} onChange={(e) => setMeta({ ...meta, respondent_name: e.target.value })} className="w-full rounded-lg bg-white/10 border border-white/20 px-3 py-2 text-sm" placeholder={`Ex. ${EXEMPLE_NOM}`} data-testid="public-form-name" />
          </div>
          <div>
            <label className="block text-[11px] font-semibold uppercase text-slate-400 mb-1">Votre email (optionnel)</label>
            <input type="email" value={meta.respondent_email} onChange={(e) => setMeta({ ...meta, respondent_email: e.target.value })} className="w-full rounded-lg bg-white/10 border border-white/20 px-3 py-2 text-sm" placeholder={`Ex. ${EXEMPLE_EMAIL}`} data-testid="public-form-email" />
          </div>
        </div>

        {/* Page nav */}
        {form.pages.length > 1 && (
          <div className="flex items-center justify-between rounded-xl bg-white/5 ring-1 ring-white/10 px-4 py-2">
            <button onClick={() => setActivePage(Math.max(0, activePage - 1))} disabled={activePage === 0} className="inline-flex items-center gap-1 text-sm hover:text-sawali-blue-light disabled:opacity-40" data-testid="pub-form-prev"><ArrowLeft className="h-4 w-4" /> Précédent</button>
            <span className="text-xs text-slate-300">Page {activePage + 1} / {form.pages.length}</span>
            <button onClick={() => setActivePage(Math.min(form.pages.length - 1, activePage + 1))} disabled={isLastPage} className="inline-flex items-center gap-1 text-sm hover:text-sawali-blue-light disabled:opacity-40" data-testid="pub-form-next">Suivant <ArrowRight className="h-4 w-4" /></button>
          </div>
        )}

        {/* 12-col grid */}
        <div className="grid grid-cols-12 gap-3 rounded-xl bg-white/5 ring-1 ring-white/10 p-5" data-testid="pub-form-grid">
          {page.fields.length === 0 && <p className="col-span-12 text-sm text-slate-400 italic">Aucun champ sur cette page.</p>}
          {page.fields.map((f) => (
            <div key={f.id} className="min-w-0" style={{ gridColumnStart: f.col_start || 1, gridColumn: `span ${Math.min(12, f.col_span || 12)} / span ${Math.min(12, f.col_span || 12)}` }}>
              <label className="block text-[11px] font-semibold uppercase tracking-wider text-slate-300 mb-1">
                {f.label}{f.required && <span className="text-rose-300 ml-1">*</span>}
              </label>
              <Input f={f} v={data[f.id]} onChange={(v) => setData((d) => ({ ...d, [f.id]: v }))} formId={jeton ? null : fid} />
            </div>
          ))}
        </div>

        {geo && <p className="text-[11px] text-emerald-300 inline-flex items-center gap-1"><MapPin className="h-3 w-3" /> Position enregistrée ({geo.lat.toFixed(4)}, {geo.lng.toFixed(4)})</p>}

        <div className="flex gap-2 flex-wrap">
          <button onClick={reset} className="inline-flex items-center gap-2 rounded-lg bg-white/10 hover:bg-white/20 px-4 py-2 text-sm"><RotateCcw className="h-4 w-4" /> Réinitialiser</button>
          <button onClick={submit} disabled={sending} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue hover:bg-sawali-blue-light text-white px-4 py-2 text-sm disabled:opacity-50" data-testid="pub-form-submit"><Send className="h-4 w-4" /> {sending ? "Envoi…" : "Envoyer mes réponses"}</button>
        </div>
      </main>
    </div>
  );
}

const Input = ({ f, v, onChange, formId }) => {
  const cls = "w-full rounded-lg bg-white/10 border border-white/20 px-3 py-2 text-sm text-white placeholder:text-slate-400 focus:outline-none focus:border-sawali-blue-light";
  switch (f.type) {
    case "textarea": return <textarea rows={4} value={v || ""} onChange={(e) => onChange(e.target.value)} className={cls} />;
    case "boolean": return <select value={v === true ? "true" : v === false ? "false" : ""} onChange={(e) => onChange(e.target.value === "true" ? true : e.target.value === "false" ? false : null)} className={cls}><option value="" className="text-slate-900">—</option><option value="true" className="text-slate-900">Oui</option><option value="false" className="text-slate-900">Non</option></select>;
    case "select": return <select value={v || ""} onChange={(e) => onChange(e.target.value)} className={cls}><option value="" className="text-slate-900">— Choisir —</option>{(f.options || []).map((o) => <option key={o} value={o} className="text-slate-900">{o}</option>)}</select>;
    // Lot 371 : cases à cocher (plus simples qu'une liste à choix multiples pour un visiteur extérieur)
    case "multiselect": return (
      <div className="grid gap-1.5">
        {(f.options || []).map((o) => {
          const choisi = (v || []).includes(o);
          return (
            <label key={o} className="flex items-start gap-2 text-sm cursor-pointer">
              <input type="checkbox" checked={choisi} className="mt-0.5" onChange={() => onChange(choisi ? (v || []).filter((x) => x !== o) : [...(v || []), o])} />
              <span>{o}</span>
            </label>
          );
        })}
      </div>
    );
    case "date": return <input type="date" value={v || ""} onChange={(e) => onChange(e.target.value)} className={cls} />;
    case "datetime": return <input type="datetime-local" value={v || ""} onChange={(e) => onChange(e.target.value)} className={cls} />;
    case "number": return <input type="number" value={v ?? ""} onChange={(e) => onChange(e.target.value === "" ? null : parseFloat(e.target.value))} className={cls} />;
    case "email": return <input type="email" value={v || ""} onChange={(e) => onChange(e.target.value)} className={cls} />;
    case "tel": return <input type="tel" value={v || ""} onChange={(e) => onChange(e.target.value)} className={cls} />;
    case "url": return <input type="url" value={v || ""} onChange={(e) => onChange(e.target.value)} className={cls} />;
    // Lot 36 — tableau à remplir et signature (formulaires créés depuis un document)
    case "table":
    case "signature":
      return <div className="rounded-lg bg-white p-1 text-slate-900"><FieldInput field={f} value={v} onChange={onChange} /></div>;
    case "file":
      // Lot 371 : dépôt de document sur un lien public (formulaire sans lien crypté) ; sinon l'ancien message
      return formId
        ? <DepotFichier f={f} v={v} onChange={onChange} formId={formId} />
        : <p className="rounded-lg border border-dashed border-white/30 px-3 py-2 text-xs text-slate-300">Pièce jointe : à transmettre directement à l'organisateur (envoi de fichier non disponible sur ce lien).</p>;
    default: return <input type="text" value={v || ""} onChange={(e) => onChange(e.target.value)} className={cls} />;
  }
};

// Lot 371 — dépôt d'un document (PDF, Word, Excel, image…, 15 Mo au plus) sur un formulaire public.
// Le fichier part tout de suite vers le serveur ; la réponse mémorise son adresse, qui sera transmise avec le formulaire.
const DepotFichier = ({ f, v, onChange, formId }) => {
  const [envoi, setEnvoi] = useState(false);
  const choisir = async (e) => {
    const fichier = e.target.files?.[0];
    e.target.value = "";
    if (!fichier) return;
    if (fichier.size > 15 * 1024 * 1024) { toast.error("Fichier trop volumineux (15 Mo au plus). Utilisez le champ « Lien de téléchargement »."); return; }
    setEnvoi(true);
    const corps = new FormData();
    corps.append("file", fichier);
    try {
      const r = await axios.post(`${API}/public/forms/${formId}/upload`, corps);
      onChange({ file_id: r.data.file_id, filename: r.data.filename, size: r.data.size, public_url: r.data.public_url });
      toast.success("Document reçu");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Envoi impossible");
    } finally { setEnvoi(false); }
  };
  if (v?.public_url) {
    return (
      <div className="flex items-center gap-2 rounded-lg bg-emerald-500/10 ring-1 ring-emerald-400/50 px-3 py-2 text-sm" data-testid={`depot-${f.id}`}>
        <Paperclip className="h-4 w-4 text-emerald-300 shrink-0" />
        <span className="flex-1 min-w-0 truncate">{v.filename}</span>
        <button type="button" onClick={() => onChange(null)} className="text-slate-300 hover:text-white" aria-label="Retirer le document"><X className="h-4 w-4" /></button>
      </div>
    );
  }
  return (
    <label className="flex items-center gap-2 rounded-lg border border-dashed border-white/30 px-3 py-2 text-sm text-slate-200 cursor-pointer hover:bg-white/5">
      {envoi ? <Loader2 className="h-4 w-4 animate-spin" /> : <Paperclip className="h-4 w-4" />}
      <span>{envoi ? "Patientez… envoi en cours" : "Choisir un document"}</span>
      <input type="file" accept={f.accept || undefined} className="sr-only" onChange={choisir} disabled={envoi} data-testid={`depot-input-${f.id}`} />
    </label>
  );
};
