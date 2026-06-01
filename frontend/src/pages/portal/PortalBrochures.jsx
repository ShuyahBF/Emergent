// S-iter39b — Portal page that lists Brochures & Guides and opens them
// inline in the internal PDF viewer (modérateurs lecture seule).
import React, { useEffect, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { FileText, BookOpen, ChevronLeft } from "lucide-react";
import PdfViewer from "@/components/PdfViewer";
import { useAuth } from "@/contexts/AuthContext";
import DownloadGate, { useDownloadGate } from "@/components/DownloadGate";

const META = {
  "guide-utilisateur": { title: "Guide Utilisateur", color: "from-sky-500 to-blue-600" },
  "brochure-presentation": { title: "Brochure de présentation", color: "from-fuchsia-500 to-pink-600" },
  "brochure-fonctionnalites": { title: "Grandes fonctionnalités", color: "from-emerald-500 to-teal-600" },
  // S-iter39e — Référence technique AdminSettings
  "admin-settings-reference": { title: "Référence technique — AdminSettings", color: "from-violet-500 to-indigo-600" },
};

export default function PortalBrochures() {
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const src = params.get("src");
  const title = params.get("title") || "Document PDF";
  const { user } = useAuth() || {};
  const role = (user?.role || "").toLowerCase();
  const tracked = (user?.tracked_role || "").toLowerCase();
  const canDownload =
    ["admin", "superviseur"].includes(role) || ["admin", "superviseur"].includes(tracked);
  // S025 — download approval gate (used only when canDownload is false but
  // the user explicitly asks for an external download)
  const { requestDownload, close, state: gateState } = useDownloadGate();

  useEffect(() => {
    if (src) return;  // viewer mode, skip list fetch
    apiClient.get("/public/docs")
      .then((r) => setDocs(r.data?.items || []))
      .catch(() => setDocs([]))
      .finally(() => setLoading(false));
  }, [src]);

  if (src) {
    return (
      <div className="h-[calc(100vh-9rem)] -mx-3 sm:-mx-6 lg:-mx-10 -mt-6 flex flex-col" data-testid="brochure-viewer-page">
        <div className="px-4 py-2 bg-white border-b border-slate-200 flex items-center gap-2">
          <button
            onClick={() => navigate("/portal/brochures")}
            className="text-xs inline-flex items-center gap-1 px-2 py-1 rounded ring-1 ring-slate-200 hover:bg-slate-50"
            data-testid="brochure-viewer-back"
          >
            <ChevronLeft className="h-3.5 w-3.5" /> Retour à la liste
          </button>
          {!canDownload && (
            <button
              onClick={() => requestDownload({ url: src, label: title })}
              className="ml-auto text-xs inline-flex items-center gap-1 px-3 py-1 rounded bg-sawali-blue text-white hover:opacity-90"
              data-testid="brochure-request-download"
              title="Demander une autorisation de téléchargement (approbation par WhatsApp)"
            >
              📥 Demander le téléchargement
            </button>
          )}
        </div>
        <div className="flex-1 min-h-0">
          <PdfViewer src={src} title={title} allowDownload={canDownload} />
        </div>
        <DownloadGate state={gateState} onClose={close} />
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="brochures-portal-page">
      <header>
        <h1 className="text-2xl font-display font-bold text-slate-900 inline-flex items-center gap-2">
          <BookOpen className="h-6 w-6 text-sawali-blue" />
          Brochures & Guides
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Consultez la documentation officielle SAWALI directement en ligne.
          {!canDownload && " Le téléchargement est réservé aux Admins / Superviseurs."}
        </p>
      </header>
      {loading ? (
        <p className="text-sm text-slate-500">Chargement…</p>
      ) : docs.length === 0 ? (
        <p className="text-sm text-slate-500 italic">Aucun document disponible.</p>
      ) : (
        <div className="grid sm:grid-cols-3 gap-4">
          {docs.map((d) => {
            const meta = META[d.slug] || { title: d.filename, color: "from-slate-500 to-slate-700" };
            const apiBase = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");
            const fullSrc = `${apiBase}${d.url}`;
            const viewerUrl = `/portal/brochures?src=${encodeURIComponent(fullSrc)}&title=${encodeURIComponent(meta.title)}`;
            return (
              <button
                key={d.slug}
                onClick={() => navigate(viewerUrl)}
                className="group rounded-xl ring-1 ring-slate-200 hover:ring-2 hover:ring-sawali-blue/50 hover:shadow-lg transition-all overflow-hidden bg-white text-left"
                data-testid={`brochure-card-${d.slug}`}
              >
                <div className={`bg-gradient-to-br ${meta.color} h-24 flex items-center justify-center text-white`}>
                  <FileText className="h-10 w-10" />
                </div>
                <div className="p-4">
                  <h3 className="text-sm font-display font-semibold text-slate-900">{meta.title}</h3>
                  <p className="text-[11px] text-slate-500 mt-1">{d.size_kb} Ko · PDF</p>
                  <p className="text-xs text-sawali-blue mt-2 inline-flex items-center gap-1 group-hover:gap-2 transition-all">
                    <BookOpen className="h-3 w-3" /> Consulter en ligne
                  </p>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
