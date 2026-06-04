// Iter40-modal — Random ad banner popup modal for the public marketing pages.
//
// Behaviour:
//  • On first mount, fetches GET /api/public/ad-banners/active?placement=public_modal
//    which returns ONE weighted-random active banner whose placement is exactly
//    "public_modal" (max 10 active modal banners can be configured in admin).
//  • Displays the banner inside a centered overlay modal once per session
//    (sessionStorage flag prevents re-showing on every route change).
//  • Fires impression tracking on display and click tracking when the user
//    clicks the image — same endpoints as AdBannerSlot.
//  • Clean dismissal via the X button or ESC key.
import React, { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { resolveAssetUrl } from "@/lib/useAssetUrl";

const SESSION_KEY = "public_ad_modal_shown";
// Wait a beat before showing so the page settles first (avoids being
// dismissed by layout shifts / route loaders).
const SHOW_DELAY_MS = 1500;

export default function PublicAdModal() {
  const [banner, setBanner] = useState(null);
  const [visible, setVisible] = useState(false);
  const apiBase = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");
  const impressionFired = useRef(false);

  useEffect(() => {
    // One modal per session
    try {
      if (sessionStorage.getItem(SESSION_KEY) === "1") return;
    } catch { /* ignore */ }

    let cancelled = false;
    let showTimer = null;

    fetch(`${apiBase}/api/public/ad-banners/active?placement=public_modal`)
      .then((r) => (r.ok ? r.json() : { banner: null }))
      .then((data) => {
        if (cancelled) return;
        const b = data?.banner || null;
        if (!b) return;
        setBanner(b);
        showTimer = setTimeout(() => {
          if (cancelled) return;
          setVisible(true);
          try { sessionStorage.setItem(SESSION_KEY, "1"); } catch { /* ignore */ }
        }, SHOW_DELAY_MS);
      })
      .catch(() => {});

    return () => {
      cancelled = true;
      if (showTimer) clearTimeout(showTimer);
    };
  }, [apiBase]);

  // ESC closes
  useEffect(() => {
    if (!visible) return;
    const onKey = (e) => { if (e.key === "Escape") setVisible(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [visible]);

  // Impression tracking — fire once when the modal becomes visible
  useEffect(() => {
    if (!visible || !banner || impressionFired.current) return;
    impressionFired.current = true;
    try {
      const variant = banner.active_variant === "b" ? "b" : "a";
      fetch(`${apiBase}/api/public/ad-banners/${banner.id}/impression?variant=${variant}`, {
        method: "POST",
        keepalive: true,
      }).catch(() => {});
    } catch { /* swallow */ }
  }, [visible, banner, apiBase]);

  if (!visible || !banner) return null;

  const isVideo = banner.media_kind === "video"
    || /\.(mp4|webm|mov)$/i.test(banner.image_url || "");
  const mediaSrc = resolveAssetUrl(banner.image_url);

  const handleClick = (e) => {
    if (!banner?.target_url) return;
    e.preventDefault();
    try {
      const variant = banner.active_variant === "b" ? "b" : "a";
      fetch(`${apiBase}/api/public/ad-banners/${banner.id}/click?variant=${variant}`, {
        method: "POST",
        keepalive: true,
      }).catch(() => {});
    } catch { /* swallow */ }
    window.open(banner.target_url, "_blank", "noopener,noreferrer");
  };

  const handleClose = () => setVisible(false);

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in duration-300"
      onClick={handleClose}
      role="dialog"
      aria-modal="true"
      aria-label={`Publicité : ${banner.name}`}
      data-testid="public-ad-modal"
    >
      <div
        className="relative max-w-2xl w-full bg-white rounded-2xl shadow-2xl overflow-hidden ring-1 ring-white/10 animate-in zoom-in-95 duration-300"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={handleClose}
          className="absolute top-2 right-2 z-10 bg-black/50 hover:bg-black/70 backdrop-blur-sm text-white rounded-full p-2 transition-colors"
          aria-label="Fermer la publicité"
          data-testid="public-ad-modal-close"
        >
          <X className="h-4 w-4" />
        </button>

        <span className="absolute top-2 left-2 z-10 bg-black/50 backdrop-blur-sm text-white/80 text-[10px] uppercase tracking-wider px-2 py-1 rounded-full">
          Publicité
        </span>

        <button
          onClick={handleClick}
          className="block w-full cursor-pointer focus:outline-none"
          aria-label={`Ouvrir : ${banner.name}`}
          data-testid={`public-ad-modal-click-${banner.id}`}
        >
          {isVideo ? (
            <video
              src={mediaSrc}
              className="w-full h-auto max-h-[70vh] object-contain bg-slate-900"
              autoPlay
              loop
              muted
              playsInline
              preload="metadata"
              data-testid={`public-ad-modal-video-${banner.id}`}
            />
          ) : (
            <img
              src={mediaSrc}
              alt={banner.advertiser_name || banner.name}
              className="w-full h-auto max-h-[70vh] object-contain bg-slate-50"
              loading="eager"
              data-testid={`public-ad-modal-image-${banner.id}`}
            />
          )}
        </button>

        {(banner.name || banner.advertiser_name) && (
          <div className="px-4 py-3 bg-slate-50 border-t border-slate-200 flex items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-slate-800 truncate">{banner.name}</p>
              {banner.advertiser_name && (
                <p className="text-xs text-slate-500 truncate">par {banner.advertiser_name}</p>
              )}
            </div>
            {banner.target_url && (
              <button
                onClick={handleClick}
                className="shrink-0 inline-flex items-center gap-1.5 bg-fuchsia-600 hover:bg-fuchsia-700 text-white text-xs font-semibold px-3 py-2 rounded-lg transition-colors"
                data-testid="public-ad-modal-cta"
              >
                Découvrir →
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
