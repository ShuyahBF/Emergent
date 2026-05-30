// =====================================================================
// Iter38r-fix9o (P1) — Stripe Webhook config section.
// Lets admin paste the Stripe webhook signing secret + see the recent
// event log used to confirm orders without polling.
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { Webhook, Copy, Check, RotateCw } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const StripeWebhookSection = () => {
  const [settings, setSettings] = useState({ stripe_webhook_secret: "" });
  const [revealed, setRevealed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);

  const webhookUrl = `${window.location.origin}/api/webhook/stripe`;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, e] = await Promise.all([
        apiClient.get("/admin/settings"),
        apiClient.get("/admin/stripe/webhook-events?limit=10").catch(() => ({ data: { items: [] } })),
      ]);
      setSettings({
        stripe_webhook_secret: s.data?.stripe_webhook_secret || "",
      });
      setEvents(e.data?.items || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setBusy(true);
    try {
      await apiClient.put("/admin/settings", {
        stripe_webhook_secret: settings.stripe_webhook_secret || null,
      });
      toast.success("Secret enregistré");
      setRevealed(false);
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setBusy(false);
    }
  };

  const copyUrl = () => {
    try {
      navigator.clipboard.writeText(webhookUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {}
  };

  return (
    <section className="rounded-2xl ring-1 ring-indigo-200 bg-gradient-to-br from-indigo-50/40 via-white to-violet-50/30 p-5" data-testid="admin-stripe-webhook-section">
      <header className="flex items-center gap-3 mb-3">
        <div className="rounded-full bg-indigo-100 ring-1 ring-indigo-200 p-2">
          <Webhook className="h-5 w-5 text-indigo-700" />
        </div>
        <div>
          <h3 className="font-display font-bold text-slate-900">Webhook Stripe (confirmation paiement sans polling)</h3>
          <p className="text-xs text-slate-500 mt-0.5">
            Configurez le webhook dans Stripe pour recevoir les événements <code className="rounded bg-slate-100 px-1">checkout.session.completed</code> et finaliser les commandes instantanément.
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          className="ml-auto text-xs rounded-lg ring-1 ring-slate-300 px-2 py-1 hover:bg-slate-50 inline-flex items-center gap-1"
          data-testid="stripe-webhook-refresh"
        >
          <RotateCw className="h-3.5 w-3.5" /> Recharger
        </button>
      </header>

      <div className="space-y-3">
        <div className="rounded-xl bg-white ring-1 ring-indigo-100 p-3">
          <label className="text-[10px] uppercase tracking-wider text-slate-500">URL du webhook (à coller dans Stripe Dashboard → Développeurs → Webhooks)</label>
          <div className="mt-1 flex items-center gap-2">
            <code className="flex-1 text-xs font-mono bg-slate-50 ring-1 ring-slate-200 rounded px-2 py-1.5 break-all" data-testid="stripe-webhook-url">{webhookUrl}</code>
            <button
              type="button"
              onClick={copyUrl}
              className="text-xs rounded-lg ring-1 ring-indigo-300 px-2 py-1.5 hover:bg-indigo-50 inline-flex items-center gap-1"
              data-testid="stripe-webhook-url-copy"
            >
              {copied ? <><Check className="h-3 w-3 text-emerald-600" /> Copié</> : <><Copy className="h-3 w-3" /> Copier</>}
            </button>
          </div>
          <p className="text-[11px] text-slate-500 mt-2">
            Événements à activer : <strong>checkout.session.completed</strong> (minimum). Optionnels : <em>checkout.session.expired</em>, <em>payment_intent.payment_failed</em>.
          </p>
        </div>

        <div className="rounded-xl bg-white ring-1 ring-indigo-100 p-3">
          <label className="text-[10px] uppercase tracking-wider text-slate-500">Signing secret (whsec_…)</label>
          <div className="mt-1 flex items-center gap-2">
            <input
              type={revealed ? "text" : "password"}
              value={settings.stripe_webhook_secret || ""}
              onChange={(e) => setSettings({ ...settings, stripe_webhook_secret: e.target.value })}
              placeholder="whsec_xxxxxxxxxxxxxxxxxxxxxxxxxxxx"
              className="flex-1 text-sm font-mono rounded-lg ring-1 ring-slate-300 px-2 py-1.5"
              data-testid="stripe-webhook-secret-input"
            />
            <button
              type="button"
              onClick={() => setRevealed((v) => !v)}
              className="text-xs rounded-lg ring-1 ring-slate-300 px-2 py-1.5 hover:bg-slate-50"
              data-testid="stripe-webhook-secret-reveal"
            >
              {revealed ? "Masquer" : "Afficher"}
            </button>
            <button
              type="button"
              onClick={save}
              disabled={busy}
              className="text-xs rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white px-3 py-1.5 disabled:opacity-50"
              data-testid="stripe-webhook-secret-save"
            >
              {busy ? "…" : "Enregistrer"}
            </button>
          </div>
          <p className="text-[11px] text-slate-500 mt-2">
            Récupérable dans Stripe Dashboard après création du webhook. Sans secret, la signature n'est pas vérifiée et tout POST sera rejeté.
          </p>
        </div>

        <div className="rounded-xl bg-white ring-1 ring-indigo-100 p-3">
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-xs font-semibold text-slate-700 uppercase tracking-wider">Événements récents</h4>
            <span className="text-[10px] text-slate-500">{events.length} dernier(s)</span>
          </div>
          {loading ? (
            <p className="text-xs text-slate-500">Chargement…</p>
          ) : events.length === 0 ? (
            <p className="text-xs text-slate-500">Aucun événement reçu. Réalisez un paiement de test pour déclencher Stripe.</p>
          ) : (
            <ul className="space-y-1.5 text-xs" data-testid="stripe-webhook-events-list">
              {events.map((ev) => (
                <li key={ev.id} className="flex items-center gap-2 rounded-lg ring-1 ring-slate-100 bg-slate-50/60 px-2 py-1">
                  <span className={`inline-block rounded-full px-1.5 py-0.5 text-[10px] font-mono ${ev.payment_status === "paid" ? "bg-emerald-100 text-emerald-800 ring-1 ring-emerald-200" : "bg-slate-100 text-slate-700 ring-1 ring-slate-200"}`}>
                    {ev.payment_status || ev.event_type || "—"}
                  </span>
                  <span className="font-mono text-[10px] text-slate-600 truncate flex-1">{ev.event_type}</span>
                  <span className="text-[10px] text-slate-500">{ev.received_at ? new Date(ev.received_at).toLocaleString("fr-FR") : ""}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
};

export default StripeWebhookSection;
