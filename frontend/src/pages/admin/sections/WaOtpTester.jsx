// Iter38r-fix9o — Tester for WhatsApp OTP template (debug).
// Sends a real OTP to a phone number via /api/admin/wa-otp/test and shows
// the verbose Meta response so the admin can fix template issues quickly.
import React, { useState } from "react";
import { Send, AlertTriangle, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

export default function WaOtpTester() {
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  const test = async () => {
    const digits = phone.replace(/\D/g, "");
    if (digits.length < 8) {
      toast.error("Numéro invalide");
      return;
    }
    setBusy(true);
    setResult(null);
    try {
      const r = await apiClient.post("/admin/wa-otp/test", { msisdn: digits });
      setResult(r.data);
      if (r.data?.ok) toast.success(`OTP envoyé via ${r.data.sent_via}`);
      else toast.error("Échec — voir détails ci-dessous");
    } catch (err) {
      setResult({ ok: false, error: err?.response?.data?.detail || String(err) });
      toast.error("Erreur API");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-4 rounded-lg ring-1 ring-amber-200 bg-amber-50/60 p-3" data-testid="wa-otp-tester">
      <h5 className="text-xs font-semibold text-slate-700 mb-2 inline-flex items-center gap-2">
        <Send className="h-3.5 w-3.5 text-amber-700" />
        Tester l'envoi (envoie un vrai OTP à ce numéro)
      </h5>
      <div className="flex gap-2">
        <input
          type="tel"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          placeholder="+22670000000"
          className="flex-1 text-sm rounded-lg ring-1 ring-slate-300 px-2 py-1.5 font-mono"
          data-testid="wa-otp-test-phone"
        />
        <button
          type="button"
          onClick={test}
          disabled={busy}
          className="text-xs rounded-lg bg-amber-600 hover:bg-amber-700 text-white px-3 py-1.5 disabled:opacity-50 inline-flex items-center gap-1"
          data-testid="wa-otp-test-send"
        >
          <Send className="h-3 w-3" /> {busy ? "Envoi…" : "Tester"}
        </button>
      </div>

      {result && (
        <div className="mt-3 rounded-lg bg-white ring-1 ring-slate-200 p-2 text-xs" data-testid="wa-otp-test-result">
          <div className={`inline-flex items-center gap-1 font-semibold mb-1 ${result.ok ? "text-emerald-700" : "text-rose-700"}`}>
            {result.ok ? <CheckCircle2 className="h-3.5 w-3.5" /> : <AlertTriangle className="h-3.5 w-3.5" />}
            {result.ok ? `Envoyé via ${result.sent_via}` : "Échec"}
          </div>
          {result.test_code && (
            <p className="text-[11px] text-slate-600">Code généré (jamais affiché en prod réelle) : <code className="font-mono bg-slate-100 px-1 rounded">{result.test_code}</code></p>
          )}
          {result.hint && <p className="text-[11px] text-amber-800 mt-1">💡 {result.hint}</p>}
          {result.attempts && result.attempts.length > 0 && (
            <details className="mt-2">
              <summary className="text-[10px] cursor-pointer text-slate-500 hover:text-slate-700">Voir les détails Meta ({result.attempts.length} tentative{result.attempts.length > 1 ? "s" : ""})</summary>
              <pre className="mt-1 text-[10px] bg-slate-50 ring-1 ring-slate-200 rounded p-2 overflow-x-auto font-mono whitespace-pre-wrap break-all">
{JSON.stringify(result.attempts, null, 2)}
              </pre>
            </details>
          )}
          {result.error && (
            <p className="text-[11px] text-rose-700 mt-1 font-mono">{result.error}</p>
          )}
        </div>
      )}
    </div>
  );
}
