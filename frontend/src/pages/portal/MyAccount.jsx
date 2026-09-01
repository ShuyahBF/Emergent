import { useEffect, useState } from "react";
import React from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { User, Mail, Phone, MessageCircle, Building2, Calendar, Clock, FileText, Activity, Users as UsersIcon, Send, Lock, ShieldCheck, ArrowRight, Sparkles, Loader2, X, Download } from "lucide-react";
// 2026-02 fork (P0) — KYC + Smart Communications par tenant
import TenantKycSection from "@/pages/portal/sections/TenantKycSection";
import SmartCommunicationsTenantSection from "@/pages/portal/sections/SmartCommunicationsTenantSection";

// Iter34k — Mon compte: read-only profile + request-change form
const Row = ({ icon: Icon, label, value, mono = false, testid }) => (
  <div className="flex items-start gap-3 py-2 border-b border-slate-100 last:border-0" data-testid={testid}>
    <Icon className="h-4 w-4 text-slate-400 mt-0.5 shrink-0" />
    <div className="flex-1 min-w-0">
      <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">{label}</p>
      <p className={`text-sm text-slate-800 ${mono ? "font-mono" : ""} ${value ? "" : "text-slate-300 italic"}`}>
        {value || "non renseigné"}
      </p>
    </div>
    <Lock className="h-3 w-3 text-slate-300 mt-1 shrink-0" title="Lecture seule — demander une modification ci-dessous" />
  </div>
);

const KpiCard = ({ icon: Icon, label, value, color }) => (
  <div className={`rounded-lg ring-1 ring-${color}-200 bg-${color}-50/60 p-3 text-center`} data-testid={`account-kpi-${label.toLowerCase()}`}>
    <Icon className={`h-5 w-5 mx-auto text-${color}-600 mb-1`} />
    <p className="text-2xl font-display font-bold text-slate-900">{value ?? 0}</p>
    <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">{label}</p>
  </div>
);

const FIELD_OPTIONS = [
  { id: "full_name", label: "Identité (nom & prénom)" },
  { id: "birth_date", label: "Date de naissance" },
  { id: "phone", label: "Numéro de téléphone" },
  { id: "whatsapp", label: "Numéro WhatsApp" },
  { id: "email", label: "Adresse email" },
  { id: "company", label: "Société / entreprise" },
];

// 2026-02 fork iter108 — S164 (Emmy) — Self-contained user preference section
// for silencing browser notifications on this device. Stored in localStorage
// so no backend endpoint is needed. Respects the admin global toggle: when the
// admin has disabled notifications for everyone, we display a note instead of
// the checkbox.
function BrowserNotificationsPrefSection() {
  const [flags, setFlags] = useState({ browser_notifications_enabled: true });
  const [optedOut, setOptedOut] = useState(false);
  const [permission, setPermission] = useState(
    typeof Notification !== "undefined" ? Notification.permission : "unsupported",
  );

  useEffect(() => {
    try {
      setOptedOut(localStorage.getItem("sawali_browser_notifs_optout") === "1");
    } catch { /* ignore */ }
    const base = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");
    fetch(`${base}/api/public/ui-flags`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d) setFlags(d); })
      .catch(() => {});
  }, []);

  const globalOn = flags?.browser_notifications_enabled !== false;

  const toggleOptOut = (checked) => {
    setOptedOut(checked);
    try {
      if (checked) localStorage.setItem("sawali_browser_notifs_optout", "1");
      else localStorage.removeItem("sawali_browser_notifs_optout");
      // Force BrowserNotifications component to pick up the new state on next
      // page refresh (it reads localStorage on mount only for perf).
      toast.success(checked ? "Notifications silencées sur cet appareil" : "Notifications réactivées sur cet appareil");
    } catch { /* ignore */ }
  };

  const requestPerm = () => {
    if (typeof Notification === "undefined") return;
    Notification.requestPermission().then((p) => setPermission(p));
  };

  return (
    <section className="rounded-xl ring-1 ring-slate-200 bg-white p-5 space-y-3" data-testid="account-browser-notifs-pref">
      <div className="flex items-center gap-2">
        <div className="rounded-lg bg-sky-100 ring-1 ring-sky-200 p-2">
          <Sparkles className="h-4 w-4 text-sky-600" />
        </div>
        <div>
          <h2 className="font-display font-semibold text-sm text-slate-900">
            Notifications navigateur
          </h2>
          <p className="text-xs text-slate-500">
            Toast système + clignotement du titre quand un ticket / RDV / message arrive et que l&apos;onglet est en arrière-plan.
          </p>
        </div>
      </div>

      {!globalOn ? (
        <p className="text-xs text-amber-700 bg-amber-50 ring-1 ring-amber-200 rounded-lg px-3 py-2">
          Les notifications navigateur ont été désactivées globalement par l&apos;administrateur.
        </p>
      ) : (
        <>
          <label className="flex items-start gap-2 cursor-pointer" data-testid="browser-notifs-optout-toggle">
            <input
              type="checkbox"
              checked={optedOut}
              onChange={(e) => toggleOptOut(e.target.checked)}
              className="mt-0.5 h-4 w-4"
            />
            <div className="flex-1">
              <div className="text-sm text-slate-800">
                Silencer les notifications sur cet appareil
              </div>
              <p className="text-xs text-slate-500 mt-0.5">
                Le clignotement du titre et les toasts système seront désactivés uniquement sur ce navigateur. Vos collègues sur d&apos;autres appareils continueront à les recevoir.
              </p>
            </div>
          </label>
          {permission === "default" && (
            <button
              type="button"
              onClick={requestPerm}
              className="text-xs font-semibold text-sky-700 hover:text-sky-900 underline"
              data-testid="browser-notifs-request-perm"
            >
              Autoriser les notifications système (permission navigateur requise)
            </button>
          )}
          {permission === "denied" && (
            <p className="text-[11px] text-rose-600">
              Le navigateur bloque les notifications pour ce site. Réautorisez-les depuis la barre d&apos;adresse (🔒).
            </p>
          )}
          {permission === "granted" && (
            <p className="text-[11px] text-emerald-700">
              Notifications système autorisées ✓ (Windows / macOS / Android natif).
            </p>
          )}
        </>
      )}
    </section>
  );
}

export default function MyAccount() {
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selectedFields, setSelectedFields] = useState([]);
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  // Iter38r-fix7 — AI profile photo generation
  const [photoModal, setPhotoModal] = useState({ open: false, prompt: "", style: "professional", busy: false });

  const generateProfilePhoto = async () => {
    if (!photoModal.prompt.trim() || photoModal.busy) return;
    setPhotoModal((m) => ({ ...m, busy: true }));
    try {
      const r = await apiClient.post("/me/ai/generate-profile-photo", {
        prompt: photoModal.prompt.trim(),
        style: photoModal.style,
      });
      toast.success("Photo de profil générée et appliquée");
      setPhotoModal({ open: false, prompt: "", style: "professional", busy: false });
      await load();
      // Reflect the new avatar in the auth context refresh (next reload picks it up)
    } catch (err) {
      const status = err?.response?.status;
      const detail = err?.response?.data?.detail || "Erreur";
      if (status === 429) toast.error(`Quota IA atteint : ${detail}`);
      else if (status === 403) toast.error("Génération IA non activée — contactez votre administrateur.");
      else toast.error(detail);
      setPhotoModal((m) => ({ ...m, busy: false }));
    }
  };

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/me/account-detail");
      setData(r.data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const toggle = (id) => {
    setSelectedFields((s) => s.includes(id) ? s.filter((x) => x !== id) : [...s, id]);
  };

  const submit = async () => {
    if (!message.trim()) { toast.error("Veuillez décrire la modification souhaitée"); return; }
    setSubmitting(true);
    try {
      await apiClient.post("/me/profile-update-request", {
        message: message.trim(),
        fields: selectedFields,
      });
      toast.success("Demande envoyée à l'administrateur");
      setMessage("");
      setSelectedFields([]);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setSubmitting(false); }
  };

  const identity = data?.identity || {};
  const parent = data?.parent_client;
  const counters = data?.counters || {};

  const fmtDate = (iso) => {
    if (!iso) return null;
    try {
      return new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" });
    } catch { return iso; }
  };

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6" data-testid="my-account-page">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-bold text-slate-900">Mon compte</h1>
          <p className="text-xs text-slate-500 mt-0.5">Informations de votre compte (lecture seule)</p>
        </div>
        {identity.avatar_url && (
          <div className="relative group" data-testid="account-avatar-wrap">
            <img
              src={identity.avatar_url}
              alt="avatar"
              className="h-16 w-16 rounded-full ring-2 ring-sawali-blue/40 object-cover"
              data-testid="account-avatar"
            />
            <button
              type="button"
              onClick={() => setPhotoModal((m) => ({ ...m, open: true }))}
              className="absolute -bottom-1 -right-1 h-7 w-7 rounded-full bg-fuchsia-600 text-white shadow-lg ring-2 ring-white flex items-center justify-center hover:bg-fuchsia-700"
              title="Générer une nouvelle photo de profil par IA"
              data-testid="account-ai-photo-btn"
            >
              <Sparkles className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
        {!identity.avatar_url && identity.full_name && (
          <div className="relative group" data-testid="account-avatar-wrap">
            <div className="h-16 w-16 rounded-full ring-2 ring-sawali-blue/40 bg-gradient-to-br from-sawali-blue to-sawali-blue-light text-white text-2xl font-display font-bold flex items-center justify-center" data-testid="account-avatar-initials">
              {identity.full_name.split(" ").map((s) => s[0]).slice(0, 2).join("").toUpperCase()}
            </div>
            <button
              type="button"
              onClick={() => setPhotoModal((m) => ({ ...m, open: true }))}
              className="absolute -bottom-1 -right-1 h-7 w-7 rounded-full bg-fuchsia-600 text-white shadow-lg ring-2 ring-white flex items-center justify-center hover:bg-fuchsia-700"
              title="Générer une photo de profil par IA"
              data-testid="account-ai-photo-btn"
            >
              <Sparkles className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </header>

      {/* Iter38r-fix7 — AI profile photo modal */}
      {photoModal.open && (
        <div
          className="fixed inset-0 z-[80] flex items-center justify-center p-4 bg-black/50"
          onClick={(e) => e.target === e.currentTarget && !photoModal.busy && setPhotoModal({ open: false, prompt: "", style: "professional", busy: false })}
          data-testid="ai-photo-modal"
        >
          <div className="bg-white rounded-2xl shadow-xl max-w-md w-full p-5">
            <div className="flex items-start justify-between mb-3">
              <h3 className="font-display font-semibold text-slate-900 inline-flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-fuchsia-600" /> Générer une photo de profil
              </h3>
              <button
                onClick={() => !photoModal.busy && setPhotoModal({ open: false, prompt: "", style: "professional", busy: false })}
                className="text-slate-400 hover:text-slate-700 p-1"
                data-testid="ai-photo-close"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <p className="text-xs text-slate-500 mb-3">
              Décrivez votre photo. L'IA générera un portrait carré (1:1) qui sera appliqué automatiquement.
            </p>
            <textarea
              value={photoModal.prompt}
              onChange={(e) => setPhotoModal((m) => ({ ...m, prompt: e.target.value }))}
              placeholder="Ex: Femme africaine 35 ans, sourire chaleureux, lunettes fines, veste bleu marine"
              rows={3}
              className="w-full rounded-lg ring-1 ring-slate-300 px-3 py-2 text-sm focus:ring-fuchsia-500 focus:ring-2 outline-none resize-none mb-3"
              data-testid="ai-photo-prompt"
            />
            <label className="block text-[10px] uppercase tracking-wider font-semibold text-slate-500 mb-1">Style</label>
            <select
              value={photoModal.style}
              onChange={(e) => setPhotoModal((m) => ({ ...m, style: e.target.value }))}
              className="w-full rounded-lg ring-1 ring-slate-300 px-3 py-2 text-sm focus:ring-fuchsia-500 focus:ring-2 outline-none mb-4"
              data-testid="ai-photo-style"
            >
              <option value="professional">Corporate / professionnel</option>
              <option value="creative">Créatif / coloré</option>
              <option value="casual">Décontracté / extérieur</option>
              <option value="artistic">Artistique / peinture</option>
              <option value="avatar">Avatar vectoriel / minimaliste</option>
            </select>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setPhotoModal({ open: false, prompt: "", style: "professional", busy: false })}
                disabled={photoModal.busy}
                className="px-3 py-1.5 rounded-md ring-1 ring-slate-300 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                Annuler
              </button>
              <button
                onClick={generateProfilePhoto}
                disabled={photoModal.busy || !photoModal.prompt.trim()}
                className="px-3 py-1.5 rounded-md bg-fuchsia-600 text-white text-sm hover:bg-fuchsia-700 disabled:opacity-50 inline-flex items-center gap-1.5"
                data-testid="ai-photo-generate"
              >
                {photoModal.busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                {photoModal.busy ? "Génération…" : "Générer"}
              </button>
            </div>
          </div>
        </div>
      )}

      {loading && !data && (
        <p className="text-center text-slate-400 py-8">Chargement…</p>
      )}

      {data && (
        <>
          {/* Identity */}
          <section className="rounded-xl ring-1 ring-slate-200 bg-white p-5" data-testid="account-identity-card">
            <h2 className="font-display font-semibold text-sm text-slate-700 mb-2 flex items-center gap-2">
              <User className="h-4 w-4 text-sawali-blue" /> Identité
            </h2>
            <div className="grid sm:grid-cols-2 gap-x-6">
              <Row icon={User} label="Nom complet" value={identity.full_name} testid="account-field-full-name" />
              <Row icon={Mail} label="Email" value={identity.email} mono testid="account-field-email" />
              <Row icon={Phone} label="Téléphone" value={identity.phone} mono testid="account-field-phone" />
              <Row icon={MessageCircle} label="WhatsApp" value={identity.whatsapp} mono testid="account-field-whatsapp" />
              <Row icon={Calendar} label="Date de naissance" value={identity.birth_date} testid="account-field-birth-date" />
              <Row icon={Lock} label="Rôle" value={identity.role} testid="account-field-role" />
            </div>
          </section>

          {/* Company / Parent client */}
          <section className="rounded-xl ring-1 ring-slate-200 bg-white p-5" data-testid="account-company-card">
            <h2 className="font-display font-semibold text-sm text-slate-700 mb-2 flex items-center gap-2">
              <Building2 className="h-4 w-4 text-sawali-blue" /> Société & rattachement
            </h2>
            <div className="grid sm:grid-cols-2 gap-x-6">
              <Row icon={Building2} label="Société (entreprise)" value={identity.company} testid="account-field-company" />
              <Row icon={UsersIcon} label="Client lié" value={parent ? `${parent.full_name || "—"}${parent.company ? ` — ${parent.company}` : ""}` : "Aucun (compte principal)"} testid="account-field-parent-client" />
            </div>
          </section>

          {/* 2026-02 fork (P0) — KYC + Smart Communications, visibles pour
              chaque gestionnaire du tenant : role=admin, role=superviseur
              OU tracked_role in {'Superviseur','Administrateur'} (aligné backend). */}
          {(user?.role === "admin" || user?.role === "superviseur" || user?.tracked_role === "Superviseur" || user?.tracked_role === "Administrateur") && (
            <>
              <TenantKycSection />
              <SmartCommunicationsTenantSection />
            </>
          )}

          {/* 2026-02 fork iter108 — S164 (Emmy) — Personal browser-notification opt-out.
              Stored in localStorage (per-device) so users can silence system toasts
              without contacting an admin. Respects the global admin toggle. */}
          <BrowserNotificationsPrefSection />

          {/* Iter34s — Raccourci SMART Communications (admin only).
              Permet à l'admin SAWALI (et plus généralement à tout admin)
              de configurer depuis sa propre fiche les fonctions héritées
              par ses utilisateurs liés (RGPD, WA, SMS, IA, paiements…). */}
          {(user?.role === "admin" || user?.role === "superviseur") && (
            <Link
              to={`/admin/clients/${user.id}/features`}
              className="block rounded-xl ring-1 ring-fuchsia-200 bg-gradient-to-br from-fuchsia-50 via-white to-sky-50 p-5 hover:ring-2 hover:ring-fuchsia-300 transition-all hover:-translate-y-0.5 shadow-sm hover:shadow-md group"
              data-testid="account-smart-communications-link"
            >
              <div className="flex items-center justify-between gap-4">
                <div className="flex items-start gap-3 min-w-0">
                  <div className="rounded-lg bg-fuchsia-600/10 ring-1 ring-fuchsia-300 p-2 shrink-0">
                    <ShieldCheck className="h-5 w-5 text-fuchsia-600" />
                  </div>
                  <div className="min-w-0">
                    <h2 className="font-display font-semibold text-sm text-slate-900 flex items-center gap-1.5">
                      SMART Communications
                      <span className="rounded-full bg-fuchsia-600 text-white text-[9px] px-1.5 py-0.5 uppercase tracking-wider">Admin</span>
                    </h2>
                    <p className="text-xs text-slate-600 mt-0.5">
                      Configurez les fonctionnalités RGPD, WhatsApp, SMS, IA et paiements de votre compte. Ces réglages seront automatiquement <strong>hérités par tous vos utilisateurs liés</strong>.
                    </p>
                  </div>
                </div>
                <ArrowRight className="h-4 w-4 text-fuchsia-600 group-hover:translate-x-1 transition-transform shrink-0" />
              </div>
            </Link>
          )}

          {/* Last seen */}
          <section className="rounded-xl ring-1 ring-amber-200 bg-amber-50/40 p-4" data-testid="account-last-seen">
            <div className="flex items-center gap-2 text-amber-700">
              <Clock className="h-4 w-4" />
              <p className="text-xs">
                <span className="font-semibold">Dernière connexion :</span>{" "}
                {data.last_seen_at ? <span data-testid="account-last-seen-value">{fmtDate(data.last_seen_at)}</span> : <span className="italic text-amber-600">Aucune connexion antérieure enregistrée</span>}
              </p>
            </div>
          </section>

          {/* Counters */}
          <section data-testid="account-counters">
            <h2 className="font-display font-semibold text-sm text-slate-700 mb-2">Activité associée à votre compte</h2>
            <div className="grid grid-cols-3 gap-3">
              <KpiCard icon={FileText} label="Rapports" value={counters.reports} color="sky" />
              <KpiCard icon={Activity} label="Suivis" value={counters.suivis} color="emerald" />
              <KpiCard icon={UsersIcon} label="Contacts" value={counters.contacts} color="amber" />
            </div>
            <p className="text-[10px] text-slate-400 mt-1 text-center">Les contacts visibles incluent ceux partagés par votre société.</p>
          </section>

          {/* Iter38r-fix9l — RGPD: Export my data + WA Tasks digest opt-in */}
          <BonusFeaturesSection />

          {/* 2026-02 fork (P3) — Médecin : Planning WhatsApp du jour */}
          {(user?.tracked_role === "Médecin") && <MedecinPlanningWaDigestSection />}

          {/* Request modification */}
          <section className="rounded-xl ring-1 ring-indigo-200 bg-indigo-50/40 p-5" data-testid="account-request-section">
            <h2 className="font-display font-semibold text-sm text-indigo-800 mb-2 flex items-center gap-2">
              <Send className="h-4 w-4" /> Demande de modification
            </h2>
            <p className="text-xs text-slate-600 mb-3">
              Une faute d'orthographe, un changement de numéro, une date de naissance à corriger ? Décrivez votre demande, l'administrateur la traitera.
            </p>
            <div className="grid sm:grid-cols-2 gap-2 mb-3">
              {FIELD_OPTIONS.map((f) => (
                <label key={f.id} className="inline-flex items-center gap-2 text-xs text-slate-700 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={selectedFields.includes(f.id)}
                    onChange={() => toggle(f.id)}
                    data-testid={`request-field-${f.id}`}
                  />
                  {f.label}
                </label>
              ))}
            </div>
            <textarea
              rows={4}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              maxLength={1500}
              placeholder="Décrivez précisément la modification souhaitée (ex: 'Mon nom de famille s'écrit Diakité et non Diakite', 'Nouveau numéro WhatsApp : +225 07 XX XX XX XX', etc.)"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm resize-y"
              data-testid="request-message-input"
            />
            <div className="flex items-center justify-between mt-2">
              <span className="text-[10px] text-slate-400">{message.length}/1500</span>
              <button
                onClick={submit}
                disabled={submitting || !message.trim()}
                className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 text-sm font-semibold disabled:opacity-50"
                data-testid="request-submit-btn"
              >
                <Send className="h-4 w-4" />
                {submitting ? "Envoi…" : "Envoyer à l'admin"}
              </button>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

// =====================================================================
// Iter38r-fix9l — BonusFeaturesSection
// =====================================================================
// (1) GDPR "Exporter mes données" — downloads a JSON of everything the
//     server has about the current user.
// (2) WhatsApp Tasks Digest opt-in — toggle + hour picker.
function BonusFeaturesSection() {
  const [wa, setWa] = React.useState({ enabled: false, hour: 7, loading: true });
  const [exporting, setExporting] = React.useState(false);

  React.useEffect(() => {
    apiClient.get("/me/wa-tasks-digest")
      .then((r) => setWa({ enabled: !!r.data?.enabled, hour: r.data?.hour ?? 7, loading: false }))
      .catch(() => setWa((w) => ({ ...w, loading: false })));
  }, []);

  const saveWa = async (next) => {
    setWa((w) => ({ ...w, ...next }));
    try {
      await apiClient.put("/me/wa-tasks-digest", next);
      toast.success("Préférence enregistrée");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const exportData = async () => {
    setExporting(true);
    try {
      const r = await apiClient.get("/me/gdpr/export");
      const blob = new Blob([JSON.stringify(r.data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `sawali-mes-donnees-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Export téléchargé");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur export");
    } finally {
      setExporting(false);
    }
  };

  return (
    <section className="rounded-xl ring-1 ring-emerald-200 bg-emerald-50/40 p-5 space-y-4" data-testid="account-bonus-section">
      <h2 className="font-display font-semibold text-sm text-emerald-800 mb-2 flex items-center gap-2">
        <Sparkles className="h-4 w-4" /> Préférences & RGPD
      </h2>
      {/* GDPR Export */}
      <div className="rounded-lg ring-1 ring-emerald-200 bg-white p-3 space-y-2" data-testid="gdpr-export-row">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex-1 min-w-0">
            <div className="font-semibold text-sm text-slate-800 flex items-center gap-1.5"><Download className="h-3.5 w-3.5 text-emerald-600" /> Exporter mes données (RGPD)</div>
            <p className="text-xs text-slate-500 mt-0.5">Téléchargez toutes les données vous concernant : profil, contacts, WhatsApp, SMS, tâches, notes, rapports, suivis (format JSON).</p>
          </div>
          <button
            type="button"
            onClick={exportData}
            disabled={exporting}
            className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-1.5 text-xs font-medium disabled:opacity-50"
            data-testid="gdpr-export-btn"
          >
            {exporting ? "Préparation…" : "Télécharger"}
          </button>
        </div>
      </div>
      {/* WA Tasks Digest opt-in */}
      <div className="rounded-lg ring-1 ring-emerald-200 bg-white p-3 space-y-2" data-testid="wa-digest-row">
        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={wa.enabled}
            onChange={(e) => saveWa({ enabled: e.target.checked, hour: wa.hour })}
            disabled={wa.loading}
            className="mt-0.5 h-4 w-4"
            data-testid="wa-digest-toggle"
          />
          <div className="flex-1">
            <div className="font-semibold text-sm text-slate-800">📱 Recevoir mes tâches par WhatsApp chaque jour</div>
            <p className="text-xs text-slate-500 mt-0.5">L'admin doit avoir activé le service (côté tenant). Répondez `OK 1,3` ou `FAIT 2 5` pour cocher les tâches.</p>
          </div>
        </label>
        {wa.enabled && (
          <div className="flex items-center gap-2 pl-7">
            <span className="text-xs text-slate-600">Heure d'envoi :</span>
            <select
              value={wa.hour}
              onChange={(e) => saveWa({ enabled: true, hour: parseInt(e.target.value) })}
              className="text-sm rounded-lg border border-slate-300 px-2 py-1"
              data-testid="wa-digest-hour-select"
            >
              {[6, 7, 8, 9, 10, 11, 12, 13, 14, 18, 19, 20].map((h) => (
                <option key={h} value={h}>{h}h00 (Africa/Abidjan)</option>
              ))}
            </select>
          </div>
        )}
      </div>
    </section>
  );
}


// =====================================================================
// 2026-02 fork (P3) — Envoi quotidien du planning RDV du médecin via WA
// =====================================================================
function MedecinPlanningWaDigestSection() {
  const [state, setState] = React.useState({ enabled: false, hour: 7, loading: true });

  React.useEffect(() => {
    apiClient.get("/me/planning-wa-digest")
      .then((r) => setState({ enabled: !!r.data?.enabled, hour: r.data?.hour ?? 7, loading: false }))
      .catch(() => setState((s) => ({ ...s, loading: false })));
  }, []);

  const save = async (next) => {
    setState((s) => ({ ...s, ...next }));
    try {
      await apiClient.put("/me/planning-wa-digest", next);
      toast.success("Préférence enregistrée");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  return (
    <section className="rounded-xl ring-1 ring-sky-200 bg-sky-50/40 p-5 space-y-4" data-testid="account-medecin-planning-section">
      <h2 className="font-display font-semibold text-sm text-sky-800 mb-2 flex items-center gap-2">
        <Calendar className="h-4 w-4" /> Planning RDV via WhatsApp (Médecin)
      </h2>
      <div className="rounded-lg ring-1 ring-sky-200 bg-white p-3 space-y-2" data-testid="planning-wa-digest-row">
        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={state.enabled}
            onChange={(e) => save({ enabled: e.target.checked, hour: state.hour })}
            disabled={state.loading}
            className="mt-0.5 h-4 w-4"
            data-testid="planning-wa-digest-toggle"
          />
          <div className="flex-1">
            <div className="font-semibold text-sm text-slate-800">
              Recevoir mon planning RDV du jour par WhatsApp
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              Le message liste tous les rendez-vous du jour à l&apos;heure choisie (fuseau Africa/Abidjan). Utile pour préparer votre matinée sans ouvrir le portail.
            </p>
          </div>
        </label>
        {state.enabled && (
          <div className="flex items-center gap-2 pl-7">
            <span className="text-xs text-slate-600">Heure d&apos;envoi :</span>
            <select
              value={state.hour}
              onChange={(e) => save({ enabled: true, hour: parseInt(e.target.value) })}
              className="text-sm rounded-lg border border-slate-300 px-2 py-1"
              data-testid="planning-wa-digest-hour-select"
            >
              {[5, 6, 7, 8, 9, 10, 12, 14, 18].map((h) => (
                <option key={h} value={h}>{h}h00 (Africa/Abidjan)</option>
              ))}
            </select>
          </div>
        )}
      </div>
    </section>
  );
}

