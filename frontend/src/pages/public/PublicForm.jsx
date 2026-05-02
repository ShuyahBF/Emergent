import React, { useEffect, useState } from "react";
import axios from "axios";
import { useParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, ArrowRight, Send, RotateCcw, CheckCircle2, MapPin } from "lucide-react";
import { LOGO_URL } from "@/lib/brand";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Public anonymous form filler — served from /f/{formId}. Used for campaigns,
// QR codes, shared links. Respondent name & email are requested before submit
// so the form owner knows who filled it.
export default function PublicForm() {
  const { fid } = useParams();
  const [form, setForm] = useState(null);
  const [data, setData] = useState({});
  const [activePage, setActivePage] = useState(0);
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);
  const [geo, setGeo] = useState(null);
  const [meta, setMeta] = useState({ respondent_name: "", respondent_email: "" });
  const [error, setError] = useState(null);

  useEffect(() => {
    axios.get(`${API}/public/forms/${fid}`)
      .then((r) => setForm(r.data))
      .catch((e) => setError(e?.response?.data?.detail || "Formulaire introuvable ou non public"));
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (p) => setGeo({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy }),
        () => {}, { timeout: 4000 }
      );
    }
  }, [fid]);

  const reset = () => { if (window.confirm("Effacer toutes les saisies ?")) setData({}); };

  const submit = async () => {
    // Validate required fields (all pages)
    const missing = form.pages.flatMap((p) => p.fields).filter((f) => f.required && (data[f.id] === undefined || data[f.id] === null || data[f.id] === ""));
    if (missing.length) { toast.error(`Champs obligatoires manquants : ${missing.map((m) => m.label).join(", ").slice(0, 100)}`); return; }
    setSending(true);
    try {
      await axios.post(`${API}/public/forms/${fid}/submission`, { data, geo, ...meta });
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
        <div className="max-w-3xl mx-auto px-6 py-4 flex items-center gap-3">
          <img src={LOGO_URL} alt="SAWALI" className="h-9 w-9 rounded-md ring-1 ring-white/20" />
          <div className="flex-1 min-w-0">
            <p className="text-[10px] uppercase tracking-[0.3em] text-sawali-blue-light">Formulaire public</p>
            <h1 className="text-base font-display font-bold truncate">{form.title}</h1>
          </div>
          <code className="text-[10px] font-mono bg-white/10 px-2 py-0.5 rounded">{form.number}</code>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-8 space-y-5">
        {form.description && <p className="text-sm text-slate-300">{form.description}</p>}

        {/* Respondent info */}
        <div className="rounded-xl bg-white/5 ring-1 ring-white/10 p-5 grid sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-[11px] font-semibold uppercase text-slate-400 mb-1">Votre nom (optionnel)</label>
            <input value={meta.respondent_name} onChange={(e) => setMeta({ ...meta, respondent_name: e.target.value })} className="w-full rounded-lg bg-white/10 border border-white/20 px-3 py-2 text-sm" placeholder="Jean Dupont" data-testid="public-form-name" />
          </div>
          <div>
            <label className="block text-[11px] font-semibold uppercase text-slate-400 mb-1">Votre email (optionnel)</label>
            <input type="email" value={meta.respondent_email} onChange={(e) => setMeta({ ...meta, respondent_email: e.target.value })} className="w-full rounded-lg bg-white/10 border border-white/20 px-3 py-2 text-sm" placeholder="jean@entreprise.fr" data-testid="public-form-email" />
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
              <Input f={f} v={data[f.id]} onChange={(v) => setData((d) => ({ ...d, [f.id]: v }))} />
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

const Input = ({ f, v, onChange }) => {
  const cls = "w-full rounded-lg bg-white/10 border border-white/20 px-3 py-2 text-sm text-white placeholder:text-slate-400 focus:outline-none focus:border-sawali-blue-light";
  switch (f.type) {
    case "textarea": return <textarea rows={4} value={v || ""} onChange={(e) => onChange(e.target.value)} className={cls} />;
    case "boolean": return <select value={v === true ? "true" : v === false ? "false" : ""} onChange={(e) => onChange(e.target.value === "true" ? true : e.target.value === "false" ? false : null)} className={cls}><option value="" className="text-slate-900">—</option><option value="true" className="text-slate-900">Oui</option><option value="false" className="text-slate-900">Non</option></select>;
    case "select": return <select value={v || ""} onChange={(e) => onChange(e.target.value)} className={cls}><option value="" className="text-slate-900">— Choisir —</option>{(f.options || []).map((o) => <option key={o} value={o} className="text-slate-900">{o}</option>)}</select>;
    case "multiselect": return <select multiple value={v || []} onChange={(e) => onChange(Array.from(e.target.selectedOptions).map((o) => o.value))} className={cls + " min-h-[80px]"}>{(f.options || []).map((o) => <option key={o} value={o} className="text-slate-900">{o}</option>)}</select>;
    case "date": return <input type="date" value={v || ""} onChange={(e) => onChange(e.target.value)} className={cls} />;
    case "datetime": return <input type="datetime-local" value={v || ""} onChange={(e) => onChange(e.target.value)} className={cls} />;
    case "number": return <input type="number" value={v ?? ""} onChange={(e) => onChange(e.target.value === "" ? null : parseFloat(e.target.value))} className={cls} />;
    case "email": return <input type="email" value={v || ""} onChange={(e) => onChange(e.target.value)} className={cls} />;
    case "tel": return <input type="tel" value={v || ""} onChange={(e) => onChange(e.target.value)} className={cls} />;
    case "url": return <input type="url" value={v || ""} onChange={(e) => onChange(e.target.value)} className={cls} />;
    default: return <input type="text" value={v || ""} onChange={(e) => onChange(e.target.value)} className={cls} />;
  }
};
