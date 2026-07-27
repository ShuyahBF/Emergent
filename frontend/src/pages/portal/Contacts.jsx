import React, { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  Users, Plus, Trash2, MessageCircle, Tag, Share2, Lock,
  Send, X, History, RefreshCw, Pencil, Check, Clock,
  CheckCheck, AlertCircle, ArrowDownLeft, ArrowUpRight,
  Upload, Image as ImageIcon, FileText as FileTextIcon, Video, Info,
  CalendarClock, Trash, Link2, CreditCard, UserPlus, Inbox, Building2, Download,
  Paperclip, Mic, Play, BookmarkPlus, Ticket, CornerUpLeft, FolderOpen, ShoppingBag, FileEdit,
  Sparkles, Loader2,
} from "lucide-react";
import { parseTemplate, buildComponentsPayload, validateTemplateValues, renderPreview } from "@/lib/waTemplate";
import { useAuth } from "@/contexts/AuthContext";
import { phonePlaceholder } from "@/lib/tenantMeta";
import CrossTenantSearch from "@/components/CrossTenantSearch";
import { ContactGroupChips } from "@/components/ContactGroupChips";

const BACKEND = process.env.REACT_APP_BACKEND_URL || "";
const absoluteFileUrl = (u) => {
  if (!u) return "";
  if (u.startsWith("http")) return u;
  return `${BACKEND}${u.startsWith("/") ? "" : "/"}${u}`;
};

// Defensive coercion — third-party API responses sometimes return objects in
// fields where we expect strings (Meta, OVH, Orange…). Rendering an object as
// a JSX child crashes React with "Objects are not valid as a React child".
// Always pipe such fields through safeText() before rendering.
function safeText(v) {
  if (v == null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (typeof v === "object") {
    if (typeof v.message === "string") return v.message;
    if (typeof v.error === "string") return v.error;
    if (typeof v.detail === "string") return v.detail;
    try { return JSON.stringify(v).slice(0, 300); } catch { return "[objet]"; }
  }
  return String(v);
}

// Deterministic avatar color palette so the same contact always gets the same hue
const AVATAR_PALETTE = [
  "bg-emerald-500", "bg-sky-500", "bg-violet-500", "bg-rose-500",
  "bg-amber-500", "bg-fuchsia-500", "bg-teal-500", "bg-indigo-500",
];
function paletteFor(seed) {
  let h = 0;
  for (let i = 0; i < (seed || "").length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return AVATAR_PALETTE[h % AVATAR_PALETTE.length];
}

// Circular avatar (à la WhatsApp profile picture).
// Renders the contact's photo_url if present, otherwise a colored circle with
// initials derived from the contact's name (or its phone if no name).
function ContactAvatar({ contact, size = 32 }) {
  const photo = absoluteFileUrl(contact?.photo_url);
  if (photo) {
    return (
      <img
        src={photo}
        alt={contact?.name || "Avatar"}
        className="rounded-full object-cover ring-2 ring-white shadow-sm flex-shrink-0"
        style={{ width: size, height: size }}
        data-testid={`contact-avatar-${contact?.id}`}
      />
    );
  }
  const seed = (contact?.name || contact?.phone || contact?.whatsapp || "?").toLowerCase();
  const colorClass = paletteFor(seed);
  const source = (contact?.name || contact?.phone || "?").trim();
  const parts = source.replace(/[._-]+/g, " ").split(/\s+/).filter(Boolean);
  let initials = "?";
  if (parts.length >= 2) initials = (parts[0][0] + parts[1][0]).toUpperCase();
  else if (parts.length === 1) initials = parts[0].slice(0, 2).toUpperCase();
  return (
    <span
      className={`inline-flex items-center justify-center rounded-full text-white font-semibold ring-2 ring-white shadow-sm flex-shrink-0 ${colorClass}`}
      style={{ width: size, height: size, fontSize: Math.max(10, size * 0.38) }}
      title={contact?.name || ""}
      data-testid={`contact-avatar-${contact?.id}`}
    >
      {initials}
    </span>
  );
}

/*
  Portal → Directory + WhatsApp.
  - CRUD contacts scoped to current client.
  - Inline edit of WhatsApp number (no full form needed).
  - Send WA template from the row.
  - Click a row to view the full conversation timeline.
*/
// Iter34w — Lightweight export dropdown (CSV / JSON / PDF) using a token
// added to the URL so the browser downloads the file directly. We piggyback
// on the existing API auth header by using `apiClient` to fetch as Blob.
function ContactsExportMenu() {
  const [open, setOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const download = async (format) => {
    setBusy(true);
    try {
      const r = await apiClient.get(`/me/contacts/export.${format}`, { responseType: "blob" });
      const blob = new Blob([r.data], { type: r.headers["content-type"] || "application/octet-stream" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const fname = (r.headers["content-disposition"] || "").match(/filename="?([^"]+)"?/);
      a.download = fname ? fname[1] : `contacts.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success(`Export ${format.toUpperCase()} téléchargé`);
    } catch (err) {
      toast.error("Erreur lors de l'export");
    } finally { setBusy(false); setOpen(false); }
  };
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={busy}
        className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 px-3 py-2 text-sm disabled:opacity-60"
        data-testid="contacts-export-btn"
      >
        <Download className="h-4 w-4" />
        Exporter
      </button>
      {open && (
        <div className="absolute right-0 mt-1 w-44 rounded-lg ring-1 ring-slate-200 bg-white shadow-lg py-1 z-20" data-testid="contacts-export-menu">
          <button onClick={() => download("csv")} className="w-full text-left px-3 py-1.5 text-xs hover:bg-sky-50" data-testid="export-csv-btn">CSV (Excel)</button>
          <button onClick={() => download("json")} className="w-full text-left px-3 py-1.5 text-xs hover:bg-sky-50" data-testid="export-json-btn">JSON</button>
          <button onClick={() => download("pdf")} className="w-full text-left px-3 py-1.5 text-xs hover:bg-sky-50" data-testid="export-pdf-btn">PDF</button>
        </div>
      )}
    </div>
  );
}


export default function Contacts() {
  const { user } = useAuth();
  const [items, setItems] = useState([]);
  const [clients, setClients] = useState([]); // roster used for company dropdown
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [companyFilter, setCompanyFilter] = useState(""); // ACME code or full company name
  const [modal, setModal] = useState(null); // {type:'edit'|'wa'|'history', contact?}
  const [smartFeatures, setSmartFeatures] = useState({ whatsapp: true, sms: true, ai: true, payments: true });
  const [unread, setUnread] = useState({ total: 0, by_contact: {} });
  // Iter34p — Affiche société + client lié à côté du titre. Lecture via
  // /me/account-detail pour récupérer le parent canonique.
  const [accountInfo, setAccountInfo] = useState(null);
  // Iter38r-fix9f — Honor ?q=... in URL (e.g., when navigated from Liluvine toast)
  const [searchParams] = useSearchParams();
  useEffect(() => {
    const q = searchParams.get("q");
    if (q) setFilter(q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const load = async () => {
    setLoading(true);
    try {
      const [contactsRes, clientsRes] = await Promise.all([
        apiClient.get("/me/contacts"),
        apiClient.get("/me/clients-roster").catch(() => ({ data: [] })),
      ]);
      setItems(Array.isArray(contactsRes.data) ? contactsRes.data : []);
      setClients(clientsRes.data || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  };

  const loadUnread = async () => {
    try {
      const r = await apiClient.get("/me/whatsapp/unread");
      setUnread({ total: r.data?.total || 0, by_contact: r.data?.by_contact || {} });
    } catch { /* noop */ }
  };

  const [pendingImports, setPendingImports] = useState([]);
  const loadPending = async () => {
    try {
      const r = await apiClient.get("/me/wa-pending-imports");
      setPendingImports(Array.isArray(r.data) ? r.data : []);
    } catch { /* noop */ }
  };

  useEffect(() => {
    load();
    loadUnread();
    loadPending();
    apiClient.get("/me/features").then((r) => setSmartFeatures(r.data?.features || {})).catch(() => {});
    apiClient.get("/me/account-detail").then((r) => setAccountInfo(r.data)).catch(() => {});
  }, []);
  useEffect(() => {
    const t = setInterval(() => { loadUnread(); loadPending(); }, 30000);
    return () => clearInterval(t);
  }, []);

  const del = async (id) => {
    if (!window.confirm("Supprimer ce contact ?")) return;
    try {
      await apiClient.delete(`/me/contacts/${id}`);
      toast.success("Contact supprimé");
      await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const companyOptions = useMemo(() => {
    const seen = new Set();
    const opts = [];
    clients.forEach((c) => {
      const code = c.client_code || "";
      const name = c.company || c.full_name || "";
      const key = (code || name).toLowerCase();
      if (!key || seen.has(key)) return;
      seen.add(key);
      opts.push({ value: name || code, code, label: code ? `${code} — ${name}` : name });
    });
    // Also surface any company already typed on existing contacts but not in clients (legacy)
    items.forEach((c) => {
      const key = (c.company || "").toLowerCase();
      if (!key || seen.has(key)) return;
      seen.add(key);
      opts.push({ value: c.company, code: "", label: c.company });
    });
    return opts.sort((a, b) => a.label.localeCompare(b.label));
  }, [clients, items]);

  // Iter34r — Quick share-filter pill: tous / partagés / privés / non-lus
  const [shareFilter, setShareFilter] = useState("all");
  // Iter43-fix5 — Tri configurable. Par défaut : date d'interaction décroissante.
  const [sortBy, setSortBy] = useState("interaction_desc"); // interaction_desc | name_asc | name_desc
  // Iter35r — Auto-open on "Non-lus" tab when there are unread inbound messages.
  // Only triggered once (when the unread count crosses 0) to avoid overriding
  // the user's manual tab choice afterwards.
  const autoOpenedRef = React.useRef(false);
  useEffect(() => {
    if (!autoOpenedRef.current && unread.total > 0) {
      setShareFilter("unread");
      autoOpenedRef.current = true;
    }
  }, [unread.total]);

  const filtered = items.filter((c) => {
    if (companyFilter && (c.company || "") !== companyFilter) return false;
    if (shareFilter === "shared" && !c.shared) return false;
    if (shareFilter === "private" && c.shared) return false;
    if (shareFilter === "unread" && !(unread.by_contact && unread.by_contact[c.id])) return false;
    if (!filter.trim()) return true;
    const q = filter.toLowerCase();
    return [c.name, c.phone, c.whatsapp, c.email, c.company, (c.tags || []).join(" ")]
      .some((v) => (v || "").toLowerCase().includes(q));
  });

  // Iter43-fix5 — Tri appliqué après filtres. Le champ `last_interaction_at`
  // est calculé côté backend depuis wa_messages + sms_messages (digits-10).
  const sorted = useMemo(() => {
    const arr = filtered.slice();
    if (sortBy === "name_asc") {
      arr.sort((a, b) => (a.name || "").localeCompare(b.name || "", "fr", { sensitivity: "base" }));
    } else if (sortBy === "name_desc") {
      arr.sort((a, b) => (b.name || "").localeCompare(a.name || "", "fr", { sensitivity: "base" }));
    } else {
      // interaction_desc (défaut) — contacts sans interaction passent en fin de liste
      arr.sort((a, b) => {
        const ta = a.last_interaction_at || "";
        const tb = b.last_interaction_at || "";
        if (ta && !tb) return -1;
        if (!ta && tb) return 1;
        if (!ta && !tb) return (a.name || "").localeCompare(b.name || "", "fr", { sensitivity: "base" });
        return tb.localeCompare(ta);
      });
    }
    return arr;
  }, [filtered, sortBy]);

  // Live counts for the pills (respect company + search filters, ignore the
  // share filter itself so the counts reflect "what's available to switch to").
  const shareCounts = useMemo(() => {
    const base = items.filter((c) => {
      if (companyFilter && (c.company || "") !== companyFilter) return false;
      if (!filter.trim()) return true;
      const q = filter.toLowerCase();
      return [c.name, c.phone, c.whatsapp, c.email, c.company, (c.tags || []).join(" ")]
        .some((v) => (v || "").toLowerCase().includes(q));
    });
    return {
      all: base.length,
      shared: base.filter((c) => c.shared).length,
      private: base.filter((c) => !c.shared).length,
      unread: base.filter((c) => unread.by_contact && unread.by_contact[c.id]).length,
    };
  }, [items, companyFilter, filter, unread]);

  return (
    <div className="max-w-6xl space-y-5" data-testid="contacts-page">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Communication</p>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2 flex-wrap">
            <Users className="h-5 w-5 text-sawali-blue" />
            <span>Centre de Messagerie</span>
            {(user?.company || accountInfo?.parent_client?.company) && (
              <span className="inline-flex items-center gap-2 text-[11px] font-medium font-sans normal-case tracking-normal ml-2" data-testid="messagerie-context-pill">
                {user?.company && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-sky-100 text-sky-700 px-2.5 py-1 ring-1 ring-sky-200" title="Société de votre compte">
                    <Building2 className="h-3 w-3" /> {user.company}
                  </span>
                )}
                {accountInfo?.parent_client?.full_name && accountInfo.parent_client.full_name !== user?.full_name && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 text-emerald-700 px-2.5 py-1 ring-1 ring-emerald-200" title="Client lié (compte canonique)">
                    <Link2 className="h-3 w-3" /> Client lié : {accountInfo.parent_client.full_name}
                  </span>
                )}
              </span>
            )}
          </h1>
          <p className="text-[11px] text-slate-500 mt-0.5">Répertoire de contacts unifié — WhatsApp, SMS &amp; planifications</p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={load}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 px-3 py-2 text-sm disabled:opacity-60"
            data-testid="contacts-refresh"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Actualiser
          </button>
          {/* Iter34w — Exports list */}
          <ContactsExportMenu />
          <button
            onClick={() => setModal({ type: "edit" })}
            className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light"
            data-testid="contact-add-btn"
          >
            <Plus className="h-4 w-4" /> Nouveau contact
          </button>
        </div>
      </div>

      <div className="flex gap-3 items-center flex-wrap">
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Rechercher nom, tél, email, société, tag…"
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm min-w-[220px]"
          data-testid="contact-search"
        />
        <select
          value={companyFilter}
          onChange={(e) => setCompanyFilter(e.target.value)}
          className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm min-w-[180px]"
          data-testid="contact-company-filter"
        >
          <option value="">Tous les clients</option>
          {companyOptions.map((o) => <option key={o.label} value={o.value}>{o.label}</option>)}
        </select>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
          className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm min-w-[200px]"
          data-testid="contact-sort"
          title="Choisir l'ordre d'affichage"
        >
          <option value="interaction_desc">Interaction (plus récente)</option>
          <option value="name_asc">Nom A → Z</option>
          <option value="name_desc">Nom Z → A</option>
        </select>
        <span className="text-xs text-slate-500">{filtered.length} contact(s)</span>
      </div>

      {/* Iter34r — Quick share-filter pills with live counts */}
      <div className="flex items-center gap-2 flex-wrap -mt-1" data-testid="contacts-share-filter">
        {[
          { id: "all", label: "Tous", icon: Users, base: "bg-slate-900 text-white ring-slate-900", inactive: "bg-white text-slate-600 ring-slate-200 hover:bg-slate-50" },
          { id: "shared", label: "Partagés équipe", icon: Share2, base: "bg-emerald-100 text-emerald-700 ring-emerald-300", inactive: "bg-white text-slate-600 ring-slate-200 hover:bg-emerald-50" },
          { id: "private", label: "Privés", icon: Lock, base: "bg-amber-100 text-amber-700 ring-amber-300", inactive: "bg-white text-slate-600 ring-slate-200 hover:bg-amber-50" },
          { id: "unread", label: "Non-lus", icon: Inbox, base: "bg-rose-100 text-rose-700 ring-rose-300", inactive: "bg-white text-slate-600 ring-slate-200 hover:bg-rose-50" },
        ].map((p) => {
          const Icon = p.icon;
          const active = shareFilter === p.id;
          const count = shareCounts[p.id] || 0;
          return (
            <button
              key={p.id}
              type="button"
              onClick={() => setShareFilter(p.id)}
              className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold ring-1 transition-colors ${active ? p.base : p.inactive}`}
              data-testid={`share-filter-${p.id}`}
              title={`Afficher : ${p.label}`}
            >
              <Icon className="h-3 w-3" />
              {p.label}
              <span className={`rounded-full px-1.5 py-0.5 text-[10px] tabular-nums ${active ? "bg-white/30" : "bg-slate-100"}`}>{count}</span>
            </button>
          );
        })}
      </div>

      {pendingImports.length > 0 && (
        <PendingImportsBanner
          items={pendingImports}
          onChange={() => { loadPending(); load(); }}
        />
      )}

      {/* Cross-tenant search & import (2026-02) — récupération de fiches contact perdues */}
      <CrossTenantSearch user={user} onImported={load} />

      {loading ? (
        <div className="text-center text-slate-500 py-10">Chargement…</div>
      ) : sorted.length === 0 ? (
        <div className="text-center text-slate-400 py-10 italic text-sm">
          Aucun contact. Créez-en un avec "Nouveau contact".
        </div>
      ) : (
        <div className="rounded-xl bg-white border border-slate-200 overflow-x-auto -mx-3 sm:mx-0" data-testid="contacts-table">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-xs uppercase">
              <tr>
                <th className="text-left px-3 py-2">Nom</th>
                <th className="text-left px-3 py-2 hidden sm:table-cell">Société</th>
                <th className="text-left px-3 py-2 hidden md:table-cell">Téléphone</th>
                <th className="text-left px-3 py-2">WhatsApp</th>
                <th className="text-left px-3 py-2 hidden 2xl:table-cell max-w-[220px]">Email</th>
                <th className="text-left px-3 py-2 hidden 2xl:table-cell">Partage</th>
                <th className="text-right px-2 py-2 min-w-[180px]">Actions</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((c) => (
                <ContactRow
                  key={c.id}
                  c={c}
                  onReload={load}
                  onEdit={() => setModal({ type: "edit", contact: c })}
                  onWa={() => setModal({ type: "wa", contact: c })}
                  onSms={() => setModal({ type: "sms", contact: c })}
                  onSchedule={() => setModal({ type: "schedule", contact: c })}
                  onHistory={() => setModal({ type: "history", contact: c })}
                  onLiluvine={() => setModal({ type: "liluvine", contact: c })}
                  onDelete={() => del(c.id)}
                  waEnabled={!!smartFeatures.whatsapp}
                  smsEnabled={!!smartFeatures.sms}
                  unreadCount={unread.by_contact?.[c.id] || 0}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modal?.type === "edit" && (
        <ContactEditModal
          contact={modal.contact}
          companyOptions={companyOptions}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); load(); }}
        />
      )}
      {modal?.type === "wa" && (
        <WhatsAppModal contact={modal.contact} onClose={() => setModal(null)} onSent={load} userRole={user?.role} />
      )}
      {modal?.type === "sms" && (
        <SmsModal contact={modal.contact} onClose={() => setModal(null)} onSent={load} userRole={user?.role} />
      )}
      {modal?.type === "schedule" && (
        <ScheduleModal contact={modal.contact} onClose={() => setModal(null)} onScheduled={load} />
      )}
      {modal?.type === "history" && (
        <ConversationModal
          contact={modal.contact}
          onClose={() => { setModal(null); loadUnread(); }}
          onMessagesRead={loadUnread}
        />
      )}
      {modal?.type === "liluvine" && (
        <LiluvineTimelineModal
          contact={modal.contact}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}

// --- Contact row with inline WhatsApp edit ---
const ContactRow = ({ c, onReload, onEdit, onWa, onSms, onSchedule, onHistory, onLiluvine, onDelete, waEnabled = true, smsEnabled = true, unreadCount = 0 }) => {
  const [editingWa, setEditingWa] = useState(false);
  const [waValue, setWaValue] = useState(c.whatsapp || "");
  const [saving, setSaving] = useState(false);

  const saveWa = async () => {
    const trimmed = (waValue || "").trim();
    if (trimmed === (c.whatsapp || "")) { setEditingWa(false); return; }
    setSaving(true);
    try {
      await apiClient.put(`/me/contacts/${c.id}`, { whatsapp: trimmed });
      toast.success("Numéro WhatsApp mis à jour");
      setEditingWa(false);
      await onReload();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setSaving(false);
    }
  };

  return (
    <tr className="border-t border-slate-100 hover:bg-sky-50/70 hover:ring-1 hover:ring-sky-200 transition-colors" data-testid={`contact-row-${c.id}`}>
      <td className="px-3 py-2">
        <div className="flex items-start gap-2.5">
          <ContactAvatar contact={c} size={36} />
          <div className="min-w-0 flex-1">
            <button
              onClick={onHistory}
              className="font-semibold text-slate-900 hover:text-sawali-blue hover:underline text-left inline-flex items-center gap-2"
              title="Voir la conversation WhatsApp"
              data-testid={`contact-name-${c.id}`}
            >
              <span className="truncate">{c.name}</span>
              {unreadCount > 0 && (
                <span
                  className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1.5 rounded-full bg-rose-500 text-white text-[10px] font-bold tabular-nums ring-2 ring-white shadow-sm animate-pulse"
                  title={`${unreadCount} nouveau(x) message(s) reçu(s)`}
                  data-testid={`contact-unread-${c.id}`}
                >
                  {unreadCount > 99 ? "99+" : unreadCount}
                </span>
              )}
            </button>
            {c.unique_code && (
              <div
                className="text-[11px] text-sky-600 font-mono font-bold mt-0.5 inline-flex items-center gap-1"
                title="Code Unique inaltérable du contact"
                data-testid={`contact-unique-code-${c.id}`}
              >
                <Lock className="h-2.5 w-2.5" /> {c.unique_code}
              </div>
            )}
            {/* Mobile-only context (visible when Société/Téléphone columns are hidden) */}
            <div className="sm:hidden text-[11px] text-slate-500 mt-0.5 space-y-0.5">
              {c.company && <div className="truncate">{c.company}</div>}
              {c.phone && <div className="font-mono text-sky-600">{c.phone}</div>}
            </div>
            {c.tags?.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-1">
                {c.tags.map((t) => (
                  <span key={t} className="text-[10px] bg-slate-100 px-1.5 py-0.5 rounded inline-flex items-center gap-1">
                    <Tag className="h-2.5 w-2.5" /> {t}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      </td>
      <td className="px-3 py-2 hidden sm:table-cell text-slate-600">{c.company || "—"}</td>
      <td className="px-3 py-2 hidden md:table-cell text-sky-600 font-mono text-[12px]" data-testid={`contact-phone-${c.id}`}>{c.phone || "—"}</td>
      <td className="px-3 py-2 text-sky-600 font-mono text-[12px]">
        {editingWa ? (
          <div className="flex items-center gap-1">
            <input
              autoFocus
              value={waValue}
              onChange={(e) => setWaValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") saveWa(); if (e.key === "Escape") { setEditingWa(false); setWaValue(c.whatsapp || ""); } }}
              placeholder={phonePlaceholder()}
              className="w-36 rounded border border-sawali-blue px-2 py-1 text-[12px]"
              data-testid={`contact-wa-inline-${c.id}`}
            />
            <button
              onClick={saveWa}
              disabled={saving}
              className="text-emerald-700 hover:text-emerald-900 p-1"
              title="Enregistrer"
              data-testid={`contact-wa-save-${c.id}`}
            >
              <Check className="h-4 w-4" />
            </button>
            <button
              onClick={() => { setEditingWa(false); setWaValue(c.whatsapp || ""); }}
              className="text-slate-500 hover:text-slate-800 p-1"
              title="Annuler"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : (
          <button
            onClick={() => setEditingWa(true)}
            className="group inline-flex items-center gap-1 text-slate-600 hover:text-sawali-blue"
            title="Modifier le numéro WhatsApp"
            data-testid={`contact-wa-edit-${c.id}`}
          >
            <span>{c.whatsapp || "—"}</span>
            <Pencil className="h-3 w-3 opacity-40 group-hover:opacity-100 transition" />
          </button>
        )}
      </td>
      <td className="px-2 py-2 hidden 2xl:table-cell text-slate-600 max-w-[140px] truncate text-[11px]" title={c.email || ""}>{c.email || "—"}</td>
      <td className="px-3 py-2 hidden 2xl:table-cell">
        {/* Iter29 — Tous les contacts sont collaboratifs (visibles + éditables
            par tout user du même client). On affiche un badge "Équipe" pour
            le rappeler aux utilisateurs et un sous-titre avec l'auteur. */}
        <span
          className="text-[10px] bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded inline-flex items-center gap-1"
          title={c.owner_label ? `Créé par ${c.owner_label}` : "Visible par toute l'équipe"}
        >
          <Share2 className="h-2.5 w-2.5" /> Équipe
        </span>
        {c.owner_label && (
          <div className="text-[9px] text-slate-400 mt-0.5 truncate max-w-[120px]" title={c.owner_label}>
            par {c.owner_label}
          </div>
        )}
      </td>
      <td className="px-2 py-2 text-right whitespace-nowrap">
        <div className="inline-flex gap-1 items-center">
          <button
            onClick={onWa}
            disabled={!c.whatsapp || !waEnabled}
            title={!waEnabled ? "Fonctionnalité WhatsApp non activée — contactez votre administrateur" : (c.whatsapp ? "Envoyer un WhatsApp" : "Ajoutez d'abord un numéro WhatsApp")}
            className="inline-flex items-center gap-1 text-[11px] rounded bg-emerald-600 text-white px-2 py-1 hover:bg-emerald-700 disabled:opacity-40 disabled:cursor-not-allowed"
            data-testid={`contact-wa-${c.id}`}
          >
            <MessageCircle className="h-3 w-3" /> <span className="hidden sm:inline">WhatsApp</span>
          </button>
          <button
            onClick={onSms}
            disabled={!c.phone || !smsEnabled}
            title={!smsEnabled ? "Fonctionnalité SMS non activée — contactez votre administrateur" : (c.phone ? "Envoyer un SMS" : "Ajoutez d'abord un numéro de téléphone")}
            className="inline-flex items-center gap-1 text-[11px] rounded bg-amber-600 text-white px-2 py-1 hover:bg-amber-700 disabled:opacity-40 disabled:cursor-not-allowed"
            data-testid={`contact-sms-${c.id}`}
          >
            <Send className="h-3 w-3" /> <span className="hidden sm:inline">SMS</span>
          </button>
          <button
            onClick={onSchedule}
            disabled={!c.whatsapp || !waEnabled}
            title={!waEnabled ? "Fonctionnalité WhatsApp non activée — contactez votre administrateur" : (c.whatsapp ? "Planifier un message WhatsApp" : "Ajoutez d'abord un numéro WhatsApp")}
            className="inline-flex items-center gap-1 text-[11px] rounded bg-sawali-blue text-white px-2 py-1 hover:bg-sawali-blue-light disabled:opacity-40 disabled:cursor-not-allowed"
            data-testid={`contact-schedule-${c.id}`}
          >
            <CalendarClock className="h-3 w-3" /> <span className="hidden xl:inline">Mess. Program.</span>
          </button>
          <button
            onClick={onHistory}
            title="Voir les messages échangés"
            className="relative inline-flex items-center gap-1 text-[11px] rounded bg-slate-700 text-white px-2 py-1 hover:bg-slate-800"
            data-testid={`contact-history-${c.id}`}
          >
            <History className="h-3 w-3" /> <span className="hidden xl:inline">Hist. Mess.</span>
            {unreadCount > 0 && (
              <span
                className="absolute -top-1.5 -right-1.5 inline-flex items-center justify-center min-w-[16px] h-[16px] px-1 rounded-full bg-rose-500 text-white text-[9px] font-bold tabular-nums ring-1 ring-white"
                data-testid={`contact-history-unread-${c.id}`}
              >
                {unreadCount > 9 ? "9+" : unreadCount}
              </span>
            )}
          </button>
          <button
            onClick={onLiluvine}
            title="Historique Liluvine (templates/commandes matchés)"
            className="inline-flex items-center gap-1 text-[11px] rounded bg-fuchsia-600 text-white px-2 py-1 hover:bg-fuchsia-700"
            data-testid={`contact-liluvine-${c.id}`}
          >
            <Sparkles className="h-3 w-3" /> <span className="hidden 2xl:inline">Liluvine</span>
          </button>
          <button
            onClick={onEdit}
            className="text-[11px] text-slate-600 hover:underline px-1 hidden xl:inline"
            data-testid={`contact-edit-${c.id}`}
          >
            Éditer
          </button>
          <button
            onClick={onDelete}
            className="text-rose-500 hover:text-rose-700 p-1"
            data-testid={`contact-delete-${c.id}`}
            title="Supprimer"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </td>
    </tr>
  );
};

// --- Full edit modal ---
const ContactEditModal = ({ contact, companyOptions = [], onClose, onSaved }) => {
  const { user } = useAuth();
  const role = (user?.role || "").toLowerCase();
  // Photo upload is restricted to admin/superviseur/moderateur. Standard users
  // (client/tracked) see the photo but cannot replace or remove it.
  const canManagePhoto = ["admin", "superviseur", "moderateur"].includes(role);
  const [form, setForm] = useState(() => contact || {
    name: "", phone: "", whatsapp: "", email: "", company: "", notes: "", tags: [], shared: true,
  });
  const [saving, setSaving] = useState(false);
  const [tagInput, setTagInput] = useState("");
  const [uploadingPhoto, setUploadingPhoto] = useState(false);
  const photoInputRef = React.useRef(null);

  const uploadPhoto = async (file) => {
    if (!contact?.id) {
      toast.error("Enregistrez d'abord le contact, puis ajoutez sa photo.");
      return;
    }
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) { toast.error("Photo trop lourde (max 5 Mo)"); return; }
    if (!/^image\/(png|jpe?g|webp)$/i.test(file.type)) { toast.error("Format invalide (PNG/JPEG/WEBP)"); return; }
    setUploadingPhoto(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await apiClient.post(`/me/contacts/${contact.id}/photo`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setForm((prev) => ({ ...prev, photo_url: r.data?.photo_url || prev.photo_url }));
      toast.success("Photo de profil mise à jour");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec de l'envoi");
    } finally {
      setUploadingPhoto(false);
    }
  };

  const removePhoto = async () => {
    if (!contact?.id) return;
    if (!window.confirm("Retirer la photo de profil ?")) return;
    try {
      await apiClient.delete(`/me/contacts/${contact.id}/photo`);
      setForm((prev) => ({ ...prev, photo_url: null }));
      toast.success("Photo retirée");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  // Manually re-fetch the WA profile name from the most recent inbound. Meta
  // does NOT expose third-party photos via Cloud API → photo stays manual.
  const [wasyncing, setWasyncing] = useState(false);
  const syncWaProfile = async () => {
    if (!contact?.id) return;
    setWasyncing(true);
    try {
      const r = await apiClient.post(`/me/contacts/${contact.id}/wa-sync`);
      const d = r.data || {};
      if (!d.ok) {
        toast.message(safeText(d.message) || "Aucune information disponible.");
        return;
      }
      const cur = (d.current_name || "").trim();
      const sug = (d.suggested_name || "").trim();
      // Only prompt if the WA name differs from what's saved
      if (sug && sug !== cur) {
        if (window.confirm(`WhatsApp annonce ce contact comme :\n\n« ${sug} »\n\nLe nom enregistré est « ${cur || "(vide)"} ». Voulez-vous le remplacer ?`)) {
          setForm((prev) => ({ ...prev, name: sug, wa_profile_name: sug }));
          toast.success("Nom mis à jour. N'oubliez pas d'enregistrer.");
        } else {
          setForm((prev) => ({ ...prev, wa_profile_name: sug }));
          toast.message(`Profil WA stocké : ${sug}`);
        }
      } else if (sug) {
        toast.success(`Profil WA confirmé : ${sug}`);
      }
    } catch (err) {
      toast.error(safeText(err?.response?.data?.detail) || "Erreur");
    } finally {
      setWasyncing(false);
    }
  };

  const save = async () => {
    if (!form.name.trim()) { toast.error("Le nom est requis"); return; }
    setSaving(true);
    try {
      if (contact?.id) await apiClient.put(`/me/contacts/${contact.id}`, form);
      else await apiClient.post("/me/contacts", form);
      toast.success("Contact enregistré");
      onSaved();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setSaving(false); }
  };

  const addTag = () => {
    const t = tagInput.trim();
    if (!t) return;
    setForm({ ...form, tags: [...(form.tags || []), t] });
    setTagInput("");
  };
  const rmTag = (t) => setForm({ ...form, tags: (form.tags || []).filter((x) => x !== t) });

  // Company options include any pre-existing value of form.company that isn't in the roster
  const companyOpts = useMemo(() => {
    const opts = [...companyOptions];
    if (form.company && !opts.find((o) => o.value === form.company)) {
      opts.push({ value: form.company, code: "", label: `${form.company} (manuel)` });
    }
    return opts;
  }, [companyOptions, form.company]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      data-testid="contact-edit-modal"
    >
      <div className="w-full max-w-lg rounded-2xl bg-white shadow-2xl p-6 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-display font-bold">
            {contact?.id ? "Modifier le contact" : "Nouveau contact"}
          </h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900" data-testid="contact-edit-close">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Profile picture (à la WhatsApp) + WA Profile sync */}
        <div className="flex items-center gap-3 p-3 rounded-xl bg-slate-50 ring-1 ring-slate-200" data-testid="contact-photo-block">
          <ContactAvatar contact={form} size={56} />
          <div className="flex-1 min-w-0">
            <p className="text-xs font-semibold text-slate-700">Photo de profil</p>
            <p className="text-[11px] text-slate-500 leading-snug">
              {!canManagePhoto
                ? "Seuls les administrateurs ou superviseurs peuvent modifier la photo."
                : (form.photo_url ? "Cliquez sur « Remplacer » pour changer la photo." : "Ajoutez une photo qui s'affichera comme l'avatar WhatsApp dans le portail.")}
            </p>
            {form.unique_code && (
              <p className="text-[10px] mt-1 inline-flex items-center gap-1 text-slate-700 font-mono" title="Code Unique inaltérable du contact (généré une seule fois à la création)">
                <Lock className="h-2.5 w-2.5" /> Code : <strong>{form.unique_code}</strong>
              </p>
            )}
            {!contact?.id && (
              <p className="text-[10px] text-amber-700 mt-0.5">Enregistrez d'abord le contact, puis revenez pour ajouter sa photo.</p>
            )}
            {form.wa_profile_name && form.wa_profile_name !== form.name && (
              <p className="text-[10px] text-emerald-700 mt-1 inline-flex items-center gap-1" data-testid="wa-profile-hint">
                <MessageCircle className="h-2.5 w-2.5" /> WhatsApp : <strong>{form.wa_profile_name}</strong>
              </p>
            )}
          </div>
          <input
            ref={photoInputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="hidden"
            onChange={(e) => uploadPhoto(e.target.files?.[0])}
            data-testid="contact-photo-input"
          />
          <div className="flex flex-col gap-1.5">
            <button
              type="button"
              onClick={() => photoInputRef.current?.click()}
              disabled={!contact?.id || uploadingPhoto || !canManagePhoto}
              className="inline-flex items-center justify-center gap-1 text-[11px] rounded bg-sawali-blue text-white px-2.5 py-1.5 hover:bg-sawali-blue-light disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="contact-photo-upload-btn"
              title={!canManagePhoto ? "Réservé aux administrateurs/superviseurs" : (!contact?.id ? "Enregistrez d'abord le contact" : (form.photo_url ? "Remplacer la photo" : "Ajouter une photo"))}
            >
              <Upload className="h-3 w-3" />
              {uploadingPhoto ? "Envoi…" : (form.photo_url ? "Remplacer" : "Ajouter")}
            </button>
            <button
              type="button"
              onClick={syncWaProfile}
              disabled={!contact?.id || wasyncing}
              className="inline-flex items-center justify-center gap-1 text-[11px] rounded ring-1 ring-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100 px-2.5 py-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="contact-wa-sync-btn"
              title="Lit le nom de profil WhatsApp depuis le dernier message reçu (Meta n'expose pas la photo)"
            >
              <RefreshCw className={`h-3 w-3 ${wasyncing ? "animate-spin" : ""}`} />
              {wasyncing ? "…" : "Synchro WA"}
            </button>
            {form.photo_url && canManagePhoto && (
              <button
                type="button"
                onClick={removePhoto}
                className="inline-flex items-center justify-center gap-1 text-[11px] rounded ring-1 ring-rose-200 bg-white text-rose-700 hover:bg-rose-50 px-2.5 py-1.5"
                data-testid="contact-photo-remove-btn"
              >
                <Trash2 className="h-3 w-3" /> Retirer
              </button>
            )}
          </div>
        </div>

        <div className="grid sm:grid-cols-2 gap-3">
          <Input label="Nom *" value={form.name} onChange={(v) => setForm({ ...form, name: v })} testid="contact-field-name" />
          <div>
            <label className="block text-xs font-semibold mb-1">Société (client)</label>
            <input
              list="contact-company-options"
              value={form.company || ""}
              onChange={(e) => setForm({ ...form, company: e.target.value })}
              placeholder="Tapez ou sélectionnez…"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              data-testid="contact-field-company"
              autoComplete="off"
            />
            <datalist id="contact-company-options">
              {companyOpts.map((o) => <option key={o.label} value={o.value}>{o.label}</option>)}
            </datalist>
            <p className="text-[10px] text-slate-400 mt-0.5">Tapez quelques lettres pour filtrer la liste, ou saisissez un nouveau nom.</p>
          </div>
          <Input label="Téléphone (E.164)" value={form.phone} onChange={(v) => setForm({ ...form, phone: v })} placeholder={phonePlaceholder()} testid="contact-field-phone" />
          <Input label="WhatsApp (E.164)" value={form.whatsapp} onChange={(v) => setForm({ ...form, whatsapp: v })} placeholder={phonePlaceholder()} testid="contact-field-whatsapp" />
          <Input label="Email" value={form.email} onChange={(v) => setForm({ ...form, email: v })} testid="contact-field-email" />
          {/* Iter29 — Plus de toggle "partager" : tous les contacts sont
              désormais visibles et modifiables par tous les utilisateurs du
              même client (modèle collaboratif, identique à la Bibliothèque de
              Médias). On laisse un encart explicatif à la place. */}
          <div className="mt-6 p-2.5 rounded-lg bg-emerald-50 ring-1 ring-emerald-200 text-[11px] text-emerald-900 inline-flex items-start gap-2" data-testid="contact-shared-notice">
            <Share2 className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            <span>
              <strong>Visible par toute l'équipe.</strong> Ce contact sera accessible et modifiable par tous les utilisateurs de votre client.
              {form.last_edited_by_label && form.last_edited_by_label !== form.owner_label && (
                <span className="block text-[10px] text-slate-500 mt-0.5">
                  Dernière modification par {form.last_edited_by_label}
                </span>
              )}
            </span>
          </div>
        </div>
        <div>
          <label className="block text-xs font-semibold mb-1">Notes</label>
          <textarea
            value={form.notes || ""}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
            rows={2}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            data-testid="contact-field-notes"
          />
        </div>
        <div>
          <label className="block text-xs font-semibold mb-1">Catégories / Tags</label>
          <div className="flex flex-wrap gap-1 mb-2">
            {(form.tags || []).map((t) => (
              <span key={t} className="text-xs bg-slate-100 px-2 py-0.5 rounded inline-flex items-center gap-1">
                {t}
                <button onClick={() => rmTag(t)}><X className="h-3 w-3" /></button>
              </span>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTag(); } }}
              placeholder="Fournisseur, Client, Technique…"
              className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm"
              data-testid="contact-field-tag-input"
            />
            <button onClick={addTag} className="text-xs rounded bg-slate-900 text-white px-3">Ajouter</button>
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="text-sm rounded-lg bg-slate-100 hover:bg-slate-200 px-4 py-2">Annuler</button>
          <button
            onClick={save}
            disabled={saving}
            className="text-sm rounded-lg bg-sawali-blue hover:bg-sawali-blue-light text-white px-4 py-2 disabled:opacity-50"
            data-testid="contact-edit-save"
          >
            {saving ? "Enregistrement…" : "Enregistrer"}
          </button>
        </div>
      </div>
    </div>
  );
};

// --- WhatsApp send modal (supports HEADER text/media + BODY variables + URL button params) ---
const WhatsAppModal = ({ contact, onClose, onSent, userRole }) => {
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [templateName, setTemplateName] = useState("");
  const [language, setLanguage] = useState("fr");
  const [tokens, setTokens] = useState([]);
  const [headerText, setHeaderText] = useState("");
  const [headerMedia, setHeaderMedia] = useState(null); // { link, kind, filename }
  const [headerUploading, setHeaderUploading] = useState(false);
  const [bodyVars, setBodyVars] = useState([]);
  const [buttonVars, setButtonVars] = useState([]); // [[...], [...]]
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState(null);
  const [configured, setConfigured] = useState(true);

  useEffect(() => {
    Promise.all([
      apiClient.get("/me/whatsapp/templates"),
      apiClient.get("/me/messaging/variable-tokens").catch(() => ({ data: { tokens: [] } })),
    ]).then(([tplRes, tokRes]) => {
      const items = tplRes.data?.items || [];
      setTemplates(items);
      setTokens(tokRes.data?.tokens || []);
      setConfigured(!!tplRes.data?.configured);
      if (items[0]) {
        setTemplateName(items[0].name);
        setLanguage(items[0].language || "fr");
      }
    }).catch(() => {}).finally(() => setLoading(false));
  }, []);

  const selectedTemplate = useMemo(
    () => templates.find((t) => t.name === templateName),
    [templates, templateName],
  );
  const parsed = useMemo(() => parseTemplate(selectedTemplate), [selectedTemplate]);

  // Reset inputs whenever the template selection changes
  useEffect(() => {
    setHeaderText("");
    setHeaderMedia(null);
    setBodyVars(Array(parsed.body.varCount).fill(""));
    setButtonVars((parsed.buttons || []).map((b) => Array(b.urlVarCount || 0).fill("")));
    setResult(null);
  }, [templateName, parsed.body.varCount, parsed.buttons]);

  const uploadHeader = async (file, existingMedia = null) => {
    // If user picked an existing media from the shared library, just use it.
    if (existingMedia?.public_url) {
      setHeaderMedia({ link: existingMedia.public_url, kind: existingMedia.kind, filename: existingMedia.filename });
      toast.success("Média sélectionné depuis la bibliothèque");
      return;
    }
    if (!file) return;
    setHeaderUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("label", file.name || "");
      // Save in the shared client library so any other user can reuse it.
      const r = await apiClient.post("/me/media-library", fd, { headers: { "Content-Type": "multipart/form-data" } });
      const link = r.data?.public_url;
      if (!link) throw new Error("URL publique manquante");
      setHeaderMedia({ link, kind: r.data?.kind || "document", filename: r.data?.filename || file.name });
      toast.success("Fichier ajouté à la bibliothèque et prêt pour l'en-tête");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec de l'upload");
    } finally {
      setHeaderUploading(false);
    }
  };

  const send = async () => {
    if (!templateName) { toast.error("Sélectionnez un template"); return; }
    const values = { headerText, headerMedia, bodyVars, buttonVars };
    const v = validateTemplateValues(parsed, values);
    if (!v.ok) { toast.error(v.message); return; }
    setSending(true); setResult(null);
    try {
      const components = buildComponentsPayload(parsed, values);
      const r = await apiClient.post("/me/whatsapp/send", {
        to: contact.whatsapp,
        template_name: templateName,
        language_code: language,
        components: components.length > 0 ? components : null,
        contact_id: contact.id,
        // 2026-02 (#4) — Send the rendered preview so the messaging center
        // can show the actual delivered content under the template name.
        template_rendered_body: previewBody || null,
      });
      setResult(r.data);
      if (r.data?.ok) {
        toast.success("Message WhatsApp envoyé");
        if (onSent) onSent();
      } else {
        toast.error(r.data?.error || "Échec d'envoi");
      }
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setSending(false); }
  };

  const previewBody = useMemo(
    () => renderPreview(parsed, { bodyVars }, tokens, contact),
    [parsed, bodyVars, tokens, contact],
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      data-testid="whatsapp-modal"
    >
      <div className="w-full max-w-2xl rounded-2xl bg-white shadow-2xl flex flex-col max-h-[92vh]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200">
          <h2 className="text-lg font-display font-bold inline-flex items-center gap-2">
            <MessageCircle className="h-5 w-5 text-emerald-600" /> Envoyer un WhatsApp
          </h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900"><X className="h-4 w-4" /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          <p className="text-sm text-slate-600">
            À : <strong>{contact.name}</strong>
            <code className="text-xs bg-slate-100 px-1.5 py-0.5 rounded ml-1">{contact.whatsapp}</code>
          </p>
          {loading ? (
            <p className="text-sm text-slate-500">Chargement des templates…</p>
          ) : !configured ? (
            <div className="rounded-lg bg-amber-50 ring-1 ring-amber-200 p-3 text-xs text-amber-900">
              WhatsApp Business API non configurée. Contactez l'administrateur.
            </div>
          ) : templates.length === 0 ? (
            <div className="rounded-lg bg-amber-50 ring-1 ring-amber-200 p-3 text-xs text-amber-900">
              Aucun template disponible. L'administrateur doit créer/activer des templates.
            </div>
          ) : (
            <>
              <div className="grid sm:grid-cols-[1fr_120px] gap-3">
                <div>
                  <label className="text-xs font-semibold block mb-1">Template</label>
                  <select
                    value={templateName}
                    onChange={(e) => {
                      setTemplateName(e.target.value);
                      const t = templates.find((x) => x.name === e.target.value);
                      if (t?.language) setLanguage(t.language);
                    }}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    data-testid="wa-template-select"
                  >
                    {templates.map((t) => (
                      <option key={`${t.name}_${t.language}`} value={t.name}>
                        {t.name} ({t.language}){t.note_description ? ` — ${t.note_description.slice(0, 80)}` : ""}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs font-semibold block mb-1">Langue</label>
                  <input
                    value={language}
                    onChange={(e) => setLanguage(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    data-testid="wa-language-input"
                  />
                </div>
              </div>

              {/* Admin-maintained description */}
              {selectedTemplate?.note_description && (
                <div className="rounded-lg bg-sky-50 ring-1 ring-sky-200 p-3 text-xs text-sky-900 flex items-start gap-2" data-testid="wa-template-note">
                  <Info className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                  <span>{selectedTemplate.note_description}</span>
                </div>
              )}

              {/* HEADER */}
              {parsed.header && (
                <HeaderBlock
                  header={parsed.header}
                  headerText={headerText}
                  setHeaderText={setHeaderText}
                  headerMedia={headerMedia}
                  clearMedia={() => setHeaderMedia(null)}
                  uploadHeader={uploadHeader}
                  uploading={headerUploading}
                  tokens={tokens}
                />
              )}

              {/* BODY */}
              {parsed.body.text && (
                <div className="rounded-lg bg-slate-50 ring-1 ring-slate-200 p-3 text-xs text-slate-700 whitespace-pre-wrap">
                  <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Corps du template Meta</p>
                  {parsed.body.text}
                </div>
              )}

              {parsed.body.varCount > 0 && (
                <>
                  <PaymentLinkInserter
                    paymentsEnabled={!!(contact?._payments_enabled ?? true)}
                    bodyVars={bodyVars}
                    setBodyVars={setBodyVars}
                  />
                  <VarGrid
                    label={`Variables du corps (${parsed.body.varCount})`}
                    values={bodyVars}
                    onChange={setBodyVars}
                    testPrefix="wa-variable"
                    tokens={tokens}
                  />
                </>
              )}

              {/* BUTTONS with dynamic URLs */}
              {(parsed.buttons || []).some((b) => b.type === "URL" && b.urlVarCount > 0) && (
                <div className="space-y-3">
                  <p className="text-xs font-semibold text-slate-700">Boutons dynamiques</p>
                  {parsed.buttons.map((btn, bi) => (
                    btn.type === "URL" && btn.urlVarCount > 0 ? (
                      <div key={bi} className="rounded-lg ring-1 ring-slate-200 bg-white p-3 space-y-2" data-testid={`wa-button-row-${bi}`}>
                        <p className="text-[11px] text-slate-500">
                          Bouton : <strong className="text-slate-800">{btn.text}</strong>
                          <code className="ml-2 bg-slate-100 px-1 rounded text-[10px]">{btn.url}</code>
                        </p>
                        <VarGrid
                          label=""
                          values={buttonVars[bi] || []}
                          onChange={(arr) => setButtonVars((prev) => {
                            const n = prev.map((x) => [...(x || [])]);
                            n[bi] = arr;
                            return n;
                          })}
                          testPrefix={`wa-button-${bi}-var`}
                          tokens={tokens}
                        />
                      </div>
                    ) : null
                  ))}
                </div>
              )}

              {previewBody && (
                <div className="rounded-lg ring-1 ring-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900" data-testid="wa-preview">
                  <p className="text-[10px] uppercase tracking-wider text-emerald-700 mb-1">Aperçu du corps pour {contact.name}</p>
                  <p className="whitespace-pre-line">{previewBody}</p>
                </div>
              )}
            </>
          )}
          {result && (
            <div
              className={`rounded-lg ring-1 p-3 text-xs ${
                result.ok ? "bg-emerald-50 ring-emerald-200 text-emerald-900" : "bg-rose-50 ring-rose-300 text-rose-900"
              }`}
              data-testid="wa-result"
            >
              {result.ok ? (
                <><strong>Envoyé !</strong> ID message : <code>{result.message_id}</code></>
              ) : (
                <><strong>Échec :</strong> {result.error || "Erreur inconnue"} (HTTP {result.http_status || "—"})</>
              )}
            </div>
          )}
          {/* Iter43-fix24az-d — Quick contact-group toggler (admin/superviseur/modérateur) */}
          <ContactGroupChips contact={contact} userRole={userRole} />
        </div>
        <div className="flex justify-end gap-2 px-5 py-3 border-t border-slate-200">
          <button onClick={onClose} className="text-sm rounded-lg bg-slate-100 hover:bg-slate-200 px-4 py-2">Fermer</button>
          <button
            onClick={send}
            disabled={sending || templates.length === 0 || !configured}
            className="inline-flex items-center gap-1.5 text-sm rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 disabled:opacity-50"
            data-testid="wa-send-btn"
          >
            <Send className="h-4 w-4" /> {sending ? "Envoi…" : "Envoyer"}
          </button>
        </div>
      </div>
    </div>
  );
};

// --- HEADER block: text var OR media upload (with shared media library) ---
const HeaderBlock = ({ header, headerText, setHeaderText, headerMedia, clearMedia, uploadHeader, uploading, tokens }) => {
  const fmt = header.format;
  const [showLibrary, setShowLibrary] = useState(false);
  const [library, setLibrary] = useState([]);
  const [libLoading, setLibLoading] = useState(false);

  useEffect(() => {
    if (!showLibrary) return;
    setLibLoading(true);
    apiClient.get("/me/media-library")
      .then((r) => setLibrary(r.data || []))
      .catch(() => {})
      .finally(() => setLibLoading(false));
  }, [showLibrary]);

  if (fmt === "TEXT" && header.varCount > 0) {
    return (
      <div className="rounded-lg ring-1 ring-slate-200 bg-white p-3 space-y-2" data-testid="wa-header-text-block">
        <p className="text-xs font-semibold text-slate-700">En-tête (texte)</p>
        <p className="text-[11px] text-slate-500 whitespace-pre-wrap bg-slate-50 rounded px-2 py-1">{header.text}</p>
        <div className="flex gap-2">
          <input
            value={headerText}
            onChange={(e) => setHeaderText(e.target.value)}
            placeholder="Valeur pour la variable de l'en-tête"
            className="flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-mono"
            data-testid="wa-header-text-input"
          />
          <select
            onChange={(e) => {
              const tk = e.target.value;
              if (tk) { setHeaderText((prev) => (prev || "") + tk); e.target.value = ""; }
            }}
            className="rounded-lg border border-slate-300 bg-white px-2 py-2 text-[11px]"
            defaultValue=""
            title="Insérer un token dynamique"
            data-testid="wa-header-text-token-picker"
          >
            <option value="">+ Token…</option>
            {(tokens || []).map((t) => <option key={t.token} value={t.token}>{t.label}</option>)}
          </select>
        </div>
      </div>
    );
  }
  if (["IMAGE", "DOCUMENT", "VIDEO"].includes(fmt)) {
    const Ico = fmt === "IMAGE" ? ImageIcon : fmt === "VIDEO" ? Video : FileTextIcon;
    const accept = fmt === "IMAGE" ? "image/*" : fmt === "VIDEO" ? "video/*" : ".pdf,application/pdf";
    const wantedKind = fmt === "IMAGE" ? "image" : fmt === "VIDEO" ? "video" : "document";
    const filtered = (library || []).filter((m) => m.kind === wantedKind);
    return (
      <div className="rounded-lg ring-1 ring-slate-200 bg-white p-3 space-y-2" data-testid={`wa-header-${fmt.toLowerCase()}-block`}>
        <p className="text-xs font-semibold text-slate-700 inline-flex items-center gap-1.5">
          <Ico className="h-3.5 w-3.5" /> En-tête ({fmt === "IMAGE" ? "image" : fmt === "VIDEO" ? "vidéo" : "document PDF"})
        </p>
        {headerMedia?.link ? (
          <div className="flex items-center gap-2">
            {fmt === "IMAGE" && <img src={headerMedia.link} alt="" className="h-16 w-16 object-cover rounded" />}
            <div className="flex-1 text-xs">
              <p className="font-mono break-all text-slate-600">{headerMedia.filename}</p>
              <a href={headerMedia.link} target="_blank" rel="noreferrer" className="text-[11px] text-sawali-blue hover:underline">Ouvrir</a>
            </div>
            <button onClick={clearMedia} className="text-xs text-rose-600 hover:underline" data-testid="wa-header-media-clear">Changer</button>
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            <label className="inline-flex items-center gap-2 text-xs cursor-pointer rounded bg-slate-100 hover:bg-slate-200 px-3 py-2">
              <Upload className="h-3.5 w-3.5" /> {uploading ? "Upload…" : "Uploader nouveau"}
              <input type="file" accept={accept} onChange={(e) => uploadHeader(e.target.files?.[0])} className="hidden" data-testid="wa-header-media-input" />
            </label>
            <button
              type="button"
              onClick={() => setShowLibrary((v) => !v)}
              className="inline-flex items-center gap-2 text-xs rounded ring-1 ring-slate-300 bg-white hover:bg-slate-50 px-3 py-2"
              data-testid="wa-header-media-library-toggle"
            >
              <ImageIcon className="h-3.5 w-3.5" /> {showLibrary ? "Masquer la bibliothèque" : "Choisir dans la bibliothèque"}
            </button>
          </div>
        )}
        {!headerMedia?.link && showLibrary && (
          <div className="rounded ring-1 ring-slate-200 bg-slate-50 p-2 max-h-56 overflow-y-auto" data-testid="wa-header-media-library">
            {libLoading && <p className="text-[11px] text-slate-500 italic">Chargement…</p>}
            {!libLoading && filtered.length === 0 && (
              <p className="text-[11px] text-slate-500 italic">Aucun {wantedKind} dans la bibliothèque. Uploadez ci-dessus.</p>
            )}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {filtered.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => uploadHeader(null, m)}
                  className="rounded border border-slate-200 bg-white hover:border-sawali-blue p-1.5 text-left"
                  data-testid={`wa-header-media-pick-${m.id}`}
                >
                  {m.kind === "image" ? (
                    <img src={m.public_url} alt="" className="h-16 w-full object-cover rounded" />
                  ) : (
                    <div className="h-16 flex items-center justify-center bg-slate-100 rounded text-slate-500">
                      {m.kind === "video" ? <Video className="h-6 w-6" /> : <FileTextIcon className="h-6 w-6" />}
                    </div>
                  )}
                  <p className="text-[10px] mt-1 truncate">{m.label || m.filename}</p>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }
  return null;
};

// --- Reusable variable grid (body or button) ---
const VarGrid = ({ label, values, onChange, testPrefix, tokens }) => {
  const update = (i, v) => {
    const n = [...values]; n[i] = v; onChange(n);
  };
  const append = (i, token) => {
    const n = [...values]; n[i] = (n[i] || "") + token; onChange(n);
  };
  return (
    <div className="space-y-2">
      {label && <p className="text-xs font-semibold text-slate-700">{label}</p>}
      {(values || []).map((_, i) => (
        <div key={i} className="grid grid-cols-[64px_1fr_auto] gap-2 items-center" data-testid={`${testPrefix}-row-${i + 1}`}>
          <label className="text-[11px] uppercase tracking-wider text-slate-500 font-mono text-center bg-slate-100 rounded py-2">
            {`{{${i + 1}}}`}
          </label>
          <input
            value={values[i] || ""}
            onChange={(e) => update(i, e.target.value)}
            placeholder="Texte ou tokens"
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-mono"
            data-testid={`${testPrefix}-input-${i + 1}`}
          />
          <select
            onChange={(e) => {
              const tk = e.target.value;
              if (tk) { append(i, tk); e.target.value = ""; }
            }}
            className="rounded-lg border border-slate-300 bg-white px-2 py-2 text-[11px]"
            defaultValue=""
            title="Insérer un token dynamique"
            data-testid={`${testPrefix}-token-picker-${i + 1}`}
          >
            <option value="">+ Token…</option>
            {(tokens || []).map((t) => (
              <option key={t.token} value={t.token}>{t.label}</option>
            ))}
          </select>
        </div>
      ))}
    </div>
  );
};

// --- Conversation history modal ---
const ConversationModal = ({ contact, onClose, onMessagesRead }) => {
  const { user } = useAuth();
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState({ messages: [], can_send_text: false, last_inbound_at: null, window_expires_at: null });
  const [text, setText] = useState("");
  // Iter38r-fix4 — Share-from-library modal (média / formulaire / catalogue)
  const [shareModal, setShareModal] = useState({ open: false, tab: "media", items: [], loading: false, query: "" });
  const [sending, setSending] = useState(false);
  // Iter35l — Media attach state. `pendingFile` holds the local File picked by
  // the user but not yet uploaded. We show a small preview row above the text
  // composer and let them add a caption before pressing Envoyer.
  const [pendingFile, setPendingFile] = useState(null); // { file, kind, previewUrl }
  // Iter37h — Voice recording state (MediaRecorder)
  const [recState, setRecState] = useState("idle"); // idle | recording | transcribing
  const [recElapsed, setRecElapsed] = useState(0);
  const recRef = React.useRef(null); // { mediaRecorder, chunks, stream, timerId }
  // Iter37h — Reply context (quoting a message)
  const [replyTo, setReplyTo] = useState(null); // { id, body, direction, from, message_id }
  const fileInputRef = React.useRef(null);
  // Iter34o — Auto-scroll to the latest message so the composer is always
  // anchored on the last exchange (matches WhatsApp/Messenger UX).
  const scrollEndRef = React.useRef(null);
  const scrollContainerRef = React.useRef(null);

  // Iter43-fix24az-y (2026-07-22) — Split the conversation window into 2 tabs
  // so the "Groupes de contact" panel doesn't eat the entire viewport on
  // small screens (mobile/tablet). Default = discussion (everything except
  // groups). "Groupes (n)" = only the ContactGroupChips panel.
  const [convTab, setConvTab] = useState("discussion");
  const [groupCount, setGroupCount] = useState(0);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get(`/me/contacts/${contact.id}/messages`);
      setData(r.data || { messages: [] });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setLoading(false);
    }
  };

  const markRead = async () => {
    try {
      await apiClient.post(`/me/contacts/${contact.id}/messages/mark-read`);
      onMessagesRead && onMessagesRead();
    } catch { /* noop */ }
  };

  useEffect(() => {
    load();
    markRead();
    /* eslint-disable-next-line */
  }, [contact.id]);

  const sendFreeText = async () => {
    const body = (text || "").trim();
    if (!body && !pendingFile) { toast.error("Le message est vide"); return; }
    if (!contact.whatsapp) { toast.error("Numéro WhatsApp manquant"); return; }
    // Iter37h — Resolve the reply target's WhatsApp message id (only inbound msgs have a wa_message_id we can quote)
    const replyMid = replyTo?.message_id || replyTo?.wa_message_id || null;
    setSending(true);
    try {
      let r;
      if (pendingFile) {
        const fd = new FormData();
        fd.append("to", contact.whatsapp);
        fd.append("contact_id", contact.id);
        if (body) fd.append("caption", body);
        fd.append("file", pendingFile.file);
        if (replyMid) fd.append("reply_to_message_id", replyMid);
        r = await apiClient.post("/me/whatsapp/send-media", fd, {
          headers: { "Content-Type": "multipart/form-data" },
        });
      } else {
        r = await apiClient.post("/me/whatsapp/send-text", {
          to: contact.whatsapp,
          text: body,
          contact_id: contact.id,
          reply_to_message_id: replyMid || undefined,
        });
      }
      if (r.data?.ok) {
        toast.success(pendingFile ? "Média envoyé" : "Message envoyé");
        setText("");
        clearPendingFile();
        setReplyTo(null);  // Iter37h — clear quote after send
        await load();
      } else {
        toast.error(r.data?.error || "Échec d'envoi");
      }
    } catch (err) {
      const detail = err?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "Erreur d'envoi");
    } finally {
      setSending(false);
    }
  };

  // Iter37h — Voice recording: capture mic, upload+transcribe, then EITHER
  // send the transcript as text OR send the audio file as a voice note.
  const startRecording = async () => {
    if (recState !== "idle") return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeCandidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"];
      const mime = mimeCandidates.find((m) => window.MediaRecorder && MediaRecorder.isTypeSupported(m)) || "";
      const mr = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      const chunks = [];
      mr.ondataavailable = (e) => { if (e.data && e.data.size > 0) chunks.push(e.data); };
      mr.start();
      setRecState("recording");
      setRecElapsed(0);
      const t0 = Date.now();
      const timerId = setInterval(() => setRecElapsed(Math.floor((Date.now() - t0) / 1000)), 250);
      recRef.current = { mediaRecorder: mr, chunks, stream, timerId };
    } catch (err) {
      toast.error("Microphone refusé ou indisponible");
      setRecState("idle");
    }
  };

  const stopRecording = async ({ asText }) => {
    const ref = recRef.current;
    if (!ref || recState !== "recording") return;
    const { mediaRecorder, chunks, stream, timerId } = ref;
    setRecState("transcribing");
    clearInterval(timerId);
    await new Promise((resolve) => {
      mediaRecorder.onstop = () => resolve();
      try { mediaRecorder.stop(); } catch { resolve(); }
    });
    try { stream.getTracks().forEach((t) => t.stop()); } catch { /* noop */ }
    const blob = new Blob(chunks, { type: mediaRecorder.mimeType || "audio/webm" });
    recRef.current = null;
    if (blob.size < 600) {
      toast.error("Note vocale trop courte");
      setRecState("idle");
      return;
    }
    try {
      if (asText) {
        // Transcribe via the shared chat endpoint, then push as a text message
        const fd = new FormData();
        const ext = (blob.type.includes("mp4") ? "mp4" : (blob.type.includes("ogg") ? "ogg" : "webm"));
        fd.append("file", new File([blob], `note.${ext}`, { type: blob.type }));
        const tr = await apiClient.post("/me/chat/transcribe", fd, {
          headers: { "Content-Type": "multipart/form-data" },
        });
        const transcript = (tr.data?.text || "").trim();
        if (!transcript) {
          toast.error("Transcription vide");
          setRecState("idle");
          return;
        }
        // Drop into the textarea so the user can review/edit before pressing Envoyer
        setText((prev) => (prev ? `${prev}\n${transcript}` : transcript));
        toast.success("Note vocale transcrite — vérifiez avant d'envoyer");
      } else {
        // Stage as a pending audio file → user can add a caption + send
        const ext = (blob.type.includes("mp4") ? "mp4" : (blob.type.includes("ogg") ? "ogg" : "webm"));
        const f = new File([blob], `note-vocale.${ext}`, { type: blob.type });
        setPendingFile({ file: f, kind: "audio", previewUrl: null });
        toast.success("Note vocale prête — cliquez Envoyer");
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec de la transcription");
    } finally {
      setRecState("idle");
    }
  };

  const cancelRecording = () => {
    const ref = recRef.current;
    if (!ref) { setRecState("idle"); return; }
    try { ref.mediaRecorder.stop(); } catch { /* noop */ }
    try { ref.stream.getTracks().forEach((t) => t.stop()); } catch { /* noop */ }
    if (ref.timerId) clearInterval(ref.timerId);
    recRef.current = null;
    setRecState("idle");
    setRecElapsed(0);
  };


  const onPickFile = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 16 * 1024 * 1024) {
      toast.error("Fichier trop volumineux (max 16 Mo)");
      e.target.value = "";
      return;
    }
    const ct = (f.type || "").toLowerCase();
    let kind = "document";
    if (ct.startsWith("image/")) kind = "image";
    else if (ct.startsWith("audio/")) kind = "audio";
    else if (ct.startsWith("video/")) kind = "video";
    const previewUrl = kind === "image" ? URL.createObjectURL(f) : null;
    setPendingFile({ file: f, kind, previewUrl });
    e.target.value = ""; // allow re-picking the same file
  };

  const clearPendingFile = () => {
    if (pendingFile?.previewUrl) {
      try { URL.revokeObjectURL(pendingFile.previewUrl); } catch { /* noop */ }
    }
    setPendingFile(null);
  };

  // Clean up object URL on unmount
  useEffect(() => () => {
    if (pendingFile?.previewUrl) {
      try { URL.revokeObjectURL(pendingFile.previewUrl); } catch { /* noop */ }
    }
  }, [pendingFile?.previewUrl]);

  const messages = data.messages || [];
  const canSendText = !!data.can_send_text;
  const windowExpires = data.window_expires_at;

  // Iter35o — Active (non-closed) ticket for this contact, if any.
  // Drives the small ticket bar shown above the chat header.
  const [activeTicket, setActiveTicket] = useState(null);
  const loadActiveTicket = React.useCallback(async () => {
    try {
      const r = await apiClient.get(`/me/contacts/${contact.id}/active-ticket`);
      setActiveTicket(r.data?.ticket || null);
    } catch { /* noop */ }
  }, [contact.id]);
  useEffect(() => { loadActiveTicket(); }, [loadActiveTicket]);

  // Iter36k — Ticket creation modal state (replaces window.prompt chain).
  // Forces the user to EXPLICITLY pick a "client lié" from a dropdown.
  const [ticketModalOpen, setTicketModalOpen] = useState(false);
  const [ticketClientId, setTicketClientId] = useState("");
  const [ticketMotif, setTicketMotif] = useState("");
  const [ticketClients, setTicketClients] = useState([]);
  const [ticketTemplates, setTicketTemplates] = useState([]);
  const [ticketSubmitting, setTicketSubmitting] = useState(false);
  // Iter38r-fix3 — Archive (corbeille) confirmation modal with the
  // "also unlink contact ↔ ticket" checkbox, replacing window.confirm.
  const [archiveModal, setArchiveModal] = useState({ open: false, ticket: null, alsoUnlink: false, busy: false });

  // Iter38r-fix4 — Open the share-from-library modal and lazy-load the items
  // for the selected tab. Each tab queries a different endpoint:
  //   media     → /me/media-library
  //   form      → /me/forms (only public OR mine)
  //   catalog   → /public/products (digest=light)
  const openShareModal = async (tab = "media") => {
    setShareModal({ open: true, tab, items: [], loading: true, query: "" });
    await loadShareTab(tab);
  };

  const loadShareTab = async (tab) => {
    setShareModal((m) => ({ ...m, tab, loading: true, items: [] }));
    try {
      let items = [];
      if (tab === "media") {
        const r = await apiClient.get("/me/media-library");
        items = (r.data || []).map((it) => ({
          id: it.id,
          label: it.label || it.file_name || "Document",
          url: it.public_url,
          subtitle: it.file_name,
          icon: "media",
        }));
      } else if (tab === "form") {
        const r = await apiClient.get("/me/forms");
        items = (r.data || [])
          .filter((f) => f.is_public || f.is_mine)
          .map((f) => ({
            id: f.id,
            label: f.title || f.number,
            url: `${window.location.origin}/f/${f.id}`,
            subtitle: f.number + (f.is_public ? " · Public" : " · Privé"),
            icon: "form",
          }));
      } else if (tab === "catalog") {
        const r = await apiClient.get("/public/products");
        const cats = r.data?.categories || [];
        cats.forEach((cat) => {
          (cat.products || []).forEach((p) => {
            items.push({
              id: p.id,
              label: p.label || p.name,
              url: `${window.location.origin}/catalogue?product_id=${p.id}`,
              subtitle: `${cat.name || "Sans cat."} · ${(p.price_xof || 0).toLocaleString("fr-FR")} XOF`,
              icon: "catalog",
            });
          });
        });
      }
      setShareModal((m) => ({ ...m, items, loading: false }));
    } catch (err) {
      toast.error("Impossible de charger la liste");
      setShareModal((m) => ({ ...m, loading: false }));
    }
  };

  const pickShareItem = (item) => {
    if (!item?.url) {
      toast.error("Lien indisponible pour cet élément");
      return;
    }
    // Inject a friendly markdown-like message into the textarea
    const prefix = text.trim() ? text.trim() + "\n\n" : "";
    const blurb = (() => {
      if (item.icon === "form") return `📝 Veuillez remplir ce formulaire : ${item.label}\n${item.url}`;
      if (item.icon === "catalog") return `🛍️ Découvrez ce produit : ${item.label}\n${item.url}`;
      return `📎 ${item.label}\n${item.url}`;
    })();
    setText(prefix + blurb);
    setShareModal({ open: false, tab: "media", items: [], loading: false, query: "" });
    toast.success("Lien inséré dans le message — vous pouvez ajouter du texte avant d'envoyer");
  };

  const submitArchive = async () => {
    const tk = archiveModal.ticket;
    if (!tk) return;
    setArchiveModal((m) => ({ ...m, busy: true }));
    try {
      const r = await apiClient.post(`/me/tickets/${tk.id}/archive`, { also_unlink: archiveModal.alsoUnlink });
      const unlinked = r.data?.unlinked;
      toast.success(
        `Ticket ${tk.number} mis à la corbeille` + (unlinked ? " (lien contact retiré)" : "")
      );
      setArchiveModal({ open: false, ticket: null, alsoUnlink: false, busy: false });
      await loadActiveTicket();
    } catch (err) {
      const status = err?.response?.status;
      const detail = err?.response?.data?.detail || "Erreur";
      // 404 = ticket already gone (often the orphan case). If the user
      // checked "also unlink", we still want the chat window unblocked,
      // so we just close the modal and reload — the active-ticket lookup
      // will return null and the "Generate ticket" CTA will reappear.
      if (status === 404) {
        toast.info(`Ticket déjà supprimé du système — fenêtre rafraîchie.`);
        setArchiveModal({ open: false, ticket: null, alsoUnlink: false, busy: false });
        await loadActiveTicket();
      } else {
        toast.error(detail);
        setArchiveModal((m) => ({ ...m, busy: false }));
      }
    }
  };

  const openTicket = async () => {
    // Reset + open modal, then load clients + templates in parallel
    setTicketClientId("");
    setTicketMotif("");
    setTicketModalOpen(true);
    try {
      const [rc, rt] = await Promise.all([
        apiClient.get("/me/clients"),
        apiClient.get("/me/ticket-motif-templates").catch(() => ({ data: [] })),
      ]);
      setTicketClients(rc.data || []);
      setTicketTemplates(rt.data || []);
    } catch (err) {
      toast.error("Impossible de charger la liste des clients");
    }
  };

  const submitTicket = async (forceRelease = false) => {
    const trimmed = (ticketMotif || "").trim();
    if (!ticketClientId) { toast.error("Sélectionnez le client lié"); return; }
    if (!trimmed) { toast.error("Le motif est obligatoire"); return; }
    if (trimmed.length > 200) { toast.error("Motif trop long (max 200 caractères)"); return; }
    setTicketSubmitting(true);
    try {
      const r = await apiClient.post(`/me/contacts/${contact.id}/ticket`, {
        motif: trimmed,
        client_id: ticketClientId,
        ...(forceRelease ? { force_release: true } : {}),
      });
      if (r.data?.ok) {
        toast.success(`Ticket ${r.data.ticket.number} créé`);
        if (r.data.notification?.sent) toast.info("Notification WhatsApp envoyée au contact");
        else if (r.data.notification?.error) toast.warning(`Notification non envoyée : ${r.data.notification.error}`);
        await loadActiveTicket();
        setTicketModalOpen(false);
      }
    } catch (err) {
      const detail = err?.response?.data?.detail || "Erreur";
      const blockingNumber = err?.response?.headers?.["x-blocking-ticket-number"];
      // Iter38p — If a blocking ticket prevents creation, offer to force-release it
      if (err?.response?.status === 409 && blockingNumber) {
        const ok = window.confirm(
          `${detail}\n\nLe ticket ${blockingNumber} bloque la création. ` +
          `Voulez-vous le clôturer automatiquement pour pouvoir créer le nouveau ticket ?\n\n` +
          `(Cette action est irréversible — utilisez-la uniquement si l'ancien ticket est obsolète ou orphelin.)`
        );
        if (ok) {
          await submitTicket(true);  // retry with force_release=true
          return;
        }
      }
      toast.error(detail);
    } finally {
      setTicketSubmitting(false);
    }
  };

  // Iter34o — Whenever the message list changes (initial load, refresh,
  // send), jump the scroll container straight to the bottom so the latest
  // exchange is always in view. We use `behavior:"auto"` for the very
  // first render and "smooth" once the user is already in the modal.
  const initialScrollDone = React.useRef(false);
  useEffect(() => {
    if (!scrollContainerRef.current || loading) return;
    const el = scrollContainerRef.current;
    const behavior = initialScrollDone.current ? "smooth" : "auto";
    // Use a microtask so React has committed message bubbles before we
    // measure scrollHeight.
    requestAnimationFrame(() => {
      try {
        el.scrollTo({ top: el.scrollHeight, behavior });
      } catch {
        el.scrollTop = el.scrollHeight;
      }
      initialScrollDone.current = true;
    });
  }, [messages.length, loading]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      data-testid="conversation-modal"
    >
      <div className="w-full max-w-2xl rounded-2xl bg-white shadow-2xl flex flex-col max-h-[85vh]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200">
          <div className="flex items-center gap-3 min-w-0">
            <ContactAvatar contact={contact} size={40} />
            <div className="min-w-0">
              <h2 className="text-lg font-display font-bold inline-flex items-center gap-2">
                <History className="h-4 w-4 text-sawali-blue" /> Conversation
              </h2>
              <p className="text-xs text-slate-500 mt-0.5 truncate">
                <strong className="text-slate-800">{contact.name}</strong>
                {contact.whatsapp && <code className="ml-2 bg-slate-100 px-1.5 py-0.5 rounded">{contact.whatsapp}</code>}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={load}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 px-2.5 py-1.5 text-xs"
              data-testid="conversation-refresh"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Actualiser
            </button>
            <button onClick={onClose} className="text-slate-500 hover:text-slate-900"><X className="h-4 w-4" /></button>
          </div>
        </div>
        {/* Iter43-fix24az-y (2026-07-22) — Tabs: Discussion / Groupes(n).
            Compact tab bar right below the header so small screens don't
            have the ContactGroupChips permanently eating half the viewport. */}
        <div className="flex border-b border-slate-200 bg-slate-50/60" role="tablist">
          <button
            type="button"
            onClick={() => setConvTab("discussion")}
            className={`flex-1 py-2 text-sm font-medium transition-colors ${
              convTab === "discussion"
                ? "text-sawali-blue border-b-2 border-sawali-blue bg-white"
                : "text-slate-600 hover:text-slate-900 hover:bg-slate-100"
            }`}
            role="tab"
            aria-selected={convTab === "discussion"}
            data-testid="wa-tab-discussion"
          >
            Discussion
          </button>
          <button
            type="button"
            onClick={() => setConvTab("groups")}
            className={`flex-1 py-2 text-sm font-medium transition-colors ${
              convTab === "groups"
                ? "text-sawali-blue border-b-2 border-sawali-blue bg-white"
                : "text-slate-600 hover:text-slate-900 hover:bg-slate-100"
            }`}
            role="tab"
            aria-selected={convTab === "groups"}
            data-testid="wa-tab-groups"
          >
            Groupes ({groupCount})
          </button>
        </div>
        {convTab === "groups" ? (
          <div className="flex-1 overflow-y-auto px-5 py-4" data-testid="wa-tab-groups-content">
            <ContactGroupChips
              contact={contact}
              userRole={user?.role}
              onCountChange={setGroupCount}
            />
          </div>
        ) : (
          <>
        {/* Hidden mount so groupCount stays accurate even when the user is on
            the Discussion tab (the callback fires on every membership change).
            The chips themselves are hidden via `sr-only`. */}
        <div className="sr-only" aria-hidden="true">
          <ContactGroupChips
            contact={contact}
            userRole={user?.role}
            onCountChange={setGroupCount}
          />
        </div>
        {/* Iter35o — Ticket bar (above chat) */}
        <div className="px-5 py-2 border-b border-slate-200 bg-amber-50/50" data-testid="conversation-ticket-bar">
          {activeTicket ? (
            <div className="flex items-center gap-2 text-xs flex-wrap">
              <Ticket className="h-4 w-4 text-amber-600" />
              <span className="font-mono bg-white ring-1 ring-amber-300 text-amber-900 px-1.5 py-0.5 rounded">
                {activeTicket.number}
              </span>
              <span className="text-amber-900 truncate max-w-[260px]" title={activeTicket.motif}>
                {activeTicket.motif}
              </span>
              <span className="text-[10px] uppercase tracking-wider text-amber-700 font-semibold ring-1 ring-amber-200 bg-white rounded-full px-1.5 py-0.5">
                {activeTicket.status === "open" ? "En attente" : activeTicket.status === "in_progress" ? "En cours" : "Suspendu"}
              </span>
              <Link
                to="/portal/tickets"
                className="ml-auto text-amber-700 hover:underline inline-flex items-center gap-1"
                data-testid="conversation-ticket-view"
              >
                Voir <ArrowUpRight className="h-3 w-3" />
              </Link>
              {/* Iter38q — Admin/Sup only: archive ticket to trash (irreversible) */}
              {/* Iter38r-fix3 — Replaced window.confirm with a real modal carrying
                  an "also unlink contact ↔ ticket" checkbox so admins can fully
                  release a stuck/orphan ticket from the chat window. */}
              {/* Iter38r-fix9i — Bouton corbeille visible pour Admin, Superviseur ET Modération */}
              {(user?.role === "admin" || user?.role === "superviseur" || user?.tracked_role === "Modération") && (
                <button
                  type="button"
                  onClick={() => setArchiveModal({ open: true, ticket: activeTicket, alsoUnlink: false, busy: false })}
                  className="text-rose-700 hover:bg-rose-100 rounded p-1"
                  data-testid="conversation-ticket-archive"
                  title="Mettre à la corbeille (irréversible) — supprime toutes les références"
                >
                  <Trash className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          ) : (
            <div className="flex items-center justify-between gap-2 text-xs">
              <span className="inline-flex items-center gap-1.5 text-amber-800">
                <Ticket className="h-3.5 w-3.5" /> Aucun ticket d'intervention ouvert pour ce contact.
              </span>
              <button
                onClick={openTicket}
                className="inline-flex items-center gap-1 rounded-md bg-amber-500 hover:bg-amber-600 text-white px-2.5 py-1 text-xs font-medium shadow-sm"
                data-testid="conversation-ticket-create"
                title="Générer un numéro de ticket d'intervention pour ce contact"
              >
                <Ticket className="h-3.5 w-3.5" /> Générer un ticket
              </button>
            </div>
          )}
        </div>
        {/* Iter36k — Modal: create a ticket with explicit "client lié" dropdown */}
        {/* Iter38r-fix4 — Share-from-library modal (media / form / catalog product) */}
        {shareModal.open && (
          <div
            className="fixed inset-0 z-[70] flex items-center justify-center p-4 bg-black/50"
            onClick={(e) => e.target === e.currentTarget && setShareModal({ open: false, tab: "media", items: [], loading: false, query: "" })}
            data-testid="share-library-modal"
          >
            <div className="bg-white rounded-2xl shadow-xl max-w-2xl w-full p-5 max-h-[85vh] flex flex-col">
              <div className="flex items-start justify-between mb-3">
                <h3 className="font-display font-semibold text-slate-900 inline-flex items-center gap-2">
                  <Share2 className="h-4 w-4 text-sky-600" /> Partager depuis votre bibliothèque
                </h3>
                <button
                  onClick={() => setShareModal({ open: false, tab: "media", items: [], loading: false, query: "" })}
                  className="text-slate-400 hover:text-slate-700 p-1"
                  data-testid="share-modal-close"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <p className="text-xs text-slate-500 mb-3">
                Choisissez un élément à partager — son lien sera inséré dans la zone de saisie, prêt à envoyer.
              </p>
              <div className="flex gap-1 border-b border-slate-200 mb-3" data-testid="share-modal-tabs">
                {[
                  { k: "media", label: "Bibliothèque", icon: FolderOpen },
                  { k: "form", label: "Formulaire", icon: FileEdit },
                  { k: "catalog", label: "Catalogue", icon: ShoppingBag },
                ].map((t) => {
                  const TIcon = t.icon;
                  const active = shareModal.tab === t.k;
                  return (
                    <button
                      key={t.k}
                      type="button"
                      onClick={() => loadShareTab(t.k)}
                      className={`inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold border-b-2 transition ${
                        active ? "border-sky-600 text-sky-700" : "border-transparent text-slate-500 hover:text-slate-800"
                      }`}
                      data-testid={`share-modal-tab-${t.k}`}
                    >
                      <TIcon className="h-3.5 w-3.5" /> {t.label}
                    </button>
                  );
                })}
              </div>
              <input
                type="text"
                value={shareModal.query}
                onChange={(e) => setShareModal((m) => ({ ...m, query: e.target.value }))}
                placeholder="Rechercher…"
                className="mb-3 w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-sky-500 focus:ring-1 focus:ring-sky-200 outline-none"
                data-testid="share-modal-search"
              />
              <div className="flex-1 overflow-y-auto -mx-2 px-2">
                {shareModal.loading ? (
                  <p className="text-center text-slate-400 italic py-8 text-sm">Chargement…</p>
                ) : shareModal.items.length === 0 ? (
                  <p className="text-center text-slate-400 italic py-8 text-sm">
                    Aucun élément disponible dans cet onglet.
                  </p>
                ) : (
                  <ul className="space-y-1.5" data-testid="share-modal-items">
                    {shareModal.items
                      .filter((it) => {
                        const q = shareModal.query.trim().toLowerCase();
                        if (!q) return true;
                        return (it.label || "").toLowerCase().includes(q) || (it.subtitle || "").toLowerCase().includes(q);
                      })
                      .slice(0, 100)
                      .map((it) => (
                        <li key={it.id}>
                          <button
                            type="button"
                            onClick={() => pickShareItem(it)}
                            className="w-full text-left rounded-lg ring-1 ring-slate-200 bg-white hover:ring-sky-400 hover:bg-sky-50 px-3 py-2 transition flex items-center gap-3"
                            data-testid={`share-modal-pick-${it.id}`}
                          >
                            <div className={`h-9 w-9 rounded-lg flex items-center justify-center shrink-0 ${
                              it.icon === "form" ? "bg-amber-50 text-amber-600" :
                              it.icon === "catalog" ? "bg-emerald-50 text-emerald-600" :
                              "bg-sky-50 text-sky-600"
                            }`}>
                              {it.icon === "form" ? <FileEdit className="h-4 w-4" /> :
                               it.icon === "catalog" ? <ShoppingBag className="h-4 w-4" /> :
                               <FolderOpen className="h-4 w-4" />}
                            </div>
                            <div className="flex-1 min-w-0">
                              <p className="text-sm font-semibold text-slate-900 truncate">{it.label}</p>
                              <p className="text-[11px] text-slate-500 truncate">{it.subtitle || it.url}</p>
                            </div>
                            <Send className="h-3.5 w-3.5 text-slate-400 shrink-0" />
                          </button>
                        </li>
                      ))}
                  </ul>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Iter38r-fix3 — Archive ticket confirmation modal with also_unlink checkbox */}
        {archiveModal.open && archiveModal.ticket && (
          <div
            className="fixed inset-0 z-[70] flex items-center justify-center p-4 bg-black/50"
            onClick={(e) => e.target === e.currentTarget && !archiveModal.busy && setArchiveModal({ open: false, ticket: null, alsoUnlink: false, busy: false })}
            data-testid="archive-ticket-modal"
          >
            <div className="bg-white rounded-2xl shadow-xl max-w-md w-full p-5">
              <div className="flex items-start justify-between mb-3">
                <h3 className="font-display font-semibold text-slate-900 inline-flex items-center gap-2">
                  <Trash className="h-4 w-4 text-rose-600" /> Mettre à la corbeille
                </h3>
                <button
                  onClick={() => !archiveModal.busy && setArchiveModal({ open: false, ticket: null, alsoUnlink: false, busy: false })}
                  className="text-slate-400 hover:text-slate-700 p-1"
                  data-testid="archive-modal-close"
                  aria-label="Fermer"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <p className="text-sm text-slate-700 mb-3">
                Mettre le ticket <strong>{archiveModal.ticket.number}</strong> à la corbeille ?
              </p>
              <div className="rounded-lg ring-1 ring-rose-200 bg-rose-50 p-3 text-xs text-rose-900 mb-3 space-y-1">
                <p>⚠️ Action <strong>irréversible</strong> — le ticket ne pourra plus être réactivé.</p>
                <p>Toutes ses références seront retirées des listes et conversations.</p>
              </div>
              <label className="flex items-start gap-2 text-sm text-slate-700 cursor-pointer mb-4 rounded-lg ring-1 ring-amber-200 bg-amber-50 p-3 hover:bg-amber-100" data-testid="archive-also-unlink-label">
                <input
                  type="checkbox"
                  checked={archiveModal.alsoUnlink}
                  onChange={(e) => setArchiveModal((m) => ({ ...m, alsoUnlink: e.target.checked }))}
                  className="mt-0.5"
                  data-testid="archive-also-unlink-checkbox"
                />
                <span>
                  <strong>Effacer aussi le lien contact ↔ ticket</strong>
                  <span className="block text-xs text-amber-800/80 mt-0.5">
                    Recommandé pour les tickets orphelins — permet de générer un nouveau ticket immédiatement pour ce contact, même si la fenêtre de conversation reste bloquée.
                  </span>
                </span>
              </label>
              <div className="flex gap-2 justify-end">
                <button
                  onClick={() => setArchiveModal({ open: false, ticket: null, alsoUnlink: false, busy: false })}
                  disabled={archiveModal.busy}
                  className="px-3 py-1.5 rounded-md ring-1 ring-slate-300 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                  data-testid="archive-modal-cancel"
                >
                  Annuler
                </button>
                <button
                  onClick={submitArchive}
                  disabled={archiveModal.busy}
                  className="px-3 py-1.5 rounded-md bg-rose-600 text-white text-sm hover:bg-rose-700 disabled:opacity-50 inline-flex items-center gap-1"
                  data-testid="archive-modal-confirm"
                >
                  <Trash className="h-3.5 w-3.5" />
                  {archiveModal.busy ? "Suppression…" : "Mettre à la corbeille"}
                </button>
              </div>
            </div>
          </div>
        )}

        {ticketModalOpen && (
          <div
            className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/50"
            onClick={(e) => e.target === e.currentTarget && !ticketSubmitting && setTicketModalOpen(false)}
            data-testid="ticket-create-modal"
          >
            <div className="w-full max-w-md rounded-2xl bg-white shadow-2xl p-5">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-base font-display font-bold inline-flex items-center gap-2">
                  <Ticket className="h-4 w-4 text-amber-600" /> Nouveau ticket d'intervention
                </h3>
                <button
                  onClick={() => !ticketSubmitting && setTicketModalOpen(false)}
                  className="text-slate-500 hover:text-slate-900"
                  data-testid="ticket-create-cancel-icon"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <p className="text-xs text-slate-500 mb-3">
                Contact : <strong className="text-slate-700">{contact.name}</strong>
                {contact.whatsapp && <code className="ml-2 bg-slate-100 px-1.5 py-0.5 rounded text-[11px]">{contact.whatsapp}</code>}
              </p>

              <div className="space-y-3">
                <div>
                  <label className="block text-xs font-medium text-slate-700 mb-1">
                    Client lié <span className="text-rose-500">*</span>
                  </label>
                  <select
                    value={ticketClientId}
                    onChange={(e) => setTicketClientId(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-300"
                    data-testid="ticket-create-client-select"
                    disabled={ticketSubmitting}
                  >
                    <option value="">— Sélectionnez un client —</option>
                    {ticketClients.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.full_name || c.company || c.client_code || c.id}
                        {c.company && c.full_name ? ` · ${c.company}` : ""}
                      </option>
                    ))}
                  </select>
                  <p className="text-[10px] text-slate-500 mt-1">
                    Choisissez l'entreprise/client à qui ce ticket sera rattaché.
                  </p>
                </div>

                {ticketTemplates.length > 0 && (
                  <div>
                    <label className="block text-xs font-medium text-slate-700 mb-1">
                      Modèle de motif (optionnel)
                    </label>
                    <select
                      onChange={(e) => {
                        const i = parseInt(e.target.value, 10);
                        if (!isNaN(i) && ticketTemplates[i]) {
                          setTicketMotif(ticketTemplates[i].motif || "");
                        }
                      }}
                      className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-300"
                      data-testid="ticket-create-template-select"
                      defaultValue=""
                      disabled={ticketSubmitting}
                    >
                      <option value="">— Saisir un motif libre —</option>
                      {ticketTemplates.map((t, i) => (
                        <option key={t.id || i} value={i}>{t.label}</option>
                      ))}
                    </select>
                  </div>
                )}

                <div>
                  <label className="block text-xs font-medium text-slate-700 mb-1">
                    Motif <span className="text-rose-500">*</span>
                  </label>
                  <textarea
                    value={ticketMotif}
                    onChange={(e) => setTicketMotif(e.target.value)}
                    rows={3}
                    maxLength={200}
                    placeholder="Brève description de l'intervention demandée (max 200 caractères)"
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-300 resize-none"
                    data-testid="ticket-create-motif-input"
                    disabled={ticketSubmitting}
                  />
                  <p className="text-[10px] text-slate-400 mt-1 text-right">{ticketMotif.length}/200</p>
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 mt-4">
                <button
                  onClick={() => setTicketModalOpen(false)}
                  disabled={ticketSubmitting}
                  className="rounded-lg border border-slate-300 bg-white hover:bg-slate-50 px-3 py-1.5 text-sm disabled:opacity-50"
                  data-testid="ticket-create-cancel"
                >
                  Annuler
                </button>
                <button
                  onClick={submitTicket}
                  disabled={ticketSubmitting || !ticketClientId || !ticketMotif.trim()}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500 hover:bg-amber-600 text-white px-3 py-1.5 text-sm font-medium shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
                  data-testid="ticket-create-submit"
                >
                  {ticketSubmitting ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Ticket className="h-3.5 w-3.5" />}
                  Créer le ticket
                </button>
              </div>
            </div>
          </div>
        )}
        <div ref={scrollContainerRef} className="flex-1 overflow-y-auto p-5 space-y-3 bg-slate-50/50" data-testid="conversation-scroll">
          {loading ? (
            <p className="text-center text-slate-500 text-sm">Chargement…</p>
          ) : messages.length === 0 ? (
            <p className="text-center text-slate-400 italic text-sm py-8">Aucun message échangé pour l'instant.</p>
          ) : (
            messages.map((m) => <MessageBubble key={m.id} m={m} allMessages={messages} onReply={setReplyTo} />)
          )}
          <div ref={scrollEndRef} data-testid="conversation-scroll-end" />
        </div>
        {/* Free-form text composer (only allowed within Meta 24h window) */}
        <div className="border-t border-slate-200 bg-white">
          {canSendText ? (
            <div className="px-5 py-3" data-testid="conversation-composer-open">
              <div className="flex items-center justify-between text-[11px] mb-1.5">
                <span className="inline-flex items-center gap-1.5 text-emerald-700 font-medium">
                  <Check className="h-3.5 w-3.5" /> Fenêtre 24h ouverte — réponse libre autorisée
                </span>
                {windowExpires && (
                  <span className="text-slate-500" data-testid="conversation-window-expires">
                    Expire le {fmtDate(windowExpires)}
                  </span>
                )}
              </div>

              {/* Iter37h — Reply preview banner */}
              {replyTo && (
                <div
                  className="flex items-start gap-2 mb-2 rounded-lg bg-sky-50 ring-1 ring-sky-200 border-l-4 border-sky-500 px-3 py-2"
                  data-testid="conversation-reply-banner"
                >
                  <CornerUpLeft className="h-4 w-4 text-sky-600 mt-0.5 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-[10px] font-semibold text-sky-700 uppercase tracking-wider">
                      Réponse à {replyTo.direction === "outbound" ? "vous-même" : "ce contact"}
                    </p>
                    <p className="text-xs text-slate-700 italic truncate">
                      {(replyTo.body || (replyTo.media_kind ? `[${replyTo.media_kind}]` : "—")).slice(0, 120)}
                    </p>
                  </div>
                  <button
                    onClick={() => setReplyTo(null)}
                    className="text-xs text-rose-600 hover:underline"
                    data-testid="conversation-reply-cancel"
                    title="Annuler la réponse"
                  >
                    Annuler
                  </button>
                </div>
              )}

              {/* Iter37h — Voice recording overlay */}
              {recState === "recording" && (
                <div className="flex items-center gap-3 mb-2 rounded-lg bg-rose-50 ring-1 ring-rose-200 px-3 py-2" data-testid="conversation-recording">
                  <span className="inline-flex h-2.5 w-2.5 rounded-full bg-rose-500 animate-pulse" />
                  <span className="text-sm text-rose-700 font-medium tabular-nums">
                    Enregistrement… {Math.floor(recElapsed / 60).toString().padStart(2, "0")}:{(recElapsed % 60).toString().padStart(2, "0")}
                  </span>
                  <div className="ml-auto flex items-center gap-1.5">
                    <button
                      onClick={() => stopRecording({ asText: true })}
                      className="rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white px-2.5 py-1 text-xs font-medium"
                      data-testid="conversation-rec-transcribe"
                    >
                      Transcrire & insérer
                    </button>
                    <button
                      onClick={() => stopRecording({ asText: false })}
                      className="rounded-lg bg-sky-600 hover:bg-sky-700 text-white px-2.5 py-1 text-xs font-medium"
                      data-testid="conversation-rec-attach"
                    >
                      Envoyer comme note vocale
                    </button>
                    <button
                      onClick={cancelRecording}
                      className="rounded-lg bg-slate-200 hover:bg-slate-300 text-slate-800 px-2.5 py-1 text-xs"
                      data-testid="conversation-rec-cancel"
                    >
                      Annuler
                    </button>
                  </div>
                </div>
              )}
              {recState === "transcribing" && (
                <div className="flex items-center gap-2 mb-2 rounded-lg bg-amber-50 ring-1 ring-amber-200 px-3 py-2 text-xs text-amber-800" data-testid="conversation-rec-transcribing">
                  <RefreshCw className="h-3.5 w-3.5 animate-spin" /> Transcription en cours…
                </div>
              )}

              {/* Iter35l — Pending media preview row */}
              {pendingFile && (
                <div className="flex items-center gap-3 mb-2 rounded-lg bg-emerald-50 ring-1 ring-emerald-200 p-2" data-testid="conversation-pending-media">
                  {pendingFile.kind === "image" && pendingFile.previewUrl ? (
                    <img src={pendingFile.previewUrl} alt="" className="h-12 w-12 object-cover rounded ring-1 ring-emerald-300" />
                  ) : pendingFile.kind === "audio" ? (
                    <Mic className="h-8 w-8 text-emerald-700" />
                  ) : pendingFile.kind === "video" ? (
                    <Video className="h-8 w-8 text-emerald-700" />
                  ) : (
                    <FileTextIcon className="h-8 w-8 text-emerald-700" />
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-emerald-900 truncate">{pendingFile.file.name}</p>
                    <p className="text-[10px] text-emerald-700/80">{(pendingFile.file.size / 1024).toFixed(0)} Ko · {pendingFile.kind}</p>
                  </div>
                  <button
                    onClick={clearPendingFile}
                    className="text-xs text-rose-600 hover:underline"
                    data-testid="conversation-pending-media-clear"
                    title="Retirer le fichier"
                  >
                    Retirer
                  </button>
                </div>
              )}

              <div className="flex gap-2 items-end">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*,audio/*,video/mp4,application/pdf"
                  onChange={onPickFile}
                  className="hidden"
                  data-testid="conversation-file-input"
                />
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={sending || !!pendingFile || recState !== "idle"}
                  className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 px-2.5 py-2 text-sm text-slate-600 disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
                  data-testid="conversation-attach-btn"
                  title="Joindre un fichier (image, audio, vidéo, PDF — 16 Mo max)"
                >
                  <Paperclip className="h-4 w-4" />
                </button>
                {/* Iter38r-fix4 — Share from library / form / catalog */}
                <button
                  onClick={() => openShareModal("media")}
                  disabled={sending || !!pendingFile || recState !== "idle"}
                  className="inline-flex items-center gap-1 rounded-lg border border-sky-300 bg-sky-50 hover:bg-sky-100 px-2.5 py-2 text-sm text-sky-700 disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
                  data-testid="conversation-share-btn"
                  title="Partager depuis votre bibliothèque, un formulaire ou un produit du catalogue"
                >
                  <Share2 className="h-4 w-4" />
                </button>
                {/* Iter37h — Voice note button: start recording */}
                <button
                  onClick={startRecording}
                  disabled={sending || !!pendingFile || recState !== "idle"}
                  className="inline-flex items-center gap-1 rounded-lg border border-rose-300 bg-rose-50 hover:bg-rose-100 px-2.5 py-2 text-sm text-rose-700 disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
                  data-testid="conversation-mic-btn"
                  title="Enregistrer une note vocale (puis transcrire ou envoyer)"
                >
                  <Mic className="h-4 w-4" />
                </button>
                <textarea
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); sendFreeText(); }
                  }}
                  placeholder={pendingFile ? "Légende (optionnelle)…" : "Tapez votre réponse… (Cmd/Ctrl + Entrée pour envoyer)"}
                  rows={2}
                  maxLength={4096}
                  className="flex-1 resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-sawali-blue focus:ring-1 focus:ring-sawali-blue outline-none"
                  data-testid="conversation-text-input"
                />
                <button
                  onClick={sendFreeText}
                  disabled={sending || (!text.trim() && !pendingFile)}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 text-white px-3.5 py-2 text-sm hover:bg-emerald-700 disabled:opacity-40 disabled:cursor-not-allowed shadow-sm"
                  data-testid="conversation-text-send"
                >
                  <Send className="h-4 w-4" />
                  {sending ? "Envoi…" : "Envoyer"}
                </button>
              </div>
              <p className="text-[10px] text-slate-400 mt-1 tabular-nums">{text.length} / 4096</p>
            </div>
          ) : (
            <div className="px-5 py-3 bg-amber-50 border-t border-amber-100" data-testid="conversation-composer-closed">
              <div className="flex items-start gap-2 text-[12px]">
                <AlertCircle className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
                <div className="flex-1">
                  <p className="text-amber-900 font-medium">
                    Fenêtre 24h fermée — utilisez un template Meta approuvé
                  </p>
                  <p className="text-amber-700 mt-0.5">
                    Meta n'autorise les réponses libres qu'à l'intérieur de 24h après le dernier message reçu de ce contact. Cliquez sur « WhatsApp » dans la liste pour envoyer un template (ex : <code className="bg-amber-100 px-1 rounded">hello_world</code>).
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
        <div className="px-5 py-3 border-t border-slate-200 text-[11px] text-slate-500 flex items-center justify-between">
          <span>{messages.length} message(s)</span>
          <span>Les statuts (envoyé / distribué / lu) sont mis à jour via le webhook Meta.</span>
        </div>
          </>
        )}
      </div>
    </div>
  );
};

// --- Iter43-fix24az-p — Liluvine contact timeline modal ---
const LiluvineTimelineModal = ({ contact, onClose }) => {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState({ items: [], count: 0 });

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const r = await apiClient.get(`/me/contacts/${contact.id}/liluvine-history`);
        setData(r.data || { items: [], count: 0 });
      } catch (e) {
        toast.error(e?.response?.data?.detail || "Erreur chargement timeline");
      } finally { setLoading(false); }
    })();
  }, [contact.id]);

  const renderItem = (it) => {
    const kindLabel = it.kind === "ad_template" ? "Modèle publicité" : it.kind === "fuzzy_cmd" ? "Commande floue" : it.kind;
    const kindColor = it.kind === "ad_template" ? "bg-fuchsia-100 text-fuchsia-800" : "bg-amber-100 text-amber-800";
    return (
      <li key={it.id} className="p-3 border-b border-slate-100 last:border-0" data-testid={`liluvine-timeline-item-${it.id}`}>
        <div className="flex items-start gap-2">
          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${kindColor}`}>{kindLabel}</span>
          {it.template_name && <span className="text-xs font-semibold text-slate-800 truncate">{it.template_name}</span>}
          {it.matched_command && <code className="text-[10px] bg-slate-100 px-1.5 py-0.5 rounded">!{it.matched_command}</code>}
          {it.matched_score != null && <span className="text-[10px] text-slate-400">score : {it.matched_score}%</span>}
          <span className="text-[10px] text-slate-400 ml-auto">{new Date(it.created_at).toLocaleString("fr-FR")}</span>
        </div>
        <div className="mt-1.5 space-y-1">
          <div className="text-xs text-slate-500">
            <ArrowDownLeft className="inline h-3 w-3 mr-1 text-emerald-600" />
            <em>« {it.inbound_text?.slice(0, 200) || "—"} »</em>
          </div>
          {it.response_text && (
            <div className="text-xs text-slate-700 bg-slate-50 rounded p-2">
              <ArrowUpRight className="inline h-3 w-3 mr-1 text-sawali-blue" />
              {it.response_text}
              {it.response_media_url && (
                <p className="mt-1 text-[10px] text-fuchsia-700">
                  📎 média natif : {it.response_media_kind || "image"} — {it.response_media_url}
                </p>
              )}
            </div>
          )}
        </div>
      </li>
    );
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      data-testid="liluvine-timeline-modal"
    >
      <div className="w-full max-w-2xl rounded-2xl bg-white shadow-2xl flex flex-col max-h-[85vh]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-9 h-9 rounded-lg bg-fuchsia-100 flex items-center justify-center">
              <Sparkles className="h-4 w-4 text-fuchsia-700" />
            </div>
            <div className="min-w-0">
              <h2 className="text-base font-display font-bold">Historique Liluvine</h2>
              <p className="text-xs text-slate-500 truncate">
                <strong>{contact.name}</strong>
                {contact.whatsapp && <code className="ml-2 bg-slate-100 px-1.5 py-0.5 rounded">{contact.whatsapp}</code>}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900" data-testid="liluvine-timeline-close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="p-6 text-center text-sm text-slate-500 flex items-center justify-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
            </div>
          ) : data.items?.length === 0 ? (
            <div className="p-8 text-center" data-testid="liluvine-timeline-empty">
              <Sparkles className="h-10 w-10 text-slate-300 mx-auto mb-3" />
              <p className="text-sm text-slate-500">Aucun match Liluvine pour ce contact.</p>
              <p className="text-[11px] text-slate-400 mt-2">
                Les templates publicité et les commandes floues appariées apparaîtront ici quand ce contact enverra un message.
              </p>
            </div>
          ) : (
            <>
              <div className="px-5 py-2 border-b border-slate-100 bg-slate-50 text-[11px] text-slate-500">
                <strong>{data.count}</strong> interaction(s) enregistrée(s)
              </div>
              <ul className="divide-y divide-slate-100" data-testid="liluvine-timeline-list">
                {data.items.map(renderItem)}
              </ul>
            </>
          )}
        </div>
      </div>
    </div>
  );
};


// --- Iter35m — Save inbound WA media to shared library button ---
const SaveToLibraryButton = ({ messageId, testid }) => {
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const onClick = async () => {
    if (saving || saved) return;
    setSaving(true);
    try {
      const r = await apiClient.post(`/me/whatsapp/messages/${messageId}/save-to-library`, {});
      if (r.data?.ok) {
        setSaved(true);
        toast.success(r.data?.already_existed ? "Déjà dans la bibliothèque" : "Sauvegardé dans la bibliothèque");
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setSaving(false);
    }
  };
  return (
    <button
      onClick={onClick}
      disabled={saving || saved}
      className={`inline-flex items-center gap-1 text-[10px] rounded-md px-2 py-1 ring-1 transition ${
        saved
          ? "bg-emerald-50 ring-emerald-300 text-emerald-700"
          : "bg-white ring-slate-300 text-slate-700 hover:bg-sky-50 hover:ring-sky-300 hover:text-sky-700"
      }`}
      data-testid={testid}
      title={saved ? "Sauvegardé" : "Sauvegarder dans la bibliothèque partagée pour réutilisation"}
    >
      {saved ? <Check className="h-3 w-3" /> : <BookmarkPlus className="h-3 w-3" />}
      {saving ? "…" : saved ? "Sauvegardé" : "Sauvegarder"}
    </button>
  );
};

// --- Chat bubble ---
const MessageBubble = ({ m, allMessages = [], onReply }) => {
  const outbound = m.direction === "outbound";
  // Iter37h — Find the quoted message (if this is a reply)
  const quotedTarget = (() => {
    const mid = m.reply_to_message_id;
    if (!mid || !Array.isArray(allMessages)) return null;
    return allMessages.find((x) => x.message_id === mid || x.wa_message_id === mid || x.id === mid) || null;
  })();
  const statusIcon = outbound
    ? (m.read_at ? { Icon: CheckCheck, color: "text-sky-500", label: "Lu" }
      : m.delivered_at ? { Icon: CheckCheck, color: "text-slate-400", label: "Distribué" }
      : m.failed_at ? { Icon: AlertCircle, color: "text-rose-500", label: "Échec" }
      : m.sent_at ? { Icon: Check, color: "text-slate-400", label: "Envoyé" }
      : { Icon: Clock, color: "text-slate-400", label: "En attente" })
    : null;

  const primaryTs = outbound
    ? (m.sent_at || m.created_at)
    : (m.received_at || m.created_at);

  // Iter35l — Media rendering. A row may carry image/audio/video/document via
  // m.media_url + m.media_kind (+ m.media_mime_type as fallback). For inbound
  // voice notes, m.voice_note_transcript is appended in italic.
  const mediaUrl = m.media_url ? absoluteFileUrl(m.media_url) : null;
  const mediaKind = m.media_kind
    || (m.media_mime_type ? (
      m.media_mime_type.startsWith("image/") ? "image"
        : m.media_mime_type.startsWith("audio/") ? "audio"
        : m.media_mime_type.startsWith("video/") ? "video"
        : "document"
    ) : null);
  const caption = m.media_caption || (m.media_url ? "" : null);
  const hasMedia = !!mediaUrl && !!mediaKind;

  // Body fallback: if a media bubble has no caption, hide the placeholder
  // string ("[image reçu]" / "[image envoyé]") to keep the UI clean.
  const placeholder = hasMedia && /^\[[a-z]+ (reçu|envoyé)\]$/i.test((m.body || "").trim());
  // 2026-02 (#4) — Resolve the actual delivered message body for templates.
  // Backend stores `template_rendered_body` when available; fall back to
  // `m.body` (which the worker may already have populated) so we can show
  // the user EXACTLY what was delivered to WhatsApp under the template name.
  const templateBody = outbound && m.template_name
    ? (m.template_rendered_body || m.body || "")
    : null;
  const body = placeholder ? "" : (m.body || (m.template_name ? `Template : ${m.template_name}` : ""));

  return (
    <div className={`flex group ${outbound ? "justify-end" : "justify-start"} hover:bg-sky-50/40 -mx-3 px-3 py-1 rounded-md transition-colors`} data-testid={`msg-${m.id}`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm shadow-sm transition-shadow group-hover:shadow-md ${
          outbound ? "bg-sawali-blue text-white" : "bg-white ring-1 ring-slate-200 text-slate-900"
        }`}
      >
        <div className="flex items-center gap-1.5 text-[10px] opacity-75 mb-0.5">
          {outbound
            ? <ArrowUpRight className="h-3 w-3" />
            : <ArrowDownLeft className="h-3 w-3" />}
          <span>{outbound ? "Envoyé" : "Reçu"}</span>
          {outbound && m.template_name && (
            <code className={`px-1 rounded ${outbound ? "bg-white/20" : "bg-slate-100"}`}>
              {m.template_name}
            </code>
          )}
        </div>

        {/* 2026-02 (#4) — Aperçu du contenu réellement délivré */}
        {outbound && m.template_name && templateBody && (
          <div
            className={`mb-1.5 rounded-md border-l-2 px-2 py-1 text-[11px] italic ${
              outbound ? "bg-white/10 border-white/40 text-white/95" : "bg-amber-50 border-amber-400 text-amber-900"
            }`}
            data-testid={`msg-template-preview-${m.id}`}
            title="Aperçu du message effectivement délivré au destinataire"
          >
            <p className={`font-semibold text-[9px] uppercase tracking-wider mb-0.5 ${outbound ? "text-white/70" : "text-amber-700"}`}>
              Aperçu délivré
            </p>
            <p className="whitespace-pre-wrap break-words">{templateBody}</p>
          </div>
        )}

        {/* Iter37h — Quote bar: render the message this one is replying to */}
        {(quotedTarget || m.reply_to_message_id) && (
          <div
            className={`mb-1.5 rounded-md border-l-4 px-2 py-1 text-[11px] ${
              outbound ? "bg-white/15 border-white/60 text-white/90" : "bg-sky-50 border-sky-400 text-slate-700"
            }`}
            data-testid={`msg-quote-${m.id}`}
          >
            <p className={`font-semibold text-[10px] ${outbound ? "text-white/80" : "text-sky-700"}`}>
              {quotedTarget?.direction === "outbound" ? "Vous" : "Contact"}
            </p>
            <p className="truncate italic">
              {quotedTarget
                ? (quotedTarget.body || quotedTarget.media_caption || (quotedTarget.media_kind ? `[${quotedTarget.media_kind}]` : "—")).slice(0, 120)
                : "Message d'origine indisponible"}
            </p>
          </div>
        )}

        {/* Media payload (Iter35l) */}
        {hasMedia && (
          <div className="mb-1.5" data-testid={`msg-media-${m.id}`}>
            {mediaKind === "image" ? (
              <div className="space-y-1.5">
                <a href={mediaUrl} target="_blank" rel="noreferrer">
                  <img
                    src={mediaUrl}
                    alt={m.media_filename || "image"}
                    className="max-h-72 max-w-full rounded-lg ring-1 ring-black/10 bg-slate-50 object-contain"
                    loading="lazy"
                  />
                </a>
                {/* Iter35m — Réutiliser ce média (uniquement sur images reçues) */}
                {!outbound && (
                  <SaveToLibraryButton messageId={m.id} testid={`msg-save-${m.id}`} outbound={outbound} />
                )}
              </div>
            ) : mediaKind === "audio" ? (
              <audio controls src={mediaUrl} className="w-64 max-w-full" preload="metadata" data-testid={`msg-audio-${m.id}`}>
                Votre navigateur ne supporte pas la lecture audio.
              </audio>
            ) : mediaKind === "video" ? (
              <video controls src={mediaUrl} className="max-h-72 max-w-full rounded-lg" preload="metadata">
                Votre navigateur ne supporte pas la lecture vidéo.
              </video>
            ) : (
              <a
                href={mediaUrl}
                target="_blank"
                rel="noreferrer"
                className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs ring-1 ${outbound ? "bg-white/10 ring-white/30 text-white hover:bg-white/20" : "bg-slate-50 ring-slate-300 text-slate-800 hover:bg-slate-100"}`}
                data-testid={`msg-doc-${m.id}`}
              >
                <FileTextIcon className="h-4 w-4" />
                <span className="font-medium truncate max-w-[160px]">{m.media_filename || "Document"}</span>
                <Download className="h-3 w-3 opacity-70" />
              </a>
            )}
            {m.voice_note_transcript && (
              <p className={`mt-1 text-[11px] italic ${outbound ? "text-white/80" : "text-slate-600"}`} data-testid={`msg-transcript-${m.id}`}>
                « {m.voice_note_transcript} »
              </p>
            )}
          </div>
        )}

        {body && <p className="whitespace-pre-wrap">{body}</p>}
        <div className={`flex items-center justify-between gap-3 mt-1.5 text-[10px] ${outbound ? "text-white/80" : "text-slate-400"}`}>
          <span>{fmtDate(primaryTs)}</span>
          <div className="flex items-center gap-2">
            {/* Iter37h — Reply action: only meaningful when we have a wa message id to quote */}
            {onReply && (m.message_id || m.wa_message_id) && (
              <button
                type="button"
                onClick={() => onReply({ id: m.id, body: m.body, direction: m.direction, message_id: m.message_id, wa_message_id: m.wa_message_id, media_kind: m.media_kind })}
                className={`inline-flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity hover:underline ${outbound ? "text-white/80" : "text-sky-600"}`}
                title="Répondre à ce message"
                data-testid={`msg-reply-${m.id}`}
              >
                <CornerUpLeft className="h-3 w-3" /> Répondre
              </button>
            )}
            {statusIcon && (
              <span className={`inline-flex items-center gap-1 ${outbound ? "" : statusIcon.color}`} title={statusIcon.label}>
                <statusIcon.Icon className="h-3 w-3" /> {statusIcon.label}
              </span>
            )}
          </div>
        </div>
        {outbound && (m.delivered_at || m.read_at || m.failed_at) && (
          <div className={`text-[10px] mt-1 ${outbound ? "text-white/70" : "text-slate-400"}`}>
            {m.delivered_at && <div>Distribué : {fmtDate(m.delivered_at)}</div>}
            {m.read_at && <div>Lu : {fmtDate(m.read_at)}</div>}
            {m.failed_at && <div>Échec : {fmtDate(m.failed_at)} {m.wa_error_message && `— ${m.wa_error_message}`}</div>}
          </div>
        )}
      </div>
    </div>
  );
};

const fmtDate = (iso) => {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch { return iso; }
};

const Input = ({ label, value, onChange, placeholder, testid }) => (
  <div>
    <label className="block text-xs font-semibold mb-1">{label}</label>
    <input
      value={value || ""}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:border-sawali-blue"
      data-testid={testid}
    />
  </div>
);

// --- Schedule modal: pick a template + date + time + variables, post to /me/messaging/schedules ---
const ScheduleModal = ({ contact, onClose, onScheduled }) => {
  const [templates, setTemplates] = useState([]);
  const [tokens, setTokens] = useState([]);
  const [templateName, setTemplateName] = useState("");
  const [language, setLanguage] = useState("fr");
  const [bodyVars, setBodyVars] = useState([]);
  const [headerText, setHeaderText] = useState("");
  const [headerMedia, setHeaderMedia] = useState(null);
  const [buttonVars, setButtonVars] = useState([]);
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [title, setTitle] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [configured, setConfigured] = useState(true);
  const [schedules, setSchedules] = useState([]);

  const refresh = () => apiClient.get("/me/messaging/schedules")
    .then((r) => setSchedules((r.data || []).filter((s) => (s.recipients || []).some((rc) => rc.kind === "raw" && (rc.id === contact.id || rc.phone === contact.whatsapp)))))
    .catch(() => {});

  useEffect(() => {
    Promise.all([
      apiClient.get("/me/whatsapp/templates"),
      apiClient.get("/me/messaging/variable-tokens").catch(() => ({ data: { tokens: [] } })),
    ]).then(([tplRes, tokRes]) => {
      const items = tplRes.data?.items || [];
      setTemplates(items);
      setTokens(tokRes.data?.tokens || []);
      setConfigured(!!tplRes.data?.configured);
      if (items[0]) {
        setTemplateName(items[0].name);
        setLanguage(items[0].language || "fr");
      }
    }).catch(() => {}).finally(() => setLoading(false));
    refresh();
    // eslint-disable-next-line
  }, []);

  const selectedTemplate = useMemo(
    () => templates.find((t) => t.name === templateName),
    [templates, templateName],
  );
  const parsed = useMemo(() => parseTemplate(selectedTemplate), [selectedTemplate]);

  useEffect(() => {
    setHeaderText("");
    setHeaderMedia(null);
    setBodyVars(Array(parsed.body.varCount).fill(""));
    setButtonVars((parsed.buttons || []).map((b) => Array(b.urlVarCount || 0).fill("")));
  }, [templateName, parsed.body.varCount, parsed.buttons]);

  const create = async () => {
    if (!templateName) { toast.error("Sélectionnez un template"); return; }
    if (!date || !time) { toast.error("Date et heure requises"); return; }
    const v = validateTemplateValues(parsed, { headerText, headerMedia, bodyVars, buttonVars });
    if (!v.ok) { toast.error(v.message); return; }
    const local = new Date(`${date}T${time}`);
    if (Number.isNaN(local.getTime())) { toast.error("Date invalide"); return; }
    if (local <= new Date()) { toast.error("La date doit être dans le futur"); return; }
    setSaving(true);
    try {
      const components = buildComponentsPayload(parsed, { headerText, headerMedia, bodyVars, buttonVars });
      await apiClient.post("/me/messaging/schedules", {
        title: title || `Envoi à ${contact.name}`,
        recipients: [{ kind: "raw", id: contact.id, phone: contact.whatsapp, label: contact.name }],
        template_name: templateName,
        language_code: language,
        components: components.length > 0 ? components : null,
        bodyVarsLen: bodyVars.length,
        // Server expects positional variable RECIPES, not the resolved values, when
        // tokens are involved. The portal flow sends already-resolved values, which
        // is fine — the cron will substitute at run time only if `variables` is set.
        scheduled_at: local.toISOString(),
      });
      toast.success("Message planifié");
      setTitle("");
      setDate("");
      setTime("");
      refresh();
      if (onScheduled) onScheduled();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setSaving(false);
    }
  };

  const cancel = async (sid) => {
    if (!window.confirm("Annuler cette planification ?")) return;
    try {
      await apiClient.delete(`/me/messaging/schedules/${sid}`);
      toast.success("Planification annulée");
      refresh();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      data-testid="schedule-modal"
    >
      <div className="w-full max-w-2xl rounded-2xl bg-white shadow-2xl flex flex-col max-h-[92vh]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200">
          <h2 className="text-lg font-display font-bold inline-flex items-center gap-2">
            <CalendarClock className="h-5 w-5 text-sawali-blue" /> Planifier un WhatsApp
          </h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900"><X className="h-4 w-4" /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          <p className="text-sm text-slate-600">
            À : <strong>{contact.name}</strong>
            <code className="text-xs bg-slate-100 px-1.5 py-0.5 rounded ml-1">{contact.whatsapp}</code>
          </p>
          {loading ? (
            <p className="text-sm text-slate-500">Chargement…</p>
          ) : !configured ? (
            <div className="rounded-lg bg-amber-50 ring-1 ring-amber-200 p-3 text-xs text-amber-900">
              WhatsApp Business API non configurée.
            </div>
          ) : (
            <>
              <Input label="Titre (facultatif)" value={title} onChange={setTitle} placeholder={`Envoi à ${contact.name}`} testid="schedule-title" />
              <div className="grid sm:grid-cols-[1fr_120px] gap-3">
                <div>
                  <label className="text-xs font-semibold block mb-1">Template</label>
                  <select
                    value={templateName}
                    onChange={(e) => {
                      setTemplateName(e.target.value);
                      const t = templates.find((x) => x.name === e.target.value);
                      if (t?.language) setLanguage(t.language);
                    }}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    data-testid="schedule-template-select"
                  >
                    {templates.map((t) => (
                      <option key={`${t.name}_${t.language}`} value={t.name}>
                        {t.name} ({t.language}){t.note_description ? ` — ${t.note_description.slice(0, 60)}` : ""}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs font-semibold block mb-1">Langue</label>
                  <input
                    value={language}
                    onChange={(e) => setLanguage(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    data-testid="schedule-language"
                  />
                </div>
              </div>
              <div className="grid sm:grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold block mb-1">Date</label>
                  <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="schedule-date" />
                </div>
                <div>
                  <label className="text-xs font-semibold block mb-1">Heure</label>
                  <input type="time" value={time} onChange={(e) => setTime(e.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="schedule-time" />
                </div>
              </div>

              {/* HEADER */}
              {parsed.header && (
                <HeaderBlock
                  header={parsed.header}
                  headerText={headerText}
                  setHeaderText={setHeaderText}
                  headerMedia={headerMedia}
                  clearMedia={() => setHeaderMedia(null)}
                  uploadHeader={async (file, existingMedia = null) => {
                    if (existingMedia?.public_url) {
                      setHeaderMedia({ link: existingMedia.public_url, kind: existingMedia.kind, filename: existingMedia.filename });
                      return;
                    }
                    if (!file) return;
                    const fd = new FormData();
                    fd.append("file", file);
                    fd.append("label", file.name || "");
                    try {
                      const r = await apiClient.post("/me/media-library", fd, { headers: { "Content-Type": "multipart/form-data" } });
                      const link = r.data?.public_url;
                      if (!link) throw new Error("URL publique manquante");
                      setHeaderMedia({ link, kind: r.data?.kind || "document", filename: r.data?.filename || file.name });
                    } catch (err) { toast.error(err?.response?.data?.detail || "Échec de l'upload"); }
                  }}
                  uploading={false}
                  tokens={tokens}
                />
              )}

              {parsed.body.text && (
                <div className="rounded-lg bg-slate-50 ring-1 ring-slate-200 p-3 text-xs text-slate-700 whitespace-pre-wrap">
                  <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Corps du template</p>
                  {parsed.body.text}
                </div>
              )}

              {parsed.body.varCount > 0 && (
                <VarGrid
                  label={`Variables du corps (${parsed.body.varCount})`}
                  values={bodyVars}
                  onChange={setBodyVars}
                  testPrefix="schedule-variable"
                  tokens={tokens}
                />
              )}

              {/* Existing schedules for THIS contact */}
              {schedules.length > 0 && (
                <div className="rounded-lg ring-1 ring-slate-200 bg-white" data-testid="schedule-list">
                  <p className="text-xs font-semibold px-3 py-2 border-b border-slate-100 text-slate-700">
                    Planifications pour ce contact ({schedules.length})
                  </p>
                  <table className="w-full text-xs">
                    <thead className="bg-slate-50 text-slate-500 uppercase text-[10px]">
                      <tr>
                        <th className="text-left px-2 py-1.5">Quand</th>
                        <th className="text-left px-2 py-1.5">Template</th>
                        <th className="text-left px-2 py-1.5">Statut</th>
                        <th className="px-2 py-1.5"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {schedules.map((s) => (
                        <tr key={s.id} className="border-t border-slate-100" data-testid={`schedule-row-${s.id}`}>
                          <td className="px-2 py-1.5 whitespace-nowrap text-slate-700">
                            {s.scheduled_at ? new Date(s.scheduled_at).toLocaleString("fr-FR") : "—"}
                          </td>
                          <td className="px-2 py-1.5 font-mono text-[11px] text-slate-700">{s.template_name}</td>
                          <td className="px-2 py-1.5">
                            <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                              s.status === "pending" ? "bg-amber-100 text-amber-800"
                                : s.status === "running" ? "bg-sky-100 text-sky-800"
                                : s.status === "done" ? "bg-emerald-100 text-emerald-800"
                                : s.status === "failed" ? "bg-rose-100 text-rose-800"
                                : "bg-slate-200 text-slate-700"
                            }`}>{s.status}</span>
                          </td>
                          <td className="px-2 py-1.5 text-right">
                            {(s.status === "pending" || s.status === "running") && (
                              <button onClick={() => cancel(s.id)} className="text-rose-600 hover:text-rose-800" data-testid={`schedule-cancel-${s.id}`}>
                                <Trash className="h-3.5 w-3.5" />
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
        <div className="flex justify-end gap-2 px-5 py-3 border-t border-slate-200">
          <button onClick={onClose} className="text-sm rounded-lg bg-slate-100 hover:bg-slate-200 px-4 py-2">Fermer</button>
          <button
            onClick={create}
            disabled={saving || !configured || templates.length === 0}
            className="inline-flex items-center gap-1.5 text-sm rounded-lg bg-sawali-blue hover:bg-sawali-blue-light text-white px-4 py-2 disabled:opacity-50"
            data-testid="schedule-create-btn"
          >
            <CalendarClock className="h-4 w-4" /> {saving ? "Planification…" : "Planifier"}
          </button>
        </div>
      </div>
    </div>
  );
};




// --- SMS send modal (free-text + tokens + payment link inserter) ---
const SmsModal = ({ contact, onClose, onSent, userRole }) => {
  const [providers, setProviders] = useState({ default: "auto", active: [] });
  const [provider, setProvider] = useState("auto");
  const [message, setMessage] = useState("");
  const [sender, setSender] = useState("");
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => {
    apiClient.get("/me/sms/providers").then((r) => {
      setProviders(r.data || { active: [] });
      setProvider(r.data?.default || "auto");
    }).catch(() => {});
  }, []);

  const send = async () => {
    if (!message.trim()) { toast.error("Message vide"); return; }
    if (message.length > 800) { toast.error("Message trop long"); return; }
    const target = contact.phone || contact.whatsapp;
    if (!target) { toast.error("Aucun numéro disponible"); return; }
    setSending(true); setResult(null);
    try {
      const r = await apiClient.post("/me/sms/send", {
        to: target,
        message,
        provider,
        sender: sender || undefined,
        contact_id: contact.id,
      });
      setResult(r.data);
      if (r.data?.ok) {
        toast.success("SMS envoyé via " + safeText(r.data?.provider) || "?");
        if (onSent) onSent();
      } else {
        toast.error(safeText(r.data?.error) || "Échec d'envoi");
      }
    } catch (err) {
      toast.error(safeText(err?.response?.data?.detail) || "Erreur");
    } finally { setSending(false); }
  };

  // Wrap the inserter — SMS uses a single body string, not variables. We
  // pass a 1-slot bodyVars and append the URL on insert.
  const insertLink = (url) => {
    setMessage((m) => (m ? m.replace(/\s*$/, "") + "\n" + url : url));
    toast.success("Lien collé dans le message");
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40" onClick={(e) => e.target === e.currentTarget && onClose()} data-testid="sms-modal">
      <div className="w-full max-w-lg rounded-2xl bg-white shadow-2xl flex flex-col max-h-[92vh]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 bg-amber-50">
          <h2 className="text-lg font-display font-bold inline-flex items-center gap-2">
            <Send className="h-5 w-5 text-amber-600" /> Envoyer un SMS
          </h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900"><X className="h-4 w-4" /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
          <p className="text-sm text-slate-600">
            À : <strong>{contact.name}</strong>
            <code className="text-xs bg-slate-100 px-1.5 py-0.5 rounded ml-1">{contact.phone || contact.whatsapp}</code>
          </p>
          {providers.active.length === 0 ? (
            <div className="rounded-lg ring-1 ring-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
              Aucun fournisseur SMS configuré. Contactez votre administrateur (paramètres SMS Orange / Moov / Telecel / OVH).
            </div>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-2">
                <label className="text-xs font-semibold">
                  Fournisseur
                  <select value={provider} onChange={(e) => setProvider(e.target.value)} className="w-full mt-1 rounded-lg border border-slate-300 px-2 py-1.5 text-sm" data-testid="sms-provider-select">
                    <option value="auto">Auto (selon préfixe)</option>
                    {providers.active.map((p) => (
                      <option key={p} value={p}>
                        {p === "bird" ? "📡 Bird.com" : p.toUpperCase()}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="text-xs font-semibold">
                  Expéditeur (optionnel)
                  <input value={sender} onChange={(e) => setSender(e.target.value)} maxLength={11} placeholder="SAWALI"
                    className="w-full mt-1 rounded-lg border border-slate-300 px-2 py-1.5 text-sm" data-testid="sms-sender" />
                </label>
              </div>
              <div>
                <label className="text-xs font-semibold flex items-center justify-between">
                  <span>Message ({message.length}/800)</span>
                  <PaymentLinkInserter
                    bodyVars={[]}
                    setBodyVars={() => {}}
                    insertCallback={insertLink}
                  />
                </label>
                <textarea
                  value={message}
                  onChange={(e) => setMessage(e.target.value.slice(0, 800))}
                  rows={6}
                  placeholder="Bonjour, voici votre facture du mois…"
                  className="w-full mt-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  data-testid="sms-message"
                />
                <p className="text-[10px] text-slate-400 mt-0.5">
                  Astuce : utilisez le bouton « Insérer un lien de paiement » pour ajouter un lien <code>/pay/&#123;slug&#125;</code>.
                </p>
              </div>
            </>
          )}
          {result && (
            <div className={`rounded-lg ring-1 p-3 text-xs ${result.ok ? "bg-emerald-50 ring-emerald-200 text-emerald-900" : "bg-rose-50 ring-rose-300 text-rose-900"}`} data-testid="sms-result">
              {result.ok
                ? <><strong>Envoyé !</strong> Via : {safeText(result.provider) || "?"} (HTTP {safeText(result.http_status)})</>
                : <><strong>Échec :</strong> {safeText(result.error) || "Erreur inconnue"} {result.http_status ? `(HTTP ${safeText(result.http_status)})` : ""}</>
              }
            </div>
          )}
          {/* Iter43-fix24az-d — Quick contact-group toggler (admin/superviseur/modérateur) */}
          <ContactGroupChips contact={contact} userRole={userRole} />
        </div>
        <div className="flex justify-end gap-2 px-5 py-3 border-t border-slate-200">
          <button onClick={onClose} className="text-sm rounded-lg bg-slate-100 hover:bg-slate-200 px-4 py-2">Fermer</button>
          <button onClick={send} disabled={sending || providers.active.length === 0}
            className="inline-flex items-center gap-1.5 text-sm rounded-lg bg-amber-600 hover:bg-amber-700 text-white px-4 py-2 disabled:opacity-50"
            data-testid="sms-send-btn">
            <Send className="h-4 w-4" /> {sending ? "Envoi…" : "Envoyer"}
          </button>
        </div>
      </div>
    </div>
  );
};


// --- Payment Link Inserter (used inside WhatsApp & SMS modals) ---
// Lets the user pick (or create on the fly) a payment link, then injects
// the public URL (https://…/pay/{slug}) either into a chosen template
// variable (WA flow) or via a callback (SMS flow — appends to the body).
const PaymentLinkInserter = ({ bodyVars, setBodyVars, insertCallback }) => {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState("existing"); // existing | quick
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [chosenUrl, setChosenUrl] = useState(null);
  // Quick create form
  const [features, setFeatures] = useState({});
  const [allowedMnos, setAllowedMnos] = useState([]);
  const [label, setLabel] = useState("");
  const [amount, setAmount] = useState("");
  const [openAmount, setOpenAmount] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/me/payment-links");
      setItems((r.data || []).filter((l) => l.status === "active"));
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setLoading(false);
    }
  };

  const loadFeatures = async () => {
    try {
      const r = await apiClient.get("/me/features");
      setFeatures(r.data?.features || {});
      const mnos = r.data?.pawapay_mnos || [];
      setAllowedMnos(mnos);
    } catch { /* noop */ }
  };

  const onOpen = () => {
    setOpen(true);
    setChosenUrl(null);
    setLabel("");
    setAmount("");
    setOpenAmount(false);
    load();
    loadFeatures();
  };

  const publicPayUrl = (slug) => `${window.location.origin}/pay/${slug}`;

  // When a callback flow is used (e.g. SMS), insert immediately and close.
  const handlePicked = (url) => {
    if (insertCallback) {
      insertCallback(url);
      setOpen(false);
    } else {
      setChosenUrl(url);
    }
  };

  const insertIntoVar = (i) => {
    if (!chosenUrl) return;
    const next = [...bodyVars];
    next[i] = chosenUrl;
    setBodyVars(next);
    setOpen(false);
    toast.success(`Lien collé dans la variable {{${i + 1}}}`);
  };

  const quickCreate = async () => {
    if (!label.trim()) { toast.error("Libellé requis"); return; }
    if (!openAmount) {
      const a = parseFloat(amount);
      if (!a || a <= 0) { toast.error("Montant invalide"); return; }
    }
    if (allowedMnos.length === 0) { toast.error("Aucun opérateur disponible"); return; }
    setSubmitting(true);
    try {
      const r = await apiClient.post("/me/payment-links", {
        label: label.trim(),
        amount: openAmount ? null : parseFloat(amount),
        allowed_mnos: allowedMnos,
      });
      const url = publicPayUrl(r.data?.slug);
      if (insertCallback) {
        insertCallback(url);
        setOpen(false);
      } else {
        setChosenUrl(url);
        toast.success("Lien créé. Choisissez une variable où l'insérer.");
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div data-testid="wa-payment-link-inserter">
      <button
        type="button"
        onClick={onOpen}
        className="inline-flex items-center gap-1.5 text-xs rounded-lg ring-1 ring-amber-300 bg-amber-50 hover:bg-amber-100 text-amber-800 px-3 py-1.5"
        data-testid="wa-pay-link-btn"
      >
        <Link2 className="h-3.5 w-3.5" /> Insérer un lien de paiement
      </button>

      {open && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4" onClick={(e) => e.target === e.currentTarget && setOpen(false)} data-testid="wa-pay-link-modal">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[88vh] flex flex-col">
            <div className="flex items-center justify-between px-5 py-3 border-b bg-amber-50">
              <h3 className="font-display font-bold inline-flex items-center gap-2">
                <CreditCard className="h-4 w-4 text-amber-600" /> Lien de paiement
              </h3>
              <button onClick={() => setOpen(false)} className="text-slate-500"><X className="h-4 w-4" /></button>
            </div>

            {/* Step 1 — pick or create */}
            {!chosenUrl ? (
              <>
                <div className="flex border-b border-slate-200">
                  <button onClick={() => setTab("existing")} className={`flex-1 py-2 text-sm ${tab === "existing" ? "border-b-2 border-amber-600 text-amber-700 font-semibold" : "text-slate-500"}`} data-testid="wa-pay-tab-existing">
                    Liens actifs ({items.length})
                  </button>
                  <button onClick={() => setTab("quick")} className={`flex-1 py-2 text-sm ${tab === "quick" ? "border-b-2 border-amber-600 text-amber-700 font-semibold" : "text-slate-500"}`} data-testid="wa-pay-tab-quick">
                    Nouveau lien rapide
                  </button>
                </div>
                <div className="flex-1 overflow-y-auto p-4 space-y-3">
                  {tab === "existing" ? (
                    loading ? <p className="text-sm text-slate-400 italic">Chargement…</p> :
                    items.length === 0 ? <p className="text-sm text-slate-400 italic">Aucun lien actif. Créez-en un dans l'onglet « Nouveau lien rapide ».</p> :
                    items.map((l) => (
                      <button
                        key={l.id}
                        onClick={() => handlePicked(publicPayUrl(l.slug))}
                        className="w-full text-left rounded-lg ring-1 ring-slate-200 hover:ring-amber-400 hover:bg-amber-50 p-3 transition"
                        data-testid={`wa-pay-pick-${l.slug}`}
                      >
                        <div className="font-semibold text-sm text-slate-800">{l.label}</div>
                        <div className="text-xs text-slate-500 flex items-center gap-2 mt-0.5">
                          {l.amount != null ? (
                            <span className="font-mono">{Number(l.amount).toLocaleString("fr-FR")} {l.currency || "XOF"}</span>
                          ) : (
                            <span className="italic text-amber-700">montant libre</span>
                          )}
                          <span>•</span>
                          <span>{(l.allowed_mnos || []).join(" / ")}</span>
                          <span>•</span>
                          <span>{l.uses_count || 0}{l.max_uses ? `/${l.max_uses}` : "/∞"} usages</span>
                        </div>
                      </button>
                    ))
                  ) : (
                    <>
                      <div>
                        <label className="text-xs font-semibold block mb-1">Libellé / référence *</label>
                        <input value={label} onChange={(e) => setLabel(e.target.value)} maxLength={120} placeholder="Facture #2025-001"
                          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="wa-pay-quick-label" />
                      </div>
                      <div className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200">
                        <label className="flex items-center gap-2 text-xs font-semibold cursor-pointer">
                          <input type="checkbox" checked={openAmount} onChange={(e) => setOpenAmount(e.target.checked)} data-testid="wa-pay-quick-open" />
                          Montant libre (le payeur saisit)
                        </label>
                        {!openAmount && (
                          <div className="mt-2">
                            <label className="text-[10px] uppercase tracking-wider text-slate-500 block">Montant fixe (XOF)</label>
                            <input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="5000"
                              className="w-full mt-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" data-testid="wa-pay-quick-amount" />
                          </div>
                        )}
                      </div>
                      <p className="text-[10px] text-slate-500">
                        Opérateurs autorisés (hérité du client) : {allowedMnos.join(", ") || "aucun"}.
                        {!features.payments && <span className="block text-rose-600 mt-1">⚠ Paiements non activés pour votre compte.</span>}
                      </p>
                      <button onClick={quickCreate} disabled={submitting || !features.payments || allowedMnos.length === 0}
                        className="w-full inline-flex items-center justify-center gap-1.5 text-sm rounded-lg bg-amber-600 hover:bg-amber-700 text-white px-4 py-2 disabled:opacity-50"
                        data-testid="wa-pay-quick-create-btn">
                        <Link2 className="h-4 w-4" /> {submitting ? "Création…" : "Créer le lien"}
                      </button>
                    </>
                  )}
                </div>
              </>
            ) : (
              /* Step 2 — choose variable slot */
              <div className="flex-1 overflow-y-auto p-4 space-y-3">
                <p className="text-sm text-slate-700">
                  Lien sélectionné :
                  <code className="block text-[11px] bg-slate-100 px-2 py-1 rounded mt-1 break-all">{chosenUrl}</code>
                </p>
                <p className="text-xs font-semibold text-slate-700 mt-3">Coller dans quelle variable ?</p>
                <div className="grid grid-cols-3 gap-2">
                  {bodyVars.map((_, i) => (
                    <button
                      key={i}
                      onClick={() => insertIntoVar(i)}
                      className="rounded-lg ring-1 ring-slate-300 hover:ring-amber-500 hover:bg-amber-50 px-3 py-3 text-sm font-mono"
                      data-testid={`wa-pay-target-var-${i}`}
                    >
                      {`{{${i + 1}}}`}
                    </button>
                  ))}
                </div>
                <button
                  onClick={() => setChosenUrl(null)}
                  className="text-xs text-slate-500 hover:underline mt-2"
                  data-testid="wa-pay-back-btn"
                >
                  ← Choisir un autre lien
                </button>
              </div>
            )}

            <div className="flex justify-end gap-2 px-5 py-3 border-t bg-slate-50">
              <button onClick={() => setOpen(false)} className="text-sm rounded-lg bg-white ring-1 ring-slate-300 hover:bg-slate-100 px-4 py-2">Fermer</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};


// ====================================================================
// Pending WA imports — yellow banner that lists unknown numbers that have
// written to our WhatsApp Business line but aren't in the directory yet.
// One-click "Importer" to promote them as full contacts.
// ====================================================================
const PendingImportsBanner = ({ items, onChange }) => {
  const [busy, setBusy] = useState({});
  const importOne = async (it) => {
    setBusy((b) => ({ ...b, [it.id]: true }));
    try {
      await apiClient.post(`/me/wa-pending-imports/${it.id}/import`, {});
      toast.success(`Contact « ${it.wa_profile_name || it.from} » importé`);
      onChange && onChange();
    } catch (err) {
      toast.error(safeText(err?.response?.data?.detail) || "Erreur");
    } finally {
      setBusy((b) => ({ ...b, [it.id]: false }));
    }
  };
  const dismissOne = async (it) => {
    if (!window.confirm("Ignorer ce numéro ? Il ne réapparaîtra que s'il vous écrit à nouveau.")) return;
    setBusy((b) => ({ ...b, [it.id]: true }));
    try {
      await apiClient.delete(`/me/wa-pending-imports/${it.id}`);
      toast.success("Ignoré");
      onChange && onChange();
    } catch (err) {
      toast.error(safeText(err?.response?.data?.detail) || "Erreur");
    } finally {
      setBusy((b) => ({ ...b, [it.id]: false }));
    }
  };
  return (
    <div className="rounded-xl ring-1 ring-amber-200 bg-amber-50 p-4 space-y-2" data-testid="pending-imports-banner">
      <p className="text-sm font-semibold text-amber-900 inline-flex items-center gap-2">
        <Inbox className="h-4 w-4" /> {items.length} contact(s) inconnu(s) vous ont écrit sur WhatsApp
      </p>
      <p className="text-[11px] text-amber-800">Importez-les en un clic pour démarrer la conversation depuis le portail.</p>
      <ul className="space-y-1.5 mt-1.5">
        {items.map((it) => (
          <li
            key={it.id}
            className="flex items-center justify-between gap-3 rounded-lg bg-white ring-1 ring-amber-200 px-3 py-2 text-sm"
            data-testid={`pending-import-${it.id}`}
          >
            <div className="min-w-0 flex-1">
              <p className="font-semibold text-slate-900 truncate">
                {it.wa_profile_name || "Sans nom WhatsApp"}
              </p>
              <p className="text-[11px] text-slate-500 font-mono">+{it.phone_digits}</p>
              {it.last_message && (
                <p className="text-[11px] text-slate-600 italic truncate mt-0.5" title={it.last_message}>
                  « {it.last_message} »
                </p>
              )}
              <p className="text-[10px] text-slate-400 mt-0.5">
                {it.messages_count || 1} message(s) • dernier {fmtDate(it.last_seen_at)}
              </p>
            </div>
            <div className="flex items-center gap-1.5 flex-shrink-0">
              <button
                onClick={() => importOne(it)}
                disabled={!!busy[it.id]}
                className="inline-flex items-center gap-1 text-[11px] rounded bg-emerald-600 text-white px-2.5 py-1.5 hover:bg-emerald-700 disabled:opacity-40"
                data-testid={`pending-import-btn-${it.id}`}
              >
                <UserPlus className="h-3 w-3" /> Importer
              </button>
              <button
                onClick={() => dismissOne(it)}
                disabled={!!busy[it.id]}
                className="inline-flex items-center gap-1 text-[11px] rounded ring-1 ring-slate-300 text-slate-600 hover:bg-slate-50 px-2.5 py-1.5 disabled:opacity-40"
                data-testid={`pending-dismiss-btn-${it.id}`}
              >
                <X className="h-3 w-3" /> Ignorer
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
};
