// S041 — Liluvine PRO chat message renderer.
// Detects Markdown image syntax `![alt](url)` and renders them as a
// numbered carousel below the text. The user can click an image to open
// it full-size in a new tab, or reply « C'est l'image n°2 » to refer to
// a specific picture.
import React, { useState } from "react";
import { X } from "lucide-react";

const IMG_RE = /!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g;

function parseMessage(text) {
  const images = [];
  const cleaned = (text || "").replace(IMG_RE, (_m, alt, url) => {
    images.push({ alt: (alt || "").trim(), url });
    return ""; // strip the markdown from the text body
  }).replace(/\n{3,}/g, "\n\n").trim();
  return { text: cleaned, images };
}

export default function LiluvineMessageContent({ content }) {
  const [zoomed, setZoomed] = useState(null);
  const { text, images } = parseMessage(content);
  return (
    <>
      {text && (
        <p className="whitespace-pre-wrap text-sm leading-relaxed" data-testid="liluvine-msg-text">{text}</p>
      )}
      {images.length > 0 && (
        <div className="mt-2 -mx-1" data-testid="liluvine-msg-carousel">
          <p className="text-[10px] text-slate-400 px-1 mb-1">
            {images.length === 1
              ? "🖼️ Voici une illustration —"
              : `🖼️ Voici ${images.length} illustrations — cliquez sur celle qui correspond à votre situation`}
          </p>
          <div className="flex gap-2 overflow-x-auto pb-1 px-1 snap-x">
            {images.map((img, idx) => (
              <button
                key={idx}
                onClick={() => setZoomed(img)}
                className="snap-start shrink-0 group relative rounded-lg overflow-hidden ring-1 ring-slate-200 hover:ring-2 hover:ring-fuchsia-500 transition focus:outline-none"
                data-testid={`liluvine-msg-image-${idx + 1}`}
                title={img.alt || `Image n°${idx + 1}`}
              >
                <img
                  src={img.url}
                  alt={img.alt || `Image ${idx + 1}`}
                  className="h-32 w-44 object-cover bg-slate-100"
                  loading="lazy"
                />
                <span className="absolute top-1 left-1 text-[10px] font-bold bg-fuchsia-600 text-white px-1.5 py-0.5 rounded-full ring-2 ring-white">
                  n°{idx + 1}
                </span>
                {img.alt && (
                  <span className="absolute bottom-0 inset-x-0 text-[9px] text-white bg-black/60 px-1 py-0.5 truncate">
                    {img.alt}
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Fullscreen zoom modal */}
      {zoomed && (
        <div
          className="fixed inset-0 z-[100] bg-black/90 flex items-center justify-center p-4"
          onClick={() => setZoomed(null)}
          data-testid="liluvine-msg-zoom"
        >
          <button
            onClick={(e) => { e.stopPropagation(); setZoomed(null); }}
            className="absolute top-4 right-4 text-white bg-white/10 hover:bg-white/20 rounded-full p-2"
            aria-label="Fermer"
          >
            <X className="h-5 w-5" />
          </button>
          <img
            src={zoomed.url}
            alt={zoomed.alt}
            className="max-h-full max-w-full object-contain"
            onClick={(e) => e.stopPropagation()}
          />
          {zoomed.alt && (
            <p className="absolute bottom-4 inset-x-4 text-center text-white text-sm">{zoomed.alt}</p>
          )}
        </div>
      )}
    </>
  );
}
