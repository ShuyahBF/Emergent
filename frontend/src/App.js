import React, { Suspense, useEffect, useState } from "react";
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
import AlertesPlateformesBanner from "@/components/AlertesPlateformesBanner";   // lot 352
import MarketingLayout from "@/components/MarketingLayout";
import PortalLayout from "@/components/PortalLayout";

// Public
import Home from "@/pages/public/Home";

// Auth
import Login from "@/pages/auth/Login";

// Portal

// Admin
// Lot 27 — Sondages WhatsApp
// Iter43-fix24az-f (2026-02-26) — Production module (Fabricant tenants)
// Iter43-fix24az-m (2026-07-18) — Planning médecins (RDV visualisation temps réel)
// Iter43-fix24az-ac — Page standalone d'analyse de prescription (médecin sidebar)
// Portage site-meetafrican — Fiche produit VIDAL + Posologie + Sécurisation
// Lot OCR sur Pièces (2026-09) — module commun ocr-core + adaptateur Sawali

// Iter42 (2026-02) — Self-Service Portal pour Officines (pharmacies)
import OfficineLayout from "@/components/OfficineLayout";
// Iter43-fix24f — Suggestions IA + Bird Cost
import VirtualAssistant from "@/components/VirtualAssistant";

import RouteTracker from "@/components/RouteTracker";
import WebhookResultModal from "@/components/WebhookResultModal";
import BandeauVoirEnTantQue from "@/components/BandeauVoirEnTantQue";   // lot 44
import SurveillanceMaintenance from "@/components/MaintenancePlateforme";   // lot 50 : déconnexion générale (R8)
import AbonnementAcces from "@/components/AbonnementAcces";   // lot 50 : grâce puis coupure de l'abonnement
import NouvelleVersionBandeau from "@/components/NouvelleVersionBandeau";   // lot 264 : « nouvelle version disponible »

// Lot 461 — pages chargées À LA DEMANDE (fichiers séparés) : le premier affichage ne télécharge plus les 8,7 Mo de toutes les pages.
import { paresseux } from "@/lib/paresseux";
const Missions = paresseux(() => import("@/pages/public/Missions"));
const Specialisations = paresseux(() => import("@/pages/public/Specialisations"));
const Catalogue = paresseux(() => import("@/pages/public/Catalogue"));
const AccordWhatsApp = paresseux(() => import("@/pages/public/AccordWhatsApp"));   // Lot 164 : page d'accord WhatsApp (lien personnel)
const PresentationCarte = paresseux(() => import("@/pages/public/PresentationCarte"));   // Lot 94 : carte de carrousel sans lien
const PresentationCarrousel = paresseux(() => import("@/pages/public/PresentationCarrousel"));   // Lot 111 : tout le carrousel, #carte-n
const LienCarrousel = paresseux(() => import("@/pages/public/LienCarrousel"));   // Lot 117 : bouton des cartes de carrousel (/l/<code>)
const Contact = paresseux(() => import("@/pages/public/Contact"));
const RDV = paresseux(() => import("@/pages/public/RDV"));
const Testimonials = paresseux(() => import("@/pages/public/Testimonials"));
const Feedback = paresseux(() => import("@/pages/public/Feedback"));
const CaseStudies = paresseux(() => import("@/pages/public/CaseStudies"));
const CaseStudyDetail = paresseux(() => import("@/pages/public/CaseStudyDetail"));
const Blog = paresseux(() => import("@/pages/public/Blog"));
const Subscriptions = paresseux(() => import("@/pages/public/Subscriptions"));
const BlogPost = paresseux(() => import("@/pages/public/BlogPost"));
const StatusPage = paresseux(() => import("@/pages/public/Status"));
const ConnexionGoogle = paresseux(() => import("@/pages/auth/ConnexionGoogle"));   // retour de Google
const ClientDashboard = paresseux(() => import("@/pages/portal/Dashboard"));
const ClientAppointments = paresseux(() => import("@/pages/portal/Appointments"));
const ClientDocuments = paresseux(() => import("@/pages/portal/Documents"));
const ClientInterventions = paresseux(() => import("@/pages/portal/Interventions"));
const ClientUsersTracking = paresseux(() => import("@/pages/portal/UsersTracking"));
const UserNotesPage = paresseux(() => import("@/pages/portal/UserNotes"));
const AdminDashboard = paresseux(() => import("@/pages/admin/AdminDashboard"));
const AdminClients = paresseux(() => import("@/pages/admin/AdminClients"));
const AdminAppointments = paresseux(() => import("@/pages/admin/AdminAppointments"));
const AdminInterventions = paresseux(() => import("@/pages/admin/AdminInterventions"));
const AdminDocuments = paresseux(() => import("@/pages/admin/AdminDocuments"));
const AdminContents = paresseux(() => import("@/pages/admin/AdminContents"));
const AdminSettings = paresseux(() => import("@/pages/admin/AdminSettings"));
const AdminTelecommandeTv = paresseux(() => import("@/pages/admin/AdminTelecommandeTv"));   // lot 412 : télécommande vidéo pour les Smart TV
const AdminPlateformesTempsReel = paresseux(() => import("@/pages/admin/AdminPlateformesTempsReel"));   // Lot 63
const AdminControleDistance = paresseux(() => import("@/pages/admin/AdminControleDistance"));   // Lot 135.1 : Plateformes → Contrôle à distance
const AdminRequetes = paresseux(() => import("@/pages/admin/AdminRequetes"));   // Lot 86 : requêtes des clients
const AdminEvaluationsLoois = paresseux(() => import("@/pages/admin/AdminEvaluationsLoois"));   // Lot 88 : sondages « Evaluation Loois »
const AdminSyntheseSupport = paresseux(() => import("@/pages/admin/AdminSyntheseSupport"));   // Lot 92 : synthèse du support
const AdminDemandesPlateformes = paresseux(() => import("@/pages/admin/AdminDemandesPlateformes"));   // Lot 393 : menu Plateformes
const AdminTransactionsSms = paresseux(() => import("@/pages/admin/AdminTransactionsSms"));   // Lot 389 : transactions SMS (administrateur)
const AdminLieuxBalises = paresseux(() => import("@/pages/admin/AdminLieuxBalises"));   // Lot 388 : lieux « Vous êtes ici » (administrateur + superviseur)
const LieuBalise = paresseux(() => import("@/pages/public/LieuBalise"));   // Lot 388 : page publique d'un lieu
const LooisSqlDistant = paresseux(() => import("@/pages/admin/LooisSqlDistant"));   // Lot 446 — Plateformes → Loois → SQL Distant (téléphone)
const LooisDossiersHospitalisation = paresseux(() => import("@/pages/admin/LooisDossiersHospitalisation"));   // Lot 448 — Plateformes → Loois → Dossiers d'hospitalisation (web)
const LooisSynchro = paresseux(() => import("@/pages/admin/LooisSynchro"));   // Lot 68 — Plateformes → Loois → Synchro
const AutomationsVocalesPage = paresseux(() => import("@/pages/portal/AutomationsVocalesPage"));   // lot 375 — Superviseur
const LiluvineAgenda = paresseux(() => import("@/pages/admin/LiluvineAgenda"));   // Lot 70 — agenda d'appels de Liluvine
const LiluvineConsignes = paresseux(() => import("@/pages/admin/LiluvineConsignes"));   // Lot 454 — consignes à Liluvine (menu Liluvine)
const MessagesBloquesWa = paresseux(() => import("@/pages/admin/MessagesBloquesWa"));   // Lot 79.6 — messages retenus par la barrière WA
const VidalApiLogs = paresseux(() => import("@/pages/admin/VidalApiLogs"));
const AdminContacts = paresseux(() => import("@/pages/admin/AdminContacts"));
const AdminTrackedUsers = paresseux(() => import("@/pages/admin/AdminTrackedUsers"));
const AdminTestimonials = paresseux(() => import("@/pages/admin/AdminTestimonials"));
const AdminCaseStudies = paresseux(() => import("@/pages/admin/AdminCaseStudies"));
const AdminBlog = paresseux(() => import("@/pages/admin/AdminBlog"));
const AdminSubscriptions = paresseux(() => import("@/pages/admin/AdminSubscriptions"));
const AdminNewsletter = paresseux(() => import("@/pages/admin/AdminNewsletter"));
const AdminVisits = paresseux(() => import("@/pages/admin/AdminVisits"));
const AdminDeployments = paresseux(() => import("@/pages/admin/AdminDeployments"));
const AdminBlacklist = paresseux(() => import("@/pages/admin/AdminBlacklist"));
const AdminAccessLogs = paresseux(() => import("@/pages/admin/AdminAccessLogs"));
const AdminApiTraces = paresseux(() => import("@/pages/admin/AdminApiTraces"));
const AdminSmsDashboard = paresseux(() => import("@/pages/admin/AdminSmsDashboard"));
const AdminHealthDashboard = paresseux(() => import("@/pages/admin/AdminHealthDashboard"));
const AdminDbExplorer = paresseux(() => import("@/pages/admin/AdminDbExplorer"));
const AdminFormations = paresseux(() => import("@/pages/admin/AdminFormations"));
const AdminIntegrationLinks = paresseux(() => import("@/pages/admin/AdminIntegrationLinks"));
const AdminMessaging = paresseux(() => import("@/pages/admin/AdminMessaging"));
const AdminAutomations = paresseux(() => import("@/pages/admin/AdminAutomations"));
const AdminWaTemplates = paresseux(() => import("@/pages/admin/AdminWaTemplates"));
const AdminClientTimeline = paresseux(() => import("@/pages/admin/AdminClientTimeline"));
const AdminClientFeatures = paresseux(() => import("@/pages/admin/AdminClientFeatures"));
const AdminVoiceNotifications = paresseux(() => import("@/pages/admin/AdminVoiceNotifications"));
const AdminAdBanners = paresseux(() => import("@/pages/admin/AdminAdBanners"));
const PublicAdReport = paresseux(() => import("@/pages/public/PublicAdReport"));
const AdminRgpdPreview = paresseux(() => import("@/pages/admin/AdminRgpdPreview"));
const AdminUsage = paresseux(() => import("@/pages/admin/AdminUsage"));
const AdminBrochures = paresseux(() => import("@/pages/admin/AdminBrochures"));
const AdminPolicies = paresseux(() => import("@/pages/admin/AdminPolicies"));
const AdminLiluvineHistory = paresseux(() => import("@/pages/admin/AdminLiluvineHistory"));
const AdminI18n = paresseux(() => import("@/pages/admin/AdminI18n"));
const AdminSuggestionsRegistry = paresseux(() => import("@/pages/admin/AdminSuggestionsRegistry"));
const AdminSuggestionsHistory = paresseux(() => import("@/pages/admin/AdminSuggestionsHistory"));
const AdminDownloadAudit = paresseux(() => import("@/pages/admin/AdminDownloadAudit"));
const Launch = paresseux(() => import("@/pages/public/Launch"));
const WaPlanningRecap = paresseux(() => import("@/pages/portal/WaPlanningRecap"));
const FormsList = paresseux(() => import("@/pages/portal/FormsList"));
const FormEditor = paresseux(() => import("@/pages/portal/FormEditor"));
const FormRunner = paresseux(() => import("@/pages/portal/FormRunner"));
const FormsAnalytics = paresseux(() => import("@/pages/portal/FormsAnalytics"));
const FormAnalyticsDetail = paresseux(() => import("@/pages/portal/FormAnalyticsDetail"));
const Contacts = paresseux(() => import("@/pages/portal/Contacts"));
const ContactGroups = paresseux(() => import("@/pages/portal/ContactGroups"));
const ErrorRegistry = paresseux(() => import("@/pages/portal/ErrorRegistry"));
const MediaGenerator = paresseux(() => import("@/pages/portal/MediaGenerator"));
const MediaLibrary = paresseux(() => import("@/pages/portal/MediaLibrary"));
const MyPayments = paresseux(() => import("@/pages/portal/MyPayments"));
const PayoutsPage = paresseux(() => import("@/pages/portal/Payouts"));
const VoiceStudio = paresseux(() => import("@/pages/portal/VoiceStudio"));
const CheckoutSuccess = paresseux(() => import("@/pages/public/CheckoutPages"), "CheckoutSuccess");
const CheckoutCancel = paresseux(() => import("@/pages/public/CheckoutPages"), "CheckoutCancel");
const SmsBulk = paresseux(() => import("@/pages/portal/SmsBulk"));
const WaBulk = paresseux(() => import("@/pages/portal/WaBulk"));
const Surveys = paresseux(() => import("@/pages/portal/Surveys"));
const SurveyEditor = paresseux(() => import("@/pages/portal/SurveyEditor"));
const SurveyResults = paresseux(() => import("@/pages/portal/SurveyResults"));
const PublicSurvey = paresseux(() => import("@/pages/public/PublicSurvey"));
const Disponibilites = paresseux(() => import("@/pages/public/Disponibilites"));   // lot 41
const SuiviRdv = paresseux(() => import("@/pages/public/SuiviRdv"));   // lot 321 : suivi du RDV par le patient (QR du hall)
const PortfolioInvoices = paresseux(() => import("@/pages/portal/PortfolioInvoices"));
const ComingSoon = paresseux(() => import("@/pages/portal/ComingSoon"));
const Tickets = paresseux(() => import("@/pages/portal/Tickets"));
const MesRequetes = paresseux(() => import("@/pages/portal/MesRequetes"));   // Lot 86 : requêtes des clients
const CashBilling = paresseux(() => import("@/pages/portal/CashBilling"));
const HumanResources = paresseux(() => import("@/pages/portal/HumanResources"));
const Production = paresseux(() => import("@/pages/portal/Production"));
const Planning = paresseux(() => import("@/pages/portal/Planning"));
const ReponsesRdv = paresseux(() => import("@/pages/portal/ReponsesRdv"));   // lot 303
const MetaIntegration = paresseux(() => import("@/pages/portal/MetaIntegration"));
const UnifiedInbox = paresseux(() => import("@/pages/portal/UnifiedInbox"));
const CatalogStats = paresseux(() => import("@/pages/portal/CatalogStats"));
const PaymentReturn = paresseux(() => import("@/pages/portal/PaymentReturn"));
const LiluvinePro = paresseux(() => import("@/pages/portal/LiluvinePro"));
const Vidal = paresseux(() => import("@/pages/portal/Vidal"));
const PrescriptionAnalysis = paresseux(() => import("@/pages/portal/PrescriptionAnalysis"));
const AmmEditorPage = paresseux(() => import("@/pages/portal/AmmEditor"));
const VidalFicheProduit = paresseux(() => import("@/pages/portal/VidalFicheProduit"));
const VidalPosologie = paresseux(() => import("@/pages/portal/VidalPosologie"));
const VidalSecurisation = paresseux(() => import("@/pages/portal/VidalSecurisation"));
const GestionStocks = paresseux(() => import("@/pages/portal/GestionStocks"));
const OcrPieces = paresseux(() => import("@/pages/portal/OcrPieces"));
const OrdonnancesStock = paresseux(() => import("@/pages/portal/OrdonnancesStock"));   // lot 39
const CarrouselWhatsApp = paresseux(() => import("@/pages/portal/CarrouselWhatsApp"));   // lot 40
const MaintenanceEquipements = paresseux(() => import("@/pages/portal/MaintenanceEquipements"));   // lot 41
const ParcInformatique = paresseux(() => import("@/pages/portal/ParcInformatique"));   // lot 47
const DecouverteReseau = paresseux(() => import("@/pages/admin/DecouverteReseau"));   // lot 80 : appareils découverts par Loois
const VersionsDeployees = paresseux(() => import("@/pages/admin/VersionsDeployees"));   // lot 80 : « Postes et serveurs » dans « Équipements »
const RapportParc = paresseux(() => import("@/pages/public/RapportParc"));   // lot 47 : rapport d'intervention à signer
const PublicRequete = paresseux(() => import("@/pages/public/PublicRequete"));   // lot 86.1 : lien personnel des requêtes clients (sans connexion)
const OfficinePaiement = paresseux(() => import("@/pages/public/OfficinePaiement"));   // lot 386 : paiement au comptoir (QR + séquence USSD)
const OfficinePaiementPortail = paresseux(() => import("@/pages/officines/Paiement"));   // lot 386
const OfficineOrdonnance = paresseux(() => import("@/pages/public/OfficineOrdonnance"));   // lot 57 : délivrance en officine (QR de l'ordonnance)
const Restauration = paresseux(() => import("@/pages/public/Restauration"));   // lot 49 : restauration initiale d'un site neuf
const FonctionsClients = paresseux(() => import("@/pages/portal/FonctionsClients"));   // lot 34
const PublicFormResults = paresseux(() => import("@/pages/public/PublicFormResults"));   // lot 36
const PortalBrochures = paresseux(() => import("@/pages/portal/PortalBrochures"));
const MeetingMinutes = paresseux(() => import("@/pages/portal/MeetingMinutes"));
const ReceiptPrint = paresseux(() => import("@/pages/portal/ReceiptPrint"));
const InvoicePrint = paresseux(() => import("@/pages/portal/InvoicePrint"));
const MyAccount = paresseux(() => import("@/pages/portal/MyAccount"));
const OfficineLogin = paresseux(() => import("@/pages/officines/Login"));
const OfficineMagicCallback = paresseux(() => import("@/pages/officines/MagicCallback"));
const OfficineDashboard = paresseux(() => import("@/pages/officines/Dashboard"));
const OfficineInventory = paresseux(() => import("@/pages/officines/Inventory"));
const OfficineSecret = paresseux(() => import("@/pages/officines/Secret"));
const OfficineHistory = paresseux(() => import("@/pages/officines/History"));
const AdminOfficinesRegistry = paresseux(() => import("@/pages/admin/AdminOfficinesRegistry"));
const AdminGardePlanning = paresseux(() => import("@/pages/admin/AdminGardePlanning"));
const AdminLiluvineWaRequests = paresseux(() => import("@/pages/admin/AdminLiluvineWaRequests"));
const AdminHandlerSuggestions = paresseux(() => import("@/pages/admin/AdminHandlerSuggestions"));
const AdminBirdCost = paresseux(() => import("@/pages/admin/AdminBirdCost"));
const StoryStudio = paresseux(() => import("@/pages/admin/StoryStudio"));
const PayLink = paresseux(() => import("@/pages/public/PayLink"));
const RemoteSupportConsole = paresseux(() => import("@/pages/public/RemoteSupportConsole"));
const PublicForm = paresseux(() => import("@/pages/public/PublicForm"));
const PoliciesPage = paresseux(() => import("@/pages/public/Policies"));
const PrivacyPage = paresseux(() => import("@/pages/public/Privacy"));
const PrivacyApplication = paresseux(() => import("@/pages/public/PrivacyApplication"));
const TermsOfServicePage = paresseux(() => import("@/pages/public/TermsOfService"));
const GardePage = paresseux(() => import("@/pages/public/Garde"));
const VerifierDocumentPage = paresseux(() => import("@/pages/public/VerifierDocument"));   // lot 268 : vérification d'un document par QR code
const FormationsList = paresseux(() => import("@/pages/portal/Formations"), "FormationsList");
const FormationDetail = paresseux(() => import("@/pages/portal/Formations"), "FormationDetail");
const ApiDocs = paresseux(() => import("@/pages/ApiDocs"));


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

// Lot 461 — affiché le temps de charger le fichier de la page demandée (jauge circulaire, comme sur le reste du site)
function ChargementPage() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center" role="status" aria-live="polite" data-testid="chargement-page">
      <div className="h-10 w-10 animate-spin rounded-full border-4 border-slate-300 border-t-sky-600" />
      <span className="sr-only">Patientez… chargement de la page</span>
    </div>
  );
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
        {/* Lot 44 — bandeau rouge « Voir en tant que » (toutes les pages de l'onglet) */}
        <BandeauVoirEnTantQue />
        <WebhookResultModal />
        <RouteTracker />
        <GlobalRouteLoader />
        <BackgroundApplier />
        <LlmHealthBanner />
        <AlertesPlateformesBanner />
        <AutoLogoutGate />
        {/* Lot 50 — maintenance de la plateforme et abonnement expiré (utilisateurs connectés) */}
        <SurveillanceMaintenance />
        <AbonnementAcces />
        <NouvelleVersionBandeau />
        <Suspense fallback={<ChargementPage />}>
        <Routes>
          {/* Public marketing */}
          <Route path="/" element={<PublicRoute><Home /></PublicRoute>} />
          <Route path="/missions" element={<PublicRoute><Missions /></PublicRoute>} />
          <Route path="/specialisations" element={<PublicRoute><Specialisations /></PublicRoute>} />
          <Route path="/catalogue" element={<PublicRoute><Catalogue /></PublicRoute>} />
          <Route path="/accord/:jeton" element={<PublicRoute><AccordWhatsApp /></PublicRoute>} />
          <Route path="/presentation/:code" element={<PublicRoute><PresentationCarte /></PublicRoute>} />
          {/* Lot 111 — présentation de toutes les cartes d'un carrousel, positionnée sur #carte-n */}
          <Route path="/presentation/c/:id" element={<PublicRoute><PresentationCarrousel /></PublicRoute>} />
          {/* Lot 117 — bouton des cartes de carrousel : page du site, sans redirection serveur (exigence Meta) */}
          <Route path="/l" element={<PublicRoute><LienCarrousel /></PublicRoute>} />
          <Route path="/l/:code" element={<PublicRoute><LienCarrousel /></PublicRoute>} />
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
          {/* Lot 36 — formulaire Liluvine « !formulaire » : saisie et réponses par lien crypté */}
          <Route path="/fr/:jeton" element={<PublicForm />} />
          <Route path="/fr-resultats/:jeton" element={<PublicFormResults />} />
          {/* Lot 27 — réponse à un sondage WhatsApp (lien personnel, sans compte) */}
          <Route path="/s/:token" element={<PublicSurvey />} />
          {/* Lot 41 — disponibilités partagées depuis une discussion WhatsApp */}
          <Route path="/disponibilites/:jeton" element={<Disponibilites />} />
          <Route path="/suivi-rdv" element={<SuiviRdv />} />
          <Route path="/rapport-parc/:jeton" element={<RapportParc />} />   {/* lot 47 */}
          <Route path="/requete/:jeton" element={<PublicRequete />} />   {/* lot 86.1 */}
          <Route path="/lieu/:code" element={<LieuBalise />} />   {/* lot 388 : page publique « Vous êtes ici » */}
          <Route path="/officine/payer/:jeton" element={<OfficinePaiement />} />   {/* lot 386 : page publique de paiement */}
          <Route path="/officine/ordonnance/:jeton" element={<OfficineOrdonnance />} />   {/* lot 57 : page publique de l'officine */}
          <Route path="/restauration" element={<Restauration />} />   {/* lot 49 */}
          <Route path="/pay/:slug" element={<PayLink />} />
          <Route path="/remote/support/:token" element={<RemoteSupportConsole />} />
          <Route path="/documentation" element={<ApiDocs />} />
          <Route path="/politiques" element={<PublicRoute><PoliciesPage /></PublicRoute>} />
          <Route path="/politiques/:slug" element={<PublicRoute><PoliciesPage /></PublicRoute>} />
          {/* Iter43-fix17 — URL courte /privacy pour Google Search Console + OAuth Consent Screen */}
          <Route path="/privacy" element={<PublicRoute><PrivacyPage /></PublicRoute>} />
          {/* Lot 407 — politique propre à chaque application Android : /privacy/concentration, /privacy/personnel-maison */}
          <Route path="/privacy/:app" element={<PublicRoute><PrivacyApplication /></PublicRoute>} />
          {/* Iter43-fix24as (2026-02) — Validation TikTok pour `sawalismartsystems` :
              URLs canoniques /privacy-policy + /terms-of-service avec titres
              de page contenant exactement le nom de l'app. */}
          <Route path="/privacy-policy" element={<PublicRoute><PrivacyPage /></PublicRoute>} />
          <Route path="/terms-of-service" element={<PublicRoute><TermsOfServicePage /></PublicRoute>} />
          <Route path="/terms" element={<PublicRoute><TermsOfServicePage /></PublicRoute>} />
          {/* Iter43-fix22b — Page publique des pharmacies de garde (SEO local) */}
          <Route path="/garde" element={<PublicRoute><GardePage /></PublicRoute>} />
          {/* Lot 268 — vérification d'un document (QR code chiffré) */}
          <Route path="/verifier-document" element={<PublicRoute><VerifierDocumentPage /></PublicRoute>} />

          {/* Auth */}
          <Route path="/login" element={<Login />} />
          <Route path="/connexion-google" element={<ConnexionGoogle />} />

          {/* Iter42 — Self-Service Portal pour Officines (entité indépendante,
              JWT séparé, ne passe PAS par /portal ni /admin) */}
          <Route path="/officines/login" element={<OfficineLogin />} />
          <Route path="/officines/magic" element={<OfficineMagicCallback />} />
          <Route path="/officines" element={<OfficineLayout />}>
            <Route index element={<OfficineDashboard />} />
            <Route path="inventory" element={<OfficineInventory />} />
            <Route path="paiement" element={<OfficinePaiementPortail />} />
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
            <Route path="surveys" element={<Surveys />} />
            <Route path="surveys/:sid/edit" element={<SurveyEditor />} />
            <Route path="surveys/:sid/results" element={<SurveyResults />} />
            <Route path="portfolio-invoices" element={<PortfolioInvoices />} />
            {/* Lot 70 — agenda d'appels de Liluvine (superviseurs : même écran que l'administration) */}
            <Route path="automations-vocales" element={<AutomationsVocalesPage />} />
            <Route path="liluvine-agenda" element={<LiluvineAgenda />} />
            {/* Lot 79.6 — menu Liluvine → Messages bloqués (barrière anti-rafale WhatsApp) */}
            <Route path="liluvine-messages-bloques" element={<MessagesBloquesWa />} />
            <Route path="liluvine-consignes" element={<LiluvineConsignes />} />   {/* lot 454 */}
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
            {/* Lot 40 — carrousel WhatsApp vers les contacts qui ont accepté */}
            <Route path="whatsapp-carrousel" element={<CarrouselWhatsApp />} />
            {/* Lot 41 — matériel confié pour réparation */}
            <Route path="maintenance" element={<MaintenanceEquipements />} />
            <Route path="parc" element={<ParcInformatique />} />
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
            <Route path="reponses-rdv" element={<ReponsesRdv />} />
            <Route path="meta" element={<MetaIntegration />} />
            <Route path="inbox" element={<UnifiedInbox />} />
            <Route path="catalog-stats" element={<CatalogStats />} />
            <Route path="payments/return" element={<PaymentReturn />} />
            <Route path="tickets" element={<Tickets />} />
            <Route path="requetes" element={<MesRequetes />} />
            {/* Iter38r-fix6 — Liluvine PRO assistant interne */}
            <Route path="liluvine" element={<LiluvinePro />} />
            {/* Iter41 (2026-02) — Module VIDAL France (médicaments / RCP / alertes) */}
            <Route path="vidal" element={<Vidal />} />
            {/* Iter43-fix24az-ac (2026-07-22) — Page dédiée médecin */}
            <Route path="prescription-analysis" element={<PrescriptionAnalysis />} />
            {/* Iter41 Phase 2 — Table AMM (numéros d'autorisation de mise sur le marché) */}
            <Route path="amm" element={<AmmEditorPage />} />
            {/* Portage site-meetafrican — Fiche produit VIDAL + Posologie + Sécurisation */}
            <Route path="vidal-fiche" element={<VidalFicheProduit />} />
            <Route path="vidal-posologie" element={<VidalPosologie />} />
            <Route path="vidal-securisation" element={<VidalSecurisation />} />
            {/* Lot Gestion Stocks (2026-09) — espace documentaire R2 + futur explorateur MongoDB Atlas */}
            <Route path="gestion-stocks" element={<GestionStocks />} />
            {/* Lot OCR sur Pièces (2026-09) — pharmacies (leurs pièces) + administration */}
            <Route path="ocr-pieces" element={<OcrPieces />} />
            {/* Lot 39 — photo d'ordonnance → disponibilité dans le stock du client */}
            <Route path="ordonnances-stock" element={<OrdonnancesStock />} />
            {/* Lot 34 — activation par client de « Formulaires et Sondages » et « OCR sur Pièces » (Superviseur) */}
            <Route path="smart-communications" element={<FonctionsClients />} />
            {/* S-iter39b — Brochures & Guides en visionneuse PDF interne */}
            <Route path="brochures" element={<PortalBrochures />} />
            <Route path="meetings" element={<MeetingMinutes />} />
            <Route path="meetings/:id" element={<MeetingMinutes />} />
            {/* S-iter39d (fix #2) — Liluvine PRO history accessible aux modérateurs */}
            <Route path="liluvine-history" element={<AdminLiluvineHistory />} />
            {/* Lot 25 — Page Régionalisation accessible depuis le portail : l'utilisateur
                suivi « Traducteur » n'a pas le rôle système admin, il ne peut donc pas
                ouvrir /admin/i18n. On lui affiche la même page ici (le serveur limite
                déjà ses droits à la lecture/écriture de ses langues). */}
            <Route path="i18n" element={<AdminI18n />} />
          </Route>

          {/* Admin */}
          <Route path="/admin" element={<Protected admin><PortalLayout admin /></Protected>}>
            <Route index element={<AdminDashboard />} />
            <Route path="clients" element={<AdminClients />} />
            <Route path="clients/:id/timeline" element={<AdminClientTimeline />} />
            <Route path="clients/:id/features" element={<AdminClientFeatures />} />
            <Route path="smart-communications" element={<FonctionsClients />} />   {/* lot 34 */}
            <Route path="clients/:client_id/rgpd-preview" element={<AdminRgpdPreview />} />
            <Route path="usage" element={<AdminUsage />} />
            <Route path="appointments" element={<AdminAppointments />} />
            <Route path="interventions" element={<AdminInterventions />} />
            <Route path="documents" element={<AdminDocuments />} />
            {/* Lot OCR sur Pièces (2026-09) — vue administration (modèles, coût, évaluations) */}
            <Route path="ocr-pieces" element={<OcrPieces />} />
            <Route path="ordonnances-stock" element={<OrdonnancesStock />} />   {/* lot 39 */}
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
            <Route path="forms" element={<FormsList automates />} />
            <Route path="forms/analytics" element={<FormsAnalytics />} />
            <Route path="forms/:fid/edit" element={<FormEditor />} />
            <Route path="forms/:fid/fill" element={<FormRunner />} />
            <Route path="forms/:fid/analytics" element={<FormAnalyticsDetail />} />
            <Route path="surveys" element={<Surveys />} />
            <Route path="surveys/:sid/edit" element={<SurveyEditor />} />
            <Route path="surveys/:sid/results" element={<SurveyResults />} />
            <Route path="portfolio-invoices" element={<PortfolioInvoices />} />
            <Route path="messaging" element={<AdminMessaging />} />
            <Route path="whatsapp-carrousel" element={<CarrouselWhatsApp admin />} />   {/* lot 40 */}
            <Route path="maintenance" element={<MaintenanceEquipements />} />   {/* lot 41 */}
            <Route path="parc" element={<ParcInformatique />} />   {/* lot 47 */}
            <Route path="decouverte-reseau" element={<DecouverteReseau />} />   {/* lot 80 */}
            <Route path="postes-serveurs" element={<div className="p-4"><VersionsDeployees /></div>} />   {/* lot 80 */}
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
            <Route path="television" element={<AdminTelecommandeTv />} />
            {/* Lot 63 — suivi en temps réel des plateformes (administrateur) */}
            <Route path="plateformes-temps-reel" element={<AdminPlateformesTempsReel />} />
            <Route path="controle-distance" element={<AdminControleDistance />} />
            <Route path="requetes" element={<AdminRequetes />} />
            <Route path="evaluations-loois" element={<AdminEvaluationsLoois />} />
            <Route path="synthese-support" element={<AdminSyntheseSupport />} />
            <Route path="lieux-balises" element={<AdminLieuxBalises />} />   {/* lot 388 */}
            <Route path="demandes-plateformes" element={<AdminDemandesPlateformes />} />   {/* lot 393 */}
            <Route path="transactions-sms" element={<AdminTransactionsSms />} />   {/* lot 389 */}
            {/* Lot 68 — synchro des tables HFSQL des clients Loois vers MongoDB (administrateur) */}
            <Route path="loois-synchro" element={<LooisSynchro />} />
            <Route path="loois-sql-distant" element={<LooisSqlDistant />} />   {/* lot 446 */}
            <Route path="loois-dossiers-hospitalisation" element={<LooisDossiersHospitalisation />} />   {/* lot 448 */}
            {/* Lot 70 — agenda d'appels de Liluvine (appels sortants planifiés, anniversaires) */}
            <Route path="liluvine-agenda" element={<LiluvineAgenda />} />
            {/* Lot 79.6 — menu Liluvine → Messages bloqués (barrière anti-rafale WhatsApp) */}
            <Route path="liluvine-messages-bloques" element={<MessagesBloquesWa />} />
            <Route path="liluvine-consignes" element={<LiluvineConsignes />} />   {/* lot 454 */}
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
            {/* Portage site-meetafrican — Suivi des logs VIDAL */}
            <Route path="vidal-logs" element={<VidalApiLogs />} />
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
        </Suspense>
        <VirtualAssistant />
      </BrowserRouter>
      </I18nProvider>
    </AuthProvider>
  );
}
