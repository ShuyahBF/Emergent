// Iter38r-fix9w — Ad Banner Slot (top of public + portal layouts).
// Fetches one active banner for the requested placement, fires impression
// tracking on mount, and a click tracker on banner click.
//
// Iter38r-fix9z5 — Display sizing parametrable: auto / ratio / percentage / fixed.
import React, { useEffect, useState, useRef } from "react";
import { X, Volume2, VolumeX } from "lucide-react";
import { resolveAssetUrl } from "@/lib/useAssetUrl";
import { computeBannerStyles } from "@/lib/bannerStyle";

export default function AdBannerSlot({ placement = "public" }) {
  const [banner, setBanner] = useState(null);
  const [dismissed, setDismissed] = useState(() => {
    try { return sessionStorage.getItem(`ad_dismissed_${placement}`) === "1"; } catch { return false; }
  });
  // S-iter39d (fix #8) — Sound enabled by default on public videos.
  // Browsers (Chrome/Safari/Firefox) BLOCK autoplay of unmuted videos
  // before any user gesture. We START muted to satisfy autoplay policy,
  // then on the FIRST user interaction anywhere on the page we unmute
  // automatically — giving the "son activé par défaut" semantics while
  // respecting browser policies. User can still manually mute via the
  // toggle button, and that explicit choice is persisted.
  const [muted, setMuted] = useState(() => {
    try {
      const v = sessionStorage.getItem("ad_banner_muted");
      return v === null ? true : v === "1";
    } catch { return true; }
  });
  const [userMutePrefSet, setUserMutePrefSet] = useState(() => {
    try { return sessionStorage.getItem("ad_banner_muted") !== null; } catch { return false; }
  });
  const impressionFired = useRef(false);
  const videoRef = useRef(null);
  const apiBase = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");

  // S-iter39e (fix #3) — Auto-unmute on first user gesture (anywhere on the
  // page) so videos effectively start with sound on as soon as the visitor
  // does ANY interaction. Pure-passive page loads still respect browser
  // autoplay policy (start muted). Skipped if the user explicitly muted.
  useEffect(() => {
    if (userMutePrefSet) return;
    const unmute = () => {
      if (!videoRef.current) return;
      try {
        videoRef.current.muted = false;
        videoRef.current.play().catch(() => {});
        setMuted(false);
      } catch { /* noop */ }
    };
    const opts = { once: true, passive: true };
    window.addEventListener("click", unmute, opts);
    window.addEventListener("touchstart", unmute, opts);
    window.addEventListener("keydown", unmute, opts);
    return () => {
      window.removeEventListener("click", unmute);
      window.removeEventListener("touchstart", unmute);
      window.removeEventListener("keydown", unmute);
    };
  }, [userMutePrefSet]);

  useEffect(() => {
    if (dismissed) return;
    let cancelled = false;
    fetch(`${apiBase}/api/public/ad-banners/active?placement=${encodeURIComponent(placement)}`)
      .then((r) => r.ok ? r.json() : { banner: null })
      .then((data) => { if (!cancelled) setBanner(data?.banner || null); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [apiBase, placement, dismissed]);

  useEffect(() => {
    if (!banner || impressionFired.current) return;
    impressionFired.current = true;
    try {
      const variant = banner.active_variant === "b" ? "b" : "a";
      fetch(`${apiBase}/api/public/ad-banners/${banner.id}/impression?variant=${variant}`, {
        method: "POST",
        keepalive: true,
      }).catch(() => {});
    } catch { /* swallow */ }
  }, [banner, apiBase]);

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

  const handleDismiss = (e) => {
    e.stopPropagation();
    setDismissed(true);
    try { sessionStorage.setItem(`ad_dismissed_${placement}`, "1"); } catch { /* ignore */ }
  };

  if (dismissed || !banner) return null;

  const isVideo = banner.media_kind === "video"
    || /\.(mp4|webm|mov)$/i.test(banner.image_url || "");
  const mediaSrc = resolveAssetUrl(banner.image_url);
  const styles = computeBannerStyles(banner);

  // In "auto" mode, keep the original 64/80 responsive height classes.
  // In any explicit mode, drop the height/width Tailwind utilities so the
  // inline style fully controls the dimensions.
  const isAuto = styles.mode === "auto";
  const mediaClass = isAuto
    ? `w-full h-16 sm:h-20 object-cover object-center cursor-pointer ${banner.animated && !isVideo ? "animate-pulse-soft" : ""}`
    : `cursor-pointer block ${banner.animated && !isVideo ? "animate-pulse-soft" : ""}`;

  return (
    <div
      className="relative w-full bg-gradient-to-r from-slate-900 via-slate-800 to-slate-900 border-b border-slate-200/20"
      data-testid={`ad-banner-${placement}`}
    >
      <div className="mx-auto" style={styles.outer}>
        <button
          onClick={handleClick}
          className="block w-full h-full max-w-7xl mx-auto"
          aria-label={`Bannière publicitaire : ${banner.name}`}
          data-testid={`ad-banner-click-${banner.id}`}
        >
          {isVideo ? (
            <video
              ref={videoRef}
              src={mediaSrc}
              className={mediaClass}
              style={isAuto ? undefined : styles.inner}
              muted={muted} autoPlay loop playsInline preload="metadata"
              data-testid={`ad-banner-video-${banner.id}`}
            />
          ) : (
            <img
              src={mediaSrc}
              alt={banner.advertiser_name || banner.name}
              className={mediaClass}
              style={isAuto ? undefined : styles.inner}
              loading="lazy"
            />
          )}
        </button>
      </div>
      <div className="absolute top-1 right-1 flex items-center gap-1">
        <span className="hidden sm:inline-block bg-black/40 backdrop-blur-sm text-white/70 text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded">
          Publicité
        </span>
        {/* S-iter39d (fix #8) — Sound toggle on video banners, default ON */}
        {isVideo && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              const next = !muted;
              setMuted(next);
              setUserMutePrefSet(true);
              try { sessionStorage.setItem("ad_banner_muted", next ? "1" : "0"); } catch { /* noop */ }
              // Some browsers need an explicit play() after unmute via user gesture
              if (!next && videoRef.current) {
                try {
                  videoRef.current.muted = false;
                  videoRef.current.play().catch(() => {});
                } catch { /* noop */ }
              }
            }}
            className="bg-black/40 backdrop-blur-sm hover:bg-black/60 text-white/80 hover:text-white p-1 rounded transition-colors"
            aria-label={muted ? "Activer le son" : "Couper le son"}
            title={muted ? "Activer le son" : "Couper le son"}
            data-testid={`ad-banner-sound-toggle-${banner.id}`}
          >
            {muted ? <VolumeX className="h-3 w-3" /> : <Volume2 className="h-3 w-3" />}
          </button>
        )}
        <button
          onClick={handleDismiss}
          className="bg-black/40 backdrop-blur-sm hover:bg-black/60 text-white/80 hover:text-white p-1 rounded transition-colors"
          aria-label="Fermer la bannière"
          data-testid={`ad-banner-dismiss-${banner.id}`}
        >
          <X className="h-3 w-3" />
        </button>
      </div>
    </div>
  );
}
