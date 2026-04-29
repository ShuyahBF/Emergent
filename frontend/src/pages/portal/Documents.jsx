import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { FileText, Download, Eye, Globe } from "lucide-react";
import { getFileIcon, absoluteFileUrl } from "@/lib/fileIcons";

export default function ClientDocuments() {
  const [items, setItems] = useState([]);
  const [active, setActive] = useState(null);
  useEffect(() => { apiClient.get("/me/documents").then((r) => setItems(r.data)).catch(() => {}); }, []);

  const url = (it) => it.file_url ? absoluteFileUrl(it.file_url) : null;

  return (
    <div className="space-y-6" data-testid="client-documents-page">
      <div>
        <h1 className="text-2xl font-display font-bold">Documentation des logiciels</h1>
        <p className="text-sm text-slate-500">Manuels, fiches techniques et annonces qui vous concernent. Cliquez sur l'icône pour télécharger.</p>
      </div>

      {items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 p-12 text-center text-slate-500">
          Aucun document disponible pour le moment.
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {items.map((it) => {
            const fi = getFileIcon(it.file_url || it.filename);
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
                  <div className="mt-3 flex items-center gap-3">
                    {fileUrl && (
                      <a href={fileUrl} target="_blank" rel="noreferrer" download className="text-xs inline-flex items-center gap-1 text-sawali-blue hover:underline" data-testid={`doc-download-${it.id}`}>
                        <Download className="h-3.5 w-3.5" /> Télécharger
                      </a>
                    )}
                    {(it.body_html || fileUrl) && (
                      <button onClick={() => setActive(it)} className="text-xs inline-flex items-center gap-1 text-slate-600 hover:text-sawali-blue" data-testid={`doc-view-${it.id}`}>
                        <Eye className="h-3.5 w-3.5" /> Visualiser
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {active && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={() => setActive(null)}>
          <div className="bg-white rounded-xl max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="font-display font-semibold">{active.title}</h3>
              <button onClick={() => setActive(null)} className="text-slate-500 hover:text-slate-900">✕</button>
            </div>
            <div className="flex-1 overflow-auto">
              {active.body_html ? (
                <div className="p-6 prose-sawali" dangerouslySetInnerHTML={{ __html: active.body_html }} />
              ) : url(active) && active.file_type === "image" ? (
                <img src={url(active)} alt={active.title} className="w-full" />
              ) : url(active) ? (
                <iframe src={url(active)} title={active.title} className="w-full h-[80vh]" />
              ) : null}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
