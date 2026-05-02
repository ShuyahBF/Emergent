import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { ArrowLeft, ArrowRight, Save, RotateCcw, Download, MapPin, Clock } from "lucide-react";

// Form runner — honours 12-col grid, auto-prefills on reopen, 3 buttons (reset/save/export CSV)
export default function FormRunner() {
  const { fid } = useParams();
  const navigate = useNavigate();
  const [form, setForm] = useState(null);
  const [data, setData] = useState({});
  const [submission, setSubmission] = useState(null);
  const [activePage, setActivePage] = useState(0);
  const [saving, setSaving] = useState(false);
  const [geo, setGeo] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const [fr, sr] = await Promise.all([
          apiClient.get(`/me/forms/${fid}`),
          apiClient.get(`/me/forms/${fid}/submission`),
        ]);
        setForm(fr.data);
        setSubmission(sr.data);
        setData(sr.data?.data || {});
      } catch { toast.error("Formulaire introuvable"); }
    })();
    // Attempt geolocation (best-effort)
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (p) => setGeo({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy }),
        () => {}, { timeout: 4000, maximumAge: 60000 }
      );
    }
  }, [fid]);

  const reset = () => { if (window.confirm("Effacer toutes les saisies ?")) setData({}); };

  const save = async () => {
    setSaving(true);
    try {
      const r = await apiClient.post(`/me/forms/${fid}/submission`, { data, geo });
      setSubmission(r.data);
      toast.success("Saisie enregistrée");
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setSaving(false); }
  };

  const exportCsv = () => {
    if (!form) return;
    const allFields = form.pages.flatMap((p) => p.fields);
    const header = allFields.map((f) => `"${(f.label || "").replace(/"/g, '""')}"`).join(",");
    const row = allFields.map((f) => {
      const v = data[f.id];
      const s = Array.isArray(v) ? v.join(" | ") : (v === null || v === undefined ? "" : String(v));
      return `"${s.replace(/"/g, '""')}"`;
    }).join(",");
    const csv = `${header}\n${row}`;
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `${form.number}-saisie.csv`;
    a.click(); URL.revokeObjectURL(url);
  };

  if (!form) return <div className="text-center text-slate-500 py-10">Chargement…</div>;
  const page = form.pages[activePage] || { fields: [] };

  return (
    <div className="max-w-5xl space-y-5" data-testid="form-runner-page">
      <div className="flex items-center gap-3 flex-wrap">
        <button onClick={() => navigate("/portal/forms")} className="text-sm text-slate-500 hover:text-slate-900 inline-flex items-center gap-1"><ArrowLeft className="h-4 w-4" /> Retour</button>
        <code className="text-[11px] font-mono bg-slate-100 px-2 py-0.5 rounded">{form.number}</code>
        <div className="flex-1" />
        {submission?.revisions_count > 0 && (
          <span className="text-[11px] text-slate-500 inline-flex items-center gap-1"><Clock className="h-3 w-3" /> {submission.revisions_count} révision(s) · maj {new Date(submission.updated_at).toLocaleString("fr-FR")}</span>
        )}
      </div>

      <div className="rounded-xl bg-white border border-slate-200 p-5">
        <h1 className="text-2xl font-display font-bold mb-1">{form.title}</h1>
        {form.description && <p className="text-sm text-slate-600 mb-3">{form.description}</p>}
        {geo && <p className="text-[11px] text-emerald-700 inline-flex items-center gap-1"><MapPin className="h-3 w-3" /> Position enregistrée ({geo.lat.toFixed(4)}, {geo.lng.toFixed(4)})</p>}
      </div>

      {/* Page tabs (reading navigation) */}
      {form.pages.length > 1 && (
        <div className="flex items-center justify-between rounded-xl bg-white border border-slate-200 px-4 py-2">
          <button onClick={() => setActivePage(Math.max(0, activePage - 1))} disabled={activePage === 0} className="inline-flex items-center gap-1 text-sm hover:text-sawali-blue disabled:opacity-40" data-testid="form-page-prev"><ArrowLeft className="h-4 w-4" /> Précédent</button>
          <span className="text-sm text-slate-600">Page {activePage + 1} / {form.pages.length} — <strong>{page.title}</strong></span>
          <button onClick={() => setActivePage(Math.min(form.pages.length - 1, activePage + 1))} disabled={activePage === form.pages.length - 1} className="inline-flex items-center gap-1 text-sm hover:text-sawali-blue disabled:opacity-40" data-testid="form-page-next">Suivant <ArrowRight className="h-4 w-4" /></button>
        </div>
      )}

      {/* Fields in 12-col grid */}
      <div className="grid grid-cols-12 gap-3 rounded-xl bg-white border border-slate-200 p-5" data-testid="form-grid">
        {page.fields.length === 0 && <div className="col-span-12 text-sm text-slate-400 italic">Aucun champ sur cette page.</div>}
        {page.fields.map((f) => (
          <div key={f.id} className="min-w-0" style={{ gridColumnStart: f.col_start || 1, gridColumn: `span ${Math.min(12, f.col_span || 12)} / span ${Math.min(12, f.col_span || 12)}` }} data-testid={`runner-field-${f.id}`}>
            <label className="block text-[11px] font-semibold uppercase tracking-wider text-slate-600 mb-1">
              {f.label}{f.required && <span className="text-rose-500 ml-1">*</span>}
            </label>
            <FieldInput field={f} value={data[f.id]} onChange={(v) => setData((d) => ({ ...d, [f.id]: v }))} />
          </div>
        ))}
      </div>

      {/* Action buttons */}
      <div className="flex gap-2 flex-wrap" data-testid="form-actions">
        <button onClick={reset} className="inline-flex items-center gap-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-900 px-4 py-2 text-sm" data-testid="form-reset-btn"><RotateCcw className="h-4 w-4" /> Réinitialiser</button>
        <button onClick={save} disabled={saving} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue hover:bg-sawali-blue-light text-white px-4 py-2 text-sm disabled:opacity-50" data-testid="form-save-btn"><Save className="h-4 w-4" /> {saving ? "Sauvegarde…" : "Sauvegarder"}</button>
        <button onClick={exportCsv} className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 text-sm" data-testid="form-export-btn"><Download className="h-4 w-4" /> Exporter CSV</button>
      </div>
    </div>
  );
}

const FieldInput = ({ field, value, onChange }) => {
  const commonCls = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:border-sawali-blue focus:ring-2 focus:ring-sawali-blue/20";
  switch (field.type) {
    case "textarea":
      return <textarea rows={4} value={value || ""} onChange={(e) => onChange(e.target.value)} placeholder={field.placeholder} className={commonCls} />;
    case "boolean":
      return <select value={value || ""} onChange={(e) => onChange(e.target.value === "true")} className={commonCls}><option value="">—</option><option value="true">Oui</option><option value="false">Non</option></select>;
    case "select":
      return <select value={value || ""} onChange={(e) => onChange(e.target.value)} className={commonCls}><option value="">— Choisir —</option>{(field.options || []).map((o) => <option key={o} value={o}>{o}</option>)}</select>;
    case "multiselect":
      return <select multiple value={value || []} onChange={(e) => onChange(Array.from(e.target.selectedOptions).map((o) => o.value))} className={commonCls + " min-h-[80px]"}>{(field.options || []).map((o) => <option key={o} value={o}>{o}</option>)}</select>;
    case "date":
      return <input type="date" value={value || ""} onChange={(e) => onChange(e.target.value)} className={commonCls} />;
    case "datetime":
      return <input type="datetime-local" value={value || ""} onChange={(e) => onChange(e.target.value)} className={commonCls} />;
    case "number":
      return <input type="number" value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? null : parseFloat(e.target.value))} placeholder={field.placeholder} className={commonCls} />;
    case "email":
      return <input type="email" value={value || ""} onChange={(e) => onChange(e.target.value)} placeholder={field.placeholder} className={commonCls} />;
    case "tel":
      return <input type="tel" value={value || ""} onChange={(e) => onChange(e.target.value)} placeholder={field.placeholder} className={commonCls} />;
    case "url":
      return <input type="url" value={value || ""} onChange={(e) => onChange(e.target.value)} placeholder={field.placeholder} className={commonCls} />;
    case "location":
      return (
        <div className="flex gap-2">
          <input value={value || ""} onChange={(e) => onChange(e.target.value)} placeholder="Latitude, Longitude" className={commonCls} />
          <button type="button" onClick={() => navigator.geolocation?.getCurrentPosition((p) => onChange(`${p.coords.latitude.toFixed(5)}, ${p.coords.longitude.toFixed(5)}`))} className="rounded-lg bg-slate-900 text-white px-3 text-xs" title="Ma position"><MapPin className="h-4 w-4" /></button>
        </div>
      );
    default:
      return <input type="text" value={value || ""} onChange={(e) => onChange(e.target.value)} placeholder={field.placeholder} className={commonCls} />;
  }
};
