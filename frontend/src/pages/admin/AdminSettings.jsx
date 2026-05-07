import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { useSearchParams, Link } from "react-router-dom";
import { Save, ShieldCheck, Calendar, Mail, ExternalLink, AlertCircle, CheckCircle2, Globe, Webhook, Video, Upload, MessageCircle, ClipboardList, Activity, RotateCcw, Mic, Tag, Sparkles, Smartphone, CreditCard, KeyRound, Headphones, Copy } from "lucide-react";
import PasswordInput from "@/components/PasswordInput";
import { toast } from "sonner";

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

  return (
    <div className="space-y-8" data-testid="admin-settings-page">
      <div>
        <h1 className="text-2xl font-display font-bold">Paramètres</h1>
        <p className="text-sm text-slate-500">Configurez reCAPTCHA, l'envoi d'OTP par email et Google Calendar.</p>
      </div>

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
  );
}

const Section = ({ icon: Icon, title, children }) => (
  <div className="rounded-xl border border-slate-200 bg-white p-6 space-y-3">
    <div className="flex items-center gap-2"><Icon className="h-4 w-4 text-sawali-blue" /><h2 className="font-display font-semibold">{title}</h2></div>
    {children}
  </div>
);
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
