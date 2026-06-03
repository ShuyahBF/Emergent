// S-iter39p — Admin Media Library : upload PDF / video / image, edit
// metadata (title, description, public toggle, sort, tags), delete (soft).
// S040 (2026-02) — Replaced the window.prompt cascade with MediaUploadModal.
// Mounted on /admin/brochures alongside the existing static PDF builder.
import React, { useState, useCallback, useEffect } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  Upload, Trash2, Loader2, FileText, Video, ImageIcon, Eye, EyeOff,
  Edit2, Save, X,
} from "lucide-react";
import MediaUploadModal from "./MediaUploadModal";

const KIND_LABELS = { pdf: "PDF", video: "Vidéo", image: "Image" };

function KindIcon({ kind, className = "h-5 w-5" }) {
  const map = { pdf: FileText, video: Video, image: ImageIcon };
  const Icon = map[kind] || FileText;
  return <Icon className={className} />;
}

export default function AdminMediaLibrary() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [showModal, setShowModal] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/media-library");
      setItems(r.data?.items || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const upload = async ({ file, title, description, public: pub, tags }) => {
    setUploading(true);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("title", title);
    fd.append("description", description || "");
    fd.append("public", pub ? "true" : "false");
    fd.append("sort_order", "0");
    if (tags) fd.append("tags", tags);
    try {
      await apiClient.post("/admin/media-library", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success(`« ${title} » uploadé.`);
      refresh();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Upload échoué");
      throw err;
    } finally {
      setUploading(false);
    }
  };

  const remove = async (id, title) => {
    if (!window.confirm(`Supprimer « ${title} » ?`)) return;
    try {
      await apiClient.delete(`/admin/media-library/${id}`);
      toast.success("Supprimé");
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
  };

  const togglePublic = async (it) => {
    try {
      await apiClient.patch(`/admin/media-library/${it.id}`, { public: !it.public });
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
  };

  return (
    <section className="rounded-2xl ring-1 ring-slate-200 bg-white p-5 space-y-4" data-testid="admin-media-library">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-lg font-display font-bold text-slate-900">Bibliothèque médias</h2>
          <p className="text-xs text-slate-500 mt-0.5">PDF, vidéos et images partagés dans <em>Brochures &amp; Guides</em> du portail.</p>
        </div>
        <button
          type="button"
          onClick={() => setShowModal(true)}
          disabled={uploading}
          className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white text-sm disabled:opacity-60"
          data-testid="media-library-upload"
        >
          {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
          {uploading ? "Upload en cours…" : "Téléverser un média"}
        </button>
      </div>

      <MediaUploadModal
        open={showModal}
        onClose={() => setShowModal(false)}
        onSubmit={upload}
      />

      {loading && items.length === 0 && (
        <p className="text-xs text-slate-500 inline-flex items-center gap-1"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…</p>
      )}
      {items.length === 0 && !loading && (
        <p className="text-xs text-slate-400 italic py-6 text-center">Aucun média uploadé pour l'instant.</p>
      )}

      {items.length > 0 && (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3" data-testid="media-library-grid">
          {items.map((it) => (
            <MediaCard key={it.id} item={it} onDelete={() => remove(it.id, it.title)} onTogglePublic={() => togglePublic(it)} onRefresh={refresh} />
          ))}
        </div>
      )}
    </section>
  );
}

function MediaCard({ item, onDelete, onTogglePublic, onRefresh }) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(item.title || "");
  const [description, setDescription] = useState(item.description || "");

  const save = async () => {
    try {
      await apiClient.patch(`/admin/media-library/${item.id}`, { title, description });
      toast.success("Mis à jour");
      setEditing(false); onRefresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
  };

  return (
    <div className="rounded-xl ring-1 ring-slate-200 bg-white overflow-hidden flex flex-col" data-testid={`media-card-${item.id}`}>
      <div className="aspect-video bg-slate-100 flex items-center justify-center relative">
        {item.kind === "image" && item.url ? (
          <img src={item.url} alt={item.title} className="h-full w-full object-cover" />
        ) : item.kind === "video" && item.url ? (
          <video src={item.url} className="h-full w-full object-cover" muted preload="metadata" />
        ) : (
          <KindIcon kind={item.kind} className="h-12 w-12 text-slate-400" />
        )}
        <span className="absolute top-1.5 left-1.5 text-[10px] uppercase tracking-wider font-bold bg-white/80 text-slate-700 px-2 py-0.5 rounded ring-1 ring-slate-200">
          {KIND_LABELS[item.kind]}
        </span>
        <button onClick={onTogglePublic} className="absolute top-1.5 right-1.5 text-[10px] px-2 py-0.5 rounded ring-1 ring-slate-200 bg-white/80 inline-flex items-center gap-1" data-testid={`media-toggle-public-${item.id}`}>
          {item.public ? <><Eye className="h-3 w-3 text-emerald-600" /> Public</> : <><EyeOff className="h-3 w-3 text-slate-400" /> Privé</>}
        </button>
      </div>
      <div className="p-3 flex-1 flex flex-col">
        {editing ? (
          <>
            <input value={title} onChange={(e) => setTitle(e.target.value)} className="text-sm font-semibold rounded ring-1 ring-slate-300 px-2 py-1 mb-1" />
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} className="text-xs rounded ring-1 ring-slate-300 px-2 py-1" />
            <div className="flex gap-1 mt-2">
              <button onClick={save} className="text-[11px] inline-flex items-center gap-1 px-2 py-1 rounded bg-emerald-600 text-white"><Save className="h-3 w-3" /> Sauver</button>
              <button onClick={() => setEditing(false)} className="text-[11px] inline-flex items-center gap-1 px-2 py-1 rounded ring-1 ring-slate-300"><X className="h-3 w-3" /> Annuler</button>
            </div>
          </>
        ) : (
          <>
            <h3 className="text-sm font-semibold text-slate-800 truncate">{item.title}</h3>
            {item.description && <p className="text-xs text-slate-500 mt-1 line-clamp-2">{item.description}</p>}
            <p className="text-[10px] text-slate-400 mt-1">{Math.round((item.size || 0) / 1024)} Ko · {item.filename}</p>
            <div className="flex gap-1 mt-2">
              <button onClick={() => setEditing(true)} className="text-[11px] inline-flex items-center gap-1 px-2 py-1 rounded ring-1 ring-slate-300 hover:bg-slate-50" data-testid={`media-edit-${item.id}`}><Edit2 className="h-3 w-3" /> Modifier</button>
              <button onClick={onDelete} className="text-[11px] inline-flex items-center gap-1 px-2 py-1 rounded ring-1 ring-rose-300 text-rose-700 hover:bg-rose-50" data-testid={`media-delete-${item.id}`}><Trash2 className="h-3 w-3" /> Supprimer</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
