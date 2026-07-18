// Iter41 (2026-02) — Module VIDAL France — Section AdminSettings
// Manages : enabled flag, mode test/prod, credentials (app_id + app_key + base_url
// pour les 2 envs), TTL cache, quota/jour, timeout HTTP, bouton "Tester la connexion"
// et "Vider le cache".
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  Loader2, Save, Stethoscope, Eye, EyeOff, RefreshCw, Trash2, Plug, Webhook, Copy, Info
} from "lucide-react";
import VidalUsageDashboard from "@/pages/admin/sections/VidalUsageDashboard";

const DEFAULTS = {
  test_base_url: "https://api-test.vidal.net/rest/api",
  prod_base_url: "https://api.vidal.net/rest/api",
  cache_ttl_hours: 168,
  quota_per_user_per_day: 200,
  http_timeout: 12,
};

function Field({ label, value, onChange, type = "text", testid, placeholder, hint }) {
  return (
    <label className="block text-xs">
      <span className="block text-slate-600 mb-1">{label}</span>
      <input
        type={type}
        value={value ?? ""}
        onChange={(e) => onChange(type === "number" ? (parseInt(e.target.value) || 0) : e.target.value)}
        placeholder={placeholder}
        className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono focus:ring-fuchsia-500"
        data-testid={testid}
      />
      {hint && <p className="text-[10px] text-slate-400 mt-1">{hint}</p>}
    </label>
  );
}

function SecretField({ label, value, onChange, testid, placeholder }) {
  const [show, setShow] = useState(false);
  const isMasked = value === "********";
  return (
    <label className="block text-xs">
      <span className="block text-slate-600 mb-1">{label}</span>
      <div className="flex items-stretch gap-1">
        <input
          type={show ? "text" : "password"}
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="flex-1 text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono focus:ring-fuchsia-500"
          data-testid={testid}
        />
        <button type="button" onClick={() => setShow(!show)} className="px-2 ring-1 ring-slate-300 rounded text-slate-500 hover:bg-slate-50">
          {show ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
        </button>
      </div>
      {isMasked && <p className="text-[10px] text-amber-600 mt-1">Clé masquée — écrire pour remplacer.</p>}
    </label>
  );
}

export default function S058VidalSection() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [purging, setPurging] = useState(false);
  const [form, setForm] = useState({});
  const [testResult, setTestResult] = useState(null);

  const load = async () => {
    let next;
    try {
      const r = await apiClient.get("/admin/vidal/config");
      next = r.data || {};
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Impossible de charger la config VIDAL");
    }
    setTimeout(() => {
      if (next) setForm(next);
      setLoading(false);
    }, 0);
  };

  useEffect(() => { load(); }, []);

  const upd = (k, v) => setForm((s) => ({ ...s, [k]: v }));

  const save = async () => {
    setSaving(true);
    try {
      // Ne pas renvoyer les masques au backend
      const out = { ...form };
      if (out.test_app_key === "********") delete out.test_app_key;
      if (out.prod_app_key === "********") delete out.prod_app_key;
      await apiClient.put("/admin/vidal/config", out);
      toast.success("Configuration VIDAL enregistrée");
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
    setTimeout(() => setSaving(false), 0);
  };

  const testConnection = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const r = await apiClient.post("/admin/vidal/test-connection");
      setTestResult(r.data);
      if (r.data?.ok) toast.success(`Connexion VIDAL ${r.data.mode} OK`);
      else toast.error(`Échec : ${r.data?.error || "inconnu"}`);
    } catch (e) {
      const detail = e?.response?.data?.detail || "Erreur réseau";
      setTestResult({ ok: false, error: detail, debug: null });
      toast.error(detail);
    }
    setTimeout(() => setTesting(false), 0);
  };

  const purgeCache = async () => {
    if (!window.confirm("Vider tout le cache VIDAL ?")) return;
    setPurging(true);
    try {
      const r = await apiClient.delete("/admin/vidal/cache");
      toast.success(`Cache vidé (${r.data.deleted} entrées)`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
    setTimeout(() => setPurging(false), 0);
  };

  // Iter43-fix24az-k — VIDAL Webhook proxy tester
  const [testingWebhook, setTestingWebhook] = useState(false);
  const [webhookResult, setWebhookResult] = useState(null);
  const testWebhook = async () => {
    setTestingWebhook(true);
    setWebhookResult(null);
    try {
      const r = await apiClient.post("/admin/vidal/webhook/test");
      setWebhookResult(r.data);
      if (r.data?.ok) toast.success("Webhook VIDAL testé avec succès (aller-retour OK)");
      else toast.error(`Échec webhook : ${r.data?.error || "inconnu"}`);
    } catch (e) {
      const detail = e?.response?.data?.detail || "Erreur réseau";
      setWebhookResult({ ok: false, error: detail });
      toast.error(detail);
    }
    setTimeout(() => setTestingWebhook(false), 0);
  };
  const copyCallbackUrl = () => {
    const u = form.webhook_callback_url || "";
    if (!u) return;
    try {
      navigator.clipboard.writeText(u);
      toast.success("URL callback copiée dans le presse-papier");
    } catch (_e) {
      toast.error("Copie impossible");
    }
  };

  if (loading) return (
    <div className="flex items-center gap-2 text-sm text-slate-600 py-4">
      <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
    </div>
  );

  const isProd = form.mode === "production";

  return (
    <div className="space-y-4" data-testid="s058-vidal-section">
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs text-slate-600 flex-1">
          <Stethoscope className="inline h-3 w-3 mr-1 text-fuchsia-600" />
          Module <strong>VIDAL France</strong> — recherche médicament, monographies (RCP), catalogue
          réglementaire et analyse de prescriptions (interactions, contre-indications, allergies).
          Configurez 2 environnements et basculez via <code>Mode</code>.
        </p>
      </div>

      {/* Toggle + mode */}
      <div className="grid sm:grid-cols-2 gap-3 ring-1 ring-slate-200 rounded-lg p-3 bg-white">
        <label className="flex items-center gap-2 text-xs cursor-pointer">
          <input
            type="checkbox"
            checked={!!form.enabled}
            onChange={(e) => upd("enabled", e.target.checked)}
            className="h-4 w-4"
            data-testid="vidal-enabled-toggle"
          />
          <span className="font-semibold">Module VIDAL activé</span>
        </label>
        <label className="block text-xs">
          <span className="block text-slate-600 mb-1">Mode actif</span>
          <select
            value={form.mode || "test"}
            onChange={(e) => upd("mode", e.target.value)}
            className={`w-full text-xs px-2 py-1.5 rounded ring-1 font-semibold ${isProd ? "ring-rose-400 text-rose-700 bg-rose-50" : "ring-emerald-400 text-emerald-700 bg-emerald-50"}`}
            data-testid="vidal-mode-select"
          >
            <option value="test">🧪 Test (sandbox)</option>
            <option value="production">🚀 Production</option>
          </select>
        </label>
      </div>

      {/* TEST env */}
      <div className="ring-1 ring-emerald-200 rounded-lg p-3 bg-emerald-50/30" data-testid="vidal-test-env">
        <h4 className="text-xs font-semibold text-emerald-800 mb-2">🧪 Environnement TEST</h4>
        <div className="grid sm:grid-cols-3 gap-3">
          <Field
            label="Base URL"
            value={form.test_base_url}
            onChange={(v) => upd("test_base_url", v)}
            placeholder={DEFAULTS.test_base_url}
            testid="vidal-test-base-url"
          />
          <Field
            label="app_id"
            value={form.test_app_id}
            onChange={(v) => upd("test_app_id", v)}
            placeholder="application_id"
            testid="vidal-test-app-id"
          />
          <SecretField
            label="app_key"
            value={form.test_app_key}
            onChange={(v) => upd("test_app_key", v)}
            placeholder="secret_application_key"
            testid="vidal-test-app-key"
          />
        </div>
      </div>

      {/* PROD env */}
      <div className="ring-1 ring-rose-200 rounded-lg p-3 bg-rose-50/30" data-testid="vidal-prod-env">
        <h4 className="text-xs font-semibold text-rose-800 mb-2">🚀 Environnement PRODUCTION</h4>
        <div className="grid sm:grid-cols-3 gap-3">
          <Field
            label="Base URL"
            value={form.prod_base_url}
            onChange={(v) => upd("prod_base_url", v)}
            placeholder={DEFAULTS.prod_base_url}
            testid="vidal-prod-base-url"
          />
          <Field
            label="app_id"
            value={form.prod_app_id}
            onChange={(v) => upd("prod_app_id", v)}
            placeholder="application_id"
            testid="vidal-prod-app-id"
          />
          <SecretField
            label="app_key"
            value={form.prod_app_key}
            onChange={(v) => upd("prod_app_key", v)}
            placeholder="secret_application_key"
            testid="vidal-prod-app-key"
          />
        </div>
      </div>

      {/* Cache + quota */}
      <div className="ring-1 ring-slate-200 rounded-lg p-3 bg-white grid sm:grid-cols-3 gap-3">
        <Field
          label="TTL cache (heures)"
          type="number"
          value={form.cache_ttl_hours}
          onChange={(v) => upd("cache_ttl_hours", v)}
          placeholder={DEFAULTS.cache_ttl_hours}
          hint="168 = 7 jours (recommandé)"
          testid="vidal-cache-ttl"
        />
        <Field
          label="Quota / utilisateur / jour"
          type="number"
          value={form.quota_per_user_per_day}
          onChange={(v) => upd("quota_per_user_per_day", v)}
          placeholder={DEFAULTS.quota_per_user_per_day}
          hint="0 = illimité"
          testid="vidal-quota"
        />
        <Field
          label="Timeout HTTP (secondes)"
          type="number"
          value={form.http_timeout}
          onChange={(v) => upd("http_timeout", v)}
          placeholder={DEFAULTS.http_timeout}
          hint="2 à 60"
          testid="vidal-timeout"
        />
      </div>

      {/* Iter43-fix24az-k — Webhook proxy config */}
      <div className="ring-1 ring-fuchsia-200 rounded-lg p-3 bg-fuchsia-50/50" data-testid="vidal-webhook-panel">
        <div className="flex items-center gap-2 mb-2">
          <Webhook className="h-4 w-4 text-fuchsia-600" />
          <h4 className="text-sm font-semibold text-fuchsia-900">Proxy Webhook (mode passerelle)</h4>
          <label className="ml-auto inline-flex items-center gap-1 text-xs text-slate-700 cursor-pointer">
            <input
              type="checkbox"
              checked={!!form.webhook_enabled}
              onChange={(e) => upd("webhook_enabled", e.target.checked)}
              data-testid="vidal-webhook-enabled"
            />
            <span>Activer</span>
          </label>
        </div>
        <p className="text-[11px] text-slate-600 mb-3 flex items-start gap-1">
          <Info className="h-3 w-3 mt-0.5 shrink-0 text-fuchsia-600" />
          <span>
            Quand activé, chaque requête VIDAL (y compris Liluvine) est envoyée en POST à
            l&apos;URL sortante ci-dessous au lieu d&apos;appeler VIDAL directement. Le système externe
            (n8n, Zapier, script custom…) traite la requête puis retourne le résultat en POST sur
            l&apos;URL de callback affichée à droite.
          </span>
        </p>
        <div className="grid sm:grid-cols-2 gap-3">
          <Field
            label="URL sortante (POST)"
            value={form.webhook_outbound_url}
            onChange={(v) => upd("webhook_outbound_url", v)}
            placeholder="https://n8n.example.com/webhook/vidal"
            hint="Reçoit le JSON de requête ; doit répondre 200 pour indiquer prise en compte."
            testid="vidal-webhook-outbound-url"
          />
          <Field
            label="Timeout callback (secondes)"
            type="number"
            value={form.webhook_timeout_seconds}
            onChange={(v) => upd("webhook_timeout_seconds", v)}
            placeholder="30"
            hint="5 à 300. Passé ce délai sans callback, la requête retourne une erreur."
            testid="vidal-webhook-timeout"
          />
        </div>
        <div className="mt-3">
          <label className="block text-xs">
            <span className="block text-slate-600 mb-1">URL de callback (à configurer côté système externe)</span>
            <div className="flex items-stretch gap-1">
              <input
                type="text" readOnly
                value={form.webhook_callback_url || ""}
                className="flex-1 text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono bg-white text-slate-700"
                data-testid="vidal-webhook-callback-url"
              />
              <button type="button" onClick={copyCallbackUrl} className="px-2 ring-1 ring-slate-300 rounded text-slate-600 hover:bg-slate-50" title="Copier">
                <Copy className="h-3 w-3" />
              </button>
            </div>
            <p className="text-[10px] text-slate-500 mt-1">
              Votre système externe POST son résultat sur cette URL, avec un JSON
              <code className="mx-1 px-1 rounded bg-white ring-1 ring-slate-200">{'{"correlation_id":"…","status_code":200,"body":{…}}'}</code>.
            </p>
          </label>
        </div>
        {webhookResult && (
          <div
            className={`mt-3 text-xs rounded p-2 ring-1 ${webhookResult.ok ? "bg-emerald-50 ring-emerald-300 text-emerald-800" : "bg-rose-50 ring-rose-300 text-rose-800"}`}
            data-testid="vidal-webhook-test-result"
          >
            {webhookResult.ok
              ? <>✅ Aller-retour webhook OK. Extrait : <code className="ml-1">{(webhookResult.sample || "").slice(0, 200)}</code></>
              : <>❌ {webhookResult.error || "Erreur webhook"}</>}
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex flex-wrap items-center gap-2 pt-2">
        <button
          onClick={save}
          disabled={saving}
          className="text-xs px-3 py-1.5 rounded bg-fuchsia-600 hover:bg-fuchsia-700 text-white inline-flex items-center gap-1 disabled:opacity-60"
          data-testid="vidal-save-btn"
        >
          {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />} Enregistrer
        </button>
        <button
          onClick={testConnection}
          disabled={testing}
          className="text-xs px-3 py-1.5 rounded ring-1 ring-slate-300 hover:bg-slate-50 inline-flex items-center gap-1 disabled:opacity-60"
          data-testid="vidal-test-connection-btn"
        >
          {testing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plug className="h-3 w-3" />} Tester la connexion
        </button>
        <button
          onClick={testWebhook}
          disabled={testingWebhook || !form.webhook_enabled}
          title={!form.webhook_enabled ? "Activez d'abord le webhook + saisissez son URL sortante" : "Envoyer un aller-retour de test"}
          className="text-xs px-3 py-1.5 rounded ring-1 ring-fuchsia-300 text-fuchsia-700 hover:bg-fuchsia-50 inline-flex items-center gap-1 disabled:opacity-60"
          data-testid="vidal-test-webhook-btn"
        >
          {testingWebhook ? <Loader2 className="h-3 w-3 animate-spin" /> : <Webhook className="h-3 w-3" />} Tester le webhook
        </button>
        <button
          onClick={purgeCache}
          disabled={purging}
          className="text-xs px-3 py-1.5 rounded ring-1 ring-rose-300 text-rose-700 hover:bg-rose-50 inline-flex items-center gap-1 disabled:opacity-60"
          data-testid="vidal-purge-cache-btn"
        >
          {purging ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />} Vider le cache
        </button>
        <button
          onClick={load}
          className="text-xs px-3 py-1.5 rounded ring-1 ring-slate-300 hover:bg-slate-50 inline-flex items-center gap-1"
          data-testid="vidal-reload-btn"
        >
          <RefreshCw className="h-3 w-3" /> Recharger
        </button>
      </div>

      {/* Test result */}
      {testResult && (
        <div className={`text-xs p-3 rounded ring-1 ${testResult.ok ? "ring-emerald-300 bg-emerald-50 text-emerald-800" : "ring-rose-300 bg-rose-50 text-rose-800"}`} data-testid="vidal-test-result">
          {testResult.ok
            ? `✅ Connexion ${testResult.mode} OK (réponse reçue, ${testResult.sample_size} octets analysés)`
            : `❌ Échec : ${testResult.error}`}
        </div>
      )}

      {/* Iter41 Phase 4 — Dashboard d'utilisation */}
      <div className="pt-4 border-t border-slate-200">
        <VidalUsageDashboard />
      </div>

      {/* Debug verbose — toujours rendu quand un test a été lancé */}
      {testResult && testResult.debug && (
        <details className="text-xs ring-1 ring-slate-300 rounded bg-slate-50" data-testid="vidal-debug-panel" open>
          <summary className="cursor-pointer px-3 py-2 font-semibold text-slate-700 hover:bg-slate-100">
            🔍 Debug verbose (requête + réponse)
          </summary>
          <div className="p-3 space-y-3">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Requête envoyée</div>
              <div className="bg-white ring-1 ring-slate-200 rounded p-2 space-y-1 font-mono text-[11px]">
                <div><span className="text-fuchsia-600 font-semibold">{testResult.debug.request?.method}</span> <span className="break-all">{testResult.debug.request?.url}</span></div>
                <div><span className="text-slate-500">mode:</span> <span className={testResult.debug.request?.mode === "production" ? "text-rose-700" : "text-emerald-700"}>{testResult.debug.request?.mode}</span></div>
                <div><span className="text-slate-500">timeout:</span> {testResult.debug.request?.timeout_seconds}s</div>
                <div className="text-slate-500">Params :</div>
                <pre className="bg-slate-50 rounded p-2 overflow-auto max-h-32">{JSON.stringify(testResult.debug.request?.params || {}, null, 2)}</pre>
                {testResult.debug.request?.body && (
                  <>
                    <div className="text-slate-500">Body :</div>
                    <pre className="bg-slate-50 rounded p-2 overflow-auto max-h-32">{JSON.stringify(testResult.debug.request.body, null, 2)}</pre>
                  </>
                )}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Réponse reçue</div>
              {testResult.debug.error ? (
                <div className="bg-rose-100 ring-1 ring-rose-200 rounded p-2 font-mono text-[11px] text-rose-800">
                  Erreur réseau : {testResult.debug.error}
                </div>
              ) : testResult.debug.response ? (
                <div className="bg-white ring-1 ring-slate-200 rounded p-2 space-y-1 font-mono text-[11px]">
                  <div>
                    <span className="text-slate-500">Status :</span>{" "}
                    <span className={testResult.debug.response.status_code < 400 ? "text-emerald-700 font-semibold" : "text-rose-700 font-semibold"}>
                      {testResult.debug.response.status_code}
                    </span>
                    {testResult.debug.response.elapsed_ms !== null && (
                      <span className="ml-3 text-slate-400">({testResult.debug.response.elapsed_ms} ms)</span>
                    )}
                  </div>
                  <div><span className="text-slate-500">Content-Type :</span> {testResult.debug.response.content_type || "(inconnu)"}</div>
                  <div className="text-slate-500">Body preview {testResult.debug.response.body_truncated && "(tronqué à 2000 chars)"} :</div>
                  <pre className="bg-slate-50 rounded p-2 overflow-auto max-h-60 whitespace-pre-wrap break-all">{testResult.debug.response.body_preview || "(vide)"}</pre>
                </div>
              ) : (
                <div className="text-slate-400 italic">Aucune réponse — la requête n&apos;a pas pu partir.</div>
              )}
            </div>
          </div>
        </details>
      )}
    </div>
  );
}
