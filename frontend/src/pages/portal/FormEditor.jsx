/*
  FormEditor — lot 27 : éditeur de formulaires à la manière d'ALBARKA.

  Même format de formulaire qu'avant (pages → champs, grille de 12 colonnes) :
  le remplissage, le lien public, les réponses et les statistiques ne changent pas.
  Nouveautés d'édition :
    - palette des types de champs : clic pour ajouter (après le champ
      sélectionné) ou glisser-déposer à l'endroit voulu ;
    - champs réordonnés par glisser-déposer (ou flèches), dupliqués,
      supprimés, déplacés vers une autre page ;
    - pages nommées, ajoutées, supprimées (avec confirmation) ;
    - panneau de propriétés : question, type, obligatoire, largeur (pleine,
      3/4, 2/3, moitié, 1/3, 1/4), texte indicatif, valeur par défaut,
      options, colonnes de tableau, types de fichiers acceptés ;
    - aperçu en direct avec le même rendu que le formulaire réel ;
    - alerte avant de quitter la page avec des modifications non enregistrées.
*/
import React, { useEffect, useState } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  Save, Plus, Trash2, ArrowLeft, Globe, Lock, GripVertical, PlayCircle, Share2, Eye, X, Copy, ArrowUp, ArrowDown,
  Type, AlignLeft, Hash, ToggleLeft, List, ListChecks, Calendar, Clock, Mail, Phone, Link2, MapPin, Table2, Paperclip, PenLine, Loader2,
} from "lucide-react";
import ShareFormModal from "@/components/ShareFormModal";
import ClientAccessSelector from "@/components/ClientAccessSelector";
import { FieldInput } from "@/pages/portal/FormRunner";

// Types de champs de Sawali (inchangés) avec leur icône pour la palette
const FIELD_TYPES = [
  { v: "text", l: "Texte court", icon: Type }, { v: "textarea", l: "Texte long", icon: AlignLeft },
  { v: "number", l: "Numérique", icon: Hash }, { v: "boolean", l: "Oui / Non", icon: ToggleLeft },
  { v: "select", l: "Liste déroulante", icon: List }, { v: "multiselect", l: "Choix multiples", icon: ListChecks },
  { v: "date", l: "Date", icon: Calendar }, { v: "datetime", l: "Date & heure", icon: Clock },
  { v: "email", l: "E-mail", icon: Mail }, { v: "tel", l: "Téléphone", icon: Phone }, { v: "url", l: "Lien (URL)", icon: Link2 },
  { v: "location", l: "Géolocalisation", icon: MapPin }, { v: "table", l: "Tableau", icon: Table2 },
  { v: "file", l: "Fichier joint (≤ 1 Mo)", icon: Paperclip }, { v: "signature", l: "Signature", icon: PenLine },
];
const TYPE_BY = Object.fromEntries(FIELD_TYPES.map((t) => [t.v, t]));
// Largeur dans la grille de 12 colonnes
const WIDTHS = [[12, "Pleine largeur"], [9, "3/4"], [8, "2/3"], [6, "Moitié"], [4, "1/3"], [3, "1/4"]];
const WITH_PLACEHOLDER = ["text", "textarea", "number", "email", "tel", "url"];
const clone = (x) => JSON.parse(JSON.stringify(x));
const uid = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`);
const newField = (type) => ({
  id: uid(), type, label: TYPE_BY[type]?.l || "Nouveau champ", required: false, col_start: 1, col_span: 12, row: 0,
  ...(type === "select" || type === "multiselect" ? { options: ["Option 1", "Option 2"] } : {}),
  ...(type === "table" ? { columns: [{ key: "col0", label: "Désignation", type: "text" }, { key: "col1", label: "Quantité", type: "number" }] } : {}),
});

// Panneau de propriétés du champ sélectionné
function Properties({ field, pages, pageIdx, update, moveToPage, signatureTaken }) {
  const set = (patch) => update({ ...field, ...patch });
  const input = "mt-1 w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm focus:outline-none focus:border-sawali-blue";
  const label = "text-[10px] uppercase tracking-wider text-slate-500 font-semibold";
  const T = TYPE_BY[field.type];
  return (
    <div className="space-y-3 text-sm" data-testid="field-properties">
      <div className="flex items-center gap-2 text-xs font-semibold text-sawali-blue border-b border-slate-100 pb-2">
        {T && <T.icon className="h-4 w-4" />} {T?.l || field.type}
      </div>
      <label className="block"><span className={label}>Question</span>
        <input value={field.label} onChange={(e) => set({ label: e.target.value })} className={input} data-testid="prop-label" /></label>
      <label className="block"><span className={label}>Type</span>
        <select value={field.type} data-testid="prop-type" className={input}
          onChange={(e) => set({ type: e.target.value, ...(["select", "multiselect"].includes(e.target.value) && !field.options?.length ? { options: ["Option 1", "Option 2"] } : {}) })}>
          {FIELD_TYPES.map((t) => <option key={t.v} value={t.v}>{t.l}</option>)}
        </select></label>
      <label className="inline-flex items-center gap-2"><input type="checkbox" checked={!!field.required} onChange={(e) => set({ required: e.target.checked })} data-testid="prop-required" /> Obligatoire</label>
      <label className="block"><span className={label}>Largeur</span>
        <select value={Math.min(12, field.col_span || 12)} onChange={(e) => set({ col_span: Number(e.target.value), col_start: 1 })} className={input} data-testid="prop-width">
          {WIDTHS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          {!WIDTHS.some(([v]) => v === (field.col_span || 12)) && <option value={field.col_span}>{field.col_span}/12</option>}
        </select></label>
      {WITH_PLACEHOLDER.includes(field.type) && (
        <>
          <label className="block"><span className={label}>Texte indicatif</span>
            <input value={field.placeholder || ""} onChange={(e) => set({ placeholder: e.target.value })} className={input} /></label>
          <label className="block"><span className={label}>Valeur par défaut</span>
            <input value={field.default_value ?? ""} onChange={(e) => set({ default_value: e.target.value === "" ? null : e.target.value })} className={input} /></label>
        </>
      )}
      {(field.type === "select" || field.type === "multiselect") && (
        <label className="block"><span className={label}>Options (une par ligne)</span>
          <textarea rows={5} value={(field.options || []).join("\n")} data-testid="prop-options" className={`${input} font-mono`}
            onChange={(e) => set({ options: e.target.value.split("\n") })}
            onBlur={(e) => set({ options: e.target.value.split("\n").map((o) => o.trim()).filter(Boolean) })} /></label>
      )}
      {field.type === "table" && (
        <div className="space-y-1">
          <span className={label}>Colonnes du tableau</span>
          {(field.columns || []).map((c, i) => (
            <div key={c.key || i} className="flex gap-1">
              <input value={c.label || ""} placeholder="Libellé" onChange={(e) => set({ columns: field.columns.map((x, j) => (j === i ? { ...x, label: e.target.value, key: x.key || `col${j}` } : x)) })}
                className="flex-1 rounded border border-slate-300 px-2 py-1 text-xs" />
              <select value={c.type || "text"} onChange={(e) => set({ columns: field.columns.map((x, j) => (j === i ? { ...x, type: e.target.value } : x)) })}
                className="rounded border border-slate-300 px-1 text-xs"><option value="text">Texte</option><option value="number">Numérique</option><option value="date">Date</option></select>
              <button type="button" onClick={() => set({ columns: field.columns.filter((_, j) => j !== i) })} className="px-1 text-slate-400 hover:text-rose-600"><X className="h-4 w-4" /></button>
            </div>
          ))}
          <button type="button" onClick={() => set({ columns: [...(field.columns || []), { key: `col${Date.now().toString(36)}`, label: "", type: "text" }] })}
            className="text-xs text-sawali-blue inline-flex items-center gap-1"><Plus className="h-3 w-3" /> Colonne</button>
        </div>
      )}
      {field.type === "file" && (
        <label className="block"><span className={label}>Types acceptés (vide = tous)</span>
          <input value={field.accept || ""} placeholder=".pdf,image/*" onChange={(e) => set({ accept: e.target.value })} className={`${input} font-mono`} />
          <span className="text-[10px] text-slate-400">Limite : 1 Mo par fichier.</span></label>
      )}
      {field.type === "signature" && signatureTaken && (
        <p className="text-[11px] text-amber-700 bg-amber-50 ring-1 ring-amber-200 rounded p-2">Un seul champ signature par formulaire : supprimez l'autre ou changez de type.</p>
      )}
      {pages.length > 1 && (
        <label className="block"><span className={label}>Déplacer vers la page</span>
          <select value={pageIdx} onChange={(e) => moveToPage(Number(e.target.value))} className={input}>
            {pages.map((p, i) => <option key={p.id} value={i}>{p.title || `Page ${i + 1}`}</option>)}</select></label>
      )}
    </div>
  );
}

export default function FormEditor() {
  const { fid } = useParams();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const base = pathname.startsWith("/admin") ? "/admin" : "/portal";
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [pageIdx, setPageIdx] = useState(0);
  const [selected, setSelected] = useState(null);
  const [showShare, setShowShare] = useState(false);
  const [categories, setCategories] = useState([]);
  const [preview, setPreview] = useState(false);
  const [previewData, setPreviewData] = useState({});
  const [previewPage, setPreviewPage] = useState(0);
  const [dragInfo, setDragInfo] = useState(null);     // {kind:"new", type} | {kind:"move", index}
  const [dropIndex, setDropIndex] = useState(null);

  useEffect(() => {
    apiClient.get(`/me/forms/${fid}`).then((r) => {
      const f = r.data;
      setForm({ ...f, pages: f.pages?.length ? f.pages : [{ id: uid(), title: "Page 1", fields: [] }] });
    }).catch(() => toast.error("Formulaire introuvable"));
    apiClient.get("/me/form-categories").then((r) => setCategories(r.data || [])).catch(() => setCategories([]));
  }, [fid]);

  // Alerte avant de quitter avec des modifications non enregistrées
  useEffect(() => {
    const h = (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirty]);

  // Échap ferme l'aperçu
  useEffect(() => {
    if (!preview) return undefined;
    const h = (e) => { if (e.key === "Escape") setPreview(false); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [preview]);

  const change = (patch) => { setForm((f) => ({ ...f, ...patch })); setDirty(true); };
  const pages = form?.pages || [];
  const page = pages[Math.min(pageIdx, Math.max(0, pages.length - 1))] || { fields: [] };
  const setPages = (fn) => change({ pages: fn(clone(pages)) });
  const selField = page.fields.find((f) => f.id === selected);   // champ sélectionné (panneau de droite)
  const signatureCount = pages.flatMap((p) => p.fields).filter((f) => f.type === "signature").length;

  // ---- Champs ------------------------------------------------------------
  const insertField = (type, at) => {
    const f = newField(type);
    setPages((ps) => { const fs = ps[pageIdx].fields; fs.splice(at ?? fs.length, 0, f); return ps; });
    setSelected(f.id);
  };
  const addAfterSelected = (type) => {
    const idx = page.fields.findIndex((f) => f.id === selected);
    insertField(type, idx >= 0 ? idx + 1 : page.fields.length);
  };
  const updateField = (nf) => setPages((ps) => { ps[pageIdx].fields = ps[pageIdx].fields.map((f) => (f.id === nf.id ? nf : f)); return ps; });
  const moveField = (from, to) => setPages((ps) => {
    const fs = ps[pageIdx].fields;
    if (to < 0 || to >= fs.length) return ps;
    const [x] = fs.splice(from, 1); fs.splice(to, 0, x); return ps;
  });
  const dupField = (i) => setPages((ps) => { const c = { ...clone(ps[pageIdx].fields[i]), id: uid() }; ps[pageIdx].fields.splice(i + 1, 0, c); return ps; });
  const delField = (i) => { setPages((ps) => { ps[pageIdx].fields.splice(i, 1); return ps; }); setSelected(null); };
  const moveToPage = (target) => {
    if (target === pageIdx || !selField) return;
    setPages((ps) => { ps[pageIdx].fields = ps[pageIdx].fields.filter((f) => f.id !== selField.id); ps[target].fields.push(selField); return ps; });
    setPageIdx(target);
  };
  // Glisser-déposer (HTML5) : depuis la palette ou pour réordonner
  const onDrop = (e, at) => {
    e.preventDefault();
    if (dragInfo?.kind === "new") insertField(dragInfo.type, at);
    else if (dragInfo?.kind === "move") moveField(dragInfo.index, at > dragInfo.index ? at - 1 : at);
    setDragInfo(null); setDropIndex(null);
  };

  // ---- Pages --------------------------------------------------------------
  const addPage = () => { setPages((ps) => [...ps, { id: uid(), title: `Page ${ps.length + 1}`, fields: [] }]); setPageIdx(pages.length); setSelected(null); };
  const removePage = () => {
    if (pages.length <= 1) return;
    if (page.fields.length && !window.confirm(`Supprimer « ${page.title || `Page ${pageIdx + 1}`} » et ses ${page.fields.length} champ(s) ?`)) return;
    setPages((ps) => ps.filter((_, i) => i !== pageIdx)); setPageIdx(0); setSelected(null);
  };

  const save = async () => {
    if (signatureCount > 1) { toast.error("Un seul champ signature par formulaire"); return; }
    setSaving(true);
    try {
      // Ordre d'affichage enregistré dans `row` ; options vides retirées
      const cleanPages = pages.map((p) => ({ ...p, fields: p.fields.map((f, i) => ({ ...f, row: i,
        ...(f.options ? { options: f.options.map((o) => String(o).trim()).filter(Boolean) } : {}) })) }));
      await apiClient.put(`/me/forms/${fid}`, {
        title: form.title, description: form.description, is_public: form.is_public,
        category_id: form.category_id || null, pages: cleanPages,
        access_client_ids: Array.isArray(form.access_client_ids) ? form.access_client_ids : [],
      });
      setDirty(false);
      toast.success("Formulaire sauvegardé");
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); } finally { setSaving(false); }
  };

  if (!form) return <div className="text-center text-slate-500 py-10">Chargement…</div>;

  return (
    <div className="max-w-7xl space-y-4" data-testid="form-editor-page">
      {/* Barre d'actions */}
      <div className="flex flex-wrap items-center gap-3">
        <button onClick={() => { if (!dirty || window.confirm("Quitter sans enregistrer les modifications ?")) navigate(`${base}/forms`); }}
          className="text-sm text-slate-500 hover:text-slate-900 inline-flex items-center gap-1"><ArrowLeft className="h-4 w-4" /> Retour</button>
        <code className="text-[11px] font-mono bg-slate-100 px-2 py-0.5 rounded">{form.number}</code>
        <div className="flex-1" />
        <button onClick={() => { setPreviewData({}); setPreviewPage(pageIdx); setPreview(true); }} data-testid="builder-preview-btn"
          className="inline-flex items-center gap-1.5 text-sm rounded-lg bg-slate-100 hover:bg-slate-200 px-3 py-2"><Eye className="h-4 w-4" /> Aperçu</button>
        <button onClick={() => navigate(`${base}/forms/${fid}/fill`)} className="inline-flex items-center gap-1.5 text-sm rounded-lg bg-slate-100 hover:bg-slate-200 px-3 py-2" data-testid="form-preview-btn"><PlayCircle className="h-4 w-4" /> Remplir</button>
        {form.is_public && (
          <button onClick={() => setShowShare(true)} className="inline-flex items-center gap-1.5 text-sm rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-2" data-testid="form-share-btn"><Share2 className="h-4 w-4" /> Partager</button>
        )}
        <button onClick={save} disabled={saving} data-testid="form-save-btn"
          className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light disabled:opacity-50">
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} {dirty ? "Sauvegarder" : "Sauvegardé"}
        </button>
      </div>
      {showShare && <ShareFormModal form={form} onClose={() => setShowShare(false)} />}

      {/* En-tête du formulaire */}
      <div className="rounded-xl border border-slate-200 bg-white p-5 space-y-3">
        <input value={form.title} onChange={(e) => change({ title: e.target.value })} className="w-full text-2xl font-display font-bold focus:outline-none" placeholder="Titre du formulaire" data-testid="form-title-input" />
        <textarea value={form.description || ""} onChange={(e) => change({ description: e.target.value })} className="w-full text-sm text-slate-600 focus:outline-none resize-none" placeholder="Brève description…" rows={2} data-testid="form-desc-input" />
        <div className="flex flex-wrap items-center gap-4">
          <label className="inline-flex items-center gap-2 text-sm" data-testid="form-public-toggle-wrap">
            <input type="checkbox" checked={form.is_public} onChange={(e) => change({ is_public: e.target.checked })} data-testid="form-public-toggle" />
            {form.is_public ? <><Globe className="h-4 w-4 text-emerald-600" /> Public — importable par les autres clients</> : <><Lock className="h-4 w-4 text-slate-500" /> Privé</>}
          </label>
          {categories.length > 0 && (
            <label className="text-xs"><span className="text-slate-600 mr-2">Catégorie :</span>
              <select value={form.category_id || ""} onChange={(e) => change({ category_id: e.target.value || null })} className="text-sm rounded ring-1 ring-slate-300 px-2 py-1" data-testid="form-category-select">
                <option value="">— Sans catégorie —</option>
                {categories.map((c) => <option key={c.id} value={c.id}>{c.name}{c.is_default ? " (défaut)" : ""}</option>)}
              </select></label>
          )}
        </div>
        <ClientAccessSelector value={Array.isArray(form.access_client_ids) ? form.access_client_ids : []}
          onChange={(ids) => change({ access_client_ids: ids })} label="Clients autorisés à voir ce formulaire" testIdPrefix="form-access-clients" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[200px_1fr_290px] gap-4">
        {/* Palette */}
        <div className="space-y-1" data-testid="builder-palette">
          <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">Ajouter un champ</p>
          <div className="grid grid-cols-2 lg:grid-cols-1 gap-1">
            {FIELD_TYPES.map((t) => (
              <button key={t.v} type="button" draggable onDragStart={() => setDragInfo({ kind: "new", type: t.v })} onDragEnd={() => setDragInfo(null)}
                onClick={() => addAfterSelected(t.v)} data-testid={`palette-${t.v}`}
                className="flex items-center gap-2 rounded-lg ring-1 ring-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700 hover:ring-sawali-blue hover:text-sawali-blue hover:bg-sawali-blue/5 cursor-grab transition">
                <t.icon className="h-3.5 w-3.5 text-sawali-blue" /> {t.l}
              </button>
            ))}
          </div>
          <p className="text-[10px] text-slate-400 pt-1">Clic : ajoute après le champ sélectionné. Glisser : dépose à l'endroit voulu.</p>
        </div>

        {/* Pages + champs */}
        <div className="space-y-2 min-w-0">
          <div className="flex flex-wrap items-center gap-1">
            {pages.map((p, i) => (
              <button key={p.id} type="button" onClick={() => { setPageIdx(i); setSelected(null); }} data-testid={`form-page-tab-${i}`}
                className={`text-xs px-3 py-1.5 rounded-full ring-1 transition ${i === pageIdx ? "bg-sawali-blue text-white ring-sawali-blue" : "bg-white ring-slate-200 hover:ring-sawali-blue/50"}`}>
                {p.title || `Page ${i + 1}`} ({p.fields.length})
              </button>
            ))}
            <button type="button" onClick={addPage} className="inline-flex items-center gap-1 text-xs text-sawali-blue hover:underline px-2" data-testid="form-page-add"><Plus className="h-3 w-3" /> Page</button>
          </div>
          <div className="flex items-center gap-2">
            <input value={page.title || ""} onChange={(e) => setPages((ps) => { ps[pageIdx].title = e.target.value; return ps; })} placeholder="Titre de la page"
              className="max-w-xs rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm font-semibold" aria-label="Titre de la page" data-testid="form-page-title" />
            {pages.length > 1 && (
              <button type="button" onClick={removePage} className="text-xs text-rose-500 hover:bg-rose-50 rounded px-1.5 py-1 inline-flex items-center gap-1" data-testid={`form-page-remove-${pageIdx}`}>
                <Trash2 className="h-3 w-3" /> Supprimer la page</button>
            )}
          </div>
          <div className="rounded-xl border-2 border-dashed border-slate-200 bg-slate-50/60 p-3 space-y-2 min-h-[240px]" data-testid="builder-canvas"
            onDragOver={(e) => { e.preventDefault(); if (dropIndex === null) setDropIndex(page.fields.length); }}
            onDrop={(e) => onDrop(e, dropIndex ?? page.fields.length)}>
            {page.fields.length === 0 && <p className="text-sm text-slate-400 italic py-10 text-center">Cliquez ou glissez un type de champ depuis la palette.</p>}
            {page.fields.map((f, i) => {
              const T = TYPE_BY[f.type];
              return (
                <div key={f.id}>
                  {dropIndex === i && dragInfo && <div className="h-1 rounded bg-sawali-blue/60 my-1" />}
                  <div draggable onDragStart={() => setDragInfo({ kind: "move", index: i })} onDragEnd={() => { setDragInfo(null); setDropIndex(null); }}
                    onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); const r = e.currentTarget.getBoundingClientRect(); setDropIndex(e.clientY < r.top + r.height / 2 ? i : i + 1); }}
                    onClick={() => setSelected(f.id)} data-testid={`form-field-${i}`}
                    className={`group flex items-center gap-2 rounded-xl border bg-white px-3 py-2.5 cursor-pointer transition ${selected === f.id ? "border-sawali-blue ring-2 ring-sawali-blue/20 shadow-sm" : "border-slate-200 hover:border-slate-300"}`}>
                    <GripVertical className="h-4 w-4 text-slate-300 cursor-grab shrink-0" />
                    {T && <span className="h-7 w-7 rounded-lg bg-sawali-blue/10 text-sawali-blue inline-flex items-center justify-center shrink-0"><T.icon className="h-3.5 w-3.5" /></span>}
                    <div className="min-w-0 flex-1">
                      <p className="text-sm truncate">{f.label || "(sans libellé)"}{f.required && <span className="text-rose-600"> *</span>}</p>
                      <p className="text-[11px] text-slate-400">{T?.l || f.type} · {(WIDTHS.find(([v]) => v === (f.col_span || 12)) || [0, `${f.col_span}/12`])[1]}
                        {(f.options || []).length ? ` · ${f.options.length} option(s)` : ""}</p>
                    </div>
                    <div className="flex items-center gap-0.5 opacity-60 group-hover:opacity-100">
                      <button type="button" title="Monter" onClick={(e) => { e.stopPropagation(); moveField(i, i - 1); }} className="p-1 hover:text-sawali-blue"><ArrowUp className="h-3.5 w-3.5" /></button>
                      <button type="button" title="Descendre" onClick={(e) => { e.stopPropagation(); moveField(i, i + 1); }} className="p-1 hover:text-sawali-blue"><ArrowDown className="h-3.5 w-3.5" /></button>
                      <button type="button" title="Dupliquer" onClick={(e) => { e.stopPropagation(); dupField(i); }} className="p-1 hover:text-sawali-blue" data-testid={`field-dup-${i}`}><Copy className="h-3.5 w-3.5" /></button>
                      <button type="button" title="Supprimer" onClick={(e) => { e.stopPropagation(); delField(i); }} className="p-1 hover:text-rose-600" data-testid={`field-remove-${i}`}><Trash2 className="h-3.5 w-3.5" /></button>
                    </div>
                  </div>
                </div>
              );
            })}
            {dropIndex === page.fields.length && dragInfo && page.fields.length > 0 && <div className="h-1 rounded bg-sawali-blue/60 my-1" />}
          </div>
        </div>

        {/* Propriétés */}
        <div className="rounded-xl border border-slate-200 bg-white p-4 h-fit lg:sticky lg:top-4">
          {selField ? (
            <Properties field={selField} pages={pages} pageIdx={pageIdx} update={updateField} moveToPage={moveToPage}
              signatureTaken={selField.type === "signature" && signatureCount > 1} />
          ) : <p className="text-sm text-slate-400 italic">Sélectionnez un champ pour le configurer.</p>}
        </div>
      </div>

      {/* Aperçu en direct : même rendu que le formulaire réel */}
      {preview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40" onClick={(e) => e.target === e.currentTarget && setPreview(false)}>
          <div className="w-full max-w-4xl max-h-[90vh] overflow-auto rounded-2xl bg-white p-6 shadow-2xl space-y-4" data-testid="builder-preview">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-wider text-slate-500">Aperçu (rien n'est enregistré)</p>
                <h2 className="text-xl font-display font-bold text-slate-900">{form.title}</h2>
                {form.description && <p className="text-sm text-slate-600 mt-1 whitespace-pre-line">{form.description}</p>}
              </div>
              <button onClick={() => setPreview(false)} className="p-1 rounded hover:bg-slate-100" aria-label="Fermer"><X className="h-5 w-5" /></button>
            </div>
            {pages.length > 1 && (
              <div className="flex flex-wrap gap-1">
                {pages.map((p, i) => (
                  <button key={p.id} onClick={() => setPreviewPage(i)} className={`text-xs px-3 py-1 rounded-full ring-1 ${i === previewPage ? "bg-sawali-blue text-white ring-sawali-blue" : "ring-slate-200"}`}>
                    {p.title || `Page ${i + 1}`}</button>
                ))}
              </div>
            )}
            <div className="grid grid-cols-12 gap-3 rounded-xl border border-slate-200 p-5">
              {(pages[previewPage]?.fields || []).map((f) => (
                <div key={f.id} className="min-w-0" style={{ gridColumn: `span ${Math.min(12, f.col_span || 12)} / span ${Math.min(12, f.col_span || 12)}` }}>
                  <label className="block text-[11px] font-semibold uppercase tracking-wider text-slate-600 mb-1">{f.label}{f.required && <span className="text-rose-500 ml-1">*</span>}</label>
                  {f.type === "file"
                    ? <p className="rounded-lg border border-dashed border-slate-300 px-3 py-2 text-xs text-slate-400">Fichier joint{f.accept ? ` (${f.accept})` : ""} — envoi possible dans le vrai formulaire</p>
                    : <FieldInput field={f} value={previewData[f.id] ?? f.default_value ?? undefined} onChange={(v) => setPreviewData((d) => ({ ...d, [f.id]: v }))} />}
                </div>
              ))}
              {!(pages[previewPage]?.fields || []).length && <p className="col-span-12 text-sm text-slate-400 italic">Aucun champ sur cette page.</p>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
