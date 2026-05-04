import React, { useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api";
import { FileText, Download, Eye, Globe, Plus, X, Upload, Trash2, RefreshCw } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { getFileIcon, absoluteFileUrl } from "@/lib/fileIcons";
import { toast } from "sonner";

const ELEVATED = new Set(["Moderation", "Administrateur", "Superviseur"]);
const ADMIN_LEVEL = new Set(["Administrateur", "Superviseur"]);
function isElevated(user) {
  if (!user) return false;
  if (user.role === "admin" || user.role === "superviseur") return true;
  return ELEVATED.has(user.tracked_role);
}
function canDelete(user) {
  if (!user) return false;
  if (user.role === "admin" || user.role === "superviseur") return true;
  return ADMIN_LEVEL.has(user.tracked_role);
}

const CATEGORIES = [
  { value: "documentation", label: "Documentation" },
  { value: "catalog", label: "Catalogue" },
  { value: "announcement", label: "Annonce" },
];

export default function ClientDocuments() {
  const { user } = useAuth();
  const [items, setItems] = useState([]);
  const [active, setActive] = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/me/documents");
      setItems(r.data || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const del = async (id) => {
    if (!window.confirm("Supprimer ce document ?")) return;
    try {
      await apiClient.delete(`/me/documents/${id}`);
      toast.success("Document supprimé");
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const url = (it) => it.file_url ? absoluteFileUrl(it.file_url) : null;
  const elevated = isElevated(user);
  const deletable = canDelete(user);

  return (
    <div className="space-y-6" data-testid="client-documents-page">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-display font-bold">Documentation des logiciels</h1>
          <p className="text-sm text-slate-500">Manuels, fiches techniques et annonces qui vous concernent. Cliquez sur l'icône pour télécharger.</p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={load}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 px-3 py-2 text-sm disabled:opacity-60"
            data-testid="documents-refresh"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Actualiser
          </button>
          {elevated && (
            <button
              onClick={() => setShowCreate(true)}
              className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light"
              data-testid="documents-create-btn"
            >
              <Plus className="h-4 w-4" /> Nouveau document
            </button>
          )}
        </div>
      </div>

      {loading ? (
        <div className="text-center text-slate-500 py-10">Chargement…</div>
      ) : items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 p-12 text-center text-slate-500">
          Aucun document disponible pour le moment.
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {items.map((it) => {
            const fi = getFileIcon(it.file_extension || it.filename || it.file_url);
            const Icn = fi.icon;
            const fileUrl = url(it);
            return (
              <div key={it.id} className="rounded-xl border border-slate-200 bg-white overflow-hidden" data-testid={`doc-card-${it.id}`}>
                <div className="h-36 bg-gradient-to-br from-sawali-navy to-sawali-navy-dark flex items-center justify-center">
                  {it.cover_image_url ? <img src={it.cover_image_url} alt="" className="h-full w-full object-cover" /> :
                    it.body_html && !fileUrl ? <Globe className="h-10 w-10 text-sawali-blue-light/70" /> :
                    fileUrl ? (
                      <a
                        href={fileUrl}
                        target="_blank"
                        rel="noreferrer"
                        download
                        title={`Télécharger ${it.filename || it.title}`}
                        className="flex flex-col items-center gap-1 hover:scale-110 transition-transform"
                        data-testid={`doc-icon-${it.id}`}
                      >
                        <Icn className="h-12 w-12" color={fi.color} strokeWidth={1.6} />
                        {fi.ext && <span className="text-[10px] uppercase tracking-widest font-mono text-sawali-blue-light/70">.{fi.ext}</span>}
                      </a>
                    ) : <FileText className="h-10 w-10 text-sawali-blue-light/70" />}
                </div>
                <div className="p-4">
                  <h3 className="font-display font-semibold">{it.title}</h3>
                  {it.description && <p className="text-xs text-slate-500 mt-1 line-clamp-2">{it.description}</p>}
                  <div className="mt-3 flex items-center gap-3 flex-wrap">
                    {fileUrl && (
                      <a href={fileUrl} target="_blank" rel="noreferrer" download className="text-xs inline-flex items-center gap-1 text-sawali-blue hover:underline" data-testid={`doc-download-${it.id}`}>
                        <Download className="h-3.5 w-3.5" /> Télécharger
                      </a>
                    )}
                    {(it.body_html || fileUrl) && (
                      <button onClick={() => setActive(it)} className="text-xs inline-flex items-center gap-1 text-slate-600 hover:text-sawali-blue" data-testid={`doc-view-${it.id}`}>
                        <Eye className="h-3.5 w-3.5" /> Aperçu
                      </button>
                    )}
                    {deletable && (
                      <button
                        onClick={() => del(it.id)}
                        className="ml-auto text-xs inline-flex items-center gap-1 text-rose-600 hover:underline"
                        data-testid={`doc-delete-${it.id}`}
                      >
                        <Trash2 className="h-3.5 w-3.5" /> Supprimer
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {active && <PreviewModal it={active} onClose={() => setActive(null)} />}
      {showCreate && (
        <CreateDocumentModal
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); load(); }}
        />
      )}
    </div>
  );
}

const PreviewModal = ({ it, onClose }) => (
  <div
    className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60"
    onClick={(e) => e.target === e.currentTarget && onClose()}
    data-testid="doc-preview-modal"
  >
    <div className="w-full max-w-4xl max-h-[90vh] bg-white rounded-2xl shadow-2xl flex flex-col">
      <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200">
        <h3 className="font-display font-semibold">{it.title}</h3>
        <button onClick={onClose} className="text-slate-500 hover:text-slate-900"><X className="h-4 w-4" /></button>
      </div>
      <div className="flex-1 overflow-auto p-5">
        {it.body_html ? <div className="prose max-w-none" dangerouslySetInnerHTML={{ __html: it.body_html }} /> : null}
        {it.file_url && (
          <iframe src={absoluteFileUrl(it.file_url)} title={it.title} className="w-full h-[70vh] rounded border border-slate-200" />
        )}
      </div>
    </div>
  </div>
);

const CreateDocumentModal = ({ onClose, onCreated }) => {
  const [form, setForm] = useState({ title: "", description: "", category: "documentation" });
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const inputRef = useRef(null);

  const submit = async () => {
    if (!form.title.trim()) { toast.error("Le titre est requis"); return; }
    setUploading(true);
    try {
      let fileMeta = {};
      if (file) {
        const fd = new FormData();
        fd.append("file", file);
        const upRes = await apiClient.post("/me/upload", fd, {
          headers: { "Content-Type": "multipart/form-data" },
          onUploadProgress: (e) => setProgress(Math.round((e.loaded * 100) / (e.total || 1))),
        });
        fileMeta = {
          file_id: upRes.data.id,
          file_url: upRes.data.url,
          filename: upRes.data.filename,
          file_extension: upRes.data.extension,
          file_type: (upRes.data.content_type || "").startsWith("image") ? "image" : (upRes.data.extension === "pdf" ? "pdf" : "file"),
        };
      }
      await apiClient.post("/me/documents", { ...form, ...fileMeta });
      toast.success("Document créé");
      onCreated();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur lors de la création");
    } finally {
      setUploading(false);
      setProgress(0);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      data-testid="doc-create-modal"
    >
      <div className="w-full max-w-lg rounded-2xl bg-white shadow-2xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-display font-bold">Nouveau document</h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900" data-testid="doc-create-close"><X className="h-4 w-4" /></button>
        </div>
        <div>
          <label className="block text-xs font-semibold mb-1">Titre *</label>
          <input
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            placeholder="Manuel d'utilisation v2.3"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            data-testid="doc-field-title"
          />
        </div>
        <div>
          <label className="block text-xs font-semibold mb-1">Description</label>
          <textarea
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            rows={3}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            data-testid="doc-field-description"
          />
        </div>
        <div>
          <label className="block text-xs font-semibold mb-1">Catégorie</label>
          <select
            value={form.category}
            onChange={(e) => setForm({ ...form, category: e.target.value })}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            data-testid="doc-field-category"
          >
            {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-semibold mb-1">Fichier (PDF, image, docx, xlsx, pptx, txt…)</label>
          <input
            ref={inputRef}
            type="file"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="w-full text-xs"
            data-testid="doc-field-file"
          />
          {file && <p className="text-[11px] text-slate-500 mt-1">Sélectionné : {file.name} ({Math.round(file.size / 1024)} Ko)</p>}
          {uploading && progress > 0 && (
            <div className="mt-2 h-1.5 bg-slate-200 rounded overflow-hidden">
              <div className="h-full bg-sawali-blue" style={{ width: `${progress}%` }} />
            </div>
          )}
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="text-sm rounded-lg bg-slate-100 hover:bg-slate-200 px-4 py-2">Annuler</button>
          <button
            onClick={submit}
            disabled={uploading}
            className="inline-flex items-center gap-1.5 text-sm rounded-lg bg-sawali-blue hover:bg-sawali-blue-light text-white px-4 py-2 disabled:opacity-50"
            data-testid="doc-create-save"
          >
            <Upload className="h-4 w-4" /> {uploading ? "Envoi…" : "Créer"}
          </button>
        </div>
      </div>
    </div>
  );
};
