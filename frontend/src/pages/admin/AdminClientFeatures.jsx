import React, { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { ArrowLeft, MessageCircle, Smartphone, Sparkles, CreditCard, Save, ShieldCheck, Webhook, Building2, Volume2, MessageSquareText, Facebook, Megaphone, Image as ImageIcon, Film, Gauge, Wallet, Download, FileSpreadsheet, FileText } from "lucide-react";

/*
  Admin → Fiche client → SMART Communications
  Per-client feature flags (whatsapp, sms, ai, payments) inherited by every
  tracked user belonging to the client. Backend endpoints:
    GET  /api/admin/clients/{id}/features
    PUT  /api/admin/clients/{id}/features
*/
const FEATURE_META = [
  {
    key: "whatsapp",
    label: "Messages WhatsApp",
    description: "Envoi & planification de messages WhatsApp Business via le portail.",
    icon: MessageCircle,
    color: "text-emerald-600",
    bg: "bg-emerald-50",
  },
  {
    key: "sms",
    label: "Messages SMS",
    description: "Envoi de SMS via les opérateurs configurés (Orange, Moov, Telecel, OVH).",
    icon: Smartphone,
    color: "text-sky-600",
    bg: "bg-sky-50",
  },
  {
    key: "ai",
    label: "Génération IA",
    description: "Synthèse IA des conversations + transcription audio (Whisper).",
    icon: Sparkles,
    color: "text-fuchsia-600",
    bg: "bg-fuchsia-50",
  },
  {
    key: "payments",
    label: "Paiements électroniques (PawaPay)",
    description: "Encaissement Mobile Money via PawaPay pour les factures et formations.",
    icon: CreditCard,
    color: "text-amber-600",
    bg: "bg-amber-50",
  },
  {
    key: "webhook_returns",
    label: "Retours de Webhook",
    description: "Affiche une fenêtre détaillée (URL, code HTTP, réponse) après chaque action déclenchant un webhook sortant. Les utilisateurs suivis du client en héritent.",
    icon: Webhook,
    color: "text-violet-600",
    bg: "bg-violet-50",
  },
  {
    key: "anon_name",
    label: "RGPD — Anonymiser les noms",
    description: "Affiche les noms sous la forme « J*** D*** » pour les utilisateurs non privilégiés (Modérateur/Admin/Superviseur voient toujours en clair).",
    icon: ShieldCheck,
    color: "text-rose-600",
    bg: "bg-rose-50",
    rgpd: true,
  },
  {
    key: "anon_company",
    label: "RGPD — Anonymiser les sociétés",
    description: "Masque le champ « Société » sous la forme « A***  C*** ». Le Code Unique du contact (ex. 2026-ACME-0001) reste lisible pour permettre la traçabilité sans exposer l'identité.",
    icon: Building2,
    color: "text-rose-600",
    bg: "bg-rose-50",
    rgpd: true,
  },
  {
    key: "anon_email",
    label: "RGPD — Anonymiser les emails",
    description: "Affiche les emails sous la forme « j***@gmail.com ».",
    icon: ShieldCheck,
    color: "text-rose-600",
    bg: "bg-rose-50",
    rgpd: true,
  },
  {
    key: "anon_phone",
    label: "RGPD — Anonymiser les téléphones",
    description: "Affiche les numéros sous la forme « +225 07 ** ** ** 89 ».",
    icon: ShieldCheck,
    color: "text-rose-600",
    bg: "bg-rose-50",
    rgpd: true,
  },
  {
    key: "anon_whatsapp",
    label: "RGPD — Anonymiser les WhatsApp",
    description: "Même format que téléphone, appliqué au champ WhatsApp.",
    icon: ShieldCheck,
    color: "text-rose-600",
    bg: "bg-rose-50",
    rgpd: true,
  },
  // Iter34u — Content-level restrictions: when ON, the corresponding kind
  // of resource is visible ONLY to its creator (plus admin/superviseur).
  {
    key: "anon_rapports",
    label: "Restriction — Rapports (créateur uniquement)",
    description: "Quand activé, seuls le créateur et les admins/superviseurs peuvent visualiser les Rapports. Les autres utilisateurs liés ne voient pas le contenu.",
    icon: ShieldCheck,
    color: "text-blue-600",
    bg: "bg-blue-50",
    rgpd: true,
  },
  {
    key: "anon_suivis",
    label: "Restriction — Suivis (créateur uniquement)",
    description: "Quand activé, seuls le créateur et les admins/superviseurs peuvent visualiser les Suivis.",
    icon: ShieldCheck,
    color: "text-blue-600",
    bg: "bg-blue-50",
    rgpd: true,
  },
  {
    key: "anon_communications",
    label: "Restriction — Communications (SMS, WhatsApp, Paiements…)",
    description: "Quand activé, seuls le créateur et les admins/superviseurs peuvent voir les SMS, WhatsApp et liens de paiement émis/reçus.",
    icon: ShieldCheck,
    color: "text-blue-600",
    bg: "bg-blue-50",
    rgpd: true,
  },
  {
    key: "wa_sound_alerts",
    label: "Alerte sonore WhatsApp",
    description: "Autorise les utilisateurs du client à activer la notification sonore (« blip ») à la réception d'un nouveau message WhatsApp dans le portail. Décocher pour interdire ce son côté utilisateurs (les alertes desktop restent disponibles).",
    icon: Volume2,
    color: "text-emerald-600",
    bg: "bg-emerald-50",
  },
  {
    key: "internal_chat",
    label: "Chat interne temps réel",
    description: "Active un chat texte en temps réel (WebSocket) entre le client et ses utilisateurs suivis : fil collectif #général et conversations 1-à-1. Décocher pour masquer la bulle de chat dans leur portail.",
    icon: MessageSquareText,
    color: "text-sky-600",
    bg: "bg-sky-50",
  },
  // Iter38g — Meta integration toggles (gated by Admin Settings > Meta App).
  // When ON, the corresponding module appears in the user's portal AND the
  // backend integration routes become accessible for this client.
  {
    key: "meta_pages",
    label: "Meta — Pages Facebook",
    description: "Gestion des pages Facebook (publication, modération des commentaires, statistiques). Requiert une App Meta connectée dans les paramètres admin.",
    icon: Facebook,
    color: "text-blue-600",
    bg: "bg-blue-50",
    meta: true,
  },
  {
    key: "meta_messenger",
    label: "Meta — Messenger",
    description: "Réception et réponse aux messages Messenger dans la même inbox unifiée que WhatsApp.",
    icon: MessageCircle,
    color: "text-blue-600",
    bg: "bg-blue-50",
    meta: true,
  },
  {
    key: "meta_ads",
    label: "Meta — Ads Manager",
    description: "Création, suivi et statistiques des campagnes publicitaires Meta (Facebook + Instagram). Requiert un Business Manager connecté.",
    icon: Megaphone,
    color: "text-blue-600",
    bg: "bg-blue-50",
    meta: true,
  },
  // Iter38o — AI media generation toggles (Nano Banana + Sora 2)
  {
    key: "ai_image_gen",
    label: "Génération d'Image IA (Nano Banana)",
    description: "Active la génération de visuels IA via Gemini Nano Banana (icônes produits, illustrations marketing). Quand désactivé, le bouton de génération est masqué et les appels API retournent 403.",
    icon: ImageIcon,
    color: "text-fuchsia-600",
    bg: "bg-fuchsia-50",
  },
  {
    key: "ai_video_gen",
    label: "Génération de Vidéo IA (Sora 2)",
    description: "Active la génération vidéo IA via OpenAI Sora 2 (clips de 4 à 12 secondes). Quand désactivé, l'onglet vidéo est masqué et les appels API retournent 403.",
    icon: Film,
    color: "text-violet-600",
    bg: "bg-violet-50",
  },
  // Iter38r-fix7 — Liluvine PRO (internal AI assistant)
  {
    key: "ai_liluvine_pro",
    label: "Liluvine PRO (Assistant IA interne)",
    description: "Active l'assistant IA propulsé par Claude Sonnet avec accès lecture seule aux contacts, tickets, paiements, RDV et notes. Quand désactivé, l'entrée menu reste visible mais grisée avec un message d'invitation à contacter l'administrateur.",
    icon: Sparkles,
    color: "text-fuchsia-600",
    bg: "bg-fuchsia-50",
  },
];

export default function AdminClientFeatures() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [features, setFeatures] = useState({ whatsapp: false, sms: false, ai: false, payments: false, webhook_returns: false, anon_name: false, anon_company: false, anon_email: false, anon_phone: false, anon_whatsapp: false, anon_rapports: false, anon_suivis: false, anon_communications: false, wa_sound_alerts: true, internal_chat: false, meta_pages: false, meta_messenger: false, meta_ads: false, ai_image_gen: false, ai_video_gen: false, ai_liluvine_pro: false });
  // Iter38r — PawaPay MSISDN policy (true | false | null = global default)
  const [pawapayFixMsisdn, setPawapayFixMsisdn] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get(`/admin/clients/${id}/features`);
      setData(r.data);
      setFeatures(r.data?.features || {});
      setPawapayFixMsisdn(r.data?.pawapay_fix_msisdn);
      setDirty(false);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [id]);

  const toggle = (key) => {
    setFeatures((f) => ({ ...f, [key]: !f[key] }));
    setDirty(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      await apiClient.put(`/admin/clients/${id}/features`, {
        ...features,
        pawapay_fix_msisdn: pawapayFixMsisdn,
      });
      toast.success("Fonctionnalités enregistrées");
      setDirty(false);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <p className="text-slate-500 p-6">Chargement…</p>;

  return (
    <div className="space-y-6 p-6 max-w-4xl" data-testid="admin-client-features-page">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <Link to="/admin/clients" className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-sawali-blue mb-1">
            <ArrowLeft className="h-3 w-3" /> Retour aux clients
          </Link>
          <h1 className="text-2xl font-display font-bold inline-flex items-center gap-2">
            <ShieldCheck className="h-6 w-6 text-sawali-blue" /> SMART Communications
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Fonctionnalités activables pour <strong>{data?.client?.full_name}</strong>
            {data?.client?.company ? <> ({data.client.company})</> : null}.
            Les utilisateurs suivis du client héritent automatiquement de ces réglages.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            to={`/admin/clients/${id}/rgpd-preview`}
            className="inline-flex items-center gap-2 rounded-lg ring-1 ring-rose-300 bg-rose-50 text-rose-700 hover:bg-rose-100 px-4 py-2 text-sm"
            data-testid="rgpd-preview-link"
            title="Audit RGPD — voir ce qu'un utilisateur non-privilégié verrait"
          >
            <ShieldCheck className="h-4 w-4" /> Audit RGPD
          </Link>
          <button
            onClick={save}
            disabled={!dirty || saving}
            className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light disabled:opacity-50"
            data-testid="features-save-btn"
          >
            <Save className="h-4 w-4" /> {saving ? "Enregistrement…" : "Enregistrer"}
          </button>
        </div>
      </div>

      <div className="grid sm:grid-cols-2 gap-4">
        {FEATURE_META.map((f) => {
          const Icon = f.icon;
          const enabled = !!features[f.key];
          return (
            <button
              key={f.key}
              type="button"
              onClick={() => toggle(f.key)}
              className={`relative text-left rounded-2xl ring-1 transition p-5 ${
                enabled
                  ? `${f.bg} ring-2 ring-offset-1 ring-current ${f.color} shadow-sm`
                  : "bg-white ring-slate-200 hover:ring-slate-300 text-slate-500"
              }`}
              data-testid={`features-toggle-${f.key}`}
            >
              <div className="flex items-start justify-between gap-3 mb-2">
                <div className={`h-10 w-10 rounded-xl flex items-center justify-center ${enabled ? "bg-white/70" : "bg-slate-100"}`}>
                  <Icon className={`h-5 w-5 ${enabled ? f.color : "text-slate-400"}`} />
                </div>
                <span
                  className={`text-[10px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded-full ${
                    enabled
                      ? "bg-white/80 text-emerald-700"
                      : "bg-slate-100 text-slate-500"
                  }`}
                  data-testid={`features-badge-${f.key}`}
                >
                  {enabled ? "Activé" : "Désactivé"}
                </span>
              </div>
              <h3 className={`font-display font-semibold mb-1 ${enabled ? "text-slate-900" : "text-slate-700"}`}>
                {f.label}
              </h3>
              <p className={`text-xs leading-relaxed ${enabled ? "text-slate-700" : "text-slate-500"}`}>
                {f.description}
              </p>
            </button>
          );
        })}
      </div>

      {/* Iter38r — PawaPay MSISDN policy (true/false/null=global default) */}
      <div className="rounded-2xl ring-1 ring-slate-200 bg-white p-5 space-y-3" data-testid="pawapay-msisdn-policy-section">
        <div className="flex items-start gap-3">
          <div className="h-10 w-10 rounded-xl bg-sky-50 flex items-center justify-center">
            <ShieldCheck className="h-5 w-5 text-sky-600" />
          </div>
          <div className="flex-1">
            <h3 className="font-display font-semibold text-slate-900">Politique MSISDN PawaPay (page hébergée)</h3>
            <p className="text-xs text-slate-500 mt-1">
              Définit si le numéro mobile du client doit être pré-rempli sur la page de paiement PawaPay, ou laissé vide pour qu'il le saisisse lui-même.
            </p>
          </div>
        </div>
        <div className="grid sm:grid-cols-3 gap-2">
          {[
            { v: null, label: "Défaut global", hint: "Suit le réglage du paramétrage PawaPay" },
            { v: true, label: "Pré-remplir", hint: "Utilise le numéro WhatsApp/téléphone enregistré" },
            { v: false, label: "Saisie libre", hint: "Le client tape son numéro sur la page PawaPay" },
          ].map((opt) => {
            const active = pawapayFixMsisdn === opt.v;
            return (
              <button
                key={String(opt.v)}
                type="button"
                onClick={() => { setPawapayFixMsisdn(opt.v); setDirty(true); }}
                className={`text-left rounded-xl ring-1 px-4 py-3 transition ${
                  active ? "ring-2 ring-sky-500 bg-sky-50 text-sky-900" : "ring-slate-200 bg-white hover:ring-slate-300 text-slate-600"
                }`}
                data-testid={`pawapay-fix-msisdn-${opt.v === null ? "default" : opt.v ? "true" : "false"}`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className={`h-3 w-3 rounded-full ${active ? "bg-sky-500" : "bg-slate-300"}`} />
                  <span className="font-semibold text-sm">{opt.label}</span>
                </div>
                <p className="text-[11px] leading-tight">{opt.hint}</p>
              </button>
            );
          })}
        </div>
      </div>

      {/* Iter38r-fix6 — AI Quotas & Usage per Client Lié */}
      <AiQuotasSection clientId={id} clientLabel={data?.client?.full_name || data?.client?.email || id} />

      <div className="rounded-xl ring-1 ring-amber-200 bg-amber-50 p-4 text-xs text-amber-900">
        <p className="font-semibold mb-1">Comment ça marche ?</p>
        <ul className="list-disc list-inside space-y-1">
          <li><strong>Activé</strong> : la fonctionnalité est disponible pour le client et ses utilisateurs suivis.</li>
          <li><strong>Désactivé</strong> : le bouton/menu reste visible côté portail mais grisé/non cliquable, avec une infobulle expliquant que la fonctionnalité doit être demandée à l'administrateur.</li>
          <li>Les utilisateurs du même client héritent automatiquement — pas besoin de configurer chaque utilisateur séparément.</li>
        </ul>
      </div>
    </div>
  );
}

// =============================================================================
// Iter38r-fix6 — AI Quotas & Usage Section
// =============================================================================
const RESOURCE_LABEL = { image: "Images", video: "Vidéos", transcription: "Transcriptions", chat: "Chat IA" };
const RESOURCE_UNIT = { image: "img", video: "vid", transcription: "min", chat: "tk" };

function AiQuotasSection({ clientId, clientLabel }) {
  const [cfg, setCfg] = useState(null);
  const [costs, setCosts] = useState({});
  const [defaults, setDefaults] = useState({});
  const [usage, setUsage] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [r1, r2] = await Promise.all([
        apiClient.get(`/admin/clients/${clientId}/ai-quota`),
        apiClient.get(`/admin/clients/${clientId}/ai-usage`),
      ]);
      setCfg({ mode: "off", alert_warn_pct: 80, block_on_limit: true, ...r1.data.config });
      setCosts(r1.data.effective_costs_xof || {});
      setDefaults(r1.data.defaults || {});
      setUsage(r2.data);
      setDirty(false);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement des quotas IA");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [clientId]);

  const upd = (k, v) => { setCfg((c) => ({ ...c, [k]: v })); setDirty(true); };

  const save = async () => {
    setSaving(true);
    try {
      const payload = { ...cfg };
      // Drop empty strings → null so the server treats them as "unset"
      Object.keys(payload).forEach((k) => { if (payload[k] === "") payload[k] = null; });
      await apiClient.put(`/admin/clients/${clientId}/ai-quota`, payload);
      toast.success("Quotas IA enregistrés");
      setDirty(false);
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setSaving(false); }
  };

  const downloadExport = async (kind) => {
    try {
      const r = await apiClient.get(
        `/admin/clients/${clientId}/ai-usage/export.${kind}`,
        { responseType: "blob" },
      );
      const blob = new Blob([r.data], { type: kind === "csv" ? "text/csv" : "application/pdf" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const month = new Date().toISOString().slice(0, 7);
      a.download = `ai-usage-${clientLabel.replace(/[^a-z0-9]/gi, "_")}-${month}.${kind}`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success(`Export ${kind.toUpperCase()} téléchargé`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur d'export");
    }
  };

  if (loading || !cfg) {
    return (
      <div className="rounded-2xl ring-1 ring-slate-200 bg-white p-5" data-testid="ai-quotas-loading">
        <p className="text-sm text-slate-500">Chargement des quotas IA…</p>
      </div>
    );
  }

  const isQuota = cfg.mode === "quota";
  const isBudget = cfg.mode === "budget";
  const rollup = usage?.rollup || {};
  const status = usage?.status || {};
  const limits = status.limits || {};
  const budget = status.budget;

  return (
    <div className="rounded-2xl ring-1 ring-slate-200 bg-white p-5 space-y-4" data-testid="ai-quotas-section">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-start gap-3">
          <div className="h-10 w-10 rounded-xl bg-fuchsia-50 flex items-center justify-center">
            <Gauge className="h-5 w-5 text-fuchsia-600" />
          </div>
          <div>
            <h3 className="font-display font-semibold text-slate-900">Quotas & Consommation IA</h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Limitez la consommation IA (Images, Vidéos, Transcriptions, Chat) par quota ou budget mensuel. Devise : <strong>XOF (FCFA)</strong>.
            </p>
          </div>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={() => downloadExport("csv")}
            className="inline-flex items-center gap-1.5 rounded-lg ring-1 ring-emerald-300 bg-emerald-50 hover:bg-emerald-100 text-emerald-700 px-3 py-1.5 text-xs"
            data-testid="ai-quota-export-csv"
            title="Exporter l'historique en CSV"
          >
            <FileSpreadsheet className="h-3.5 w-3.5" /> CSV
          </button>
          <button
            onClick={() => downloadExport("pdf")}
            className="inline-flex items-center gap-1.5 rounded-lg ring-1 ring-rose-300 bg-rose-50 hover:bg-rose-100 text-rose-700 px-3 py-1.5 text-xs"
            data-testid="ai-quota-export-pdf"
            title="Exporter l'historique en PDF"
          >
            <FileText className="h-3.5 w-3.5" /> PDF
          </button>
        </div>
      </div>

      {/* Mode selector */}
      <div className="grid sm:grid-cols-3 gap-2">
        {[
          { v: "off", label: "Désactivé", hint: "Aucune limite, pas de blocage", color: "slate" },
          { v: "quota", label: "Quotas par ressource", hint: "Caps mensuels par type", color: "sky" },
          { v: "budget", label: "Budget global XOF", hint: "Plafond mensuel en FCFA", color: "fuchsia" },
        ].map((opt) => {
          const active = cfg.mode === opt.v;
          return (
            <button
              key={opt.v}
              type="button"
              onClick={() => upd("mode", opt.v)}
              className={`text-left rounded-xl ring-1 px-3 py-2.5 transition ${
                active ? `ring-2 ring-${opt.color}-500 bg-${opt.color}-50` : "ring-slate-200 bg-white hover:ring-slate-300"
              }`}
              data-testid={`ai-quota-mode-${opt.v}`}
            >
              <div className="flex items-center gap-2 mb-0.5">
                <span className={`h-3 w-3 rounded-full ${active ? `bg-${opt.color}-500` : "bg-slate-300"}`} />
                <span className="font-semibold text-sm text-slate-900">{opt.label}</span>
              </div>
              <p className="text-[10px] text-slate-500">{opt.hint}</p>
            </button>
          );
        })}
      </div>

      {/* Quota fields */}
      {isQuota && (
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3" data-testid="ai-quota-caps">
          {[
            { k: "monthly_images", label: "Images / mois", unit: "images", icon: ImageIcon },
            { k: "monthly_videos", label: "Vidéos / mois", unit: "vidéos", icon: Film },
            { k: "monthly_transcription_minutes", label: "Transcription / mois", unit: "minutes", icon: Volume2 },
            { k: "monthly_chat_tokens", label: "Chat IA / mois", unit: "tokens", icon: MessageSquareText },
          ].map((q) => {
            const Q = q.icon;
            return (
              <div key={q.k} className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3">
                <label className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold flex items-center gap-1 mb-1">
                  <Q className="h-3 w-3" /> {q.label}
                </label>
                <input
                  type="number" min="0" step="1"
                  value={cfg[q.k] ?? ""}
                  onChange={(e) => upd(q.k, e.target.value === "" ? null : Number(e.target.value))}
                  placeholder="∞ illimité"
                  className="w-full rounded-md ring-1 ring-slate-300 bg-white px-2 py-1.5 text-sm focus:ring-sky-500 focus:ring-2 outline-none"
                  data-testid={`ai-quota-input-${q.k}`}
                />
                <p className="text-[9px] text-slate-400 mt-0.5">{q.unit} / mois</p>
              </div>
            );
          })}
        </div>
      )}

      {/* Budget field */}
      {isBudget && (
        <div className="rounded-lg ring-1 ring-fuchsia-200 bg-fuchsia-50 p-4" data-testid="ai-quota-budget">
          <label className="text-[10px] uppercase tracking-wider text-fuchsia-700 font-semibold flex items-center gap-1 mb-1">
            <Wallet className="h-3 w-3" /> Budget mensuel global
          </label>
          <div className="flex items-center gap-2">
            <input
              type="number" min="0" step="100"
              value={cfg.monthly_budget_xof ?? ""}
              onChange={(e) => upd("monthly_budget_xof", e.target.value === "" ? null : Number(e.target.value))}
              placeholder="Ex: 5000"
              className="flex-1 rounded-md ring-1 ring-fuchsia-300 bg-white px-3 py-1.5 text-lg font-mono focus:ring-fuchsia-500 focus:ring-2 outline-none"
              data-testid="ai-quota-budget-input"
            />
            <span className="text-sm font-bold text-fuchsia-700">XOF / mois</span>
          </div>
          <p className="text-[10px] text-fuchsia-700/80 mt-1">
            Toute consommation IA (images + vidéos + transcriptions + chat) est convertie en XOF et débitée de ce budget.
          </p>
        </div>
      )}

      {/* Alert thresholds */}
      {(isQuota || isBudget) && (
        <div className="grid sm:grid-cols-2 gap-3">
          <div className="rounded-lg ring-1 ring-amber-200 bg-amber-50 p-3">
            <label className="text-[10px] uppercase tracking-wider text-amber-700 font-semibold mb-1 block">
              Seuil d'alerte (warn)
            </label>
            <div className="flex items-center gap-2">
              <input
                type="number" min="1" max="99" step="1"
                value={cfg.alert_warn_pct ?? 80}
                onChange={(e) => upd("alert_warn_pct", Number(e.target.value))}
                className="w-20 rounded-md ring-1 ring-amber-300 bg-white px-2 py-1 text-sm focus:ring-amber-500 focus:ring-2 outline-none"
                data-testid="ai-quota-warn-pct"
              />
              <span className="text-sm text-amber-800">% du quota</span>
            </div>
          </div>
          <label className="rounded-lg ring-1 ring-rose-200 bg-rose-50 p-3 flex items-start gap-2 cursor-pointer" data-testid="ai-quota-block-toggle">
            <input
              type="checkbox"
              checked={cfg.block_on_limit !== false}
              onChange={(e) => upd("block_on_limit", e.target.checked)}
              className="mt-0.5"
            />
            <div>
              <span className="text-sm font-semibold text-rose-900">Bloquer à 100%</span>
              <p className="text-[10px] text-rose-700/80">
                Quand le quota est atteint, les nouvelles requêtes IA renvoient une erreur 429. Décocher pour seulement alerter sans bloquer.
              </p>
            </div>
          </label>
        </div>
      )}

      {/* Tarifs (collapsible) */}
      <details className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3" data-testid="ai-quota-costs-details">
        <summary className="text-xs font-semibold text-slate-700 cursor-pointer flex items-center gap-1">
          <Sparkles className="h-3 w-3" /> Tarifs effectifs (XOF) — modifiable
        </summary>
        <div className="grid sm:grid-cols-4 gap-2 mt-3">
          {[
            { k: "cost_per_image_xof", default_k: "image", label: "Image", unit: "img" },
            { k: "cost_per_video_xof", default_k: "video", label: "Vidéo", unit: "vid" },
            { k: "cost_per_transcription_minute_xof", default_k: "transcription", label: "Transcription", unit: "min" },
            { k: "cost_per_1k_tokens_xof", default_k: "chat", label: "Chat IA", unit: "/ 1k tokens" },
          ].map((c) => (
            <div key={c.k}>
              <label className="text-[9px] uppercase tracking-wider text-slate-500 font-semibold block mb-0.5">{c.label}</label>
              <input
                type="number" min="0" step="0.01"
                value={cfg[c.k] ?? ""}
                onChange={(e) => upd(c.k, e.target.value === "" ? null : Number(e.target.value))}
                placeholder={String(defaults[c.default_k] ?? "—")}
                className="w-full rounded-md ring-1 ring-slate-300 bg-white px-2 py-1 text-xs"
                data-testid={`ai-quota-cost-${c.k}`}
              />
              <p className="text-[9px] text-slate-400">Effectif: {costs[c.default_k]} XOF/{c.unit}</p>
            </div>
          ))}
        </div>
      </details>

      {/* Current usage */}
      <div className="rounded-lg ring-1 ring-slate-200 bg-white p-3" data-testid="ai-quota-usage-block">
        <p className="text-xs font-semibold text-slate-700 mb-2 flex items-center gap-1">
          <Gauge className="h-3 w-3 text-fuchsia-600" /> Consommation du mois ({usage?.year_month})
        </p>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-2">
          {[
            { k: "images", res: "image", label: "Images", value: rollup.images || 0 },
            { k: "videos", res: "video", label: "Vidéos", value: rollup.videos || 0 },
            { k: "transcription_minutes", res: "transcription", label: "Minutes audio", value: rollup.transcription_minutes || 0 },
            { k: "chat_tokens", res: "chat", label: "Tokens chat", value: rollup.chat_tokens || 0 },
          ].map((r) => {
            const lim = limits[r.res] || {};
            const blocked = lim.blocked;
            const warn = lim.warn;
            return (
              <div key={r.k} className={`rounded-md p-2 ring-1 ${
                blocked ? "ring-rose-300 bg-rose-50" : warn ? "ring-amber-300 bg-amber-50" : "ring-slate-200 bg-slate-50"
              }`} data-testid={`usage-card-${r.k}`}>
                <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">{r.label}</p>
                <p className="text-xl font-bold text-slate-900 tabular-nums">{r.value}</p>
                {lim.limit !== null && lim.limit !== undefined && (
                  <p className="text-[10px] text-slate-500">
                    / {lim.limit} ({lim.pct}%)
                  </p>
                )}
              </div>
            );
          })}
        </div>
        {budget && budget.limit_xof && (
          <div className={`mt-2 rounded-md p-3 ring-1 ${
            budget.blocked ? "ring-rose-400 bg-rose-100" : budget.warn ? "ring-amber-400 bg-amber-50" : "ring-fuchsia-200 bg-fuchsia-50"
          }`} data-testid="usage-budget-bar">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-slate-700">Budget mensuel</span>
              <span className="text-xs font-mono">{(budget.used_xof || 0).toLocaleString("fr-FR")} / {budget.limit_xof.toLocaleString("fr-FR")} XOF · {budget.pct}%</span>
            </div>
            <div className="h-2 rounded-full bg-slate-200 overflow-hidden">
              <div
                className={`h-full ${budget.blocked ? "bg-rose-600" : budget.warn ? "bg-amber-500" : "bg-fuchsia-500"}`}
                style={{ width: `${Math.min(100, budget.pct || 0)}%` }}
              />
            </div>
          </div>
        )}
        {/* Per-user breakdown */}
        {(usage?.per_user || []).length > 0 && (
          <details className="mt-3" data-testid="usage-per-user-details">
            <summary className="text-xs font-semibold text-slate-700 cursor-pointer">Détail par Utilisateur Suivi ({usage.per_user.length})</summary>
            <table className="w-full text-xs mt-2">
              <thead className="bg-slate-100 text-slate-600">
                <tr>
                  <th className="text-left px-2 py-1">Utilisateur</th>
                  <th className="text-right px-2 py-1">Images</th>
                  <th className="text-right px-2 py-1">Vidéos</th>
                  <th className="text-right px-2 py-1">Min.</th>
                  <th className="text-right px-2 py-1">Tokens</th>
                  <th className="text-right px-2 py-1">Coût (XOF)</th>
                </tr>
              </thead>
              <tbody>
                {usage.per_user.map((u) => (
                  <tr key={u.user_id} className="border-t border-slate-100">
                    <td className="px-2 py-1 text-slate-800">{u.user_label} <span className="text-[9px] text-slate-400">{u.tracked_role || ""}</span></td>
                    <td className="px-2 py-1 text-right tabular-nums">{u.by_resource?.image?.units || 0}</td>
                    <td className="px-2 py-1 text-right tabular-nums">{u.by_resource?.video?.units || 0}</td>
                    <td className="px-2 py-1 text-right tabular-nums">{(u.by_resource?.transcription?.units || 0).toFixed(1)}</td>
                    <td className="px-2 py-1 text-right tabular-nums">{u.by_resource?.chat?.units || 0}</td>
                    <td className="px-2 py-1 text-right tabular-nums font-semibold">{(u.total_xof || 0).toLocaleString("fr-FR")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        )}
      </div>

      {dirty && (
        <div className="flex justify-end">
          <button
            onClick={save}
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-lg bg-fuchsia-600 text-white px-4 py-2 text-sm hover:bg-fuchsia-700 disabled:opacity-50"
            data-testid="ai-quota-save-btn"
          >
            <Save className="h-4 w-4" /> {saving ? "Enregistrement…" : "Enregistrer les quotas IA"}
          </button>
        </div>
      )}
    </div>
  );
}
