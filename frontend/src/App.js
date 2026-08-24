import React, { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import "@/App.css";
import { apiClient } from "@/lib/api";

// === Global runtime error reporter ===
// Captures any uncaught JS error or unhandled promise rejection that escapes
// React's render tree (event handlers, async code, libs like PostHog) and
// posts a tiny breadcrumb to the backend so we can debug production-only crashes.
if (typeof window !== "undefined" && !window.__sawali_err_handler__) {
  window.__sawali_err_handler__ = true;
  const post = (kind, msg, stack) => {
    try {
      apiClient.post("/me/api-trace", {
        method: "CLIENT_ERROR",
        url: window.location.pathname,
        status: 0,
        module: "client-error",
        error: String(msg).slice(0, 500),
        request_body: { kind, ua: navigator.userAgent.slice(0, 200) },
        response_body: { stack: String(stack || "").slice(0, 2000) },
      }).catch(() => {});
    } catch { /* noop */ }
  };
  window.addEventListener("error", (e) => {
    if (e?.error?.name === "DataCloneError") return; // already filtered
    post("window.error", e?.message, e?.error?.stack);
  });
  window.addEventListener("unhandledrejection", (e) => {
    post("unhandledrejection", e?.reason?.message || e?.reason, e?.reason?.stack);
  });
}

import { AuthProvider, useAuth } from "@/contexts/AuthContext";
import { I18nProvider } from "@/contexts/I18nContext";
import AutoLogoutGate from "@/components/AutoLogoutGate";
import GlobalRouteLoader from "@/components/GlobalRouteLoader";
import BackgroundApplier from "@/components/BackgroundApplier";
import { useUIFlags } from "@/lib/useUIFlags";
import LlmHealthBanner from "@/components/LlmHealthBanner";
import MarketingLayout from "@/components/MarketingLayout";
import PortalLayout from "@/components/PortalLayout";

// Public
import Home from "@/pages/public/Home";
import Missions from "@/pages/public/Missions";
import Specialisations from "@/pages/public/Specialisations";
import Catalogue from "@/pages/public/Catalogue";
import Contact from "@/pages/public/Contact";
import RDV from "@/pages/public/RDV";
import Testimonials from "@/pages/public/Testimonials";
import Feedback from "@/pages/public/Feedback";
import CaseStudies from "@/pages/public/CaseStudies";
import CaseStudyDetail from "@/pages/public/CaseStudyDetail";
import Blog from "@/pages/public/Blog";
import Subscriptions from "@/pages/public/Subscriptions";
import BlogPost from "@/pages/public/BlogPost";
import StatusPage from "@/pages/public/Status";

// Auth
import Login from "@/pages/auth/Login";

// Portal
import ClientDashboard from "@/pages/portal/Dashboard";
import ClientAppointments from "@/pages/portal/Appointments";
import ClientDocuments from "@/pages/portal/Documents";
import ClientInterventions from "@/pages/portal/Interventions";
import ClientUsersTracking from "@/pages/portal/UsersTracking";
import UserNotesPage from "@/pages/portal/UserNotes";

// Admin
import AdminDashboard from "@/pages/admin/AdminDashboard";
import AdminClients from "@/pages/admin/AdminClients";
import AdminAppointments from "@/pages/admin/AdminAppointments";
import AdminInterventions from "@/pages/admin/AdminInterventions";
import AdminDocuments from "@/pages/admin/AdminDocuments";
import AdminContents from "@/pages/admin/AdminContents";
import AdminSettings from "@/pages/admin/AdminSettings";
import AdminContacts from "@/pages/admin/AdminContacts";
import AdminTrackedUsers from "@/pages/admin/AdminTrackedUsers";
import AdminTestimonials from "@/pages/admin/AdminTestimonials";
import AdminCaseStudies from "@/pages/admin/AdminCaseStudies";
import AdminBlog from "@/pages/admin/AdminBlog";
import AdminSubscriptions from "@/pages/admin/AdminSubscriptions";
import AdminNewsletter from "@/pages/admin/AdminNewsletter";
import AdminVisits from "@/pages/admin/AdminVisits";
import AdminDeployments from "@/pages/admin/AdminDeployments";
import AdminBlacklist from "@/pages/admin/AdminBlacklist";
import AdminAccessLogs from "@/pages/admin/AdminAccessLogs";
import AdminApiTraces from "@/pages/admin/AdminApiTraces";
import AdminSmsDashboard from "@/pages/admin/AdminSmsDashboard";
import AdminHealthDashboard from "@/pages/admin/AdminHealthDashboard";
import AdminDbExplorer from "@/pages/admin/AdminDbExplorer";
import AdminFormations from "@/pages/admin/AdminFormations";
import AdminIntegrationLinks from "@/pages/admin/AdminIntegrationLinks";
import AdminMessaging from "@/pages/admin/AdminMessaging";
import AdminAutomations from "@/pages/admin/AdminAutomations";
import AdminWaTemplates from "@/pages/admin/AdminWaTemplates";
import AdminClientTimeline from "@/pages/admin/AdminClientTimeline";
import AdminClientFeatures from "@/pages/admin/AdminClientFeatures";
import AdminVoiceNotifications from "@/pages/admin/AdminVoiceNotifications";
import AdminAdBanners from "@/pages/admin/AdminAdBanners";
import PublicAdReport from "@/pages/public/PublicAdReport";
import AdminRgpdPreview from "@/pages/admin/AdminRgpdPreview";
import AdminUsage from "@/pages/admin/AdminUsage";
import AdminBrochures from "@/pages/admin/AdminBrochures";
import AdminPolicies from "@/pages/admin/AdminPolicies";
import AdminLiluvineHistory from "@/pages/admin/AdminLiluvineHistory";
import AdminI18n from "@/pages/admin/AdminI18n";
import AdminSuggestionsRegistry from "@/pages/admin/AdminSuggestionsRegistry";
import AdminSuggestionsHistory from "@/pages/admin/AdminSuggestionsHistory";
import AdminDownloadAudit from "@/pages/admin/AdminDownloadAudit";
import Launch from "@/pages/public/Launch";
import WaPlanningRecap from "@/pages/portal/WaPlanningRecap";
import FormsList from "@/pages/portal/FormsList";
import FormEditor from "@/pages/portal/FormEditor";
import FormRunner from "@/pages/portal/FormRunner";
import FormsAnalytics from "@/pages/portal/FormsAnalytics";
import FormAnalyticsDetail from "@/pages/portal/FormAnalyticsDetail";
import Contacts from "@/pages/portal/Contacts";
import ContactGroups from "@/pages/portal/ContactGroups";
import ErrorRegistry from "@/pages/portal/ErrorRegistry";
import MediaGenerator from "@/pages/portal/MediaGenerator";
import MediaLibrary from "@/pages/portal/MediaLibrary";
import MyPayments from "@/pages/portal/MyPayments";
import PayoutsPage from "@/pages/portal/Payouts";
import VoiceStudio from "@/pages/portal/VoiceStudio";
import { CheckoutSuccess, CheckoutCancel } from "@/pages/public/CheckoutPages";
import SmsBulk from "@/pages/portal/SmsBulk";
import WaBulk from "@/pages/portal/WaBulk";
import ComingSoon from "@/pages/portal/ComingSoon";
import Tickets from "@/pages/portal/Tickets";
import CashBilling from "@/pages/portal/CashBilling";
import HumanResources from "@/pages/portal/HumanResources";
// Iter43-fix24az-f (2026-02-26) — Production module (Fabricant tenants)
import Production from "@/pages/portal/Production";
// Iter43-fix24az-m (2026-07-18) — Planning médecins (RDV visualisation temps réel)
import Planning from "@/pages/portal/Planning";
import MetaIntegration from "@/pages/portal/MetaIntegration";
import UnifiedInbox from "@/pages/portal/UnifiedInbox";
import CatalogStats from "@/pages/portal/CatalogStats";
import PaymentReturn from "@/pages/portal/PaymentReturn";
import LiluvinePro from "@/pages/portal/LiluvinePro";
import Vidal from "@/pages/portal/Vidal";
// Iter43-fix24az-ac — Page standalone d'analyse de prescription (médecin sidebar)
import PrescriptionAnalysis from "@/pages/portal/PrescriptionAnalysis";
import AmmEditorPage from "@/pages/portal/AmmEditor";
import PortalBrochures from "@/pages/portal/PortalBrochures";
import MeetingMinutes from "@/pages/portal/MeetingMinutes";
import ReceiptPrint from "@/pages/portal/ReceiptPrint";
import InvoicePrint from "@/pages/portal/InvoicePrint";
import MyAccount from "@/pages/portal/MyAccount";

// Iter42 (2026-02) — Self-Service Portal pour Officines (pharmacies)
import OfficineLayout from "@/components/OfficineLayout";
import OfficineLogin from "@/pages/officines/Login";
import OfficineMagicCallback from "@/pages/officines/MagicCallback";
import OfficineDashboard from "@/pages/officines/Dashboard";
import OfficineInventory from "@/pages/officines/Inventory";
import OfficineSecret from "@/pages/officines/Secret";
import OfficineHistory from "@/pages/officines/History";
import AdminOfficinesRegistry from "@/pages/admin/AdminOfficinesRegistry";
import AdminGardePlanning from "@/pages/admin/AdminGardePlanning";
import AdminLiluvineWaRequests from "@/pages/admin/AdminLiluvineWaRequests";
// Iter43-fix24f — Suggestions IA + Bird Cost
import AdminHandlerSuggestions from "@/pages/admin/AdminHandlerSuggestions";
import AdminBirdCost from "@/pages/admin/AdminBirdCost";
import StoryStudio from "@/pages/admin/StoryStudio";
import PayLink from "@/pages/public/PayLink";
import RemoteSupportConsole from "@/pages/public/RemoteSupportConsole";
import PublicForm from "@/pages/public/PublicForm";
import PoliciesPage from "@/pages/public/Policies";
import PrivacyPage from "@/pages/public/Privacy";
import TermsOfServicePage from "@/pages/public/TermsOfService";
import GardePage from "@/pages/public/Garde";
import { FormationsList, FormationDetail } from "@/pages/portal/Formations";
import VirtualAssistant from "@/components/VirtualAssistant";

import RouteTracker from "@/components/RouteTracker";
import WebhookResultModal from "@/components/WebhookResultModal";

import ApiDocs from "@/pages/ApiDocs";

const PublicRoute = ({ children }) => <MarketingLayout>{children}</MarketingLayout>;

const Protected = ({ admin = false, children }) => {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Navigate to="/login" replace />;
  if (admin && user.role !== "admin") return <Navigate to="/portal" replace />;
  return children;
};

// Iter43-fix24r (2026-06) — Route-guard spécifique pour le menu Officines délégué.
// Un utilisateur non-admin listé dans `settings.officines_menu_allowed_emails` doit
// pouvoir atteindre `/admin/officines-registry` sans être redirigé. Cette
// protection asynchrone interroge `/me/officines-permissions` AVANT de rediriger.
function OfficinesDelegatedProtected({ children }) {
  const { user, loading } = useAuth();
  const [allowed, setAllowed] = useState(null); // null = loading
  useEffect(() => {
    if (!user) { setAllowed(false); return; }
    if (user.role === "admin") { setAllowed(true); return; }
    let cancelled = false;
    apiClient.get("/me/officines-permissions").then((r) => {
      if (!cancelled) setAllowed(r.data?.can_view === true);
    }).catch(() => { if (!cancelled) setAllowed(false); });
    return () => { cancelled = true; };
  }, [user]);
  if (loading) return null;
  if (!user) return <Navigate to="/login" replace />;
  if (allowed === null) return null;
  if (allowed === false) return <Navigate to="/portal" replace />;
  return children;
}

// Iter43-fix24az-i (2026-02-26) — Fabricant tenants have no dashboard/welcome
// screen. Their entry point should be /portal/cash directly rather than the
// generic /portal home page.
function PortalIndex() {
  const { user } = useAuth();
  const bt = (user?.business_type || "").toLowerCase();
  if (bt === "fabricant") {
    return <Navigate to="/portal/cash" replace />;
  }
  return <ClientDashboard />;
}

export default function App() {
  // Iter40-ui-flags — Apply public branding (title, --brand-primary CSS var)
  // app-wide. The hook fetches once and listens for ui-flags-updated.
  useUIFlags();
  return (
    <AuthProvider>
      <I18nProvider>
        <BrowserRouter>
        <Toaster richColors position="top-right" />
        <WebhookResultModal />
        <RouteTracker />
        <GlobalRouteLoader />
        <BackgroundApplier />
        <LlmHealthBanner />
        <AutoLogoutGate />
        <Routes>
          {/* Public marketing */}
          <Route path="/" element={<PublicRoute><Home /></PublicRoute>} />
          <Route path="/missions" element={<PublicRoute><Missions /></PublicRoute>} />
          <Route path="/specialisations" element={<PublicRoute><Specialisations /></PublicRoute>} />
          <Route path="/catalogue" element={<PublicRoute><Catalogue /></PublicRoute>} />
          <Route path="/checkout/success" element={<PublicRoute><CheckoutSuccess /></PublicRoute>} />
          <Route path="/checkout/cancel" element={<PublicRoute><CheckoutCancel /></PublicRoute>} />
          <Route path="/contact" element={<PublicRoute><Contact /></PublicRoute>} />
          <Route path="/rdv" element={<PublicRoute><RDV /></PublicRoute>} />
          <Route path="/temoignages" element={<PublicRoute><Testimonials /></PublicRoute>} />
          <Route path="/etudes-de-cas" element={<PublicRoute><CaseStudies /></PublicRoute>} />
          <Route path="/etudes-de-cas/:slug" element={<PublicRoute><CaseStudyDetail /></PublicRoute>} />
          <Route path="/blog" element={<PublicRoute><Blog /></PublicRoute>} />
          <Route path="/blog/:slug" element={<PublicRoute><BlogPost /></PublicRoute>} />
          {/* Iter38r-fix9y — Public live report for advertisers */}
          <Route path="/ads/:slug" element={<PublicAdReport />} />
          <Route path="/subscriptions" element={<PublicRoute><Subscriptions /></PublicRoute>} />
          <Route path="/feedback/:token" element={<Feedback />} />
          <Route path="/uptime" element={<StatusPage />} />
          <Route path="/launch" element={<Launch />} />
          {/* 2026-02 fork (P3 recap) — Deep-link auto-login from médecin planning WA digest */}
          <Route path="/wa-recap" element={<WaPlanningRecap />} />
          <Route path="/f/:fid" element={<PublicForm />} />
          <Route path="/pay/:slug" element={<PayLink />} />
          <Route path="/remote/support/:token" element={<RemoteSupportConsole />} />
          <Route path="/documentation" element={<ApiDocs />} />
          <Route path="/politiques" element={<PublicRoute><PoliciesPage /></PublicRoute>} />
          <Route path="/politiques/:slug" element={<PublicRoute><PoliciesPage /></PublicRoute>} />
          {/* Iter43-fix17 — URL courte /privacy pour Google Search Console + OAuth Consent Screen */}
          <Route path="/privacy" element={<PublicRoute><PrivacyPage /></PublicRoute>} />
          {/* Iter43-fix24as (2026-02) — Validation TikTok pour `sawalismartsystems` :
              URLs canoniques /privacy-policy + /terms-of-service avec titres
              de page contenant exactement le nom de l'app. */}
          <Route path="/privacy-policy" element={<PublicRoute><PrivacyPage /></PublicRoute>} />
          <Route path="/terms-of-service" element={<PublicRoute><TermsOfServicePage /></PublicRoute>} />
          <Route path="/terms" element={<PublicRoute><TermsOfServicePage /></PublicRoute>} />
          {/* Iter43-fix22b — Page publique des pharmacies de garde (SEO local) */}
          <Route path="/garde" element={<PublicRoute><GardePage /></PublicRoute>} />

          {/* Auth */}
          <Route path="/login" element={<Login />} />

          {/* Iter42 — Self-Service Portal pour Officines (entité indépendante,
              JWT séparé, ne passe PAS par /portal ni /admin) */}
          <Route path="/officines/login" element={<OfficineLogin />} />
          <Route path="/officines/magic" element={<OfficineMagicCallback />} />
          <Route path="/officines" element={<OfficineLayout />}>
            <Route index element={<OfficineDashboard />} />
            <Route path="inventory" element={<OfficineInventory />} />
            <Route path="secret" element={<OfficineSecret />} />
            <Route path="history" element={<OfficineHistory />} />
          </Route>

          {/* Client portal */}
          <Route path="/portal" element={<Protected><PortalLayout admin={false} /></Protected>}>
            <Route index element={<PortalIndex />} />
            <Route path="appointments" element={<ClientAppointments />} />
            <Route path="documents" element={<ClientDocuments />} />
            <Route path="interventions" element={<ClientInterventions />} />
            <Route path="users" element={<ClientUsersTracking />} />
            <Route path="formations" element={<FormationsList />} />
            <Route path="formations/:fid" element={<FormationDetail />} />
            <Route path="forms" element={<FormsList />} />
            <Route path="forms/analytics" element={<FormsAnalytics />} />
            <Route path="forms/:fid/edit" element={<FormEditor />} />
            <Route path="forms/:fid/fill" element={<FormRunner />} />
            <Route path="forms/:fid/analytics" element={<FormAnalyticsDetail />} />
            <Route path="contacts" element={<Contacts />} />
            <Route path="contact-groups" element={<ContactGroups />} />
            <Route path="error-registry" element={<ErrorRegistry />} />
            <Route path="media-library" element={<MediaLibrary />} />
            <Route path="media-generator" element={<MediaGenerator />} />
            <Route path="notes/:kind" element={<UserNotesPage />} />
            <Route path="payments" element={<MyPayments />} />
            <Route path="payouts" element={<PayoutsPage />} />
            <Route path="voice-studio" element={<VoiceStudio />} />
            <Route path="sms" element={<SmsBulk />} />
            <Route path="whatsapp-bulk" element={<WaBulk />} />
            <Route path="my-account" element={<MyAccount />} />
            {/* Iter36u — Caisse & Facturation module */}
            <Route path="cash" element={<CashBilling defaultTab="receipts" />} />
            <Route path="cash/receipt/:id" element={<ReceiptPrint />} />
            <Route path="billing" element={<CashBilling defaultTab="invoices" />} />
            <Route path="billing/invoice/:id" element={<InvoicePrint />} />
            <Route path="catalog" element={<CashBilling defaultTab="catalog" />} />
            <Route path="hr" element={<HumanResources />} />
            {/* Iter43-fix24az-f — Production module (Fabricant tenants) */}
            <Route path="production" element={<Production />} />
            {/* Iter43-fix24az-m (2026-07-18) — Planning médecins */}
            <Route path="planning" element={<Planning />} />
            <Route path="meta" element={<MetaIntegration />} />
            <Route path="inbox" element={<UnifiedInbox />} />
            <Route path="catalog-stats" element={<CatalogStats />} />
            <Route path="payments/return" element={<PaymentReturn />} />
            <Route path="tickets" element={<Tickets />} />
            {/* Iter38r-fix6 — Liluvine PRO assistant interne */}
            <Route path="liluvine" element={<LiluvinePro />} />
            {/* Iter41 (2026-02) — Module VIDAL France (médicaments / RCP / alertes) */}
            <Route path="vidal" element={<Vidal />} />
            {/* Iter43-fix24az-ac (2026-07-22) — Page dédiée médecin */}
            <Route path="prescription-analysis" element={<PrescriptionAnalysis />} />
            {/* Iter41 Phase 2 — Table AMM (numéros d'autorisation de mise sur le marché) */}
            <Route path="amm" element={<AmmEditorPage />} />
            {/* S-iter39b — Brochures & Guides en visionneuse PDF interne */}
            <Route path="brochures" element={<PortalBrochures />} />
            <Route path="meetings" element={<MeetingMinutes />} />
            <Route path="meetings/:id" element={<MeetingMinutes />} />
            {/* S-iter39d (fix #2) — Liluvine PRO history accessible aux modérateurs */}
            <Route path="liluvine-history" element={<AdminLiluvineHistory />} />
          </Route>

          {/* Admin */}
          <Route path="/admin" element={<Protected admin><PortalLayout admin /></Protected>}>
            <Route index element={<AdminDashboard />} />
            <Route path="clients" element={<AdminClients />} />
            <Route path="clients/:id/timeline" element={<AdminClientTimeline />} />
            <Route path="clients/:id/features" element={<AdminClientFeatures />} />
            <Route path="clients/:client_id/rgpd-preview" element={<AdminRgpdPreview />} />
            <Route path="usage" element={<AdminUsage />} />
            <Route path="appointments" element={<AdminAppointments />} />
            <Route path="interventions" element={<AdminInterventions />} />
            <Route path="documents" element={<AdminDocuments />} />
            <Route path="contents" element={<AdminContents />} />
            <Route path="contacts" element={<AdminContacts />} />
            <Route path="tracked-users" element={<AdminTrackedUsers />} />
            <Route path="brochures" element={<AdminBrochures />} />
            <Route path="testimonials" element={<AdminTestimonials />} />
            <Route path="case-studies" element={<AdminCaseStudies />} />
            <Route path="blog" element={<AdminBlog />} />
            <Route path="subscriptions" element={<AdminSubscriptions />} />
            <Route path="newsletter" element={<AdminNewsletter />} />
            <Route path="visits" element={<AdminVisits />} />
            <Route path="deployments" element={<AdminDeployments />} />
            <Route path="blacklist" element={<AdminBlacklist />} />
            <Route path="access-logs" element={<AdminAccessLogs />} />
            <Route path="api-traces" element={<AdminApiTraces />} />
            <Route path="sms-dashboard" element={<AdminSmsDashboard />} />
            <Route path="health" element={<AdminHealthDashboard />} />
            <Route path="db-explorer" element={<AdminDbExplorer />} />
            <Route path="formations" element={<AdminFormations />} />
            <Route path="forms" element={<FormsList />} />
            <Route path="forms/analytics" element={<FormsAnalytics />} />
            <Route path="forms/:fid/edit" element={<FormEditor />} />
            <Route path="forms/:fid/fill" element={<FormRunner />} />
            <Route path="forms/:fid/analytics" element={<FormAnalyticsDetail />} />
            <Route path="messaging" element={<AdminMessaging />} />
            <Route path="automations" element={<AdminAutomations />} />
            <Route path="whatsapp-templates" element={<AdminWaTemplates />} />
            <Route path="policies" element={<AdminPolicies />} />
            <Route path="integration-links" element={<AdminIntegrationLinks />} />
            <Route path="liluvine-history" element={<AdminLiluvineHistory />} />
            <Route path="suggestions" element={<AdminSuggestionsRegistry />} />
            <Route path="suggestions-history" element={<AdminSuggestionsHistory />} />
            <Route path="download-audit" element={<AdminDownloadAudit />} />
            <Route path="i18n" element={<AdminI18n />} />
            <Route path="notes/:kind" element={<UserNotesPage />} />
            <Route path="settings" element={<AdminSettings />} />
            <Route path="voice-notifications" element={<AdminVoiceNotifications />} />
            <Route path="ad-banners" element={<AdminAdBanners />} />
            {/* Iter42 — Officines Registry (validation des pharmacies inscrites).
                Iter43-fix24r (2026-06) — DÉPLACÉ hors de ce groupe : la route
                top-level `/admin/officines-registry` ci-dessous gère désormais
                la délégation aux non-admins listés dans
                `settings.officines_menu_allowed_emails`. */}
            <Route path="garde-planning" element={<AdminGardePlanning />} />
            <Route path="liluvine-wa-requests" element={<AdminLiluvineWaRequests />} />
            {/* Iter43-fix24f */}
            <Route path="handler-suggestions" element={<AdminHandlerSuggestions />} />
            <Route path="bird-cost" element={<AdminBirdCost />} />
            <Route path="story-studio" element={<StoryStudio />} />
          </Route>

          {/* Iter43-fix24r (2026-06) — Route Officines Registry isolée, autorise
              les utilisateurs délégués (non-admin) listés dans
              `settings.officines_menu_allowed_emails`. */}
          <Route
            path="/admin/officines-registry"
            element={
              <OfficinesDelegatedProtected>
                <PortalLayout admin />
              </OfficinesDelegatedProtected>
            }
          >
            <Route index element={<AdminOfficinesRegistry />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        <VirtualAssistant />
      </BrowserRouter>
      </I18nProvider>
    </AuthProvider>
  );
}
