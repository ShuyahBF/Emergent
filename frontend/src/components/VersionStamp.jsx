import React, { useEffect, useState } from "react";

/*
  Tiny version pill rendered at the bottom-right of any page.
  Shows the running build version + last restart time.
  Re-fetches every 5 minutes so a redeploy is reflected without a full page reload.
*/
export default function VersionStamp({ tone = "light" }) {
  const [info, setInfo] = useState(null);

  useEffect(() => {
    let alive = true;
    const fetchVer = () => {
      fetch("/api/version")
        .then((r) => r.json())
        .then((j) => { if (alive) setInfo(j); })
        .catch(() => {});
    };
    fetchVer();
    const id = setInterval(fetchVer, 5 * 60 * 1000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  if (!info) return null;
  const stamp = info.started_at
    ? new Date(info.started_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })
    : "—";
  const isLight = tone === "light";
  return (
    <div
      className={`fixed bottom-2 left-3 z-30 text-[10px] font-mono select-none pointer-events-none tracking-wide ${
        isLight ? "text-white/70" : "text-slate-500"
      }`}
      data-testid="version-stamp"
      title={`Version ${info.version} — déployé le ${stamp}`}
    >
      v{info.version} · {stamp}
    </div>
  );
}
