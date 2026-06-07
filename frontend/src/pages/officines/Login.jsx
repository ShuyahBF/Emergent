// Iter42 — Officine portal: combined Login / Register page
import React from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { officineApi, saveOfficineSession } from "@/lib/officineApi";
import { LOGO_URL } from "@/lib/brand";
import { MessageCircle, Smartphone, Mail, UserPlus, LogIn, ShieldCheck } from "lucide-react";

const TABS = [
  { id: "otp", label: "Code OTP", icon: Smartphone },
  { id: "magic", label: "Lien email", icon: Mail },
  { id: "register", label: "Inscription", icon: UserPlus },
];

export default function OfficineLogin() {
  const [tab, setTab] = React.useState("otp");
  return (
    <div className="min-h-screen bg-gradient-to-br from-[#0E1F3D] via-[#11264a] to-[#0E1F3D] flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-6">
          <img src={LOGO_URL} alt="SAWALI" className="h-14 w-14 mx-auto rounded-lg object-cover ring-1 ring-white/30" />
          <p className="mt-3 text-xs uppercase tracking-[0.25em] text-sky-200">Portail Officines</p>
          <h1 className="text-2xl font-display font-bold text-white mt-1">SAWALI Smart Systems</h1>
          <p className="text-sm text-sky-100/70 mt-1">Gérez votre pharmacie en self-service</p>
        </div>

        <div className="bg-white rounded-2xl shadow-2xl overflow-hidden">
          <div className="flex border-b border-slate-200" data-testid="officine-login-tabs">
            {TABS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                className={`flex-1 inline-flex items-center justify-center gap-1.5 px-2 py-3 text-xs font-medium border-b-2 transition ${
                  tab === id ? "border-sawali-blue text-sawali-blue" : "border-transparent text-slate-500 hover:text-slate-700"
                }`}
                data-testid={`officine-tab-${id}`}
              >
                <Icon className="h-4 w-4" />
                {label}
              </button>
            ))}
          </div>
          <div className="p-6">
            {tab === "otp" && <OtpForm />}
            {tab === "magic" && <MagicForm />}
            {tab === "register" && <RegisterForm onDone={() => setTab("otp")} />}
          </div>
        </div>

        <p className="text-center text-xs text-sky-100/60 mt-4">
          Besoin d&apos;aide ? Contactez votre administrateur SAWALI.
        </p>
      </div>
    </div>
  );
}

function OtpForm() {
  const navigate = useNavigate();
  const [identifier, setIdentifier] = React.useState("");
  const [channel, setChannel] = React.useState("wa");
  const [code, setCode] = React.useState("");
  const [step, setStep] = React.useState("request");
  const [busy, setBusy] = React.useState(false);

  const requestOtp = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await officineApi.post("/officines-portal/auth/request-otp", { identifier, channel });
      toast.success(`Code envoyé via ${r.data.sent_via} (${r.data.expires_in_minutes} min)`);
      setStep("verify");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec de l'envoi");
    } finally {
      setBusy(false);
    }
  };

  const verifyOtp = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await officineApi.post("/officines-portal/auth/verify-otp", { identifier, code });
      saveOfficineSession(r.data.token, r.data.officine);
      toast.success("Connecté");
      navigate("/officines", { replace: true });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Code invalide");
    } finally {
      setBusy(false);
    }
  };

  if (step === "request") {
    return (
      <form onSubmit={requestOtp} className="space-y-4" data-testid="officine-otp-request-form">
        <div>
          <label className="block text-xs font-medium text-slate-700 mb-1">Email OU numéro de téléphone</label>
          <input
            type="text"
            required
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            placeholder="email@officine.com ou +22501234567"
            className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sawali-blue"
            data-testid="officine-otp-identifier"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-700 mb-2">Canal de réception</label>
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => setChannel("wa")}
              className={`inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium ring-1 transition ${
                channel === "wa" ? "bg-emerald-50 text-emerald-700 ring-emerald-300" : "bg-slate-50 text-slate-600 ring-slate-200 hover:bg-slate-100"
              }`}
              data-testid="officine-otp-channel-wa"
            >
              <MessageCircle className="h-4 w-4" /> WhatsApp
            </button>
            <button
              type="button"
              onClick={() => setChannel("sms")}
              className={`inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium ring-1 transition ${
                channel === "sms" ? "bg-sky-50 text-sky-700 ring-sky-300" : "bg-slate-50 text-slate-600 ring-slate-200 hover:bg-slate-100"
              }`}
              data-testid="officine-otp-channel-sms"
            >
              <Smartphone className="h-4 w-4" /> SMS
            </button>
          </div>
        </div>
        <button
          type="submit"
          disabled={busy || !identifier}
          className="w-full inline-flex items-center justify-center gap-2 bg-sawali-blue text-white font-medium py-2.5 rounded-lg hover:bg-sawali-blue/90 disabled:opacity-50 transition"
          data-testid="officine-otp-request-submit"
        >
          {busy ? "Envoi..." : "Envoyer le code"}
        </button>
      </form>
    );
  }

  return (
    <form onSubmit={verifyOtp} className="space-y-4" data-testid="officine-otp-verify-form">
      <p className="text-sm text-slate-600">
        Un code à 6 chiffres a été envoyé à votre {channel === "wa" ? "WhatsApp" : "téléphone"}.
      </p>
      <div>
        <label className="block text-xs font-medium text-slate-700 mb-1">Code reçu</label>
        <input
          type="text"
          required
          inputMode="numeric"
          pattern="[0-9]{6}"
          maxLength={6}
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
          placeholder="123456"
          className="w-full border rounded-lg px-3 py-2 text-center text-lg tracking-[0.5em] font-mono focus:outline-none focus:ring-2 focus:ring-sawali-blue"
          data-testid="officine-otp-code"
        />
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setStep("request")}
          className="px-3 py-2.5 rounded-lg text-xs font-medium bg-slate-100 text-slate-700 hover:bg-slate-200"
          data-testid="officine-otp-back"
        >
          ← Retour
        </button>
        <button
          type="submit"
          disabled={busy || code.length !== 6}
          className="flex-1 inline-flex items-center justify-center gap-2 bg-sawali-blue text-white font-medium py-2.5 rounded-lg hover:bg-sawali-blue/90 disabled:opacity-50 transition"
          data-testid="officine-otp-verify-submit"
        >
          <LogIn className="h-4 w-4" /> {busy ? "Vérification..." : "Se connecter"}
        </button>
      </div>
    </form>
  );
}

function MagicForm() {
  const [email, setEmail] = React.useState("");
  const [sent, setSent] = React.useState(false);
  const [busy, setBusy] = React.useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await officineApi.post("/officines-portal/auth/magic-link", { email });
      setSent(true);
      toast.success("Si un compte existe, un email a été envoyé.");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec de l'envoi");
    } finally {
      setBusy(false);
    }
  };

  if (sent) {
    return (
      <div className="text-center py-6" data-testid="officine-magic-sent">
        <ShieldCheck className="h-10 w-10 text-emerald-500 mx-auto" />
        <p className="mt-3 text-sm font-medium text-slate-800">Vérifiez vos emails</p>
        <p className="mt-1 text-xs text-slate-500">
          Si une officine existe avec cet email, un lien de connexion vous a été envoyé.
          <br />Le lien est valable 15 minutes.
        </p>
        <button
          onClick={() => setSent(false)}
          className="mt-4 text-xs text-sawali-blue hover:underline"
          data-testid="officine-magic-resend"
        >
          Renvoyer un lien
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-4" data-testid="officine-magic-form">
      <div>
        <label className="block text-xs font-medium text-slate-700 mb-1">Email de l&apos;officine</label>
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="contact@officine.com"
          className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sawali-blue"
          data-testid="officine-magic-email"
        />
      </div>
      <button
        type="submit"
        disabled={busy || !email}
        className="w-full inline-flex items-center justify-center gap-2 bg-sawali-blue text-white font-medium py-2.5 rounded-lg hover:bg-sawali-blue/90 disabled:opacity-50 transition"
        data-testid="officine-magic-submit"
      >
        <Mail className="h-4 w-4" /> {busy ? "Envoi..." : "Recevoir un lien"}
      </button>
    </form>
  );
}

function RegisterForm({ onDone }) {
  const [form, setForm] = React.useState({
    name: "", email: "", phone: "", city: "", country: "", address: "",
    contact_name: "", linked_client_email: "",
  });
  const [busy, setBusy] = React.useState(false);
  const [done, setDone] = React.useState(false);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const payload = { ...form };
      if (!payload.linked_client_email) delete payload.linked_client_email;
      await officineApi.post("/officines-portal/register", payload);
      setDone(true);
      toast.success("Inscription enregistrée — en attente de validation admin");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec de l'inscription");
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <div className="text-center py-4" data-testid="officine-register-done">
        <ShieldCheck className="h-10 w-10 text-emerald-500 mx-auto" />
        <p className="mt-3 text-sm font-medium text-slate-800">Demande envoyée</p>
        <p className="mt-2 text-xs text-slate-600 leading-relaxed">
          Votre officine sera activée après validation par l&apos;administrateur SAWALI.
          <br />Vous recevrez une notification dès que votre compte sera actif.
        </p>
        <button
          onClick={onDone}
          className="mt-4 text-xs px-4 py-2 rounded-lg bg-sawali-blue text-white hover:bg-sawali-blue/90"
          data-testid="officine-register-back"
        >
          Retour à la connexion
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-3 max-h-[60vh] overflow-y-auto" data-testid="officine-register-form">
      <Field label="Nom de la pharmacie *" testid="register-name">
        <input required value={form.name} onChange={set("name")} className="w-full border rounded px-3 py-2 text-sm" />
      </Field>
      <Field label="Email *" testid="register-email">
        <input required type="email" value={form.email} onChange={set("email")} className="w-full border rounded px-3 py-2 text-sm" />
      </Field>
      <Field label="Téléphone (WhatsApp) *" testid="register-phone">
        <input required value={form.phone} onChange={set("phone")} placeholder="+22501234567" className="w-full border rounded px-3 py-2 text-sm" />
      </Field>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Ville" testid="register-city">
          <input value={form.city} onChange={set("city")} className="w-full border rounded px-3 py-2 text-sm" />
        </Field>
        <Field label="Pays" testid="register-country">
          <input value={form.country} onChange={set("country")} className="w-full border rounded px-3 py-2 text-sm" />
        </Field>
      </div>
      <Field label="Adresse" testid="register-address">
        <input value={form.address} onChange={set("address")} className="w-full border rounded px-3 py-2 text-sm" />
      </Field>
      <Field label="Nom du contact" testid="register-contact">
        <input value={form.contact_name} onChange={set("contact_name")} className="w-full border rounded px-3 py-2 text-sm" />
      </Field>
      <Field label="Email d'un client CRM associé (optionnel)" testid="register-linked">
        <input type="email" value={form.linked_client_email} onChange={set("linked_client_email")} placeholder="client@example.com" className="w-full border rounded px-3 py-2 text-sm" />
      </Field>
      <button
        type="submit"
        disabled={busy}
        className="w-full inline-flex items-center justify-center gap-2 bg-sawali-blue text-white font-medium py-2.5 rounded-lg hover:bg-sawali-blue/90 disabled:opacity-50 transition"
        data-testid="officine-register-submit"
      >
        <UserPlus className="h-4 w-4" /> {busy ? "Envoi..." : "S'inscrire"}
      </button>
    </form>
  );
}

function Field({ label, children, testid }) {
  return (
    <div data-testid={testid}>
      <label className="block text-xs font-medium text-slate-700 mb-1">{label}</label>
      {children}
    </div>
  );
}
