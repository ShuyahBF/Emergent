import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { useSearchParams } from "react-router-dom";
import { Save, ShieldCheck, Calendar, Mail, ExternalLink, AlertCircle, CheckCircle2 } from "lucide-react";
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
      for (const k of ["smtp_password", "google_client_secret", "recaptcha_secret_key"]) {
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
        <div className="grid sm:grid-cols-3 gap-3">
          <Input label="Ouverture" type="time" value={s.business_open_time || "09:00"} onChange={(v) => upd("business_open_time", v)} testid="open-time" />
          <Input label="Fermeture" type="time" value={s.business_close_time || "18:00"} onChange={(v) => upd("business_close_time", v)} testid="close-time" />
          <Input label="Durée créneau (min)" type="number" value={s.slot_duration_min || 30} onChange={(v) => upd("slot_duration_min", parseInt(v) || 30)} testid="slot-duration" />
        </div>
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
