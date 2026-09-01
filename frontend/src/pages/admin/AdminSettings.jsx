import React, { useEffect, useState, useMemo, useRef, useCallback, createContext, useContext } from "react";
import { apiClient } from "@/lib/api";
import { applyBrandingLocal } from "@/lib/useUIFlags";
import { useSearchParams, Link } from "react-router-dom";
import { Save, ShieldCheck, Calendar, Mail, ExternalLink, AlertCircle, CheckCircle2, Globe, Webhook, Video, Upload, MessageCircle, ClipboardList, Activity, RotateCcw, Mic, Tag, Sparkles, Smartphone, CreditCard, KeyRound, Headphones, Copy, Database, RefreshCw, Wrench, Search, ChevronDown, X, Download, FileArchive, Trash2, Pencil, Cloud, Inbox, UserCog, Check, MessageSquare, Lock, Ticket, Link2, Megaphone, Brain, Bell, Clock, Bot, Package, Building2, MapPin } from "lucide-react";
import PasswordInput from "@/components/PasswordInput";
import { toast } from "sonner";
import { phonePlaceholder } from "@/lib/tenantMeta";
import PayrollWebhooksSection from "@/pages/admin/sections/PayrollWebhooksSection";
import PlanningWebhookSection from "@/pages/admin/sections/PlanningWebhookSection";
import LiluvineReactionsSection from "@/pages/admin/sections/LiluvineReactionsSection";
import MetaConfigSection from "@/pages/admin/sections/MetaConfigSection";
import WeatherWidgetSection from "@/pages/admin/sections/WeatherWidgetSection";
import LiluvineWaAutoreplySection from "@/pages/admin/sections/LiluvineWaAutoreplySection";
import LiluvineKnowledgeBaseSection from "@/pages/admin/sections/LiluvineKnowledgeBaseSection";
import LiluvineBrandingSection from "@/pages/admin/sections/LiluvineBrandingSection";
import LiluvineSystemPromptSection from "@/pages/admin/sections/LiluvineSystemPromptSection";
import VidalActionsSection from "@/components/admin/VidalActionsSection";
import GardeReplyTemplateSection from "@/pages/admin/sections/GardeReplyTemplateSection";
import GardePublicPageSection from "@/pages/admin/sections/GardePublicPageSection";
import IntegrationHealthSection from "@/pages/admin/sections/IntegrationHealthSection";
import WaCommandImagesSection from "@/pages/admin/sections/WaCommandImagesSection";
import LiluvineBypassEmailsSection from "@/pages/admin/sections/LiluvineBypassEmailsSection";
import LiluvineModuleAclSection from "@/pages/admin/sections/LiluvineModuleAclSection";
import WaSilentPhonesSection from "@/pages/admin/sections/WaSilentPhonesSection";
import WaSilentDropsSection from "@/pages/admin/sections/WaSilentDropsSection";
import WaNotificationSoundSection from "@/pages/admin/sections/WaNotificationSoundSection";
import S057ThemingSection from "@/pages/admin/sections/S057ThemingSection";
import S058VidalSection from "@/pages/admin/sections/S058VidalSection";
import S059SyntheseOfficinesSection from "@/pages/admin/sections/S059SyntheseOfficinesSection";
import WaOtpTester from "@/pages/admin/sections/WaOtpTester";
import TemplatesOtpSection from "@/pages/admin/sections/TemplatesOtpSection";
import IncidentsAndCountrySection from "@/pages/admin/sections/IncidentsAndCountrySection";
import ErrorSeverityMappingSection from "@/pages/admin/sections/ErrorSeverityMappingSection";
import CouponsSection from "@/pages/admin/sections/CouponsSection";
import StripeWebhookSection from "@/pages/admin/sections/StripeWebhookSection";
import LinkedInSection from "@/pages/admin/sections/LinkedInSection";
import TwitterSection from "@/pages/admin/sections/TwitterSection";
import FacebookSection from "@/pages/admin/sections/FacebookSection";
import GoogleCalendarWatchPanel from "@/pages/admin/sections/GoogleCalendarWatchPanel";
import AiSubscriptionsSection from "@/pages/admin/sections/AiSubscriptionsSection";
import LlmBudgetTestButton from "@/components/LlmBudgetTestButton";
import LiluvineEscalationTestButton from "@/components/LiluvineEscalationTestButton";
import QdrantRagSection from "@/components/QdrantRagSection";

// ============================================================
// iter33 — Searchable Settings + "Nouveau" bubble system
// ----------------------------------------------------------
// Context shared by every <Section> and the 4 custom cards. Each card calls
// useSettingsFilter() to:
//   • Hide itself if the search query doesn't match its title
//   • Render a blue "NEW" bubble when its `addedAt` is recent AND the user
//     hasn't dismissed/used it for 3 full days yet (per-browser, localStorage)
// The toolbar at the top of the page provides the search input and a
// jump-to-section dropdown built from the list of registered titles.
// ============================================================
const NEW_SECTIONS = {
  // 2026-02 (fork) — Configurable WhatsApp inbound notification sound
  "🔔 WhatsApp — Son de notification (message entrant)": "2026-02-14",
  // S-iter39o (2026-02 post-handoff) — Qdrant RAG
  "RAG (Qdrant) — Base de connaissance vectorielle (S038)": "2026-02-02",
  // S-iter39k (2026-02 post-handoff) — Liluvine escalation
  "Liluvine PRO — Demande d'aide WhatsApp à l'admin (S036)": "2026-02-02",
  // S-iter39g (2026-02 post-handoff) — Universal Key burn-rate thresholds
  "Universal Key Emergent — Seuils de consommation & alertes (S032)": "2026-02-02",
  // S-iter39e (2026-02 post-handoff) — Approval workflow + signers notify
  "Sécurité — Approbation WhatsApp pour téléchargements (S025)": "2026-02-02",
  "PV de réunions — Notification automatique des signataires (S026)": "2026-02-02",
  // S-iter39b (2026-02 post-handoff) — Nouveaux modules
  "Nouveaux modules — PV de réunions / Visionneuse PDF / Filtre Liluvine": "2026-02-01",
  // Iter38o (2026-05-27)
  "Intégration Meta (Facebook / Messenger / Ads)": "2026-05-26",
  "Webhooks Paie (n8n)": "2026-05-24",
  // Iter37h.A — Recently added (2026-05-24 → 2026-05-25)
  "Recalibrage des tenants Caisse/Facturation": "2026-05-24",
  "Briefing de bienvenue — Mode du compteur 'Non lus'": "2026-05-24",
  // Iter36e — recent addition
  "Note de Service (historique + template)": "2026-05-19",
  // Iter35x — recent additions
  "Notifications vocales Alexa (Voice Monkey)": "2026-05-19",
  "Historique des modifications de clés": "2026-05-19",
  "Restauration des contacts/messages (revert retag)": "2026-05-11",
  "Demandes de modification de profil (utilisateurs)": "2026-05-11",
  "Suivi des actions (historique du travail)": "2026-05-10",
  "Sauvegarde de la base (Snapshot)": "2026-05-10",
  "Diagnostic des données orphelines": "2026-05-09",
  "Cohérence multi-utilisateurs (panoramique)": "2026-05-10",
  "Diagnostic visibilité par utilisateur": "2026-05-10",
  "Jauge d'occupation du Support technique": "2026-05-01",
  "Compteur de visites (page d'accueil)": "2026-04-30",
  "Bandeau d'incident (public + portail)": "2026-04-30",
  "Santé applicative — Alertes & rapports": "2026-04-30",
  "Authentification — OTP par domaine": "2026-04-26",
};
// Iter37h.A — Bump the visibility window so newly-added sections actually show.
const NEW_WINDOW_DAYS = 21;  // was 3 (caused badges to vanish before users even saw them)
const STORAGE_KEY_SEEN = "sawali_settings_first_seen_v1";
const SEEN_FADE_DAYS = 3;
function readSeen() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY_SEEN) || "{}"); } catch { return {}; }
}
function writeSeen(map) {
  try { localStorage.setItem(STORAGE_KEY_SEEN, JSON.stringify(map)); } catch { /* ignore */ }
}
const SettingsFilterCtx = createContext(null);
const useSettingsFilter = () => useContext(SettingsFilterCtx);

// S-iter39q — Settings page split into tabs. Each section's category is
// derived from its title via keyword matching so we don't have to
// manually annotate the 30+ existing `<Filterable>` blocks. The bare
// `<Section>` calls (reCAPTCHA, SMTP, OTP, Google Auth…) are bucketed
// into "Sécurité & Auth" by default.
const TABS = [
  { key: "all",         label: "Tous",                emoji: "📋" },
  { key: "auth",        label: "Sécurité & Auth",     emoji: "🔐" },
  { key: "liluvine",    label: "Liluvine PRO",        emoji: "🤖" },
  { key: "meta",        label: "META (FB / WA)",      emoji: "💬" },
  { key: "ia",          label: "IA & Universal Key",  emoji: "🧠" },
  { key: "paiements",   label: "Paiements & Caisse",  emoji: "💳" },
  { key: "comms",       label: "Communications",      emoji: "📨" },
  { key: "rh",          label: "GRH & Personnel",     emoji: "👥" },
  { key: "modules",     label: "Modules & Bonus",     emoji: "✨" },
  { key: "meteo",       label: "Météo",               emoji: "🌤️" },
  { key: "diagnostics", label: "Diagnostics & Logs",  emoji: "🛠️" },
];

function categoryOf(title = "") {
  const t = title.toLowerCase();
  if (/qdrant|universal key|llm|liluvine|kb|ocr|rag|gpt|claude/i.test(title)) {
    if (/liluvine|kb|ocr/i.test(title)) return "liluvine";
    return "ia";
  }
  if (/whatsapp|wa\b|facebook|messenger|meta\b|approbation/i.test(title)) return "meta";
  if (/météo|meteo|weather/i.test(title)) return "meteo";
  if (/stripe|paywall|pawapay|coupon|paiement|caisse|facture|abonnement/i.test(title)) return "paiements";
  if (/email|sms|smtp|otp|notification|alexa|note de service|template|digest|pv de réunion/i.test(title)) return "comms";
  if (/grh|paie|salaire|personnel|webhook paie/i.test(title)) return "rh";
  if (/recaptcha|sécurité|gdpr|brute|approval|2fa|mfa|téléchargement|téléchargements|signature|auth|verrouillage/i.test(title)) return "auth";
  if (/diagnostic|log|historique|orphelins|orphans|version/i.test(title)) return "diagnostics";
  return "modules";
}
function isStillNew(title, seenMap) {
  const addedAt = NEW_SECTIONS[title];
  if (!addedAt) return false;
  const now = Date.now();
  const added = new Date(addedAt).getTime();
  if (isNaN(added) || (now - added) / 86400000 > NEW_WINDOW_DAYS) return false;
  const seen = seenMap?.[title];
  if (!seen) return true;
  return (now - new Date(seen).getTime()) / 86400000 < SEEN_FADE_DAYS;
}
function slugify(title) {
  return (title || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

const Filterable = ({ title, anchorId, category, children }) => {
  const ctx = useSettingsFilter();
  const ref = useRef(null);
  const [, force] = useState(0);
  const cat = category || categoryOf(title);
  useEffect(() => {
    if (!ctx) return;
    ctx.register(title, anchorId, cat);
    return () => ctx.unregister(title);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title, anchorId, cat]);
  useEffect(() => {
    if (!ref.current || !ctx) return;
    if (!isStillNew(title, ctx.seenMap || {})) return;
    const obs = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting && !ctx.seenMap[title]) {
          ctx.markSeen(title);
          force((n) => n + 1);
        }
      });
    }, { threshold: 0.4 });
    obs.observe(ref.current);
    return () => obs.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title]);
  if (ctx?.search) {
    if (!title.toLowerCase().includes(ctx.search.toLowerCase())) return null;
  }
  // S-iter39q — Tab-based filtering. When activeTab !== "all", hide
  // sections that don't belong to the active tab.
  if (ctx?.activeTab && ctx.activeTab !== "all" && cat !== ctx.activeTab) return null;
  const showNew = isStillNew(title, ctx?.seenMap || {});
  return (
    <div ref={ref} id={anchorId} className="relative scroll-mt-32" data-settings-anchor={anchorId}>
      {showNew && (
        <span
          className="absolute -top-2 -left-2 z-10 inline-flex items-center gap-1 rounded-full bg-sky-600 text-white px-2 py-0.5 text-[10px] font-bold shadow-lg ring-2 ring-white animate-pulse"
          title={`Nouveau (${NEW_SECTIONS[title]}) — disparaîtra ${SEEN_FADE_DAYS} jours après votre première consultation`}
          data-testid={`new-badge-${anchorId}`}
        >
          • NOUVEAU
        </span>
      )}
      {children}
    </div>
  );
};

const SettingsToolbar = () => {
  const ctx = useSettingsFilter();
  const titles = useMemo(() => Object.keys(ctx?.registry || {}).sort((a, b) => a.localeCompare(b)), [ctx?.registry]);
  // S-iter39q — Filter titles by active tab so the dropdown stays in sync
  const visibleTitles = useMemo(() => {
    if (!ctx?.activeTab || ctx.activeTab === "all") return titles;
    return titles.filter((t) => (ctx.registry[t]?.category || categoryOf(t)) === ctx.activeTab);
  }, [titles, ctx?.activeTab, ctx?.registry]);
  // Count items per tab for the badge (computed before any early return so
  // React hook order stays stable across renders)
  const countsPerTab = useMemo(() => {
    const c = {};
    titles.forEach((t) => {
      const k = ctx?.registry?.[t]?.category || categoryOf(t);
      c[k] = (c[k] || 0) + 1;
    });
    return c;
  }, [titles, ctx?.registry]);
  if (!ctx) return null;
  const newCount = visibleTitles.filter((t) => isStillNew(t, ctx.seenMap)).length;
  const matchCount = ctx.search ? visibleTitles.filter((t) => t.toLowerCase().includes(ctx.search.toLowerCase())).length : visibleTitles.length;
  return (
    <div className="sticky top-0 z-30 -mx-3 sm:-mx-6 lg:-mx-10 px-3 sm:px-6 lg:px-10 py-3 bg-slate-50/95 backdrop-blur border-b border-slate-200" data-testid="settings-toolbar">
      {/* S-iter39q — Tab bar */}
      <div className="flex gap-1 overflow-x-auto pb-2 -mx-1 px-1" data-testid="settings-tab-bar">
        {TABS.map((t) => {
          const count = t.key === "all" ? titles.length : (countsPerTab[t.key] || 0);
          const isActive = ctx.activeTab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => ctx.setActiveTab(t.key)}
              className={`shrink-0 text-xs px-3 py-1.5 rounded-full inline-flex items-center gap-1.5 transition ${isActive ? "bg-sawali-blue text-white shadow-md" : "bg-white ring-1 ring-slate-200 text-slate-700 hover:ring-slate-400"}`}
              data-testid={`settings-tab-${t.key}`}
            >
              <span>{t.emoji}</span>
              <span>{t.label}</span>
              {count > 0 && (
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-semibold ${isActive ? "bg-white/30" : "bg-slate-100 text-slate-600"}`}>{count}</span>
              )}
            </button>
          );
        })}
      </div>
      <div className="flex flex-col sm:flex-row gap-2 items-stretch sm:items-center">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
          <input
            value={ctx.search}
            onChange={(e) => ctx.setSearch(e.target.value)}
            placeholder="Rechercher un paramètre par son titre…"
            className="w-full pl-9 pr-9 py-2 rounded-lg border border-slate-300 text-sm bg-white"
            data-testid="settings-search-input"
          />
          {ctx.search && (
            <button onClick={() => ctx.setSearch("")} className="absolute right-2 top-2 text-slate-400 hover:text-slate-700" data-testid="settings-search-clear">
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
        <div className="relative shrink-0">
          <select
            value=""
            onChange={(e) => {
              const t = e.target.value;
              if (t && ctx.registry[t]) {
                document.getElementById(ctx.registry[t].anchorId)?.scrollIntoView({ behavior: "smooth", block: "start" });
              }
            }}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm pr-8 appearance-none w-full sm:w-72"
            data-testid="settings-jump-select"
          >
            {/* Iter43-fix23 — Pré-calculer le texte pour éviter le warning hydration
                (le Visual Editor wrappe les expressions dynamiques en <span>, invalides dans <option>) */}
            <option value="">{newCount > 0 ? `Aller à un paramètre…  (${newCount} nouveau${newCount > 1 ? "x" : ""})` : "Aller à un paramètre…"}</option>
            {visibleTitles.map((t) => {
              const label = isStillNew(t, ctx.seenMap) ? `🆕  ${t}` : t;
              return <option key={t} value={t}>{label}</option>;
            })}
          </select>
          <ChevronDown className="h-4 w-4 absolute right-2 top-2.5 text-slate-400 pointer-events-none" />
        </div>
      </div>
      {ctx.search && (
        <p className="text-[11px] text-slate-500 mt-1.5 ml-1" data-testid="settings-filter-info">
          {matchCount} paramètre(s) trouvé(s) pour « {ctx.search} »
        </p>
      )}
    </div>
  );
};

// Iter40-ui-flags-bg (S057) — Background editor for one scope (public or portal).
// Renders a mode select + conditional fields + live preview tile so the admin
// can verify the result without leaving Settings.
function BgEditor({ scope, label, s, upd }) {
  const mode = s[`${scope}_bg_mode`] || "default";
  const color = s[`${scope}_bg_color`] || "";
  const imageUrl = s[`${scope}_bg_image_url`] || "";
  const pos = s[`${scope}_bg_image_position`] || "cover";
  const set = (k, v) => upd(`${scope}_${k}`, v);
  const previewStyle = (() => {
    if (mode === "color" && color) return { backgroundColor: color };
    if (mode === "image" && imageUrl) {
      const base = { backgroundColor: color || "#0E1F3D" };
      if (pos === "repeat") return { ...base, backgroundImage: `url("${imageUrl}")`, backgroundRepeat: "repeat", backgroundSize: "auto", backgroundPosition: "top left" };
      if (pos === "contain") return { ...base, backgroundImage: `url("${imageUrl}")`, backgroundRepeat: "no-repeat", backgroundSize: "contain", backgroundPosition: "center" };
      if (pos === "center") return { ...base, backgroundImage: `url("${imageUrl}")`, backgroundRepeat: "no-repeat", backgroundSize: "auto", backgroundPosition: "center" };
      return { ...base, backgroundImage: `url("${imageUrl}")`, backgroundRepeat: "no-repeat", backgroundSize: "cover", backgroundPosition: "center" };
    }
    return { background: "linear-gradient(135deg, #0E1F3D 0%, #1E90FF 100%)" };
  })();
  return (
    <div className="rounded-xl ring-1 ring-slate-200 bg-slate-50/60 p-3 space-y-2" data-testid={`bg-editor-${scope}`}>
      <p className="text-[11px] font-semibold text-slate-700">{label}</p>
      <div>
        <label className="text-[10px] uppercase text-slate-500 mb-1 block">Mode</label>
        <select
          value={mode}
          onChange={(e) => set("bg_mode", e.target.value)}
          className="w-full text-xs rounded ring-1 ring-slate-300 bg-white px-2 py-1.5"
          data-testid={`bg-${scope}-mode`}
        >
          <option value="default">Défaut (palette SAWALI)</option>
          <option value="color">Couleur unie</option>
          <option value="image">Image de fond</option>
        </select>
      </div>
      {mode === "color" && (
        <div>
          <label className="text-[10px] uppercase text-slate-500 mb-1 block">Couleur de fond</label>
          <div className="flex items-center gap-2">
            <input
              type="color"
              value={color || "#0E1F3D"}
              onChange={(e) => set("bg_color", e.target.value)}
              className="h-8 w-10 rounded ring-1 ring-slate-300 cursor-pointer"
              data-testid={`bg-${scope}-color-picker`}
            />
            <input
              type="text"
              value={color}
              onChange={(e) => set("bg_color", e.target.value)}
              placeholder="#0E1F3D"
              pattern="^#[0-9A-Fa-f]{6}$"
              className="flex-1 px-2 py-1.5 rounded ring-1 ring-slate-300 text-xs font-mono"
              data-testid={`bg-${scope}-color-hex`}
              maxLength={9}
            />
          </div>
        </div>
      )}
      {mode === "image" && (
        <>
          <div>
            <label className="text-[10px] uppercase text-slate-500 mb-1 block">URL de l'image</label>
            <input
              type="url"
              value={imageUrl}
              onChange={(e) => set("bg_image_url", e.target.value)}
              placeholder="https://… ou /api/files/<id>"
              className="w-full px-2 py-1.5 rounded ring-1 ring-slate-300 text-xs"
              data-testid={`bg-${scope}-image-url`}
            />
            <p className="text-[10px] text-slate-500 italic mt-1">
              Utilisez l'uploader de logo ci-dessus pour téléverser une image (puis collez son URL ici).
            </p>
          </div>
          <div>
            <label className="text-[10px] uppercase text-slate-500 mb-1 block">Affichage de l'image</label>
            <select
              value={pos}
              onChange={(e) => set("bg_image_position", e.target.value)}
              className="w-full text-xs rounded ring-1 ring-slate-300 bg-white px-2 py-1.5"
              data-testid={`bg-${scope}-image-position`}
            >
              <option value="cover">Plein écran (cover, recommandé)</option>
              <option value="contain">Contenue (contain — image entière visible)</option>
              <option value="center">Centrée (taille originale, sans répétition)</option>
              <option value="repeat">Répétée en mosaïque (pattern / motif)</option>
            </select>
          </div>
          <div>
            <label className="text-[10px] uppercase text-slate-500 mb-1 block">Couleur d'arrière-plan (optionnelle, sous l'image)</label>
            <input
              type="color"
              value={color || "#0E1F3D"}
              onChange={(e) => set("bg_color", e.target.value)}
              className="h-8 w-10 rounded ring-1 ring-slate-300 cursor-pointer"
              data-testid={`bg-${scope}-overlay-color`}
            />
          </div>
        </>
      )}
      {/* Live preview tile */}
      <div className="h-24 rounded ring-1 ring-slate-300 overflow-hidden" style={previewStyle} data-testid={`bg-${scope}-preview`}>
        <div className="h-full w-full bg-black/0 backdrop-blur-[0px] flex items-center justify-center">
          <span className="text-xs text-white/80 font-semibold drop-shadow">Aperçu</span>
        </div>
      </div>
    </div>
  );
}


export default function AdminSettings() {
  const [s, setS] = useState({});
  const [loading, setLoading] = useState(false);
  const [params] = useSearchParams();

  const load = () => apiClient.get("/admin/settings").then((r) => setS(r.data));
  useEffect(() => {
    load().catch(() => {});
    if (params.get("gcal") === "ok") toast.success("Google Calendar connecté");
    if (params.get("gcal") === "error") toast.error("Erreur Google Calendar : " + (params.get("msg") || ""));
  }, [params]);

  const save = async () => {
    setLoading(true);
    try {
      const payload = { ...s };
      // Don't send masked values
      for (const k of ["smtp_password", "google_client_secret", "recaptcha_secret_key", "tracking_auth_header", "webhook_token", "webhook_basic_pass", "notes_webhook_token", "notes_webhook_basic_pass", "health_webhook_token", "health_webhook_basic_pass", "wa_access_token", "wa_verify_token", "openai_api_key", "openai_chat_api_key", "n8n_webhook_token", "n8n_webhook_basic_pass",
        "sms_orange_token", "sms_orange_basic_pass", "sms_orange_header_value",
        "sms_moov_token", "sms_moov_basic_pass", "sms_moov_header_value",
        "sms_telecel_token", "sms_telecel_basic_pass", "sms_telecel_header_value",
        "sms_ovh_application_secret", "sms_ovh_consumer_key",
        "pawapay_api_token"]) {
        if (payload[k] === "********") delete payload[k];
      }
      delete payload.google_calendar_connected;
      // Iter43-fix24o — VIDAL fields are managed by their own endpoint
      // (/admin/vidal/config in `S058VidalSection`). Stripping them from the
      // global Save avoids the stale-state regression where the page-level
      // state still holds OLD vidal credentials and overwrites the freshly
      // saved ones.
      for (const k of Object.keys(payload)) {
        if (k.startsWith("vidal_")) delete payload[k];
      }
      await apiClient.put("/admin/settings", payload);
      toast.success("Paramètres enregistrés");
      // Iter40-ui-flags — Notify the global hook so the localStorage cache is
      // refreshed (other open tabs / fresh reloads will pick up the new values).
      try { window.dispatchEvent(new CustomEvent("ui-flags-updated")); } catch { /* ignore */ }
      await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setLoading(false); }
  };

  const connectGoogle = async () => {
    try {
      const r = await apiClient.get("/admin/google/auth-url");
      window.location.href = r.data.auth_url;
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };
  const disconnectGoogle = async () => {
    await apiClient.post("/admin/google/disconnect");
    toast.success("Déconnecté"); await load();
  };
  // Iter43-fix24ao (2026-06-17) — Test the live Google Calendar connection
  // (lists the next 3 upcoming events) without creating any event.
  const [gcalTestState, setGcalTestState] = useState({ loading: false, result: null });
  const testGoogleConnection = async () => {
    setGcalTestState({ loading: true, result: null });
    try {
      const r = await apiClient.get("/admin/google/test-connection");
      setGcalTestState({ loading: false, result: r.data });
      if (r.data?.ok) {
        toast.success(`Google Calendar OK — ${r.data.events_count} événement(s) à venir`);
      } else {
        toast.error(r.data?.message || "Échec du test de connexion");
      }
    } catch (err) {
      const msg = err?.response?.data?.detail || err?.message || "Erreur réseau";
      setGcalTestState({ loading: false, result: { ok: false, message: msg } });
      toast.error(msg);
    }
  };

  const upd = (k, v) => setS({ ...s, [k]: v });

  // iter33 — Settings filter context state
  // S-iter39q — Adds `activeTab` to the registry (tab-scoped filtering).
  const [search, setSearch] = useState("");
  const [activeTab, setActiveTab] = useState(() => {
    try { return localStorage.getItem("adminSettings.activeTab") || "all"; } catch { return "all"; }
  });
  useEffect(() => {
    try { localStorage.setItem("adminSettings.activeTab", activeTab); } catch { /* ignore */ }
  }, [activeTab]);
  const [registry, setRegistry] = useState({});  // {title: {anchorId, category}}
  const [seenMap, setSeenMap] = useState(() => readSeen());
  const register = (title, anchorId, category) => setRegistry((m) => {
    const prev = m[title];
    if (prev && prev.anchorId === anchorId && prev.category === category) return m;
    return { ...m, [title]: { anchorId, category } };
  });
  const unregister = (title) => setRegistry((m) => { const n = { ...m }; delete n[title]; return n; });
  const markSeen = (title) => setSeenMap((m) => {
    if (m[title]) return m;
    const n = { ...m, [title]: new Date().toISOString() };
    writeSeen(n);
    return n;
  });
  const filterCtxValue = useMemo(
    () => ({ search, setSearch, activeTab, setActiveTab, registry, register, unregister, seenMap, markSeen }),
    [search, activeTab, registry, seenMap],
  );

  return (
    <SettingsFilterCtx.Provider value={filterCtxValue}>
    <div className="space-y-8" data-testid="admin-settings-page">
      <div>
        <h1 className="text-2xl font-display font-bold">Paramètres</h1>
        <p className="text-sm text-slate-500">Configurez reCAPTCHA, l'envoi d'OTP par email et Google Calendar.</p>
      </div>
      <SettingsToolbar />

      <Section icon={ShieldCheck} title="Google reCAPTCHA v2">
        <Toggle label="Activer reCAPTCHA" value={!!s.recaptcha_enabled} onChange={(v) => upd("recaptcha_enabled", v)} testid="toggle-recaptcha" />
        <Input label="Site Key" value={s.recaptcha_site_key || ""} onChange={(v) => upd("recaptcha_site_key", v)} testid="recaptcha-site" />
        <Input label="Secret Key" type="password" value={s.recaptcha_secret_key || ""} onChange={(v) => upd("recaptcha_secret_key", v)} testid="recaptcha-secret" placeholder={s.recaptcha_secret_key === "********" ? "Cliquez pour modifier (déjà défini)" : ""} />
        <p className="text-xs text-slate-500">Obtenez vos clés sur <a href="https://www.google.com/recaptcha/admin" target="_blank" rel="noreferrer" className="text-sawali-blue underline">google.com/recaptcha/admin</a>.</p>
      </Section>

      <Section icon={Mail} title="SMTP (envoi des codes OTP par email)">
        <div className="grid sm:grid-cols-2 gap-3">
          <Input label="Host" value={s.smtp_host || ""} onChange={(v) => upd("smtp_host", v)} placeholder="smtp.gmail.com" testid="smtp-host" />
          <Input label="Port" type="number" value={s.smtp_port || ""} onChange={(v) => upd("smtp_port", parseInt(v) || 0)} placeholder="587" testid="smtp-port" />
          <Input label="Utilisateur" value={s.smtp_user || ""} onChange={(v) => upd("smtp_user", v)} testid="smtp-user" />
          <Input label="Mot de passe" type="password" value={s.smtp_password || ""} onChange={(v) => upd("smtp_password", v)} testid="smtp-password" placeholder={s.smtp_password === "********" ? "(déjà défini)" : ""} />
          <Input label="From email" value={s.smtp_from_email || ""} onChange={(v) => upd("smtp_from_email", v)} testid="smtp-from" />
          <Input label="Nom expéditeur visible" value={s.smtp_from_name || ""} onChange={(v) => upd("smtp_from_name", v)} placeholder="SAWALI SMART SYSTEMS" testid="smtp-from-name" />
        </div>
        <Toggle label="Utiliser STARTTLS" value={s.smtp_use_tls !== false} onChange={(v) => upd("smtp_use_tls", v)} testid="smtp-tls" />
      </Section>

      <Section icon={KeyRound} title="Authentification — OTP par domaine">
        <p className="text-xs text-slate-500">
          Les emails appartenant à un domaine interne <strong>affichent le code OTP directement</strong> sur la page de connexion
          (badge « Plateforme Interne ») au lieu de l'envoyer par email. Utile pour votre équipe.
          Tous les autres utilisateurs reçoivent leur code par e-mail via SMTP.
        </p>
        <Input
          label="Domaines internes (séparés par virgule)"
          value={s.internal_domains || ""}
          onChange={(v) => upd("internal_domains", v)}
          placeholder="sawalismartsystems.com, sawali.local"
          testid="internal-domains"
        />
        <p className="text-[10px] text-slate-400">
          Valeur par défaut : <code>sawalismartsystems.com</code>. Laissez vide pour forcer l'envoi par email pour tous.
        </p>
        <div className="pt-2 border-t border-slate-100">
          <Toggle
            label="Tag obligatoire dans les contacts (CRM)"
            value={!!s.contacts_require_tag}
            onChange={(v) => upd("contacts_require_tag", v)}
            testid="contacts-require-tag"
          />
          <p className="text-[10px] text-slate-400 mt-0.5">
            Si activé, les utilisateurs doivent renseigner au moins un tag pour créer ou modifier un contact.
          </p>
        </div>
      </Section>

      <Section icon={Calendar} title="Google Calendar">
        <p className="text-sm text-slate-500">Calendrier ciblé : <strong>{s.google_calendar_email || "(non défini)"}</strong></p>
        <Input label="Email du calendrier" value={s.google_calendar_email || ""} onChange={(v) => upd("google_calendar_email", v)} placeholder="sup.alphasofti@gmail.com" testid="gcal-email" />
        <Input label="Mot de passe (paramétrable, indicatif)" type="password" value={s.google_calendar_password_hint || ""} onChange={(v) => upd("google_calendar_password_hint", v)} testid="gcal-password" placeholder={s.google_calendar_password_hint === "********" ? "(défini)" : "Information mémo, ne sert pas à l'API"} />
        <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded p-2 flex gap-2 items-start">
          <AlertCircle className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" /> Google n'autorise plus l'authentification par mot de passe. Utilisez OAuth2 ci-dessous (le mot de passe ci-dessus est purement informatif/mémo).
        </p>
        <div className="grid sm:grid-cols-2 gap-3">
          <Input label="Google Client ID" value={s.google_client_id || ""} onChange={(v) => upd("google_client_id", v)} testid="gcal-client-id" />
          <Input label="Google Client Secret" type="password" value={s.google_client_secret || ""} onChange={(v) => upd("google_client_secret", v)} testid="gcal-client-secret" placeholder={s.google_client_secret === "********" ? "(défini)" : ""} />
        </div>
        <div className="flex items-center gap-3 mt-4">
          {s.google_calendar_connected ? (
            <>
              <span className="inline-flex items-center gap-2 text-sm text-emerald-700"><CheckCircle2 className="h-4 w-4" /> Connecté</span>
              <button
                onClick={testGoogleConnection}
                disabled={gcalTestState.loading}
                className="text-sm inline-flex items-center gap-1.5 rounded-lg border border-emerald-300 bg-emerald-50 hover:bg-emerald-100 text-emerald-700 px-3 py-1.5 disabled:opacity-50"
                data-testid="gcal-test-connection"
              >
                {gcalTestState.loading ? "Test en cours…" : "🧪 Tester connexion"}
              </button>
              <button onClick={disconnectGoogle} className="text-sm text-rose-600 underline" data-testid="gcal-disconnect">Se déconnecter</button>
            </>
          ) : (
            <button onClick={connectGoogle} className="inline-flex items-center gap-2 rounded-lg border border-sawali-blue text-sawali-blue px-4 py-2 text-sm hover:bg-sawali-blue/10" data-testid="gcal-connect">
              <ExternalLink className="h-4 w-4" /> Connecter Google Calendar
            </button>
          )}
        </div>
        {/* Iter43-fix24ao — Test connection result panel */}
        {gcalTestState.result && (
          <div
            className={`mt-3 rounded-lg p-3 text-xs ring-1 ${gcalTestState.result.ok ? "bg-emerald-50 ring-emerald-200 text-emerald-900" : "bg-rose-50 ring-rose-200 text-rose-900"}`}
            data-testid="gcal-test-result"
          >
            {gcalTestState.result.ok ? (
              <>
                <p className="font-semibold mb-1">
                  ✅ Connexion OK — {gcalTestState.result.events_count} événement{gcalTestState.result.events_count > 1 ? "s" : ""} à venir
                </p>
                <p className="text-[10px] text-slate-600 mb-2">
                  Calendrier : <code>{gcalTestState.result.calendar_id}</code>
                </p>
                {(gcalTestState.result.events || []).length > 0 ? (
                  <ul className="space-y-1.5">
                    {gcalTestState.result.events.map((ev) => (
                      <li key={ev.id} className="rounded bg-white ring-1 ring-emerald-100 p-2" data-testid={`gcal-test-event-${ev.id}`}>
                        <p className="font-semibold">{ev.summary}</p>
                        <p className="text-[10px] text-slate-600">
                          {ev.start ? new Date(ev.start).toLocaleString("fr-FR") : "—"}{" "}
                          → {ev.end ? new Date(ev.end).toLocaleString("fr-FR") : "—"}
                        </p>
                        {ev.html_link && (
                          <a href={ev.html_link} target="_blank" rel="noopener noreferrer" className="text-[10px] text-emerald-700 underline">
                            Ouvrir dans Google Calendar →
                          </a>
                        )}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="italic text-slate-600">Aucun événement à venir (calendrier vide ou tous les événements sont passés).</p>
                )}
              </>
            ) : (
              <>
                <p className="font-semibold mb-1">❌ Échec du test</p>
                <p className="break-words">{gcalTestState.result.message}</p>
                {gcalTestState.result.reason === "not_connected" && (
                  <p className="text-[10px] italic mt-1">Cliquez sur « Connecter Google Calendar » ci-dessus.</p>
                )}
                {gcalTestState.result.error_type && (
                  <p className="text-[10px] font-mono mt-1 text-slate-600">type: {gcalTestState.result.error_type}</p>
                )}
              </>
            )}
          </div>
        )}
        <p className="text-xs text-slate-500">Sauvegardez les Client ID et Secret avant de cliquer sur Connecter.</p>
        {/* Iter43-fix24ay (2026-02-26) — Google Calendar Watch API (real-time push sync) */}
        {s.google_calendar_connected && <GoogleCalendarWatchPanel />}
      </Section>

      {/* Iter43-fix24az-b (2026-02-26) — Google Maps API key UI (was DB-only) */}
      <Section icon={MapPin} title="Google Maps (Géocodage des Officines)">
        <p className="text-sm text-slate-500">
          Permet de géocoder automatiquement les pharmacies (lat/lng) à partir de leur nom + ville.
          Sans clé, le système retombe sur <strong>OpenStreetMap Nominatim</strong> (gratuit mais moins précis en Afrique de l&apos;Ouest).
        </p>
        <Input
          label="Google Maps API Key"
          type="password"
          value={s.google_maps_api_key || ""}
          onChange={(v) => upd("google_maps_api_key", v)}
          testid="google-maps-api-key"
          placeholder={s.google_maps_api_key === "********" ? "(défini)" : "AIzaSy..."}
        />
        <Input
          label="Biais pays (ISO-3166, ex: BF, CI, ML)"
          value={s.geocode_country_bias || ""}
          onChange={(v) => upd("geocode_country_bias", v)}
          testid="geocode-country-bias"
          placeholder="BF"
        />
        <p className="text-[11px] text-slate-500">
          Obtenez votre clé sur{" "}
          <a href="https://console.cloud.google.com/google/maps-apis/credentials" target="_blank" rel="noreferrer" className="text-sawali-blue underline">
            console.cloud.google.com → Maps APIs → Credentials
          </a>{" "}
          (activez <em>Geocoding API</em> + <em>Places API</em>). Free tier : 5000 requêtes/mois.
        </p>
      </Section>

      <Section icon={Calendar} title="Heures ouvrables / RDV">
        <div className="grid sm:grid-cols-4 gap-3">
          <Input label="Ouverture activités" type="time" value={s.business_open_time || "09:00"} onChange={(v) => upd("business_open_time", v)} testid="open-time" />
          <Input label="Fermeture activités" type="time" value={s.business_close_time || "18:00"} onChange={(v) => upd("business_close_time", v)} testid="close-time" />
          <Input label="Heure de descente" type="time" value={s.descent_time || ""} onChange={(v) => upd("descent_time", v)} testid="descent-time" />
          <Input label="Durée créneau (min)" type="number" value={s.slot_duration_min || 30} onChange={(v) => upd("slot_duration_min", parseInt(v) || 30)} testid="slot-duration" />
        </div>
        <p className="text-[11px] text-slate-500">
          <strong>Heure de descente</strong> : seuil quotidien pour la création de Rapports / Suivis / Interventions.
          Au-delà de <strong>1 heure</strong> après cette heure, l'enregistrement est refusé pour la journée. Laisser vide pour désactiver.
        </p>
        <div className="flex flex-wrap gap-2 mt-2">
          {["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"].map((d, idx) => {
            const list = s.business_days || [];
            const on = list.includes(idx);
            return (
              <button key={idx} type="button" onClick={() => {
                const next = on ? list.filter((x) => x !== idx) : [...list, idx];
                upd("business_days", next.sort());
              }} className={`px-3 py-1.5 rounded text-xs ${on ? "bg-sawali-blue text-white" : "bg-slate-100 text-slate-700"}`} data-testid={`day-${idx}`}>
                {d}
              </button>
            );
          })}
        </div>
      </Section>

      <Section icon={Mail} title="Coordonnées de l'entreprise">
        <div className="grid sm:grid-cols-2 gap-3">
          <Input label="Email" value={s.company_email || ""} onChange={(v) => upd("company_email", v)} testid="company-email" />
          <Input label="Téléphone" value={s.company_phone || ""} onChange={(v) => upd("company_phone", v)} testid="company-phone" />
          <Input label="WhatsApp" value={s.company_whatsapp || ""} onChange={(v) => upd("company_whatsapp", v)} placeholder={phonePlaceholder()} testid="company-whatsapp" />
          <Input label="Adresse" value={s.company_address || ""} onChange={(v) => upd("company_address", v)} testid="company-address" />
          <Input label="Ville" value={s.company_city || ""} onChange={(v) => upd("company_city", v)} testid="company-city" />
          <Input label="Pays" value={s.company_country || ""} onChange={(v) => upd("company_country", v)} testid="company-country" />
        </div>
      </Section>

      <CountryPrefixSection />

      {/* S-iter39b — Récap des nouveaux modules livrés.
           Inscrit dans NEW_SECTIONS pour afficher le badge "NOUVEAU" dans la
           dropdown "Aller à un paramètre…" pendant 21 jours, dismissable. */}
      <Filterable title="Nouveaux modules — PV de réunions / Visionneuse PDF / Filtre Liluvine" anchorId="s-new-modules-39b">
        <Section icon={Sparkles} title="Nouveaux modules — Février 2026">
          <div className="space-y-3">
            <p className="text-xs text-slate-600">
              Trois modules ajoutés ce mois-ci, accessibles depuis la sidebar du portail :
            </p>
            <ul className="space-y-2 text-sm">
              <li className="rounded-lg ring-1 ring-fuchsia-200 bg-fuchsia-50/60 p-3" data-testid="new-module-meetings">
                <p className="font-semibold text-fuchsia-900">📋 PV de réunions internes</p>
                <p className="text-xs text-fuchsia-800 mt-0.5">
                  Procès-verbaux autonumérotés (PV-YYYY-NNN), éditeur riche avec Dicter, impression et export PDF. Heure de fin = clic sur Enregistrer.
                </p>
                <Link to="/portal/meetings" className="text-xs text-fuchsia-700 underline mt-1 inline-block" data-testid="new-module-meetings-link">Ouvrir le module →</Link>
              </li>
              <li className="rounded-lg ring-1 ring-sky-200 bg-sky-50/60 p-3" data-testid="new-module-pdf-viewer">
                <p className="font-semibold text-sky-900">📖 Visionneuse PDF interne</p>
                <p className="text-xs text-sky-800 mt-0.5">
                  Lecture en ligne des Brochures & Guides avec sommaire cliquable + recherche plein-texte. Téléchargement réservé Admin/Superviseur.
                </p>
                <Link to="/portal/brochures" className="text-xs text-sky-700 underline mt-1 inline-block" data-testid="new-module-pdf-link">Consulter les brochures →</Link>
              </li>
              <li className="rounded-lg ring-1 ring-emerald-200 bg-emerald-50/60 p-3" data-testid="new-module-liluvine-recent">
                <p className="font-semibold text-emerald-900">🕒 Liluvine PRO — Filtre 3 dernières conversations</p>
                <p className="text-xs text-emerald-800 mt-0.5">
                  Bascule rapide pour ne voir que les 3 dernières conversations. Les modérateurs peuvent désormais cliquer sur « Reprendre » pour suspendre Liluvine pendant 2 h.
                </p>
                <Link to="/portal/liluvine" className="text-xs text-emerald-700 underline mt-1 inline-block" data-testid="new-module-liluvine-link">Aller à Liluvine PRO →</Link>
              </li>
            </ul>
          </div>
        </Section>
      </Filterable>

      <Filterable title="Webhooks Paie (n8n)" anchorId="s-webhooks-paie-n8n">
        <PayrollWebhooksSection />
      </Filterable>
      <Filterable title="Webhook Planning consultations (RDV patients)" anchorId="s-webhook-planning">
        <PlanningWebhookSection />
      </Filterable>
      <Filterable title="Liluvine Reactions & Ad Auto-Replies (fuzzy commands, templates FB)" anchorId="s-liluvine-reactions">
        <LiluvineReactionsSection />
      </Filterable>
      <Filterable title="Intégration Meta (Facebook / Messenger / Ads)" anchorId="s-integration-meta">
        <MetaConfigSection />
      </Filterable>

      {/* Iter43-fix20 — Widget météo (Open-Meteo, gratuit, sans clé) */}
      <Filterable title="🌤️ Widget Météo (Open-Meteo)" anchorId="s-weather-widget">
        <WeatherWidgetSection />
      </Filterable>

      <Filterable title="Coupons de réduction (Stripe Checkout)" anchorId="s-coupons-stripe">
        <CouponsSection />
      </Filterable>

      <Filterable title="Webhook Stripe (confirmation paiement)" anchorId="s-stripe-webhook">
        <StripeWebhookSection />
      </Filterable>

      {/* Iter43-fix24au (2026-02-26) — LinkedIn OAuth + Posts API */}
      <Filterable title="💼 LinkedIn — Publications & lecture (OAuth + Posts API)" anchorId="s-linkedin">
        <LinkedInSection />
      </Filterable>

      {/* Iter43-fix24ax (2026-02-26) — Twitter (X) + Facebook Page social integrations */}
      <Filterable title="✖️ X / Twitter — Posts API" anchorId="s-twitter">
        <TwitterSection />
      </Filterable>

      <Filterable title="📘 Facebook Page — Posts API" anchorId="s-facebook">
        <FacebookSection />
      </Filterable>

      {/* Iter38r-fix9u — AI Subscriptions reminder table */}
      <Filterable title="Abonnements IA — Rappels de renouvellement" anchorId="s-ai-subscriptions">
        <Section icon={Bell} title="Abonnements IA & SaaS surveillés">
          <AiSubscriptionsSection />
        </Section>
      </Filterable>

      <Filterable title="Liluvine PRO — Auto-réponse WhatsApp (sans n8n)" anchorId="s-liluvine-wa-autoreply">
        <LiluvineWaAutoreplySection />
      </Filterable>

      <Filterable title="Liluvine PRO — Bypass (emails autorisés malgré feature OFF)" anchorId="s-liluvine-bypass">
        <LiluvineBypassEmailsSection />
      </Filterable>

      <Filterable title="Liluvine PRO — ACL modules métier (RAG WhatsApp)" anchorId="s-liluvine-module-acl">
        <LiluvineModuleAclSection />
      </Filterable>

      <Filterable title="WhatsApp — Filtre no-toast (numéros silencieux)" anchorId="s-wa-silent-phones">
        <WaSilentPhonesSection />
      </Filterable>

      <Filterable title="🛡️ WhatsApp — Silent Drops (surveillance rejets Meta 2xx sans message_id)" anchorId="s-wa-silent-drops">
        <WaSilentDropsSection />
      </Filterable>

      <Filterable title="🔔 WhatsApp — Son de notification (message entrant)" anchorId="s-wa-notification-sound">
        <WaNotificationSoundSection />
      </Filterable>

      <Filterable title="🎨 S057 — Habillage complet (Sidebar / Login / Blocs publics)" anchorId="s-s057-theming">
        <S057ThemingSection />
      </Filterable>

      <Filterable title="💊 S058 — Module VIDAL France (médicaments, RCP, alertes prescription)" anchorId="s-s058-vidal">
        <S058VidalSection />
      </Filterable>

      {/* Iter43-fix24ac (2026-06-16) — VIDAL Actions configurables */}
      <Filterable title="⚙️ S058b — VIDAL : Actions configurables (boutons portail + commandes WhatsApp)" anchorId="s-s058b-vidal-actions">
        <VidalActionsSection />
      </Filterable>

      {/* Iter43-fix24ai (2026-06-17) — Template configurable de la réponse `!garde` */}
      <Filterable title="🏥 S058c — WhatsApp !garde : Template de réponse personnalisable" anchorId="s-s058c-garde-reply">
        <GardeReplyTemplateSection />
      </Filterable>

      {/* Iter43-fix24ak (2026-06-17) — Personnalisation de la page publique /garde */}
      <Filterable title="🌐 S058d — Page publique /garde : Bandeaux + image" anchorId="s-s058d-garde-public">
        <GardePublicPageSection />
      </Filterable>

      {/* Iter43-fix24ap (2026-06-17) — Monitoring des intégrations (Google Cal + Meta) */}
      <Filterable title="🩺 S058e — Monitoring intégrations (Google Cal + Meta WA)" anchorId="s-s058e-integration-health">
        <IntegrationHealthSection />
      </Filterable>

      {/* Iter43-fix24aq (2026-06-17) — Images jointes aux réponses WhatsApp !commands */}
      <Filterable title="🖼 S058f — Images jointes aux commandes WhatsApp (!garde, !produits, …)" anchorId="s-s058f-wa-cmd-images">
        <WaCommandImagesSection />
      </Filterable>

      <Filterable title="📊 S059 — Synthèse Liluvine + API Officines + Image sidebar" anchorId="s-s059-synthese-officines">
        <S059SyntheseOfficinesSection />
      </Filterable>

      <Filterable title="📲 Templates OTP (WhatsApp) — Login général + Officines" anchorId="s-templates-otp">
        <TemplatesOtpSection />
      </Filterable>

      <Filterable title="🚨 Webhook Incidents entrant + Pays par défaut AMM" anchorId="s-incidents-webhook">
        <IncidentsAndCountrySection />
      </Filterable>

      <Filterable title="Liluvine PRO — Prompt système (personnalisation)" anchorId="s-liluvine-system-prompt">
        <LiluvineSystemPromptSection />
      </Filterable>

      <Filterable title="Liluvine PRO — Personnalisation visuelle (Branding)" anchorId="s-liluvine-branding">
        <LiluvineBrandingSection />
      </Filterable>

      <Filterable title="Liluvine PRO — Base de connaissance (KB)" anchorId="s-liluvine-kb">
        <LiluvineKnowledgeBaseSection />
      </Filterable>

      {/* Iter38r-fix9k — OCR cost controls for the Liluvine KB */}
      <Filterable title="Liluvine PRO — Coût OCR (Claude Vision)" anchorId="s-liluvine-ocr-cost">
        <Section icon={Brain} title="OCR Claude Vision — Coût & plafond mensuel">
          <p className="text-xs text-slate-500 mb-3">
            Suivi du coût de l'OCR Claude Vision (images et PDF rasterisés). Le compteur
            <code className="mx-1 rounded bg-slate-100 px-1">ai_usage</code> stocke chaque page traitée
            pour la facturation. <strong>0 dans un champ = désactivé</strong>.
          </p>
          <div className="grid sm:grid-cols-3 gap-3">
            <Input
              label="Coût par page OCR (XOF)"
              type="number"
              value={s.kb_ocr_xof_per_page ?? ""}
              onChange={(v) => upd("kb_ocr_xof_per_page", parseInt(v) || 0)}
              placeholder="50"
              testid="kb-ocr-xof-per-page"
            />
            <Input
              label="Plafond mensuel (XOF, 0 = illimité)"
              type="number"
              value={s.kb_ocr_xof_monthly_cap ?? ""}
              onChange={(v) => upd("kb_ocr_xof_monthly_cap", parseInt(v) || 0)}
              placeholder="10000"
              testid="kb-ocr-xof-cap"
            />
            <Input
              label="Pages max par PDF (sécurité)"
              type="number"
              value={s.kb_ocr_pdf_max_pages ?? ""}
              onChange={(v) => upd("kb_ocr_pdf_max_pages", parseInt(v) || 0)}
              placeholder="30"
              testid="kb-ocr-pdf-max-pages"
            />
          </div>
          <p className="text-[11px] text-slate-500 mt-2">
            ⚠️ Lorsque le plafond mensuel est atteint, les uploads OCR retournent 429 jusqu'au mois suivant.
            Consultez la consommation via <code className="rounded bg-slate-100 px-1">GET /admin/liluvine-pro/kb/ocr-usage</code>.
          </p>
        </Section>
      </Filterable>

      {/* Iter43-fix (2026-03) — Taux horaire global d'intervention */}
      <Filterable title="🛠️ Interventions — Taux horaire par défaut (XOF)" anchorId="s-intervention-rate">
        <Section icon={ClipboardList} title="Coût horaire d'intervention">
          <p className="text-xs text-slate-500 mb-3">
            Taux horaire utilisé pour calculer le coût total d'une intervention (durée × taux)
            dans le PDF d'historique. Chaque tenant peut surcharger ce taux dans sa fiche.
            Si aucun taux n'est défini, la valeur par défaut est <strong>15&nbsp;000 XOF/h</strong>.
          </p>
          <div className="grid sm:grid-cols-2 gap-3">
            <Input
              label="Taux horaire global (XOF/h)"
              type="number"
              value={s.default_intervention_hourly_rate_xof ?? ""}
              onChange={(v) => upd("default_intervention_hourly_rate_xof", parseInt(v) || 0)}
              placeholder="15000"
              testid="intervention-default-hourly-rate"
            />
          </div>
        </Section>
      </Filterable>



      {/* Iter43-fix (2026-03) — Mapping sévérités logiciel → plateforme */}
      <Filterable title="🎯 Registre des Erreurs — Mapping sévérités logiciel" anchorId="s-error-severity-mapping">
        <ErrorSeverityMappingSection settings={s} onChange={upd} />
      </Filterable>



      {/* Iter38r-fix9k — Notes / Tâches : mode strict checklist */}
      <Filterable title="Notes & Tâches — Mode strict (liste à cocher uniquement)" anchorId="s-notes-mode">
        <Section icon={ClipboardList} title="Mode d'édition des tâches">
          <label className="flex items-start gap-3 rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3 cursor-pointer hover:bg-slate-100" data-testid="notes-strict-tasks-toggle-wrapper">
            <input
              type="checkbox"
              checked={!!s.notes_strict_tasks_only}
              onChange={(e) => upd("notes_strict_tasks_only", e.target.checked)}
              className="mt-0.5 h-4 w-4"
              data-testid="notes-strict-tasks-toggle"
            />
            <span className="text-sm">
              <strong>Mode strict</strong> — Sur la page <em>Tâches</em>, n'autoriser que la <strong>liste à cocher</strong> (style Google Keep). Le rédacteur HTML est masqué.<br/>
              <span className="text-xs text-slate-500">Lorsque désactivé (mode mixte par défaut), l'utilisateur peut combiner liste à cocher + texte libre.</span>
            </span>
          </label>
        </Section>
      </Filterable>

      {/* Iter38r-fix9l — Bonus pack: WA digest + Liluvine weekly + GDPR */}
      <Filterable title="Bonus — WhatsApp Tasks · Digest Liluvine · GDPR auto" anchorId="s-bonus-pack">
        <Section icon={Sparkles} title="WhatsApp Tasks · Digest Liluvine · Anonymisation RGPD">
          <p className="text-xs text-slate-500 mb-3">
            Pack bonus : envoi quotidien des tâches par WhatsApp avec accusé de réception
            (réponse `OK 1,3`), digest hebdo Liluvine PRO par email (Lundi 8h), et
            anonymisation automatique des données anciennes (RGPD).
          </p>
          <div className="space-y-2">
            <label className="flex items-start gap-3 rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3 cursor-pointer hover:bg-slate-100">
              <input type="checkbox" checked={!!s.wa_tasks_digest_enabled} onChange={(e) => upd("wa_tasks_digest_enabled", e.target.checked)} className="mt-0.5 h-4 w-4" data-testid="wa-tasks-digest-toggle" />
              <span className="text-sm"><strong>WhatsApp Tasks — Digest quotidien</strong><br/><span className="text-xs text-slate-500">Chaque utilisateur opt-in reçoit ses tâches non-faites par WA à l'heure de son choix. Réponse `OK 1,3` ou `FAIT 2 5` pour cocher.</span></span>
            </label>
            <label className="flex items-start gap-3 rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3 cursor-pointer hover:bg-slate-100">
              <input type="checkbox" checked={!!s.liluvine_weekly_digest_enabled} onChange={(e) => upd("liluvine_weekly_digest_enabled", e.target.checked)} className="mt-0.5 h-4 w-4" data-testid="liluvine-weekly-digest-toggle" />
              <span className="text-sm"><strong>Digest hebdo Liluvine PRO (Lundi 8h, email)</strong><br/><span className="text-xs text-slate-500">Top 5 contacts WhatsApp, ROI temps gagné, sessions reprises, CTA campagne ciblée.</span></span>
            </label>
            <label className="flex items-start gap-3 rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3 cursor-pointer hover:bg-slate-100">
              <input type="checkbox" checked={!!s.gdpr_auto_anonymize_enabled} onChange={(e) => upd("gdpr_auto_anonymize_enabled", e.target.checked)} className="mt-0.5 h-4 w-4" data-testid="gdpr-auto-anonymize-toggle" />
              <span className="text-sm"><strong>RGPD — Anonymisation automatique quotidienne</strong><br/><span className="text-xs text-slate-500">Daily 03:30. Supprime contacts inactifs (24m), anonymise WA/SMS (12m), purge logs (90j) — délais configurables ci-dessous.</span></span>
            </label>
          </div>
          <div className="grid sm:grid-cols-3 gap-3 mt-3">
            <Input label="Délai contacts inactifs (mois)" type="number" value={s.gdpr_contact_inactive_months ?? ""} onChange={(v) => upd("gdpr_contact_inactive_months", parseInt(v) || 24)} placeholder="24" testid="gdpr-contact-months" />
            <Input label="Rétention messages (mois)" type="number" value={s.gdpr_msg_retention_months ?? ""} onChange={(v) => upd("gdpr_msg_retention_months", parseInt(v) || 12)} placeholder="12" testid="gdpr-msg-months" />
            <Input label="Rétention logs (jours)" type="number" value={s.gdpr_log_retention_days ?? ""} onChange={(v) => upd("gdpr_log_retention_days", parseInt(v) || 90)} placeholder="90" testid="gdpr-log-days" />
          </div>
          <p className="text-[11px] text-slate-500 mt-2">
            ⚙️ Les utilisateurs activent le digest WA depuis leur <strong>profil</strong> (heure configurable).
            Lancement manuel : <code className="rounded bg-slate-100 px-1">POST /admin/wa-tasks-digest/run-now</code>,
            <code className="rounded bg-slate-100 px-1">POST /admin/liluvine-weekly-digest/run-now</code>,
            <code className="rounded bg-slate-100 px-1">POST /admin/gdpr/anonymize-now</code>.
          </p>
        </Section>
      </Filterable>

      {/* Iter38c — Cashier expense justification deadline */}
      <Section icon={CreditCard} title="Caisse — Délai de justification des dépenses">
        <p className="text-xs text-slate-500 mb-3">
          Délai maximum en heures pour qu'un employé puisse justifier une dépense
          de caisse ou par chèque qu'il a saisie. Passé ce délai, la justification
          est refusée (sauf forçage par l'administrateur) et le montant est déduit
          automatiquement de la prochaine fiche de paie. <strong>0 = pas de limite.</strong>
        </p>
        <div className="flex items-center gap-2">
          <input
            type="number"
            min={0}
            value={s.expense_justification_deadline_hours ?? 72}
            onChange={(e) => upd("expense_justification_deadline_hours", parseInt(e.target.value || 0, 10))}
            data-testid="expense-deadline-input"
            className="w-32 rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
          <span className="text-sm text-slate-600">heures (défaut: 72h)</span>
        </div>
      </Section>

      <SupportLoadSection s={s} upd={upd} />
      <AlexaVoiceMonkeySection s={s} upd={upd} />
      <NoteServiceHistorySection s={s} upd={upd} />
      <ProfileRequestsSection />
      <DbSnapshotsSection s={s} upd={upd} reloadSettings={load} />
      <Filterable title="Stockage de fichiers (Object Storage)" anchorId="s-file-storage" category="diagnostics">
        <FileStorageSection />
      </Filterable>
      <Filterable title="Coffre-fort des secrets (Secrets Vault)" anchorId="s-secrets-vault" category="auth">
        <SecretsVaultSection />
      </Filterable>
      <Filterable title="Roadmap & Suivi des fonctionnalités" anchorId="s-roadmap-tracker" category="diagnostics">
        <RoadmapTrackerSection />
      </Filterable>
      {/* Iter38r-fix9z10 — Suggestion S009 — Auto-logout on inactivity */}
      <Section icon={Clock} title="Sécurité — Déconnexion automatique par inactivité">
        <p className="text-xs text-slate-500">
          Force la déconnexion d'un utilisateur après <strong>N minutes</strong> sans activité (souris, clavier, scroll, touch).
          Une fenêtre d'avertissement apparaît <strong>30 secondes avant</strong> avec un bouton « Rester connecté ».
          Empêche les sessions oubliées en fin de journée. <strong>Mettre 0 pour désactiver.</strong>
        </p>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {[0, 5, 10, 15, 30, 60].map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => upd("auto_logout_minutes", m)}
              className={`px-3 py-1.5 rounded-lg ring-1 transition ${
                Number(s.auto_logout_minutes ?? 0) === m
                  ? "bg-rose-600 text-white ring-rose-700 shadow-sm"
                  : "bg-white text-slate-700 ring-slate-300 hover:ring-rose-400"
              }`}
              data-testid={`auto-logout-preset-${m}`}
            >
              {m === 0 ? "Désactivé" : `${m} min`}
            </button>
          ))}
          <div className="inline-flex items-center gap-2 ml-2">
            <span className="text-slate-500">Personnalisé :</span>
            <input
              type="number" min="0" max="120"
              value={s.auto_logout_minutes ?? 0}
              onChange={(e) => upd("auto_logout_minutes", parseInt(e.target.value, 10) || 0)}
              className="w-20 text-xs rounded ring-1 ring-slate-300 px-2 py-1 bg-white font-mono"
              data-testid="auto-logout-custom"
            />
            <span className="text-slate-500">min</span>
          </div>
        </div>
        <p className="text-[10px] text-slate-500 italic">
          S'applique à TOUS les utilisateurs (admin, superviseur, client, équipe). Le paramètre est rechargé à la prochaine connexion.
          Référence : <code>/app/memory/SUGGESTIONS.md → S009</code>.
        </p>
      </Section>

      {/* Iter40-route-loader (S051) — Toggle the global circular page-loader */}
      <Section icon={Clock} title="Affichage — Jauge de transition entre pages">
        <p className="text-xs text-slate-500">
          Le <strong>GlobalRouteLoader</strong> est une mini barre circulaire bleu/violet qui apparaît brièvement
          (au centre de l'écran) lors de chaque changement de page et de chaque requête réseau.
          Elle rassure l'utilisateur sur la réactivité du serveur, mais peut être perçue comme intrusive
          par les utilisateurs habitués à la plateforme.
        </p>
        <label className="inline-flex items-center gap-2 text-sm cursor-pointer">
          <input
            type="checkbox"
            checked={s.global_route_loader_enabled !== false}
            onChange={(e) => {
              upd("global_route_loader_enabled", e.target.checked);
              // Iter40-route-loader — Notify the loader so it picks up the
              // new flag without requiring a full page reload.
              try { window.dispatchEvent(new CustomEvent("ui-flags-updated")); } catch { /* ignore */ }
            }}
            data-testid="global-route-loader-enabled"
          />
          <span>
            Afficher la jauge de transition entre pages
            <span className="ml-1 text-[10px] text-slate-500">(décocher = navigation silencieuse, sans indicateur visuel)</span>
          </span>
        </label>
        <p className="text-[10px] text-slate-500 italic">
          Référence : <code>/app/memory/SUGGESTIONS.md → S051</code>. Le réglage est lu à chaque rafraîchissement de page via <code>GET /api/public/ui-flags</code> (endpoint anonyme — aucune donnée sensible).
        </p>
      </Section>

      {/* 2026-02 fork iter108 — S164 (Emmy) — Browser Push Notifications */}
      <Section icon={Bell} title="Notifications navigateur — Alerte temps réel">
        <p className="text-xs text-slate-500">
          Active les notifications système du navigateur (Windows / macOS / Android) et le clignotement
          du titre de l'onglet dès qu'un nouveau ticket, RDV, message WhatsApp ou paiement arrive
          <strong> pendant que l'onglet est en arrière-plan</strong>. L'utilisateur doit accepter la
          permission au premier chargement (invitation automatique 5s après connexion).
          Chaque utilisateur peut aussi désactiver ces alertes depuis son profil via l'option
          « Silencer les notifications navigateur » stockée en local (localStorage).
        </p>
        <label className="inline-flex items-center gap-2 text-sm cursor-pointer">
          <input
            type="checkbox"
            checked={s.browser_notifications_enabled !== false}
            onChange={(e) => {
              upd("browser_notifications_enabled", e.target.checked);
              try { window.dispatchEvent(new CustomEvent("ui-flags-updated")); } catch { /* ignore */ }
            }}
            data-testid="browser-notifications-enabled"
          />
          <span>
            Activer les notifications navigateur pour tous les utilisateurs du portail
            <span className="ml-1 text-[10px] text-slate-500">(décocher = plus aucun toast système ni clignotement du titre)</span>
          </span>
        </label>
        <p className="text-[10px] text-slate-500 italic">
          Référence : <code>/app/memory/SUGGESTIONS.md → S164 (Emmy)</code>. Infrastructure Notification API native — aucune
          dépendance externe (VAPID, Service Worker, Firebase). Fallback automatique : le titre de l'onglet
          clignote même si l'utilisateur refuse la permission.
        </p>
      </Section>

      {/* Iter40-ui-flags — Public branding (exposed via /api/public/ui-flags) */}
      <Section icon={Sparkles} title="Identité publique — marque, logo, couleur">
        <p className="text-xs text-slate-500">
          Personnalisez les éléments visuels affichés sur le site public (titre de l'onglet, logo, couleur primaire,
          accroche du hero). Idéal pour les déploiements <em>white-label</em> ou pour ajuster le branding sans toucher au code.
          Les valeurs vides utilisent les défauts SAWALI. <strong>Aperçu en direct dans votre navigateur</strong> — cliquez sur <strong>« Enregistrer »</strong> en bas de la page pour persister et propager à tous les visiteurs.
        </p>
        <div className="grid sm:grid-cols-2 gap-3">
          <div>
            <label className="text-[11px] font-semibold text-slate-600 block mb-1">Nom de la marque</label>
            <input
              type="text"
              value={s.public_brand_name || ""}
              onChange={(e) => {
                upd("public_brand_name", e.target.value);
                // Iter40-ui-flags — Live preview: apply locally without
                // waiting for a DB round-trip. Persistence happens on "Save".
                applyBrandingLocal({ public_brand_name: e.target.value });
              }}
              placeholder="SAWALI Smart Systems"
              className="w-full px-3 py-2 rounded-lg ring-1 ring-slate-300 text-sm"
              data-testid="brand-name"
              maxLength={120}
            />
            <p className="text-[10px] text-slate-500 italic mt-1">Utilisé pour <code>document.title</code> (onglet du navigateur).</p>
          </div>
          <div>
            <label className="text-[11px] font-semibold text-slate-600 block mb-1">Couleur primaire (fond)</label>
            <div className="flex items-center gap-2">
              <input
                type="color"
                value={s.public_brand_color || "#1E90FF"}
                onChange={(e) => {
                  upd("public_brand_color", e.target.value);
                  applyBrandingLocal({ public_brand_color: e.target.value });
                }}
                className="h-9 w-12 rounded ring-1 ring-slate-300 cursor-pointer"
                data-testid="brand-color-picker"
              />
              <input
                type="text"
                value={s.public_brand_color || ""}
                onChange={(e) => {
                  upd("public_brand_color", e.target.value);
                  if (/^#[0-9A-Fa-f]{6}$/.test(e.target.value)) {
                    applyBrandingLocal({ public_brand_color: e.target.value });
                  }
                }}
                placeholder="#1E90FF"
                pattern="^#[0-9A-Fa-f]{6}$"
                className="flex-1 px-3 py-2 rounded-lg ring-1 ring-slate-300 text-sm font-mono"
                data-testid="brand-color-hex"
                maxLength={9}
              />
            </div>
            <p className="text-[10px] text-slate-500 italic mt-1">Exposée comme <code>var(--brand-primary)</code> · sert de couleur de fond pour les boutons CTA et accents.</p>
          </div>
          {/* Iter40-ui-flags-text — Second color picker for text on brand backgrounds */}
          <div>
            <label className="text-[11px] font-semibold text-slate-600 block mb-1">Couleur du texte (sur fond brand)</label>
            <div className="flex items-center gap-2">
              <input
                type="color"
                value={s.public_brand_text_color || "#FFFFFF"}
                onChange={(e) => {
                  upd("public_brand_text_color", e.target.value);
                  applyBrandingLocal({ public_brand_text_color: e.target.value });
                }}
                className="h-9 w-12 rounded ring-1 ring-slate-300 cursor-pointer"
                data-testid="brand-text-color-picker"
              />
              <input
                type="text"
                value={s.public_brand_text_color || ""}
                onChange={(e) => {
                  upd("public_brand_text_color", e.target.value);
                  if (/^#[0-9A-Fa-f]{6}$/.test(e.target.value)) {
                    applyBrandingLocal({ public_brand_text_color: e.target.value });
                  }
                }}
                placeholder="#FFFFFF"
                pattern="^#[0-9A-Fa-f]{6}$"
                className="flex-1 px-3 py-2 rounded-lg ring-1 ring-slate-300 text-sm font-mono"
                data-testid="brand-text-color-hex"
                maxLength={9}
              />
            </div>
            <p className="text-[10px] text-slate-500 italic mt-1">Exposée comme <code>var(--brand-text)</code> · texte des boutons CTA et badges sur fond brand. Défaut : blanc.</p>
            {/* Live preview tile to verify contrast */}
            <div className="mt-2 inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold"
                 style={{
                   backgroundColor: s.public_brand_color || "#1E90FF",
                   color: s.public_brand_text_color || "#FFFFFF",
                 }}
                 data-testid="brand-contrast-preview">
              Aperçu — Texte sur fond brand
            </div>
          </div>
          <div className="sm:col-span-2">
            <label className="text-[11px] font-semibold text-slate-600 block mb-1">URL du logo public</label>
            <div className="flex gap-2">
              <input
                type="url"
                value={s.public_logo_url || ""}
                onChange={(e) => {
                  upd("public_logo_url", e.target.value);
                  try { window.dispatchEvent(new CustomEvent("ui-flags-updated")); } catch { /* ignore */ }
                }}
                placeholder="https://exemple.com/logo.svg ou /api/files/<id>"
                className="flex-1 px-3 py-2 rounded-lg ring-1 ring-slate-300 text-sm"
                data-testid="brand-logo-url"
              />
              {/* Iter40-ui-flags — Direct file upload (drag-replacement of /api/admin/upload) */}
              <label
                className="inline-flex items-center gap-1.5 cursor-pointer text-xs font-semibold bg-slate-100 hover:bg-slate-200 text-slate-700 px-3 py-2 rounded-lg ring-1 ring-slate-300 whitespace-nowrap"
                data-testid="brand-logo-upload-label"
                title="Téléverser une image (PNG/SVG/JPG) et remplir automatiquement l'URL"
              >
                <Upload className="h-3.5 w-3.5" />
                Téléverser
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/svg+xml,image/webp"
                  className="hidden"
                  data-testid="brand-logo-upload-input"
                  onChange={async (e) => {
                    const f = e.target.files?.[0];
                    if (!f) return;
                    const fd = new FormData();
                    fd.append("file", f);
                    try {
                      const r = await apiClient.post("/admin/upload", fd, {
                        headers: { "Content-Type": "multipart/form-data" },
                      });
                      const url = r.data?.url;
                      if (url) {
                        upd("public_logo_url", url);
                        try { window.dispatchEvent(new CustomEvent("ui-flags-updated")); } catch { /* ignore */ }
                        toast.success("Logo téléversé — pensez à enregistrer les paramètres.");
                      } else {
                        toast.error("Réponse d'upload invalide");
                      }
                    } catch (err) {
                      toast.error(err?.response?.data?.detail || "Échec du téléversement");
                    } finally {
                      e.target.value = ""; // allow re-upload of same file
                    }
                  }}
                />
              </label>
            </div>
            {s.public_logo_url && (
              <div className="mt-2 rounded-lg ring-1 ring-slate-200 bg-slate-50 p-2 inline-block">
                <img src={s.public_logo_url} alt="Aperçu du logo" className="h-12 w-auto object-contain" data-testid="brand-logo-preview" />
              </div>
            )}
            <p className="text-[10px] text-slate-500 italic mt-1">
              Téléversez un fichier image (PNG/JPG/SVG/WEBP) ou collez une URL externe. Le fichier sera servi via <code>/api/files/&lt;id&gt;</code>.
            </p>
          </div>
          <div className="sm:col-span-2">
            <label className="text-[11px] font-semibold text-slate-600 block mb-1">Accroche du hero (page d'accueil)</label>
            <input
              type="text"
              value={s.public_hero_tagline || ""}
              onChange={(e) => {
                upd("public_hero_tagline", e.target.value);
                try { window.dispatchEvent(new CustomEvent("ui-flags-updated")); } catch { /* ignore */ }
              }}
              placeholder="Construisons ensemble votre transformation digitale"
              className="w-full px-3 py-2 rounded-lg ring-1 ring-slate-300 text-sm"
              data-testid="brand-hero-tagline"
              maxLength={200}
            />
            <p className="text-[10px] text-slate-500 italic mt-1">
              Override optionnel — laisser vide pour utiliser l'accroche du contenu <code>home_hero</code> (admin/contents).
            </p>
          </div>
        </div>
      </Section>

      {/* Iter40-ui-flags-bg (S057) — Background theming for public + portal */}
      <Section icon={Sparkles} title="Habillage — fond de page (événementiel / charte client)">
        <p className="text-xs text-slate-500">
          Habillez le site avec une <strong>couleur unie</strong> ou une <strong>image de fond</strong> (centrée, répétée ou plein écran).
          Utile pour les événements (Noël, anniversaire SAWALI, lancement de produit) ou pour adopter la charte graphique d'un client.
          Aperçu en direct dans votre navigateur ; cliquez « Enregistrer » pour persister.
        </p>
        <div className="grid lg:grid-cols-2 gap-3">
          <BgEditor
            scope="public"
            label="Pages publiques (Accueil, Missions, Contact, …)"
            s={s}
            upd={upd}
          />
          <BgEditor
            scope="portal"
            label="Espace Loois (Portail + Admin)"
            s={s}
            upd={upd}
          />
        </div>
      </Section>

      {/* Iter40-modal — Global cap of public ad modals per visitor per day */}
      <Section icon={Clock} title="Régie publicitaire — Plafond de modales par visiteur / jour">
        <p className="text-xs text-slate-500">
          Limite le nombre <strong>maximum de modales publicitaires</strong> qu'un même visiteur peut voir
          sur les pages publiques sur une fenêtre glissante de 24 heures, toutes campagnes confondues.
          Évite la sur-sollicitation quand plusieurs campagnes <em>« à chaque chargement »</em> tournent en parallèle.
          <strong> Mettre 0 pour désactiver le plafond.</strong>
        </p>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {[0, 1, 2, 3, 5].map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => upd("modal_global_cap_per_day", m)}
              className={`px-3 py-1.5 rounded-lg ring-1 transition ${
                Number(s.modal_global_cap_per_day ?? 2) === m
                  ? "bg-fuchsia-600 text-white ring-fuchsia-700 shadow-sm"
                  : "bg-white text-slate-700 ring-slate-300 hover:ring-fuchsia-400"
              }`}
              data-testid={`modal-cap-preset-${m}`}
            >
              {m === 0 ? "Illimité" : `${m} / jour`}
            </button>
          ))}
          <div className="inline-flex items-center gap-2 ml-2">
            <span className="text-slate-500">Personnalisé :</span>
            <input
              type="number" min="0" max="20"
              value={s.modal_global_cap_per_day ?? 2}
              onChange={(e) => upd("modal_global_cap_per_day", parseInt(e.target.value, 10) || 0)}
              className="w-20 text-xs rounded ring-1 ring-slate-300 px-2 py-1 bg-white font-mono"
              data-testid="modal-cap-custom"
            />
            <span className="text-slate-500">modales/jour</span>
          </div>
        </div>
        <p className="text-[10px] text-slate-500 italic">
          Le compteur est stocké côté navigateur (<code>localStorage</code>) — réinitialisé après 24h. Défaut : 2.
        </p>
      </Section>

      {/* 2026-02 (#3) — Default Liluvine takeover duration */}
      <Filterable title="Liluvine PRO — Durée par défaut de la reprise (minutes)" anchorId="s-liluvine-takeover-minutes">
        <Section icon={Bot} title="Liluvine — Reprise humaine">
          <p className="text-xs text-slate-500">
            Lorsqu'un modérateur clique « Reprendre » sur une conversation Liluvine,
            l'IA est mise en pause pour cette durée. <strong>30 min par défaut</strong>
            (vs l'ancienne valeur de 120 min jugée trop longue). Plage : 5 à 10 080 min (7 jours).
          </p>
          <div className="flex items-center gap-2 mt-2">
            <input
              type="number"
              min={5}
              max={10080}
              value={s.liluvine_takeover_default_minutes ?? 30}
              onChange={(e) => upd("liluvine_takeover_default_minutes", parseInt(e.target.value || "30", 10))}
              className="w-32 rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
              data-testid="liluvine-takeover-minutes-input"
            />
            <span className="text-xs text-slate-500">minutes</span>
          </div>
        </Section>
      </Filterable>

      {/* S025 — Approbation de téléchargement par WhatsApp */}
      <Filterable title="Sécurité — Approbation WhatsApp pour téléchargements (S025)" anchorId="s-download-approval">
        <Section icon={ShieldCheck} title="Approbation WhatsApp des téléchargements">
          <p className="text-xs text-slate-500">
            Lorsqu'activé, un utilisateur non-admin qui demande à télécharger un PDF/document
            interne déclenche l'envoi d'un message WhatsApp à l'approbateur configuré
            (template Meta avec 2 boutons « Autoriser » / « Refuser ») ou, à défaut de template,
            un texte simple avec 2 liens magiques.
            En attendant la réponse, l'utilisateur voit une jauge circulaire avec le message
            personnalisable ci-dessous. La demande expire automatiquement après 24 h.
          </p>
          <label className="inline-flex items-center gap-2 text-sm cursor-pointer mt-2">
            <input
              type="checkbox"
              checked={!!s.download_approval_enabled}
              onChange={(e) => upd("download_approval_enabled", e.target.checked)}
              data-testid="dl-approval-enabled"
            />
            <span>Activer le workflow d'approbation par WhatsApp</span>
          </label>
          <label className="inline-flex items-center gap-2 text-sm cursor-pointer mt-1">
            <input
              type="checkbox"
              checked={s.download_gauge_enabled !== false}
              onChange={(e) => upd("download_gauge_enabled", e.target.checked)}
              data-testid="dl-gauge-enabled"
            />
            <span>
              Afficher la jauge d'attente plein écran
              <span className="ml-1 text-[10px] text-slate-500">(décocher pour un simple toast discret)</span>
            </span>
          </label>
          <div className="grid sm:grid-cols-2 gap-3 mt-2">
            <div>
              <label className="text-[11px] font-semibold text-slate-600">Numéro WhatsApp de l'approbateur (E.164)</label>
              <input
                type="text"
                value={s.download_approval_whatsapp || ""}
                onChange={(e) => upd("download_approval_whatsapp", e.target.value)}
                placeholder="225XXXXXXXXXX"
                className="w-full mt-0.5 px-3 py-2 rounded-lg ring-1 ring-slate-300 text-sm"
                data-testid="dl-approval-whatsapp"
              />
            </div>
            <div>
              <label className="text-[11px] font-semibold text-slate-600">Nom du template Meta (optionnel)</label>
              <input
                type="text"
                value={s.download_approval_template_name || ""}
                onChange={(e) => upd("download_approval_template_name", e.target.value)}
                placeholder="ex: download_approval_buttons"
                className="w-full mt-0.5 px-3 py-2 rounded-lg ring-1 ring-slate-300 text-sm"
                data-testid="dl-approval-template-name"
              />
              <p className="text-[10px] text-slate-400 mt-0.5">Doit déclarer 2 boutons QUICK_REPLY (vide ⇒ fallback texte)</p>
            </div>
          </div>
          <div className="mt-2">
            <label className="text-[11px] font-semibold text-slate-600">Langue du template (par défaut fr)</label>
            <input
              type="text"
              value={s.download_approval_template_lang || ""}
              onChange={(e) => upd("download_approval_template_lang", e.target.value)}
              placeholder="fr"
              className="w-32 mt-0.5 px-3 py-2 rounded-lg ring-1 ring-slate-300 text-sm"
              data-testid="dl-approval-template-lang"
            />
          </div>
          <div className="mt-2">
            <label className="text-[11px] font-semibold text-slate-600">Message affiché dans la jauge d'attente</label>
            <input
              type="text"
              value={s.download_pending_message || ""}
              onChange={(e) => upd("download_pending_message", e.target.value)}
              placeholder="En attente d'approbation pour le téléchargement..."
              className="w-full mt-0.5 px-3 py-2 rounded-lg ring-1 ring-slate-300 text-sm"
              data-testid="dl-pending-message"
            />
          </div>
          <div className="mt-2">
            <label className="text-[11px] font-semibold text-slate-600">Corps du message texte (fallback hors template) — variables : {`{requester}`}, {`{label}`}, {`{approve}`}, {`{deny}`}</label>
            <textarea
              value={s.download_approval_text_body || ""}
              onChange={(e) => upd("download_approval_text_body", e.target.value)}
              rows={5}
              className="w-full mt-0.5 px-3 py-2 rounded-lg ring-1 ring-slate-300 text-xs font-mono"
              data-testid="dl-approval-text-body"
              placeholder="Demande reçue : {requester} souhaite télécharger {label}.\nAUTORISER : {approve}\nREFUSER : {deny}"
            />
          </div>
        </Section>
      </Filterable>

      {/* S026 — Notification des signataires de PV */}
      <Filterable title="PV de réunions — Notification automatique des signataires (S026)" anchorId="s-meeting-signers-notify">
        <Section icon={Bell} title="Notification des signataires d'un PV">
          <p className="text-xs text-slate-500">
            À la création d'un PV avec des signataires obligatoires déclarés (ligne 1 du
            formulaire), les signataires reçoivent automatiquement une notification leur
            demandant de consulter et signer le document. Choisissez le canal :
          </p>
          <div className="grid sm:grid-cols-4 gap-2 mt-2">
            {[
              { v: "none", l: "Aucun (désactivé)" },
              { v: "email", l: "📧 Email seul" },
              { v: "wa", l: "💬 WhatsApp seul" },
              { v: "both", l: "📧 + 💬 Les deux" },
            ].map((opt) => (
              <button
                key={opt.v}
                onClick={() => upd("meeting_signers_notify_channel", opt.v)}
                className={`text-xs px-3 py-2 rounded-lg ring-1 transition ${
                  (s.meeting_signers_notify_channel || "none") === opt.v
                    ? "bg-fuchsia-600 text-white ring-fuchsia-700 font-semibold"
                    : "bg-white text-slate-700 ring-slate-300 hover:bg-slate-50"
                }`}
                data-testid={`signers-notify-${opt.v}`}
              >
                {opt.l}
              </button>
            ))}
          </div>
        </Section>
      </Filterable>

      {/* S032 — Seuils de consommation Universal Key Emergent */}
      <Filterable title="Universal Key Emergent — Seuils de consommation & alertes (S032)" anchorId="s-llm-budget-thresholds">
        <Section icon={Brain} title="Budget IA — Seuils d'alerte (avertissement + critique)">
          <p className="text-xs text-slate-500">
            Surveille la consommation mensuelle de la Universal Key Emergent (Liluvine PRO, auto-réponse WA, OCR KB, planificateur IA).
            Lorsque la consommation atteint le seuil d'<strong>avertissement</strong> (par défaut <strong>80 %</strong>) ou le seuil <strong>critique</strong> (par défaut <strong>95 %</strong>),
            un email et/ou un message WhatsApp est automatiquement envoyé à l'admin <em>(une fois par 23 h par niveau)</em>.
            Une bannière colorée apparaît également en haut du portail pour l'admin <code>admin@sawalismartsystems.com</code>.
          </p>
          <div className="grid sm:grid-cols-3 gap-3">
            <Input
              label="Seuil d'avertissement (% du budget mensuel)"
              type="number"
              min="50" max="99" step="1"
              value={s.llm_budget_warning_pct ?? 80}
              onChange={(v) => upd("llm_budget_warning_pct", v === "" ? null : parseInt(v, 10))}
              placeholder="80"
              testid="llm-budget-warning-pct"
            />
            <Input
              label="Seuil critique (% du budget mensuel)"
              type="number"
              min="60" max="99" step="1"
              value={s.llm_budget_critical_pct ?? 95}
              onChange={(v) => upd("llm_budget_critical_pct", v === "" ? null : parseInt(v, 10))}
              placeholder="95"
              testid="llm-budget-critical-pct"
            />
            <Input
              label="Budget mensuel max (USD)"
              type="number"
              min="0.1" step="0.1"
              value={s.llm_budget_max_usd ?? 3.0}
              onChange={(v) => upd("llm_budget_max_usd", v === "" ? null : parseFloat(v))}
              placeholder="3.00"
              testid="llm-budget-max-usd"
            />
          </div>
          <div className="grid sm:grid-cols-2 gap-3 mt-2">
            <Toggle
              label="📧 Envoyer un email d'alerte à admin@sawalismartsystems.com"
              value={s.llm_budget_notify_email !== false}
              onChange={(v) => upd("llm_budget_notify_email", v)}
              testid="toggle-llm-budget-notify-email"
            />
            <Toggle
              label="💬 Envoyer une alerte WhatsApp"
              value={s.llm_budget_notify_wa !== false}
              onChange={(v) => upd("llm_budget_notify_wa", v)}
              testid="toggle-llm-budget-notify-wa"
            />
          </div>
          <Input
            label="Numéro WhatsApp de l'admin pour les alertes (format E.164)"
            value={s.llm_budget_notify_wa_phone || ""}
            onChange={(v) => upd("llm_budget_notify_wa_phone", v)}
            placeholder="+225XXXXXXXXXX"
            testid="llm-budget-notify-wa-phone"
          />
          <p className="text-[11px] text-slate-500">
            ⚠️ L'envoi WhatsApp libre exige que ce numéro ait écrit au bot dans les dernières 24 h
            (fenêtre de service client Meta). Sinon, seul l'email sera reçu.
          </p>

          {/* S033 — Bouton test manuel + déclencheur WA par mot-clé */}
          <div className="mt-4 pt-4 border-t border-slate-200 space-y-3">
            <div>
              <p className="text-xs font-semibold text-slate-700 mb-1">🧪 Tester maintenant (S033)</p>
              <p className="text-[11px] text-slate-500 mb-2">
                Force un ping immédiat de la Universal Key et affiche le résumé (consommation, vitesse, projection).
              </p>
              <LlmBudgetTestButton />
            </div>
            <div className="grid sm:grid-cols-2 gap-3">
              <Toggle
                label="💬 Activer le cockpit WhatsApp (SOLDE / STATS / INCIDENTS / AIDE)"
                value={!!s.llm_budget_wa_query_enabled}
                onChange={(v) => upd("llm_budget_wa_query_enabled", v)}
                testid="toggle-llm-budget-wa-query"
              />
              <Input
                label="Mot-clé principal (compatibilité — défaut SOLDE)"
                value={s.llm_budget_wa_query_keyword || "SOLDE"}
                onChange={(v) => upd("llm_budget_wa_query_keyword", v)}
                placeholder="SOLDE"
                testid="llm-budget-wa-query-keyword"
              />
            </div>
            <div className="text-[11px] text-slate-600 bg-indigo-50/60 ring-1 ring-indigo-200 rounded-lg px-3 py-2 leading-relaxed" data-testid="cockpit-commands-help">
              <strong className="text-indigo-700">Commandes du cockpit (S034) :</strong>
              <ul className="mt-1 space-y-0.5 ml-3 list-disc">
                <li><code className="bg-white px-1 rounded">SOLDE</code> ou <code className="bg-white px-1 rounded">BUDGET</code> — consommation Universal Key</li>
                <li><code className="bg-white px-1 rounded">STATS</code> ou <code className="bg-white px-1 rounded">KPI</code> — WA / SMS / RDV / tickets / contacts (24h)</li>
                <li><code className="bg-white px-1 rounded">INCIDENTS</code> ou <code className="bg-white px-1 rounded">TICKETS</code> — top 5 tickets ouverts</li>
                <li><code className="bg-white px-1 rounded">AIDE</code>, <code className="bg-white px-1 rounded">HELP</code> ou <code className="bg-white px-1 rounded">MENU</code> — afficher le menu</li>
              </ul>
            </div>
            <p className="text-[11px] text-slate-500">
              Le numéro <em>autorisé</em> (celui des alertes ci-dessus) peut envoyer ces mots-clés au bot
              pour recevoir un résumé instantané. Les messages déclencheurs ne sont ni stockés ni transmis à Liluvine PRO.
            </p>
          </div>
        </Section>
      </Filterable>

      {/* S036 — Escalation Liluvine PRO vers admin via WhatsApp */}
      <Filterable title="Liluvine PRO — Demande d'aide WhatsApp à l'admin (S036)" anchorId="s-liluvine-escalation">
        <Section icon={Brain} title="Liluvine PRO appelle l'admin quand elle est bloquée">
          <p className="text-xs text-slate-500">
            Quand Liluvine PRO ne sait pas répondre à un contact (question complexe, demande sensible,
            frustration détectée…), elle peut envoyer automatiquement un message WhatsApp à l'admin
            avec le contexte de la conversation et la raison du blocage. Anti-spam intégré : maximum
            une escalade par contact toutes les <strong>{s.liluvine_escalation_cooldown_minutes || 30} min</strong>.
          </p>
          <div className="grid sm:grid-cols-1 gap-3">
            <Toggle
              label="🆘 Activer les demandes d'aide WhatsApp de Liluvine"
              value={!!s.liluvine_escalation_enabled}
              onChange={(v) => upd("liluvine_escalation_enabled", v)}
              testid="toggle-liluvine-escalation"
            />
          </div>
          <div className="grid sm:grid-cols-2 gap-3">
            <Input
              label="Numéro WhatsApp de l'admin (E.164)"
              value={s.liluvine_escalation_wa_phone || ""}
              onChange={(v) => upd("liluvine_escalation_wa_phone", v)}
              placeholder="+225XXXXXXXXXX (sinon utilise celui des alertes ci-dessus)"
              testid="liluvine-escalation-wa-phone"
            />
            <Input
              label="Délai anti-spam entre escalades (minutes)"
              type="number"
              min="1" max="1440" step="1"
              value={s.liluvine_escalation_cooldown_minutes ?? 30}
              onChange={(v) => upd("liluvine_escalation_cooldown_minutes", v === "" ? null : parseInt(v, 10))}
              placeholder="30"
              testid="liluvine-escalation-cooldown"
            />
          </div>
          <p className="text-[11px] text-slate-500">
            ⚠️ L'envoi WhatsApp libre exige que ce numéro ait écrit au bot dans les dernières 24 h
            (fenêtre de service client Meta). Si laissé vide, le numéro des alertes Universal Key est utilisé.
          </p>
          <div className="mt-2 pt-2 border-t border-slate-200">
            <p className="text-xs font-semibold text-slate-700 mb-2">🧪 Tester l'envoi maintenant</p>
            <LiluvineEscalationTestButton />
          </div>
        </Section>
      </Filterable>

      {/* S038 — RAG semantic knowledge base (Qdrant) */}
      <Filterable title="RAG — Base de connaissance vectorielle (Qdrant) (S038)" anchorId="s-rag-qdrant">
        <Section icon={Brain} title="Recherche sémantique pour Liluvine PRO (RAG)">
          <p className="text-xs text-slate-500">
            Connectez votre base Qdrant Cloud, créez des collections (FAQ, produits, procédures…)
            et injectez du contenu : <strong>texte brut</strong>, <strong>PDF</strong> (extraction
            automatique) ou <strong>URLs web</strong> (scraping). Liluvine PRO interrogera
            sémantiquement les collections que vous activez ci-dessous à chaque message client.
            Modèle d'embeddings : <code>paraphrase-multilingual-MiniLM-L12-v2</code> (384 dim,
            optimisé multilingue dont français, exécution locale sans coût Universal Key).
          </p>
          <Toggle
            label="🟢 Activer la recherche sémantique Qdrant pour Liluvine PRO"
            value={!!s.qdrant_enabled}
            onChange={(v) => upd("qdrant_enabled", v)}
            testid="toggle-qdrant-enabled"
          />
          <div className="space-y-1">
            <Toggle
              label="👁️ Enrichir automatiquement les images uploadées via Claude Vision (OCR + description)"
              value={s.qdrant_image_auto_describe !== false}
              onChange={(v) => upd("qdrant_image_auto_describe", v)}
              testid="toggle-qdrant-image-auto-describe"
            />
            <p className="text-[11px] text-slate-500 ml-7">
              Quand activé, chaque image envoyée dans une collection Qdrant est analysée par Claude Sonnet 4.6 Vision
              pour extraire son texte (OCR) et générer une description visuelle. Cela rend l'image retrouvable par
              Liluvine même sans légende manuelle. Désactivez pour économiser sur la Universal Key (~$0.001/image).
              Le toggle par-upload dans Qdrant &gt; Image reste prioritaire si vous souhaitez forcer ou couper au cas par cas.
            </p>
          </div>
          <QdrantRagSection />
        </Section>
      </Filterable>

      <OrphanDataSection />
      <ClientsConsistencySection />
      <ClientDataDiagnosticSection />
      <RevertRetagSection />
      <CashierTenantBackfillSection />
      <Section icon={MessageCircle} title="Briefing de bienvenue — Mode du compteur 'Non lus'">  <p className="text-xs text-slate-500">
          <strong>Bornée</strong> (recommandé) : ne compte que les messages WhatsApp/SMS reçus <em>depuis votre dernière visite</em> (ou les 7 derniers jours si jamais vu).
          C'est le réglage qui évite l'effet "compteur qui ne descend jamais".<br />
          <strong>Cumulative</strong> : compte <em>tous</em> les messages jamais lus depuis le début. Ne baisse que quand l'utilisateur ouvre la conversation du contact concerné (qui appelle <code>/messages/mark-read</code>).
        </p>
        <div className="grid sm:grid-cols-2 gap-3">
          <label className="inline-flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="radio" name="welcome_unread_mode" value="bounded"
              checked={(s.welcome_unread_mode || "bounded") === "bounded"}
              onChange={() => upd("welcome_unread_mode", "bounded")}
              data-testid="welcome-unread-mode-bounded"
            />
            <span><strong>Bornée</strong> — fenêtre last_seen / 7j</span>
          </label>
          <label className="inline-flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="radio" name="welcome_unread_mode" value="lifetime"
              checked={s.welcome_unread_mode === "lifetime"}
              onChange={() => upd("welcome_unread_mode", "lifetime")}
              data-testid="welcome-unread-mode-lifetime"
            />
            <span><strong>Cumulative</strong> — tous les non lus</span>
          </label>
        </div>
      </Section>
      <Section icon={Globe} title="Suivi des visiteurs (REST API externe)">
        <p className="text-xs text-slate-500">
          Chaque accès au site et consultation de page génère une requête contenant : <strong>date/heure, IP, pays, ville, page</strong>.
          Cette requête est transmise à votre service REST si l'option est activée.
        </p>
        <Toggle label="Activer le forwarding vers votre API REST externe" value={!!s.tracking_enabled} onChange={(v) => upd("tracking_enabled", v)} testid="toggle-tracking" />
        <Input label="URL de base de votre API" value={s.tracking_base_url || ""} onChange={(v) => upd("tracking_base_url", v)} placeholder="https://api.votre-service.com" testid="tracking-base-url" />
        <Input label="Point de terminaison (endpoint)" value={s.tracking_endpoint || ""} onChange={(v) => upd("tracking_endpoint", v)} placeholder="/events/visit" testid="tracking-endpoint" />
        <Input label="En-tête d'authentification (optionnel)" value={s.tracking_auth_header || ""} onChange={(v) => upd("tracking_auth_header", v)} placeholder="Bearer xxxxxxxx" testid="tracking-auth" />
        <p className="text-[11px] text-slate-500">
          Format JSON envoyé : <code className="text-sawali-blue">{`{ id, datetime, ip, country, city, region, page, referrer, user_agent, session_id }`}</code>
        </p>
      </Section>

      <Section icon={Video} title="Vidéo de la page d'accueil">
        <p className="text-xs text-slate-500">
          Ajoutez une vidéo (MP4) qui s'affichera dans une section dédiée sur la page d'accueil, juste après le hero.
          La vidéo est paramétrable (autoplay, boucle, son).
        </p>
        <Toggle label="Activer la section vidéo" value={!!s.hero_video_enabled} onChange={(v) => upd("hero_video_enabled", v)} testid="toggle-hero-video" />

        <div>
          <label className="block text-xs font-semibold mb-1">Fichier vidéo (MP4) *</label>
          <label className="inline-flex items-center gap-2 cursor-pointer rounded-lg border border-dashed border-slate-300 px-4 py-3 text-sm text-slate-600 hover:border-sawali-blue">
            <Upload className="h-4 w-4" /> {s.hero_video_url ? "Remplacer la vidéo" : "Choisir un fichier MP4"}
            <input
              type="file"
              hidden
              accept="video/mp4,video/webm,video/quicktime"
              onChange={async (e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                if (file.size > 80 * 1024 * 1024) {
                  toast.error("Fichier trop volumineux (max 80 Mo)");
                  return;
                }
                const fd = new FormData(); fd.append("file", file);
                try {
                  const r = await apiClient.post("/admin/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
                  upd("hero_video_url", r.data.url);
                  toast.success("Vidéo téléversée");
                } catch (err) { toast.error("Erreur upload vidéo"); }
              }}
              data-testid="hero-video-input"
            />
          </label>
          {s.hero_video_url && <p className="text-xs text-slate-500 mt-1 break-all">URL : {s.hero_video_url}</p>}
        </div>

        <Input label="Titre de la section" value={s.hero_video_title || ""} onChange={(v) => upd("hero_video_title", v)} testid="hero-video-title" />
        <div>
          <label className="block text-xs font-semibold mb-1">Description</label>
          <textarea rows={2} value={s.hero_video_description || ""} onChange={(e) => upd("hero_video_description", e.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="hero-video-description" />
        </div>

        <div className="grid sm:grid-cols-3 gap-3">
          <Toggle label="Autoplay" value={s.hero_video_autoplay !== false} onChange={(v) => upd("hero_video_autoplay", v)} testid="toggle-hero-autoplay" />
          <Toggle label="Boucle" value={s.hero_video_loop !== false} onChange={(v) => upd("hero_video_loop", v)} testid="toggle-hero-loop" />
          <Toggle label="Muet" value={s.hero_video_muted !== false} onChange={(v) => upd("hero_video_muted", v)} testid="toggle-hero-muted" />
        </div>

        <Input label="Image de couverture (URL, optionnel)" value={s.hero_video_poster_url || ""} onChange={(v) => upd("hero_video_poster_url", v)} placeholder="/api/files/xxx ou URL externe" />
      </Section>

      <Section icon={MessageCircle} title="Assistant virtuel (chatbot)">
        <p className="text-xs text-slate-500">
          Bouton flottant en bas à droite du site qui ouvre un chatbot externe (JotForm AI Agent ou compatible) pour
          permettre aux visiteurs et clients de contacter le support. Compatible avec n'importe quelle URL d'agent qui
          accepte un paramètre <code>parentURL</code>.
        </p>
        <Toggle label="Activer l'assistant" value={!!s.assistant_enabled} onChange={(v) => upd("assistant_enabled", v)} testid="toggle-assistant" />
        <Input
          label="URL de l'agent (popup)"
          value={s.assistant_url || ""}
          onChange={(v) => upd("assistant_url", v)}
          placeholder="https://agent.jotform.com/xxxxx?embedMode=popup"
          testid="assistant-url"
        />
        <Input
          label="Libellé du bouton"
          value={s.assistant_label || ""}
          onChange={(v) => upd("assistant_label", v)}
          placeholder="Liluvine — Support Technique"
          testid="assistant-label"
        />
        <div>
          <label className="block text-xs font-semibold mb-1">Couleur du bouton</label>
          <div className="flex items-center gap-2">
            <input
              type="color"
              value={s.assistant_color || "#0075E3"}
              onChange={(e) => upd("assistant_color", e.target.value)}
              className="h-10 w-12 rounded border border-slate-300 cursor-pointer"
              data-testid="assistant-color"
            />
            <input
              type="text"
              value={s.assistant_color || "#0075E3"}
              onChange={(e) => upd("assistant_color", e.target.value)}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono w-32"
              placeholder="#0075E3"
            />
          </div>
        </div>
      </Section>

      <Section icon={ClipboardList} title="Espace client : Rapports & Suivis">        <p className="text-xs text-slate-500">
          Contrôle l'affichage des cartes <strong>Rapports</strong> et <strong>Suivis</strong> sur le tableau de bord
          de l'espace client. Quand activées, les utilisateurs suivis peuvent saisir et conserver leurs notes avec
          mise en forme (gras, listes, couleurs, etc.).
        </p>
        <div className="grid sm:grid-cols-2 gap-3">
          <Toggle label="Afficher la carte Rapports" value={s.show_reports_button !== false} onChange={(v) => upd("show_reports_button", v)} testid="toggle-show-reports" />
          <Toggle label="Afficher la carte Suivis" value={s.show_suivis_button !== false} onChange={(v) => upd("show_suivis_button", v)} testid="toggle-show-suivis" />
        </div>
      </Section>

      <Section icon={Activity} title="Compteur de visites (page d'accueil)">
        <p className="text-xs text-slate-500">
          Affiche le nombre total de visites sur la page d'accueil publique. Le compteur est incrémenté
          automatiquement à chaque chargement de page. Vous pouvez le réinitialiser à zéro à tout moment
          (les visites historiques restent enregistrées en base pour les statistiques /admin/visits).
        </p>
        <Toggle
          label="Afficher le compteur sur la page d'accueil"
          value={s.visits_counter_enabled !== false}
          onChange={(v) => upd("visits_counter_enabled", v)}
          testid="toggle-visits-counter"
        />
        <div className="grid sm:grid-cols-2 gap-3 items-end">
          <Input
            label="Décalage manuel (offset)"
            type="number"
            value={s.visits_counter_offset ?? 0}
            onChange={(v) => upd("visits_counter_offset", parseInt(v || "0", 10))}
            placeholder="0"
            testid="visits-counter-offset"
          />
          <button
            type="button"
            onClick={async () => {
              if (!window.confirm("Réinitialiser le compteur affiché à 0 ?")) return;
              try {
                await apiClient.post("/admin/visits/reset");
                toast.success("Compteur remis à zéro");
                await load();
              } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
            }}
            className="inline-flex items-center justify-center gap-2 rounded-lg border border-rose-300 bg-rose-50 text-rose-700 px-4 py-2 text-sm hover:bg-rose-100"
            data-testid="reset-visits-btn"
          >
            <RotateCcw className="h-4 w-4" /> Réinitialiser à 0
          </button>
        </div>
        <p className="text-[11px] text-slate-500">
          Le compteur affiché = visites réelles + offset. Réinitialiser règle l'offset à <code>-(visites_actuelles)</code>.
        </p>
      </Section>

      <Section icon={AlertCircle} title="Bandeau d'incident (public + portail)">
        <p className="text-xs text-slate-500">
          Affiche un bandeau collant en haut de toutes les pages publiques ET du portail client lorsqu'un incident est en cours
          ou qu'une maintenance est planifiée. Le bandeau est dismissible côté visiteur jusqu'à la prochaine modification.
        </p>
        <Toggle label="Activer le bandeau" value={!!s.incident_banner_enabled} onChange={(v) => upd("incident_banner_enabled", v)} testid="toggle-incident-banner" />
        <div className="grid sm:grid-cols-3 gap-3">
          <div>
            <label className="block text-xs font-semibold mb-1">Sévérité</label>
            <select
              value={s.incident_banner_severity || "warning"}
              onChange={(e) => upd("incident_banner_severity", e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              data-testid="incident-banner-severity"
            >
              <option value="info">Info (bleu)</option>
              <option value="warning">Avertissement (orange)</option>
              <option value="critical">Critique (rouge)</option>
            </select>
          </div>
          <Input label="Libellé du lien (optionnel)" value={s.incident_banner_link_label || ""} onChange={(v) => upd("incident_banner_link_label", v)} placeholder="Plus de détails" testid="incident-banner-link-label" />
          <Input label="URL du lien (optionnel)" value={s.incident_banner_link_url || ""} onChange={(v) => upd("incident_banner_link_url", v)} placeholder="/uptime ou https://..." testid="incident-banner-link-url" />
        </div>
        <div>
          <label className="block text-xs font-semibold mb-1">Message <span className="text-slate-400">(visible par tous les visiteurs)</span></label>
          <textarea
            value={s.incident_banner_message || ""}
            onChange={(e) => upd("incident_banner_message", e.target.value)}
            rows={2}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:border-sawali-blue focus:ring-2 focus:ring-sawali-blue/20"
            placeholder="Maintenance planifiée le 30/04 de 22h à 23h GMT — accès au portail interrompu."
            data-testid="incident-banner-message-input"
          />
        </div>
        {/* Live preview */}
        {s.incident_banner_enabled && s.incident_banner_message && (
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3" data-testid="incident-banner-preview">
            <p className="text-[10px] uppercase tracking-[0.2em] text-slate-500 mb-2">Aperçu en direct</p>
            <BannerPreview
              severity={s.incident_banner_severity || "warning"}
              message={s.incident_banner_message}
              linkLabel={s.incident_banner_link_label}
              linkUrl={s.incident_banner_link_url}
            />
          </div>
        )}
      </Section>

      <Section icon={MessageCircle} title="WhatsApp Business API (Meta Cloud)">
        <p className="text-xs text-slate-500">
          Configuration globale. Tous les clients utilisent ce compte WhatsApp Business (Meta Business Portfolio).
          Les templates doivent être créés et approuvés dans Meta Business Suite &rarr; WhatsApp &rarr; Templates de messages.
          <a href="https://business.facebook.com/wa/manage/home/" target="_blank" rel="noreferrer" className="text-sawali-blue underline ml-1">Ouvrir Meta Business Suite →</a>
        </p>
        <div className="grid sm:grid-cols-2 gap-3">
          <Input label="WhatsApp Business Account ID (WABA)" value={s.wa_business_account_id || ""} onChange={(v) => upd("wa_business_account_id", v)} placeholder="102xxxxxxxxxxx" testid="wa-waba-id" />
          <Input label="Phone Number ID" value={s.wa_phone_number_id || ""} onChange={(v) => upd("wa_phone_number_id", v)} placeholder="10xxxxxxxxxxxxx" testid="wa-phone-number-id" />
          <Input label="Meta App ID" value={s.wa_app_id || ""} onChange={(v) => upd("wa_app_id", v)} placeholder="App ID (facebook developers)" testid="wa-app-id" />
          <Input label="Langue par défaut (ex: fr, en_US)" value={s.wa_default_language || "fr"} onChange={(v) => upd("wa_default_language", v)} placeholder="fr" testid="wa-default-language" />
        </div>
        <Input label="System User Access Token (permanent)" type="password" value={s.wa_access_token || ""} onChange={(v) => upd("wa_access_token", v)} placeholder={s.wa_access_token === "********" ? "(défini — cliquer pour modifier)" : "EAAxxxxxxxxxxxx…"} testid="wa-access-token" />
        <Input label="Webhook Verify Token (secret partagé)" type="password" value={s.wa_verify_token || ""} onChange={(v) => upd("wa_verify_token", v)} placeholder={s.wa_verify_token === "********" ? "(défini — cliquer pour modifier)" : "Jeton aléatoire à inscrire aussi côté Meta"} testid="wa-verify-token" />
        <WaTestPanel />
        <WaTokenHealthPanel />
        <WaWebhookSubscriptionPanel />
        <WaWebhookLogsPanel />
        <WaSilenceAlertPanel s={s} upd={upd} />

        {/* Iter37g — Caisse templates */}
        <div className="rounded-xl ring-1 ring-sky-200 bg-sky-50/40 p-4 space-y-3">
          <p className="text-sm font-semibold text-sawali-blue">Templates Caisse — Reçus & Factures/Proformas</p>
          <p className="text-xs text-slate-600">
            Lors de l'envoi WhatsApp d'un reçu ou d'une facture, ces templates Meta sont utilisés (avec PDF en pièce jointe).
            Les paramètres du <em>body</em> sont, dans l'ordre :
            <br /><strong>Reçu</strong> : <code>{`{1}`}</code> nom client, <code>{`{2}`}</code> n° reçu, <code>{`{3}`}</code> montant, <code>{`{4}`}</code> motif.
            <br /><strong>Facture/Proforma</strong> : <code>{`{1}`}</code> nom client, <code>{`{2}`}</code> type (Facture/Proforma), <code>{`{3}`}</code> n° doc, <code>{`{4}`}</code> montant.
          </p>
          <div className="grid sm:grid-cols-2 gap-3">
            <Input
              label="Template Reçu (nom Meta)"
              value={s.wa_template_receipt_name || ""}
              onChange={(v) => upd("wa_template_receipt_name", v)}
              placeholder="confirmation_paiement_avecrecu"
              testid="wa-template-receipt-name"
            />
            <Input
              label="Langue Reçu (ex: fr)"
              value={s.wa_template_receipt_language || ""}
              onChange={(v) => upd("wa_template_receipt_language", v)}
              placeholder="fr"
              testid="wa-template-receipt-language"
            />
            <Input
              label="Template Facture/Proforma (nom Meta)"
              value={s.wa_template_invoice_name || ""}
              onChange={(v) => upd("wa_template_invoice_name", v)}
              placeholder="document_piecejointe_facturation"
              testid="wa-template-invoice-name"
            />
            <Input
              label="Langue Facture (ex: fr)"
              value={s.wa_template_invoice_language || ""}
              onChange={(v) => upd("wa_template_invoice_language", v)}
              placeholder="fr"
              testid="wa-template-invoice-language"
            />
          </div>
        </div>

        {/* Iter38r-fix9o (Item 8) — Template OTP login WhatsApp.
            Réutilise la même config WA (access_token + phone_number_id) ;
            il suffit de créer un template Meta avec UN paramètre body. */}
        <div className="mt-4 pt-4 border-t border-slate-200">
          <h4 className="text-sm font-semibold text-slate-700 inline-flex items-center gap-2">
            <MessageCircle className="h-4 w-4 text-emerald-600" />
            Template WhatsApp — Connexion par OTP (page de login)
          </h4>
          <p className="text-xs text-slate-500 mt-1">
            Réutilise la même configuration WhatsApp ci-dessus. Variable unique <code className="rounded bg-slate-100 px-1">{"{{1}}"}</code> = code à 6 chiffres.
            Si vide, le code est envoyé en <strong>message texte direct</strong> (fenêtre 24h uniquement).
          </p>
          <div className="mt-3 grid sm:grid-cols-2 gap-3">
            <Input
              label="Nom du template (ex. wa_envoiotp_fr)"
              value={s.wa_otp_template || ""}
              onChange={(v) => upd("wa_otp_template", v)}
              placeholder="wa_envoiotp_fr"
              testid="wa-otp-template"
            />
            <Input
              label="Langue du template OTP"
              value={s.wa_otp_template_lang || ""}
              onChange={(v) => upd("wa_otp_template_lang", v)}
              placeholder="fr"
              testid="wa-otp-template-lang"
            />
          </div>
          <div className="mt-3 rounded-lg bg-emerald-50 ring-1 ring-emerald-200 p-3 text-xs text-emerald-900">
            <strong className="block mb-1">📝 Exemple de contenu à créer côté Meta Business Manager :</strong>
            <pre className="font-mono text-[11px] whitespace-pre-wrap leading-relaxed">SAWALI — Votre code de connexion est : {"{{1}}"}.{"\n"}Valable 10 minutes. Ne le partagez avec personne.</pre>
            <p className="text-[10px] mt-2 text-emerald-800">
              Catégorie : <strong>Authentication</strong> ou <strong>Utility</strong> · 1 paramètre body uniquement.
            </p>
          </div>

          {/* Iter38r-fix9o — Test send button to validate template config */}
          <WaOtpTester />
        </div>
      </Section>

      <Section icon={Ticket} title="Tickets d'intervention — notifications WhatsApp">
        <p className="text-xs text-slate-500">
          À l'ouverture/clôture d'un ticket, le contact peut recevoir une notification via un template Meta approuvé.
          Les variables transmises sont : <code className="bg-slate-100 px-1 rounded">{`{1}`}</code> = numéro de ticket,{" "}
          <code className="bg-slate-100 px-1 rounded">{`{2}`}</code> = motif (à l'ouverture) ou durée (à la clôture).
        </p>
        <div className="grid sm:grid-cols-2 gap-3">
          <Toggle
            label="Notifier le contact à l'ouverture d'un ticket"
            value={s.notify_on_ticket_open !== false}
            onChange={(v) => upd("notify_on_ticket_open", v)}
            testid="toggle-notify-ticket-open"
          />
          <Toggle
            label="Notifier le contact à la clôture d'un ticket"
            value={s.notify_on_ticket_close !== false}
            onChange={(v) => upd("notify_on_ticket_close", v)}
            testid="toggle-notify-ticket-close"
          />
        </div>
        <div className="grid sm:grid-cols-2 gap-3">
          <Input
            label="Template Meta — ouverture (ex. ticket_open_fr)"
            value={s.wa_template_ticket_open || ""}
            onChange={(v) => upd("wa_template_ticket_open", v)}
            placeholder="ticket_open_fr"
            testid="wa-tpl-ticket-open"
          />
          <Input
            label="Template Meta — clôture (ex. ticket_close_fr)"
            value={s.wa_template_ticket_close || ""}
            onChange={(v) => upd("wa_template_ticket_close", v)}
            placeholder="ticket_close_fr"
            testid="wa-tpl-ticket-close"
          />
        </div>
        <Input
          label="Langue du template (code Meta, ex. fr, en_US)"
          value={s.wa_template_ticket_language || ""}
          onChange={(v) => upd("wa_template_ticket_language", v)}
          placeholder="fr"
          testid="wa-tpl-ticket-language"
        />
      </Section>

      <Section icon={Upload} title="Médias WhatsApp (réception, envoi, filigrane)">
        <p className="text-xs text-slate-500">
          Réglages liés à l'envoi/réception d'images, audio, vidéos et PDF sur WhatsApp.
          Le filigrane discret et le QR code sont automatiquement appliqués sur les <strong>images sortantes</strong>.
          Les notes vocales reçues peuvent être transcrites automatiquement par OpenAI Whisper.
        </p>
        <div className="grid sm:grid-cols-2 gap-3">
          <Toggle
            label="Autoriser l'envoi de médias depuis ce terminal"
            value={s.wa_allow_terminal_media !== false}
            onChange={(v) => upd("wa_allow_terminal_media", v)}
            testid="toggle-wa-terminal-media"
          />
          <Toggle
            label="Transcrire automatiquement les notes vocales reçues (Whisper)"
            value={s.wa_voice_transcribe_enabled !== false}
            onChange={(v) => upd("wa_voice_transcribe_enabled", v)}
            testid="toggle-wa-voice-transcribe"
          />
          <Toggle
            label="Filigrane sur les images envoyées"
            value={s.wa_watermark_enabled !== false}
            onChange={(v) => upd("wa_watermark_enabled", v)}
            testid="toggle-wa-watermark"
          />
          <Toggle
            label="QR code sur les images envoyées"
            value={s.wa_qr_enabled !== false}
            onChange={(v) => upd("wa_qr_enabled", v)}
            testid="toggle-wa-qr"
          />
        </div>
        <Input
          label="Texte du filigrane (par défaut : nom de l'entreprise)"
          value={s.wa_watermark_text || ""}
          onChange={(v) => upd("wa_watermark_text", v)}
          placeholder="SAWALI SMART SYSTEMS"
          testid="wa-watermark-text"
        />
        <Input
          label="Charge utile du QR code (URL ou texte ; par défaut : site web)"
          value={s.wa_qr_payload || ""}
          onChange={(v) => upd("wa_qr_payload", v)}
          placeholder="https://votre-site.com"
          testid="wa-qr-payload"
        />
      </Section>

      <Section icon={Mic} title="Transcription audio (OpenAI Whisper)">
        <p className="text-xs text-slate-500">
          Permet à l'utilisateur d'enregistrer sa voix pour rédiger un Rapport ou un Suivi.
          La clé est stockée chiffrée et n'est jamais ré-affichée en clair.
          Obtenez votre clé sur <a href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer" className="text-sawali-blue underline">platform.openai.com/api-keys</a>.
        </p>
        <Input
          label="Clé API OpenAI"
          type="password"
          value={s.openai_api_key || ""}
          onChange={(v) => upd("openai_api_key", v)}
          placeholder={s.openai_api_key === "********" ? "(définie — cliquer pour modifier)" : "sk-..."}
          testid="openai-api-key"
        />
        <Input
          label="Modèle Whisper (par défaut: whisper-1)"
          value={s.openai_whisper_model || ""}
          onChange={(v) => upd("openai_whisper_model", v)}
          placeholder="whisper-1"
          testid="openai-whisper-model"
        />
      </Section>

      <Section icon={Sparkles} title="Synthèse IA (ChatGPT ou n8n / AgentAI)">
        <p className="text-xs text-slate-500">
          Le bouton « Synthèse IA » du tableau de bord appelle le moteur sélectionné ci-dessous.
          Vous pouvez basculer librement entre OpenAI ChatGPT et un webhook n8n (compatible AgentAI).
        </p>
        <div>
          <label className="block text-xs font-semibold mb-1">Moteur de synthèse</label>
          <select
            value={s.ai_summary_provider || "openai"}
            onChange={(e) => upd("ai_summary_provider", e.target.value)}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            data-testid="ai-summary-provider"
          >
            <option value="openai">OpenAI ChatGPT (clé API directe)</option>
            <option value="n8n">Webhook n8n / AgentAI</option>
          </select>
        </div>

        {/* OpenAI ChatGPT block */}
        <div className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3 space-y-2">
          <p className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">OpenAI ChatGPT</p>
          <Input
            label="Clé API ChatGPT"
            type="password"
            value={s.openai_chat_api_key || ""}
            onChange={(v) => upd("openai_chat_api_key", v)}
            placeholder={s.openai_chat_api_key === "********" ? "(définie — cliquer pour modifier)" : "sk-..."}
            testid="openai-chat-api-key"
          />
          <Input
            label="Modèle ChatGPT (par défaut: gpt-4o-mini)"
            value={s.openai_chat_model || ""}
            onChange={(v) => upd("openai_chat_model", v)}
            placeholder="gpt-4o-mini"
            testid="openai-chat-model"
          />
        </div>

        {/* n8n webhook block */}
        <div className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3 space-y-2">
          <p className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">Webhook n8n / AgentAI</p>
          <p className="text-[11px] text-slate-500">
            Le portail postera <code>{"{type, user, context, target, system_prompt, user_prompt, messages}"}</code> sur cette URL et attend une réponse JSON contenant <code>summary</code> (ou <code>text</code> / <code>output</code>).
          </p>
          <Input
            label="URL du webhook n8n"
            value={s.n8n_webhook_url || ""}
            onChange={(v) => upd("n8n_webhook_url", v)}
            placeholder="https://n8n.example.com/webhook/sawali-summary"
            testid="n8n-webhook-url"
          />
          <div>
            <label className="block text-xs font-semibold mb-1">Authentification</label>
            <select
              value={s.n8n_webhook_auth_type || "none"}
              onChange={(e) => upd("n8n_webhook_auth_type", e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              data-testid="n8n-webhook-auth-type"
            >
              <option value="none">Aucune</option>
              <option value="bearer">Bearer Token</option>
              <option value="basic">Basic Auth</option>
            </select>
          </div>
          {s.n8n_webhook_auth_type === "bearer" && (
            <Input
              label="Token Bearer"
              type="password"
              value={s.n8n_webhook_token || ""}
              onChange={(v) => upd("n8n_webhook_token", v)}
              placeholder={s.n8n_webhook_token === "********" ? "(défini)" : ""}
              testid="n8n-webhook-token"
            />
          )}
          {s.n8n_webhook_auth_type === "basic" && (
            <div className="grid sm:grid-cols-2 gap-3">
              <Input label="Utilisateur" value={s.n8n_webhook_basic_user || ""} onChange={(v) => upd("n8n_webhook_basic_user", v)} testid="n8n-webhook-basic-user" />
              <Input
                label="Mot de passe"
                type="password"
                value={s.n8n_webhook_basic_pass || ""}
                onChange={(v) => upd("n8n_webhook_basic_pass", v)}
                placeholder={s.n8n_webhook_basic_pass === "********" ? "(défini)" : ""}
                testid="n8n-webhook-basic-pass"
              />
            </div>
          )}
        </div>
      </Section>

      <Section icon={Smartphone} title="SMS — Opérateurs Burkina Faso (Orange / Moov / Telecel)">
        <p className="text-xs text-slate-500">
          Trois fournisseurs indépendants. Chacun expose son propre endpoint REST.
          Renseignez l'URL fournie par l'opérateur, la méthode HTTP et le mode d'authentification.
        </p>
        {[
          { key: "orange", label: "Orange Burkina", color: "#FF7900" },
          { key: "moov", label: "Moov Africa Burkina", color: "#0076BB" },
          { key: "telecel", label: "Telecel Burkina", color: "#E2241A" },
        ].map((op) => (
          <div key={op.key} className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3 space-y-2" data-testid={`sms-${op.key}-block`}>
            <div className="flex items-center justify-between">
              <p className="text-[11px] uppercase tracking-wider font-semibold" style={{ color: op.color }}>
                SMS {op.label}
              </p>
              <Toggle
                label="Activer"
                value={!!s[`sms_${op.key}_enabled`]}
                onChange={(v) => upd(`sms_${op.key}_enabled`, v)}
                testid={`sms-${op.key}-enabled`}
              />
            </div>
            <div className="grid sm:grid-cols-[1fr_140px] gap-3">
              <Input
                label="URL de l'API SMS"
                value={s[`sms_${op.key}_url`] || ""}
                onChange={(v) => upd(`sms_${op.key}_url`, v)}
                placeholder="https://api.operateur.bf/v1/sms/send"
                testid={`sms-${op.key}-url`}
              />
              <div>
                <label className="block text-xs font-semibold mb-1">Méthode</label>
                <select
                  value={s[`sms_${op.key}_method`] || "POST"}
                  onChange={(e) => upd(`sms_${op.key}_method`, e.target.value)}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  data-testid={`sms-${op.key}-method`}
                >
                  <option value="POST">POST</option>
                  <option value="GET">GET</option>
                </select>
              </div>
            </div>
            <div>
              <label className="block text-xs font-semibold mb-1">Authentification</label>
              <select
                value={s[`sms_${op.key}_auth_type`] || "none"}
                onChange={(e) => upd(`sms_${op.key}_auth_type`, e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                data-testid={`sms-${op.key}-auth-type`}
              >
                <option value="none">Aucune</option>
                <option value="bearer">Bearer Token</option>
                <option value="basic">Basic Auth</option>
                <option value="header">En-tête personnalisé (API Key)</option>
                {/* Iter35i — Orange Developer / Moov / Telecel OAuth2 client_credentials */}
                <option value="orange_oauth">OAuth2 client_credentials (Orange Developer)</option>
                {/* Iter35k — Webhook bridge (n8n/Make/Zapier) */}
                <option value="webhook">Webhook personnalisé (n8n / Make / Zapier)</option>
              </select>
            </div>
            {s[`sms_${op.key}_auth_type`] === "webhook" && (
              <div className="rounded-lg border-2 border-indigo-300 bg-indigo-50/40 p-3 space-y-2" data-testid={`sms-${op.key}-webhook-block`}>
                <p className="text-[11px] text-indigo-900">
                  <strong>Mode webhook (n8n / Make / Zapier).</strong> Notre serveur fait un{" "}
                  <code>POST</code> JSON vers <code>{`{URL ci-dessus}`}</code> avec le payload :
                </p>
                <pre className="text-[10px] bg-white border border-indigo-200 rounded p-2 overflow-x-auto">{`{
  "provider": "${op.key}",
  "phone": "+22607332313",
  "message": "Bonjour…",
  "sender": "+22677000155"
}`}</pre>
                <p className="text-[11px] text-indigo-900">
                  Votre workflow doit retourner soit un statut HTTP 200 vide,
                  soit un JSON <code>{`{ "ok": true }`}</code> ou{" "}
                  <code>{`{ "status": "sent" }`}</code>. En cas d'erreur :{" "}
                  <code>{`{ "error": { "status": 400, "code": "...", "message": "..." } }`}</code>.
                </p>
                <Input
                  label="Token Bearer pour sécuriser l'appel (facultatif)"
                  type="password"
                  value={s[`sms_${op.key}_token`] || ""}
                  onChange={(v) => upd(`sms_${op.key}_token`, v)}
                  placeholder={s[`sms_${op.key}_token`] === "********" ? "(défini)" : "Laisser vide si le webhook est public"}
                  testid={`sms-${op.key}-webhook-token`}
                />
                <p className="text-[10px] text-indigo-700">
                  💡 Pensez à renseigner <strong>URL de l'API SMS</strong> ci-dessus avec l'URL de votre webhook (ex. <code>https://n8n.exemple.com/webhook/88e0f7b3-…</code>).
                </p>
              </div>
            )}
            {s[`sms_${op.key}_auth_type`] === "orange_oauth" && (
              <div className="rounded-lg border-2 border-orange-300 bg-orange-50/40 p-3 space-y-2" data-testid={`sms-${op.key}-oauth-block`}>
                <p className="text-[11px] text-orange-900">
                  <strong>Mode Orange Developer.</strong> Génère automatiquement un token Bearer via{" "}
                  <code>POST {`{oauth_url}`}</code> avec{" "}
                  <code>Authorization: Basic base64(client_id:client_secret)</code> et un corps{" "}
                  <code>grant_type=client_credentials</code> au format <code>x-www-form-urlencoded</code>.
                  Corrige l'erreur « Missing grant_type in body » du flow générique.
                </p>
                <Input
                  label="URL OAuth (défaut : https://api.orange.com/oauth/v3/token)"
                  value={s[`sms_${op.key}_oauth_url`] || ""}
                  onChange={(v) => upd(`sms_${op.key}_oauth_url`, v)}
                  placeholder="https://api.orange.com/oauth/v3/token"
                  testid={`sms-${op.key}-oauth-url`}
                />
                <Input
                  label="Client ID"
                  value={s[`sms_${op.key}_client_id`] || ""}
                  onChange={(v) => upd(`sms_${op.key}_client_id`, v)}
                  placeholder="abc123…"
                  testid={`sms-${op.key}-client-id`}
                />
                <Input
                  label="Client Secret"
                  type="password"
                  value={s[`sms_${op.key}_client_secret`] || ""}
                  onChange={(v) => upd(`sms_${op.key}_client_secret`, v)}
                  placeholder={s[`sms_${op.key}_client_secret`] === "********" ? "(défini)" : ""}
                  testid={`sms-${op.key}-client-secret`}
                />
                <Input
                  label="Numéro émetteur Orange (format E.164, ex. +22670000000)"
                  value={s[`sms_${op.key}_sender_msisdn`] || ""}
                  onChange={(v) => upd(`sms_${op.key}_sender_msisdn`, v)}
                  placeholder="+22670000000"
                  testid={`sms-${op.key}-sender-msisdn`}
                />
                <p className="text-[10px] text-orange-700">
                  💡 Pour Orange, laissez « URL de l'API SMS » sur <code>https://api.orange.com/smsmessaging/v1</code> — on construit automatiquement le chemin <code>/outbound/tel:&lt;sender&gt;/requests</code>.
                </p>
              </div>
            )}
            {s[`sms_${op.key}_auth_type`] === "bearer" && (
              <Input
                label="Token Bearer"
                type="password"
                value={s[`sms_${op.key}_token`] || ""}
                onChange={(v) => upd(`sms_${op.key}_token`, v)}
                placeholder={s[`sms_${op.key}_token`] === "********" ? "(défini)" : ""}
                testid={`sms-${op.key}-token`}
              />
            )}
            {s[`sms_${op.key}_auth_type`] === "basic" && (
              <div className="grid sm:grid-cols-2 gap-3">
                <Input label="Utilisateur" value={s[`sms_${op.key}_basic_user`] || ""} onChange={(v) => upd(`sms_${op.key}_basic_user`, v)} testid={`sms-${op.key}-basic-user`} />
                <Input
                  label="Mot de passe"
                  type="password"
                  value={s[`sms_${op.key}_basic_pass`] || ""}
                  onChange={(v) => upd(`sms_${op.key}_basic_pass`, v)}
                  placeholder={s[`sms_${op.key}_basic_pass`] === "********" ? "(défini)" : ""}
                  testid={`sms-${op.key}-basic-pass`}
                />
              </div>
            )}
            {s[`sms_${op.key}_auth_type`] === "header" && (
              <div className="grid sm:grid-cols-2 gap-3">
                <Input
                  label="Nom de l'en-tête"
                  value={s[`sms_${op.key}_header_name`] || ""}
                  onChange={(v) => upd(`sms_${op.key}_header_name`, v)}
                  placeholder="X-API-Key"
                  testid={`sms-${op.key}-header-name`}
                />
                <Input
                  label="Valeur"
                  type="password"
                  value={s[`sms_${op.key}_header_value`] || ""}
                  onChange={(v) => upd(`sms_${op.key}_header_value`, v)}
                  placeholder={s[`sms_${op.key}_header_value`] === "********" ? "(définie)" : ""}
                  testid={`sms-${op.key}-header-value`}
                />
              </div>
            )}
            <Input
              label="Identifiant expéditeur (sender ID)"
              value={s[`sms_${op.key}_sender`] || ""}
              onChange={(v) => upd(`sms_${op.key}_sender`, v)}
              placeholder="SAWALI"
              testid={`sms-${op.key}-sender`}
            />
            <div>
              <label className="block text-xs font-semibold mb-1">
                Template du payload (JSON ou form-data) — placeholders : <code className="text-[10px] bg-slate-100 px-1">{"{phone}"}</code> <code className="text-[10px] bg-slate-100 px-1">{"{message}"}</code> <code className="text-[10px] bg-slate-100 px-1">{"{sender}"}</code>
              </label>
              <textarea
                value={s[`sms_${op.key}_payload_template`] || ""}
                onChange={(e) => upd(`sms_${op.key}_payload_template`, e.target.value)}
                rows={3}
                placeholder={'{"to":"{phone}","text":"{message}","from":"{sender}"}'}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-mono"
                data-testid={`sms-${op.key}-payload-template`}
              />
              <div className="grid grid-cols-2 gap-2 mt-1">
                <select
                  value={s[`sms_${op.key}_content_type`] || "json"}
                  onChange={(e) => upd(`sms_${op.key}_content_type`, e.target.value)}
                  className="rounded-md ring-1 ring-slate-300 px-2 py-1 text-xs bg-white"
                  data-testid={`sms-${op.key}-content-type`}
                >
                  <option value="json">JSON (application/json)</option>
                  <option value="form">Form (application/x-www-form-urlencoded)</option>
                </select>
              </div>
            </div>
            <SmsTestButton provider={op.key} testid={`sms-${op.key}-test-btn`} />
          </div>
        ))}
      </Section>

      <Section icon={Smartphone} title="SMS — OVH (API officielle)">
        <p className="text-xs text-slate-500">
          OVH SMS expose une API REST signée HMAC. Créez un service SMS sur <a href="https://www.ovhtelecom.fr/sms/" target="_blank" rel="noreferrer" className="text-sawali-blue underline">ovhtelecom.fr</a> puis générez l'application via <code>https://api.ovh.com/createApp</code>.
        </p>
        <div className="grid sm:grid-cols-2 gap-3">
          <Toggle label="Activer" value={!!s.sms_ovh_enabled} onChange={(v) => upd("sms_ovh_enabled", v)} testid="sms-ovh-enabled" />
          <div>
            <label className="block text-xs font-semibold mb-1">Endpoint OVH</label>
            <select
              value={s.sms_ovh_endpoint || "ovh-eu"}
              onChange={(e) => upd("sms_ovh_endpoint", e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              data-testid="sms-ovh-endpoint"
            >
              <option value="ovh-eu">ovh-eu (Europe)</option>
              <option value="ovh-ca">ovh-ca (Canada)</option>
            </select>
          </div>
        </div>
        <Input label="Application Key (AK)" value={s.sms_ovh_application_key || ""} onChange={(v) => upd("sms_ovh_application_key", v)} placeholder="xxxxxxxxxxxxxxxx" testid="sms-ovh-application-key" />
        <Input
          label="Application Secret (AS)"
          type="password"
          value={s.sms_ovh_application_secret || ""}
          onChange={(v) => upd("sms_ovh_application_secret", v)}
          placeholder={s.sms_ovh_application_secret === "********" ? "(défini)" : ""}
          testid="sms-ovh-application-secret"
        />
        <Input
          label="Consumer Key (CK)"
          type="password"
          value={s.sms_ovh_consumer_key || ""}
          onChange={(v) => upd("sms_ovh_consumer_key", v)}
          placeholder={s.sms_ovh_consumer_key === "********" ? "(défini)" : ""}
          testid="sms-ovh-consumer-key"
        />
        <Input label="Service Name" value={s.sms_ovh_service_name || ""} onChange={(v) => upd("sms_ovh_service_name", v)} placeholder="sms-ab1234-1" testid="sms-ovh-service-name" />
        <Input label="Sender (expéditeur enregistré)" value={s.sms_ovh_sender || ""} onChange={(v) => upd("sms_ovh_sender", v)} placeholder="OVHSMS" testid="sms-ovh-sender" />
        <SmsTestButton provider="ovh" testid="sms-ovh-test-btn" />
        <div className="rounded-lg bg-slate-50 ring-1 ring-slate-200 p-3 mt-3">
          <label className="block text-xs font-semibold mb-1">Fournisseur SMS par défaut</label>
          <select
            value={s.sms_default_provider || "auto"}
            onChange={(e) => upd("sms_default_provider", e.target.value)}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm bg-white"
            data-testid="sms-default-provider"
          >
            <option value="auto">Auto (selon préfixe — Burkina → opérateur local, sinon OVH)</option>
            <option value="orange">Orange Burkina</option>
            <option value="moov">Moov Burkina</option>
            <option value="telecel">Telecel Burkina</option>
            <option value="ovh">OVH</option>
          </select>
          <p className="text-[10px] text-slate-500 mt-1">
            Utilisé quand le portail/Admin n'impose pas explicitement un fournisseur. Mode « auto » privilégie l'opérateur local Burkina pour les numéros +226, sinon bascule sur OVH.
          </p>
        </div>
      </Section>

      {/* Iter43-fix23b (2026-06) — Bird.com 2-Way SMS (remplace Africa's Talking) */}
      <Section icon={MessageSquare} title="📱 Bird.com — SMS Bidirectionnel (offline Liluvine)" anchorId="s-bird-sms">
        <p className="text-xs text-slate-500">
          Permet aux clients en zones à faible couverture internet (Burkina Faso) d'envoyer un SMS à Liluvine
          et de recevoir une réponse IA. Bird a racheté Africa's Talking et propose une plateforme unifiée.
          Provisionnez un Workspace + Channel SMS sur
          <a href="https://app.bird.com" target="_blank" rel="noreferrer" className="text-sawali-blue underline mx-1">app.bird.com</a>,
          créez une clé API avec la policy <strong>Messaging</strong>, puis configurez le webhook entrant pour qu'il pointe vers l'URL ci-dessous.
        </p>
        <Toggle label="Activer Bird SMS" value={!!s.bird_enabled} onChange={(v) => upd("bird_enabled", v)} testid="bird-enabled" />
        <Input
          label="API Base URL"
          value={s.bird_api_base_url || ""}
          onChange={(v) => upd("bird_api_base_url", v)}
          placeholder="https://api.bird.com (défaut)"
          testid="bird-api-base-url"
        />
        <div className="grid sm:grid-cols-2 gap-3">
          <Input
            label="Workspace ID"
            value={s.bird_workspace_id || ""}
            onChange={(v) => upd("bird_workspace_id", v)}
            placeholder="UUID workspace Bird"
            testid="bird-workspace-id"
          />
          <Input
            label="Channel ID (SMS)"
            value={s.bird_channel_id || ""}
            onChange={(v) => upd("bird_channel_id", v)}
            placeholder="UUID channel SMS Bird"
            testid="bird-channel-id"
          />
        </div>
        <Input
          label="Access Key (policy Messaging)"
          type="password"
          value={s.bird_access_key || ""}
          onChange={(v) => upd("bird_access_key", v)}
          placeholder={s.bird_access_key === "********" ? "(défini)" : "n685... (clé Bird avec policy Messaging)"}
          testid="bird-access-key"
        />
        <Input
          label="Webhook Signing Secret (HMAC SHA-256)"
          type="password"
          value={s.bird_webhook_secret || ""}
          onChange={(v) => upd("bird_webhook_secret", v)}
          placeholder={s.bird_webhook_secret === "********" ? "(défini)" : "Secret partagé pour vérifier Bird-Signature"}
          testid="bird-webhook-secret"
        />
        <Input
          label="Sender ID / Numéro long par défaut"
          value={s.bird_default_sender || ""}
          onChange={(v) => upd("bird_default_sender", v)}
          placeholder="ex. SAWALI ou +226XXXXXXXX"
          testid="bird-default-sender"
        />
        <Input
          label="Signature (ajoutée à chaque réponse)"
          value={s.bird_signature || ""}
          onChange={(v) => upd("bird_signature", v)}
          placeholder="ex. — Liluvine / SAWALI"
          testid="bird-signature"
        />
        <Toggle
          label="Router les SMS entrants vers Liluvine (réponse IA automatique)"
          value={s.bird_use_liluvine !== false}
          onChange={(v) => upd("bird_use_liluvine", v)}
          testid="bird-use-liluvine"
        />
        {/* Iter43-fix24d — Estimation de coût SMS (badge inbox + admin) */}
        <div className="grid sm:grid-cols-2 gap-3">
          <Input
            label="Coût unitaire par SMS"
            type="number"
            value={s.bird_cost_per_sms_xof || ""}
            onChange={(v) => upd("bird_cost_per_sms_xof", v)}
            placeholder="25 (défaut)"
            testid="bird-cost-per-sms"
          />
          <div>
            <label className="block text-xs font-semibold mb-1">Devise</label>
            <select
              value={s.bird_cost_currency || "XOF"}
              onChange={(e) => upd("bird_cost_currency", e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              data-testid="bird-cost-currency"
            >
              <option value="XOF">XOF (FCFA)</option>
              <option value="EUR">EUR</option>
              <option value="USD">USD</option>
            </select>
          </div>
        </div>
        <div className="rounded-lg bg-slate-50 ring-1 ring-slate-200 p-3 mt-3 space-y-2">
          <p className="text-xs font-semibold text-slate-700">📌 URLs à configurer dans Bird → Channels → SMS → Webhooks :</p>
          {/* Iter43-fix24e — URL publique éditable (par défaut = REACT_APP_BACKEND_URL = preview) */}
          <Input
            label="Base URL publique (pour les webhooks)"
            value={s.public_base_url || ""}
            onChange={(v) => upd("public_base_url", v)}
            placeholder="https://sawalismartsystems.com (laisser vide pour utiliser l'URL preview courante)"
            testid="public-base-url"
          />
          <CopyableUrl
            label="Inbound Messages (SMS entrants → Liluvine)"
            path="/api/webhooks/bird/inbound-sms"
            baseUrl={s.public_base_url}
          />
          <CopyableUrl
            label="Delivery Reports (rapports de livraison — optionnel)"
            path="/api/webhooks/bird/delivery-report"
            baseUrl={s.public_base_url}
          />
          <p className="text-[10px] text-slate-500 mt-2">
            💡 Le webhook valide la signature HMAC SHA-256 dans le header <code>Bird-Signature</code>
            si le Webhook Signing Secret est défini ci-dessus. Sans secret, le webhook est ouvert (à éviter en prod).
          </p>
        </div>
        {/* Iter43-fix24l — Bouton de test SMS Bird avec retour HTTP complet */}
        <BirdTestSmsBlock defaultSender={s.bird_default_sender || ""} />
      </Section>

      {/* Iter43-fix24n (2026-06) — Délégation menu Officines à des comptes non-admin */}
      <Section icon={Building2} title="🏥 Délégation menu Officines (comptes autorisés)" anchorId="s-officines-delegation">
        <p className="text-xs text-slate-500">
          Liste des comptes utilisateur (par email) autorisés à accéder à <code className="px-1 bg-slate-100 rounded">/admin/officines</code>
          sans avoir le rôle administrateur. Ces utilisateurs ne peuvent modifier que :
          <strong className="text-slate-700"> intitulé, téléphone, WhatsApp, géolocalisation (lat/lon), indication de localisation, activité principale</strong>.
          Tous les autres champs restent grisés en édition. Pour la création d'une nouvelle officine, tous les champs sont actifs.
        </p>
        <Input
          label="Emails autorisés (séparés par des virgules)"
          value={Array.isArray(s.officines_menu_allowed_emails)
            ? s.officines_menu_allowed_emails.join(", ")
            : (s.officines_menu_allowed_emails || "")}
          onChange={(v) => {
            const arr = (v || "").split(",").map((x) => x.trim()).filter(Boolean);
            upd("officines_menu_allowed_emails", arr);
          }}
          placeholder="user1@sawali.com, user2@sawali.com"
          testid="officines-allowed-emails"
        />
        <p className="text-[10px] text-slate-500 mt-1">
          💡 Les administrateurs gardent un accès complet automatiquement, indépendamment de cette liste.
        </p>
      </Section>

      {/* Iter43-fix23 (2026-06) — Webhook d'inventaire officines (Bearer) */}
      <Section icon={Package} title="📦 Webhook Inventaire Officines (Bearer)" anchorId="s-officines-inventory-webhook">
        <p className="text-xs text-slate-500">
          Endpoint REST POST qui reçoit l'inventaire d'une officine via Bearer token, en complément
          des modes CSV/JSON existants. Communiquez le token aux SI partenaires des officines.
        </p>
        <Input
          label="Bearer Token (partagé entre SI officines)"
          type="password"
          value={s.officines_inventory_webhook_token || ""}
          onChange={(v) => upd("officines_inventory_webhook_token", v)}
          placeholder={s.officines_inventory_webhook_token === "********" ? "(défini)" : "Générer un token long (≥ 32 chars)"}
          testid="officines-inventory-webhook-token"
        />
        <div className="rounded-lg bg-slate-50 ring-1 ring-slate-200 p-3 mt-3 space-y-2">
          <p className="text-xs font-semibold text-slate-700">📌 Endpoint :</p>
          <CopyableUrl
            label="POST inventaire (avec Authorization: Bearer ...)"
            path="/api/webhooks/officines/inventory"
            baseUrl={s.public_base_url}
          />
          <CopyableUrl
            label="Documentation intégrateurs (JSON)"
            path="/api/webhooks/officines/inventory/docs"
            baseUrl={s.public_base_url}
          />
          <p className="text-[10px] text-slate-500 mt-2">
            Le payload accepte les clés JSON (product_name, cip, quantity, …) OU les clés CSV françaises
            (Nom du produit, CIP, Quantité, …). Voir <code>/api/webhooks/officines/inventory/docs</code> pour le schéma complet.
          </p>
        </div>
      </Section>

      <Section icon={CreditCard} title="Paiement — PawaPay (Mobile Money)">        <p className="text-xs text-slate-500">
          Configuration prête pour intégration PawaPay (Mobile Money Africa).
          Le flow d'encaissement utilisateur sera ajouté ultérieurement.
        </p>
        <Toggle label="Activer PawaPay" value={!!s.pawapay_enabled} onChange={(v) => upd("pawapay_enabled", v)} testid="pawapay-enabled" />
        <Input
          label="API Token"
          type="password"
          value={s.pawapay_api_token || ""}
          onChange={(v) => upd("pawapay_api_token", v)}
          placeholder={s.pawapay_api_token === "********" ? "(défini)" : "eyJ..."}
          testid="pawapay-api-token"
        />
        <div className="grid sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-semibold mb-1">Environnement</label>
            <select
              value={s.pawapay_environment || "sandbox"}
              onChange={(e) => upd("pawapay_environment", e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              data-testid="pawapay-environment"
            >
              <option value="sandbox">Sandbox (test)</option>
              <option value="production">Production</option>
            </select>
          </div>
          <Input
            label="Pays par défaut (ISO-3)"
            value={s.pawapay_country || ""}
            onChange={(v) => upd("pawapay_country", (v || "").toUpperCase())}
            placeholder="BFA"
            testid="pawapay-country"
          />
        </div>
        <PawaPayCallbackUrls />
      </Section>

      <Section icon={Calendar} title="Agenda — Webhook n8n / AI Agent">
        <p className="text-xs text-slate-500">
          Permet à un agent IA dans n8n d'interroger ou de modifier les rendez-vous via webhook. Tous les utilisateurs d'un même client voient un agenda partagé.
          Coexiste avec Google Calendar (les RDV créés via n8n n'ont pas de gcal_event_id).
        </p>

        <div className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3 space-y-2">
          <p className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">Webhook sortant (notification → n8n)</p>
          <p className="text-[11px] text-slate-500">Posté à chaque création/modification/suppression manuelle d'un RDV.</p>
          <Toggle label="Activer notifications sortantes" value={!!s.agenda_n8n_outbound_enabled} onChange={(v) => upd("agenda_n8n_outbound_enabled", v)} testid="agenda-out-enabled" />
          <Input label="URL n8n" value={s.agenda_n8n_outbound_url || ""} onChange={(v) => upd("agenda_n8n_outbound_url", v)} placeholder="https://n8n.example.com/webhook/agenda" testid="agenda-out-url" />
          <div>
            <label className="block text-xs font-semibold mb-1">Authentification</label>
            <select value={s.agenda_n8n_outbound_auth_type || "none"} onChange={(e) => upd("agenda_n8n_outbound_auth_type", e.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="agenda-out-auth-type">
              <option value="none">Aucune</option>
              <option value="bearer">Bearer Token</option>
              <option value="basic">Basic Auth</option>
            </select>
          </div>
          {s.agenda_n8n_outbound_auth_type === "bearer" && (
            <Input label="Token" type="password" value={s.agenda_n8n_outbound_token || ""} onChange={(v) => upd("agenda_n8n_outbound_token", v)} placeholder={s.agenda_n8n_outbound_token === "********" ? "(défini)" : ""} testid="agenda-out-token" />
          )}
          {s.agenda_n8n_outbound_auth_type === "basic" && (
            <div className="grid sm:grid-cols-2 gap-3">
              <Input label="Utilisateur" value={s.agenda_n8n_outbound_basic_user || ""} onChange={(v) => upd("agenda_n8n_outbound_basic_user", v)} testid="agenda-out-basic-user" />
              <Input label="Mot de passe" type="password" value={s.agenda_n8n_outbound_basic_pass || ""} onChange={(v) => upd("agenda_n8n_outbound_basic_pass", v)} placeholder={s.agenda_n8n_outbound_basic_pass === "********" ? "(défini)" : ""} testid="agenda-out-basic-pass" />
            </div>
          )}
        </div>

        <div className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3 space-y-2">
          <p className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">Webhook entrant (n8n → SAWALI)</p>
          <p className="text-[11px] text-slate-500">
            n8n peut poster sur <code className="text-slate-800">POST /api/webhooks/agenda/{"{secret}"}</code> avec body
            <code className="text-slate-800"> {"{action: 'create|update|delete|list', client_email, appointment_id?, subject?, scheduled_at?, duration_min?, status?}"}</code>.
          </p>
          <Toggle label="Activer le webhook entrant" value={!!s.agenda_n8n_inbound_enabled} onChange={(v) => upd("agenda_n8n_inbound_enabled", v)} testid="agenda-in-enabled" />
          <Input
            label="Secret (path token)"
            type="password"
            value={s.agenda_n8n_inbound_secret || ""}
            onChange={(v) => upd("agenda_n8n_inbound_secret", v)}
            placeholder={s.agenda_n8n_inbound_secret === "********" ? "(défini)" : "ex: 5f3a-7c91-bd-..."}
            testid="agenda-in-secret"
          />
          <p className="text-[10px] text-slate-400">
            Choisissez une chaîne longue et aléatoire. Elle sert d'authentification dans l'URL du webhook entrant.
          </p>
        </div>
      </Section>

      <Section icon={Tag} title="Version stamp (footer)">
        <p className="text-xs text-slate-500">
          Personnalise l'affichage discret de la version (ex. <code>v1.0 · 06/05/2026 13:09</code>) en bas à gauche.
        </p>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <div>
            <label className="block text-xs font-semibold mb-1">Couleur</label>
            <div className="flex items-center gap-2">
              <input
                type="color"
                value={s.version_stamp_color || "#94a3b8"}
                onChange={(e) => upd("version_stamp_color", e.target.value)}
                className="h-10 w-14 rounded border border-slate-300 cursor-pointer"
                data-testid="version-stamp-color"
              />
              <input
                value={s.version_stamp_color || ""}
                onChange={(e) => upd("version_stamp_color", e.target.value)}
                placeholder="#94a3b8"
                className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono"
              />
            </div>
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">Taille</label>
            <select
              value={s.version_stamp_size || "xs"}
              onChange={(e) => upd("version_stamp_size", e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              data-testid="version-stamp-size"
            >
              <option value="xs">Très petit (10px)</option>
              <option value="sm">Petit (12px)</option>
              <option value="md">Normal (14px)</option>
              <option value="lg">Grand (16px)</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">Opacité ({s.version_stamp_opacity ?? 70}%)</label>
            <input
              type="range"
              min="10"
              max="100"
              step="5"
              value={s.version_stamp_opacity ?? 70}
              onChange={(e) => upd("version_stamp_opacity", parseInt(e.target.value, 10))}
              className="w-full"
              data-testid="version-stamp-opacity"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">Style</label>
            <select
              value={s.version_stamp_style || "normal"}
              onChange={(e) => upd("version_stamp_style", e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              data-testid="version-stamp-style"
            >
              <option value="normal">Normal</option>
              <option value="bold">Gras</option>
              <option value="italic">Italique</option>
              <option value="bold_italic">Gras + Italique</option>
            </select>
          </div>
        </div>
        {/* Preview */}
        <div className="mt-2 rounded ring-1 ring-slate-200 bg-slate-100 p-3">
          <p className="text-[11px] uppercase tracking-wider text-slate-500 mb-2">Aperçu</p>
          <span
            data-testid="version-stamp-preview"
            style={{
              color: s.version_stamp_color || "#94a3b8",
              opacity: (s.version_stamp_opacity ?? 70) / 100,
              fontSize:
                s.version_stamp_size === "lg" ? 16 :
                s.version_stamp_size === "md" ? 14 :
                s.version_stamp_size === "sm" ? 12 : 10,
              fontWeight: (s.version_stamp_style || "").includes("bold") ? 700 : 400,
              fontStyle: (s.version_stamp_style || "").includes("italic") ? "italic" : "normal",
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
            }}
          >
            v1.0 · 06/05/2026 13:09
          </span>
        </div>
      </Section>

      <Section icon={Activity} title="Santé applicative — Alertes & rapports">
        <p className="text-xs text-slate-500">
          Active l'envoi automatique d'alertes lors d'erreurs API et le rapport hebdomadaire (vendredi 05:00 Africa/Abidjan).
          Réservé au superviseur principal.
        </p>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <Toggle label="Alertes temps réel (erreurs ≥ 400)" value={!!s.health_realtime_enabled} onChange={(v) => upd("health_realtime_enabled", v)} testid="toggle-health-realtime" />
          <Toggle label="Rapport hebdomadaire (Vendredi 05:00)" value={!!s.health_weekly_enabled} onChange={(v) => upd("health_weekly_enabled", v)} testid="toggle-health-weekly" />
          <Toggle label="Auth Checker (alerte si flow login cassé)" value={!!s.health_auth_check_enabled} onChange={(v) => upd("health_auth_check_enabled", v)} testid="toggle-health-auth-check" />
          <Toggle label="Uptime Monitor (alerte si service indisponible)" value={!!s.health_uptime_alerts_enabled} onChange={(v) => upd("health_uptime_alerts_enabled", v)} testid="toggle-health-uptime" />
        </div>
        <Input label="Email destinataire (laisser vide = superviseur)" value={s.health_email_to || ""} onChange={(v) => upd("health_email_to", v)} placeholder="admin@sawalismartsystems.com" testid="health-email-to" />
        <Input label="Webhook URL" value={s.health_webhook_url || ""} onChange={(v) => upd("health_webhook_url", v)} placeholder="https://votre-service.com/sawali/health" testid="health-webhook-url" />
        <div>
          <label className="block text-xs font-semibold mb-1">Authentification webhook</label>
          <select value={s.health_webhook_auth_type || "none"} onChange={(e) => upd("health_webhook_auth_type", e.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="health-webhook-auth-type">
            <option value="none">Aucune</option>
            <option value="bearer">Bearer Token</option>
            <option value="basic">Basic Auth</option>
          </select>
        </div>
        {s.health_webhook_auth_type === "bearer" && (
          <Input label="Token Bearer" type="password" value={s.health_webhook_token || ""} onChange={(v) => upd("health_webhook_token", v)} placeholder={s.health_webhook_token === "********" ? "(défini)" : ""} testid="health-webhook-token" />
        )}
        {s.health_webhook_auth_type === "basic" && (
          <div className="grid sm:grid-cols-2 gap-3">
            <Input label="Utilisateur" value={s.health_webhook_basic_user || ""} onChange={(v) => upd("health_webhook_basic_user", v)} testid="health-webhook-basic-user" />
            <Input label="Mot de passe" type="password" value={s.health_webhook_basic_pass || ""} onChange={(v) => upd("health_webhook_basic_pass", v)} placeholder={s.health_webhook_basic_pass === "********" ? "(défini)" : ""} testid="health-webhook-basic-pass" />
          </div>
        )}
        <p className="text-[11px] text-slate-500">
          → Ouvrir <Link to="/admin/health" className="text-sawali-blue underline">/admin/health</Link> pour le dashboard temps réel et les boutons « Test alerte / Hebdo maintenant ».
        </p>
      </Section>

      {/* 2026-02 fork iter104 — Retard de paiement (seuil global) */}
      <Section icon={Webhook} title="Contrats — Seuil de retard de paiement (par défaut)" testid="contract-overdue-section">
        <p className="text-xs text-slate-500">
          Nombre de jours après la <em>dernière date de règlement</em> (ou, à défaut, la <em>date de signature</em>) au-delà duquel un client est considéré comme en retard. Chaque fiche client peut fixer sa propre valeur qui prévaut sur ce défaut. Un scan quotidien (08:15 Africa/Abidjan) envoie un email à l'administrateur pour chaque client au-delà du seuil.
        </p>
        <div className="grid sm:grid-cols-2 gap-3 items-end">
          <Input
            label="Nombre de jours par défaut"
            type="number"
            value={s.contract_overdue_days_default ?? 5}
            onChange={(v) => upd("contract_overdue_days_default", v === "" ? null : Math.max(1, Number(v) || 5))}
            placeholder="5"
            testid="contract-overdue-days-default"
          />
          <button
            type="button"
            onClick={async () => {
              try {
                const r = await apiClient.post("/admin/contract-overdue/run");
                toast.success(`Scan lancé : ${r.data.dispatched}/${r.data.scanned} clients notifiés (seuil ${r.data.threshold_default} j).`);
              } catch (e) {
                toast.error(e?.response?.data?.detail || "Erreur");
              }
            }}
            className="rounded-lg bg-teal-600 hover:bg-teal-700 text-white text-sm px-3 py-2"
            data-testid="contract-overdue-run-btn"
          >
            Lancer un scan maintenant
          </button>
        </div>
      </Section>

      <Section icon={Webhook} title="Webhook Interventions (REST API externe)">
        <p className="text-xs text-slate-500">
          À chaque création/mise à jour d'intervention, une requête <strong>POST</strong> est envoyée à
          <code className="text-sawali-blue mx-1">{"{URL_de_base}/{action}/{client_code}/{numero_intervention}"}</code>.
          <br />Exemple : <code className="text-sawali-blue">https://api.exemple.com/created/ACME/INT-2026-ACME-0001</code>.
          Le corps JSON contient l'objet intervention complet.
        </p>
        <Toggle label="Activer le webhook" value={!!s.webhook_enabled} onChange={(v) => upd("webhook_enabled", v)} testid="toggle-webhook" />
        <Input label="URL de base" value={s.webhook_base_url || ""} onChange={(v) => upd("webhook_base_url", v)} placeholder="https://api.votre-service.com" testid="webhook-base-url" />
        <div>
          <label className="block text-xs font-semibold mb-1">Authentification</label>
          <select value={s.webhook_auth_type || "none"} onChange={(e) => upd("webhook_auth_type", e.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="webhook-auth-type">
            <option value="none">Aucune</option>
            <option value="bearer">Bearer Token (header Authorization)</option>
            <option value="basic">Basic Auth (utilisateur + mot de passe)</option>
          </select>
        </div>
        {s.webhook_auth_type === "bearer" && (
          <Input label="Token Bearer" type="password" value={s.webhook_token || ""} onChange={(v) => upd("webhook_token", v)} placeholder={s.webhook_token === "********" ? "(défini)" : "ex. eyJhbGc..."} testid="webhook-token" />
        )}
        {s.webhook_auth_type === "basic" && (
          <div className="grid sm:grid-cols-2 gap-3">
            <Input label="Utilisateur" value={s.webhook_basic_user || ""} onChange={(v) => upd("webhook_basic_user", v)} testid="webhook-basic-user" />
            <Input label="Mot de passe" type="password" value={s.webhook_basic_pass || ""} onChange={(v) => upd("webhook_basic_pass", v)} placeholder={s.webhook_basic_pass === "********" ? "(défini)" : ""} testid="webhook-basic-pass" />
          </div>
        )}
        <p className="text-[11px] text-slate-500">
          Le code client est issu du champ <strong>Code client</strong> dans la fiche client (ou dérivé du nom de l'entreprise).
        </p>
      </Section>

      <Section icon={Webhook} title="Webhook Rapports & Suivis (REST API externe)">
        <p className="text-xs text-slate-500">
          À chaque création / modification / suppression d'un <strong>Rapport</strong> ou <strong>Suivi</strong>,
          une requête <strong>POST</strong> est envoyée à
          <code className="text-sawali-blue mx-1">{"{URL}/{action}/{kind}/{note_id}"}</code>.
          <br />Actions : <code>created</code>, <code>updated</code>, <code>deleted</code>. Kind : <code>reports</code> ou <code>suivis</code>.
          Le corps JSON contient la note complète + l'auteur (id, email, rôle).
        </p>
        <Toggle label="Activer le webhook Notes" value={!!s.notes_webhook_enabled} onChange={(v) => upd("notes_webhook_enabled", v)} testid="toggle-notes-webhook" />
        <Input label="URL de base" value={s.notes_webhook_url || ""} onChange={(v) => upd("notes_webhook_url", v)} placeholder="https://api.votre-service.com/sawali/notes" testid="notes-webhook-url" />
        <div>
          <label className="block text-xs font-semibold mb-1">Authentification</label>
          <select value={s.notes_webhook_auth_type || "none"} onChange={(e) => upd("notes_webhook_auth_type", e.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="notes-webhook-auth-type">
            <option value="none">Aucune</option>
            <option value="bearer">Bearer Token</option>
            <option value="basic">Basic Auth</option>
          </select>
        </div>
        {s.notes_webhook_auth_type === "bearer" && (
          <Input label="Token Bearer" type="password" value={s.notes_webhook_token || ""} onChange={(v) => upd("notes_webhook_token", v)} placeholder={s.notes_webhook_token === "********" ? "(défini)" : ""} testid="notes-webhook-token" />
        )}
        {s.notes_webhook_auth_type === "basic" && (
          <div className="grid sm:grid-cols-2 gap-3">
            <Input label="Utilisateur" value={s.notes_webhook_basic_user || ""} onChange={(v) => upd("notes_webhook_basic_user", v)} testid="notes-webhook-basic-user" />
            <Input label="Mot de passe" type="password" value={s.notes_webhook_basic_pass || ""} onChange={(v) => upd("notes_webhook_basic_pass", v)} placeholder={s.notes_webhook_basic_pass === "********" ? "(défini)" : ""} testid="notes-webhook-basic-pass" />
          </div>
        )}
      </Section>

      <div className="mt-6 ring-1 ring-amber-200 bg-amber-50 rounded-lg p-3 text-xs text-amber-800 max-w-3xl" data-testid="settings-save-hint">
        💡 <strong>Astuce</strong> : les sections <strong>S057 (Habillage)</strong>, <strong>S058 (VIDAL)</strong> et <strong>S059 (Synthèse / Officines / Image sidebar)</strong> ont chacune leur propre bouton « Enregistrer » de couleur (fuchsia / rose / violet). Le bouton bleu ci-dessous ne sauvegarde QUE les paramètres généraux.
      </div>

      <button onClick={save} disabled={loading} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-5 py-2.5 text-sm font-medium hover:bg-sawali-blue-light disabled:opacity-50" data-testid="save-settings-btn">
        <Save className="h-4 w-4" /> {loading ? "Enregistrement..." : "Enregistrer les paramètres généraux"}
      </button>
    </div>
    </SettingsFilterCtx.Provider>
  );
}

const ClientsConsistencySection = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/clients-consistency");
      setData(r.data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const realign = async (email) => {
    if (!window.confirm(`Réaligner ${email} sur le client canonique de son entreprise ?`)) return;
    setBusy(email);
    try {
      const r = await apiClient.post("/admin/realign-user-to-client", { email });
      toast.success(`${r.data.actions?.length || 0} action(s) appliquée(s) pour ${email}.`);
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setBusy(null); }
  };

  const total = data?.misaligned_users_total ?? 0;
  const TITLE = "Cohérence multi-utilisateurs (panoramique)";

  return (
    <Filterable title={TITLE} anchorId={`s-${slugify(TITLE)}`}>
    <div className="rounded-xl border-2 border-violet-200 bg-violet-50/40 p-6 space-y-3" data-testid="admin-clients-consistency-section">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Wrench className="h-4 w-4 text-violet-600" />
          <h2 className="font-display font-semibold">
            Cohérence multi-utilisateurs (panoramique)
            {data && total === 0 && <CheckCircle2 className="inline h-4 w-4 text-emerald-600 ml-2" />}
            {total > 0 && <AlertCircle className="inline h-4 w-4 text-rose-600 ml-2 animate-pulse" />}
          </h2>
        </div>
        <button onClick={load} disabled={loading} className="text-xs inline-flex items-center gap-1 text-slate-500 hover:text-slate-900" data-testid="cc-refresh-btn">
          <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} /> Actualiser
        </button>
      </div>
      <p className="text-xs text-slate-600">
        Vue panoramique de toutes les entreprises (groupées par <code className="font-mono">company</code>) ayant plusieurs utilisateurs.
        Identifie celles dont les membres ne partagent pas le même <code className="font-mono">client_id</code> canonique (admin/superviseur, ou client_id majoritaire).
        Cliquez « Réaligner » à côté d'un utilisateur pour appliquer la correction proposée par le diagnostic ciblé.
      </p>

      {!data ? (
        <p className="text-xs text-slate-400 italic">Chargement…</p>
      ) : total === 0 ? (
        <div className="rounded-lg ring-1 ring-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-900 inline-flex items-center gap-2" data-testid="cc-status-clean">
          <CheckCircle2 className="h-4 w-4" />
          <span><strong>Toutes les entreprises sont cohérentes</strong> — {data.scanned_groups} entreprise(s) scannée(s), {data.aligned_groups} alignée(s).</span>
        </div>
      ) : (
        <div className="space-y-3" data-testid="cc-status-found">
          <div className="rounded-lg ring-1 ring-rose-200 bg-rose-50 p-3 text-xs text-rose-900 flex items-center justify-between gap-3">
            <span><strong>⚠️ {total} utilisateur(s) désaligné(s)</strong> sur {data.misaligned_groups} entreprise(s) (sur {data.scanned_groups} scannées).</span>
            <button
              onClick={async () => {
                if (!window.confirm(`Réaligner ${total} utilisateur(s) désaligné(s) ? Cette opération applique le diagnostic à chaque utilisateur en lot et peut prendre quelques secondes.`)) return;
                try {
                  const r = await apiClient.post("/admin/clients-consistency/realign-all", { confirm: true });
                  const done = r.data?.users_realigned ?? 0;
                  toast.success(`✅ ${done} utilisateur(s) réaligné(s) en lot`);
                  load();
                } catch (e) {
                  toast.error(e?.response?.data?.detail || "Erreur lors du réalignement en lot");
                }
              }}
              className="shrink-0 inline-flex items-center gap-1.5 rounded-lg bg-rose-600 hover:bg-rose-700 text-white px-3 py-1.5 text-[11px] font-medium shadow-sm"
              data-testid="cc-realign-all"
            >
              <Wrench className="h-3.5 w-3.5" /> Tout réaligner
            </button>
          </div>
          <div className="space-y-2">
            {data.groups.map((g) => (
              <div key={g.company} className="rounded-lg ring-1 ring-rose-200 bg-white p-3" data-testid={`cc-group-${g.company}`}>
                <div className="flex items-center justify-between mb-1.5">
                  <h4 className="font-semibold text-sm">{g.company} <span className="text-slate-400 text-[10px] font-normal">— {g.misaligned_count}/{g.members_total} désaligné(s)</span></h4>
                  <span className="text-[10px] text-slate-500 font-mono">canonique : {String(g.canonical_client_id || "—").slice(0, 12)}… <span className="text-slate-400">({g.canonical_via || "?"})</span></span>
                </div>
                <ul className="divide-y divide-slate-100">
                  {g.misaligned.map((m) => (
                    <li key={m.id} className="py-1.5 flex items-center justify-between gap-2 text-xs">
                      <div className="min-w-0">
                        <div className="truncate"><strong>{m.full_name || m.email}</strong> <span className="text-slate-400 text-[10px]">({m.role})</span></div>
                        <div className="text-[10px] text-slate-500 font-mono truncate">
                          scope effectif : <span className="text-rose-700">{String(m.effective_scope).slice(0, 12)}…</span>
                        </div>
                      </div>
                      <button
                        onClick={() => realign(m.email)}
                        disabled={busy === m.email || !m.email}
                        className="shrink-0 inline-flex items-center gap-1 rounded bg-rose-600 hover:bg-rose-700 text-white px-2 py-1 text-[11px] disabled:opacity-50"
                        data-testid={`cc-realign-${m.email || m.id}`}
                      >
                        {busy === m.email ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Database className="h-3 w-3" />}
                        Réaligner
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
    </Filterable>
  );
};


const ClientDataDiagnosticSection = () => {
  const [email, setEmail] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);

  const inspect = async () => {
    if (!email.trim()) { toast.error("Email requis"); return; }
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/client-data-diagnostic", { params: { email: email.trim() } });
      setData(r.data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
      setData(null);
    } finally { setLoading(false); }
  };

  const apply = async () => {
    if (!data?.realign_plan?.needed) return;
    if (!window.confirm(`Réaligner les données de ${data.user.email} vers le client canonique ${data.canonical.client_id?.slice(0, 8)}… ? Cette action retague les rows et conserve l'ancien client_id dans client_id_legacy.`)) return;
    setApplying(true);
    try {
      const r = await apiClient.post("/admin/realign-user-to-client", { email: data.user.email, dry_run: false });
      toast.success(`Réalignement appliqué : ${r.data.actions?.length || 0} action(s).`);
      setData(r.data.diagnostic_after || null);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setApplying(false); }
  };

  const u = data?.user;
  const can = data?.canonical;
  const plan = data?.realign_plan;
  const TITLE = "Diagnostic visibilité par utilisateur";

  return (
    <Filterable title={TITLE} anchorId={`s-${slugify(TITLE)}`}>
    <div className="rounded-xl border-2 border-sky-200 bg-sky-50/40 p-6 space-y-3" data-testid="admin-client-data-diagnostic-section">
      <div className="flex items-center gap-2">
        <Wrench className="h-4 w-4 text-sky-600" />
        <h2 className="font-display font-semibold">Diagnostic visibilité par utilisateur</h2>
      </div>
      <p className="text-xs text-slate-600">
        Si deux utilisateurs d'un même client ne voient pas les mêmes contacts/messages, entrez l'email du moins privilégié.
        L'outil trace son <code className="font-mono">client_id</code>, identifie le client canonique de son entreprise (via <code className="font-mono">parent_client_id</code> ou via le nom de société),
        liste ses pairs et indique précisément ce qu'il faut retaguer pour aligner sa visibilité.
      </p>

      <div className="flex gap-2">
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && inspect()}
          placeholder="user@exemple.com"
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
          data-testid="cdd-email-input"
        />
        <button
          onClick={inspect}
          disabled={loading || !email.trim()}
          className="inline-flex items-center gap-1 rounded-lg bg-sky-600 hover:bg-sky-700 text-white px-3 py-2 text-sm font-semibold disabled:opacity-50"
          data-testid="cdd-inspect-btn"
        >
          {loading ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Activity className="h-4 w-4" />}
          Diagnostiquer
        </button>
      </div>

      {data && u && (
        <div className="space-y-3 mt-2">
          <div className="rounded-lg ring-1 ring-slate-200 bg-white p-3 text-xs space-y-1" data-testid="cdd-user-block">
            <div><strong>{u.full_name || u.email}</strong> <span className="text-slate-400">— {u.role}</span></div>
            <div className="font-mono text-[11px] text-slate-600 break-all">
              id: {u.id}<br />
              client_id: <span className={u.client_id ? "" : "text-rose-600"}>{u.client_id || "—"}</span><br />
              parent_client_id: {u.parent_client_id || "—"}<br />
              tracked_user_id: {u.tracked_user_id || "—"}<br />
              <strong>effective_scope (lit):</strong> {u.effective_scope}
            </div>
          </div>

          {data.parent_company_mismatch && (
            <div className="rounded-lg ring-2 ring-rose-300 bg-rose-50 p-3 text-xs" data-testid="cdd-parent-mismatch">
              <p className="font-semibold text-rose-900">⚠️ Pointeur parent périmé détecté</p>
              <p className="text-rose-800 mt-1">
                Le compte affiche <code className="font-mono bg-white px-1 rounded">company = "{u.company || "—"}"</code>{" "}
                mais son <code className="font-mono bg-white px-1 rounded">parent_client_id</code> pointe encore vers le
                client <code className="font-mono bg-white px-1 rounded">"{data.parent_company_observed || "?"}"</code>.
              </p>
              <p className="text-rose-800 mt-1">
                {can?.client_id
                  ? "→ Le réalignement va recâbler le parent vers le client canonique de la société typée et retaguer les rows associées."
                  : "→ Impossible de résoudre automatiquement un client canonique pour cette société (aucun admin/superviseur ne porte exactement ce nom). Corrigez l'orthographe de la société, ou définissez un client primaire pour cette société, puis relancez le diagnostic."}
              </p>
            </div>
          )}

          {can && can.client_id ? (
            <div className="rounded-lg ring-1 ring-emerald-200 bg-emerald-50 p-3 text-xs">
              <p><strong>Client canonique résolu</strong> via <em>{can.source}</em> :</p>
              <p className="font-mono mt-1">{can.client_id}{can.user && ` (${can.user.email})`}</p>
            </div>
          ) : (
            <div className="rounded-lg ring-1 ring-amber-200 bg-amber-50 p-3 text-xs">
              <strong>⚠️ Aucun client canonique trouvé.</strong> L'utilisateur n'a ni <code className="font-mono">parent_client_id</code> ni admin/superviseur partageant son nom de société. Ajustez d'abord son <code className="font-mono">parent_client_id</code> ou son <code className="font-mono">company</code>.
            </div>
          )}

          {data.peers?.length > 0 && (
            <div className="rounded-lg ring-1 ring-slate-200 bg-white text-xs overflow-hidden">
              <div className="px-3 py-2 bg-slate-50 font-semibold uppercase tracking-wider text-[10px]">Pairs ({data.peers.length})</div>
              <ul className="divide-y divide-slate-100 max-h-44 overflow-y-auto">
                {data.peers.map((p) => (
                  <li key={p.id} className="px-3 py-1.5 flex items-center justify-between gap-2">
                    <span className="truncate">
                      <strong>{p.full_name || p.email}</strong>
                      <span className="text-slate-400 text-[10px]"> ({p.role})</span>
                    </span>
                    <span className="text-[10px] font-mono shrink-0">
                      <span className={p.scope_matches_canonical ? "text-emerald-700" : "text-rose-700 font-bold"}>
                        {p.scope_matches_canonical ? "✓" : "✗"}
                      </span>{" "}
                      {p.visible_contacts} contacts
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {plan?.needed ? (
            <div className="space-y-2" data-testid="cdd-plan-block">
              <div className="rounded-lg ring-1 ring-rose-200 bg-rose-50 p-3 text-xs space-y-1">
                <p className="font-semibold">⚠️ {plan.actions.length} action(s) requise(s) pour aligner cet utilisateur :</p>
                {plan.actions.map((a, i) => (
                  <div key={i} className="font-mono text-[11px] bg-white px-2 py-1 rounded ring-1 ring-rose-200">
                    {a.type === "set_user_client_id" && (
                      <>users.client_id : <span className="text-rose-600">{a.from || "null"}</span> → <span className="text-emerald-700">{String(a.to).slice(0, 8)}…</span></>
                    )}
                    {a.type === "relink_parent" && (
                      <>users.parent_client_id : <span className="text-rose-600">{String(a.from_parent || "null").slice(0, 8)}…</span> → <span className="text-emerald-700">{String(a.to_parent).slice(0, 8)}…</span> <span className="text-slate-500">(+ mirror client_id)</span></>
                    )}
                    {a.type === "retag_rows" && (
                      <>{a.collection} : retag <strong>{a.count}</strong> row(s) <span className="text-rose-600">{String(a.from).slice(0, 8)}…</span> → <span className="text-emerald-700">{String(a.to).slice(0, 8)}…</span></>
                    )}
                  </div>
                ))}
              </div>
              <button
                onClick={apply}
                disabled={applying}
                className="inline-flex items-center gap-2 rounded-lg bg-rose-600 hover:bg-rose-700 text-white px-4 py-2 text-sm font-semibold disabled:opacity-50"
                data-testid="cdd-apply-btn"
              >
                <Database className="h-4 w-4" />
                {applying ? "Application…" : "Appliquer le réalignement"}
              </button>
            </div>
          ) : (
            <div className="rounded-lg ring-1 ring-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-900 inline-flex items-center gap-2" data-testid="cdd-aligned">
              <CheckCircle2 className="h-4 w-4" /> <strong>Cet utilisateur est correctement aligné</strong> sur son client canonique.
            </div>
          )}
        </div>
      )}
    </div>
    </Filterable>
  );
};


// ============================================================
// iter34o — Recovery panel for the over-broad retag bug.
// Lets the admin run a dry-run first (count rows per collection),
// optionally scope by from/to client_id, and then apply the revert.
// ============================================================
const RevertRetagSection = () => {
  const TITLE = "Restauration des contacts/messages (revert retag)";
  const COLLECTIONS = [
    { id: "directory_contacts", label: "Contacts" },
    { id: "whatsapp_messages", label: "Messages WhatsApp" },
    { id: "sms_messages", label: "Messages SMS" },
    { id: "whatsapp_schedules", label: "Programmations WhatsApp" },
    { id: "payment_links", label: "Liens de paiement" },
  ];
  const [selected, setSelected] = useState(COLLECTIONS.map((c) => c.id));
  const [fromCid, setFromCid] = useState("");
  const [toCid, setToCid] = useState("");
  const [preview, setPreview] = useState(null);  // dry-run result
  const [busy, setBusy] = useState(false);

  const toggle = (id) => setSelected((s) => s.includes(id) ? s.filter((x) => x !== id) : [...s, id]);

  const run = async (dry_run) => {
    setBusy(true);
    try {
      const body = { dry_run, collections: selected };
      if (fromCid.trim()) body.from_client_id = fromCid.trim();
      if (toCid.trim()) body.to_client_id = toCid.trim();
      const r = await apiClient.post("/admin/contacts/revert-retag", body);
      setPreview(r.data);
      if (!dry_run) {
        const mods = (r.data.results || []).reduce((acc, x) => acc + (x.modified_count || 0), 0);
        toast.success(`Restauration appliquée : ${mods} ligne(s) modifiée(s).`);
      } else {
        toast.success(`Aperçu : ${r.data.total_rows || 0} ligne(s) éligible(s).`);
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setBusy(false); }
  };

  const apply = async () => {
    if (!preview) { toast.error("Lancez d'abord l'aperçu (dry-run)."); return; }
    const total = preview.total_rows || 0;
    if (total === 0) { toast.info("Rien à restaurer."); return; }
    if (!window.confirm(`Restaurer ${total} ligne(s) vers leur client_id d'origine ? Cette opération est idempotente — les lignes déjà restaurées seront ignorées.`)) return;
    run(false);
  };

  return (
    <Filterable title={TITLE} anchorId={`s-${slugify(TITLE)}`}>
    <div className="rounded-xl border-2 border-amber-300 bg-amber-50/40 p-6 space-y-3" data-testid="admin-revert-retag-section">
      <div className="flex items-center gap-2">
        <RotateCcw className="h-4 w-4 text-amber-700" />
        <h2 className="font-display font-semibold">{TITLE}</h2>
      </div>
      <p className="text-xs text-slate-700">
        Avant iter34o, le réalignement d'un utilisateur (ex : rabo.f) retaguait <strong>toutes</strong> les rows de la société source vers la cible — ce qui déplaçait les contacts des autres clients par erreur.
        Les valeurs d'origine sont conservées dans <code className="font-mono bg-white px-1 rounded text-[10px]">client_id_legacy</code>.
        Cette fonction restaure ces rows à leur état d'avant le retag. Idempotente — vous pouvez la relancer sans risque.
      </p>

      <div className="grid sm:grid-cols-2 gap-2">
        {COLLECTIONS.map((c) => (
          <label key={c.id} className="inline-flex items-center gap-2 text-xs text-slate-700 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={selected.includes(c.id)}
              onChange={() => toggle(c.id)}
              data-testid={`revert-coll-${c.id}`}
            />
            {c.label} <span className="text-slate-400 font-mono text-[10px]">({c.id})</span>
          </label>
        ))}
      </div>

      <div className="grid sm:grid-cols-2 gap-3">
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">Limite à un client_id d'origine (optionnel)</label>
          <input
            value={fromCid}
            onChange={(e) => setFromCid(e.target.value)}
            placeholder="ex: CMCO_id"
            className="w-full rounded border border-slate-300 px-2 py-1.5 text-xs font-mono"
            data-testid="revert-from-cid"
          />
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">Limite à un client_id cible (optionnel)</label>
          <input
            value={toCid}
            onChange={(e) => setToCid(e.target.value)}
            placeholder="ex: SAWALI_admin_id"
            className="w-full rounded border border-slate-300 px-2 py-1.5 text-xs font-mono"
            data-testid="revert-to-cid"
          />
        </div>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={() => run(true)}
          disabled={busy || selected.length === 0}
          className="inline-flex items-center gap-1.5 rounded-lg ring-1 ring-amber-400 bg-white hover:bg-amber-50 px-3 py-1.5 text-xs font-semibold text-amber-900 disabled:opacity-50"
          data-testid="revert-preview-btn"
        >
          {busy ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Search className="h-3 w-3" />}
          Aperçu (dry-run)
        </button>
        <button
          onClick={apply}
          disabled={busy || !preview || (preview?.total_rows || 0) === 0}
          className="inline-flex items-center gap-1.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
          data-testid="revert-apply-btn"
        >
          <Database className="h-3 w-3" /> Appliquer la restauration
        </button>
      </div>

      {preview && (
        <div className="rounded-lg ring-1 ring-amber-200 bg-white p-3 text-xs space-y-1" data-testid="revert-preview-block">
          <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">
            {preview.dry_run ? "Aperçu — aucune écriture effectuée" : "Résultat appliqué"} — Total : <strong>{preview.total_rows || 0}</strong> ligne(s)
          </p>
          <ul className="divide-y divide-slate-100">
            {(preview.results || []).map((r) => (
              <li key={r.collection} className="flex items-center justify-between py-1 font-mono text-[11px]">
                <span>{r.collection}</span>
                <span>
                  {r.count} éligible(s)
                  {r.modified_count != null && <span className="text-emerald-700 font-semibold"> · {r.modified_count} restauré(s)</span>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
    </Filterable>
  );
};


// ============================================================
// Iter37f — Recalibrage des tenants Caisse/Facturation
// ============================================================
// =====================================================================
// Iter38b — Country & dial-prefix section (tenant default + catalog CRUD)
// =====================================================================
const CountryPrefixSection = () => {
  const TITLE = "Pays & indicatifs téléphoniques";
  const [meta, setMeta] = useState(null);
  const [countries, setCountries] = useState([]);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ code: "", name: "", dial: "+", example: "" });

  const load = useCallback(async () => {
    try {
      const [m, c] = await Promise.all([
        apiClient.get("/admin/tenant-country"),
        apiClient.get("/admin/countries"),
      ]);
      setMeta(m.data);
      setCountries(c.data || []);
    } catch (err) {
      toast.error("Impossible de charger les pays");
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const selectCountry = async (code) => {
    setBusy(true);
    try {
      const r = await apiClient.patch("/admin/tenant-country", { country_code: code });
      setMeta(r.data);
      try {
        localStorage.setItem("sawali_tenant_meta", JSON.stringify(r.data));
      } catch { /* noop */ }
      toast.success(`Pays par défaut: ${r.data.country_name} (${r.data.dial_prefix})`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setBusy(false); }
  };

  const addCountry = async () => {
    if (!form.code || !form.name || !form.dial) { toast.error("Code, nom et indicatif requis"); return; }
    try {
      await apiClient.post("/admin/countries", form);
      toast.success("Pays ajouté");
      setForm({ code: "", name: "", dial: "+", example: "" });
      setEditing(false);
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const removeCountry = async (code) => {
    if (!window.confirm(`Supprimer le pays ${code} de la liste ?`)) return;
    try {
      await apiClient.delete(`/admin/countries/${code}`);
      toast.success("Pays supprimé");
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  return (
    <Filterable title={TITLE} anchorId={`s-${slugify(TITLE)}`}>
    <div className="rounded-xl border-2 border-emerald-300 bg-emerald-50/40 p-6 space-y-4" data-testid="admin-country-section">
      <div className="flex items-center gap-2">
        <Globe className="h-4 w-4 text-emerald-700" />
        <h2 className="font-display font-semibold">{TITLE}</h2>
      </div>
      <p className="text-sm text-slate-600">
        Sélectionnez le <strong>pays par défaut</strong> de votre tenant. L'indicatif (ex: <code>+226</code>)
        sera utilisé automatiquement dans les exemples de champs téléphone partout dans l'application.
      </p>

      {meta && (
        <div className="bg-white border border-emerald-200 rounded-lg p-3" data-testid="admin-country-current">
          <span className="text-xs text-slate-500">Sélection actuelle :</span>
          <div className="flex items-center gap-3 mt-1">
            <span className="font-medium text-slate-900">{meta.country_name}</span>
            <span className="px-2 py-0.5 bg-emerald-100 text-emerald-700 rounded text-sm font-mono">{meta.dial_prefix}</span>
            <span className="text-xs text-slate-400">Exemple: <span className="font-mono">{meta.phone_example}</span></span>
          </div>
        </div>
      )}

      <div>
        <label className="text-xs text-slate-500 mb-1 block">Changer le pays par défaut</label>
        <select
          value={meta?.country_code || "BF"}
          onChange={(e) => selectCountry(e.target.value)}
          disabled={busy}
          data-testid="admin-country-select"
          className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm bg-white"
        >
          {countries.map((c) => (
            <option key={c.code} value={c.code}>
              {c.name} ({c.dial}) — {c.code}
            </option>
          ))}
        </select>
      </div>

      <div className="border-t border-emerald-200 pt-3">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold text-slate-700">Liste des pays disponibles ({countries.length})</h3>
          <button onClick={() => setEditing(!editing)} data-testid="admin-country-add-toggle"
            className="text-xs px-2 py-1 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded">
            {editing ? "Annuler" : "+ Ajouter un pays"}
          </button>
        </div>
        {editing && (
          <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 mb-3" data-testid="admin-country-add-form">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              <input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })}
                placeholder="Code ISO (ex: GH)" maxLength={4}
                data-testid="admin-country-add-code"
                className="px-2 py-1.5 border border-slate-200 rounded text-sm" />
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Nom (ex: Ghana)"
                data-testid="admin-country-add-name"
                className="px-2 py-1.5 border border-slate-200 rounded text-sm" />
              <input value={form.dial} onChange={(e) => setForm({ ...form, dial: e.target.value })}
                placeholder="+233"
                data-testid="admin-country-add-dial"
                className="px-2 py-1.5 border border-slate-200 rounded text-sm font-mono" />
              <input value={form.example} onChange={(e) => setForm({ ...form, example: e.target.value })}
                placeholder="+233500000000 (optionnel)"
                data-testid="admin-country-add-example"
                className="px-2 py-1.5 border border-slate-200 rounded text-sm font-mono" />
            </div>
            <button onClick={addCountry} data-testid="admin-country-add-submit"
              className="mt-2 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white text-sm rounded">
              Ajouter
            </button>
          </div>
        )}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-1 max-h-64 overflow-y-auto" data-testid="admin-country-list">
          {countries.map((c) => (
            <div key={c.code} className="flex items-center justify-between px-2 py-1.5 bg-white border border-slate-100 rounded text-sm">
              <div className="flex items-center gap-2">
                <span className="font-medium">{c.name}</span>
                <span className="text-slate-500 text-xs font-mono">{c.dial}</span>
              </div>
              {c.code !== "BF" && (
                <button onClick={() => removeCountry(c.code)} data-testid={`admin-country-delete-${c.code}`}
                  className="text-rose-500 hover:text-rose-700">
                  <Trash2 size={12} />
                </button>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
    </Filterable>
  );
};


const CashierTenantBackfillSection = () => {
  const TITLE = "Recalibrage des tenants Caisse/Facturation";
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [rewrite, setRewrite] = useState(true);

  const run = async () => {
    if (!window.confirm(
      `Recalculer le tenant de tous les reçus / factures / clients en compte / produits / modes de paiement / dropdowns ?\n\n` +
      `${rewrite ? "Mode REWRITE : remplace tous les tenant_id existants (consolide les utilisateurs partageant la même société)." : "Mode INCRÉMENTAL : ne touche que les docs sans tenant_id."}\n\n` +
      `Opération idempotente — relançable sans risque.`
    )) return;
    setBusy(true);
    try {
      const r = await apiClient.post("/admin/cashier/backfill-tenants", { rewrite });
      setResult(r.data);
      const total = Object.values(r.data?.rows_updated || {}).reduce((a, b) => a + b, 0);
      toast.success(`Recalibrage terminé : ${total} document(s) mis à jour.`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur lors du recalibrage");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Filterable title={TITLE} anchorId={`s-${slugify(TITLE)}`}>
    <div className="rounded-xl border-2 border-fuchsia-300 bg-fuchsia-50/40 p-6 space-y-3" data-testid="admin-cashier-backfill-section">
      <div className="flex items-center gap-2">
        <Database className="h-4 w-4 text-fuchsia-700" />
        <h2 className="font-display font-semibold">{TITLE}</h2>
      </div>
      <p className="text-xs text-slate-700">
        À utiliser <strong>après chaque redéploiement</strong> ou quand vous remarquez que deux utilisateurs de la même société (ex : <code className="font-mono bg-white px-1 rounded text-[10px]">support@…</code> et <code className="font-mono bg-white px-1 rounded text-[10px]">rabo.f@…</code>) ne voient pas la même liste de clients en compte / catalogue.
        Cette opération recalcule le <code className="font-mono bg-white px-1 rounded text-[10px]">tenant_id</code> de chaque document Caisse en consolidant les utilisateurs partageant le même champ <strong>Société</strong>.
      </p>
      <label className="inline-flex items-center gap-2 text-xs text-slate-700 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={rewrite}
          onChange={(e) => setRewrite(e.target.checked)}
          data-testid="backfill-rewrite-toggle"
        />
        <strong>Mode REWRITE</strong> — Recalculer tous les <code className="font-mono text-[10px]">tenant_id</code> existants (recommandé pour consolider).
      </label>
      <button
        onClick={run}
        disabled={busy}
        className="inline-flex items-center gap-1.5 rounded-lg bg-fuchsia-600 hover:bg-fuchsia-700 text-white px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
        data-testid="cashier-backfill-run-btn"
      >
        {busy ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Database className="h-3 w-3" />}
        {busy ? "Recalibrage en cours…" : "Lancer le recalibrage"}
      </button>
      {result && (
        <div className="rounded-lg ring-1 ring-fuchsia-200 bg-white p-3 text-xs space-y-2" data-testid="cashier-backfill-result">
          <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">
            Résultat — Total : <strong>{Object.values(result.rows_updated || {}).reduce((a, b) => a + b, 0)}</strong> document(s) mis à jour
          </p>
          <ul className="divide-y divide-slate-100">
            {Object.entries(result.rows_updated || {}).map(([k, v]) => (
              <li key={k} className="flex items-center justify-between py-1">
                <span className="font-mono text-slate-700">{k}</span>
                <span className={`font-bold tabular-nums ${v > 0 ? "text-fuchsia-700" : "text-slate-400"}`}>{v}</span>
              </li>
            ))}
          </ul>
          {Array.isArray(result.canonical_users_sample) && result.canonical_users_sample.length > 0 && (
            <details className="text-[11px] text-slate-600">
              <summary className="cursor-pointer text-fuchsia-700 font-semibold">Voir les utilisateurs canoniques détectés ({result.canonical_users_sample.length})</summary>
              <ul className="mt-2 space-y-0.5 font-mono">
                {result.canonical_users_sample.map((u) => (
                  <li key={u.id}>
                    <span className="text-slate-500">{u.role}</span> · <strong>{u.company || "—"}</strong> · {u.email}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
    </Filterable>
  );
};






// ============================================================
// iter34l — Demandes de modification de profil envoyées par les
// utilisateurs depuis leur page "Mon compte". Admin peut filtrer
// (pending/processed/all), saisir une note interne et marquer
// la demande comme traitée. Le compteur "admin_profile_requests"
// du sidebar se met à jour automatiquement.
// ============================================================
const FIELD_LABELS = {
  full_name: "Identité (nom & prénom)",
  birth_date: "Date de naissance",
  phone: "Numéro de téléphone",
  whatsapp: "Numéro WhatsApp",
  email: "Adresse email",
  company: "Société / entreprise",
};
const ProfileRequestsSection = () => {
  const TITLE = "Demandes de modification de profil (utilisateurs)";
  const [data, setData] = useState({ items: [], pending_count: 0 });
  const [filter, setFilter] = useState("pending");  // pending | processed | all
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState({});  // {id: true}
  const [drafts, setDrafts] = useState({});  // {id: noteString}
  const [savingId, setSavingId] = useState(null);

  const load = async (f = filter) => {
    setLoading(true);
    try {
      const r = await apiClient.get(`/admin/profile-requests?status=${encodeURIComponent(f)}`);
      setData(r.data || { items: [], pending_count: 0 });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setLoading(false); }
  };
  useEffect(() => { load(filter); /* eslint-disable-next-line */ }, [filter]);

  const onToggle = (id) => setExpanded((e) => ({ ...e, [id]: !e[id] }));

  const updateOne = async (id, payload, successMsg) => {
    setSavingId(id);
    try {
      await apiClient.patch(`/admin/profile-requests/${id}`, payload);
      toast.success(successMsg || "Mis à jour");
      await load(filter);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setSavingId(null); }
  };

  const markProcessed = (it) => {
    const note = drafts[it.id] ?? it.admin_note ?? "";
    updateOne(it.id, { status: "processed", admin_note: note }, "Demande marquée comme traitée");
  };
  const reopen = (it) => updateOne(it.id, { status: "pending" }, "Demande remise en attente");
  const saveNoteOnly = (it) => {
    const note = drafts[it.id] ?? it.admin_note ?? "";
    updateOne(it.id, { admin_note: note }, "Note enregistrée");
  };

  const fmt = (iso) => {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" });
    } catch { return iso; }
  };

  const items = data.items || [];
  const pendingCount = data.pending_count || 0;

  return (
    <Filterable title={TITLE} anchorId={`s-${slugify(TITLE)}`}>
    <div className="rounded-xl border-2 border-rose-200 bg-rose-50/30 p-6 space-y-4" data-testid="admin-profile-requests-section">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <UserCog className="h-4 w-4 text-rose-600" />
          <h2 className="font-display font-semibold">{TITLE}</h2>
          {pendingCount > 0 && (
            <span
              className="inline-flex items-center gap-1 rounded-full bg-rose-600 text-white px-2 py-0.5 text-[10px] font-bold tabular-nums animate-pulse"
              data-testid="profile-requests-pending-badge"
              title={`${pendingCount} demande(s) en attente de traitement`}
            >
              {pendingCount} en attente
            </span>
          )}
        </div>
        <div className="inline-flex rounded-lg ring-1 ring-rose-200 bg-white overflow-hidden text-xs">
          {[
            { id: "pending", label: "En attente" },
            { id: "processed", label: "Traitées" },
            { id: "all", label: "Toutes" },
          ].map((t) => (
            <button
              key={t.id}
              onClick={() => setFilter(t.id)}
              className={`px-3 py-1.5 font-semibold ${filter === t.id ? "bg-rose-600 text-white" : "text-slate-600 hover:bg-rose-50"}`}
              data-testid={`profile-requests-filter-${t.id}`}
            >
              {t.label}
            </button>
          ))}
          <button
            onClick={() => load(filter)}
            disabled={loading}
            className="px-2 py-1.5 text-slate-500 hover:bg-rose-50 border-l border-rose-100"
            title="Rafraîchir"
            data-testid="profile-requests-refresh"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      <p className="text-xs text-slate-600">
        Les utilisateurs peuvent envoyer ici une demande de correction (faute d'orthographe sur le nom, nouveau numéro, etc.)
        depuis leur page <strong>Mon compte</strong>. Traitez-la, notez ce qui a été modifié, puis cliquez sur
        « Marquer comme traitée » — le compteur du bandeau latéral se mettra à jour automatiquement.
      </p>

      {loading && !items.length && (
        <p className="text-center text-xs text-slate-400 py-6">Chargement…</p>
      )}

      {!loading && !items.length && (
        <p className="text-center text-xs text-slate-400 py-6 italic" data-testid="profile-requests-empty">
          {filter === "pending" ? "Aucune demande en attente — tout est à jour 🎉" : filter === "processed" ? "Aucune demande traitée pour le moment." : "Aucune demande pour le moment."}
        </p>
      )}

      <ul className="space-y-2">
        {items.map((it) => {
          const isOpen = !!expanded[it.id];
          const isProcessed = it.status === "processed";
          const noteDraft = drafts[it.id] ?? it.admin_note ?? "";
          return (
            <li
              key={it.id}
              className={`rounded-lg ring-1 ${isProcessed ? "ring-emerald-200 bg-emerald-50/40" : "ring-rose-200 bg-white"}`}
              data-testid={`profile-request-row-${it.id}`}
            >
              <button
                type="button"
                onClick={() => onToggle(it.id)}
                className="w-full flex items-start gap-3 p-3 text-left hover:bg-rose-50/40"
                data-testid={`profile-request-toggle-${it.id}`}
              >
                <span className={`mt-0.5 inline-flex items-center justify-center h-6 w-6 rounded-full text-white text-xs font-bold ${isProcessed ? "bg-emerald-600" : "bg-rose-600"}`}>
                  {isProcessed ? <Check className="h-3.5 w-3.5" /> : <Inbox className="h-3.5 w-3.5" />}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-slate-900 truncate">
                    {it.user_full_name || it.user_email || "Utilisateur inconnu"}
                    {it.company && <span className="text-slate-500 font-normal"> — {it.company}</span>}
                  </p>
                  <p className="text-[11px] text-slate-500 truncate font-mono">{it.user_email}</p>
                  <p className="text-xs text-slate-700 mt-1 line-clamp-2">{it.message}</p>
                  <div className="flex items-center gap-2 mt-1 flex-wrap">
                    <span className="text-[10px] text-slate-400">Reçue le {fmt(it.created_at)}</span>
                    {isProcessed && it.resolved_at && (
                      <span className="text-[10px] text-emerald-700 font-semibold">• Traitée le {fmt(it.resolved_at)}{it.resolved_by_email ? ` par ${it.resolved_by_email}` : ""}</span>
                    )}
                    {(it.fields || []).length > 0 && (
                      <span className="text-[10px] text-indigo-700">• {it.fields.length} champ(s) ciblé(s)</span>
                    )}
                  </div>
                </div>
                <ChevronDown className={`h-4 w-4 text-slate-400 transition-transform shrink-0 mt-1 ${isOpen ? "rotate-180" : ""}`} />
              </button>

              {isOpen && (
                <div className="border-t border-rose-100 p-3 space-y-3" data-testid={`profile-request-detail-${it.id}`}>
                  {(it.fields || []).length > 0 && (
                    <div>
                      <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">Champs concernés</p>
                      <div className="flex flex-wrap gap-1">
                        {(it.fields || []).map((f) => (
                          <span key={f} className="inline-block rounded-full bg-indigo-100 text-indigo-700 text-[10px] font-semibold px-2 py-0.5">
                            {FIELD_LABELS[f] || f}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  <div>
                    <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">Message complet de l'utilisateur</p>
                    <p className="text-sm text-slate-800 whitespace-pre-wrap rounded bg-slate-50 ring-1 ring-slate-200 p-2">{it.message}</p>
                  </div>
                  <div>
                    <label className="block text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1 flex items-center gap-1">
                      <MessageSquare className="h-3 w-3" /> Note interne (admin)
                    </label>
                    <textarea
                      rows={3}
                      value={noteDraft}
                      onChange={(e) => setDrafts((d) => ({ ...d, [it.id]: e.target.value }))}
                      placeholder="Ex: Nom corrigé en BDD le 11/05, prévenir l'utilisateur par WA."
                      maxLength={2000}
                      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm resize-y"
                      data-testid={`profile-request-note-${it.id}`}
                    />
                    <p className="text-[10px] text-slate-400 text-right mt-0.5">{noteDraft.length}/2000</p>
                  </div>
                  <div className="flex items-center gap-2 flex-wrap">
                    {!isProcessed ? (
                      <button
                        onClick={() => markProcessed(it)}
                        disabled={savingId === it.id}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
                        data-testid={`profile-request-mark-processed-${it.id}`}
                      >
                        <Check className="h-3.5 w-3.5" /> Marquer comme traitée
                      </button>
                    ) : (
                      <button
                        onClick={() => reopen(it)}
                        disabled={savingId === it.id}
                        className="inline-flex items-center gap-1.5 rounded-lg ring-1 ring-rose-300 text-rose-700 hover:bg-rose-50 px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
                        data-testid={`profile-request-reopen-${it.id}`}
                      >
                        <RotateCcw className="h-3.5 w-3.5" /> Rouvrir
                      </button>
                    )}
                    <button
                      onClick={() => saveNoteOnly(it)}
                      disabled={savingId === it.id || noteDraft === (it.admin_note || "")}
                      className="inline-flex items-center gap-1.5 rounded-lg ring-1 ring-slate-300 hover:bg-slate-50 px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
                      data-testid={`profile-request-save-note-${it.id}`}
                    >
                      <Save className="h-3.5 w-3.5" /> Enregistrer la note
                    </button>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
    </Filterable>
  );
};



// ============================================================
// iter34h — Roadmap tracker (historique des actions développées)
// ============================================================
const RoadmapTrackerSection = () => {
  const [data, setData] = useState({ items: [], totals: null });
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState("all");  // all | done | pending
  const [dateRange, setDateRange] = useState("today");  // today | 7d | 30d | 90d | all  (Iter38r-fix9o : défaut "Aujourd'hui")
  const [editing, setEditing] = useState(null);  // {code, observations}
  const [creating, setCreating] = useState(false);
  const [newForm, setNewForm] = useState({ title: "", backlog_ref: "", details: "", duration_h: 0 });
  const [view, setView] = useState("table");  // table | kanban
  const TITLE = "Suivi des actions (historique du travail)";

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/roadmap-actions");
      setData(r.data || { items: [], totals: null });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const saveObs = async () => {
    if (!editing) return;
    try {
      await apiClient.patch(`/admin/roadmap-actions/${editing.code}`, { observations: editing.observations });
      toast.success("Observation enregistrée");
      setEditing(null);
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const toggleDone = async (it) => {
    try {
      await apiClient.patch(`/admin/roadmap-actions/${it.code}`, { done: !it.done });
      toast.success(it.done ? "Action marquée À faire" : "Action marquée comme réalisée");
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const setStatus = async (it, newStatus) => {
    if ((it.status || (it.done ? "done" : "todo")) === newStatus) return;
    try {
      await apiClient.patch(`/admin/roadmap-actions/${it.code}`, { status: newStatus });
      const labels = { todo: "À faire", in_progress: "En cours", done: "Réalisée" };
      toast.success(`Action déplacée → ${labels[newStatus]}`);
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const removeAction = async (it) => {
    if (!window.confirm(`Supprimer définitivement ${it.code} — « ${it.title} » ?`)) return;
    try {
      await apiClient.delete(`/admin/roadmap-actions/${it.code}`);
      toast.success("Action supprimée");
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Suppression impossible (actions du seed historique protégées)");
    }
  };

  const createAction = async () => {
    if (!newForm.title.trim()) { toast.error("Le titre est obligatoire"); return; }
    try {
      await apiClient.post("/admin/roadmap-actions", {
        title: newForm.title.trim(),
        backlog_ref: newForm.backlog_ref.trim(),
        details: newForm.details.trim(),
        duration_h: parseFloat(newForm.duration_h) || 0,
      });
      toast.success("Action ajoutée au pipeline");
      setCreating(false);
      setNewForm({ title: "", backlog_ref: "", details: "", duration_h: 0 });
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const fmt = (iso) => {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" });
    } catch { return iso; }
  };

  const exportCsv = () => {
    // Build CSV from the currently-filtered rows. Excel-FR friendly: `;`
    // separator + UTF-8 BOM so accents render correctly when opened directly.
    const escape = (v) => {
      const s = (v ?? "").toString().replace(/"/g, '""');
      return /[";\n\r]/.test(s) ? `"${s}"` : s;
    };
    const headers = ["N°", "Créée le", "Réalisée le", "Action", "Référence backlog", "Détails", "Durée (h)", "Coût (XOF)", "État", "Observations"];
    const rows = items.map((it) => [
      it.code,
      it.created_at || "",
      it.done_at || "",
      it.title || "",
      it.backlog_ref || "",
      (it.details || "").replace(/\s+/g, " "),
      (it.duration_h || 0).toString().replace(".", ","),
      (it.cost_xof || 0).toString(),
      it.done ? "FAIT" : "À FAIRE",
      it.observations || "",
    ]);
    const csv = [headers, ...rows].map((r) => r.map(escape).join(";")).join("\r\n");
    const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8;" });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `suivi-actions-sawali-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => window.URL.revokeObjectURL(url), 1000);
    toast.success(`${rows.length} ligne(s) exportée(s)`);
  };

  const items = (data.items || []).filter((r) => {
    const status = r.status || (r.done ? "done" : "todo");
    if (filter === "done" && status !== "done") return false;
    if (filter === "in_progress" && status !== "in_progress") return false;
    if (filter === "pending" && status !== "todo") return false;
    if (dateRange !== "all") {
      const windowDays = { today: 1, "7d": 7, "30d": 30, "90d": 90 }[dateRange] || 0;
      if (windowDays > 0) {
        // Reference date: done_at if available, else created_at
        const ref = r.done_at || r.created_at;
        if (!ref) return false;
        const t = Date.parse(ref);
        if (Number.isNaN(t)) return false;
        const cutoff = Date.now() - windowDays * 24 * 3600 * 1000;
        if (t < cutoff) return false;
      }
    }
    return true;
  });
  const totals = data.totals || {};

  return (
    <Filterable title={TITLE} anchorId={`s-${slugify(TITLE)}`}>
    <div className="rounded-xl border-2 border-indigo-200 bg-indigo-50/30 p-6 space-y-4" data-testid="admin-roadmap-tracker-section">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <ClipboardList className="h-4 w-4 text-indigo-600" />
          <h2 className="font-display font-semibold">Suivi des actions (historique du travail)</h2>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setCreating((v) => !v)}
            className="text-xs inline-flex items-center gap-1 rounded bg-indigo-600 hover:bg-indigo-700 text-white px-2.5 py-1 font-semibold"
            data-testid="roadmap-new-btn"
          >
            <Sparkles className="h-3 w-3" /> {creating ? "Annuler" : "Nouvelle action"}
          </button>
          <button
            onClick={exportCsv}
            disabled={loading || items.length === 0}
            className="text-xs inline-flex items-center gap-1 rounded ring-1 ring-indigo-300 bg-white px-2 py-1 text-indigo-700 hover:bg-indigo-50 disabled:opacity-50"
            data-testid="roadmap-export-csv"
          >
            <Download className="h-3 w-3" /> Exporter CSV
          </button>
          <button
            onClick={load}
            disabled={loading}
            className="text-xs inline-flex items-center gap-1 text-slate-500 hover:text-slate-900 transition"
            data-testid="roadmap-refresh"
          >
            <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} /> Actualiser
          </button>
        </div>
      </div>
      <p className="text-xs text-slate-600">
        Liste auto-incrémentée des évolutions livrées avec date, durée et coût approximatifs. Seule la colonne <strong>Observations</strong> est modifiable depuis cette page — les autres colonnes sont alimentées automatiquement à chaque livraison.
      </p>

      {/* New-action inline form */}
      {creating && (
        <div className="rounded-lg ring-1 ring-indigo-300 bg-white p-3 space-y-2" data-testid="roadmap-new-form">
          <div className="grid sm:grid-cols-2 gap-2">
            <input
              autoFocus
              value={newForm.title}
              onChange={(e) => setNewForm({ ...newForm, title: e.target.value })}
              placeholder="Titre de l'action (obligatoire)"
              className="rounded border border-slate-300 px-2 py-1.5 text-xs"
              data-testid="roadmap-new-title"
            />
            <input
              value={newForm.backlog_ref}
              onChange={(e) => setNewForm({ ...newForm, backlog_ref: e.target.value })}
              placeholder="Référence backlog (ex: P1, User-request)"
              className="rounded border border-slate-300 px-2 py-1.5 text-xs"
              data-testid="roadmap-new-backlog"
            />
          </div>
          <textarea
            rows={2}
            value={newForm.details}
            onChange={(e) => setNewForm({ ...newForm, details: e.target.value })}
            placeholder="Détails / contexte (optionnel)"
            className="w-full rounded border border-slate-300 px-2 py-1.5 text-xs resize-y"
            data-testid="roadmap-new-details"
          />
          <div className="flex items-center gap-2 flex-wrap">
            <label className="text-xs text-slate-700 inline-flex items-center gap-1.5">
              Durée estimée (h) :
              <input
                type="number"
                step="0.25"
                min={0}
                value={newForm.duration_h}
                onChange={(e) => setNewForm({ ...newForm, duration_h: e.target.value })}
                className="w-20 rounded border border-slate-300 px-1.5 py-1 text-xs"
                data-testid="roadmap-new-duration"
              />
            </label>
            <span className="text-[10px] text-slate-500">≈ {(parseFloat(newForm.duration_h || 0) * 25000).toLocaleString("fr-FR")} XOF</span>
            <button
              onClick={createAction}
              className="ml-auto rounded bg-indigo-600 hover:bg-indigo-700 text-white px-3 py-1 text-xs font-semibold"
              data-testid="roadmap-new-save"
            >
              Ajouter au pipeline
            </button>
          </div>
        </div>
      )}

      {/* Totals strip */}
      {totals && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs" data-testid="roadmap-totals">
          <div className="rounded ring-1 ring-indigo-200 bg-white p-2">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">Total actions</div>
            <div className="font-bold text-slate-800">{totals.count || 0}</div>
          </div>
          <div className="rounded ring-1 ring-emerald-200 bg-white p-2">
            <div className="text-[10px] uppercase tracking-wider text-emerald-700">Réalisées</div>
            <div className="font-bold text-emerald-700">{totals.done || 0}</div>
          </div>
          <div className="rounded ring-1 ring-slate-200 bg-white p-2">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">Durée cumulée</div>
            <div className="font-bold text-slate-800">{(totals.duration_h || 0).toFixed(1)} h</div>
          </div>
          <div className="rounded ring-1 ring-amber-200 bg-white p-2">
            <div className="text-[10px] uppercase tracking-wider text-amber-700">Coût cumulé</div>
            <div className="font-bold text-amber-700">{(totals.cost_xof || 0).toLocaleString("fr-FR")} XOF</div>
          </div>
        </div>
      )}

      {/* View switcher + Filter */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="inline-flex rounded ring-1 ring-slate-200 bg-white p-0.5">
          {[["all", `Toutes (${totals.count || 0})`], ["done", `Réalisées (${totals.done || 0})`], ["in_progress", `En cours (${totals.in_progress || 0})`], ["pending", `À faire (${totals.pending || 0})`]].map(([v, l]) => (
            <button
              key={v}
              onClick={() => setFilter(v)}
              className={`px-3 py-1 text-[11px] rounded ${filter === v ? "bg-indigo-600 text-white" : "text-slate-600 hover:bg-slate-50"}`}
              data-testid={`roadmap-filter-${v}`}
            >
              {l}
            </button>
          ))}
        </div>
        <div className="inline-flex rounded ring-1 ring-emerald-200 bg-white p-0.5" data-testid="roadmap-date-range-filter" title="Filtrer par date de réalisation/création">
          {[
            ["today", "Aujourd'hui"],
            ["7d", "7 j"],
            ["30d", "30 j"],
            ["90d", "90 j"],
            ["all", "Toujours"],
          ].map(([v, l]) => (
            <button
              key={v}
              onClick={() => setDateRange(v)}
              className={`px-3 py-1 text-[11px] rounded ${dateRange === v ? "bg-emerald-600 text-white" : "text-slate-600 hover:bg-emerald-50"}`}
              data-testid={`roadmap-date-${v}`}
            >
              {l}
            </button>
          ))}
        </div>
        <div className="inline-flex rounded ring-1 ring-slate-200 bg-white p-0.5 ml-auto">
          {[["table", "Tableau"], ["kanban", "Kanban"]].map(([v, l]) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`px-3 py-1 text-[11px] rounded ${view === v ? "bg-slate-800 text-white" : "text-slate-600 hover:bg-slate-50"}`}
              data-testid={`roadmap-view-${v}`}
            >
              {l}
            </button>
          ))}
        </div>
      </div>

      {/* Table or Kanban */}
      {view === "table" ? (
      <div className="rounded-lg ring-1 ring-slate-200 bg-white overflow-x-auto" data-testid="roadmap-table">
        <table className="w-full text-xs min-w-[920px]">
          <thead className="bg-slate-50 text-[10px] uppercase tracking-wider text-slate-600">
            <tr>
              <th className="px-2 py-2 text-left">N°</th>
              <th className="px-2 py-2 text-left">Créée le</th>
              <th className="px-2 py-2 text-left">Action / Backlog</th>
              <th className="px-2 py-2 text-left">Réalisée le</th>
              <th className="px-2 py-2 text-right">Durée</th>
              <th className="px-2 py-2 text-right">Coût (XOF)</th>
              <th className="px-2 py-2 text-center">État</th>
              <th className="px-2 py-2 text-left">Observations (modifiable)</th>
              <th className="px-2 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr><td colSpan={9} className="px-3 py-6 text-center text-slate-400 italic">Aucune action pour ce filtre.</td></tr>
            ) : items.map((it) => (
              <tr key={it.code} className="border-t border-slate-100 hover:bg-slate-50/40" data-testid={`roadmap-row-${it.code}`}>
                <td className="px-2 py-1.5 font-mono font-semibold text-indigo-700">{it.code}</td>
                <td className="px-2 py-1.5 text-slate-500 whitespace-nowrap">{fmt(it.created_at)}</td>
                <td className="px-2 py-1.5">
                  <div className="font-semibold text-slate-800">{it.title}</div>
                  {it.backlog_ref && <div className="text-[10px] text-slate-500">{it.backlog_ref}</div>}
                  {it.details && <div className="text-[10px] text-slate-400 mt-0.5 max-w-[400px]">{it.details}</div>}
                </td>
                <td className="px-2 py-1.5 text-slate-500 whitespace-nowrap">{fmt(it.done_at)}</td>
                <td className="px-2 py-1.5 text-right font-mono text-slate-700">{(it.duration_h || 0).toFixed(2)} h</td>
                <td className="px-2 py-1.5 text-right font-mono text-slate-700">{(it.cost_xof || 0).toLocaleString("fr-FR")}</td>
                <td className="px-2 py-1.5 text-center">
                  <button
                    onClick={() => toggleDone(it)}
                    className={`rounded px-1.5 py-0.5 text-[9px] font-bold transition hover:scale-105 ${it.done ? "bg-emerald-100 text-emerald-700 hover:bg-emerald-200" : "bg-amber-100 text-amber-700 hover:bg-amber-200"}`}
                    title={it.done ? "Cliquer pour remettre 'À faire'" : "Cliquer pour marquer 'Réalisée'"}
                    data-testid={`roadmap-toggle-${it.code}`}
                  >
                    {it.done ? "✓ FAIT" : "À FAIRE"}
                  </button>
                </td>
                <td className="px-2 py-1.5 max-w-[280px]">
                  {editing?.code === it.code ? (
                    <div className="flex flex-col gap-1">
                      <textarea
                        autoFocus
                        rows={2}
                        value={editing.observations}
                        onChange={(e) => setEditing({ ...editing, observations: e.target.value })}
                        className="w-full rounded border border-slate-300 px-2 py-1 text-[11px] resize-y"
                        data-testid={`roadmap-obs-input-${it.code}`}
                      />
                      <div className="flex gap-1">
                        <button onClick={saveObs} className="text-[11px] text-emerald-700 font-semibold hover:underline" data-testid={`roadmap-obs-save-${it.code}`}>
                          Enregistrer
                        </button>
                        <button onClick={() => setEditing(null)} className="text-[11px] text-slate-500 hover:underline">Annuler</button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-start gap-1.5 cursor-pointer group" onClick={() => setEditing({ code: it.code, observations: it.observations || "" })} data-testid={`roadmap-obs-display-${it.code}`}>
                      <span className="text-slate-600 italic flex-1">
                        {it.observations || <span className="text-slate-300">(cliquer pour ajouter)</span>}
                      </span>
                      <Pencil className="h-3 w-3 text-slate-300 group-hover:text-indigo-500 shrink-0 mt-0.5" />
                    </div>
                  )}
                </td>
                <td className="px-2 py-1.5 text-center">
                  <button
                    onClick={() => removeAction(it)}
                    className="text-rose-400 hover:text-rose-700 transition"
                    title="Supprimer (uniquement actions admin)"
                    data-testid={`roadmap-delete-${it.code}`}
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      ) : (
        <RoadmapKanban items={items} onMove={setStatus} onDelete={removeAction} />
      )}
    </div>
    </Filterable>
  );
};

const RoadmapKanban = ({ items, onMove, onDelete }) => {
  const cols = [
    { id: "todo", label: "À faire", ring: "ring-amber-200", bg: "bg-amber-50/40", border: "border-amber-200", text: "text-amber-700" },
    { id: "in_progress", label: "En cours", ring: "ring-sky-200", bg: "bg-sky-50/40", border: "border-sky-200", text: "text-sky-700" },
    { id: "done", label: "Réalisée", ring: "ring-emerald-200", bg: "bg-emerald-50/40", border: "border-emerald-200", text: "text-emerald-700" },
  ];
  const grouped = { todo: [], in_progress: [], done: [] };
  items.forEach((it) => {
    const s = it.status || (it.done ? "done" : "todo");
    if (grouped[s]) grouped[s].push(it);
  });
  return (
    <div className="grid md:grid-cols-3 gap-3" data-testid="roadmap-kanban">
      {cols.map((col) => (
        <div key={col.id} className={`rounded-lg ring-1 ${col.ring} ${col.bg} flex flex-col`} data-testid={`kanban-col-${col.id}`}>
          <div className={`px-3 py-2 border-b ${col.border} flex items-center justify-between`}>
            <h3 className={`text-xs font-semibold ${col.text} uppercase tracking-wider`}>{col.label}</h3>
            <span className={`rounded-full bg-white ring-1 ${col.ring} ${col.text} px-2 text-[10px] font-bold`}>
              {grouped[col.id].length}
            </span>
          </div>
          <div className="p-2 space-y-2 max-h-[480px] overflow-y-auto">
            {grouped[col.id].length === 0 ? (
              <p className="text-[10px] text-slate-400 italic text-center py-8">Aucune carte</p>
            ) : grouped[col.id].map((it) => (
              <RoadmapKanbanCard key={it.code} item={it} cols={cols} currentCol={col.id} onMove={onMove} onDelete={onDelete} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
};

const RoadmapKanbanCard = ({ item, cols, currentCol, onMove, onDelete }) => {
  const otherCols = cols.filter((c) => c.id !== currentCol);
  const btnClass = {
    todo: "ring-amber-300 text-amber-700 hover:bg-amber-50",
    in_progress: "ring-sky-300 text-sky-700 hover:bg-sky-50",
    done: "ring-emerald-300 text-emerald-700 hover:bg-emerald-50",
  };
  return (
    <div className="rounded-lg bg-white ring-1 ring-slate-200 p-2.5 shadow-sm hover:shadow-md transition" data-testid={`kanban-card-${item.code}`}>
      <div className="flex items-start justify-between gap-1.5 mb-1">
        <span className="font-mono text-[10px] font-bold text-indigo-700">{item.code}</span>
        <button
          onClick={() => onDelete(item)}
          className="text-rose-300 hover:text-rose-600 transition"
          title="Supprimer"
          data-testid={`kanban-delete-${item.code}`}
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </div>
      <p className="text-[11px] font-semibold text-slate-800 leading-snug">{item.title}</p>
      {item.backlog_ref && <p className="text-[9px] text-slate-500 mt-0.5">{item.backlog_ref}</p>}
      <div className="flex items-center justify-between mt-2 text-[10px] text-slate-500">
        <span className="font-mono">{(item.duration_h || 0).toFixed(2)} h</span>
        <span className="font-mono">{(item.cost_xof || 0).toLocaleString("fr-FR")} XOF</span>
      </div>
      <div className="flex items-center gap-1 mt-2 pt-2 border-t border-slate-100">
        <span className="text-[9px] text-slate-400 mr-auto">Déplacer →</span>
        {otherCols.map((c) => (
          <button
            key={c.id}
            onClick={() => onMove(item, c.id)}
            className={`text-[9px] font-semibold rounded px-1.5 py-0.5 ring-1 ${btnClass[c.id]}`}
            data-testid={`kanban-move-${item.code}-${c.id}`}
          >
            {c.label}
          </button>
        ))}
      </div>
    </div>
  );
};


const formatBytes = (bytes) => {
  if (!bytes) return "0 B";
  const u = ["B", "kB", "MB", "GB"];
  let i = 0;
  let n = bytes;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(n >= 10 || i === 0 ? 0 : 1)} ${u[i]}`;
};

// ============================================================
// Iter35e — Secrets Vault (Coffre-fort des secrets).
// Encrypted export/restore of every API token + non-secret config the
// admin would otherwise have to re-enter by hand after an incident.
// Bundle is encrypted client-side-safe (AES-256-GCM + PBKDF2-200k) with
// a password the admin chooses and remembers. Server never persists it.
// ============================================================
const SecretsVaultSection = () => {
  const [keys, setKeys] = useState(null);
  const [loadingKeys, setLoadingKeys] = useState(false);
  // Export state
  const [exportPwd, setExportPwd] = useState("");
  const [exportPwd2, setExportPwd2] = useState("");
  const [exportComment, setExportComment] = useState("");
  const [exporting, setExporting] = useState(false);
  // Import state
  const importInputRef = useRef(null);
  const [importPwd, setImportPwd] = useState("");
  const [importDry, setImportDry] = useState(true);
  const [overwriteFilled, setOverwriteFilled] = useState(false);
  const [importing, setImporting] = useState(false);
  const [lastImport, setLastImport] = useState(null);
  // Audit state
  const [audit, setAudit] = useState([]);
  const [auditOpen, setAuditOpen] = useState(false);
  // Iter35u/v — Editable critical URLs (used by background jobs for absolute links + outbound integrations)
  const CRITICAL_URL_FIELDS = [
    { key: "public_base_url", label: "URL publique de production", help: "Liens absolus, OAuth redirects, webhooks sortants. Prend le pas sur la variable d'environnement PUBLIC_BASE_URL.", placeholder: "https://sawalismartsystems.com" },
    { key: "tracking_base_url", label: "URL du tracker de visites", help: "Serveur qui reçoit les hits de visiteurs (n8n / Plausible / matomo…)", placeholder: "https://tracker.sawalismartsystems.com" },
    { key: "tracking_endpoint", label: "Chemin du tracker", help: "Path relatif appendé à l'URL ci-dessus (ex: /events/visit)", placeholder: "/events/visit" },
    { key: "webhook_base_url", label: "Webhook générique (sortant)", help: "URL appelée pour les notifications génériques.", placeholder: "https://sawalismartsystems.app.n8n.cloud/webhook/..." },
    { key: "notes_webhook_url", label: "Webhook Notes/Tâches/Rapports", help: "Notifie un workflow externe à chaque création/édition de note/tâche/rapport.", placeholder: "https://sawalismartsystems.app.n8n.cloud/webhook/notes" },
    { key: "health_webhook_url", label: "Webhook Santé applicative", help: "Reçoit les alertes santé (auth lockouts, snapshot failures, etc.).", placeholder: "https://sawalismartsystems.app.n8n.cloud/webhook/health" },
    { key: "n8n_webhook_url", label: "Webhook n8n (général)", help: "URL générale pour l'orchestration n8n.", placeholder: "https://sawalismartsystems.app.n8n.cloud/webhook/general" },
  ];
  const [urlValues, setUrlValues] = useState({});
  const [urlInitial, setUrlInitial] = useState({});
  const [savingUrlKey, setSavingUrlKey] = useState(null);
  const [urlsOpen, setUrlsOpen] = useState(true);
  // Iter35x — Webhook test state per critical URL key
  const [testingUrlKey, setTestingUrlKey] = useState(null);
  const [urlTestResult, setUrlTestResult] = useState({}); // { key: { ok, http_status, elapsed_ms, response, error } }
  const TESTABLE_URL_KEYS = new Set(["public_base_url", "tracking_base_url", "webhook_base_url", "notes_webhook_url", "health_webhook_url", "n8n_webhook_url"]);
  // Iter35x — Secret change audit (per-key history, no values, only fingerprints)
  const [changeAudit, setChangeAudit] = useState([]);
  const [changeAuditOpen, setChangeAuditOpen] = useState(false);
  const [changeAuditFilter, setChangeAuditFilter] = useState("");
  const [auditEmailEnabled, setAuditEmailEnabled] = useState(false);
  const [auditEmailTo, setAuditEmailTo] = useState("");
  const [auditEmailDirty, setAuditEmailDirty] = useState(false);
  const [savingAuditEmail, setSavingAuditEmail] = useState(false);
  const loadChangeAudit = useCallback(async () => {
    try {
      const r = await apiClient.get(`/admin/secrets/change-audit${changeAuditFilter ? `?key=${encodeURIComponent(changeAuditFilter)}` : ""}`);
      setChangeAudit(r.data?.items || []);
      setChangeAuditOpen(true);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec");
    }
  }, [changeAuditFilter]);
  const loadAuditEmailSettings = useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/settings");
      setAuditEmailEnabled(!!r.data?.secret_audit_email_enabled);
      setAuditEmailTo((r.data?.secret_audit_email_to || "").toString());
      setAuditEmailDirty(false);
    } catch (err) { /* silent */ }
  }, []);
  useEffect(() => { loadAuditEmailSettings(); }, [loadAuditEmailSettings]);
  const saveAuditEmail = async () => {
    setSavingAuditEmail(true);
    try {
      await apiClient.put("/admin/settings", {
        secret_audit_email_enabled: auditEmailEnabled,
        secret_audit_email_to: auditEmailTo.trim(),
      });
      toast.success("Notifications de modif coffre-fort enregistrées");
      setAuditEmailDirty(false);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec");
    } finally {
      setSavingAuditEmail(false);
    }
  };

  const loadCriticalUrls = useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/settings");
      const next = {};
      CRITICAL_URL_FIELDS.forEach(({ key }) => {
        next[key] = (r.data?.[key] || "").toString();
      });
      setUrlValues(next);
      setUrlInitial(next);
    } catch (err) {
      // Silent — admin will see empty fields
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => { loadCriticalUrls(); }, [loadCriticalUrls]);

  const saveCriticalUrl = async (key) => {
    const v = (urlValues[key] || "").trim();
    // Path fields (tracking_endpoint) may start with /; others must be http(s) URLs
    const isPath = key === "tracking_endpoint";
    if (v && !isPath && !/^https?:\/\//i.test(v)) {
      toast.error("L'URL doit commencer par http:// ou https://");
      return;
    }
    if (v && isPath && !v.startsWith("/")) {
      toast.error("Le chemin doit commencer par /");
      return;
    }
    setSavingUrlKey(key);
    try {
      await apiClient.put("/admin/settings", { [key]: v });
      setUrlInitial({ ...urlInitial, [key]: v });
      toast.success(v ? `${key} : enregistré` : `${key} : vidé`);
      loadKeys();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec");
    } finally {
      setSavingUrlKey(null);
    }
  };

  // Iter35w — Send a dry-run ping to the configured webhook URL
  const testCriticalUrl = async (key) => {
    setTestingUrlKey(key);
    setUrlTestResult((prev) => ({ ...prev, [key]: null }));
    try {
      const r = await apiClient.post("/admin/settings/test-url", { key });
      const data = r.data || {};
      setUrlTestResult((prev) => ({ ...prev, [key]: data }));
      if (data.ok) {
        toast.success(`${key} : HTTP ${data.http_status} en ${data.elapsed_ms} ms ✓`, { duration: 6000 });
      } else if (data.error) {
        toast.error(`${key} : ${data.error}`, { duration: 8000 });
      } else {
        toast.error(`${key} : HTTP ${data.http_status} — réponse non OK`, { duration: 8000 });
      }
    } catch (err) {
      const msg = err?.response?.data?.detail || err?.message || "Échec du test";
      setUrlTestResult((prev) => ({ ...prev, [key]: { ok: false, error: msg } }));
      toast.error(msg, { duration: 8000 });
    } finally {
      setTestingUrlKey(null);
    }
  };

  const loadKeys = useCallback(async () => {
    setLoadingKeys(true);
    try {
      const r = await apiClient.get("/admin/secrets/keys");
      setKeys(r.data || null);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec");
    } finally {
      setLoadingKeys(false);
    }
  }, []);

  useEffect(() => { loadKeys(); }, [loadKeys]);

  const doExport = async () => {
    if (exportPwd.length < 8) { toast.error("Mot de passe : 8 caractères minimum"); return; }
    if (exportPwd !== exportPwd2) { toast.error("Les mots de passe ne correspondent pas"); return; }
    setExporting(true);
    try {
      const r = await apiClient.post("/admin/secrets/export", {
        password: exportPwd,
        comment: exportComment,
      });
      // Trigger file download
      const blob = new Blob([JSON.stringify(r.data.envelope, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = r.data.filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast.success(`Coffre-fort téléchargé (${r.data.keys_count} clés chiffrées). Conservez ce fichier en lieu sûr.`, { duration: 8000 });
      setExportPwd(""); setExportPwd2(""); setExportComment("");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec de l'export");
    } finally { setExporting(false); }
  };

  const onImportFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (!importPwd) { toast.error("Saisissez d'abord le mot de passe"); return; }
    setImporting(true); setLastImport(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("password", importPwd);
      fd.append("dry_run", importDry ? "true" : "false");
      fd.append("overwrite_filled", overwriteFilled ? "true" : "false");
      const r = await apiClient.post("/admin/secrets/import", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setLastImport(r.data);
      if (r.data?.dry_run) {
        toast.info(`Aperçu : ${(r.data.plan || []).filter(p => p.will_apply).length}/${r.data.plan?.length || 0} clés seraient restaurées`);
      } else {
        toast.success(`✅ ${r.data.applied_count} clé(s) restaurée(s) — votre coffre-fort est intact.`, { duration: 8000 });
        await loadKeys();
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec de l'import");
    } finally { setImporting(false); }
  };

  const loadAudit = async () => {
    try {
      const r = await apiClient.get("/admin/secrets/audit");
      setAudit(r.data?.items || []);
      setAuditOpen(true);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec");
    }
  };

  return (
    <div className="rounded-xl border-2 border-purple-200 bg-purple-50/40 p-6 space-y-4" data-testid="admin-secrets-vault-section">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <Lock className="h-4 w-4 text-purple-600" />
          <h2 className="font-display font-semibold">Coffre-fort des secrets (Iter35e)</h2>
        </div>
        <button
          onClick={loadKeys}
          disabled={loadingKeys}
          className="text-xs inline-flex items-center gap-1 text-slate-500 hover:text-slate-900 transition"
          data-testid="vault-refresh-btn"
        >
          <RefreshCw className={`h-3 w-3 ${loadingKeys ? "animate-spin" : ""}`} /> Actualiser
        </button>
      </div>
      <p className="text-xs text-slate-700">
        Sauvegarde <strong>chiffrée</strong> (AES-256-GCM + PBKDF2 200 000 itérations) de tous vos tokens API (WhatsApp, SMTP,
        SMS, PawaPay, Google, OpenAI, webhooks…) plus les paramètres associés. Le fichier <code>.json</code> est
        chiffré <strong>avant</strong> de quitter le serveur — sans votre mot de passe, le contenu est inutilisable.
        En cas d'incident (snapshot raté, env reset, nouvelle installation), restaurez vos credentials en un clic.
      </p>

      {/* Iter35u/v — Quick-edit: URLs critiques (DB override of env var + outbound webhooks) */}
      <div className="rounded-lg ring-1 ring-purple-200 bg-white p-3" data-testid="critical-urls-editor">
        <button
          type="button"
          onClick={() => setUrlsOpen((v) => !v)}
          className="w-full flex items-center justify-between gap-2 text-left"
          data-testid="critical-urls-toggle"
        >
          <span className="flex items-center gap-2">
            <Link2 className="h-4 w-4 text-purple-600" />
            <span className="font-display font-semibold text-sm text-slate-800">URLs critiques</span>
            <span className="text-[10px] text-purple-700 bg-purple-100 px-1.5 py-0.5 rounded-full">{Object.values(urlInitial).filter(Boolean).length}/{CRITICAL_URL_FIELDS.length}</span>
          </span>
          <span className="text-xs text-slate-400">{urlsOpen ? "Masquer" : "Afficher"}</span>
        </button>
        <p className="text-[11px] text-slate-500 mt-1">
          Centralisation des URLs sortantes (base publique, tracker, webhooks n8n). Toutes éditables en un seul endroit, sauvegardées dans le coffre.
        </p>
        {urlsOpen && (
          <div className="mt-3 space-y-3">
            {CRITICAL_URL_FIELDS.map(({ key, label, help, placeholder }) => {
              const dirty = (urlValues[key] || "") !== (urlInitial[key] || "");
              const saving = savingUrlKey === key;
              const testable = TESTABLE_URL_KEYS.has(key) && !!urlInitial[key];
              const testing = testingUrlKey === key;
              const testResult = urlTestResult[key];
              return (
                <div key={key} className="rounded ring-1 ring-slate-200 bg-slate-50/50 p-2.5" data-testid={`critical-url-${key}`}>
                  <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                    <span className="font-mono text-[10px] bg-purple-100 text-purple-900 px-1.5 py-0.5 rounded">{key}</span>
                    <span className="text-xs font-semibold text-slate-700">{label}</span>
                    {urlInitial[key] && <span className="text-[9px] text-emerald-600 font-semibold uppercase tracking-wider">✓ Renseigné</span>}
                  </div>
                  <div className="flex gap-2 flex-wrap">
                    <input
                      type="text"
                      value={urlValues[key] || ""}
                      onChange={(e) => setUrlValues({ ...urlValues, [key]: e.target.value })}
                      placeholder={placeholder}
                      className="flex-1 min-w-[240px] rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-mono"
                      data-testid={`critical-url-input-${key}`}
                    />
                    <button
                      onClick={() => saveCriticalUrl(key)}
                      disabled={saving || !dirty}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-40 disabled:cursor-not-allowed px-3 py-1.5 text-xs font-medium transition"
                      data-testid={`critical-url-save-${key}`}
                    >
                      {saving ? "…" : "Enregistrer"}
                    </button>
                    {testable && (
                      <button
                        onClick={() => testCriticalUrl(key)}
                        disabled={testing || dirty}
                        title={dirty ? "Enregistrez d'abord pour tester la valeur en base" : "Envoyer un payload de test dry_run"}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-white text-purple-700 ring-1 ring-purple-300 hover:bg-purple-50 disabled:opacity-40 disabled:cursor-not-allowed px-3 py-1.5 text-xs font-medium transition"
                        data-testid={`critical-url-test-${key}`}
                      >
                        {testing ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Webhook className="h-3 w-3" />}
                        {testing ? "Test…" : "Tester"}
                      </button>
                    )}
                  </div>
                  <p className="text-[10px] text-slate-500 mt-1">{help}</p>
                  {testResult && (
                    <div
                      className={`mt-2 rounded ring-1 p-2 text-[11px] ${testResult.ok ? "bg-emerald-50 ring-emerald-200 text-emerald-900" : "bg-rose-50 ring-rose-200 text-rose-900"}`}
                      data-testid={`critical-url-test-result-${key}`}
                    >
                      <div className="flex items-center gap-2 flex-wrap mb-1">
                        <strong>{testResult.ok ? "✓ Succès" : "✗ Échec"}</strong>
                        {testResult.http_status !== undefined && <span>HTTP {testResult.http_status}</span>}
                        {testResult.elapsed_ms !== undefined && <span className="text-slate-500">· {testResult.elapsed_ms} ms</span>}
                        {testResult.method && <span className="font-mono text-slate-500">{testResult.method}</span>}
                      </div>
                      {testResult.final_url && (
                        <div className="font-mono text-[10px] text-slate-600 truncate" title={testResult.final_url}>→ {testResult.final_url}</div>
                      )}
                      {testResult.error && <div className="text-rose-700 mt-1">{testResult.error}</div>}
                      {testResult.response !== undefined && testResult.response !== null && (
                        <details className="mt-1">
                          <summary className="cursor-pointer text-slate-600 hover:text-slate-900">Voir la réponse</summary>
                          <pre className="mt-1 max-h-40 overflow-auto bg-white ring-1 ring-slate-200 rounded p-1.5 text-[10px] whitespace-pre-wrap break-words">{typeof testResult.response === "string" ? testResult.response : JSON.stringify(testResult.response, null, 2)}</pre>
                        </details>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Status overview */}
      {keys && (
        <div className="rounded-lg ring-1 ring-purple-200 bg-white p-3 text-xs" data-testid="vault-status">
          <div className="font-semibold text-slate-700 mb-1.5">État actuel du coffre</div>
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-emerald-700 font-semibold">
              {keys.populated} clé(s) renseignée(s)
            </span>
            <span className="text-slate-400">·</span>
            <span className="text-slate-500">{keys.total - keys.populated} clé(s) vide(s)</span>
            <span className="text-slate-400">·</span>
            <span className="text-slate-500">{keys.total} clés au total surveillées</span>
          </div>
          <details className="mt-2">
            <summary className="cursor-pointer text-slate-600 hover:text-slate-900">Voir le détail des clés</summary>
            <div className="mt-2 grid grid-cols-2 sm:grid-cols-3 gap-1 text-[10px]">
              {(keys.keys || []).map((k) => (
                <div key={k.key} className={`rounded px-1.5 py-1 ring-1 ${k.populated ? "bg-emerald-50 ring-emerald-200 text-emerald-900" : "bg-slate-50 ring-slate-200 text-slate-500"}`} data-testid={`vault-key-${k.key}`}>
                  <span className="font-mono">{k.key}</span>
                  {k.is_secret && <span className="ml-1 text-rose-600" title="Secret">🔐</span>}
                  {k.populated ? <span className="ml-1 text-emerald-600">✓</span> : <span className="ml-1 text-slate-400">—</span>}
                </div>
              ))}
            </div>
          </details>
        </div>
      )}

      {/* Export panel */}
      <div className="rounded-lg ring-1 ring-purple-200 bg-white p-4 space-y-3" data-testid="vault-export-card">
        <div className="text-xs font-semibold uppercase tracking-wider text-purple-700 flex items-center gap-1.5">
          <Save className="h-3.5 w-3.5" /> Exporter (créer un coffre)
        </div>
        <p className="text-xs text-slate-500">
          Choisissez un mot de passe <strong>fort</strong> et que vous retiendrez : <strong>il sera impossible de récupérer le contenu sans</strong>. Stockez le fichier téléchargé dans un endroit hors de votre serveur (gestionnaire de mots de passe, clé USB, mail privé).
        </p>
        <div className="grid sm:grid-cols-2 gap-2">
          <label className="text-xs font-semibold">
            Mot de passe (min. 8 car.)
            <input type="password" value={exportPwd} onChange={(e) => setExportPwd(e.target.value)} placeholder="••••••••" className="w-full mt-1 rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="vault-export-pwd" autoComplete="new-password" />
          </label>
          <label className="text-xs font-semibold">
            Confirmer le mot de passe
            <input type="password" value={exportPwd2} onChange={(e) => setExportPwd2(e.target.value)} placeholder="••••••••" className="w-full mt-1 rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="vault-export-pwd2" autoComplete="new-password" />
          </label>
        </div>
        <input
          value={exportComment}
          onChange={(e) => setExportComment(e.target.value)}
          maxLength={200}
          placeholder="Commentaire (ex: snapshot pré-migration 2026-05-13)"
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          data-testid="vault-export-comment"
        />
        <button
          onClick={doExport}
          disabled={exporting || exportPwd.length < 8 || exportPwd !== exportPwd2}
          className="inline-flex items-center gap-2 rounded-lg bg-purple-600 text-white px-4 py-2 text-sm font-semibold hover:bg-purple-700 disabled:opacity-50"
          data-testid="vault-export-btn"
        >
          <Save className="h-4 w-4" />
          {exporting ? "Création…" : "Télécharger le coffre chiffré"}
        </button>
      </div>

      {/* Import panel */}
      <div className="rounded-lg ring-1 ring-purple-200 bg-white p-4 space-y-3" data-testid="vault-import-card">
        <div className="text-xs font-semibold uppercase tracking-wider text-purple-700 flex items-center gap-1.5">
          <Upload className="h-3.5 w-3.5" /> Restaurer un coffre
        </div>
        <p className="text-xs text-slate-500">
          Importez un fichier <code>sawali-vault-*.json</code> précédemment téléchargé et saisissez son mot de passe.
          Le mode « aperçu » liste ce qui sera restauré sans rien modifier.
        </p>
        <input
          type="password"
          value={importPwd}
          onChange={(e) => setImportPwd(e.target.value)}
          placeholder="Mot de passe du coffre"
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          data-testid="vault-import-pwd"
          autoComplete="off"
        />
        <div className="flex flex-wrap items-center gap-3">
          <label className="inline-flex items-center gap-2 text-xs text-slate-700">
            <input type="checkbox" checked={importDry} onChange={(e) => setImportDry(e.target.checked)} data-testid="vault-import-dry" />
            Aperçu (dry-run) — ne rien modifier
          </label>
          <label className="inline-flex items-center gap-2 text-xs text-slate-700">
            <input type="checkbox" checked={overwriteFilled} onChange={(e) => setOverwriteFilled(e.target.checked)} data-testid="vault-import-overwrite" />
            Écraser les clés déjà renseignées
          </label>
        </div>
        <input
          ref={importInputRef}
          type="file"
          accept=".json,application/json"
          onChange={onImportFile}
          className="hidden"
          data-testid="vault-import-input"
        />
        <button
          onClick={() => importInputRef.current?.click()}
          disabled={importing || !importPwd}
          className="inline-flex items-center gap-2 rounded-lg bg-amber-600 text-white px-4 py-2 text-sm font-semibold hover:bg-amber-700 disabled:opacity-50"
          data-testid="vault-import-btn"
        >
          <Upload className="h-4 w-4" />
          {importing ? "Restauration…" : "Choisir le coffre et restaurer"}
        </button>

        {lastImport && (
          <div className={`rounded p-3 text-xs ${lastImport.dry_run ? "bg-sky-50 ring-1 ring-sky-300" : "bg-emerald-50 ring-1 ring-emerald-300"}`} data-testid="vault-import-result">
            <p className="font-semibold text-slate-800 mb-1">
              {lastImport.dry_run ? "🔍 Aperçu" : "✅ Restauration appliquée"}
              {lastImport.bundle_exported_at && (
                <span className="text-slate-500 font-normal ml-2">
                  · coffre du {new Date(lastImport.bundle_exported_at).toLocaleString("fr-FR")}
                  {lastImport.bundle_exported_by && ` · par ${lastImport.bundle_exported_by}`}
                </span>
              )}
            </p>
            {lastImport.bundle_comment && <p className="italic text-slate-600 mb-1">« {lastImport.bundle_comment} »</p>}
            <p>
              <strong>{lastImport.applied_count}</strong> clé(s) {lastImport.dry_run ? "seraient" : "ont été"} restaurée(s) sur <strong>{lastImport.incoming_count}</strong> présentes dans le coffre.
            </p>
            <details className="mt-2">
              <summary className="cursor-pointer text-slate-600">Détail par clé</summary>
              <div className="mt-1 grid grid-cols-1 sm:grid-cols-2 gap-1 text-[10px]">
                {(lastImport.plan || []).map((p) => (
                  <div key={p.key} className={`rounded px-1.5 py-1 ring-1 ${p.will_apply ? "bg-white ring-emerald-200" : "bg-slate-100 ring-slate-200 text-slate-500"}`}>
                    <span className="font-mono">{p.key}</span>
                    {p.is_secret && <span className="ml-1 text-rose-600">🔐</span>}
                    {p.will_apply ? <span className="ml-1 text-emerald-600">✓ appliquera</span> : <span className="ml-1 text-slate-400">⊘ déjà rempli</span>}
                  </div>
                ))}
              </div>
            </details>
          </div>
        )}
      </div>

      {/* Audit trail */}
      <div className="rounded-lg ring-1 ring-slate-200 bg-white p-3" data-testid="vault-audit-card">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-600">Journal d'activité</span>
          <button onClick={loadAudit} className="text-xs text-purple-700 hover:underline" data-testid="vault-audit-btn">
            {auditOpen ? "Actualiser" : "Charger le journal"}
          </button>
        </div>
        {auditOpen && (
          <div className="mt-2 max-h-48 overflow-y-auto text-[11px]">
            {audit.length === 0 && <p className="italic text-slate-400">Aucune action enregistrée.</p>}
            {audit.map((a) => (
              <div key={a.id} className="flex items-center gap-2 py-1 border-b last:border-0 border-slate-100" data-testid={`vault-audit-${a.id}`}>
                <span className="font-mono text-slate-500">{new Date(a.created_at).toLocaleString("fr-FR")}</span>
                <span className={`rounded px-1.5 py-0.5 text-[9px] font-bold ${a.action === "export" ? "bg-purple-100 text-purple-700" : a.action === "import" ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>
                  {a.action.toUpperCase()}
                </span>
                <span className="text-slate-700">{a.actor_email}</span>
                {a.action === "export" && <span className="text-slate-500">→ {a.keys_count} clés</span>}
                {a.action.startsWith("import") && <span className="text-slate-500">→ {a.applied_count}/{a.incoming_count} appliquées</span>}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Iter35x — Historique des modifications de clés (qui/quand/quelle clé — jamais la valeur) */}
      <Filterable title="Historique des modifications de clés" anchorId="secret-change-audit">
        <div className="rounded-lg ring-1 ring-purple-200 bg-white p-3 space-y-3" data-testid="secret-change-audit-card">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-purple-600" />
              <span className="text-xs font-semibold text-slate-700">Historique des modifications de clés</span>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <input
                type="text"
                value={changeAuditFilter}
                onChange={(e) => setChangeAuditFilter(e.target.value)}
                placeholder="Filtrer par clé (ex: public_base_url)"
                className="rounded border border-slate-300 px-2 py-1 text-xs font-mono w-56"
                data-testid="secret-change-audit-filter"
              />
              <button
                onClick={loadChangeAudit}
                className="text-xs inline-flex items-center gap-1 rounded bg-purple-600 text-white hover:bg-purple-700 px-2 py-1"
                data-testid="secret-change-audit-load"
              >
                <RefreshCw className="h-3 w-3" /> Charger
              </button>
            </div>
          </div>
          <div className="rounded ring-1 ring-slate-200 bg-slate-50/50 p-2.5" data-testid="secret-audit-email-block">
            <div className="flex items-center gap-2 mb-1.5">
              <Mail className="h-3.5 w-3.5 text-purple-600" />
              <span className="text-xs font-semibold text-slate-700">Email à chaque modification</span>
            </div>
            <p className="text-[10px] text-slate-500 mb-1.5">
              Reçoit un email automatique à chaque modif/création/suppression d'une clé sensible. L'email contient <strong>qui, quand, quelle clé</strong> — jamais la valeur. Une empreinte SHA-256 (16 car.) permet de vérifier l'unicité de la nouvelle valeur côté admin.
            </p>
            <label className="flex items-center gap-2 text-xs cursor-pointer mb-1.5">
              <input
                type="checkbox"
                checked={auditEmailEnabled}
                onChange={(e) => { setAuditEmailEnabled(e.target.checked); setAuditEmailDirty(true); }}
                className="accent-purple-600"
                data-testid="secret-audit-email-enabled"
              />
              <span>Activer les notifications par email</span>
            </label>
            <div className="flex gap-2 flex-wrap">
              <input
                type="email"
                value={auditEmailTo}
                onChange={(e) => { setAuditEmailTo(e.target.value); setAuditEmailDirty(true); }}
                placeholder="admin@sawalismartsystems.com"
                disabled={!auditEmailEnabled}
                className="flex-1 min-w-[220px] rounded-lg border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-50"
                data-testid="secret-audit-email-to"
              />
              <button
                onClick={saveAuditEmail}
                disabled={savingAuditEmail || !auditEmailDirty}
                className="inline-flex items-center gap-1.5 rounded-lg bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-40 disabled:cursor-not-allowed px-3 py-1.5 text-xs font-medium transition"
                data-testid="secret-audit-email-save"
              >
                {savingAuditEmail ? "…" : "Enregistrer"}
              </button>
            </div>
          </div>
          {changeAuditOpen && (
            <div className="max-h-72 overflow-y-auto text-[11px]" data-testid="secret-change-audit-list">
              {changeAudit.length === 0 && <p className="italic text-slate-400">Aucune modification enregistrée{changeAuditFilter ? ` pour la clé "${changeAuditFilter}"` : ""}.</p>}
              {changeAudit.map((a) => (
                <div key={a.id} className="flex items-center gap-2 py-1 border-b last:border-0 border-slate-100" data-testid={`secret-change-audit-row-${a.id}`}>
                  <span className="font-mono text-slate-500 min-w-[140px]">{new Date(a.ts).toLocaleString("fr-FR")}</span>
                  <span className={`rounded px-1.5 py-0.5 text-[9px] font-bold uppercase ${a.action === "created" ? "bg-emerald-100 text-emerald-700" : a.action === "deleted" ? "bg-rose-100 text-rose-700" : "bg-sky-100 text-sky-700"}`}>
                    {a.action}
                  </span>
                  <span className="font-mono text-purple-900 truncate flex-1" title={a.key}>{a.key}</span>
                  {a.is_secret && <Lock className="h-3 w-3 text-rose-500" />}
                  <span className="text-slate-700 truncate max-w-[180px]" title={a.actor_email}>{a.actor_email}</span>
                  {a.fingerprint && <span className="font-mono text-[9px] text-slate-400" title="Empreinte SHA-256">{a.fingerprint}</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      </Filterable>
    </div>
  );
};


// =====================================================================
// Iter35q — Stockage objet persistant (Emergent Object Storage)
// =====================================================================
const FileStorageSection = () => {
  const [orphans, setOrphans] = useState(null);
  const [backfillResult, setBackfillResult] = useState(null);
  const [busy, setBusy] = useState(false);

  const fetchOrphans = async () => {
    setBusy(true);
    try {
      const r = await apiClient.get("/admin/files/orphans");
      setOrphans(r.data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setBusy(false); }
  };

  const runBackfill = async () => {
    if (!window.confirm("Pousser tous les fichiers encore présents sur disque vers le stockage objet persistant ? (à faire une seule fois après chaque redéploiement)")) return;
    setBusy(true);
    try {
      const r = await apiClient.post("/admin/files/backfill");
      setBackfillResult(r.data);
      toast.success(`${r.data.mirrored} fichier(s) sauvegardé(s) dans le stockage persistant`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setBusy(false); }
  };

  return (
    <Section icon={FileArchive} title="Stockage persistant des fichiers (Emergent Object Storage)">
      <p className="text-xs text-slate-500">
        Les fichiers uploadés (Documents, médias WhatsApp, etc.) sont automatiquement sauvegardés
        sur le stockage objet Emergent pour qu'ils survivent aux redéploiements. À utiliser après
        chaque redéploiement pour pousser les fichiers existants vers le stockage persistant.
      </p>
      <div className="flex gap-2 flex-wrap">
        <button
          onClick={runBackfill}
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white hover:opacity-90 px-3 py-2 text-sm disabled:opacity-50"
          data-testid="storage-backfill-btn"
          title="Sauvegarder tous les fichiers présents sur disque vers le stockage persistant (à exécuter une seule fois après redéploiement)"
        >
          <Cloud className="h-4 w-4" /> Sauvegarder les fichiers existants
        </button>
        <button
          onClick={fetchOrphans}
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 px-3 py-2 text-sm disabled:opacity-50"
          data-testid="storage-orphans-btn"
          title="Lister les fichiers définitivement perdus (références DB sans binaire ni sur disque ni dans le stockage)"
        >
          <AlertCircle className="h-4 w-4" /> Vérifier les fichiers manquants
        </button>
      </div>
      {backfillResult && (
        <div className="rounded-lg ring-1 ring-emerald-200 bg-emerald-50 p-3 text-xs space-y-1" data-testid="storage-backfill-result">
          <p className="font-semibold text-emerald-800">✓ Sauvegarde terminée</p>
          <p className="text-emerald-700">
            <strong>{backfillResult.mirrored}</strong> fichier(s) sauvegardé(s) • {backfillResult.skipped_no_disk} ignoré(s) (absents du disque)
            {backfillResult.errors?.length > 0 && (
              <span className="text-rose-700"> • {backfillResult.errors.length} erreur(s)</span>
            )}
          </p>
          {backfillResult.errors?.length > 0 && (
            <details>
              <summary className="cursor-pointer text-rose-700 underline">Détails erreurs</summary>
              <ul className="mt-1 list-disc list-inside text-rose-700">
                {backfillResult.errors.map((e, i) => <li key={i}><code>{e.id}</code> : {e.error}</li>)}
              </ul>
            </details>
          )}
        </div>
      )}
      {orphans && (
        <div className="rounded-lg ring-1 ring-amber-200 bg-amber-50 p-3 text-xs space-y-1" data-testid="storage-orphans-result">
          <p className="font-semibold text-amber-900">
            {orphans.count === 0 ? "✓ Aucun fichier perdu" : `⚠ ${orphans.count} fichier(s) définitivement perdu(s)`}
          </p>
          {orphans.count > 0 && (
            <>
              <p className="text-amber-800">
                Ces fichiers n'existent ni sur disque, ni dans le stockage persistant. Ils doivent être ré-uploadés manuellement.
              </p>
              <details>
                <summary className="cursor-pointer text-amber-900 underline">Voir la liste</summary>
                <table className="mt-2 w-full text-[11px]">
                  <thead>
                    <tr className="text-left text-amber-900">
                      <th className="pr-2">Nom</th><th className="pr-2">Taille</th><th className="pr-2">Uploadé par</th><th>Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {orphans.items.slice(0, 100).map((f) => (
                      <tr key={f.id} className="border-t border-amber-200">
                        <td className="py-1 pr-2 truncate max-w-[200px]">{f.filename}</td>
                        <td className="py-1 pr-2">{f.size ? `${(f.size / 1024).toFixed(0)} Ko` : "—"}</td>
                        <td className="py-1 pr-2 truncate max-w-[160px]">{f.uploaded_by_email || "—"}</td>
                        <td className="py-1">{f.uploaded_at ? new Date(f.uploaded_at).toLocaleDateString("fr-FR") : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {orphans.items.length > 100 && <p className="mt-1 text-amber-800">… et {orphans.items.length - 100} autres</p>}
              </details>
            </>
          )}
        </div>
      )}
    </Section>
  );
};


const DbSnapshotsSection = ({ s = {}, upd = () => {}, reloadSettings = () => {} }) => {
  const [list, setList] = useState([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [comment, setComment] = useState("");
  const [maskSecrets, setMaskSecrets] = useState(true);
  const [editing, setEditing] = useState(null);  // {id, comment}
  const [importMode, setImportMode] = useState("replace");
  const [importDryRun, setImportDryRun] = useState(true);
  const [importComment, setImportComment] = useState("");
  const [importing, setImporting] = useState(false);
  const [lastImport, setLastImport] = useState(null);
  const [imports, setImports] = useState([]);
  const [autoRunning, setAutoRunning] = useState(false);
  const [autoSaving, setAutoSaving] = useState(false);
  const fileInputRef = useRef(null);
  const TITLE = "Sauvegarde de la base (Snapshot)";

  const load = async () => {
    setLoading(true);
    try {
      const [a, b] = await Promise.all([
        apiClient.get("/admin/snapshots"),
        apiClient.get("/admin/snapshots/imports"),
      ]);
      setList(a.data?.snapshots || []);
      setImports(b.data?.imports || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const create = async () => {
    setCreating(true);
    try {
      const r = await apiClient.post("/admin/snapshots", { comment, mask_secrets: maskSecrets });
      toast.success(`Snapshot créé (${formatBytes(r.data.size_bytes)}, ${r.data.total_documents} documents)`);
      setComment("");
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setCreating(false); }
  };

  const download = async (snap) => {
    try {
      const r = await apiClient.get(`/admin/snapshots/${snap.id}/download`, { responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([r.data]));
      const a = document.createElement("a");
      a.href = url;
      a.download = snap.file_name || `snapshot_${snap.id}.json.gz`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de téléchargement");
    }
  };

  const removeSnap = async (snap) => {
    if (!window.confirm(`Supprimer définitivement ce snapshot du ${new Date(snap.created_at).toLocaleString("fr-FR")} ?`)) return;
    try {
      await apiClient.delete(`/admin/snapshots/${snap.id}`);
      toast.success("Snapshot supprimé");
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const saveComment = async () => {
    if (!editing) return;
    try {
      await apiClient.patch(`/admin/snapshots/${editing.id}`, { comment: editing.comment });
      toast.success("Commentaire mis à jour");
      setEditing(null);
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const onPickFile = () => fileInputRef.current?.click();
  const [uploadProgress, setUploadProgress] = useState(0);
  const onFileChange = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (!importDryRun && importMode === "replace") {
      if (!window.confirm("⚠️ Mode REMPLACER actif : toutes les collections vont être VIDÉES puis remplies par le snapshot. Cette action est IRRÉVERSIBLE. Continuer ?")) return;
    }
    setImporting(true);
    setLastImport(null);
    setUploadProgress(0);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("mode", importMode);
      fd.append("dry_run", importDryRun ? "true" : "false");
      fd.append("comment", importComment || "");
      const sizeKo = Math.round(file.size / 1024);
      // Iter35j — explicit 10-min timeout + upload progress so the user
      // doesn't think "nothing is happening" on a >5 Mo snapshot.
      const r = await apiClient.post("/admin/snapshots/import", fd, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 600000,
        onUploadProgress: (evt) => {
          if (evt.total) {
            const pct = Math.round((evt.loaded / evt.total) * 100);
            setUploadProgress(pct);
            if (pct === 100) {
              toast(`📤 Fichier transféré (${sizeKo} Ko), application en cours… (peut prendre jusqu'à 5 min sur une grosse base)`, { duration: 6000 });
            }
          }
        },
      });
      setLastImport(r.data);
      if (r.data?.dry_run) {
        toast.info("Aperçu (dry-run) calculé. Vérifiez le résumé ci-dessous puis désactivez le dry-run pour appliquer.");
      } else {
        // Iter35c — richer success/error toast based on summary + notifications.
        const summary = r.data?.summary || {};
        const totalErrors = Object.values(summary).filter((v) => v?.action === "error").length;
        const impacted = Object.values(summary).filter((v) => (v?.incoming || 0) > 0 || (v?.action || "") === "replaced").length;
        const notif = r.data?.notifications || {};
        const emailOk = notif?.email?.sent;
        const waOk = notif?.whatsapp?.any_sent;
        if (totalErrors > 0) {
          toast.warning(
            `Import terminé avec ${totalErrors} erreur(s) sur ${impacted} collection(s). Voir le détail ci-dessous.`,
            { duration: 8000 }
          );
        } else {
          toast.success(
            `✅ Import appliqué — ${impacted} collection(s) impactée(s). ` +
              (emailOk ? "Email envoyé ✓" : "Email ✗") +
              (waOk ? " · WhatsApp envoyé ✓" : (notif?.whatsapp?.attempts?.length ? " · WhatsApp ✗" : "")),
            { duration: 8000 }
          );
        }
        setImportComment("");
      }
      await load();
    } catch (err) {
      // Iter35j — surface ALL flavors of failure so the user never sees "rien ne se passe":
      //   - axios timeout (code='ECONNABORTED'): proxy killed the request after N seconds
      //   - network: backend or ingress dropped the connection
      //   - 4xx/5xx with backend detail
      console.error("snapshot import failed", err);
      let msg = err?.response?.data?.detail;
      if (!msg) {
        if (err?.code === "ECONNABORTED") msg = "⏱️ Délai dépassé — la base est peut-être trop grosse. Essayez de l'importer en plusieurs morceaux (export par catégorie).";
        else if (err?.message?.includes("Network")) msg = "🌐 Erreur réseau — la connexion a été coupée avant la fin de l'import. Réessayez avec une connexion stable.";
        else msg = err?.message || "Erreur inconnue lors de l'import";
      }
      toast.error(msg, { duration: 12000 });
      setLastImport({ error: msg });
    } finally { setImporting(false); setUploadProgress(0); }
  };

  const runAutoNow = async () => {
    if (!window.confirm("Lancer maintenant une sauvegarde automatique ? Elle sera marquée 'auto' et soumise à la rotation.")) return;
    setAutoRunning(true);
    try {
      const r = await apiClient.post("/admin/snapshots/auto-run");
      toast.success(`Auto-snapshot créé (${r.data?.deleted ?? 0} ancien(s) purgé(s))`);
      await load();
      await reloadSettings();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setAutoRunning(false); }
  };

  const saveAutoSettings = async (patch) => {
    setAutoSaving(true);
    try {
      await apiClient.put("/admin/settings", patch);
      await reloadSettings();
      toast.success("Préférences enregistrées");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setAutoSaving(false); }
  };

  const autoEnabled = !!s.auto_snapshot_enabled;
  const autoKeep = Number.isFinite(s.auto_snapshot_keep) ? s.auto_snapshot_keep : 4;

  return (
    <Filterable title={TITLE} anchorId={`s-${slugify(TITLE)}`}>
    <div className="rounded-xl border-2 border-sky-200 bg-sky-50/40 p-6 space-y-4" data-testid="admin-db-snapshots-section">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Cloud className="h-4 w-4 text-sky-600" />
          <h2 className="font-display font-semibold">Sauvegarde de la base (Snapshot)</h2>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="text-xs inline-flex items-center gap-1 text-slate-500 hover:text-slate-900 transition"
          data-testid="snapshots-refresh-btn"
        >
          <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} /> Actualiser
        </button>
      </div>
      <p className="text-xs text-slate-600">
        Exportez l'état actuel des données métier (utilisateurs, contacts, RDV, interventions, documents, paramètres…) sous forme de fichier <code className="font-mono">.json.gz</code> téléchargeable.
        Les <strong>tokens API et secrets</strong> sont masqués par défaut. Les <strong>fichiers binaires</strong> (PDF, images uploadés) ne sont <strong>pas</strong> inclus.
        Pour répliquer la prod sur ce preview : exportez depuis la prod, téléchargez le fichier, puis utilisez le bloc « Importer un snapshot » plus bas.
      </p>

      {/* Auto snapshot — weekly cron */}
      <div className="rounded-lg ring-1 ring-emerald-200 bg-white p-4 space-y-3" data-testid="snapshot-auto-card">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wider text-emerald-700 flex items-center gap-1.5">
              <RotateCcw className="h-3.5 w-3.5" /> Sauvegarde automatique hebdomadaire
            </div>
            <p className="text-[11px] text-slate-600 mt-1">
              Crée un snapshot tous les <strong>dimanches à 03:00</strong> (heure d'Abidjan), conservé sous l'étiquette <code>auto</code>. Rotation automatique : seuls les <strong>{autoKeep} plus récents</strong> sont conservés. Les snapshots créés à la main ne sont jamais supprimés.
            </p>
            {s.auto_snapshot_last_run_at && (
              <p className="text-[11px] text-slate-500 mt-1" data-testid="snapshot-auto-last-run">
                Dernière exécution : <strong>{new Date(s.auto_snapshot_last_run_at).toLocaleString("fr-FR")}</strong>
                {s.auto_snapshot_last_run_trigger ? <span className="ml-1 text-slate-400">({s.auto_snapshot_last_run_trigger})</span> : null}
              </p>
            )}
          </div>
          <label className="inline-flex items-center gap-2 text-xs text-slate-700 shrink-0 select-none">
            <input
              type="checkbox"
              checked={autoEnabled}
              disabled={autoSaving}
              onChange={(e) => { upd("auto_snapshot_enabled", e.target.checked); saveAutoSettings({ auto_snapshot_enabled: e.target.checked }); }}
              data-testid="snapshot-auto-toggle"
            />
            <span className={autoEnabled ? "text-emerald-700 font-semibold" : "text-slate-500"}>{autoEnabled ? "Activé" : "Désactivé"}</span>
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-xs text-slate-700">
            <span className="block font-semibold mb-1">Nombre à conserver (rotation)</span>
            <input
              type="number"
              min={1}
              max={52}
              value={autoKeep}
              disabled={autoSaving}
              onChange={(e) => upd("auto_snapshot_keep", parseInt(e.target.value || "4", 10))}
              onBlur={(e) => saveAutoSettings({ auto_snapshot_keep: parseInt(e.target.value || "4", 10) })}
              className="w-24 rounded border border-slate-300 px-2 py-1.5 text-xs"
              data-testid="snapshot-auto-keep"
            />
          </label>
          <button
            onClick={runAutoNow}
            disabled={autoRunning}
            className="inline-flex items-center gap-2 rounded-lg ring-1 ring-emerald-300 bg-emerald-50 hover:bg-emerald-100 text-emerald-800 px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
            data-testid="snapshot-auto-run-now"
          >
            <RefreshCw className={`h-3 w-3 ${autoRunning ? "animate-spin" : ""}`} />
            {autoRunning ? "Lancement…" : "Lancer maintenant"}
          </button>
        </div>

        {/* Email delivery */}
        <div className="rounded ring-1 ring-slate-200 bg-slate-50 p-3 space-y-2" data-testid="snapshot-auto-email-block">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-700 inline-flex items-center gap-1.5">
              <Mail className="h-3 w-3" /> Envoi par email (copie offsite)
            </div>
            <label className="inline-flex items-center gap-2 text-[11px] text-slate-700 select-none">
              <input
                type="checkbox"
                checked={!!s.auto_snapshot_email_enabled}
                disabled={autoSaving}
                onChange={(e) => { upd("auto_snapshot_email_enabled", e.target.checked); saveAutoSettings({ auto_snapshot_email_enabled: e.target.checked }); }}
                data-testid="snapshot-auto-email-toggle"
              />
              <span>{s.auto_snapshot_email_enabled ? "Activé" : "Désactivé"}</span>
            </label>
          </div>
          <input
            type="email"
            value={s.auto_snapshot_email_to || ""}
            onChange={(e) => upd("auto_snapshot_email_to", e.target.value)}
            onBlur={(e) => saveAutoSettings({ auto_snapshot_email_to: e.target.value })}
            placeholder="admin@votreentreprise.com"
            className="w-full rounded border border-slate-300 px-2 py-1.5 text-xs bg-white"
            data-testid="snapshot-auto-email-to"
          />
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                apiClient.get("/admin/snapshots/weekly-report-preview", { responseType: "blob" })
                  .then((r) => {
                    const blobUrl = window.URL.createObjectURL(new Blob([r.data], { type: "application/pdf" }));
                    window.open(blobUrl, "_blank");
                    setTimeout(() => window.URL.revokeObjectURL(blobUrl), 60000);
                  })
                  .catch((err) => toast.error(err?.response?.data?.detail || "Erreur"));
              }}
              className="inline-flex items-center gap-1 rounded ring-1 ring-slate-300 bg-white hover:bg-slate-100 px-2 py-1 text-[11px] font-semibold text-slate-700"
              data-testid="snapshot-weekly-report-preview"
            >
              <FileArchive className="h-3 w-3" /> Aperçu du rapport PDF
            </button>
          </div>
          <p className="text-[10px] text-slate-500 leading-snug">
            Le fichier <code>.json.gz</code> et le <strong>rapport PDF hebdomadaire</strong> (KPIs, état de la plateforme, derniers contacts) seront joints au message. Nécessite que <strong>SMTP</strong> soit configuré dans les paramètres.
            {s.auto_snapshot_last_email_sent === false && s.auto_snapshot_email_enabled && (
              <span className="block text-rose-600 mt-0.5" data-testid="snapshot-auto-email-warn">
                Le dernier envoi a échoué — vérifiez SMTP et l'adresse.
              </span>
            )}
            {s.auto_snapshot_last_email_sent === true && s.auto_snapshot_last_email_to && (
              <span className="block text-emerald-700 mt-0.5" data-testid="snapshot-auto-email-ok">
                Dernier envoi OK → <strong>{s.auto_snapshot_last_email_to}</strong>
              </span>
            )}
          </p>
        </div>
      </div>

      {/* Export */}
      <div className="rounded-lg ring-1 ring-sky-200 bg-white p-4 space-y-3" data-testid="snapshot-export-card">
        <div className="text-xs font-semibold uppercase tracking-wider text-sky-700 flex items-center gap-1.5"><FileArchive className="h-3.5 w-3.5" /> Créer un nouveau snapshot</div>
        <input
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="Commentaire (ex: avant migration v2.4)"
          maxLength={500}
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          data-testid="snapshot-comment-input"
        />
        <div className="flex flex-wrap items-center gap-3">
          <label className="inline-flex items-center gap-2 text-xs text-slate-700">
            <input
              type="checkbox"
              checked={maskSecrets}
              onChange={(e) => setMaskSecrets(e.target.checked)}
              data-testid="snapshot-mask-toggle"
            />
            Masquer les tokens et secrets API
          </label>
          <button
            onClick={create}
            disabled={creating}
            className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm font-semibold hover:bg-sawali-blue-light disabled:opacity-50"
            data-testid="snapshot-create-btn"
          >
            <Save className="h-4 w-4" />
            {creating ? "Création…" : "Créer le snapshot maintenant"}
          </button>
        </div>
      </div>

      {/* History */}
      <div className="rounded-lg ring-1 ring-slate-200 bg-white overflow-hidden" data-testid="snapshot-history-card">
        <div className="px-3 py-2 bg-slate-50 font-semibold uppercase tracking-wider text-[10px] text-slate-600 flex items-center justify-between">
          <span>Historique ({list.length})</span>
          <span className="font-normal normal-case text-slate-400">Ordonné du plus récent au plus ancien</span>
        </div>
        {list.length === 0 ? (
          <p className="px-3 py-6 text-center text-xs text-slate-400 italic">Aucun snapshot pour le moment.</p>
        ) : (
          <ul className="divide-y divide-slate-100 max-h-72 overflow-y-auto text-xs">
            {list.map((s) => (
              <li key={s.id} className="px-3 py-2 flex flex-col sm:flex-row sm:items-center gap-2" data-testid={`snapshot-row-${s.id}`}>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-mono text-[11px] text-slate-700">{new Date(s.created_at).toLocaleString("fr-FR")}</span>
                    <span className="text-slate-400">•</span>
                    <span className="text-slate-600">{s.author_email}</span>
                    <span className="text-slate-400">•</span>
                    <span className="font-semibold text-slate-700">{formatBytes(s.size_bytes)}</span>
                    <span className="text-slate-400">•</span>
                    <span className="text-slate-500">{s.total_documents} docs</span>
                    {s.kind === "auto" ? <span className="rounded bg-emerald-100 text-emerald-700 px-1.5 py-0.5 text-[9px] font-bold">AUTO</span> : <span className="rounded bg-slate-100 text-slate-600 px-1.5 py-0.5 text-[9px] font-bold">MANUEL</span>}
                    {s.mask_secrets ? <span className="rounded bg-emerald-100 text-emerald-700 px-1.5 py-0.5 text-[9px] font-bold">SECRETS MASQUÉS</span> : <span className="rounded bg-amber-100 text-amber-800 px-1.5 py-0.5 text-[9px] font-bold">SECRETS BRUTS</span>}
                  </div>
                  {editing?.id === s.id ? (
                    <div className="mt-1 flex items-center gap-2">
                      <input
                        autoFocus
                        value={editing.comment}
                        onChange={(e) => setEditing({ ...editing, comment: e.target.value })}
                        onKeyDown={(e) => { if (e.key === "Enter") saveComment(); if (e.key === "Escape") setEditing(null); }}
                        className="flex-1 rounded border border-slate-300 px-2 py-1 text-xs"
                        data-testid={`snapshot-edit-input-${s.id}`}
                      />
                      <button onClick={saveComment} className="text-[11px] text-emerald-700 font-semibold" data-testid={`snapshot-edit-save-${s.id}`}>Enregistrer</button>
                      <button onClick={() => setEditing(null)} className="text-[11px] text-slate-500">Annuler</button>
                    </div>
                  ) : (
                    <div className="mt-0.5 text-slate-600 italic flex items-center gap-1.5">
                      <span className="truncate">{s.comment || <span className="text-slate-300">(aucun commentaire)</span>}</span>
                      <button onClick={() => setEditing({ id: s.id, comment: s.comment || "" })} className="text-slate-400 hover:text-sawali-blue shrink-0" title="Modifier le commentaire" data-testid={`snapshot-edit-btn-${s.id}`}>
                        <Pencil className="h-3 w-3" />
                      </button>
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    onClick={() => download(s)}
                    className="inline-flex items-center gap-1 rounded bg-sky-600 hover:bg-sky-700 text-white px-2 py-1 text-[11px] font-semibold"
                    title="Télécharger"
                    data-testid={`snapshot-download-${s.id}`}
                  >
                    <Download className="h-3 w-3" /> Télécharger
                  </button>
                  <button
                    onClick={() => removeSnap(s)}
                    className="inline-flex items-center gap-1 rounded border border-rose-300 text-rose-700 hover:bg-rose-50 px-2 py-1 text-[11px] font-semibold"
                    title="Supprimer"
                    data-testid={`snapshot-delete-${s.id}`}
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Import */}
      <div className="rounded-lg ring-1 ring-amber-200 bg-amber-50/60 p-4 space-y-3" data-testid="snapshot-import-card">
        <div className="text-xs font-semibold uppercase tracking-wider text-amber-700 flex items-center gap-1.5"><Upload className="h-3.5 w-3.5" /> Importer un snapshot</div>
        <p className="text-[11px] text-slate-600">
          Téléversez un fichier <code>.json.gz</code> (ou <code>.json</code>) précédemment exporté depuis la prod.
          Activez d'abord le mode <strong>Aperçu (dry-run)</strong> pour voir l'impact sans écrire.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-xs text-slate-700">
            <span className="block font-semibold mb-1">Mode</span>
            <select
              value={importMode}
              onChange={(e) => setImportMode(e.target.value)}
              className="rounded border border-slate-300 px-2 py-1.5 text-xs bg-white"
              data-testid="snapshot-import-mode"
            >
              <option value="replace">Remplacer (vide puis ré-insère)</option>
              <option value="merge">Fusionner (upsert par id/email)</option>
            </select>
          </label>
          <label className="inline-flex items-center gap-2 text-xs text-slate-700">
            <input
              type="checkbox"
              checked={importDryRun}
              onChange={(e) => setImportDryRun(e.target.checked)}
              data-testid="snapshot-import-dryrun"
            />
            Aperçu (dry-run, n'écrit rien)
          </label>
          <input
            value={importComment}
            onChange={(e) => setImportComment(e.target.value)}
            placeholder="Commentaire (optionnel)"
            maxLength={500}
            className="flex-1 min-w-[200px] rounded border border-slate-300 px-2 py-1.5 text-xs"
            data-testid="snapshot-import-comment"
          />
        </div>
        <div className="flex items-center gap-2">
          <input ref={fileInputRef} type="file" accept=".gz,.json,application/gzip,application/json" className="hidden" onChange={onFileChange} data-testid="snapshot-import-file-input" />
          <button
            onClick={onPickFile}
            disabled={importing}
            className="inline-flex items-center gap-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white px-4 py-2 text-sm font-semibold disabled:opacity-50"
            data-testid="snapshot-import-btn"
          >
            <Upload className="h-4 w-4" />
            {importing ? "Import en cours…" : "Choisir un fichier et importer"}
          </button>
        </div>

        {/* Iter35j — upload progress bar (visible during file transfer) */}
        {importing && uploadProgress > 0 && uploadProgress < 100 && (
          <div className="mt-2" data-testid="snapshot-upload-progress">
            <div className="flex items-center justify-between text-xs text-slate-600 mb-1">
              <span>📤 Transfert du fichier…</span>
              <span className="font-mono font-semibold">{uploadProgress}%</span>
            </div>
            <div className="h-2 rounded bg-slate-200 overflow-hidden">
              <div className="h-full bg-amber-500 transition-all" style={{ width: `${uploadProgress}%` }} />
            </div>
          </div>
        )}
        {importing && uploadProgress >= 100 && (
          <div className="mt-2 rounded bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-900" data-testid="snapshot-applying">
            ⏳ Application du snapshot sur la base… (peut prendre jusqu'à 5 min pour les grosses bases — ne fermez pas la page)
          </div>
        )}

        {lastImport && (
          <div className="space-y-2" data-testid="snapshot-import-summary">
            {/* Iter35c — prominent global status banner */}
            {lastImport.error ? (
              <div className="rounded-lg p-4 bg-rose-50 ring-2 ring-rose-300 text-rose-900" data-testid="snapshot-import-banner-error">
                <p className="font-semibold text-base mb-1">❌ Échec de l'importation</p>
                <p className="text-sm">{lastImport.error}</p>
              </div>
            ) : (() => {
              const summary = lastImport.summary || {};
              const errorCount = Object.values(summary).filter((v) => v?.action === "error").length;
              const impacted = Object.values(summary).filter((v) => (v?.incoming || 0) > 0 || (v?.action || "") === "replaced" || (v?.action || "") === "merged").length;
              const isDry = lastImport.dry_run;
              const allOk = errorCount === 0 && !isDry;
              const palette = isDry
                ? "bg-sky-50 ring-sky-300 text-sky-900"
                : errorCount > 0
                ? "bg-amber-50 ring-amber-300 text-amber-900"
                : "bg-emerald-50 ring-emerald-300 text-emerald-900";
              const icon = isDry ? "🔍" : errorCount > 0 ? "⚠️" : "✅";
              const headline = isDry
                ? `Aperçu (dry-run) — ${impacted} collection(s) seraient impactée(s)`
                : errorCount > 0
                ? `Import terminé avec ${errorCount} erreur(s)`
                : `Import appliqué avec succès — ${impacted} collection(s) impactée(s)`;
              return (
                <div className={`rounded-lg p-4 ring-2 ${palette}`} data-testid={`snapshot-import-banner-${isDry ? "dry" : errorCount > 0 ? "warn" : "ok"}`}>
                  <p className="font-semibold text-base mb-1">{icon} {headline}</p>
                  <p className="text-xs">Mode : <b>{lastImport.mode}</b> · Import ID : <code className="font-mono">{lastImport.import_id}</code></p>
                  {/* Notification dispatch status (real imports only) */}
                  {!isDry && lastImport.notifications && (
                    <div className="mt-2 grid sm:grid-cols-2 gap-2 text-xs">
                      <div className={`rounded px-2 py-1.5 bg-white ring-1 ${lastImport.notifications.email?.sent ? "ring-emerald-300" : "ring-rose-300"}`} data-testid="snapshot-import-email-status">
                        <span className="font-semibold">📧 Email : </span>
                        {lastImport.notifications.email?.sent ? (
                          <span className="text-emerald-700">envoyé à <code>{lastImport.notifications.email.to}</code></span>
                        ) : (
                          <span className="text-rose-700">
                            non envoyé — {lastImport.notifications.email?.error || "raison inconnue"}
                          </span>
                        )}
                      </div>
                      <div className={`rounded px-2 py-1.5 bg-white ring-1 ${lastImport.notifications.whatsapp?.any_sent ? "ring-emerald-300" : "ring-amber-300"}`} data-testid="snapshot-import-wa-status">
                        <span className="font-semibold">💬 WhatsApp : </span>
                        {lastImport.notifications.whatsapp?.any_sent ? (
                          <span className="text-emerald-700">
                            envoyé à {lastImport.notifications.whatsapp.attempts.filter((a) => a.ok).length}/{lastImport.notifications.whatsapp.attempts.length} destinataire(s)
                          </span>
                        ) : (lastImport.notifications.whatsapp?.attempts?.length || 0) > 0 ? (
                          <span className="text-amber-700">
                            tentatives échouées ({lastImport.notifications.whatsapp.attempts.length}) — {lastImport.notifications.whatsapp.attempts[0]?.error || "hors fenêtre 24h ?"}
                          </span>
                        ) : (
                          <span className="text-slate-500">{lastImport.notifications.whatsapp?.error || "aucun destinataire configuré"}</span>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })()}

            {/* Per-collection table */}
            {!lastImport.error && (
              <div className={`rounded p-3 text-xs ${lastImport.dry_run ? "bg-sky-50 ring-1 ring-sky-200" : "bg-emerald-50 ring-1 ring-emerald-200"}`}>
                <p className="font-semibold mb-1 text-slate-700">Détail par collection</p>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5 text-[11px]">
                  {Object.entries(lastImport.summary || {}).filter(([, v]) => (v.incoming || 0) > 0 || (v.before || 0) > 0 || v.action === "error").map(([k, v]) => (
                    <div key={k} className={`rounded px-2 py-1 ring-1 font-mono ${v.action === "error" ? "bg-rose-50 ring-rose-300" : "bg-white ring-slate-200"}`} data-testid={`snapshot-import-row-${k}`}>
                      <div className="font-semibold text-slate-700 flex items-center gap-1">
                        {k}
                        {v.action === "error" && <span className="text-rose-600">⚠️</span>}
                      </div>
                      {v.action === "error" ? (
                        <div className="text-rose-600 text-[10px]">{v.error}</div>
                      ) : (
                        <div className="text-slate-500">avant {v.before} → après {v.after ?? "—"} (entrant {v.incoming})</div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {imports.length > 0 && (
          <details className="text-xs">
            <summary className="cursor-pointer text-slate-600 hover:text-slate-900 font-semibold">Historique des imports ({imports.length})</summary>
            <ul className="mt-2 divide-y divide-slate-100 ring-1 ring-slate-200 rounded bg-white max-h-40 overflow-y-auto">
              {imports.map((it) => (
                <li key={it.id} className="px-2 py-1.5 flex items-center justify-between gap-2" data-testid={`snapshot-import-log-${it.id}`}>
                  <span className="font-mono text-[10px]">{new Date(it.created_at).toLocaleString("fr-FR")}</span>
                  <span className="text-slate-600 truncate">{it.author_email} • {it.mode}{it.dry_run ? " (dry-run)" : ""}</span>
                  <span className="text-slate-400 truncate italic max-w-[40%]">{it.comment || "—"}</span>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </div>
    </Filterable>
  );
};


const OrphanDataSection = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);

  const inspect = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/migrate-orphan-data");
      setData(r.data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setLoading(false); }
  };
  useEffect(() => { inspect(); }, []);

  const apply = async () => {
    if (!window.confirm("Confirmer la migration ? Cette action re-tague les données orphelines vers le bon client_id (avec champ client_id_legacy conservé pour traçabilité).")) return;
    setApplying(true);
    try {
      const r = await apiClient.post("/admin/migrate-orphan-data");
      toast.success(`Migration appliquée : ${r.data.total_migrated} document(s) re-tagué(s) sur ${r.data.affected_users.length} utilisateur(s).`);
      setData({ ...r.data, dry_run: true });  // refetch as dry-run for the canary
      inspect();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setApplying(false); }
  };

  const total = data?.total_migrated ?? 0;
  const collections = data?.per_collection_totals || {};
  const users = data?.affected_users || [];
  const TITLE = "Diagnostic des données orphelines";

  return (
    <Filterable title={TITLE} anchorId={`s-${slugify(TITLE)}`}>
    <div className="rounded-xl border-2 border-amber-200 bg-amber-50/40 p-6 space-y-3" data-testid="admin-orphan-data-section">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Wrench className="h-4 w-4 text-amber-600" />
          <h2 className="font-display font-semibold">
            Diagnostic des données orphelines
            {total === 0 && data && <CheckCircle2 className="inline h-4 w-4 text-emerald-600 ml-2" />}
            {total > 0 && <AlertCircle className="inline h-4 w-4 text-rose-600 ml-2 animate-pulse" />}
          </h2>
        </div>
        <button
          onClick={inspect}
          disabled={loading}
          className="text-xs inline-flex items-center gap-1 text-slate-500 hover:text-slate-900 transition"
          data-testid="orphan-refresh-btn"
        >
          <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} /> Actualiser
        </button>
      </div>
      <p className="text-xs text-slate-600">
        Détecte les contacts/messages/SMS/planifications/liens-de-paiement encore tagués avec l'<code className="font-mono">id</code> d'un utilisateur suivi
        au lieu de son <code className="font-mono">parent_client_id</code>. Ces rows sont invisibles à leur propriétaire.
        La migration les re-tague vers le client parent et conserve l'ancien <code className="font-mono">client_id</code> dans <code className="font-mono">client_id_legacy</code>.
      </p>

      {data === null ? (
        <p className="text-xs text-slate-400 italic">Chargement…</p>
      ) : total === 0 ? (
        <div className="rounded-lg ring-1 ring-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-900 inline-flex items-center gap-2" data-testid="orphan-status-clean">
          <CheckCircle2 className="h-4 w-4" />
          <span><strong>Aucune donnée orpheline détectée.</strong> Tout est cohérent.</span>
        </div>
      ) : (
        <div className="space-y-3" data-testid="orphan-status-found">
          <div className="rounded-lg ring-1 ring-rose-200 bg-rose-50 p-3 text-xs text-rose-900">
            <p className="font-semibold mb-1">⚠️ {total} document(s) orphelin(s) détecté(s) sur {users.length} utilisateur(s)</p>
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 mt-2">
              {Object.entries(collections).map(([k, v]) => (
                <div key={k} className="bg-white rounded px-2 py-1 ring-1 ring-rose-200">
                  <div className="text-[9px] uppercase tracking-wider text-slate-500">{k.replace(/_/g, " ")}</div>
                  <div className={`font-mono font-bold ${v > 0 ? "text-rose-700" : "text-slate-400"}`}>{v}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-lg ring-1 ring-slate-200 bg-white text-xs overflow-hidden">
            <div className="px-3 py-2 bg-slate-50 font-semibold uppercase tracking-wider text-[10px] text-slate-600">Utilisateurs affectés</div>
            <ul className="divide-y divide-slate-100 max-h-40 overflow-y-auto">
              {users.map((u) => (
                <li key={u.user_id} className="px-3 py-1.5 flex items-center justify-between">
                  <span className="truncate"><strong>{u.user_label}</strong> <span className="text-slate-400">({u.user_email})</span></span>
                  <span className="text-[10px] font-mono text-slate-500 shrink-0">
                    {Object.entries(u.per_collection).filter(([, v]) => v > 0).map(([k, v]) => `${k.split("_")[0]}:${v}`).join(" ")}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <button
            onClick={apply}
            disabled={applying || loading}
            className="inline-flex items-center gap-2 rounded-lg bg-rose-600 hover:bg-rose-700 text-white px-4 py-2 text-sm font-semibold disabled:opacity-50"
            data-testid="orphan-apply-btn"
          >
            <Database className="h-4 w-4" />
            {applying ? "Application en cours…" : `Appliquer la migration (${total} document(s))`}
          </button>
        </div>
      )}
    </div>
    </Filterable>
  );
};


const Section = ({ icon: Icon, title, children }) => {
  const anchorId = `s-${slugify(title)}`;
  return (
    <Filterable title={title} anchorId={anchorId}>
      <div className="rounded-xl border border-slate-200 bg-white p-6 space-y-3" data-section-title={title}>
        <div className="flex items-center gap-2">
          {Icon && <Icon className="h-4 w-4 text-sawali-blue" />}
          <h2 className="font-display font-semibold">{title}</h2>
        </div>
        {children}
      </div>
    </Filterable>
  );
};
const Input = ({ label, value, onChange, type = "text", placeholder, testid }) => {
  const handleFocus = (e) => {
    // If value is the masked sentinel, clear it on focus so the user can type a new one
    if (value === "********") onChange("");
  };
  return (
  <div>
    <label className="block text-xs font-semibold mb-1">{label}</label>
    {type === "password" ? (
      <PasswordInput
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={handleFocus}
        placeholder={placeholder}
        className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
        autoComplete="new-password"
        testid={testid}
      />
    ) : (
      <input type={type} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid={testid} />
    )}
  </div>
  );
};

// Iter43-fix23 — Affiche une URL complète (origine + path + secret optionnel) avec bouton Copier.
// Iter43-fix24e — Utilise `public_base_url` du settings en priorité ; permet aussi d'éditer manuellement.
const CopyableUrl = ({ label, path, secret, baseUrl }) => {
  const FALLBACK = process.env.REACT_APP_BACKEND_URL || "";
  const origin = (baseUrl && baseUrl.trim()) || FALLBACK;
  const cleanOrigin = origin.replace(/\/$/, "");
  const fullUrl = `${cleanOrigin}${path}${secret && secret !== "********" ? `?secret=${encodeURIComponent(secret)}` : ""}`;
  return (
    <div className="space-y-1">
      <p className="text-[11px] text-slate-600">{label}</p>
      <div className="flex items-stretch gap-1">
        <input
          readOnly
          value={fullUrl}
          className="flex-1 px-2 py-1 text-xs font-mono bg-white border border-slate-300 rounded text-slate-700"
          onClick={(e) => e.target.select()}
        />
        <button
          type="button"
          onClick={() => {
            navigator.clipboard.writeText(fullUrl);
            toast.success("URL copiée");
          }}
          className="px-2 py-1 rounded bg-sawali-blue text-white text-xs hover:bg-sawali-blue/90 inline-flex items-center gap-1"
          title="Copier l'URL"
        >
          <Copy className="h-3 w-3" />
        </button>
      </div>
    </div>
  );
};

// Iter43-fix24l (2026-06) — Composant de test SMS Bird (envoi réel + diagnostics)
const BirdTestSmsBlock = ({ defaultSender }) => {
  const [to, setTo] = useState("");
  const [text, setText] = useState("Test Bird SAWALI ✓");
  const [sender, setSender] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);

  const runTest = async () => {
    if (!to.trim()) {
      toast.error("Numéro destinataire requis");
      return;
    }
    setLoading(true);
    setResult(null);
    try {
      const r = await apiClient.post("/admin/bird/test-sms", {
        to: to.trim(),
        text: text.trim() || "Test Bird SAWALI ✓",
        sender: sender.trim() || undefined,
      });
      setResult(r.data);
      if (r.data?.ok) {
        toast.success(`SMS test envoyé (HTTP ${r.data.response?.http_status})`);
      } else {
        toast.error("Test échoué — voir détails");
      }
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.message || "Erreur inconnue";
      setResult({ ok: false, error: detail, verdict: `❌ ${detail}` });
      toast.error("Test échoué");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="rounded-lg ring-1 ring-emerald-300 bg-emerald-50/40 p-3 mt-3 space-y-3" data-testid="bird-test-sms-block">
      <h4 className="text-xs font-semibold text-emerald-900 inline-flex items-center gap-1.5">
        🧪 Tester l'envoi SMS Bird
      </h4>
      <p className="text-[10px] text-emerald-900/70 leading-relaxed">
        Envoie un VRAI SMS au numéro indiqué et affiche le code HTTP + la réponse complète de Bird.
        Idéal pour valider workspace_id / channel_id / access_key avant activation en production.
        Ce test n'écrit PAS dans l'historique des messages.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
        <label className="block md:col-span-1">
          <span className="block text-[10px] uppercase tracking-wider font-semibold text-emerald-900">Destinataire (E.164)</span>
          <input
            type="text"
            value={to}
            onChange={(e) => setTo(e.target.value)}
            placeholder="+22670123456"
            className="w-full mt-1 text-xs font-mono rounded border border-emerald-300 px-2 py-1.5 bg-white"
            data-testid="bird-test-to"
          />
        </label>
        <label className="block md:col-span-1">
          <span className="block text-[10px] uppercase tracking-wider font-semibold text-emerald-900">
            Expéditeur (optionnel)
          </span>
          <input
            type="text"
            value={sender}
            onChange={(e) => setSender(e.target.value)}
            placeholder={defaultSender || "SAWALI"}
            className="w-full mt-1 text-xs font-mono rounded border border-emerald-300 px-2 py-1.5 bg-white"
            data-testid="bird-test-sender"
          />
        </label>
        <label className="block md:col-span-1">
          <span className="block text-[10px] uppercase tracking-wider font-semibold text-emerald-900">Message</span>
          <input
            type="text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            maxLength={160}
            className="w-full mt-1 text-xs rounded border border-emerald-300 px-2 py-1.5 bg-white"
            data-testid="bird-test-text"
          />
        </label>
      </div>
      <button
        type="button"
        onClick={runTest}
        disabled={loading || !to.trim()}
        className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white text-xs font-semibold px-3 py-1.5"
        data-testid="bird-test-run"
      >
        {loading ? "Envoi en cours…" : "🧪 Envoyer le SMS test"}
      </button>
      {result && (
        <div
          className={`rounded-lg p-3 ring-1 text-xs space-y-2 ${
            result.ok ? "bg-white ring-emerald-300" : "bg-rose-50 ring-rose-300"
          }`}
          data-testid="bird-test-result"
        >
          <p className={`font-semibold ${result.ok ? "text-emerald-700" : "text-rose-700"}`} data-testid="bird-test-verdict">
            {result.verdict || (result.ok ? "✅ Succès" : "❌ Échec")}
          </p>
          {result.config_check && (
            <details className="text-[11px]">
              <summary className="cursor-pointer text-slate-600">Vérification config</summary>
              <pre className="bg-slate-50 rounded p-2 mt-1 overflow-auto whitespace-pre-wrap font-mono">
                {JSON.stringify(result.config_check, null, 2)}
              </pre>
            </details>
          )}
          {result.request && (
            <details className="text-[11px]">
              <summary className="cursor-pointer text-slate-600">Requête envoyée</summary>
              <pre className="bg-slate-50 rounded p-2 mt-1 overflow-auto whitespace-pre-wrap font-mono">
                {JSON.stringify(result.request, null, 2)}
              </pre>
            </details>
          )}
          {result.response && (
            <details className="text-[11px]" open>
              <summary className="cursor-pointer text-slate-600">
                Réponse Bird (HTTP <strong data-testid="bird-test-http-status">{result.response.http_status}</strong> · {result.response.latency_ms} ms)
              </summary>
              <pre className="bg-slate-50 rounded p-2 mt-1 overflow-auto whitespace-pre-wrap font-mono max-h-64">
                {JSON.stringify(result.response, null, 2)}
              </pre>
            </details>
          )}
          {result.error && !result.response && (
            <pre className="bg-rose-100 rounded p-2 text-rose-800 whitespace-pre-wrap font-mono">
              {result.error}
            </pre>
          )}
        </div>
      )}
    </div>
  );
};

// Panel that lets the admin probe Meta Graph API live to validate WA config.
const WaTestPanel = () => {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const run = async () => {
    setLoading(true);
    setResult(null);
    try {
      const r = await apiClient.post("/admin/whatsapp/test-config");
      setResult(r.data);
      if (r.data?.ok) toast.success("Paramètres WhatsApp valides");
      else toast.error("Un ou plusieurs paramètres sont invalides");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur pendant le test");
    } finally {
      setLoading(false);
    }
  };
  return (
    <div className="rounded-lg border border-dashed border-sawali-blue/40 bg-sky-50/50 p-4 space-y-3" data-testid="wa-test-panel">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="text-xs text-slate-600">
          <p className="font-semibold text-slate-800">Valider la configuration Meta</p>
          <p>Lance un appel en direct vers Graph API pour vérifier que votre WABA, votre numéro et votre token fonctionnent, avant d'envoyer des messages réels.</p>
          <p className="text-[11px] text-amber-700 mt-1">Astuce : enregistrez d'abord vos modifications avec le bouton "Enregistrer" en bas de page.</p>
        </div>
        <button
          type="button"
          onClick={run}
          disabled={loading}
          data-testid="wa-test-btn"
          className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue px-3 py-2 text-xs font-semibold text-white hover:brightness-110 disabled:opacity-60"
        >
          {loading ? <RotateCcw className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
          {loading ? "Test en cours…" : "Tester la connexion Meta"}
        </button>
      </div>
      {result && (
        <div className="space-y-1.5" data-testid="wa-test-result">
          <p className={`text-xs font-semibold ${result.ok ? "text-emerald-700" : "text-rose-700"}`}>{result.summary}</p>
          <ul className="space-y-1">
            {(result.checks || []).map((c, i) => (
              <li key={i} className="flex items-start gap-2 text-xs" data-testid={`wa-test-check-${c.key}`}>
                {c.ok ? <CheckCircle2 className="h-4 w-4 text-emerald-600 flex-shrink-0 mt-0.5" /> : <AlertCircle className="h-4 w-4 text-rose-600 flex-shrink-0 mt-0.5" />}
                <div>
                  <span className="font-semibold text-slate-800">{c.label}</span>
                  <span className="text-slate-600"> — {c.detail}</span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

// Iter35a — Webhook payloads inspector. Show the last N raw payloads Meta
// has pushed to /api/whatsapp/webhook so the admin can debug "I'm not
// receiving messages" without server log access. Each row is collapsible


// Iter43-fix3 (2026-03) — Diagnostic du token WhatsApp Cloud API.
// Pattern « marche 2 jours puis ne marche plus » = token utilisateur 24h.
const WaTokenHealthPanel = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const run = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/whatsapp/token-health");
      setData(r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    } finally { setLoading(false); }
  };
  useEffect(() => { run(); }, []);

  const colorByStatus = () => {
    if (!data) return "bg-slate-50 ring-slate-200";
    if (data.ok) return "bg-emerald-50 ring-emerald-200";
    return "bg-rose-50 ring-rose-200";
  };
  return (
    <div className={`rounded-xl ring-1 p-4 space-y-2 ${colorByStatus()}`} data-testid="wa-token-health-panel">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-slate-800">🔐 Diagnostic du token WhatsApp</p>
        <button onClick={run} disabled={loading}
                className="text-xs px-3 py-1 rounded bg-white ring-1 ring-slate-300 hover:bg-slate-50 disabled:opacity-50"
                data-testid="wa-token-health-refresh">
          {loading ? "Diagnostic…" : "Vérifier maintenant"}
        </button>
      </div>
      {!data && !loading && (
        <p className="text-xs text-slate-500">Cliquez sur « Vérifier maintenant »</p>
      )}
      {data && (
        <div className="text-xs grid sm:grid-cols-2 gap-2">
          <div>
            <span className="text-slate-500">État :</span>{" "}
            {data.ok
              ? <span className="text-emerald-700 font-semibold">✅ Token valide</span>
              : <span className="text-rose-700 font-semibold">❌ Token invalide / configuration incorrecte</span>}
          </div>
          <div>
            <span className="text-slate-500">Type :</span>{" "}
            <strong className={data.token_type === "SYSTEM_USER" ? "text-emerald-700" : "text-amber-700"}>
              {data.token_type || "—"}
            </strong>
            {data.token_type === "USER" && <span className="ml-1 text-amber-600">⚠️ recommandé : SYSTEM_USER</span>}
          </div>
          <div>
            <span className="text-slate-500">Expiration :</span>{" "}
            {data.expires_at
              ? <span className={data.days_to_expiry < 7 ? "text-rose-700 font-semibold" : "text-slate-700"}>
                  {new Date(data.expires_at).toLocaleString("fr-FR")} ({data.days_to_expiry} j)
                </span>
              : <span className="text-emerald-700">Permanent (n'expire pas)</span>}
          </div>
          <div>
            <span className="text-slate-500">App ID :</span>{" "}
            <code className="font-mono text-slate-700">{data.app_id || "—"}</code>
          </div>
          {data.phone_check && (
            <div className="sm:col-span-2 bg-white/60 ring-1 ring-slate-200 rounded p-2 mt-1">
              <p className="font-semibold text-slate-700 mb-0.5">Test fonctionnel sur le Phone Number ID</p>
              {data.phone_check.ok ? (
                <p className="text-emerald-700">
                  ✅ {data.phone_check.display_phone_number} — {data.phone_check.verified_name}
                  {data.phone_check.quality_rating && <span className="ml-2 text-[10px]">Quality : <strong>{data.phone_check.quality_rating}</strong></span>}
                </p>
              ) : (
                <p className="text-rose-700">❌ {data.phone_check.error} {data.phone_check.error_code && `(code ${data.phone_check.error_code})`}</p>
              )}
            </div>
          )}
          {data.warning && (
            <div className="sm:col-span-2 rounded-lg ring-1 ring-amber-300 bg-amber-50 p-2 text-amber-900">
              {data.warning}
            </div>
          )}
          {data.message && (
            <div className="sm:col-span-2 rounded-lg ring-1 ring-rose-300 bg-rose-50 p-2 text-rose-900">
              <strong>Erreur Meta :</strong> {data.message}
            </div>
          )}
          {data.scopes?.length > 0 && (
            <div className="sm:col-span-2 text-[11px] text-slate-500">
              <strong>Scopes :</strong> {data.scopes.join(", ")}
            </div>
          )}
          <div className="sm:col-span-2 mt-2 rounded-lg ring-1 ring-sky-200 bg-sky-50 p-2 text-[11px] text-sky-900">
            💡 <strong>Pour éviter les coupures :</strong> utilisez un <strong>System User token permanent</strong> (Meta Business Manager → Paramètres business → Utilisateurs système → Générer un nouveau token → cocher <code>whatsapp_business_messaging</code> + <code>whatsapp_business_management</code> → <strong>SANS expiration</strong>). Les tokens copiés depuis le dashboard Developers expirent en 24 h.
          </div>
        </div>
      )}
    </div>
  );
};

// Iter43-fix16 (2026-06) — Diagnostic + bouton de re-souscription du webhook Meta.
// Symptôme : « les messages WA sortants partent mais on ne reçoit plus rien
// depuis X jours » → Meta a retiré la souscription `messages` de l'app.
const WaWebhookSubscriptionPanel = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [resubLoading, setResubLoading] = useState(false);

  const check = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/whatsapp/webhook-subscription");
      setData(r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur diagnostic souscription");
    } finally {
      setLoading(false);
    }
  };

  const resubscribe = async () => {
    if (!window.confirm(
      "Re-souscrire l'application Meta au webhook ?\n\n"
      + "Action sûre, idempotente. Meta recommencera à envoyer les messages "
      + "entrants vers /api/whatsapp/webhook dans les secondes qui suivent."
    )) return;
    setResubLoading(true);
    try {
      const r = await apiClient.post("/admin/whatsapp/webhook-subscribe");
      if (r.data?.ok) {
        toast.success(r.data.message || "Souscription rétablie");
      } else {
        toast.error(r.data?.message || "Échec de la re-souscription");
      }
      // Rafraîchir le diagnostic
      await check();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur lors de la re-souscription");
    } finally {
      setResubLoading(false);
    }
  };

  const colorByStatus = () => {
    if (!data) return "ring-slate-200 bg-slate-50";
    if (data.ok) return "ring-emerald-200 bg-emerald-50";
    return "ring-rose-200 bg-rose-50";
  };

  return (
    <div className={`rounded-xl ring-1 p-4 space-y-2 ${colorByStatus()}`} data-testid="wa-webhook-subscription-panel">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <p className="text-sm font-semibold text-slate-800">📡 Diagnostic souscription Webhook Meta</p>
        <div className="flex items-center gap-2">
          <button
            onClick={check}
            disabled={loading}
            className="text-xs px-3 py-1 rounded bg-white ring-1 ring-slate-300 hover:bg-slate-50 disabled:opacity-50"
            data-testid="wa-webhook-subscription-check"
          >
            {loading ? "Vérification…" : "Vérifier la souscription"}
          </button>
          {data && !data.ok && (
            <button
              onClick={resubscribe}
              disabled={resubLoading || (data.token_probe && data.token_probe.ok === false)}
              title={
                data.token_probe && data.token_probe.ok === false
                  ? "Le token Meta est invalide ou expiré : régénérez-le d'abord dans Meta Business Manager → Utilisateurs système, puis re-collez-le dans Admin Settings → WhatsApp."
                  : "Re-souscrire l'application Meta au webhook"
              }
              className="text-xs px-3 py-1 rounded bg-amber-600 text-white font-semibold hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed"
              data-testid="wa-webhook-subscription-resubscribe"
            >
              {resubLoading ? "Re-souscription…" : "🔁 Re-souscrire le webhook"}
            </button>
          )}
        </div>
      </div>
      <p className="text-[11px] text-slate-600">
        Vérifie côté Meta si l'app est toujours abonnée aux événements <code>messages</code> du WABA.
        Cause typique du « plus aucun message entrant depuis X jours alors que l'envoi fonctionne ».
      </p>
      {!data && !loading && (
        <p className="text-xs text-slate-500">Cliquez sur « Vérifier la souscription »</p>
      )}
      {data && (
        <div className="text-xs space-y-1">
          <div>
            <span className="text-slate-500">État :</span>{" "}
            {data.ok ? (
              <span className="text-emerald-700 font-semibold">✅ Souscription active</span>
            ) : (
              <span className="text-rose-700 font-semibold">❌ Aucune souscription / problème</span>
            )}
          </div>
          {data.waba_id && (
            <div>
              <span className="text-slate-500">WABA ID :</span>{" "}
              <code className="text-[11px]">{data.waba_id}</code>
            </div>
          )}
          <div>
            <span className="text-slate-500">Apps abonnées :</span>{" "}
            <strong>{(data.subscribed_apps || []).length}</strong>
            {(data.subscribed_apps || []).length === 0 && (
              <span className="ml-1 text-rose-700">→ ⚠️ critique, Meta ne vous appellera plus</span>
            )}
          </div>
          {(data.subscribed_apps || []).length > 0 && (
            <ul className="ml-4 list-disc text-slate-600 text-[11px]">
              {(data.subscribed_apps || []).map((a, i) => (
                <li key={i}>
                  <code>{a.whatsapp_business_api_data?.id || a.name || a.id || "(app)"}</code>
                  {a.whatsapp_business_api_data?.name && (
                    <span className="ml-1 text-slate-500">— {a.whatsapp_business_api_data.name}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
          {data.message && (
            <div className={`mt-1 p-2 rounded text-[11px] ${data.ok ? "bg-white text-slate-700" : "bg-rose-100 text-rose-900"}`}>
              {data.message}
            </div>
          )}
          {data.error_code && (
            <div className="text-[11px] text-slate-500">
              Code Meta : <code>{data.error_code}</code> · Type : <code>{data.error_type || "—"}</code>
            </div>
          )}
          {data.http_status && (
            <div className="text-[11px] text-slate-500">
              HTTP Meta : <code>{data.http_status}</code>
            </div>
          )}
          {/* Iter43-fix24ar (2026-02) — Token probe (résultat de l'appel /me préalable) */}
          {data.token_probe && (
            <div
              className={`mt-1 p-2 rounded text-[11px] ring-1 ${
                data.token_probe.ok
                  ? "bg-emerald-50 ring-emerald-200 text-emerald-900"
                  : "bg-amber-50 ring-amber-300 text-amber-900"
              }`}
              data-testid="wa-webhook-subscription-token-probe"
            >
              <strong>Token Meta :</strong>{" "}
              {data.token_probe.ok ? (
                <>
                  ✅ Valide — utilisateur/app{" "}
                  <code>{data.token_probe.name || data.token_probe.id || "?"}</code>
                </>
              ) : (
                <>
                  ❌ Invalide / expiré
                  {data.token_probe.error_code && <> (code {data.token_probe.error_code})</>}
                  {data.token_probe.error && (
                    <div className="mt-1 font-mono text-[10px]">{data.token_probe.error}</div>
                  )}
                </>
              )}
            </div>
          )}
          {data.raw_response_preview && (
            <details className="text-[11px] text-slate-500">
              <summary className="cursor-pointer">Aperçu de la réponse brute Meta</summary>
              <pre className="mt-1 bg-white p-2 rounded ring-1 ring-slate-200 overflow-auto text-[10px] font-mono whitespace-pre-wrap break-all">{data.raw_response_preview}</pre>
            </details>
          )}
          {data.note && (
            <div className="text-[11px] text-slate-600 italic">{data.note}</div>
          )}
          <div className="mt-2 rounded-lg ring-1 ring-sky-200 bg-sky-50 p-2 text-[11px] text-sky-900">
            💡 Si « Re-souscrire » échoue ou ne suffit pas, ouvrez
            {" "}<a href="https://business.facebook.com/wa/manage/home/" target="_blank" rel="noreferrer"
                    className="underline font-semibold">Meta Business Suite</a>{" "}
            → WhatsApp → Configuration → Webhooks → vérifiez l'URL
            {" "}<code>https://sawalismartsystems.com/api/whatsapp/webhook</code>{" "}
            et que le champ <strong>messages</strong> est bien coché.
          </div>
          {/* Iter43-fix24ar — Test du pipeline interne SANS dépendre de Meta */}
          <WaSimulateInboundPanel />
        </div>
      )}
    </div>
  );
};

// Iter43-fix24ar (2026-02) — Simulate an incoming WhatsApp message END-TO-END
// to verify the pipeline `webhook → whatsapp_messages → inbox → notifs` works
// EVEN IF Meta is not calling our webhook. Useful to isolate whether the bug
// is Meta-side (no inbound calls) or internal (calls received but lost).
const WaSimulateInboundPanel = () => {
  const [phone, setPhone] = useState("+22670112233");
  const [text, setText] = useState("Test pipeline — message simulé");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);

  const run = async () => {
    if (!phone || !text) {
      toast.error("Numéro et message requis");
      return;
    }
    setRunning(true);
    setResult(null);
    try {
      const r = await apiClient.post("/admin/whatsapp/simulate-inbound", {
        from_phone: phone,
        text,
        profile_name: "Sim Admin Test",
      });
      setResult(r.data);
      if (r.data?.ok) {
        toast.success("Message inséré — vérifiez l'inbox unifiée");
      } else {
        toast.warning(r.data?.stage || "Pipeline en erreur");
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur lors de la simulation");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="mt-3 rounded-lg ring-1 ring-violet-200 bg-violet-50/50 p-3 space-y-2"
         data-testid="wa-simulate-inbound-panel">
      <p className="text-xs font-semibold text-slate-700">
        🧪 Tester le pipeline (sans Meta) — synthétise un message entrant et le route à travers le vrai handler
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <div className="flex-1 min-w-[160px]">
          <label className="block text-[10px] text-slate-600 font-semibold mb-0.5">De (E.164)</label>
          <input
            type="text"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="+22670112233"
            className="w-full px-2 py-1 rounded ring-1 ring-slate-300 text-xs font-mono"
            data-testid="wa-simulate-from-phone"
          />
        </div>
        <div className="flex-[2] min-w-[200px]">
          <label className="block text-[10px] text-slate-600 font-semibold mb-0.5">Message</label>
          <input
            type="text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Bonjour SAWALI"
            className="w-full px-2 py-1 rounded ring-1 ring-slate-300 text-xs"
            data-testid="wa-simulate-text"
          />
        </div>
        <button
          onClick={run}
          disabled={running}
          className="text-xs px-3 py-1 rounded bg-violet-600 text-white font-semibold hover:brightness-110 disabled:opacity-50"
          data-testid="wa-simulate-run"
        >
          {running ? "Simulation…" : "▶️ Simuler"}
        </button>
      </div>
      {result && (
        <div className="text-[11px] mt-1 space-y-1" data-testid="wa-simulate-result">
          <div className={result.ok ? "text-emerald-700" : "text-rose-700"}>
            <strong>{result.ok ? "✅ Pipeline OK" : "❌ Pipeline cassé"}</strong>
            {result.stage && <span className="ml-1">— stage: <code>{result.stage}</code></span>}
            {result.error && <div className="font-mono text-[10px]">{result.error}</div>}
          </div>
          {result.inserted && (
            <div className="text-slate-700">
              📥 <strong>Inséré :</strong> tenant <code>{result.inserted.client_id || "?"}</code>{" "}
              · contact_id <code>{result.inserted.contact_id || "—"}</code>
            </div>
          )}
          {result.webhook_log && (
            <div className="text-slate-700">
              📋 <strong>Log webhook :</strong> {result.webhook_log.inserted_messages}/{result.webhook_log.extracted_messages} insérés
              {result.webhook_log.errors?.length > 0 && (
                <span className="ml-1 text-rose-600">
                  · erreurs : {result.webhook_log.errors.join(", ")}
                </span>
              )}
            </div>
          )}
          {result.ai_reply ? (
            <div className="text-slate-700">
              🤖 <strong>AI a répondu :</strong> « {(result.ai_reply.body || "").slice(0, 80)} »
              {result.ai_reply.command && <span className="ml-1 text-slate-500">(cmd: {result.ai_reply.command})</span>}
            </div>
          ) : (
            <div className="text-slate-500 italic">
              🤖 Pas de réponse IA (autoreply désactivé ou cooldown actif)
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// and shows the parsed JSON.
const WaWebhookLogsPanel = () => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [opened, setOpened] = useState({});
  const [expanded, setExpanded] = useState({});

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/whatsapp/webhook-logs?limit=50");
      setItems(r.data?.items || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec du chargement des logs");
    } finally {
      setLoading(false);
    }
  };

  const clearAll = async () => {
    if (!window.confirm("Purger tous les logs de webhook ?")) return;
    try {
      const r = await apiClient.delete("/admin/whatsapp/webhook-logs");
      toast.success(`${r.data?.deleted || 0} logs supprimés`);
      setItems([]);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec");
    }
  };

  return (
    <div className="rounded-lg border border-dashed border-amber-400/60 bg-amber-50/50 p-4 space-y-3" data-testid="wa-webhook-logs-panel">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="text-xs text-slate-600">
          <p className="font-semibold text-slate-800">Inspecter les payloads Meta entrants</p>
          <p>Affiche les 50 derniers appels reçus sur <code className="bg-white px-1 rounded">/api/whatsapp/webhook</code>. Utile quand vos clients vous écrivent et que rien n'apparaît : vous voyez ici si Meta vous appelle bien (et exactement quel JSON il envoie).</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => { setOpened((o) => ({ ...o, root: !o.root })); if (!opened.root) load(); }}
            data-testid="wa-webhook-logs-toggle"
            className="inline-flex items-center gap-2 rounded-lg bg-amber-600 px-3 py-2 text-xs font-semibold text-white hover:brightness-110"
          >
            {opened.root ? "Fermer" : "Charger les payloads"}
          </button>
          {opened.root && (
            <>
              <button
                type="button"
                onClick={load}
                disabled={loading}
                data-testid="wa-webhook-logs-refresh"
                className="inline-flex items-center gap-2 rounded-lg bg-white px-3 py-2 text-xs font-semibold text-slate-700 border hover:bg-slate-50 disabled:opacity-60"
              >
                {loading ? <RotateCcw className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
                Actualiser
              </button>
              <button
                type="button"
                onClick={clearAll}
                data-testid="wa-webhook-logs-clear"
                className="inline-flex items-center gap-2 rounded-lg bg-white px-3 py-2 text-xs font-semibold text-rose-700 border hover:bg-rose-50"
              >
                Purger
              </button>
            </>
          )}
        </div>
      </div>
      {opened.root && (
        <div className="space-y-2" data-testid="wa-webhook-logs-list">
          {loading && <p className="text-xs text-slate-500">Chargement…</p>}
          {!loading && items.length === 0 && (
            <p className="text-xs text-slate-500 italic">Aucun appel reçu. Si vos clients vous écrivent et que ce panneau reste vide, votre webhook n'est pas accessible par Meta (vérifiez l'URL et le Verify Token dans Meta Business Suite → WhatsApp → Configuration).</p>
          )}
          {!loading && items.map((it) => {
            const isExp = expanded[it.id];
            const hasErr = (it.errors || []).length > 0;
            return (
              <div key={it.id} className={`rounded border ${hasErr ? "border-rose-300 bg-rose-50/40" : "border-slate-200 bg-white"} p-2 text-xs`} data-testid={`wa-webhook-log-${it.id}`}>
                <div className="flex items-center justify-between gap-2 cursor-pointer" onClick={() => setExpanded((e) => ({ ...e, [it.id]: !e[it.id] }))}>
                  <div className="flex-1">
                    <span className="font-semibold text-slate-800">{new Date(it.received_at).toLocaleString("fr-FR")}</span>
                    <span className="ml-2 text-slate-500">{it.entry_count} entry{it.entry_count > 1 ? "ies" : "y"} · {it.extracted_messages} msg · {it.extracted_statuses} status · inserted={it.inserted_messages}</span>
                  </div>
                  {hasErr && <span className="rounded bg-rose-100 text-rose-800 px-1.5 py-0.5 text-[10px] font-semibold">{it.errors.length} erreur(s)</span>}
                </div>
                {isExp && (
                  <pre className="mt-2 p-2 bg-slate-900 text-emerald-200 rounded overflow-auto max-h-64 text-[10px] leading-relaxed">{JSON.stringify(it.body, null, 2)}</pre>
                )}
                {isExp && hasErr && (
                  <div className="mt-2 p-2 bg-rose-50 border border-rose-200 rounded text-rose-900">
                    <div className="font-semibold mb-1">Erreurs d'extraction :</div>
                    <ul className="list-disc ml-4">{it.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

// Iter35b — WhatsApp silence detector. Notifies admin (email + optional
// Discord) when our app sends WA messages but receives ZERO webhook hits
// from Meta over the configured window. Catches "Meta stopped calling us"
// failures that would otherwise go undetected for days.
const WaSilenceAlertPanel = ({ s, upd }) => {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [historyOpen, setHistoryOpen] = useState(false);

  const runNow = async () => {
    setRunning(true);
    setResult(null);
    try {
      const r = await apiClient.post("/admin/whatsapp/silence-check");
      setResult(r.data);
      if (r.data?.fired) toast.success("Alerte envoyée (email" + (r.data?.discord_sent ? " + Discord" : "") + ")");
      else if (r.data?.silent) toast(r.data?.throttled_until ? "Alerte récente — anti-spam actif" : "Silence détecté mais alerte non envoyée");
      else toast.success("Tout va bien — Meta vous appelle correctement");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec");
    } finally {
      setRunning(false);
    }
  };

  const loadHistory = async () => {
    try {
      const r = await apiClient.get("/admin/whatsapp/silence-alerts");
      setHistory(r.data?.items || []);
      setHistoryOpen(true);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec du chargement");
    }
  };

  return (
    <div className="rounded-lg border border-dashed border-rose-300 bg-rose-50/40 p-4 space-y-3" data-testid="wa-silence-alert-panel">
      <div className="text-xs text-slate-600">
        <p className="font-semibold text-slate-800">Détecteur de silence WhatsApp (Iter35b)</p>
        <p>
          Vous prévient automatiquement par email (et Discord en option) si vous avez envoyé des messages WhatsApp
          mais que Meta n'a appelé <b>aucun webhook</b> en retour pendant la fenêtre configurée.
          Le job tourne toutes les 4 h ; vous pouvez aussi le déclencher manuellement ci-dessous.
        </p>
      </div>
      <Toggle
        label="Activer la détection automatique"
        value={!!s.wa_silence_alert_enabled}
        onChange={(v) => upd("wa_silence_alert_enabled", v)}
        testid="wa-silence-alert-enabled"
      />
      <div className="grid sm:grid-cols-3 gap-3">
        <Input
          label="Seuil (nb msg envoyés)"
          type="number"
          value={String(s.wa_silence_alert_threshold ?? 3)}
          onChange={(v) => upd("wa_silence_alert_threshold", parseInt(v) || 3)}
          placeholder="3"
          testid="wa-silence-threshold"
        />
        <Input
          label="Fenêtre (heures)"
          type="number"
          value={String(s.wa_silence_alert_window_hours ?? 24)}
          onChange={(v) => upd("wa_silence_alert_window_hours", parseInt(v) || 24)}
          placeholder="24"
          testid="wa-silence-window"
        />
        <Input
          label="Email destinataire (vide = celui de la santé)"
          value={s.wa_silence_alert_email_to || ""}
          onChange={(v) => upd("wa_silence_alert_email_to", v)}
          placeholder={s.health_email_to || "admin@example.com"}
          testid="wa-silence-email"
        />
      </div>
      <Input
        label="Webhook Discord (optionnel — pour ping #ops)"
        value={s.wa_silence_alert_discord_webhook || ""}
        onChange={(v) => upd("wa_silence_alert_discord_webhook", v)}
        placeholder="https://discord.com/api/webhooks/…"
        testid="wa-silence-discord"
      />
      <div className="flex items-center gap-2 flex-wrap">
        <button
          type="button"
          onClick={runNow}
          disabled={running}
          data-testid="wa-silence-run-now"
          className="inline-flex items-center gap-2 rounded-lg bg-rose-600 px-3 py-2 text-xs font-semibold text-white hover:brightness-110 disabled:opacity-60"
        >
          {running ? <RotateCcw className="h-3.5 w-3.5 animate-spin" /> : <AlertCircle className="h-3.5 w-3.5" />}
          {running ? "Vérification…" : "Lancer une vérification maintenant"}
        </button>
        <button
          type="button"
          onClick={loadHistory}
          data-testid="wa-silence-history"
          className="inline-flex items-center gap-2 rounded-lg bg-white px-3 py-2 text-xs font-semibold text-slate-700 border hover:bg-slate-50"
        >
          Historique des alertes
        </button>
      </div>
      {result && (
        <div className={`p-3 rounded text-xs ${result.fired ? "bg-rose-100 text-rose-900" : result.silent ? "bg-amber-100 text-amber-900" : "bg-emerald-100 text-emerald-900"}`} data-testid="wa-silence-result">
          <div className="font-semibold mb-1">
            {result.fired ? "🚨 Alerte envoyée" : result.silent ? "⚠️ Silence détecté (pas d'envoi : anti-spam)" : "✅ Communication OK"}
          </div>
          <div>Fenêtre : {result.window_hours} h · Seuil : {result.threshold}</div>
          <div>Envoyés : <b>{result.outbound_count}</b> · Webhooks reçus : <b>{result.inbound_webhook_count}</b> · Messages entrants : <b>{result.inbound_message_count}</b></div>
          {result.fired && result.email_to && <div>Email envoyé à : <code>{result.email_to}</code> {result.discord_sent && " + Discord ✓"}</div>}
          {result.throttled_until && <div className="mt-1 text-[11px]">Prochaine alerte possible après : {new Date(result.throttled_until).toLocaleString("fr-FR")}</div>}
        </div>
      )}
      {historyOpen && (
        <div className="space-y-1 text-xs" data-testid="wa-silence-history-list">
          {history.length === 0 && <p className="italic text-slate-500">Aucune alerte enregistrée pour le moment.</p>}
          {history.map((h) => (
            <div key={h.id} className="bg-white border rounded p-2">
              <div className="font-semibold">{new Date(h.fired_at).toLocaleString("fr-FR")}</div>
              <div className="text-slate-600">
                {h.outbound_count} envoyés · 0 reçus · fenêtre {h.window_hours} h ·{" "}
                {h.email_sent ? "email ✓" : "email ✗"} · {h.discord_sent ? "discord ✓" : "—"} · {h.triggered_by}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

const Toggle = ({ label, value, onChange, testid }) => (
  <label className="flex items-center gap-3 text-sm">
    <input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)} data-testid={testid} />
    {label}
  </label>
);

// Iter38r-fix2 — PawaPay callback URLs (deposits + refunds) for the merchant
// dashboard. The endpoint auto-generates the callback_secret if missing so the
// URLs are always ready to paste. The base host is derived from the request,
// so preview admins see preview URLs and production admins see production URLs.
const PawaPayCallbackUrls = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const fetchUrls = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/pawapay/callback-urls");
      setData(r.data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Impossible de récupérer les URLs");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { fetchUrls(); }, [fetchUrls]);
  const copy = (text, label) => {
    navigator.clipboard.writeText(text).then(
      () => toast.success(`${label} copiée`),
      () => toast.error("Copie impossible — sélectionnez le texte manuellement")
    );
  };
  return (
    <div className="rounded-lg ring-1 ring-sky-200 bg-sky-50 p-3 space-y-3" data-testid="pawapay-callback-urls">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs font-semibold text-sky-900">URLs de callback PawaPay</p>
          <p className="text-[11px] text-sky-800/80">
            Collez ces URLs dans le tableau de bord PawaPay → Configuration → Callback URLs.
          </p>
        </div>
        <button
          type="button"
          onClick={fetchUrls}
          disabled={loading}
          className="text-[11px] inline-flex items-center gap-1 px-2 py-1 rounded ring-1 ring-sky-300 bg-white hover:bg-sky-100 disabled:opacity-50"
          data-testid="pawapay-callback-refresh"
        >
          <RefreshCw className="h-3 w-3" /> Rafraîchir
        </button>
      </div>
      {loading && !data && <p className="text-xs text-sky-800/70">Chargement…</p>}
      {data && (
        <div className="space-y-2">
          <UrlRow label="Deposits" value={data.deposits_url} onCopy={copy} testid="pawapay-deposits-url" />
          <UrlRow label="Refunds" value={data.refunds_url} onCopy={copy} testid="pawapay-refunds-url" />
          <details className="text-[11px] text-sky-800/70">
            <summary className="cursor-pointer">URL legacy (rétro-compatibilité)</summary>
            <div className="mt-2"><UrlRow label="Legacy" value={data.legacy_url} onCopy={copy} testid="pawapay-legacy-url" /></div>
          </details>
          <p className="text-[10px] text-sky-800/60">
            Secret callback : <span className="font-mono">{data.secret_preview}</span>
            {data.generated_at && <> · Généré le {new Date(data.generated_at).toLocaleDateString("fr-FR")}</>}
          </p>
        </div>
      )}
    </div>
  );
};

const UrlRow = ({ label, value, onCopy, testid }) => (
  <div className="flex items-center gap-2">
    <span className="text-[10px] uppercase tracking-wider font-semibold text-sky-900 w-16 flex-shrink-0">{label}</span>
    <input
      readOnly
      value={value || ""}
      onClick={(e) => e.target.select()}
      className="flex-1 bg-white rounded px-2 py-1 text-[11px] font-mono text-slate-700 ring-1 ring-sky-200 select-all"
      data-testid={`${testid}-input`}
    />
    <button
      type="button"
      onClick={() => onCopy(value, `URL ${label}`)}
      className="text-[10px] px-2 py-1 rounded bg-sky-600 text-white hover:bg-sky-700 inline-flex items-center gap-1"
      data-testid={`${testid}-copy`}
    >
      <Copy className="h-3 w-3" /> Copier
    </button>
  </div>
);

// Live preview of the incident banner — mirrors IncidentBanner.jsx visuals
const BannerPreview = ({ severity, message, linkLabel, linkUrl }) => {
  const palette = {
    info: { bg: "bg-sky-500", text: "text-white" },
    warning: { bg: "bg-amber-500", text: "text-slate-900" },
    critical: { bg: "bg-rose-600", text: "text-white" },
  }[severity] || { bg: "bg-amber-500", text: "text-slate-900" };
  return (
    <div className={`rounded ${palette.bg} ${palette.text} px-3 py-2 text-sm flex items-center gap-2`}>
      <AlertCircle className="h-4 w-4 flex-shrink-0" />
      <span className="flex-1">
        {message}
        {linkUrl && (
          <span className="ml-2 underline decoration-2 underline-offset-2 font-semibold">
            {linkLabel || "En savoir plus"} →
          </span>
        )}
      </span>
    </div>
  );
};



// --- SMS Test Button (per-provider) ---
const SmsTestButton = ({ provider, testid }) => {
  const [open, setOpen] = useState(false);
  const [to, setTo] = useState("+226");
  const [message, setMessage] = useState("Test SMS depuis SAWALI Admin.");
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState(null);

  const send = async () => {
    if (!to.trim()) { toast.error("Numéro requis"); return; }
    if (!message.trim()) { toast.error("Message requis"); return; }
    setSending(true); setResult(null);
    try {
      const r = await apiClient.post("/admin/sms/test", { provider, to, message });
      setResult(r.data);
      if (r.data?.ok) toast.success("SMS de test envoyé via " + provider.toUpperCase());
      else toast.error(r.data?.api_message || "Échec");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setSending(false); }
  };

  return (
    <>
      <button
        onClick={() => { setResult(null); setOpen(true); }}
        type="button"
        className="inline-flex items-center gap-1.5 text-xs rounded-lg ring-1 ring-amber-300 bg-amber-50 hover:bg-amber-100 text-amber-800 px-3 py-1.5"
        data-testid={testid}
      >
        <Activity className="h-3.5 w-3.5" /> Tester l'envoi {provider.toUpperCase()}
      </button>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={(e) => e.target === e.currentTarget && setOpen(false)} data-testid={`${testid}-modal`}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md">
            <div className="flex items-center justify-between px-5 py-3 border-b bg-amber-50">
              <h3 className="font-display font-bold inline-flex items-center gap-2">
                <Smartphone className="h-4 w-4" /> Test SMS — {provider.toUpperCase()}
              </h3>
              <button onClick={() => setOpen(false)} className="text-slate-500 text-lg">×</button>
            </div>
            <div className="p-5 space-y-3">
              <p className="text-[11px] text-slate-500">
                Le message sera envoyé via le fournisseur <strong>{provider.toUpperCase()}</strong> avec les paramètres saisis ci-dessus. Pensez à enregistrer la configuration avant de tester.
              </p>
              <div>
                <label className="block text-xs font-semibold mb-1">Numéro destinataire (E.164)</label>
                <input value={to} onChange={(e) => setTo(e.target.value)} placeholder="+22670000000"
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" data-testid={`${testid}-to`} />
              </div>
              <div>
                <label className="block text-xs font-semibold mb-1">Message ({message.length}/600)</label>
                <textarea value={message} onChange={(e) => setMessage(e.target.value.slice(0, 600))} rows={3}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid={`${testid}-message`} />
              </div>
              {result && (
                <div className={`rounded-lg ring-1 p-3 text-xs ${result.ok ? "bg-emerald-50 ring-emerald-200 text-emerald-900" : "bg-rose-50 ring-rose-300 text-rose-900"}`} data-testid={`${testid}-result`}>
                  <p><strong>{result.ok ? "Succès" : "Échec"}</strong> via {result.provider} (HTTP {result.http_status || "—"})</p>
                  {result.api_message && <p className="mt-1">{result.api_message}</p>}
                  {result.raw_response && (
                    <details className="mt-2"><summary className="cursor-pointer text-[10px] underline">Réponse brute</summary>
                      <pre className="text-[9px] mt-1 max-h-40 overflow-auto whitespace-pre-wrap">{JSON.stringify(result.raw_response, null, 2)}</pre>
                    </details>
                  )}
                </div>
              )}
            </div>
            <div className="flex justify-end gap-2 px-5 py-3 border-t bg-slate-50">
              <button onClick={() => setOpen(false)} className="text-sm rounded-lg bg-white ring-1 ring-slate-300 hover:bg-slate-100 px-4 py-2">Fermer</button>
              <button onClick={send} disabled={sending} className="inline-flex items-center gap-1.5 text-sm rounded-lg bg-amber-600 hover:bg-amber-700 text-white px-4 py-2 disabled:opacity-50" data-testid={`${testid}-send`}>
                <Activity className="h-4 w-4" /> {sending ? "Envoi…" : "Envoyer test"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};



// --- Support Technique — Load Gauge admin section ---
const LEVEL_LABELS = {
  0: "Inactif", 1: "Très disponible", 2: "Disponible",
  3: "Charge légère", 4: "Charge modérée", 5: "Charge élevée",
  6: "Très occupé", 7: "Saturé",
};
const BAR_COLORS = ["#16a34a", "#22c55e", "#84cc16", "#eab308", "#f59e0b", "#f97316", "#ef4444"];

// =====================================================================
// Iter35x — Alexa Echo voice notifications via Voice Monkey
// =====================================================================
const ALEXA_EVENT_TYPES = [
  { value: "sms_inbound", label: "SMS reçu" },
  { value: "wa_inbound", label: "WhatsApp reçu" },
  { value: "appointment_due", label: "Rendez-vous imminent (24h)" },
  { value: "support_load_critical", label: "Niveau de support critique (≥6/7)" },
];

const AlexaVoiceMonkeySection = ({ s, upd }) => {
  const enabled = !!s.alexa_enabled;
  const url = s.alexa_webhook_url || "";
  const events = Array.isArray(s.alexa_events) ? s.alexa_events : [];
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);

  const toggleEvent = (val) => {
    const next = events.includes(val) ? events.filter((e) => e !== val) : [...events, val];
    upd("alexa_events", next);
  };

  const runTest = async () => {
    if (!url.startsWith("http")) {
      toast.error("Configurez d'abord l'URL du webhook Voice Monkey");
      return;
    }
    setTesting(true);
    setTestResult(null);
    try {
      const r = await apiClient.post("/admin/settings/test-url", { key: "alexa_webhook_url" });
      setTestResult(r.data);
      if (r.data?.ok) toast.success(`Voice Monkey : HTTP ${r.data.http_status} en ${r.data.elapsed_ms} ms ✓`);
      else toast.error(r.data?.error || `HTTP ${r.data?.http_status}`);
    } catch (err) {
      const msg = err?.response?.data?.detail || err?.message || "Échec";
      setTestResult({ ok: false, error: msg });
      toast.error(msg);
    } finally {
      setTesting(false);
    }
  };

  return (
    <Filterable title="Notifications vocales Alexa (Voice Monkey)" anchorId="alexa-voice-monkey">
      <Section icon={Headphones} title="Notifications vocales Alexa (Voice Monkey)">
        <p className="text-xs text-slate-500">
          Annonce vocalement les événements importants sur votre Echo via Voice Monkey. Configurez votre webhook
          dans <a href="https://voicemonkey.io" target="_blank" rel="noreferrer" className="text-purple-700 underline">voicemonkey.io</a> (formule
          gratuite ≤ 50 calls/jour, 5 $/mois pour illimité), puis collez l'URL ci-dessous et cochez les événements à
          annoncer.
        </p>
        <Toggle
          label="Activer les notifications vocales Alexa"
          value={enabled}
          onChange={(v) => upd("alexa_enabled", v)}
          testid="alexa-enabled-toggle"
        />
        <Input
          label="URL du webhook Voice Monkey"
          value={url}
          onChange={(v) => upd("alexa_webhook_url", v)}
          placeholder="https://api-v2.voicemonkey.io/announcement?token=...&device=..."
          testid="alexa-webhook-url"
        />
        <div className="rounded-lg ring-1 ring-purple-200 bg-purple-50/40 p-3" data-testid="alexa-events-block">
          <p className="text-xs font-semibold text-slate-700 mb-2">Événements déclencheurs</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {ALEXA_EVENT_TYPES.map((ev) => (
              <label key={ev.value} className={`flex items-center gap-2 text-xs cursor-pointer rounded p-2 ring-1 ${events.includes(ev.value) ? "ring-purple-300 bg-white" : "ring-slate-200 bg-slate-50"}`} data-testid={`alexa-event-${ev.value}`}>
                <input
                  type="checkbox"
                  checked={events.includes(ev.value)}
                  onChange={() => toggleEvent(ev.value)}
                  disabled={!enabled}
                  className="accent-purple-600"
                />
                <span>{ev.label}</span>
              </label>
            ))}
          </div>
        </div>
        <div className="flex gap-2 items-center flex-wrap">
          <button
            onClick={runTest}
            disabled={testing || !enabled || !url.startsWith("http")}
            className="inline-flex items-center gap-1.5 rounded-lg bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-40 disabled:cursor-not-allowed px-3 py-1.5 text-xs font-medium transition"
            data-testid="alexa-test-btn"
          >
            {testing ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Headphones className="h-3 w-3" />}
            {testing ? "Test…" : "Tester l'annonce"}
          </button>
          <span className="text-[10px] text-slate-500">Envoie un payload de test à Voice Monkey (votre Echo doit annoncer un message court).</span>
        </div>
        {testResult && (
          <div className={`rounded ring-1 p-2 text-[11px] ${testResult.ok ? "bg-emerald-50 ring-emerald-200 text-emerald-900" : "bg-rose-50 ring-rose-200 text-rose-900"}`} data-testid="alexa-test-result">
            <div className="flex items-center gap-2 flex-wrap">
              <strong>{testResult.ok ? "✓ Succès" : "✗ Échec"}</strong>
              {testResult.http_status !== undefined && <span>HTTP {testResult.http_status}</span>}
              {testResult.elapsed_ms !== undefined && <span className="text-slate-500">· {testResult.elapsed_ms} ms</span>}
            </div>
            {testResult.error && <div className="text-rose-700 mt-1">{testResult.error}</div>}
          </div>
        )}
      </Section>
    </Filterable>
  );
};

// =====================================================================
// Iter36e — Note de Service: admin history panel (last 20 broadcasts)
// =====================================================================
const NoteServiceHistorySection = ({ s, upd }) => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(null);
  const [retrying, setRetrying] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/note-service/history?limit=20");
      setItems(r.data?.items || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec du chargement");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const retryFailed = async (noteId, numero) => {
    setRetrying(noteId);
    try {
      const r = await apiClient.post(`/admin/note-service/${noteId}/retry-failed`);
      const { sent_count, skipped_count, total_targets, message } = r.data || {};
      if (total_targets === 0 || message) {
        toast.info(message || "Rien à retenter — aucun destinataire en échec.");
      } else {
        toast.success(`${numero} : rediffusion ${sent_count}/${total_targets} (${skipped_count} encore en échec)`, { duration: 7000 });
      }
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec de la rediffusion");
    } finally {
      setRetrying(null);
    }
  };

  const tplName = s.wa_template_note_service || "";
  const tplLang = s.wa_template_note_service_language || "";

  return (
    <Filterable title="Note de Service (historique + template)" anchorId="note-service-history">
      <Section icon={Megaphone} title="Note de Service (historique + template)">
        <p className="text-xs text-slate-500">
          Diffusion d'une note publique numérotée par WhatsApp template à tous les utilisateurs suivis du client lié.
          Le bouton apparaît automatiquement sur chaque note publique numérotée dans le portail (
          <code className="bg-slate-100 px-1 rounded">/portal/notes</code>).
        </p>
        <Input
          label="Nom du template WhatsApp"
          value={tplName}
          onChange={(v) => upd("wa_template_note_service", v)}
          placeholder="notedeservice_fr"
          testid="note-service-template-name"
        />
        <Input
          label="Code de langue"
          value={tplLang}
          onChange={(v) => upd("wa_template_note_service_language", v)}
          placeholder="fr"
          testid="note-service-template-lang"
        />
        <div className="rounded-lg ring-1 ring-emerald-200 bg-emerald-50/40 p-3 text-[11px] text-slate-700">
          <strong className="text-emerald-900">Paramètres du template (ordre) :</strong>
          <ol className="list-decimal list-inside mt-1 space-y-0.5">
            <li><code className="bg-white px-1 rounded">{"{{1}}"}</code> → Numéro de la note (ex: NTE-2026-0042)</li>
            <li><code className="bg-white px-1 rounded">{"{{2}}"}</code> → Nom du destinataire (utilisateur suivi)</li>
            <li><code className="bg-white px-1 rounded">{"{{3}}"}</code> → Contenu de la note (texte brut, max 900 car.)</li>
          </ol>
        </div>
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <h4 className="text-sm font-semibold text-slate-800 flex items-center gap-2">
            <Activity className="h-4 w-4 text-emerald-600" />
            20 dernières diffusions
          </h4>
          <button
            onClick={load}
            className="text-xs inline-flex items-center gap-1.5 rounded bg-emerald-600 text-white hover:bg-emerald-700 px-2.5 py-1 transition"
            data-testid="note-service-history-refresh"
          >
            <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
            Actualiser
          </button>
        </div>
        {loading && items.length === 0 ? (
          <p className="text-xs italic text-slate-400">Chargement…</p>
        ) : items.length === 0 ? (
          <p className="text-xs italic text-slate-400" data-testid="note-service-history-empty">
            Aucune Note de Service diffusée pour l'instant.
          </p>
        ) : (
          <div className="space-y-2" data-testid="note-service-history-list">
            {items.map((it) => {
              const isOpen = expanded === it.note_id;
              const totalKo = it.failed_count || 0;
              const totalOk = it.sent_count || 0;
              const tone = totalKo === 0 ? "emerald" : totalKo < totalOk ? "amber" : "rose";
              const toneCls = {
                emerald: "ring-emerald-200 bg-emerald-50/30",
                amber: "ring-amber-200 bg-amber-50/40",
                rose: "ring-rose-200 bg-rose-50/40",
              }[tone];
              return (
                <div key={it.note_id} className={`rounded-lg ring-1 ${toneCls} p-2.5 transition`} data-testid={`note-service-history-${it.note_id}`}>
                  <button
                    type="button"
                    onClick={() => setExpanded(isOpen ? null : it.note_id)}
                    className="w-full flex items-start justify-between gap-2 text-left"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-mono text-[10px] bg-white px-1.5 py-0.5 rounded ring-1 ring-slate-200 text-purple-900">{it.note_numero || "—"}</span>
                        <span className="text-sm font-semibold text-slate-800 truncate" title={it.note_title}>{it.note_title || "(note supprimée)"}</span>
                      </div>
                      <div className="text-[10px] text-slate-500 mt-0.5 flex items-center gap-2 flex-wrap">
                        <span>{it.last_sent_at ? new Date(it.last_sent_at).toLocaleString("fr-FR") : "—"}</span>
                        {it.owner_email && <span>· par {it.owner_name || it.owner_email}</span>}
                        {it.template_name && <span className="font-mono text-purple-700">· {it.template_name}</span>}
                      </div>
                    </div>
                    <div className="flex items-center gap-1 flex-shrink-0">
                      <span className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800" title="Envoyés OK">✓ {totalOk}</span>
                      {totalKo > 0 && <span className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded bg-rose-100 text-rose-800" title="Échecs">✗ {totalKo}</span>}
                      <ChevronDown className={`h-3.5 w-3.5 text-slate-400 transition ${isOpen ? "rotate-180" : ""}`} />
                    </div>
                  </button>
                  {isOpen && (
                    <div className="mt-2 pt-2 border-t border-slate-200 space-y-1" data-testid={`note-service-recipients-${it.note_id}`}>
                      <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Destinataires ({it.recipients?.length || 0})</p>
                      <div className="max-h-48 overflow-y-auto space-y-0.5">
                        {(it.recipients || []).map((r, i) => (
                          <div key={i} className="flex items-center gap-2 text-[11px] py-0.5">
                            <span className={`text-[9px] font-bold uppercase px-1 py-0.5 rounded ${r.status === "sent" ? "bg-emerald-100 text-emerald-700" : "bg-rose-100 text-rose-700"}`}>
                              {r.status === "sent" ? "OK" : "KO"}
                            </span>
                            <span className="text-slate-700 truncate flex-1">{r.tracked_user_name || r.phone || "—"}</span>
                            <span className="font-mono text-slate-400 text-[10px]">{r.phone}</span>
                            {r.error && <span className="text-rose-600 truncate max-w-[180px]" title={r.error}>{r.error}</span>}
                          </div>
                        ))}
                      </div>
                      <div className="pt-1.5">
                        <div className="flex items-center gap-2 flex-wrap">
                          <a
                            href="/portal/notes"
                            className="text-[11px] text-emerald-700 hover:underline inline-flex items-center gap-1"
                          >
                            → Voir la note source dans le portail
                          </a>
                          {totalKo > 0 && (
                            <button
                              type="button"
                              onClick={() => retryFailed(it.note_id, it.note_numero)}
                              disabled={retrying === it.note_id}
                              className="ml-auto inline-flex items-center gap-1 rounded bg-amber-500 hover:bg-amber-600 text-white px-2 py-0.5 text-[10px] font-semibold disabled:opacity-50 transition"
                              title={`Rediffuser uniquement aux ${totalKo} destinataire(s) en échec`}
                              data-testid={`note-service-retry-${it.note_id}`}
                            >
                              {retrying === it.note_id ? <RefreshCw className="h-2.5 w-2.5 animate-spin" /> : <Megaphone className="h-2.5 w-2.5" />}
                              Rediffuser {totalKo} KO
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Section>
    </Filterable>
  );
};

const SupportLoadSection = ({ s, upd }) => {
  const [saving, setSaving] = useState(false);
  const [secret, setSecret] = useState(s.support_load_webhook_secret || "");

  useEffect(() => { setSecret(s.support_load_webhook_secret || ""); }, [s.support_load_webhook_secret]);

  const level = Math.max(0, Math.min(7, parseInt(s.support_load_level ?? 0, 10) || 0));
  const enabled = !!s.support_load_enabled;
  const label = s.support_load_label || "";

  const generateSecret = () => {
    const v = Array.from(crypto.getRandomValues(new Uint8Array(16))).map((b) => b.toString(16).padStart(2, "0")).join("");
    setSecret(v); upd("support_load_webhook_secret", v);
  };

  const pushNow = async (newLevel) => {
    setSaving(true);
    try {
      await apiClient.post("/admin/support-load", { level: newLevel, label, enabled });
      upd("support_load_level", newLevel);
      toast.success("Niveau d'occupation mis à jour");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setSaving(false); }
  };

  const webhookUrl = secret ? `${window.location.origin}/api/webhooks/support-load/${secret}` : "";

  const copy = () => {
    if (!webhookUrl) return;
    navigator.clipboard?.writeText(webhookUrl).then(() => toast.success("URL copiée"));
  };

  return (
    <Section icon={Headphones} title="Jauge d'occupation du Support technique" testid="support-load-section">
      <p className="text-xs text-slate-500 mb-3">
        Affichée tout en haut de chaque page publique sous forme de 7 barres (style signal cellulaire) — du <strong className="text-emerald-700">vert</strong> (très disponible) au <strong className="text-rose-700">rouge</strong> (saturé). Permet aux clients de voir le niveau d'activité en temps réel et d'éviter les appels en heure de pointe.
      </p>

      <div className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3 mb-3 flex items-center justify-center gap-3" data-testid="support-load-preview">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">Aperçu</span>
        <div className="flex items-end gap-[2px] h-4">
          {[4, 6, 8, 10, 12, 14, 16].map((h, i) => {
            const active = i < level;
            return (
              <div key={i} className="w-[3px] rounded-sm" style={{ height: `${h}px`, backgroundColor: active ? BAR_COLORS[i] : "rgba(148,163,184,0.25)" }} />
            );
          })}
        </div>
        <span className="font-semibold text-sm" style={{ color: level > 0 ? BAR_COLORS[level - 1] : "#64748b" }}>
          {label || LEVEL_LABELS[level]}
        </span>
        <span className="text-[10px] text-slate-400">{level}/7</span>
      </div>

      <label className="flex items-center gap-2 text-sm font-semibold cursor-pointer mb-3">
        <input type="checkbox" checked={enabled} onChange={(e) => upd("support_load_enabled", e.target.checked)} data-testid="support-load-enabled" />
        Activer l'affichage public de la jauge
      </label>

      <div className="grid sm:grid-cols-8 gap-1 mb-3" data-testid="support-load-levels">
        {[0, 1, 2, 3, 4, 5, 6, 7].map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => pushNow(n)}
            disabled={saving}
            className={`rounded-lg px-2 py-2 text-xs font-semibold ring-1 transition ${level === n ? "ring-2 text-white shadow" : "ring-slate-200 text-slate-600 bg-white hover:bg-slate-50"}`}
            style={level === n ? { backgroundColor: n > 0 ? BAR_COLORS[n - 1] : "#64748b", borderColor: n > 0 ? BAR_COLORS[n - 1] : "#64748b" } : {}}
            data-testid={`support-load-level-${n}`}
            title={LEVEL_LABELS[n]}
          >
            {n} <span className="block text-[9px] font-normal opacity-80 truncate">{LEVEL_LABELS[n]}</span>
          </button>
        ))}
      </div>

      <Input
        label="Libellé personnalisé (optionnel — sinon le libellé du niveau s'affiche)"
        value={label}
        onChange={(v) => upd("support_load_label", v.slice(0, 140))}
        placeholder="Ex: Forte affluence ce matin — appel possible avec délai d'attente"
        testid="support-load-label"
      />

      <LiluvineAlertBlock s={s} upd={upd} />

      <div className="rounded-lg bg-amber-50 ring-1 ring-amber-200 p-3 mt-4">
        <h4 className="text-sm font-semibold inline-flex items-center gap-2 mb-2">
          <Webhook className="h-3.5 w-3.5" /> Webhook de mise à jour automatique
        </h4>
        <p className="text-[11px] text-slate-600 mb-2">
          Pour une mise à jour automatique depuis votre outil de monitoring (Zabbix, Grafana, Freshdesk, n8n…), configurez l'URL ci-dessous avec un secret. Acceptable en GET (`?level=N&label=...`) ou POST JSON (`{"{level: N, label: '…'}"}`).
        </p>
        <div className="flex gap-2 mb-2">
          <input
            value={secret}
            onChange={(e) => { setSecret(e.target.value); upd("support_load_webhook_secret", e.target.value); }}
            placeholder="Secret webhook (32 char recommandé)"
            className="flex-1 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-mono"
            data-testid="support-load-secret"
          />
          <button type="button" onClick={generateSecret}
            className="text-xs rounded-lg ring-1 ring-amber-400 bg-amber-100 hover:bg-amber-200 px-3 py-1.5"
            data-testid="support-load-gen-secret">
            <RotateCcw className="h-3 w-3 inline-block mr-1" /> Générer
          </button>
        </div>
        {webhookUrl && (
          <div className="rounded-lg bg-white ring-1 ring-slate-200 p-2 flex items-center gap-2">
            <code className="text-[11px] font-mono break-all flex-1">{webhookUrl}?level=4&label=Charge%20mod%C3%A9r%C3%A9e</code>
            <button type="button" onClick={copy} className="text-xs inline-flex items-center gap-1 rounded ring-1 ring-slate-200 hover:bg-slate-100 px-2 py-1" data-testid="support-load-copy-url">
              <Copy className="h-3 w-3" /> Copier
            </button>
          </div>
        )}
        <p className="text-[10px] text-slate-500 mt-2">
          ⚠️ Le webhook **active automatiquement** la jauge dès qu'il reçoit un niveau valide.
        </p>
      </div>
    </Section>
  );
};



// --- Liluvine Smart Alert block (inside Support Load admin section) ---
const LiluvineAlertBlock = ({ s, upd }) => {
  const [generating, setGenerating] = useState(false);
  const [link, setLink] = useState(null);
  const threshold = Math.max(0, Math.min(7, parseInt(s.liluvine_alert_threshold ?? 6, 10) || 6));
  const enabled = !!s.liluvine_alert_enabled;
  const alertLabel = s.liluvine_alert_label || "";
  const alertMessage = s.liluvine_alert_message || "";
  const adminPhones = Array.isArray(s.liluvine_remote_admin_phones) ? s.liluvine_remote_admin_phones : (typeof s.liluvine_remote_admin_phones === "string" ? s.liluvine_remote_admin_phones.split(",").map((x) => x.trim()).filter(Boolean) : []);
  const phonesValue = adminPhones.join(", ");

  const generateLink = async () => {
    setGenerating(true);
    try {
      const r = await apiClient.post("/admin/liluvine/remote-link", { ttl_hours: 24 * 30 });
      setLink(r.data);
      toast.success("Lien généré (valide 30 jours) — bookmarkez-le sur votre téléphone");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setGenerating(false); }
  };

  const copyLink = () => {
    if (!link?.url) return;
    navigator.clipboard?.writeText(link.url).then(() => toast.success("URL copiée"));
  };

  return (
    <div className="rounded-lg bg-rose-50 ring-1 ring-rose-200 p-3 mt-4" data-testid="liluvine-alert-block">
      <h4 className="text-sm font-semibold inline-flex items-center gap-2 mb-2 text-rose-900">
        <Sparkles className="h-3.5 w-3.5" /> Liluvine — Redirection intelligente
      </h4>
      <p className="text-[11px] text-slate-600 mb-3">
        Quand le niveau d'occupation atteint le seuil défini, le bouton flottant Liluvine devient rouge et propose le chat comme canal prioritaire — pour décharger la ligne téléphonique aux heures de pointe.
      </p>

      <label className="flex items-center gap-2 text-sm font-semibold cursor-pointer mb-3">
        <input type="checkbox" checked={enabled} onChange={(e) => upd("liluvine_alert_enabled", e.target.checked)} data-testid="liluvine-alert-enabled" />
        Activer le mode alerte
      </label>

      <div className="mb-3">
        <label className="block text-xs font-semibold mb-1">
          Seuil de déclenchement <span className="text-slate-500 font-normal">(quand niveau ≥ seuil → alerte ON)</span>
        </label>
        <div className="grid grid-cols-7 gap-1" data-testid="liluvine-threshold-grid">
          {[1, 2, 3, 4, 5, 6, 7].map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => upd("liluvine_alert_threshold", n)}
              className={`rounded-lg px-2 py-2 text-xs font-bold ring-1 ${threshold === n ? "ring-2 bg-rose-100 text-rose-900 ring-rose-400" : "ring-slate-200 text-slate-600 bg-white hover:bg-slate-50"}`}
              data-testid={`liluvine-threshold-${n}`}
            >
              ≥{n}
            </button>
          ))}
        </div>
      </div>

      <Input
        label="Libellé du bouton en mode alerte (≤ 60 char)"
        value={alertLabel}
        onChange={(v) => upd("liluvine_alert_label", v.slice(0, 60))}
        placeholder="🔴 Forte affluence — chat plutôt"
        testid="liluvine-alert-label"
      />
      <div className="mt-2">
        <label className="block text-xs font-semibold mb-1">Message d'alerte affiché dans la bulle</label>
        <textarea
          value={alertMessage}
          onChange={(e) => upd("liluvine_alert_message", e.target.value.slice(0, 250))}
          rows={2}
          maxLength={250}
          placeholder="Notre équipe est très sollicitée. Privilégiez ce chat ou notre formulaire de contact pour une réponse plus rapide qu'au téléphone."
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          data-testid="liluvine-alert-message"
        />
        <p className="text-[10px] text-slate-400 mt-0.5">{alertMessage.length}/250 caractères</p>
      </div>

      {/* Remote control */}
      <div className="mt-4 rounded-lg bg-white ring-1 ring-slate-200 p-3">
        <h5 className="text-xs font-semibold inline-flex items-center gap-1 mb-2">
          <KeyRound className="h-3 w-3" /> Contrôle distant (mobile)
        </h5>
        <p className="text-[11px] text-slate-500 mb-2">
          Générez un lien <strong>HMAC sécurisé</strong> à bookmarker sur votre téléphone : il vous permet de modifier le niveau et le seuil <em>sans login</em>.
        </p>
        <button
          type="button"
          onClick={generateLink}
          disabled={generating}
          className="text-xs inline-flex items-center gap-1.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white px-3 py-1.5 disabled:opacity-50"
          data-testid="liluvine-gen-link"
        >
          <ExternalLink className="h-3 w-3" /> {generating ? "Génération…" : "Générer un lien (30 jours)"}
        </button>
        {link?.url && (
          <div className="mt-2 rounded-lg bg-slate-50 ring-1 ring-slate-200 p-2 flex items-center gap-2" data-testid="liluvine-remote-url">
            <code className="text-[10px] font-mono break-all flex-1">{link.url}</code>
            <button type="button" onClick={copyLink} className="text-xs inline-flex items-center gap-1 rounded ring-1 ring-slate-200 hover:bg-slate-100 px-2 py-1" data-testid="liluvine-copy-link">
              <Copy className="h-3 w-3" /> Copier
            </button>
          </div>
        )}
        <p className="text-[10px] text-slate-400 mt-2">
          Expire : {link?.expires_at ? new Date(link.expires_at).toLocaleString("fr-FR") : "—"}. Toute action est tracée dans les logs.
        </p>
      </div>

      {/* WhatsApp command */}
      <div className="mt-3 rounded-lg bg-emerald-50 ring-1 ring-emerald-200 p-3">
        <h5 className="text-xs font-semibold inline-flex items-center gap-1 mb-2 text-emerald-900">
          <MessageCircle className="h-3 w-3" /> Contrôle via WhatsApp
        </h5>
        <p className="text-[11px] text-slate-600 mb-2">
          Envoyez à votre numéro WhatsApp Business une de ces commandes pour ajuster en direct :
        </p>
        <ul className="text-[11px] font-mono space-y-0.5 mb-2 ml-3">
          <li><code className="bg-white ring-1 ring-emerald-200 px-1 rounded">!niveau 5</code> — fixe le niveau (auto-active la jauge)</li>
          <li><code className="bg-white ring-1 ring-emerald-200 px-1 rounded">!niveau 6 Forte affluence</code> — niveau + libellé</li>
          <li><code className="bg-white ring-1 ring-emerald-200 px-1 rounded">!seuil 4</code> — règle le seuil Liluvine</li>
        </ul>
        <Input
          label="Numéros WhatsApp autorisés à envoyer ces commandes (séparés par virgule)"
          value={phonesValue}
          onChange={(v) => upd("liluvine_remote_admin_phones", v.split(",").map((x) => x.trim()).filter(Boolean))}
          placeholder="+22670000000, +22670000001"
          testid="liluvine-admin-phones"
        />
        <p className="text-[10px] text-slate-500 mt-1">
          Format international avec ou sans « + ». Une commande envoyée par un numéro non listé est rejetée silencieusement.
        </p>
      </div>
    </div>
  );
};
