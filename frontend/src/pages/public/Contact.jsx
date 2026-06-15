import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Mail, Phone, MapPin, Send, CheckCircle2, MessageCircle } from "lucide-react";
import { toast } from "sonner";
import TeamPresenceBadge from "@/components/TeamPresenceBadge";
import { useI18n } from "@/contexts/I18nContext";

export default function Contact() {
  const { t } = useI18n();
  const [info, setInfo] = useState(null);
  const [form, setForm] = useState({ name: "", email: "", phone: "", company: "", subject: "", message: "" });
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  useEffect(() => { apiClient.get("/company-info").then((r) => setInfo(r.data)).catch(() => {}); }, []);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await apiClient.post("/contact", form);
      setSent(true);
      toast.success(t("public.contact.success_toast", "Message envoyé. Nous reviendrons vers vous rapidement."));
      setForm({ name: "", email: "", phone: "", company: "", subject: "", message: "" });
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("public.contact.error", "Erreur lors de l'envoi"));
    } finally { setLoading(false); }
  };

  return (
    <section className="py-20" data-testid="contact-page">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 grid lg:grid-cols-5 gap-10">
        <div className="lg:col-span-2">
          <p className="text-xs uppercase tracking-[0.25em] text-sawali-blue-light">{t("public.contact.kicker", "Contact")}</p>
          <h1 className="mt-3 text-4xl sm:text-5xl font-display font-bold text-white">{t("public.contact.title", "Parlons de votre projet.")}</h1>
          <p className="mt-4 text-slate-300">{t("public.contact.subtitle", "Notre équipe revient vers vous sous 24h ouvrées.")}</p>
          <div className="mt-4">
            <TeamPresenceBadge tone="dark" />
          </div>
          <div className="mt-10 space-y-4 text-slate-300">
            <div className="flex items-center gap-3"><Mail className="h-5 w-5 text-sawali-blue-light" /> {info?.email}</div>
            <div className="flex items-center gap-3"><Phone className="h-5 w-5 text-sawali-blue-light" /> {info?.phone}</div>
            {info?.whatsapp && (
              <div className="flex items-center gap-3"><MessageCircle className="h-5 w-5 text-emerald-400" /> WhatsApp : {info.whatsapp}</div>
            )}
            <div className="flex items-center gap-3"><MapPin className="h-5 w-5 text-sawali-blue-light" /> {[info?.address, info?.city, info?.country].filter(Boolean).join(", ")}</div>
          </div>
        </div>
        <form onSubmit={submit} className="lg:col-span-3 glow-card rounded-2xl p-6 lg:p-8 space-y-4" data-testid="contact-form">
          {sent && (
            <div className="rounded-lg border border-emerald-400/30 bg-emerald-400/10 p-3 text-emerald-200 text-sm flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4" /> {t("public.contact.success_inline", "Message envoyé. Merci !")}
            </div>
          )}
          <div className="grid sm:grid-cols-2 gap-4">
            <Field label={t("public.contact.field_name", "Nom complet")} name="name" value={form.name} onChange={(v) => setForm({ ...form, name: v })} required />
            <Field label={t("public.contact.field_email", "Email")} name="email" type="email" value={form.email} onChange={(v) => setForm({ ...form, email: v })} required />
            <Field label={t("public.contact.field_phone", "Téléphone")} name="phone" value={form.phone} onChange={(v) => setForm({ ...form, phone: v })} />
            <Field label={t("public.contact.field_company", "Entreprise")} name="company" value={form.company} onChange={(v) => setForm({ ...form, company: v })} />
          </div>
          <Field label={t("public.contact.field_subject", "Sujet")} name="subject" value={form.subject} onChange={(v) => setForm({ ...form, subject: v })} />
          <div>
            <label className="block text-xs uppercase tracking-[0.2em] text-slate-400 mb-2">{t("public.contact.field_message", "Message")} *</label>
            <textarea
              required
              rows={6}
              value={form.message}
              onChange={(e) => setForm({ ...form, message: e.target.value })}
              className="w-full rounded-lg bg-white/5 border border-white/10 text-white placeholder:text-slate-500 px-4 py-3 text-sm focus:outline-none focus:border-sawali-blue"
              placeholder={t("public.contact.field_message_placeholder", "Décrivez votre besoin...")}
              data-testid="contact-message"
            />
          </div>
          <button type="submit" disabled={loading} className="btn-electric inline-flex items-center gap-2 rounded-lg px-5 py-3 font-medium" data-testid="contact-submit">
            <Send className="h-4 w-4" /> {loading ? t("public.contact.btn_sending", "Envoi...") : t("public.contact.btn_send", "Envoyer le message")}
          </button>
        </form>
      </div>
    </section>
  );
}

function Field({ label, name, value, onChange, type = "text", required }) {
  return (
    <div>
      <label className="block text-xs uppercase tracking-[0.2em] text-slate-400 mb-2">{label}{required && " *"}</label>
      <input
        type={type}
        required={required}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg bg-white/5 border border-white/10 text-white placeholder:text-slate-500 px-4 py-2.5 text-sm focus:outline-none focus:border-sawali-blue"
        data-testid={`contact-field-${name}`}
      />
    </div>
  );
}
