// S046 (2026-02) — Admin Régionalisation page (i18n translations table).
// Allows admin/superviseur to manage the i18n_translations collection
// with inline edits, add/delete rows, CSV export/import, and bulk save.
// 2026-02 — Translator role : limited to their `allowed_languages`, with
// a live score panel (day/month words + payable amount).
import React, { useEffect, useMemo, useRef, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import { Plus, Trash2, Save, RefreshCw, Search, Languages, Loader2, FileText, Download, Upload, Coins, Sparkles } from "lucide-react";

const BLANK_ROW = { key: "", fr: "", en: "", ar: "", lg1: "", lg2: "", context: "" };

export default function AdminI18n() {
  const { user } = useAuth();
  const [items, setItems] = useState([]);
  const [languages, setLanguages] = useState([]);
  const [coverage, setCoverage] = useState({});
  const [totalRows, setTotalRows] = useState(0);
  const [allowedLangs, setAllowedLangs] = useState(null); // null = admin (no restriction)
  const [viewerRole, setViewerRole] = useState("admin");
  const [score, setScore] = useState(null);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState("");
  const [editing, setEditing] = useState(null); // row being edited
  const [saving, setSaving] = useState(false);
  const [importing, setImporting] = useState(false);
  const [aiLoading, setAiLoading] = useState(null); // field code being translated
  // Iter40-i18n-model — Available translation models + currently selected
  const [aiModels, setAiModels] = useState([]);
  const [aiModelId, setAiModelId] = useState("claude-sonnet-4-5-20250929");
  // Iter40-i18n-batch — Bulk-translate-empty state
  const [bulkTargetLang, setBulkTargetLang] = useState("en");
  const [bulkRunning, setBulkRunning] = useState(false);
  const fileInputRef = useRef(null);

  const isTranslator = (user?.tracked_role || "") === "Traducteur";

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/i18n/translations");
      setItems(r.data?.items || []);
      setLanguages(r.data?.languages || []);
      setCoverage(r.data?.coverage || {});
      setTotalRows(r.data?.total || (r.data?.items || []).length);
      setViewerRole(r.data?.viewer_role || "admin");
      if (r.data?.viewer_role === "translator") {
        setAllowedLangs(r.data?.allowed_languages || []);
      } else {
        setAllowedLangs(null);
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  };

  const loadScore = async () => {
    if (!isTranslator) return;
    try {
      const r = await apiClient.get("/admin/i18n/translator-score");
      setScore(r.data);
    } catch { /* noop */ }
  };

  useEffect(() => { load(); loadScore(); }, []);

  // Iter40-i18n-model — Load available translation models once
  useEffect(() => {
    apiClient.get("/admin/i18n/translate-models").then((r) => {
      setAiModels(r.data?.items || []);
      if (r.data?.default) setAiModelId(r.data.default);
    }).catch(() => { /* admin-only endpoint; translators can skip */ });
  }, []);

  // Iter40-i18n-batch — Run "translate all empty cells" for the selected lang+model
  const runBulkTranslate = async () => {
    if (!aiModelId) { toast.warning("Sélectionnez un modèle IA."); return; }
    if (!window.confirm(
      `Lancer la traduction IA de TOUTES les cellules vides en ${bulkTargetLang.toUpperCase()} ` +
      `avec le modèle ${aiModelId} ?\n\nCela peut prendre quelques minutes et consomme des crédits IA.`
    )) return;
    setBulkRunning(true);
    try {
      const r = await apiClient.post("/admin/i18n/translate-empty-bulk", {
        target_lang: bulkTargetLang, model: aiModelId,
      });
      const n = r.data?.translated || 0;
      const errs = (r.data?.errors || []).length;
      toast.success(
        `${n} cellule${n > 1 ? "s" : ""} traduite${n > 1 ? "s" : ""} en ${bulkTargetLang.toUpperCase()}` +
        (errs > 0 ? ` · ${errs} erreur${errs > 1 ? "s" : ""}` : ""),
        { duration: 8000 }
      );
      if (errs > 0) console.warn("[i18n] bulk-translate errors:", r.data.errors);
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de traduction en masse");
    } finally {
      setBulkRunning(false);
    }
  };

  // Helper : is the translator allowed to edit a given language column?
  const canEditLang = (lang) => {
    if (viewerRole !== "translator") return true;
    if (lang === "fr" || lang === "context") return false; // FR reserved to admin
    return (allowedLangs || []).includes(lang);
  };

  // 2026-02 — AI-assisted translation suggestion (Claude Sonnet via Emergent LLM key)
  const suggestTranslation = async (targetLang) => {
    if (!editing) return;
    const fr = (editing.fr || "").trim();
    if (!fr) { toast.warning("Renseignez d'abord le texte FR source."); return; }
    setAiLoading(targetLang);
    try {
      const r = await apiClient.post("/admin/i18n/translate-suggest", {
        fr, target_lang: targetLang, context: editing.context || "",
        model: aiModelId,
      });
      const suggestion = r.data?.suggestion || "";
      if (!suggestion) { toast.warning("Aucune suggestion retournée."); return; }
      setEditing({ ...editing, [targetLang]: suggestion });
      toast.success(`Suggestion ${targetLang.toUpperCase()} générée — relisez avant d'enregistrer.`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur LLM");
    } finally {
      setAiLoading(null);
    }
  };

  const filtered = useMemo(() => {
    if (!filter.trim()) return items;
    const q = filter.toLowerCase();
    return items.filter((it) =>
      (it.key || "").toLowerCase().includes(q) ||
      (it.fr || "").toLowerCase().includes(q) ||
      (it.en || "").toLowerCase().includes(q) ||
      (it.context || "").toLowerCase().includes(q)
    );
  }, [items, filter]);

  const save = async (row) => {
    if (!row.key?.trim() || !row.fr?.trim()) {
      toast.error("Clé et version FR sont requises");
      return;
    }
    setSaving(true);
    try {
      const r = await apiClient.post("/admin/i18n/translations", row);
      const words = r.data?.words_added || 0;
      if (isTranslator && words > 0) {
        toast.success(`Clé ${row.key} sauvée · +${words} mot${words > 1 ? "s" : ""} crédités`);
        loadScore();
      } else {
        toast.success(`Clé ${row.key} enregistrée`);
      }
      setEditing(null);
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur d'enregistrement");
    } finally {
      setSaving(false);
    }
  };

  const removeRow = async (key) => {
    if (!window.confirm(`Supprimer la traduction « ${key} » ? Cette action est irréversible.`)) return;
    try {
      await apiClient.delete(`/admin/i18n/translations/${key}`);
      toast.success("Supprimé");
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  // Export the current collection as a CSV file (UTF-8 BOM, Excel-friendly).
  const exportCsv = async () => {
    try {
      const r = await apiClient.get("/admin/i18n/translations.csv", { responseType: "blob" });
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `sawali_translations_${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success("Export CSV téléchargé");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur d'export");
    }
  };

  const onPickCsv = () => fileInputRef.current?.click();

  const importCsv = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // reset so the same file can be re-picked
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".csv")) {
      toast.error("Veuillez sélectionner un fichier .csv");
      return;
    }
    if (!window.confirm(
      `Importer « ${file.name} » ? Les clés existantes seront mises à jour. ` +
      `Les nouvelles seront ajoutées. Les clés absentes du CSV ne seront PAS supprimées.`
    )) return;
    setImporting(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const r = await apiClient.post("/admin/i18n/translations/import-csv", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      const n = r.data?.upserted || 0;
      const errs = r.data?.errors_count || 0;
      toast.success(
        `${n} clé${n > 1 ? "s" : ""} importée${n > 1 ? "s" : ""}` +
        (errs > 0 ? ` · ${errs} ligne${errs > 1 ? "s" : ""} ignorée${errs > 1 ? "s" : ""}` : ""),
        { duration: 7000 }
      );
      if (errs > 0 && r.data?.errors) {
        console.warn("CSV import errors:", r.data.errors);
      }
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur d'import");
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="space-y-4 p-4" data-testid="admin-i18n-page">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2">
            <Languages className="h-6 w-6 text-sawali-blue" /> Régionalisation
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            La colonne <strong>FR</strong> est la source. Les autres langues servent de remplacement —
            si vide, le texte FR s'affiche par défaut. <strong>LG1 = Gulmancema</strong>, <strong>LG2 = Mooré</strong>.
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <input
            type="file"
            accept=".csv"
            ref={fileInputRef}
            onChange={importCsv}
            style={{ display: "none" }}
            data-testid="i18n-csv-file-input"
          />
          <button
            onClick={exportCsv}
            className="inline-flex items-center gap-1.5 rounded-lg ring-1 ring-emerald-300 text-emerald-700 hover:bg-emerald-50 px-3 py-1.5 text-xs"
            data-testid="i18n-export-csv"
            title="Télécharger toutes les traductions au format CSV (UTF-8 BOM, Excel-compatible)"
          >
            <Download className="h-3.5 w-3.5" /> Exporter CSV
          </button>
          <button
            onClick={onPickCsv}
            disabled={importing}
            className="inline-flex items-center gap-1.5 rounded-lg ring-1 ring-fuchsia-300 text-fuchsia-700 hover:bg-fuchsia-50 px-3 py-1.5 text-xs disabled:opacity-50"
            data-testid="i18n-import-csv"
            title="Importer un fichier CSV (les clés existantes sont mises à jour, les nouvelles ajoutées)"
          >
            {importing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
            Importer CSV
          </button>
          <button
            onClick={load}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg ring-1 ring-slate-300 hover:bg-slate-50 px-3 py-1.5 text-xs"
            data-testid="i18n-refresh"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Actualiser
          </button>
          <button
            onClick={() => setEditing({ ...BLANK_ROW })}
            disabled={isTranslator}
            className="inline-flex items-center gap-1.5 rounded-lg bg-sawali-blue hover:bg-sawali-blue-light text-white px-3 py-1.5 text-xs disabled:opacity-40 disabled:cursor-not-allowed"
            data-testid="i18n-add"
            title={isTranslator ? "Création de clé réservée à l'admin" : "Ajouter une clé"}
          >
            <Plus className="h-3.5 w-3.5" /> Nouvelle clé
          </button>
        </div>
      </div>

      {/* Coverage strip — % of non-empty cells per language */}
      <div className="rounded-lg ring-1 ring-slate-200 bg-white p-3" data-testid="i18n-coverage">
        <div className="flex flex-wrap items-center gap-3 text-[11px]">
          <span className="font-semibold text-slate-700">Couverture · {totalRows} clés</span>
          {["en", "ar", "lg1", "lg2"].map((code) => {
            const pct = coverage[code] ?? 0;
            const color = pct >= 80 ? "emerald" : pct >= 40 ? "amber" : "rose";
            return (
              <div key={code} className="flex items-center gap-1.5" data-testid={`coverage-${code}`}>
                <span className="uppercase font-mono text-[10px] text-slate-500">{code}</span>
                <div className="h-1.5 w-24 rounded-full bg-slate-100 overflow-hidden">
                  <div
                    className={`h-full bg-${color}-500`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className={`font-semibold text-${color}-700`}>{pct}%</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Iter40-i18n-model — AI translator: model selector + bulk-translate-empty */}
      {!isTranslator && aiModels.length > 0 && (
        <div className="rounded-lg ring-1 ring-violet-200 bg-violet-50/40 p-3 space-y-2" data-testid="i18n-ai-toolbar">
          <div className="flex items-center gap-2 text-xs font-semibold text-violet-900">
            <Sparkles className="h-4 w-4 text-violet-600" />
            <span>Traducteur IA — réglages</span>
          </div>
          <div className="flex flex-wrap items-end gap-2 text-xs">
            <div className="flex flex-col">
              <label className="text-[10px] uppercase text-slate-500 mb-1">Modèle IA</label>
              <select
                value={aiModelId}
                onChange={(e) => setAiModelId(e.target.value)}
                className="rounded ring-1 ring-violet-300 bg-white px-2 py-1.5 text-xs"
                data-testid="i18n-ai-model"
              >
                {aiModels.map((m) => (
                  <option key={m.id} value={m.id}>{m.label}</option>
                ))}
              </select>
            </div>
            <div className="flex flex-col">
              <label className="text-[10px] uppercase text-slate-500 mb-1">Langue cible (en masse)</label>
              <select
                value={bulkTargetLang}
                onChange={(e) => setBulkTargetLang(e.target.value)}
                className="rounded ring-1 ring-violet-300 bg-white px-2 py-1.5 text-xs"
                data-testid="i18n-bulk-target-lang"
              >
                <option value="en">EN — Anglais</option>
                <option value="ar">AR — Arabe</option>
                <option value="lg1">LG1 — Gulmancema</option>
                <option value="lg2">LG2 — Mooré</option>
              </select>
            </div>
            <button
              onClick={runBulkTranslate}
              disabled={bulkRunning}
              className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 hover:bg-violet-700 text-white px-3 py-1.5 disabled:opacity-50"
              data-testid="i18n-run-bulk-translate"
              title="Traduit toutes les cellules vides dans la langue cible avec le modèle sélectionné"
            >
              {bulkRunning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
              Traduire toutes les cellules vides en {bulkTargetLang.toUpperCase()}
            </button>
          </div>
          <p className="text-[10px] text-slate-500 italic">
            Le modèle sélectionné s'applique aussi au bouton ✨ ligne-par-ligne dans l'éditeur. La traduction préserve les balises HTML et placeholders.
          </p>
        </div>
      )}

      {/* Translator score (only for tracked_role=Traducteur) */}
      {isTranslator && score && (
        <div className="rounded-lg ring-1 ring-fuchsia-200 bg-fuchsia-50/40 p-3" data-testid="i18n-translator-score">
          <div className="flex items-center gap-2 mb-2">
            <Coins className="h-4 w-4 text-fuchsia-600" />
            <span className="font-semibold text-fuchsia-900 text-sm">Mon score (en tant que Traducteur)</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
            <div className="rounded bg-white ring-1 ring-fuchsia-100 px-3 py-2" data-testid="score-day">
              <div className="text-[10px] uppercase tracking-wider text-fuchsia-700">Aujourd'hui</div>
              <div className="text-lg font-bold text-fuchsia-900 mt-0.5">{score.day?.words || 0} mots</div>
              <div className="text-[11px] text-fuchsia-700">
                {(score.day?.amount || 0).toFixed(2)} · {score.day?.lines || 0} lignes
              </div>
            </div>
            <div className="rounded bg-white ring-1 ring-fuchsia-100 px-3 py-2" data-testid="score-month">
              <div className="text-[10px] uppercase tracking-wider text-fuchsia-700">Ce mois-ci</div>
              <div className="text-lg font-bold text-fuchsia-900 mt-0.5">{score.month?.words || 0} mots</div>
              <div className="text-[11px] text-fuchsia-700">
                {(score.month?.amount || 0).toFixed(2)} · {score.month?.lines || 0} lignes
              </div>
            </div>
            <div className="rounded bg-white ring-1 ring-fuchsia-100 px-3 py-2" data-testid="score-total">
              <div className="text-[10px] uppercase tracking-wider text-fuchsia-700">Total</div>
              <div className="text-lg font-bold text-fuchsia-900 mt-0.5">{score.total?.words || 0} mots</div>
              <div className="text-[11px] text-fuchsia-700">
                {(score.total?.amount || 0).toFixed(2)} · {score.total?.lines || 0} lignes
              </div>
            </div>
          </div>
          <p className="text-[10px] text-fuchsia-600 mt-2 italic">
            Taux : {score.rate_per_word || 0} / mot · Langues autorisées : {(allowedLangs || []).map((l) => l.toUpperCase()).join(", ") || "aucune"}
          </p>
        </div>
      )}

      <div className="flex items-center gap-2">
        <div className="relative flex-1 max-w-md">
          <Search className="h-3.5 w-3.5 text-slate-400 absolute left-2.5 top-2" />
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filtrer par clé, FR, EN, contexte…"
            className="w-full pl-8 pr-3 py-1.5 text-sm rounded-lg ring-1 ring-slate-300 focus:ring-sawali-blue focus:outline-none"
            data-testid="i18n-filter"
          />
        </div>
        <span className="text-[11px] text-slate-500">
          {filtered.length}/{items.length} clé{filtered.length > 1 ? "s" : ""}
        </span>
      </div>

      <div className="rounded-xl ring-1 ring-slate-200 bg-white overflow-x-auto">
        <table className="w-full text-xs min-w-[1200px]" data-testid="i18n-table">
          <thead className="bg-slate-50 text-[10px] uppercase tracking-wider text-slate-600">
            <tr>
              <th className="px-2 py-2 text-left w-[200px]">Clé</th>
              <th className="px-2 py-2 text-left">FR <span className="text-rose-500">*</span></th>
              <th className="px-2 py-2 text-left">EN</th>
              <th className="px-2 py-2 text-left">AR</th>
              <th className="px-2 py-2 text-left">LG1</th>
              <th className="px-2 py-2 text-left">LG2</th>
              <th className="px-2 py-2 text-left w-[140px]">Contexte</th>
              <th className="px-2 py-2 text-right w-[80px]">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={8} className="px-3 py-8 text-center text-slate-400 italic">Chargement…</td></tr>
            ) : filtered.length === 0 ? (
              <tr><td colSpan={8} className="px-3 py-8 text-center text-slate-400 italic">Aucune traduction.</td></tr>
            ) : filtered.map((row) => {
              const isEditing = editing && editing.key === row.key;
              const edit = isEditing ? editing : row;
              return (
                <tr key={row.key} className={`border-t border-slate-100 ${isEditing ? "bg-amber-50/50" : "hover:bg-slate-50"}`} data-testid={`i18n-row-${row.key}`}>
                  <td className="px-2 py-1.5 font-mono text-[10px] text-slate-700 truncate max-w-[200px]" title={row.key}>{row.key}</td>
                  {["fr", "en", "ar", "lg1", "lg2", "context"].map((field) => {
                    const editable = canEditLang(field);
                    const isAITarget = isEditing && editable && ["en", "ar", "lg1", "lg2"].includes(field);
                    return (
                    <td key={field} className="px-1 py-1">
                      {isEditing && editable ? (
                        <div className="space-y-1">
                          <textarea
                            value={edit[field] || ""}
                            onChange={(e) => setEditing({ ...editing, [field]: e.target.value })}
                            rows={2}
                            className={`w-full rounded ring-1 ring-slate-300 px-1.5 py-1 text-xs focus:ring-sawali-blue focus:outline-none ${field === "ar" ? "text-right" : ""}`}
                            dir={field === "ar" ? "rtl" : "ltr"}
                            data-testid={`i18n-input-${row.key}-${field}`}
                          />
                          {isAITarget && (editing.fr || row.fr) && (
                            <button
                              type="button"
                              onClick={() => suggestTranslation(field)}
                              disabled={!!aiLoading}
                              className="inline-flex items-center gap-1 text-[10px] text-fuchsia-700 hover:text-fuchsia-900 disabled:opacity-50"
                              data-testid={`i18n-ai-${row.key}-${field}`}
                              title="Suggérer une traduction via IA (Claude Sonnet)"
                            >
                              {aiLoading === field
                                ? <Loader2 className="h-3 w-3 animate-spin" />
                                : <Sparkles className="h-3 w-3" />}
                              ✨ IA
                            </button>
                          )}
                        </div>
                      ) : (
                        <div
                          className={`truncate max-w-[200px] ${field === "ar" ? "text-right" : ""} ${(!row[field] && field !== "fr" && field !== "context") ? "text-slate-300 italic" : "text-slate-700"} ${(!editable && isTranslator) ? "opacity-60" : ""}`}
                          dir={field === "ar" ? "rtl" : "ltr"}
                          title={!editable && isTranslator ? "Langue non autorisée pour votre compte" : (row[field] || (field !== "fr" ? "(vide — fallback FR)" : ""))}
                        >
                          {row[field] || (field !== "fr" && field !== "context" ? "—" : "")}
                        </div>
                      )}
                    </td>
                    );
                  })}
                  <td className="px-1 py-1 text-right">
                    <div className="inline-flex items-center gap-1">
                      {isEditing ? (
                        <>
                          <button
                            onClick={() => save(editing)}
                            disabled={saving}
                            className="text-[10px] rounded bg-emerald-600 hover:bg-emerald-700 text-white px-2 py-0.5"
                            data-testid={`i18n-save-${row.key}`}
                          >
                            {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : "Save"}
                          </button>
                          <button
                            onClick={() => setEditing(null)}
                            className="text-[10px] rounded ring-1 ring-slate-300 px-2 py-0.5 text-slate-600"
                          >
                            ✕
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            onClick={() => setEditing({ ...row })}
                            className="text-slate-500 hover:text-sawali-blue"
                            title="Éditer"
                            data-testid={`i18n-edit-${row.key}`}
                          >
                            <FileText className="h-3.5 w-3.5" />
                          </button>
                          {!isTranslator && (
                            <button
                              onClick={() => removeRow(row.key)}
                              className="text-slate-500 hover:text-rose-600"
                              title="Supprimer"
                              data-testid={`i18n-del-${row.key}`}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}

            {/* New row when adding */}
            {editing && !editing.key && (
              <tr className="border-t border-slate-100 bg-emerald-50/50">
                <td className="px-1 py-1">
                  <input
                    value={editing.key || ""}
                    onChange={(e) => setEditing({ ...editing, key: e.target.value })}
                    placeholder="nav.exemple"
                    className="w-full rounded ring-1 ring-slate-300 px-1.5 py-1 text-xs font-mono"
                    data-testid="i18n-new-key"
                  />
                </td>
                {["fr", "en", "ar", "lg1", "lg2", "context"].map((field) => (
                  <td key={field} className="px-1 py-1">
                    <textarea
                      value={editing[field] || ""}
                      onChange={(e) => setEditing({ ...editing, [field]: e.target.value })}
                      rows={2}
                      className={`w-full rounded ring-1 ring-slate-300 px-1.5 py-1 text-xs ${field === "ar" ? "text-right" : ""}`}
                      dir={field === "ar" ? "rtl" : "ltr"}
                      data-testid={`i18n-new-${field}`}
                    />
                  </td>
                ))}
                <td className="px-1 py-1 text-right">
                  <div className="inline-flex items-center gap-1">
                    <button
                      onClick={() => save(editing)}
                      disabled={saving}
                      className="text-[10px] rounded bg-emerald-600 hover:bg-emerald-700 text-white px-2 py-0.5 inline-flex items-center gap-1"
                      data-testid="i18n-new-save"
                    >
                      {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
                      Save
                    </button>
                    <button
                      onClick={() => setEditing(null)}
                      className="text-[10px] rounded ring-1 ring-slate-300 px-2 py-0.5 text-slate-600"
                    >
                      ✕
                    </button>
                  </div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <p className="text-[10px] text-slate-400">
        💡 Astuce : les langues vides retombent automatiquement sur le FR à l'affichage. Pour
        LG1 (Gulmancema) et LG2 (Mooré), remplissez ligne par ligne au rythme de la traduction
        manuelle. La sélection de langue est immédiate après enregistrement.
      </p>
    </div>
  );
}
