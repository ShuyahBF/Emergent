import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Save } from "lucide-react";

const SLUGS = [
  { slug: "home_hero", label: "Accueil — Hero" },
  { slug: "mission", label: "Notre Mission" },
  { slug: "experience", label: "Notre Expérience" },
  { slug: "specialisations", label: "Spécialisations" },
  { slug: "about", label: "À propos" },
];

export default function AdminContents() {
  const [list, setList] = useState([]);
  const [active, setActive] = useState(SLUGS[0].slug);
  const [data, setData] = useState({ title: "", body_html: "", metadata: {}, images: [] });
  const [loading, setLoading] = useState(false);

  const reload = () => apiClient.get("/content").then((r) => setList(r.data));
  useEffect(() => { reload().catch(() => {}); }, []);

  useEffect(() => {
    const found = list.find((c) => c.slug === active);
    setData(found ? { title: found.title, body_html: found.body_html || "", metadata: found.metadata || {}, images: found.images || [] } : { title: "", body_html: "", metadata: {}, images: [] });
  }, [active, list]);

  const save = async () => {
    setLoading(true);
    try {
      await apiClient.put(`/admin/content/${active}`, { slug: active, ...data });
      toast.success("Contenu mis à jour");
      await reload();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setLoading(false); }
  };

  return (
    <div className="space-y-6" data-testid="admin-contents-page">
      <div>
        <h1 className="text-2xl font-display font-bold">Contenus du site public</h1>
        <p className="text-sm text-slate-500">Modifiez les textes affichés sur le site marketing.</p>
      </div>

      <div className="flex gap-2 overflow-x-auto pb-2">
        {SLUGS.map((s) => (
          <button key={s.slug} onClick={() => setActive(s.slug)}
                  className={`px-4 py-2 rounded-lg text-sm whitespace-nowrap ${active === s.slug ? "bg-sawali-blue text-white" : "bg-white border border-slate-200 hover:bg-slate-50"}`}
                  data-testid={`tab-${s.slug}`}>
            {s.label}
          </button>
        ))}
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-6 space-y-4" data-testid="content-editor">
        <div>
          <label className="block text-xs font-semibold mb-1">Titre</label>
          <input value={data.title} onChange={(e) => setData({ ...data, title: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="content-title" />
        </div>
        <div>
          <label className="block text-xs font-semibold mb-1">Contenu HTML</label>
          <textarea rows={10} value={data.body_html} onChange={(e) => setData({ ...data, body_html: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" data-testid="content-body" />
          {data.body_html && <div className="mt-2 rounded-lg border border-slate-200 p-3 prose-sawali bg-slate-50" dangerouslySetInnerHTML={{ __html: data.body_html }} />}
        </div>
        <div>
          <label className="block text-xs font-semibold mb-1">Métadonnées (JSON)</label>
          <textarea rows={6} value={JSON.stringify(data.metadata, null, 2)} onChange={(e) => {
            try { setData({ ...data, metadata: JSON.parse(e.target.value || "{}") }); } catch { /* ignore */ }
          }} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-mono" data-testid="content-metadata" />
          <p className="text-xs text-slate-500 mt-1">Ex : pour "specialisations", utilisez {`{"items":[{"title":"...","icon":"Globe","desc":"..."}]}`}.</p>
        </div>
        <button onClick={save} disabled={loading} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light disabled:opacity-50" data-testid="save-content-btn">
          <Save className="h-4 w-4" /> {loading ? "Enregistrement..." : "Enregistrer"}
        </button>
      </div>
    </div>
  );
}
