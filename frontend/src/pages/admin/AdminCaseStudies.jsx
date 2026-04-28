import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Plus, Trash2, Edit, X, Upload, Image as ImageIcon, Star, Eye, EyeOff } from "lucide-react";
import { toast } from "sonner";

const empty = {
  title: "", slug: "", client_name: "", sector: "", year: "", duration: "",
  summary: "", challenge: "", solution: "", results: "",
  cover_image_url: "", before_image_url: "", after_image_url: "",
  gallery: [], kpis: [], tags: [],
  is_published: true, featured: false,
};

export default function AdminCaseStudies() {
  const [items, setItems] = useState([]);
  const [isOpen, setIsOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(empty);
  const [tagInput, setTagInput] = useState("");
  const [uploadingField, setUploadingField] = useState(null);

  const load = () => apiClient.get("/admin/case-studies").then((r) => setItems(r.data));
  useEffect(() => { load().catch(() => {}); }, []);

  const open = (it = null) => {
    setEditing(it);
    setForm(it ? { ...empty, ...it, kpis: it.kpis || [], gallery: it.gallery || [], tags: it.tags || [] } : empty);
    setTagInput("");
    setIsOpen(true);
  };
  const close = () => { setIsOpen(false); setEditing(null); setForm(empty); setTagInput(""); };

  const upload = async (file, field) => {
    const fd = new FormData(); fd.append("file", file);
    setUploadingField(field);
    try {
      const r = await apiClient.post("/admin/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      const url = `${process.env.REACT_APP_BACKEND_URL}${r.data.url}`;
      if (field === "gallery") {
        setForm((p) => ({ ...p, gallery: [...p.gallery, url] }));
      } else {
        setForm((p) => ({ ...p, [field]: url }));
      }
      toast.success("Image téléversée");
    } catch (err) { toast.error("Erreur upload"); }
    finally { setUploadingField(null); }
  };

  const submit = async (e) => {
    e.preventDefault();
    try {
      if (editing?.id) await apiClient.put(`/admin/case-studies/${editing.id}`, form);
      else await apiClient.post("/admin/case-studies", form);
      toast.success("Étude de cas enregistrée"); close(); await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const del = async (id) => {
    if (!window.confirm("Supprimer cette étude ?")) return;
    await apiClient.delete(`/admin/case-studies/${id}`);
    await load();
  };
  const togglePublish = async (it) => {
    await apiClient.put(`/admin/case-studies/${it.id}`, { is_published: !it.is_published });
    await load();
  };

  const addKpi = () => setForm((p) => ({ ...p, kpis: [...p.kpis, { label: "", value: "", suffix: "" }] }));
  const updateKpi = (i, k, v) => setForm((p) => ({ ...p, kpis: p.kpis.map((x, idx) => idx === i ? { ...x, [k]: v } : x) }));
  const removeKpi = (i) => setForm((p) => ({ ...p, kpis: p.kpis.filter((_, idx) => idx !== i) }));

  const addTag = () => {
    const t = tagInput.trim();
    if (t && !form.tags.includes(t)) setForm((p) => ({ ...p, tags: [...p.tags, t] }));
    setTagInput("");
  };
  const removeTag = (t) => setForm((p) => ({ ...p, tags: p.tags.filter((x) => x !== t) }));
  const removeGalleryAt = (i) => setForm((p) => ({ ...p, gallery: p.gallery.filter((_, idx) => idx !== i) }));

  return (
    <div className="space-y-6" data-testid="admin-case-studies-page">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-display font-bold">Études de cas</h1>
          <p className="text-sm text-slate-500">Présentez vos missions livrées avec photos avant/après et indicateurs clés.</p>
        </div>
        <button onClick={() => open()} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light" data-testid="new-case-study-btn">
          <Plus className="h-4 w-4" /> Nouvelle étude
        </button>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.length === 0 && <p className="text-slate-500 col-span-full">Aucune étude de cas.</p>}
        {items.map((c) => (
          <div key={c.id} className="rounded-xl border border-slate-200 bg-white overflow-hidden" data-testid={`case-row-${c.id}`}>
            <div className="h-32 bg-slate-100 relative">
              {c.cover_image_url ? <img src={c.cover_image_url} alt="" className="h-full w-full object-cover" /> : <div className="h-full grid place-items-center"><ImageIcon className="h-7 w-7 text-slate-400" /></div>}
              {c.featured && <span className="absolute top-2 left-2 text-[9px] uppercase tracking-widest bg-amber-400 text-amber-900 px-2 py-0.5 rounded inline-flex items-center gap-1"><Star className="h-3 w-3" />Mis en avant</span>}
              {!c.is_published && <span className="absolute top-2 right-2 text-[9px] uppercase tracking-widest bg-slate-700 text-white px-2 py-0.5 rounded">Brouillon</span>}
            </div>
            <div className="p-4">
              <p className="text-[10px] uppercase tracking-widest text-sawali-blue">{c.sector || "Étude"} {c.year && `· ${c.year}`}</p>
              <h3 className="font-display font-semibold mt-1 line-clamp-2">{c.title}</h3>
              {c.client_name && <p className="text-xs text-slate-500 mt-0.5">{c.client_name}</p>}
              <div className="mt-3 flex flex-wrap gap-2 text-xs">
                <button onClick={() => open(c)} className="text-sawali-blue hover:underline inline-flex items-center gap-1"><Edit className="h-3 w-3" /> Modifier</button>
                <button onClick={() => togglePublish(c)} className="text-slate-600 hover:text-sawali-blue inline-flex items-center gap-1">
                  {c.is_published ? <><EyeOff className="h-3 w-3" /> Dépublier</> : <><Eye className="h-3 w-3" /> Publier</>}
                </button>
                <button onClick={() => del(c.id)} className="text-rose-600 hover:underline inline-flex items-center gap-1 ml-auto"><Trash2 className="h-3 w-3" /> Supprimer</button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 overflow-y-auto" onClick={close}>
          <div className="bg-white rounded-xl w-full max-w-3xl my-8" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b sticky top-0 bg-white rounded-t-xl">
              <h3 className="font-display font-semibold">{editing?.id ? "Modifier l'étude" : "Nouvelle étude de cas"}</h3>
              <button onClick={close}><X className="h-4 w-4" /></button>
            </div>
            <form onSubmit={submit} className="p-5 space-y-5" data-testid="case-study-form">
              <div className="grid sm:grid-cols-2 gap-3">
                <Field label="Titre *" required value={form.title} onChange={(v) => setForm({ ...form, title: v })} testid="cs-title" />
                <Field label="Slug (URL)" value={form.slug} onChange={(v) => setForm({ ...form, slug: v })} placeholder="auto-généré si vide" testid="cs-slug" />
                <Field label="Client" value={form.client_name} onChange={(v) => setForm({ ...form, client_name: v })} testid="cs-client" />
                <Field label="Secteur" value={form.sector} onChange={(v) => setForm({ ...form, sector: v })} placeholder="Banque, Santé, Logistique..." testid="cs-sector" />
                <Field label="Année" value={form.year} onChange={(v) => setForm({ ...form, year: v })} placeholder="2025" testid="cs-year" />
                <Field label="Durée" value={form.duration} onChange={(v) => setForm({ ...form, duration: v })} placeholder="6 mois" testid="cs-duration" />
              </div>

              <Textarea label="Résumé (description courte)" value={form.summary} onChange={(v) => setForm({ ...form, summary: v })} rows={2} testid="cs-summary" />
              <Textarea label="Le défi" value={form.challenge} onChange={(v) => setForm({ ...form, challenge: v })} rows={3} testid="cs-challenge" />
              <Textarea label="Notre solution" value={form.solution} onChange={(v) => setForm({ ...form, solution: v })} rows={3} testid="cs-solution" />
              <Textarea label="Résultats" value={form.results} onChange={(v) => setForm({ ...form, results: v })} rows={3} testid="cs-results" />

              {/* KPIs */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-xs font-semibold">Indicateurs clés (KPIs)</label>
                  <button type="button" onClick={addKpi} className="text-xs text-sawali-blue inline-flex items-center gap-1" data-testid="add-kpi"><Plus className="h-3 w-3" /> Ajouter</button>
                </div>
                <div className="space-y-2">
                  {form.kpis.map((k, i) => (
                    <div key={i} className="grid grid-cols-12 gap-2" data-testid={`kpi-row-${i}`}>
                      <input placeholder="Label (Temps)" value={k.label} onChange={(e) => updateKpi(i, "label", e.target.value)} className="col-span-5 rounded-md border border-slate-300 px-2 py-1.5 text-sm" />
                      <input placeholder="Valeur (-70)" value={k.value} onChange={(e) => updateKpi(i, "value", e.target.value)} className="col-span-3 rounded-md border border-slate-300 px-2 py-1.5 text-sm" />
                      <input placeholder="Suffixe (%)" value={k.suffix || ""} onChange={(e) => updateKpi(i, "suffix", e.target.value)} className="col-span-3 rounded-md border border-slate-300 px-2 py-1.5 text-sm" />
                      <button type="button" onClick={() => removeKpi(i)} className="col-span-1 text-rose-600"><Trash2 className="h-4 w-4" /></button>
                    </div>
                  ))}
                  {form.kpis.length === 0 && <p className="text-xs text-slate-500">Aucun KPI. Ex : "Temps de traitement" / "-70" / "%"</p>}
                </div>
              </div>

              {/* Images */}
              <div>
                <label className="text-xs font-semibold">Image de couverture</label>
                <ImagePicker url={form.cover_image_url} onUpload={(f) => upload(f, "cover_image_url")} onClear={() => setForm({ ...form, cover_image_url: "" })} loading={uploadingField === "cover_image_url"} testid="cs-cover" />
              </div>
              <div className="grid sm:grid-cols-2 gap-4">
                <div>
                  <label className="text-xs font-semibold">Photo "Avant"</label>
                  <ImagePicker url={form.before_image_url} onUpload={(f) => upload(f, "before_image_url")} onClear={() => setForm({ ...form, before_image_url: "" })} loading={uploadingField === "before_image_url"} testid="cs-before" />
                </div>
                <div>
                  <label className="text-xs font-semibold">Photo "Après"</label>
                  <ImagePicker url={form.after_image_url} onUpload={(f) => upload(f, "after_image_url")} onClear={() => setForm({ ...form, after_image_url: "" })} loading={uploadingField === "after_image_url"} testid="cs-after" />
                </div>
              </div>

              {/* Gallery */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-xs font-semibold">Galerie</label>
                  <label className="text-xs text-sawali-blue inline-flex items-center gap-1 cursor-pointer">
                    <Upload className="h-3 w-3" /> {uploadingField === "gallery" ? "Téléversement..." : "Ajouter une image"}
                    <input type="file" hidden accept="image/*" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0], "gallery")} data-testid="cs-gallery-input" />
                  </label>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  {form.gallery.map((src, i) => (
                    <div key={i} className="relative rounded-md overflow-hidden border border-slate-200">
                      <img src={src} alt="" className="h-20 w-full object-cover" />
                      <button type="button" onClick={() => removeGalleryAt(i)} className="absolute top-1 right-1 bg-black/70 text-white rounded-full p-1"><X className="h-3 w-3" /></button>
                    </div>
                  ))}
                </div>
              </div>

              {/* Tags */}
              <div>
                <label className="text-xs font-semibold">Technologies / Tags</label>
                <div className="flex gap-2 mt-1">
                  <input value={tagInput} onChange={(e) => setTagInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addTag())}
                         placeholder="React, FastAPI, Mongo..." className="flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm" data-testid="cs-tag-input" />
                  <button type="button" onClick={addTag} className="rounded-md bg-slate-100 px-3 text-sm">Ajouter</button>
                </div>
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {form.tags.map((t) => (
                    <span key={t} className="text-xs px-2 py-1 rounded bg-sawali-blue/10 text-sawali-blue border border-sawali-blue/30 inline-flex items-center gap-1">
                      {t} <button type="button" onClick={() => removeTag(t)}><X className="h-3 w-3" /></button>
                    </span>
                  ))}
                </div>
              </div>

              <div className="grid sm:grid-cols-2 gap-3">
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={form.is_published} onChange={(e) => setForm({ ...form, is_published: e.target.checked })} data-testid="cs-published" />
                  Publié sur le site
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={form.featured} onChange={(e) => setForm({ ...form, featured: e.target.checked })} data-testid="cs-featured" />
                  Mettre en avant
                </label>
              </div>

              <button type="submit" className="w-full rounded-lg bg-sawali-blue text-white px-4 py-2.5 text-sm font-medium hover:bg-sawali-blue-light" data-testid="save-case-study-btn">
                {editing?.id ? "Mettre à jour" : "Créer l'étude de cas"}
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

const Field = ({ label, value, onChange, required, placeholder, testid }) => (
  <div>
    <label className="block text-xs font-semibold mb-1">{label}</label>
    <input required={required} value={value || ""} onChange={(e) => onChange(e.target.value)} placeholder={placeholder}
           className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid={testid} />
  </div>
);

const Textarea = ({ label, value, onChange, rows = 3, testid }) => (
  <div>
    <label className="block text-xs font-semibold mb-1">{label}</label>
    <textarea rows={rows} value={value || ""} onChange={(e) => onChange(e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid={testid} />
  </div>
);

const ImagePicker = ({ url, onUpload, onClear, loading, testid }) => (
  <div className="mt-1 flex items-center gap-3">
    {url ? (
      <img src={url} alt="" className="h-20 w-32 rounded-md object-cover border border-slate-200" />
    ) : (
      <div className="h-20 w-32 rounded-md border-2 border-dashed border-slate-200 grid place-items-center">
        <ImageIcon className="h-6 w-6 text-slate-400" />
      </div>
    )}
    <label className="inline-flex items-center gap-2 cursor-pointer rounded-md border border-slate-300 px-3 py-1.5 text-xs hover:bg-slate-50">
      <Upload className="h-3 w-3" /> {loading ? "Téléversement..." : (url ? "Remplacer" : "Téléverser")}
      <input type="file" hidden accept="image/*" onChange={(e) => e.target.files?.[0] && onUpload(e.target.files[0])} data-testid={testid} />
    </label>
    {url && <button type="button" onClick={onClear} className="text-xs text-rose-600 underline">Retirer</button>}
  </div>
);
