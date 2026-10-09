import React, { useEffect, useState } from "react";
import { NavLink, useNavigate, Outlet, Link, useLocation } from "react-router-dom";
import {
  LayoutDashboard, Calendar, FileText, Wrench, Users, GalleryHorizontalEnd,
  Settings, LogOut, Menu, X, Inbox, Mail, ShieldCheck, Boxes, FileEdit, Star, Briefcase, Newspaper, Send, Activity, Globe2, ShieldAlert, History, GraduationCap, Bug, HeartPulse, Database, Link2, MessageCircle, MessageSquare, Zap, Shield, Wand2, FolderOpen, BarChart3, Wallet, Receipt, ShoppingBag, Banknote, Ticket, Tag, Bell, BellOff, Volume2, VolumeX, Bot, Megaphone, ClipboardList, ScrollText, Languages, AlertOctagon, AlertTriangle, Sparkles, CircleDollarSign, Factory, Moon, Sun, StickyNote, Pill, Stethoscope, ScanText, Monitor, PhoneCall,
} from "lucide-react";
import { ChevronDown } from "lucide-react";   // lot 73 : flèche du groupe « Liluvine » dépliable
import { Radar, Server, Cpu } from "lucide-react";   // lot 80 : menu « Équipements »
import { MessageSquareWarning } from "lucide-react";   // lot 86 : requêtes des clients
import { useAuth } from "@/contexts/AuthContext";
import { VidalUiSettingsProvider, useVidalUiSettings } from "@/contexts/VidalUiSettingsContext";
import { LOGO_URL } from "@/lib/brand";
import { apiClient } from "@/lib/api";
import AdBannerSlot from "@/components/AdBannerSlot";
import { toast } from "sonner";
import IncidentBanner from "@/components/IncidentBanner";
import DemoBanner from "@/components/DemoBanner";
import VersionStamp from "@/components/VersionStamp";
import EtatConnexion from "@/components/EtatConnexion";
import InternalChatPanel from "@/components/InternalChatPanel";
import TicketsBubble from "@/components/TicketsBubble";
import AppelsWhatsApp from "@/components/AppelsWhatsApp";   // Lot 60
import VeilleStatsPlateformes from "@/components/VeilleStatsPlateformes";   // Lot 64.9
import LiluvineLiveToast from "@/components/LiluvineLiveToast";
import { useMesureAtlas, PastilleAtlas, DetailAtlas } from "@/components/JaugeAtlasSidebar";   // Lots 79.9 / 79.10 : jauge Atlas (administrateur)
import AlertesAppelsLiluvine from "@/components/AlertesAppelsLiluvine";   // Lot 72 : toast persistant « Liluvine appelle … »
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
import DerniereSauvegarde from "@/components/DerniereSauvegarde";   // lot 50

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
  // Lot 27 — « Formulaires & Sondages » : une seule entrée (sidebar plus courte) ;
  // la page bascule entre Formulaires et Sondages WhatsApp (FormsSurveysTabs).
  // `alsoActive` : le lien reste en surbrillance sur les pages des sondages.
  // Lot 34 — fonction activable par client (SMART Communications) : grisée si désactivée.
  { to: "/portal/forms", label: "Formulaires & Sondages", tKey: "nav.forms_surveys", icon: FileText, alsoActive: ["/portal/surveys"], featureGate: "forms_surveys", fsBadges: true },
  // Lot 27 — bilans formulaires & sondages à facturer (admin et Superviseur : choix de la TVA)
  { to: "/portal/portfolio-invoices", label: "Bilans à facturer", icon: Receipt, adminOrSup: true },
  // Lot 70 — agenda d'appels de Liluvine (superviseurs ; l'administrateur l'a dans son menu)
  { to: "/portal/liluvine-agenda", label: "Agenda d'appels", icon: PhoneCall, adminOrSup: true, groupe: "liluvine", partage: "agenda" },
  // Lot 79.6 — messages WhatsApp retenus par la barrière anti-rafale (tous correspondants)
  { to: "/portal/liluvine-messages-bloques", label: "Messages bloqués", icon: ShieldAlert, adminOrSup: true, groupe: "liluvine", partage: "bloques" },
  // Lot 34 — activation par client de « Formulaires et Sondages » et « OCR sur Pièces »
  // Lot 41 — renommé « Outils+ » : « SMART Communications » reste le nom de l'onglet de chaque fiche client.
  { to: "/portal/smart-communications", label: "Outils+", icon: ShieldCheck, adminOrSup: true },
  { to: "/portal/contacts", label: "Centre de Messagerie", tKey: "nav.contacts", icon: MessageCircle, module: "contacts_unread", noMarkSeen: true },
  { to: "/portal/contact-groups", label: "Groupes de contacts", icon: Users },
  // Lot 25 — `errorRegistryOnly` : lien affiché seulement aux rôles système que le
  // serveur accepte (admin, superviseur, modérateur) — voir routes/error_registry.py.
  { to: "/portal/error-registry", label: "Registre des erreurs", icon: AlertOctagon, showBadges: true, errorRegistryOnly: true },
  // Iter38i — Unified omnichannel inbox (WhatsApp + Messenger)
  { to: "/portal/inbox", label: "Inbox unifiée (WA + Messenger)", icon: MessageCircle },
  { to: "/portal/sms", label: "SMS — Masse & Planif.", icon: Send, module: "sms" },
  { to: "/portal/whatsapp-bulk", label: "WhatsApp — Masse & Planif.", icon: MessageCircle, module: "whatsapp" },
  // Lot 40 — carrousel de 2 à 10 cartes vers les contacts qui ont accepté (fonction activable).
  { to: "/portal/whatsapp-carrousel", label: "Carrousel WhatsApp", icon: GalleryHorizontalEnd, featureGate: "whatsapp_carrousel" },
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
  // Lot 86 — requêtes du client (dysfonctionnements, remarques, logiciels, équipements ; écrites ou vocales)
  { to: "/portal/requetes", label: "Mes requêtes", icon: MessageSquareWarning },
  { to: "/portal/media-library", label: "Bibliothèque de médias", icon: FolderOpen },
  { to: "/portal/media-generator", label: "Générateur d'Images et Vidéos", icon: Wand2 },
  // Lot 25 — Grisé (featureGate) quand la fonctionnalité « Génération Vocale IA »
  // (clé ai_voice_gen, testée par backend routes/ai_media_9m.py) est désactivée.
  { to: "/portal/voice-studio", label: "Voice Studio (Clonage)", icon: Volume2, featureGate: "ai_voice_gen" },
  // Iter38n — Catalog analytics cockpit (admin/sup/tracked users)
  { to: "/portal/catalog-stats", label: "Statistiques catalogue", icon: BarChart3, catalogStatsOnly: true },
  // Iter38r-fix6/7 — Liluvine PRO (visible mais grisé si ai_liluvine_pro = false)
  { to: "/portal/liluvine", label: "Liluvine PRO (Assistant IA)", tKey: "nav.liluvine", icon: Bot, featureGate: "ai_liluvine_pro", groupe: "liluvine", partage: "pro" },
  // Iter41 (2026-02) — Module VIDAL France (médicaments / RCP / alertes prescription)
  { to: "/portal/vidal", label: "VIDAL France (médicaments)", icon: HeartPulse, featureGate: "vidal_enabled" },
  // Iter41 Phase 2 — Table AMM (régulateurs / admins / superviseurs)
  { to: "/portal/amm", label: "Numéros AMM (régulateur)", icon: ScrollText, featureGate: "vidal_enabled" },
  // Portage site-meetafrican — Fiche produit VIDAL (voies + documents + équivalences)
  { to: "/portal/vidal-fiche", label: "Fiche produit VIDAL", icon: Pill, featureGate: "vidal_enabled" },
  // Portage site-meetafrican — Posologie (profil patient + recherche posologie)
  { to: "/portal/vidal-posologie", label: "Posologie", icon: Stethoscope, featureGate: "vidal_enabled" },
  // Portage site-meetafrican — Sécurisation (schéma XML réel, calculateurs, alertes)
  { to: "/portal/vidal-securisation", label: "Sécurisation", icon: AlertTriangle, featureGate: "vidal_enabled" },
  // S-iter39b — PV de réunions internes (autonumérotés, impression/PDF)
  { to: "/portal/meetings", label: "PV de réunions", icon: ClipboardList },
  // S-iter39d (fix #2) — Liluvine PRO Historique accessible aux modérateurs
  // (et aux admin/sup pour cohérence avec la sidebar admin)
  { to: "/portal/liluvine-history", label: "Liluvine PRO — Historique", icon: Bot, moderationOnly: true, groupe: "liluvine", partage: "historique" },
  // S-iter39b — Brochures & Guides accessible aux modérateurs (lecture en
  // ligne via la visionneuse PDF interne ; téléchargement réservé admin/sup).
  { to: "/portal/brochures", label: "Brochures & Guides", icon: FileText, moderationOnly: true },
  // Lot OCR sur Pièces (2026-09) — dépôt et analyse IA des pièces (factures
  // fournisseurs, bons de livraison…). Lot 34 : fonction activable par client
  // (SMART Communications), grisée tant qu'elle n'est pas activée ; les
  // pharmacien(ne)s suivi(e)s ont le lien dans leur sidebar réduite plus bas.
  { to: "/portal/ocr-pieces", label: "OCR sur Pièces", icon: ScanText, featureGate: "ocr_pieces" },
  // Lot 39 — photo d'ordonnance → disponibilité dans le stock du client (fonction activable).
  { to: "/portal/ordonnances-stock", label: "Ordonnances et stock", icon: Pill, featureGate: "ordonnances_stock" },
  // Lot 41 — matériel confié pour réparation (fonction activable).
  { to: "/portal/maintenance", label: "Maintenance des équipements", icon: Wrench, featureGate: "maintenance_equipements", groupe: "equipements" },
  // Lot 47 — parc informatique du client : équipements, interventions, rapports signés (fonction activable).
  // Lot 80 — regroupés avec la maintenance dans le menu dépliable « Équipements »
  { to: "/portal/parc", label: "Parc informatique", icon: Monitor, featureGate: "parc_informatique", groupe: "equipements" },
];

const adminLinks = [
  { to: "/admin", label: "Tableau de bord", icon: LayoutDashboard, end: true },
  { to: "/admin/clients", label: "Clients", icon: Users, module: "admin_clients" },
  { to: "/admin/smart-communications", label: "Outils+", icon: ShieldCheck },   // lot 34 (renommé « Outils+ » au lot 41)
  { to: "/admin/usage", label: "Usage & Facturation", icon: BarChart3 },
  { to: "/admin/appointments", label: "Rendez-vous", icon: Calendar, module: "admin_appointments" },
  { to: "/admin/interventions", label: "Interventions", icon: Wrench, module: "admin_interventions", badgeKey: "tickets_pending" },
  { to: "/admin/documents", label: "Documents", icon: FileText },
  // Lot 27 — une seule entrée, bascule Formulaires / Sondages dans la page
  { to: "/admin/forms", label: "Formulaires & Sondages", icon: FileEdit, alsoActive: ["/admin/surveys"], fsBadges: true },   // lot 41 : bulles
  { to: "/admin/portfolio-invoices", label: "Bilans à facturer", icon: Receipt },   // lot 27
  { to: "/admin/messaging", label: "Messagerie WhatsApp", icon: MessageCircle },
  { to: "/admin/whatsapp-carrousel", label: "Carrousel WhatsApp", icon: GalleryHorizontalEnd },   // lot 40
  { to: "/admin/whatsapp-templates", label: "Templates WhatsApp", icon: FileEdit },
  // Lot 70 — appels sortants planifiés de Liluvine (relances, prospection, anniversaires…)
  { to: "/admin/liluvine-agenda", label: "Agenda d'appels", icon: PhoneCall, groupe: "liluvine", partage: "agenda" },
  // Lot 79.6 — messages WhatsApp retenus par la barrière anti-rafale (tous correspondants)
  { to: "/admin/liluvine-messages-bloques", label: "Messages bloqués", icon: ShieldAlert, groupe: "liluvine", partage: "bloques" },
  // Lot 73 — Liluvine PRO (assistant) accessible aussi depuis le menu Liluvine de l'administration
  { to: "/portal/liluvine", label: "Liluvine PRO (Assistant IA)", icon: Bot, groupe: "liluvine", partage: "pro" },
  { to: "/admin/automations", label: "Automations", icon: Zap },
  { to: "/admin/liluvine-history", label: "Liluvine PRO — Historique", icon: Bot, groupe: "liluvine", partage: "historique" },
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
  // Lot OCR sur Pièces (2026-09) — choix du modèle d'IA, coût réel en FCFA,
  // évaluation 1-5 étoiles, tableau de bord par modèle.
  { to: "/admin/ocr-pieces", label: "OCR sur Pièces", icon: ScanText },
  { to: "/admin/ordonnances-stock", label: "Ordonnances et stock", icon: Pill },   // lot 39
  // Lot 80 — menu dépliable « Équipements » : parc, maintenance, découverte du réseau, postes et serveurs
  { to: "/admin/parc", label: "Parc informatique", icon: Monitor, groupe: "equipements" },   // lot 47
  { to: "/admin/maintenance", label: "Maintenance des équipements", icon: Wrench, groupe: "equipements" },   // lot 41
  { to: "/admin/decouverte-reseau", label: "Découverte du réseau", icon: Radar, groupe: "equipements" },   // lot 80
  { to: "/admin/postes-serveurs", label: "Postes et serveurs", icon: Server, groupe: "equipements" },   // lot 80
  // Iter43-fix22 — Planning des gardes (admin/superviseur)
  { to: "/admin/garde-planning", label: "Planning des gardes", icon: Calendar, adminOrSup: true },
  // Iter43-fix22 — Interrogations WhatsApp à Liluvine (admin/moderator/superviseur)
  // Iter43-fix24d — Renommé "Exclamations Reçues" (ne contient que les !commandes).
  { to: "/admin/liluvine-wa-requests", label: "Commandes « ! » reçues", icon: Inbox, moderatorPlus: true, groupe: "liluvine" },
  // Iter43-fix24f — Historique des suggestions IA de handlers + dashboard coût Bird
  { to: "/admin/handler-suggestions", label: "Handlers IA", icon: Sparkles, adminOnly: true, groupe: "liluvine" },
  { to: "/admin/bird-cost", label: "Coût SMS Bird", icon: CircleDollarSign, adminOnly: true },
  { to: "/admin/story-studio", label: "Story Studio (AI)", icon: Sparkles },
  // Portage site-meetafrican — Suivi des logs VIDAL (appels API réels + sync référentiel)
  { to: "/admin/vidal-logs", label: "Suivi des logs VIDAL", icon: History, adminOrSup: true },
  // Lot 63 — activité des plateformes (adLyn, Ster, beAuthentik…) en temps réel
  { to: "/admin/plateformes-temps-reel", label: "Temps réel", icon: Activity, adminOnly: true, groupe: "plateformes" },   // lot 79.10 : groupe « Plateformes »
  // Lot 86 — requêtes de tous les clients, lots de correction, évaluations
  { to: "/admin/requetes", label: "Requêtes clients", icon: MessageSquareWarning, adminOrSup: true },   // lot 86.3 : superviseurs aussi
  { to: "/admin/evaluations-loois", label: "Évaluations Loois", icon: ClipboardList, adminOrSup: true },   // lot 88 : sondages du support
  // Lot 68 — Plateformes → Loois → Synchro : tables HFSQL remontées par Loois dans MongoDB
  { to: "/admin/loois-synchro", label: "Loois → Synchro", icon: Database, adminOnly: true, groupe: "plateformes" },   // lot 79.10
  { to: "/admin/settings", label: "Paramètres", icon: Settings, module: "admin_profile_requests", noMarkSeen: true },
];

// Portage site-meetafrican (SecureLayout.jsx "Réglages") — thème
// clair/sombre (tous les utilisateurs connectés) et "Notes VIDAL (admin)"
// (admin/superviseur uniquement). Le composant exporté par défaut n'enveloppe
// que le provider ; toute la logique reste dans PortalLayoutInner pour
// pouvoir consommer `useVidalUiSettings()`.
export default function PortalLayout(props) {
  return (
    <VidalUiSettingsProvider>
      <PortalLayoutInner {...props} />
    </VidalUiSettingsProvider>
  );
}

function PortalLayoutInner({ admin = false }) {
  const { user, logout } = useAuth();
  const { theme, setTheme, vidalAdminNotes, setVidalAdminNotes } = useVidalUiSettings();
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
  // Lot 73 — éléments de Liluvine partagés avec ce compte (superviseur restreint) et groupe déplié ou non
  const [partageLiluvine, setPartageLiluvine] = useState(null);
  const [liluvineOuvert, setLiluvineOuvert] = useState(() => {
    try { return localStorage.getItem("sawali.menu.liluvine") === "1"; } catch { return false; }
  });
  // Lot 79.10 — groupe « Plateformes » (temps réel, Loois → Synchro) dépliable comme « Liluvine »
  const [plateformesOuvert, setPlateformesOuvert] = useState(() => {
    try { return localStorage.getItem("sawali.menu.plateformes") === "1"; } catch { return false; }
  });
  // Lot 80 — groupe « Équipements » (parc, maintenance, découverte du réseau, postes) dépliable
  const [equipementsOuvert, setEquipementsOuvert] = useState(() => {
    try { return localStorage.getItem("sawali.menu.equipements") === "1"; } catch { return false; }
  });
  // Lot 79.10 — bas de la barre latérale compact : panneau déplié (null, "atlas" ou "reglages")
  const [panneauBas, setPanneauBas] = useState(null);
  // Lot 79.10 — mesure Atlas lue seulement pour l'administrateur (pastille + détail du bas de la barre latérale)
  const mesureAtlas = useMesureAtlas(user?.role === "admin");
  // Lot 41 — nouvelles données reçues : soumissions de formulaires (bulle verte) et
  // réponses aux sondages (bulle bleue), depuis la dernière consultation de chacun.
  const [fsNouveautes, setFsNouveautes] = useState({ formulaires: 0, sondages: 0 });
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
  // Lot 25 — Rôle SYSTÈME modérateur : il existe sous deux orthographes
  // (« moderateur » enregistré par le formulaire Clients, « moderator » ailleurs).
  const isSysModerator = ["moderateur", "moderator"].includes(user?.role || "");
  // 2026-02 (#1) — Traducteur : seul accès = /portal/i18n (Régionalisation, lot 25).
  // Toutes les autres entrées de la sidebar sont masquées. L'utilisateur
  // est forcé d'aller sur Régionalisation au login (route handled in App.js).
  const isTranslator = (user?.tracked_role || "") === "Traducteur";
  // Iter43-fix24az-m (2026-07-18) — Médecin tracked role : accès UNIQUE au
  // planning des consultations. La sidebar ne montre QUE cet item.
  const isMedecinTracked = (user?.tracked_role || "") === "Médecin";
  // Portage site-meetafrican — Pharmacien tracked role : accès UNIQUE à
  // Posologie (pas de Sécurisation, contrairement au médecin). Sert de pont
  // vers l'"officine-registry" — même session utilisateur suivi, pas de JWT
  // séparé (option retenue explicitement par l'utilisateur).
  const isPharmacienTracked = (user?.tracked_role || "") === "Pharmacien";
  // Lot 54 — Auxiliaire en Pharmacie : SEULEMENT Fiche Produit, Posologie et Ordonnances et Stock
  // (scan + OCR). Le serveur refuse toute autre route (403, backend/roles_restreints.py).
  const isAuxiliairePharmacie = (user?.tracked_role || "") === "Auxiliaire en Pharmacie";
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
  // Lot 25 — Peut créer un document : même règle que le bouton « Nouveau document »
  // de la page Documentation (pages/portal/Documents.jsx, fonction isElevated).
  const canCreateDocuments = isAdminOrSup || ["Moderation", "Administrateur", "Superviseur"].includes(user?.tracked_role || "");
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
  const isRestrictedByRoleForDashboard = isComptaStrict || isTranslator || isMedecinTracked || isPharmacienTracked || isSecretaireMedicale || isFabricant || isAuxiliairePharmacie;
  const p4ShowDashboard = user?.show_dashboard === true
    ? true
    : user?.show_dashboard === false
      ? false
      : !isRestrictedByRoleForDashboard;
  const p4ShowWelcome = user?.show_welcome_modal === true
    ? true
    : user?.show_welcome_modal === false
      ? false
      : !(isFabricant || isMedecinTracked || isPharmacienTracked || isAuxiliairePharmacie);
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
  // Lot 25 — Le Traducteur utilise la page Régionalisation du portail
  // (/portal/i18n) : /admin/i18n le renvoyait vers /portal (rôle système non admin).
  const allowedTranslatorPaths = new Set(["/portal/i18n"]);
  const allowedMedecinTrackedPaths = new Set([
    "/portal/planning",
    "/portal/prescription-analysis",  // Iter43-fix24az-ac — conservé pour compatibilité, plus lié en sidebar
    // Portage site-meetafrican — Sécurisation remplace "Analyse prescription"
    // en sidebar (même page conceptuelle, enrichie — voir VidalSecurisation.jsx).
    "/portal/vidal-securisation",
    // Un médecin suivi doit aussi voir Fiche produit VIDAL et Posologie
    // (mêmes options qu'un compte médecin/pharmacien à rôle système).
    "/portal/vidal-fiche",
    "/portal/vidal-posologie",
    "/portal/my-account",
  ]);
  // Portage site-meetafrican — Pharmacien suivi : Posologie uniquement (pas
  // de Sécurisation, ni Fiche produit — accès volontairement plus étroit
  // que le médecin, demandé explicitement par l'utilisateur).
  // Lot Gestion Stocks (2026-09) — ajout du nouvel espace documentaire.
  // Lot 19 (2026-09) — Fiche produit VIDAL ouverte aussi au Pharmacien suivi.
  const allowedPharmacienTrackedPaths = new Set([
    "/portal/vidal-posologie",
    "/portal/vidal-fiche",
    // Lecteur PDF interne où la Fiche produit ouvre les documents VIDAL (RCP) ;
    // chemin autorisé mais pas de lien en sidebar (contenu public uniquement).
    "/portal/brochures",
    "/portal/gestion-stocks",
    // Lot OCR sur Pièces (2026-09)
    "/portal/ocr-pieces",
    "/portal/my-account",
  ]);
  // Lot 54 — Auxiliaire en Pharmacie (pas de tableau de bord, même avec l'option d'affichage)
  const allowedAuxiliairePaths = new Set([
    "/portal/vidal-fiche",
    "/portal/vidal-posologie",
    "/portal/ordonnances-stock",
    "/portal/my-account",
  ]);
  const allowedSecretaireMedicalePaths = new Set([
    "/portal/planning",
    "/portal/my-account",
  ]);
  const allowedRegulateurPaths = new Set(["/portal/amm", "/portal/liluvine"]);
  const allowedEditeurVidalPaths = new Set([
    "/portal/vidal", "/portal/amm", "/portal/liluvine",
    "/portal/vidal-fiche", "/portal/vidal-posologie", "/portal/vidal-securisation",
  ]);
  // Paths réservés à certains rôles métier (cachés pour les autres)
  const restrictedVidalPaths = new Set([
    "/portal/vidal", "/portal/amm", "/portal/vidal-fiche", "/portal/vidal-posologie", "/portal/vidal-securisation",
  ]);
  // Correctif — sans isMedecinTracked/isPharmacienTracked ici, ce filtre
  // masquait les liens Fiche produit/Posologie/Sécurisation qu'on vient
  // d'ajouter à leur sidebar réduite (leur `role` système est "client",
  // le contrôle d'accès réel pour eux vient déjà de leur propre allowlist
  // ci-dessus — ce filtre global ne doit pas les re-bloquer en plus).
  const canSeeVidal = isAdminOrSup || isRegulateur || isPharmacien || isMedecin || isEditeurVidal || isMedecinTracked || isPharmacienTracked || isAuxiliairePharmacie;
  // Lot 25 — Lien unique du Traducteur : la page Régionalisation côté portail.
  const baseLinks = isTranslator
    ? [{ to: "/portal/i18n", label: "Régionalisation", icon: Languages }]
    : (isMedecinTracked
        ? [
            { to: "/portal/planning", label: "Planning consultations", icon: Calendar, badgeKey: "walk_ins_today" },
            // Iter43-fix24az-ac (2026-07-22) — devenu "Sécurisation" (portage
            // site-meetafrican) : même page conceptuelle, enrichie — voir
            // VidalSecurisation.jsx. featureGate conservé pour masquer le
            // lien quand le module VIDAL n'est pas activé sur le tenant.
            { to: "/portal/vidal-securisation", label: "Sécurisation", icon: AlertTriangle, featureGate: "vidal_enabled" },
            // Portage site-meetafrican — même accès VIDAL riche qu'un compte
            // médecin à rôle système (demandé explicitement par l'utilisateur).
            { to: "/portal/vidal-fiche", label: "Fiche produit VIDAL", icon: Pill, featureGate: "vidal_enabled" },
            { to: "/portal/vidal-posologie", label: "Posologie", icon: Stethoscope, featureGate: "vidal_enabled" },
          ]
        : (isAuxiliairePharmacie
          ? [
              { to: "/portal/vidal-fiche", label: "Fiche produit VIDAL", icon: Pill, featureGate: "vidal_enabled" },
              { to: "/portal/vidal-posologie", label: "Posologie", icon: Stethoscope, featureGate: "vidal_enabled" },
              { to: "/portal/ordonnances-stock", label: "Ordonnances et stock", icon: Pill, featureGate: "ordonnances_stock" },
            ]
        : (isPharmacienTracked
            ? [
                // Portage site-meetafrican — pont vers "officine-registry" :
                // même session utilisateur suivi, sidebar réduite à Posologie
                // uniquement (pas de Sécurisation ni Fiche produit).
                { to: "/portal/vidal-posologie", label: "Posologie", icon: Stethoscope, featureGate: "vidal_enabled" },
                // Lot 19 (2026-09) — Fiche produit VIDAL en plus de Posologie
                // (mêmes routes backend /vidal/product/..., déjà contrôlées par
                // l'accès VIDAL du tenant ; pas de Sécurisation).
                { to: "/portal/vidal-fiche", label: "Fiche produit VIDAL", icon: Pill, featureGate: "vidal_enabled" },
                // Lot Gestion Stocks (2026-09) — espace documentaire R2
                // (inventaires, contrôle qualité, etc) + futur explorateur
                // MongoDB Atlas.
                { to: "/portal/gestion-stocks", label: "Gestion de Stocks", icon: Boxes },
                // Lot OCR sur Pièces (2026-09) — dépôt + synthèse IA des pièces.
                { to: "/portal/ocr-pieces", label: "OCR sur Pièces", icon: ScanText, featureGate: "ocr_pieces" },
                // Lot 39 — Ordonnances et stock (pharmacien(ne)s suivi(e)s).
                { to: "/portal/ordonnances-stock", label: "Ordonnances et stock", icon: Pill, featureGate: "ordonnances_stock" },
              ]
            : (isSecretaireMedicale
                ? [
                    { to: "/portal/planning", label: "Planning consultations", icon: Calendar, badgeKey: "walk_ins_today" },
                  ]
                : (admin ? adminLinks : clientLinks)))));
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
    .filter((l) => !isPharmacienTracked || allowedPharmacienTrackedPaths.has(l.to) || (l.to === "/portal" && p4ShowDashboard))
    .filter((l) => !isAuxiliairePharmacie || allowedAuxiliairePaths.has(l.to))
    // Lot 54 — « Ordonnances et stock » suit la règle d'Outils+ pour tous les rôles (hors Admin /
    // Superviseur) : visible si la fonction est cochée pour le client, absente sinon (plus de lien grisé).
    .filter((l) => l.to !== "/portal/ordonnances-stock" || isAdminOrSup || !!tenantFeatures.ordonnances_stock)
    .filter((l) => !isRegulateur || allowedRegulateurPaths.has(l.to))
    .filter((l) => !isEditeurVidal || allowedEditeurVidalPaths.has(l.to))
    // Iter43-fix24az-f — Fabricant tenants : allowlist stricte
    // Lot 25 — Les utilisateurs suivis héritent désormais du profil Fabricant de leur
    // client parent : les rôles qui ont déjà leur propre menu réduit (Traducteur,
    // Médecin, Pharmacien, Secrétaire médicale) gardent ce menu au lieu d'être vidés.
    .filter((l) => !isFabricant || isTranslator || isMedecinTracked || isPharmacienTracked || isSecretaireMedicale || isAuxiliairePharmacie
      || fabricantAllowedPaths.has(l.to) || (l.to === "/portal" && p4ShowDashboard))
    .filter((l) => !l.fabricantOnly || isFabricant)
    .filter((l) => !restrictedVidalPaths.has(l.to) || canSeeVidal)
    .filter((l) => !l.trackedOnly || isTracked)
    // 2026-02 fork iter105 — Cache Documents / Formations / Formulaires quand
    // le tenant lié n'a rien de visible. Admin/superviseur bypass via `accessSummary=null`
    // (l'endpoint retourne toujours has_XXX=true pour eux).
    // Lot 25 — Exception : le lien reste affiché aux comptes qui peuvent CRÉER le
    // premier élément (sinon ils ne pourraient jamais le créer) :
    //   • Documentation : mêmes conditions que le bouton « Nouveau document »
    //     (Documents.jsx : rôle admin/superviseur ou suivi Moderation/Administrateur/Superviseur) ;
    //   • Formulaires : le bouton « Nouveau formulaire » (FormsList.jsx) est proposé à
    //     tous les comptes du portail, le lien reste donc toujours visible.
    .filter((l) => {
      if (!accessSummary) return true;
      if (l.to === "/portal/documents") return accessSummary.has_documents !== false || canCreateDocuments;
      if (l.to === "/portal/formations") return accessSummary.has_formations !== false;
      if (l.to === "/portal/forms") return true;
      return true;
    })
    .filter((l) => !l.superAdminOnly || isSuperAdmin)
    // Lot 25 — Même condition que la page Caisse (CashBilling.jsx : admin/superviseur
    // ou can_cash) : un Comptable sans « can_cash » ne voit plus un lien qui le bloquerait.
    .filter((l) => !l.cashOnly || canCash)
    .filter((l) => !l.hrOnly || canHR)
    .filter((l) => !l.metaOnly || metaEnabled || isAdminOrSup)
    .filter((l) => !l.cashAdminOnly || isAdminOrSup)
    // Lot 25 — Brochures / Liluvine Historique : modérateur suivi OU rôle système modérateur.
    .filter((l) => !l.moderationOnly || isModerator || isSysModerator || isAdminOrSup)
    .filter((l) => !l.adminOrSup || isAdminOrSup)
    .filter((l) => !l.moderatorPlus || isModerator || isSysModerator || isAdminOrSup)
    // Lot 25 — Registre des erreurs : mêmes rôles que le serveur (admin, superviseur,
    // modérateur système). Le registre n'est pas cloisonné par client, donc le
    // modérateur SUIVI (« Moderation », rattaché à un client) ne le voit pas.
    .filter((l) => !l.errorRegistryOnly || isAdminOrSup || isSysModerator)
    .filter((l) => !l.catalogStatsOnly || isAdminOrSup || isTracked)
    // 2026-02 fork (P4) — Override de masquage explicite du Tableau de bord
    .filter((l) => l.to !== "/portal" || p4ShowDashboard)
    // Lot 73 — superviseur restreint : seuls les éléments de Liluvine partagés par l'administrateur
    .filter((l) => !l.partage || !partageLiluvine?.restreint || (partageLiluvine.elements || []).includes(l.partage));

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
    // Lot 41 — bulles « Formulaires & Sondages » (best effort)
    try {
      const r4 = await apiClient.get("/me/formulaires-sondages/nouveautes");
      setFsNouveautes({ formulaires: r4.data?.formulaires || 0, sondages: r4.data?.sondages || 0 });
    } catch { /* noop */ }
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
  // Lot 41 — les pages Données / Résultats signalent une consultation : bulles relues aussitôt
  useEffect(() => {
    window.addEventListener("sawali:fs-vu", refreshBadges);
    return () => window.removeEventListener("sawali:fs-vu", refreshBadges);
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
    // Portage site-meetafrican — Pharmacien tracked : redirigé vers Posologie
    // ("officine-registry", même session) plutôt que /portal/planning — un
    // pharmacien n'a pas de planning de consultations.
    if (user && isPharmacienTracked && !allowedPharmacienTrackedPaths.has(location.pathname)) {
      const dashboardAllowed = location.pathname === "/portal" && p4ShowDashboard;
      if (!dashboardAllowed) {
        navigate("/portal/vidal-posologie");
      }
    }
    // Lot 54 — Auxiliaire en Pharmacie : uniquement ses trois pages (et « Mon compte »)
    if (user && isAuxiliairePharmacie && !allowedAuxiliairePaths.has(location.pathname)) {
      navigate("/portal/vidal-fiche");
    }
  }, [user, admin, navigate, officinesDelegated, permissionsLoaded, location.pathname, isFabricant, isMedecinTracked, isPharmacienTracked, isAuxiliairePharmacie, p4ShowDashboard]);

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
        || (l.alsoActive || []).some((p) => path === p || path.startsWith(p + "/"))
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

  // Lot 73 — ce que l'administrateur partage de Liluvine avec ce compte (menu « Liluvine »)
  useEffect(() => {
    if (!user) return;
    apiClient.get("/me/liluvine-partage").then((r) => setPartageLiluvine(r.data)).catch(() => setPartageLiluvine(null));
  }, [user]);

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

  // Lot 54 — Ordinateur (lg et plus) : le haut (logo, langue, météo) et le bas (compte, alertes,
  // réglages, déconnexion) restent figés ; seule la liste des options défile. Téléphone et
  // tablette (tiroir) : comportement inchangé, tout le tiroir défile.
  // Lot 73 — « le menu de la barre latérale est devenu trop complexe » : tout ce qui concerne Liluvine est
  // regroupé dans UNE entrée « Liluvine » dépliable (placée là où apparaissait le premier élément du groupe).
  // Le groupe s'ouvre seul quand la page affichée en fait partie ; sinon il garde le dernier choix (navigateur).
  // Lot 79.10 — même principe pour « Plateformes » : un seul code dessine tous les groupes dépliables.
  const GROUPES = {
    liluvine: { libelle: "Liluvine", icone: Bot, ouvert: liluvineOuvert, cle: "sawali.menu.liluvine", changer: setLiluvineOuvert },
    plateformes: { libelle: "Plateformes", icone: Globe2, ouvert: plateformesOuvert, cle: "sawali.menu.plateformes", changer: setPlateformesOuvert },
    equipements: { libelle: "Équipements", icone: Cpu, ouvert: equipementsOuvert, cle: "sawali.menu.equipements", changer: setEquipementsOuvert },   // lot 80
  };
  const basculerGroupe = (g) => GROUPES[g].changer((avant) => {
    try { localStorage.setItem(GROUPES[g].cle, avant ? "0" : "1"); } catch { /* ignore */ }
    return !avant;
  });
  const rendreMenu = (liste, rendreLien) => {
    const sortie = [];
    const places = new Set();          // groupes déjà dessinés (à la place de leur premier élément)
    liste.forEach((l) => {
      const g = l.groupe && GROUPES[l.groupe] ? l.groupe : null;
      if (!g) { sortie.push(rendreLien(l)); return; }
      if (places.has(g)) return;
      places.add(g);
      const enfants = liste.filter((e) => e.groupe === g);
      if (enfants.length === 1) { sortie.push(rendreLien(enfants[0])); return; }   // un seul élément : pas de groupe
      const { libelle, icone: Icone } = GROUPES[g];
      const actif = enfants.some((e) => location.pathname === e.to || location.pathname.startsWith(e.to + "/"));
      const ouvert = GROUPES[g].ouvert || actif;
      sortie.push(
        <div key={`groupe-${g}`} data-testid={`sidebar-groupe-${g}`}>
          <button type="button" onClick={() => basculerGroupe(g)} aria-expanded={ouvert}
            className={`sidebar-link w-full ${actif && !ouvert ? "active" : ""} group`}
            title={ouvert ? `Replier le menu ${libelle}` : `Déplier le menu ${libelle}`}>
            <Icone className="h-4 w-4" />
            <span className="flex-1 truncate text-left">{libelle}</span>
            <span className="text-[10px] text-slate-400">{enfants.length}</span>
            <ChevronDown className={`h-3.5 w-3.5 transition-transform ${ouvert ? "rotate-180" : ""}`} />
          </button>
          {ouvert && (
            <div className="ml-3 mt-1 space-y-1 border-l border-white/10 pl-2" data-testid={`sidebar-groupe-${g}-liens`}>
              {enfants.map(rendreLien)}
            </div>
          )}
        </div>,
      );
    });
    return sortie;
  };

  const renderSidebar = (bureau) => (
    <>
      <div className={bureau ? "shrink-0" : undefined} data-testid={bureau ? "sidebar-haut" : undefined}>
      <Link to="/" className="flex items-center gap-3 mb-2 px-2">
        <img src={displayedLogo} alt={displayedName} className={`h-10 w-10 ${useClientLogo ? "rounded-md object-contain bg-white/95 p-1" : "rounded-md object-cover"} ring-1 ring-white/20`} />
        <div className="min-w-0">
          <p className="font-display font-bold text-white text-sm truncate" title={displayedName}>{displayedName}</p>
          <p className="text-[9px] uppercase tracking-[0.25em] text-sawali-blue-light">
            {displayedSubtitle}
          </p>
        </div>
      </Link>
      <div className="px-2 mb-6 flex items-center justify-between gap-2" data-testid="sidebar-language-row">
        {/* État du serveur et version du déploiement, en petit, à gauche du bouton des langues */}
        <EtatConnexion tone="dark" compact className="min-w-0 flex-1" />
        <LanguageSelector compact />
      </div>
      <div className="px-2 mb-3" data-testid="sidebar-weather-row">
        <WeatherWidget variant="compact" placement="portal" className="w-full justify-start" />
      </div>
      </div>
      <nav className={bureau ? "space-y-1 flex-1 min-h-[8rem] overflow-y-auto overscroll-contain -mx-2 px-2" : "space-y-1"}
           data-testid={bureau ? "sidebar-liste" : undefined}>
        {(() => {
        // Lot 73 — dessin d'un lien du menu (inchangé), réutilisé pour les liens du groupe « Liluvine »
        const rendreLien = ({ to, label, tKey, icon: Icon, end, module, soon, badgeKey, featureGate, showBadges, disabled, disabledReason, alsoActive, fsBadges }) => {
          // Lot 27 — actif aussi sur les chemins associés (ex. sondages sous « Formulaires & Sondages »)
          const extraActive = (alsoActive || []).some((p) => location.pathname === p || location.pathname.startsWith(p + "/"));
          // Lot 23 — le badge du Centre de Messagerie affiche le MÊME nombre que la cloche
          // et que les pastilles des contacts (/me/whatsapp/unread, relu toutes les 15 s
          // et dès qu'une conversation est lue), au lieu d'un second compteur relu toutes les 90 s.
          const rawCount = module === "contacts_unread"
            ? (waNotifier.unread || 0)
            : module ? (badges[module] || 0) : 0;
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
                  : `sidebar-link ${isActive || extraActive ? "active" : ""} group`
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
              {/* Lot 41 — nouvelles données : formulaires (vert) et sondages (bleu) */}
              {fsBadges && !isDisabled && fsNouveautes.formulaires > 0 && (
                <span
                  className="inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full bg-emerald-500 text-white text-[10px] font-bold tabular-nums ring-2 ring-[#0E1F3D] animate-in fade-in slide-in-from-right-1"
                  data-testid="badge-fs-formulaires"
                  title={`${fsNouveautes.formulaires} nouvelle(s) soumission(s) de formulaire`}
                >
                  {fsNouveautes.formulaires > 99 ? "99+" : fsNouveautes.formulaires}
                </span>
              )}
              {fsBadges && !isDisabled && fsNouveautes.sondages > 0 && (
                <span
                  className="inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full bg-sky-500 text-white text-[10px] font-bold tabular-nums ring-2 ring-[#0E1F3D] animate-in fade-in slide-in-from-right-1"
                  data-testid="badge-fs-sondages"
                  title={`${fsNouveautes.sondages} nouvelle(s) réponse(s) de sondage`}
                >
                  {fsNouveautes.sondages > 99 ? "99+" : fsNouveautes.sondages}
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
        };
        return rendreMenu(links, rendreLien);
        })()}
      </nav>

      <div className={bureau ? "shrink-0 mt-3 border-t border-white/10 pt-3" : "mt-8 border-t border-white/10 pt-4"}
           data-testid={bureau ? "sidebar-bas" : undefined}>
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
        {/* Lot 79.10 — bas de la barre latérale COMPACT : une seule ligne d'icônes toujours visible
            (Notif · Son · Base Atlas pour l'administrateur · Réglages) ; un clic sur Base Atlas ou Réglages
            déplie son détail juste en dessous (un seul panneau ouvert à la fois). Rien n'a été retiré. */}
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
            {/* Base Atlas (administrateur) : pastille couleur + % */}
            {user?.role === "admin" && (
              <PastilleAtlas mesure={mesureAtlas} ouvert={panneauBas === "atlas"}
                onClick={() => setPanneauBas((p) => (p === "atlas" ? null : "atlas"))} />
            )}
            {/* Réglages : préférences de son, mode sombre, notes VIDAL */}
            <button type="button" onClick={() => setPanneauBas((p) => (p === "reglages" ? null : "reglages"))}
              aria-expanded={panneauBas === "reglages"}
              className={`inline-flex items-center justify-center text-[10px] rounded px-1.5 py-1 ring-1 transition-colors ${panneauBas === "reglages" ? "bg-white/15 text-white ring-white/30" : "bg-white/5 text-slate-300 ring-white/10 hover:bg-white/10"}`}
              title="Réglages : préférences de son, mode sombre, notes VIDAL" data-testid="bouton-reglages-bas">
              <Settings className="h-3 w-3" />
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
          {/* Panneau déplié : détail de la base Atlas */}
          {panneauBas === "atlas" && user?.role === "admin" && (
            <div className="pt-1.5 border-t border-white/10"><DetailAtlas mesure={mesureAtlas} /></div>
          )}
          {/* Panneau déplié : réglages */}
          {panneauBas === "reglages" && (
            <div className="pt-1.5 border-t border-white/10 space-y-1.5" data-testid="portal-ui-settings">
          {waNotifier.soundAllowedByAdmin && waNotifier.soundOn && (
            <WaSoundPreferences
              adminDefaults={waNotifier.soundAdminDefaults}
              disabled={false}
              onChange={waNotifier.refreshSoundConfig}
            />
          )}
          <button
            type="button"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            className="w-full flex items-center justify-between text-xs text-slate-200 hover:text-white"
            data-testid="toggle-theme"
          >
            <span className="inline-flex items-center gap-1.5">
              {theme === "dark" ? <Moon className="h-3.5 w-3.5" /> : <Sun className="h-3.5 w-3.5" />}
              Mode sombre
            </span>
            <span className={`inline-block w-8 h-[18px] rounded-full relative transition-colors ${theme === "dark" ? "bg-sawali-blue" : "bg-white/15"}`}>
              <span className={`absolute top-[2px] left-[2px] w-[14px] h-[14px] rounded-full bg-white transition-transform ${theme === "dark" ? "translate-x-[14px]" : ""}`} />
            </span>
          </button>
          {isAdminOrSup && (
            <button
              type="button"
              onClick={() => setVidalAdminNotes(!vidalAdminNotes)}
              className="w-full flex items-center justify-between text-xs text-slate-200 hover:text-white"
              data-testid="toggle-vidal-admin-notes"
            >
              <span className="inline-flex items-center gap-1.5">
                <StickyNote className="h-3.5 w-3.5" />
                Notes VIDAL (admin)
              </span>
              <span className={`inline-block w-8 h-[18px] rounded-full relative transition-colors ${vidalAdminNotes ? "bg-sawali-blue" : "bg-white/15"}`}>
                <span className={`absolute top-[2px] left-[2px] w-[14px] h-[14px] rounded-full bg-white transition-transform ${vidalAdminNotes ? "translate-x-[14px]" : ""}`} />
              </span>
            </button>
          )}
            </div>
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
    <div className="h-screen bg-slate-50 dark:bg-slate-950 flex overflow-hidden">
      {/* Desktop sidebar — full screen height, never moves; its own scroll
          when the menu is taller than the viewport. Using a non-sticky
          shell prevents the "pinned-then-truncated" bug some browsers
          exhibit with `position: sticky` inside a flex row. */}
      {/* Lot 54 — le défilement se fait dans la liste du milieu ; celui de l'aside ne sert plus
          qu'en dernier recours, sur un écran très bas où le haut et le bas ne tiennent pas. */}
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
        {renderSidebar(true)}
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
            {renderSidebar(false)}
          </aside>
        </div>
      )}

      {/* Main column scrolls independently — keeps the sidebar perfectly stable. */}
      <div className="flex-1 flex flex-col min-w-0 h-screen overflow-y-auto overflow-x-hidden dark:bg-slate-950">
        <DemoBanner />
        <IncidentBanner />
        <header className="lg:hidden sticky top-0 z-40 bg-white dark:bg-slate-900 dark:border-slate-800 border-b flex items-center justify-between px-4 h-14">
          <button onClick={() => setOpen(true)} aria-label="Menu" data-testid="portal-menu-toggle">
            <Menu className="h-5 w-5" />
          </button>
          <div className="flex items-center gap-2">
            {admin ? <ShieldCheck className="h-4 w-4 text-sawali-blue" /> : <Mail className="h-4 w-4 text-sawali-blue" />}
            <span className="font-display font-semibold text-sm dark:text-white">{admin ? "Admin SAWALI" : "Espace Loois"}</span>
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
        {/* Lot 50 — date de la dernière sauvegarde générale (discret) */}
        <DerniereSauvegarde variante="pied" />
        {/* Lot 79.13 — sur téléphone : version en bas de page (plus de libellé flottant sur le contenu) */}
        <VersionStamp variante="pied" />
      </div>
      <VersionStamp tone="dark" />
      {showBriefing && <WelcomeBriefing onClose={() => setShowBriefing(false)} isComptaStrict={isComptaStrict} />}
      {/* Iter38r-fix7 — Comptable strict: hide the internal chat bubble entirely. */}
      {!isComptaStrict && <InternalChatPanel />}
      <TicketsBubble />
      {/* Lot 60 — appels WhatsApp : sonnerie, décroché dans le navigateur, journal */}
      {!isComptaStrict && <AppelsWhatsApp />}
      {/* Lot 64.9 — bulle à chaque statistique de plateforme qui change (administrateur) */}
      <VeilleStatsPlateformes />
      {/* Iter38r-fix9e — Live toast for Liluvine WhatsApp auto-replies (admins + superviseurs only). */}
      {isAdminOrSup && <LiluvineLiveToast />}
      {/* Lot 72 — administrateur ou superviseur (y compris utilisateur suivi de ce rôle) : appels de l'agenda */}
      {(isAdminOrSup || ["Administrateur", "Superviseur"].includes(user?.tracked_role))
        && (!partageLiluvine?.restreint || (partageLiluvine.elements || []).includes("alertes")) && <AlertesAppelsLiluvine />}
      <BrowserNotifications />
    </div>
  );
}
