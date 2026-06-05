import React, { useEffect, useState } from "react";
import MarketingNav from "@/components/MarketingNav";
import MarketingFooter from "@/components/MarketingFooter";
import StatusPill from "@/components/StatusPill";
import IncidentBanner from "@/components/IncidentBanner";
import VersionStamp from "@/components/VersionStamp";
import CookieBanner from "@/components/CookieBanner";
import PublicAdModal from "@/components/PublicAdModal";

// Iter40-ui-flags-bg (S057) — Watch the override marker set by BackgroundApplier
// so the marketing layout can become transparent (revealing the body's themed
// background). Without this, the marketing-dark gradient would mask the
// admin-chosen color/image.
function useBgOverrideActive() {
  const [active, setActive] = useState(false);
  useEffect(() => {
    if (typeof document === "undefined") return undefined;
    const check = () => setActive(document.body.getAttribute("data-bg-override-active") === "1");
    check();
    const obs = new MutationObserver(check);
    obs.observe(document.body, { attributes: true, attributeFilter: ["data-bg-override-active"] });
    return () => obs.disconnect();
  }, []);
  return active;
}

export default function MarketingLayout({ children }) {
  const bgOverride = useBgOverrideActive();
  const themeClass = bgOverride
    ? "min-h-screen flex flex-col overflow-x-hidden text-white"
    : "marketing-dark min-h-screen flex flex-col overflow-x-hidden";
  return (
    <div className={themeClass}>
      <IncidentBanner />
      <MarketingNav />
      <main className="flex-1 max-w-full">{children}</main>
      <MarketingFooter />
      <StatusPill />
      <VersionStamp tone="light" />
      <CookieBanner />
      <PublicAdModal />
    </div>
  );
}
