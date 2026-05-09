import React, { useState } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { Menu, X, ArrowRight, LogIn } from "lucide-react";
import { LOGO_URL } from "@/lib/brand";
import { useAuth } from "@/contexts/AuthContext";
import SupportLoadGauge from "@/components/SupportLoadGauge";

const links = [
  { to: "/", label: "Accueil" },
  { to: "/missions", label: "Missions" },
  { to: "/specialisations", label: "Spécialisations" },
  { to: "/catalogue", label: "Catalogue" },
  { to: "/etudes-de-cas", label: "Études de cas" },
  { to: "/subscriptions", label: "Abonnements" },
  { to: "/temoignages", label: "Témoignages" },
  { to: "/rdv", label: "Demande RDV" },
  { to: "/contact", label: "Contact" },
  { to: "/politiques", label: "Politiques" },
];

export default function MarketingNav() {
  const [open, setOpen] = useState(false);
  const { user } = useAuth();
  const navigate = useNavigate();

  const portalHref = user ? (user.role === "admin" ? "/admin" : "/portal") : "/login";
  const portalLabel = user ? "Mon espace" : "Espace Client";

  return (
    <header className="glass-nav sticky top-0 z-50 backdrop-blur-md bg-[#081226]/85 border-b border-white/5" data-testid="marketing-navbar">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="relative flex h-16 items-center justify-between">
          <Link to="/" className="flex items-center gap-3 z-10" data-testid="navbar-logo-link">
            <img src={LOGO_URL} alt="SAWALI" className="h-10 w-10 rounded-md object-cover ring-1 ring-white/20" />
            <div className="hidden sm:flex flex-col leading-tight">
              <span className="font-display font-bold text-white tracking-tight">SAWALI SMART SYSTEMS</span>
              <span className="text-[10px] uppercase tracking-[0.25em] text-sawali-blue-light">Software Engineering</span>
            </div>
          </Link>

          {/* Center — Support Load Gauge (cellular-bars). Absolute-centered so it stays visually centered regardless of left/right widths. Hidden on small screens to keep the bar tidy. */}
          <div
            className="hidden md:flex absolute left-1/2 -translate-x-1/2 items-center pointer-events-auto"
            data-testid="navbar-support-gauge-wrap"
          >
            <SupportLoadGauge inline />
          </div>

          <nav className="hidden lg:flex items-center gap-1 ml-auto mr-4">
            {links.map((l) => (
              <NavLink
                key={l.to}
                to={l.to}
                end={l.to === "/"}
                className={({ isActive }) =>
                  `px-2.5 py-2 text-[13px] font-medium transition-colors ${
                    isActive ? "text-white" : "text-slate-300 hover:text-white"
                  }`
                }
                data-testid={`nav-link-${l.to.replace("/", "") || "home"}`}
              >
                {l.label}
              </NavLink>
            ))}
          </nav>

          <div className="flex items-center gap-2 z-10">
            <button
              onClick={() => navigate(portalHref)}
              className="hidden sm:inline-flex items-center gap-2 rounded-lg border border-sawali-blue/40 px-4 py-2 text-sm text-white hover:bg-sawali-blue/10 transition"
              data-testid="navbar-portal-button"
            >
              <LogIn className="h-4 w-4" />
              {portalLabel}
            </button>
            <Link
              to="/rdv"
              className="hidden md:inline-flex items-center gap-2 rounded-lg btn-electric px-4 py-2 text-sm font-medium"
              data-testid="navbar-cta-rdv"
            >
              Réserver un RDV
              <ArrowRight className="h-4 w-4" />
            </Link>
            <button
              className="lg:hidden p-2 text-white"
              onClick={() => setOpen((v) => !v)}
              aria-label="Menu"
              data-testid="mobile-menu-toggle"
            >
              {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
          </div>
        </div>
      </div>

      {open && (
        <div className="lg:hidden border-t border-white/10 bg-[#081226]/95 px-4 py-3 space-y-1" data-testid="mobile-menu">
          {links.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              end={l.to === "/"}
              onClick={() => setOpen(false)}
              className={({ isActive }) =>
                `block rounded-md px-3 py-2 text-sm ${isActive ? "bg-sawali-blue/20 text-white" : "text-slate-300"}`
              }
            >
              {l.label}
            </NavLink>
          ))}
          <button
            onClick={() => { setOpen(false); navigate(portalHref); }}
            className="w-full text-left rounded-md px-3 py-2 text-sm text-white border border-sawali-blue/40 mt-2"
            data-testid="mobile-portal-button"
          >
            {portalLabel}
          </button>
        </div>
      )}
    </header>
  );
}
