// =====================================================================
// Iter38d — Payroll Webhooks (n8n) admin section.
// Extracted from AdminSettings.jsx to keep it manageable.
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { Webhook } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const TITLE = "Webhooks Paie (n8n)";

const PayrollWebhooksSection = () => {
  const [cfg, setCfg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [revealed, setRevealed] = useState({ outbound: null, inbound: null });
  const [log, setLog] = useState([]);
  const [today] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  });
  const [month, setMonth] = useState(today);
  const [previewJson, setPreviewJson] = useState(null);

  const load = useCallback(async () => {
    try {
      const [c, l] = await Promise.all([
        apiClient.get("/admin/payroll-webhooks/config"),
        apiClient.get("/admin/payroll-webhooks/log?limit=20"),
      ]);
      setCfg(c.data);
      setLog(l.data || []);
    } catch (err) {
      toast.error("Erreur de chargement");
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const patch = async (updates) => {
    setBusy(true);
    try {
      const r = await apiClient.patch("/admin/payroll-webhooks/config", updates);
      setCfg(r.data);
      if (r.data.new_outbound_secret || r.data.new_inbound_secret) {
        setRevealed({
          outbound: r.data.new_outbound_secret || revealed.outbound,
          inbound: r.data.new_inbound_secret || revealed.inbound,
        });
      }
      toast.success("Configuration mise à jour");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setBusy(false); }
  };

  const preview = async () => {
    try {
      const r = await apiClient.get(`/admin/payroll-webhooks/outbound/preview?month=${month}`);
      setPreviewJson(r.data);
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const dispatchTest = async () => {
    setBusy(true);
    try {
      const r = await apiClient.post(`/admin/payroll-webhooks/outbound/test?month=${month}`);
      const disp = r.data?.dispatch || {};
      if (disp.ok) {
        toast.success(`Dispatch OK (HTTP ${disp.http_status})`);
      } else {
        toast.error(`Dispatch KO: ${disp.reason || disp.error || disp.http_status}`);
      }
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setBusy(false); }
  };

  if (!cfg) return null;

  return (
    <div id="s-webhooks-paie-n8n" className="scroll-mt-32" data-settings-anchor="s-webhooks-paie-n8n">
    <div className="rounded-xl border-2 border-indigo-300 bg-indigo-50/40 p-6 space-y-4" data-testid="admin-payroll-webhooks">
      <div className="flex items-center gap-2">
        <Webhook className="h-4 w-4 text-indigo-700" />
        <h2 className="font-display font-semibold">{TITLE}</h2>
      </div>
      <p className="text-sm text-slate-600">
        Synchronisez votre paie mensuelle avec <strong>n8n</strong> via 2 webhooks. <strong>Sortant</strong> :
        envoi automatique le 1er de chaque mois (03:00 UTC) du mois précédent. <strong>Entrant</strong> :
        n8n peut retourner des ajustements (net override, commentaire) signés en HMAC-SHA256
        avec anti-replay.
      </p>

      {/* OUTBOUND */}
      <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-3">
        <h3 className="text-sm font-semibold text-slate-800">Sortant — vers n8n</h3>
        <div>
          <label className="text-xs text-slate-500 mb-1 block">URL du webhook n8n</label>
          <input value={cfg.outbound_url || ""}
            onChange={(e) => setCfg({ ...cfg, outbound_url: e.target.value })}
            onBlur={() => patch({ outbound_url: cfg.outbound_url })}
            data-testid="webhook-outbound-url"
            placeholder="https://n8n.example.com/webhook/payroll"
            className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" />
        </div>
        <div className="flex flex-wrap gap-4">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={cfg.outbound_enabled}
              onChange={(e) => patch({ outbound_enabled: e.target.checked })}
              data-testid="webhook-outbound-enabled" />
            Activé
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={cfg.outbound_auto_monthly}
              onChange={(e) => patch({ outbound_auto_monthly: e.target.checked })}
              data-testid="webhook-outbound-auto" />
            Envoi automatique mensuel (CRON le 1er à 03:00 UTC)
          </label>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-500">Secret HMAC :</span>
          <code className="bg-slate-100 px-2 py-0.5 rounded font-mono">{cfg.outbound_secret_preview || "(non défini)"}</code>
          <button onClick={() => patch({ rotate_outbound_secret: true })}
            disabled={busy} data-testid="webhook-outbound-rotate"
            className="ml-1 text-xs text-indigo-600 hover:underline">
            Régénérer
          </button>
        </div>
        {revealed.outbound && (
          <div className="bg-amber-50 border border-amber-200 rounded p-2 text-xs" data-testid="webhook-outbound-revealed">
            <strong>Nouveau secret (à copier maintenant)</strong> :
            <code className="ml-2 font-mono break-all">{revealed.outbound}</code>
          </div>
        )}
        <div className="flex flex-wrap gap-2 pt-2 border-t border-slate-100">
          <input type="month" value={month} onChange={(e) => setMonth(e.target.value)}
            data-testid="webhook-test-month"
            className="px-2 py-1.5 border border-slate-200 rounded text-sm" />
          <button onClick={preview} data-testid="webhook-outbound-preview"
            className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm rounded">
            Aperçu JSON
          </button>
          <button onClick={dispatchTest} disabled={busy || !cfg.outbound_enabled || !cfg.outbound_url}
            data-testid="webhook-outbound-test"
            className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white text-sm rounded disabled:opacity-50">
            Envoyer maintenant
          </button>
        </div>
        {previewJson && (
          <pre className="bg-slate-900 text-emerald-200 text-xs p-3 rounded max-h-64 overflow-auto" data-testid="webhook-outbound-preview-json">
            {JSON.stringify(previewJson, null, 2)}
          </pre>
        )}
      </div>

      {/* INBOUND */}
      <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-3">
        <h3 className="text-sm font-semibold text-slate-800">Entrant — depuis n8n</h3>
        <p className="text-xs text-slate-500">
          URL à configurer côté n8n: <code className="bg-slate-100 px-2 py-0.5 rounded font-mono break-all">
          {`${window.location.origin}/api/webhooks/n8n/payroll/${cfg.tenant_id}`}</code>
        </p>
        <div className="flex flex-wrap gap-4">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={cfg.inbound_enabled}
              onChange={(e) => patch({ inbound_enabled: e.target.checked })}
              data-testid="webhook-inbound-enabled" />
            Activé
          </label>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-500">Secret HMAC :</span>
          <code className="bg-slate-100 px-2 py-0.5 rounded font-mono">{cfg.inbound_secret_preview || "(non défini)"}</code>
          <button onClick={() => patch({ rotate_inbound_secret: true })}
            disabled={busy} data-testid="webhook-inbound-rotate"
            className="ml-1 text-xs text-indigo-600 hover:underline">
            Régénérer
          </button>
        </div>
        {revealed.inbound && (
          <div className="bg-amber-50 border border-amber-200 rounded p-2 text-xs" data-testid="webhook-inbound-revealed">
            <strong>Nouveau secret (à copier maintenant)</strong> :
            <code className="ml-2 font-mono break-all">{revealed.inbound}</code>
          </div>
        )}
        <details className="text-xs text-slate-600">
          <summary className="cursor-pointer font-medium">Format attendu (HMAC-SHA256)</summary>
          <pre className="mt-2 bg-slate-50 p-2 rounded font-mono">{`POST /api/webhooks/n8n/payroll/{tenant_id}
Headers:
  Content-Type: application/json
  X-Sawali-Timestamp: 1700000000   (epoch seconds, fenêtre ±5 min)
  X-Sawali-Signature: sha256=HEX   (HMAC-SHA256 de "timestamp.body")
Body:
{"lines": [
  {"matricule": "MAT-XXXX-00001", "month": "2026-05", "net_override": 150000, "comment": "..."}
]}`}</pre>
        </details>
      </div>

      {/* LOG */}
      <div className="bg-white border border-slate-200 rounded-lg p-4">
        <h3 className="text-sm font-semibold text-slate-800 mb-2">Journal d'audit (20 dernières entrées)</h3>
        {log.length === 0 ? (
          <p className="text-xs text-slate-400 italic">Aucune entrée.</p>
        ) : (
          <div className="space-y-1 max-h-64 overflow-y-auto" data-testid="webhook-log-list">
            {log.map((l) => (
              <div key={l.id} className="text-xs grid grid-cols-12 gap-2 py-1 border-b border-slate-50">
                <span className="col-span-3 text-slate-500 font-mono">{(l.created_at || "").slice(0, 19).replace("T", " ")}</span>
                <span className={`col-span-2 font-medium ${l.direction === "outbound" ? "text-indigo-700" : "text-emerald-700"}`}>{l.direction}</span>
                <span className={`col-span-2 font-medium ${l.status === "ok" || l.status === "applied" ? "text-emerald-700" : "text-rose-700"}`}>{l.status}</span>
                <span className="col-span-5 text-slate-600 truncate">{JSON.stringify(l.payload).slice(0, 120)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
    </div>
  );
};

export default PayrollWebhooksSection;
