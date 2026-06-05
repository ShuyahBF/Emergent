// Iter40-ui-flags-bg (S057) — Dynamic theming: public/portal background.
//
// Reads ui flags (background mode / color / image / position) and applies
// them to <body> depending on the current route:
//   - /portal/*, /admin/* → portal_bg_* fields
//   - everything else (public marketing pages) → public_bg_* fields
//
// Why <body> and not <html> ? React mounts on #root inside <body>; if we
// apply on <html>, it covers the loader / scrollbar gutter which can look
// odd. <body> is the canonical place for "page-level" theme.
//
// The component is render-less (returns null) and just listens to:
//   1. Route changes via useLocation()
//   2. UI flags refresh via useUIFlags()
//
// When mode === "default" (or no flag set), we strip our overrides so the
// app falls back to the natural Tailwind palette set by individual layouts.
import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { useUIFlags } from "@/lib/useUIFlags";

const OVERRIDE_MARKER = "data-bg-override-active";

function buildBgStyle(mode, color, imageUrl, position) {
  if (mode === "color" && color) {
    return {
      backgroundColor: color,
      backgroundImage: "none",
    };
  }
  if (mode === "image" && imageUrl) {
    const pos = position || "cover";
    const css = {
      backgroundColor: color || "transparent",
      backgroundImage: `url("${imageUrl}")`,
      backgroundAttachment: "fixed",
    };
    if (pos === "repeat") {
      css.backgroundRepeat = "repeat";
      css.backgroundSize = "auto";
      css.backgroundPosition = "top left";
    } else if (pos === "contain") {
      css.backgroundRepeat = "no-repeat";
      css.backgroundSize = "contain";
      css.backgroundPosition = "center";
    } else if (pos === "center") {
      css.backgroundRepeat = "no-repeat";
      css.backgroundSize = "auto";
      css.backgroundPosition = "center";
    } else {
      // cover (default)
      css.backgroundRepeat = "no-repeat";
      css.backgroundSize = "cover";
      css.backgroundPosition = "center";
    }
    return css;
  }
  return null;
}

function applyStyle(style) {
  if (typeof document === "undefined") return;
  const body = document.body;
  if (!body) return;
  if (!style) {
    // Strip our overrides
    if (body.getAttribute(OVERRIDE_MARKER) === "1") {
      body.style.backgroundColor = "";
      body.style.backgroundImage = "";
      body.style.backgroundRepeat = "";
      body.style.backgroundSize = "";
      body.style.backgroundPosition = "";
      body.style.backgroundAttachment = "";
      body.removeAttribute(OVERRIDE_MARKER);
    }
    return;
  }
  body.style.backgroundColor = style.backgroundColor || "";
  body.style.backgroundImage = style.backgroundImage || "";
  body.style.backgroundRepeat = style.backgroundRepeat || "";
  body.style.backgroundSize = style.backgroundSize || "";
  body.style.backgroundPosition = style.backgroundPosition || "";
  body.style.backgroundAttachment = style.backgroundAttachment || "";
  body.setAttribute(OVERRIDE_MARKER, "1");
}

export default function BackgroundApplier() {
  const flags = useUIFlags();
  const location = useLocation();

  useEffect(() => {
    const path = location.pathname || "/";
    const isPortal = path.startsWith("/portal") || path.startsWith("/admin");
    const mode = isPortal ? flags?.portal_bg_mode : flags?.public_bg_mode;
    const color = isPortal ? flags?.portal_bg_color : flags?.public_bg_color;
    const img = isPortal ? flags?.portal_bg_image_url : flags?.public_bg_image_url;
    const pos = isPortal ? flags?.portal_bg_image_position : flags?.public_bg_image_position;
    const style = buildBgStyle(mode, color, img, pos);
    applyStyle(style);
  }, [
    location.pathname,
    flags?.public_bg_mode, flags?.public_bg_color, flags?.public_bg_image_url, flags?.public_bg_image_position,
    flags?.portal_bg_mode, flags?.portal_bg_color, flags?.portal_bg_image_url, flags?.portal_bg_image_position,
  ]);

  return null;
}
