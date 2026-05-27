/*
 * Iter38n — Catalogue Analytics Cockpit
 *
 * Cockpit showing the conversion funnel + top products of the public
 * catalogue. Accessible to admin / superviseur / any tracked user.
 *
 * Sections:
 *  - 4 KPI cards (Vues catalogue, Aperçus produits, Partages, Devis demandés)
 *  - Funnel ratios (Share rate, Quote rate)
 *  - Top 5 products by interactions
 *  - Daily timeline (sparkline)
 *  - History table (recent events)
 */
import React, { useEffect, useMemo, useState, useCallback } from "react";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import {
  BarChart3, Eye, Share2, Sparkles, TrendingUp, RefreshCw,
  ShoppingBag, Clock, History, Loader2, Filter, Download, AlertTriangle, CheckCircle2,
} from "lucide-react";

const fmtNum = (n) => Number(n || 0).toLocaleString("fr-FR");
const fmtDate = (iso) => {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }); }
  catch { return iso; }
};

const EVENT_LABELS = {
  catalog_view: { label: "Vue catalogue", color: "bg-slate-100 text-slate-700" },
  product_og_fetch: { label: "Aperçu produit", color: "bg-blue-100 text-blue-700" },
  product_share: { label: "Partage", color: "bg-violet-100 text-violet-700" },
  product_quote_click: { label: "Devis demandé", color: "bg-emerald-100 text-emerald-700" },
};

function KpiCard({ icon: Icon, label, value, sub, accent }) {
  return (
    <div className={`rounded-xl border p-4 ${accent}`} data-testid={`catalog-kpi-${label.toLowerCase().replace(/\s/g, "-")}`}>
      <div className="flex items-center gap-2 mb-2">
        <Icon size={16} className="opacity-80" />
        <span className="text-xs font-medium uppercase tracking-wide">{label}</span>
      </div>
      <p className="text-2xl font-bold">{fmtNum(value)}</p>
      {sub && <p className="text-xs opacity-75 mt-1">{sub}</p>}
    </div>
  );
}

function Sparkline({ data, accessor, color = "#3b82f6" }) {
  const values = (data || []).map((d) => accessor(d) || 0);
  const max = Math.max(...values, 1);
  const w = 280;
  const h = 50;
  const stepX = values.length > 1 ? w / (values.length - 1) : 0;
  const pts = values.map((v, i) => `${i * stepX},${h - (v / max) * h}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="w-full h-12">
      <polyline points={pts} fill="none" stroke={color} strokeWidth="2" />
    </svg>
  );
}

export default function CatalogStats() {
  const { user } = useAuth();
  const [days, setDays] = useState(30);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [eventFilter, setEventFilter] = useState("");

  const isAllowed = useMemo(() => {
    if (!user) return false;
    if (["admin", "superviseur"].includes(user.role)) return true;
    if (user.tracked_role || user.tracked_user_id) return true;
    return false;
  }, [user]);

  const loadStats = useCallback(async () => {
    if (!isAllowed) return;
    setLoading(true);
    try {
      const r = await apiClient.get(`/me/catalog/stats?days=${days}`);
      setStats(r.data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally { setLoading(false); }
  }, [days, isAllowed]);

  const loadHistory = useCallback(async () => {
    if (!isAllowed) return;
    setHistoryLoading(true);
    try {
      const params = new URLSearchParams({ days: String(days), limit: "100" });
      if (eventFilter) params.set("event_type", eventFilter);
      const r = await apiClient.get(`/me/catalog/history?${params.toString()}`);
      setHistory(r.data?.items || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de l'historique");
    } finally { setHistoryLoading(false); }
  }, [days, eventFilter, isAllowed]);

  useEffect(() => { loadStats(); loadHistory(); }, [loadStats, loadHistory]);

  if (!isAllowed) {
    return (
      <div className="p-6 text-center text-slate-500" data-testid="catalog-stats-denied">
        Cet espace est réservé aux Administrateurs, Superviseurs et utilisateurs suivis.
      </div>
    );
  }

  return (
    <div className="p-4 md:p-6 max-w-7xl mx-auto" data-testid="catalog-stats-page">
      <div className="mb-6 flex items-start justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-emerald-100 rounded-xl flex items-center justify-center">
            <BarChart3 className="text-emerald-600" size={20} />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Statistiques catalogue</h1>
            <p className="text-sm text-slate-500">Conversion publique · vues · partages · devis</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={days}
            onChange={(e) => setDays(parseInt(e.target.value, 10))}
            data-testid="catalog-stats-period"
            className="px-3 py-2 border border-slate-200 rounded-lg text-sm bg-white"
          >
            <option value={7}>7 jours</option>
            <option value={14}>14 jours</option>
            <option value={30}>30 jours</option>
            <option value={60}>60 jours</option>
            <option value={90}>90 jours</option>
          </select>
          {/* Iter38o — CSV export */}
          <a
            href={`${process.env.REACT_APP_BACKEND_URL}/api/me/catalog/export.csv?days=${days}${eventFilter ? `&event_type=${eventFilter}` : ""}`}
            target="_blank" rel="noreferrer"
            className="px-3 py-2 bg-emerald-50 text-emerald-700 hover:bg-emerald-100 border border-emerald-200 rounded-lg text-sm flex items-center gap-1"
            data-testid="catalog-stats-export-csv"
            title="Télécharger les événements en CSV"
          >
            <Download size={14} /> CSV
          </a>
          <button
            onClick={() => { loadStats(); loadHistory(); }}
            className="p-2 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-lg"
            title="Actualiser"
            data-testid="catalog-stats-refresh"
          >
            <RefreshCw size={16} />
          </button>
        </div>
      </div>

      {loading ? (
        <div className="text-center py-12 text-slate-400 italic text-sm">
          <Loader2 size={20} className="inline animate-spin mr-2" />
          Chargement…
        </div>
      ) : !stats ? (
        <div className="text-center py-12 text-slate-400 italic text-sm">Aucune donnée.</div>
      ) : (
        <>
          {/* KPI Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            <KpiCard
              icon={ShoppingBag}
              label="Vues catalogue"
              value={stats.global_catalog_views}
              sub={`Hits sur /catalogue · ${days}j`}
              accent="bg-slate-50 border-slate-200 text-slate-700"
            />
            <KpiCard
              icon={Eye}
              label="Aperçus produits"
              value={stats.tenant_event_totals.og_fetches}
              sub="Liens partagés ouverts"
              accent="bg-blue-50 border-blue-200 text-blue-800"
            />
            <KpiCard
              icon={Share2}
              label="Partages"
              value={stats.tenant_event_totals.shares}
              sub={`${stats.funnel.share_rate}% des aperçus`}
              accent="bg-violet-50 border-violet-200 text-violet-800"
            />
            <KpiCard
              icon={Sparkles}
              label="Devis demandés"
              value={stats.tenant_event_totals.quote_clicks}
              sub={`${stats.funnel.quote_rate}% des aperçus`}
              accent="bg-emerald-50 border-emerald-200 text-emerald-800"
            />
          </div>

          {/* Iter38o — Pending quotes alert */}
          {(stats.pending_quotes_alerts || []).length > 0 && (
            <div className="rounded-xl border-2 border-amber-300 bg-amber-50 p-4 mb-6" data-testid="catalog-stats-pending-alerts">
              <div className="flex items-center gap-2 mb-3">
                <AlertTriangle className="text-amber-700" size={20} />
                <h2 className="text-sm font-bold text-amber-900">
                  {stats.pending_quotes_alerts.length} produit(s) avec demandes de devis non traitées (&gt;10)
                </h2>
              </div>
              <div className="space-y-2">
                {stats.pending_quotes_alerts.map((p) => (
                  <div key={p.product_id} className="flex items-center justify-between bg-white rounded-lg p-3" data-testid={`pending-alert-${p.product_id}`}>
                    <div className="flex-1">
                      <div className="font-semibold text-slate-900">{p.product_name}</div>
                      <div className="text-xs text-slate-500">
                        SKU: {p.product_sku} · {p.pending_count} demande(s) en attente · plus ancienne : {fmtDate(p.oldest_at)}
                      </div>
                    </div>
                    <button
                      onClick={async () => {
                        try {
                          await apiClient.post("/me/catalog/quotes/mark-treated", { product_id: p.product_id });
                          toast.success("Demandes marquées comme traitées");
                          loadStats();
                        } catch (err) {
                          toast.error(err?.response?.data?.detail || "Erreur");
                        }
                      }}
                      data-testid={`mark-treated-${p.product_id}`}
                      className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white text-xs rounded-lg flex items-center gap-1"
                    >
                      <CheckCircle2 size={12} /> Marquer traitées
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Funnel */}
          <div className="bg-white rounded-xl border border-slate-200 p-5 mb-6" data-testid="catalog-stats-funnel">
            <h2 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
              <TrendingUp size={16} className="text-emerald-600" /> Tunnel de conversion
            </h2>
            <FunnelBar label="Aperçus produits" value={stats.funnel.og_fetches} max={stats.funnel.og_fetches || 1} color="bg-blue-500" />
            <FunnelBar label="Partages" value={stats.funnel.shares} max={stats.funnel.og_fetches || 1} color="bg-violet-500" />
            <FunnelBar label="Demandes de devis" value={stats.funnel.quote_clicks} max={stats.funnel.og_fetches || 1} color="bg-emerald-500" />
            <p className="text-xs text-slate-400 mt-2">Rapport partages → aperçus : <strong>{stats.funnel.share_rate}%</strong> · Rapport devis → aperçus : <strong>{stats.funnel.quote_rate}%</strong></p>
          </div>

          {/* Top products */}
          <div className="bg-white rounded-xl border border-slate-200 p-5 mb-6" data-testid="catalog-stats-top">
            <h2 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
              <ShoppingBag size={16} className="text-emerald-600" /> Top 5 produits
            </h2>
            {stats.top_products.length === 0 ? (
              <p className="text-sm text-slate-400 italic">Aucune interaction enregistrée sur les {days} derniers jours.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-xs text-slate-500 border-b border-slate-200">
                    <tr>
                      <th className="px-3 py-2 text-left">#</th>
                      <th className="px-3 py-2 text-left">Produit</th>
                      <th className="px-3 py-2 text-left">SKU</th>
                      <th className="px-3 py-2 text-right">Aperçus</th>
                      <th className="px-3 py-2 text-right">Partages</th>
                      <th className="px-3 py-2 text-right">Devis</th>
                      <th className="px-3 py-2 text-right">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stats.top_products.map((p, idx) => (
                      <tr key={p.product_id} className="border-t border-slate-100" data-testid={`catalog-top-product-${p.product_id}`}>
                        <td className="px-3 py-2 font-bold text-slate-400">{idx + 1}</td>
                        <td className="px-3 py-2 font-medium text-slate-900">{p.product_name}</td>
                        <td className="px-3 py-2 font-mono text-xs text-slate-500">{p.product_sku}</td>
                        <td className="px-3 py-2 text-right text-blue-700 font-semibold">{fmtNum(p.views)}</td>
                        <td className="px-3 py-2 text-right text-violet-700 font-semibold">{fmtNum(p.shares)}</td>
                        <td className="px-3 py-2 text-right text-emerald-700 font-semibold">{fmtNum(p.quotes)}</td>
                        <td className="px-3 py-2 text-right font-bold text-slate-900">{fmtNum(p.total)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Daily timeline (sparklines) */}
          <div className="bg-white rounded-xl border border-slate-200 p-5 mb-6" data-testid="catalog-stats-timeline">
            <h2 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
              <Clock size={16} className="text-emerald-600" /> Évolution quotidienne
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <p className="text-xs text-blue-700 mb-1">Aperçus / jour</p>
                <Sparkline data={stats.timeline} accessor={(d) => d.og_fetches} color="#3b82f6" />
              </div>
              <div>
                <p className="text-xs text-violet-700 mb-1">Partages / jour</p>
                <Sparkline data={stats.timeline} accessor={(d) => d.shares} color="#8b5cf6" />
              </div>
              <div>
                <p className="text-xs text-emerald-700 mb-1">Devis / jour</p>
                <Sparkline data={stats.timeline} accessor={(d) => d.quotes} color="#10b981" />
              </div>
            </div>
          </div>
        </>
      )}

      {/* History */}
      <div className="bg-white rounded-xl border border-slate-200 p-5" data-testid="catalog-stats-history">
        <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
          <h2 className="text-sm font-semibold text-slate-700 flex items-center gap-2">
            <History size={16} className="text-emerald-600" /> Historique des événements ({history.length})
          </h2>
          <div className="flex items-center gap-2">
            <Filter size={14} className="text-slate-400" />
            <select
              value={eventFilter}
              onChange={(e) => setEventFilter(e.target.value)}
              data-testid="catalog-history-filter"
              className="px-3 py-1.5 border border-slate-200 rounded text-xs bg-white"
            >
              <option value="">Tous les types</option>
              <option value="catalog_view">Vue catalogue</option>
              <option value="product_og_fetch">Aperçus produits</option>
              <option value="product_share">Partages</option>
              <option value="product_quote_click">Devis demandés</option>
            </select>
          </div>
        </div>
        {historyLoading ? (
          <div className="text-center py-6 text-slate-400 italic text-sm">Chargement…</div>
        ) : history.length === 0 ? (
          <div className="text-center py-6 text-slate-400 italic text-sm">Aucun événement sur la période.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-slate-500 border-b border-slate-200">
                <tr>
                  <th className="px-3 py-2 text-left">Date</th>
                  <th className="px-3 py-2 text-left">Événement</th>
                  <th className="px-3 py-2 text-left">Produit</th>
                  <th className="px-3 py-2 text-left">SKU</th>
                  <th className="px-3 py-2 text-left">Provenance</th>
                </tr>
              </thead>
              <tbody>
                {history.map((e) => {
                  const meta = EVENT_LABELS[e.event_type] || { label: e.event_type, color: "bg-slate-100 text-slate-700" };
                  return (
                    <tr key={e.id} className="border-t border-slate-100" data-testid={`catalog-history-row-${e.id}`}>
                      <td className="px-3 py-2 text-xs text-slate-600 whitespace-nowrap">{fmtDate(e.created_at)}</td>
                      <td className="px-3 py-2"><span className={`px-2 py-0.5 rounded text-xs ${meta.color}`}>{meta.label}</span></td>
                      <td className="px-3 py-2 text-slate-700">{e.product_name || "—"}</td>
                      <td className="px-3 py-2 font-mono text-xs text-slate-500">{e.product_sku || "—"}</td>
                      <td className="px-3 py-2 text-xs text-slate-500 truncate max-w-[200px]" title={e.referrer || e.user_agent}>
                        {e.referrer ? new URL(e.referrer, "http://x").host : (e.user_agent || "").slice(0, 30)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function FunnelBar({ label, value, max, color }) {
  const pct = Math.round((value / max) * 100);
  return (
    <div className="mb-2 last:mb-0">
      <div className="flex items-center justify-between text-xs mb-1">
        <span className="text-slate-600">{label}</span>
        <span className="text-slate-900 font-semibold">{fmtNum(value)}</span>
      </div>
      <div className="w-full bg-slate-100 rounded-full h-2">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
