// Iter38r-fix9y — Public live report for an ad banner (no auth required).
// Reached via /ads/:slug?token=XXX. Advertisers can bookmark this URL to
// monitor their campaign's impressions, clicks, CTR and remaining budget
// without ever logging into the SAWALI CRM.
import React, { useEffect, useState } from "react";
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
} from "lucide-react";
import { LOGO_URL } from "@/lib/brand";

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
  const resolveUrl = (u) => {
    if (!u) return "";
    if (u.startsWith("http://") || u.startsWith("https://")) return u;
    if (u.startsWith("/")) return `${apiBase}${u}`;
    return u;
  };
  const mediaSrc = resolveUrl(report.image_url);
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
