import React, { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import QRCode from "qrcode";
import SignaturePad from "signature_pad";
import { ArrowLeft, ArrowRight, Save, RotateCcw, Download, MapPin, Clock, Printer, QrCode, Plus, Trash2, Upload as UploadIcon, X } from "lucide-react";

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
  const [showQr, setShowQr] = useState(false);
  const [qrDataUrl, setQrDataUrl] = useState("");
  const [shareUrl, setShareUrl] = useState("");

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

  // Build the QR payload — a compact JSON of {form_id, numero, data}.
  // Used by external apps to re-import a saved submission.
  const buildDataQrPayload = () => JSON.stringify({
    form_id: form?.id,
    numero: form?.numero || form?.number,
    title: form?.title,
    data,
    generated_at: new Date().toISOString(),
  });

  const openDataQr = async () => {
    try {
      const payload = buildDataQrPayload();
      const dataUrl = await QRCode.toDataURL(payload, { errorCorrectionLevel: "M", width: 320, margin: 1 });
      setQrDataUrl(dataUrl);
      setShowQr(true);
    } catch {
      toast.error("Trop de données pour un QR code (réduisez le contenu)");
    }
  };

  const computeShareUrl = () => {
    if (!form) return "";
    const base = window.location.origin;
    return form.is_public ? `${base}/f/${form.id}` : `${base}/portal/forms/${form.id}/fill`;
  };

  const printPdf = async () => {
    if (!form) return;
    const url = computeShareUrl();
    setShareUrl(url);
    let qrUrl = "";
    try {
      qrUrl = await QRCode.toDataURL(url, { errorCorrectionLevel: "M", width: 240, margin: 1 });
    } catch { /* noop */ }
    const w = window.open("", "_blank", "width=900,height=1100");
    if (!w) { toast.error("Ouverture bloquée par le navigateur"); return; }
    const today = new Date().toLocaleString("fr-FR");
    const fields = (form.pages || []).flatMap((p) => p.fields || []);
    const escape = (s) => String(s).replace(/[<>&]/g, (m) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[m]));
    const rowsHtml = fields.map((f) => {
      const v = data[f.id];
      let display = "";
      if (f.type === "signature" && typeof v === "string" && v.startsWith("data:image")) {
        display = `<img src="${v}" alt="signature" style="max-height:80px;border:1px solid #cbd5e1;border-radius:4px"/>`;
      } else if (f.type === "table" && Array.isArray(v)) {
        const cols = f.columns || [];
        const header = cols.map((c) => `<th style="border:1px solid #cbd5e1;padding:4px;background:#f8fafc">${escape(c.label || c.key)}</th>`).join("");
        const trs = v.map((row) => `<tr>${cols.map((c) => `<td style="border:1px solid #cbd5e1;padding:4px">${escape(row[c.key] ?? "")}</td>`).join("")}</tr>`).join("");
        display = `<table style="border-collapse:collapse;width:100%;font-size:11px"><thead><tr>${header}</tr></thead><tbody>${trs}</tbody></table>`;
      } else if (f.type === "file" && v && v.public_url) {
        display = `${escape(v.filename || "Fichier")} — <a href="${v.public_url}">${v.public_url}</a>`;
      } else if (Array.isArray(v)) {
        display = v.map((x) => escape(String(x))).join(", ");
      } else if (v === null || v === undefined || v === "") {
        display = "<em style='color:#94a3b8'>—</em>";
      } else if (typeof v === "boolean") {
        display = v ? "Oui" : "Non";
      } else {
        display = escape(v);
      }
      return `<tr><th style="text-align:left;padding:6px 8px;background:#f1f5f9;width:40%;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:0.05em;color:#64748b">${escape(f.label)}</th><td style="padding:6px 8px;font-size:13px">${display}</td></tr>`;
    }).join("");
    const numero = form.numero || form.number || "—";
    const titlePart = form.is_public ? '<span style="color:#16a34a">PUBLIC</span>' : '<span style="color:#7c3aed">PRIVÉ</span>';
    const html = `<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>${escape(form.title)} — ${numero}</title>
      <style>@media print{ button{display:none} } body{font-family:system-ui,sans-serif;color:#0f172a;margin:24px;max-width:780px}</style>
      </head><body>
      <div style="display:flex;justify-content:space-between;align-items:flex-start;border-bottom:2px solid #1e90ff;padding-bottom:12px;margin-bottom:16px">
        <div>
          <h1 style="margin:0 0 4px 0;font-size:22px">${escape(form.title)}</h1>
          <p style="margin:0;color:#64748b;font-size:12px">N° ${escape(numero)} · ${titlePart} · imprimé le ${today}</p>
          ${form.description ? `<p style="margin:6px 0 0 0;color:#475569;font-size:13px">${escape(form.description)}</p>` : ""}
        </div>
        ${qrUrl ? `<div style="text-align:center"><img src="${qrUrl}" alt="QR" style="width:120px;height:120px"/><p style="margin:4px 0 0 0;font-size:9px;color:#64748b;max-width:140px;word-break:break-all">${escape(url)}</p></div>` : ""}
      </div>
      <table style="width:100%;border-collapse:collapse;border:1px solid #e2e8f0">${rowsHtml || '<tr><td style="padding:12px;color:#94a3b8;font-style:italic">Aucune donnée saisie</td></tr>'}</table>
      <div style="text-align:center;margin-top:32px"><button onclick="window.print()" style="padding:8px 16px;background:#1e90ff;color:white;border:0;border-radius:6px;cursor:pointer">Imprimer / Enregistrer en PDF</button></div>
      </body></html>`;
    w.document.open(); w.document.write(html); w.document.close();
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
        <button onClick={printPdf} className="inline-flex items-center gap-2 rounded-lg bg-violet-600 hover:bg-violet-700 text-white px-4 py-2 text-sm" data-testid="form-print-btn"><Printer className="h-4 w-4" /> Imprimer PDF</button>
        <button onClick={openDataQr} className="inline-flex items-center gap-2 rounded-lg bg-fuchsia-600 hover:bg-fuchsia-700 text-white px-4 py-2 text-sm" data-testid="form-qrdata-btn"><QrCode className="h-4 w-4" /> QR des données</button>
      </div>

      {showQr && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={(e) => e.target === e.currentTarget && setShowQr(false)}
          data-testid="qr-data-modal"
        >
          <div className="bg-white rounded-xl p-6 max-w-md w-full text-center">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-semibold text-sm inline-flex items-center gap-1"><QrCode className="h-4 w-4" /> QR code des données</h3>
              <button onClick={() => setShowQr(false)} className="text-slate-500 hover:text-slate-900"><X className="h-4 w-4" /></button>
            </div>
            <img src={qrDataUrl} alt="QR" className="mx-auto rounded ring-1 ring-slate-200" data-testid="qr-data-image" />
            <p className="text-xs text-slate-500 mt-3">Scannez avec n'importe quel lecteur QR pour récupérer les données saisies au format JSON.</p>
            <a href={qrDataUrl} download={`${form.numero || form.number || "form"}-qr.png`} className="inline-block mt-3 text-xs text-sawali-blue hover:underline" data-testid="qr-data-download">Télécharger l'image</a>
          </div>
        </div>
      )}
    </div>
  );
}

// =====================================================================
// Per-field input. New types: table, file, signature.
// =====================================================================
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
    case "table":
      return <TableField field={field} value={Array.isArray(value) ? value : []} onChange={onChange} />;
    case "file":
      return <FileField field={field} value={value} onChange={onChange} />;
    case "signature":
      return <SignatureField value={value} onChange={onChange} />;
    default:
      return <input type="text" value={value || ""} onChange={(e) => onChange(e.target.value)} placeholder={field.placeholder} className={commonCls} />;
  }
};

// Tableau dynamique : l'admin définit les colonnes, l'utilisateur ajoute des lignes
const TableField = ({ field, value, onChange }) => {
  const cols = field.columns || [];
  const rows = value;
  const update = (next) => onChange(next);
  const setCell = (i, key, v) => {
    const next = rows.map((r, ri) => (ri === i ? { ...r, [key]: v } : r));
    update(next);
  };
  const addRow = () => update([...rows, Object.fromEntries(cols.map((c) => [c.key || c.label, ""]))]);
  const delRow = (i) => update(rows.filter((_, ri) => ri !== i));
  if (cols.length === 0) return <p className="text-xs italic text-slate-400">Tableau non configuré (aucune colonne).</p>;
  return (
    <div className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-2 overflow-x-auto" data-testid={`table-field-${field.id}`}>
      <table className="w-full text-xs">
        <thead className="text-[10px] uppercase text-slate-500">
          <tr>
            {cols.map((c) => <th key={c.key || c.label} className="text-left px-2 py-1 whitespace-nowrap">{c.label || c.key}</th>)}
            <th className="w-8"></th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={cols.length + 1} className="text-center px-2 py-3 text-slate-400 italic">Aucune ligne.</td></tr>
          )}
          {rows.map((r, ri) => (
            <tr key={ri} className="border-t border-slate-200" data-testid={`table-row-${field.id}-${ri}`}>
              {cols.map((c) => (
                <td key={c.key || c.label} className="px-1 py-1">
                  <input
                    type={c.type === "number" ? "number" : c.type === "date" ? "date" : "text"}
                    value={r[c.key] ?? ""}
                    onChange={(e) => setCell(ri, c.key, c.type === "number" ? (e.target.value === "" ? "" : parseFloat(e.target.value)) : e.target.value)}
                    className="w-full rounded border border-slate-300 px-2 py-1 text-xs bg-white"
                    data-testid={`table-cell-${field.id}-${ri}-${c.key}`}
                  />
                </td>
              ))}
              <td className="px-1 py-1 text-right">
                <button type="button" onClick={() => delRow(ri)} className="text-rose-500 hover:bg-rose-50 rounded px-1 text-xs"><Trash2 className="h-3 w-3" /></button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button type="button" onClick={addRow} className="mt-2 inline-flex items-center gap-1 text-xs text-sawali-blue hover:underline" data-testid={`table-addrow-${field.id}`}>
        <Plus className="h-3 w-3" /> Ajouter une ligne
      </button>
    </div>
  );
};

// Fichier ≤ 1 Mo, posté sur /api/me/forms/{form_id}/upload via le runner
const FileField = ({ field, value, onChange }) => {
  const { fid: formId } = useParams();
  const [busy, setBusy] = useState(false);
  const upload = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 1024 * 1024) { toast.error("Fichier trop volumineux (max 1 Mo)"); return; }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const r = await apiClient.post(`/me/forms/${formId}/upload`, fd, { headers: { "Content-Type": "multipart/form-data" } });
      onChange({ public_url: r.data.public_url, filename: r.data.filename, size: r.data.size, content_type: r.data.content_type });
      toast.success("Fichier envoyé");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur d'envoi");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-2" data-testid={`file-field-${field.id}`}>
      {value && value.public_url ? (
        <div className="flex items-center justify-between gap-2 rounded-lg ring-1 ring-emerald-200 bg-emerald-50 px-3 py-2 text-xs">
          <a href={value.public_url} target="_blank" rel="noreferrer" className="text-emerald-700 hover:underline truncate flex-1">
            📎 {value.filename || "Fichier"} ({(value.size / 1024).toFixed(0)} ko)
          </a>
          <button type="button" onClick={() => onChange(null)} className="text-rose-500 hover:bg-rose-50 rounded px-1" data-testid={`file-clear-${field.id}`}>
            <X className="h-3 w-3" />
          </button>
        </div>
      ) : (
        <label className="inline-flex items-center gap-2 rounded-lg ring-1 ring-slate-300 bg-white hover:bg-slate-50 px-3 py-2 text-sm cursor-pointer" data-testid={`file-upload-${field.id}`}>
          <UploadIcon className="h-4 w-4" />
          {busy ? "Envoi…" : "Joindre un fichier (max 1 Mo)"}
          <input type="file" className="hidden" accept={field.accept || ""} onChange={upload} disabled={busy} />
        </label>
      )}
    </div>
  );
};

// Signature manuscrite via signature_pad
const SignatureField = ({ value, onChange }) => {
  const canvasRef = useRef(null);
  const padRef = useRef(null);
  useEffect(() => {
    if (!canvasRef.current) return;
    // Ensure canvas backing store matches CSS size for crisp lines on HiDPI
    const canvas = canvasRef.current;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = canvas.offsetWidth * ratio;
    canvas.height = canvas.offsetHeight * ratio;
    canvas.getContext("2d").scale(ratio, ratio);
    padRef.current = new SignaturePad(canvas, { backgroundColor: "rgba(255,255,255,1)", penColor: "#0f172a" });
    padRef.current.addEventListener("endStroke", () => {
      onChange(padRef.current.toDataURL("image/png"));
    });
    if (value && typeof value === "string" && value.startsWith("data:image")) {
      padRef.current.fromDataURL(value);
    }
    return () => padRef.current?.off();
    // eslint-disable-next-line
  }, []);
  const clear = () => { padRef.current?.clear(); onChange(null); };
  return (
    <div className="space-y-2" data-testid="signature-field">
      <canvas ref={canvasRef} className="w-full h-40 bg-white rounded-lg ring-1 ring-slate-300 cursor-crosshair touch-none" />
      <div className="flex justify-between text-[11px]">
        <span className="text-slate-400 italic">Tracez votre signature ci-dessus</span>
        <button type="button" onClick={clear} className="text-rose-600 hover:underline" data-testid="signature-clear">
          Effacer la signature
        </button>
      </div>
    </div>
  );
};
