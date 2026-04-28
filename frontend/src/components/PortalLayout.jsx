import React, { useEffect, useState } from "react";
import { NavLink, useNavigate, Outlet, Link } from "react-router-dom";
import {
  LayoutDashboard, Calendar, FileText, Wrench, Users,
  Settings, LogOut, Menu, X, Inbox, Mail, ShieldCheck, Boxes, FileEdit, Star, Briefcase, Newspaper, Send, Activity, Globe2,
} from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { LOGO_URL } from "@/lib/brand";

const clientLinks = [
  { to: "/portal", label: "Tableau de bord", icon: LayoutDashboard, end: true },
  { to: "/portal/appointments", label: "Mes rendez-vous", icon: Calendar },
  { to: "/portal/documents", label: "Documentation", icon: FileText },
  { to: "/portal/interventions", label: "Historique interventions", icon: Wrench },
  { to: "/portal/users", label: "Suivi utilisateurs", icon: Users },
];

const adminLinks = [
  { to: "/admin", label: "Tableau de bord", icon: LayoutDashboard, end: true },
  { to: "/admin/clients", label: "Clients", icon: Users },
  { to: "/admin/appointments", label: "Rendez-vous", icon: Calendar },
  { to: "/admin/interventions", label: "Interventions", icon: Wrench },
  { to: "/admin/documents", label: "Documents", icon: FileText },
  { to: "/admin/contents", label: "Contenus du site", icon: FileEdit },
  { to: "/admin/case-studies", label: "Études de cas", icon: Briefcase },
  { to: "/admin/blog", label: "Blog", icon: Newspaper },
  { to: "/admin/newsletter", label: "Newsletter", icon: Send },
  { to: "/admin/visits", label: "Trafic & Visites", icon: Activity },
  { to: "/admin/deployments", label: "Déploiements", icon: Globe2 },
  { to: "/admin/contacts", label: "Messages reçus", icon: Inbox },
  { to: "/admin/testimonials", label: "Témoignages NPS", icon: Star },
  { to: "/admin/tracked-users", label: "Utilisateurs suivis", icon: Boxes },
  { to: "/admin/settings", label: "Paramètres", icon: Settings },
];

export default function PortalLayout({ admin = false }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const links = admin ? adminLinks : clientLinks;

  useEffect(() => {
    if (!user) navigate("/login");
    if (admin && user && user.role !== "admin") navigate("/portal");
  }, [user, admin, navigate]);

  if (!user) return null;

  const SidebarContent = (
    <>
      <Link to="/" className="flex items-center gap-3 mb-8 px-2">
        <img src={LOGO_URL} alt="SAWALI" className="h-10 w-10 rounded-md object-cover ring-1 ring-white/20" />
        <div>
          <p className="font-display font-bold text-white text-sm">SAWALI</p>
          <p className="text-[9px] uppercase tracking-[0.25em] text-sawali-blue-light">
            {admin ? "Admin Console" : "Espace Client"}
          </p>
        </div>
      </Link>
      <nav className="space-y-1">
        {links.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            onClick={() => setOpen(false)}
            className={({ isActive }) => `sidebar-link ${isActive ? "active" : ""}`}
            data-testid={`sidebar-link-${to.replace(/\//g, "-")}`}
          >
            <Icon className="h-4 w-4" />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="mt-8 border-t border-white/10 pt-4">
        <div className="px-3 py-2">
          <p className="text-xs text-slate-400">Connecté en tant que</p>
          <p className="text-sm text-white truncate">{user.full_name}</p>
          <p className="text-xs text-sawali-blue-light truncate">{user.email}</p>
        </div>
        <button
          onClick={() => { logout(); navigate("/"); }}
          className="sidebar-link w-full text-left mt-2"
          data-testid="logout-button"
        >
          <LogOut className="h-4 w-4" />
          Se déconnecter
        </button>
      </div>
    </>
  );

  return (
    <div className="min-h-screen bg-slate-50 flex">
      {/* Desktop sidebar */}
      <aside className="hidden lg:block w-72 bg-[#0E1F3D] p-5 sticky top-0 h-screen overflow-y-auto" data-testid="portal-sidebar">
        {SidebarContent}
      </aside>

      {/* Mobile drawer */}
      {open && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
          <aside className="relative w-72 bg-[#0E1F3D] p-5 h-full overflow-y-auto">
            {SidebarContent}
          </aside>
        </div>
      )}

      <div className="flex-1 flex flex-col min-w-0">
        <header className="lg:hidden sticky top-0 z-40 bg-white border-b flex items-center justify-between px-4 h-14">
          <button onClick={() => setOpen(true)} aria-label="Menu" data-testid="portal-menu-toggle">
            <Menu className="h-5 w-5" />
          </button>
          <div className="flex items-center gap-2">
            {admin ? <ShieldCheck className="h-4 w-4 text-sawali-blue" /> : <Mail className="h-4 w-4 text-sawali-blue" />}
            <span className="font-display font-semibold text-sm">{admin ? "Admin SAWALI" : "Espace Client SAWALI"}</span>
          </div>
          <div className="w-5" />
        </header>
        <main className="flex-1 p-4 sm:p-6 lg:p-10">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
