/*
 * 2026-02 fork (P0) — Section "Paramètres Smart Communications" par tenant
 * dans /portal/my-account. Chaque tenant fournit SES PROPRES identifiants
 * WhatsApp Business, Meta, Instagram, X, TikTok, LinkedIn.
 *
 * Q3=b : STRICT OVERRIDE — pas de fallback global. Un tenant sans config = pas
 * d'envoi de communications pour ce tenant.
 *
 * Les secrets (tokens/secrets API) sont masqués en lecture (last 4 chars).
 * Un champ vide au PUT signifie "conserver la valeur actuelle".
 */
import React, { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { MessageSquare, Loader2, Save, Info } from "lucide-react";

const CHANNELS = [
  {
    key: "wa",
    label: "WhatsApp Business (WABA)",
    color: "emerald",
    fields: [
      { name: "wa_waba_id", label: "WABA ID" },
      { name: "wa_phone_number_id", label: "Phone Number ID" },
      { name: "wa_access_token", label: "Access Token", secret: true },
      { name: "wa_verify_token", label: "Verify Token webhook", secret: true },
    ],
  },
  {
    key: "meta",
    label: "Meta (Facebook)",
    color: "blue",
    fields: [
      { name: "meta_app_id", label: "App ID" },
      { name: "meta_app_secret", label: "App Secret", secret: true },
      { name: "meta_page_id", label: "Page ID" },
      { name: "meta_page_access_token", label: "Page Access Token", secret: true },
    ],
  },
  {
    key: "instagram",
    label: "Instagram Business",
    color: "pink",
    fields: [
      { name: "instagram_business_id", label: "Business Account ID" },
      { name: "instagram_access_token", label: "Access Token", secret: true },
    ],
  },
  {
    key: "x",
    label: "X (Twitter)",
    color: "slate",
    fields: [
      { name: "x_api_key", label: "API Key" },
      { name: "x_api_secret", label: "API Secret", secret: true },
      { name: "x_access_token", label: "Access Token" },
      { name: "x_access_secret", label: "Access Secret", secret: true },
    ],
  },
  {
    key: "tiktok",
    label: "TikTok",
    color: "rose",
    fields: [
      { name: "tiktok_client_id", label: "Client ID" },
      { name: "tiktok_client_secret", label: "Client Secret", secret: true },
      { name: "tiktok_access_token", label: "Access Token", secret: true },
    ],
  },
  {
    key: "linkedin",
    label: "LinkedIn",
    color: "cyan",
    fields: [
      { name: "linkedin_client_id", label: "Client ID" },
      { name: "linkedin_client_secret", label: "Client Secret", secret: true },
      { name: "linkedin_access_token", label: "Access Token", secret: true },
      { name: "linkedin_organization_id", label: "Organization ID" },
    ],
  },
];

export default function SmartCommunicationsTenantSection() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [current, setCurrent] = useState({});
  const [draft, setDraft] = useState({});
  const [activeChannel, setActiveChannel] = useState(CHANNELS[0].key);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/me/smart-communications");
      setCurrent(r.data || {});
      setDraft({});  // start fresh
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const set = (name, value) => setDraft((d) => ({ ...d, [name]: value }));

  const save = async () => {
    // Only send non-empty values (empty = keep current)
    const payload = {};
    for (const [k, v] of Object.entries(draft)) {
      if (typeof v === "string" && v.trim() !== "") payload[k] = v.trim();
    }
    if (Object.keys(payload).length === 0) {
      toast.info("Aucune modification à enregistrer");
      return;
    }
    setSaving(true);
    try {
      await apiClient.put("/me/smart-communications", payload);
      toast.success("Paramètres Smart Communications enregistrés");
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    } finally { setSaving(false); }
  };

  const activeCfg = CHANNELS.find((c) => c.key === activeChannel);
  const dirty = Object.keys(draft).some((k) => (draft[k] || "").trim() !== "");

  return (
    <section
      className="rounded-xl ring-1 ring-purple-200 bg-purple-50/40 p-5 space-y-4"
      data-testid="tenant-smart-comm-section"
    >
      <h2 className="font-display font-semibold text-sm text-purple-800 flex items-center gap-2">
        <MessageSquare className="h-4 w-4" /> Paramètres Smart Communications (spécifiques à mon tenant)
      </h2>

      <div className="flex items-start gap-2 rounded-lg bg-white ring-1 ring-purple-200 p-2 text-xs text-purple-800">
        <Info className="h-4 w-4 shrink-0 mt-0.5" />
        <div>
          Configurez ici <strong>vos propres identifiants API</strong> pour envoyer/recevoir des messages WhatsApp,
          publier sur les réseaux sociaux et suivre vos campagnes. Ces paramètres sont propres à votre tenant
          et remplacent la configuration globale par défaut. Les secrets sont automatiquement masqués après enregistrement.
        </div>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-slate-500 text-sm">
          <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
        </div>
      ) : (
        <>
          {/* Channel tabs */}
          <div className="flex flex-wrap gap-1">
            {CHANNELS.map((c) => {
              // Show a small green dot when at least one field for this channel is configured
              const hasCfg = c.fields.some((f) => (current[f.name] || current[`${f.name}_masked`]));
              return (
                <button
                  key={c.key}
                  type="button"
                  onClick={() => setActiveChannel(c.key)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors inline-flex items-center gap-1 ${
                    activeChannel === c.key
                      ? "bg-purple-600 text-white"
                      : "bg-white ring-1 ring-purple-200 text-purple-700 hover:bg-purple-100"
                  }`}
                  data-testid={`smart-comm-tab-${c.key}`}
                >
                  {hasCfg && <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500" title="Configuré" />}
                  {c.label}
                </button>
              );
            })}
          </div>

          {/* Active channel form */}
          {activeCfg && (
            <div className="grid sm:grid-cols-2 gap-3 rounded-lg bg-white ring-1 ring-purple-200 p-4">
              {activeCfg.fields.map((f) => {
                const maskedKey = `${f.name}_masked`;
                const currentMasked = current[maskedKey];
                const currentValue = current[f.name];
                const draftValue = draft[f.name];
                // For non-secret fields : if the user hasn't started typing,
                // show the saved value AS the input value (not a grey
                // placeholder). This makes "already configured" obvious.
                const displayValue = f.secret
                  ? (draftValue ?? "")
                  : (draftValue ?? currentValue ?? "");
                return (
                  <label key={f.name} className="block">
                    <span className="text-xs font-semibold text-slate-700">{f.label}{f.secret ? " 🔒" : ""}</span>
                    <input
                      type={f.secret ? "password" : "text"}
                      value={displayValue}
                      onChange={(e) => set(f.name, e.target.value)}
                      placeholder={f.secret
                        ? (currentMasked || (currentValue ? "•••• (déjà configuré)" : "Non défini"))
                        : "Non défini"}
                      className="mt-1 w-full px-2 py-1.5 rounded-lg border border-slate-300 text-sm"
                      data-testid={`smart-comm-field-${f.name}`}
                    />
                    {f.secret && (currentMasked || currentValue) && (
                      <span className="text-[10px] text-slate-500">Actuel : {currentMasked || "••••"}</span>
                    )}
                  </label>
                );
              })}
            </div>
          )}

          <button
            type="button"
            onClick={save}
            disabled={saving || !dirty}
            className="inline-flex items-center gap-1.5 rounded-lg bg-purple-600 hover:bg-purple-700 text-white px-3 py-1.5 text-sm disabled:opacity-50"
            data-testid="smart-comm-save-btn"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Enregistrer
          </button>
          {dirty && !saving && (
            <span className="ml-2 text-xs text-purple-700">Modifications non enregistrées</span>
          )}
        </>
      )}
    </section>
  );
}
