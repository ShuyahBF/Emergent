import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { Plus, Edit, Trash2, X, Star, StarOff, Settings, Edit2, Check, Upload, Activity, MessageCircle, Send, RefreshCw, Inbox, ShieldCheck, Link2, Building2, Users as UsersIcon, Wrench, Wallet } from "lucide-react";
import { toast } from "sonner";
import IconPicker, { CategoryIcon } from "@/components/IconPicker";

const empty = { email: "", full_name: "", password: "", phone: "", whatsapp_number: "", company: "", client_code: "", category_slug: "", country: "", city: "", logo_url: "", account_status: "active", role: "client", wa_unit_cost: 0, wa_currency: "XOF", link_to_client_id: null, hourly_rate: 0, flat_rate: 0, can_cash: false, tenant_sharing_mode: "AND", business_type: "", contract_number: "", contract_signed_at: "", contract_amount: "", contract_currency: "XOF", last_payment_at: "", contract_overdue_days: "", payment_confirmation_template: "", contract_billing_period: "", auto_suspend_after_overdue_days: "" };

export default function AdminClients() {
  const [items, setItems] = useState([]);
  // Iter34q — Active role filter for the quick-filter pills above the table.
  // "all" shows every group; a specific role narrows down to that group only.
  const [roleFilter, setRoleFilter] = useState("all");
  // Iter38r-fix9v — Source filter (e.g. "wa_otp_login" for WA-onboarded users)
  // + sort by created_at / last_login_at / full_name
  const [sourceFilter, setSourceFilter] = useState("all");
  const [sortBy, setSortBy] = useState("");      // "" | created_at | last_login_at | full_name
  const [sortOrder, setSortOrder] = useState("desc");
  const [categories, setCategories] = useState([]);
  const [isOpen, setIsOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(empty);
  const [loading, setLoading] = useState(false);
  const [catManagerOpen, setCatManagerOpen] = useState(false);
  const [waStats, setWaStats] = useState(null); // {client_id, full_name} object → triggers modal
  // iter32 — Auto-suggest canonical client when a known `company` is typed
  const [companyHint, setCompanyHint] = useState(null);
  const [hintLoading, setHintLoading] = useState(false);
  // 2026-02 fork iter104 — Global overdue threshold (fetched once from settings).
  const [overdueDefault, setOverdueDefault] = useState(5);
  // 2026-02 fork iter104 — Payment History modal state.
  const [paymentsFor, setPaymentsFor] = useState(null); // client object or null

  useEffect(() => {
    apiClient.get("/admin/settings").then((r) => {
      const v = r.data?.contract_overdue_days_default;
      if (v && Number(v) > 0) setOverdueDefault(Number(v));
    }).catch(() => {});
  }, []);

  // Trigger hint lookup on company blur (or when editing existing user, skip).
  // The endpoint is admin-only and returns the canonical user for that name
  // if any exists. Call only on CREATE flows to avoid noise when editing.
  const checkCompany = async (name) => {
    if (editing?.id) return;  // editing existing — no auto-link
    if (!name || !name.trim()) { setCompanyHint(null); return; }
    setHintLoading(true);
    try {
      const r = await apiClient.get("/admin/resolve-company", { params: { company: name.trim() } });
      // Only show banner if the canonical is NOT this same draft user
      if (r.data?.found && r.data?.canonical_user) {
        setCompanyHint(r.data);
      } else {
        setCompanyHint(null);
      }
    } catch { setCompanyHint(null); } finally { setHintLoading(false); }
  };

  const load = () => {
    const params = {};
    if (sourceFilter && sourceFilter !== "all") params.source = sourceFilter;
    if (sortBy) { params.sort_by = sortBy; params.sort_order = sortOrder; }
    return apiClient.get("/admin/clients", { params }).then((r) => setItems(r.data));
  };
  const loadCats = () => apiClient.get("/admin/client-categories").then((r) => setCategories(r.data));
  useEffect(() => {
    load().catch(() => {});
    loadCats().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceFilter, sortBy, sortOrder]);

  const catOf = (slug) => categories.find((c) => c.slug === slug);

  // 2026-02 fork iter103 — Payment-delay helper for the Retard column.
  // Uses `last_payment_at` if set, else `contract_signed_at`. Returns
  // `{ days, ref, refField }` OR `null` when no reference date is available.
  const formatMoney = (amount, currency) => {
    if (amount == null || amount === "" || Number.isNaN(Number(amount))) return null;
    try {
      return new Intl.NumberFormat("fr-FR", { style: "currency", currency: currency || "XOF", maximumFractionDigits: 0 }).format(Number(amount));
    } catch {
      return `${Number(amount).toLocaleString("fr-FR")} ${currency || ""}`.trim();
    }
  };
  const computePaymentDelay = (c) => {
    const refIso = c.last_payment_at || c.contract_signed_at || null;
    if (!refIso) return null;
    const d = new Date(refIso);
    if (Number.isNaN(d.getTime())) return null;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const start = new Date(d);
    start.setHours(0, 0, 0, 0);
    const days = Math.max(0, Math.floor((today.getTime() - start.getTime()) / 86400000));
    // 2026-02 fork iter104 — Threshold : per-client override > global setting > 5.
    const threshold = Math.max(1, Number(c.contract_overdue_days) || Number(overdueDefault) || 5);
    return {
      days,
      refIso,
      refField: c.last_payment_at ? "last_payment_at" : "contract_signed_at",
      threshold,
      overdue: days >= threshold,
    };
  };

  // Iter34p — Group rows by role with a fixed display order. Each section
  // gets a labelled header above the user rows so the admin can scan
  // categories at a glance (Admins, Superviseurs, Clients, Modérateurs…).
  // Iter34q adds a role-level filter so the admin can narrow the view.
  const ROLE_ORDER = useMemo(() => [
    { role: "admin", label: "Admins clients", color: "#b45309", bg: "bg-amber-50", ring: "ring-amber-200", text: "text-amber-700" },
    { role: "superviseur", label: "Superviseurs", color: "#1E90FF", bg: "bg-sky-50", ring: "ring-sky-200", text: "text-sky-700" },
    { role: "client", label: "Clients", color: "#475569", bg: "bg-slate-50", ring: "ring-slate-200", text: "text-slate-700" },
    { role: "moderateur", label: "Modérateurs", color: "#a21caf", bg: "bg-fuchsia-50", ring: "ring-fuchsia-200", text: "text-fuchsia-700" },
    // Iter35h — Demo accounts (limited features, expiration date)
    { role: "demo", label: "Démos", color: "#d97706", bg: "bg-orange-50", ring: "ring-orange-200", text: "text-orange-700" },
    // Iter42c (2026-02) — Rôles métier pharmaceutiques
    { role: "regulateur", label: "💊 Régulateurs", color: "#e11d48", bg: "bg-rose-50", ring: "ring-rose-200", text: "text-rose-700" },
    { role: "pharmacien", label: "💊 Pharmaciens", color: "#0d9488", bg: "bg-teal-50", ring: "ring-teal-200", text: "text-teal-700" },
    { role: "medecin", label: "⚕️ Médecins", color: "#2563eb", bg: "bg-blue-50", ring: "ring-blue-200", text: "text-blue-700" },
    { role: "editeur_vidal", label: "📚 Éditeurs VIDAL", color: "#7c3aed", bg: "bg-violet-50", ring: "ring-violet-200", text: "text-violet-700" },
  ], []);

  const roleCounts = useMemo(() => {
    const counts = { all: items.length, other: 0 };
    ROLE_ORDER.forEach((g) => { counts[g.role] = 0; });
    items.forEach((c) => {
      if (counts[c.role] != null) counts[c.role]++;
      else counts.other++;
    });
    return counts;
  }, [items, ROLE_ORDER]);

  const groupedByRole = useMemo(() => {
    const fallback = { role: "other", label: "Autres rôles", color: "#64748b", rows: [] };
    const groups = ROLE_ORDER.map((g) => ({ ...g, rows: [] }));
    items.forEach((c) => {
      const target = groups.find((g) => g.role === c.role) || fallback;
      target.rows.push(c);
    });
    const all = [...groups, fallback].filter((g) => g.rows.length > 0);
    if (roleFilter === "all") return all;
    return all.filter((g) => g.role === roleFilter);
  }, [items, roleFilter, ROLE_ORDER]);

  const open = (it = null) => {
    setEditing(it);
    // S-iter39a — Pre-fill link_to_client_id from existing parent_client_id so
    // the "Client lié" dropdown shows the current value when editing.
    setForm(it ? { ...empty, ...it, password: "", link_to_client_id: it.parent_client_id || "" } : empty);
    setCompanyHint(null);
    setIsOpen(true);
  };
  const close = () => { setIsOpen(false); setEditing(null); setForm(empty); setCompanyHint(null); };

  const submit = async (e) => {
    e.preventDefault(); setLoading(true);
    // 2026-02 fork iter103 — Normaliser les champs contrat : chaîne vide → null,
    // montant vide → null (sinon Pydantic → 422 sur `contract_amount = ""`).
    const normContract = (f) => {
      const out = { ...f };
      for (const k of ["contract_number", "contract_signed_at", "contract_currency", "last_payment_at", "payment_confirmation_template"]) {
        if (out[k] === "" || out[k] === undefined) out[k] = null;
      }
      const amt = out.contract_amount;
      if (amt === "" || amt === null || amt === undefined) out.contract_amount = null;
      else if (typeof amt === "string") out.contract_amount = Number(amt) || 0;
      const od = out.contract_overdue_days;
      if (od === "" || od === null || od === undefined) out.contract_overdue_days = null;
      else out.contract_overdue_days = Math.max(1, Number(od) || 5);
      // 2026-02 fork iter108 — S159 : sanitize auto_suspend_after_overdue_days
      const susp = out.auto_suspend_after_overdue_days;
      if (susp === "" || susp === null || susp === undefined) out.auto_suspend_after_overdue_days = null;
      else out.auto_suspend_after_overdue_days = Math.max(1, Number(susp) || 30);
      // 2026-02 fork iter108 — S158 : normalize billing period
      const bp = (out.contract_billing_period || "").toLowerCase();
      out.contract_billing_period = ["monthly", "quarterly", "annual"].includes(bp) ? bp : null;
      return out;
    };
    try {
      if (editing?.id) {
        const payload = normContract({ ...form });
        if (!payload.password) delete payload.password;
        const r = await apiClient.put(`/admin/clients/${editing.id}`, payload);
        toast.success("Client mis à jour");
        // Iter34n — Surface the auto-realign guard rail when the admin
        // edits a user's `company` field. If the parent_client_id was
        // stale (rabo.f-style bug) we either auto-fixed it or detected an
        // unresolvable typo that the admin needs to address.
        const ar = r?.data?.auto_realign;
        if (ar?.applied) {
          toast.success(
            `Pointeur parent recalibré automatiquement sur "${ar.to_company || "client canonique"}" (${ar.actions_count} action${ar.actions_count > 1 ? "s" : ""}).`,
            { duration: 7000 }
          );
        } else if (ar && ar.reason === "no_canonical_for_company") {
          toast.warning(
            `Société "${ar.typed_company}" sans client canonique trouvé. Vérifiez l'orthographe ou désignez un Client Primaire pour cette société.`,
            { duration: 9000 }
          );
        }
      } else {
        await apiClient.post("/admin/clients", normContract(form));
        toast.success("Client créé");
      }
      close(); await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setLoading(false); }
  };

  const del = async (id) => {
    if (!window.confirm("Supprimer ce client ?")) return;
    await apiClient.delete(`/admin/clients/${id}`);
    toast.success("Client supprimé");
    await load();
  };

  const setPrimary = async (id) => {
    if (!window.confirm("Désigner ce client comme Client Primaire ? Il sera automatiquement promu Superviseur.")) return;
    try {
      await apiClient.post(`/admin/clients/${id}/set-primary`);
      toast.success("Client primaire défini");
      await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const unsetPrimary = async (id) => {
    if (!window.confirm("Retirer le statut Client Primaire ? Le rôle reviendra à 'Client'.")) return;
    try {
      await apiClient.post(`/admin/clients/${id}/unset-primary`);
      toast.success("Statut retiré");
      await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  // Bug #3 (2026-02 — rabo.f) — Repair the directory_contacts row for a user.
  // Useful when an admin/superviseur/moderateur whose number sends WhatsApp
  // messages doesn't appear in /portal/contacts (or appears nameless).
  const repairContact = async (c) => {
    if (!c?.email) { toast.error("Email manquant"); return; }
    if (!c?.phone) {
      toast.error("Cet utilisateur n'a pas de numéro de téléphone. Renseignez-le d'abord.");
      return;
    }
    if (!window.confirm(
      `Réparer le contact de "${c.full_name || c.email}" ?\n\n` +
      `• Crée/corrige la ligne directory_contacts dans le bon tenant.\n` +
      `• Ré-attache les WhatsApp orphelins.\n` +
      `• Supprime les wa_pending_imports correspondants.\n\n` +
      `Action idempotente, sans destruction de données.`
    )) return;
    try {
      const r = await apiClient.post("/admin/contacts/repair-user-contact", { email: c.email });
      const actions = r?.data?.actions || [];
      const summary = actions.map((a) => a.type).join(", ") || "aucune action nécessaire";
      toast.success(
        `Contact réparé : ${r?.data?.canonical_contact_name || c.full_name}\n` +
        `Actions : ${summary}`,
        { duration: 9000 }
      );
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur lors de la réparation");
    }
  };

  return (
    <div className="space-y-6" data-testid="admin-clients-page">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-display font-bold">Clients</h1>
          <p className="text-sm text-slate-500">Gérez les comptes des clients ayant accès au portail.</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setCatManagerOpen(true)} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white text-slate-700 hover:border-sawali-blue hover:text-sawali-blue px-3.5 py-2 text-sm" data-testid="manage-client-categories-btn">
            <Settings className="h-4 w-4" /> Catégories
          </button>
          <button onClick={() => open()} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light" data-testid="new-client-button">
            <Plus className="h-4 w-4" /> Nouveau client
          </button>
        </div>
      </div>

      {/* Iter34q — Quick role filter pills with live counts */}
      <div className="flex items-center gap-2 flex-wrap" data-testid="clients-role-filter">
        <button
          onClick={() => setRoleFilter("all")}
          className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold ring-1 transition-colors ${roleFilter === "all" ? "bg-slate-900 text-white ring-slate-900" : "bg-white text-slate-600 ring-slate-200 hover:bg-slate-50"}`}
          data-testid="role-filter-all"
        >
          Tous
          <span className={`rounded-full px-1.5 py-0.5 text-[10px] tabular-nums ${roleFilter === "all" ? "bg-white/20" : "bg-slate-100"}`}>{roleCounts.all}</span>
        </button>
        {ROLE_ORDER.filter((g) => roleCounts[g.role] > 0).map((g) => {
          const active = roleFilter === g.role;
          return (
            <button
              key={g.role}
              onClick={() => setRoleFilter(g.role)}
              className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold ring-1 transition-colors ${active ? `${g.bg} ${g.text} ring-current` : "bg-white text-slate-600 ring-slate-200 hover:" + g.bg}`}
              style={active ? { borderColor: g.color } : undefined}
              data-testid={`role-filter-${g.role}`}
              title={`Afficher uniquement les ${g.label}`}
            >
              <UsersIcon className="h-3 w-3" />
              {g.label}
              <span className={`rounded-full px-1.5 py-0.5 text-[10px] tabular-nums ${active ? "bg-white/70" : "bg-slate-100"}`}>{roleCounts[g.role]}</span>
            </button>
          );
        })}
        {roleCounts.other > 0 && (
          <button
            onClick={() => setRoleFilter("other")}
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold ring-1 transition-colors ${roleFilter === "other" ? "bg-slate-100 text-slate-700 ring-slate-300" : "bg-white text-slate-600 ring-slate-200 hover:bg-slate-50"}`}
            data-testid="role-filter-other"
          >
            Autres
            <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] tabular-nums">{roleCounts.other}</span>
          </button>
        )}
      </div>

      {/* Iter38r-fix9v — Source filter + sort order */}
      <div className="flex flex-wrap items-center gap-2 -mt-2 mb-2">
        <span className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">Source :</span>
        <button
          onClick={() => setSourceFilter("all")}
          className={`inline-flex items-center rounded-full px-3 py-1 text-xs ring-1 ${sourceFilter === "all" ? "bg-slate-900 text-white ring-slate-900" : "bg-white text-slate-600 ring-slate-200 hover:bg-slate-50"}`}
          data-testid="source-filter-all"
        >Toutes</button>
        <button
          onClick={() => setSourceFilter("wa_otp_login")}
          className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs ring-1 ${sourceFilter === "wa_otp_login" ? "bg-emerald-600 text-white ring-emerald-600" : "bg-white text-emerald-700 ring-emerald-300 hover:bg-emerald-50"}`}
          data-testid="source-filter-wa"
          title="Filtrer les comptes créés via login WhatsApp OTP"
        >📱 WhatsApp OTP</button>

        <span className="ml-4 text-[11px] uppercase tracking-wider text-slate-500 font-semibold">Trier :</span>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
          className="text-xs rounded-full ring-1 ring-slate-200 bg-white px-3 py-1"
          data-testid="sort-by-select"
        >
          <option value="">Par défaut</option>
          <option value="created_at">Date de création</option>
          <option value="last_login_at">Dernière connexion</option>
          <option value="full_name">Nom (alphabétique)</option>
        </select>
        {sortBy && (
          <button
            onClick={() => setSortOrder((o) => o === "asc" ? "desc" : "asc")}
            className="text-xs rounded-full ring-1 ring-slate-200 bg-white px-3 py-1 hover:bg-slate-50"
            data-testid="sort-order-toggle"
            title="Inverser l'ordre"
          >{sortOrder === "asc" ? "↑ Asc" : "↓ Desc"}</button>
        )}
      </div>

      <div className="rounded-xl border border-slate-200 bg-white overflow-x-auto">
        <table className="w-full text-sm min-w-[1100px]">
          <thead className="bg-slate-50 text-xs uppercase text-slate-600">
            <tr>
              <th className="text-left px-4 py-3">Nom</th>
              <th className="text-left px-4 py-3">Email</th>
              <th className="text-left px-4 py-3">Catégorie</th>
              <th className="text-left px-4 py-3">Pays</th>
              <th className="text-left px-4 py-3">Rôle</th>
              <th className="text-left px-4 py-3">Statut</th>
              <th className="text-left px-4 py-3">N° Contrat</th>
              <th className="text-left px-4 py-3">Retard</th>
              <th className="text-right px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={9} className="px-4 py-10 text-center text-slate-500">Aucun client.</td></tr>}
            {items.length > 0 && groupedByRole.length === 0 && (
              <tr><td colSpan={9} className="px-4 py-10 text-center text-slate-500">Aucun client dans cette catégorie de rôle.</td></tr>
            )}
            {groupedByRole.map(({ role, label, color, rows }) => (
              <React.Fragment key={role}>
                <tr className="bg-gradient-to-r from-sky-100/80 via-sky-50/60 to-transparent">
                  <td colSpan={9} className="px-4 py-2">
                    <div className="inline-flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-sawali-blue" data-testid={`clients-group-${role}`}>
                      <UsersIcon className="h-3.5 w-3.5" />
                      <span>{label}</span>
                      <span className="rounded-full bg-white ring-1 ring-slate-200 px-2 py-0.5 text-slate-700 text-[10px] tabular-nums">{rows.length}</span>
                    </div>
                  </td>
                </tr>
                {rows.map((c) => (
                  <tr
                    key={c.id}
                    className={`border-t border-slate-100 hover:bg-sky-50/70 hover:ring-1 hover:ring-sky-200 transition-colors ${c.is_primary_client ? "bg-sawali-blue/5" : ""}`}
                    data-testid={`client-row-${c.id}`}
                  >
                    <td className="px-4 py-3 font-medium">
                      <div className="flex items-center gap-2">
                        {c.is_primary_client && (
                          <span title="Client primaire (Superviseur)" className="inline-flex items-center justify-center text-amber-500">
                            <Star className="h-4 w-4 fill-amber-400" />
                          </span>
                        )}
                        <span>{c.full_name}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-slate-600">{c.email}</td>
                    <td className="px-4 py-3 text-slate-600">
                      {(() => {
                        const cat = catOf(c.category_slug);
                        return cat ? (
                          <span className="inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded" style={{ background: (cat.color || "#1E90FF") + "15", color: cat.color || "#1E90FF" }}>
                            <CategoryIcon name={cat.icon} color={cat.color} className="h-3 w-3" />
                            {cat.label}
                          </span>
                        ) : (c.company || "-");
                      })()}
                    </td>
                    <td className="px-4 py-3 text-slate-600 text-xs">
                      {c.country ? (
                        <span>{c.country}{c.city ? <span className="text-slate-400"> · {c.city}</span> : null}</span>
                      ) : (
                        <span className="text-slate-400">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded border ${c.role === "superviseur" ? "bg-sawali-blue/10 text-sawali-blue border-sawali-blue/30" : c.role === "admin" ? "bg-amber-50 text-amber-700 border-amber-200" : c.role === "moderateur" ? "bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200" : "bg-slate-100 text-slate-700 border-slate-200"}`}>{c.role}</span>
                      {c.can_cash && (
                        <span className="ml-1 text-[10px] px-1.5 py-0.5 rounded border bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200" title="Rôle Caissier — accès au module Caisse/Facturation" data-testid={`can-cash-badge-${c.id}`}>💰 Caissier</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-1 rounded ${c.account_status === "active" ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-700"}`}>{c.account_status}</span>
                    </td>
                    {/* 2026-02 fork iter103 — N° contrat + Retard paiement (rendus uniquement si champs renseignés) */}
                    <td className="px-4 py-3 text-xs" data-testid={`client-contract-${c.id}`}>
                      {c.contract_number ? (
                        <div>
                          <div className="font-mono font-semibold text-teal-700">{c.contract_number}</div>
                          {(c.contract_amount != null && c.contract_amount !== "") && (
                            <div className="text-[10px] text-slate-500">{formatMoney(c.contract_amount, c.contract_currency)}</div>
                          )}
                          {c.contract_signed_at && (
                            <div className="text-[10px] text-slate-400">signé le {String(c.contract_signed_at).slice(0, 10)}</div>
                          )}
                        </div>
                      ) : (
                        <span className="text-slate-300">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs" data-testid={`client-payment-delay-${c.id}`}>
                      {(() => {
                        const d = computePaymentDelay(c);
                        if (!d) return <span className="text-slate-300">—</span>;
                        // 2026-02 fork iter104 — Retard basé sur le seuil (par client
                        // ou global). Vert = à jour ; ambre = 50-99% du seuil ;
                        // rose foncé = seuil atteint/dépassé.
                        const ratio = d.days / d.threshold;
                        const cls = d.overdue
                          ? "bg-rose-100 text-rose-800 border-rose-300"
                          : ratio >= 0.5
                          ? "bg-amber-100 text-amber-800 border-amber-200"
                          : d.days === 0
                          ? "bg-emerald-100 text-emerald-800 border-emerald-200"
                          : "bg-slate-100 text-slate-700 border-slate-200";
                        const refLabel = d.refField === "last_payment_at" ? "depuis le dernier règlement" : "depuis la signature";
                        return (
                          <span
                            className={`inline-flex flex-col items-start px-2 py-0.5 rounded border ${cls}`}
                            title={`${d.days} jour${d.days > 1 ? "s" : ""} ${refLabel} (${String(d.refIso).slice(0,10)}) — seuil ${d.threshold} j${d.overdue ? " ⚠ en retard" : ""}`}
                          >
                            <span className="font-mono font-semibold text-[11px]">{d.days} j</span>
                            <span className="text-[9px] uppercase tracking-wide opacity-70">/ {d.threshold} j {d.overdue ? "⚠" : ""}</span>
                          </span>
                        );
                      })()}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {c.is_primary_client ? (
                        <button onClick={() => unsetPrimary(c.id)} title="Retirer le statut primaire" className="text-amber-500 hover:text-amber-600 mr-3" data-testid={`unset-primary-${c.id}`}>
                          <StarOff className="h-4 w-4 inline" />
                        </button>
                      ) : (
                        <button onClick={() => setPrimary(c.id)} title="Désigner comme client primaire (Superviseur)" className="text-slate-400 hover:text-amber-500 mr-3" data-testid={`set-primary-${c.id}`}>
                          <Star className="h-4 w-4 inline" />
                        </button>
                      )}
                      <Link to={`/admin/clients/${c.id}/timeline`} className="text-slate-500 hover:text-emerald-600 mr-3" data-testid={`timeline-client-${c.id}`} title="Timeline CRM"><Activity className="h-4 w-4 inline" /></Link>
                      <Link to={`/admin/clients/${c.id}/features`} className="text-slate-500 hover:text-fuchsia-600 mr-3" data-testid={`features-client-${c.id}`} title="SMART Communications"><ShieldCheck className="h-4 w-4 inline" /></Link>
                      <button onClick={() => setWaStats(c)} className="text-slate-500 hover:text-emerald-600 mr-3" data-testid={`wa-stats-${c.id}`} title="Consommation WhatsApp"><MessageCircle className="h-4 w-4 inline" /></button>
                      {/* 2026-02 fork iter104 — Payments panel */}
                      <button
                        onClick={() => setPaymentsFor(c)}
                        className="text-slate-500 hover:text-teal-600 mr-3"
                        data-testid={`payments-${c.id}`}
                        title="Paiements / historique règlements"
                      >
                        <Wallet className="h-4 w-4 inline" />
                      </button>
                      <button
                        onClick={() => repairContact(c)}
                        className="text-slate-500 hover:text-fuchsia-600 mr-3"
                        data-testid={`repair-contact-${c.id}`}
                        title="Réparer la fiche contact (directory_contacts) — utile si l'utilisateur n'apparaît pas dans /portal/contacts malgré ses WhatsApp"
                      >
                        <Wrench className="h-4 w-4 inline" />
                      </button>
                      <button onClick={() => open(c)} className="text-slate-500 hover:text-sawali-blue mr-3" data-testid={`edit-client-${c.id}`}><Edit className="h-4 w-4 inline" /></button>
                      <button onClick={() => del(c.id)} className="text-slate-500 hover:text-rose-600" data-testid={`del-client-${c.id}`}><Trash2 className="h-4 w-4 inline" /></button>
                    </td>
                  </tr>
                ))}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>

      {isOpen && (
        <Modal onClose={close} title={editing?.id ? "Modifier le client" : "Nouveau client"}>
          <form onSubmit={submit} className="space-y-3" data-testid="client-form">
            <Input label="Nom complet *" value={form.full_name} onChange={(v) => setForm({ ...form, full_name: v })} required />
            <Input label="Email *" type="email" value={form.email} onChange={(v) => setForm({ ...form, email: v })} required />
            <Input label={editing?.id ? "Mot de passe (laisser vide pour ne pas changer)" : "Mot de passe *"} type="password" value={form.password} onChange={(v) => setForm({ ...form, password: v })} required={!editing?.id} />
            <Input label="Téléphone" value={form.phone || ""} onChange={(v) => setForm({ ...form, phone: v })} />
            <Input label="N° WhatsApp (E.164)" value={form.whatsapp_number || ""} onChange={(v) => setForm({ ...form, whatsapp_number: v })} testid="client-whatsapp-number" />
            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-700 inline-flex items-center gap-1"><Building2 className="h-3 w-3" /> Entreprise</label>
              <input
                value={form.company || ""}
                onChange={(e) => {
                  const v = e.target.value;
                  setForm((prev) => ({ ...prev, company: v, link_to_client_id: null }));
                  setCompanyHint(null);
                }}
                onBlur={(e) => checkCompany(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                data-testid="client-field-company"
              />
              {hintLoading && <p className="text-[10px] text-slate-400">Vérification…</p>}
              {!editing?.id && companyHint?.found && companyHint.canonical_user && (
                <div className="rounded-lg ring-1 ring-violet-200 bg-violet-50 p-2.5 text-[11px] space-y-1.5" data-testid="company-hint-banner">
                  <p className="font-semibold inline-flex items-center gap-1 text-violet-900">
                    <Link2 className="h-3 w-3" />
                    Une entreprise « <strong>{companyHint.canonical_user.company}</strong> » existe déjà
                    <span className="text-slate-500 font-normal"> ({companyHint.member_count} membre{companyHint.member_count > 1 ? "s" : ""})</span>
                  </p>
                  <p className="text-slate-700">
                    Client canonique : <strong>{companyHint.canonical_user.full_name}</strong>
                    <span className="text-slate-500"> ({companyHint.canonical_user.email}, {companyHint.canonical_user.role})</span>
                  </p>
                  <label className="flex items-start gap-2 cursor-pointer pt-1">
                    <input
                      type="checkbox"
                      checked={form.link_to_client_id === companyHint.canonical_user.id}
                      onChange={(e) => setForm((prev) => ({ ...prev, link_to_client_id: e.target.checked ? companyHint.canonical_user.id : null }))}
                      className="mt-0.5 accent-violet-600"
                      data-testid="company-hint-link-checkbox"
                    />
                    <span className="text-slate-800">
                      <strong>Lier ce nouvel utilisateur au client canonique</strong> — il partagera ses contacts, médias, RGPD, fonctionnalités et facturation. <span className="text-slate-500">(recommandé sauf si vous créez réellement une entité distincte avec un nom identique)</span>
                    </span>
                  </label>
                </div>
              )}
            </div>
            <Input label="Code client (utilisé pour la numérotation des interventions, ex. ACME)" value={form.client_code || ""} onChange={(v) => setForm({ ...form, client_code: v.toUpperCase() })} />
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">Catégorie</label>
              <select value={form.category_slug || ""} onChange={(e) => setForm({ ...form, category_slug: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="client-category-select">
                <option value="">— Aucune —</option>
                {categories.map((c) => <option key={c.id} value={c.slug}>{c.label}</option>)}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Input label="Pays" value={form.country || ""} onChange={(v) => setForm({ ...form, country: v })} />
              <Input label="Ville" value={form.city || ""} onChange={(v) => setForm({ ...form, city: v })} />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">Logo du client (image)</label>
              <div className="flex items-center gap-3">
                {form.logo_url && (
                  <img src={form.logo_url} alt="Logo" className="h-12 w-12 rounded border border-slate-200 object-contain bg-slate-50" />
                )}
                <label className="inline-flex items-center gap-2 cursor-pointer rounded-lg border border-dashed border-slate-300 px-3 py-2 text-xs text-slate-600 hover:border-sawali-blue">
                  <Upload className="h-3.5 w-3.5" /> {form.logo_url ? "Remplacer" : "Téléverser un logo"}
                  <input
                    type="file"
                    hidden
                    accept="image/*"
                    onChange={async (e) => {
                      const file = e.target.files?.[0];
                      if (!file) return;
                      const fd = new FormData(); fd.append("file", file);
                      try {
                        const r = await apiClient.post("/admin/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
                        setForm((prev) => ({ ...prev, logo_url: r.data.url }));
                        toast.success("Logo téléversé");
                      } catch (err) { toast.error("Erreur upload"); }
                    }}
                    data-testid="client-logo-input"
                  />
                </label>
                {form.logo_url && (
                  <button type="button" onClick={() => setForm({ ...form, logo_url: "" })} className="text-xs text-rose-600 hover:underline">Retirer</button>
                )}
              </div>
              <p className="mt-1 text-[11px] text-slate-500">Affiché dans la sidebar du portail à la place du logo SAWALI quand l'utilisateur de ce client est connecté.</p>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Select label="Rôle" value={form.role} onChange={(v) => setForm({ ...form, role: v })} options={[{ v: "client", l: "Client" }, { v: "admin", l: "Admin (client)" }, { v: "superviseur", l: "Superviseur" }, { v: "moderateur", l: "Modérateur" }, { v: "regulateur", l: "💊 Régulateur (AMM)" }, { v: "editeur_vidal", l: "📚 Éditeur VIDAL (lecture)" }, { v: "pharmacien", l: "💊 Pharmacien" }, { v: "medecin", l: "⚕️ Médecin" }, { v: "demo", l: "Démo (limité)" }]} />
              <Select label="Statut" value={form.account_status} onChange={(v) => setForm({ ...form, account_status: v })} options={[{ v: "active", l: "Actif" }, { v: "disabled", l: "Désactivé" }]} />
            </div>

            {/* S-iter39a — Client lié canonique (modifiable depuis la fiche).
                 Permet à un Admin/Superviseur de rattacher ou détacher ce compte
                 d'un client canonique parent. Le pointeur parent_client_id est
                 utilisé partout (Centre Messagerie, Contacts, Briefing, RGPD,
                 facturation, etc.) donc la modification se propage automatiquement. */}
            {editing?.id && (
              <div className="rounded-lg border-2 border-violet-200 bg-violet-50/40 p-3 space-y-2" data-testid="link-to-client-section">
                <div className="flex items-center gap-2">
                  <Link2 className="h-4 w-4 text-violet-700" />
                  <span className="text-sm font-display font-bold text-violet-900">Client lié canonique</span>
                </div>
                <p className="text-[11px] text-violet-800">
                  Définit la <strong>société mère</strong> à laquelle ce compte est rattaché.
                  Ce choix se répercute partout où l'information « Client lié » apparaît (Centre Messagerie, Contacts, Briefing, RGPD, facturation WhatsApp…).
                  Laissez vide pour faire de ce compte un <strong>tenant indépendant</strong>.
                </p>
                <select
                  value={form.link_to_client_id || ""}
                  onChange={(e) => setForm({ ...form, link_to_client_id: e.target.value })}
                  className="w-full rounded-lg border border-violet-300 bg-white px-3 py-2 text-sm"
                  data-testid="client-link-to-client-select"
                >
                  <option value="">— Aucun (tenant indépendant) —</option>
                  {items
                    .filter((u) => u.id !== editing.id && ["admin", "superviseur", "moderateur", "client"].includes(u.role))
                    .map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.full_name}{u.company ? ` — ${u.company}` : ""} ({u.role})
                      </option>
                    ))}
                </select>
                {form.link_to_client_id && (
                  <p className="text-[10px] text-violet-700 italic">
                    En enregistrant, <code>parent_client_id</code> et <code>client_id</code> seront alignés sur ce client canonique.
                  </p>
                )}
              </div>
            )}

            {/* WhatsApp billing — set unit cost so the consumption page can valorise messages sent. */}
            <div className="rounded-lg border border-emerald-200 bg-emerald-50/40 p-3 space-y-2">
              <div className="flex items-center gap-2">
                <MessageCircle className="h-4 w-4 text-emerald-600" />
                <span className="text-xs font-semibold text-emerald-900">Facturation WhatsApp</span>
              </div>
              <p className="text-[11px] text-emerald-800">Coût appliqué à chaque message WhatsApp envoyé avec succès depuis ce client (utilisé dans la page Consommation).</p>
              <div className="grid grid-cols-2 gap-3">
                <Input label="Coût par message" type="number" value={form.wa_unit_cost ?? 0} onChange={(v) => setForm({ ...form, wa_unit_cost: v === "" ? 0 : Number(v) })} testid="client-wa-unit-cost" />
                <Input label="Devise (XOF, EUR, USD…)" value={form.wa_currency || "XOF"} onChange={(v) => setForm({ ...form, wa_currency: (v || "").toUpperCase() })} testid="client-wa-currency" />
              </div>
            </div>

            {/* 2026-02 fork iter103 — Contract tracking (optional per tenant). */}
            <div className="rounded-lg border-2 border-teal-200 bg-teal-50/40 p-3 space-y-2" data-testid="client-contract-section">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-sm font-display font-bold text-teal-900">📄 Contrat</span>
                <span className="text-[10px] text-teal-700">— champs optionnels, laissez vides si non applicables</span>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Input
                  label="Numéro de contrat"
                  value={form.contract_number || ""}
                  onChange={(v) => setForm({ ...form, contract_number: v })}
                  testid="client-contract-number"
                />
                <Input
                  label="Date de signature"
                  type="date"
                  value={(form.contract_signed_at || "").slice(0, 10)}
                  onChange={(v) => setForm({ ...form, contract_signed_at: v || "" })}
                  testid="client-contract-signed-at"
                />
                <Input
                  label="Montant du contrat"
                  type="number"
                  value={form.contract_amount ?? ""}
                  onChange={(v) => setForm({ ...form, contract_amount: v })}
                  testid="client-contract-amount"
                />
                <Input
                  label="Devise du contrat"
                  value={form.contract_currency || ""}
                  onChange={(v) => setForm({ ...form, contract_currency: (v || "").toUpperCase() })}
                  testid="client-contract-currency"
                />
                <Input
                  label="Date du dernier règlement"
                  type="date"
                  value={(form.last_payment_at || "").slice(0, 10)}
                  onChange={(v) => setForm({ ...form, last_payment_at: v || "" })}
                  testid="client-last-payment-at"
                />
                {/* 2026-02 fork iter104 — Per-tenant overdue threshold override */}
                <Input
                  label={`Seuil de retard (j) — défaut ${overdueDefault}`}
                  type="number"
                  value={form.contract_overdue_days ?? ""}
                  onChange={(v) => setForm({ ...form, contract_overdue_days: v })}
                  testid="client-contract-overdue-days"
                />
                <Input
                  label="Template WA — confirmation paiement"
                  value={form.payment_confirmation_template || ""}
                  onChange={(v) => setForm({ ...form, payment_confirmation_template: v })}
                  testid="client-payment-confirmation-template"
                />
                {/* 2026-02 fork iter108 — S158 : Recurring billing period */}
                <div>
                  <label className="text-[11px] font-semibold text-slate-600 block mb-1">Périodicité facturation (S158)</label>
                  <select
                    value={form.contract_billing_period || ""}
                    onChange={(e) => setForm({ ...form, contract_billing_period: e.target.value || null })}
                    className="w-full px-3 py-2 rounded-lg ring-1 ring-slate-300 text-sm bg-white"
                    data-testid="client-contract-billing-period"
                  >
                    <option value="">— Aucune (paiement unique) —</option>
                    <option value="monthly">Mensuelle (30 j)</option>
                    <option value="quarterly">Trimestrielle (90 j)</option>
                    <option value="annual">Annuelle (365 j)</option>
                  </select>
                  <p className="text-[10px] text-slate-500 italic mt-1">
                    Envoi automatique d&apos;un rappel WA + Email 3 jours avant chaque échéance.
                  </p>
                </div>
                {/* 2026-02 fork iter108 — S159 : Auto-suspend on unpaid */}
                <Input
                  label="Auto-suspension après (j) — vide = désactivé"
                  type="number"
                  value={form.auto_suspend_after_overdue_days ?? ""}
                  onChange={(v) => setForm({ ...form, auto_suspend_after_overdue_days: v })}
                  testid="client-auto-suspend-days"
                />
              </div>
              <p className="text-[11px] text-teal-800 italic">
                Le nombre de jours de retard est calculé automatiquement dans la liste des clients à partir de la <em>date du dernier règlement</em> ou, à défaut, de la <em>date de signature</em>. Le <em>seuil de retard</em> propre au client (si renseigné) prévaut sur la valeur globale des paramètres. Le <em>template WA</em> par défaut est <code>confirmation_paiement_avecrecu</code>.
                <br /><strong>S158</strong> : périodicité active un rappel automatique 3 jours avant échéance. <strong>S159</strong> : auto-suspension bloque le login au-delà du seuil de jours de retard — la réactivation est automatique dès qu&apos;un paiement est enregistré.
              </p>
            </div>

            {/* Iter37c — Tarification interventions (Tickets) */}
            <div className="rounded-lg border-2 border-sky-200 bg-sky-50/40 p-3 space-y-2" data-testid="ticket-pricing-section">
              <div className="flex items-center gap-2">
                <span className="text-sm font-display font-bold text-sky-900">🎟️ Tarification des interventions (tickets)</span>
              </div>
              <p className="text-[11px] text-sky-800">
                Utilisé pour calculer le coût d'un ticket à sa clôture (visible uniquement par admin/superviseur/modérateur).
                <br /><b>Forfait</b> prioritaire si &gt; 0, sinon <b>Taux horaire × durée active</b>.
              </p>
              <div className="grid grid-cols-2 gap-3">
                <Input label="Taux horaire (XOF)" type="number" value={form.hourly_rate ?? 0} onChange={(v) => setForm({ ...form, hourly_rate: v === "" ? 0 : Number(v) })} testid="client-hourly-rate" />
                <Input label="Forfait par intervention (XOF)" type="number" value={form.flat_rate ?? 0} onChange={(v) => setForm({ ...form, flat_rate: v === "" ? 0 : Number(v) })} testid="client-flat-rate" />
              </div>
            </div>

            {/* Iter37d — Rôle Caissier (Caisse & Facturation access) */}
            <div className="rounded-lg border-2 border-fuchsia-200 bg-fuchsia-50/40 p-3 space-y-2" data-testid="cashier-role-section">
              <label className="flex items-start gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4"
                  checked={!!form.can_cash}
                  onChange={(e) => setForm({ ...form, can_cash: e.target.checked })}
                  data-testid="client-can-cash-toggle"
                />
                <span className="text-sm">
                  <span className="font-display font-bold text-fuchsia-900">💰 Rôle Caissier</span>
                  <span className="block text-[11px] text-fuchsia-800 mt-0.5">
                    Si activé, cet utilisateur peut accéder au module « Caisse / Facturation » (créer reçus, factures, proformas).
                    Inutile pour les rôles <code>admin</code> ou <code>superviseur</code> (déjà autorisés).
                  </span>
                </span>
              </label>
            </div>

            {/* Iter43 (2026-02) — Mode de partage entre comptes du tenant */}
            <div className="rounded-lg border-2 border-indigo-200 bg-indigo-50/40 p-3 space-y-2" data-testid="tenant-sharing-section">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-sm font-display font-bold text-indigo-900">🤝 Partage entre comptes de la société</span>
              </div>
              <p className="text-[11px] text-indigo-800 mb-2">
                Définit la règle de visibilité des documents (rapports, suivis, notes, tâches, PV, groupes contacts)
                marqués « partagés » par leurs auteurs. La règle compare les champs <code>société</code> et <code>rattachement</code>
                (= « Client lié ») des profils.
              </p>
              <div className="grid grid-cols-2 gap-2">
                <label className={`cursor-pointer rounded ring-2 p-2 text-xs ${form.tenant_sharing_mode !== "OR" ? "ring-indigo-500 bg-white" : "ring-slate-200 bg-white/50 hover:ring-indigo-300"}`}>
                  <input
                    type="radio" name="tenant_sharing_mode" value="AND"
                    checked={form.tenant_sharing_mode !== "OR"}
                    onChange={() => setForm({ ...form, tenant_sharing_mode: "AND" })}
                    className="mr-2" data-testid="tenant-sharing-AND"
                  />
                  <strong>ET</strong> (strict) — défaut
                  <span className="block text-[10px] text-slate-500 mt-0.5">
                    Société <em>ET</em> rattachement doivent correspondre.
                  </span>
                </label>
                <label className={`cursor-pointer rounded ring-2 p-2 text-xs ${form.tenant_sharing_mode === "OR" ? "ring-indigo-500 bg-white" : "ring-slate-200 bg-white/50 hover:ring-indigo-300"}`}>
                  <input
                    type="radio" name="tenant_sharing_mode" value="OR"
                    checked={form.tenant_sharing_mode === "OR"}
                    onChange={() => setForm({ ...form, tenant_sharing_mode: "OR" })}
                    className="mr-2" data-testid="tenant-sharing-OR"
                  />
                  <strong>OU</strong> (souple)
                  <span className="block text-[10px] text-slate-500 mt-0.5">
                    Société <em>OU</em> rattachement suffit — utile multi-succursales.
                  </span>
                </label>
              </div>
            </div>

            {/* Iter43-fix24az-f (2026-02-26) — Business type (tenant profile) */}
            <div className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3">
              <p className="text-xs font-semibold uppercase text-slate-600 mb-2">
                Profil d&apos;entreprise (sidebar réduite si Fabricant)
              </p>
              <select
                value={form.business_type || ""}
                onChange={(e) => setForm({ ...form, business_type: e.target.value })}
                className="w-full text-sm px-3 py-2 rounded ring-1 ring-slate-300 bg-white"
                data-testid="business-type-select"
              >
                <option value="">Standard (tous les modules visibles)</option>
                <option value="fabricant">Fabricant — Caisse + GRH + Officines (consultation) + Catalogue + Production</option>
              </select>
              <p className="text-[10px] text-slate-500 mt-1">
                Le profil <strong>Fabricant</strong> réduit la sidebar aux modules pertinents et active le module <strong>Production</strong> (coût de revient, marge, prix de vente).
              </p>
            </div>

            {/* Iter35h — Demo account configuration */}
            {form.role === "demo" && (
              <div className="rounded-lg border-2 border-orange-300 bg-orange-50/50 p-3 space-y-2" data-testid="demo-config-section">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-orange-900">⏳ Configuration du compte de démonstration</span>
                </div>
                <p className="text-[11px] text-orange-800">
                  Ce compte bénéficie de quotas limités sur WhatsApp / SMS / IA / transcription / contacts / paiements / stockage,
                  et expire automatiquement à la date choisie. Les valeurs vides utilisent les défauts (WA 2, SMS 1, IA 1, Whisper 2, Contacts 5, Paiements 0, Stockage 5 Mo).
                </p>
                <Input
                  label="Date d'expiration (YYYY-MM-DD ou ISO)"
                  type="date"
                  value={(form.demo_expires_at || "").slice(0, 10)}
                  onChange={(v) => setForm({ ...form, demo_expires_at: v ? `${v}T23:59:59+00:00` : null })}
                  testid="demo-expires-at"
                />
                <div className="grid grid-cols-3 gap-2">
                  <Input label="Quota WA" type="number" value={(form.demo_quotas?.whatsapp_sends ?? "") + ""} onChange={(v) => setForm({ ...form, demo_quotas: { ...(form.demo_quotas || {}), whatsapp_sends: v === "" ? null : Number(v) } })} testid="demo-quota-wa" />
                  <Input label="Quota SMS" type="number" value={(form.demo_quotas?.sms_sends ?? "") + ""} onChange={(v) => setForm({ ...form, demo_quotas: { ...(form.demo_quotas || {}), sms_sends: v === "" ? null : Number(v) } })} testid="demo-quota-sms" />
                  <Input label="Quota IA" type="number" value={(form.demo_quotas?.ai_generations ?? "") + ""} onChange={(v) => setForm({ ...form, demo_quotas: { ...(form.demo_quotas || {}), ai_generations: v === "" ? null : Number(v) } })} testid="demo-quota-ai" />
                  <Input label="Quota Transcr." type="number" value={(form.demo_quotas?.transcriptions ?? "") + ""} onChange={(v) => setForm({ ...form, demo_quotas: { ...(form.demo_quotas || {}), transcriptions: v === "" ? null : Number(v) } })} testid="demo-quota-whisper" />
                  <Input label="Quota Contacts" type="number" value={(form.demo_quotas?.directory_contacts ?? "") + ""} onChange={(v) => setForm({ ...form, demo_quotas: { ...(form.demo_quotas || {}), directory_contacts: v === "" ? null : Number(v) } })} testid="demo-quota-contacts" />
                  <Input label="Quota Paiements" type="number" value={(form.demo_quotas?.payments ?? "") + ""} onChange={(v) => setForm({ ...form, demo_quotas: { ...(form.demo_quotas || {}), payments: v === "" ? null : Number(v) } })} testid="demo-quota-payments" />
                </div>
                <Input
                  label="Stockage max (Mo)"
                  type="number"
                  value={(form.demo_quotas?.attachments_bytes ?? "") === "" ? "" : Math.round((form.demo_quotas?.attachments_bytes || 0) / 1024 / 1024)}
                  onChange={(v) => setForm({ ...form, demo_quotas: { ...(form.demo_quotas || {}), attachments_bytes: v === "" ? null : Number(v) * 1024 * 1024 } })}
                  testid="demo-quota-storage-mb"
                />
              </div>
            )}

            <button type="submit" disabled={loading} className="w-full rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light disabled:opacity-50" data-testid="save-client-button">
              {loading ? "Enregistrement..." : "Enregistrer"}
            </button>
          </form>
        </Modal>
      )}

      {catManagerOpen && (
        <ClientCategoryManager
          categories={categories}
          onClose={() => setCatManagerOpen(false)}
          onChanged={async () => { await loadCats(); await load(); }}
        />
      )}

      {waStats && (
        <WaConsumptionModal
          client={waStats}
          onClose={() => setWaStats(null)}
          onCostUpdated={async () => { await load(); }}
        />
      )}

      {/* 2026-02 fork iter104 — Payment history modal */}
      {paymentsFor && (
        <PaymentsModal
          client={paymentsFor}
          onClose={() => setPaymentsFor(null)}
          onChanged={async () => { await load(); }}
        />
      )}
    </div>
  );
}

// --- WhatsApp consumption modal ---
const WaConsumptionModal = ({ client, onClose, onCostUpdated }) => {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [unitCost, setUnitCost] = useState(client.wa_unit_cost ?? 0);
  const [currency, setCurrency] = useState(client.wa_currency || "XOF");
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get(`/admin/clients/${client.id}/whatsapp-stats`);
      setStats(r.data);
      setUnitCost(r.data.unit_cost ?? 0);
      setCurrency(r.data.currency || "XOF");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [client.id]);

  const saveCost = async () => {
    setSaving(true);
    try {
      await apiClient.put(`/admin/clients/${client.id}/whatsapp-cost`, {
        wa_unit_cost: Number(unitCost) || 0,
        wa_currency: (currency || "XOF").toUpperCase(),
      });
      toast.success("Tarif mis à jour");
      await load();
      if (onCostUpdated) onCostUpdated();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setSaving(false);
    }
  };

  const fmt = (v) => Number(v || 0).toLocaleString("fr-FR", { minimumFractionDigits: 0, maximumFractionDigits: 4 });
  const fmtDate = (iso) => iso ? new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      data-testid="wa-consumption-modal"
    >
      <div className="w-full max-w-2xl rounded-2xl bg-white shadow-2xl flex flex-col max-h-[90vh]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200">
          <div>
            <h2 className="text-lg font-display font-bold inline-flex items-center gap-2">
              <MessageCircle className="h-5 w-5 text-emerald-600" /> Consommation WhatsApp
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Client : <strong>{client.full_name}</strong>{client.company ? ` · ${client.company}` : ""}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={load}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 px-2.5 py-1.5 text-xs"
              data-testid="wa-stats-refresh"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Actualiser
            </button>
            <button onClick={onClose} className="text-slate-500 hover:text-slate-900"><X className="h-4 w-4" /></button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          {loading || !stats ? (
            <p className="text-center text-slate-500 py-8">Chargement…</p>
          ) : (
            <>
              <div className="grid sm:grid-cols-3 gap-3">
                <StatCard
                  testid="wa-stat-sent"
                  icon={Send}
                  label="Messages envoyés"
                  value={stats.sent_ok}
                  subtitle={stats.sent_ko > 0 ? `${stats.sent_ko} échec(s)` : "100% de succès"}
                  tone="emerald"
                />
                <StatCard
                  testid="wa-stat-inbound"
                  icon={Inbox}
                  label="Messages reçus"
                  value={stats.inbound}
                  subtitle="Via webhook Meta"
                  tone="sky"
                />
                <StatCard
                  testid="wa-stat-cost"
                  icon={MessageCircle}
                  label="Coût total facturé"
                  value={`${fmt(stats.total_cost)} ${stats.currency}`}
                  subtitle={`${stats.billable_messages} message(s) × ${fmt(stats.unit_cost)} ${stats.currency}`}
                  tone="amber"
                />
              </div>

              <div className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-4 text-xs text-slate-600 space-y-1">
                <p><strong className="text-slate-800">Dernier envoi :</strong> {fmtDate(stats.last_outbound_at)}</p>
                <p><strong className="text-slate-800">Dernière réception :</strong> {fmtDate(stats.last_inbound_at)}</p>
              </div>

              <div className="rounded-lg ring-1 ring-emerald-200 bg-emerald-50/50 p-4 space-y-3">
                <p className="text-sm font-semibold text-emerald-900">Tarif facturé à ce client</p>
                <p className="text-[11px] text-emerald-800">Le coût est appliqué uniquement aux messages envoyés avec succès. Le coût total ci-dessus est calculé en temps réel.</p>
                <div className="grid sm:grid-cols-[1fr_120px_auto] gap-2">
                  <div>
                    <label className="block text-[11px] uppercase tracking-wider text-emerald-700 mb-1">Coût par message</label>
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      value={unitCost}
                      onChange={(e) => setUnitCost(e.target.value)}
                      className="w-full rounded-lg border border-emerald-300 bg-white px-3 py-2 text-sm"
                      data-testid="wa-cost-input"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] uppercase tracking-wider text-emerald-700 mb-1">Devise</label>
                    <input
                      value={currency}
                      onChange={(e) => setCurrency(e.target.value.toUpperCase())}
                      className="w-full rounded-lg border border-emerald-300 bg-white px-3 py-2 text-sm uppercase"
                      data-testid="wa-currency-input"
                    />
                  </div>
                  <div className="flex items-end">
                    <button
                      onClick={saveCost}
                      disabled={saving}
                      className="rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 text-sm disabled:opacity-50"
                      data-testid="wa-cost-save"
                    >
                      {saving ? "…" : "Enregistrer"}
                    </button>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

const StatCard = ({ icon: Icon, label, value, subtitle, tone = "slate", testid }) => {
  const palette = {
    emerald: "from-emerald-50 to-emerald-100 ring-emerald-200 text-emerald-900",
    sky: "from-sky-50 to-sky-100 ring-sky-200 text-sky-900",
    amber: "from-amber-50 to-amber-100 ring-amber-200 text-amber-900",
    slate: "from-slate-50 to-slate-100 ring-slate-200 text-slate-900",
  }[tone];
  return (
    <div className={`rounded-xl ring-1 bg-gradient-to-br ${palette} p-4`} data-testid={testid}>
      <div className="flex items-center justify-between">
        <span className="text-[11px] uppercase tracking-wider opacity-75">{label}</span>
        <Icon className="h-4 w-4 opacity-60" />
      </div>
      <p className="mt-1 text-2xl font-display font-bold">{value}</p>
      {subtitle && <p className="text-[11px] opacity-75 mt-0.5">{subtitle}</p>}
    </div>
  );
};

const ClientCategoryManager = ({ categories, onClose, onChanged }) => {
  const [newLabel, setNewLabel] = useState("");
  const [newIcon, setNewIcon] = useState("Building2");
  const [newColor, setNewColor] = useState("#1E90FF");
  const [editingId, setEditingId] = useState(null);
  const [editLabel, setEditLabel] = useState("");
  const [editSlug, setEditSlug] = useState("");
  const [editIcon, setEditIcon] = useState("");
  const [editColor, setEditColor] = useState("");
  const [busy, setBusy] = useState(false);

  const add = async (e) => {
    e.preventDefault();
    if (!newLabel.trim()) return;
    setBusy(true);
    try {
      await apiClient.post("/admin/client-categories", { label: newLabel.trim(), icon: newIcon, color: newColor });
      toast.success("Catégorie ajoutée");
      setNewLabel(""); setNewIcon("Building2"); setNewColor("#1E90FF");
      await onChanged();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setBusy(false); }
  };

  const startEdit = (c) => {
    setEditingId(c.id); setEditLabel(c.label); setEditSlug(c.slug);
    setEditIcon(c.icon || "Building2"); setEditColor(c.color || "#1E90FF");
  };
  const cancelEdit = () => { setEditingId(null); };

  const saveEdit = async () => {
    setBusy(true);
    try {
      await apiClient.put(`/admin/client-categories/${editingId}`, {
        label: editLabel.trim(), slug: editSlug.trim(), icon: editIcon, color: editColor,
      });
      toast.success("Catégorie mise à jour");
      cancelEdit();
      await onChanged();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setBusy(false); }
  };

  const remove = async (c) => {
    if (!window.confirm(`Supprimer "${c.label}" ?`)) return;
    setBusy(true);
    try {
      await apiClient.delete(`/admin/client-categories/${c.id}`);
      toast.success("Supprimée");
      await onChanged();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={onClose}>
      <div className="bg-white rounded-xl w-full max-w-lg max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b">
          <h3 className="font-display font-semibold">Catégories de clients</h3>
          <button onClick={onClose}><X className="h-4 w-4" /></button>
        </div>
        <div className="p-4 space-y-4">
          <p className="text-xs text-slate-500">
            Ces catégories permettent de typer chaque client (clinique, pharmacie, commerce…) et d'afficher une icône personnalisable.
          </p>
          <form onSubmit={add} className="rounded-lg border border-slate-200 p-3 space-y-3 bg-slate-50/40">
            <div className="flex items-center gap-2">
              <CategoryIcon name={newIcon} color={newColor} className="h-5 w-5" />
              <input value={newLabel} onChange={(e) => setNewLabel(e.target.value)} placeholder="Nouvelle catégorie (ex. Hôpital)" className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="new-client-category-input" />
              <button type="submit" disabled={busy || !newLabel.trim()} className="inline-flex items-center gap-1 rounded-lg bg-sawali-blue text-white px-3 py-2 text-sm hover:bg-sawali-blue-light disabled:opacity-50" data-testid="add-client-category-btn">
                <Plus className="h-4 w-4" /> Ajouter
              </button>
            </div>
            <IconPicker value={newIcon} color={newColor} onChange={setNewIcon} onColorChange={setNewColor} />
          </form>
          <div className="rounded-lg border border-slate-200 divide-y divide-slate-100">
            {categories.map((c) => (
              <div key={c.id} className="p-3" data-testid={`client-category-row-${c.id}`}>
                {editingId === c.id ? (
                  <div className="space-y-3">
                    <div className="flex items-center gap-2">
                      <CategoryIcon name={editIcon} color={editColor} className="h-5 w-5" />
                      <input value={editLabel} onChange={(e) => setEditLabel(e.target.value)} className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm" />
                      <input value={editSlug} onChange={(e) => setEditSlug(e.target.value.toLowerCase().replace(/\s+/g, "-"))} className="w-32 rounded border border-slate-300 px-2 py-1 text-sm font-mono" />
                      <button onClick={saveEdit} disabled={busy} className="text-emerald-600"><Check className="h-4 w-4" /></button>
                      <button onClick={cancelEdit} className="text-slate-400"><X className="h-4 w-4" /></button>
                    </div>
                    <IconPicker value={editIcon} color={editColor} onChange={setEditIcon} onColorChange={setEditColor} />
                  </div>
                ) : (
                  <div className="flex items-center gap-3">
                    <span className="inline-flex items-center justify-center h-8 w-8 rounded-md flex-shrink-0" style={{ background: (c.color || "#1E90FF") + "20" }}>
                      <CategoryIcon name={c.icon} color={c.color} className="h-4 w-4" />
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">
                        {c.label}
                        {c.is_default && <span className="ml-2 text-[10px] uppercase tracking-wider text-slate-400 bg-slate-100 rounded px-1.5 py-0.5">défaut</span>}
                      </p>
                      <p className="text-xs text-slate-400 font-mono">{c.slug}</p>
                    </div>
                    <button onClick={() => startEdit(c)} className="text-slate-400 hover:text-sawali-blue" title="Modifier"><Edit2 className="h-4 w-4" /></button>
                    {!c.is_default && (
                      <button onClick={() => remove(c)} className="text-slate-400 hover:text-rose-600" title="Supprimer"><Trash2 className="h-4 w-4" /></button>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

const Input = ({ label, type = "text", value, onChange, required, testid }) => (
  <div>
    <label className="block text-xs font-semibold text-slate-700 mb-1">{label}</label>
    <input type={type} required={required} value={value} onChange={(e) => onChange(e.target.value)}
           data-testid={testid}
           className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:border-sawali-blue" />
  </div>
);
const Select = ({ label, value, onChange, options }) => (
  <div>
    <label className="block text-xs font-semibold text-slate-700 mb-1">{label}</label>
    <select value={value} onChange={(e) => onChange(e.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
      {options.map((o) => <option key={o.v} value={o.v}>{o.l}</option>)}
    </select>
  </div>
);
const Modal = ({ children, onClose, title }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={onClose}>
    <div className="bg-white rounded-xl w-full max-w-md max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
      <div className="flex items-center justify-between p-4 border-b">
        <h3 className="font-display font-semibold">{title}</h3>
        <button onClick={onClose} className="text-slate-500"><X className="h-4 w-4" /></button>
      </div>
      <div className="p-4">{children}</div>
    </div>
  </div>
);

// ---------------------------------------------------------------------------
// 2026-02 fork iter104 — PaymentsModal
// Register a payment + list previous ones for a client. Automatically triggers
// the WA confirmation template via the backend (POST /admin/clients/{id}/payments).
// ---------------------------------------------------------------------------
const PaymentsModal = ({ client, onClose, onChanged }) => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [methods, setMethods] = useState([]);
  const [saving, setSaving] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [draft, setDraft] = useState({
    payment_date: new Date().toISOString().slice(0, 10),
    invoice_ref: "",
    amount_due: "",
    amount_paid: "",
    payment_method_id: "",
    payment_method_label: "",
    notes: "",
    send_confirmation: true,
  });

  const load = async () => {
    setLoading(true);
    try {
      const [r1, r2] = await Promise.all([
        apiClient.get(`/admin/clients/${client.id}/payments`),
        apiClient.get("/payment-methods").catch(() => ({ data: [] })),
      ]);
      setItems(r1.data || []);
      // 2026-02 fork iter105 — Fallback list when the tenant hasn't configured
      // any payment method yet. Prevents empty dropdown & the "UID displayed"
      // symptom by always offering a labelled selection.
      const list = r2.data || [];
      if (list.length === 0) {
        setMethods([
          { id: "cash", label: "Espèces" },
          { id: "mobile_money", label: "Mobile Money" },
          { id: "bank_transfer", label: "Virement bancaire" },
          { id: "check", label: "Chèque" },
          { id: "card", label: "Carte bancaire" },
          { id: "other", label: "Autre" },
        ]);
      } else {
        setMethods(list);
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Chargement paiements impossible");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [client.id]);

  const save = async () => {
    if (!draft.payment_date || !draft.amount_paid) {
      toast.error("Date et montant payé requis");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        payment_date: draft.payment_date,
        invoice_ref: draft.invoice_ref || null,
        amount_due: draft.amount_due === "" ? null : Number(draft.amount_due),
        amount_paid: Number(draft.amount_paid),
        payment_method_id: draft.payment_method_id || null,
        payment_method_label: draft.payment_method_label || null,
        notes: draft.notes || null,
        send_confirmation: !!draft.send_confirmation,
      };
      const r = await apiClient.post(`/admin/clients/${client.id}/payments`, payload);
      const wa = r.data?.wa_confirmation;
      if (payload.send_confirmation && wa) {
        if (wa.ok) toast.success(`Paiement enregistré + WA envoyé (${wa.template})`);
        else toast.warning(`Paiement enregistré mais WA échoué : ${wa.error || "erreur inconnue"}`);
      } else {
        toast.success("Paiement enregistré");
      }
      setShowForm(false);
      setDraft({
        payment_date: new Date().toISOString().slice(0, 10),
        invoice_ref: "", amount_due: "", amount_paid: "",
        payment_method_id: "", payment_method_label: "", notes: "",
        send_confirmation: true,
      });
      await load();
      await onChanged?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (pid) => {
    if (!window.confirm("Supprimer ce paiement ?")) return;
    try {
      await apiClient.delete(`/admin/clients/${client.id}/payments/${pid}`);
      toast.success("Paiement supprimé");
      await load();
      await onChanged?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
  };

  const formatMoney = (amount, currency) => {
    if (amount == null || amount === "" || Number.isNaN(Number(amount))) return "—";
    try {
      return new Intl.NumberFormat("fr-FR", { style: "currency", currency: currency || "XOF", maximumFractionDigits: 0 }).format(Number(amount));
    } catch {
      return `${Number(amount).toLocaleString("fr-FR")} ${currency || ""}`.trim();
    }
  };

  const currency = client.contract_currency || "XOF";
  const totalPaid = items.reduce((sum, p) => sum + (Number(p.amount_paid) || 0), 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={onClose} data-testid="payments-modal">
      <div className="bg-white rounded-xl w-full max-w-3xl max-h-[92vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b bg-gradient-to-r from-teal-50 to-white">
          <div>
            <h3 className="font-display font-semibold text-lg text-teal-900">Paiements — {client.company || client.full_name || client.email}</h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Total réglé : <strong className="text-teal-700">{formatMoney(totalPaid, currency)}</strong>
              {client.contract_amount ? <> · Contrat : <strong>{formatMoney(client.contract_amount, currency)}</strong></> : null}
              {client.contract_number ? <> · N° {client.contract_number}</> : null}
            </p>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-700"><X className="h-5 w-5" /></button>
        </div>

        <div className="p-4 space-y-4">
          <div className="flex justify-between items-center">
            <h4 className="text-sm font-semibold text-slate-700">Historique ({items.length})</h4>
            {!showForm && (
              <button
                onClick={() => setShowForm(true)}
                className="inline-flex items-center gap-1.5 rounded-lg bg-teal-600 hover:bg-teal-700 text-white px-3 py-1.5 text-sm"
                data-testid="payments-add-btn"
              >
                <Plus className="h-4 w-4" /> Nouveau paiement
              </button>
            )}
          </div>

          {showForm && (
            <div className="rounded-lg border-2 border-teal-200 bg-teal-50/40 p-3 space-y-3" data-testid="payments-form">
              <div className="grid grid-cols-2 gap-3">
                <Input label="Date du paiement" type="date" value={draft.payment_date} onChange={(v) => setDraft({ ...draft, payment_date: v })} testid="payments-date" />
                <Input label="Référence facture" value={draft.invoice_ref} onChange={(v) => setDraft({ ...draft, invoice_ref: v })} testid="payments-invoice-ref" />
                <Input label={`Montant net à payer (${currency})`} type="number" value={draft.amount_due} onChange={(v) => setDraft({ ...draft, amount_due: v })} testid="payments-amount-due" />
                <Input label={`Montant payé (${currency})`} type="number" value={draft.amount_paid} onChange={(v) => setDraft({ ...draft, amount_paid: v })} testid="payments-amount-paid" />
                <div>
                  <label className="block text-xs font-semibold mb-1 text-slate-700">Type de paiement</label>
                  <select
                    value={draft.payment_method_id}
                    onChange={(e) => {
                      const id = e.target.value;
                      const m = methods.find((x) => x.id === id);
                      setDraft({ ...draft, payment_method_id: id, payment_method_label: m?.label || "" });
                    }}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    data-testid="payments-method"
                  >
                    <option value="">— Sélectionner —</option>
                    {methods.map((m) => (
                      <option key={m.id} value={m.id}>{m.label}</option>
                    ))}
                  </select>
                </div>
                <Input label="Notes (optionnel)" value={draft.notes} onChange={(v) => setDraft({ ...draft, notes: v })} testid="payments-notes" />
              </div>
              <label className="inline-flex items-center gap-2 text-xs cursor-pointer">
                <input
                  type="checkbox"
                  checked={!!draft.send_confirmation}
                  onChange={(e) => setDraft({ ...draft, send_confirmation: e.target.checked })}
                  data-testid="payments-send-confirm"
                />
                <span>Envoyer automatiquement le WhatsApp de confirmation (template <code className="bg-white px-1 rounded">{client.payment_confirmation_template || "confirmation_paiement_avecrecu"}</code>)</span>
              </label>
              <div className="flex justify-end gap-2">
                <button onClick={() => setShowForm(false)} className="text-sm px-3 py-1.5 text-slate-600 hover:text-slate-800">Annuler</button>
                <button
                  onClick={save}
                  disabled={saving}
                  className="rounded-lg bg-teal-600 hover:bg-teal-700 text-white px-4 py-1.5 text-sm disabled:opacity-50"
                  data-testid="payments-save-btn"
                >
                  {saving ? "Enregistrement…" : "Enregistrer"}
                </button>
              </div>
            </div>
          )}

          {loading ? (
            <p className="text-sm text-slate-500 text-center py-8">Chargement…</p>
          ) : items.length === 0 ? (
            <p className="text-sm text-slate-500 text-center py-8" data-testid="payments-empty">Aucun paiement enregistré.</p>
          ) : (
            <table className="w-full text-sm border-t">
              <thead className="text-xs uppercase text-slate-500">
                <tr>
                  <th className="text-left px-2 py-1">Date</th>
                  <th className="text-left px-2 py-1">Réf. facture</th>
                  <th className="text-right px-2 py-1">Dû</th>
                  <th className="text-right px-2 py-1">Payé</th>
                  <th className="text-left px-2 py-1">Type</th>
                  <th className="text-right px-2 py-1"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {items.map((p) => {
                  // 2026-02 fork iter105 — Resolve label from methods list when
                  // the stored `payment_method_label` is missing (legacy rows or
                  // when only the id was persisted). Prevents raw UUIDs showing.
                  const resolvedType = (p.payment_method_label && p.payment_method_label.trim())
                    || methods.find((m) => m.id === p.payment_method_id)?.label
                    || (p.payment_method_id ? "—" : "—");
                  return (
                  <tr key={p.id} className="hover:bg-slate-50" data-testid={`payment-row-${p.id}`}>
                    <td className="px-2 py-1.5 font-mono text-xs">{p.payment_date}</td>
                    <td className="px-2 py-1.5">{p.invoice_ref || "—"}</td>
                    <td className="px-2 py-1.5 text-right text-slate-600 font-mono text-xs">{formatMoney(p.amount_due, currency)}</td>
                    <td className="px-2 py-1.5 text-right text-teal-700 font-semibold font-mono text-xs">{formatMoney(p.amount_paid, currency)}</td>
                    <td className="px-2 py-1.5 text-xs text-slate-600">{resolvedType}</td>
                    <td className="px-2 py-1.5 text-right">
                      <button onClick={() => remove(p.id)} className="text-slate-400 hover:text-rose-600" title="Supprimer" data-testid={`payment-delete-${p.id}`}>
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
};

