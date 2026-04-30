import React from "react";
import MarketingNav from "@/components/MarketingNav";
import MarketingFooter from "@/components/MarketingFooter";
import StatusPill from "@/components/StatusPill";
import IncidentBanner from "@/components/IncidentBanner";

export default function MarketingLayout({ children }) {
  return (
    <div className="marketing-dark min-h-screen flex flex-col">
      <IncidentBanner />
      <MarketingNav />
      <main className="flex-1">{children}</main>
      <MarketingFooter />
      <StatusPill />
    </div>
  );
}
