// Iter41 (2026-02) — Portail VIDAL France
// Page unifiée : recherche médicament + fiche médicament + analyse de prescription
// Trois onglets : Recherche, Catalogue, Analyse de prescription.
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  Stethoscope, Search, Loader2, AlertTriangle, FileText, Pill, ListChecks, Plus, X
} from "lucide-react";

const TABS = [
  { key: "search", label: "Recherche", icon: Search },
  { key: "catalog", label: "Catalogue", icon: ListChecks },
  { key: "analyze", label: "Analyse prescription", icon: AlertTriangle },
];

const FILTER_OPTIONS = [
  { value: "product", label: "Médicament (produit)" },
  { value: "package", label: "Présentation (boîte)" },
  { value: "ucd", label: "UCD (hospitalier)" },
  { value: "vmp", label: "VMP (virtuel)" },
];

const CATALOG_STATUSES = [
  { value: "NEW", label: "Nouveautés" },
  { value: "AVAILABLE", label: "Disponibles" },
  { value: "DELETED", label: "Retirés" },
  { value: "PHARMACO", label: "Vigilance" },
];

function ResultTable({ data, onPick }) {
  // VIDAL responses can be Atom-style. We try to detect entries[] or items[].
  const entries = data?.entries || data?.items || data?.feed?.entries || [];
  if (!Array.isArray(entries) || entries.length === 0) {
    return (
      <div className="text-xs text-slate-500 italic p-3 ring-1 ring-slate-200 rounded bg-slate-50">
        Aucun résultat structuré renvoyé. Réponse brute :
        <pre className="mt-2 text-[10px] overflow-auto max-h-60 bg-white p-2 rounded ring-1 ring-slate-100">
          {JSON.stringify(data, null, 2).slice(0, 4000)}
        </pre>
      </div>
    );
  }
  return (
    <table className="w-full text-xs ring-1 ring-slate-200 rounded">
      <thead className="bg-slate-50 text-slate-600">
        <tr>
          <th className="text-left px-2 py-1.5">Nom</th>
          <th className="text-left px-2 py-1.5">ID VIDAL</th>
          <th className="text-left px-2 py-1.5">Type</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {entries.map((e, i) => {
          const id = e?.id || e?.vidal_id || e?.product_id || e?.idVidal;
          const title = e?.title || e?.name || e?.label || "(sans nom)";
          const type = e?.type || e?.objectType || "-";
          return (
            <tr key={i} className="border-t border-slate-100 hover:bg-fuchsia-50">
              <td className="px-2 py-1.5 font-semibold">{title}</td>
              <td className="px-2 py-1.5 font-mono text-slate-500">{id || "?"}</td>
              <td className="px-2 py-1.5 text-slate-500">{type}</td>
              <td className="px-2 py-1.5 text-right">
                {id && (
                  <button
                    type="button"
                    onClick={() => onPick(parseInt(id) || id)}
                    className="text-fuchsia-600 hover:text-fuchsia-700 text-[10px] underline"
                    data-testid={`vidal-pick-${i}`}
                  >
                    Voir la fiche →
                  </button>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function ProductDetail({ id, onClose }) {
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState(null);
  const [rcp, setRcp] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [a, b] = await Promise.all([
          apiClient.get(`/vidal/product/${id}`),
          apiClient.get(`/vidal/product/${id}/documents?type=RCP`),
        ]);
        if (!cancelled) {
          setDetail(a.data?.data);
          setRcp(b.data?.data);
        }
      } catch (e) {
        toast.error(e?.response?.data?.detail || "Erreur fiche VIDAL");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [id]);

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" data-testid="vidal-product-modal">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-slate-100 px-4 py-3 flex items-center justify-between">
          <h2 className="font-semibold text-slate-800 inline-flex items-center gap-2">
            <Pill className="h-4 w-4 text-fuchsia-600" />
            Fiche médicament — ID {id}
          </h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700" data-testid="vidal-product-close">
            <X className="h-4 w-4" />
          </button>
        </div>
        {loading ? (
          <div className="p-6 text-sm text-slate-500 flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
          </div>
        ) : (
          <div className="p-4 space-y-4">
            <section data-testid="vidal-product-detail">
              <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-2">Informations produit</h3>
              <pre className="text-[11px] bg-slate-50 ring-1 ring-slate-200 rounded p-3 overflow-auto max-h-72">
                {JSON.stringify(detail, null, 2).slice(0, 6000)}
              </pre>
            </section>
            <section data-testid="vidal-product-rcp">
              <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-2">
                <FileText className="inline h-3 w-3 mr-1" />
                Monographie (RCP)
              </h3>
              <pre className="text-[11px] bg-slate-50 ring-1 ring-slate-200 rounded p-3 overflow-auto max-h-72">
                {JSON.stringify(rcp, null, 2).slice(0, 6000)}
              </pre>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

function SearchTab({ onPick }) {
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("product");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);

  const run = async () => {
    if (q.length < 2) {
      toast.warning("Saisir au moins 2 caractères");
      return;
    }
    setLoading(true);
    try {
      const r = await apiClient.get(`/vidal/search?q=${encodeURIComponent(q)}&filter=${filter}`);
      setResult(r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
    setTimeout(() => setLoading(false), 0);
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="flex-1 min-w-[200px]">
          <label className="block text-xs text-slate-600 mb-1">Recherche (nom, DCI, code)</label>
          <input
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && run()}
            placeholder="ex: amoxicilline, doliprane, 3400930…"
            className="w-full text-sm px-3 py-2 rounded ring-1 ring-slate-300 focus:ring-fuchsia-500"
            data-testid="vidal-search-input"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-600 mb-1">Filtre</label>
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="text-sm px-3 py-2 rounded ring-1 ring-slate-300"
            data-testid="vidal-search-filter"
          >
            {FILTER_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <button
          onClick={run}
          disabled={loading}
          className="text-sm px-4 py-2 rounded bg-fuchsia-600 hover:bg-fuchsia-700 text-white inline-flex items-center gap-2 disabled:opacity-60"
          data-testid="vidal-search-submit"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />} Rechercher
        </button>
      </div>
      {result && (
        <>
          {result.cached && (
            <p className="text-[10px] text-emerald-600">⚡ Réponse depuis le cache</p>
          )}
          <ResultTable data={result.data} onPick={onPick} />
        </>
      )}
    </div>
  );
}

function CatalogTab({ onPick }) {
  const [status, setStatus] = useState("NEW");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);

  const run = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get(`/vidal/products/status?status=${status}`);
      setResult(r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
    setTimeout(() => setLoading(false), 0);
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <div>
          <label className="block text-xs text-slate-600 mb-1">Statut réglementaire</label>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="text-sm px-3 py-2 rounded ring-1 ring-slate-300"
            data-testid="vidal-catalog-status"
          >
            {CATALOG_STATUSES.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <button
          onClick={run}
          disabled={loading}
          className="text-sm px-4 py-2 rounded bg-fuchsia-600 hover:bg-fuchsia-700 text-white inline-flex items-center gap-2 disabled:opacity-60"
          data-testid="vidal-catalog-submit"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ListChecks className="h-4 w-4" />} Lister
        </button>
      </div>
      {result && <ResultTable data={result.data} onPick={onPick} />}
    </div>
  );
}

function AnalyzeTab() {
  const [patient, setPatient] = useState({ birth_date: "", sex: "F", weight_kg: "" });
  const [prescriptions, setPrescriptions] = useState([{ vidal_id: "", dose: "" }]);
  const [allergies, setAllergies] = useState("");
  const [pathologies, setPathologies] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);

  const addRow = () => setPrescriptions((p) => [...p, { vidal_id: "", dose: "" }]);
  const removeRow = (idx) => setPrescriptions((p) => p.filter((_, i) => i !== idx));
  const updateRow = (idx, k, v) => setPrescriptions((p) =>
    p.map((row, i) => (i === idx ? { ...row, [k]: v } : row))
  );

  const run = async () => {
    if (prescriptions.every((p) => !p.vidal_id)) {
      toast.warning("Saisir au moins un ID VIDAL");
      return;
    }
    setLoading(true);
    try {
      const r = await apiClient.post("/vidal/prescription/analyze", {
        patient: {
          birth_date: patient.birth_date || null,
          sex: patient.sex,
          weight_kg: patient.weight_kg ? parseFloat(patient.weight_kg) : null,
        },
        prescriptions: prescriptions.filter((p) => p.vidal_id),
        allergies: allergies.split(",").map((s) => s.trim()).filter(Boolean),
        pathologies: pathologies.split(",").map((s) => s.trim()).filter(Boolean),
      });
      setResult(r.data?.data || r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
    setTimeout(() => setLoading(false), 0);
  };

  return (
    <div className="space-y-4">
      {/* Patient */}
      <div className="ring-1 ring-slate-200 rounded-lg p-3 bg-white grid sm:grid-cols-3 gap-3">
        <label className="block text-xs">
          <span className="block text-slate-600 mb-1">Date de naissance</span>
          <input
            type="date"
            value={patient.birth_date}
            onChange={(e) => setPatient({ ...patient, birth_date: e.target.value })}
            className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300"
            data-testid="vidal-patient-birth"
          />
        </label>
        <label className="block text-xs">
          <span className="block text-slate-600 mb-1">Sexe</span>
          <select
            value={patient.sex}
            onChange={(e) => setPatient({ ...patient, sex: e.target.value })}
            className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300"
            data-testid="vidal-patient-sex"
          >
            <option value="F">F</option>
            <option value="M">M</option>
          </select>
        </label>
        <label className="block text-xs">
          <span className="block text-slate-600 mb-1">Poids (kg)</span>
          <input
            type="number"
            step="0.1"
            value={patient.weight_kg}
            onChange={(e) => setPatient({ ...patient, weight_kg: e.target.value })}
            className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300"
            data-testid="vidal-patient-weight"
          />
        </label>
      </div>

      {/* Prescriptions */}
      <div className="ring-1 ring-slate-200 rounded-lg p-3 bg-white">
        <h4 className="text-xs font-semibold text-slate-700 mb-2">Médicaments prescrits (ID VIDAL + posologie)</h4>
        {prescriptions.map((row, idx) => (
          <div key={idx} className="grid sm:grid-cols-[1fr_2fr_auto] gap-2 mb-2">
            <input
              type="number"
              placeholder="ID VIDAL"
              value={row.vidal_id}
              onChange={(e) => updateRow(idx, "vidal_id", parseInt(e.target.value) || "")}
              className="text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono"
              data-testid={`vidal-rx-id-${idx}`}
            />
            <input
              type="text"
              placeholder="Posologie (ex: 500 mg x 3/j pendant 7 jours)"
              value={row.dose}
              onChange={(e) => updateRow(idx, "dose", e.target.value)}
              className="text-xs px-2 py-1.5 rounded ring-1 ring-slate-300"
              data-testid={`vidal-rx-dose-${idx}`}
            />
            {prescriptions.length > 1 && (
              <button onClick={() => removeRow(idx)} className="text-rose-500 hover:text-rose-700 px-2" data-testid={`vidal-rx-remove-${idx}`}>
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
        ))}
        <button
          onClick={addRow}
          className="text-xs px-2 py-1 rounded ring-1 ring-slate-300 hover:bg-slate-50 inline-flex items-center gap-1"
          data-testid="vidal-rx-add"
        >
          <Plus className="h-3 w-3" /> Ajouter un médicament
        </button>
      </div>

      {/* Context */}
      <div className="ring-1 ring-slate-200 rounded-lg p-3 bg-white grid sm:grid-cols-2 gap-3">
        <label className="block text-xs">
          <span className="block text-slate-600 mb-1">Allergies connues (séparées par virgules)</span>
          <input
            type="text"
            value={allergies}
            onChange={(e) => setAllergies(e.target.value)}
            placeholder="pénicilline, arachide…"
            className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300"
            data-testid="vidal-allergies"
          />
        </label>
        <label className="block text-xs">
          <span className="block text-slate-600 mb-1">Pathologies (séparées par virgules)</span>
          <input
            type="text"
            value={pathologies}
            onChange={(e) => setPathologies(e.target.value)}
            placeholder="diabète, insuffisance rénale…"
            className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300"
            data-testid="vidal-pathologies"
          />
        </label>
      </div>

      <button
        onClick={run}
        disabled={loading}
        className="text-sm px-4 py-2 rounded bg-rose-600 hover:bg-rose-700 text-white inline-flex items-center gap-2 disabled:opacity-60"
        data-testid="vidal-analyze-submit"
      >
        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <AlertTriangle className="h-4 w-4" />} Analyser la prescription
      </button>

      {result && (
        <div className="ring-1 ring-rose-200 rounded-lg p-3 bg-rose-50/30" data-testid="vidal-analyze-result">
          <h4 className="text-xs font-semibold text-rose-800 mb-2">Alertes VIDAL</h4>
          <pre className="text-[11px] bg-white ring-1 ring-rose-100 rounded p-3 overflow-auto max-h-96">
            {JSON.stringify(result, null, 2).slice(0, 8000)}
          </pre>
        </div>
      )}
    </div>
  );
}

export default function Vidal() {
  const [tab, setTab] = useState("search");
  const [pickedId, setPickedId] = useState(null);
  const [quota, setQuota] = useState(null);

  useEffect(() => {
    apiClient.get("/vidal/quota/me").then((r) => setQuota(r.data)).catch(() => setQuota(null));
  }, []);

  return (
    <div className="p-4 md:p-6 space-y-4" data-testid="portal-vidal">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-slate-800 inline-flex items-center gap-2">
          <Stethoscope className="h-6 w-6 text-fuchsia-600" />
          VIDAL France
        </h1>
        {quota && (
          <div className="text-xs text-slate-600 ring-1 ring-slate-200 rounded px-3 py-1.5 bg-white" data-testid="vidal-quota-badge">
            Quota : <strong>{quota.used}</strong>
            {quota.limit > 0 ? ` / ${quota.limit}` : " (illimité)"} aujourd&apos;hui
            <span className={`ml-2 text-[10px] px-1.5 py-0.5 rounded ${quota.mode === "production" ? "bg-rose-100 text-rose-700" : "bg-emerald-100 text-emerald-700"}`}>
              {quota.mode === "production" ? "🚀 PROD" : "🧪 TEST"}
            </span>
          </div>
        )}
      </div>

      <div className="flex flex-wrap gap-1 ring-1 ring-slate-200 rounded-lg p-1 bg-white w-fit">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`text-xs px-3 py-1.5 rounded inline-flex items-center gap-1 ${tab === t.key ? "bg-fuchsia-600 text-white" : "text-slate-600 hover:bg-slate-50"}`}
            data-testid={`vidal-tab-${t.key}`}
          >
            <t.icon className="h-3 w-3" /> {t.label}
          </button>
        ))}
      </div>

      <div className="ring-1 ring-slate-200 rounded-lg bg-white p-4">
        {tab === "search" && <SearchTab onPick={setPickedId} />}
        {tab === "catalog" && <CatalogTab onPick={setPickedId} />}
        {tab === "analyze" && <AnalyzeTab />}
      </div>

      {pickedId && <ProductDetail id={pickedId} onClose={() => setPickedId(null)} />}
    </div>
  );
}
