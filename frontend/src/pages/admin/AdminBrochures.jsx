// Iter38r-fix9p — Admin page listing the 3 generated brochures/guides PDF.
// Replaces the dashboard widget for direct access from the sidebar.
import React from "react";
import BrochuresWidget from "@/components/BrochuresWidget";

export default function AdminBrochures() {
  return (
    <div className="space-y-6" data-testid="admin-brochures-page">
      <header>
        <h1 className="text-2xl font-display font-bold text-slate-900">Brochures & Guide utilisateur</h1>
        <p className="text-sm text-slate-500 mt-1">
          3 documents PDF en français à partager avec vos clients, prospects et équipes.
        </p>
      </header>
      <BrochuresWidget />
      <div className="rounded-2xl ring-1 ring-slate-200 bg-white p-5 text-xs text-slate-600 leading-relaxed">
        <h2 className="font-semibold text-slate-900 mb-2">💡 Comment regénérer les PDFs ?</h2>
        <p>
          Les documents sont générés à partir des screenshots du portail. Pour les mettre à jour après une refonte UI majeure, exécutez côté serveur :
        </p>
        <pre className="mt-2 bg-slate-50 ring-1 ring-slate-200 rounded p-2 font-mono text-[11px]">cd /app/docs && python3 generate_pdfs.py</pre>
      </div>
    </div>
  );
}
