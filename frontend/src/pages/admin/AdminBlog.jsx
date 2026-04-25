import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Plus, Trash2, Edit, X, Upload, Image as ImageIcon, Eye, EyeOff, Star } from "lucide-react";
import { toast } from "sonner";

const empty = {
  title: "", slug: "", excerpt: "", body_html: "",
  cover_image_url: "",
  author_name: "Équipe SAWALI", author_role: "", author_photo_url: "",
  tags: [], reading_time_min: 5,
  is_published: true, featured: false,
};

export default function AdminBlog() {
  const [items, setItems] = useState([]);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(empty);
  const [tagInput, setTagInput] = useState("");
  const [uploadingField, setUploadingField] = useState(null);

  const load = () => apiClient.get("/admin/blog").then((r) => setItems(r.data));
  useEffect(() => { load().catch(() => {}); }, []);

  const open = async (it = null) => {
    if (it?.id) {
      const r = await apiClient.get(`/admin/blog/${it.id}`);
      setEditing(r.data);
      setForm({ ...empty, ...r.data, tags: r.data.tags || [] });
    } else {
      setEditing({});
      setForm(empty);
    }
    setTagInput("");
  };
  const close = () => { setEditing(null); setForm(empty); setTagInput(""); };

  const upload = async (file, field) => {
    const fd = new FormData(); fd.append("file", file);
    setUploadingField(field);
    try {
      const r = await apiClient.post("/admin/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      const url = `${process.env.REACT_APP_BACKEND_URL}${r.data.url}`;
      setForm((p) => ({ ...p, [field]: url }));
      toast.success("Image téléversée");
    } catch (err) { toast.error("Erreur upload"); }
    finally { setUploadingField(null); }
  };

  const submit = async (e) => {
    e.preventDefault();
    try {
      const payload = { ...form, reading_time_min: parseInt(form.reading_time_min) || 0 };
      if (editing?.id) await apiClient.put(`/admin/blog/${editing.id}`, payload);
      else await apiClient.post("/admin/blog", payload);
      toast.success("Article enregistré"); close(); await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };
  const del = async (id) => {
    if (!window.confirm("Supprimer cet article ?")) return;
    await apiClient.delete(`/admin/blog/${id}`);
    await load();
  };
  const togglePublish = async (it) => {
    await apiClient.put(`/admin/blog/${it.id}`, { is_published: !it.is_published });
    await load();
  };

  const addTag = () => {
    const t = tagInput.trim();
    if (t && !form.tags.includes(t)) setForm((p) => ({ ...p, tags: [...p.tags, t] }));
    setTagInput("");
  };
  const removeTag = (t) => setForm((p) => ({ ...p, tags: p.tags.filter((x) => x !== t) }));

  const wrapTag = (tag) => {
    const ta = document.querySelector('[data-testid="blog-body"]');
    if (!ta) return;
    const start = ta.selectionStart, end = ta.selectionEnd;
    const text = form.body_html;
    const sel = text.slice(start, end);
    const wrapped = sel ? `<${tag}>${sel}</${tag}>` : `<${tag}></${tag}>`;
    setForm({ ...form, body_html: text.slice(0, start) + wrapped + text.slice(end) });
  };

  return (
    <div className="space-y-6" data-testid="admin-blog-page">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-display font-bold">Blog technique</h1>
          <p className="text-sm text-slate-500">Publiez vos articles d'expertise et retours d'expérience.</p>
        </div>
        <button onClick={() => open()} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light" data-testid="new-blog-btn">
          <Plus className="h-4 w-4" /> Nouvel article
        </button>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.length === 0 && <p className="text-slate-500 col-span-full">Aucun article.</p>}
        {items.map((p) => (
          <div key={p.id} className="rounded-xl border border-slate-200 bg-white overflow-hidden" data-testid={`blog-row-${p.id}`}>
            <div className="h-32 bg-slate-100 relative">
              {p.cover_image_url ? <img src={p.cover_image_url} alt="" className="h-full w-full object-cover" /> : <div className="h-full grid place-items-center"><ImageIcon className="h-7 w-7 text-slate-400" /></div>}
              {p.featured && <span className="absolute top-2 left-2 text-[9px] uppercase tracking-widest bg-amber-400 text-amber-900 px-2 py-0.5 rounded inline-flex items-center gap-1"><Star className="h-3 w-3" />À la une</span>}
              {!p.is_published && <span className="absolute top-2 right-2 text-[9px] uppercase tracking-widest bg-slate-700 text-white px-2 py-0.5 rounded">Brouillon</span>}
            </div>
            <div className="p-4">
              <p className="text-[10px] uppercase tracking-widest text-sawali-blue">
                {p.published_at ? new Date(p.published_at).toLocaleDateString("fr-FR") : "—"} · {p.reading_time_min || 0} min · {p.views || 0} vues
              </p>
              <h3 className="font-display font-semibold mt-1 line-clamp-2">{p.title}</h3>
              <p className="text-xs text-slate-500 mt-0.5 truncate">par {p.author_name}</p>
              <div className="mt-3 flex flex-wrap gap-2 text-xs">
                <button onClick={() => open(p)} className="text-sawali-blue hover:underline inline-flex items-center gap-1"><Edit className="h-3 w-3" /> Modifier</button>
                <button onClick={() => togglePublish(p)} className="text-slate-600 hover:text-sawali-blue inline-flex items-center gap-1">
                  {p.is_published ? <><EyeOff className="h-3 w-3" /> Dépublier</> : <><Eye className="h-3 w-3" /> Publier</>}
                </button>
                <button onClick={() => del(p.id)} className="text-rose-600 hover:underline inline-flex items-center gap-1 ml-auto"><Trash2 className="h-3 w-3" /> Supprimer</button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {editing !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 overflow-y-auto" onClick={close}>
          <div className="bg-white rounded-xl w-full max-w-3xl my-8" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b sticky top-0 bg-white rounded-t-xl">
              <h3 className="font-display font-semibold">{editing?.id ? "Modifier l'article" : "Nouvel article"}</h3>
              <button onClick={close}><X className="h-4 w-4" /></button>
            </div>
            <form onSubmit={submit} className="p-5 space-y-5" data-testid="blog-form">
              <div className="grid sm:grid-cols-2 gap-3">
                <Field label="Titre *" required value={form.title} onChange={(v) => setForm({ ...form, title: v })} testid="blog-title" />
                <Field label="Slug (URL)" value={form.slug} onChange={(v) => setForm({ ...form, slug: v })} placeholder="auto-généré" testid="blog-slug" />
              </div>
              <Textarea label="Résumé / Extrait" rows={2} value={form.excerpt} onChange={(v) => setForm({ ...form, excerpt: v })} testid="blog-excerpt" />

              {/* Cover */}
              <div>
                <label className="text-xs font-semibold">Image de couverture</label>
                <ImagePicker url={form.cover_image_url} onUpload={(f) => upload(f, "cover_image_url")} onClear={() => setForm({ ...form, cover_image_url: "" })} loading={uploadingField === "cover_image_url"} testid="blog-cover" />
              </div>

              {/* Author */}
              <div className="rounded-lg border border-slate-200 p-4">
                <p className="text-xs font-semibold mb-3">Auteur</p>
                <div className="flex items-center gap-4">
                  {form.author_photo_url ? (
                    <img src={form.author_photo_url} alt="" className="h-12 w-12 rounded-full object-cover ring-1 ring-slate-200" />
                  ) : (
                    <div className="h-12 w-12 rounded-full bg-sawali-blue/10 grid place-items-center"><ImageIcon className="h-5 w-5 text-sawali-blue" /></div>
                  )}
                  <label className="inline-flex items-center gap-2 cursor-pointer rounded-md border border-slate-300 px-3 py-1.5 text-xs hover:bg-slate-50">
                    <Upload className="h-3 w-3" /> {uploadingField === "author_photo_url" ? "..." : "Photo"}
                    <input type="file" hidden accept="image/*" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0], "author_photo_url")} data-testid="blog-author-photo" />
                  </label>
                  {form.author_photo_url && <button type="button" onClick={() => setForm({ ...form, author_photo_url: "" })} className="text-xs text-rose-600 underline">Retirer</button>}
                </div>
                <div className="mt-3 grid sm:grid-cols-2 gap-3">
                  <Field label="Nom" value={form.author_name} onChange={(v) => setForm({ ...form, author_name: v })} testid="blog-author-name" />
                  <Field label="Rôle" value={form.author_role} onChange={(v) => setForm({ ...form, author_role: v })} placeholder="Lead Dev, CTO..." testid="blog-author-role" />
                </div>
              </div>

              {/* Body HTML */}
              <div>
                <label className="text-xs font-semibold">Contenu (HTML)</label>
                <div className="flex gap-1 my-1 text-xs">
                  {[["h2", "Titre"], ["h3", "Sous-titre"], ["p", "Paragraphe"], ["b", "Gras"], ["i", "Italique"], ["ul", "Liste"], ["li", "Item"], ["blockquote", "Citation"], ["code", "Code"]].map(([t, l]) => (
                    <button type="button" key={t} onClick={() => wrapTag(t)} className="px-2 py-1 rounded border border-slate-200 hover:bg-slate-50">{l}</button>
                  ))}
                </div>
                <textarea rows={14} value={form.body_html} onChange={(e) => setForm({ ...form, body_html: e.target.value })}
                          placeholder="<h2>Introduction</h2><p>...</p>"
                          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" data-testid="blog-body" />
                {form.body_html && (
                  <details className="mt-2">
                    <summary className="text-xs text-sawali-blue cursor-pointer">Aperçu du rendu</summary>
                    <div className="mt-2 rounded-lg border border-slate-200 p-4 bg-slate-50 prose-sawali" dangerouslySetInnerHTML={{ __html: form.body_html }} />
                  </details>
                )}
              </div>

              {/* Tags + reading time */}
              <div className="grid sm:grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold">Tags</label>
                  <div className="flex gap-2 mt-1">
                    <input value={tagInput} onChange={(e) => setTagInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addTag())}
                           placeholder="Ingénierie, Cloud..." className="flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm" data-testid="blog-tag-input" />
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
                <Field label="Temps de lecture (min)" value={form.reading_time_min} onChange={(v) => setForm({ ...form, reading_time_min: v })} placeholder="5" testid="blog-reading-time" />
              </div>

              <div className="grid sm:grid-cols-2 gap-3">
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={form.is_published} onChange={(e) => setForm({ ...form, is_published: e.target.checked })} data-testid="blog-published" />
                  Publié
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={form.featured} onChange={(e) => setForm({ ...form, featured: e.target.checked })} data-testid="blog-featured" />
                  À la une (mise en avant en tête de page blog)
                </label>
              </div>

              <button type="submit" className="w-full rounded-lg bg-sawali-blue text-white px-4 py-2.5 text-sm font-medium hover:bg-sawali-blue-light" data-testid="save-blog-btn">
                {editing?.id ? "Mettre à jour" : "Créer l'article"}
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
const Textarea = ({ label, rows = 3, value, onChange, testid }) => (
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
