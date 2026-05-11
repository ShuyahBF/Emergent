import React, { useEffect, useState, useMemo, useRef, createContext, useContext } from "react";
import { apiClient } from "@/lib/api";
import { useSearchParams, Link } from "react-router-dom";
import { Save, ShieldCheck, Calendar, Mail, ExternalLink, AlertCircle, CheckCircle2, Globe, Webhook, Video, Upload, MessageCircle, ClipboardList, Activity, RotateCcw, Mic, Tag, Sparkles, Smartphone, CreditCard, KeyRound, Headphones, Copy, Database, RefreshCw, Wrench, Search, ChevronDown, X, Download, FileArchive, Trash2, Pencil, Cloud, Inbox, UserCog, Check, MessageSquare } from "lucide-react";
import PasswordInput from "@/components/PasswordInput";
import { toast } from "sonner";

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
const STORAGE_KEY_SEEN = "sawali_settings_first_seen_v1";
const NEW_WINDOW_DAYS = 14;
const SEEN_FADE_DAYS = 3;
function readSeen() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY_SEEN) || "{}"); } catch { return {}; }
}
function writeSeen(map) {
  try { localStorage.setItem(STORAGE_KEY_SEEN, JSON.stringify(map)); } catch { /* ignore */ }
}
const SettingsFilterCtx = createContext(null);
const useSettingsFilter = () => useContext(SettingsFilterCtx);
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

const Filterable = ({ title, anchorId, children }) => {
  const ctx = useSettingsFilter();
  const ref = useRef(null);
  const [, force] = useState(0);
  useEffect(() => {
    if (!ctx) return;
    ctx.register(title, anchorId);
    return () => ctx.unregister(title);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title, anchorId]);
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
  if (!ctx) return null;
  const newCount = titles.filter((t) => isStillNew(t, ctx.seenMap)).length;
  const matchCount = ctx.search ? titles.filter((t) => t.toLowerCase().includes(ctx.search.toLowerCase())).length : titles.length;
  return (
    <div className="sticky top-0 z-30 -mx-3 sm:-mx-6 lg:-mx-10 px-3 sm:px-6 lg:px-10 py-3 bg-slate-50/95 backdrop-blur border-b border-slate-200" data-testid="settings-toolbar">
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
                document.getElementById(ctx.registry[t])?.scrollIntoView({ behavior: "smooth", block: "start" });
              }
            }}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm pr-8 appearance-none w-full sm:w-72"
            data-testid="settings-jump-select"
          >
            <option value="">Aller à un paramètre…{newCount > 0 ? `  (${newCount} nouveau${newCount > 1 ? "x" : ""})` : ""}</option>
            {titles.map((t) => (
              <option key={t} value={t}>{isStillNew(t, ctx.seenMap) ? "🆕  " : ""}{t}</option>
            ))}
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
      await apiClient.put("/admin/settings", payload);
      toast.success("Paramètres enregistrés");
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

  const upd = (k, v) => setS({ ...s, [k]: v });

  // iter33 — Settings filter context state
  const [search, setSearch] = useState("");
  const [registry, setRegistry] = useState({});  // {title: anchorId}
  const [seenMap, setSeenMap] = useState(() => readSeen());
  const register = (title, anchorId) => setRegistry((m) => (m[title] === anchorId ? m : { ...m, [title]: anchorId }));
  const unregister = (title) => setRegistry((m) => { const n = { ...m }; delete n[title]; return n; });
  const markSeen = (title) => setSeenMap((m) => {
    if (m[title]) return m;
    const n = { ...m, [title]: new Date().toISOString() };
    writeSeen(n);
    return n;
  });
  const filterCtxValue = useMemo(
    () => ({ search, setSearch, registry, register, unregister, seenMap, markSeen }),
    [search, registry, seenMap],
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
              <button onClick={disconnectGoogle} className="text-sm text-rose-600 underline" data-testid="gcal-disconnect">Se déconnecter</button>
            </>
          ) : (
            <button onClick={connectGoogle} className="inline-flex items-center gap-2 rounded-lg border border-sawali-blue text-sawali-blue px-4 py-2 text-sm hover:bg-sawali-blue/10" data-testid="gcal-connect">
              <ExternalLink className="h-4 w-4" /> Connecter Google Calendar
            </button>
          )}
        </div>
        <p className="text-xs text-slate-500">Sauvegardez les Client ID et Secret avant de cliquer sur Connecter.</p>
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
          <Input label="WhatsApp" value={s.company_whatsapp || ""} onChange={(v) => upd("company_whatsapp", v)} placeholder="+228 99 99 99 99" testid="company-whatsapp" />
          <Input label="Adresse" value={s.company_address || ""} onChange={(v) => upd("company_address", v)} testid="company-address" />
          <Input label="Ville" value={s.company_city || ""} onChange={(v) => upd("company_city", v)} testid="company-city" />
          <Input label="Pays" value={s.company_country || ""} onChange={(v) => upd("company_country", v)} testid="company-country" />
        </div>
      </Section>

      <SupportLoadSection s={s} upd={upd} />
      <ProfileRequestsSection />
      <DbSnapshotsSection s={s} upd={upd} reloadSettings={load} />
      <RoadmapTrackerSection />
      <OrphanDataSection />
      <ClientsConsistencySection />
      <ClientDataDiagnosticSection />
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
              </select>
            </div>
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

      <button onClick={save} disabled={loading} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-5 py-2.5 text-sm font-medium hover:bg-sawali-blue-light disabled:opacity-50" data-testid="save-settings-btn">
        <Save className="h-4 w-4" /> {loading ? "Enregistrement..." : "Enregistrer les paramètres"}
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
          <div className="rounded-lg ring-1 ring-rose-200 bg-rose-50 p-3 text-xs text-rose-900">
            <strong>⚠️ {total} utilisateur(s) désaligné(s)</strong> sur {data.misaligned_groups} entreprise(s) (sur {data.scanned_groups} scannées).
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
    if (filter === "done") return status === "done";
    if (filter === "in_progress") return status === "in_progress";
    if (filter === "pending") return status === "todo";
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
  const onFileChange = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (!importDryRun && importMode === "replace") {
      if (!window.confirm("⚠️ Mode REMPLACER actif : toutes les collections vont être VIDÉES puis remplies par le snapshot. Cette action est IRRÉVERSIBLE. Continuer ?")) return;
    }
    setImporting(true);
    setLastImport(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("mode", importMode);
      fd.append("dry_run", importDryRun ? "true" : "false");
      fd.append("comment", importComment || "");
      const r = await apiClient.post("/admin/snapshots/import", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setLastImport(r.data);
      if (r.data?.dry_run) {
        toast.info("Aperçu (dry-run) calculé. Vérifiez le résumé ci-dessous puis désactivez le dry-run pour appliquer.");
      } else {
        toast.success("Import appliqué avec succès");
        setImportComment("");
      }
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur d'import");
    } finally { setImporting(false); }
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

        {lastImport && (
          <div className={`rounded p-3 text-xs ${lastImport.dry_run ? "bg-sky-50 ring-1 ring-sky-200" : "bg-emerald-50 ring-1 ring-emerald-200"}`} data-testid="snapshot-import-summary">
            <p className="font-semibold mb-1">
              {lastImport.dry_run ? "Aperçu (dry-run)" : "Import appliqué"} — mode {lastImport.mode}
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5 text-[11px]">
              {Object.entries(lastImport.summary || {}).filter(([, v]) => (v.incoming || 0) > 0 || (v.before || 0) > 0).map(([k, v]) => (
                <div key={k} className="bg-white rounded px-2 py-1 ring-1 ring-slate-200 font-mono">
                  <div className="font-semibold text-slate-700">{k}</div>
                  <div className="text-slate-500">avant {v.before} → après {v.after ?? "—"} (entrant {v.incoming})</div>
                </div>
              ))}
            </div>
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

const Toggle = ({ label, value, onChange, testid }) => (
  <label className="flex items-center gap-3 text-sm">
    <input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)} data-testid={testid} />
    {label}
  </label>
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
