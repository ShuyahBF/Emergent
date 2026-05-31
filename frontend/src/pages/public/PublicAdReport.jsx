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
