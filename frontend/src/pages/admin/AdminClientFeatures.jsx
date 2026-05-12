import React, { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { ArrowLeft, MessageCircle, Smartphone, Sparkles, CreditCard, Save, ShieldCheck, Webhook, Building2, Volume2 } from "lucide-react";

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
];

export default function AdminClientFeatures() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [features, setFeatures] = useState({ whatsapp: false, sms: false, ai: false, payments: false, webhook_returns: false, anon_name: false, anon_company: false, anon_email: false, anon_phone: false, anon_whatsapp: false, anon_rapports: false, anon_suivis: false, anon_communications: false, wa_sound_alerts: true });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get(`/admin/clients/${id}/features`);
      setData(r.data);
      setFeatures(r.data?.features || {});
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
      await apiClient.put(`/admin/clients/${id}/features`, features);
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
