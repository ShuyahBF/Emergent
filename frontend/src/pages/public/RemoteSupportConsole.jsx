import React, { useEffect, useState, useCallback } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import {
  Headphones, RefreshCw, Lock, AlertCircle, CheckCircle2, Save,
} from "lucide-react";
import { LOGO_URL } from "@/lib/brand";

/*
  Mobile-first remote console for the SAWALI admin to retune Liluvine
  threshold + support load level WITHOUT going through the login screen.
  Works via an HMAC-signed token issued by /api/admin/liluvine/remote-link.
  Bookmark this page on your phone and you can update the gauge in 2 taps.
*/
const BACKEND = process.env.REACT_APP_BACKEND_URL || "";

const LEVEL_LABELS = {
  0: "Inactif", 1: "Très disponible", 2: "Disponible",
  3: "Charge légère", 4: "Charge modérée", 5: "Charge élevée",
  6: "Très occupé", 7: "Saturé",
};
const BAR_COLORS = ["#16a34a", "#22c55e", "#84cc16", "#eab308", "#f59e0b", "#f97316", "#ef4444"];

export default function RemoteSupportConsole() {
  const { token } = useParams();
  const [state, setState] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [level, setLevel] = useState(0);
  const [threshold, setThreshold] = useState(6);
  const [label, setLabel] = useState("");
  const [saving, setSaving] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${BACKEND}/api/public/remote/support/${token}`, { timeout: 8000 });
      setState(r.data);
      setLevel(r.data.support_load_level ?? 0);
      setThreshold(r.data.liluvine_alert_threshold ?? 6);
      setLabel(r.data.support_load_label ?? "");
      setError(null);
    } catch (err) {
      setError(err?.response?.data?.detail || "Lien invalide ou expiré");
    } finally { setLoading(false); }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const update = async (patch, key) => {
    setSaving(key);
    try {
      const r = await axios.post(`${BACKEND}/api/public/remote/support/${token}`, patch, { timeout: 8000 });
      setState((s) => ({ ...(s || {}), ...r.data }));
      toast.success("Mis à jour");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setSaving(null); }
  };

  if (loading) {
    return <Centered><RefreshCw className="h-6 w-6 animate-spin text-amber-600" /><p className="text-sm text-slate-500">Vérification du lien…</p></Centered>;
  }
  if (error) {
    return <Centered>
      <AlertCircle className="h-10 w-10 text-rose-600" />
      <h1 className="font-display text-xl font-bold">Accès refusé</h1>
      <p className="text-sm text-slate-500 max-w-sm text-center">{error}</p>
      <p className="text-[11px] text-slate-400 max-w-sm text-center">Demandez à votre admin de générer un nouveau lien depuis Admin → Settings → Jauge d'occupation.</p>
    </Centered>;
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-100 via-amber-50/40 to-slate-100 py-8 px-4">
      <div className="max-w-md mx-auto">
        <div className="flex items-center gap-3 mb-6">
          <img src={LOGO_URL} alt="SAWALI" className="h-10 w-10 rounded ring-1 ring-slate-200 bg-white object-contain p-1" />
          <div>
            <p className="font-display font-bold text-slate-800">Console distante Liluvine</p>
            <p className="text-[10px] uppercase tracking-[0.2em] text-amber-700 inline-flex items-center gap-1">
              <Lock className="h-2.5 w-2.5" /> Accès sécurisé HMAC
            </p>
          </div>
        </div>

        {/* Current preview */}
        <div className="rounded-2xl bg-slate-900 text-slate-100 p-4 mb-4" data-testid="remote-current-preview">
          <p className="text-[10px] uppercase tracking-wider opacity-70 mb-2 inline-flex items-center gap-1">
            <Headphones className="h-3 w-3" /> Aperçu jauge
          </p>
          <div className="flex items-center gap-3">
            <Bars level={state?.support_load_level || 0} />
            <span className="font-semibold" style={{ color: (state?.support_load_level || 0) > 0 ? BAR_COLORS[(state?.support_load_level || 0) - 1] : "#94a3b8" }}>
              {state?.support_load_label || LEVEL_LABELS[state?.support_load_level || 0]}
            </span>
            <span className="text-xs opacity-60">{state?.support_load_level || 0}/7</span>
          </div>
          <div className="mt-2 text-[10px] opacity-70">
            Seuil Liluvine : <strong>{state?.liluvine_alert_threshold ?? 6}/7</strong>
            {state?.alert_active && <span className="ml-2 px-1.5 py-0.5 rounded bg-rose-600 text-white text-[9px]">ALERTE ACTIVE</span>}
          </div>
        </div>

        {/* Level picker */}
        <Section title="Niveau d'occupation actuel">
          <div className="grid grid-cols-4 gap-1.5" data-testid="remote-level-picker">
            {[0, 1, 2, 3, 4, 5, 6, 7].map((n) => {
              const active = level === n;
              return (
                <button
                  key={n}
                  type="button"
                  onClick={() => { setLevel(n); update({ level: n }, `level-${n}`); }}
                  disabled={saving === `level-${n}`}
                  className={`rounded-lg px-2 py-3 text-sm font-bold ring-1 transition ${active ? "ring-2 text-white shadow" : "ring-slate-200 text-slate-600 bg-white"}`}
                  style={active ? { backgroundColor: n > 0 ? BAR_COLORS[n - 1] : "#64748b", borderColor: n > 0 ? BAR_COLORS[n - 1] : "#64748b" } : {}}
                  data-testid={`remote-level-${n}`}
                >
                  {n}<span className="block text-[8px] font-normal opacity-80 truncate">{LEVEL_LABELS[n]}</span>
                </button>
              );
            })}
          </div>
        </Section>

        {/* Threshold picker */}
        <Section title="Seuil de déclenchement Liluvine">
          <p className="text-[11px] text-slate-500 mb-2">
            Quand le niveau actuel <strong>≥ seuil</strong>, Liluvine affiche le message d'alerte. Recommandation : 5 ou 6.
          </p>
          <div className="grid grid-cols-4 gap-1.5" data-testid="remote-threshold-picker">
            {[1, 2, 3, 4, 5, 6, 7].map((n) => {
              const active = threshold === n;
              return (
                <button
                  key={n}
                  type="button"
                  onClick={() => { setThreshold(n); update({ threshold: n }, `th-${n}`); }}
                  disabled={saving === `th-${n}`}
                  className={`rounded-lg px-2 py-2 text-sm font-bold ring-1 transition ${active ? "ring-2 bg-amber-50 text-amber-900 ring-amber-400" : "ring-slate-200 text-slate-600 bg-white"}`}
                  data-testid={`remote-threshold-${n}`}
                >
                  ≥{n}
                </button>
              );
            })}
          </div>
        </Section>

        {/* Custom label */}
        <Section title="Libellé personnalisé (optionnel)">
          <div className="flex gap-2">
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value.slice(0, 140))}
              placeholder="Ex: Forte affluence ce matin"
              className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
              data-testid="remote-label-input"
            />
            <button
              type="button"
              onClick={() => update({ label }, "label")}
              disabled={saving === "label"}
              className="inline-flex items-center gap-1 rounded-lg bg-amber-600 hover:bg-amber-700 text-white px-3 py-2 text-sm disabled:opacity-50"
              data-testid="remote-label-save"
            >
              {saving === "label" ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            </button>
          </div>
        </Section>

        <button
          onClick={load}
          className="w-full inline-flex items-center justify-center gap-2 rounded-lg ring-1 ring-slate-300 bg-white hover:bg-slate-50 px-3 py-2 text-sm mt-4"
          data-testid="remote-refresh"
        >
          <RefreshCw className="h-4 w-4" /> Rafraîchir
        </button>

        <p className="text-center text-[10px] text-slate-400 mt-6 inline-flex items-center justify-center w-full gap-1">
          <CheckCircle2 className="h-3 w-3 text-emerald-500" /> Lien HMAC validé — actions tracées
        </p>
      </div>
    </div>
  );
}

function Bars({ level }) {
  return (
    <div className="flex items-end gap-[2px] h-4">
      {[4, 6, 8, 10, 12, 14, 16].map((h, i) => (
        <div key={i} className="w-[3px] rounded-sm" style={{
          height: `${h}px`,
          backgroundColor: i < level ? BAR_COLORS[i] : "rgba(148,163,184,0.25)",
        }} />
      ))}
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div className="rounded-xl ring-1 ring-slate-200 bg-white p-3 mb-3">
      <h3 className="text-xs font-display font-bold text-slate-700 mb-2">{title}</h3>
      {children}
    </div>
  );
}

function Centered({ children }) {
  return <div className="min-h-screen flex flex-col items-center justify-center gap-3 bg-slate-50 px-4">{children}</div>;
}
