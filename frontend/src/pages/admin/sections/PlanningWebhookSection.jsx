/*
 * Iter43-fix24az-m + n (2026-07-18) — Section AdminSettings pour configurer
 * l'URL webhook Planning (RDV patients) + le template WA de rappel 1h avant.
 */
import React, { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Copy, RefreshCw, Loader2, Webhook, ClipboardCheck, MessageCircle, Play } from "lucide-react";

const DEFAULT_TEMPLATE = "Bonjour {patient}, rappel : votre rendez-vous avec {medecin} est prévu à {start_time}. Motif : {motif}. Merci de vous présenter 10 minutes en avance. — SAWALI";

export default function PlanningWebhookSection() {
  const [cfg, setCfg] = useState(null);
  const [loading, setLoading] = useState(true);
  const [regenerating, setRegenerating] = useState(false);
  const [copied, setCopied] = useState(false);
  const [template, setTemplate] = useState("");
  const [savingTpl, setSavingTpl] = useState(false);
  const [runningCron, setRunningCron] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const c = await apiClient.get("/admin/planning/config");
      setCfg(c.data);
      setTemplate(c.data?.reminder_template || "");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Impossible de charger la config");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const copyUrl = async () => {
    if (!cfg?.webhook_url) return;
    try {
      await navigator.clipboard.writeText(cfg.webhook_url);
      setCopied(true);
      toast.success("URL du webhook copiée");
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      toast.error("Impossible de copier — veuillez copier manuellement");
    }
  };

  const regenerate = async () => {
    if (!window.confirm("Régénérer le secret invalide le webhook précédent. Continuer ?")) return;
    setRegenerating(true);
    try {
      const r = await apiClient.put("/admin/planning/config", { regenerate: true });
      setCfg((c) => ({ ...(c || {}), planning_webhook_secret: r.data.planning_webhook_secret, webhook_url: r.data.webhook_url }));
      toast.success("Nouveau secret généré");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur de régénération");
    } finally {
      setRegenerating(false);
    }
  };

  return (
    <section className="bg-white rounded-2xl border border-slate-200 p-6 space-y-4" data-testid="planning-webhook-section">
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-lg bg-sky-100 flex items-center justify-center shrink-0">
          <Webhook className="h-5 w-5 text-sky-700" />
        </div>
        <div className="flex-1">
          <h2 className="text-base font-semibold text-slate-800">Webhook Planning consultations</h2>
          <p className="text-sm text-slate-500 mt-0.5">
            URL à configurer chez votre système externe (clinique, calendrier) pour recevoir en temps réel
            les rendez-vous patients. Payload JSON attendu : <code className="text-xs bg-slate-100 px-1 py-0.5 rounded">
            {"{code_clinique, medecin, patient, start, end, motif, id_user}"}
            </code>. Aucun mot de passe n'est requis — la sécurité repose sur le secret dans l'URL.
          </p>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-slate-500 text-sm py-3">
          <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
        </div>
      ) : (
        <>
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">
              URL du webhook (à copier chez votre prestataire)
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                readOnly
                value={cfg?.webhook_url || ""}
                className="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono bg-slate-50"
                data-testid="planning-webhook-url"
              />
              <button
                type="button"
                onClick={copyUrl}
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-sky-600 hover:bg-sky-700 text-white text-sm"
                data-testid="planning-webhook-copy-btn"
              >
                {copied ? <ClipboardCheck className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                {copied ? "Copié" : "Copier"}
              </button>
              <button
                type="button"
                onClick={regenerate}
                disabled={regenerating}
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-amber-100 hover:bg-amber-200 text-amber-800 text-sm disabled:opacity-50"
                data-testid="planning-webhook-regenerate-btn"
                title="Régénérer un nouveau secret (invalide l'ancien)"
              >
                {regenerating ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                Régénérer
              </button>
            </div>
          </div>

          <details className="bg-slate-50 rounded-lg border border-slate-200 p-3">
            <summary className="text-sm font-medium text-slate-700 cursor-pointer">
              Exemple de requête (à tester avec curl)
            </summary>
            <pre className="mt-3 text-[11px] bg-slate-900 text-slate-100 p-3 rounded-lg overflow-x-auto" data-testid="planning-webhook-example">
{`curl -X POST "${cfg?.webhook_url || "…"}" \\
  -H "Content-Type: application/json" \\
  -d '${JSON.stringify(cfg?.sample_payload || {}, null, 2)}'`}
            </pre>
          </details>

          <div className="text-xs text-slate-500 space-y-1">
            <p><strong>Sécurité</strong> : Le secret dans l'URL agit comme un jeton. Traitez-le comme un mot de passe.</p>
            <p><strong>Idempotence</strong> : Envoyer plusieurs fois le même RDV met simplement à jour l'existant (upsert sur code_clinique + médecin + patient + heure début).</p>
            <p><strong>Rôle Médecin</strong> : Créez des utilisateurs suivis avec le rôle "Médecin" pour que le champ <code>medecin_email</code> soit routé automatiquement dans leur planning.</p>
            <p><strong>Rappels WA</strong> : Ajoutez le champ <code>patient_phone</code> (format E.164, ex: <code>+22670001122</code>) dans le payload pour activer les rappels WhatsApp automatiques 1h avant chaque RDV.</p>
          </div>

          {/* Iter43-fix24az-n — Template de rappel WA */}
          <div className="pt-4 border-t border-slate-200 space-y-3">
            <div className="flex items-start gap-3">
              <div className="w-9 h-9 rounded-lg bg-emerald-100 flex items-center justify-center shrink-0">
                <MessageCircle className="h-4 w-4 text-emerald-700" />
              </div>
              <div className="flex-1">
                <h3 className="text-sm font-semibold text-slate-800">Rappel WhatsApp 1h avant RDV</h3>
                <p className="text-xs text-slate-500">
                  Un cron toutes les 5 minutes envoie ce message WA au patient si <code>patient_phone</code> est fourni.
                  Placeholders : <code className="bg-slate-100 px-1 rounded">{"{patient}"}</code>,{" "}
                  <code className="bg-slate-100 px-1 rounded">{"{medecin}"}</code>,{" "}
                  <code className="bg-slate-100 px-1 rounded">{"{start_time}"}</code>,{" "}
                  <code className="bg-slate-100 px-1 rounded">{"{motif}"}</code>.
                </p>
              </div>
            </div>
            <textarea
              value={template}
              onChange={(e) => setTemplate(e.target.value)}
              rows={4}
              placeholder={DEFAULT_TEMPLATE}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono"
              data-testid="planning-reminder-template"
            />
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={async () => {
                  setSavingTpl(true);
                  try {
                    await apiClient.put("/admin/planning/config", { reminder_template: template });
                    toast.success("Template sauvegardé");
                  } catch (e) {
                    toast.error(e?.response?.data?.detail || "Erreur sauvegarde");
                  } finally {
                    setSavingTpl(false);
                  }
                }}
                disabled={savingTpl}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm disabled:opacity-50"
                data-testid="planning-reminder-save-btn"
              >
                {savingTpl ? <Loader2 className="h-4 w-4 animate-spin" /> : <ClipboardCheck className="h-4 w-4" />}
                Enregistrer le template
              </button>
              <button
                type="button"
                onClick={async () => {
                  setRunningCron(true);
                  try {
                    const r = await apiClient.post("/admin/planning/reminders/run");
                    const d = r.data || {};
                    toast.success(`Rappels envoyés : ${d.sent ?? 0} (skipped ${d.skipped ?? 0})`);
                  } catch (e) {
                    toast.error(e?.response?.data?.detail || "Erreur cron");
                  } finally {
                    setRunningCron(false);
                  }
                }}
                disabled={runningCron}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white border border-slate-300 hover:bg-slate-50 text-sm text-slate-700 disabled:opacity-50"
                data-testid="planning-reminder-run-now-btn"
                title="Déclenche immédiatement le cron des rappels (utile pour tester)"
              >
                {runningCron ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                Lancer maintenant
              </button>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
