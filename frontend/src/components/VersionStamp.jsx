import React, { useEffect, useState } from "react";

/*
  Tiny version pill rendered at the bottom-left of any page.
  Shows the running build version + last restart time.
  Re-fetches every 5 minutes so a redeploy is reflected without a full page reload.
  Visual style (color / size / opacity / weight / italic) is configurable
  by the super-admin in /admin/settings → "Version stamp".
*/
const SIZE_PX = { xs: 10, sm: 12, md: 14, lg: 16 };

export default function VersionStamp() {
  const [info, setInfo] = useState(null);
  const [style, setStyle] = useState({
    color: null,
    size: "xs",
    opacity: 70,
    style: "normal",
  });

  useEffect(() => {
    let alive = true;
    const fetchVer = () => {
      fetch("/api/version")
        .then((r) => r.json())
        .then((j) => { if (alive) setInfo(j); })
        .catch(() => {});
    };
    const fetchStyle = () => {
      fetch("/api/company-info")
        .then((r) => r.json())
        .then((j) => {
          if (!alive) return;
          const v = j?.version_stamp || {};
          setStyle({
            color: v.color || null,
            size: v.size || "xs",
            opacity: typeof v.opacity === "number" ? v.opacity : 70,
            style: v.style || "normal",
          });
        })
        .catch(() => {});
    };
    fetchVer();
    fetchStyle();
    const id = setInterval(fetchVer, 5 * 60 * 1000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  if (!info) return null;
  const stamp = info.started_at
    ? new Date(info.started_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })
    : "—";

  const fontSize = SIZE_PX[style.size] || SIZE_PX.xs;
  const fontWeight = (style.style || "").includes("bold") ? 700 : 400;
  const fontStyle = (style.style || "").includes("italic") ? "italic" : "normal";
  const opacity = Math.max(10, Math.min(100, style.opacity || 70)) / 100;
  // Default falls back to slate-500 when no color is configured.
  const color = style.color || "#64748b";

  return (
    <div
      className="fixed bottom-2 left-3 z-30 select-none pointer-events-none tracking-wide"
      data-testid="version-stamp"
      title={`Version ${info.version} — déployé le ${stamp}`}
      style={{
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        fontSize,
        fontWeight,
        fontStyle,
        opacity,
        color,
      }}
    >
      v{info.version} · {stamp}
    </div>
  );
}
