import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import {
  Eye, EyeOff, CheckCircle2, Trash2, Link2, Copy, Star, Plus, Edit, X, Upload, User as UserIcon,
} from "lucide-react";
import { toast } from "sonner";

const STATUS = {
  pending: ["En modération", "bg-amber-100 text-amber-700"],
  published: ["Publié", "bg-emerald-100 text-emerald-700"],
  hidden: ["Masqué", "bg-slate-100 text-slate-700"],
};

const empty = {
  client_name: "", client_company: "", subject: "", comment: "",
  city: "", country: "", photo_url: "",
  score: 10, rating_5: 5, status: "published", allow_publish: true,
};

export default function AdminTestimonials() {
  const [items, setItems] = useState([]);
  const [appts, setAppts] = useState([]);
  const [isOpen, setIsOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(empty);
  const [uploading, setUploading] = useState(false);

  const load = () => apiClient.get("/admin/testimonials").then((r) => setItems(r.data));
  useEffect(() => {
    load().catch(() => {});
    apiClient.get("/admin/appointments").then((r) => setAppts(r.data.filter((a) => a.status === "completed"))).catch(() => {});
  }, []);

  const open = (it = null) => {
    setEditing(it);
    if (it) {
      setForm({
        ...empty, ...it,
        rating_5: it.rating_5 ?? 5,
        photo_url: it.photo_url || "",
        city: it.city || "", country: it.country || "",
      });
    } else setForm(empty);
    setIsOpen(true);
  };
  const close = () => { setIsOpen(false); setEditing(null); setForm(empty); };

  const upload = async (file) => {
    const fd = new FormData(); fd.append("file", file);
    setUploading(true);
    try {
      const r = await apiClient.post("/admin/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      const url = `${process.env.REACT_APP_BACKEND_URL}${r.data.url}`;
      setForm((p) => ({ ...p, photo_url: url }));
      toast.success("Photo téléversée");
    } catch (err) { toast.error("Erreur upload"); }
    finally { setUploading(false); }
  };

  const submit = async (e) => {
    e.preventDefault();
    try {
      const payload = { ...form, score: parseInt(form.score) || 0, rating_5: form.rating_5 === "" ? null : parseFloat(form.rating_5) };
      if (editing?.id) await apiClient.put(`/admin/testimonials/${editing.id}`, payload);
      else await apiClient.post("/admin/testimonials", payload);
      toast.success("Témoignage enregistré"); close(); await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

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
      toast.success("Lien généré et copié", { description: url });
      await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };
  const copyLink = async (token) => {
    const url = `${window.location.origin}/feedback/${token}`;
    await navigator.clipboard.writeText(url).catch(() => {});
    toast.success("Lien copié");
  };

  const pending = items.filter((x) => x.status === "pending").length;
  const published = items.filter((x) => x.status === "published").length;

  return (
    <div className="space-y-6" data-testid="admin-testimonials-page">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-display font-bold">Témoignages clients</h1>
          <p className="text-sm text-slate-500">Modérez les avis NPS reçus ou créez des témoignages manuellement.</p>
        </div>
        <button onClick={() => open()} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light" data-testid="new-testimonial-btn">
          <Plus className="h-4 w-4" /> Nouveau témoignage
        </button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Stat label="Reçus" value={items.length} />
        <Stat label="En modération" value={pending} accent="text-amber-600" />
        <Stat label="Publiés" value={published} accent="text-emerald-600" />
        <Stat label="RDV terminés" value={appts.length} />
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-5" data-testid="request-feedback-section">
        <h2 className="font-display font-semibold flex items-center gap-2"><Link2 className="h-4 w-4 text-sawali-blue" /> Demander un avis NPS automatique</h2>
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
                  <button onClick={() => copyLink(a.feedback_token)} className="text-xs text-sawali-blue hover:underline inline-flex items-center gap-1" data-testid={`copy-link-${a.id}`}><Copy className="h-3.5 w-3.5" /> Copier le lien</button>
                ) : (
                  <button onClick={() => requestFeedback(a.id)} className="text-xs text-sawali-blue hover:underline inline-flex items-center gap-1" data-testid={`gen-link-${a.id}`}><Link2 className="h-3.5 w-3.5" /> Générer le lien</button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="space-y-3">
        {items.length === 0 && <p className="text-slate-500">Aucun témoignage.</p>}
        {items.map((t) => {
          const [label, cls] = STATUS[t.status] || [t.status, "bg-slate-100 text-slate-700"];
          return (
            <div key={t.id} className="rounded-xl border border-slate-200 bg-white p-5" data-testid={`testimonial-row-${t.id}`}>
              <div className="flex items-start justify-between flex-wrap gap-3">
                <div className="flex items-center gap-3">
                  {t.photo_url ? (
                    <img src={t.photo_url} alt="" className="h-12 w-12 rounded-full object-cover" />
                  ) : (
                    <div className="h-12 w-12 rounded-full bg-sawali-blue/10 flex items-center justify-center">
                      <UserIcon className="h-5 w-5 text-sawali-blue" />
                    </div>
                  )}
                  <div>
                    <p className="font-semibold">{t.client_name}{t.client_company ? ` — ${t.client_company}` : ""}</p>
                    <p className="text-xs text-slate-500">
                      {[t.city, t.country].filter(Boolean).join(", ")}
                      {(t.city || t.country) && t.subject ? " · " : ""}
                      {t.subject}
                    </p>
                    <div className="text-xs text-slate-600 mt-1 flex items-center gap-3">
                      <span>NPS : <strong className="text-slate-800">{t.score}/10</strong></span>
                      {t.rating_5 != null && <Stars value={t.rating_5} />}
                      {t.source === "manual" && <span className="text-[10px] uppercase tracking-widest text-slate-400">Manuel</span>}
                    </div>
                  </div>
                </div>
                <span className={`text-xs px-2 py-1 rounded ${cls}`}>{label}</span>
              </div>
              {t.comment && <p className="mt-3 text-sm text-slate-700 italic">"{t.comment}"</p>}
              <div className="mt-3 flex flex-wrap gap-2 text-xs">
                <button onClick={() => open(t)} className="inline-flex items-center gap-1 rounded border border-slate-200 px-3 py-1.5 hover:bg-slate-50" data-testid={`edit-${t.id}`}>
                  <Edit className="h-3.5 w-3.5" /> Modifier
                </button>
                {t.status !== "published" && (
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

      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 overflow-y-auto" onClick={close}>
          <div className="bg-white rounded-xl w-full max-w-2xl my-8" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b sticky top-0 bg-white rounded-t-xl">
              <h3 className="font-display font-semibold">{editing?.id ? "Modifier le témoignage" : "Nouveau témoignage"}</h3>
              <button onClick={close}><X className="h-4 w-4" /></button>
            </div>
            <form onSubmit={submit} className="p-5 space-y-4" data-testid="testimonial-form">
              <div className="grid sm:grid-cols-2 gap-3">
                <Field label="Identité (Nom complet) *" required value={form.client_name} onChange={(v) => setForm({ ...form, client_name: v })} testid="t-name" />
                <Field label="Entreprise" value={form.client_company} onChange={(v) => setForm({ ...form, client_company: v })} testid="t-company" />
                <Field label="Ville" value={form.city} onChange={(v) => setForm({ ...form, city: v })} testid="t-city" />
                <Field label="Pays" value={form.country} onChange={(v) => setForm({ ...form, country: v })} testid="t-country" />
                <Field label="Sujet (optionnel)" value={form.subject} onChange={(v) => setForm({ ...form, subject: v })} testid="t-subject" />
              </div>

              <div>
                <label className="block text-xs font-semibold mb-1">Témoignage</label>
                <textarea rows={4} value={form.comment} onChange={(e) => setForm({ ...form, comment: e.target.value })}
                          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="t-comment"
                          placeholder="Texte du témoignage..." />
              </div>

              <div>
                <label className="block text-xs font-semibold mb-1">Photo (optionnelle — sinon icône par défaut)</label>
                <div className="flex items-center gap-4">
                  {form.photo_url ? (
                    <img src={form.photo_url} alt="" className="h-16 w-16 rounded-full object-cover ring-1 ring-slate-200" />
                  ) : (
                    <div className="h-16 w-16 rounded-full bg-sawali-blue/10 flex items-center justify-center">
                      <UserIcon className="h-7 w-7 text-sawali-blue" />
                    </div>
                  )}
                  <label className="inline-flex items-center gap-2 cursor-pointer rounded-lg border border-dashed border-slate-300 px-4 py-2 text-sm text-slate-600 hover:border-sawali-blue">
                    <Upload className="h-4 w-4" /> {uploading ? "Téléversement..." : (form.photo_url ? "Remplacer" : "Téléverser une photo")}
                    <input type="file" hidden accept="image/*" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} data-testid="t-photo-input" />
                  </label>
                  {form.photo_url && (
                    <button type="button" onClick={() => setForm({ ...form, photo_url: "" })} className="text-xs text-rose-600 underline">Retirer</button>
                  )}
                </div>
              </div>

              <div className="grid sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold mb-1">Note d'évaluation /5 *</label>
                  <RatingInput value={parseFloat(form.rating_5) || 0} onChange={(v) => setForm({ ...form, rating_5: v })} />
                  <p className="text-xs text-slate-500 mt-1">Cliquez pour choisir 1 à 5 étoiles.</p>
                </div>
                <div>
                  <label className="block text-xs font-semibold mb-1">Score NPS /10</label>
                  <input type="number" min="0" max="10" value={form.score} onChange={(e) => setForm({ ...form, score: e.target.value })}
                         className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="t-score" />
                  <p className="text-xs text-slate-500 mt-1">Affecte le score NPS public (0-10).</p>
                </div>
              </div>

              <div className="grid sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold mb-1">Statut</label>
                  <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}
                          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="t-status">
                    <option value="published">Publié</option>
                    <option value="pending">En modération</option>
                    <option value="hidden">Masqué</option>
                  </select>
                </div>
                <label className="flex items-center gap-2 text-sm self-end">
                  <input type="checkbox" checked={form.allow_publish} onChange={(e) => setForm({ ...form, allow_publish: e.target.checked })} />
                  Publication autorisée
                </label>
              </div>

              <button type="submit" className="w-full rounded-lg bg-sawali-blue text-white px-4 py-2.5 text-sm font-medium hover:bg-sawali-blue-light" data-testid="save-testimonial-btn">
                {editing?.id ? "Mettre à jour" : "Créer le témoignage"}
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

const Stat = ({ label, value, accent = "text-slate-900" }) => (
  <div className="rounded-xl border border-slate-200 bg-white p-4">
    <p className="text-xs uppercase tracking-[0.2em] text-slate-500">{label}</p>
    <p className={`mt-1 text-2xl font-display font-bold ${accent}`}>{value}</p>
  </div>
);

const Field = ({ label, value, onChange, required, testid }) => (
  <div>
    <label className="block text-xs font-semibold mb-1">{label}</label>
    <input required={required} value={value || ""} onChange={(e) => onChange(e.target.value)}
           className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid={testid} />
  </div>
);

const RatingInput = ({ value, onChange }) => (
  <div className="flex items-center gap-1" data-testid="rating-input">
    {[1, 2, 3, 4, 5].map((n) => (
      <button type="button" key={n} onClick={() => onChange(n)}
              className="p-1 transition" data-testid={`rating-${n}`}>
        <Star className={`h-7 w-7 ${value >= n ? "fill-amber-400 text-amber-400" : "text-slate-300"}`} />
      </button>
    ))}
    <span className="ml-2 text-sm text-slate-600">{value || 0}/5</span>
  </div>
);

const Stars = ({ value }) => (
  <span className="inline-flex items-center gap-0.5">
    {[1, 2, 3, 4, 5].map((n) => (
      <Star key={n} className={`h-3.5 w-3.5 ${value >= n ? "fill-amber-400 text-amber-400" : "text-slate-300"}`} />
    ))}
    <span className="ml-1 text-xs text-slate-500">{Number(value).toFixed(1)}</span>
  </span>
);
