import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Save, Plus, Trash2, ArrowLeft, Globe, Lock, GripVertical, PlayCircle, Share2 } from "lucide-react";
import ShareFormModal from "@/components/ShareFormModal";
import ClientAccessSelector from "@/components/ClientAccessSelector";

const FIELD_TYPES = [
  { v: "text", l: "Texte court" }, { v: "textarea", l: "Texte long" },
  { v: "number", l: "Numérique" }, { v: "boolean", l: "Oui/Non" },
  { v: "select", l: "Liste déroulante" }, { v: "multiselect", l: "Liste à choix multiples" },
  { v: "date", l: "Date" }, { v: "datetime", l: "Date & heure" },
  { v: "email", l: "Email" }, { v: "tel", l: "Téléphone" }, { v: "url", l: "URL" },
  { v: "location", l: "Géolocalisation" },
  { v: "table", l: "Tableau (lignes dynamiques)" },
  { v: "file", l: "Fichier joint (≤ 1 Mo)" },
  { v: "signature", l: "Signature manuscrite" },
];

// Limit signature fields to 1 per form (UX simplification)
const isSignatureUnique = (form, currentFieldId) => {
  const all = (form?.pages || []).flatMap((p) => p.fields || []);
  return !all.some((f) => f.type === "signature" && f.id !== currentFieldId);
};

// Form builder — multi-page, 12-col grid, simple field reordering
export default function FormEditor() {
  const { fid } = useParams();
  const navigate = useNavigate();
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [activePage, setActivePage] = useState(0);
  const [showShare, setShowShare] = useState(false);
  const [categories, setCategories] = useState([]);

  useEffect(() => {
    apiClient.get(`/me/forms/${fid}`).then((r) => setForm(r.data)).catch(() => toast.error("Formulaire introuvable"));
    apiClient.get("/me/form-categories").then((r) => setCategories(r.data || [])).catch(() => setCategories([]));
  }, [fid]);

  const save = async () => {
    setSaving(true);
    try {
      await apiClient.put(`/me/forms/${fid}`, {
        title: form.title, description: form.description, is_public: form.is_public,
        category_id: form.category_id || null, pages: form.pages,
        access_client_ids: Array.isArray(form.access_client_ids) ? form.access_client_ids : [],
      });
      toast.success("Formulaire sauvegardé");
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setSaving(false); }
  };

  const addPage = () => setForm((f) => ({ ...f, pages: [...(f.pages || []), { id: crypto.randomUUID(), title: `Page ${(f.pages?.length || 0) + 1}`, fields: [] }] }));
  const removePage = (idx) => setForm((f) => ({ ...f, pages: f.pages.filter((_, i) => i !== idx) }));
  const updatePage = (idx, patch) => setForm((f) => ({ ...f, pages: f.pages.map((p, i) => i === idx ? { ...p, ...patch } : p) }));

  const addField = () => {
    const newF = { id: crypto.randomUUID(), type: "text", label: "Nouveau champ", required: false, col_start: 1, col_span: 12, row: (form.pages[activePage].fields || []).length };
    updatePage(activePage, { fields: [...(form.pages[activePage].fields || []), newF] });
  };
  const updateField = (fidx, patch) => updatePage(activePage, { fields: form.pages[activePage].fields.map((fd, i) => i === fidx ? { ...fd, ...patch } : fd) });
  const removeField = (fidx) => updatePage(activePage, { fields: form.pages[activePage].fields.filter((_, i) => i !== fidx) });
  const moveField = (fidx, dir) => {
    const fields = [...form.pages[activePage].fields];
    const swap = fidx + dir;
    if (swap < 0 || swap >= fields.length) return;
    [fields[fidx], fields[swap]] = [fields[swap], fields[fidx]];
    updatePage(activePage, { fields });
  };

  if (!form) return <div className="text-center text-slate-500 py-10">Chargement…</div>;

  const page = form.pages[activePage] || { fields: [] };

  return (
    <div className="max-w-5xl space-y-5" data-testid="form-editor-page">
      <div className="flex items-center gap-3">
        <button onClick={() => navigate("/portal/forms")} className="text-sm text-slate-500 hover:text-slate-900 inline-flex items-center gap-1"><ArrowLeft className="h-4 w-4" /> Retour</button>
        <code className="text-[11px] font-mono bg-slate-100 px-2 py-0.5 rounded">{form.number}</code>
        <div className="flex-1" />
        <button onClick={() => navigate(`/portal/forms/${fid}/fill`)} className="inline-flex items-center gap-1.5 text-sm rounded-lg bg-slate-100 hover:bg-slate-200 px-3 py-2" data-testid="form-preview-btn"><PlayCircle className="h-4 w-4" /> Aperçu</button>
        {form.is_public && (
          <button onClick={() => setShowShare(true)} className="inline-flex items-center gap-1.5 text-sm rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-2" data-testid="form-share-btn"><Share2 className="h-4 w-4" /> Partager</button>
        )}
        <button onClick={save} disabled={saving} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light disabled:opacity-50" data-testid="form-save-btn"><Save className="h-4 w-4" /> {saving ? "Sauvegarde…" : "Sauvegarder"}</button>
      </div>

      {showShare && <ShareFormModal form={form} onClose={() => setShowShare(false)} />}

      <div className="rounded-xl border border-slate-200 bg-white p-5 space-y-3">
        <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} className="w-full text-2xl font-display font-bold focus:outline-none" placeholder="Titre du formulaire" data-testid="form-title-input" />
        <textarea value={form.description || ""} onChange={(e) => setForm({ ...form, description: e.target.value })} className="w-full text-sm text-slate-600 focus:outline-none resize-none" placeholder="Brève description…" rows={2} data-testid="form-desc-input" />
        <label className="inline-flex items-center gap-2 text-sm" data-testid="form-public-toggle-wrap">
          <input type="checkbox" checked={form.is_public} onChange={(e) => setForm({ ...form, is_public: e.target.checked })} data-testid="form-public-toggle" />
          {form.is_public ? <><Globe className="h-4 w-4 text-emerald-600" /> Public — importable par les autres clients</> : <><Lock className="h-4 w-4 text-slate-500" /> Privé</>}
        </label>
        {categories.length > 0 && (
          <label className="block text-xs">
            <span className="text-slate-600 mr-2">Catégorie :</span>
            <select
              value={form.category_id || ""}
              onChange={(e) => setForm({ ...form, category_id: e.target.value || null })}
              className="text-sm rounded ring-1 ring-slate-300 px-2 py-1"
              data-testid="form-category-select"
            >
              <option value="">— Sans catégorie —</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>{c.name}{c.is_default ? " (défaut)" : ""}</option>
              ))}
            </select>
          </label>
        )}
        <ClientAccessSelector
          value={Array.isArray(form.access_client_ids) ? form.access_client_ids : []}
          onChange={(ids) => setForm({ ...form, access_client_ids: ids })}
          label="Clients autorisés à voir ce formulaire"
          testIdPrefix="form-access-clients"
        />
      </div>

      {/* Page tabs */}
      <div className="flex gap-2 items-center flex-wrap border-b border-slate-200">
        {form.pages.map((p, i) => (
          <button key={p.id} onClick={() => setActivePage(i)} className={`inline-flex items-center gap-2 px-3 py-2 text-sm border-b-2 ${activePage === i ? "border-sawali-blue text-sawali-blue font-semibold" : "border-transparent text-slate-500 hover:text-slate-900"}`} data-testid={`form-page-tab-${i}`}>
            Page {i + 1}
            {form.pages.length > 1 && <span onClick={(e) => { e.stopPropagation(); removePage(i); setActivePage(Math.max(0, i - 1)); }} className="h-4 w-4 inline-flex items-center justify-center rounded-full hover:bg-rose-100" data-testid={`form-page-remove-${i}`}><Trash2 className="h-3 w-3 text-rose-500" /></span>}
          </button>
        ))}
        <button onClick={addPage} className="inline-flex items-center gap-1 text-sm text-sawali-blue hover:underline" data-testid="form-page-add"><Plus className="h-3.5 w-3.5" /> Page</button>
      </div>

      {/* Page content */}
      <div className="rounded-xl border border-slate-200 bg-white p-5 space-y-3" data-testid="form-page-content">
        <input value={page.title || ""} onChange={(e) => updatePage(activePage, { title: e.target.value })} className="text-lg font-display font-bold w-full focus:outline-none" placeholder="Titre de la page" />
        {page.fields.length === 0 ? (
          <p className="text-sm text-slate-400 italic">Aucun champ. Cliquez sur « Ajouter un champ » ci-dessous.</p>
        ) : (
          <div className="space-y-2">
            {page.fields.map((fd, fidx) => (
              <div key={fd.id} className="rounded-lg border border-slate-200 p-3 flex gap-2 items-start" data-testid={`form-field-${fidx}`}>
                <div className="flex flex-col gap-0.5 pt-1">
                  <button onClick={() => moveField(fidx, -1)} className="text-slate-400 hover:text-slate-900" title="Monter">↑</button>
                  <GripVertical className="h-4 w-4 text-slate-300" />
                  <button onClick={() => moveField(fidx, 1)} className="text-slate-400 hover:text-slate-900" title="Descendre">↓</button>
                </div>
                <div className="flex-1 grid sm:grid-cols-2 gap-2">
                  <div>
                    <label className="text-[10px] uppercase tracking-wider text-slate-500">Libellé</label>
                    <input value={fd.label} onChange={(e) => updateField(fidx, { label: e.target.value })} className="w-full rounded border border-slate-300 px-2 py-1 text-sm" data-testid={`field-label-${fidx}`} />
                  </div>
                  <div>
                    <label className="text-[10px] uppercase tracking-wider text-slate-500">Type</label>
                    <select value={fd.type} onChange={(e) => updateField(fidx, { type: e.target.value })} className="w-full rounded border border-slate-300 px-2 py-1 text-sm" data-testid={`field-type-${fidx}`}>
                      {FIELD_TYPES.map((t) => <option key={t.v} value={t.v}>{t.l}</option>)}
                    </select>
                  </div>
                  {(fd.type === "select" || fd.type === "multiselect") && (
                    <div className="sm:col-span-2">
                      <label className="text-[10px] uppercase tracking-wider text-slate-500">Options (une par ligne)</label>
                      <textarea value={(fd.options || []).join("\n")} onChange={(e) => updateField(fidx, { options: e.target.value.split("\n").map((s) => s.trim()).filter(Boolean) })} rows={3} className="w-full rounded border border-slate-300 px-2 py-1 text-sm font-mono" data-testid={`field-options-${fidx}`} />
                    </div>
                  )}
                  {fd.type === "table" && (
                    <div className="sm:col-span-2 rounded bg-slate-50 ring-1 ring-slate-200 p-2">
                      <label className="text-[10px] uppercase tracking-wider text-slate-500 block mb-1">Colonnes du tableau</label>
                      {(fd.columns || []).map((col, ci) => (
                        <div key={ci} className="flex gap-2 mb-1" data-testid={`field-table-col-${fidx}-${ci}`}>
                          <input
                            value={col.label || ""}
                            onChange={(e) => {
                              const next = [...(fd.columns || [])];
                              next[ci] = { ...col, label: e.target.value, key: col.key || `col${ci}` };
                              updateField(fidx, { columns: next });
                            }}
                            placeholder="Libellé"
                            className="flex-1 rounded border border-slate-300 px-2 py-1 text-xs"
                          />
                          <select
                            value={col.type || "text"}
                            onChange={(e) => {
                              const next = [...(fd.columns || [])];
                              next[ci] = { ...col, type: e.target.value };
                              updateField(fidx, { columns: next });
                            }}
                            className="rounded border border-slate-300 px-2 py-1 text-xs"
                          >
                            <option value="text">Texte</option>
                            <option value="number">Numérique</option>
                            <option value="date">Date</option>
                          </select>
                          <button
                            type="button"
                            onClick={() => updateField(fidx, { columns: (fd.columns || []).filter((_, i) => i !== ci) })}
                            className="text-rose-500 hover:bg-rose-50 px-1 rounded text-xs"
                          >×</button>
                        </div>
                      ))}
                      <button
                        type="button"
                        onClick={() => updateField(fidx, { columns: [...(fd.columns || []), { key: `col${(fd.columns || []).length}`, label: "", type: "text" }] })}
                        className="text-xs text-sawali-blue hover:underline mt-1"
                        data-testid={`field-table-addcol-${fidx}`}
                      >
                        + Ajouter une colonne
                      </button>
                    </div>
                  )}
                  {fd.type === "file" && (
                    <div className="sm:col-span-2">
                      <label className="text-[10px] uppercase tracking-wider text-slate-500">Types acceptés (facultatif)</label>
                      <input
                        value={fd.accept || ""}
                        onChange={(e) => updateField(fidx, { accept: e.target.value })}
                        placeholder=".pdf,image/*"
                        className="w-full rounded border border-slate-300 px-2 py-1 text-sm font-mono"
                        data-testid={`field-accept-${fidx}`}
                      />
                      <p className="text-[10px] text-slate-400 mt-0.5">Limite : 1 Mo par fichier.</p>
                    </div>
                  )}
                  {fd.type === "signature" && !isSignatureUnique(form, fd.id) && (
                    <div className="sm:col-span-2 text-[11px] text-amber-700 bg-amber-50 ring-1 ring-amber-200 rounded p-2">
                      ⚠ Un seul champ signature autorisé par formulaire — supprimez le précédent ou changez de type.
                    </div>
                  )}
                  <div className="grid grid-cols-3 gap-2 sm:col-span-2">
                    <div>
                      <label className="text-[10px] uppercase tracking-wider text-slate-500">Col. départ (1-12)</label>
                      <input type="number" min={1} max={12} value={fd.col_start} onChange={(e) => updateField(fidx, { col_start: parseInt(e.target.value) || 1 })} className="w-full rounded border border-slate-300 px-2 py-1 text-sm" />
                    </div>
                    <div>
                      <label className="text-[10px] uppercase tracking-wider text-slate-500">Largeur (1-12)</label>
                      <input type="number" min={1} max={12} value={fd.col_span} onChange={(e) => updateField(fidx, { col_span: parseInt(e.target.value) || 12 })} className="w-full rounded border border-slate-300 px-2 py-1 text-sm" />
                    </div>
                    <div>
                      <label className="text-[10px] uppercase tracking-wider text-slate-500 block">Obligatoire</label>
                      <input type="checkbox" checked={!!fd.required} onChange={(e) => updateField(fidx, { required: e.target.checked })} className="mt-2" data-testid={`field-required-${fidx}`} />
                    </div>
                  </div>
                </div>
                <button onClick={() => removeField(fidx)} className="text-rose-500 hover:bg-rose-50 p-1 rounded" data-testid={`field-remove-${fidx}`}><Trash2 className="h-4 w-4" /></button>
              </div>
            ))}
          </div>
        )}
        <button onClick={addField} className="inline-flex items-center gap-1 text-sm text-sawali-blue hover:underline" data-testid="form-field-add"><Plus className="h-3.5 w-3.5" /> Ajouter un champ</button>
      </div>
    </div>
  );
}
