// Iter42 — Officine portal layout (header + tabs + outlet).
import React from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { LOGO_URL } from "@/lib/brand";
import { LayoutDashboard, Boxes, KeyRound, History, LogOut } from "lucide-react";
import { loadOfficineSession, clearOfficineSession } from "@/lib/officineApi";

const TABS = [
  { to: "/officines", label: "Tableau de bord", icon: LayoutDashboard, end: true },
  { to: "/officines/inventory", label: "Inventaire", icon: Boxes },
  { to: "/officines/secret", label: "Clé HMAC", icon: KeyRound },
  { to: "/officines/history", label: "Historique", icon: History },
];

export default function OfficineLayout() {
  const navigate = useNavigate();
  const { officine, token } = loadOfficineSession();

  React.useEffect(() => {
    if (!token) navigate("/officines/login", { replace: true });
  }, [token, navigate]);

  const handleLogout = () => {
    clearOfficineSession();
    navigate("/officines/login", { replace: true });
  };

  if (!token) return null;

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-[#0E1F3D] text-white">
        <div className="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <img src={LOGO_URL} alt="SAWALI" className="h-9 w-9 rounded-md object-cover ring-1 ring-white/20" />
            <div>
              <p className="text-xs uppercase tracking-[0.25em] text-sky-200">Portail Officines</p>
              <p className="font-display font-bold text-base" data-testid="officine-name">{officine?.name || "Pharmacie"}</p>
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md bg-white/10 hover:bg-white/20 ring-1 ring-white/20 transition"
            data-testid="officine-logout-btn"
          >
            <LogOut className="h-3.5 w-3.5" /> Se déconnecter
          </button>
        </div>
        <nav className="max-w-6xl mx-auto px-4 flex gap-1 overflow-x-auto" data-testid="officine-tabs">
          {TABS.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `inline-flex items-center gap-1.5 px-3 py-2 text-sm border-b-2 transition ${
                  isActive ? "border-sky-300 text-white" : "border-transparent text-white/70 hover:text-white"
                }`
              }
              data-testid={`officine-tab-${to.replace(/\//g, "-")}`}
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="max-w-6xl mx-auto px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
