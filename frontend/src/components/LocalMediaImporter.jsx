/*
 * Iter43-fix24az-l retest (2026-02-26) — Composant réutilisable d'import local
 * de médias (image + vidéo) pour les AI Media Generators.
 *
 * Comportement :
 * - Sélection de fichier via bouton (déclenche <input type="file">)
 * - Preview local instantané (via URL.createObjectURL)
 * - Upload vers l'endpoint fourni (défaut /api/me/media-library)
 * - Toast success/error + spinner pendant l'upload
 * - Appelle onImported({ public_url, kind, id, filename, size, content_type })
 *   après upload réussi
 * - Validation basique (taille max, extension autorisée)
 *
 * Props :
 * - accept    : "image", "video", ou "both" (défaut: "both")
 * - maxSizeMb : Number (défaut: 50)
 * - label     : String — bouton label (défaut: "Importer un média local")
 * - onImported: (media) => void — callback après upload réussi
 * - autoLabel : Boolean — utilise le nom de fichier comme label (défaut: true)
 * - testIdPrefix : String — préfixe data-testid (défaut: "local-media-importer")
 * - endpoint  : String — endpoint POST relatif (défaut: "/me/media-library")
 * - fileField : String — nom du champ multipart (défaut: "file")
 * - labelField: String — nom du champ multipart pour le label (défaut: "label")
 * - extraFields : Object — champs multipart additionnels (défaut: {})
 * - normalizeResponse : (data, file) => media — transforme la réponse serveur
 *   avant onImported (défaut: passthrough)
 */
import React, { useMemo, useRef, useState } from "react";
import { apiClient } from "@/lib/api";
import { Upload, Loader2, X, Image as ImageIcon, Film } from "lucide-react";
import { toast } from "sonner";

const DEFAULT_MAX_MB = 50;

const ACCEPT_MAP = {
  image: "image/*",
  video: "video/*",
  both: "image/*,video/*",
};

function formatMb(bytes) {
  const mb = (Number(bytes) || 0) / (1024 * 1024);
  return `${mb.toFixed(2)} Mo`;
}

export function LocalMediaImporter({
  accept = "both",
  maxSizeMb = DEFAULT_MAX_MB,
  label = "Importer un média local",
  onImported,
  autoLabel = true,
  testIdPrefix = "local-media-importer",
  endpoint = "/me/media-library",
  fileField = "file",
  labelField = "label",
  extraFields = {},
  normalizeResponse,
}) {
  const inputRef = useRef(null);
  const [uploading, setUploading] = useState(false);
  const [preview, setPreview] = useState(null); // { url, kind, name, size }

  const acceptAttr = ACCEPT_MAP[accept] || ACCEPT_MAP.both;

  const inferKind = (file) => {
    const t = (file.type || "").toLowerCase();
    if (t.startsWith("image")) return "image";
    if (t.startsWith("video")) return "video";
    return "document";
  };

  const validate = (file) => {
    if (!file) return "Aucun fichier";
    const kind = inferKind(file);
    if (accept === "image" && kind !== "image") return "Seules les images sont acceptées";
    if (accept === "video" && kind !== "video") return "Seules les vidéos sont acceptées";
    if (accept === "both" && kind === "document") return "Formats acceptés : image ou vidéo";
    if (file.size > maxSizeMb * 1024 * 1024) return `Taille max ${maxSizeMb} Mo (fichier: ${formatMb(file.size)})`;
    return null;
  };

  const onFileChange = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const err = validate(file);
    if (err) {
      toast.error(err);
      if (inputRef.current) inputRef.current.value = "";
      return;
    }
    // Local preview
    const objUrl = URL.createObjectURL(file);
    const kind = inferKind(file);
    setPreview({ url: objUrl, kind, name: file.name, size: file.size });
    // Upload
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append(fileField, file);
      if (autoLabel && file.name && labelField) fd.append(labelField, file.name);
      // Champs multipart additionnels (title, tenant_id, etc.)
      Object.entries(extraFields || {}).forEach(([k, v]) => {
        if (v !== undefined && v !== null && v !== "") fd.append(k, String(v));
      });
      const r = await apiClient.post(endpoint, fd);
      const data = r.data || {};
      const media = typeof normalizeResponse === "function"
        ? normalizeResponse(data, file)
        : {
            public_url: data.public_url || data.url || null,
            kind: data.kind || kind,
            id: data.id,
            file_id: data.file_id,
            filename: data.filename || data.original_filename || file.name,
            size: data.size || data.file_size || file.size,
            content_type: data.content_type || file.type,
          };
      toast.success(`${kind === "video" ? "Vidéo" : "Image"} importée avec succès`);
      if (typeof onImported === "function") {
        onImported(media, data);
      }
    } catch (uploadErr) {
      toast.error(uploadErr?.response?.data?.detail || "Échec de l'import");
      setPreview(null);
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const clearPreview = () => {
    if (preview?.url) URL.revokeObjectURL(preview.url);
    setPreview(null);
  };

  const kindIcon = useMemo(() => {
    if (preview?.kind === "video") return <Film className="h-4 w-4" />;
    return <ImageIcon className="h-4 w-4" />;
  }, [preview]);

  return (
    <div className="space-y-2" data-testid={`${testIdPrefix}-root`}>
      <input
        type="file"
        accept={acceptAttr}
        onChange={onFileChange}
        ref={inputRef}
        className="hidden"
        data-testid={`${testIdPrefix}-input`}
      />
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={uploading}
          className="inline-flex items-center gap-2 text-sm px-3 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 disabled:opacity-50 text-slate-700"
          data-testid={`${testIdPrefix}-trigger`}
        >
          {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
          {uploading ? "Import en cours…" : label}
        </button>
        {preview && (
          <span className="inline-flex items-center gap-1.5 text-xs bg-violet-50 text-violet-700 px-2 py-1 rounded" data-testid={`${testIdPrefix}-badge`}>
            {kindIcon}
            <span className="truncate max-w-[160px]">{preview.name}</span>
            <span className="text-violet-500">{formatMb(preview.size)}</span>
            <button
              type="button"
              onClick={clearPreview}
              className="ml-1 hover:text-violet-900"
              aria-label="Retirer l'aperçu"
              data-testid={`${testIdPrefix}-clear`}
            >
              <X className="h-3 w-3" />
            </button>
          </span>
        )}
      </div>
      {preview && (
        <div className="rounded-lg overflow-hidden bg-slate-100 border border-slate-200 max-w-md" data-testid={`${testIdPrefix}-preview`}>
          {preview.kind === "video" ? (
            <video src={preview.url} controls className="w-full max-h-64" data-testid={`${testIdPrefix}-preview-video`} />
          ) : (
            <img src={preview.url} alt="Aperçu" className="w-full max-h-64 object-contain" data-testid={`${testIdPrefix}-preview-image`} />
          )}
        </div>
      )}
    </div>
  );
}

export default LocalMediaImporter;
