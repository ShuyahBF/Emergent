import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { FileText, Download, ImageIcon, Layers } from "lucide-react";

export default function Catalogue() {
  const [items, setItems] = useState([]);
  useEffect(() => {
    apiClient.get("/catalog").then((r) => setItems(r.data)).catch(() => {});
  }, []);
  return (
    <section className="py-20" data-testid="catalogue-page">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <p className="text-xs uppercase tracking-[0.25em] text-sawali-blue-light">Nos solutions</p>
        <h1 className="mt-3 text-4xl sm:text-5xl font-display font-bold text-white">Catalogue</h1>
        <p className="mt-4 text-slate-300 max-w-2xl">
          Téléchargez nos brochures et fiches produits. De nouveaux contenus seront ajoutés régulièrement par notre équipe.
        </p>

        {items.length === 0 ? (
          <div className="mt-12 rounded-xl border border-dashed border-white/10 p-16 text-center text-slate-400" data-testid="catalog-empty">
            <Layers className="h-10 w-10 mx-auto text-sawali-blue-light/60" />
            <p className="mt-3">Le catalogue sera bientôt disponible. Revenez prochainement.</p>
          </div>
        ) : (
          <div className="mt-12 grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {items.map((it) => (
              <article key={it.id} className="glow-card rounded-xl overflow-hidden" data-testid={`catalog-item-${it.id}`}>
                {it.cover_image_url ? (
                  <img src={it.cover_image_url} alt={it.title} className="h-44 w-full object-cover" />
                ) : (
                  <div className="h-44 w-full bg-gradient-to-br from-sawali-navy to-sawali-navy-dark flex items-center justify-center">
                    {it.file_type === "image" ? <ImageIcon className="h-10 w-10 text-sawali-blue-light/70" /> : <FileText className="h-10 w-10 text-sawali-blue-light/70" />}
                  </div>
                )}
                <div className="p-5">
                  <h3 className="font-display font-semibold text-white">{it.title}</h3>
                  {it.description && <p className="mt-1 text-sm text-slate-400 line-clamp-3">{it.description}</p>}
                  <div className="mt-4 flex items-center gap-3">
                    {it.file_url && (
                      <a
                        href={`${process.env.REACT_APP_BACKEND_URL}${it.file_url}`}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-2 text-sm text-sawali-blue-light hover:text-white"
                        data-testid={`catalog-download-${it.id}`}
                      >
                        <Download className="h-4 w-4" /> Télécharger
                      </a>
                    )}
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
