// Iter43-fix24ac (2026-06-16) — VIDAL Actions configurable table.
// Lets the admin define / edit / delete VIDAL API actions:
//   - method (GET/POST/PUT/DELETE)
//   - path (with {placeholders})
//   - query params (key + value template)
//   - body template (XML for /alerts/full etc.)
//   - is_public (gates WhatsApp access via "Abonné VIDAL" tag)
//   - exclamation_command (`!recherche`)
//   - portal button visibility + label
//   - example URL (admin reference)
//
// Each action's example URL is shown so the admin can compare with the
// VIDAL documentation when editing.
import React, { useEffect, useState } from "react";
import { apiClient } from "../../lib/api";
import { toast } from "sonner";
import VidalActionTesterModal from "./VidalActionTesterModal";

const METHODS = ["GET", "POST", "PUT", "DELETE"];

export default function VidalActionsSection() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [actions, setActions] = useState([]);
  const [expandedId, setExpandedId] = useState(null);
  // Iter43-fix24ae (2026-06-17) — Tester modal state
  const [testerAction, setTesterAction] = useState(null);

  const reload = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/vidal/actions");
      setActions(r.data?.actions || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Chargement actions VIDAL impossible");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const updateAction = (id, patch) => {
    setActions((prev) => prev.map((a) => (a.id === id ? { ...a, ...patch } : a)));
  };

  const updateQueryParam = (actionId, idx, patch) => {
    setActions((prev) =>
      prev.map((a) => {
        if (a.id !== actionId) return a;
        const qp = [...(a.query_params || [])];
        qp[idx] = { ...qp[idx], ...patch };
        return { ...a, query_params: qp };
      }),
    );
  };

  const addQueryParam = (actionId) => {
    setActions((prev) =>
      prev.map((a) => (a.id === actionId
        ? { ...a, query_params: [...(a.query_params || []), { key: "", value_template: "", required: false }] }
        : a)),
    );
  };

  const removeQueryParam = (actionId, idx) => {
    setActions((prev) =>
      prev.map((a) => (a.id === actionId
        ? { ...a, query_params: (a.query_params || []).filter((_, i) => i !== idx) }
        : a)),
    );
  };

  const addAction = () => {
    const id = `action_${Date.now().toString(36)}`;
    const newAction = {
      id, label: "Nouvelle action", method: "GET", path: "/", query_params: [],
      body_template: "", is_public: true, exclamation_command: "",
      portal_button_visible: true, portal_button_label: "Action",
      input_label: "Saisir une valeur", input_param: "q", example_url: "",
      order: actions.length + 1,
    };
    setActions((prev) => [...prev, newAction]);
    setExpandedId(id);
  };

  const removeAction = (id) => {
    if (!window.confirm(`Supprimer l'action "${id}" ?`)) return;
    setActions((prev) => prev.filter((a) => a.id !== id));
  };

  const save = async () => {
    setSaving(true);
    try {
      await apiClient.put("/admin/vidal/actions", { actions });
      toast.success(`${actions.length} actions VIDAL enregistrées`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Sauvegarde impossible");
    } finally {
      setSaving(false);
    }
  };

  const resetDefaults = async () => {
    if (!window.confirm("Réinitialiser les actions VIDAL aux valeurs par défaut ? Tes modifications seront perdues.")) return;
    try {
      await apiClient.post("/admin/vidal/actions/reset-defaults");
      await reload();
      toast.success("Actions VIDAL réinitialisées");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Réinitialisation impossible");
    }
  };

  if (loading) {
    return <p className="text-sm text-slate-500 italic">Chargement…</p>;
  }

  return (
    <div className="space-y-4" data-testid="vidal-actions-section">
      <div className="text-sm text-slate-700 bg-amber-50 ring-1 ring-amber-200 p-3 rounded leading-relaxed">
        <p className="font-semibold mb-1">⚙️ Actions VIDAL configurables</p>
        <p className="text-xs">
          Chaque action ci-dessous correspond à une <strong>fonction VIDAL</strong> appelable depuis :
        </p>
        <ul className="text-xs list-disc pl-5 mt-1 space-y-0.5">
          <li>La page <strong>/portal/vidal</strong> (un bouton par action visible)</li>
          <li>WhatsApp via <code className="bg-amber-100 px-1 rounded">!commande</code> (ex. <code className="bg-amber-100 px-1 rounded">!recherche doliprane</code>)</li>
        </ul>
        <p className="text-xs mt-1">
          À l&apos;exécution, l&apos;URL finale est : <code className="bg-amber-100 px-1 rounded text-[10px]">{`{base_url}{path}?{query}&app_id=...&app_key=...`}</code>
        </p>
        <p className="text-xs mt-1">
          Les actions <strong>non publiques</strong> (<code className="bg-amber-100 px-1 rounded">is_public=false</code>) ne sont accessibles via WhatsApp que si le contact porte le tag <strong>« Abonné VIDAL »</strong>.
        </p>
      </div>

      <div className="space-y-2">
        {actions.map((a, idx) => (
          <ActionEditor
            key={a.id}
            action={a}
            isExpanded={expandedId === a.id}
            onToggle={() => setExpandedId(expandedId === a.id ? null : a.id)}
            onUpdate={(patch) => updateAction(a.id, patch)}
            onUpdateQueryParam={(qIdx, patch) => updateQueryParam(a.id, qIdx, patch)}
            onAddQueryParam={() => addQueryParam(a.id)}
            onRemoveQueryParam={(qIdx) => removeQueryParam(a.id, qIdx)}
            onRemove={() => removeAction(a.id)}
            onTest={() => setTesterAction(a)}
          />
        ))}
      </div>

      <div className="flex items-center gap-2 pt-2 border-t border-slate-200">
        <button
          type="button"
          onClick={addAction}
          className="text-xs px-3 py-1.5 rounded bg-slate-100 hover:bg-slate-200 ring-1 ring-slate-300"
          data-testid="vidal-actions-add"
        >
          ➕ Ajouter une action
        </button>
        <button
          type="button"
          onClick={resetDefaults}
          className="text-xs px-3 py-1.5 rounded bg-rose-50 hover:bg-rose-100 ring-1 ring-rose-200 text-rose-700"
          data-testid="vidal-actions-reset"
        >
          🔄 Réinitialiser aux défauts
        </button>
        <div className="flex-1" />
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="text-sm px-4 py-1.5 rounded bg-fuchsia-600 hover:bg-fuchsia-700 text-white font-semibold disabled:opacity-50"
          data-testid="vidal-actions-save"
        >
          {saving ? "Enregistrement…" : "💾 Enregistrer les actions VIDAL"}
        </button>
      </div>

      {testerAction && (
        <VidalActionTesterModal
          key={testerAction.id}
          action={testerAction}
          onClose={() => setTesterAction(null)}
        />
      )}
    </div>
  );
}

function ActionEditor({ action, isExpanded, onToggle, onUpdate, onUpdateQueryParam, onAddQueryParam, onRemoveQueryParam, onRemove, onTest }) {
  const m = action.method || "GET";
  const headerColor = action.is_public ? "bg-emerald-50 ring-emerald-200" : "bg-amber-50 ring-amber-200";
  return (
    <div className={`rounded ring-1 ${headerColor}`} data-testid={`vidal-action-${action.id}`}>
      <div className="flex items-center gap-2 p-2">
        <button
          type="button"
          onClick={onToggle}
          className="text-xs text-slate-600 hover:text-slate-900 flex-1 text-left"
        >
          {isExpanded ? "▼" : "▶"}{" "}
          <span className="font-mono font-bold text-[10px] uppercase">{m}</span>{" "}
          <span className="font-mono text-[11px] text-slate-700">{action.path}</span>{" "}
          <span className="text-slate-500">— {action.label}</span>
          {action.exclamation_command && (
            <span className="ml-2 px-1.5 py-0.5 rounded bg-slate-200 text-slate-600 text-[10px] font-mono">!{action.exclamation_command}</span>
          )}
          {!action.is_public && (
            <span className="ml-1 px-1.5 py-0.5 rounded bg-amber-200 text-amber-800 text-[10px] font-semibold">🔒 Abonné VIDAL</span>
          )}
        </button>
        <button
          type="button"
          onClick={onTest}
          className="text-xs text-sky-700 hover:text-sky-900 px-2 py-0.5 rounded bg-sky-100 hover:bg-sky-200 ring-1 ring-sky-300 font-semibold"
          title="Tester cette action — voir la requête et la réponse VIDAL"
          data-testid={`vidal-action-${action.id}-test`}
        >
          🧪 Tester
        </button>
        <button
          type="button"
          onClick={onRemove}
          className="text-xs text-rose-600 hover:text-rose-800 px-1.5 py-0.5 rounded hover:bg-rose-100"
          data-testid={`vidal-action-${action.id}-remove`}
        >
          🗑
        </button>
      </div>

      {isExpanded && (
        <div className="border-t border-slate-200 bg-white p-3 space-y-2.5 text-xs">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            <Field label="Identifiant (slug)" value={action.id} onChange={(v) => onUpdate({ id: v })} placeholder="ex : recherche" mono testId={`vidal-action-${action.id}-id`} />
            <Field label="Libellé humain" value={action.label} onChange={(v) => onUpdate({ label: v })} placeholder="ex : Recherche par nom" />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-[120px_1fr] gap-2">
            <div>
              <label className="block text-[10px] font-semibold text-slate-600 mb-0.5">Méthode</label>
              <select
                value={m}
                onChange={(e) => onUpdate({ method: e.target.value })}
                className="w-full px-2 py-1 rounded ring-1 ring-slate-300 focus:ring-2 focus:ring-fuchsia-400 outline-none font-mono"
                data-testid={`vidal-action-${action.id}-method`}
              >
                {METHODS.map((mm) => <option key={mm}>{mm}</option>)}
              </select>
            </div>
            <Field
              label="Chemin (path) avec placeholders {var}"
              value={action.path}
              onChange={(v) => onUpdate({ path: v })}
              placeholder="ex : /product/{id}"
              mono
              testId={`vidal-action-${action.id}-path`}
            />
          </div>

          {/* Query params */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-[10px] font-semibold text-slate-600">Query params</label>
              <button type="button" onClick={onAddQueryParam} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 hover:bg-slate-200">+ ajouter</button>
            </div>
            {(action.query_params || []).length === 0 ? (
              <p className="text-[10px] italic text-slate-400 px-1">Aucun paramètre — les clés <code className="bg-slate-100 px-0.5 rounded">app_id</code> / <code className="bg-slate-100 px-0.5 rounded">app_key</code> sont ajoutées automatiquement.</p>
            ) : (
              <div className="space-y-1">
                {(action.query_params || []).map((qp, idx) => (
                  <div key={idx} className="flex items-center gap-1.5">
                    <input
                      type="text"
                      placeholder="clé"
                      value={qp.key || ""}
                      onChange={(e) => onUpdateQueryParam(idx, { key: e.target.value })}
                      className="w-32 px-1.5 py-0.5 rounded ring-1 ring-slate-300 text-[11px] font-mono"
                    />
                    <span className="text-slate-400">=</span>
                    <input
                      type="text"
                      placeholder="valeur (peut contenir {var})"
                      value={qp.value_template || ""}
                      onChange={(e) => onUpdateQueryParam(idx, { value_template: e.target.value })}
                      className="flex-1 px-1.5 py-0.5 rounded ring-1 ring-slate-300 text-[11px] font-mono"
                    />
                    <label className="flex items-center gap-1 text-[10px] text-slate-500">
                      <input type="checkbox" checked={!!qp.required} onChange={(e) => onUpdateQueryParam(idx, { required: e.target.checked })} />
                      req.
                    </label>
                    <button type="button" onClick={() => onRemoveQueryParam(idx)} className="text-rose-500 hover:text-rose-700 text-[10px]">×</button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {(m === "POST" || m === "PUT") && (
            <div>
              <label className="block text-[10px] font-semibold text-slate-600 mb-0.5">
                Body template (XML / JSON) — placeholders <code className="bg-slate-100 px-0.5 rounded">{`{var}`}</code> rendus à l&apos;exécution
              </label>
              <textarea
                value={action.body_template || ""}
                onChange={(e) => onUpdate({ body_template: e.target.value })}
                rows={8}
                placeholder='<?xml version="1.0" encoding="UTF-8"?>...'
                className="w-full px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono text-[10px] focus:ring-2 focus:ring-fuchsia-400 outline-none"
                data-testid={`vidal-action-${action.id}-body`}
              />
              <p className="text-[10px] text-slate-500 italic mt-0.5">
                Envoyé en <code>Content-Type: text/xml; charset=utf-8</code> (configuration backend `_vidal_call`)
              </p>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-2 pt-2 border-t border-slate-100">
            <label className="flex items-center gap-1.5 text-xs cursor-pointer">
              <input
                type="checkbox"
                checked={!!action.is_public}
                onChange={(e) => onUpdate({ is_public: e.target.checked })}
                data-testid={`vidal-action-${action.id}-public`}
              />
              <span><strong>Public</strong> via WhatsApp (sinon réservé aux <em>Abonné VIDAL</em>)</span>
            </label>
            <Field label="Commande WhatsApp (sans !)" value={action.exclamation_command} onChange={(v) => onUpdate({ exclamation_command: v.replace(/\s+/g, "").toLowerCase() })} placeholder="ex : recherche" mono testId={`vidal-action-${action.id}-cmd`} />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            <label className="flex items-center gap-1.5 text-xs cursor-pointer">
              <input
                type="checkbox"
                checked={!!action.portal_button_visible}
                onChange={(e) => onUpdate({ portal_button_visible: e.target.checked })}
              />
              <span>Bouton visible sur <strong>/portal/vidal</strong></span>
            </label>
            <Field label="Libellé du bouton portail" value={action.portal_button_label} onChange={(v) => onUpdate({ portal_button_label: v })} placeholder="ex : 🔍 Recherche" />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            <Field label="Texte d'invite du champ (input)" value={action.input_label} onChange={(v) => onUpdate({ input_label: v })} placeholder="ex : Médicament" />
            <Field label="Nom du placeholder lié au champ" value={action.input_param} onChange={(v) => onUpdate({ input_param: v })} placeholder="ex : q ou id" mono />
          </div>

          <div>
            <label className="block text-[10px] font-semibold text-slate-600 mb-0.5">Exemple d&apos;URL VIDAL (doc / référence)</label>
            <input
              type="text"
              value={action.example_url || ""}
              onChange={(e) => onUpdate({ example_url: e.target.value })}
              placeholder="https://api.vidal.fr/rest/api/products?app_id=XXX&app_key=YYY&q=doliprane"
              className="w-full px-2 py-1 rounded ring-1 ring-slate-300 font-mono text-[10px]"
            />
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, value, onChange, placeholder, mono = false, testId }) {
  return (
    <div>
      <label className="block text-[10px] font-semibold text-slate-600 mb-0.5">{label}</label>
      <input
        type="text"
        value={value || ""}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={`w-full px-2 py-1 rounded ring-1 ring-slate-300 focus:ring-2 focus:ring-fuchsia-400 outline-none text-xs ${mono ? "font-mono" : ""}`}
        data-testid={testId}
      />
    </div>
  );
}
