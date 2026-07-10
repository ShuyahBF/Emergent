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
  Factory, Plus, Trash2, Pencil, Save, X, Download, FileText,
  Package, Droplet, Zap, User as UserIcon, Cog, BarChart3, Loader2,
  DollarSign, Percent, ArrowRightLeft,
} from "lucide-react";
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
const RecipesTab = ({ recipes, summary, intrants, defaultMargin, onEdit, onDelete, onExportRecipe, onExportAll }) => (
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
                      <td className="px-3 py-2 text-right font-mono">{i.unit_cost?.toLocaleString("fr-FR", { maximumFractionDigits: 2 })}</td>
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
            <label className="block"><span className="block text-xs text-slate-600 mb-1">Coût unitaire (CFA)</span>
              <input type="number" step="0.01" value={f.unit_cost} onChange={(e) => setF({ ...f, unit_cost: Number(e.target.value) })} className="w-full text-sm px-3 py-2 ring-1 ring-slate-300 rounded text-right font-mono" data-testid="intrant-modal-cost" />
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
  const [f, setF] = useState({
    name: recipe.name || "",
    variant_label: recipe.variant_label || "",
    output_batch_units: recipe.output_batch_units || 1,
    output_unit_label: recipe.output_unit_label || "unit",
    intrants: recipe.intrants ? recipe.intrants.map((i) => ({ intrant_id: i.intrant_id, quantity: i.quantity })) : [],
    pricing_mode: recipe.pricing_mode || "margin_first",
    margin_pct: recipe.margin_pct ?? defaultMargin ?? 42,
    public_price: recipe.public_price ?? 0,
    notes: recipe.notes || "",
  });
  const [saving, setSaving] = useState(false);

  // Real-time recomputation
  const computed = useMemo(() => {
    const intrantsById = Object.fromEntries(intrants.map((i) => [i.id, i]));
    let costBatch = 0;
    for (const it of f.intrants) {
      const src = intrantsById[it.intrant_id];
      if (!src) continue;
      costBatch += (Number(it.quantity) || 0) * (Number(src.unit_cost) || 0);
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
      costBatch, costPrice,
      publicPrice, marginPct,
      profit: publicPrice - costPrice,
    };
  }, [f, intrants]);

  const toggleIntrant = (id) => {
    setF((p) => {
      const has = p.intrants.find((x) => x.intrant_id === id);
      if (has) return { ...p, intrants: p.intrants.filter((x) => x.intrant_id !== id) };
      return { ...p, intrants: [...p.intrants, { intrant_id: id, quantity: 0 }] };
    });
  };
  const setQty = (id, q) => setF((p) => ({
    ...p,
    intrants: p.intrants.map((x) => (x.intrant_id === id ? { ...x, quantity: Number(q) || 0 } : x)),
  }));

  const save = async () => {
    if (!f.name.trim()) { toast.error("Nom du produit requis"); return; }
    if (f.intrants.length === 0) { toast.error("Cochez au moins un intrant"); return; }
    setSaving(true);
    try {
      const payload = { ...f };
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
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <label className="block md:col-span-2"><span className="block text-xs text-slate-600 mb-1">Nom du produit</span>
              <input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} className="w-full text-sm px-3 py-2 ring-1 ring-slate-300 rounded font-semibold" data-testid="recipe-modal-name" placeholder="ex. SPRAY ICARIDINE" />
            </label>
            <label className="block"><span className="block text-xs text-slate-600 mb-1">Variante / présentation</span>
              <input value={f.variant_label} onChange={(e) => setF({ ...f, variant_label: e.target.value })} className="w-full text-sm px-3 py-2 ring-1 ring-slate-300 rounded" data-testid="recipe-modal-variant" placeholder="ex. 50 ml, 4%, boîte 12" />
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

          {/* Intrants selector */}
          <div className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3">
            <p className="text-xs font-semibold uppercase text-slate-600 mb-2">Intrants nécessaires (cocher + saisir la quantité par batch)</p>
            {intrants.length === 0 ? (
              <p className="text-xs text-slate-500 italic">Aucun intrant disponible. Créez d&apos;abord des intrants dans l&apos;onglet Intrants.</p>
            ) : (
              CATEGORIES.map((c) => {
                const items = grouped[c.value] || [];
                if (!items.length) return null;
                return (
                  <div key={c.value} className="mb-2">
                    <p className="text-[10px] font-semibold uppercase mb-1" style={{ color: c.color }}>{c.label}</p>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-1">
                      {items.map((i) => {
                        const sel = f.intrants.find((x) => x.intrant_id === i.id);
                        return (
                          <div key={i.id} className={`flex items-center gap-2 px-2 py-1.5 rounded ${sel ? "bg-white ring-1 ring-indigo-300" : "hover:bg-slate-100"}`}>
                            <input type="checkbox" checked={!!sel} onChange={() => toggleIntrant(i.id)} data-testid={`recipe-intrant-toggle-${i.id}`} className="cursor-pointer" />
                            <span className="text-xs flex-1 truncate" title={i.name}>{i.name}</span>
                            <span className="text-[10px] text-slate-500">{i.unit_cost} CFA/{i.unit}</span>
                            {sel && (
                              <input type="number" step="0.01" value={sel.quantity} onChange={(e) => setQty(i.id, e.target.value)}
                                     className="w-20 text-right px-1 py-0.5 text-xs ring-1 ring-slate-300 rounded font-mono"
                                     placeholder="qté" data-testid={`recipe-intrant-qty-${i.id}`} />
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
      {(Number.isFinite(value) ? value : 0).toLocaleString("fr-FR", { maximumFractionDigits: 2 })} <span className="text-[10px] text-slate-500 font-normal">{suffix}</span>
    </p>
  </div>
);
