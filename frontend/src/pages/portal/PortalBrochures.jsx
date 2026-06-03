// S-iter39b — Portal page that lists Brochures & Guides and opens them
// inline in the internal viewer (modérateurs lecture seule).
// S-iter39p (2026-02) — Extended to surface the Media Library (PDF,
// vidéos, images uploadées par l'admin) + lecteurs internes + boutons
// de partage social (vidéos + images uniquement, jamais sur PDF).
import React, { useEffect, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { FileText, BookOpen, ChevronLeft, Video, ImageIcon, Play } from "lucide-react";
import PdfViewer from "@/components/PdfViewer";
import SocialShareButtons from "@/components/SocialShareButtons";
import { useAuth } from "@/contexts/AuthContext";
import DownloadGate, { useDownloadGate } from "@/components/DownloadGate";

const META = {
  "guide-utilisateur": { title: "Guide Utilisateur", color: "from-sky-500 to-blue-600" },
  "brochure-presentation": { title: "Brochure de présentation", color: "from-fuchsia-500 to-pink-600" },
  "brochure-fonctionnalites": { title: "Grandes fonctionnalités", color: "from-emerald-500 to-teal-600" },
  "admin-settings-reference": { title: "Référence technique — AdminSettings", color: "from-violet-500 to-indigo-600" },
};

export default function PortalBrochures() {
  const [docs, setDocs] = useState([]);
  const [media, setMedia] = useState([]);
  const [loading, setLoading] = useState(true);
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const src = params.get("src");
  const title = params.get("title") || "Document";
  const kind = (params.get("kind") || "pdf").toLowerCase();
  const { user } = useAuth() || {};
  const role = (user?.role || "").toLowerCase();
  const tracked = (user?.tracked_role || "").toLowerCase();
  const canDownload =
    ["admin", "superviseur"].includes(role) || ["admin", "superviseur"].includes(tracked);
  const { requestDownload, close, state: gateState } = useDownloadGate();

  useEffect(() => {
    if (src) return;
    Promise.allSettled([
      apiClient.get("/public/docs"),
      apiClient.get("/public/media-library"),
    ]).then(([d, m]) => {
      setDocs(d.status === "fulfilled" ? (d.value?.data?.items || []) : []);
      setMedia(m.status === "fulfilled" ? (m.value?.data?.items || []) : []);
    }).finally(() => setLoading(false));
  }, [src]);

  // ---- Viewer mode ----
  if (src) {
    return (
      <div className="h-[calc(100vh-9rem)] -mx-3 sm:-mx-6 lg:-mx-10 -mt-6 flex flex-col" data-testid="brochure-viewer-page">
        <div className="px-4 py-2 bg-white border-b border-slate-200 flex items-center gap-2 flex-wrap">
          <button
            onClick={() => navigate("/portal/brochures")}
            className="text-xs inline-flex items-center gap-1 px-2 py-1 rounded ring-1 ring-slate-200 hover:bg-slate-50"
            data-testid="brochure-viewer-back"
          >
            <ChevronLeft className="h-3.5 w-3.5" /> Retour à la liste
          </button>
          <span className="text-xs text-slate-500 truncate flex-1">{title}</span>
          {(kind === "video" || kind === "image") && (
            <SocialShareButtons url={src} title={title} kind={kind} />
          )}
          {kind === "pdf" && !canDownload && (
            <button
              onClick={() => requestDownload({ url: src, label: title })}
              className="text-xs inline-flex items-center gap-1 px-3 py-1 rounded bg-sawali-blue text-white hover:opacity-90"
              data-testid="brochure-request-download"
              title="Demander une autorisation de téléchargement"
            >
              📥 Demander le téléchargement
            </button>
          )}
        </div>
        <div className="flex-1 min-h-0 bg-slate-900 flex items-center justify-center overflow-auto">
          {kind === "pdf" && <PdfViewer src={src} title={title} allowDownload={canDownload} />}
          {kind === "video" && (
            <video
              src={src}
              controls
              className="max-h-full max-w-full"
              data-testid="brochure-video-player"
              autoPlay
            >
              Votre navigateur ne supporte pas la balise vidéo.
            </video>
          )}
          {kind === "image" && (
            <img
              src={src}
              alt={title}
              className="max-h-full max-w-full object-contain"
              data-testid="brochure-image-viewer"
            />
          )}
        </div>
        <DownloadGate state={gateState} onClose={close} />
      </div>
    );
  }

  // ---- List mode : merge PDFs + media ----
  const apiBase = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");
  const pdfCards = docs.map((d) => {
    const meta = META[d.slug] || { title: d.filename, color: "from-slate-500 to-slate-700" };
    const fullSrc = `${apiBase}${d.url}`;
    return {
      key: `static-${d.slug}`,
      title: meta.title,
      color: meta.color,
      kind: "pdf",
      src: fullSrc,
      size_kb: d.size_kb,
      isStatic: true,
    };
  });
  const mediaCards = media.map((m) => ({
    key: `media-${m.id}`,
    title: m.title,
    description: m.description,
    color: m.kind === "video" ? "from-rose-500 to-orange-600" : m.kind === "image" ? "from-amber-400 to-yellow-600" : "from-slate-500 to-slate-700",
    kind: m.kind,
    src: m.url && m.url.startsWith("http") ? m.url : `${apiBase}${m.url || ""}`,
    size_kb: Math.round((m.size || 0) / 1024),
    isStatic: false,
    rawUrl: m.url,
  }));
  const cards = [...pdfCards, ...mediaCards];

  return (
    <div className="space-y-6" data-testid="brochures-portal-page">
      <header>
        <h1 className="text-2xl font-display font-bold text-slate-900 inline-flex items-center gap-2">
          <BookOpen className="h-6 w-6 text-sawali-blue" />
          Brochures, Guides &amp; Médias
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Documents officiels, vidéos de présentation et visuels SAWALI.
          {!canDownload && " Le téléchargement PDF est réservé aux Admins / Superviseurs."}
        </p>
      </header>
      {loading ? (
        <p className="text-sm text-slate-500">Chargement…</p>
      ) : cards.length === 0 ? (
        <p className="text-sm text-slate-500 italic">Aucun document disponible.</p>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {cards.map((c) => {
            const viewerUrl = `/portal/brochures?src=${encodeURIComponent(c.src)}&title=${encodeURIComponent(c.title)}&kind=${c.kind}`;
            const Icon = c.kind === "video" ? Video : c.kind === "image" ? ImageIcon : FileText;
            return (
              <div key={c.key} className="group rounded-xl ring-1 ring-slate-200 hover:ring-2 hover:ring-sawali-blue/50 hover:shadow-lg transition-all overflow-hidden bg-white text-left flex flex-col" data-testid={`brochure-card-${c.key}`}>
                <button
                  onClick={() => navigate(viewerUrl)}
                  className="text-left"
                  data-testid={`brochure-card-open-${c.key}`}
                >
                  <div className={`bg-gradient-to-br ${c.color} h-28 flex items-center justify-center text-white relative`}>
                    {c.kind === "image" && c.src ? (
                      <img src={c.src} alt={c.title} className="absolute inset-0 h-full w-full object-cover opacity-90" />
                    ) : c.kind === "video" && c.src ? (
                      <>
                        <video src={c.src} className="absolute inset-0 h-full w-full object-cover opacity-70" muted preload="metadata" />
                        <Play className="h-10 w-10 relative z-10" />
                      </>
                    ) : (
                      <Icon className="h-10 w-10" />
                    )}
                  </div>
                  <div className="p-4">
                    <h3 className="text-sm font-display font-semibold text-slate-900">{c.title}</h3>
                    {c.description && <p className="text-[11px] text-slate-500 mt-1 line-clamp-2">{c.description}</p>}
                    <p className="text-[11px] text-slate-500 mt-1">{c.size_kb} Ko · {c.kind.toUpperCase()}</p>
                  </div>
                </button>
                {(c.kind === "video" || c.kind === "image") && (
                  <div className="px-4 pb-3 flex items-center justify-between">
                    <button
                      onClick={() => navigate(viewerUrl)}
                      className="text-xs text-sawali-blue hover:underline inline-flex items-center gap-1"
                    >
                      <Play className="h-3 w-3" /> Ouvrir
                    </button>
                    <SocialShareButtons url={c.src} title={c.title} kind={c.kind} compact />
                  </div>
                )}
                {c.kind === "pdf" && (
                  <div className="px-4 pb-3">
                    <button
                      onClick={() => navigate(viewerUrl)}
                      className="text-xs text-sawali-blue hover:underline inline-flex items-center gap-1"
                    >
                      <BookOpen className="h-3 w-3" /> Consulter en ligne
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
