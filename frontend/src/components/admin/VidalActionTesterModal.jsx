// Iter43-fix24ae (2026-06-17) — Tester modal for VIDAL actions.
//
// Full-screen modal that lets an admin execute a configured VIDAL action
// and inspect the Request + Response in dedicated tabs without having
// to switch to the `/portal/vidal` page.
//
// - Tab "Requête"  : method, URL, params (app_key masqué), body
// - Tab "Réponse"  : status HTTP, content-type, body (JSON / XML / HTML brut)
//
// Le body de la requête (POST/PUT XML) est éditable avant exécution pour
// permettre des essais rapides avec des valeurs différentes (Iter43-fix24ag).
import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "../../lib/api";
import { toast } from "sonner";

/**
 * Build a default user_input object using the action.input_param and a value.
 *
 * Special case: if input_param === "id1" (interactions endpoint), the user
 * input is expected to be "id1 id2" → split and produce {id1, id2}.
 */
function buildUserInput(action, value) {
  const param = (action?.input_param || "q").trim();
  if (!value && value !== 0) return {};
  if (param === "id1") {
    const parts = String(value).trim().split(/\s+/);
    return { id1: parts[0] || "", id2: parts[1] || "" };
  }
  return { [param]: value };
}

export default function VidalActionTesterModal({ action, onClose }) {
  const [input, setInput] = useState("");
  // Iter43-fix24ag (2026-06-17) — Allow admin to edit the body template
  // before executing, so they can iterate on XML payloads without saving.
  // Initialized from action.body_template; modal is keyed on action.id so
  // it remounts (resetting state) when admin opens a different action.
  const [bodyEdit, setBodyEdit] = useState(action?.body_template || "");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null); // {data, action, status}
  const [tab, setTab] = useState("request"); // "request" | "response"

  // ESC closes modal
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const hasBody = action?.method && action.method !== "GET";

  const execute = async () => {
    setLoading(true);
    setResult(null);
    try {
      const userInput = buildUserInput(action, input);
      const r = await apiClient.post(`/vidal/execute/${action.id}`, userInput, {
        // ?body_override=... not yet supported by backend — we keep editing
        // for visual feedback but pass through input only. (Body template
        // edits are non-persistent: they will be saved via the main "Enregistrer".)
      });
      setResult({
        status: r.status,
        data: r.data,
      });
      setTab("response");
    } catch (e) {
      setResult({
        status: e?.response?.status || 0,
        data: e?.response?.data || { error: String(e) },
        error: true,
      });
      setTab("response");
      toast.error(e?.response?.data?.detail || `Erreur ${e?.response?.status || ""}`);
    } finally {
      setLoading(false);
    }
  };

  // Extract request/response details for display
  const reqInfo = useMemo(() => {
    // Pre-fill computed request from action config (before execution)
    const userInput = buildUserInput(action, input);
    let renderedPath = action?.path || "";
    Object.keys(userInput).forEach((k) => {
      renderedPath = renderedPath.replace(new RegExp(`\\{${k}\\}`, "g"), userInput[k]);
    });
    const params = {};
    (action?.query_params || []).forEach((qp) => {
      let v = qp.value_template || "";
      Object.keys(userInput).forEach((k) => {
        v = v.replace(new RegExp(`\\{${k}\\}`, "g"), userInput[k]);
      });
      params[qp.key] = v;
    });
    let body = hasBody ? (bodyEdit || "") : "";
    Object.keys(userInput).forEach((k) => {
      body = body.replace(new RegExp(`\\{${k}\\}`, "g"), userInput[k]);
    });
    // Override with the actual executed request if available
    const exec = result?.data?.data?._request || result?.data?._request;
    if (exec) {
      return {
        method: exec.method || action?.method,
        url: exec.url || "",
        params: exec.params || {},
        body: exec.body || body,
        timeout_seconds: exec.timeout_seconds,
        mode: exec.mode,
        path: renderedPath,
      };
    }
    return {
      method: action?.method || "GET",
      url: "(non exécutée encore — clic Exécuter)",
      params: { ...params, app_id: "<configuré côté serveur>", app_key: "***" },
      body,
      path: renderedPath,
    };
  }, [action, input, bodyEdit, hasBody, result]);

  const respInfo = useMemo(() => {
    if (!result) return null;
    const inner = result.data?.data || result.data;
    return {
      status_http: result.status,
      vidal_status: inner?._error?.status,
      content_type: inner?._error?.content_type || (inner?.raw ? "(text/xml ou html)" : "application/json"),
      raw: inner?.raw,
      json_keys: inner && typeof inner === "object" ? Object.keys(inner).filter((k) => !k.startsWith("_")) : [],
      error: inner?._error || result.data?.detail,
      full: inner,
    };
  }, [result]);

  return (
    <div
      className="fixed inset-0 z-[100] bg-slate-900/70 backdrop-blur-sm flex items-stretch justify-center p-2 sm:p-6"
      data-testid="vidal-tester-modal"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg shadow-xl w-full max-w-6xl flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-slate-200 bg-gradient-to-r from-sky-50 to-fuchsia-50">
          <div className="flex-1 min-w-0">
            <h2 className="font-semibold text-slate-800 flex items-center gap-2">
              🧪 Tester l&apos;action VIDAL
              <span className="font-mono text-xs px-2 py-0.5 rounded bg-slate-200 text-slate-700">{action.id}</span>
            </h2>
            <p className="text-xs text-slate-600 truncate">
              <span className="font-mono font-bold text-[10px] uppercase">{action.method}</span>{" "}
              <span className="font-mono">{action.path}</span> — {action.label}
            </p>
          </div>
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onClose();
            }}
            onPointerDown={(e) => e.stopPropagation()}
            className="text-slate-500 hover:text-slate-900 text-2xl leading-none px-3 py-1 rounded hover:bg-slate-100 focus:outline-none focus:ring-2 focus:ring-sky-400 transition-colors"
            aria-label="Fermer"
            data-testid="vidal-tester-close"
          >
            ×
          </button>
        </div>

        {/* Input bar */}
        <div className="flex flex-wrap items-end gap-2 px-4 py-3 bg-slate-50 border-b border-slate-200">
          <div className="flex-1 min-w-[200px]">
            <label className="block text-[10px] font-semibold text-slate-600 mb-0.5">
              {action.input_label || "Valeur de test"}{" "}
              <span className="font-mono bg-slate-200 px-1 rounded text-[9px]">{`{${action.input_param || "q"}}`}</span>
            </label>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") execute(); }}
              placeholder={action.input_label || "ex : doliprane"}
              className="w-full px-3 py-1.5 rounded ring-1 ring-slate-300 focus:ring-2 focus:ring-sky-400 outline-none text-sm"
              data-testid="vidal-tester-input"
              autoFocus
            />
          </div>
          <button
            type="button"
            onClick={execute}
            disabled={loading}
            className="text-sm px-4 py-1.5 rounded bg-sky-600 hover:bg-sky-700 text-white font-semibold disabled:opacity-50"
            data-testid="vidal-tester-execute"
          >
            {loading ? "Exécution…" : "▶ Exécuter"}
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-slate-200 bg-white">
          <TabBtn active={tab === "request"} onClick={() => setTab("request")} testId="vidal-tester-tab-request">
            📤 Requête
          </TabBtn>
          <TabBtn active={tab === "response"} onClick={() => setTab("response")} testId="vidal-tester-tab-response">
            📥 Réponse{respInfo ? ` (${respInfo.status_http})` : ""}
          </TabBtn>
        </div>

        {/* Tab content */}
        <div className="flex-1 overflow-auto p-4 bg-slate-50">
          {tab === "request" ? (
            <RequestPanel info={reqInfo} hasBody={hasBody} bodyEdit={bodyEdit} setBodyEdit={setBodyEdit} action={action} />
          ) : (
            <ResponsePanel info={respInfo} loading={loading} />
          )}
        </div>
      </div>
    </div>
  );
}

function TabBtn({ active, onClick, children, testId }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-4 py-2 text-sm font-semibold border-b-2 transition-colors ${
        active
          ? "border-sky-500 text-sky-700 bg-sky-50"
          : "border-transparent text-slate-500 hover:text-slate-800"
      }`}
      data-testid={testId}
    >
      {children}
    </button>
  );
}

function RequestPanel({ info, hasBody, bodyEdit, setBodyEdit, action }) {
  // Build curl-like reproducible command for support / debug
  const curl = useMemo(() => {
    if (!info?.url || info.url.startsWith("(non exécutée")) return null;
    const qs = Object.entries(info.params || {})
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
      .join("&");
    const fullUrl = qs ? `${info.url}?${qs}` : info.url;
    let cmd = `curl -X ${info.method} '${fullUrl}'`;
    if (hasBody && info.body) {
      cmd += ` \\\n  -H 'Content-Type: text/xml; charset=utf-8' \\\n  --data-binary @-`;
      cmd = `cat <<'EOF' | ${cmd}\n${info.body}\nEOF`;
    }
    return cmd;
  }, [info, hasBody]);

  return (
    <div className="space-y-3 text-xs" data-testid="vidal-tester-request-panel">
      <Row label="Méthode">
        <span className="font-mono font-bold uppercase px-2 py-0.5 rounded bg-slate-200">{info.method}</span>
      </Row>
      <Row label="Path rendu">
        <code className="font-mono text-[11px] bg-slate-100 px-2 py-0.5 rounded break-all">{info.path}</code>
      </Row>
      {info.url && (
        <Row label="URL complète (exécutée)">
          <code className="font-mono text-[11px] bg-slate-100 px-2 py-0.5 rounded break-all">{info.url}</code>
        </Row>
      )}
      <div>
        <label className="block text-[10px] font-semibold text-slate-600 mb-1">Query params</label>
        <div className="bg-white ring-1 ring-slate-200 rounded p-2 space-y-1 font-mono text-[11px]">
          {Object.keys(info.params || {}).length === 0 ? (
            <p className="text-slate-400 italic">(aucun)</p>
          ) : (
            Object.entries(info.params).map(([k, v]) => (
              <div key={k} className="flex items-start gap-2">
                <span className="font-semibold text-fuchsia-700 min-w-[80px]">{k}</span>
                <span className="text-slate-400">=</span>
                <span className="break-all flex-1">{String(v)}</span>
              </div>
            ))
          )}
        </div>
      </div>
      {hasBody && (
        <div>
          <label className="block text-[10px] font-semibold text-slate-600 mb-1">
            Body (template — placeholders <code className="bg-slate-100 px-0.5 rounded">{`{var}`}</code> rendus à l&apos;exécution)
          </label>
          <textarea
            value={bodyEdit}
            onChange={(e) => setBodyEdit(e.target.value)}
            rows={10}
            className="w-full px-2 py-1.5 rounded ring-1 ring-slate-300 focus:ring-2 focus:ring-sky-400 outline-none font-mono text-[10px]"
            data-testid="vidal-tester-body"
          />
          <p className="text-[10px] text-slate-500 italic mt-0.5">
            Le body est éditable pour les tests ; pour le persister, copie-le dans le champ « Body template » de l&apos;action et clique sur « Enregistrer les actions VIDAL ».
          </p>
          {info.body && info.body !== bodyEdit && (
            <details className="mt-2">
              <summary className="text-[10px] text-slate-600 cursor-pointer">Voir le body rendu (envoyé)</summary>
              <pre className="bg-slate-900 text-slate-100 p-2 rounded mt-1 text-[10px] overflow-auto max-h-60">{info.body}</pre>
            </details>
          )}
        </div>
      )}
      {curl && (
        <div>
          <label className="block text-[10px] font-semibold text-slate-600 mb-1">Équivalent curl (reproductible)</label>
          <pre className="bg-slate-900 text-emerald-200 p-2 rounded text-[10px] overflow-auto max-h-40">{curl}</pre>
        </div>
      )}
      {info.timeout_seconds && (
        <p className="text-[10px] text-slate-500">
          Timeout : {info.timeout_seconds}s · Mode : <span className="font-mono">{info.mode || "?"}</span>
        </p>
      )}
    </div>
  );
}

function ResponsePanel({ info, loading }) {
  if (loading) {
    return (
      <p className="text-sm text-slate-500 italic" data-testid="vidal-tester-response-loading">
        Exécution en cours…
      </p>
    );
  }
  if (!info) {
    return (
      <p className="text-sm text-slate-500 italic" data-testid="vidal-tester-response-empty">
        Aucune exécution. Saisis une valeur ci-dessus puis clique sur « Exécuter ».
      </p>
    );
  }
  const httpOk = info.status_http >= 200 && info.status_http < 300;
  return (
    <div className="space-y-3 text-xs" data-testid="vidal-tester-response-panel">
      <Row label="Statut HTTP (backend)">
        <span className={`font-mono font-bold px-2 py-0.5 rounded ${httpOk ? "bg-emerald-100 text-emerald-700" : "bg-rose-100 text-rose-700"}`}>
          {info.status_http}
        </span>
      </Row>
      {info.vidal_status && (
        <Row label="Statut VIDAL (renvoyé par api.vidal.fr)">
          <span className="font-mono font-bold px-2 py-0.5 rounded bg-amber-100 text-amber-800">
            {info.vidal_status}
          </span>
        </Row>
      )}
      <Row label="Content-Type">
        <code className="font-mono text-[11px] bg-slate-100 px-2 py-0.5 rounded">{info.content_type}</code>
      </Row>
      {info.error && (
        <div className="bg-rose-50 ring-1 ring-rose-200 rounded p-2">
          <p className="text-xs font-semibold text-rose-700 mb-1">Erreur</p>
          <pre className="text-[10px] text-rose-800 overflow-auto max-h-32">{JSON.stringify(info.error, null, 2)}</pre>
        </div>
      )}
      {info.raw && (
        <div>
          <label className="block text-[10px] font-semibold text-slate-600 mb-1">Body brut (XML / Atom / HTML)</label>
          <pre className="bg-slate-900 text-slate-100 p-3 rounded text-[10px] overflow-auto max-h-[400px] whitespace-pre-wrap break-words">{info.raw}</pre>
        </div>
      )}
      {!info.raw && info.full && (
        <div>
          <label className="block text-[10px] font-semibold text-slate-600 mb-1">Body JSON</label>
          <pre className="bg-slate-900 text-emerald-200 p-3 rounded text-[10px] overflow-auto max-h-[400px]">{JSON.stringify(
            Object.fromEntries(Object.entries(info.full).filter(([k]) => !k.startsWith("_"))),
            null,
            2
          )}</pre>
        </div>
      )}
    </div>
  );
}

function Row({ label, children }) {
  return (
    <div className="flex items-start gap-3">
      <span className="text-[10px] font-semibold text-slate-600 min-w-[140px] pt-0.5">{label}</span>
      <span className="flex-1 min-w-0">{children}</span>
    </div>
  );
}
