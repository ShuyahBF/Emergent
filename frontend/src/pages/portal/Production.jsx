/**
 * Iter43-fix24az-f (2026-02-26) — Production page for Fabricant tenants.
 *
 * 3 onglets simples :
 *   1. Intrants (matières premières + eau + électricité + main d'œuvre …)
 *   2. Recettes (produits fabriqués, coût de revient auto, marge/prix vente)
 *   3. Paramètres (marge par défaut, export global)
 *
 * Le calcul est temps réel : dès qu'un intrant est modifié, toutes les
 * recettes qui l'utilisent voient leur coût recalculé au prochain load.
 * L'export PDF (global ou par recette) délègue à reportlab côté serveur.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Factory, Plus, Trash2, Pencil, Save, X, Download, FileText, Copy,
  Package, Droplet, Zap, User as UserIcon, Cog, BarChart3, Loader2,
  DollarSign, Percent, ArrowRightLeft, PieChart as PieIcon, TrendingUp,
  Trophy, AlertTriangle, LineChart as LineIcon,
} from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer,
  PieChart, Pie, Cell, LineChart, Line, CartesianGrid,
} from "recharts";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const CATEGORIES = [
  { value: "raw_material", label: "Matière première", icon: Package, color: "#4f46e5" },
  { value: "packaging", label: "Emballage / flaconnage", icon: Package, color: "#0891b2" },
  { value: "water", label: "Eau", icon: Droplet, color: "#0284c7" },
  { value: "electricity", label: "Électricité", icon: Zap, color: "#f59e0b" },
  { value: "labor", label: "Main d'œuvre", icon: UserIcon, color: "#dc2626" },
  { value: "amortization", label: "Amortissement machines", icon: Cog, color: "#6b7280" },
  { value: "other", label: "Autre", icon: Package, color: "#78716c" },
];

const UNITS = ["ml", "g", "kg", "L", "m3", "kWh", "h", "min", "unit", "pct"];

const cat = (v) => CATEGORIES.find((c) => c.value === v) || CATEGORIES[0];

export default function Production() {
  const [tab, setTab] = useState("recipes");
  const [intrants, setIntrants] = useState([]);
  const [recipes, setRecipes] = useState([]);
  const [summary, setSummary] = useState(null);
  const [settings, setSettings] = useState({ production_default_margin_pct: 42 });
  const [loading, setLoading] = useState(true);
  const [editingIntrant, setEditingIntrant] = useState(null);
  const [editingRecipe, setEditingRecipe] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ri, rr, rs] = await Promise.all([
        apiClient.get("/production/intrants"),
        apiClient.get("/production/recipes"),
        apiClient.get("/production/settings"),
      ]);
      setIntrants(ri.data?.items || []);
      setRecipes(rr.data?.items || []);
      setSummary(rr.data?.summary || null);
      setSettings({ production_default_margin_pct: rs.data?.production_default_margin_pct ?? 42 });
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur chargement");
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <header className="flex items-center gap-3">
        <Factory className="h-7 w-7 text-indigo-600" />
        <div>
          <h1 className="text-2xl font-display font-bold">Production</h1>
          <p className="text-xs text-slate-500">Prix de revient, marge et prix public — calcul temps réel</p>
        </div>
      </header>

      <nav className="flex flex-wrap gap-1 border-b border-slate-200">
        {[
          { id: "recipes", label: "Recettes", icon: Factory },
          { id: "intrants", label: `Intrants (${intrants.length})`, icon: Package },
          { id: "analytics", label: "Analyses", icon: BarChart3 },
          { id: "settings", label: "Paramètres", icon: Cog },
        ].map((t) => {
          const Icon = t.icon;
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`text-sm px-4 py-2 rounded-t inline-flex items-center gap-1.5 ${tab === t.id ? "bg-indigo-50 text-indigo-700 font-semibold border-b-2 border-indigo-600" : "text-slate-600 hover:bg-slate-50"}`}
              data-testid={`production-tab-${t.id}`}
            >
              <Icon className="h-4 w-4" /> {t.label}
            </button>
          );
        })}
      </nav>

      {loading ? (
        <div className="py-16 text-center text-slate-400"><Loader2 className="h-6 w-6 animate-spin inline mr-2" /> Chargement…</div>
      ) : (
        <>
          {tab === "recipes" && (
            <RecipesTab
              recipes={recipes}
              summary={summary}
              intrants={intrants}
              defaultMargin={settings.production_default_margin_pct}
              onEdit={setEditingRecipe}
              onDelete={async (id) => {
                if (!window.confirm("Supprimer cette recette ?")) return;
                try {
                  await apiClient.delete(`/production/recipes/${id}`);
                  toast.success("Recette supprimée"); await load();
                } catch (e) { toast.error(e?.response?.data?.detail || "Échec"); }
              }}
              onDuplicate={async (id) => {
                try {
                  const r = await apiClient.post(`/production/recipes/${id}/duplicate`);
                  toast.success("Recette dupliquée — définissez le dosage puis enregistrez");
                  await load();
                  setEditingRecipe(r.data); // open the copy so user sets the dosage
                } catch (e) { toast.error(e?.response?.data?.detail || "Échec de la duplication"); }
              }}
              onExportRecipe={(id) => window.open(`${process.env.REACT_APP_BACKEND_URL}/api/production/export/recipe/${id}.pdf`, "_blank")}
              onExportAll={() => window.open(`${process.env.REACT_APP_BACKEND_URL}/api/production/export/recipes.pdf`, "_blank")}
            />
          )}
          {tab === "intrants" && (
            <IntrantsTab
              intrants={intrants}
              onEdit={setEditingIntrant}
              onDelete={async (id) => {
                if (!window.confirm("Supprimer cet intrant ? (refusé s'il est utilisé dans une recette)")) return;
                try {
                  await apiClient.delete(`/production/intrants/${id}`);
                  toast.success("Intrant supprimé"); await load();
                } catch (e) { toast.error(e?.response?.data?.detail || "Échec"); }
              }}
            />
          )}
          {tab === "analytics" && (
            <AnalyticsTab recipes={recipes} summary={summary} />
          )}
          {tab === "settings" && (
            <SettingsTab
              settings={settings}
              onSave={async (v) => {
                try {
                  await apiClient.put("/production/settings", { production_default_margin_pct: v });
                  toast.success("Marge par défaut enregistrée"); await load();
                } catch (e) { toast.error(e?.response?.data?.detail || "Échec"); }
              }}
            />
          )}
        </>
      )}

      {editingIntrant && (
        <IntrantModal
          intrant={editingIntrant}
          onClose={() => setEditingIntrant(null)}
          onSaved={async () => { setEditingIntrant(null); await load(); }}
        />
      )}
      {editingRecipe && (
        <RecipeModal
          recipe={editingRecipe}
          intrants={intrants}
          defaultMargin={settings.production_default_margin_pct}
          onClose={() => setEditingRecipe(null)}
          onSaved={async () => { setEditingRecipe(null); await load(); }}
        />
      )}
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Recipes tab                                                               */
/* ────────────────────────────────────────────────────────────────────────── */
const RecipesTab = ({ recipes, summary, intrants, defaultMargin, onEdit, onDelete, onDuplicate, onExportRecipe, onExportAll }) => (
  <div className="space-y-4">
    <div className="flex flex-wrap items-center gap-2">
      <button
        onClick={() => onEdit({ __new: true, name: "", pricing_mode: "margin_first", margin_pct: defaultMargin, output_batch_units: 1, output_unit_label: "unit", intrants: [] })}
        className="text-sm px-3 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white inline-flex items-center gap-1 font-semibold"
        data-testid="production-new-recipe"
      ><Plus className="h-4 w-4" /> Nouvelle recette</button>
      <button
        onClick={onExportAll}
        disabled={recipes.length === 0}
        className="text-sm px-3 py-2 rounded-lg bg-white ring-1 ring-slate-300 hover:bg-slate-50 inline-flex items-center gap-1 disabled:opacity-50"
        data-testid="production-export-all"
      ><FileText className="h-4 w-4" /> Exporter tout (PDF)</button>
    </div>

    {summary && recipes.length > 0 && (
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <KpiCard label="Recettes" value={summary.total_recipes} color="#4f46e5" icon={Factory} />
        <KpiCard label="Coût moyen" value={summary.avg_cost_price?.toLocaleString("fr-FR", { maximumFractionDigits: 0 }) + " CFA"} color="#0284c7" icon={DollarSign} />
        <KpiCard label="Prix public moyen" value={summary.avg_public_price?.toLocaleString("fr-FR", { maximumFractionDigits: 0 }) + " CFA"} color="#0891b2" icon={DollarSign} />
        <KpiCard label="Marge moyenne" value={(summary.avg_margin_pct || 0).toFixed(1) + " %"} color="#059669" icon={Percent} />
      </div>
    )}

    {recipes.length === 0 ? (
      <div className="rounded-xl ring-1 ring-slate-200 bg-white p-8 text-center text-sm text-slate-500">
        Aucune recette. Commencez par créer des <strong>intrants</strong> (onglet Intrants), puis créez une <strong>recette</strong> en cochant les intrants nécessaires avec leurs quantités.
      </div>
    ) : (
      <div className="overflow-x-auto rounded-xl ring-1 ring-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-600">
            <tr>
              <th className="text-left px-3 py-2">Produit</th>
              <th className="text-left px-3 py-2">Variante</th>
              <th className="text-right px-3 py-2">Batch</th>
              <th className="text-right px-3 py-2">Prix revient</th>
              <th className="text-right px-3 py-2">Marge %</th>
              <th className="text-right px-3 py-2">Prix public</th>
              <th className="text-right px-3 py-2">Bénéfice</th>
              <th className="text-right px-3 py-2">Actions</th>
            </tr>
          </thead>
          <tbody data-testid="production-recipes-body">
            {recipes.map((r) => (
              <tr key={r.id} className="border-t border-slate-100 hover:bg-slate-50">
                <td className="px-3 py-2 font-semibold">{r.name}</td>
                <td className="px-3 py-2 text-slate-600">{r.variant_label || "—"}</td>
                <td className="px-3 py-2 text-right text-xs">{r.output_batch_units} {r.output_unit_label}</td>
                <td className="px-3 py-2 text-right font-mono">{r.cost_price?.toLocaleString("fr-FR", { maximumFractionDigits: 2 })}</td>
                <td className="px-3 py-2 text-right"><span className="inline-block px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 text-xs font-semibold">{r.margin_pct?.toFixed(1)}%</span></td>
                <td className="px-3 py-2 text-right font-mono font-bold">{r.public_price?.toLocaleString("fr-FR", { maximumFractionDigits: 2 })}</td>
                <td className="px-3 py-2 text-right font-mono text-emerald-700">{r.profit_per_unit?.toLocaleString("fr-FR", { maximumFractionDigits: 2 })}</td>
                <td className="px-3 py-2 text-right space-x-1">
                  <button onClick={() => onEdit(r)} className="p-1 rounded hover:bg-indigo-100 text-indigo-600" title="Éditer" data-testid={`production-edit-recipe-${r.id}`}><Pencil className="h-3.5 w-3.5" /></button>
                  <button onClick={() => onDuplicate(r.id)} className="p-1 rounded hover:bg-fuchsia-100 text-fuchsia-600" title="Dupliquer (sans dosage)" data-testid={`production-duplicate-recipe-${r.id}`}><Copy className="h-3.5 w-3.5" /></button>
                  <button onClick={() => onExportRecipe(r.id)} className="p-1 rounded hover:bg-slate-200" title="Fiche PDF"><Download className="h-3.5 w-3.5" /></button>
                  <button onClick={() => onDelete(r.id)} className="p-1 rounded hover:bg-rose-100 text-rose-600" title="Supprimer"><Trash2 className="h-3.5 w-3.5" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )}
  </div>
);

const KpiCard = ({ label, value, color, icon: Icon }) => (
  <div className="rounded-xl ring-1 ring-slate-200 bg-white p-3 flex items-center gap-3">
    <div className="rounded-lg p-2" style={{ background: `${color}15`, color }}><Icon className="h-5 w-5" /></div>
    <div>
      <p className="text-[10px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className="text-lg font-bold" style={{ color }}>{value}</p>
    </div>
  </div>
);

/* ────────────────────────────────────────────────────────────────────────── */
/* Analytics tab — Recharts visualisations                                   */
/* ────────────────────────────────────────────────────────────────────────── */
const fmtCFA = (v) =>
  (Number.isFinite(Number(v)) ? Number(v) : 0).toLocaleString("fr-FR", { maximumFractionDigits: 0 });
const fmtCFA2 = (v) =>
  (Number.isFinite(Number(v)) ? Number(v) : 0).toLocaleString("fr-FR", { maximumFractionDigits: 2 });

const ChartTooltip = ({ active, payload, label, suffix = " CFA" }) => {
  if (!active || !payload || !payload.length) return null;
  return (
    <div className="rounded-lg bg-white ring-1 ring-slate-300 shadow-lg px-3 py-2 text-xs">
      {label && <p className="font-semibold text-slate-800 mb-1">{label}</p>}
      {payload.map((p, idx) => (
        <p key={idx} className="flex items-center gap-2 font-mono" style={{ color: p.color || p.payload?.color }}>
          <span className="inline-block h-2 w-2 rounded-sm" style={{ background: p.color || p.payload?.color }} />
          <span className="text-slate-600">{p.name}</span>
          <span className="font-bold">{fmtCFA2(p.value)}{suffix}</span>
        </p>
      ))}
    </div>
  );
};

const LineChartTooltip = ({ active, payload }) => {
  if (!active || !payload || !payload.length) return null;
  const row = payload[0].payload;
  return (
    <div className="rounded-lg bg-white ring-1 ring-slate-300 shadow-lg px-3 py-2 text-xs">
      <p className="font-semibold text-slate-800 mb-1">{row.name}</p>
      <p className="text-slate-500">{row.date}</p>
      <p className="font-mono text-sky-700">Coût : {fmtCFA2(row.cost)} CFA</p>
      <p className="font-mono text-emerald-700">Prix : {fmtCFA2(row.price)} CFA</p>
    </div>
  );
};

const AnalyticsTab = ({ recipes, summary }) => {
  const [selected, setSelected] = useState(() => new Set());
  // Initialize selection: keep top-10 highest-cost recipes selected by default
  useEffect(() => {
    if (recipes.length === 0) return;
    const top = [...recipes].sort((a, b) => (b.cost_price || 0) - (a.cost_price || 0)).slice(0, 10);
    setSelected(new Set(top.map((r) => r.id)));
  }, [recipes]);

  const toggle = (id) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  const selectAll = () => setSelected(new Set(recipes.map((r) => r.id)));
  const selectNone = () => setSelected(new Set());

  // Enriched KPI cards
  const analytics = useMemo(() => {
    if (recipes.length === 0) return null;
    const sorted = [...recipes];
    const mostProfitable = sorted.slice().sort((a, b) => (b.profit_per_unit || 0) - (a.profit_per_unit || 0))[0];
    const leastProfitable = sorted.slice().sort((a, b) => (a.margin_pct || 0) - (b.margin_pct || 0))[0];
    const mostExpensive = sorted.slice().sort((a, b) => (b.cost_price || 0) - (a.cost_price || 0))[0];
    const uniqueIntrants = new Set();
    recipes.forEach((r) => (r.intrants || []).forEach((i) => uniqueIntrants.add(i.intrant_id)));
    const totalBatchCost = recipes.reduce((s, r) => s + (r.intrants_total_batch || 0), 0);
    return { mostProfitable, leastProfitable, mostExpensive, uniqueIntrantsCount: uniqueIntrants.size, totalBatchCost };
  }, [recipes]);

  // BarChart data — recipes selected
  const barData = useMemo(
    () =>
      recipes
        .filter((r) => selected.has(r.id))
        .map((r) => ({
          name: r.variant_label ? `${r.name} — ${r.variant_label}` : r.name,
          cost: Number((r.cost_price || 0).toFixed(2)),
          price: Number((r.public_price || 0).toFixed(2)),
          profit: Number((r.profit_per_unit || 0).toFixed(2)),
        })),
    [recipes, selected],
  );

  // PieChart — aggregated cost per category across ALL recipes
  // Iter43-fix24az-h + fix24az-l (2026-02-26) — dosage-aware :
  //   * new model (dosage_number>0) :
  //       - packaging/other  → cost = unit_cost (fixed, does NOT scale)
  //       - other categories → cost = unit_cost × dosage_number
  //   * legacy : cost = quantity × unit_cost
  const _FIXED_CATS_ANALYTICS = new Set(["packaging", "other"]);
  const pieData = useMemo(() => {
    const acc = {};
    recipes.forEach((r) => {
      const dosageNum = Number(r.dosage_number) || 0;
      const useDosage = dosageNum > 0;
      (r.intrants || []).forEach((it) => {
        const c = it.category_snapshot || "raw_material";
        const uc = Number(it.unit_cost_snapshot) || 0;
        let cost;
        if (useDosage) {
          cost = _FIXED_CATS_ANALYTICS.has(c) ? uc : uc * dosageNum;
        } else {
          cost = uc * (Number(it.quantity) || 0);
        }
        acc[c] = (acc[c] || 0) + cost;
      });
    });
    return CATEGORIES.map((c) => ({
      name: c.label,
      value: Number((acc[c.value] || 0).toFixed(4)),
      color: c.color,
      key: c.value,
    })).filter((d) => d.value > 0);
  }, [recipes]);
  const pieTotal = useMemo(() => pieData.reduce((s, d) => s + d.value, 0), [pieData]);

  // LineChart — cost evolution over time (recipes chronologically by created_at)
  const lineData = useMemo(
    () =>
      [...recipes]
        .filter((r) => r.created_at)
        .sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)))
        .map((r) => {
          const d = new Date(r.created_at);
          const label = Number.isNaN(d.valueOf())
            ? r.name
            : d.toLocaleDateString("fr-FR", { month: "short", day: "2-digit" });
          return {
            name: r.name,
            date: label,
            cost: Number((r.cost_price || 0).toFixed(2)),
            price: Number((r.public_price || 0).toFixed(2)),
          };
        }),
    [recipes],
  );

  if (recipes.length === 0) {
    return (
      <div className="rounded-xl ring-1 ring-slate-200 bg-white p-8 text-center text-sm text-slate-500" data-testid="analytics-empty">
        <BarChart3 className="h-8 w-8 mx-auto mb-2 text-slate-300" />
        Aucune donnée analytique. Créez au moins une recette pour visualiser les analyses.
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="production-analytics">
      {/* KPI cards */}
      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
          <KpiCard label="Recettes" value={summary.total_recipes} color="#4f46e5" icon={Factory} />
          <KpiCard label="Coût moyen" value={fmtCFA(summary.avg_cost_price) + " CFA"} color="#0284c7" icon={DollarSign} />
          <KpiCard label="Prix public moyen" value={fmtCFA(summary.avg_public_price) + " CFA"} color="#0891b2" icon={DollarSign} />
          <KpiCard label="Marge moyenne" value={(summary.avg_margin_pct || 0).toFixed(1) + " %"} color="#059669" icon={Percent} />
          {analytics && (
            <KpiCard label="Intrants distincts" value={analytics.uniqueIntrantsCount} color="#7c3aed" icon={Package} />
          )}
          {analytics && (
            <KpiCard label="Coût cumulé batches" value={fmtCFA(analytics.totalBatchCost) + " CFA"} color="#dc2626" icon={TrendingUp} />
          )}
        </div>
      )}
      {/* Highlight cards */}
      {analytics && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
          <HighlightCard
            testid="analytics-highlight-top"
            icon={Trophy}
            color="#059669"
            label="Recette la plus rentable"
            title={analytics.mostProfitable?.name || "—"}
            subtitle={
              analytics.mostProfitable
                ? `Bénéfice/unité : ${fmtCFA2(analytics.mostProfitable.profit_per_unit)} CFA`
                : ""
            }
          />
          <HighlightCard
            testid="analytics-highlight-expensive"
            icon={DollarSign}
            color="#dc2626"
            label="Coût de revient le plus élevé"
            title={analytics.mostExpensive?.name || "—"}
            subtitle={
              analytics.mostExpensive
                ? `${fmtCFA2(analytics.mostExpensive.cost_price)} CFA / unité`
                : ""
            }
          />
          <HighlightCard
            testid="analytics-highlight-low"
            icon={AlertTriangle}
            color="#f59e0b"
            label="Marge la plus faible"
            title={analytics.leastProfitable?.name || "—"}
            subtitle={
              analytics.leastProfitable
                ? `Marge : ${(analytics.leastProfitable.margin_pct || 0).toFixed(1)} %`
                : ""
            }
          />
        </div>
      )}

      {/* BarChart + selector */}
      <div className="rounded-xl ring-1 ring-slate-200 bg-white p-4">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold inline-flex items-center gap-1.5"><BarChart3 className="h-4 w-4 text-indigo-600" /> Coût de revient vs Prix public</h3>
          <div className="flex items-center gap-1 text-xs">
            <button onClick={selectAll} className="px-2 py-1 rounded bg-slate-100 hover:bg-slate-200" data-testid="analytics-select-all">Tout</button>
            <button onClick={selectNone} className="px-2 py-1 rounded bg-slate-100 hover:bg-slate-200" data-testid="analytics-select-none">Aucune</button>
            <span className="text-slate-500 ml-2">{selected.size}/{recipes.length}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-1 mb-3 max-h-24 overflow-y-auto p-1 rounded bg-slate-50 ring-1 ring-slate-200">
          {recipes.map((r) => {
            const on = selected.has(r.id);
            return (
              <label
                key={r.id}
                className={`text-[11px] px-2 py-1 rounded cursor-pointer inline-flex items-center gap-1 ${on ? "bg-indigo-600 text-white" : "bg-white ring-1 ring-slate-300 text-slate-700 hover:bg-slate-100"}`}
                data-testid={`analytics-recipe-toggle-${r.id}`}
              >
                <input type="checkbox" checked={on} onChange={() => toggle(r.id)} className="hidden" />
                {r.name}{r.variant_label ? ` — ${r.variant_label}` : ""}
              </label>
            );
          })}
        </div>
        {barData.length === 0 ? (
          <div className="py-8 text-center text-xs text-slate-400">Cochez au moins une recette ci-dessus.</div>
        ) : (
          <div className="h-96" data-testid="analytics-bar-chart">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={barData} margin={{ top: 8, right: 12, left: 0, bottom: 80 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis
                  dataKey="name"
                  interval={0}
                  tick={{ fontSize: 10, fill: "#475569" }}
                  angle={-28}
                  textAnchor="end"
                  height={90}
                />
                <YAxis tick={{ fontSize: 11, fill: "#475569" }} tickFormatter={(v) => fmtCFA(v)} />
                <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(79,70,229,0.05)" }} />
                <Legend verticalAlign="top" align="right" wrapperStyle={{ fontSize: 11, paddingBottom: 8 }} />
                <Bar dataKey="cost" name="Coût de revient" fill="#0284c7" radius={[4, 4, 0, 0]} />
                <Bar dataKey="price" name="Prix public" fill="#059669" radius={[4, 4, 0, 0]} />
                <Bar dataKey="profit" name="Bénéfice" fill="#f59e0b" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* PieChart — aggregate categories */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="rounded-xl ring-1 ring-slate-200 bg-white p-4">
          <h3 className="text-sm font-semibold inline-flex items-center gap-1.5 mb-2"><PieIcon className="h-4 w-4 text-fuchsia-600" /> Répartition des coûts par catégorie</h3>
          <p className="text-[11px] text-slate-500 mb-2">Vue agrégée sur toutes les recettes ({recipes.length}).</p>
          {pieData.length === 0 ? (
            <div className="py-8 text-center text-xs text-slate-400">Aucune donnée à afficher.</div>
          ) : (
            <div className="h-80" data-testid="analytics-pie-chart">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={pieData}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    innerRadius={55}
                    outerRadius={110}
                    paddingAngle={2}
                    label={({ percent }) => (percent > 0.05 ? `${(percent * 100).toFixed(0)}%` : "")}
                    labelLine={false}
                  >
                    {pieData.map((d) => (<Cell key={d.key} fill={d.color} />))}
                  </Pie>
                  <Tooltip content={<ChartTooltip />} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}
          {pieTotal > 0 && (
            <p className="text-[11px] text-slate-500 mt-2 text-center">
              Total des coûts intrants (tous batches confondus) : <span className="font-mono font-bold text-slate-800">{fmtCFA(pieTotal)} CFA</span>
            </p>
          )}
        </div>

        {/* Category legend as list */}
        <div className="rounded-xl ring-1 ring-slate-200 bg-white p-4">
          <h3 className="text-sm font-semibold mb-2 inline-flex items-center gap-1.5"><Package className="h-4 w-4 text-slate-600" /> Détail par catégorie</h3>
          {pieData.length === 0 ? (
            <div className="py-8 text-center text-xs text-slate-400">Aucune donnée.</div>
          ) : (
            <ul className="text-xs space-y-1.5" data-testid="analytics-category-list">
              {pieData
                .slice()
                .sort((a, b) => b.value - a.value)
                .map((d) => {
                  const pct = pieTotal > 0 ? (d.value / pieTotal) * 100 : 0;
                  return (
                    <li key={d.key} className="flex items-center gap-2">
                      <span className="inline-block h-3 w-3 rounded-sm" style={{ background: d.color }} />
                      <span className="flex-1 truncate">{d.name}</span>
                      <span className="font-mono font-semibold text-slate-800">{fmtCFA(d.value)} CFA</span>
                      <span className="text-slate-500 w-12 text-right">{pct.toFixed(1)}%</span>
                    </li>
                  );
                })}
            </ul>
          )}
        </div>
      </div>

      {/* LineChart — cost evolution */}
      <div className="rounded-xl ring-1 ring-slate-200 bg-white p-4">
        <h3 className="text-sm font-semibold inline-flex items-center gap-1.5 mb-1"><LineIcon className="h-4 w-4 text-emerald-600" /> Évolution des coûts dans le temps</h3>
        <p className="text-[11px] text-slate-500 mb-2">Recettes ordonnées par date de création — utile pour détecter l&apos;inflation ou l&apos;amélioration des marges.</p>
        {lineData.length === 0 ? (
          <div className="py-8 text-center text-xs text-slate-400">Pas encore d&apos;historique disponible.</div>
        ) : (
          <div className="h-72" data-testid="analytics-line-chart">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={lineData} margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#475569" }} />
                <YAxis tick={{ fontSize: 11, fill: "#475569" }} tickFormatter={(v) => fmtCFA(v)} />
                <Tooltip content={<LineChartTooltip />} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line type="monotone" dataKey="cost" name="Coût de revient" stroke="#0284c7" strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} />
                <Line type="monotone" dataKey="price" name="Prix public" stroke="#059669" strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  );
};

const HighlightCard = ({ icon: Icon, color, label, title, subtitle, testid }) => (
  <div
    className="rounded-xl ring-1 ring-slate-200 bg-white p-3 flex items-center gap-3"
    data-testid={testid}
  >
    <div className="rounded-lg p-2" style={{ background: `${color}15`, color }}>
      <Icon className="h-5 w-5" />
    </div>
    <div className="min-w-0">
      <p className="text-[10px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className="text-sm font-bold text-slate-800 truncate" title={title}>{title}</p>
      <p className="text-[11px] text-slate-500 truncate">{subtitle}</p>
    </div>
  </div>
);


/* ────────────────────────────────────────────────────────────────────────── */
/* Intrants tab                                                              */
/* ────────────────────────────────────────────────────────────────────────── */
const IntrantsTab = ({ intrants, onEdit, onDelete }) => {
  // Group by category for readability
  const grouped = useMemo(() => {
    const g = {};
    CATEGORIES.forEach((c) => { g[c.value] = []; });
    intrants.forEach((i) => { (g[i.category] = g[i.category] || []).push(i); });
    return g;
  }, [intrants]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <button
          onClick={() => onEdit({ __new: true, name: "", unit: "ml", unit_cost: 0, category: "raw_material" })}
          className="text-sm px-3 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white inline-flex items-center gap-1 font-semibold"
          data-testid="production-new-intrant"
        ><Plus className="h-4 w-4" /> Nouvel intrant</button>
      </div>

      {intrants.length === 0 ? (
        <div className="rounded-xl ring-1 ring-slate-200 bg-white p-8 text-center text-sm text-slate-500">
          Aucun intrant. Ajoutez d&apos;abord les matières premières (ex. ICARIDINE, ALCOOL, GLYCERINE, TWEEN20, CARBOPOL, PEG7, PERMETHRINE) et les charges (eau, électricité, main d&apos;œuvre).
        </div>
      ) : (
        CATEGORIES.map((c) => {
          const items = grouped[c.value] || [];
          if (!items.length) return null;
          const Icon = c.icon;
          return (
            <div key={c.value} className="rounded-xl ring-1 ring-slate-200 bg-white overflow-hidden">
              <div className="px-3 py-2 flex items-center gap-2" style={{ background: `${c.color}12`, borderLeft: `4px solid ${c.color}` }}>
                <Icon className="h-4 w-4" style={{ color: c.color }} />
                <h3 className="text-sm font-semibold" style={{ color: c.color }}>{c.label} ({items.length})</h3>
              </div>
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-xs uppercase text-slate-600">
                  <tr>
                    <th className="text-left px-3 py-2">Nom</th>
                    <th className="text-left px-3 py-2">Unité</th>
                    <th className="text-right px-3 py-2">Coût unitaire (CFA)</th>
                    <th className="text-right px-3 py-2">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((i) => (
                    <tr key={i.id} className="border-t border-slate-100">
                      <td className="px-3 py-2 font-medium">{i.name}</td>
                      <td className="px-3 py-2 text-slate-500 text-xs">{i.unit}</td>
                      <td className="px-3 py-2 text-right font-mono">{i.unit_cost?.toLocaleString("fr-FR", { maximumFractionDigits: 4 })}</td>
                      <td className="px-3 py-2 text-right space-x-1">
                        <button onClick={() => onEdit(i)} className="p-1 rounded hover:bg-indigo-100 text-indigo-600" data-testid={`production-edit-intrant-${i.id}`}><Pencil className="h-3.5 w-3.5" /></button>
                        <button onClick={() => onDelete(i.id)} className="p-1 rounded hover:bg-rose-100 text-rose-600"><Trash2 className="h-3.5 w-3.5" /></button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        })
      )}
    </div>
  );
};

/* ────────────────────────────────────────────────────────────────────────── */
/* Settings tab                                                              */
/* ────────────────────────────────────────────────────────────────────────── */
const SettingsTab = ({ settings, onSave }) => {
  const [m, setM] = useState(settings.production_default_margin_pct);
  useEffect(() => setM(settings.production_default_margin_pct), [settings.production_default_margin_pct]);
  return (
    <div className="rounded-xl ring-1 ring-slate-200 bg-white p-5 max-w-lg">
      <h3 className="text-sm font-semibold mb-2 inline-flex items-center gap-1"><Cog className="h-4 w-4" /> Marge bénéficiaire par défaut</h3>
      <p className="text-xs text-slate-500 mb-3">
        Utilisée pour les nouvelles recettes. Chaque recette peut ensuite être ajustée individuellement.
      </p>
      <div className="flex items-center gap-2">
        <input
          type="number" step="0.1" min="-100" max="1000"
          value={m}
          onChange={(e) => setM(Number(e.target.value))}
          className="w-24 text-right px-2 py-1.5 ring-1 ring-slate-300 rounded"
          data-testid="production-default-margin-input"
        />
        <span className="text-slate-600">%</span>
        <button
          onClick={() => onSave(m)}
          className="text-sm px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-700 text-white inline-flex items-center gap-1"
          data-testid="production-save-default-margin"
        ><Save className="h-3.5 w-3.5" /> Enregistrer</button>
      </div>
    </div>
  );
};

/* ────────────────────────────────────────────────────────────────────────── */
/* Intrant modal                                                             */
/* ────────────────────────────────────────────────────────────────────────── */
const IntrantModal = ({ intrant, onClose, onSaved }) => {
  const [f, setF] = useState({
    name: intrant.name || "",
    unit: intrant.unit || "ml",
    unit_cost: intrant.unit_cost || 0,
    category: intrant.category || "raw_material",
    notes: intrant.notes || "",
  });
  const [saving, setSaving] = useState(false);
  const save = async () => {
    if (!f.name.trim()) { toast.error("Nom requis"); return; }
    setSaving(true);
    try {
      if (intrant.__new) await apiClient.post("/production/intrants", f);
      else await apiClient.put(`/production/intrants/${intrant.id}`, f);
      toast.success("Enregistré"); onSaved();
    } catch (e) { toast.error(e?.response?.data?.detail || "Échec"); }
    finally { setSaving(false); }
  };
  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md">
        <div className="px-5 py-3 border-b border-slate-200 flex items-center justify-between">
          <h2 className="font-display font-bold">{intrant.__new ? "Nouvel intrant" : "Modifier l'intrant"}</h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-slate-100"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-3">
          <label className="block"><span className="block text-xs text-slate-600 mb-1">Nom</span>
            <input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} className="w-full text-sm px-3 py-2 ring-1 ring-slate-300 rounded" data-testid="intrant-modal-name" placeholder="ex. ICARIDINE" />
          </label>
          <label className="block"><span className="block text-xs text-slate-600 mb-1">Catégorie</span>
            <select value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} className="w-full text-sm px-3 py-2 ring-1 ring-slate-300 rounded" data-testid="intrant-modal-category">
              {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label className="block"><span className="block text-xs text-slate-600 mb-1">Unité</span>
              <select value={f.unit} onChange={(e) => setF({ ...f, unit: e.target.value })} className="w-full text-sm px-3 py-2 ring-1 ring-slate-300 rounded" data-testid="intrant-modal-unit">
                {UNITS.map((u) => <option key={u} value={u}>{u}</option>)}
              </select>
            </label>
            <label className="block"><span className="block text-xs text-slate-600 mb-1">Coût unitaire (CFA / 1 unité)</span>
              <input type="number" step="0.0001" value={f.unit_cost} onChange={(e) => setF({ ...f, unit_cost: Number(e.target.value) })} className="w-full text-sm px-3 py-2 ring-1 ring-slate-300 rounded text-right font-mono" data-testid="intrant-modal-cost" />
            </label>
          </div>
          <label className="block"><span className="block text-xs text-slate-600 mb-1">Notes (facultatif)</span>
            <textarea rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} className="w-full text-sm px-3 py-2 ring-1 ring-slate-300 rounded" />
          </label>
        </div>
        <div className="px-5 py-3 border-t border-slate-200 flex justify-end gap-2">
          <button onClick={onClose} className="text-sm px-3 py-1.5 rounded bg-slate-100 hover:bg-slate-200">Annuler</button>
          <button onClick={save} disabled={saving} className="text-sm px-3 py-1.5 rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 inline-flex items-center gap-1" data-testid="intrant-modal-save"><Save className="h-3.5 w-3.5" /> Enregistrer</button>
        </div>
      </div>
    </div>
  );
};

/* ────────────────────────────────────────────────────────────────────────── */
/* Recipe modal — real-time price computation                                */
/* ────────────────────────────────────────────────────────────────────────── */
const RecipeModal = ({ recipe, intrants, defaultMargin, onClose, onSaved }) => {
  // Iter43-fix24az-h (2026-02-26) — Cost model : each intrant's cost = unit_cost
  // × recipe.dosage_number. All intrants share the same multiplier (product volume).
  // Legacy recipes without dosage_number are handled by fallback (see below).
  const legacy = !recipe.__new && (recipe.dosage_number === undefined || recipe.dosage_number === null);
  const parsedLegacyDosage = React.useMemo(() => {
    // Try to auto-migrate from the free-text variant_label (e.g. "50 ml", "100 ml").
    if (!legacy) return { number: null, unit: null };
    const m = /^\s*(\d+(?:[.,]\d+)?)\s*(ml|g|l|kg|unit|mg)?\s*$/i.exec(recipe.variant_label || "");
    if (!m) return { number: null, unit: null };
    return { number: parseFloat(m[1].replace(",", ".")), unit: (m[2] || "ml").toLowerCase() };
  }, [legacy, recipe.variant_label]);

  const [f, setF] = useState({
    name: recipe.name || "",
    dosage_number: recipe.dosage_number ?? parsedLegacyDosage.number ?? "",
    dosage_unit: recipe.dosage_unit ?? parsedLegacyDosage.unit ?? "ml",
    output_batch_units: recipe.output_batch_units || 1,
    output_unit_label: recipe.output_unit_label || "unit",
    intrants: recipe.intrants ? recipe.intrants.map((i) => ({ intrant_id: i.intrant_id })) : [],
    pricing_mode: recipe.pricing_mode || "margin_first",
    margin_pct: recipe.margin_pct ?? defaultMargin ?? 42,
    public_price: recipe.public_price ?? 0,
    notes: recipe.notes || "",
  });
  const [saving, setSaving] = useState(false);

  // Real-time recomputation — dosage-based only (per-intrant quantity removed).
  // Iter43-fix24az-l (2026-02-26) — Packaging + other DO NOT scale with dosage.
  const _FIXED_CATEGORIES = new Set(["packaging", "other"]);
  const computed = useMemo(() => {
    const intrantsById = Object.fromEntries(intrants.map((i) => [i.id, i]));
    const dosageNum = Number(f.dosage_number) || 0;
    let costBatch = 0;
    for (const it of f.intrants) {
      const src = intrantsById[it.intrant_id];
      if (!src) continue;
      const uc = Number(src.unit_cost) || 0;
      const cat = src.category || "raw_material";
      if (_FIXED_CATEGORIES.has(cat)) {
        costBatch += uc;              // fixed per-batch (does not scale)
      } else {
        costBatch += uc * dosageNum;  // scales with dosage
      }
    }
    const batchUnits = Number(f.output_batch_units) || 1;
    const costPrice = costBatch / (batchUnits > 0 ? batchUnits : 1);
    let publicPrice = 0, marginPct = 0;
    if (f.pricing_mode === "price_first") {
      publicPrice = Number(f.public_price) || 0;
      marginPct = costPrice > 0 ? (publicPrice / costPrice - 1) * 100 : 0;
    } else {
      marginPct = Number(f.margin_pct) || 0;
      publicPrice = costPrice * (1 + marginPct / 100);
    }
    return {
      costBatch, costPrice, publicPrice, marginPct,
      profit: publicPrice - costPrice,
    };
  }, [f, intrants]);

  const toggleIntrant = (id) => {
    setF((p) => {
      const has = p.intrants.find((x) => x.intrant_id === id);
      if (has) return { ...p, intrants: p.intrants.filter((x) => x.intrant_id !== id) };
      return { ...p, intrants: [...p.intrants, { intrant_id: id }] };
    });
  };

  const save = async () => {
    if (!f.name.trim()) { toast.error("Nom du produit requis"); return; }
    if (f.intrants.length === 0) { toast.error("Cochez au moins un intrant"); return; }
    const dosageNum = Number(f.dosage_number);
    if (!(dosageNum > 0)) { toast.error("Le dosage doit être supérieur à 0"); return; }
    setSaving(true);
    try {
      const payload = {
        name: f.name,
        dosage_number: dosageNum,
        dosage_unit: f.dosage_unit,
        output_batch_units: f.output_batch_units,
        output_unit_label: f.output_unit_label,
        intrants: f.intrants.map((x) => ({ intrant_id: x.intrant_id, quantity: 0 })),
        pricing_mode: f.pricing_mode,
        margin_pct: f.margin_pct,
        public_price: f.public_price,
        notes: f.notes,
      };
      if (recipe.__new) await apiClient.post("/production/recipes", payload);
      else await apiClient.put(`/production/recipes/${recipe.id}`, payload);
      toast.success("Recette enregistrée"); onSaved();
    } catch (e) { toast.error(e?.response?.data?.detail || "Échec"); }
    finally { setSaving(false); }
  };

  const grouped = useMemo(() => {
    const g = {};
    CATEGORIES.forEach((c) => { g[c.value] = []; });
    intrants.forEach((i) => { (g[i.category] = g[i.category] || []).push(i); });
    return g;
  }, [intrants]);

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[95vh] flex flex-col">
        <div className="px-5 py-3 border-b border-slate-200 flex items-center justify-between">
          <h2 className="font-display font-bold">{recipe.__new ? "Nouvelle recette" : "Modifier la recette"}</h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-slate-100"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-4 overflow-y-auto flex-1">
          {/* Product info */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <label className="block md:col-span-2"><span className="block text-xs text-slate-600 mb-1">Nom du produit</span>
              <input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} className="w-full text-sm px-3 py-2 ring-1 ring-slate-300 rounded font-semibold" data-testid="recipe-modal-name" placeholder="ex. SPRAY ICARIDINE" />
            </label>
            {/* Iter43-fix24az-h — Dosage split : number + unit dropdown.
                Multiplier appliqué à chaque intrant = dosage_number. */}
            <label className="block"><span className="block text-xs text-slate-600 mb-1">Dosage (volume)</span>
              <input type="number" step="0.0001" min="0" value={f.dosage_number}
                     onChange={(e) => setF({ ...f, dosage_number: e.target.value })}
                     className="w-full text-sm px-3 py-2 ring-1 ring-indigo-300 rounded text-right font-mono font-bold"
                     placeholder="50" data-testid="recipe-modal-dosage-number" />
            </label>
            <label className="block"><span className="block text-xs text-slate-600 mb-1">Unité</span>
              <select value={f.dosage_unit} onChange={(e) => setF({ ...f, dosage_unit: e.target.value })}
                      className="w-full text-sm px-3 py-2 ring-1 ring-indigo-300 rounded"
                      data-testid="recipe-modal-dosage-unit">
                <option value="ml">ml</option>
                <option value="g">g</option>
                <option value="L">L</option>
                <option value="kg">kg</option>
                <option value="unit">unité</option>
              </select>
            </label>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <label className="block"><span className="block text-xs text-slate-600 mb-1">Unités produites par batch</span>
              <input type="number" step="1" value={f.output_batch_units} onChange={(e) => setF({ ...f, output_batch_units: Number(e.target.value) })} className="w-full text-sm px-3 py-2 ring-1 ring-slate-300 rounded text-right font-mono" data-testid="recipe-modal-batch" />
            </label>
            <label className="block"><span className="block text-xs text-slate-600 mb-1">Libellé unité</span>
              <input value={f.output_unit_label} onChange={(e) => setF({ ...f, output_unit_label: e.target.value })} className="w-full text-sm px-3 py-2 ring-1 ring-slate-300 rounded" placeholder="flacon, tube, sachet…" data-testid="recipe-modal-unit-label" />
            </label>
          </div>

          {/* Intrants selector (no per-intrant quantity anymore) */}
          <div className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3">
            <p className="text-xs font-semibold uppercase text-slate-600 mb-1">
              Intrants nécessaires — coût = coût unitaire × dosage ({f.dosage_number || 0} {f.dosage_unit})
            </p>
            <p className="text-[10px] text-slate-500 mb-2 italic">
              Les intrants « matière première / eau / électricité / main d&apos;œuvre / amortissement » multiplient leur coût unitaire par le dosage.
              Les intrants <span className="font-semibold text-amber-700">Emballage/flaconnage</span> et <span className="font-semibold text-amber-700">Autre</span> sont à <strong>coût fixe</strong> (ne scalent pas avec le dosage).
            </p>
            {intrants.length === 0 ? (
              <p className="text-xs text-slate-500 italic">Aucun intrant disponible. Créez d&apos;abord des intrants dans l&apos;onglet Intrants.</p>
            ) : (
              CATEGORIES.map((c) => {
                const items = grouped[c.value] || [];
                if (!items.length) return null;
                const dosageNum = Number(f.dosage_number) || 0;
                return (
                  <div key={c.value} className="mb-2">
                    <p className="text-[10px] font-semibold uppercase mb-1" style={{ color: c.color }}>{c.label}</p>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-1">
                      {items.map((i) => {
                        const sel = f.intrants.find((x) => x.intrant_id === i.id);
                        const isFixed = _FIXED_CATEGORIES.has(i.category || "raw_material");
                        const contribCost = isFixed
                          ? (Number(i.unit_cost) || 0)
                          : dosageNum * (Number(i.unit_cost) || 0);
                        return (
                          <div key={i.id} className={`flex items-center gap-2 px-2 py-1.5 rounded ${sel ? "bg-white ring-1 ring-indigo-300" : "hover:bg-slate-100"}`}>
                            <input type="checkbox" checked={!!sel} onChange={() => toggleIntrant(i.id)} data-testid={`recipe-intrant-toggle-${i.id}`} className="cursor-pointer" />
                            <span className="text-xs flex-1 truncate" title={i.name}>{i.name}</span>
                            {isFixed && (
                              <span className="text-[9px] px-1 rounded bg-amber-100 text-amber-800 font-semibold" title="Coût fixe — ne varie pas avec le dosage">FIXE</span>
                            )}
                            <span className="text-[10px] text-slate-500 font-mono">
                              {(Number(i.unit_cost) || 0).toLocaleString("fr-FR", { maximumFractionDigits: 4 })} CFA/{i.unit}
                            </span>
                            {sel && (dosageNum > 0 || isFixed) && (
                              <span
                                className="text-[10px] font-mono font-semibold text-emerald-700 min-w-[70px] text-right"
                                data-testid={`recipe-intrant-contrib-${i.id}`}
                                title={`Coût dans la recette : ${contribCost.toFixed(4)} CFA`}
                              >
                                = {contribCost.toLocaleString("fr-FR", { maximumFractionDigits: 4 })}
                              </span>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })
            )}
          </div>

          {/* Pricing */}
          <div className="rounded-lg ring-1 ring-emerald-200 bg-emerald-50/40 p-3">
            <div className="flex items-center gap-2 mb-3">
              <button
                onClick={() => setF({ ...f, pricing_mode: "margin_first" })}
                className={`text-xs px-3 py-1 rounded font-semibold ${f.pricing_mode === "margin_first" ? "bg-emerald-600 text-white" : "bg-white ring-1 ring-slate-300"}`}
                data-testid="recipe-pricing-mode-margin"
              >Marge → Prix</button>
              <ArrowRightLeft className="h-3 w-3 text-slate-400" />
              <button
                onClick={() => setF({ ...f, pricing_mode: "price_first" })}
                className={`text-xs px-3 py-1 rounded font-semibold ${f.pricing_mode === "price_first" ? "bg-emerald-600 text-white" : "bg-white ring-1 ring-slate-300"}`}
                data-testid="recipe-pricing-mode-price"
              >Prix → Marge</button>
            </div>
            <div className="grid grid-cols-2 gap-3">
              {f.pricing_mode === "margin_first" ? (
                <label className="block"><span className="block text-xs text-slate-600 mb-1">Marge (%)</span>
                  <input type="number" step="0.1" value={f.margin_pct} onChange={(e) => setF({ ...f, margin_pct: Number(e.target.value) })}
                         className="w-full text-sm px-3 py-2 ring-1 ring-emerald-400 rounded text-right font-mono font-bold" data-testid="recipe-margin-input" />
                </label>
              ) : (
                <label className="block"><span className="block text-xs text-slate-600 mb-1">Prix public (CFA)</span>
                  <input type="number" step="1" value={f.public_price} onChange={(e) => setF({ ...f, public_price: Number(e.target.value) })}
                         className="w-full text-sm px-3 py-2 ring-1 ring-emerald-400 rounded text-right font-mono font-bold" data-testid="recipe-price-input" />
                </label>
              )}
            </div>

            {/* Live computed values */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-3">
              <LiveKpi label="Coût batch" value={computed.costBatch} suffix="CFA" color="#0284c7" testid="recipe-live-costbatch" />
              <LiveKpi label="Prix de revient (unité)" value={computed.costPrice} suffix="CFA" color="#0891b2" testid="recipe-live-costunit" />
              <LiveKpi
                label={f.pricing_mode === "margin_first" ? "Prix public (calculé)" : "Marge (calculée)"}
                value={f.pricing_mode === "margin_first" ? computed.publicPrice : computed.marginPct}
                suffix={f.pricing_mode === "margin_first" ? "CFA" : "%"}
                color="#059669"
                testid="recipe-live-output"
              />
              <LiveKpi label="Bénéfice / unité" value={computed.profit} suffix="CFA" color="#16a34a" testid="recipe-live-profit" />
            </div>
          </div>

          <label className="block"><span className="block text-xs text-slate-600 mb-1">Notes (facultatif)</span>
            <textarea rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} className="w-full text-sm px-3 py-2 ring-1 ring-slate-300 rounded" />
          </label>
        </div>
        <div className="px-5 py-3 border-t border-slate-200 flex justify-end gap-2">
          <button onClick={onClose} className="text-sm px-3 py-1.5 rounded bg-slate-100 hover:bg-slate-200">Annuler</button>
          <button onClick={save} disabled={saving} className="text-sm px-3 py-1.5 rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 inline-flex items-center gap-1" data-testid="recipe-modal-save"><Save className="h-3.5 w-3.5" /> Enregistrer</button>
        </div>
      </div>
    </div>
  );
};

const LiveKpi = ({ label, value, suffix, color, testid }) => (
  <div className="rounded bg-white p-2 ring-1 ring-slate-200" data-testid={testid}>
    <p className="text-[9px] uppercase tracking-wider text-slate-500">{label}</p>
    <p className="text-sm font-bold font-mono" style={{ color }}>
      {(Number.isFinite(value) ? value : 0).toLocaleString("fr-FR", { maximumFractionDigits: 4 })} <span className="text-[10px] text-slate-500 font-normal">{suffix}</span>
    </p>
  </div>
);
