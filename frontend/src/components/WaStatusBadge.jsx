/*
 * Iter38e (B.1) — WhatsApp send result indicator badge.
 *
 * Displays the result of the last WhatsApp dispatch for a receipt/invoice:
 *   - "OK — Envoyé à {to} le {date}"            (green)
 *   - "KO — Dernier échec : {error}"            (red)
 *
 * Reads these optional fields on the doc:
 *   whatsapp_last_status: "ok" | "ko" | undefined
 *   whatsapp_last_to: E.164 phone
 *   whatsapp_last_attempt_at: ISO timestamp
 *   whatsapp_last_error: short message (only on ko)
 *   whatsapp_sent_at: legacy success timestamp (used when last_status absent)
 *   whatsapp_to: legacy success recipient
 */
import React from "react";
import { CheckCircle2, AlertTriangle } from "lucide-react";

const fmtDate = (iso) => {
  if (!iso) return "";
  try { return new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }); }
  catch { return iso; }
};

export default function WaStatusBadge({ doc }) {
  if (!doc) return null;
  const status = doc.whatsapp_last_status;
  const lastAt = doc.whatsapp_last_attempt_at || doc.whatsapp_sent_at;
  const to = doc.whatsapp_last_to || doc.whatsapp_to;

  // Nothing to display if no attempt ever made
  if (!status && !doc.whatsapp_sent_at) return null;

  if (status === "ko") {
    return (
      <span
        title={`Dernier échec : ${doc.whatsapp_last_error || "Échec WhatsApp"}\nLe ${fmtDate(lastAt)}`}
        className="inline-flex items-center gap-1 rounded-full bg-rose-50 text-rose-700 ring-1 ring-rose-200 px-2 py-1 text-xs font-medium max-w-[280px]"
        data-testid="wa-status-badge-ko"
      >
        <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate">KO — {(doc.whatsapp_last_error || "Échec WhatsApp").slice(0, 60)}</span>
      </span>
    );
  }

  // Either status === "ok" OR legacy whatsapp_sent_at present
  return (
    <span
      title={to ? `Envoyé à ${to} le ${fmtDate(lastAt)}` : "Envoyé"}
      className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 px-2 py-1 text-xs font-medium"
      data-testid="wa-status-badge-ok"
    >
      <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
      <span className="truncate">Envoyé{to ? ` → ${to}` : ""} ({fmtDate(lastAt)})</span>
    </span>
  );
}
