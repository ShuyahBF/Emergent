import React, { useEffect, useState } from "react";
import { NavLink, useNavigate, Outlet, Link, useLocation } from "react-router-dom";
import {
  LayoutDashboard, Calendar, FileText, Wrench, Users,
  Settings, LogOut, Menu, X, Inbox, Mail, ShieldCheck, Boxes, FileEdit, Star, Briefcase, Newspaper, Send, Activity, Globe2, ShieldAlert, History, GraduationCap, Bug, HeartPulse, Database, Link2, MessageCircle, MessageSquare, Zap, Shield, Wand2, FolderOpen, BarChart3, Wallet, Receipt, ShoppingBag, Banknote, Ticket, Tag, Bell, BellOff, Volume2, VolumeX, Bot, Megaphone, ClipboardList,
} from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { LOGO_URL } from "@/lib/brand";
import { apiClient } from "@/lib/api";
import AdBannerSlot from "@/components/AdBannerSlot";
import { toast } from "sonner";
import IncidentBanner from "@/components/IncidentBanner";
import DemoBanner from "@/components/DemoBanner";
import VersionStamp from "@/components/VersionStamp";
import InternalChatPanel from "@/components/InternalChatPanel";
import TicketsBubble from "@/components/TicketsBubble";
import LiluvineLiveToast from "@/components/LiluvineLiveToast";
import { useWhatsAppNotifier } from "@/hooks/useWhatsAppNotifier";
import { useActivityFeedNotifier } from "@/hooks/useActivityFeedNotifier";
import { useTicketNotifier } from "@/hooks/useTicketNotifier";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import WelcomeBriefing, { shouldShowWelcomeBriefing } from "@/components/WelcomeBriefing";

const BACKEND = process.env.REACT_APP_BACKEND_URL || "";
function absoluteUrl(u) {
  if (!u) return u;
  if (u.startsWith("http")) return u;
  return `${BACKEND}${u.startsWith("/") ? "" : "/"}${u}`;
}

const clientLinks = [
  { to: "/portal", label: "Tableau de bord", icon: LayoutDashboard, end: true },
  { to: "/portal/appointments", label: "Mes rendez-vous", icon: Calendar, module: "appointments" },
  { to: "/portal/documents", label: "Documentation", icon: FileText, module: "documents" },
  { to: "/portal/interventions", label: "Historique interventions", icon: Wrench, module: "interventions" },
  { to: "/portal/users", label: "Suivi utilisateurs", icon: Users },
  { to: "/portal/formations", label: "Formations Spécialisées", icon: GraduationCap, trackedOnly: true, module: "formations" },
  { to: "/portal/notes/reports", label: "Mes rapports", icon: FileEdit, module: "reports" },
  { to: "/portal/notes/suivis", label: "Mes suivis", icon: FileEdit, module: "suivis" },
  { to: "/portal/forms", label: "Formulaires", icon: FileText },
  { to: "/portal/contacts", label: "Centre de Messagerie", icon: MessageCircle, module: "contacts_unread", noMarkSeen: true },
  // Iter38i — Unified omnichannel inbox (WhatsApp + Messenger)
  { to: "/portal/inbox", label: "Inbox unifiée (WA + Messenger)", icon: MessageCircle },
  { to: "/portal/sms", label: "SMS — Masse & Planif.", icon: Send, module: "sms" },
  { to: "/portal/whatsapp-bulk", label: "WhatsApp — Masse & Planif.", icon: MessageCircle, module: "whatsapp" },
  // Iter38r-fix9p — Sidebar entry "Mes paiements" retirée (page accessible
  // via /portal/cash → onglet Reçus + bouton Mobile Money). La route reste
  // active pour les liens directs (emails de confirmation, etc.).
  { to: "/portal/cash", label: "Caisse/Facturation", icon: Banknote, cashOnly: true },
  { to: "/portal/hr", label: "GRH — Ressources Humaines", icon: Users, hrOnly: true },
  // Iter38h — Meta integration (Pages + Messenger + Ads). Shown only if at
  // least one of the three meta_* features is enabled for the tenant.
  { to: "/portal/meta", label: "Meta (Facebook/Messenger/Ads)", icon: MessageCircle, metaOnly: true },
  { to: "/portal/tickets", label: "Tickets", icon: Ticket, badgeKey: "tickets_pending" },
  { to: "/portal/media-library", label: "Bibliothèque de médias", icon: FolderOpen },
  { to: "/portal/media-generator", label: "Générateur d'Images et Vidéos", icon: Wand2 },
  { to: "/portal/voice-studio", label: "Voice Studio (Clonage)", icon: Volume2 },
  // Iter38n — Catalog analytics cockpit (admin/sup/tracked users)
  { to: "/portal/catalog-stats", label: "Statistiques catalogue", icon: BarChart3, catalogStatsOnly: true },
  // Iter38r-fix6/7 — Liluvine PRO (visible mais grisé si ai_liluvine_pro = false)
  { to: "/portal/liluvine", label: "Liluvine PRO (Assistant IA)", icon: Bot, featureGate: "ai_liluvine_pro" },
  // S-iter39b — PV de réunions internes (autonumérotés, impression/PDF)
  { to: "/portal/meetings", label: "PV de réunions", icon: ClipboardList },
  // S-iter39b — Brochures & Guides accessible aux modérateurs (lecture en
  // ligne via la visionneuse PDF interne ; téléchargement réservé admin/sup).
  { to: "/portal/brochures", label: "Brochures & Guides", icon: FileText, moderationOnly: true },
];

const adminLinks = [
  { to: "/admin", label: "Tableau de bord", icon: LayoutDashboard, end: true },
  { to: "/admin/clients", label: "Clients", icon: Users, module: "admin_clients" },
  { to: "/admin/usage", label: "Usage & Facturation", icon: BarChart3 },
  { to: "/admin/appointments", label: "Rendez-vous", icon: Calendar, module: "admin_appointments" },
  { to: "/admin/interventions", label: "Interventions", icon: Wrench, module: "admin_interventions", badgeKey: "tickets_pending" },
  { to: "/admin/documents", label: "Documents", icon: FileText },
  { to: "/admin/forms", label: "Formulaires", icon: FileEdit },
  { to: "/admin/messaging", label: "Messagerie WhatsApp", icon: MessageCircle },
  { to: "/admin/whatsapp-templates", label: "Templates WhatsApp", icon: FileEdit },
  { to: "/admin/automations", label: "Automations", icon: Zap },
  { to: "/admin/liluvine-history", label: "Liluvine PRO — Historique", icon: Bot },
  { to: "/admin/policies", label: "Politiques publiques", icon: Shield },
  { to: "/admin/formations", label: "Formations", icon: GraduationCap },
  { to: "/admin/contents", label: "Contenus du site", icon: FileEdit },
  { to: "/admin/case-studies", label: "Études de cas", icon: Briefcase },
  { to: "/admin/blog", label: "Blog", icon: Newspaper },
  { to: "/admin/subscriptions", label: "Abonnements", icon: Tag },
  { to: "/admin/newsletter", label: "Newsletter", icon: Send },
  { to: "/admin/visits", label: "Trafic & Visites", icon: Activity, module: "admin_visits" },
  { to: "/admin/deployments", label: "Déploiements", icon: Globe2 },
  { to: "/admin/blacklist", label: "Blacklist IP", icon: ShieldAlert },
  { to: "/admin/access-logs", label: "Logs d'accès", icon: History, module: "admin_access_logs" },
  { to: "/admin/api-traces", label: "Traces API (debug)", icon: Bug, superAdminOnly: true, module: "admin_api_traces" },
  { to: "/admin/sms-dashboard", label: "Tableau de bord SMS", icon: MessageSquare },
  { to: "/admin/health", label: "Santé applicative", icon: HeartPulse, superAdminOnly: true },
  { to: "/admin/db-explorer", label: "Explorateur DB", icon: Database, superAdminOnly: true },
  { to: "/admin/integration-links", label: "Liens cryptés", icon: Link2, superAdminOnly: true },
  { to: "/admin/contacts", label: "Messages reçus", icon: Inbox, module: "admin_contacts" },
  { to: "/admin/testimonials", label: "Témoignages NPS", icon: Star, module: "admin_testimonials" },
  { to: "/admin/tracked-users", label: "Utilisateurs suivis", icon: Boxes },
  // Iter38r-fix9p — Direct link to the 3 generated brochures (PDFs)
  { to: "/admin/brochures", label: "Brochures & Guide", icon: FileText },
  // Iter38r-fix9r — Home Assistant voice notifications
  { to: "/admin/voice-notifications", label: "Notifications vocales (HA)", icon: Volume2 },
  // Iter38r-fix9w — Ad banner monetization
  { to: "/admin/ad-banners", label: "Régie publicitaire", icon: Megaphone },
  { to: "/admin/settings", label: "Paramètres", icon: Settings, module: "admin_profile_requests", noMarkSeen: true },
];

export default function PortalLayout({ admin = false }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [branding, setBranding] = useState(null);
  const [badges, setBadges] = useState({});
  // Iter35o — Pending tickets count is fetched from a dedicated endpoint
  // (count is per-client scope, not "unseen" semantics like other badges).
  const [ticketsPending, setTicketsPending] = useState(0);
  // Iter38h — Tenant meta features (loaded from /me/features)
  const [metaEnabled, setMetaEnabled] = useState(false);
  // Iter38r-fix7 — Full features object for per-link gate (visible-but-disabled)
  const [tenantFeatures, setTenantFeatures] = useState({});
  useEffect(() => {
    apiClient.get("/me/features").then((r) => {
      const f = r.data?.features || r.data || {};
      setMetaEnabled(!!(f.meta_pages || f.meta_messenger || f.meta_ads));
      setTenantFeatures(f);
    }).catch(() => {});
  }, []);
  const isTracked = !!user?.tracked_user_id || !!user?.tracked_role;
  const isSuperAdmin = (user?.email || "").toLowerCase() === "admin@sawalismartsystems.com";
  const isAdminOrSup = user?.role === "admin" || user?.role === "superviseur";
  const canCash = !!user?.can_cash || isAdminOrSup;
  const isComptable = (user?.tracked_role || "") === "Comptable";
  const canHR = isAdminOrSup || isComptable;
  // Iter38r-fix4 — Comptables (non-admin) ne voient QUE Caisse/Facturation
  // + GRH. Toutes les autres options du menu sont masquées (demande user).
  const isComptaStrict = isComptable && !isAdminOrSup;
  // S-iter39b — Modérateurs (tracked_role="Moderation") accèdent à Brochures
  const isModerator = (user?.tracked_role || "") === "Moderation";
  const allowedComptaPaths = new Set(["/portal/cash", "/portal/hr"]);
  const links = (admin ? adminLinks : clientLinks)
    .filter((l) => !isComptaStrict || allowedComptaPaths.has(l.to))
    .filter((l) => !l.trackedOnly || isTracked)
    .filter((l) => !l.superAdminOnly || isSuperAdmin)
    .filter((l) => !l.cashOnly || canCash || isComptable)
    .filter((l) => !l.hrOnly || canHR)
    .filter((l) => !l.metaOnly || metaEnabled || isAdminOrSup)
    .filter((l) => !l.cashAdminOnly || isAdminOrSup)
    .filter((l) => !l.moderationOnly || isModerator || isAdminOrSup)
    // Iter38n — Catalog stats visible to admin/sup/tracked users
    .filter((l) => !l.catalogStatsOnly || isAdminOrSup || isTracked);

  // Fetch badge counts on mount + whenever we navigate (so opening a page
  // that was counted refreshes the list). Also refresh every 90s.
  const refreshBadges = React.useCallback(async () => {
    if (!user) return;
    try {
      const r = await apiClient.get("/me/notifications/counts");
      setBadges(r.data?.counts || {});
    } catch { /* noop */ }
    // Iter35o — Pending tickets (non-closed) — best effort, ignore errors
    try {
      const r2 = await apiClient.get("/me/tickets/pending-count");
      setTicketsPending(r2.data?.count || 0);
    } catch { /* noop */ }
  }, [user]);

  useEffect(() => { refreshBadges(); }, [refreshBadges, location.pathname]);
  useEffect(() => {
    const t = setInterval(refreshBadges, 90000);
    return () => clearInterval(t);
  }, [refreshBadges]);

  // When user navigates to a page that has a module, mark it as seen.
  useEffect(() => {
    if (!user) return;
    const match = [...adminLinks, ...clientLinks].find((l) =>
      l.module && (l.end ? location.pathname === l.to : location.pathname === l.to || location.pathname.startsWith(l.to + "/"))
    );
    if (match?.module && !match?.noMarkSeen) {
      apiClient.post("/me/notifications/mark-seen", { module: match.module })
        .then(() => refreshBadges())
        .catch(() => {});
    }
  }, [user, location.pathname, refreshBadges]);

  useEffect(() => {
    if (!user) navigate("/login");
    if (admin && user && user.role !== "admin") navigate("/portal");
  }, [user, admin, navigate]);

  // Web Notifications + son sur nouveaux WA
  const waNotifier = useWhatsAppNotifier();
  // Iter34x — toasts live des actions des autres utilisateurs liés
  useActivityFeedNotifier(!!user);
  // Iter36b — toasts + son sur nouveaux tickets / changements de statut
  useTicketNotifier(!!user);

  // Access log every page change for any logged-in portal user
  useEffect(() => {
    if (!user) return;
    const path = location.pathname;
    // Resolve a friendly module label from the matching link
    const match = [...adminLinks, ...clientLinks].find((l) =>
      l.end ? path === l.to : path === l.to || path.startsWith(l.to + "/")
    );
    const moduleLabel = match?.label || (path.startsWith("/admin") ? "Admin" : "Portail");
    apiClient.post("/me/access-log", { module: moduleLabel, page: path }).catch(() => {});
  }, [user, location.pathname]);

  useEffect(() => {
    // Fetch client branding (logo) only for non-admin (client portal)
    if (!admin && user) {
      apiClient.get("/me/branding").then((r) => setBranding(r.data)).catch(() => {});
    }
  }, [admin, user]);

  // Iter35r — Welcome briefing modal: shown once per session after login
  const [showBriefing, setShowBriefing] = useState(false);
  useEffect(() => {
    if (user && shouldShowWelcomeBriefing()) {
      setShowBriefing(true);
    }
  }, [user]);

  if (!user) return null;

  // For client portal : prefer client logo when available; admin always sees SAWALI brand.
  const useClientLogo = !admin && branding?.logo_url;
  const displayedLogo = useClientLogo ? absoluteUrl(branding.logo_url) : LOGO_URL;
  const displayedName = useClientLogo ? (branding.company || user.company || user.full_name) : "SAWALI";
  const displayedSubtitle = admin ? "Admin Console" : (useClientLogo ? "Espace Loois" : "Espace Loois");

  const SidebarContent = (
    <>
      <Link to="/" className="flex items-center gap-3 mb-8 px-2">
        <img src={displayedLogo} alt={displayedName} className={`h-10 w-10 ${useClientLogo ? "rounded-md object-contain bg-white/95 p-1" : "rounded-md object-cover"} ring-1 ring-white/20`} />
        <div className="min-w-0">
          <p className="font-display font-bold text-white text-sm truncate" title={displayedName}>{displayedName}</p>
          <p className="text-[9px] uppercase tracking-[0.25em] text-sawali-blue-light">
            {displayedSubtitle}
          </p>
        </div>
      </Link>
      <nav className="space-y-1">
        {links.map(({ to, label, icon: Icon, end, module, soon, badgeKey, featureGate }) => {
          const count = module ? (badges[module] || 0) : 0;
          const liveCount = badgeKey === "tickets_pending" ? ticketsPending : 0;
          // Iter38r-fix7 — Feature-gated links stay visible but greyed out
          // and unclickable when the parent admin's feature is OFF.
          const featureDisabled = featureGate && !tenantFeatures[featureGate];
          return (
            <NavLink
              key={to}
              to={featureDisabled ? "#" : to}
              end={end}
              onClick={(e) => {
                if (featureDisabled) {
                  e.preventDefault();
                  toast.info(`Fonctionnalité « ${label} » non activée — contactez votre administrateur SAWALI.`);
                  return;
                }
                setOpen(false);
              }}
              className={({ isActive }) =>
                featureDisabled
                  ? "sidebar-link opacity-40 cursor-not-allowed group"
                  : `sidebar-link ${isActive ? "active" : ""} group`
              }
              data-testid={`sidebar-link-${to.replace(/\//g, "-")}`}
              title={featureDisabled ? `${label} (non activé)` : undefined}
            >
              <Icon className="h-4 w-4" />
              <span className="flex-1 truncate">{label}</span>
              {featureDisabled && (
                <span
                  className="text-[8px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded bg-slate-500/30 text-slate-300 ring-1 ring-slate-500/40"
                  data-testid={`badge-disabled-${to.replace(/\//g, "-")}`}
                  title="Non activé"
                >
                  OFF
                </span>
              )}
              {soon && (
                <span
                  className="text-[8px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-200 ring-1 ring-amber-400/30"
                  data-testid={`badge-soon-${to.replace(/\//g, "-")}`}
                  title="Bientôt disponible"
                >
                  Bientôt
                </span>
              )}
              {count > 0 && (
                <span
                  className="inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full bg-rose-500 text-white text-[10px] font-bold tabular-nums ring-2 ring-[#0E1F3D] animate-in fade-in slide-in-from-right-1"
                  data-testid={`badge-${module}`}
                  title={`${count} nouveau(x) élément(s)`}
                >
                  {count > 99 ? "99+" : count}
                </span>
              )}
              {liveCount > 0 && (
                <span
                  className="inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full bg-amber-500 text-white text-[10px] font-bold tabular-nums ring-2 ring-[#0E1F3D]"
                  data-testid={`badge-${badgeKey}`}
                  title={`${liveCount} ticket(s) en cours`}
                >
                  {liveCount > 99 ? "99+" : liveCount}
                </span>
              )}
            </NavLink>
          );
        })}
      </nav>

      <div className="mt-8 border-t border-white/10 pt-4">
        <NavLink
          to="/portal/my-account"
          onClick={() => setOpen(false)}
          className="block px-3 py-2 rounded-lg hover:bg-white/5 transition group"
          data-testid="account-menu-link"
        >
          <p className="text-xs text-slate-400 group-hover:text-sawali-blue-light transition">Connecté en tant que</p>
          <p className="text-sm text-white truncate">{user.full_name}</p>
          <p className="text-xs text-sawali-blue-light truncate">{user.email}</p>
          <p className="text-[10px] text-slate-500 mt-0.5 group-hover:text-slate-300 transition">→ Voir mon compte</p>
        </NavLink>
        <div className="px-3 py-2 mt-1 rounded-lg bg-white/5 ring-1 ring-white/10 space-y-1.5" data-testid="wa-notifier-controls">
          <p className="text-[10px] uppercase tracking-wider text-slate-400 inline-flex items-center gap-1.5">
            <Bell className="h-3 w-3" /> Alerte WhatsApp
            {waNotifier.unread > 0 && (
              <span className="inline-flex items-center justify-center min-w-[16px] h-[16px] px-1 rounded-full bg-rose-500 text-white text-[9px] font-bold tabular-nums" data-testid="wa-notifier-count">
                {waNotifier.unread > 99 ? "99+" : waNotifier.unread}
              </span>
            )}
          </p>
          <div className="flex gap-1">
            <button
              onClick={waNotifier.toggleDesktop}
              className={`flex-1 inline-flex items-center justify-center gap-1 text-[10px] rounded px-1.5 py-1 ring-1 transition-colors ${waNotifier.desktopOn ? "bg-emerald-500/20 text-emerald-200 ring-emerald-400/40" : "bg-white/5 text-slate-400 ring-white/10 hover:bg-white/10"}`}
              data-testid="wa-notifier-desktop-toggle"
              title={waNotifier.permission === "denied" ? "Bloqué par le navigateur — réautorisez les notifications dans les paramètres" : (waNotifier.desktopOn ? "Désactiver les notifications" : "Activer les notifications")}
            >
              {waNotifier.desktopOn ? <Bell className="h-3 w-3" /> : <BellOff className="h-3 w-3" />}
              {waNotifier.desktopOn ? "Notif" : "Off"}
            </button>
            <button
              onClick={waNotifier.toggleSound}
              disabled={!waNotifier.soundAllowedByAdmin}
              className={`flex-1 inline-flex items-center justify-center gap-1 text-[10px] rounded px-1.5 py-1 ring-1 transition-colors ${!waNotifier.soundAllowedByAdmin ? "bg-white/5 text-slate-500 ring-white/10 cursor-not-allowed opacity-50" : (waNotifier.soundOn ? "bg-amber-500/20 text-amber-200 ring-amber-400/40" : "bg-white/5 text-slate-400 ring-white/10 hover:bg-white/10")}`}
              data-testid="wa-notifier-sound-toggle"
              title={!waNotifier.soundAllowedByAdmin ? "Son désactivé par l'administrateur du client" : (waNotifier.soundOn ? "Couper le son" : "Activer le son")}
            >
              {!waNotifier.soundAllowedByAdmin || !waNotifier.soundOn ? <VolumeX className="h-3 w-3" /> : <Volume2 className="h-3 w-3" />}
              {!waNotifier.soundAllowedByAdmin ? "Bloqué" : (waNotifier.soundOn ? "Son" : "Muet")}
            </button>
          </div>
          {waNotifier.permission === "default" && waNotifier.desktopOn && (
            <button
              onClick={waNotifier.requestPermission}
              className="w-full text-[10px] bg-sawali-blue text-white rounded px-2 py-1 hover:bg-sawali-blue-light"
              data-testid="wa-notifier-permission-btn"
            >
              Autoriser les notifications
            </button>
          )}
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
    <div className="h-screen bg-slate-50 flex overflow-hidden">
      {/* Desktop sidebar — full screen height, never moves; its own scroll
          when the menu is taller than the viewport. Using a non-sticky
          shell prevents the "pinned-then-truncated" bug some browsers
          exhibit with `position: sticky` inside a flex row. */}
      <aside className="hidden lg:flex flex-col shrink-0 w-72 bg-[#0E1F3D] p-5 h-screen overflow-y-auto" data-testid="portal-sidebar">
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

      {/* Main column scrolls independently — keeps the sidebar perfectly stable. */}
      <div className="flex-1 flex flex-col min-w-0 h-screen overflow-y-auto overflow-x-hidden">
        <DemoBanner />
        <IncidentBanner />
        <header className="lg:hidden sticky top-0 z-40 bg-white border-b flex items-center justify-between px-4 h-14">
          <button onClick={() => setOpen(true)} aria-label="Menu" data-testid="portal-menu-toggle">
            <Menu className="h-5 w-5" />
          </button>
          <div className="flex items-center gap-2">
            {admin ? <ShieldCheck className="h-4 w-4 text-sawali-blue" /> : <Mail className="h-4 w-4 text-sawali-blue" />}
            <span className="font-display font-semibold text-sm">{admin ? "Admin SAWALI" : "Espace Loois"}</span>
          </div>
          <div className="w-5" />
        </header>
        {/* Iter38r-fix9w — Monetized ad banner slot at the top of the portal */}
        <AdBannerSlot placement="portal" />
        <main className="flex-1 p-3 sm:p-6 lg:p-10 min-w-0 max-w-full">
          <ErrorBoundary name={`portal:${location.pathname}`} resetKey={location.pathname}>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
      <VersionStamp tone="dark" />
      {showBriefing && <WelcomeBriefing onClose={() => setShowBriefing(false)} isComptaStrict={isComptaStrict} />}
      {/* Iter38r-fix7 — Comptable strict: hide the internal chat bubble entirely. */}
      {!isComptaStrict && <InternalChatPanel />}
      <TicketsBubble />
      {/* Iter38r-fix9e — Live toast for Liluvine WhatsApp auto-replies (admins + superviseurs only). */}
      {isAdminOrSup && <LiluvineLiveToast />}
    </div>
  );
}
