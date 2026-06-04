import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { resolveAssetUrl } from "@/lib/useAssetUrl";
import { computeBannerStyles } from "@/lib/bannerStyle";
import AdBannersLivePanel from "./AdBannersLivePanel";
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
  Share2,
  RefreshCw,
  Ruler,
  Beaker,
  Mail,
  Phone,
  Bell,
  Trophy,
  Send,
} from "lucide-react";

// Iter38r-fix9w — Admin page to manage paid advertising banners.

const DEFAULT_DRAFT = {
  name: "",
  advertiser_name: "",
  image_url: "",
  media_kind: "image",
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
  // Iter38r-fix9z5 — Display sizing controls
  display_mode: "auto",
  aspect_ratio: "16:9",
  width_pct: 100,
  height_px: 80,
  width_px: 728,
  object_fit: "cover",
  // Iter38r-fix9z6 — A/B testing + contact + reminders
  ab_enabled: false,
  variant_b_image_url: "",
  variant_b_media_kind: "image",
  variant_b_target_url: "",
  advertiser_email: "",
  advertiser_phone: "",
  reminder_email_enabled: true,
  reminder_wa_enabled: false,
  reminder_days_before: 3,
  // Iter40-modal — Modal display frequency (only used when placement=public_modal)
  modal_frequency: "session",
  // Iter40-modal-ab — Per-variant modal frequency override (empty = same as A)
  variant_b_modal_frequency: "",
};

export default function AdminAdBanners() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState(DEFAULT_DRAFT);
  const [editing, setEditing] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [statsId, setStatsId] = useState(null);
  const [stats, setStats] = useState(null);
  const [renewals, setRenewals] = useState([]);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/ad-banners");
      setItems(r.data?.items || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally { setLoading(false); }
    // Iter38r-fix9z5 — Load renewal requests (best-effort, silent on failure)
    try {
      const r2 = await apiClient.get("/admin/ad-renewal-requests");
      setRenewals(r2.data?.items || []);
    } catch { /* ignore */ }
  };

  const markRenewalHandled = async (id) => {
    try {
      await apiClient.post(`/admin/ad-renewal-requests/${id}/mark-handled`);
      toast.success("Demande marquée comme traitée");
      await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
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
      media_kind: it.media_kind || (/\.(mp4|webm|mov)$/i.test(it.image_url || "") ? "video" : "image"),
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
      // Iter38r-fix9z5 — Display sizing
      display_mode: it.display_mode || "auto",
      aspect_ratio: it.aspect_ratio || "16:9",
      width_pct: it.width_pct ?? 100,
      height_px: it.height_px ?? 80,
      width_px: it.width_px ?? 728,
      object_fit: it.object_fit || "cover",
      // Iter38r-fix9z6 — A/B + contact + reminder
      ab_enabled: !!it.ab_enabled,
      variant_b_image_url: it.variant_b_image_url || "",
      variant_b_media_kind: it.variant_b_media_kind || "image",
      variant_b_target_url: it.variant_b_target_url || "",
      advertiser_email: it.advertiser_email || "",
      advertiser_phone: it.advertiser_phone || "",
      reminder_email_enabled: it.reminder_email_enabled !== false,
      reminder_wa_enabled: !!it.reminder_wa_enabled,
      reminder_days_before: it.reminder_days_before ?? 3,
      // Iter40-modal — Modal display frequency
      modal_frequency: it.modal_frequency || "session",
      // Iter40-modal-ab — Per-variant modal frequency override
      variant_b_modal_frequency: it.variant_b_modal_frequency || "",
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

  // Iter38r-fix9y — Copy the public share URL to clipboard
  const copyShareUrl = async (it) => {
    if (!it.share_path) {
      toast.error("Cette bannière n'a pas encore de lien public — enregistrez-la d'abord.");
      return;
    }
    const origin = window.location.origin;
    const url = `${origin}${it.share_path}`;
    try {
      await navigator.clipboard.writeText(url);
      toast.success("Lien public copié dans le presse-papier", {
        description: url,
        duration: 6000,
      });
    } catch {
      // Fallback: prompt
      window.prompt("Copiez ce lien public pour l'annonceur :", url);
    }
  };

  const rotateToken = async (it) => {
    if (!window.confirm(`Régénérer le lien public ? L'ancien lien partagé à l'annonceur cessera de fonctionner.`)) return;
    try {
      await apiClient.post(`/admin/ad-banners/${it.id}/rotate-token`);
      toast.success("Nouveau lien généré");
      await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
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

      {/* Iter38r-fix9z7 — Live impressions/clicks panel (WebSocket) */}
      <AdBannersLivePanel />

      {/* Iter38r-fix9z5 — Renewal requests inbox (from public ad reports) */}
      {renewals.filter((r) => r.status === "new").length > 0 && (
        <section className="rounded-2xl ring-1 ring-fuchsia-200 bg-fuchsia-50/40 p-4 space-y-2" data-testid="ad-renewal-inbox">
          <h2 className="font-display font-semibold text-fuchsia-900 inline-flex items-center gap-2">
            <RefreshCw className="h-4 w-4" /> Demandes de renouvellement · {renewals.filter((r) => r.status === "new").length}
          </h2>
          <div className="space-y-2">
            {renewals.filter((r) => r.status === "new").map((r) => (
              <div key={r.id} className="rounded-xl bg-white ring-1 ring-fuchsia-200 p-3 flex items-start gap-3 flex-wrap" data-testid={`ad-renewal-${r.id}`}>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-slate-800">{r.banner_name} · {r.advertiser_name || "—"}</p>
                  <p className="text-xs text-slate-600">
                    {r.contact_name && <span>{r.contact_name} · </span>}
                    {r.contact_email && <span className="text-sky-700">{r.contact_email}</span>}
                    {r.contact_email && r.contact_phone && <span> · </span>}
                    {r.contact_phone && <span className="font-mono text-emerald-700">{r.contact_phone}</span>}
                  </p>
                  <p className="text-xs text-slate-700 mt-1">
                    Nouveau budget : <strong>{(r.new_budget || 0).toLocaleString("fr-FR")} {r.currency}</strong>
                    {" · "}Durée : <strong>{r.target_duration_days} jours</strong>
                  </p>
                  {r.message && <p className="text-[11px] text-slate-500 mt-1 italic">« {r.message} »</p>}
                  <p className="text-[10px] text-slate-400 mt-0.5">{new Date(r.created_at).toLocaleString("fr-FR")}</p>
                </div>
                <button
                  onClick={() => markRenewalHandled(r.id)}
                  className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 text-white px-3 py-1.5 text-xs hover:bg-emerald-700"
                  data-testid={`ad-renewal-handle-${r.id}`}
                >
                  <CheckCircle2 className="h-3.5 w-3.5" /> Marquer traitée
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

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
                            it.media_kind === "video" ? (
                              <video src={resolveAssetUrl(it.image_url)} className="h-8 w-16 object-cover rounded ring-1 ring-slate-200" muted autoPlay loop playsInline />
                            ) : (
                              <img src={resolveAssetUrl(it.image_url)} alt="" className="h-8 w-16 object-cover rounded ring-1 ring-slate-200" />
                            )
                          )}
                          <div className="min-w-0">
                            <p className="font-semibold text-slate-800 truncate">{it.name}</p>
                            {it.advertiser_name && <p className="text-[10px] text-slate-500 truncate">{it.advertiser_name}</p>}
                          </div>
                        </div>
                      </td>
                      <td className="text-slate-700 px-2 capitalize">{it.placement === "both" ? "Public + Portail" : it.placement === "public_modal" ? "Modale publique" : it.placement}</td>
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
                          {/* Iter38r-fix9y — Copy public share URL */}
                          <button onClick={() => copyShareUrl(it)} className="rounded p-1 ring-1 ring-emerald-300 bg-emerald-50 hover:bg-emerald-100 text-emerald-700" title="Copier le lien public pour l'annonceur" data-testid={`ad-banner-share-${it.id}`}>
                            <Share2 className="h-3 w-3" />
                          </button>
                          <button onClick={() => rotateToken(it)} className="rounded p-1 ring-1 ring-amber-300 bg-amber-50 hover:bg-amber-100 text-amber-700" title="Régénérer le lien public (invalide l'ancien)" data-testid={`ad-banner-rotate-${it.id}`}>
                            <RefreshCw className="h-3 w-3" />
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
  const handleFileChange = async (e, variant = "a") => {
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
      // Iter38r-fix9z — Store the relative path (e.g. "/api/files/abc"). The
      // browser resolves it against window.location.origin at render time,
      // so the same DB row works in BOTH preview and production. Storing the
      // preview origin here was the cause of the broken-links incident.
      const relativeUrl = (data.url || "").startsWith("/")
        ? data.url
        : `/${data.url || ""}`;
      // Iter38r-fix9z3 — Save the media kind so the renderer knows whether to
      // use <img> or <video>. Without this, /api/files/{id} URLs (extension-less)
      // were mis-rendered as <img> for video files → broken-image icon.
      const mediaKind = file.type.startsWith("video/") ? "video" : "image";
      if (variant === "b") {
        setDraft((d) => ({
          ...d,
          variant_b_image_url: relativeUrl,
          variant_b_media_kind: mediaKind,
          variant_b_target_url: d.variant_b_target_url ? d.variant_b_target_url : (d.target_url || relativeUrl),
        }));
      } else {
        setDraft((d) => ({
          ...d,
          image_url: relativeUrl,
          media_kind: mediaKind,
          target_url: d.target_url ? d.target_url : relativeUrl,
        }));
      }
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
          {draft.media_kind === "video" ? (
            <video src={resolveAssetUrl(draft.image_url)} className="h-14 w-28 object-cover rounded" muted autoPlay loop playsInline controls />
          ) : (
            <img src={resolveAssetUrl(draft.image_url)} alt="aperçu" className="h-14 w-28 object-cover rounded" />
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
            <option value="public_modal">Modale aléatoire (page publique)</option>
          </select>
        </Field>
        {draft.placement === "public_modal" && (
          <Field label="Fréquence d'affichage de la modale" testid="ad-form-modal-frequency">
            <select value={draft.modal_frequency} onChange={(e) => setDraft({ ...draft, modal_frequency: e.target.value })} className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white">
              <option value="session">1 fois par session (recommandé)</option>
              <option value="daily">1 fois par jour et par visiteur</option>
              <option value="always">À chaque chargement de page</option>
            </select>
          </Field>
        )}
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

      {/* Iter38r-fix9z6 — A/B testing + advertiser contact + reminder */}
      <BannerABBlock draft={draft} setDraft={setDraft} handleFileChange={handleFileChange} uploading={uploading} />
      <BannerContactReminderBlock draft={draft} setDraft={setDraft} />

      {/* Iter38r-fix9z5 — Sizing controls */}
      <BannerSizingBlock draft={draft} setDraft={setDraft} />

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

          {/* Iter38r-fix9z6 — A/B breakdown */}
          {stats.ab?.enabled && <ABBreakdown ab={stats.ab} />}

          {/* Iter40-modal — Modal-specific counters (only when modal_impressions > 0) */}
          {stats.modal && (stats.modal.impressions > 0 || stats.modal.clicks > 0) && (
            <div className="rounded-xl ring-1 ring-fuchsia-200 bg-fuchsia-50/40 p-3 space-y-2" data-testid="ad-stats-modal-breakdown">
              <p className="text-xs uppercase font-semibold text-fuchsia-700">
                Modale aléatoire · Fréquence : {stats.modal.frequency === "session" ? "1×/session" : stats.modal.frequency === "daily" ? "1×/jour" : "À chaque chargement"}
              </p>
              <div className="grid grid-cols-3 gap-2 text-xs">
                <div className="rounded-lg bg-white ring-1 ring-fuchsia-200 p-2">
                  <p className="text-[10px] uppercase text-slate-500">Affichages modale</p>
                  <p className="font-display font-bold text-slate-800 tabular-nums">{stats.modal.impressions.toLocaleString("fr-FR")}</p>
                </div>
                <div className="rounded-lg bg-white ring-1 ring-fuchsia-200 p-2">
                  <p className="text-[10px] uppercase text-slate-500">Clics modale</p>
                  <p className="font-display font-bold text-slate-800 tabular-nums">{stats.modal.clicks.toLocaleString("fr-FR")}</p>
                </div>
                <div className="rounded-lg bg-white ring-1 ring-fuchsia-200 p-2">
                  <p className="text-[10px] uppercase text-slate-500">CTR modale</p>
                  <p className="font-display font-bold text-fuchsia-700 tabular-nums">{stats.modal.ctr_pct}%</p>
                </div>
              </div>
              {/* Iter40-modal-ab — Per-variant breakdown when A/B is on */}
              {stats.ab?.enabled && (stats.modal.variant_a?.impressions > 0 || stats.modal.variant_b?.impressions > 0) && (
                <div className="grid grid-cols-2 gap-2 pt-2 border-t border-fuchsia-200/60">
                  <ModalVariantTile
                    label="A"
                    st={stats.modal.variant_a}
                    freqLabel={stats.modal.frequency}
                  />
                  <ModalVariantTile
                    label="B"
                    st={stats.modal.variant_b}
                    freqLabel={stats.modal.variant_b_frequency || stats.modal.frequency}
                  />
                </div>
              )}
            </div>
          )}

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


// Iter38r-fix9z5 — Sizing controls for the banner display.
// Lets the admin pick between four modes:
//   • auto        — current responsive default (64/80px tall, full width)
//   • ratio       — % width × aspect ratio (16:9, 21:9, 4:1, custom)
//   • percentage  — % width with a fixed height in pixels
//   • fixed       — exact pixel width × height
const COMMON_RATIOS = ["16:9", "21:9", "4:1", "3:1", "2:1", "1:1", "4:5", "9:16"];

function BannerSizingBlock({ draft, setDraft }) {
  const mode = draft.display_mode || "auto";
  const update = (patch) => setDraft({ ...draft, ...patch });
  const aspectIsCustom = !COMMON_RATIOS.includes(draft.aspect_ratio);

  // Live preview style
  const previewStyles = computeBannerStyles(draft);

  return (
    <div className="rounded-xl ring-1 ring-sky-200 bg-sky-50/40 p-4 space-y-3" data-testid="ad-banner-sizing-block">
      <h4 className="inline-flex items-center gap-2 text-sm font-display font-semibold text-sky-900">
        <Ruler className="h-4 w-4" /> Dimensions d'affichage
      </h4>
      <p className="text-[10px] text-slate-500 -mt-1">
        Contrôlez comment la bannière s'affiche sur les pages publiques / le portail. Les valeurs respectent la largeur maximale du conteneur (1280px).
      </p>

      <div className="flex flex-wrap gap-2 text-xs" data-testid="ad-sizing-mode">
        {[
          { v: "auto", label: "Auto (responsive)", hint: "Défaut — 64/80px de haut" },
          { v: "ratio", label: "Ratio", hint: "% largeur × aspect-ratio" },
          { v: "percentage", label: "Pourcentage", hint: "% largeur + hauteur fixe" },
          { v: "fixed", label: "Fixe (px)", hint: "Dimensions exactes" },
        ].map((opt) => (
          <button
            key={opt.v}
            type="button"
            onClick={() => update({ display_mode: opt.v })}
            className={`px-3 py-1.5 rounded-lg ring-1 transition-all ${
              mode === opt.v
                ? "bg-sky-600 text-white ring-sky-700 shadow-sm"
                : "bg-white text-slate-700 ring-slate-300 hover:ring-sky-400"
            }`}
            data-testid={`ad-sizing-mode-${opt.v}`}
            title={opt.hint}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {mode === "ratio" && (
        <div className="grid sm:grid-cols-2 gap-3" data-testid="ad-sizing-ratio-block">
          <label className="block">
            <span className="text-[11px] uppercase font-semibold text-slate-500">Aspect ratio (L:H)</span>
            <div className="flex gap-2 mt-1">
              <select
                value={aspectIsCustom ? "__custom" : draft.aspect_ratio}
                onChange={(e) => {
                  if (e.target.value === "__custom") {
                    update({ aspect_ratio: "10:3" });
                  } else {
                    update({ aspect_ratio: e.target.value });
                  }
                }}
                className="text-sm rounded-lg ring-1 ring-slate-300 px-2 py-2 bg-white flex-1"
                data-testid="ad-sizing-aspect-select"
              >
                {COMMON_RATIOS.map((r) => <option key={r} value={r}>{r}</option>)}
                <option value="__custom">Personnalisé…</option>
              </select>
              {aspectIsCustom && (
                <input
                  type="text"
                  value={draft.aspect_ratio}
                  onChange={(e) => update({ aspect_ratio: e.target.value })}
                  placeholder="ex: 10:3"
                  pattern="\d{1,4}:\d{1,4}"
                  className="w-24 text-sm rounded-lg ring-1 ring-slate-300 px-2 py-2 bg-white font-mono"
                  data-testid="ad-sizing-aspect-custom"
                />
              )}
            </div>
          </label>
          <label className="block">
            <span className="text-[11px] uppercase font-semibold text-slate-500">Largeur (% du conteneur)</span>
            <div className="flex items-center gap-3 mt-1">
              <input
                type="range" min="10" max="100" step="5"
                value={draft.width_pct}
                onChange={(e) => update({ width_pct: parseInt(e.target.value, 10) })}
                className="flex-1"
                data-testid="ad-sizing-width-pct-slider"
              />
              <span className="font-mono text-xs w-12 text-right tabular-nums">{draft.width_pct}%</span>
            </div>
          </label>
        </div>
      )}

      {mode === "percentage" && (
        <div className="grid sm:grid-cols-2 gap-3" data-testid="ad-sizing-pct-block">
          <label className="block">
            <span className="text-[11px] uppercase font-semibold text-slate-500">Largeur (% du conteneur)</span>
            <div className="flex items-center gap-3 mt-1">
              <input
                type="range" min="10" max="100" step="5"
                value={draft.width_pct}
                onChange={(e) => update({ width_pct: parseInt(e.target.value, 10) })}
                className="flex-1"
                data-testid="ad-sizing-width-pct-slider"
              />
              <span className="font-mono text-xs w-12 text-right tabular-nums">{draft.width_pct}%</span>
            </div>
          </label>
          <label className="block">
            <span className="text-[11px] uppercase font-semibold text-slate-500">Hauteur (px)</span>
            <input
              type="number" min="20" max="1200" step="10"
              value={draft.height_px}
              onChange={(e) => update({ height_px: parseInt(e.target.value, 10) || 80 })}
              className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white mt-1"
              data-testid="ad-sizing-height-px"
            />
          </label>
        </div>
      )}

      {mode === "fixed" && (
        <div className="grid sm:grid-cols-2 gap-3" data-testid="ad-sizing-fixed-block">
          <label className="block">
            <span className="text-[11px] uppercase font-semibold text-slate-500">Largeur (px)</span>
            <input
              type="number" min="50" max="2400" step="10"
              value={draft.width_px}
              onChange={(e) => update({ width_px: parseInt(e.target.value, 10) || 728 })}
              className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white mt-1 font-mono"
              data-testid="ad-sizing-width-px"
            />
          </label>
          <label className="block">
            <span className="text-[11px] uppercase font-semibold text-slate-500">Hauteur (px)</span>
            <input
              type="number" min="20" max="1200" step="10"
              value={draft.height_px}
              onChange={(e) => update({ height_px: parseInt(e.target.value, 10) || 90 })}
              className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white mt-1 font-mono"
              data-testid="ad-sizing-height-px"
            />
          </label>
        </div>
      )}

      {mode !== "auto" && (
        <label className="block">
          <span className="text-[11px] uppercase font-semibold text-slate-500">Adaptation du média (object-fit)</span>
          <div className="flex gap-2 mt-1 text-xs">
            {[
              { v: "cover", label: "Cover (remplit, peut rogner)" },
              { v: "contain", label: "Contain (visible intégralement, peut avoir des bandes)" },
              { v: "fill", label: "Fill (étire)" },
            ].map((opt) => (
              <button
                key={opt.v}
                type="button"
                onClick={() => update({ object_fit: opt.v })}
                className={`px-3 py-1.5 rounded-lg ring-1 transition-all ${
                  draft.object_fit === opt.v
                    ? "bg-slate-800 text-white ring-slate-900"
                    : "bg-white text-slate-700 ring-slate-300 hover:ring-slate-500"
                }`}
                data-testid={`ad-sizing-fit-${opt.v}`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </label>
      )}

      {/* Live preview */}
      <div className="border-t border-sky-200 pt-3 mt-1">
        <p className="text-[10px] uppercase font-semibold text-slate-500 mb-1.5">Aperçu en direct</p>
        <div className="bg-slate-900 rounded-lg p-1 overflow-hidden ring-1 ring-slate-700" data-testid="ad-sizing-preview">
          {draft.image_url ? (
            <div style={previewStyles.outer} className="mx-auto bg-slate-800">
              {draft.media_kind === "video" ? (
                <video
                  src={resolveAssetUrl(draft.image_url)}
                  className={previewStyles.mode === "auto" ? "w-full h-16 sm:h-20 object-cover" : ""}
                  style={previewStyles.mode === "auto" ? undefined : previewStyles.inner}
                  muted autoPlay loop playsInline
                />
              ) : (
                <img
                  src={resolveAssetUrl(draft.image_url)}
                  alt="aperçu"
                  className={previewStyles.mode === "auto" ? "w-full h-16 sm:h-20 object-cover" : ""}
                  style={previewStyles.mode === "auto" ? undefined : previewStyles.inner}
                />
              )}
            </div>
          ) : (
            <p className="text-center text-[11px] text-slate-400 italic py-6">Chargez une image ou une vidéo pour voir l'aperçu</p>
          )}
        </div>
      </div>
    </div>
  );
}

// Iter40-modal-ab — Per-variant modal CTR tile (fuchsia palette to match the modal section).
function ModalVariantTile({ label, st, freqLabel }) {
  const s = st || { impressions: 0, clicks: 0, ctr_pct: 0 };
  const fLabel =
    freqLabel === "session" ? "1×/session"
    : freqLabel === "daily" ? "1×/jour"
    : freqLabel === "always" ? "À chaque chargement"
    : (freqLabel || "—");
  return (
    <div className="rounded-lg bg-white ring-1 ring-fuchsia-200 p-2" data-testid={`ad-stats-modal-variant-${label.toLowerCase()}`}>
      <div className="flex items-center justify-between">
        <p className="text-[10px] uppercase font-semibold text-fuchsia-700">Variante {label}</p>
        <span className="text-[9px] text-slate-500 italic">{fLabel}</span>
      </div>
      <div className="grid grid-cols-3 gap-1.5 text-[11px] mt-1.5">
        <div>
          <p className="text-[9px] uppercase text-slate-500">Affich.</p>
          <p className="font-display font-bold text-slate-800 tabular-nums">{(s.impressions || 0).toLocaleString("fr-FR")}</p>
        </div>
        <div>
          <p className="text-[9px] uppercase text-slate-500">Clics</p>
          <p className="font-display font-bold text-slate-800 tabular-nums">{(s.clicks || 0).toLocaleString("fr-FR")}</p>
        </div>
        <div>
          <p className="text-[9px] uppercase text-slate-500">CTR</p>
          <p className="font-display font-bold text-fuchsia-700 tabular-nums">{s.ctr_pct || 0}%</p>
        </div>
      </div>
    </div>
  );
}


// Iter38r-fix9z6 — Per-variant CTR comparison + winner badge.
function ABBreakdown({ ab }) {
  const a = ab.variant_a || {};
  const b = ab.variant_b || {};
  const winner = ab.winner; // "a" | "b" | null
  const tile = (label, st, isWinner) => (
    <div className={`rounded-xl p-3 ring-1 ${isWinner ? "ring-amber-400 bg-amber-50" : "ring-slate-200 bg-white"}`} data-testid={`ad-stats-variant-${label.toLowerCase()}`}>
      <div className="flex items-center justify-between mb-1">
        <p className="text-[11px] uppercase font-bold tracking-wider text-slate-600">Variante {label}</p>
        {isWinner && (
          <span className="inline-flex items-center gap-1 text-[10px] font-bold text-amber-700 bg-amber-100 px-2 py-0.5 rounded">
            <Trophy className="h-3 w-3" /> GAGNANTE
          </span>
        )}
      </div>
      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <p className="text-[9px] uppercase text-slate-400">Vues</p>
          <p className="font-display font-bold tabular-nums">{(st.impressions || 0).toLocaleString("fr-FR")}</p>
        </div>
        <div>
          <p className="text-[9px] uppercase text-slate-400">Clics</p>
          <p className="font-display font-bold tabular-nums">{(st.clicks || 0).toLocaleString("fr-FR")}</p>
        </div>
        <div>
          <p className="text-[9px] uppercase text-slate-400">CTR</p>
          <p className={`font-display font-bold tabular-nums ${isWinner ? "text-amber-700" : "text-slate-700"}`}>{(st.ctr_pct || 0)}%</p>
        </div>
      </div>
    </div>
  );
  return (
    <div className="rounded-xl ring-1 ring-violet-200 bg-violet-50/30 p-3 space-y-2" data-testid="ad-stats-ab-breakdown">
      <p className="text-xs font-semibold text-violet-900 inline-flex items-center gap-1.5">
        <Beaker className="h-3.5 w-3.5" /> Test A/B — comparatif par variante
        {!winner && (a.impressions < 30 || b.impressions < 30) && (
          <span className="ml-2 text-[10px] text-slate-500 italic font-normal">En attente · min. 30 affichages par variante</span>
        )}
      </p>
      <div className="grid sm:grid-cols-2 gap-2">
        {tile("A", a, winner === "a")}
        {tile("B", b, winner === "b")}
      </div>
    </div>
  );
}


// Iter38r-fix9z6 — A/B testing block: upload variant B + target URL +
// preview side-by-side with variant A.
function BannerABBlock({ draft, setDraft, handleFileChange, uploading }) {
  return (
    <div className="rounded-xl ring-1 ring-violet-200 bg-violet-50/40 p-4 space-y-3" data-testid="ad-banner-ab-block">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h4 className="inline-flex items-center gap-2 text-sm font-display font-semibold text-violet-900">
          <Beaker className="h-4 w-4" /> Test A/B — 2 variantes alternées 50/50
        </h4>
        <label className="inline-flex items-center gap-2 text-xs cursor-pointer">
          <input
            type="checkbox"
            checked={!!draft.ab_enabled}
            onChange={(e) => setDraft({ ...draft, ab_enabled: e.target.checked })}
            className="h-4 w-4 accent-violet-600"
            data-testid="ad-ab-enable"
          />
          <span className="font-semibold">Activer le mode A/B</span>
        </label>
      </div>
      {draft.ab_enabled && (
        <>
          <p className="text-[11px] text-violet-700">
            Chaque visiteur voit aléatoirement la variante A ou la variante B (50/50). Les statistiques distinguent les performances pour identifier la version gagnante (mini 30 affichages par variante requis).
          </p>
          <div className="grid sm:grid-cols-2 gap-3">
            <div className="rounded-lg bg-white ring-1 ring-slate-200 p-3">
              <p className="text-[10px] uppercase font-semibold text-slate-500 mb-2">Variante A (par défaut)</p>
              {draft.image_url ? (
                draft.media_kind === "video" ? (
                  <video src={resolveAssetUrl(draft.image_url)} className="w-full h-20 object-cover rounded ring-1 ring-slate-200" muted autoPlay loop playsInline />
                ) : (
                  <img src={resolveAssetUrl(draft.image_url)} alt="Variante A" className="w-full h-20 object-cover rounded ring-1 ring-slate-200" />
                )
              ) : (
                <div className="h-20 rounded bg-slate-100 flex items-center justify-center text-[10px] text-slate-400 italic">Aucun média</div>
              )}
              <p className="text-[10px] text-slate-500 mt-1.5 truncate font-mono">{draft.target_url || "—"}</p>
            </div>
            <div className="rounded-lg bg-white ring-1 ring-violet-300 p-3">
              <p className="text-[10px] uppercase font-semibold text-violet-700 mb-2">Variante B</p>
              {draft.variant_b_image_url ? (
                draft.variant_b_media_kind === "video" ? (
                  <video src={resolveAssetUrl(draft.variant_b_image_url)} className="w-full h-20 object-cover rounded ring-1 ring-violet-200" muted autoPlay loop playsInline />
                ) : (
                  <img src={resolveAssetUrl(draft.variant_b_image_url)} alt="Variante B" className="w-full h-20 object-cover rounded ring-1 ring-violet-200" />
                )
              ) : (
                <div className="h-20 rounded bg-slate-50 flex items-center justify-center text-[10px] text-slate-400 italic">Aucun média</div>
              )}
              <input
                type="file"
                accept="image/*,video/*"
                disabled={uploading}
                onChange={(e) => handleFileChange(e, "b")}
                className="w-full text-[10px] mt-2 file:mr-2 file:py-1 file:px-2 file:rounded file:border-0 file:text-[10px] file:bg-violet-100 file:text-violet-700 hover:file:bg-violet-200"
                data-testid="ad-ab-variant-b-upload"
              />
              <input
                type="url"
                value={draft.variant_b_target_url}
                onChange={(e) => setDraft({ ...draft, variant_b_target_url: e.target.value })}
                placeholder="URL cible variante B"
                className="w-full text-xs rounded ring-1 ring-violet-200 px-2 py-1.5 mt-2 bg-white"
                data-testid="ad-ab-variant-b-target"
              />
              {draft.placement === "public_modal" && (
                <select
                  value={draft.variant_b_modal_frequency || ""}
                  onChange={(e) => setDraft({ ...draft, variant_b_modal_frequency: e.target.value })}
                  className="w-full text-xs rounded ring-1 ring-violet-200 px-2 py-1.5 mt-2 bg-white"
                  data-testid="ad-ab-variant-b-frequency"
                  title="Fréquence d'affichage spécifique à la variante B (vide = même que A)"
                >
                  <option value="">Fréquence : identique à variante A</option>
                  <option value="session">B : 1×/session</option>
                  <option value="daily">B : 1×/jour</option>
                  <option value="always">B : à chaque chargement</option>
                </select>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// Iter38r-fix9z6 — Advertiser contact info + reminder email toggle.
function BannerContactReminderBlock({ draft, setDraft }) {
  return (
    <div className="rounded-xl ring-1 ring-emerald-200 bg-emerald-50/40 p-4 space-y-3" data-testid="ad-banner-contact-block">
      <h4 className="inline-flex items-center gap-2 text-sm font-display font-semibold text-emerald-900">
        <Bell className="h-4 w-4" /> Contact annonceur + rappel de renouvellement
      </h4>
      <div className="grid sm:grid-cols-2 gap-3">
        <label className="block">
          <span className="text-[11px] uppercase font-semibold text-slate-500 inline-flex items-center gap-1"><Mail className="h-3 w-3" /> Email annonceur</span>
          <input
            type="email" value={draft.advertiser_email}
            onChange={(e) => setDraft({ ...draft, advertiser_email: e.target.value })}
            placeholder="contact@entreprise.com"
            className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 mt-1 bg-white"
            data-testid="ad-contact-email"
          />
        </label>
        <label className="block">
          <span className="text-[11px] uppercase font-semibold text-slate-500 inline-flex items-center gap-1"><Phone className="h-3 w-3" /> Téléphone / WhatsApp</span>
          <input
            type="tel" value={draft.advertiser_phone}
            onChange={(e) => setDraft({ ...draft, advertiser_phone: e.target.value })}
            placeholder="+225 …"
            className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 mt-1 bg-white font-mono"
            data-testid="ad-contact-phone"
          />
        </label>
      </div>
      <div className="flex items-center justify-between gap-3 flex-wrap rounded-lg bg-white ring-1 ring-emerald-200 px-3 py-2">
        <label className="inline-flex items-center gap-2 text-xs cursor-pointer">
          <input
            type="checkbox"
            checked={!!draft.reminder_email_enabled}
            onChange={(e) => setDraft({ ...draft, reminder_email_enabled: e.target.checked })}
            className="h-4 w-4 accent-emerald-600"
            data-testid="ad-reminder-enable"
          />
          <Mail className="h-3.5 w-3.5 text-emerald-700" />
          <span className="font-semibold">Rappel par email</span>
        </label>
        <label className="inline-flex items-center gap-2 text-xs cursor-pointer">
          <input
            type="checkbox"
            checked={!!draft.reminder_wa_enabled}
            onChange={(e) => setDraft({ ...draft, reminder_wa_enabled: e.target.checked })}
            className="h-4 w-4 accent-green-600"
            data-testid="ad-reminder-wa-enable"
          />
          <Send className="h-3.5 w-3.5 text-green-700" />
          <span className="font-semibold">Rappel par WhatsApp</span>
        </label>
        <label className="inline-flex items-center gap-2 text-xs">
          <span className="text-slate-500">Délai :</span>
          <input
            type="number" min="1" max="30"
            value={draft.reminder_days_before}
            onChange={(e) => setDraft({ ...draft, reminder_days_before: parseInt(e.target.value, 10) || 3 })}
            disabled={!draft.reminder_email_enabled && !draft.reminder_wa_enabled}
            className="w-16 text-xs rounded ring-1 ring-slate-300 px-2 py-1 bg-white font-mono disabled:opacity-50"
            data-testid="ad-reminder-days"
          />
          <span className="text-slate-500">jours avant</span>
        </label>
      </div>
      <p className="text-[10px] text-slate-500 italic">
        Si activé et qu'une date d'expiration + un contact annonceur (email/téléphone) sont renseignés, un rappel automatique est envoyé chaque matin (09h30 Abidjan) avec le bilan de la campagne et un lien direct pour la renouveler.
      </p>
    </div>
  );
}

