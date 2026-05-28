import React, { useEffect, useMemo, useState, useCallback } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  CreditCard, Plus, RefreshCw, X, CheckCircle2, Clock, AlertCircle, Wallet,
  Download, Filter, Send, TrendingUp, Link2, Receipt, BarChart3,
} from "lucide-react";
import MyPaymentLinks from "./MyPaymentLinks";
import PaymentsDashboard from "./PaymentsDashboard";

/*
  Portal → Mes paiements (PawaPay Mobile Money).
  v1 features : déposit + historique + relance échec + filtres + export CSV.
*/
const MNO_LABELS = {
  ORANGE: { label: "Orange Money", color: "#FF7900" },
  MOOV: { label: "Moov Money", color: "#0076BB" },
  TELECEL: { label: "Telecel Cash", color: "#E2241A" },
};

const STATUS_BADGE = {
  pending: { cls: "bg-amber-100 text-amber-800 ring-amber-200", icon: Clock, label: "En attente" },
  completed: { cls: "bg-emerald-100 text-emerald-800 ring-emerald-200", icon: CheckCircle2, label: "Complété" },
  failed: { cls: "bg-rose-100 text-rose-800 ring-rose-200", icon: AlertCircle, label: "Échec" },
};

function fmtAmount(n, ccy = "XOF") {
  if (n == null) return "—";
  const v = Number(n);
  return `${v.toLocaleString("fr-FR")} ${ccy}`;
}
function fmtDate(d) {
  if (!d) return "—";
  try {
    return new Date(d).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
  } catch { return d; }
}

// Safely coerce any value (incl. PawaPay rejection objects) to a printable string.
// Without this, rendering `{p.api_message}` when api_message is `{rejectionCode, rejectionMessage}`
// would crash React with "Objects are not valid as a React child".
function safeText(v) {
  if (v == null) return "";
  if (typeof v === "string" || typeof v === "number") return String(v);
  if (typeof v === "object") {
    const code = v.failureCode || v.rejectionCode || v.code;
    const msg = v.failureMessage || v.rejectionMessage || v.message || v.detail;
    if (code && msg) return `${code} — ${msg}`;
    if (msg) return String(msg);
    if (code) return String(code);
    try { return JSON.stringify(v).slice(0, 200); } catch { return ""; }
  }
  return String(v);
}

export default function MyPayments() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [features, setFeatures] = useState({});
  const [mnos, setMnos] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const [resendPrefill, setResendPrefill] = useState(null);
  const [tab, setTab] = useState("dashboard"); // dashboard | transactions | links

  // Filters
  const [statusFilter, setStatusFilter] = useState("all"); // all|pending|completed|failed
  const [mnoFilter, setMnoFilter] = useState("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/me/payments");
      setItems(r.data || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    apiClient.get("/me/features").then((r) => {
      setFeatures(r.data?.features || {});
      setMnos(r.data?.pawapay_mnos || []);
    }).catch(() => {});
  }, [load]);

  // Auto-refresh pending rows every 20s
  useEffect(() => {
    const hasPending = items.some((p) => p.status === "pending");
    if (!hasPending) return;
    const t = setInterval(() => {
      items.filter((p) => p.status === "pending").slice(0, 5).forEach((p) => {
        apiClient.get(`/me/payments/${p.deposit_id}`).then((r) => {
          setItems((prev) => prev.map((x) => (x.deposit_id === p.deposit_id ? r.data : x)));
        }).catch(() => {});
      });
    }, 20000);
    return () => clearInterval(t);
  }, [items]);

  const refreshOne = async (deposit_id) => {
    try {
      const r = await apiClient.get(`/me/payments/${deposit_id}`);
      setItems((prev) => prev.map((p) => (p.deposit_id === deposit_id ? r.data : p)));
      toast.success("Statut actualisé");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const handleResend = (p) => {
    setResendPrefill({
      amount: String(p.amount || ""),
      msisdn: p.msisdn || "",
      mno: p.mno || (mnos[0] || "ORANGE"),
      description: p.description || "",
    });
    setShowModal(true);
  };

  // Filtered list
  const filtered = useMemo(() => {
    let arr = items;
    if (statusFilter !== "all") arr = arr.filter((p) => p.status === statusFilter);
    if (mnoFilter !== "all") arr = arr.filter((p) => (p.mno || "").toUpperCase() === mnoFilter);
    if (dateFrom) {
      const tFrom = new Date(dateFrom).getTime();
      arr = arr.filter((p) => new Date(p.created_at).getTime() >= tFrom);
    }
    if (dateTo) {
      const tTo = new Date(dateTo).getTime() + 24 * 3600 * 1000 - 1; // inclusive end-of-day
      arr = arr.filter((p) => new Date(p.created_at).getTime() <= tTo);
    }
    return arr;
  }, [items, statusFilter, mnoFilter, dateFrom, dateTo]);

  // KPIs (computed on filtered to reflect what user sees)
  const kpis = useMemo(() => {
    const sumIf = (s) => filtered.filter((p) => p.status === s).reduce((a, p) => a + Number(p.amount || 0), 0);
    return {
      completed_count: filtered.filter((p) => p.status === "completed").length,
      completed_total: sumIf("completed"),
      pending_count: filtered.filter((p) => p.status === "pending").length,
      pending_total: sumIf("pending"),
      failed_count: filtered.filter((p) => p.status === "failed").length,
      total_count: filtered.length,
    };
  }, [filtered]);

  const exportCSV = () => {
    const header = ["Date", "Référence", "Opérateur", "Numéro", "Montant", "Devise", "Statut", "Description", "Message API"];
    const rows = filtered.map((p) => [
      p.created_at || "",
      p.deposit_id || "",
      p.mno || "",
      p.msisdn || "",
      p.amount ?? "",
      p.currency || "XOF",
      STATUS_BADGE[p.status]?.label || p.status || "",
      (p.description || "").replace(/"/g, '""'),
      (p.api_message || "").replace(/"/g, '""'),
    ]);
    const csv = [header, ...rows].map((r) => r.map((c) => `"${c}"`).join(";")).join("\r\n");
    // BOM UTF-8 pour Excel FR
    const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `paiements_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a); a.click();
    a.remove(); URL.revokeObjectURL(url);
  };

  const resetFilters = () => {
    setStatusFilter("all"); setMnoFilter("all"); setDateFrom(""); setDateTo("");
  };
  const filtersActive = statusFilter !== "all" || mnoFilter !== "all" || !!dateFrom || !!dateTo;

  return (
    <div className="space-y-6 max-w-full" data-testid="my-payments-page">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-display font-bold inline-flex items-center gap-2">
            <Wallet className="h-7 w-7 text-amber-600" /> Mes paiements
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Encaissements via Mobile Money (PawaPay) — Burkina Faso.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={load} className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50" data-testid="payments-refresh">
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Actualiser
          </button>
          <button onClick={exportCSV} disabled={!filtered.length} className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-40" data-testid="payments-export-csv">
            <Download className="h-4 w-4" /> Export CSV
          </button>
          <button
            onClick={() => {
              try {
                // Diagnostic — fire-and-forget breadcrumb to backend so we can debug prod-only crashes
                apiClient.post("/me/api-trace", {
                  method: "CLIENT_DEBUG", url: "/portal/payments#new-payment-click", status: 0,
                  module: "payments-new-btn",
                  request_body: { features, mnos_len: (mnos || []).length, items_len: (items || []).length, tab },
                }).catch(() => {});
                if (!features.payments) { toast.error("Paiements non activés pour votre compte"); return; }
                if (!mnos || mnos.length === 0) { toast.error("Aucun opérateur Mobile Money autorisé"); return; }
                setResendPrefill(null);
                setShowModal(true);
              } catch (err) {
                toast.error("Erreur : " + (err?.message || err));
                apiClient.post("/me/api-trace", {
                  method: "CLIENT_ERROR", url: "/portal/payments#new-payment-click", status: 0,
                  module: "payments-new-btn-crash", error: String(err?.message || err),
                  response_body: { stack: String(err?.stack || "").slice(0, 1500) },
                }).catch(() => {});
              }
            }}
            disabled={!features.payments || mnos.length === 0}
            className="inline-flex items-center gap-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white px-4 py-2 text-sm disabled:opacity-40 disabled:cursor-not-allowed"
            data-testid="payments-new-btn"
          >
            <Plus className="h-4 w-4" /> Nouveau paiement
          </button>
        </div>
      </div>

      {!features.payments && (
        <div className="rounded-lg ring-1 ring-amber-200 bg-amber-50 p-3 text-xs text-amber-900" data-testid="payments-disabled-banner">
          La fonctionnalité Paiements n'est pas activée pour votre compte. Contactez votre administrateur.
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b border-slate-200" data-testid="payments-tabs">
        <button
          onClick={() => setTab("dashboard")}
          className={`inline-flex items-center gap-1.5 px-4 py-2 text-sm border-b-2 -mb-px ${tab === "dashboard" ? "border-amber-600 text-amber-700 font-semibold" : "border-transparent text-slate-500 hover:text-slate-700"}`}
          data-testid="tab-dashboard"
        >
          <BarChart3 className="h-4 w-4" /> Dashboard 360°
        </button>
        <button
          onClick={() => setTab("transactions")}
          className={`inline-flex items-center gap-1.5 px-4 py-2 text-sm border-b-2 -mb-px ${tab === "transactions" ? "border-amber-600 text-amber-700 font-semibold" : "border-transparent text-slate-500 hover:text-slate-700"}`}
          data-testid="tab-transactions"
        >
          <Receipt className="h-4 w-4" /> Transactions ({items.length})
        </button>
        <button
          onClick={() => setTab("links")}
          className={`inline-flex items-center gap-1.5 px-4 py-2 text-sm border-b-2 -mb-px ${tab === "links" ? "border-amber-600 text-amber-700 font-semibold" : "border-transparent text-slate-500 hover:text-slate-700"}`}
          data-testid="tab-links"
        >
          <Link2 className="h-4 w-4" /> Liens de paiement
        </button>
      </div>

      {tab === "dashboard" ? (
        <PaymentsDashboard />
      ) : tab === "links" ? (
        <MyPaymentLinks features={features} mnos={mnos} />
      ) : (
        <TransactionsPanel
          items={items}
          loading={loading}
          filtered={filtered}
          kpis={kpis}
          statusFilter={statusFilter} setStatusFilter={setStatusFilter}
          mnoFilter={mnoFilter} setMnoFilter={setMnoFilter}
          dateFrom={dateFrom} setDateFrom={setDateFrom}
          dateTo={dateTo} setDateTo={setDateTo}
          filtersActive={filtersActive} resetFilters={resetFilters}
          refreshOne={refreshOne} handleResend={handleResend}
          features={features} mnosLen={mnos.length}
        />
      )}

      {showModal && (
        <NewPaymentModal
          mnos={mnos}
          prefill={resendPrefill}
          onClose={() => { setShowModal(false); setResendPrefill(null); }}
          onCreated={load}
        />
      )}
    </div>
  );
}

function TransactionsPanel({
  items, loading, filtered, kpis,
  statusFilter, setStatusFilter, mnoFilter, setMnoFilter,
  dateFrom, setDateFrom, dateTo, setDateTo,
  filtersActive, resetFilters, refreshOne, handleResend, features, mnosLen,
}) {
  return (
    <>
      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Complétés" value={kpis.completed_count} sub={fmtAmount(kpis.completed_total)} tone="emerald" icon={CheckCircle2} testid="kpi-completed" />
        <KpiCard label="En attente" value={kpis.pending_count} sub={fmtAmount(kpis.pending_total)} tone="amber" icon={Clock} testid="kpi-pending" />
        <KpiCard label="Échoués" value={kpis.failed_count} sub="—" tone="rose" icon={AlertCircle} testid="kpi-failed" />
        <KpiCard label="Total transactions" value={kpis.total_count} sub={`${items.length} au total`} tone="slate" icon={TrendingUp} testid="kpi-total" />
      </div>

      {/* Filters */}
      <div className="rounded-xl ring-1 ring-slate-200 bg-white p-3 flex flex-wrap items-end gap-3 mt-4" data-testid="payments-filters">
        <div className="flex items-center gap-1 text-xs text-slate-500 mr-2 self-center">
          <Filter className="h-3.5 w-3.5" /> Filtres
        </div>
        <Field label="Statut">
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="rounded-md ring-1 ring-slate-300 px-2 py-1 text-sm bg-white" data-testid="filter-status">
            <option value="all">Tous</option>
            <option value="pending">En attente</option>
            <option value="completed">Complétés</option>
            <option value="failed">Échoués</option>
          </select>
        </Field>
        <Field label="Opérateur">
          <select value={mnoFilter} onChange={(e) => setMnoFilter(e.target.value)} className="rounded-md ring-1 ring-slate-300 px-2 py-1 text-sm bg-white" data-testid="filter-mno">
            <option value="all">Tous</option>
            {Object.keys(MNO_LABELS).map((m) => <option key={m} value={m}>{MNO_LABELS[m].label}</option>)}
          </select>
        </Field>
        <Field label="Du">
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="rounded-md ring-1 ring-slate-300 px-2 py-1 text-sm bg-white" data-testid="filter-date-from" />
        </Field>
        <Field label="Au">
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="rounded-md ring-1 ring-slate-300 px-2 py-1 text-sm bg-white" data-testid="filter-date-to" />
        </Field>
        {filtersActive && (
          <button onClick={resetFilters} className="text-xs text-rose-700 hover:underline" data-testid="filter-reset">
            Réinitialiser
          </button>
        )}
      </div>

      {/* Table */}
      <div className="rounded-xl ring-1 ring-slate-200 bg-white overflow-hidden mt-4">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-500 uppercase text-[10px]">
              <tr>
                <th className="text-left px-3 py-2">Date</th>
                <th className="text-left px-3 py-2 hidden lg:table-cell">Référence</th>
                <th className="text-left px-3 py-2 hidden sm:table-cell">Opérateur</th>
                <th className="text-left px-3 py-2 hidden md:table-cell">Numéro</th>
                <th className="text-left px-3 py-2 hidden lg:table-cell">Motif</th>
                <th className="text-right px-3 py-2">Montant</th>
                <th className="text-left px-3 py-2">Statut</th>
                <th className="text-right px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {loading && items.length === 0 && (
                <tr><td colSpan={8} className="px-3 py-6 text-center text-slate-400 italic">Chargement…</td></tr>
              )}
              {!loading && filtered.length === 0 && items.length > 0 && (
                <tr><td colSpan={8} className="px-3 py-6 text-center text-slate-400 italic">Aucun paiement ne correspond à ces filtres.</td></tr>
              )}
              {!loading && items.length === 0 && (
                <tr><td colSpan={8} className="px-3 py-6 text-center text-slate-400 italic">Aucun paiement pour l'instant. Cliquez sur « Nouveau paiement » pour démarrer.</td></tr>
              )}
              {filtered.map((p) => {
                const sb = STATUS_BADGE[p.status] || STATUS_BADGE.pending;
                const Icon = sb.icon;
                const mno = MNO_LABELS[p.mno] || (p.mno ? { label: p.mno, color: "#64748b" } : { label: "—", color: "#94a3b8" });
                const motif = p.description || p.reason || "—";
                return (
                  <tr key={p.deposit_id} className="border-t border-slate-100 hover:bg-slate-50" data-testid={`payment-row-${p.deposit_id}`}>
                    <td className="px-3 py-2 text-slate-600 whitespace-nowrap text-xs">
                      <div>{fmtDate(p.created_at)}</div>
                      {/* Mobile-only context: opérateur + numéro + motif */}
                      <div className="sm:hidden text-[10px] mt-0.5" style={{ color: mno.color }} data-testid={`payment-mobile-mno-${p.deposit_id}`}>{mno.label}</div>
                      <div className="md:hidden text-[10px] font-mono text-slate-400 mt-0.5">{p.msisdn || "—"}</div>
                      {motif !== "—" && <div className="lg:hidden text-[10px] text-slate-500 mt-0.5 max-w-[140px] truncate" title={motif}>{motif}</div>}
                    </td>
                    <td className="px-3 py-2 hidden lg:table-cell font-mono text-[10px] text-slate-700" title={p.deposit_id}>{p.deposit_id?.slice(0, 8)}…</td>
                    <td className="px-3 py-2 hidden sm:table-cell" data-testid={`payment-mno-${p.deposit_id}`}><span className="text-[11px] font-semibold" style={{ color: mno.color }}>{mno.label}</span></td>
                    <td className="px-3 py-2 hidden md:table-cell font-mono text-xs text-slate-700">{p.msisdn || "—"}</td>
                    <td className="px-3 py-2 hidden lg:table-cell text-xs text-slate-700 max-w-[180px] truncate" title={motif} data-testid={`payment-motif-${p.deposit_id}`}>{motif}</td>
                    <td className="px-3 py-2 text-right font-mono whitespace-nowrap">{Number(p.amount || 0).toLocaleString("fr-FR")} <span className="text-[10px] text-slate-400">{p.currency || "XOF"}</span></td>
                    <td className="px-3 py-2">
                      <span className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded ring-1 ${sb.cls}`}>
                        <Icon className="h-3 w-3" /> <span className="hidden sm:inline">{sb.label}</span>
                      </span>
                      {p.api_message && <span className="hidden md:block text-[10px] text-slate-500 mt-0.5 max-w-[180px] truncate" title={safeText(p.api_message)}>{safeText(p.api_message)}</span>}
                    </td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      {p.status === "pending" && (
                        <button onClick={() => refreshOne(p.deposit_id)} className="text-xs text-sawali-blue hover:underline mr-2" data-testid={`payment-refresh-${p.deposit_id}`}>
                          Vérifier
                        </button>
                      )}
                      {p.status === "failed" && features.payments && mnosLen > 0 && (
                        <button onClick={() => handleResend(p)} className="inline-flex items-center gap-1 text-xs text-rose-700 hover:bg-rose-50 px-2 py-0.5 rounded" data-testid={`payment-resend-${p.deposit_id}`}>
                          <Send className="h-3 w-3" /> <span className="hidden sm:inline">Renvoyer</span>
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

function Field({ label, children }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-wider text-slate-400">{label}</span>
      {children}
    </label>
  );
}

const TONES = {
  emerald: "bg-emerald-50 ring-emerald-200 text-emerald-900",
  amber: "bg-amber-50 ring-amber-200 text-amber-900",
  rose: "bg-rose-50 ring-rose-200 text-rose-900",
  slate: "bg-slate-50 ring-slate-200 text-slate-900",
};

function KpiCard({ label, value, sub, tone = "slate", icon: Icon, testid }) {
  return (
    <div className={`rounded-xl ring-1 p-3 ${TONES[tone]}`} data-testid={testid}>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] uppercase tracking-wider opacity-70">{label}</span>
        {Icon && <Icon className="h-4 w-4 opacity-60" />}
      </div>
      <div className="text-2xl font-display font-bold">{value}</div>
      <div className="text-[11px] opacity-70 truncate">{sub}</div>
    </div>
  );
}

function NewPaymentModal({ mnos, prefill, onClose, onCreated }) {
  const [amount, setAmount] = useState(prefill?.amount || "");
  const [msisdn, setMsisdn] = useState(prefill?.msisdn || "226");
  const [mno, setMno] = useState(prefill?.mno || mnos[0] || "ORANGE");
  const [description, setDescription] = useState(prefill?.description || "");
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    const amt = parseFloat(amount);
    if (!amt || amt <= 0) { toast.error("Montant invalide"); return; }
    // Iter38r — MSISDN is now OPTIONAL (collected on PawaPay's hosted page if blank)
    if (msisdn && msisdn.replace(/\D/g, "").length < 8) {
      toast.error("Numéro mobile invalide. Laissez vide pour le saisir sur la page PawaPay.");
      return;
    }
    setSubmitting(true);
    let toastId;
    try {
      // Pre-flight breadcrumb so we can debug from the api_traces collection
      apiClient.post("/me/api-trace", {
        method: "CLIENT_DEBUG", url: "/portal/payments#submit-click", status: 0,
        module: "payment-submit-pre",
        request_body: { amount: amt, mno, msisdn_len: msisdn.replace(/\D/g, "").length, has_description: !!description },
      }).catch(() => {});
      toastId = toast.loading("Création de la session de paiement…", { duration: 35000 });
      // Iter38r — Use the hosted Payment Page flow (handles MSISDN + PIN/OTP)
      const r = await apiClient.post("/me/payments/pawapay/payment-page", {
        amount: amt,
        msisdn: msisdn.replace(/\D/g, "") || undefined,
        reason: (description || "").slice(0, 22) || undefined,
      }, { timeout: 32000 });
      if (toastId !== undefined) toast.dismiss(toastId);
      const redirectUrl = r.data?.redirect_url;
      if (redirectUrl) {
        toast.success("Redirection vers PawaPay…");
        // Brief delay so the toast renders before navigation
        setTimeout(() => { window.location.href = redirectUrl; }, 300);
      } else {
        toast.error("Aucun lien de paiement reçu de PawaPay");
        onCreated && onCreated();
      }
    } catch (err) {
      if (toastId !== undefined) toast.dismiss(toastId);
      const msg = safeText(err?.response?.data?.detail) || err?.message || "Erreur inconnue";
      toast.error(`Erreur : ${msg}`, { duration: 8000 });
      // Log full detail server-side so we can diagnose prod-only crashes
      apiClient.post("/me/api-trace", {
        method: "CLIENT_ERROR", url: "/portal/payments#submit-fail", status: err?.response?.status || 0,
        module: "payment-submit-fail",
        error: String(msg).slice(0, 400),
        request_body: { amount: amt, mno, msisdn_len: msisdn.replace(/\D/g, "").length },
        response_body: { stack: String(err?.stack || "").slice(0, 1500) },
      }).catch(() => {});
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      data-testid="payment-new-modal"
    >
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 bg-amber-50">
          <h2 className="text-lg font-display font-bold inline-flex items-center gap-2">
            <CreditCard className="h-5 w-5 text-amber-600" />
            {prefill ? "Renvoyer le paiement" : "Nouveau paiement"}
          </h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900" data-testid="payment-modal-close"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-3">
          {prefill && (
            <div className="text-[11px] rounded-md ring-1 ring-amber-200 bg-amber-50 p-2 text-amber-900">
              Les informations du paiement échoué ont été pré-remplies. Vérifiez puis relancez.
            </div>
          )}
          <div>
            <label className="text-xs font-semibold block mb-1">Montant (XOF)</label>
            <input
              type="number"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="5000"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono"
              data-testid="payment-amount"
            />
          </div>
          <div>
            <label className="text-xs font-semibold block mb-1">Opérateur Mobile Money</label>
            <div className="text-xs text-slate-600 bg-blue-50 border border-blue-200 rounded-lg p-2 mb-2">
              ℹ️ Vous choisirez votre opérateur (Orange, Moov, Telecel…) directement sur la page sécurisée PawaPay à l'étape suivante.
            </div>
            {/* Hidden mno kept for potential pre-fill compat — not used by Payment Page */}
          </div>
          <div>
            <label className="text-xs font-semibold block mb-1">Numéro Mobile Money (optionnel)</label>
            <input
              value={msisdn}
              onChange={(e) => setMsisdn(e.target.value)}
              placeholder="Laissez vide pour le saisir sur PawaPay"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono"
              data-testid="payment-msisdn"
            />
            <p className="text-[10px] text-slate-400 mt-0.5">Si renseigné, le numéro sera pré-fixé sur la page de paiement.</p>
          </div>
          <div>
            <label className="text-xs font-semibold block mb-1">Description (facultatif, max 22 car.)</label>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value.slice(0, 22))}
              maxLength={22}
              placeholder="Facture #1234"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              data-testid="payment-description"
            />
          </div>
        </div>
        <div className="flex justify-end gap-2 px-5 py-3 border-t border-slate-200 bg-slate-50">
          <button onClick={onClose} className="text-sm rounded-lg bg-white ring-1 ring-slate-300 hover:bg-slate-100 px-4 py-2" data-testid="payment-cancel-btn">Annuler</button>
          <button
            onClick={submit}
            disabled={submitting}
            className="inline-flex items-center gap-1.5 text-sm rounded-lg bg-amber-600 hover:bg-amber-700 text-white px-4 py-2 disabled:opacity-50"
            data-testid="payment-submit-btn"
          >
            <CreditCard className="h-4 w-4" /> {submitting ? "Création…" : "Payer via PawaPay"}
          </button>
        </div>
      </div>
    </div>
  );
}
