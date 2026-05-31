// Iter38r-fix9y — Public live report for an ad banner (no auth required).
// Reached via /ads/:slug?token=XXX. Advertisers can bookmark this URL to
// monitor their campaign's impressions, clicks, CTR and remaining budget
// without ever logging into the SAWALI CRM.
//
// Iter38r-fix9z5 — Added sparkline trend chart (30j) + "Renew campaign"
// CTA widget that lets the advertiser request a renewal in one click.
import React, { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams, Link } from "react-router-dom";
import {
  Eye,
  MousePointerClick,
  TrendingUp,
  Wallet,
  Calendar,
  AlertTriangle,
  CheckCircle2,
  RefreshCw,
  ExternalLink,
  RotateCw,
  Send,
  X as IconX,
  CreditCard,
  Upload as UploadIcon,
  Image as ImageIcon,
  Edit3,
  Sparkles,
  Lightbulb,
  MessageSquare,
  TrendingDown,
} from "lucide-react";
import { LOGO_URL } from "@/lib/brand";
import { resolveAssetUrl } from "@/lib/useAssetUrl";

const REFRESH_INTERVAL_MS = 30000; // auto-refresh every 30s

export default function PublicAdReport() {
  const { slug } = useParams();
  const [search] = useSearchParams();
  const token = search.get("token") || "";
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshedAt, setRefreshedAt] = useState(null);
  const apiBase = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");

  useEffect(() => {
    if (!slug || !token) {
      setError("URL invalide — slug ou token manquant");
      setLoading(false);
      return;
    }
    let cancelled = false;

    const fetchReport = async () => {
      try {
        const r = await fetch(
          `${apiBase}/api/public/ads-report/${encodeURIComponent(slug)}?token=${encodeURIComponent(token)}`,
        );
        if (!r.ok) {
          const data = await r.json().catch(() => ({}));
          if (!cancelled) {
            setError(data.detail || `Erreur ${r.status}`);
            setReport(null);
            setLoading(false);
          }
          return;
        }
        const data = await r.json();
        if (!cancelled) {
          setReport(data);
          setError(null);
          setRefreshedAt(new Date());
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.message || "Erreur réseau");
          setLoading(false);
        }
      }
    };

    fetchReport();
    const id = setInterval(fetchReport, REFRESH_INTERVAL_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, [apiBase, slug, token]);

  if (loading) {
    return <div className="min-h-screen flex items-center justify-center text-slate-500" data-testid="ads-report-loading">Chargement du tableau de bord…</div>;
  }

  if (error || !report) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6">
        <div className="max-w-md w-full rounded-2xl ring-1 ring-rose-200 bg-rose-50 p-6 text-center" data-testid="ads-report-error">
          <AlertTriangle className="h-10 w-10 text-rose-500 mx-auto mb-3" />
          <h1 className="font-display font-bold text-slate-900 mb-1">Tableau de bord inaccessible</h1>
          <p className="text-sm text-rose-700">{error || "Bannière introuvable"}</p>
          <Link to="/" className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-sawali-blue mt-4">← Retour à l'accueil SAWALI</Link>
        </div>
      </div>
    );
  }

  const isVideo = report.media_kind === "video"
    || /\.(mp4|webm|mov)$/i.test(report.image_url || "");
  const mediaSrc = resolveAssetUrl(report.image_url);
  const ctr = report.totals?.ctr_pct ?? 0;
  const budget = report.budget || {};
  const daily = report.daily || [];
  const progressColor = budget.progress_pct >= 90 ? "bg-rose-500" : budget.progress_pct >= 70 ? "bg-amber-500" : "bg-emerald-500";

  return (
    <div className="min-h-screen bg-slate-50" data-testid="ads-report-page">
      {/* Header */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between flex-wrap gap-3">
          <Link to="/" className="flex items-center gap-2 text-slate-900 hover:opacity-80">
            <img src={LOGO_URL} alt="SAWALI" className="h-8 w-auto" />
            <span className="font-display font-bold">SAWALI · Régie publicitaire</span>
          </Link>
          <div className="text-[10px] text-slate-500 inline-flex items-center gap-1.5">
            <RefreshCw className="h-3 w-3" />
            Actualisation auto · dernière màj {refreshedAt ? refreshedAt.toLocaleTimeString("fr-FR") : "—"}
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-8 space-y-6">
        {/* Banner preview */}
        <section className="rounded-2xl ring-1 ring-slate-200 bg-white overflow-hidden shadow-sm" data-testid="ads-report-banner">
          <div className="bg-gradient-to-r from-slate-900 via-slate-800 to-slate-900 flex items-center justify-center">
            {isVideo ? (
              <video src={mediaSrc} className="w-full max-h-32 object-contain" muted autoPlay loop playsInline controls preload="metadata" />
            ) : (
              <img src={mediaSrc} alt="aperçu bannière" className="w-full max-h-32 object-contain" />
            )}
          </div>
          <div className="p-5 flex items-start justify-between flex-wrap gap-3">
            <div className="flex-1 min-w-0">
              <h1 className="text-xl font-display font-bold text-slate-900">{report.name}</h1>
              {report.advertiser_name && <p className="text-sm text-slate-500 mt-0.5">Annonceur : <strong>{report.advertiser_name}</strong></p>}
              <p className="text-xs text-slate-500 mt-1 inline-flex items-center gap-2">
                {report.is_currently_active ? (
                  <span className="inline-flex items-center gap-1 text-emerald-700 font-semibold">
                    <CheckCircle2 className="h-3.5 w-3.5" /> Campagne active
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-slate-500 font-semibold">
                    <AlertTriangle className="h-3.5 w-3.5" /> Suspendue
                  </span>
                )}
                {report.expiration_date && (
                  <span className="text-slate-400">
                    · expire le {report.expiration_date}
                  </span>
                )}
              </p>
            </div>
            {report.target_url && (
              <a
                href={report.target_url} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 rounded-lg ring-1 ring-slate-300 bg-white hover:bg-slate-50 px-3 py-1.5 text-xs text-slate-700"
                data-testid="ads-report-target-link"
              >
                <ExternalLink className="h-3 w-3" /> Voir la cible
              </a>
            )}
          </div>
        </section>

        {/* Key stats */}
        <section className="grid grid-cols-2 sm:grid-cols-4 gap-3" data-testid="ads-report-stats">
          <Stat icon={Eye} label="Affichages" value={(report.totals?.impressions || 0).toLocaleString("fr-FR")} accent="sky" />
          <Stat icon={MousePointerClick} label="Clics" value={(report.totals?.clicks || 0).toLocaleString("fr-FR")} accent="violet" />
          <Stat icon={TrendingUp} label="CTR" value={`${ctr}%`} accent="emerald" />
          <Stat icon={Wallet} label="Dépensé"
                value={`${(report.totals?.amount_spent || 0).toLocaleString("fr-FR")} ${report.currency}`} accent="amber" />
        </section>

        {/* Budget progression */}
        {budget.amount > 0 && (
          <section className="rounded-2xl ring-1 ring-slate-200 bg-white p-5" data-testid="ads-report-budget">
            <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
              <h2 className="font-display font-semibold text-slate-900">Budget</h2>
              <p className="text-sm text-slate-600">
                <span className="font-mono">{budget.amount.toLocaleString("fr-FR")} {report.currency}</span> · Restant <span className="font-mono font-bold text-emerald-700">{budget.remaining.toLocaleString("fr-FR")} {report.currency}</span>
              </p>
            </div>
            <div className="w-full h-3 rounded-full bg-slate-100 overflow-hidden">
              <div className={`h-full ${progressColor} transition-all`} style={{ width: `${Math.min(budget.progress_pct, 100)}%` }} />
            </div>
            <p className="text-[11px] text-slate-500 mt-1.5">{budget.progress_pct}% du budget consommé</p>
          </section>
        )}

        {/* Iter38r-fix9z5 — Conversion trend chart */}
        {daily.length > 1 && <ConversionTrend daily={daily} currency={report.currency} />}

        {/* Iter38r-fix9z5 — Renew campaign CTA */}
        <RenewCampaignWidget
          slug={slug}
          token={token}
          apiBase={apiBase}
          currency={report.currency}
          currentBudget={budget.amount || 0}
          remainingBudget={budget.remaining || 0}
          isCurrentlyActive={report.is_currently_active}
        />

        {/* Iter38r-fix9z8 — Self-service: online payment + media update */}
        <OnlineRenewalCheckout
          slug={slug}
          token={token}
          apiBase={apiBase}
          currency={report.currency}
          currentBudget={budget.amount || 0}
        />
        <SelfServiceMediaUpdate
          slug={slug}
          token={token}
          apiBase={apiBase}
          currentImageUrl={report.image_url}
          currentMediaKind={report.media_kind}
          currentTargetUrl={report.target_url}
        />

        {/* Iter38r-fix9z9 — AI campaign plan */}
        <AICampaignPlan slug={slug} token={token} apiBase={apiBase} currency={report.currency} />

        {/* Daily history */}
        {daily.length > 0 && (
          <section className="rounded-2xl ring-1 ring-slate-200 bg-white p-5" data-testid="ads-report-daily">
            <h2 className="font-display font-semibold text-slate-900 mb-3 inline-flex items-center gap-2">
              <Calendar className="h-4 w-4" /> Historique quotidien · {daily.length} jour(s)
            </h2>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-slate-50 text-slate-500 uppercase tracking-wider text-[10px]">
                  <tr>
                    <th className="text-left px-3 py-2">Date</th>
                    <th className="text-right px-3 py-2">Affichages</th>
                    <th className="text-right px-3 py-2">Clics</th>
                    <th className="text-right px-3 py-2">CTR</th>
                    <th className="text-right px-3 py-2">Dépensé ({report.currency})</th>
                  </tr>
                </thead>
                <tbody>
                  {[...daily].reverse().map((d, i) => {
                    const dctr = d.impressions > 0 ? ((d.clicks / d.impressions) * 100).toFixed(1) : "—";
                    return (
                      <tr key={i} className="border-t border-slate-100 hover:bg-slate-50">
                        <td className="px-3 py-1.5 text-slate-700">{d.date}</td>
                        <td className="text-right font-mono">{(d.impressions || 0).toLocaleString("fr-FR")}</td>
                        <td className="text-right font-mono">{(d.clicks || 0).toLocaleString("fr-FR")}</td>
                        <td className="text-right font-mono text-slate-500">{dctr}{dctr !== "—" && "%"}</td>
                        <td className="text-right font-mono">{(d.spent || 0).toLocaleString("fr-FR")}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )}

        <p className="text-[10px] text-slate-400 text-center">
          Tableau de bord généré le {new Date(report.generated_at).toLocaleString("fr-FR")} — données mises à jour en temps réel toutes les 30 secondes.
          Lien personnel : ne le partagez qu'avec votre annonceur.
        </p>
      </main>
    </div>
  );
}

function Stat({ icon: Icon, label, value, accent }) {
  const palette = {
    sky: "bg-sky-50 text-sky-700",
    violet: "bg-violet-50 text-violet-700",
    emerald: "bg-emerald-50 text-emerald-700",
    amber: "bg-amber-50 text-amber-700",
  }[accent] || "bg-slate-50 text-slate-700";
  return (
    <div className="rounded-2xl ring-1 ring-slate-200 bg-white p-4 flex items-center gap-3" data-testid={`stat-${label}`}>
      <div className={`rounded-lg p-2 ${palette}`}>
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0">
        <p className="text-[10px] uppercase font-bold tracking-wider text-slate-500">{label}</p>
        <p className="text-lg font-display font-bold text-slate-900 tabular-nums truncate">{value}</p>
      </div>
    </div>
  );
}


// Iter38r-fix9z5 — Lightweight inline SVG dual-line sparkline:
// shows impressions (blue) and clicks (violet) over the last 30 days.
function ConversionTrend({ daily, currency }) {
  const series = useMemo(() => daily.slice(-30), [daily]);
  if (!series || series.length < 2) return null;
  const maxImp = Math.max(1, ...series.map((d) => d.impressions || 0));
  const maxClk = Math.max(1, ...series.map((d) => d.clicks || 0));
  const W = 760;
  const H = 120;
  const pad = 8;
  const stepX = (W - 2 * pad) / (series.length - 1);
  const path = (key, max) =>
    series
      .map((d, i) => {
        const x = pad + i * stepX;
        const y = H - pad - ((d[key] || 0) / max) * (H - 2 * pad);
        return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  const totalImp = series.reduce((s, d) => s + (d.impressions || 0), 0);
  const totalClk = series.reduce((s, d) => s + (d.clicks || 0), 0);
  const totalSpent = series.reduce((s, d) => s + (d.spent || 0), 0);
  const avgCtr = totalImp > 0 ? ((totalClk / totalImp) * 100).toFixed(2) : "0";

  return (
    <section className="rounded-2xl ring-1 ring-slate-200 bg-white p-5" data-testid="ads-report-trend">
      <div className="flex items-center justify-between flex-wrap gap-3 mb-3">
        <h2 className="font-display font-semibold text-slate-900 inline-flex items-center gap-2">
          <TrendingUp className="h-4 w-4" /> Tendance — {series.length} derniers jours
        </h2>
        <div className="flex flex-wrap gap-3 text-[11px] text-slate-600">
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-2 w-3 rounded-sm bg-sky-500" /> Affichages · <strong>{totalImp.toLocaleString("fr-FR")}</strong>
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-2 w-3 rounded-sm bg-violet-500" /> Clics · <strong>{totalClk.toLocaleString("fr-FR")}</strong>
          </span>
          <span className="text-slate-500">CTR moyen · <strong className="text-emerald-700">{avgCtr}%</strong></span>
          {totalSpent > 0 && <span className="text-slate-500">Dépensé · <strong>{totalSpent.toLocaleString("fr-FR")} {currency}</strong></span>}
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto block" preserveAspectRatio="none" data-testid="ads-report-spark-svg">
        <defs>
          <linearGradient id="impFill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#0ea5e9" stopOpacity="0.25" />
            <stop offset="100%" stopColor="#0ea5e9" stopOpacity="0" />
          </linearGradient>
        </defs>
        {/* Impressions area */}
        <path
          d={`${path("impressions", maxImp)} L${(W - pad).toFixed(1)},${H - pad} L${pad},${H - pad} Z`}
          fill="url(#impFill)"
        />
        <path d={path("impressions", maxImp)} fill="none" stroke="#0ea5e9" strokeWidth="2" />
        <path d={path("clicks", maxClk)} fill="none" stroke="#8b5cf6" strokeWidth="2" />
        {/* X-axis day markers */}
        {series.map((d, i) => {
          if (series.length > 10 && i % Math.ceil(series.length / 6) !== 0 && i !== series.length - 1) return null;
          const x = pad + i * stepX;
          const label = (d.date || "").slice(5); // MM-DD
          return (
            <text key={i} x={x} y={H - 1} fontSize="9" fill="#94a3b8" textAnchor="middle">{label}</text>
          );
        })}
      </svg>
    </section>
  );
}

// Iter38r-fix9z5 — Inline form to request a renewal/extension of the campaign.
// On submit, posts to /api/public/ads-report/{slug}/renew which creates a
// row in `ad_renewal_requests`. The admin sees it in their inbox.
function RenewCampaignWidget({ slug, token, apiBase, currency, currentBudget, remainingBudget, isCurrentlyActive }) {
  const [open, setOpen] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const [form, setForm] = useState({
    contact_name: "",
    contact_email: "",
    contact_phone: "",
    new_budget: currentBudget || 0,
    target_duration_days: 30,
    message: "",
  });

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.contact_email && !form.contact_phone) {
      setErrorMsg("Merci de renseigner au moins un moyen de contact (email ou téléphone)");
      return;
    }
    setSubmitting(true);
    setErrorMsg(null);
    try {
      const r = await fetch(
        `${apiBase}/api/public/ads-report/${encodeURIComponent(slug)}/renew?token=${encodeURIComponent(token)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...form,
            new_budget: parseFloat(form.new_budget) || 0,
            target_duration_days: parseInt(form.target_duration_days, 10) || 30,
          }),
        },
      );
      if (!r.ok) {
        const data = await r.json().catch(() => ({}));
        setErrorMsg(data.detail || `Erreur ${r.status}`);
        return;
      }
      setSubmitted(true);
    } catch (err) {
      setErrorMsg(err.message || "Erreur réseau");
    } finally {
      setSubmitting(false);
    }
  };

  if (submitted) {
    return (
      <section className="rounded-2xl ring-1 ring-emerald-200 bg-emerald-50 p-5 text-center" data-testid="ads-report-renew-ok">
        <CheckCircle2 className="h-10 w-10 text-emerald-600 mx-auto mb-2" />
        <h2 className="font-display font-bold text-emerald-900">Demande envoyée — merci !</h2>
        <p className="text-sm text-emerald-800 mt-1">L'équipe SAWALI va vous recontacter sous 24h pour finaliser le renouvellement de votre campagne.</p>
      </section>
    );
  }

  if (!open) {
    return (
      <section className="rounded-2xl ring-1 ring-fuchsia-200 bg-gradient-to-br from-fuchsia-50 to-rose-50 p-5 sm:p-6" data-testid="ads-report-renew-cta">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-start gap-3 max-w-xl">
            <div className="rounded-lg bg-white p-2 ring-1 ring-fuchsia-200 hidden sm:block">
              <RotateCw className="h-5 w-5 text-fuchsia-600" />
            </div>
            <div>
              <h2 className="font-display font-bold text-slate-900">
                {isCurrentlyActive ? "Prolonger ou augmenter le budget" : "Relancer cette campagne"}
              </h2>
              <p className="text-sm text-slate-700 mt-1">
                Une seule formule, sans login. Précisez vos besoins (durée, budget) et notre équipe revient vers vous avec un devis sous 24h.
              </p>
            </div>
          </div>
          <button
            onClick={() => setOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-fuchsia-600 hover:bg-fuchsia-700 text-white px-4 py-2 text-sm font-semibold shadow-sm"
            data-testid="ads-report-renew-open"
          >
            <RotateCw className="h-4 w-4" /> Renouveler ma campagne
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-2xl ring-1 ring-fuchsia-300 bg-white p-5 sm:p-6" data-testid="ads-report-renew-form">
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-display font-bold text-slate-900 inline-flex items-center gap-2">
          <RotateCw className="h-4 w-4 text-fuchsia-600" /> Renouvellement de campagne
        </h2>
        <button onClick={() => setOpen(false)} className="text-slate-400 hover:text-slate-600" aria-label="Fermer" data-testid="ads-report-renew-close">
          <IconX className="h-4 w-4" />
        </button>
      </div>

      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="grid sm:grid-cols-2 gap-3">
          <label className="block">
            <span className="text-[11px] uppercase font-semibold text-slate-500">Nom du contact</span>
            <input
              type="text" value={form.contact_name}
              onChange={(e) => setForm({ ...form, contact_name: e.target.value })}
              className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 mt-1 bg-white"
              placeholder="Votre nom"
              data-testid="renew-contact-name"
            />
          </label>
          <label className="block">
            <span className="text-[11px] uppercase font-semibold text-slate-500">Email</span>
            <input
              type="email" value={form.contact_email}
              onChange={(e) => setForm({ ...form, contact_email: e.target.value })}
              className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 mt-1 bg-white"
              placeholder="vous@entreprise.com"
              data-testid="renew-contact-email"
            />
          </label>
          <label className="block">
            <span className="text-[11px] uppercase font-semibold text-slate-500">Téléphone / WhatsApp</span>
            <input
              type="tel" value={form.contact_phone}
              onChange={(e) => setForm({ ...form, contact_phone: e.target.value })}
              className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 mt-1 bg-white font-mono"
              placeholder="+225 …"
              data-testid="renew-contact-phone"
            />
          </label>
          <label className="block">
            <span className="text-[11px] uppercase font-semibold text-slate-500">Durée souhaitée (jours)</span>
            <input
              type="number" min="1" max="730"
              value={form.target_duration_days}
              onChange={(e) => setForm({ ...form, target_duration_days: e.target.value })}
              className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 mt-1 bg-white font-mono"
              data-testid="renew-duration"
            />
          </label>
          <label className="block sm:col-span-2">
            <span className="text-[11px] uppercase font-semibold text-slate-500">Nouveau budget souhaité ({currency})</span>
            <input
              type="number" min="0" step="1000"
              value={form.new_budget}
              onChange={(e) => setForm({ ...form, new_budget: e.target.value })}
              className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 mt-1 bg-white font-mono"
              data-testid="renew-budget"
            />
            <p className="text-[10px] text-slate-500 mt-0.5">Budget actuel : {currentBudget.toLocaleString("fr-FR")} {currency} · Restant {remainingBudget.toLocaleString("fr-FR")} {currency}</p>
          </label>
        </div>
        <label className="block">
          <span className="text-[11px] uppercase font-semibold text-slate-500">Notes pour l'équipe (optionnel)</span>
          <textarea
            rows={2} value={form.message}
            onChange={(e) => setForm({ ...form, message: e.target.value })}
            placeholder="Précisez vos objectifs, contraintes ou questions…"
            className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 mt-1 bg-white"
            data-testid="renew-message"
          />
        </label>
        {errorMsg && <p className="text-xs text-rose-600" data-testid="renew-error">{errorMsg}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={() => setOpen(false)} className="text-xs text-slate-600 hover:underline">Annuler</button>
          <button
            type="submit" disabled={submitting}
            className="inline-flex items-center gap-1.5 rounded-lg bg-fuchsia-600 hover:bg-fuchsia-700 disabled:opacity-50 text-white px-4 py-2 text-sm font-semibold"
            data-testid="renew-submit"
          >
            <Send className="h-3.5 w-3.5" /> {submitting ? "Envoi…" : "Envoyer la demande"}
          </button>
        </div>
      </form>
    </section>
  );
}

// Iter38r-fix9z8 — Online payment widget. Calls /api/public/ads-report/{slug}/checkout
// to create a Stripe Checkout Session, redirects there, and polls
// /payment-status/{session_id} on return (URL ?session_id=…&renew=ok).
function OnlineRenewalCheckout({ slug, token, apiBase, currency, currentBudget }) {
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState(Math.max(10000, Math.round((currentBudget || 50000))));
  const [duration, setDuration] = useState(30);
  const [contactEmail, setContactEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const [postPayStatus, setPostPayStatus] = useState(null); // {payment_status, renewal_applied}
  const [params, setParams] = useSearchParams();

  // After Stripe redirect, poll status
  useEffect(() => {
    const sid = params.get("session_id");
    const renew = params.get("renew");
    if (renew === "ok" && sid) {
      let cancelled = false;
      let attempts = 0;
      const poll = async () => {
        attempts += 1;
        try {
          const r = await fetch(
            `${apiBase}/api/public/ads-report/${encodeURIComponent(slug)}/payment-status/${encodeURIComponent(sid)}?token=${encodeURIComponent(token)}`
          );
          const data = await r.json();
          if (cancelled) return;
          setPostPayStatus(data);
          if (data.payment_status === "paid" || attempts > 6) {
            // Clean URL
            params.delete("session_id");
            params.delete("renew");
            setParams(params, { replace: true });
            return;
          }
          setTimeout(poll, 2500);
        } catch {
          if (attempts < 6) setTimeout(poll, 2500);
        }
      };
      poll();
      return () => { cancelled = true; };
    }
  }, [params, slug, token, apiBase, setParams]);

  const handleCheckout = async () => {
    setBusy(true); setErrorMsg(null);
    try {
      const origin = window.location.origin;
      const r = await fetch(
        `${apiBase}/api/public/ads-report/${encodeURIComponent(slug)}/checkout?token=${encodeURIComponent(token)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            amount_xof: parseFloat(amount) || 0,
            duration_days: parseInt(duration, 10) || 30,
            origin_url: origin,
            contact_email: contactEmail.trim(),
          }),
        },
      );
      if (!r.ok) {
        const data = await r.json().catch(() => ({}));
        throw new Error(data.detail || `Erreur ${r.status}`);
      }
      const data = await r.json();
      if (data.url) {
        window.location.href = data.url;
      } else {
        setErrorMsg("Aucune URL de paiement renvoyée");
      }
    } catch (err) {
      setErrorMsg(err.message || "Erreur réseau");
      setBusy(false);
    }
  };

  // Post-payment success banner takes priority
  if (postPayStatus?.payment_status === "paid" && postPayStatus?.renewal_applied) {
    return (
      <section className="rounded-2xl ring-1 ring-emerald-200 bg-emerald-50 p-5 text-center" data-testid="ads-report-pay-success">
        <CheckCircle2 className="h-10 w-10 text-emerald-600 mx-auto mb-2" />
        <h2 className="font-display font-bold text-emerald-900">Paiement reçu — campagne renouvelée !</h2>
        <p className="text-sm text-emerald-800 mt-1">
          Budget crédité : <strong>{(postPayStatus.amount_xof || 0).toLocaleString("fr-FR")} {currency}</strong> ·
          Prolongation : <strong>{postPayStatus.duration_days} jours</strong>
        </p>
      </section>
    );
  }

  if (!open) {
    return (
      <section className="rounded-2xl ring-1 ring-sky-200 bg-gradient-to-br from-sky-50 to-cyan-50 p-5" data-testid="ads-report-pay-cta">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-start gap-3 max-w-xl">
            <div className="rounded-lg bg-white p-2 ring-1 ring-sky-200 hidden sm:block">
              <CreditCard className="h-5 w-5 text-sky-600" />
            </div>
            <div>
              <h2 className="font-display font-bold text-slate-900">Payer en ligne · renouvellement instantané</h2>
              <p className="text-sm text-slate-700 mt-1">
                Réglez votre budget par carte bancaire (Stripe sécurisé). Dès paiement validé, la campagne est automatiquement prolongée — aucune intervention manuelle requise.
              </p>
            </div>
          </div>
          <button
            onClick={() => setOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-sky-600 hover:bg-sky-700 text-white px-4 py-2 text-sm font-semibold shadow-sm"
            data-testid="ads-report-pay-open"
          >
            <CreditCard className="h-4 w-4" /> Payer en ligne
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-2xl ring-1 ring-sky-300 bg-white p-5 space-y-3" data-testid="ads-report-pay-form">
      <div className="flex items-center justify-between">
        <h2 className="font-display font-bold text-slate-900 inline-flex items-center gap-2">
          <CreditCard className="h-4 w-4 text-sky-600" /> Paiement en ligne
        </h2>
        <button onClick={() => setOpen(false)} className="text-slate-400 hover:text-slate-600" data-testid="ads-report-pay-close">
          <IconX className="h-4 w-4" />
        </button>
      </div>
      <div className="grid sm:grid-cols-2 gap-3">
        <label className="block">
          <span className="text-[11px] uppercase font-semibold text-slate-500">Montant ({currency})</span>
          <input
            type="number" min="500" step="500"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 mt-1 font-mono bg-white"
            data-testid="ads-report-pay-amount"
          />
        </label>
        <label className="block">
          <span className="text-[11px] uppercase font-semibold text-slate-500">Durée (jours)</span>
          <input
            type="number" min="1" max="730"
            value={duration}
            onChange={(e) => setDuration(e.target.value)}
            className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 mt-1 font-mono bg-white"
            data-testid="ads-report-pay-duration"
          />
        </label>
        <label className="block sm:col-span-2">
          <span className="text-[11px] uppercase font-semibold text-slate-500">Email pour le reçu</span>
          <input
            type="email"
            value={contactEmail}
            onChange={(e) => setContactEmail(e.target.value)}
            placeholder="vous@entreprise.com"
            className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 mt-1 bg-white"
            data-testid="ads-report-pay-email"
          />
        </label>
      </div>
      {errorMsg && <p className="text-xs text-rose-600" data-testid="ads-report-pay-error">{errorMsg}</p>}
      <p className="text-[10px] text-slate-500">
        Vous serez redirigé vers la page de paiement sécurisée Stripe. Conversion XOF → EUR au cours fixe (655,957). À la fin du paiement, vous reviendrez automatiquement ici.
      </p>
      <div className="flex justify-end">
        <button
          onClick={handleCheckout} disabled={busy || !amount}
          className="inline-flex items-center gap-1.5 rounded-lg bg-sky-600 hover:bg-sky-700 disabled:opacity-50 text-white px-4 py-2 text-sm font-semibold"
          data-testid="ads-report-pay-submit"
        >
          <CreditCard className="h-3.5 w-3.5" /> {busy ? "Redirection…" : `Payer ${Number(amount || 0).toLocaleString("fr-FR")} ${currency}`}
        </button>
      </div>
    </section>
  );
}


// Iter38r-fix9z8 — Self-service media update.
// Lets the advertiser swap the campaign's image/video + target URL without
// going through admin. Uses the same /api/admin/upload endpoint with no auth
// (admin/upload accepts anonymous uploads for public catalogue purposes;
// see backend). Storage is shared with the rest of the platform.
function SelfServiceMediaUpdate({ slug, token, apiBase, currentImageUrl, currentMediaKind, currentTargetUrl }) {
  const [open, setOpen] = useState(false);
  const [newImage, setNewImage] = useState("");
  const [newMediaKind, setNewMediaKind] = useState(currentMediaKind || "image");
  const [newTarget, setNewTarget] = useState(currentTargetUrl || "");
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const [savedAt, setSavedAt] = useState(null);

  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 20 * 1024 * 1024) {
      setErrorMsg("Fichier trop volumineux (max 20 Mo)");
      return;
    }
    setErrorMsg(null);
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const r = await fetch(`${apiBase}/api/admin/upload`, { method: "POST", body: form });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || `Upload échoué (${r.status})`);
      }
      const data = await r.json();
      const rel = (data.url || "").startsWith("/") ? data.url : `/${data.url || ""}`;
      setNewImage(rel);
      setNewMediaKind(file.type.startsWith("video/") ? "video" : "image");
    } catch (err) {
      setErrorMsg(err.message || "Erreur upload");
    } finally {
      setUploading(false);
    }
  };

  const handleSave = async () => {
    if (!newImage && !newTarget) {
      setErrorMsg("Choisissez un nouveau média ou modifiez l'URL cible");
      return;
    }
    setSaving(true); setErrorMsg(null);
    try {
      const body = {};
      if (newImage) { body.image_url = newImage; body.media_kind = newMediaKind; }
      if (newTarget && newTarget !== currentTargetUrl) body.target_url = newTarget;
      const r = await fetch(
        `${apiBase}/api/public/ads-report/${encodeURIComponent(slug)}/media?token=${encodeURIComponent(token)}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
      );
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || `Erreur ${r.status}`);
      }
      setSavedAt(new Date());
      setNewImage("");
    } catch (err) {
      setErrorMsg(err.message || "Erreur réseau");
    } finally {
      setSaving(false);
    }
  };

  const resolveSrc = (u) => {
    if (!u) return "";
    if (u.startsWith("http://") || u.startsWith("https://")) return u;
    if (u.startsWith("/")) return `${apiBase}${u}`;
    return u;
  };

  if (!open) {
    return (
      <section className="rounded-2xl ring-1 ring-amber-200 bg-amber-50/60 p-4 flex items-center justify-between gap-3 flex-wrap" data-testid="ads-report-media-cta">
        <div className="flex items-start gap-2.5">
          <Edit3 className="h-5 w-5 text-amber-600 mt-0.5" />
          <div>
            <p className="font-display font-semibold text-slate-900 text-sm">Mettre à jour mon visuel</p>
            <p className="text-xs text-slate-600">Remplacez votre image / vidéo ou modifiez l'URL de destination sans contacter l'équipe.</p>
          </div>
        </div>
        <button onClick={() => setOpen(true)} className="text-xs rounded-lg bg-amber-600 hover:bg-amber-700 text-white px-3 py-1.5 font-semibold" data-testid="ads-report-media-open">
          Modifier
        </button>
      </section>
    );
  }

  return (
    <section className="rounded-2xl ring-1 ring-amber-300 bg-white p-5 space-y-3" data-testid="ads-report-media-form">
      <div className="flex items-center justify-between">
        <h2 className="font-display font-bold text-slate-900 inline-flex items-center gap-2">
          <Edit3 className="h-4 w-4 text-amber-600" /> Mise à jour libre-service du visuel
        </h2>
        <button onClick={() => setOpen(false)} className="text-slate-400 hover:text-slate-600" data-testid="ads-report-media-close">
          <IconX className="h-4 w-4" />
        </button>
      </div>
      <div className="grid sm:grid-cols-2 gap-3">
        <div>
          <p className="text-[11px] uppercase font-semibold text-slate-500 mb-1">Média actuel</p>
          <div className="rounded-lg ring-1 ring-slate-200 bg-slate-50 h-24 overflow-hidden flex items-center justify-center">
            {currentImageUrl ? (
              currentMediaKind === "video" ? (
                <video src={resolveSrc(currentImageUrl)} className="w-full h-full object-contain" muted autoPlay loop playsInline />
              ) : (
                <img src={resolveSrc(currentImageUrl)} alt="" className="w-full h-full object-contain" />
              )
            ) : (<ImageIcon className="h-6 w-6 text-slate-300" />)}
          </div>
        </div>
        <div>
          <p className="text-[11px] uppercase font-semibold text-slate-500 mb-1">Nouveau média</p>
          <div className="rounded-lg ring-1 ring-amber-300 bg-amber-50/40 h-24 overflow-hidden flex items-center justify-center">
            {newImage ? (
              newMediaKind === "video" ? (
                <video src={resolveSrc(newImage)} className="w-full h-full object-contain" muted autoPlay loop playsInline />
              ) : (
                <img src={resolveSrc(newImage)} alt="" className="w-full h-full object-contain" />
              )
            ) : (<span className="text-[10px] text-slate-400 italic">Aucun fichier choisi</span>)}
          </div>
        </div>
      </div>
      <input
        type="file" accept="image/*,video/*"
        onChange={handleUpload}
        disabled={uploading || saving}
        className="w-full text-xs file:mr-2 file:py-1.5 file:px-3 file:rounded file:border-0 file:text-xs file:bg-amber-100 file:text-amber-700 hover:file:bg-amber-200"
        data-testid="ads-report-media-upload"
      />
      <label className="block">
        <span className="text-[11px] uppercase font-semibold text-slate-500">URL de destination</span>
        <input
          type="url" value={newTarget}
          onChange={(e) => setNewTarget(e.target.value)}
          className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 mt-1 bg-white"
          data-testid="ads-report-media-target"
        />
      </label>
      {errorMsg && <p className="text-xs text-rose-600" data-testid="ads-report-media-error">{errorMsg}</p>}
      {savedAt && <p className="text-xs text-emerald-700 inline-flex items-center gap-1" data-testid="ads-report-media-saved"><CheckCircle2 className="h-3 w-3" /> Mise à jour enregistrée à {savedAt.toLocaleTimeString("fr-FR")}</p>}
      <div className="flex justify-end gap-2">
        <button
          onClick={handleSave} disabled={saving || uploading || (!newImage && newTarget === currentTargetUrl)}
          className="inline-flex items-center gap-1.5 rounded-lg bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white px-4 py-2 text-sm font-semibold"
          data-testid="ads-report-media-save"
        >
          <UploadIcon className="h-3.5 w-3.5" /> {saving ? "Enregistrement…" : "Enregistrer"}
        </button>
      </div>
    </section>
  );
}


// Iter38r-fix9z9 — AI Campaign Plan widget.
// Calls POST /api/public/ads-report/{slug}/ai-plan and renders the 4
// recommendations (visual hint, slogans, recommended budget, justification).
// Cached 6h server-side — second click is instant.
function AICampaignPlan({ slug, token, apiBase, currency }) {
  const [plan, setPlan] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);
  const [copied, setCopied] = useState(null);

  const run = async () => {
    setLoading(true); setErr(null);
    try {
      const r = await fetch(
        `${apiBase}/api/public/ads-report/${encodeURIComponent(slug)}/ai-plan?token=${encodeURIComponent(token)}`,
        { method: "POST" },
      );
      if (!r.ok) {
        const data = await r.json().catch(() => ({}));
        throw new Error(data.detail || `Erreur ${r.status}`);
      }
      const data = await r.json();
      setPlan(data);
    } catch (e) {
      setErr(e.message || "Erreur réseau");
    } finally {
      setLoading(false);
    }
  };

  const copyToClipboard = async (text, key) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
      setTimeout(() => setCopied(null), 1500);
    } catch { /* ignore */ }
  };

  if (!plan && !loading && !err) {
    return (
      <section className="rounded-2xl ring-1 ring-violet-200 bg-gradient-to-br from-violet-50 to-fuchsia-50 p-5" data-testid="ads-report-ai-cta">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-start gap-3 max-w-xl">
            <div className="rounded-lg bg-white p-2 ring-1 ring-violet-200 hidden sm:block">
              <Sparkles className="h-5 w-5 text-violet-600" />
            </div>
            <div>
              <h2 className="font-display font-bold text-slate-900 inline-flex items-center gap-1.5">
                Plan de campagne IA
                <span className="text-[10px] uppercase tracking-wider font-bold bg-violet-600 text-white px-1.5 py-0.5 rounded">Premium</span>
              </h2>
              <p className="text-sm text-slate-700 mt-1">
                Claude Haiku 4.5 analyse vos statistiques (affichages, clics, CTR, A/B) et propose 3 axes d'optimisation : visuel, slogan, budget. Résultat en 5 secondes.
              </p>
            </div>
          </div>
          <button
            onClick={run}
            className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 hover:bg-violet-700 text-white px-4 py-2 text-sm font-semibold shadow-sm"
            data-testid="ads-report-ai-run"
          >
            <Sparkles className="h-4 w-4" /> Générer mon plan IA
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-2xl ring-1 ring-violet-300 bg-white p-5 space-y-4" data-testid="ads-report-ai-result">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="font-display font-bold text-slate-900 inline-flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-violet-600" /> Plan de campagne IA
          {plan?.cached && (
            <span className="text-[10px] uppercase font-bold bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded" title="Résultat mis en cache 6h pour éviter la sur-consommation IA">CACHE</span>
          )}
        </h2>
        <button
          onClick={run}
          disabled={loading}
          className="text-xs inline-flex items-center gap-1 rounded-md ring-1 ring-violet-300 text-violet-700 hover:bg-violet-50 px-2 py-1 disabled:opacity-50"
          data-testid="ads-report-ai-refresh"
        >
          <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} /> {loading ? "Analyse…" : "Régénérer"}
        </button>
      </div>

      {loading && (
        <div className="text-sm text-slate-600 italic py-6 text-center">Claude analyse votre campagne…</div>
      )}

      {err && (
        <p className="text-sm text-rose-600 inline-flex items-center gap-1.5" data-testid="ads-report-ai-error">
          <AlertTriangle className="h-4 w-4" /> {err}
        </p>
      )}

      {plan && !loading && (
        <div className="space-y-3">
          {/* Visual hint */}
          <div className="rounded-xl ring-1 ring-fuchsia-200 bg-fuchsia-50/40 p-4" data-testid="ads-report-ai-visual">
            <p className="text-[11px] uppercase font-bold tracking-wider text-fuchsia-700 inline-flex items-center gap-1 mb-1">
              <ImageIcon className="h-3 w-3" /> Idée de visuel
            </p>
            <p className="text-sm text-slate-800">{plan.visual_hint}</p>
            <button
              onClick={() => copyToClipboard(plan.visual_hint, "visual")}
              className="mt-2 text-[11px] text-fuchsia-700 hover:underline"
              data-testid="ads-report-ai-copy-visual"
            >
              {copied === "visual" ? "✓ Copié" : "Copier la description"}
            </button>
          </div>

          {/* Slogans */}
          <div className="rounded-xl ring-1 ring-sky-200 bg-sky-50/40 p-4" data-testid="ads-report-ai-slogans">
            <p className="text-[11px] uppercase font-bold tracking-wider text-sky-700 inline-flex items-center gap-1 mb-1">
              <MessageSquare className="h-3 w-3" /> Slogans / Appels à l'action
            </p>
            <ul className="space-y-1.5 mt-1">
              {(plan.slogans || []).map((s, i) => (
                <li key={i} className="flex items-start justify-between gap-2 group">
                  <span className="text-sm text-slate-800 flex-1">
                    <span className="text-sky-500 font-bold mr-1.5">{i + 1}.</span>{s}
                  </span>
                  <button
                    onClick={() => copyToClipboard(s, `slogan-${i}`)}
                    className="text-[10px] text-sky-600 hover:underline opacity-0 group-hover:opacity-100 transition-opacity"
                    data-testid={`ads-report-ai-copy-slogan-${i}`}
                  >
                    {copied === `slogan-${i}` ? "✓" : "copier"}
                  </button>
                </li>
              ))}
            </ul>
          </div>

          {/* Budget */}
          <div className="rounded-xl ring-1 ring-emerald-200 bg-emerald-50/40 p-4" data-testid="ads-report-ai-budget">
            <p className="text-[11px] uppercase font-bold tracking-wider text-emerald-700 inline-flex items-center gap-1 mb-1">
              <Wallet className="h-3 w-3" /> Budget mensuel recommandé
            </p>
            <p className="font-display font-bold text-3xl text-emerald-700 tabular-nums">
              {Math.round(plan.recommended_budget_xof || 0).toLocaleString("fr-FR")} <span className="text-base font-normal text-slate-600">{currency}</span>
            </p>
            <p className="text-xs text-slate-700 mt-1.5">{plan.budget_justification}</p>
          </div>

          {plan.based_on && (
            <p className="text-[10px] text-slate-500 italic">
              Analyse basée sur : {plan.based_on.impressions} affichages · {plan.based_on.clicks} clics · CTR {plan.based_on.ctr_pct}% · budget actuel {Math.round(plan.based_on.current_budget).toLocaleString("fr-FR")} {currency}{plan.based_on.ab_enabled ? " · A/B actif" : ""}.
              {plan.generated_at && ` Généré le ${new Date(plan.generated_at).toLocaleString("fr-FR")}.`}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

