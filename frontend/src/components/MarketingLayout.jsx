import React from "react";
import MarketingNav from "@/components/MarketingNav";
import MarketingFooter from "@/components/MarketingFooter";
import StatusPill from "@/components/StatusPill";
import IncidentBanner from "@/components/IncidentBanner";
import VersionStamp from "@/components/VersionStamp";
import SupportLoadGauge from "@/components/SupportLoadGauge";

export default function MarketingLayout({ children }) {
  return (
    <div className="marketing-dark min-h-screen flex flex-col overflow-x-hidden">
      <SupportLoadGauge />
      <IncidentBanner />
      <MarketingNav />
      <main className="flex-1 max-w-full">{children}</main>
      <MarketingFooter />
      <StatusPill />
      <VersionStamp tone="light" />
    </div>
  );
}
