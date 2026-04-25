import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Eye, EyeOff, CheckCircle2, Trash2, Link2, Copy, Star } from "lucide-react";
import { toast } from "sonner";

const STATUS = {
  pending: ["En modération", "bg-amber-100 text-amber-700"],
  published: ["Publié", "bg-emerald-100 text-emerald-700"],
  hidden: ["Masqué", "bg-slate-100 text-slate-700"],
};

export default function AdminTestimonials() {
  const [items, setItems] = useState([]);
  const [appts, setAppts] = useState([]);

  const load = () => apiClient.get("/admin/testimonials").then((r) => setItems(r.data));
  useEffect(() => {
    load().catch(() => {});
    apiClient.get("/admin/appointments").then((r) => setAppts(r.data.filter((a) => a.status === "completed")));
  }, []);

  const setStatus = async (id, status) => {
    await apiClient.put(`/admin/testimonials/${id}`, { status });
    toast.success("Statut mis à jour"); await load();
  };
  const del = async (id) => {
    if (!window.confirm("Supprimer ?")) return;
    await apiClient.delete(`/admin/testimonials/${id}`);
    await load();
  };
  const requestFeedback = async (apptId) => {
    try {
      const r = await apiClient.post(`/admin/testimonials/request/${apptId}`);
      const url = `${window.location.origin}${r.data.feedback_url}`;
      await navigator.clipboard.writeText(url).catch(() => {});
      toast.success("Lien généré et copié dans le presse-papier", { description: url });
      await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };
  const copyLink = async (apptId, token) => {
    const url = `${window.location.origin}/feedback/${token}`;
    await navigator.clipboard.writeText(url).catch(() => {});
    toast.success("Lien copié");
  };

  const pending = items.filter((x) => x.status === "pending").length;
  const published = items.filter((x) => x.status === "published").length;

  return (
    <div className="space-y-6" data-testid="admin-testimonials-page">
      <div>
        <h1 className="text-2xl font-display font-bold">Témoignages clients</h1>
        <p className="text-sm text-slate-500">Modérez les avis NPS reçus avant publication.</p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Stat label="Reçus" value={items.length} />
        <Stat label="En modération" value={pending} accent="text-amber-600" />
        <Stat label="Publiés" value={published} accent="text-emerald-600" />
        <Stat label="RDV terminés" value={appts.length} />
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-5" data-testid="request-feedback-section">
        <h2 className="font-display font-semibold flex items-center gap-2"><Link2 className="h-4 w-4 text-sawali-blue" /> Demander un avis NPS</h2>
        <p className="text-xs text-slate-500 mt-1">Sélectionnez un RDV terminé pour générer/copier son lien d'évaluation.</p>
        <div className="mt-4 max-h-60 overflow-auto divide-y divide-slate-100">
          {appts.length === 0 && <p className="text-sm text-slate-500 py-4">Aucun RDV terminé.</p>}
          {appts.map((a) => (
            <div key={a.id} className="py-2 flex items-center justify-between gap-3 text-sm">
              <div className="min-w-0">
                <p className="font-medium truncate">{a.name} — {a.subject}</p>
                <p className="text-xs text-slate-500">{new Date(a.scheduled_at).toLocaleDateString("fr-FR")} · {a.email}</p>
              </div>
              <div className="flex items-center gap-2">
                {a.feedback_status === "submitted" ? (
                  <span className="text-xs text-emerald-700 inline-flex items-center gap-1"><CheckCircle2 className="h-3.5 w-3.5" /> Avis reçu</span>
                ) : a.feedback_token ? (
                  <button onClick={() => copyLink(a.id, a.feedback_token)} className="text-xs text-sawali-blue hover:underline inline-flex items-center gap-1" data-testid={`copy-link-${a.id}`}><Copy className="h-3.5 w-3.5" /> Copier le lien</button>
                ) : (
                  <button onClick={() => requestFeedback(a.id)} className="text-xs text-sawali-blue hover:underline inline-flex items-center gap-1" data-testid={`gen-link-${a.id}`}><Link2 className="h-3.5 w-3.5" /> Générer le lien</button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="space-y-3">
        {items.length === 0 && <p className="text-slate-500">Aucun témoignage reçu.</p>}
        {items.map((t) => {
          const [label, cls] = STATUS[t.status] || [t.status, "bg-slate-100 text-slate-700"];
          return (
            <div key={t.id} className="rounded-xl border border-slate-200 bg-white p-5" data-testid={`testimonial-row-${t.id}`}>
              <div className="flex items-start justify-between flex-wrap gap-3">
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 rounded-lg bg-sawali-blue/10 flex items-center justify-center font-display font-bold text-sawali-blue">{t.score}</div>
                  <div>
                    <p className="font-semibold">{t.client_name}{t.client_company ? ` — ${t.client_company}` : ""}</p>
                    <p className="text-xs text-slate-500">{t.subject} · {new Date(t.created_at).toLocaleDateString("fr-FR")}</p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`text-xs px-2 py-1 rounded ${cls}`}>{label}</span>
                  {!t.allow_publish && <span className="text-xs px-2 py-1 rounded bg-rose-100 text-rose-700">Publication non autorisée</span>}
                </div>
              </div>
              {t.comment && <p className="mt-3 text-sm text-slate-700 italic">"{t.comment}"</p>}
              <div className="mt-3 flex flex-wrap gap-2 text-xs">
                {t.status !== "published" && t.allow_publish && (
                  <button onClick={() => setStatus(t.id, "published")} className="inline-flex items-center gap-1 rounded bg-emerald-600 text-white px-3 py-1.5 hover:bg-emerald-700" data-testid={`publish-${t.id}`}>
                    <CheckCircle2 className="h-3.5 w-3.5" /> Publier
                  </button>
                )}
                {t.status !== "hidden" && (
                  <button onClick={() => setStatus(t.id, "hidden")} className="inline-flex items-center gap-1 rounded border border-slate-200 px-3 py-1.5 hover:bg-slate-50" data-testid={`hide-${t.id}`}>
                    <EyeOff className="h-3.5 w-3.5" /> Masquer
                  </button>
                )}
                {t.status !== "pending" && (
                  <button onClick={() => setStatus(t.id, "pending")} className="inline-flex items-center gap-1 rounded border border-slate-200 px-3 py-1.5 hover:bg-slate-50">
                    <Eye className="h-3.5 w-3.5" /> Mettre en modération
                  </button>
                )}
                <button onClick={() => del(t.id)} className="inline-flex items-center gap-1 rounded text-rose-600 px-3 py-1.5 hover:bg-rose-50 ml-auto" data-testid={`del-${t.id}`}>
                  <Trash2 className="h-3.5 w-3.5" /> Supprimer
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const Stat = ({ label, value, accent = "text-slate-900" }) => (
  <div className="rounded-xl border border-slate-200 bg-white p-4">
    <p className="text-xs uppercase tracking-[0.2em] text-slate-500">{label}</p>
    <p className={`mt-1 text-2xl font-display font-bold ${accent}`}>{value}</p>
  </div>
);
