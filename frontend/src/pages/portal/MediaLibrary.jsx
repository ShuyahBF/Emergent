import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  Image as ImageIcon, FileText as FileTextIcon, Video, Upload, Trash2,
  RefreshCw, Copy, Search, FolderOpen,
} from "lucide-react";

/*
  Portal → Bibliothèque de médias partagée par client.
  All users of the same client see the same library.
  Used to attach images/PDFs as headers in WhatsApp templates.
*/
const KIND_LABELS = { image: "Images", document: "Documents", video: "Vidéos" };

export default function MediaLibrary() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [filter, setFilter] = useState("");
  const [kindFilter, setKindFilter] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/me/media-library");
      setItems(r.data || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const upload = async (file) => {
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("label", file.name || "");
      await apiClient.post("/me/media-library", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success("Média ajouté");
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec de l'upload");
    } finally {
      setUploading(false);
    }
  };

  const del = async (id) => {
    if (!window.confirm("Supprimer ce média de la bibliothèque ?")) return;
    try {
      await apiClient.delete(`/me/media-library/${id}`);
      toast.success("Supprimé");
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const copyUrl = async (url) => {
    try {
      await navigator.clipboard.writeText(url);
      toast.success("URL copiée");
    } catch {
      toast.error("Copie impossible");
    }
  };

  const filtered = items.filter((m) => {
    if (kindFilter && m.kind !== kindFilter) return false;
    if (!filter.trim()) return true;
    const q = filter.toLowerCase();
    return [m.label, m.filename, m.uploaded_by_label].some((v) => (v || "").toLowerCase().includes(q));
  });

  const sizeLabel = (b) => {
    const n = Number(b || 0);
    if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} Mo`;
    if (n >= 1024) return `${Math.round(n / 1024)} Ko`;
    return `${n} o`;
  };

  return (
    <div className="space-y-6" data-testid="media-library-page">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Banque partagée</p>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2">
            <FolderOpen className="h-5 w-5 text-sawali-blue" /> Bibliothèque de médias
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Images, documents PDF et vidéos partagés entre tous les utilisateurs de votre client.
            Utilisés comme pièces jointes pour les templates WhatsApp (en-tête).
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={load}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 px-3 py-2 text-sm disabled:opacity-60"
            data-testid="media-refresh"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Actualiser
          </button>
          <label className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light cursor-pointer" data-testid="media-upload-btn">
            <Upload className="h-4 w-4" /> {uploading ? "Upload…" : "Ajouter un média"}
            <input
              type="file"
              accept="image/*,video/*,.pdf,application/pdf"
              onChange={(e) => upload(e.target.files?.[0])}
              className="hidden"
              data-testid="media-upload-input"
            />
          </label>
        </div>
      </div>

      <div className="flex gap-2 items-center flex-wrap">
        <div className="relative flex-1 min-w-[220px]">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Rechercher par nom, fichier, auteur…"
            className="w-full rounded-lg border border-slate-300 pl-8 pr-3 py-2 text-sm"
            data-testid="media-search"
          />
        </div>
        <select
          value={kindFilter}
          onChange={(e) => setKindFilter(e.target.value)}
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm bg-white"
          data-testid="media-kind-filter"
        >
          <option value="">Tous les formats</option>
          <option value="image">Images</option>
          <option value="document">Documents (PDF)</option>
          <option value="video">Vidéos</option>
        </select>
        <span className="text-xs text-slate-500">{filtered.length} média(s)</span>
      </div>

      {loading ? (
        <div className="text-center text-slate-500 py-10">Chargement…</div>
      ) : filtered.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 p-12 text-center">
          <FolderOpen className="h-10 w-10 text-slate-300 mx-auto mb-2" />
          <p className="text-slate-500 text-sm">Aucun média. Cliquez sur <strong>Ajouter un média</strong> pour démarrer.</p>
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {filtered.map((m) => {
            const Icn = m.kind === "image" ? ImageIcon : m.kind === "video" ? Video : FileTextIcon;
            return (
              <div key={m.id} className="rounded-xl border border-slate-200 bg-white overflow-hidden flex flex-col" data-testid={`media-card-${m.id}`}>
                <a href={m.public_url} target="_blank" rel="noreferrer" className="h-36 bg-slate-100 flex items-center justify-center hover:opacity-90 transition">
                  {m.kind === "image" ? (
                    <img src={m.public_url} alt={m.label || m.filename} className="h-full w-full object-cover" />
                  ) : (
                    <Icn className="h-10 w-10 text-slate-400" />
                  )}
                </a>
                <div className="p-3 flex-1 flex flex-col">
                  <p className="text-sm font-medium text-slate-800 truncate" title={m.label || m.filename}>
                    {m.label || m.filename}
                  </p>
                  <p className="text-[11px] text-slate-500">
                    {KIND_LABELS[m.kind] || m.kind} · {sizeLabel(m.size)} · .{m.extension}
                  </p>
                  <p className="text-[10px] text-slate-400 mt-1">
                    Par {m.uploaded_by_label || "—"} le {new Date(m.created_at).toLocaleDateString("fr-FR")}
                  </p>
                  <div className="mt-auto pt-2 flex items-center gap-2 text-[11px]">
                    <button onClick={() => copyUrl(m.public_url)} className="inline-flex items-center gap-1 text-slate-600 hover:text-sawali-blue" data-testid={`media-copy-${m.id}`} title="Copier l'URL publique">
                      <Copy className="h-3 w-3" /> URL
                    </button>
                    <a href={m.public_url} download className="inline-flex items-center gap-1 text-slate-600 hover:text-sawali-blue" data-testid={`media-download-${m.id}`}>
                      <FileTextIcon className="h-3 w-3" /> Télécharger
                    </a>
                    <button onClick={() => del(m.id)} className="ml-auto text-rose-500 hover:text-rose-700" data-testid={`media-delete-${m.id}`}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
