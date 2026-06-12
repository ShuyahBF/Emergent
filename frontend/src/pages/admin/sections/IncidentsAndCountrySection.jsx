// Iter42d (2026-02) — Section AdminSettings : Webhook entrant Incidents
// + code pays par défaut pour le catalogue AMM.
//
// Le webhook entrant permet aux serveurs tiers (Watchdog, Uptime-Bot, etc.)
// d'envoyer un incident via POST /api/public/incidents avec auth simple
// (header X-Webhook-Password ou champ password dans le body).
//
// Le code pays par défaut (ISO-2) est utilisé pour rattacher les nouveaux
// AMM créés (POST/import CSV) à un pays. Chaque pays a sa propre autorité
// pharmaceutique → chaque AMM est lié à un pays.
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Loader2, KeyRound, Copy, AlertTriangle, Save, RefreshCw, Trash2, ShieldCheck, Globe2 } from "lucide-react";

export default function IncidentsAndCountrySection() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [info, setInfo] = useState({ configured: false, url: "/api/public/incidents", recent: [] });
  const [newPwd, setNewPwd] = useState(null);
  const [busy, setBusy] = useState(false);
  const [country, setCountry] = useState("");
  // Iter42e — URL publique forcée (optionnel) : permet à l'admin de
  // surcharger l'URL affichée si le domaine de production diffère du domaine
  // où l'admin est connecté (rare — CDN/proxy). Par défaut on prend
  // window.location.origin qui suit toujours le domaine courant.
  const [publicUrlOverride, setPublicUrlOverride] = useState("");
  const [savingUrl, setSavingUrl] = useState(false);

  // Iter42e — Utiliser window.location.origin (= domaine courant du navigateur)
  // au lieu de REACT_APP_BACKEND_URL qui est fixé au build et peut pointer
  // vers la preview même en production.
  const browserOrigin = typeof window !== "undefined" ? window.location.origin.replace(/\/$/, "") : "";
  const apiBase = (publicUrlOverride || browserOrigin).replace(/\/$/, "");

  const load = async () => {
    setLoading(true);
    try {
      const [r1, r2] = await Promise.all([
        apiClient.get("/admin/incidents-webhook"),
        apiClient.get("/admin/settings"),
      ]);
      setInfo(r1.data || { configured: false, url: "/api/public/incidents", recent: [] });
      setCountry((r2.data?.amm_default_country || "").toUpperCase());
      setPublicUrlOverride(r2.data?.public_app_url || "");
    } catch {
      toast.error("Erreur chargement");
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const regen = async () => {
    if (!window.confirm("Confirmer la régénération ? L'ancien mot de passe sera révoqué immédiatement.")) return;
    setBusy(true);
    try {
      const r = await apiClient.post("/admin/incidents-webhook/regenerate-password");
      setNewPwd(r.data.password);
      toast.success("Nouveau mot de passe généré — copiez-le maintenant");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    } finally { setBusy(false); }
  };

  const disable = async () => {
    if (!window.confirm("Désactiver le webhook ? Les requêtes entrantes seront refusées (503).")) return;
    setBusy(true);
    try {
      await apiClient.delete("/admin/incidents-webhook/password");
      toast.success("Webhook désactivé");
      setNewPwd(null);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    } finally { setBusy(false); }
  };

  const copy = (text) => {
    navigator.clipboard.writeText(text);
    toast.success("Copié");
  };

  const saveCountry = async () => {
    setSaving(true);
    try {
      await apiClient.put("/admin/settings", { amm_default_country: country.toUpperCase().slice(0, 2) });
      toast.success("Code pays par défaut enregistré");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    } finally { setSaving(false); }
  };

  const savePublicUrl = async () => {
    setSavingUrl(true);
    try {
      const cleaned = (publicUrlOverride || "").trim().replace(/\/$/, "");
      await apiClient.put("/admin/settings", { public_app_url: cleaned || null });
      toast.success(cleaned ? "URL publique enregistrée" : "Override désactivé (domaine courant utilisé)");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    } finally { setSavingUrl(false); }
  };

  if (loading) return (
    <div className="flex items-center gap-2 text-sm text-slate-600 py-4">
      <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
    </div>
  );

  const fullUrl = `${apiBase}${info.url}`;

  return (
    <div className="space-y-6" data-testid="incidents-country-section">

      {/* ============= Code pays par défaut AMM ============= */}
      <div className="ring-1 ring-slate-200 rounded-lg p-4 bg-white" data-testid="amm-default-country-card">
        <div className="flex items-start gap-3 mb-3">
          <div className="h-10 w-10 rounded-xl bg-indigo-100 text-indigo-700 flex items-center justify-center">
            <Globe2 className="h-5 w-5" />
          </div>
          <div className="flex-1">
            <h3 className="font-semibold text-slate-900">Code pays par défaut du catalogue AMM</h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Chaque pays a sa propre autorité pharmaceutique avec ses propres numéros AMM.
              Ce code (ISO-2) est associé automatiquement à tout nouvel AMM créé via POST ou import CSV.
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <label className="block text-xs">
            <span className="block text-slate-600 mb-1">Code pays (2 lettres)</span>
            <input value={country} onChange={(e) => setCountry(e.target.value.toUpperCase().slice(0, 2))}
                   placeholder="BF" maxLength={2}
                   className="w-24 text-center text-lg font-mono px-3 py-2 rounded ring-1 ring-slate-300"
                   data-testid="amm-default-country-input" />
          </label>
          <button onClick={saveCountry} disabled={saving}
                  className="text-sm px-3 py-2 rounded bg-indigo-600 hover:bg-indigo-700 text-white inline-flex items-center gap-2 disabled:opacity-60"
                  data-testid="amm-default-country-save">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Enregistrer
          </button>
          <p className="text-[11px] text-slate-500 ml-2">
            Exemples : <code className="bg-slate-100 px-1 rounded">BF</code> Burkina, <code className="bg-slate-100 px-1 rounded">CI</code> Côte d&apos;Ivoire, <code className="bg-slate-100 px-1 rounded">FR</code> France, <code className="bg-slate-100 px-1 rounded">SN</code> Sénégal
          </p>
        </div>
      </div>

      {/* ============= Webhook entrant Incidents ============= */}
      <div className="ring-1 ring-slate-200 rounded-lg p-4 bg-white" data-testid="incidents-webhook-card">
        <div className="flex items-start gap-3 mb-3">
          <div className={`h-10 w-10 rounded-xl flex items-center justify-center ${info.configured ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
            <KeyRound className="h-5 w-5" />
          </div>
          <div className="flex-1">
            <h3 className="font-semibold text-slate-900">Webhook entrant — Incidents serveur</h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Endpoint public permettant à vos serveurs tiers d&apos;envoyer un incident.
              Auth par mot de passe simple (header <code className="bg-slate-100 px-1 rounded">X-Webhook-Password</code> ou champ <code className="bg-slate-100 px-1 rounded">password</code> dans le body JSON).
              Chaque incident crée un ticket dans le module support.
            </p>
          </div>
          <span className={`text-[10px] uppercase tracking-wider font-medium px-2 py-1 rounded ring-1 self-start ${
            info.configured
              ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
              : "bg-slate-50 text-slate-500 ring-slate-200"
          }`}>
            {info.configured ? "Actif" : "Inactif"}
          </span>
        </div>

        <div className="space-y-2">
          {/* Iter42e — URL publique override (optionnel) */}
          <div className="bg-slate-50 ring-1 ring-slate-200 rounded p-3 text-xs">
            <div className="flex items-start gap-2 mb-2">
              <Globe2 className="h-4 w-4 text-slate-600 mt-0.5" />
              <div className="flex-1">
                <p className="font-medium text-slate-700">URL publique du portail (optionnel)</p>
                <p className="text-[11px] text-slate-500 mt-0.5">
                  Par défaut on utilise le <strong>domaine courant</strong> de votre navigateur (<code className="bg-white px-1 rounded ring-1 ring-slate-200">{browserOrigin}</code>).
                  Saisissez ici l&apos;URL exacte de production si vous voulez forcer son affichage dans les exemples ci-dessous.
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <input
                value={publicUrlOverride}
                onChange={(e) => setPublicUrlOverride(e.target.value)}
                placeholder="https://votre-domaine.com"
                className="flex-1 text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono"
                data-testid="public-url-override-input"
              />
              <button onClick={savePublicUrl} disabled={savingUrl}
                      className="text-xs px-3 py-1.5 rounded bg-slate-700 hover:bg-slate-800 text-white inline-flex items-center gap-1 disabled:opacity-60"
                      data-testid="public-url-override-save">
                {savingUrl ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />} Enregistrer
              </button>
              {publicUrlOverride && (
                <button onClick={() => { setPublicUrlOverride(""); savePublicUrl(); }}
                        className="text-[11px] text-slate-500 hover:text-slate-700 px-2"
                        title="Vider et utiliser le domaine courant"
                        data-testid="public-url-override-clear">
                  Vider
                </button>
              )}
            </div>
          </div>

          <Field label="URL publique du webhook (à utiliser depuis votre serveur)">
            <div className="flex items-center gap-1">
              <code className="flex-1 bg-slate-50 ring-1 ring-slate-200 rounded px-2 py-1.5 text-[11px] font-mono break-all" data-testid="incidents-webhook-url">{fullUrl}</code>
              <button onClick={() => copy(fullUrl)} className="p-1.5 rounded hover:bg-slate-100" title="Copier l'URL"
                      data-testid="incidents-webhook-copy-url">
                <Copy className="h-3.5 w-3.5 text-slate-600" />
              </button>
            </div>
          </Field>

          {!info.configured && (
            <div className="bg-amber-50 ring-1 ring-amber-200 rounded p-3 text-xs text-amber-800">
              <p className="font-medium inline-flex items-center gap-1"><AlertTriangle className="h-3.5 w-3.5" /> Webhook non configuré</p>
              <p className="mt-1">Cliquez sur « Générer un mot de passe » pour activer.</p>
            </div>
          )}

          {newPwd && (
            <div className="bg-emerald-50 ring-2 ring-emerald-300 rounded p-3" data-testid="incidents-new-pwd">
              <div className="flex items-start gap-2">
                <ShieldCheck className="h-5 w-5 text-emerald-600 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-emerald-900">Nouveau mot de passe</p>
                  <p className="text-[11px] text-emerald-800 mt-0.5">⚠️ Copiez-le maintenant — il ne sera plus affiché.</p>
                  <div className="mt-2 flex items-center gap-1">
                    <code className="flex-1 break-all bg-white ring-1 ring-emerald-200 rounded px-2 py-1.5 text-xs font-mono" data-testid="incidents-new-pwd-value">{newPwd}</code>
                    <button onClick={() => copy(newPwd)} className="text-xs px-2 py-1.5 rounded bg-emerald-600 text-white hover:bg-emerald-700 inline-flex items-center gap-1"
                            data-testid="incidents-new-pwd-copy">
                      <Copy className="h-3 w-3" /> Copier
                    </button>
                  </div>
                  <button onClick={() => setNewPwd(null)} className="mt-2 text-xs text-emerald-700 hover:underline" data-testid="incidents-new-pwd-done">
                    ✓ J&apos;ai sauvegardé le mot de passe
                  </button>
                </div>
              </div>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2 pt-2">
            <button onClick={regen} disabled={busy}
                    className="text-xs px-3 py-2 rounded bg-rose-600 hover:bg-rose-700 text-white inline-flex items-center gap-1 disabled:opacity-60"
                    data-testid="incidents-regen-btn">
              <RefreshCw className="h-3 w-3" /> {info.configured ? "Régénérer le mot de passe" : "Générer un mot de passe"}
            </button>
            {info.configured && (
              <button onClick={disable} disabled={busy}
                      className="text-xs px-3 py-2 rounded ring-1 ring-slate-300 text-slate-700 hover:bg-slate-50 inline-flex items-center gap-1 disabled:opacity-60"
                      data-testid="incidents-disable-btn">
                <Trash2 className="h-3 w-3" /> Désactiver le webhook
              </button>
            )}
          </div>

          {/* Exemple curl */}
          <details className="text-xs ring-1 ring-slate-200 rounded bg-slate-50 mt-2" data-testid="incidents-example-curl">
            <summary className="cursor-pointer px-3 py-2 font-medium text-slate-700 hover:bg-slate-100">
              💡 Exemple d&apos;appel depuis votre serveur (curl / Python)
            </summary>
            <div className="p-3 space-y-3">
              <div>
                <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">curl</p>
                <pre className="bg-slate-900 text-emerald-200 p-2 rounded text-[11px] overflow-x-auto">
{`curl -X POST "${fullUrl}" \\
  -H "Content-Type: application/json" \\
  -H "X-Webhook-Password: VOTRE_MOT_DE_PASSE" \\
  -d '{
    "title": "Outage prod DB",
    "description": "Mongo unreachable for 2min",
    "severity": "critical",
    "source": "watchdog-prod",
    "metadata": {"region": "eu-west-1"}
  }'`}
                </pre>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Python</p>
                <pre className="bg-slate-900 text-emerald-200 p-2 rounded text-[11px] overflow-x-auto">
{`import requests
requests.post(
    "${fullUrl}",
    headers={"X-Webhook-Password": "VOTRE_MOT_DE_PASSE"},
    json={
        "title": "Outage prod DB",
        "severity": "critical",
        "source": "watchdog-prod",
    },
)`}
                </pre>
              </div>
              <p className="text-[10px] text-slate-500">
                Le champ <code>severity</code> accepte : <code>low</code>, <code>medium</code>, <code>high</code>, <code>critical</code>.
              </p>
            </div>
          </details>

          {/* Logs récents */}
          {info.recent?.length > 0 && (
            <details className="text-xs ring-1 ring-slate-200 rounded bg-white mt-2" data-testid="incidents-recent-log">
              <summary className="cursor-pointer px-3 py-2 font-medium text-slate-700 hover:bg-slate-50">
                📜 Activité récente ({info.recent.length})
              </summary>
              <ul className="divide-y divide-slate-100 text-[11px]">
                {info.recent.slice(0, 20).map((it) => (
                  <li key={it.id} className="px-3 py-1.5 flex items-center justify-between gap-2">
                    <span className="flex items-center gap-1.5 min-w-0">
                      <span className={`inline-block w-1.5 h-1.5 rounded-full ${it.ok ? "bg-emerald-500" : "bg-rose-500"}`}></span>
                      <span className="font-mono text-slate-500">{it.remote_ip || "—"}</span>
                      <span className="truncate text-slate-700">
                        {it.ok ? `${it.ticket_number} • ${it.title_preview}` : `❌ ${it.reason || "fail"}`}
                      </span>
                    </span>
                    <time className="text-slate-400 whitespace-nowrap">{new Date(it.created_at).toLocaleString("fr-FR")}</time>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      </div>

      {/* ============= Webhook Registre des Erreurs (Aizenta, Biolog, etc.) ============= */}
      <ErrorRegistryWebhookCard apiBase={apiBase} />
    </div>
  );
}

// =====================================================================
// Iter43 (2026-03) — Section dédiée au webhook /api/errors/ingest pour
// les logiciels métier (Aizenta, Biolog, etc.). Token Bearer + URL.
// =====================================================================
function ErrorRegistryWebhookCard({ apiBase }) {
  const [token, setToken] = useState("");
  const [original, setOriginal] = useState("");
  const [saving, setSaving] = useState(false);
  const [showToken, setShowToken] = useState(false);
  const [migrating, setMigrating] = useState(false);
  useEffect(() => {
    apiClient.get("/admin/settings").then((r) => {
      const t = r.data?.errors_webhook_token || "";
      setToken(t);
      setOriginal(t);
    }).catch(() => {});
  }, []);
  const dirty = token !== original;
  const saveToken = async () => {
    setSaving(true);
    try {
      await apiClient.put("/admin/settings", { errors_webhook_token: token });
      setOriginal(token);
      toast.success(token ? "Token enregistré" : "Token vidé (auth désactivée)");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    } finally { setSaving(false); }
  };
  const regenToken = () => {
    // génère un token aléatoire 32 bytes hex
    const bytes = new Uint8Array(32);
    (window.crypto || window.msCrypto).getRandomValues(bytes);
    const t = Array.from(bytes).map((b) => b.toString(16).padStart(2, "0")).join("");
    setToken(t);
    setShowToken(true);
  };
  const migrate = async () => {
    if (!window.confirm("Rapatrier les erreurs envoyées par erreur sur /api/public/incidents (support_tickets) vers le Registre des Erreurs (collection error_registry) ?\n\nIdempotent — peut être relancé sans risque.")) return;
    setMigrating(true);
    try {
      const r = await apiClient.post("/admin/error-registry/migrate-from-tickets");
      toast.success(`Migration OK : ${r.data.migrated} migrée(s) · ${r.data.skipped_already} déjà présente(s)`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur migration");
    } finally { setMigrating(false); }
  };
  const fullErrorsUrl = `${apiBase}/api/errors/ingest`;
  return (
    <div className="ring-1 ring-amber-200 rounded-lg p-4 bg-amber-50/30" data-testid="errors-webhook-card">
      <div className="flex items-start gap-3 mb-3">
        <div className={`h-10 w-10 rounded-xl flex items-center justify-center ${token ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-500"}`}>
          <AlertTriangle className="h-5 w-5" />
        </div>
        <div className="flex-1">
          <h3 className="font-semibold text-slate-900">Webhook entrant — Registre des Erreurs (logiciels métier)</h3>
          <p className="text-xs text-slate-600 mt-0.5">
            Pour <strong>Aizenta, Biolog</strong> et tout logiciel client qui pousse ses exceptions / erreurs.
            Endpoint distinct du webhook « Incidents serveur » ci-dessus.
            Accepte les formats <em>plat</em> ou imbriqué (<code className="text-[10px] bg-white px-1 rounded ring-1 ring-slate-200">{`{TicketDemnde:{...}}`}</code> Aizenta, <code className="text-[10px] bg-white px-1 rounded ring-1 ring-slate-200">{`{Erreur:{...}}`}</code> Biolog…).
          </p>
        </div>
        <span className={`text-[10px] uppercase tracking-wider font-medium px-2 py-1 rounded ring-1 self-start ${
          token ? "bg-amber-100 text-amber-800 ring-amber-300" : "bg-slate-100 text-slate-600 ring-slate-300"
        }`}>{token ? "Token actif" : "Pas d'auth"}</span>
      </div>

      <div className="space-y-3">
        <div className="bg-white ring-1 ring-slate-200 rounded p-3 text-xs space-y-2">
          <Field label="URL publique de l'endpoint">
            <div className="flex gap-2">
              <input readOnly value={fullErrorsUrl}
                     className="flex-1 px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono bg-slate-50 text-slate-700"
                     data-testid="errors-webhook-url" />
              <button onClick={() => { navigator.clipboard.writeText(fullErrorsUrl); toast.success("URL copiée"); }}
                      className="px-2 py-1.5 rounded ring-1 ring-slate-300 hover:bg-slate-50" data-testid="errors-webhook-copy-url">
                <Copy className="h-3 w-3" />
              </button>
            </div>
          </Field>
          <Field label={`Token Bearer (header Authorization: "Bearer <token>")${token ? "" : " — vide = pas d'auth (DÉCONSEILLÉ en production)"}`}>
            <div className="flex gap-2">
              <input value={token}
                     onChange={(e) => setToken(e.target.value)}
                     type={showToken ? "text" : "password"}
                     placeholder="(aucun token configuré)"
                     className="flex-1 px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono"
                     data-testid="errors-webhook-token-input" />
              <button onClick={() => setShowToken((v) => !v)}
                      className="px-2 py-1.5 rounded ring-1 ring-slate-300 hover:bg-slate-50 text-xs"
                      data-testid="errors-webhook-token-toggle">
                {showToken ? "Masquer" : "Afficher"}
              </button>
              <button onClick={regenToken}
                      className="px-2 py-1.5 rounded ring-1 ring-amber-300 bg-amber-100 text-amber-900 hover:bg-amber-200 inline-flex items-center gap-1"
                      data-testid="errors-webhook-token-regen">
                <RefreshCw className="h-3 w-3" /> Générer
              </button>
              <button onClick={saveToken} disabled={!dirty || saving}
                      className="px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-700 text-white inline-flex items-center gap-1 disabled:opacity-50"
                      data-testid="errors-webhook-token-save">
                {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />} Enregistrer
              </button>
            </div>
          </Field>
        </div>

        <details className="text-xs ring-1 ring-amber-200 rounded bg-white">
          <summary className="cursor-pointer px-3 py-2 font-medium text-amber-900 hover:bg-amber-50">
            💡 Exemple cURL (format Aizenta)
          </summary>
          <pre className="px-3 py-2 text-[10px] bg-slate-900 text-amber-100 overflow-x-auto rounded-b">
{`curl -X POST "${fullErrorsUrl}" \\
  -H "Authorization: Bearer ${token || "VOTRE_TOKEN"}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "TicketDemnde": {
      "Motif": "Erreur d écriture port 1",
      "CodeApplicatif": "WAB",
      "Code_Client": "AMY",
      "CompteClient": "Pharmacie X",
      "TypeTicket": "Erreur",
      "StatutEnCours": "exception"
    }
  }'`}
          </pre>
        </details>

        <div className="bg-sky-50 ring-1 ring-sky-200 rounded p-3">
          <div className="flex items-start gap-2">
            <RefreshCw className="h-4 w-4 text-sky-700 mt-0.5 flex-shrink-0" />
            <div className="flex-1">
              <p className="text-xs font-medium text-sky-900">Migration depuis le webhook Incidents</p>
              <p className="text-[11px] text-sky-800 mt-0.5">
                Si vous aviez configuré Aizenta par erreur sur <code className="bg-white px-1 rounded ring-1 ring-sky-300">/api/public/incidents</code>,
                vos erreurs sont allées dans la table des tickets de support.
                Ce bouton rebalance les entrées « webhook + metadata Aizenta » vers le Registre. <strong>Idempotent</strong>.
              </p>
            </div>
            <button onClick={migrate} disabled={migrating}
                    className="text-xs px-3 py-1.5 rounded bg-sky-600 hover:bg-sky-700 text-white inline-flex items-center gap-1 disabled:opacity-50 flex-shrink-0"
                    data-testid="errors-webhook-migrate-btn">
              {migrating ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
              {migrating ? "Migration…" : "Rapatrier"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <label className="block text-xs text-slate-600 mb-1">{label}</label>
      {children}
    </div>
  );
}
