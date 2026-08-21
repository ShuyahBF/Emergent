// Iter43-fix24az-ac (2026-07-22) — Standalone Prescription Analysis page.
// Extracted from Vidal.jsx (AnalyzeTab) so médecins can access it directly
// via sidebar link `/portal/prescription-analysis` without needing the
// Search/Catalogue tabs.
//
// The internal Vidal tab still re-uses this component so behavior remains
// identical between the standalone page and the Vidal tab.
import React, { useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { AlertTriangle, Loader2, Plus, X } from "lucide-react";

export function PrescriptionAnalysisForm() {
  const [patient, setPatient] = useState({ birth_date: "", sex: "F", weight_kg: "" });
  const [prescriptions, setPrescriptions] = useState([{ vidal_id: "", dose: "" }]);
  const [allergies, setAllergies] = useState("");
  const [pathologies, setPathologies] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [errorState, setErrorState] = useState(null);

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
    setErrorState(null);
    setResult(null);
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
      // Sanitize: strip debug fields (`_request`) before rendering so end-users
      // don't see the outbound VIDAL URL / app_id / body dumped as JSON.
      const raw = r.data?.data || r.data || {};
      const clean = { ...raw };
      delete clean._request;
      delete clean.request;
      delete clean.raw;
      setResult(clean);
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.message || "Erreur inconnue";
      setErrorState(detail);
      toast.error(detail);
    }
    setTimeout(() => setLoading(false), 0);
  };

  return (
    <div className="space-y-4" data-testid="prescription-analysis-form">
      {/* Patient */}
      <div className="ring-1 ring-slate-200 rounded-lg p-3 bg-white grid sm:grid-cols-3 gap-3">
        <label className="block text-xs">
          <span className="block text-slate-600 mb-1">Date de naissance</span>
          <input
            type="date"
            value={patient.birth_date}
            onChange={(e) => setPatient({ ...patient, birth_date: e.target.value })}
            className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300"
            data-testid="rx-patient-birth"
          />
        </label>
        <label className="block text-xs">
          <span className="block text-slate-600 mb-1">Sexe</span>
          <select
            value={patient.sex}
            onChange={(e) => setPatient({ ...patient, sex: e.target.value })}
            className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300"
            data-testid="rx-patient-sex"
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
            data-testid="rx-patient-weight"
          />
        </label>
      </div>

      {/* Prescriptions */}
      <div className="ring-1 ring-slate-200 rounded-lg p-3 bg-white">
        <h4 className="text-xs font-semibold text-slate-700 mb-2">
          Médicaments prescrits (ID VIDAL + posologie)
        </h4>
        {prescriptions.map((row, idx) => (
          <div key={idx} className="grid sm:grid-cols-[1fr_2fr_auto] gap-2 mb-2">
            <input
              type="number"
              placeholder="ID VIDAL"
              value={row.vidal_id}
              onChange={(e) => updateRow(idx, "vidal_id", parseInt(e.target.value) || "")}
              className="text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono"
              data-testid={`rx-id-${idx}`}
            />
            <input
              type="text"
              placeholder="Posologie (ex: 500 mg x 3/j pendant 7 jours)"
              value={row.dose}
              onChange={(e) => updateRow(idx, "dose", e.target.value)}
              className="text-xs px-2 py-1.5 rounded ring-1 ring-slate-300"
              data-testid={`rx-dose-${idx}`}
            />
            {prescriptions.length > 1 && (
              <button
                onClick={() => removeRow(idx)}
                className="text-rose-500 hover:text-rose-700 px-2"
                data-testid={`rx-remove-${idx}`}
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
        ))}
        <button
          onClick={addRow}
          className="text-xs px-2 py-1 rounded ring-1 ring-slate-300 hover:bg-slate-50 inline-flex items-center gap-1"
          data-testid="rx-add"
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
            data-testid="rx-allergies"
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
            data-testid="rx-pathologies"
          />
        </label>
      </div>

      <button
        onClick={run}
        disabled={loading}
        className="text-sm px-4 py-2 rounded bg-rose-600 hover:bg-rose-700 text-white inline-flex items-center gap-2 disabled:opacity-60"
        data-testid="rx-analyze-submit"
      >
        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <AlertTriangle className="h-4 w-4" />}
        Analyser la prescription
      </button>

      {errorState && (
        <div
          className="ring-1 ring-amber-200 rounded-lg p-3 bg-amber-50/60 text-xs text-amber-800"
          data-testid="rx-analyze-error"
        >
          <div className="font-semibold mb-1">Analyse impossible</div>
          <div className="whitespace-pre-wrap">{errorState}</div>
        </div>
      )}

      {result && (
        <div className="ring-1 ring-rose-200 rounded-lg p-3 bg-rose-50/30" data-testid="rx-analyze-result">
          <h4 className="text-xs font-semibold text-rose-800 mb-2">Alertes VIDAL</h4>
          <pre className="text-[11px] bg-white ring-1 ring-rose-100 rounded p-3 overflow-auto max-h-96">
            {JSON.stringify(result, null, 2).slice(0, 8000)}
          </pre>
        </div>
      )}
    </div>
  );
}

// Standalone page. NOTE: the parent Route `/portal` already wraps children
// with <PortalLayout>, so we render the page content directly (no double
// wrapping — that was the "page vide" bug reported by the user on 2026-02-14).
export default function PrescriptionAnalysis() {
  return (
    <div className="space-y-4" data-testid="prescription-analysis-page">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-lg bg-rose-100 ring-1 ring-rose-200 flex items-center justify-center">
          <AlertTriangle className="h-5 w-5 text-rose-600" />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-slate-800">Analyse de prescription</h1>
          <p className="text-xs text-slate-500">
            Analyse VIDAL des interactions, contre-indications et posologies pour un patient donné.
          </p>
        </div>
      </div>
      <PrescriptionAnalysisForm />
    </div>
  );
}
