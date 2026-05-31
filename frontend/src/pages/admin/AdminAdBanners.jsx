import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  ArrowLeft,
  Plus,
  Edit3,
  Trash2,
  X,
  Save,
  CheckCircle2,
  XCircle,
  TrendingUp,
  Eye,
  MousePointerClick,
  DollarSign,
  Image as ImageIcon,
  Megaphone,
  Sparkles,
  Calendar,
} from "lucide-react";

// Iter38r-fix9w — Admin page to manage paid advertising banners.

const DEFAULT_DRAFT = {
  name: "",
  advertiser_name: "",
  image_url: "",
  target_url: "",
  placement: "both",
  animated: false,
  active: true,
  budget_amount: 0,
  currency: "XOF",
  cost_per_impression: 0,
  cost_per_click: 0,
  paid: false,
  payment_date: "",
  expiration_date: "",
  start_date: "",
  notes: "",
};

export default function AdminAdBanners() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState(DEFAULT_DRAFT);
  const [editing, setEditing] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [statsId, setStatsId] = useState(null);
  const [stats, setStats] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/ad-banners");
      setItems(r.data?.items || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const totals = useMemo(() => items.reduce((acc, it) => {
    acc.impressions += it.total_impressions || 0;
    acc.clicks += it.total_clicks || 0;
    acc.spent[it.currency || "XOF"] = (acc.spent[it.currency || "XOF"] || 0) + (it.amount_spent || 0);
    if (it.is_currently_active) acc.active_count += 1;
    return acc;
  }, { impressions: 0, clicks: 0, spent: {}, active_count: 0 }), [items]);

  const startCreate = () => { setEditing(null); setDraft(DEFAULT_DRAFT); setShowForm(true); };

  const startEdit = (it) => {
    setEditing(it.id);
    setDraft({
      name: it.name || "",
      advertiser_name: it.advertiser_name || "",
      image_url: it.image_url || "",
      target_url: it.target_url || "",
      placement: it.placement || "both",
      animated: !!it.animated,
      active: !!it.active,
      budget_amount: it.budget_amount || 0,
      currency: it.currency || "XOF",
      cost_per_impression: it.cost_per_impression || 0,
      cost_per_click: it.cost_per_click || 0,
      paid: !!it.paid,
      payment_date: it.payment_date || "",
      expiration_date: it.expiration_date || "",
      start_date: it.start_date || "",
      notes: it.notes || "",
    });
    setShowForm(true);
  };

  const save = async () => {
    if (!draft.name.trim() || !draft.image_url.trim() || !draft.target_url.trim()) {
      toast.error("Nom, URL de l'image et URL cible sont obligatoires");
      return;
    }
    try {
      const body = { ...draft };
      // Strip empty strings → null for optional date fields
      ["payment_date", "expiration_date", "start_date"].forEach((k) => {
        if (!body[k]) body[k] = null;
      });
      if (editing) {
        await apiClient.put(`/admin/ad-banners/${editing}`, body);
        toast.success("Bannière mise à jour");
      } else {
        await apiClient.post("/admin/ad-banners", body);
        toast.success("Bannière créée");
      }
      setShowForm(false); setEditing(null); setDraft(DEFAULT_DRAFT);
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const remove = async (id, name) => {
    if (!window.confirm(`Supprimer la bannière « ${name} » ?`)) return;
    try {
      await apiClient.delete(`/admin/ad-banners/${id}`);
      toast.success("Supprimée");
      await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const togglePaid = async (id) => {
    try {
      await apiClient.post(`/admin/ad-banners/${id}/toggle-paid`);
      await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const openStats = async (id) => {
    setStatsId(id); setStats(null);
    try {
      const r = await apiClient.get(`/admin/ad-banners/${id}/stats`);
      setStats(r.data);
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); setStatsId(null); }
  };

  return (
    <div className="space-y-6 p-6 max-w-7xl" data-testid="admin-ad-banners-page">
      <div>
        <Link to="/admin/settings" className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-sawali-blue mb-1">
          <ArrowLeft className="h-3 w-3" /> Retour aux paramètres
        </Link>
        <h1 className="text-2xl font-display font-bold inline-flex items-center gap-2">
          <Megaphone className="h-6 w-6 text-fuchsia-600" /> Régie publicitaire — Bannières monétisées
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Vendez un espace publicitaire en haut des pages publiques et/ou de l'Espace Loois.
          La rotation, le tracking (affichages/clics) et l'auto-pause budget/expiration sont gérés automatiquement.
        </p>
      </div>

      {/* Totals strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3" data-testid="ad-banner-totals">
        <Stat icon={Sparkles} label="Actives" value={totals.active_count} accent="emerald" />
        <Stat icon={Eye} label="Affichages" value={totals.impressions.toLocaleString("fr-FR")} accent="sky" />
        <Stat icon={MousePointerClick} label="Clics" value={totals.clicks.toLocaleString("fr-FR")} accent="violet" />
        <Stat icon={DollarSign} label="Dépensé"
              value={Object.entries(totals.spent).map(([c, a]) => `${a.toLocaleString("fr-FR")} ${c}`).join(" · ") || "—"}
              accent="amber" />
      </div>

      <div className="flex justify-end">
        <button
          onClick={startCreate}
          className="inline-flex items-center gap-1.5 rounded-lg bg-fuchsia-600 text-white px-4 py-2 text-sm hover:bg-fuchsia-700"
          data-testid="ad-banner-add-btn"
        >
          <Plus className="h-4 w-4" /> Nouvelle bannière
        </button>
      </div>

      {showForm && <BannerForm draft={draft} setDraft={setDraft} onSave={save} onCancel={() => { setShowForm(false); setEditing(null); }} editing={editing} />}

      {/* Table */}
      <section className="rounded-2xl ring-1 ring-slate-200 bg-white overflow-hidden">
        {loading ? (
          <p className="p-6 text-slate-500">Chargement…</p>
        ) : items.length === 0 ? (
          <p className="p-8 text-center text-slate-400 italic">Aucune bannière. Créez-en une pour commencer à monétiser.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs" data-testid="ad-banners-table">
              <thead className="bg-slate-50 text-slate-500 uppercase tracking-wider text-[10px]">
                <tr>
                  <th className="text-left px-3 py-2">Aperçu / Nom</th>
                  <th className="text-left px-2 py-2">Emplacement</th>
                  <th className="text-center px-2 py-2">Statut</th>
                  <th className="text-right px-2 py-2">Affichages</th>
                  <th className="text-right px-2 py-2">Clics / CTR</th>
                  <th className="text-right px-2 py-2">Budget</th>
                  <th className="text-right px-2 py-2">Dépensé</th>
                  <th className="text-left px-2 py-2">Expire</th>
                  <th className="text-center px-2 py-2">Payé</th>
                  <th className="text-center px-2 py-2">Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => {
                  const ctr = it.total_impressions > 0 ? ((it.total_clicks / it.total_impressions) * 100).toFixed(1) : "—";
                  return (
                    <tr key={it.id} className={`border-t border-slate-100 hover:bg-slate-50 ${!it.active ? "opacity-60" : ""}`} data-testid={`ad-banner-row-${it.id}`}>
                      <td className="px-3 py-2 max-w-[260px]">
                        <div className="flex items-center gap-2">
                          {it.image_url && (
                            <img src={it.image_url} alt="" className="h-8 w-16 object-cover rounded ring-1 ring-slate-200" />
                          )}
                          <div className="min-w-0">
                            <p className="font-semibold text-slate-800 truncate">{it.name}</p>
                            {it.advertiser_name && <p className="text-[10px] text-slate-500 truncate">{it.advertiser_name}</p>}
                          </div>
                        </div>
                      </td>
                      <td className="text-slate-700 px-2 capitalize">{it.placement === "both" ? "Public + Portail" : it.placement}</td>
                      <td className="text-center">
                        {it.is_currently_active
                          ? <span className="inline-block h-2 w-2 rounded-full bg-emerald-500" title="Active maintenant" />
                          : it.is_expired
                            ? <span className="inline-block h-2 w-2 rounded-full bg-rose-500" title="Expirée" />
                            : it.is_budget_exhausted
                              ? <span className="inline-block h-2 w-2 rounded-full bg-amber-500" title="Budget atteint" />
                              : <span className="inline-block h-2 w-2 rounded-full bg-slate-300" title="Inactive" />}
                      </td>
                      <td className="text-right font-mono tabular-nums">{(it.total_impressions || 0).toLocaleString("fr-FR")}</td>
                      <td className="text-right font-mono tabular-nums">
                        {(it.total_clicks || 0).toLocaleString("fr-FR")}
                        <span className="text-[10px] text-slate-400 ml-1">({ctr}%)</span>
                      </td>
                      <td className="text-right font-mono tabular-nums">
                        {(it.budget_amount || 0).toLocaleString("fr-FR")} <span className="text-[10px] text-slate-400">{it.currency}</span>
                      </td>
                      <td className="text-right font-mono tabular-nums">
                        {(it.amount_spent || 0).toLocaleString("fr-FR")}
                        <span className="text-[10px] text-slate-400 ml-1">({it.progress_pct}%)</span>
                      </td>
                      <td className="text-slate-600 text-[11px]">{it.expiration_date || "—"}</td>
                      <td className="text-center">
                        <button
                          onClick={() => togglePaid(it.id)}
                          className="text-xs"
                          title={it.paid ? `Payé le ${it.payment_date || ""}` : "Marquer comme payé"}
                          data-testid={`ad-banner-paid-${it.id}`}
                        >
                          {it.paid
                            ? <CheckCircle2 className="h-4 w-4 text-emerald-600 mx-auto" />
                            : <XCircle className="h-4 w-4 text-slate-300 mx-auto" />}
                        </button>
                      </td>
                      <td className="px-2 py-2">
                        <div className="flex justify-center gap-1">
                          <button onClick={() => openStats(it.id)} className="rounded p-1 ring-1 ring-sky-300 bg-sky-50 hover:bg-sky-100 text-sky-700" title="Statistiques" data-testid={`ad-banner-stats-${it.id}`}>
                            <TrendingUp className="h-3 w-3" />
                          </button>
                          <button onClick={() => startEdit(it)} className="rounded p-1 ring-1 ring-slate-300 bg-slate-50 hover:bg-slate-100 text-slate-700" title="Modifier" data-testid={`ad-banner-edit-${it.id}`}>
                            <Edit3 className="h-3 w-3" />
                          </button>
                          <button onClick={() => remove(it.id, it.name)} className="rounded p-1 ring-1 ring-rose-300 bg-rose-50 hover:bg-rose-100 text-rose-700" title="Supprimer" data-testid={`ad-banner-delete-${it.id}`}>
                            <Trash2 className="h-3 w-3" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {statsId && stats && <StatsModal stats={stats} onClose={() => { setStatsId(null); setStats(null); }} />}
    </div>
  );
}

function Stat({ icon: Icon, label, value, accent }) {
  const colors = {
    emerald: "from-emerald-500 to-emerald-700 text-emerald-600 bg-emerald-50",
    sky: "from-sky-500 to-sky-700 text-sky-600 bg-sky-50",
    violet: "from-violet-500 to-violet-700 text-violet-600 bg-violet-50",
    amber: "from-amber-500 to-amber-700 text-amber-600 bg-amber-50",
  };
  const [grad, ic, bg] = (colors[accent] || colors.sky).split(" ").slice(0, 4).join(" ").split(" ").slice(0, 3);
  return (
    <div className="rounded-xl ring-1 ring-slate-200 bg-white p-4 flex items-center gap-3">
      <div className={`rounded-lg p-2 ${bg}`}>
        <Icon className={`h-4 w-4 ${ic}`} />
      </div>
      <div>
        <p className="text-[10px] uppercase font-semibold text-slate-500 tracking-wider">{label}</p>
        <p className="text-lg font-display font-bold text-slate-900 tabular-nums">{value}</p>
      </div>
    </div>
  );
}

function BannerForm({ draft, setDraft, onSave, onCancel, editing }) {
  const [uploading, setUploading] = React.useState(false);
  const fileInputRef = React.useRef(null);
  const apiBase = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");

  // Iter38r-fix9x — Upload an image/video file and auto-fill image_url + target_url
  const handleFileChange = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith("image/") && !file.type.startsWith("video/")) {
      toast.error("Veuillez choisir une image ou une vidéo");
      return;
    }
    // 20 MB max
    if (file.size > 20 * 1024 * 1024) {
      toast.error("Fichier trop volumineux (max 20 Mo)");
      return;
    }
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const token = localStorage.getItem("sawali_token") || "";
      const resp = await fetch(`${apiBase}/api/admin/upload`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || "Échec de l'upload");
      }
      const data = await resp.json();
      const absoluteUrl = `${apiBase}${data.url}`;
      // Auto-fill image_url AND target_url (per user choice "a": click opens the file)
      setDraft((d) => ({
        ...d,
        image_url: absoluteUrl,
        target_url: d.target_url ? d.target_url : absoluteUrl,
      }));
      toast.success(`Fichier chargé (${Math.round(file.size / 1024)} Ko)`);
    } catch (err) {
      toast.error(err.message || "Erreur d'upload");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  return (
    <div className="rounded-2xl ring-1 ring-fuchsia-300 bg-fuchsia-50/30 p-5 space-y-3" data-testid="ad-banner-form">
      <div className="flex justify-between items-center">
        <h3 className="font-display font-semibold">{editing ? "Modifier la bannière" : "Nouvelle bannière publicitaire"}</h3>
        <button onClick={onCancel} className="text-slate-400 hover:text-slate-700"><X className="h-4 w-4" /></button>
      </div>

      {/* Iter38r-fix9x — Direct file upload */}
      <div className="rounded-xl ring-1 ring-fuchsia-200 bg-white p-3 flex items-center gap-3 flex-wrap" data-testid="ad-banner-upload-block">
        <ImageIcon className="h-5 w-5 text-fuchsia-600" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-slate-800">Charger une image ou une vidéo</p>
          <p className="text-[10px] text-slate-500">Le fichier sera hébergé sur le site. URL image + URL cible (au clic) seront générées automatiquement. Max 20 Mo.</p>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*,video/mp4,video/webm"
          onChange={handleFileChange}
          className="hidden"
          data-testid="ad-banner-file-input"
        />
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className="inline-flex items-center gap-1.5 rounded-lg bg-fuchsia-600 text-white px-3 py-1.5 text-xs hover:bg-fuchsia-700 disabled:opacity-50"
          data-testid="ad-banner-upload-btn"
        >
          {uploading ? "Chargement…" : "Choisir un fichier"}
        </button>
      </div>
      {draft.image_url && (
        <div className="flex items-center gap-3 rounded-lg ring-1 ring-slate-200 bg-white p-2" data-testid="ad-banner-preview">
          {/\.(mp4|webm)$/i.test(draft.image_url) ? (
            <video src={draft.image_url} className="h-14 w-28 object-cover rounded" muted autoPlay loop playsInline />
          ) : (
            <img src={draft.image_url} alt="aperçu" className="h-14 w-28 object-cover rounded" />
          )}
          <p className="text-[10px] text-slate-500 truncate flex-1">{draft.image_url}</p>
        </div>
      )}

      <div className="grid sm:grid-cols-2 gap-3">
        <Field label="Nom (campagne)" required testid="ad-form-name">
          <input type="text" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white" />
        </Field>
        <Field label="Annonceur" testid="ad-form-advertiser">
          <input type="text" value={draft.advertiser_name} onChange={(e) => setDraft({ ...draft, advertiser_name: e.target.value })} className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white" />
        </Field>
        <Field label="URL de l'image de la bannière" required testid="ad-form-image">
          <input type="url" value={draft.image_url} onChange={(e) => setDraft({ ...draft, image_url: e.target.value })} placeholder="https://…" className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white font-mono" />
        </Field>
        <Field label="URL cible (au clic)" required testid="ad-form-target">
          <input type="url" value={draft.target_url} onChange={(e) => setDraft({ ...draft, target_url: e.target.value })} placeholder="https://…" className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white font-mono" />
        </Field>
        <Field label="Emplacement" testid="ad-form-placement">
          <select value={draft.placement} onChange={(e) => setDraft({ ...draft, placement: e.target.value })} className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white">
            <option value="public">Pages publiques uniquement</option>
            <option value="portal">Espace Loois uniquement</option>
            <option value="both">Public + Espace Loois</option>
          </select>
        </Field>
        <Field label="Date de début (optionnelle)" testid="ad-form-start">
          <input type="date" value={draft.start_date || ""} onChange={(e) => setDraft({ ...draft, start_date: e.target.value })} className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white" />
        </Field>
        <Field label="Date d'expiration (optionnelle)" testid="ad-form-exp">
          <input type="date" value={draft.expiration_date || ""} onChange={(e) => setDraft({ ...draft, expiration_date: e.target.value })} className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white" />
        </Field>
        <Field label="Budget total" testid="ad-form-budget">
          <div className="flex gap-2">
            <input type="number" min="0" step="0.01" value={draft.budget_amount} onChange={(e) => setDraft({ ...draft, budget_amount: parseFloat(e.target.value) || 0 })} className="flex-1 text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white" />
            <select value={draft.currency} onChange={(e) => setDraft({ ...draft, currency: e.target.value })} className="text-sm rounded-lg ring-1 ring-slate-300 px-2 bg-white">
              <option>XOF</option><option>EUR</option><option>USD</option>
            </select>
          </div>
        </Field>
        <Field label="Coût / Affichage (CPM unitaire)" testid="ad-form-cpi">
          <input type="number" min="0" step="0.01" value={draft.cost_per_impression} onChange={(e) => setDraft({ ...draft, cost_per_impression: parseFloat(e.target.value) || 0 })} className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white" />
        </Field>
        <Field label="Coût / Clic (CPC)" testid="ad-form-cpc">
          <input type="number" min="0" step="0.01" value={draft.cost_per_click} onChange={(e) => setDraft({ ...draft, cost_per_click: parseFloat(e.target.value) || 0 })} className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white" />
        </Field>
        <label className="inline-flex items-center gap-2 mt-6 cursor-pointer">
          <input type="checkbox" checked={draft.active} onChange={(e) => setDraft({ ...draft, active: e.target.checked })} className="h-4 w-4" data-testid="ad-form-active" />
          <span className="text-sm font-semibold text-slate-700">Active (diffusée)</span>
        </label>
        <label className="inline-flex items-center gap-2 mt-6 cursor-pointer">
          <input type="checkbox" checked={draft.animated} onChange={(e) => setDraft({ ...draft, animated: e.target.checked })} className="h-4 w-4" />
          <span className="text-sm text-slate-700">Animation pulse (subtle)</span>
        </label>
        <label className="inline-flex items-center gap-2 mt-6 cursor-pointer">
          <input type="checkbox" checked={draft.paid} onChange={(e) => setDraft({ ...draft, paid: e.target.checked })} className="h-4 w-4" data-testid="ad-form-paid" />
          <span className="text-sm font-semibold text-slate-700">Payée par l'annonceur</span>
        </label>
      </div>
      <Field label="Notes (optionnel)" testid="ad-form-notes">
        <textarea rows={2} value={draft.notes} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} placeholder="Contrat, contact annonceur…" className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white" />
      </Field>
      <div className="flex justify-end gap-2">
        <button onClick={onCancel} className="text-xs text-slate-600 hover:underline">Annuler</button>
        <button onClick={onSave} className="inline-flex items-center gap-1 rounded-lg bg-fuchsia-600 text-white px-4 py-2 text-sm hover:bg-fuchsia-700" data-testid="ad-form-save">
          <Save className="h-3.5 w-3.5" /> {editing ? "Enregistrer" : "Créer"}
        </button>
      </div>
    </div>
  );
}

function Field({ label, required, children, testid }) {
  return (
    <label className="block" data-testid={testid}>
      <span className="text-[11px] uppercase font-semibold text-slate-500">
        {label}{required && <span className="text-rose-500 ml-0.5">*</span>}
      </span>
      {children}
    </label>
  );
}

function StatsModal({ stats, onClose }) {
  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50" onClick={onClose} data-testid="ad-banner-stats-modal">
      <div className="bg-white rounded-2xl shadow-xl max-w-2xl w-full m-4 max-h-[80vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="p-5 border-b border-slate-200 flex justify-between items-center">
          <h3 className="font-display font-bold text-lg inline-flex items-center gap-2">
            <TrendingUp className="h-5 w-5 text-sky-600" /> Statistiques de la bannière
          </h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700"><X className="h-5 w-5" /></button>
        </div>
        <div className="p-5 space-y-4">
          <div className="grid grid-cols-3 gap-3">
            <Stat icon={Eye} label="Affichages" value={stats.totals.impressions.toLocaleString("fr-FR")} accent="sky" />
            <Stat icon={MousePointerClick} label="Clics" value={`${stats.totals.clicks.toLocaleString("fr-FR")} (CTR ${stats.totals.ctr_pct}%)`} accent="violet" />
            <Stat icon={DollarSign} label="Dépensé" value={`${stats.totals.amount_spent.toLocaleString("fr-FR")}`} accent="amber" />
          </div>
          <div className="rounded-xl ring-1 ring-slate-200 bg-slate-50 p-3">
            <p className="text-xs text-slate-600 inline-flex items-center gap-2">
              <Calendar className="h-3.5 w-3.5" />
              Budget total : <strong>{stats.budget_amount.toLocaleString("fr-FR")}</strong> · Restant : <strong className="text-emerald-700">{stats.remaining_budget.toLocaleString("fr-FR")}</strong>
              <span className="ml-auto text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded ring-1 ring-slate-300 bg-white">
                {stats.is_currently_active ? "✅ Active" : "⏸️ Suspendue"}
              </span>
            </p>
          </div>
          {stats.daily.length > 0 && (
            <div>
              <h4 className="text-xs uppercase font-semibold text-slate-500 mb-2">Historique quotidien</h4>
              <table className="w-full text-xs">
                <thead className="bg-slate-50">
                  <tr>
                    <th className="text-left px-2 py-1.5">Date</th>
                    <th className="text-right px-2 py-1.5">Affich.</th>
                    <th className="text-right px-2 py-1.5">Clics</th>
                    <th className="text-right px-2 py-1.5">Dépensé</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.daily.slice(-30).map((d, i) => (
                    <tr key={i} className="border-t border-slate-100">
                      <td className="px-2 py-1 text-slate-600">{d.date}</td>
                      <td className="text-right font-mono">{(d.impressions || 0).toLocaleString("fr-FR")}</td>
                      <td className="text-right font-mono">{(d.clicks || 0).toLocaleString("fr-FR")}</td>
                      <td className="text-right font-mono">{(d.spent || 0).toLocaleString("fr-FR")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
