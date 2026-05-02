import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Link2, Copy, Clock, CheckCircle2 } from "lucide-react";

// Admin-only builder for signed deep-links. Produces a URL that an external
// Windows app can fire to land the user on the right page (login, rdv, etc.)
// with params (client code, username, target id) encrypted inside a JWT.
export default function AdminIntegrationLinks() {
  const [actions, setActions] = useState([]);
  const [form, setForm] = useState({ action: "login", client_code: "", username: "", target_id: "", ttl_seconds: 900 });
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    apiClient.get("/integrations/link-actions").then((r) => setActions(r.data)).catch(() => {});
  }, []);

  const build = async () => {
    setLoading(true);
    try {
      const r = await apiClient.post("/integrations/build-link", {
        action: form.action,
        client_code: form.client_code || null,
        username: form.username || null,
        target_id: form.target_id || null,
        ttl_seconds: Number(form.ttl_seconds) || 900,
      });
      // Prepend origin if backend returned a relative URL
      const fullUrl = r.data.url.startsWith("http") ? r.data.url : `${window.location.origin}${r.data.url}`;
      setResult({ ...r.data, url: fullUrl });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur lors de la génération");
    } finally { setLoading(false); }
  };

  const copy = async () => {
    if (!result?.url) return;
    try { await navigator.clipboard.writeText(result.url); toast.success("Lien copié"); }
    catch { toast.error("Impossible de copier"); }
  };

  const upd = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <div className="max-w-3xl space-y-6" data-testid="admin-integration-links">
      <div>
        <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Intégrations</p>
        <h1 className="text-2xl font-display font-bold flex items-center gap-2">
          <Link2 className="h-5 w-5 text-sawali-blue" /> Générateur de liens cryptés
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Ces liens embarquent tous les paramètres (code client, utilisateur, action) dans un jeton signé et à durée de vie limitée.
          Idéal pour les boutons "Ouvrir SAWALI" de vos applications Windows.
        </p>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-5 space-y-4">
        <div className="grid sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-semibold mb-1">Action</label>
            <select
              value={form.action}
              onChange={(e) => upd("action", e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              data-testid="link-action-select"
            >
              {actions.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">Durée de validité</label>
            <select
              value={form.ttl_seconds}
              onChange={(e) => upd("ttl_seconds", e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              data-testid="link-ttl-select"
            >
              <option value={300}>5 minutes</option>
              <option value={900}>15 minutes (recommandé)</option>
              <option value={3600}>1 heure</option>
              <option value={14400}>4 heures</option>
              <option value={86400}>24 heures (max)</option>
            </select>
          </div>
          <Field label="Code client (optionnel)" value={form.client_code} onChange={(v) => upd("client_code", v)} placeholder="ACME-001" testid="link-client-code" />
          <Field label="Utilisateur (optionnel)" value={form.username} onChange={(v) => upd("username", v)} placeholder="jean.dupont@acme.fr" testid="link-username" />
        </div>
        <Field label="Identifiant cible (optionnel)" value={form.target_id} onChange={(v) => upd("target_id", v)} placeholder="ID du document / de l'intervention / du RDV" testid="link-target-id" />

        <button
          onClick={build}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light disabled:opacity-50"
          data-testid="link-generate-btn"
        >
          {loading ? "Génération…" : "Générer le lien"}
        </button>
      </div>

      {result && (
        <div className="rounded-xl ring-2 ring-emerald-400 bg-emerald-50 p-5" data-testid="link-result">
          <div className="flex items-start gap-3 mb-4">
            <CheckCircle2 className="h-5 w-5 text-emerald-600 mt-0.5 flex-shrink-0" />
            <div>
              <p className="text-sm font-semibold text-emerald-900">Lien généré avec succès</p>
              <p className="text-[11px] text-emerald-700 mt-0.5 inline-flex items-center gap-1">
                <Clock className="h-3 w-3" /> Expire le {new Date(result.expires_at).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" })}
                {" · "}Action : <strong>{result.action_label}</strong>
              </p>
            </div>
          </div>
          <div className="flex gap-2">
            <input
              readOnly
              value={result.url}
              className="flex-1 rounded-lg bg-white border border-slate-300 px-3 py-2 text-[12px] font-mono"
              data-testid="link-result-url"
              onFocus={(e) => e.target.select()}
            />
            <button
              onClick={copy}
              className="inline-flex items-center gap-1 rounded-lg bg-slate-900 text-white px-3 py-2 text-xs hover:bg-slate-800"
              data-testid="link-copy-btn"
            >
              <Copy className="h-3.5 w-3.5" /> Copier
            </button>
          </div>
          <details className="mt-3">
            <summary className="text-xs text-slate-600 cursor-pointer">Voir le token JWT seul</summary>
            <code className="block mt-2 text-[11px] bg-white p-2 rounded border border-slate-200 break-all font-mono">{result.token}</code>
          </details>
        </div>
      )}
    </div>
  );
}

const Field = ({ label, value, onChange, placeholder, testid }) => (
  <div>
    <label className="block text-xs font-semibold mb-1">{label}</label>
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:border-sawali-blue"
      data-testid={testid}
    />
  </div>
);
