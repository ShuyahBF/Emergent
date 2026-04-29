import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { useSearchParams } from "react-router-dom";
import { Save, ShieldCheck, Calendar, Mail, ExternalLink, AlertCircle, CheckCircle2, Globe, Webhook, Video, Upload, MessageCircle, ClipboardList, Activity, RotateCcw } from "lucide-react";
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
      for (const k of ["smtp_password", "google_client_secret", "recaptcha_secret_key", "tracking_auth_header", "webhook_token", "webhook_basic_pass", "notes_webhook_token", "notes_webhook_basic_pass"]) {
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
const Input = ({ label, value, onChange, type = "text", placeholder, testid }) => (
  <div>
    <label className="block text-xs font-semibold mb-1">{label}</label>
    <input type={type} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid={testid} />
  </div>
);
const Toggle = ({ label, value, onChange, testid }) => (
  <label className="flex items-center gap-3 text-sm">
    <input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)} data-testid={testid} />
    {label}
  </label>
);
