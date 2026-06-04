import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Save, Plus, Trash2, Languages, Sparkles, Loader2 } from "lucide-react";

const SLUGS = [
  { slug: "home_hero", label: "Accueil — Hero" },
  { slug: "mission", label: "Notre Mission" },
  { slug: "experience", label: "Expérience (chiffres clés Accueil)" },
  { slug: "specialisations", label: "Spécialisations" },
  { slug: "about", label: "À propos" },
];

const ICON_OPTIONS = ["Globe", "Smartphone", "Database", "Cpu", "Code"];
// Iter40-content-i18n — Sentinel key for the base/default content (FR).
// Stored at the top-level of the doc; other langs live under `translations.<code>`.
const DEFAULT_LANG_KEY = "__default__";

export default function AdminContents() {
  const [list, setList] = useState([]);
  const [active, setActive] = useState(SLUGS[0].slug);
  // Iter40-content-i18n — supported languages list (loaded from /i18n/languages)
  const [languages, setLanguages] = useState([]);
  // Iter40-content-i18n — Currently edited language; `__default__` = base FR fields
  const [activeLang, setActiveLang] = useState(DEFAULT_LANG_KEY);
  // Full document (default fields + translations map)
  const [doc, setDoc] = useState({ title: "", body_html: "", metadata: {}, images: [], translations: {} });
  const [loading, setLoading] = useState(false);
  // Iter40-content-i18n — Model selector for the "Translate this content" feature
  const [aiModels, setAiModels] = useState([]);
  const [aiModelId, setAiModelId] = useState("claude-sonnet-4-5-20250929");
  const [aiTranslating, setAiTranslating] = useState(false);

  const reload = () => apiClient.get("/content").then((r) => setList(r.data));
  useEffect(() => { reload().catch(() => {}); }, []);

  // Load supported languages once
  useEffect(() => {
    apiClient.get("/i18n/languages").then((r) => setLanguages(r.data?.items || [])).catch(() => {});
  }, []);

  // Iter40-content-i18n — Load available translation models
  useEffect(() => {
    apiClient.get("/admin/i18n/translate-models").then((r) => {
      setAiModels(r.data?.items || []);
      if (r.data?.default) setAiModelId(r.data.default);
    }).catch(() => {});
  }, []);

  // Iter40-content-i18n — Translate the current default content into the
  // currently selected language in one LLM call. Persists to translations[lang].
  const translateThisContent = async () => {
    if (isDefault) { toast.warning("Sélectionnez d'abord une langue à traduire (autre que « Par défaut »)"); return; }
    if (!aiModelId) { toast.warning("Sélectionnez un modèle IA."); return; }
    if (!(doc.title || doc.body_html || (doc.metadata?.kicker))) {
      toast.warning("Le contenu par défaut est vide — rien à traduire."); return;
    }
    setAiTranslating(true);
    try {
      const r = await apiClient.post(`/admin/content/${active}/translate`, {
        target_lang: activeLang, model: aiModelId,
      });
      const override = r.data?.override || {};
      // Merge into local state so the editor immediately shows the translation
      const t = { ...(doc.translations || {}) };
      t[activeLang] = override;
      setDoc({ ...doc, translations: t });
      toast.success(`Contenu traduit en ${activeLang.toUpperCase()} — relisez avant d'enregistrer.`);
      await reload();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de traduction");
    } finally {
      setAiTranslating(false);
    }
  };

  // When tab changes, hydrate the editor with the saved content
  useEffect(() => {
    const found = list.find((c) => c.slug === active);
    setDoc(found
      ? {
          title: found.title || "",
          body_html: found.body_html || "",
          metadata: found.metadata || {},
          images: found.images || [],
          translations: found.translations || {},
        }
      : { title: "", body_html: "", metadata: {}, images: [], translations: {} });
    setActiveLang(DEFAULT_LANG_KEY); // reset to default whenever the slug changes
  }, [active, list]);

  // -------------------------------------------------------------------
  // Iter40-content-i18n — All `data.*` helpers below operate on the
  // currently selected language. For `__default__`, they read/write
  // the top-level fields; for any other language, they read/write the
  // entry inside `translations[lang]` (deep merge).
  // -------------------------------------------------------------------
  const isDefault = activeLang === DEFAULT_LANG_KEY;
  const langOverride = !isDefault ? (doc.translations?.[activeLang] || {}) : null;

  // Merged "view" the editor shows. For overrides, we let the form display
  // the override value but fall back to default fields when the override
  // doesn't define a key — that way the admin sees a meaningful baseline.
  const data = isDefault
    ? doc
    : {
        title: langOverride?.title ?? doc.title,
        body_html: langOverride?.body_html ?? doc.body_html,
        metadata: { ...(doc.metadata || {}), ...(langOverride?.metadata || {}) },
      };

  // Setters route to default OR override
  const setTitle = (v) => {
    if (isDefault) return setDoc({ ...doc, title: v });
    const t = { ...(doc.translations || {}) };
    t[activeLang] = { ...(t[activeLang] || {}), title: v };
    setDoc({ ...doc, translations: t });
  };
  const setBody = (v) => {
    if (isDefault) return setDoc({ ...doc, body_html: v });
    const t = { ...(doc.translations || {}) };
    t[activeLang] = { ...(t[activeLang] || {}), body_html: v };
    setDoc({ ...doc, translations: t });
  };
  const updMeta = (key, value) => {
    if (isDefault) {
      setDoc({ ...doc, metadata: { ...(doc.metadata || {}), [key]: value } });
      return;
    }
    const t = { ...(doc.translations || {}) };
    const cur = t[activeLang] || {};
    const curMeta = cur.metadata || {};
    t[activeLang] = { ...cur, metadata: { ...curMeta, [key]: value } };
    setDoc({ ...doc, translations: t });
  };

  const save = async () => {
    setLoading(true);
    try {
      const payload = {
        slug: active,
        title: doc.title || "",
        body_html: doc.body_html || "",
        metadata: doc.metadata || {},
        images: doc.images || [],
        translations: doc.translations || {},
      };
      await apiClient.put(`/admin/content/${active}`, payload);
      toast.success(isDefault
        ? "Contenu de base mis à jour"
        : `Traduction « ${activeLang.toUpperCase()} » enregistrée`);
      await reload();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setLoading(false);
    }
  };

  // Iter40-content-i18n — Clear the active language overrides (revert to default)
  const clearLangOverrides = () => {
    if (isDefault) return;
    const t = { ...(doc.translations || {}) };
    delete t[activeLang];
    setDoc({ ...doc, translations: t });
    toast.message(`Surcharges « ${activeLang.toUpperCase()} » supprimées (non sauvegardées)`);
  };

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

  // Iter40-content-i18n — Has-override indicator for tab badges
  const hasOverride = (code) => !!(doc.translations || {})[code];

  return (
    <div className="space-y-6" data-testid="admin-contents-page">
      <div>
        <h1 className="text-2xl font-display font-bold">Contenus du site public</h1>
        <p className="text-sm text-slate-500">Modifiez les textes, chiffres et spécialisations affichés sur le site, par langue.</p>
      </div>

      {/* Section tabs (slug) */}
      <div className="flex gap-2 overflow-x-auto pb-2">
        {SLUGS.map((s) => (
          <button key={s.slug} onClick={() => setActive(s.slug)}
                  className={`px-4 py-2 rounded-lg text-sm whitespace-nowrap ${active === s.slug ? "bg-sawali-blue text-white" : "bg-white border border-slate-200 hover:bg-slate-50"}`}
                  data-testid={`tab-${s.slug}`}>
            {s.label}
          </button>
        ))}
      </div>

      {/* Iter40-content-i18n — Language sub-tabs */}
      <div className="rounded-xl border border-fuchsia-200 bg-fuchsia-50/40 p-3 space-y-2" data-testid="content-lang-tabs">
        <div className="flex items-center gap-2 text-xs text-fuchsia-700 font-semibold">
          <Languages className="h-4 w-4" />
          <span>Langue à éditer</span>
          {!isDefault && (
            <button
              onClick={clearLangOverrides}
              className="ml-auto text-[10px] underline text-rose-600 hover:text-rose-700"
              data-testid="clear-lang-overrides-btn"
              title="Supprime les surcharges de cette langue (revient au contenu par défaut)"
            >
              Effacer les surcharges {activeLang.toUpperCase()}
            </button>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setActiveLang(DEFAULT_LANG_KEY)}
            className={`px-3 py-1.5 rounded-lg text-xs ring-1 transition ${
              isDefault ? "bg-fuchsia-600 text-white ring-fuchsia-700" : "bg-white text-slate-700 ring-slate-300 hover:ring-fuchsia-400"
            }`}
            data-testid="lang-tab-default"
          >
            Par défaut (FR base)
          </button>
          {languages.filter((l) => l.code !== "fr").map((l) => (
            <button
              key={l.code}
              onClick={() => setActiveLang(l.code)}
              className={`px-3 py-1.5 rounded-lg text-xs ring-1 transition inline-flex items-center gap-1.5 ${
                activeLang === l.code ? "bg-fuchsia-600 text-white ring-fuchsia-700" : "bg-white text-slate-700 ring-slate-300 hover:ring-fuchsia-400"
              }`}
              data-testid={`lang-tab-${l.code}`}
              title={l.name}
            >
              <span className="uppercase font-semibold">{l.code}</span>
              <span className="text-[10px] opacity-70">{l.name}</span>
              {hasOverride(l.code) && (
                <span className="ml-1 h-1.5 w-1.5 rounded-full bg-emerald-400" title="Surcharges définies" />
              )}
            </button>
          ))}
        </div>
        {/* Iter40-content-i18n — AI translate this content (whole doc, one LLM call) */}
        {!isDefault && (
          <div className="flex flex-wrap items-end gap-2 pt-2 border-t border-fuchsia-200/60">
            <div className="flex flex-col">
              <label className="text-[10px] uppercase text-slate-500 mb-1">Modèle IA</label>
              <select
                value={aiModelId}
                onChange={(e) => setAiModelId(e.target.value)}
                className="rounded ring-1 ring-violet-300 bg-white px-2 py-1.5 text-xs"
                data-testid="content-ai-model"
              >
                {aiModels.map((m) => (
                  <option key={m.id} value={m.id}>{m.label}</option>
                ))}
              </select>
            </div>
            <button
              onClick={translateThisContent}
              disabled={aiTranslating}
              className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 hover:bg-violet-700 text-white px-3 py-1.5 text-xs disabled:opacity-50"
              data-testid="content-translate-btn"
              title="Traduit l'intégralité du contenu (titre, corps HTML, kicker, chiffres clés, items) en une seule passe en préservant les balises"
            >
              {aiTranslating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
              Traduire ce contenu en {activeLang.toUpperCase()}
            </button>
            <p className="text-[10px] text-slate-500 italic ml-1">
              Préserve les balises HTML et placeholders ; la réponse est pré-remplie dans les champs ci-dessous — relisez puis sauvegardez.
            </p>
          </div>
        )}
        <p className="text-[10px] text-slate-500 italic">
          Les champs ci-dessous s'appliquent à la langue sélectionnée. Quand un visiteur change la langue sur le site, les champs traduits remplacent les valeurs par défaut. <strong>Pour effacer une surcharge</strong>, videz le champ correspondant et sauvegardez.
        </p>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-6 space-y-5" data-testid="content-editor">
        <div>
          <label className="block text-xs font-semibold mb-1">
            Titre {!isDefault && <span className="text-fuchsia-600">({activeLang.toUpperCase()})</span>}
          </label>
          <input value={data.title} onChange={(e) => setTitle(e.target.value)}
                 className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="content-title" />
        </div>

        {active === "home_hero" && (
          <div>
            <label className="block text-xs font-semibold mb-1">
              Surtitre (kicker) {!isDefault && <span className="text-fuchsia-600">({activeLang.toUpperCase()})</span>}
            </label>
            <input value={kicker} onChange={(e) => updMeta("kicker", e.target.value)}
                   className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="content-kicker"
                   placeholder="SAWALI · Software Engineering" />
          </div>
        )}

        <div>
          <label className="block text-xs font-semibold mb-1">
            Contenu HTML {!isDefault && <span className="text-fuchsia-600">({activeLang.toUpperCase()})</span>}
          </label>
          <textarea rows={8} value={data.body_html} onChange={(e) => setBody(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" data-testid="content-body" />
          {data.body_html && <div className="mt-2 rounded-lg border border-slate-200 p-3 prose-sawali bg-slate-50" dangerouslySetInnerHTML={{ __html: data.body_html }} />}
        </div>

        {/* Structured editor for "experience" → metrics */}
        {active === "experience" && (
          <div className="rounded-lg border border-slate-200 p-4" data-testid="metrics-editor">
            <div className="flex items-center justify-between mb-3">
              <label className="text-sm font-semibold">
                Chiffres clés affichés sur l'accueil {!isDefault && <span className="text-fuchsia-600 text-xs">({activeLang.toUpperCase()})</span>}
              </label>
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
              <label className="text-sm font-semibold">
                Spécialisations (cards) {!isDefault && <span className="text-fuchsia-600 text-xs">({activeLang.toUpperCase()})</span>}
              </label>
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

        {/* Fallback raw JSON editor for advanced edits — always edits the default doc */}
        <details className="rounded-lg border border-slate-200 p-3">
          <summary className="text-xs cursor-pointer text-slate-600">
            Avancé : éditer le JSON brut des métadonnées
            {!isDefault && <span className="text-fuchsia-600 ml-1">(surcharge {activeLang.toUpperCase()})</span>}
          </summary>
          <textarea rows={6} value={JSON.stringify(data.metadata, null, 2)} onChange={(e) => {
            try {
              const parsed = JSON.parse(e.target.value || "{}");
              if (isDefault) {
                setDoc({ ...doc, metadata: parsed });
              } else {
                const t = { ...(doc.translations || {}) };
                t[activeLang] = { ...(t[activeLang] || {}), metadata: parsed };
                setDoc({ ...doc, translations: t });
              }
            } catch { /* ignore */ }
          }} className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-mono" data-testid="content-metadata" />
        </details>

        <button onClick={save} disabled={loading} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light disabled:opacity-50" data-testid="save-content-btn">
          <Save className="h-4 w-4" /> {loading ? "Enregistrement..." : "Enregistrer"}
        </button>
      </div>
    </div>
  );
}
