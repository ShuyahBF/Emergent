import React, { useEffect, useState } from "react";
import { NavLink, useNavigate, Outlet, Link, useLocation } from "react-router-dom";
import {
  LayoutDashboard, Calendar, FileText, Wrench, Users,
  Settings, LogOut, Menu, X, Inbox, Mail, ShieldCheck, Boxes, FileEdit, Star, Briefcase, Newspaper, Send, Activity, Globe2, ShieldAlert, History, GraduationCap, Bug, HeartPulse, Database, Link2, MessageCircle, MessageSquare, Zap, Shield, Wand2, FolderOpen, BarChart3, Wallet, Receipt, ShoppingBag, Banknote, Ticket, Tag, Bell, BellOff, Volume2, VolumeX, Bot, Megaphone, ClipboardList, ScrollText, Languages, AlertOctagon, AlertTriangle, Sparkles, CircleDollarSign, Factory,
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
import LanguageSelector from "@/components/LanguageSelector";
import { useT } from "@/contexts/I18nContext";
import BrowserNotifications from "@/components/BrowserNotifications";
import WeatherWidget from "@/components/WeatherWidget";
import { useWhatsAppNotifier } from "@/hooks/useWhatsAppNotifier";
import WaSoundPreferences from "@/components/WaSoundPreferences";
import { useActivityFeedNotifier } from "@/hooks/useActivityFeedNotifier";
import { useTicketNotifier } from "@/hooks/useTicketNotifier";
import { useErrorRegistryNotifier } from "@/hooks/useErrorRegistryNotifier";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import WelcomeBriefing, { shouldShowWelcomeBriefing } from "@/components/WelcomeBriefing";

const BACKEND = process.env.REACT_APP_BACKEND_URL || "";
function absoluteUrl(u) {
  if (!u) return u;
  if (u.startsWith("http")) return u;
  return `${BACKEND}${u.startsWith("/") ? "" : "/"}${u}`;
}

const clientLinks = [
  { to: "/portal", label: "Tableau de bord", tKey: "nav.dashboard", icon: LayoutDashboard, end: true },
  { to: "/portal/appointments", label: "Mes rendez-vous", tKey: "nav.appointments", icon: Calendar, module: "appointments" },
  { to: "/portal/documents", label: "Documentation", tKey: "nav.documentation", icon: FileText, module: "documents" },
  { to: "/portal/interventions", label: "Historique interventions", tKey: "nav.interventions", icon: Wrench, module: "interventions" },
  { to: "/portal/users", label: "Suivi utilisateurs", tKey: "nav.users_tracking", icon: Users },
  { to: "/portal/formations", label: "Formations Spécialisées", icon: GraduationCap, trackedOnly: true, module: "formations" },
  { to: "/portal/notes/reports", label: "Mes rapports", tKey: "nav.reports", icon: FileEdit, module: "reports" },
  { to: "/portal/notes/suivis", label: "Mes suivis", tKey: "nav.followups", icon: FileEdit, module: "suivis" },
  { to: "/portal/forms", label: "Formulaires", tKey: "nav.forms", icon: FileText },
  { to: "/portal/contacts", label: "Centre de Messagerie", tKey: "nav.contacts", icon: MessageCircle, module: "contacts_unread", noMarkSeen: true },
  { to: "/portal/contact-groups", label: "Groupes de contacts", icon: Users },
  { to: "/portal/error-registry", label: "Registre des erreurs", icon: AlertOctagon, showBadges: true },
  // Iter38i — Unified omnichannel inbox (WhatsApp + Messenger)
  { to: "/portal/inbox", label: "Inbox unifiée (WA + Messenger)", icon: MessageCircle },
  { to: "/portal/sms", label: "SMS — Masse & Planif.", icon: Send, module: "sms" },
  { to: "/portal/whatsapp-bulk", label: "WhatsApp — Masse & Planif.", icon: MessageCircle, module: "whatsapp" },
  // Iter38r-fix9p — Sidebar entry "Mes paiements" retirée (page accessible
  // via /portal/cash → onglet Reçus + bouton Mobile Money). La route reste
  // active pour les liens directs (emails de confirmation, etc.).
  { to: "/portal/cash", label: "Caisse/Facturation", icon: Banknote, cashOnly: true },
  // Iter42f (2026-02) — Restauration du lien "Catalogue" retiré par erreur
  // le 23 mai 2026 lors du regroupement Caisse/Facturation. La route
  // existe toujours et délègue à CashBilling avec defaultTab="catalog".
  // Accessible aux admin/superviseur + comptables (cashAdminOnly).
  { to: "/portal/catalog", label: "Catalogue (produits & analytics)", icon: ShoppingBag, cashAdminOnly: true },
  { to: "/portal/hr", label: "GRH — Ressources Humaines", icon: Users, hrOnly: true },
  // Iter43-fix24az-f (2026-02-26) — Production module for Fabricant tenants
  // (visible only when business_type='fabricant' AND role admin/superviseur).
  { to: "/portal/production", label: "Production", icon: Factory, fabricantOnly: true, adminOrSup: true },
  // Iter43-fix24az-m (2026-07-18) — Planning des consultations médecins (RDV temps réel)
  // Visible pour tous ; les utilisateurs suivis "Médecin" verront UNIQUEMENT ce lien.
  { to: "/portal/planning", label: "Planning consultations", icon: Calendar },
  // Iter38h — Meta integration (Pages + Messenger + Ads). Shown only if at
  // least one of the three meta_* features is enabled for the tenant.
  { to: "/portal/meta", label: "Meta (Facebook/Messenger/Ads)", icon: MessageCircle, metaOnly: true },
  { to: "/portal/tickets", label: "Tickets", tKey: "nav.tickets", icon: Ticket, badgeKey: "tickets_pending" },
  { to: "/portal/media-library", label: "Bibliothèque de médias", icon: FolderOpen },
  { to: "/portal/media-generator", label: "Générateur d'Images et Vidéos", icon: Wand2 },
  { to: "/portal/voice-studio", label: "Voice Studio (Clonage)", icon: Volume2 },
  // Iter38n — Catalog analytics cockpit (admin/sup/tracked users)
  { to: "/portal/catalog-stats", label: "Statistiques catalogue", icon: BarChart3, catalogStatsOnly: true },
  // Iter38r-fix6/7 — Liluvine PRO (visible mais grisé si ai_liluvine_pro = false)
  { to: "/portal/liluvine", label: "Liluvine PRO (Assistant IA)", tKey: "nav.liluvine", icon: Bot, featureGate: "ai_liluvine_pro" },
  // Iter41 (2026-02) — Module VIDAL France (médicaments / RCP / alertes prescription)
  { to: "/portal/vidal", label: "VIDAL France (médicaments)", icon: HeartPulse, featureGate: "vidal_enabled" },
  // Iter41 Phase 2 — Table AMM (régulateurs / admins / superviseurs)
  { to: "/portal/amm", label: "Numéros AMM (régulateur)", icon: ScrollText, featureGate: "vidal_enabled" },
  // S-iter39b — PV de réunions internes (autonumérotés, impression/PDF)
  { to: "/portal/meetings", label: "PV de réunions", icon: ClipboardList },
  // S-iter39d (fix #2) — Liluvine PRO Historique accessible aux modérateurs
  // (et aux admin/sup pour cohérence avec la sidebar admin)
  { to: "/portal/liluvine-history", label: "Liluvine PRO — Historique", icon: Bot, moderationOnly: true },
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
  { to: "/admin/suggestions", label: "Suggestions (registre S###)", icon: ScrollText },
  { to: "/admin/suggestions-history", label: "Historique des suggestions", icon: History },
  { to: "/admin/download-audit", label: "Téléchargements — Audit (S029)", icon: History },
  { to: "/admin/i18n", label: "Régionalisation", icon: Languages },
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
  // Iter42 — Officines Registry (validation pharmacies inscrites au self-service)
  { to: "/admin/officines-registry", label: "Officines (validation)", icon: HeartPulse, featureGate: "vidal_enabled" },
  // Iter43-fix22 — Planning des gardes (admin/superviseur)
  { to: "/admin/garde-planning", label: "Planning des gardes", icon: Calendar, adminOrSup: true },
  // Iter43-fix22 — Interrogations WhatsApp à Liluvine (admin/moderator/superviseur)
  // Iter43-fix24d — Renommé "Exclamations Reçues" (ne contient que les !commandes).
  { to: "/admin/liluvine-wa-requests", label: "Exclamations Reçues", icon: Inbox, moderatorPlus: true },
  // Iter43-fix24f — Historique des suggestions IA de handlers + dashboard coût Bird
  { to: "/admin/handler-suggestions", label: "Handlers IA", icon: Sparkles, adminOnly: true },
  { to: "/admin/bird-cost", label: "Coût SMS Bird", icon: CircleDollarSign, adminOnly: true },
  { to: "/admin/story-studio", label: "Story Studio (AI)", icon: Sparkles },
  { to: "/admin/settings", label: "Paramètres", icon: Settings, module: "admin_profile_requests", noMarkSeen: true },
];

export default function PortalLayout({ admin = false }) {
  const { user, logout } = useAuth();
  const t = useT();
  const navigate = useNavigate();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [branding, setBranding] = useState(null);
  const [badges, setBadges] = useState({});
  // Iter35o — Pending tickets count is fetched from a dedicated endpoint
  // (count is per-client scope, not "unseen" semantics like other badges).
  const [ticketsPending, setTicketsPending] = useState(0);
  // Iter43-fix24az-aa (2026-07-22) — Live counter for walk-ins waiting TODAY.
  // Shown as a sidebar badge on "Planning consultations" for médecins.
  const [walkInsToday, setWalkInsToday] = useState(0);
  // Iter38h — Tenant meta features (loaded from /me/features)
  const [metaEnabled, setMetaEnabled] = useState(false);
  // Iter38r-fix7 — Full features object for per-link gate (visible-but-disabled)
  const [tenantFeatures, setTenantFeatures] = useState({});
  // Iter43-fix24o (2026-06) — Délégation menu Officines à des non-admin
  const [officinesDelegated, setOfficinesDelegated] = useState(false);
  // Iter43-fix24q — race condition fix : ne pas rediriger avant d'avoir reçu les perms.
  const [permissionsLoaded, setPermissionsLoaded] = useState(false);
  useEffect(() => {
    if (!user) return;
    apiClient.get("/me/officines-permissions")
      .then((r) => {
        setOfficinesDelegated(r.data?.can_view === true && r.data?.edit_mode === "limited");
      })
      .catch(() => setOfficinesDelegated(false))
      .finally(() => setPermissionsLoaded(true));
  }, [user]);
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
  // 2026-02 (#1) — Traducteur : seul accès = /admin/i18n (Régionalisation).
  // Toutes les autres entrées de la sidebar sont masquées. L'utilisateur
  // est forcé d'aller sur Régionalisation au login (route handled in App.js).
  const isTranslator = (user?.tracked_role || "") === "Traducteur";
  // Iter43-fix24az-m (2026-07-18) — Médecin tracked role : accès UNIQUE au
  // planning des consultations. La sidebar ne montre QUE cet item.
  const isMedecinTracked = (user?.tracked_role || "") === "Médecin";
  // 2026-02 fork (P2) — Secrétaire médicale tracked role : accès uniquement
  // au planning consultations (gestion walk-ins). Menu ultra-réduit comme
  // le médecin, mais SANS Analyse prescription.
  const isSecretaireMedicale = (user?.tracked_role || "") === "Secrétaire médicale";
  // Iter42b (2026-02) — Rôles métier réglementaires :
  //   • regulateur     → uniquement /portal/amm + /portal/liluvine
  //   • editeur_vidal  → uniquement /portal/vidal + /portal/amm + /portal/liluvine (lecture seule)
  // /portal/vidal et /portal/amm sont masqués pour tous les rôles SAUF
  // admin, superviseur, regulateur (amm), pharmacien, medecin, editeur_vidal.
  const isRegulateur = user?.role === "regulateur";
  const isEditeurVidal = user?.role === "editeur_vidal";
  const isPharmacien = user?.role === "pharmacien";
  const isMedecin = user?.role === "medecin";
  // Iter43-fix24az-f (2026-02-26) — Business-type Fabricant : sidebar réduite
  const isFabricant = (user?.business_type || "").toLowerCase() === "fabricant";
  // 2026-02 fork iter105 — Sidebar entries Documents/Formations/Formulaires
  // hidden when the user's linked tenant has no accessible items. Fetched once
  // via `/me/access-summary`. Admins/super-admins always see the entries.
  const [accessSummary, setAccessSummary] = React.useState(null);
  React.useEffect(() => {
    if (!user) return;
    apiClient.get("/me/access-summary")
      .then((r) => setAccessSummary(r.data || {}))
      .catch(() => setAccessSummary(null));
  }, [user?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // 2026-02 fork (P4) — Overrides visibilité par tracked user.
  // Résolution : true/false = override explicite ; null/undefined = défaut du rôle.
  // Le "défaut du rôle" : les rôles à sidebar réduite (Comptable strict,
  // Traducteur, Médecin, Secrétaire médicale, Fabricant) ne voient PAS le
  // Dashboard/Welcome/Notifs, tous les autres tracked users OUI.
  const isRestrictedByRoleForDashboard = isComptaStrict || isTranslator || isMedecinTracked || isSecretaireMedicale || isFabricant;
  const p4ShowDashboard = user?.show_dashboard === true
    ? true
    : user?.show_dashboard === false
      ? false
      : !isRestrictedByRoleForDashboard;
  const p4ShowWelcome = user?.show_welcome_modal === true
    ? true
    : user?.show_welcome_modal === false
      ? false
      : !(isFabricant || isMedecinTracked);
  const p4ShowMsgNotifs = user?.show_messaging_notifs === true
    ? true
    : user?.show_messaging_notifs === false
      ? false
      : true;  // par défaut, les notifs sont ON pour tous ceux qui ont accès au portail
  const fabricantAllowedPaths = new Set([
    "/portal/cash",
    "/portal/catalog",
    "/portal/hr",
    "/portal/production",
    "/admin/officines-registry",
  ]);
  const allowedComptaPaths = new Set(["/portal/cash", "/portal/hr"]);
  const allowedTranslatorPaths = new Set(["/admin/i18n"]);
  const allowedMedecinTrackedPaths = new Set([
    "/portal/planning",
    "/portal/prescription-analysis",  // Iter43-fix24az-ac
    "/portal/my-account",
  ]);
  const allowedSecretaireMedicalePaths = new Set([
    "/portal/planning",
    "/portal/my-account",
  ]);
  const allowedRegulateurPaths = new Set(["/portal/amm", "/portal/liluvine"]);
  const allowedEditeurVidalPaths = new Set(["/portal/vidal", "/portal/amm", "/portal/liluvine"]);
  // Paths réservés à certains rôles métier (cachés pour les autres)
  const restrictedVidalPaths = new Set(["/portal/vidal", "/portal/amm"]);
  const canSeeVidal = isAdminOrSup || isRegulateur || isPharmacien || isMedecin || isEditeurVidal;
  const baseLinks = isTranslator
    ? [{ to: "/admin/i18n", label: "Régionalisation", icon: Languages }]
    : (isMedecinTracked
        ? [
            { to: "/portal/planning", label: "Planning consultations", icon: Calendar, badgeKey: "walk_ins_today" },
            // Iter43-fix24az-ac (2026-07-22) — Analyse prescription VIDAL (médecin only)
            // 2026-02 fork P4 — featureGate ajouté pour masquer le lien quand
            // le module VIDAL n'est pas activé sur le tenant du médecin
            // (sinon 403 dead-end en cliquant).
            { to: "/portal/prescription-analysis", label: "Analyse prescription", icon: AlertTriangle, featureGate: "vidal_enabled" },
          ]
        : (isSecretaireMedicale
            ? [
                { to: "/portal/planning", label: "Planning consultations", icon: Calendar, badgeKey: "walk_ins_today" },
              ]
            : (admin ? adminLinks : clientLinks)));
  // Iter43-fix24o — Ajoute le lien "Officines" pour les utilisateurs délégués
  // (non-admin listés dans `officines_menu_allowed_emails`). Visible UNIQUEMENT
  // dans le portail client (admin layout l'affiche déjà via adminLinks).
  // Iter43-fix24az-h (2026-02-26) — Pour les tenants Fabricant : le lien
  // Officines est affiché GRISÉ (disabled) en sidebar plutôt que cliquable.
  const linksWithDelegation = !admin && (officinesDelegated || isFabricant)
    ? [...baseLinks, {
        to: "/admin/officines-registry",
        label: isFabricant ? "Officines" : "Officines",
        icon: HeartPulse,
        officinesDelegated: !isFabricant,
        disabled: isFabricant,
        disabledReason: isFabricant ? "Non disponible pour votre profil Fabricant" : undefined,
        // For fabricant tenants we don't require the delegation-permission
        // toggle : all fabricant admin/sup can view.
      }]
    : baseLinks;
  const links = linksWithDelegation
    .filter((l) => !isComptaStrict || allowedComptaPaths.has(l.to) || (l.to === "/portal" && p4ShowDashboard))
    .filter((l) => !isTranslator || allowedTranslatorPaths.has(l.to) || (l.to === "/portal" && p4ShowDashboard))
    .filter((l) => !isMedecinTracked || allowedMedecinTrackedPaths.has(l.to) || (l.to === "/portal" && p4ShowDashboard))
    .filter((l) => !isRegulateur || allowedRegulateurPaths.has(l.to))
    .filter((l) => !isEditeurVidal || allowedEditeurVidalPaths.has(l.to))
    // Iter43-fix24az-f — Fabricant tenants : allowlist stricte
    .filter((l) => !isFabricant || fabricantAllowedPaths.has(l.to) || (l.to === "/portal" && p4ShowDashboard))
    .filter((l) => !l.fabricantOnly || isFabricant)
    .filter((l) => !restrictedVidalPaths.has(l.to) || canSeeVidal)
    .filter((l) => !l.trackedOnly || isTracked)
    // 2026-02 fork iter105 — Cache Documents / Formations / Formulaires quand
    // le tenant lié n'a rien de visible. Admin/superviseur bypass via `accessSummary=null`
    // (l'endpoint retourne toujours has_XXX=true pour eux).
    .filter((l) => {
      if (!accessSummary) return true;
      if (l.to === "/portal/documents") return accessSummary.has_documents !== false;
      if (l.to === "/portal/formations") return accessSummary.has_formations !== false;
      if (l.to === "/portal/forms") return accessSummary.has_forms !== false;
      return true;
    })
    .filter((l) => !l.superAdminOnly || isSuperAdmin)
    .filter((l) => !l.cashOnly || canCash || isComptable)
    .filter((l) => !l.hrOnly || canHR)
    .filter((l) => !l.metaOnly || metaEnabled || isAdminOrSup)
    .filter((l) => !l.cashAdminOnly || isAdminOrSup)
    .filter((l) => !l.moderationOnly || isModerator || isAdminOrSup)
    .filter((l) => !l.adminOrSup || isAdminOrSup)
    .filter((l) => !l.moderatorPlus || isModerator || isAdminOrSup)
    .filter((l) => !l.catalogStatsOnly || isAdminOrSup || isTracked)
    // 2026-02 fork (P4) — Override de masquage explicite du Tableau de bord
    .filter((l) => l.to !== "/portal" || p4ShowDashboard);

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
    // Iter43-fix24az-aa — Walk-ins waiting TODAY (Planning sidebar badge).
    // Only médecins tracked have "Planning" as their main tab, but we fetch
    // for admins/supervisors too so they see the queue when they open their
    // planning link. Best effort — ignore errors.
    try {
      const r3 = await apiClient.get("/me/planning/counts");
      setWalkInsToday(r3.data?.today_walk_ins_open || 0);
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
    // Iter43-fix24o + 24q — délégation Officines : attendre que les perms soient chargées
    // avant de décider du redirect (sinon race condition → moderator vire vers /portal).
    // Iter43-fix24az-f — Fabricant admin/superviseur peuvent voir /admin/officines-registry.
    if (admin && user && user.role !== "admin" && permissionsLoaded) {
      const onOfficinesRegistry = location.pathname.startsWith("/admin/officines-registry");
      const isFabricantSup = isFabricant && (user.role === "superviseur");
      if (!(onOfficinesRegistry && (officinesDelegated || isFabricantSup))) {
        navigate("/portal");
      }
    }
    // Iter43-fix24az-x (2026-07-22) — Médecin tracked : redirect vers
    // /portal/planning si l'utilisateur se retrouve sur une route non
    // autorisée (ex: /portal, /admin, session stale, deep-link).
    // 2026-02 fork (P4) — Si show_dashboard=true est activé, on autorise le
    // médecin à rester sur /portal (Dashboard) pour la visite explicite.
    if (user && isMedecinTracked && !allowedMedecinTrackedPaths.has(location.pathname)) {
      const dashboardAllowed = location.pathname === "/portal" && p4ShowDashboard;
      if (!dashboardAllowed) {
        navigate("/portal/planning");
      }
    }
  }, [user, admin, navigate, officinesDelegated, permissionsLoaded, location.pathname, isFabricant, isMedecinTracked, p4ShowDashboard]);

  // Web Notifications + son sur nouveaux WA
  // 2026-02 fork (P4) — Coupe la surveillance quand `show_messaging_notifs=false`
  const waNotifier = useWhatsAppNotifier({ enabled: p4ShowMsgNotifs });
  // Iter34x — toasts live des actions des autres utilisateurs liés
  useActivityFeedNotifier(!!user);
  // Iter36b — toasts + son sur nouveaux tickets / changements de statut
  useTicketNotifier(!!user);
  // Iter43-fix2 — Notifications dédiées au Registre des Erreurs
  useErrorRegistryNotifier(!!user);

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

  // Iter35r — Welcome briefing modal: shown once per session after login.
  // Iter43-fix24az-j (2026-02-26) — Skip Welcome for Fabricant tenants (they
  // don't have a dashboard/welcome experience and land directly on /portal/cash).
  // Iter43-fix24az-x (2026-07-22) — Skip Welcome for Médecins tracked too
  // (they land directly on /portal/planning — no dashboard experience).
  // 2026-02 fork (P4) — Override par tracked user via `show_welcome_modal`.
  const [showBriefing, setShowBriefing] = useState(false);
  useEffect(() => {
    if (user && p4ShowWelcome && shouldShowWelcomeBriefing()) {
      setShowBriefing(true);
    }
  }, [user, p4ShowWelcome]);

  if (!user) return null;

  // For client portal : prefer client logo when available; admin always sees SAWALI brand.
  const useClientLogo = !admin && branding?.logo_url;
  const displayedLogo = useClientLogo ? absoluteUrl(branding.logo_url) : LOGO_URL;
  const displayedName = useClientLogo ? (branding.company || user.company || user.full_name) : "SAWALI";
  const displayedSubtitle = admin ? "Admin Console" : (useClientLogo ? "Espace Loois" : "Espace Loois");

  const SidebarContent = (
    <>
      <Link to="/" className="flex items-center gap-3 mb-2 px-2">
        <img src={displayedLogo} alt={displayedName} className={`h-10 w-10 ${useClientLogo ? "rounded-md object-contain bg-white/95 p-1" : "rounded-md object-cover"} ring-1 ring-white/20`} />
        <div className="min-w-0">
          <p className="font-display font-bold text-white text-sm truncate" title={displayedName}>{displayedName}</p>
          <p className="text-[9px] uppercase tracking-[0.25em] text-sawali-blue-light">
            {displayedSubtitle}
          </p>
        </div>
      </Link>
      <div className="px-2 mb-6 flex justify-end" data-testid="sidebar-language-row">
        <LanguageSelector compact />
      </div>
      <div className="px-2 mb-3" data-testid="sidebar-weather-row">
        <WeatherWidget variant="compact" placement="portal" className="w-full justify-start" />
      </div>
      <nav className="space-y-1">
        {links.map(({ to, label, tKey, icon: Icon, end, module, soon, badgeKey, featureGate, showBadges, disabled, disabledReason }) => {
          const rawCount = module ? (badges[module] || 0) : 0;
          // 2026-02 fork (P4) — Masque le badge WA non lu sur "Centre de
          // Messagerie" quand show_messaging_notifs=false.
          const count = (!p4ShowMsgNotifs && module === "contacts_unread") ? 0 : rawCount;
          // Iter43-fix24az-aa — Support additional live counters : tickets_pending
          // (yellow) + walk_ins_today (emerald, only shown to médecins).
          const liveCount = badgeKey === "tickets_pending"
            ? ticketsPending
            : badgeKey === "walk_ins_today"
              ? walkInsToday
              : 0;
          // Iter43-fix (2026-03) — Lit `errors_critical` + `errors_high` en priorité,
          // avec fallback sur les anciens noms `errors_fatale` / `errors_exception`.
          const errorHigh = showBadges ? (badges.errors_high ?? badges.errors_exception ?? 0) : 0;
          const errorCritical = showBadges ? (badges.errors_critical ?? badges.errors_fatale ?? 0) : 0;
          const featureDisabled = featureGate && !tenantFeatures[featureGate];
          // Iter43-fix24az-h — Générique : un lien peut aussi être marqué `disabled`
          // via `disabled: true` (ex. Officines pour tenants Fabricant).
          const isDisabled = featureDisabled || disabled;
          // S046 — translate label if a tKey is provided
          // Iter41 Phase 4b — strip parenthetical hints from sidebar labels
          // (e.g. "VIDAL France (médicaments)" → "VIDAL France")
          const rawLabel = tKey ? t(tKey, label) : label;
          const displayLabel = String(rawLabel || "").replace(/\s*\([^)]*\)/g, "").trim();
          return (
            <NavLink
              key={to}
              to={isDisabled ? "#" : to}
              end={end}
              onClick={(e) => {
                if (featureDisabled) {
                  e.preventDefault();
                  toast.info(`Fonctionnalité « ${displayLabel} » non activée — contactez votre administrateur SAWALI.`);
                  return;
                }
                if (disabled) {
                  e.preventDefault();
                  if (disabledReason) toast.info(disabledReason);
                  return;
                }
                setOpen(false);
              }}
              className={({ isActive }) =>
                isDisabled
                  ? "sidebar-link opacity-40 cursor-not-allowed group"
                  : `sidebar-link ${isActive ? "active" : ""} group`
              }
              data-testid={`sidebar-link-${to.replace(/\//g, "-")}`}
              title={featureDisabled ? `${displayLabel} (non activé)` : (disabled ? (disabledReason || `${displayLabel} (non disponible)`) : undefined)}
            >
              <Icon className="h-4 w-4" />
              <span className="flex-1 truncate">{displayLabel}</span>
              {featureDisabled && (
                <span
                  className="text-[8px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded bg-slate-500/30 text-slate-300 ring-1 ring-slate-500/40"
                  data-testid={`badge-disabled-${to.replace(/\//g, "-")}`}
                  title="Non activé"
                >
                  OFF
                </span>
              )}
              {disabled && !featureDisabled && (
                <span
                  className="text-[8px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded bg-slate-500/30 text-slate-300 ring-1 ring-slate-500/40"
                  data-testid={`badge-disabled-${to.replace(/\//g, "-")}`}
                  title={disabledReason || "Non disponible"}
                >
                  N/A
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
                  className={`inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full text-white text-[10px] font-bold tabular-nums ring-2 ring-[#0E1F3D] ${
                    badgeKey === "walk_ins_today"
                      ? "bg-emerald-500 animate-in fade-in slide-in-from-right-1"
                      : "bg-amber-500"
                  }`}
                  data-testid={`badge-${badgeKey}`}
                  title={
                    badgeKey === "walk_ins_today"
                      ? `${liveCount} patient(s) sans RDV en attente aujourd'hui`
                      : `${liveCount} ticket(s) en cours`
                  }
                >
                  {liveCount > 99 ? "99+" : liveCount}
                </span>
              )}
              {showBadges && errorHigh > 0 && (
                <span
                  className="inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full bg-orange-500 text-white text-[10px] font-bold tabular-nums ring-2 ring-[#0E1F3D]"
                  data-testid="badge-errors-high"
                  title={`${errorHigh} erreur(s) High non lues`}
                >
                  {errorHigh > 99 ? "99+" : errorHigh}
                </span>
              )}
              {showBadges && errorCritical > 0 && (
                <span
                  className="inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full bg-rose-600 text-white text-[10px] font-bold tabular-nums ring-2 ring-[#0E1F3D] animate-pulse"
                  data-testid="badge-errors-critical"
                  title={`${errorCritical} erreur(s) Critical non lues`}
                >
                  {errorCritical > 99 ? "99+" : errorCritical}
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
          {waNotifier.soundAllowedByAdmin && waNotifier.soundOn && (
            <WaSoundPreferences
              adminDefaults={waNotifier.soundAdminDefaults}
              disabled={false}
              onChange={waNotifier.refreshSoundConfig}
            />
          )}
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
      <aside
        className="hidden lg:flex flex-col shrink-0 w-72 p-5 h-screen overflow-y-auto relative"
        style={{
          background: "var(--sidebar-bg, #0E1F3D)",
          color: "var(--sidebar-text, #ffffff)",
          backgroundImage: "var(--sidebar-bg-image, none)",
          backgroundSize: "cover",
          backgroundPosition: "center",
          backgroundBlendMode: "multiply",
        }}
        data-testid="portal-sidebar"
      >
        {SidebarContent}
      </aside>

      {/* Mobile drawer */}
      {open && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
          <aside
            className="relative w-72 p-5 h-full overflow-y-auto"
            style={{
              background: "var(--sidebar-bg, #0E1F3D)",
              color: "var(--sidebar-text, #ffffff)",
              backgroundImage: "var(--sidebar-bg-image, none)",
              backgroundSize: "cover",
              backgroundPosition: "center",
              backgroundBlendMode: "multiply",
            }}
          >
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
          <LanguageSelector compact />
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
      <BrowserNotifications />
    </div>
  );
}
