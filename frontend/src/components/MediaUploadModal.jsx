// S040 — Real upload modal for the Media Library (replaces the
// rudimentary window.prompt cascade). Shown by AdminMediaLibrary.
import React, { useState } from "react";
import { X, Loader2, Upload, FileText, Video, Image as ImageIcon } from "lucide-react";

function detectKind(file) {
  const ct = (file?.type || "").toLowerCase();
  if (ct === "application/pdf") return "pdf";
  if (ct.startsWith("video/")) return "video";
  if (ct.startsWith("image/")) return "image";
  return "other";
}

function KindBadge({ kind }) {
  const map = {
    pdf:   { label: "PDF",   icon: FileText,   color: "bg-rose-100 text-rose-700 ring-rose-200" },
    video: { label: "Vidéo", icon: Video,      color: "bg-violet-100 text-violet-700 ring-violet-200" },
    image: { label: "Image", icon: ImageIcon,  color: "bg-amber-100 text-amber-700 ring-amber-200" },
    other: { label: "Autre", icon: FileText,   color: "bg-slate-100 text-slate-700 ring-slate-200" },
  }[kind];
  const Icon = map.icon;
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full ring-1 font-semibold ${map.color}`}>
      <Icon className="h-3 w-3" /> {map.label}
    </span>
  );
}

export default function MediaUploadModal({ open, onClose, onSubmit }) {
  const [file, setFile] = useState(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [pub, setPub] = useState(true);
  const [tags, setTags] = useState("");
  const [busy, setBusy] = useState(false);

  if (!open) return null;
  const kind = detectKind(file);

  const close = () => {
    if (busy) return;
    setFile(null); setTitle(""); setDescription(""); setPub(true); setTags("");
    onClose?.();
  };

  const submit = async () => {
    if (!file) return;
    if (!title.trim()) return;
    setBusy(true);
    try {
      await onSubmit?.({ file, title: title.trim(), description: description.trim(), public: pub, tags });
      close();
    } finally { setBusy(false); }
  };

  return (
    <div
      className="fixed inset-0 z-[120] bg-slate-900/70 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={close}
      data-testid="media-upload-modal"
    >
      <div
        className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-gradient-to-br from-indigo-500 to-fuchsia-600 text-white grid place-items-center">
            <Upload className="h-5 w-5" />
          </div>
          <div className="flex-1">
            <h3 className="text-base font-bold text-slate-900">Téléverser un média</h3>
            <p className="text-xs text-slate-500">PDF, vidéo (mp4/webm) ou image (jpg/png/webp/gif)</p>
          </div>
          <button onClick={close} disabled={busy} className="p-1.5 rounded hover:bg-slate-100" data-testid="media-upload-modal-close">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">Fichier <span className="text-rose-500">*</span></label>
          <input
            type="file"
            accept="application/pdf,video/*,image/*"
            onChange={(e) => {
              const f = e.target.files?.[0] || null;
              setFile(f);
              if (f && !title) setTitle(f.name.replace(/\.[^.]+$/, ""));
            }}
            disabled={busy}
            className="block w-full text-sm"
            data-testid="media-upload-modal-file"
          />
          {file && (
            <p className="text-[11px] text-slate-500 mt-1 inline-flex items-center gap-2 flex-wrap">
              <KindBadge kind={kind} />
              <span>{file.name}</span>
              <span className="tabular-nums">· {Math.round(file.size / 1024)} Ko</span>
            </p>
          )}
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">Titre <span className="text-rose-500">*</span></label>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Ex: Guide utilisateur — Module Caisse"
            maxLength={200}
            disabled={busy}
            className="w-full rounded-lg ring-1 ring-slate-300 px-3 py-2 text-sm focus:ring-fuchsia-500 focus:ring-2 outline-none"
            data-testid="media-upload-modal-title"
            autoFocus
          />
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">Description (optionnelle)</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Brève description visible sur la carte du média côté portail."
            rows={3}
            maxLength={1000}
            disabled={busy}
            className="w-full rounded-lg ring-1 ring-slate-300 px-3 py-2 text-sm focus:ring-fuchsia-500 focus:ring-2 outline-none"
            data-testid="media-upload-modal-description"
          />
          <p className="text-[10px] text-slate-400 tabular-nums mt-0.5">{description.length} / 1000</p>
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">Tags (séparés par des virgules)</label>
          <input
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="ex: produit, tutoriel, caisse"
            disabled={busy}
            className="w-full rounded-lg ring-1 ring-slate-300 px-3 py-2 text-sm"
            data-testid="media-upload-modal-tags"
          />
        </div>

        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input
            type="checkbox"
            checked={pub}
            onChange={(e) => setPub(e.target.checked)}
            disabled={busy}
            className="h-4 w-4 rounded text-fuchsia-600 ring-1 ring-slate-300"
            data-testid="media-upload-modal-public"
          />
          <span>
            Visible publiquement sur le portail <span className="text-[11px] text-slate-500">(/portal/brochures)</span>
          </span>
        </label>

        <div className="flex gap-2 justify-end pt-2 border-t border-slate-100">
          <button
            onClick={close}
            disabled={busy}
            className="text-sm px-3 py-2 rounded-lg ring-1 ring-slate-300 text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            data-testid="media-upload-modal-cancel"
          >
            Annuler
          </button>
          <button
            onClick={submit}
            disabled={busy || !file || !title.trim()}
            className="text-sm px-4 py-2 rounded-lg bg-gradient-to-r from-indigo-600 to-fuchsia-600 text-white shadow-md hover:from-indigo-700 hover:to-fuchsia-700 disabled:opacity-50 inline-flex items-center gap-1.5"
            data-testid="media-upload-modal-submit"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            {busy ? "Upload en cours…" : "Téléverser"}
          </button>
        </div>
      </div>
    </div>
  );
}
