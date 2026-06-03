// Iter38r-fix9p — Admin page listing the 3 generated brochures/guides PDF.
// S-iter39p (2026-02) — Adds the Media Library section (PDF + video +
// image uploaded by admins, surfaced on the portal Brochures page).
import React from "react";
import BrochuresWidget from "@/components/BrochuresWidget";
import AdminMediaLibrary from "@/components/AdminMediaLibrary";

export default function AdminBrochures() {
  return (
    <div className="space-y-6" data-testid="admin-brochures-page">
      <header>
        <h1 className="text-2xl font-display font-bold text-slate-900">Brochures, Guides & Médias</h1>
        <p className="text-sm text-slate-500 mt-1">
          Documents PDF officiels + bibliothèque de médias additionnels (PDF, vidéos, images) à partager avec vos clients, prospects et équipes.
        </p>
      </header>

      <AdminMediaLibrary />

      <BrochuresWidget />

      <div className="rounded-2xl ring-1 ring-slate-200 bg-white p-5 text-xs text-slate-600 leading-relaxed">
        <h2 className="font-semibold text-slate-900 mb-2">💡 Comment regénérer les PDFs ?</h2>
        <p>
          Les 4 documents officiels sont générés à partir des screenshots du portail. Pour les mettre à jour après une refonte UI majeure, exécutez côté serveur :
        </p>
        <pre className="mt-2 bg-slate-50 ring-1 ring-slate-200 rounded p-2 font-mono text-[11px]">cd /app/docs &amp;&amp; python3 generate_pdfs.py</pre>
      </div>
    </div>
  );
}
