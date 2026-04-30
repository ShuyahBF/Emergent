import React, { useEffect, useState, useRef } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ShieldCheck, Loader2, ArrowRight, KeyRound, Mail } from "lucide-react";
import { LOGO_URL, AUTH_BG } from "@/lib/brand";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import PasswordInput from "@/components/PasswordInput";

export default function Login() {
  const { login, user } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState("credentials"); // credentials | otp
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [captchaToken, setCaptchaToken] = useState(null);
  const [captchaCfg, setCaptchaCfg] = useState({ enabled: false, site_key: null });
  const [session, setSession] = useState(null);
  const [otp, setOtp] = useState("");
  const [devOtp, setDevOtp] = useState(null);
  const [loading, setLoading] = useState(false);
  const captchaRef = useRef(null);

  useEffect(() => {
    if (user) navigate(user.role === "admin" ? "/admin" : "/portal");
  }, [user, navigate]);

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

  const submitCreds = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const r = await apiClient.post("/auth/login", { email, password, captcha_token: captchaToken });
      setSession(r.data.session_token);
      setDevOtp(r.data.dev_otp || null);
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
      navigate(r.data.user.role === "admin" ? "/admin" : "/portal");
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

  return (
    <div className="min-h-screen grid lg:grid-cols-2" data-testid="login-page">
      {/* Left: brand */}
      <div className="relative hidden lg:flex items-end p-12 marketing-dark overflow-hidden">
        <div className="absolute inset-0">
          <img src={AUTH_BG} alt="" className="w-full h-full object-cover opacity-50" />
          <div className="absolute inset-0 bg-gradient-to-tr from-[#081226]/95 via-[#081226]/70 to-transparent" />
        </div>
        <div className="relative z-10 text-white">
          <Link to="/" className="flex items-center gap-3 mb-8">
            <img src={LOGO_URL} alt="SAWALI" className="h-12 w-12 rounded-lg ring-1 ring-white/20" />
            <div>
              <p className="font-display font-bold text-lg">SAWALI SMART SYSTEMS</p>
              <p className="text-[10px] uppercase tracking-[0.3em] text-sawali-blue-light">Software Engineering</p>
            </div>
          </Link>
          <h2 className="text-4xl font-display font-bold leading-tight max-w-md">Bienvenue dans votre espace client sécurisé.</h2>
          <p className="mt-4 text-slate-300 max-w-md">
            Suivez vos rendez-vous, accédez à la documentation de vos logiciels et consultez l'historique de nos interventions.
          </p>
        </div>
      </div>

      {/* Right: form */}
      <div className="flex items-center justify-center p-6 sm:p-12 bg-slate-50">
        <div className="w-full max-w-md">
          <Link to="/" className="lg:hidden flex items-center gap-3 mb-6">
            <img src={LOGO_URL} alt="SAWALI" className="h-10 w-10 rounded-md" />
            <span className="font-display font-bold">SAWALI SMART SYSTEMS</span>
          </Link>

          <div className="rounded-2xl border border-slate-200 bg-white p-7 shadow-sm">
            <div className="flex items-center gap-2 text-sawali-blue">
              <ShieldCheck className="h-4 w-4" />
              <span className="text-xs uppercase tracking-[0.25em] font-semibold">{step === "credentials" ? "Connexion" : "Vérification 2FA"}</span>
            </div>
            <h1 className="mt-3 text-2xl font-display font-bold text-slate-900">
              {step === "credentials" ? "Espace client" : "Code de vérification"}
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              {step === "credentials"
                ? "Saisissez vos identifiants. Un code à usage unique vous sera envoyé."
                : "Saisissez le code à 6 chiffres reçu par email."}
            </p>

            {step === "credentials" ? (
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
                <button type="submit" disabled={loading} className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2.5 text-sm font-medium hover:bg-sawali-blue-light transition" data-testid="login-submit-button">
                  {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
                  Se connecter
                </button>
                <p className="text-xs text-slate-500 text-center mt-2">
                  Pas encore de compte ? <Link to="/contact" className="text-sawali-blue underline">Demander un accès</Link>
                </p>
              </form>
            ) : (
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
                  <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-amber-900 text-xs">
                    <strong>Mode développement :</strong> SMTP non configuré. Code OTP : <span className="font-mono text-base font-bold">{devOtp}</span>
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
            )}
          </div>

          <p className="mt-6 text-center text-xs text-slate-500">
            <Link to="/" className="text-sawali-blue underline">← Retour au site public</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
