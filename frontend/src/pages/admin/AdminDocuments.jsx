import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Upload, Trash2, Plus, X, FileText, Image as ImageIcon, Globe, Settings, Edit2, Check, History, Download as DownloadIcon } from "lucide-react";
import { toast } from "sonner";
import IconPicker, { CategoryIcon } from "@/components/IconPicker";
import { getFileIcon, absoluteFileUrl } from "@/lib/fileIcons";
import ClientAccessSelector from "@/components/ClientAccessSelector";

const empty = {
  title: "", description: "", category: "documentation",
  file_id: null, file_url: null, file_type: null,
  body_html: "", client_id: "", is_public: false, cover_image_url: "",
  access_client_ids: [],
};

export default function AdminDocuments() {
  const [items, setItems] = useState([]);
  const [clients, setClients] = useState([]);
  const [categories, setCategories] = useState([]);
  const [isOpen, setIsOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(empty);
  const [uploading, setUploading] = useState(false);
  const [catManagerOpen, setCatManagerOpen] = useState(false);

  const load = () => apiClient.get("/admin/documents").then((r) => setItems(r.data));
  const loadCats = () => apiClient.get("/admin/document-categories").then((r) => setCategories(r.data));
  useEffect(() => {
    load().catch(() => {});
    loadCats().catch(() => {});
    // 2026-02 fork (bug fix) — Utilise `/me/access-clients-list` (permissif
    // aux admins ET tracked-Administrateur type support@) au lieu de
    // `/admin/clients` qui exigeait role=admin strict → liste vide pour support@.
    apiClient.get("/me/access-clients-list").then((r) => setClients(r.data));
  }, []);

  const open = (it = null) => {
    setEditing(it);
    setForm(it ? { ...empty, ...it, client_id: it.client_id || "", access_client_ids: Array.isArray(it.access_client_ids) ? it.access_client_ids : [] } : empty);
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
      setForm((prev) => ({
        ...prev,
        file_id: r.data.id,
        file_url: r.data.url,
        file_type: ft,
        filename: r.data.filename,
        file_extension: r.data.extension,
      }));
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

  const [logsFor, setLogsFor] = useState(null); // {document, logs}

  const openLogs = async (doc) => {
    try {
      const r = await apiClient.get("/admin/document-logs", { params: { file_id: doc.file_id } });
      setLogsFor({ document: doc, logs: r.data });
    } catch (err) { toast.error("Erreur chargement historique"); }
  };

  return (
    <div className="space-y-6" data-testid="admin-documents-page">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-display font-bold">Documents</h1>
          <p className="text-sm text-slate-500">Catalogue, documentation logiciels, annonces. Téléversement PDF/images/textes.</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setCatManagerOpen(true)}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white text-slate-700 hover:border-sawali-blue hover:text-sawali-blue px-3.5 py-2 text-sm"
            data-testid="manage-categories-btn"
            title="Gérer les catégories"
          >
            <Settings className="h-4 w-4" /> Catégories
          </button>
          <button onClick={() => open()} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light" data-testid="new-doc-btn">
            <Plus className="h-4 w-4" /> Nouveau document
          </button>
        </div>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.map((it) => {
          const fi = getFileIcon(it.file_extension || it.filename || it.file_url);
          const Icn = fi.icon;
          return (
          <div key={it.id} className="rounded-xl border border-slate-200 bg-white overflow-hidden" data-testid={`admin-doc-${it.id}`}>
            <div className="h-32 bg-slate-50 flex items-center justify-center relative">
              {it.cover_image_url ? <img src={it.cover_image_url} alt="" className="h-full w-full object-cover" /> :
                it.body_html && !it.file_url ? <Globe className="h-10 w-10 text-slate-400" /> :
                it.file_url ? (
                  <a
                    href={absoluteFileUrl(it.file_url)}
                    target="_blank"
                    rel="noopener"
                    download
                    title={`Télécharger ${it.filename || it.title}`}
                    className="flex flex-col items-center gap-1 hover:scale-110 transition-transform"
                    data-testid={`doc-download-${it.id}`}
                  >
                    <Icn className="h-12 w-12" color={fi.color} strokeWidth={1.6} />
                    {fi.ext && <span className="text-[10px] uppercase tracking-widest font-mono text-slate-500">.{fi.ext}</span>}
                  </a>
                ) : <FileText className="h-10 w-10 text-slate-400" />}
            </div>
            <div className="p-4">
              <div className="flex items-center gap-2 mb-1">
                {(() => {
                  const cat = categories.find((c) => c.slug === it.category);
                  return (
                    <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-widest" style={{ color: cat?.color || "#1E90FF" }}>
                      {cat && <CategoryIcon name={cat.icon} color={cat.color} className="h-3 w-3" />}
                      {cat?.label || it.category}
                    </span>
                  );
                })()}
                {it.is_public && <span className="text-[10px] bg-emerald-100 text-emerald-700 px-2 rounded">Public</span>}
              </div>
              <h3 className="font-display font-semibold text-sm truncate" title={it.title}>{it.title}</h3>
              <div className="mt-3 flex flex-wrap gap-3 text-xs">
                <button onClick={() => open(it)} className="text-sawali-blue hover:underline">Modifier</button>
                {it.file_url && (
                  <button onClick={() => openLogs(it)} className="inline-flex items-center gap-1 text-slate-600 hover:text-sawali-blue" data-testid={`doc-history-${it.id}`}>
                    <History className="h-3 w-3" /> Historique
                  </button>
                )}
                <button onClick={() => del(it.id)} className="text-rose-600 hover:underline ml-auto">Supprimer</button>
              </div>
            </div>
          </div>
          );
        })}
        {items.length === 0 && <p className="text-slate-500 col-span-full">Aucun document. Créez-en un.</p>}
      </div>

      {logsFor && <DocumentLogsModal data={logsFor} onClose={() => setLogsFor(null)} />}

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
                  <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="doc-category-select">
                    {categories.map((c) => (
                      <option key={c.id} value={c.slug}>{c.label}</option>
                    ))}
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
              <ClientAccessSelector
                value={form.access_client_ids || []}
                onChange={(ids) => setForm({ ...form, access_client_ids: ids })}
                label="Clients autorisés à voir ce document"
                testIdPrefix="doc-access-clients"
              />
              <button type="submit" className="w-full rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light">Enregistrer</button>
            </form>
          </div>
        </div>
      )}

      {catManagerOpen && (
        <CategoryManager
          categories={categories}
          onClose={() => setCatManagerOpen(false)}
          onChanged={async () => { await loadCats(); await load(); }}
        />
      )}
    </div>
  );
}

const DocumentLogsModal = ({ data, onClose }) => {
  const { document, logs } = data;
  const uploads = logs.filter((l) => l.event_type === "upload");
  const downloads = logs.filter((l) => l.event_type === "download");
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={onClose}>
      <div className="bg-white rounded-xl w-full max-w-3xl max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()} data-testid="doc-logs-modal">
        <div className="flex items-center justify-between p-4 border-b">
          <div>
            <h3 className="font-display font-semibold">Historique du document</h3>
            <p className="text-xs text-slate-500 truncate">{document.title}</p>
          </div>
          <button onClick={onClose}><X className="h-4 w-4" /></button>
        </div>
        <div className="p-4 space-y-5">
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg border border-slate-200 p-3">
              <p className="text-[10px] uppercase tracking-widest text-slate-500">Téléversements</p>
              <p className="text-2xl font-display font-bold">{uploads.length}</p>
            </div>
            <div className="rounded-lg border border-slate-200 p-3">
              <p className="text-[10px] uppercase tracking-widest text-slate-500">Téléchargements</p>
              <p className="text-2xl font-display font-bold">{downloads.length}</p>
            </div>
          </div>
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full text-xs min-w-[640px]">
              <thead className="bg-slate-50 text-[10px] uppercase tracking-widest text-slate-600">
                <tr>
                  <th className="text-left px-3 py-2">Type</th>
                  <th className="text-left px-3 py-2">Date</th>
                  <th className="text-left px-3 py-2">Utilisateur</th>
                  <th className="text-left px-3 py-2">IP</th>
                  <th className="text-left px-3 py-2">Durée</th>
                </tr>
              </thead>
              <tbody>
                {logs.length === 0 && <tr><td colSpan={5} className="px-3 py-6 text-center text-slate-500">Aucun événement.</td></tr>}
                {logs.map((l) => (
                  <tr key={l.id} className="border-t border-slate-100" data-testid={`log-${l.id}`}>
                    <td className="px-3 py-2">
                      <span className={`text-[10px] px-2 py-0.5 rounded uppercase tracking-wider ${l.event_type === "upload" ? "bg-emerald-100 text-emerald-700" : "bg-blue-100 text-blue-700"}`}>{l.event_type}</span>
                    </td>
                    <td className="px-3 py-2 text-slate-700">{new Date(l.created_at).toLocaleString("fr-FR")}</td>
                    <td className="px-3 py-2 text-slate-600">{l.user_email || <span className="text-slate-400">anonyme</span>}</td>
                    <td className="px-3 py-2 font-mono text-slate-500">{l.ip || "-"}</td>
                    <td className="px-3 py-2 text-slate-500">{l.duration_ms != null ? `${l.duration_ms} ms` : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
};

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

// ====================================================================
// Inline Category Manager
// ====================================================================
const CategoryManager = ({ categories, onClose, onChanged }) => {
  const [newLabel, setNewLabel] = useState("");
  const [newIcon, setNewIcon] = useState("FileText");
  const [newColor, setNewColor] = useState("#1E90FF");
  const [editingId, setEditingId] = useState(null);
  const [editLabel, setEditLabel] = useState("");
  const [editSlug, setEditSlug] = useState("");
  const [editIcon, setEditIcon] = useState("");
  const [editColor, setEditColor] = useState("");
  const [busy, setBusy] = useState(false);

  const add = async (e) => {
    e.preventDefault();
    if (!newLabel.trim()) return;
    setBusy(true);
    try {
      await apiClient.post("/admin/document-categories", { label: newLabel.trim(), icon: newIcon, color: newColor });
      toast.success("Catégorie ajoutée");
      setNewLabel(""); setNewIcon("FileText"); setNewColor("#1E90FF");
      await onChanged();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setBusy(false); }
  };

  const startEdit = (c) => {
    setEditingId(c.id); setEditLabel(c.label); setEditSlug(c.slug);
    setEditIcon(c.icon || "FileText"); setEditColor(c.color || "#1E90FF");
  };
  const cancelEdit = () => { setEditingId(null); setEditLabel(""); setEditSlug(""); setEditIcon(""); setEditColor(""); };

  const saveEdit = async () => {
    setBusy(true);
    try {
      await apiClient.put(`/admin/document-categories/${editingId}`, {
        label: editLabel.trim(), slug: editSlug.trim(), icon: editIcon, color: editColor,
      });
      toast.success("Catégorie mise à jour");
      cancelEdit();
      await onChanged();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setBusy(false); }
  };

  const remove = async (c) => {
    if (!window.confirm(`Supprimer "${c.label}" ?`)) return;
    setBusy(true);
    try {
      await apiClient.delete(`/admin/document-categories/${c.id}`);
      toast.success("Supprimée");
      await onChanged();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={onClose}>
      <div className="bg-white rounded-xl w-full max-w-lg max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b">
          <h3 className="font-display font-semibold">Catégories de documents</h3>
          <button onClick={onClose}><X className="h-4 w-4" /></button>
        </div>

        <div className="p-4 space-y-4">
          <p className="text-xs text-slate-500">
            Les catégories par défaut <strong>(Catalogue, Documentation, Annonce)</strong> ne peuvent pas être supprimées,
            mais leur libellé/icône reste éditable.
          </p>

          <form onSubmit={add} className="rounded-lg border border-slate-200 p-3 space-y-3 bg-slate-50/40">
            <div className="flex items-center gap-2">
              <CategoryIcon name={newIcon} color={newColor} className="h-5 w-5" />
              <input
                value={newLabel}
                onChange={(e) => setNewLabel(e.target.value)}
                placeholder="Nouvelle catégorie (ex. Procédure qualité)"
                className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-sawali-blue focus:outline-none"
                data-testid="new-category-input"
              />
              <button type="submit" disabled={busy || !newLabel.trim()} className="inline-flex items-center gap-1 rounded-lg bg-sawali-blue text-white px-3 py-2 text-sm hover:bg-sawali-blue-light disabled:opacity-50" data-testid="add-category-btn">
                <Plus className="h-4 w-4" /> Ajouter
              </button>
            </div>
            <IconPicker value={newIcon} color={newColor} onChange={setNewIcon} onColorChange={setNewColor} />
          </form>

          <div className="rounded-lg border border-slate-200 divide-y divide-slate-100">
            {categories.length === 0 && <p className="p-4 text-sm text-slate-500">Chargement...</p>}
            {categories.map((c) => (
              <div key={c.id} className="p-3" data-testid={`category-row-${c.id}`}>
                {editingId === c.id ? (
                  <div className="space-y-3">
                    <div className="flex items-center gap-2">
                      <CategoryIcon name={editIcon} color={editColor} className="h-5 w-5" />
                      <input value={editLabel} onChange={(e) => setEditLabel(e.target.value)} className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm" placeholder="Libellé" />
                      <input value={editSlug} onChange={(e) => setEditSlug(e.target.value.toLowerCase().replace(/\s+/g, "-"))} className="w-32 rounded border border-slate-300 px-2 py-1 text-sm font-mono" placeholder="slug" />
                      <button onClick={saveEdit} disabled={busy} className="text-emerald-600 hover:text-emerald-700"><Check className="h-4 w-4" /></button>
                      <button onClick={cancelEdit} className="text-slate-400 hover:text-slate-600"><X className="h-4 w-4" /></button>
                    </div>
                    <IconPicker value={editIcon} color={editColor} onChange={setEditIcon} onColorChange={setEditColor} />
                  </div>
                ) : (
                  <div className="flex items-center gap-3">
                    <span className="inline-flex items-center justify-center h-8 w-8 rounded-md flex-shrink-0" style={{ background: (c.color || "#1E90FF") + "20" }}>
                      <CategoryIcon name={c.icon} color={c.color} className="h-4 w-4" />
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">
                        {c.label}
                        {c.is_default && <span className="ml-2 text-[10px] uppercase tracking-wider text-slate-400 bg-slate-100 rounded px-1.5 py-0.5">défaut</span>}
                      </p>
                      <p className="text-xs text-slate-400 font-mono">{c.slug}</p>
                    </div>
                    <button onClick={() => startEdit(c)} className="text-slate-400 hover:text-sawali-blue" title="Modifier"><Edit2 className="h-4 w-4" /></button>
                    {!c.is_default && (
                      <button onClick={() => remove(c)} className="text-slate-400 hover:text-rose-600" title="Supprimer"><Trash2 className="h-4 w-4" /></button>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
