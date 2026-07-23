import React, { useEffect, useState, useRef } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ShieldCheck, Loader2, ArrowRight, KeyRound, Mail, MessageCircle, Phone } from "lucide-react";
import { LOGO_URL, AUTH_BG } from "@/lib/brand";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import PasswordInput from "@/components/PasswordInput";
import VersionStamp from "@/components/VersionStamp";

export default function Login() {
  const { login, user } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [step, setStep] = useState(searchParams.get("wa") === "1" ? "wa_phone" : "credentials"); // credentials | otp | wa_phone | wa_otp
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [captchaToken, setCaptchaToken] = useState(null);
  const [captchaCfg, setCaptchaCfg] = useState({ enabled: false, site_key: null });
  const [session, setSession] = useState(null);
  const [otp, setOtp] = useState("");
  const [devOtp, setDevOtp] = useState(null);
  const [loading, setLoading] = useState(false);
  // Iter38r-fix9o (Item 8) — WhatsApp OTP login state
  const [waPhone, setWaPhone] = useState("");
  const [waName, setWaName] = useState("");
  const [waOtp, setWaOtp] = useState("");
  const captchaRef = useRef(null);

  // Compute the post-login redirect target. Translators get a dedicated
  // landing page (/admin/i18n) since they have no access to the rest.
  // Iter43-fix24az-x (2026-07-22) — Médecins tracked land directly on
  // /portal/planning (no dashboard, no welcome briefing).
  const _postLoginRoute = (u) => {
    if (!u) return "/portal";
    if ((u.tracked_role || "") === "Traducteur") return "/admin/i18n";
    if ((u.tracked_role || "") === "Médecin") return "/portal/planning";
    return u.role === "admin" ? "/admin" : "/portal";
  };

  useEffect(() => {
    if (user) navigate(_postLoginRoute(user));
  }, [user, navigate]);

  // Deep-link auto-prefill : if the user arrived via /launch?t=..., the Launch
  // page has stashed the decoded claims in sessionStorage — consume them once.
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem("sawali_launch_claims");
      if (!raw) return;
      const claims = JSON.parse(raw);
      if (claims?.username) setEmail(claims.username);
      sessionStorage.removeItem("sawali_launch_claims");
      if (claims?.action === "login") {
        toast.info(`Lien sécurisé reçu (${claims.client_code || "—"}). Merci de saisir votre mot de passe.`);
      }
    } catch { /* noop */ }
  }, []);

  useEffect(() => {
    apiClient.get("/auth/captcha-config").then((r) => setCaptchaCfg(r.data)).catch(() => {});
  }, []);

  // Load reCAPTCHA script when site_key is available
  useEffect(() => {
    if (!captchaCfg.enabled || !captchaCfg.site_key) return;
    if (document.getElementById("recaptcha-script")) {
      try { window.grecaptcha?.render(captchaRef.current, { sitekey: captchaCfg.site_key, callback: setCaptchaToken }); } catch {}
      return;
    }
    const s = document.createElement("script");
    s.id = "recaptcha-script";
    s.src = "https://www.google.com/recaptcha/api.js?render=explicit";
    s.async = true;
    s.defer = true;
    s.onload = () => {
      window.grecaptcha?.ready(() => {
        try { window.grecaptcha.render(captchaRef.current, { sitekey: captchaCfg.site_key, callback: setCaptchaToken }); } catch {}
      });
    };
    document.head.appendChild(s);
  }, [captchaCfg]);

  const [loginMsg, setLoginMsg] = useState(null);

  const submitCreds = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const r = await apiClient.post("/auth/login", { email, password, captcha_token: captchaToken });
      setSession(r.data.session_token);
      setDevOtp(r.data.dev_otp || null);
      setLoginMsg(r.data.message || null);
      setStep("otp");
      toast.success(r.data.message);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de connexion");
    } finally { setLoading(false); }
  };

  const submitOtp = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const r = await apiClient.post("/auth/verify-otp", { session_token: session, code: otp });
      login(r.data.access_token, r.data.user);
      toast.success("Connexion réussie");
      navigate(_postLoginRoute(r.data.user));
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Code invalide");
    } finally { setLoading(false); }
  };

  const resend = async () => {
    try {
      const r = await apiClient.post(`/auth/resend-otp?session_token=${encodeURIComponent(session)}`);
      setDevOtp(r.data.dev_otp || null);
      toast.success("Nouveau code envoyé");
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  // Iter38r-fix9o (Item 8) — WhatsApp OTP login flow
  const requestWaOtp = async (e) => {
    e.preventDefault();
    const digits = waPhone.replace(/\D/g, "");
    if (digits.length < 8) { toast.error("Numéro WhatsApp invalide"); return; }
    setLoading(true);
    try {
      const r = await apiClient.post("/auth/wa-otp/request", { msisdn: digits });
      toast.success(`Code envoyé sur WhatsApp (${r.data.sent_via === "template" ? "modèle officiel" : "message direct"}). Valable 10 min.`);
      setStep("wa_otp");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Impossible d'envoyer le code WhatsApp");
    } finally { setLoading(false); }
  };

  const verifyWaOtp = async (e) => {
    e.preventDefault();
    const digits = waPhone.replace(/\D/g, "");
    setLoading(true);
    try {
      const r = await apiClient.post("/auth/wa-otp/verify", {
        msisdn: digits, code: waOtp, display_name: waName || undefined,
      });
      login(r.data.access_token || r.data.token, r.data.user);
      toast.success("Connexion WhatsApp réussie — bienvenue !");
      navigate(_postLoginRoute(r.data.user));
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Code invalide");
    } finally { setLoading(false); }
  };

  return (
    <div
      className="min-h-screen grid lg:grid-cols-2"
      style={{
        color: "var(--login-text, inherit)",
      }}
      data-testid="login-page"
    >
      {/* Left: brand */}
      <div
        className="relative hidden lg:flex items-end p-12 marketing-dark overflow-hidden"
        style={{
          background: "var(--login-bg, transparent)",
        }}
      >
        <div className="absolute inset-0">
          <img src={AUTH_BG} alt="" className="w-full h-full object-cover opacity-50" />
          <div className="absolute inset-0 bg-gradient-to-tr from-[#081226]/95 via-[#081226]/70 to-transparent" />
        </div>
        <div className="relative z-10" style={{ color: "var(--login-text, #ffffff)" }}>
          <Link to="/" className="flex items-center gap-3 mb-8">
            <img src={LOGO_URL} alt="SAWALI" className="h-12 w-12 rounded-lg ring-1 ring-white/20" />
            <div>
              <p className="font-display font-bold text-lg">SAWALI SMART SYSTEMS</p>
              <p className="text-[10px] uppercase tracking-[0.3em] text-sawali-blue-light">Software Engineering</p>
            </div>
          </Link>
          <h2 className="text-4xl font-display font-bold leading-tight max-w-md">Bienvenue dans votre Espace Loois sécurisé.</h2>
          <p className="mt-4 max-w-md" style={{ color: "var(--login-text, #cbd5e1)" }}>
            Suivez vos rendez-vous, accédez à la documentation de vos logiciels et consultez l'historique de nos interventions.
          </p>
        </div>
      </div>

      {/* Right: form */}
      <div
        className="flex items-center justify-center p-6 sm:p-12"
        style={{ background: "var(--login-bg, #f8fafc)" }}
      >
        <div className="w-full max-w-md">
          <Link to="/" className="lg:hidden flex items-center gap-3 mb-6">
            <img src={LOGO_URL} alt="SAWALI" className="h-10 w-10 rounded-md" />
            <span className="font-display font-bold">SAWALI SMART SYSTEMS</span>
          </Link>

          <div
            className="rounded-2xl border border-slate-200 p-7 shadow-sm"
            style={{
              background: "var(--login-card-bg, #ffffff)",
              color: "var(--login-card-text, inherit)",
            }}
          >
            <div className="flex items-center gap-2 text-sawali-blue">
              <ShieldCheck className="h-4 w-4" />
              <span className="text-xs uppercase tracking-[0.25em] font-semibold">{step === "credentials" ? "Connexion" : "Vérification 2FA"}</span>
            </div>
            <h1 className="mt-3 text-2xl font-display font-bold text-slate-900">
              {step === "credentials" ? "Espace Loois"
                : step === "otp" ? "Code de vérification"
                : step === "wa_phone" ? "Connexion par WhatsApp"
                : "Code reçu par WhatsApp"}
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              {step === "credentials" ? "Saisissez vos identifiants. Un code à usage unique vous sera envoyé."
                : step === "otp" ? "Saisissez le code à 6 chiffres reçu par email."
                : step === "wa_phone" ? "Recevez un code à 6 chiffres directement sur WhatsApp pour accéder à votre espace."
                : "Saisissez le code à 6 chiffres reçu sur WhatsApp."}
            </p>

            {step === "credentials" ? (
              <>
                <form onSubmit={submitCreds} className="mt-6 space-y-4" data-testid="login-credentials-form">
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 mb-1">Email</label>
                    <div className="relative">
                      <Mail className="absolute left-3 top-3 h-4 w-4 text-slate-400" />
                      <input
                        required type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                        className="w-full rounded-lg border border-slate-300 pl-9 pr-3 py-2.5 text-sm focus:outline-none focus:border-sawali-blue focus:ring-2 focus:ring-sawali-blue/20"
                        placeholder="vous@entreprise.com"
                        data-testid="login-email"
                      />
                    </div>
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 mb-1">Mot de passe</label>
                    <PasswordInput
                      required
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className="w-full rounded-lg border border-slate-300 py-2.5 text-sm focus:outline-none focus:border-sawali-blue focus:ring-2 focus:ring-sawali-blue/20"
                      placeholder="••••••••"
                      icon={<KeyRound className="h-4 w-4" />}
                      testid="login-password"
                    />
                  </div>
                  {captchaCfg.enabled && captchaCfg.site_key && (
                    <div ref={captchaRef} data-testid="recaptcha-widget" />
                  )}
                  <button
                    type="submit"
                    disabled={loading}
                    className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2.5 text-sm font-medium hover:bg-sawali-blue-light transition"
                    style={{
                      background: "var(--login-btn-bg, var(--brand-primary, #1E90FF))",
                      color: "var(--login-btn-text, #ffffff)",
                    }}
                    data-testid="login-submit-button"
                  >
                    {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
                    Se connecter
                  </button>
                </form>
                {/* Iter38r-fix9o (Item 8) — Alternative: WhatsApp OTP login */}
                <div className="my-5 flex items-center gap-3">
                  <div className="flex-1 h-px bg-slate-200" />
                  <span className="text-[10px] uppercase tracking-wider text-slate-400">ou</span>
                  <div className="flex-1 h-px bg-slate-200" />
                </div>
                <button
                  type="button"
                  onClick={() => setStep("wa_phone")}
                  className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2.5 text-sm font-medium transition"
                  data-testid="login-wa-otp-button"
                >
                  <MessageCircle className="h-4 w-4" /> Se connecter via WhatsApp
                </button>
                <p className="text-xs text-slate-500 text-center mt-3">
                  Pas encore de compte ? <Link to="/contact" className="text-sawali-blue underline">Demander un accès</Link>
                </p>
              </>
            ) : step === "otp" ? (
              <form onSubmit={submitOtp} className="mt-6 space-y-4" data-testid="login-otp-form">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">Code à 6 chiffres</label>
                  <input
                    required value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))}
                    className="w-full rounded-lg border border-slate-300 px-3 py-3 text-center font-mono text-2xl tracking-[0.5em] focus:outline-none focus:border-sawali-blue"
                    placeholder="••••••"
                    maxLength={6}
                    data-testid="login-otp-input"
                  />
                </div>
                {devOtp && (
                  <div className={`rounded-lg border p-3 text-xs ${
                    loginMsg && loginMsg.toLowerCase().includes("interne")
                      ? "border-sawali-blue/30 bg-sawali-blue/5 text-sawali-blue"
                      : "border-amber-300 bg-amber-50 text-amber-900"
                  }`} data-testid="login-otp-inline-notice">
                    <strong>
                      {loginMsg && loginMsg.toLowerCase().includes("interne")
                        ? "Plateforme Interne :"
                        : "Service e-mail indisponible :"}
                    </strong>{" "}
                    Code OTP : <span className="font-mono text-base font-bold" data-testid="login-dev-otp">{devOtp}</span>
                  </div>
                )}
                <button type="submit" disabled={loading || otp.length !== 6} className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2.5 text-sm font-medium hover:bg-sawali-blue-light transition disabled:opacity-50" data-testid="login-verify-otp-button">
                  {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />} Vérifier le code
                </button>
                <div className="flex items-center justify-between text-xs">
                  <button type="button" onClick={resend} className="text-sawali-blue underline" data-testid="login-resend-otp">Renvoyer le code</button>
                  <button type="button" onClick={() => setStep("credentials")} className="text-slate-500 underline">Modifier l'email</button>
                </div>
              </form>
            ) : step === "wa_phone" ? (
              <form onSubmit={requestWaOtp} className="mt-6 space-y-4" data-testid="login-wa-phone-form">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">Votre numéro WhatsApp</label>
                  <div className="relative">
                    <Phone className="absolute left-3 top-3 h-4 w-4 text-slate-400" />
                    <input
                      required type="tel" value={waPhone}
                      onChange={(e) => setWaPhone(e.target.value)}
                      className="w-full rounded-lg border border-slate-300 pl-9 pr-3 py-2.5 text-sm font-mono focus:outline-none focus:border-emerald-600 focus:ring-2 focus:ring-emerald-200"
                      placeholder="+22670000000"
                      data-testid="login-wa-phone-input"
                    />
                  </div>
                  <p className="text-[11px] text-slate-500 mt-1">Format international (avec indicatif pays).</p>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">Votre nom (optionnel)</label>
                  <input
                    type="text" value={waName}
                    onChange={(e) => setWaName(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm focus:outline-none focus:border-emerald-600 focus:ring-2 focus:ring-emerald-200"
                    placeholder="Prénom Nom"
                    data-testid="login-wa-name-input"
                  />
                </div>
                <button type="submit" disabled={loading} className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2.5 text-sm font-medium transition disabled:opacity-50" data-testid="login-wa-request-button">
                  {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <MessageCircle className="h-4 w-4" />} Recevoir le code par WhatsApp
                </button>
                <button type="button" onClick={() => setStep("credentials")} className="w-full text-xs text-slate-500 underline" data-testid="login-wa-back">
                  ← Retour à la connexion classique
                </button>
              </form>
            ) : (
              <form onSubmit={verifyWaOtp} className="mt-6 space-y-4" data-testid="login-wa-otp-form">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">Code reçu sur WhatsApp</label>
                  <input
                    required value={waOtp}
                    onChange={(e) => setWaOtp(e.target.value.replace(/\D/g, "").slice(0, 6))}
                    className="w-full rounded-lg border border-slate-300 px-3 py-3 text-center font-mono text-2xl tracking-[0.5em] focus:outline-none focus:border-emerald-600"
                    placeholder="••••••"
                    maxLength={6}
                    data-testid="login-wa-otp-input"
                  />
                  <p className="text-[11px] text-slate-500 mt-1 text-center">Code envoyé sur <span className="font-mono">{waPhone}</span></p>
                </div>
                <button type="submit" disabled={loading || waOtp.length !== 6} className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2.5 text-sm font-medium transition disabled:opacity-50" data-testid="login-wa-verify-button">
                  {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />} Valider et accéder à mon espace
                </button>
                <div className="flex items-center justify-between text-xs">
                  <button type="button" onClick={() => setStep("wa_phone")} className="text-emerald-700 underline">← Changer de numéro</button>
                  <button type="button" onClick={() => setStep("credentials")} className="text-slate-500 underline">Annuler</button>
                </div>
              </form>
            )}
          </div>

          <p className="mt-6 text-center text-xs text-slate-500">
            <Link to="/" className="text-sawali-blue underline">← Retour au site public</Link>
          </p>
        </div>
      </div>
      {/* Iter35n — Version stamp identique au reste de l'app (configurable dans /admin/settings) */}
      <VersionStamp />
    </div>
  );
}
