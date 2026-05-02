import React, { useState } from "react";
import { toast } from "sonner";
import { Copy, X, QrCode, Download, Globe, AlertCircle } from "lucide-react";

// Public form share modal — displays a QR code + shareable short URL.
// Uses api.qrserver.com (zero-dependency, publicly-available QR generator).
export default function ShareFormModal({ form, onClose }) {
  const [downloading, setDownloading] = useState(false);

  if (!form) return null;
  const shareUrl = `${window.location.origin}/f/${form.id}`;
  const qrUrl = `https://api.qrserver.com/v1/create-qr-code/?size=320x320&margin=8&data=${encodeURIComponent(shareUrl)}`;

  const copy = async () => {
    try { await navigator.clipboard.writeText(shareUrl); toast.success("Lien copié"); }
    catch { toast.error("Impossible de copier"); }
  };

  const downloadQr = async () => {
    setDownloading(true);
    try {
      const r = await fetch(qrUrl); const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `qr-${form.number || form.id}.png`; a.click();
      URL.revokeObjectURL(url);
    } catch { toast.error("Téléchargement impossible"); }
    finally { setDownloading(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40" onClick={(e) => e.target === e.currentTarget && onClose()} data-testid="share-form-modal">
      <div className="w-full max-w-md rounded-2xl bg-white shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200">
          <div className="flex items-center gap-2 min-w-0">
            <QrCode className="h-5 w-5 text-sawali-blue" />
            <h2 className="text-sm font-display font-bold truncate">Partager le formulaire</h2>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900" data-testid="share-modal-close"><X className="h-4 w-4" /></button>
        </div>

        <div className="p-5 space-y-4">
          {!form.is_public && (
            <div className="rounded-lg bg-amber-50 ring-1 ring-amber-200 p-3 text-xs text-amber-900 flex items-start gap-2">
              <AlertCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
              <div>
                Ce formulaire n'est pas marqué comme <strong>public</strong>. Activez le switch dans l'éditeur pour que le lien soit accessible sans compte.
              </div>
            </div>
          )}

          <div className="text-center">
            <img src={qrUrl} alt="QR Code" className="mx-auto rounded-lg ring-1 ring-slate-200" width={240} height={240} data-testid="share-qr-image" />
            <p className="text-[11px] text-slate-500 mt-2 inline-flex items-center gap-1"><Globe className="h-3 w-3" /> Scannez ou ouvrez le lien dans un navigateur</p>
          </div>

          <div>
            <label className="block text-[10px] uppercase tracking-[0.2em] text-slate-500 mb-1">Lien partageable</label>
            <div className="flex gap-2">
              <input readOnly value={shareUrl} className="flex-1 rounded-lg bg-slate-50 border border-slate-200 px-3 py-2 text-[12px] font-mono" onFocus={(e) => e.target.select()} data-testid="share-url-input" />
              <button onClick={copy} className="inline-flex items-center gap-1 rounded-lg bg-slate-900 text-white px-3 text-xs hover:bg-slate-800" data-testid="share-copy-btn"><Copy className="h-3.5 w-3.5" /> Copier</button>
            </div>
          </div>

          <div className="flex gap-2">
            <button onClick={downloadQr} disabled={downloading} className="inline-flex items-center gap-1.5 rounded-lg bg-sawali-blue hover:bg-sawali-blue-light text-white px-3 py-2 text-xs disabled:opacity-50" data-testid="share-download-qr"><Download className="h-3.5 w-3.5" /> {downloading ? "Téléchargement…" : "Télécharger le QR"}</button>
            <a href={shareUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-900 px-3 py-2 text-xs"><Globe className="h-3.5 w-3.5" /> Ouvrir le lien</a>
          </div>
        </div>
      </div>
    </div>
  );
}
