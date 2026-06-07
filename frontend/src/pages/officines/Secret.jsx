// Iter42 — Officine portal: HMAC Secret regeneration (one-shot display)
import React from "react";
import { toast } from "sonner";
import { officineApi } from "@/lib/officineApi";
import { KeyRound, Copy, AlertTriangle, ShieldCheck } from "lucide-react";

export default function OfficineSecret() {
  const [secret, setSecret] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [confirmed, setConfirmed] = React.useState(false);

  const regenerate = async () => {
    if (!confirmed) {
      toast.error("Veuillez confirmer que vous comprenez les risques");
      return;
    }
    if (!window.confirm("Confirmer la régénération ? L'ancienne clé sera révoquée immédiatement.")) return;
    setBusy(true);
    try {
      const r = await officineApi.post("/officines-portal/me/regenerate-secret");
      setSecret(r.data.secret);
      toast.success("Nouvelle clé générée — copiez-la maintenant");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec");
    } finally { setBusy(false); }
  };

  const copy = () => {
    if (!secret) return;
    navigator.clipboard.writeText(secret);
    toast.success("Copié dans le presse-papier");
  };

  return (
    <div className="max-w-3xl space-y-5" data-testid="officine-secret-page">
      <div>
        <h1 className="text-xl font-display font-bold text-slate-900">Clé HMAC API</h1>
        <p className="text-sm text-slate-600 mt-1">
          Cette clé permet de signer les requêtes envoyées à l&apos;API publique{" "}
          <code className="text-xs bg-slate-100 px-1.5 py-0.5 rounded">/api/public/officines/register</code>
          {" "}depuis vos systèmes (script CRON, ERP officine, etc.).
        </p>
      </div>

      <div className="bg-amber-50 ring-1 ring-amber-200 rounded-xl p-4 text-sm text-amber-900">
        <div className="flex gap-2">
          <AlertTriangle className="h-5 w-5 flex-shrink-0" />
          <div>
            <p className="font-medium">Important</p>
            <ul className="mt-1 list-disc list-inside space-y-1 text-xs">
              <li>La régénération <strong>révoque immédiatement</strong> votre ancienne clé.</li>
              <li>La nouvelle clé ne sera <strong>affichée qu&apos;une seule fois</strong> — copiez-la.</li>
              <li>Si vous la perdez, vous devrez en régénérer une nouvelle.</li>
              <li>Ne partagez cette clé qu&apos;avec des systèmes de confiance.</li>
            </ul>
          </div>
        </div>
      </div>

      {!secret && (
        <div className="bg-white rounded-xl ring-1 ring-slate-200 p-5 space-y-4">
          <label className="flex items-start gap-2 cursor-pointer">
            <input
              type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)}
              className="mt-1" data-testid="secret-confirm-checkbox"
            />
            <span className="text-sm text-slate-700">
              Je comprends que la régénération révoquera ma clé actuelle et que la nouvelle clé ne sera affichée qu&apos;une seule fois.
            </span>
          </label>
          <button
            onClick={regenerate}
            disabled={busy || !confirmed}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-rose-600 hover:bg-rose-700 text-white font-medium disabled:opacity-50 transition"
            data-testid="secret-regenerate-btn"
          >
            <KeyRound className="h-4 w-4" />
            {busy ? "Génération…" : "Régénérer ma clé HMAC"}
          </button>
        </div>
      )}

      {secret && (
        <div className="bg-emerald-50 ring-2 ring-emerald-300 rounded-xl p-5" data-testid="secret-display">
          <div className="flex items-start gap-3">
            <ShieldCheck className="h-6 w-6 text-emerald-600 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="font-display font-semibold text-emerald-900">Nouvelle clé HMAC générée</p>
              <p className="text-xs text-emerald-800 mt-1">
                ⚠️ Cette clé ne sera plus jamais affichée. Copiez-la maintenant.
              </p>
              <div className="mt-3 flex items-center gap-2">
                <code className="flex-1 break-all text-xs bg-white border border-emerald-200 rounded px-3 py-2 font-mono" data-testid="secret-value">
                  {secret}
                </code>
                <button
                  onClick={copy}
                  className="inline-flex items-center gap-1 text-xs px-3 py-2 rounded bg-emerald-600 text-white hover:bg-emerald-700"
                  data-testid="secret-copy-btn"
                >
                  <Copy className="h-3.5 w-3.5" /> Copier
                </button>
              </div>
              <button
                onClick={() => { setSecret(null); setConfirmed(false); }}
                className="mt-4 text-xs text-emerald-700 hover:underline"
                data-testid="secret-done-btn"
              >
                ✓ J&apos;ai sauvegardé la clé en lieu sûr
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="bg-white rounded-xl ring-1 ring-slate-200 p-5">
        <h2 className="font-display font-semibold text-slate-900 text-sm">Exemple d&apos;utilisation</h2>
        <pre className="mt-2 text-[11px] bg-slate-900 text-emerald-200 p-3 rounded overflow-x-auto" data-testid="secret-example-code">
{`# Python — signer une requête /api/public/officines/register
import time, hmac, hashlib, json, requests

SECRET = b"VOTRE_CLE_HMAC"        # la clé régénérée ici
OFFICINE_ID = "votre_officine_id"  # voir tableau de bord
body = json.dumps({
    "officine_name": "Pharmacie X",
    "inventory": [{"product_name": "Doliprane", "stock_qty": 50}],
})
ts = str(int(time.time()))
sig = hmac.new(SECRET, f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
r = requests.post(
    "https://votre-domaine.com/api/public/officines/register",
    headers={
        "Content-Type": "application/json",
        "X-Officine-Id": OFFICINE_ID,
        "X-Timestamp": ts,
        "X-Signature": sig,
    }, data=body,
)
print(r.status_code, r.text)`}
        </pre>
      </div>
    </div>
  );
}
