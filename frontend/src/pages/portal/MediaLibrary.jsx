import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
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
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [filter, setFilter] = useState("");
  const [kindFilter, setKindFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState(""); // Iter35n — "" | "whatsapp_inbound"
  const [clients, setClients] = useState([]);
  const [targetClientId, setTargetClientId] = useState("");
  // Iter35n — WhatsApp media cleanup state
  const [cleanup, setCleanup] = useState(null); // {to_delete, examined} after dry-run
  const [cleaning, setCleaning] = useState(false);

  const isElevated = user?.role === "admin" || user?.role === "superviseur";

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/me/media-library", {
        params: sourceFilter ? { source: sourceFilter } : {},
      });
      setItems(r.data || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    load();
    if (isAdmin) {
      apiClient.get("/me/clients-roster").then((r) => setClients(r.data || [])).catch(() => {});
    }
    // eslint-disable-next-line
  }, [isAdmin, sourceFilter]);

  // Iter35n — WhatsApp media cleanup (admin/superviseur)
  const previewCleanup = async () => {
    setCleaning(true);
    try {
      const r = await apiClient.post("/me/media-library/wa-cleanup?dry_run=true");
      setCleanup(r.data);
      if (!r.data?.to_delete?.length) {
        toast.info("Aucun média WhatsApp inutilisé à supprimer.");
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setCleaning(false);
    }
  };
  const confirmCleanup = async () => {
    if (!cleanup?.to_delete?.length) return;
    if (!window.confirm(`Supprimer définitivement ${cleanup.to_delete.length} média(s) WhatsApp inutilisé(s) ?`)) return;
    setCleaning(true);
    try {
      const r = await apiClient.post("/me/media-library/wa-cleanup?dry_run=false");
      toast.success(`${r.data?.deleted || 0} média(s) supprimé(s)`);
      setCleanup(null);
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setCleaning(false);
    }
  };

  const upload = async (file) => {
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("label", file.name || "");
      // Admin: optionally attach to a specific client's library so the upload is
      // visible to all users of that client (and not only to the admin).
      if (isAdmin && targetClientId) fd.append("target_client_id", targetClientId);
      await apiClient.post("/me/media-library", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success(isAdmin && targetClientId ? "Média ajouté pour le client sélectionné" : "Média ajouté");
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
          {isAdmin && (
            <select
              value={targetClientId}
              onChange={(e) => setTargetClientId(e.target.value)}
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm min-w-[200px]"
              title="Cible le client à qui ce média sera attaché"
              data-testid="media-target-client"
            >
              <option value="">Pour mon espace (admin)</option>
              {clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.client_code ? `${c.client_code} — ` : ""}{c.company || c.full_name}
                </option>
              ))}
            </select>
          )}
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
        {/* Iter35n — Source filter (WhatsApp re-saved vs all) */}
        <div className="inline-flex rounded-lg ring-1 ring-slate-300 bg-slate-50 p-0.5" data-testid="media-source-filter">
          <button
            onClick={() => setSourceFilter("")}
            className={`text-xs px-2.5 py-1 rounded-md transition ${sourceFilter === "" ? "bg-sawali-blue text-white shadow-sm" : "text-slate-600 hover:bg-white"}`}
            data-testid="media-source-all"
          >
            Tous
          </button>
          <button
            onClick={() => setSourceFilter("whatsapp_inbound")}
            className={`text-xs px-2.5 py-1 rounded-md transition ${sourceFilter === "whatsapp_inbound" ? "bg-emerald-600 text-white shadow-sm" : "text-slate-600 hover:bg-white"}`}
            data-testid="media-source-wa"
            title="Images sauvegardées depuis le chat WhatsApp"
          >
            WhatsApp
          </button>
        </div>
        <span className="text-xs text-slate-500">{filtered.length} média(s)</span>
        {/* Iter35n — Cleanup unused WA media (admin / superviseur) */}
        {isElevated && sourceFilter === "whatsapp_inbound" && (
          <div className="ml-auto flex items-center gap-2" data-testid="media-cleanup-wrapper">
            {!cleanup ? (
              <button
                onClick={previewCleanup}
                disabled={cleaning}
                className="inline-flex items-center gap-1 rounded-lg border border-amber-300 bg-amber-50 hover:bg-amber-100 px-2.5 py-1.5 text-xs text-amber-900 disabled:opacity-50"
                data-testid="media-cleanup-preview"
                title="Aperçu des médias WA non référencés (rapports/suivis/notes)"
              >
                <Trash2 className="h-3.5 w-3.5" /> Nettoyer les inutilisés
              </button>
            ) : (
              <>
                <span className="text-xs text-amber-900 bg-amber-50 ring-1 ring-amber-200 rounded px-2 py-1">
                  {cleanup.to_delete?.length || 0} / {cleanup.examined} à supprimer
                </span>
                <button
                  onClick={() => setCleanup(null)}
                  className="text-xs text-slate-600 hover:underline"
                  data-testid="media-cleanup-cancel"
                >
                  Annuler
                </button>
                <button
                  onClick={confirmCleanup}
                  disabled={cleaning || !cleanup.to_delete?.length}
                  className="inline-flex items-center gap-1 rounded-lg bg-rose-600 text-white hover:bg-rose-700 px-2.5 py-1.5 text-xs disabled:opacity-40"
                  data-testid="media-cleanup-confirm"
                >
                  <Trash2 className="h-3.5 w-3.5" /> Confirmer
                </button>
              </>
            )}
          </div>
        )}
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
