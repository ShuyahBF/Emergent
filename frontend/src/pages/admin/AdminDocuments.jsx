import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Upload, Trash2, Plus, X, FileText, Image as ImageIcon, Globe } from "lucide-react";
import { toast } from "sonner";

const empty = {
  title: "", description: "", category: "documentation",
  file_id: null, file_url: null, file_type: null,
  body_html: "", client_id: "", is_public: false, cover_image_url: "",
};

export default function AdminDocuments() {
  const [items, setItems] = useState([]);
  const [clients, setClients] = useState([]);
  const [isOpen, setIsOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(empty);
  const [uploading, setUploading] = useState(false);

  const load = () => apiClient.get("/admin/documents").then((r) => setItems(r.data));
  useEffect(() => {
    load().catch(() => {});
    apiClient.get("/admin/clients").then((r) => setClients(r.data));
  }, []);

  const open = (it = null) => {
    setEditing(it);
    setForm(it ? { ...empty, ...it, client_id: it.client_id || "" } : empty);
    setIsOpen(true);
  };
  const close = () => { setIsOpen(false); setEditing(null); setForm(empty); };

  const upload = async (file) => {
    const fd = new FormData(); fd.append("file", file);
    setUploading(true);
    try {
      const r = await apiClient.post("/admin/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      const ct = (r.data.content_type || "").toLowerCase();
      const ft = ct.startsWith("image/") ? "image" : ct.includes("pdf") ? "pdf" : "file";
      setForm((prev) => ({ ...prev, file_id: r.data.id, file_url: r.data.url, file_type: ft }));
      toast.success("Fichier téléversé");
    } catch (err) { toast.error("Erreur upload"); }
    finally { setUploading(false); }
  };

  const submit = async (e) => {
    e.preventDefault();
    const payload = { ...form, client_id: form.client_id || null };
    try {
      if (editing?.id) await apiClient.put(`/admin/documents/${editing.id}`, payload);
      else await apiClient.post("/admin/documents", payload);
      toast.success("Document enregistré"); close(); await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const del = async (id) => {
    if (!window.confirm("Supprimer ?")) return;
    await apiClient.delete(`/admin/documents/${id}`);
    await load();
  };

  return (
    <div className="space-y-6" data-testid="admin-documents-page">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-display font-bold">Documents</h1>
          <p className="text-sm text-slate-500">Catalogue, documentation logiciels, annonces. Téléversement PDF/images/textes.</p>
        </div>
        <button onClick={() => open()} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm" data-testid="new-doc-btn">
          <Plus className="h-4 w-4" /> Nouveau document
        </button>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.map((it) => (
          <div key={it.id} className="rounded-xl border border-slate-200 bg-white overflow-hidden" data-testid={`admin-doc-${it.id}`}>
            <div className="h-32 bg-slate-50 flex items-center justify-center">
              {it.cover_image_url ? <img src={it.cover_image_url} alt="" className="h-full w-full object-cover" /> :
                it.file_type === "image" ? <ImageIcon className="h-8 w-8 text-slate-400" /> :
                it.body_html ? <Globe className="h-8 w-8 text-slate-400" /> :
                <FileText className="h-8 w-8 text-slate-400" />}
            </div>
            <div className="p-4">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-[10px] uppercase tracking-widest text-sawali-blue">{it.category}</span>
                {it.is_public && <span className="text-[10px] bg-emerald-100 text-emerald-700 px-2 rounded">Public</span>}
              </div>
              <h3 className="font-display font-semibold text-sm">{it.title}</h3>
              <div className="mt-3 flex gap-3 text-xs">
                <button onClick={() => open(it)} className="text-sawali-blue hover:underline">Modifier</button>
                <button onClick={() => del(it.id)} className="text-rose-600 hover:underline">Supprimer</button>
              </div>
            </div>
          </div>
        ))}
        {items.length === 0 && <p className="text-slate-500 col-span-full">Aucun document. Créez-en un.</p>}
      </div>

      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={close}>
          <div className="bg-white rounded-xl w-full max-w-2xl max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="font-display font-semibold">{editing?.id ? "Modifier" : "Nouveau document"}</h3>
              <button onClick={close}><X className="h-4 w-4" /></button>
            </div>
            <form onSubmit={submit} className="p-4 space-y-3" data-testid="document-form">
              <div className="grid sm:grid-cols-2 gap-3">
                <Input label="Titre *" value={form.title} onChange={(v) => setForm({ ...form, title: v })} required />
                <div>
                  <label className="block text-xs font-semibold mb-1">Catégorie</label>
                  <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                    <option value="documentation">Documentation logiciel</option>
                    <option value="catalog">Catalogue (public)</option>
                    <option value="announcement">Annonce</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="block text-xs font-semibold mb-1">Description</label>
                <textarea rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-xs font-semibold mb-1">Fichier (PDF / image)</label>
                <label className="inline-flex items-center gap-2 cursor-pointer rounded-lg border border-dashed border-slate-300 px-4 py-3 text-sm text-slate-600 hover:border-sawali-blue">
                  <Upload className="h-4 w-4" /> {uploading ? "Téléversement..." : (form.file_url ? "Remplacer le fichier" : "Choisir un fichier")}
                  <input type="file" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} accept="image/*,application/pdf" data-testid="doc-file-input" />
                </label>
                {form.file_url && <p className="text-xs text-slate-500 mt-1 break-all">URL : {form.file_url}</p>}
              </div>
              <div>
                <label className="block text-xs font-semibold mb-1">Contenu HTML (texte enrichi, optionnel)</label>
                <RichEditor value={form.body_html || ""} onChange={(v) => setForm({ ...form, body_html: v })} />
              </div>
              <Input label="Image de couverture (URL)" value={form.cover_image_url || ""} onChange={(v) => setForm({ ...form, cover_image_url: v })} />
              <div className="grid sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold mb-1">Visibilité</label>
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={form.is_public} onChange={(e) => setForm({ ...form, is_public: e.target.checked })} />
                    Document public (visible par tous)
                  </label>
                </div>
                <div>
                  <label className="block text-xs font-semibold mb-1">Client spécifique</label>
                  <select value={form.client_id} onChange={(e) => setForm({ ...form, client_id: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                    <option value="">— Tous les clients —</option>
                    {clients.map((c) => <option key={c.id} value={c.id}>{c.full_name}</option>)}
                  </select>
                </div>
              </div>
              <button type="submit" className="w-full rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm">Enregistrer</button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

const Input = ({ label, value, onChange, required, type = "text" }) => (
  <div>
    <label className="block text-xs font-semibold mb-1">{label}</label>
    <input type={type} required={required} value={value} onChange={(e) => onChange(e.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
  </div>
);

const RichEditor = ({ value, onChange }) => {
  const wrap = (tag) => {
    const sel = window.getSelection();
    const txt = sel?.toString();
    if (txt) onChange(value.replace(txt, `<${tag}>${txt}</${tag}>`));
  };
  return (
    <div>
      <div className="flex gap-1 mb-1 text-xs">
        {[["b", "Gras"], ["i", "Italique"], ["u", "Souligné"], ["h2", "Titre"], ["p", "Paragraphe"]].map(([t, l]) => (
          <button key={t} type="button" onClick={() => wrap(t)} className="px-2 py-1 rounded border border-slate-200 hover:bg-slate-50">{l}</button>
        ))}
      </div>
      <textarea rows={6} value={value} onChange={(e) => onChange(e.target.value)} placeholder="<p>Votre contenu HTML</p>"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" />
      {value && <div className="mt-2 rounded-lg border border-slate-200 p-3 prose-sawali bg-slate-50 max-h-40 overflow-auto" dangerouslySetInnerHTML={{ __html: value }} />}
    </div>
  );
};
