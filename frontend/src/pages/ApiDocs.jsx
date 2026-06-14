import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Link } from "react-router-dom";
import { Code2, ExternalLink, Database } from "lucide-react";

const METHOD_COLORS = {
  GET: "bg-emerald-100 text-emerald-700 border-emerald-200",
  POST: "bg-sky-100 text-sky-700 border-sky-200",
  PUT: "bg-amber-100 text-amber-700 border-amber-200",
  DELETE: "bg-rose-100 text-rose-700 border-rose-200",
};

export default function ApiDocs() {
  const [routes, setRoutes] = useState([]);
  useEffect(() => { apiClient.get("/api-routes").then((r) => setRoutes(r.data)).catch(() => {}); }, []);

  const grouped = routes.reduce((acc, r) => {
    const key = r.tags?.[0] || "Autres";
    (acc[key] = acc[key] || []).push(r);
    return acc;
  }, {});
  // Iter43-fix15 (2026-03) — utilise window.location.origin (runtime) plutôt que
  // process.env.REACT_APP_BACKEND_URL (build-time) pour que les liens Swagger/Redoc
  // pointent vers le domaine actuel (preview ou production) et non vers l'URL
  // capturée au moment du build.
  const backend = typeof window !== "undefined" ? window.location.origin : (process.env.REACT_APP_BACKEND_URL || "");

  return (
    <div className="min-h-screen bg-slate-50" data-testid="api-docs-page">
      <div className="bg-[#081226] text-white py-12 border-b border-white/10">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <Link to="/" className="text-xs uppercase tracking-[0.25em] text-sawali-blue-light hover:underline">← Retour au site</Link>
          <h1 className="mt-3 text-4xl font-display font-bold">Documentation de l'API SAWALI</h1>
          <p className="mt-3 text-slate-300 max-w-2xl">Tous les endpoints GET / POST / PUT / DELETE disponibles, regroupés par section.</p>
          <div className="mt-6 flex flex-wrap gap-3 text-sm">
            <a href={`${backend}/api/docs`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue px-4 py-2 hover:bg-sawali-blue-light">
              <ExternalLink className="h-4 w-4" /> Swagger UI interactif
            </a>
            <a href={`${backend}/api/redoc`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-lg border border-white/20 px-4 py-2 hover:bg-white/5">
              <Code2 className="h-4 w-4" /> ReDoc
            </a>
            <a href={`${backend}/api/openapi.json`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-lg border border-white/20 px-4 py-2 hover:bg-white/5">
              <Database className="h-4 w-4" /> openapi.json
            </a>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8 py-12 space-y-10">
        <p className="text-sm text-slate-600">
          <strong>Base URL :</strong> <code className="bg-slate-100 px-2 py-1 rounded text-sawali-blue">{backend}/api</code>.
          Authentification via token JWT (header <code>Authorization: Bearer &lt;token&gt;</code>) pour les routes <code>/me/*</code> et <code>/admin/*</code>.
        </p>
        {Object.entries(grouped).map(([tag, list]) => (
          <section key={tag} data-testid={`api-section-${tag}`}>
            <h2 className="text-2xl font-display font-bold mb-4">{tag}</h2>
            <div className="rounded-xl border border-slate-200 bg-white divide-y divide-slate-100">
              {list.map((r, i) => (
                <div key={i} className="p-4 flex flex-wrap items-center gap-3">
                  <div className="flex gap-1">
                    {r.methods.map((m) => (
                      <span key={m} className={`text-[10px] font-bold uppercase tracking-widest px-2 py-1 rounded border ${METHOD_COLORS[m] || "bg-slate-100 text-slate-700 border-slate-200"}`}>{m}</span>
                    ))}
                  </div>
                  <code className="font-mono text-sm text-slate-800 break-all flex-1">{r.path}</code>
                  {r.summary && <p className="text-xs text-slate-500 w-full sm:w-auto">{r.summary}</p>}
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
