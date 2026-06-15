import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  Send, Users, CalendarClock, X, Trash2, Eye, RefreshCw,
  CheckCircle2, Clock, AlertCircle, Search, Filter, Hash,
} from "lucide-react";

/*
  Portal → SMS Bulk + Scheduling page (/portal/sms).
  Sub-flows :
    1. Pick contacts (search + multi-select)
    2. Compose message (with personalization tokens + payment-link inserter)
    3. Send now OR schedule for later
    4. View past schedules / cancel pending ones
*/
const TOKENS = ["name", "company", "phone", "whatsapp", "email", "tag"];

const STATUS_BADGE = {
  pending: { cls: "bg-amber-100 text-amber-800 ring-amber-200", icon: Clock, label: "En attente" },
  running: { cls: "bg-sky-100 text-sky-800 ring-sky-200", icon: RefreshCw, label: "En cours" },
  done: { cls: "bg-emerald-100 text-emerald-800 ring-emerald-200", icon: CheckCircle2, label: "Envoyé" },
  failed: { cls: "bg-rose-100 text-rose-800 ring-rose-200", icon: AlertCircle, label: "Échec" },
  cancelled: { cls: "bg-slate-100 text-slate-700 ring-slate-200", icon: X, label: "Annulé" },
};

function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
}

// Defensive coercer (FastAPI sometimes returns `detail` as an array of validation errors)
function safeText(v) {
  if (v == null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (typeof v === "object") {
    if (typeof v.message === "string") return v.message;
    if (typeof v.detail === "string") return v.detail;
    try { return JSON.stringify(v).slice(0, 300); } catch { return "[objet]"; }
  }
  return String(v);
}

export default function SmsBulk() {
  const [contacts, setContacts] = useState([]);
  const [providers, setProviders] = useState({ default: "auto", active: [] });
  const [features, setFeatures] = useState({});
  const [schedules, setSchedules] = useState([]);
  const [search, setSearch] = useState("");
  const [companyFilter, setCompanyFilter] = useState("");
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [provider, setProvider] = useState("auto");
  const [sender, setSender] = useState("");
  const [message, setMessage] = useState("");
  const [scheduleAt, setScheduleAt] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [clientsRoster, setClientsRoster] = useState([]);
  // Iter40 (2026-02) — Sélecteur de groupes de contacts
  const [groups, setGroups] = useState([]);
  const [selectedGroupIds, setSelectedGroupIds] = useState(new Set());

  const loadAll = async () => {
    try {
      const [cR, fR, pR, sR, rosterR, gR] = await Promise.all([
        apiClient.get("/me/contacts"),
        apiClient.get("/me/features"),
        apiClient.get("/me/sms/providers"),
        apiClient.get("/me/sms/schedules"),
        apiClient.get("/me/clients-roster").catch(() => ({ data: [] })),
        apiClient.get("/me/contact-groups").catch(() => ({ data: [] })),
      ]);
      setContacts(cR.data || []);
      setFeatures(fR.data?.features || {});
      setProviders(pR.data || { default: "auto", active: [] });
      setProvider(pR.data?.default || "auto");
      setSchedules(sR.data || []);
      setClientsRoster(rosterR.data || []);
      setGroups(gR.data || []);
    } catch (err) {
      toast.error(safeText(err?.response?.data?.detail) || "Erreur");
    }
  };

  // Iter40 — Toggle a group : add/remove its contact_ids from the selection.
  const toggleGroup = async (g) => {
    const next = new Set(selectedGroupIds);
    if (next.has(g.id)) next.delete(g.id); else next.add(g.id);
    setSelectedGroupIds(next);
    try {
      const r = await apiClient.post("/me/contact-groups/resolve", {
        group_ids: Array.from(next),
        contact_ids: [],
      });
      const ids = new Set(r.data?.contact_ids || []);
      // Merge with previously hand-picked contacts (preserve manual selection)
      setSelectedIds((prev) => {
        const merged = new Set(ids);
        // Keep manual ones not in any selected group (i.e. extras the user picked individually)
        prev.forEach((cid) => merged.add(cid));
        return merged;
      });
      if (ids.size > 0) {
        toast.success(`${ids.size} contact(s) ajouté(s) depuis ${next.size} groupe(s)`);
      }
    } catch (e) {
      toast.error("Erreur résolution groupes");
    }
  };

  useEffect(() => { loadAll(); }, []);

  // Build list of (label, value) options matching admin clients to filter by:
  // we expose ACME code OR company name. The contact `company` field stores
  // the full company string, so we match on either.
  const companyOptions = useMemo(() => {
    const set = new Map();
    (clientsRoster || []).forEach((c) => {
      const lbl = c.full_name || c.company || c.email;
      if (lbl) set.set(c.id, { label: lbl, value: c.company || lbl, code: c.acme_code });
    });
    // Also fold in any `company` strings present on contacts that don't match
    // a roster entry (so users can filter by ad-hoc company labels)
    contacts.forEach((c) => {
      const v = (c.company || "").trim();
      if (v && !Array.from(set.values()).some((o) => o.value === v)) {
        set.set(`__c_${v}`, { label: v, value: v });
      }
    });
    return Array.from(set.values()).sort((a, b) => a.label.localeCompare(b.label));
  }, [clientsRoster, contacts]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    let arr = contacts.filter((c) => c.phone || c.whatsapp);
    if (companyFilter) {
      const f = companyFilter.toLowerCase();
      arr = arr.filter((c) => (c.company || "").toLowerCase().includes(f));
    }
    if (!q) return arr;
    return arr.filter((c) =>
      [c.name, c.company, c.phone, c.whatsapp, c.email, ...(c.tags || [])]
        .filter(Boolean).join(" ").toLowerCase().includes(q)
    );
  }, [contacts, search, companyFilter]);

  const allSelected = filtered.length > 0 && filtered.every((c) => selectedIds.has(c.id));

  const toggleAll = () => {
    if (allSelected) {
      const next = new Set(selectedIds);
      filtered.forEach((c) => next.delete(c.id));
      setSelectedIds(next);
    } else {
      const next = new Set(selectedIds);
      filtered.forEach((c) => next.add(c.id));
      setSelectedIds(next);
    }
  };

  const toggle = (id) => {
    setSelectedIds((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const insertToken = (tok) => setMessage((m) => m + `{{${tok}}}`);

  const previews = useMemo(() => {
    return Array.from(selectedIds).slice(0, 3).map((id) => {
      const c = contacts.find((x) => x.id === id) || {};
      let body = message;
      const ctx = {
        name: c.name || "",
        company: c.company || "",
        phone: c.phone || "",
        whatsapp: c.whatsapp || "",
        email: c.email || "",
        tag: (c.tags || []).join(", "),
      };
      Object.entries(ctx).forEach(([k, v]) => { body = body.split(`{{${k}}}`).join(v); });
      return { contact: c, body };
    });
  }, [selectedIds, contacts, message]);

  const send = async () => {
    if (!features.sms) { toast.error("SMS non activé"); return; }
    if (selectedIds.size === 0) { toast.error("Sélectionnez au moins 1 destinataire"); return; }
    if (!message.trim()) { toast.error("Message vide"); return; }
    if (message.length > 800) { toast.error("Message trop long"); return; }
    if (selectedIds.size > 500) { toast.error("Maximum 500 destinataires"); return; }
    setSubmitting(true);
    try {
      const body = {
        contact_ids: Array.from(selectedIds),
        message,
        provider,
        sender: sender || undefined,
      };
      if (scheduleAt) {
        const dt = new Date(scheduleAt);
        if (isNaN(dt.getTime())) { toast.error("Date invalide"); setSubmitting(false); return; }
        body.scheduled_at = dt.toISOString();
      }
      const r = await apiClient.post("/me/sms/bulk", body);
      if (r.data?.scheduled) {
        toast.success(`Planifié pour ${fmtDate(r.data.scheduled_at)} (${r.data.recipients} destinataires)`);
      } else {
        toast.success(`${r.data?.sent_ok || 0} envoyés, ${r.data?.sent_ko || 0} échoués${r.data?.skipped?.length ? `, ${r.data.skipped.length} ignorés` : ""}`);
      }
      setMessage(""); setSelectedIds(new Set()); setScheduleAt("");
      loadAll();
    } catch (err) {
      toast.error(safeText(err?.response?.data?.detail) || "Erreur");
    } finally { setSubmitting(false); }
  };

  const cancelSchedule = async (sid) => {
    if (!window.confirm("Annuler cette planification ?")) return;
    try {
      await apiClient.delete(`/me/sms/schedules/${sid}`);
      toast.success("Planification annulée");
      loadAll();
    } catch (err) {
      toast.error(safeText(err?.response?.data?.detail) || "Erreur");
    }
  };

  return (
    <div className="space-y-6 max-w-full" data-testid="sms-bulk-page">
      <div>
        <h1 className="text-3xl font-display font-bold inline-flex items-center gap-2">
          <Send className="h-7 w-7 text-amber-600" /> Envoi SMS — Masse & Planification
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Envoyez un SMS personnalisé à plusieurs contacts en une fois, ou planifiez l'envoi pour plus tard.
        </p>
      </div>

      {!features.sms && (
        <div className="rounded-lg ring-1 ring-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
          La fonctionnalité SMS n'est pas activée pour votre compte.
        </div>
      )}

      <div className="grid lg:grid-cols-2 gap-6">
        {/* LEFT — Contacts picker */}
        <div className="rounded-xl ring-1 ring-slate-200 bg-white p-4 flex flex-col" data-testid="sms-contacts-block">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-display font-semibold inline-flex items-center gap-2">
              <Users className="h-4 w-4" /> Destinataires
              <span className="text-xs bg-amber-100 text-amber-900 px-2 py-0.5 rounded-full ml-1">{selectedIds.size}</span>
            </h3>
            <button onClick={toggleAll} className="text-xs text-sawali-blue hover:underline" data-testid="sms-toggle-all">
              {allSelected ? "Tout désélectionner" : "Tout sélectionner"} ({filtered.length})
            </button>
          </div>
          <div className="relative mb-2">
            <Search className="h-4 w-4 absolute left-2.5 top-2.5 text-slate-400" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Rechercher (nom, téléphone, tag…)"
              className="w-full pl-9 pr-3 py-2 rounded-lg border border-slate-300 text-sm" data-testid="sms-contacts-search" />
          </div>
          <div className="flex gap-2 mb-3">
            <select
              value={companyFilter}
              onChange={(e) => setCompanyFilter(e.target.value)}
              className="flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
              data-testid="sms-company-filter"
            >
              <option value="">Tous les clients</option>
              {companyOptions.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}{o.code ? ` [${o.code}]` : ""}
                </option>
              ))}
            </select>
            {companyFilter && (
              <button
                onClick={() => setCompanyFilter("")}
                className="text-xs text-slate-500 hover:text-rose-600 px-2"
                data-testid="sms-company-filter-clear"
              >
                ✕ Effacer
              </button>
            )}
          </div>
          {/* Iter40 — Sélecteur de groupes de contacts */}
          {groups.length > 0 && (
            <div className="mb-3" data-testid="sms-groups-row">
              <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5 inline-flex items-center gap-1">
                <Users className="h-3 w-3" /> Groupes ({groups.length})
              </div>
              <div className="flex flex-wrap gap-1">
                {groups.map((g) => {
                  const active = selectedGroupIds.has(g.id);
                  return (
                    <button
                      key={g.id}
                      type="button"
                      onClick={() => toggleGroup(g)}
                      className={`text-[11px] px-2 py-0.5 rounded-full ring-1 inline-flex items-center gap-1 transition ${active ? "bg-fuchsia-100 ring-fuchsia-400 text-fuchsia-800" : "bg-white ring-slate-200 text-slate-600 hover:ring-fuchsia-300"}`}
                      data-testid={`sms-group-${g.id}`}
                    >
                      <span className="h-2 w-2 rounded-full" style={{ background: g.color || "#6366f1" }} />
                      {g.name}
                      <span className="opacity-60">({g.contact_count})</span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
          <div className="flex-1 overflow-y-auto max-h-[420px] divide-y divide-slate-100 ring-1 ring-slate-100 rounded-lg">
            {filtered.length === 0 && (
              <p className="text-center text-slate-400 italic py-8 text-sm">Aucun contact avec téléphone disponible.</p>
            )}
            {filtered.map((c) => {
              const checked = selectedIds.has(c.id);
              return (
                <label key={c.id} className={`flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-slate-50 ${checked ? "bg-amber-50" : ""}`} data-testid={`sms-contact-${c.id}`}>
                  <input type="checkbox" checked={checked} onChange={() => toggle(c.id)} className="accent-amber-600" />
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold text-sm text-slate-800 truncate">{c.name}</div>
                    <div className="text-[11px] text-slate-500 font-mono truncate">{c.phone || c.whatsapp}{c.company ? ` • ${c.company}` : ""}</div>
                  </div>
                </label>
              );
            })}
          </div>
        </div>

        {/* RIGHT — Compose */}
        <div className="rounded-xl ring-1 ring-slate-200 bg-white p-4 flex flex-col" data-testid="sms-compose-block">
          <h3 className="font-display font-semibold inline-flex items-center gap-2 mb-3">
            <Hash className="h-4 w-4" /> Message
          </h3>
          <div className="grid grid-cols-2 gap-2 mb-2">
            <label className="text-xs font-semibold">
              Fournisseur
              <select value={provider} onChange={(e) => setProvider(e.target.value)} className="w-full mt-1 rounded-lg border border-slate-300 px-2 py-1.5 text-sm" data-testid="sms-bulk-provider">
                <option value="auto">Auto (selon préfixe)</option>
                {providers.active.map((p) => (
                  <option key={p} value={p}>
                    {p === "bird" ? "📡 Bird.com" : p.toUpperCase()}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs font-semibold">
              Expéditeur (optionnel, max 11)
              <input value={sender} onChange={(e) => setSender(e.target.value.slice(0, 11))} placeholder="SAWALI"
                className="w-full mt-1 rounded-lg border border-slate-300 px-2 py-1.5 text-sm" data-testid="sms-bulk-sender" />
            </label>
          </div>
          <div className="flex flex-wrap gap-1 mb-1.5">
            <span className="text-[10px] uppercase tracking-wider text-slate-400 self-center mr-1">Insérer :</span>
            {TOKENS.map((t) => (
              <button key={t} type="button" onClick={() => insertToken(t)} className="text-[10px] rounded ring-1 ring-slate-200 bg-slate-50 hover:bg-slate-100 px-2 py-0.5 font-mono" data-testid={`sms-token-${t}`}>
                {`{{${t}}}`}
              </button>
            ))}
          </div>
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value.slice(0, 800))}
            rows={6}
            placeholder="Bonjour {{name}}, votre facture est prête. Réglez ici : https://…/pay/abc"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono"
            data-testid="sms-bulk-message"
          />
          <p className="text-[10px] text-slate-400 mt-0.5">
            {message.length}/800 caractères {message.length > 160 && <span className="text-amber-600">— attention, peut être facturé en plusieurs SMS au-delà de 160 car.</span>}
          </p>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <label className="text-xs font-semibold">
              Planifier l'envoi (optionnel)
              <input
                type="datetime-local"
                value={scheduleAt}
                onChange={(e) => setScheduleAt(e.target.value)}
                className="w-full mt-1 rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
                data-testid="sms-bulk-schedule-at"
              />
            </label>
            <div className="flex items-end">
              <button
                onClick={() => setPreviewOpen(true)}
                disabled={selectedIds.size === 0 || !message.trim()}
                className="w-full inline-flex items-center justify-center gap-1.5 rounded-lg ring-1 ring-slate-300 bg-white hover:bg-slate-50 px-3 py-2 text-sm disabled:opacity-50"
                data-testid="sms-bulk-preview"
              >
                <Eye className="h-4 w-4" /> Aperçu
              </button>
            </div>
          </div>
          <button
            onClick={send}
            disabled={submitting || !features.sms || selectedIds.size === 0 || !message.trim() || providers.active.length === 0}
            className="mt-4 inline-flex items-center justify-center gap-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white px-4 py-2.5 text-sm font-semibold disabled:opacity-50"
            data-testid="sms-bulk-send-btn"
          >
            {scheduleAt ? <CalendarClock className="h-4 w-4" /> : <Send className="h-4 w-4" />}
            {submitting ? "Traitement…" : scheduleAt ? `Planifier l'envoi (${selectedIds.size} contacts)` : `Envoyer maintenant (${selectedIds.size})`}
          </button>
        </div>
      </div>

      {/* Schedules list */}
      <div className="rounded-xl ring-1 ring-slate-200 bg-white p-4" data-testid="sms-schedules-block">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-display font-semibold inline-flex items-center gap-2">
            <CalendarClock className="h-4 w-4" /> Planifications & historique des envois groupés
          </h3>
          <button onClick={loadAll} className="text-xs inline-flex items-center gap-1 hover:underline">
            <RefreshCw className="h-3 w-3" /> Actualiser
          </button>
        </div>
        {schedules.length === 0 ? (
          <p className="text-sm text-slate-400 italic py-6 text-center">Aucune planification.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-500 uppercase text-[10px]">
                <tr>
                  <th className="text-left px-3 py-2">Programmé pour</th>
                  <th className="text-left px-3 py-2 hidden md:table-cell">Message</th>
                  <th className="text-center px-3 py-2 hidden sm:table-cell">Dest.</th>
                  <th className="text-left px-3 py-2 hidden lg:table-cell">Provider</th>
                  <th className="text-left px-3 py-2">Statut</th>
                  <th className="text-right px-3 py-2">Action</th>
                </tr>
              </thead>
              <tbody>
                {schedules.map((sc) => {
                  const sb = STATUS_BADGE[sc.status] || STATUS_BADGE.pending;
                  const Icon = sb.icon;
                  return (
                    <tr key={sc.id} className="border-t border-slate-100 hover:bg-slate-50" data-testid={`sms-sched-${sc.id}`}>
                      <td className="px-3 py-2 whitespace-nowrap text-xs">
                        <div>{fmtDate(sc.scheduled_at)}</div>
                        {/* Mobile-only context */}
                        <div className="md:hidden text-[10px] text-slate-500 mt-0.5 max-w-[160px] truncate" title={sc.message_template}>
                          {sc.message_template}
                        </div>
                        <div className="sm:hidden text-[10px] text-slate-400 mt-0.5">
                          {(sc.contact_ids || []).length} dest. • {(sc.provider || "auto").toUpperCase()}
                        </div>
                      </td>
                      <td className="px-3 py-2 hidden md:table-cell max-w-[300px] truncate text-xs text-slate-600" title={sc.message_template}>{sc.message_template}</td>
                      <td className="px-3 py-2 hidden sm:table-cell text-center font-mono text-xs">
                        {(sc.contact_ids || []).length}
                        {sc.result_summary && <span className="text-[10px] text-emerald-700 block">✓ {sc.result_summary.sent_ok || 0}</span>}
                      </td>
                      <td className="px-3 py-2 hidden lg:table-cell text-xs">{(sc.provider || "auto").toUpperCase()}</td>
                      <td className="px-3 py-2">
                        <span className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded ring-1 ${sb.cls}`}>
                          <Icon className={`h-3 w-3 ${sc.status === "running" ? "animate-spin" : ""}`} /> <span className="hidden sm:inline">{sb.label}</span>
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right">
                        {sc.status === "pending" && (
                          <button onClick={() => cancelSchedule(sc.id)} className="text-xs text-rose-600 hover:underline inline-flex items-center gap-1" data-testid={`sms-sched-cancel-${sc.id}`}>
                            <Trash2 className="h-3 w-3" /> <span className="hidden sm:inline">Annuler</span>
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {previewOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={(e) => e.target === e.currentTarget && setPreviewOpen(false)} data-testid="sms-preview-modal">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[88vh] overflow-y-auto">
            <div className="flex items-center justify-between px-5 py-3 border-b">
              <h3 className="font-display font-bold inline-flex items-center gap-2">
                <Eye className="h-4 w-4" /> Aperçu personnalisé (3 premiers destinataires)
              </h3>
              <button onClick={() => setPreviewOpen(false)} className="text-slate-500"><X className="h-4 w-4" /></button>
            </div>
            <div className="p-5 space-y-3">
              {previews.map((p, i) => (
                <div key={i} className="rounded-lg ring-1 ring-slate-200 p-3 bg-slate-50" data-testid={`sms-preview-${i}`}>
                  <p className="text-[11px] uppercase tracking-wider text-slate-500 mb-1">
                    Pour : <strong>{p.contact.name}</strong> <code className="bg-white ring-1 ring-slate-200 px-1 ml-1">{p.contact.phone || p.contact.whatsapp}</code>
                  </p>
                  <p className="text-sm text-slate-800 font-mono whitespace-pre-wrap">{p.body}</p>
                  <p className="text-[10px] text-slate-400 mt-1">{p.body.length} caractères</p>
                </div>
              ))}
              {selectedIds.size > 3 && (
                <p className="text-xs text-slate-500 text-center">… et {selectedIds.size - 3} autre(s) destinataire(s).</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
