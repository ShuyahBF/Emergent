// S-iter39b — Internal PDF viewer with TOC navigation + full-text search.
// Download is hidden for non-admin/superviseur roles (canDownload prop).
// Uses react-pdf 9 (pdf.js 4) under the hood; worker is loaded from a CDN
// matching the bundled pdfjs-dist version.
import React, { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import {
  ChevronLeft, ChevronRight, ZoomIn, ZoomOut, Search, X, Download, BookOpen, Loader2,
} from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";

// pdf.js worker — fixed CDN URL matched to bundled version (4.8.69)
pdfjs.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

/**
 * Props:
 *  - src            : URL absolue du PDF
 *  - title          : titre affiché en en-tête
 *  - onClose        : optional callback (utilisé si embarqué dans un modal)
 *  - allowDownload  : override, sinon calculé via le rôle utilisateur
 */
export default function PdfViewer({ src, title = "Document PDF", onClose, allowDownload }) {
  const { user } = useAuth() || {};
  const role = (user?.role || "").toLowerCase();
  const tracked = (user?.tracked_role || "").toLowerCase();
  const isAdminOrSup =
    ["admin", "superviseur"].includes(role) || ["admin", "superviseur"].includes(tracked);
  const canDownload = allowDownload !== undefined ? allowDownload : isAdminOrSup;

  const [numPages, setNumPages] = useState(0);
  const [pageNumber, setPageNumber] = useState(1);
  const [scale, setScale] = useState(1.1);
  const [outline, setOutline] = useState([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [searchHits, setSearchHits] = useState([]);   // [{page, snippet}]
  const [searching, setSearching] = useState(false);
  const [activeHit, setActiveHit] = useState(-1);
  const [showOutline, setShowOutline] = useState(true);
  const pdfDocRef = useRef(null);
  const pageRef = useRef(null);

  const onDocLoadSuccess = useCallback(async (pdf) => {
    pdfDocRef.current = pdf;
    setNumPages(pdf.numPages);
    try {
      const ol = await pdf.getOutline();
      // Normalize { title, dest } recursively
      const flatten = async (items, depth = 0) => {
        const out = [];
        for (const it of items || []) {
          let page = null;
          try {
            const dest = typeof it.dest === "string"
              ? await pdf.getDestination(it.dest)
              : it.dest;
            if (Array.isArray(dest) && dest[0]) {
              const idx = await pdf.getPageIndex(dest[0]);
              page = idx + 1;
            }
          } catch { /* noop */ }
          out.push({ title: it.title, page, depth });
          if (it.items?.length) out.push(...(await flatten(it.items, depth + 1)));
        }
        return out;
      };
      setOutline(await flatten(ol || []));
    } catch {
      setOutline([]);
    }
  }, []);

  const runSearch = useCallback(async () => {
    const q = searchTerm.trim().toLowerCase();
    setActiveHit(-1);
    setSearchHits([]);
    if (!q || !pdfDocRef.current) return;
    setSearching(true);
    try {
      const hits = [];
      for (let p = 1; p <= pdfDocRef.current.numPages; p++) {
        const page = await pdfDocRef.current.getPage(p);
        const txt = await page.getTextContent();
        const str = txt.items.map((i) => i.str).join(" ").toLowerCase();
        let idx = str.indexOf(q);
        while (idx !== -1) {
          const start = Math.max(0, idx - 30);
          const end = Math.min(str.length, idx + q.length + 30);
          hits.push({ page: p, snippet: str.slice(start, end) });
          if (hits.length >= 200) break;
          idx = str.indexOf(q, idx + q.length);
        }
        if (hits.length >= 200) break;
      }
      setSearchHits(hits);
      if (hits.length > 0) {
        setPageNumber(hits[0].page);
        setActiveHit(0);
      }
    } finally {
      setSearching(false);
    }
  }, [searchTerm]);

  const goToHit = (i) => {
    if (i < 0 || i >= searchHits.length) return;
    setActiveHit(i);
    setPageNumber(searchHits[i].page);
  };

  const file = useMemo(() => ({ url: src }), [src]);

  // Disable native context menu + Ctrl/Cmd+S so non-admins can't save easily.
  useEffect(() => {
    if (canDownload) return;
    const onCtx = (e) => e.preventDefault();
    const onKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && (e.key === "s" || e.key === "S")) {
        e.preventDefault();
      }
    };
    document.addEventListener("contextmenu", onCtx);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("contextmenu", onCtx);
      document.removeEventListener("keydown", onKey);
    };
  }, [canDownload]);

  return (
    <div className="flex h-full w-full bg-slate-100" data-testid="pdf-viewer">
      {/* Sidebar: outline + search */}
      <aside
        className={`bg-white border-r border-slate-200 overflow-hidden transition-all ${showOutline ? "w-72" : "w-0"} flex flex-col`}
        data-testid="pdf-sidebar"
      >
        <div className="p-3 border-b border-slate-200 space-y-2">
          <div className="flex gap-1">
            <div className="relative flex-1">
              <Search className="h-3.5 w-3.5 absolute left-2 top-2.5 text-slate-400" />
              <input
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") runSearch(); }}
                placeholder="Rechercher…"
                className="w-full pl-7 pr-2 py-1.5 text-xs rounded ring-1 ring-slate-300 focus:ring-sawali-blue outline-none"
                data-testid="pdf-search-input"
              />
            </div>
            <button
              onClick={runSearch}
              disabled={searching || !searchTerm.trim()}
              className="px-2 rounded bg-sawali-blue text-white text-xs disabled:opacity-50"
              data-testid="pdf-search-button"
              title="Rechercher dans le PDF"
            >
              {searching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "OK"}
            </button>
          </div>
          {searchHits.length > 0 && (
            <div className="flex items-center justify-between text-[10px] text-slate-600">
              <span>{activeHit + 1} / {searchHits.length} occurrences</span>
              <div className="flex gap-0.5">
                <button onClick={() => goToHit(activeHit - 1)} disabled={activeHit <= 0} className="px-1 rounded hover:bg-slate-100 disabled:opacity-30"><ChevronLeft className="h-3 w-3" /></button>
                <button onClick={() => goToHit(activeHit + 1)} disabled={activeHit >= searchHits.length - 1} className="px-1 rounded hover:bg-slate-100 disabled:opacity-30"><ChevronRight className="h-3 w-3" /></button>
              </div>
            </div>
          )}
        </div>
        <div className="flex-1 overflow-y-auto p-2 text-xs">
          {searchHits.length > 0 ? (
            <div className="space-y-1" data-testid="pdf-search-hits">
              {searchHits.map((h, i) => (
                <button
                  key={`${h.page}-${i}`}
                  onClick={() => goToHit(i)}
                  className={`block w-full text-left p-1.5 rounded hover:bg-sky-50 ${i === activeHit ? "bg-sky-100 ring-1 ring-sky-300" : ""}`}
                  data-testid={`pdf-search-hit-${i}`}
                >
                  <span className="text-[10px] font-mono text-slate-500">p. {h.page}</span>
                  <p className="text-[11px] text-slate-700 leading-tight mt-0.5">…{h.snippet}…</p>
                </button>
              ))}
            </div>
          ) : outline.length > 0 ? (
            <div className="space-y-0.5" data-testid="pdf-outline">
              <p className="text-[10px] uppercase tracking-widest text-slate-400 font-semibold px-1 mb-1 inline-flex items-center gap-1"><BookOpen className="h-3 w-3" /> Sommaire</p>
              {outline.map((o, i) => (
                <button
                  key={i}
                  onClick={() => o.page && setPageNumber(o.page)}
                  disabled={!o.page}
                  className="block w-full text-left px-1.5 py-1 rounded hover:bg-sky-50 disabled:text-slate-400 truncate"
                  style={{ paddingLeft: 6 + (o.depth || 0) * 10 }}
                  title={o.title}
                  data-testid={`pdf-outline-${i}`}
                >
                  <span className="text-[11px] text-slate-700">{o.title}</span>
                  {o.page && <span className="text-[10px] font-mono text-slate-400 ml-1">p.{o.page}</span>}
                </button>
              ))}
            </div>
          ) : (
            <p className="text-[11px] text-slate-400 italic px-1 mt-2">Pas de sommaire ni de résultat de recherche.</p>
          )}
        </div>
      </aside>

      {/* Main: toolbar + page */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="px-3 py-2 border-b border-slate-200 bg-white flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2 min-w-0">
            <button onClick={() => setShowOutline((v) => !v)} className="px-2 py-1 rounded ring-1 ring-slate-200 hover:bg-slate-50 text-xs" data-testid="pdf-toggle-sidebar" title="Afficher/masquer le sommaire">
              <BookOpen className="h-3.5 w-3.5" />
            </button>
            <h2 className="text-sm font-display font-semibold truncate" title={title}>{title}</h2>
          </div>
          <div className="flex items-center gap-1">
            <button onClick={() => setPageNumber((p) => Math.max(1, p - 1))} disabled={pageNumber <= 1} className="px-2 py-1 rounded ring-1 ring-slate-200 hover:bg-slate-50 disabled:opacity-40" data-testid="pdf-prev"><ChevronLeft className="h-3.5 w-3.5" /></button>
            <span className="text-xs font-mono px-2" data-testid="pdf-page-indicator">{pageNumber} / {numPages || "—"}</span>
            <button onClick={() => setPageNumber((p) => Math.min(numPages, p + 1))} disabled={pageNumber >= numPages} className="px-2 py-1 rounded ring-1 ring-slate-200 hover:bg-slate-50 disabled:opacity-40" data-testid="pdf-next"><ChevronRight className="h-3.5 w-3.5" /></button>
            <div className="mx-1 h-4 w-px bg-slate-200" />
            <button onClick={() => setScale((s) => Math.max(0.5, s - 0.15))} className="px-2 py-1 rounded ring-1 ring-slate-200 hover:bg-slate-50" data-testid="pdf-zoom-out"><ZoomOut className="h-3.5 w-3.5" /></button>
            <span className="text-[10px] font-mono px-1 text-slate-500">{Math.round(scale * 100)}%</span>
            <button onClick={() => setScale((s) => Math.min(2.5, s + 0.15))} className="px-2 py-1 rounded ring-1 ring-slate-200 hover:bg-slate-50" data-testid="pdf-zoom-in"><ZoomIn className="h-3.5 w-3.5" /></button>
            {canDownload && (
              <a
                href={src}
                download
                target="_blank"
                rel="noopener noreferrer"
                className="ml-2 inline-flex items-center gap-1 px-2 py-1 rounded bg-sawali-blue text-white text-xs hover:opacity-90"
                data-testid="pdf-download-button"
                title="Télécharger le PDF (Admin/Superviseur)"
              >
                <Download className="h-3 w-3" /> Télécharger
              </a>
            )}
            {onClose && (
              <button onClick={onClose} className="ml-1 px-2 py-1 rounded text-slate-500 hover:bg-slate-100" data-testid="pdf-close"><X className="h-3.5 w-3.5" /></button>
            )}
          </div>
        </div>
        <div className="flex-1 overflow-auto p-4 flex justify-center" data-testid="pdf-page-area">
          <Document
            file={file}
            onLoadSuccess={onDocLoadSuccess}
            loading={<div className="text-sm text-slate-500 flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" /> Chargement du PDF…</div>}
            error={<div className="text-sm text-rose-600">Impossible de charger le PDF.</div>}
          >
            <div ref={pageRef} className="bg-white shadow-lg ring-1 ring-slate-200 inline-block" data-testid={`pdf-page-${pageNumber}`}>
              <Page pageNumber={pageNumber} scale={scale} />
            </div>
          </Document>
        </div>
        {!canDownload && (
          <div className="px-3 py-1.5 bg-amber-50 border-t border-amber-200 text-[11px] text-amber-800 text-center" data-testid="pdf-download-blocked">
            🔒 Lecture en ligne uniquement — le téléchargement est réservé aux rôles Admin / Superviseur.
          </div>
        )}
      </div>
    </div>
  );
}
