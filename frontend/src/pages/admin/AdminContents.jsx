import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Save, Plus, Trash2 } from "lucide-react";

const SLUGS = [
  { slug: "home_hero", label: "Accueil — Hero" },
  { slug: "mission", label: "Notre Mission" },
  { slug: "experience", label: "Expérience (chiffres clés Accueil)" },
  { slug: "specialisations", label: "Spécialisations" },
  { slug: "about", label: "À propos" },
];

const ICON_OPTIONS = ["Globe", "Smartphone", "Database", "Cpu", "Code"];

export default function AdminContents() {
  const [list, setList] = useState([]);
  const [active, setActive] = useState(SLUGS[0].slug);
  const [data, setData] = useState({ title: "", body_html: "", metadata: {}, images: [] });
  const [loading, setLoading] = useState(false);

  const reload = () => apiClient.get("/content").then((r) => setList(r.data));
  useEffect(() => { reload().catch(() => {}); }, []);

  useEffect(() => {
    const found = list.find((c) => c.slug === active);
    setData(found
      ? { title: found.title, body_html: found.body_html || "", metadata: found.metadata || {}, images: found.images || [] }
      : { title: "", body_html: "", metadata: {}, images: [] });
  }, [active, list]);

  const save = async () => {
    setLoading(true);
    try {
      await apiClient.put(`/admin/content/${active}`, { slug: active, ...data });
      toast.success("Contenu mis à jour");
      await reload();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setLoading(false); }
  };

  const updMeta = (key, value) => setData({ ...data, metadata: { ...data.metadata, [key]: value } });

  // Metrics editor (for "experience")
  const metrics = data.metadata?.metrics || [];
  const addMetric = () => updMeta("metrics", [...metrics, { label: "", value: "" }]);
  const updMetric = (i, k, v) => updMeta("metrics", metrics.map((m, idx) => idx === i ? { ...m, [k]: v } : m));
  const removeMetric = (i) => updMeta("metrics", metrics.filter((_, idx) => idx !== i));

  // Specialisations items editor
  const items = data.metadata?.items || [];
  const addItem = () => updMeta("items", [...items, { title: "", desc: "", icon: "Code" }]);
  const updItem = (i, k, v) => updMeta("items", items.map((m, idx) => idx === i ? { ...m, [k]: v } : m));
  const removeItem = (i) => updMeta("items", items.filter((_, idx) => idx !== i));

  // Hero kicker
  const kicker = data.metadata?.kicker || "";

  return (
    <div className="space-y-6" data-testid="admin-contents-page">
      <div>
        <h1 className="text-2xl font-display font-bold">Contenus du site public</h1>
        <p className="text-sm text-slate-500">Modifiez les textes, chiffres et spécialisations affichés sur le site.</p>
      </div>

      <div className="flex gap-2 overflow-x-auto pb-2">
        {SLUGS.map((s) => (
          <button key={s.slug} onClick={() => setActive(s.slug)}
                  className={`px-4 py-2 rounded-lg text-sm whitespace-nowrap ${active === s.slug ? "bg-sawali-blue text-white" : "bg-white border border-slate-200 hover:bg-slate-50"}`}
                  data-testid={`tab-${s.slug}`}>
            {s.label}
          </button>
        ))}
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-6 space-y-5" data-testid="content-editor">
        <div>
          <label className="block text-xs font-semibold mb-1">Titre</label>
          <input value={data.title} onChange={(e) => setData({ ...data, title: e.target.value })}
                 className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="content-title" />
        </div>

        {active === "home_hero" && (
          <div>
            <label className="block text-xs font-semibold mb-1">Suréltitre (kicker)</label>
            <input value={kicker} onChange={(e) => updMeta("kicker", e.target.value)}
                   className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="content-kicker"
                   placeholder="SAWALI · Software Engineering" />
          </div>
        )}

        <div>
          <label className="block text-xs font-semibold mb-1">Contenu HTML</label>
          <textarea rows={8} value={data.body_html} onChange={(e) => setData({ ...data, body_html: e.target.value })}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" data-testid="content-body" />
          {data.body_html && <div className="mt-2 rounded-lg border border-slate-200 p-3 prose-sawali bg-slate-50" dangerouslySetInnerHTML={{ __html: data.body_html }} />}
        </div>

        {/* Structured editor for "experience" → metrics */}
        {active === "experience" && (
          <div className="rounded-lg border border-slate-200 p-4" data-testid="metrics-editor">
            <div className="flex items-center justify-between mb-3">
              <label className="text-sm font-semibold">Chiffres clés affichés sur l'accueil</label>
              <button onClick={addMetric} className="text-xs text-sawali-blue inline-flex items-center gap-1" data-testid="add-metric"><Plus className="h-3 w-3" /> Ajouter</button>
            </div>
            <p className="text-xs text-slate-500 mb-3">
              Ex : "Années d'expérience" → 10+, "Projets livrés" → 50+, "Clients satisfaits" → 30+
            </p>
            <div className="space-y-2">
              {metrics.map((m, i) => (
                <div key={i} className="grid grid-cols-12 gap-2" data-testid={`metric-row-${i}`}>
                  <input value={m.label} onChange={(e) => updMetric(i, "label", e.target.value)}
                         placeholder="Libellé (ex: Années d'expérience)"
                         className="col-span-7 rounded-md border border-slate-300 px-2 py-1.5 text-sm" />
                  <input value={m.value} onChange={(e) => updMetric(i, "value", e.target.value)}
                         placeholder="Valeur (ex: 10+)"
                         className="col-span-4 rounded-md border border-slate-300 px-2 py-1.5 text-sm" />
                  <button type="button" onClick={() => removeMetric(i)} className="col-span-1 text-rose-600"><Trash2 className="h-4 w-4" /></button>
                </div>
              ))}
              {metrics.length === 0 && <p className="text-xs text-slate-500">Aucun chiffre clé. Cliquez sur "Ajouter" pour en créer.</p>}
            </div>
          </div>
        )}

        {/* Structured editor for "specialisations" → items */}
        {active === "specialisations" && (
          <div className="rounded-lg border border-slate-200 p-4" data-testid="specs-editor">
            <div className="flex items-center justify-between mb-3">
              <label className="text-sm font-semibold">Spécialisations (cards)</label>
              <button onClick={addItem} className="text-xs text-sawali-blue inline-flex items-center gap-1" data-testid="add-spec"><Plus className="h-3 w-3" /> Ajouter</button>
            </div>
            <div className="space-y-3">
              {items.map((it, i) => (
                <div key={i} className="rounded-md border border-slate-200 p-3 space-y-2" data-testid={`spec-item-${i}`}>
                  <div className="grid grid-cols-12 gap-2">
                    <input value={it.title} onChange={(e) => updItem(i, "title", e.target.value)}
                           placeholder="Titre (Développement Web)"
                           className="col-span-7 rounded-md border border-slate-300 px-2 py-1.5 text-sm" />
                    <select value={it.icon || "Code"} onChange={(e) => updItem(i, "icon", e.target.value)}
                            className="col-span-4 rounded-md border border-slate-300 px-2 py-1.5 text-sm">
                      {ICON_OPTIONS.map((ic) => <option key={ic} value={ic}>{ic}</option>)}
                    </select>
                    <button type="button" onClick={() => removeItem(i)} className="col-span-1 text-rose-600"><Trash2 className="h-4 w-4" /></button>
                  </div>
                  <textarea rows={2} value={it.desc || ""} onChange={(e) => updItem(i, "desc", e.target.value)}
                            placeholder="Description courte..."
                            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm" />
                </div>
              ))}
              {items.length === 0 && <p className="text-xs text-slate-500">Aucune spécialisation.</p>}
            </div>
          </div>
        )}

        {/* Fallback raw JSON editor for advanced edits */}
        <details className="rounded-lg border border-slate-200 p-3">
          <summary className="text-xs cursor-pointer text-slate-600">Avancé : éditer le JSON brut des métadonnées</summary>
          <textarea rows={6} value={JSON.stringify(data.metadata, null, 2)} onChange={(e) => {
            try { setData({ ...data, metadata: JSON.parse(e.target.value || "{}") }); } catch { /* ignore */ }
          }} className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-mono" data-testid="content-metadata" />
        </details>

        <button onClick={save} disabled={loading} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light disabled:opacity-50" data-testid="save-content-btn">
          <Save className="h-4 w-4" /> {loading ? "Enregistrement..." : "Enregistrer"}
        </button>
      </div>
    </div>
  );
}
