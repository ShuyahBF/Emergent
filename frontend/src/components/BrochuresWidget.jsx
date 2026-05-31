// Iter38r-fix9p — "Téléchargez nos brochures" widget for the portal.
// Visible only to admin/superviseur roles. Lists the 3 generated PDFs
// (Guide utilisateur, brochures de présentation et fonctionnalités).
import React, { useEffect, useState } from "react";
import { FileText, Download, ExternalLink } from "lucide-react";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";

const META = {
  "guide-utilisateur": {
    title: "Guide Utilisateur",
    desc: "Manuel complet avec sommaire numéroté, captures d'écran et détails des champs.",
    color: "from-sky-500 to-blue-600",
  },
  "brochure-presentation": {
    title: "Brochure de présentation",
    desc: "Argumentaire commercial avec « Pourquoi SAWALI ? » et tarifs.",
    color: "from-fuchsia-500 to-pink-600",
  },
  "brochure-fonctionnalites": {
    title: "Grandes fonctionnalités",
    desc: "Vue ultra-visuelle : 1 page par module avec capture sans sidebar.",
    color: "from-emerald-500 to-teal-600",
  },
};

export default function BrochuresWidget() {
  const { user } = useAuth() || {};
  const role = (user?.role || "").toLowerCase();
  const tracked = (user?.tracked_role || "").toLowerCase();
  const canSee = ["admin", "superviseur"].includes(role) || ["admin", "superviseur"].includes(tracked);
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!canSee) return;
    apiClient.get("/public/docs")
      .then((r) => setDocs(r.data?.items || []))
      .catch(() => setDocs([]))
      .finally(() => setLoading(false));
  }, [canSee]);

  if (!canSee) return null;
  if (!loading && docs.length === 0) return null;

  return (
    <section className="rounded-2xl ring-1 ring-slate-200 bg-white p-5" data-testid="brochures-widget">
      <header className="flex items-center gap-3 mb-4">
        <div className="rounded-full bg-slate-100 p-2 ring-1 ring-slate-200">
          <FileText className="h-5 w-5 text-slate-700" />
        </div>
        <div>
          <h2 className="font-display font-bold text-slate-900">Téléchargez nos brochures</h2>
          <p className="text-xs text-slate-500 mt-0.5">3 documents PDF en français — à partager avec vos prospects et équipes.</p>
        </div>
      </header>

      {loading ? (
        <p className="text-sm text-slate-500">Chargement…</p>
      ) : (
        <div className="grid sm:grid-cols-3 gap-3">
          {docs.map((d) => {
            const meta = META[d.slug] || { title: d.filename, desc: "", color: "from-slate-500 to-slate-700" };
            const apiBase = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");
            const downloadUrl = `${apiBase}${d.url}`;
            return (
              <a
                key={d.slug}
                href={downloadUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="group rounded-xl ring-1 ring-slate-200 bg-gradient-to-br hover:ring-2 hover:ring-sawali-blue/50 hover:shadow-lg transition-all overflow-hidden flex flex-col"
                data-testid={`brochure-${d.slug}`}
              >
                <div className={`bg-gradient-to-br ${meta.color} h-20 flex items-center justify-center text-white`}>
                  <FileText className="h-8 w-8" />
                </div>
                <div className="p-3 flex-1 flex flex-col">
                  <h3 className="text-sm font-display font-semibold text-slate-900">{meta.title}</h3>
                  <p className="text-xs text-slate-500 mt-1 flex-1">{meta.desc}</p>
                  <div className="flex items-center justify-between mt-3 pt-2 border-t border-slate-100">
                    <span className="text-[10px] text-slate-500">{d.size_kb} KB · PDF</span>
                    <span className="text-xs font-medium text-sawali-blue inline-flex items-center gap-1 group-hover:gap-2 transition-all">
                      <Download className="h-3 w-3" /> Télécharger <ExternalLink className="h-3 w-3" />
                    </span>
                  </div>
                </div>
              </a>
            );
          })}
        </div>
      )}
    </section>
  );
}
