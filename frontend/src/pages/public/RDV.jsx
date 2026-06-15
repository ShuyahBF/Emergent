import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { Calendar as CalendarIcon, Clock, ArrowRight, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import { useI18n } from "@/contexts/I18nContext";

const formatDate = (d) => d.toISOString().slice(0, 10);
const dayLabel = (d) =>
  d.toLocaleDateString("fr-FR", { weekday: "short", day: "2-digit", month: "short" });

export default function RDV() {
  const { t } = useI18n();
  const [params] = useSearchParams();
  const [days, setDays] = useState([]);
  const [selectedDate, setSelectedDate] = useState(null);
  const [slots, setSlots] = useState([]);
  const [selectedSlot, setSelectedSlot] = useState(null);
  const [loadingSlots, setLoadingSlots] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", phone: "", company: "", subject: "", message: "" });
  const [sending, setSending] = useState(false);
  const [success, setSuccess] = useState(null);

  // Iter38f — Pre-fill subject/message when arriving from a catalogue CTA
  useEffect(() => {
    const product = params.get("product");
    const sku = params.get("sku");
    if (product) {
      const subject = `Demande de devis — ${product}`.slice(0, 200);
      const message = `Bonjour,\n\nJe souhaite recevoir un devis pour : ${product}${sku ? ` (réf. ${sku})` : ""}.\n\nMerci de me recontacter.`;
      setForm((f) => ({
        ...f,
        subject: f.subject || subject,
        message: f.message || message,
      }));
    }
  }, [params]);

  useEffect(() => {
    const list = [];
    const today = new Date();
    for (let i = 0; i < 14; i++) {
      const d = new Date(today.getTime() + i * 24 * 60 * 60 * 1000);
      list.push(d);
    }
    setDays(list);
    setSelectedDate(formatDate(today));
  }, []);

  useEffect(() => {
    if (!selectedDate) return;
    setLoadingSlots(true);
    setSelectedSlot(null);
    apiClient
      .get(`/availability?date=${selectedDate}`)
      .then((r) => setSlots(r.data.slots || []))
      .catch(() => setSlots([]))
      .finally(() => setLoadingSlots(false));
  }, [selectedDate]);

  const submit = async (e) => {
    e.preventDefault();
    if (!selectedSlot) return toast.error(t("public.rdv.error_no_slot", "Choisissez un créneau horaire"));
    setSending(true);
    try {
      const r = await apiClient.post("/appointments/public", {
        ...form,
        scheduled_at: selectedSlot.start,
        duration_min: 30,
      });
      setSuccess(r.data.appointment);
      toast.success(t("public.rdv.success_toast", "RDV demandé. Confirmation à venir par email."));
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("public.rdv.error_generic", "Erreur lors de la prise de RDV"));
    } finally { setSending(false); }
  };

  if (success) {
    return (
      <section className="py-24" data-testid="rdv-success">
        <div className="mx-auto max-w-2xl px-4 text-center">
          <div className="mx-auto h-16 w-16 rounded-full bg-emerald-400/15 border border-emerald-400/40 flex items-center justify-center">
            <CheckCircle2 className="h-8 w-8 text-emerald-300" />
          </div>
          <h1 className="mt-6 text-3xl sm:text-4xl font-display font-bold text-white">{t("public.rdv.success_title", "Rendez-vous enregistré !")}</h1>
          <p className="mt-4 text-slate-300">
            {t("public.rdv.success_body_1", "Nous avons bien reçu votre demande pour le")}{" "}
            <strong className="text-sawali-blue-light">
              {new Date(success.scheduled_at).toLocaleString("fr-FR", { dateStyle: "full", timeStyle: "short" })}
            </strong>.
          </p>
          <p className="mt-2 text-slate-400 text-sm">{t("public.rdv.success_ref", "Référence :")} {success.id}</p>
        </div>
      </section>
    );
  }

  return (
    <section className="py-20" data-testid="rdv-page">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <p className="text-xs uppercase tracking-[0.25em] text-sawali-blue-light">{t("public.rdv.kicker", "Prise de rendez-vous")}</p>
        <h1 className="mt-3 text-4xl sm:text-5xl font-display font-bold text-white">{t("public.rdv.title", "Réserver un créneau")}</h1>
        <p className="mt-3 text-slate-300 max-w-2xl">{t("public.rdv.subtitle", "Choisissez une date et un horaire disponibles, puis renseignez vos coordonnées.")}</p>

        {/* Date strip */}
        <div className="mt-10 flex gap-2 overflow-x-auto pb-2" data-testid="rdv-day-strip">
          {days.map((d) => {
            const k = formatDate(d);
            const active = k === selectedDate;
            return (
              <button
                key={k}
                onClick={() => setSelectedDate(k)}
                className={`min-w-[88px] rounded-xl border px-4 py-3 text-center transition ${
                  active ? "bg-sawali-blue text-white border-sawali-blue" : "bg-white/5 border-white/10 text-slate-300 hover:bg-white/10"
                }`}
                data-testid={`rdv-day-${k}`}
              >
                <div className="text-[10px] uppercase tracking-widest">{dayLabel(d)}</div>
                <div className="mt-1 text-base font-display font-semibold">{d.getDate()}</div>
              </button>
            );
          })}
        </div>

        {/* Slots + form */}
        <div className="mt-8 grid lg:grid-cols-5 gap-6">
          <div className="lg:col-span-3 glow-card rounded-2xl p-6">
            <div className="flex items-center gap-2 text-white">
              <Clock className="h-4 w-4 text-sawali-blue-light" />
              <h2 className="font-display font-semibold">{t("public.rdv.slots_title", "Créneaux disponibles")}</h2>
            </div>
            {loadingSlots ? (
              <p className="mt-4 text-slate-400 text-sm">{t("public.rdv.loading", "Chargement...")}</p>
            ) : slots.length === 0 ? (
              <p className="mt-4 text-slate-400 text-sm">{t("public.rdv.no_slots", "Aucun créneau disponible ce jour.")}</p>
            ) : (
              <div className="mt-5 grid grid-cols-3 sm:grid-cols-4 gap-2">
                {slots.map((s) => {
                  const time = new Date(s.start).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
                  const active = selectedSlot?.start === s.start;
                  return (
                    <button
                      key={s.start}
                      disabled={!s.available}
                      onClick={() => setSelectedSlot(s)}
                      className={`rounded-lg border px-3 py-2 text-sm transition ${
                        !s.available
                          ? "border-white/5 bg-white/[0.02] text-slate-600 cursor-not-allowed line-through"
                          : active
                          ? "bg-sawali-blue text-white border-sawali-blue"
                          : "border-white/10 text-white hover:bg-white/10"
                      }`}
                      data-testid={`rdv-slot-${s.start}`}
                    >
                      {time}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <form onSubmit={submit} className="lg:col-span-2 glow-card rounded-2xl p-6 space-y-3" data-testid="rdv-form">
            <h2 className="font-display font-semibold text-white flex items-center gap-2"><CalendarIcon className="h-4 w-4 text-sawali-blue-light" /> {t("public.rdv.form_title", "Vos coordonnées")}</h2>
            {[
              ["name", `${t("public.rdv.field_name", "Nom complet")} *`],
              ["email", `${t("public.rdv.field_email", "Email")} *`],
              ["phone", `${t("public.rdv.field_phone", "Téléphone")} *`],
              ["company", t("public.rdv.field_company", "Entreprise")],
              ["subject", `${t("public.rdv.field_subject", "Sujet")} *`],
            ].map(([n, l]) => (
              <div key={n}>
                <label className="block text-[10px] uppercase tracking-[0.2em] text-slate-400 mb-1">{l}</label>
                <input
                  required={l.includes("*")}
                  type={n === "email" ? "email" : "text"}
                  value={form[n]}
                  onChange={(e) => setForm({ ...form, [n]: e.target.value })}
                  className="w-full rounded-lg bg-white/5 border border-white/10 text-white px-3 py-2 text-sm focus:outline-none focus:border-sawali-blue"
                  data-testid={`rdv-field-${n}`}
                />
              </div>
            ))}
            <div>
              <label className="block text-[10px] uppercase tracking-[0.2em] text-slate-400 mb-1">{t("public.rdv.field_message", "Message")}</label>
              <textarea
                rows={3}
                value={form.message}
                onChange={(e) => setForm({ ...form, message: e.target.value })}
                className="w-full rounded-lg bg-white/5 border border-white/10 text-white px-3 py-2 text-sm"
                data-testid="rdv-field-message"
              />
            </div>
            <button type="submit" disabled={sending || !selectedSlot} className="btn-electric inline-flex items-center justify-center w-full gap-2 rounded-lg px-4 py-3 font-medium disabled:opacity-50" data-testid="rdv-submit">
              {sending ? t("public.rdv.btn_sending", "Envoi...") : t("public.rdv.btn_submit", "Confirmer ma demande")} <ArrowRight className="h-4 w-4" />
            </button>
            {selectedSlot && (
              <p className="text-xs text-slate-400">{t("public.rdv.slot_chosen", "Créneau choisi :")} {new Date(selectedSlot.start).toLocaleString("fr-FR", { dateStyle: "full", timeStyle: "short" })}</p>
            )}
          </form>
        </div>
      </div>
    </section>
  );
}
