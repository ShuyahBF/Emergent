import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  Send, Users, CalendarClock, X, Trash2, Eye, RefreshCw,
  CheckCircle2, Clock, AlertCircle, Search, Hash, MessageCircle,
} from "lucide-react";
import { parseTemplate, buildButtonSpecs } from "@/lib/waTemplate";

/*
  Portal → WhatsApp Bulk + Scheduling page (/portal/whatsapp-bulk).
  Mirrors the SMS bulk flow but uses Meta-approved templates:
    1. Pick a template (only APPROVED + admin-allowed are listed)
    2. Fill BODY variables (and HEADER/BUTTON vars when the template requires them)
       — each variable supports personalization tokens like {{name}}, {{company}}, {{client_code}}.
    3. Pick contacts (search + multi-select, optional company filter)
    4. Send now OR schedule for later (cron picks it up & runs per-contact)
    5. View past schedules and cancel pending ones.
  Backend endpoint: POST /me/whatsapp/bulk
*/

// Personalization tokens available for body/header variables. Resolved per-contact at send time.
// `client_code` resolves to the contact's `unique_code` (e.g. 2026-ACME-0001).
const TOKENS = ["name", "company", "phone", "email", "client_code", "today", "tomorrow"];

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

// Render a token-aware preview against a contact's fields. Mirrors the backend
// `_render_variable` substitutions so users see exactly what each contact will receive.
function renderTokens(text, c) {
  if (!text) return "";
  const ctx = {
    name: c?.name || "",
    full_name: c?.name || "",
    company: c?.company || "",
    phone: c?.phone || c?.whatsapp || "",
    whatsapp: c?.whatsapp || c?.phone || "",
    email: c?.email || "",
    client_code: c?.unique_code || "",
    today: new Date().toLocaleDateString("fr-FR"),
    tomorrow: new Date(Date.now() + 86400000).toLocaleDateString("fr-FR"),
  };
  return text.replace(/\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}/g, (_, k) => ctx[k.toLowerCase()] ?? "");
}

// Replace the {{1}}, {{2}} … placeholders of a Meta template's body/header text
// with the values the user typed (after token resolution).
function fillPositional(template, values) {
  if (!template) return "";
  return template.replace(/\{\{\s*(\d+)\s*\}\}/g, (_, n) => values[parseInt(n, 10) - 1] ?? "");
}

export default function WaBulk() {
  const [contacts, setContacts] = useState([]);
  const [features, setFeatures] = useState({});
  const [templates, setTemplates] = useState([]);
  const [templatesConfigured, setTemplatesConfigured] = useState(true);
  const [schedules, setSchedules] = useState([]);
  const [clientsRoster, setClientsRoster] = useState([]);

  const [search, setSearch] = useState("");
  const [companyFilter, setCompanyFilter] = useState("");
  const [selectedIds, setSelectedIds] = useState(new Set());

  const [templateName, setTemplateName] = useState("");
  const [language, setLanguage] = useState("fr");
  const [bodyVars, setBodyVars] = useState([]);     // string[]
  const [headerVars, setHeaderVars] = useState([]); // string[] (only for HEADER format=TEXT with vars)
  const [buttonVars, setButtonVars] = useState([]); // string[][]
  const [scheduleAt, setScheduleAt] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [activeTokenField, setActiveTokenField] = useState(null); // {kind:"body"|"header"|"btn"|"sms_fb", index, btnIdx?}
  // SMS fallback config — when WhatsApp delivery fails for a contact, retry via SMS
  const [smsFallback, setSmsFallback] = useState(false);
  const [smsFallbackMessage, setSmsFallbackMessage] = useState("");
  const [smsProviders, setSmsProviders] = useState({ default: "auto", active: [] });
  const [smsProvider, setSmsProvider] = useState("auto");
  const [smsSender, setSmsSender] = useState("");
  // Iter40 (2026-02) — Sélecteur de groupes de contacts
  const [groups, setGroups] = useState([]);
  const [selectedGroupIds, setSelectedGroupIds] = useState(new Set());

  const loadAll = async () => {
    try {
      const [cR, fR, tR, sR, rosterR, pR, gR] = await Promise.all([
        apiClient.get("/me/contacts"),
        apiClient.get("/me/features"),
        apiClient.get("/me/whatsapp/templates"),
        apiClient.get("/me/messaging/schedules").catch(() => ({ data: [] })),
        apiClient.get("/me/clients-roster").catch(() => ({ data: [] })),
        apiClient.get("/me/sms/providers").catch(() => ({ data: { default: "auto", active: [] } })),
        apiClient.get("/me/contact-groups").catch(() => ({ data: [] })),
      ]);
      setContacts(cR.data || []);
      setFeatures(fR.data?.features || {});
      setTemplates(tR.data?.items || []);
      setTemplatesConfigured(tR.data?.configured !== false);
      setSchedules(sR.data || []);
      setClientsRoster(rosterR.data || []);
      setSmsProviders(pR.data || { default: "auto", active: [] });
      setSmsProvider(pR.data?.default || "auto");
      setGroups(gR.data || []);
    } catch (err) {
      toast.error(safeText(err?.response?.data?.detail) || "Erreur de chargement");
    }
  };

  const toggleGroup = async (g) => {
    const next = new Set(selectedGroupIds);
    if (next.has(g.id)) next.delete(g.id); else next.add(g.id);
    setSelectedGroupIds(next);
    try {
      const r = await apiClient.post("/me/contact-groups/resolve", {
        group_ids: Array.from(next), contact_ids: [],
      });
      const ids = new Set(r.data?.contact_ids || []);
      setSelectedIds((prev) => {
        const merged = new Set(ids);
        prev.forEach((cid) => merged.add(cid));
        return merged;
      });
      if (ids.size > 0) {
        toast.success(`${ids.size} contact(s) ajouté(s) depuis ${next.size} groupe(s)`);
      }
    } catch {
      toast.error("Erreur résolution groupes");
    }
  };

  useEffect(() => { loadAll(); }, []);

  const selectedTemplate = useMemo(
    () => templates.find((t) => t.name === templateName) || null,
    [templates, templateName],
  );
  const parsed = useMemo(() => (selectedTemplate ? parseTemplate(selectedTemplate) : null), [selectedTemplate]);

  // Sync the variable arrays whenever the template changes so the form fields
  // line up with the chosen template's placeholders.
  useEffect(() => {
    if (!parsed) {
      setBodyVars([]); setHeaderVars([]); setButtonVars([]);
      return;
    }
    setBodyVars(Array.from({ length: parsed.body.varCount || 0 }, () => ""));
    setHeaderVars(parsed.header && parsed.header.format === "TEXT"
      ? Array.from({ length: parsed.header.varCount || 0 }, () => "")
      : []);
    setButtonVars((parsed.buttons || []).map((b) => Array.from({ length: b.urlVarCount || 0 }, () => "")));
    setLanguage(selectedTemplate?.language || "fr");
  }, [parsed, selectedTemplate]);

  const companyOptions = useMemo(() => {
    const set = new Map();
    (clientsRoster || []).forEach((c) => {
      const lbl = c.full_name || c.company || c.email;
      if (lbl) set.set(c.id, { label: lbl, value: c.company || lbl, code: c.client_code });
    });
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
    let arr = contacts.filter((c) => c.whatsapp || c.phone);
    if (companyFilter) {
      const f = companyFilter.toLowerCase();
      arr = arr.filter((c) => (c.company || "").toLowerCase().includes(f));
    }
    if (!q) return arr;
    return arr.filter((c) =>
      [c.name, c.company, c.phone, c.whatsapp, c.email, c.unique_code, ...(c.tags || [])]
        .filter(Boolean).join(" ").toLowerCase().includes(q),
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

  const toggle = (id) => setSelectedIds((cur) => {
    const next = new Set(cur);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  // Insert a {{token}} into whichever variable input the user last focused.
  const insertToken = (tok) => {
    if (!activeTokenField) {
      toast.message("Cliquez d'abord dans un champ variable.");
      return;
    }
    const piece = `{{${tok}}}`;
    if (activeTokenField.kind === "body") {
      setBodyVars((prev) => prev.map((v, i) => (i === activeTokenField.index ? (v + piece) : v)));
    } else if (activeTokenField.kind === "header") {
      setHeaderVars((prev) => prev.map((v, i) => (i === activeTokenField.index ? (v + piece) : v)));
    } else if (activeTokenField.kind === "btn") {
      setButtonVars((prev) => prev.map((arr, bi) =>
        bi === activeTokenField.btnIdx
          ? arr.map((v, i) => (i === activeTokenField.index ? (v + piece) : v))
          : arr,
      ));
    } else if (activeTokenField.kind === "sms_fb") {
      setSmsFallbackMessage((prev) => prev + piece);
    }
  };

  // Live preview against the first 3 selected contacts
  const previews = useMemo(() => {
    if (!parsed) return [];
    return Array.from(selectedIds).slice(0, 3).map((id) => {
      const c = contacts.find((x) => x.id === id) || {};
      const headerResolved = headerVars.map((v) => renderTokens(v, c));
      const bodyResolved = bodyVars.map((v) => renderTokens(v, c));
      const headerText = parsed.header?.format === "TEXT"
        ? fillPositional(parsed.header.text, headerResolved)
        : null;
      const bodyText = fillPositional(parsed.body.text, bodyResolved);
      return { contact: c, headerText, bodyText };
    });
  }, [parsed, selectedIds, contacts, headerVars, bodyVars]);

  const send = async () => {
    if (!features.whatsapp) { toast.error("WhatsApp non activé pour votre compte"); return; }
    if (!templateName) { toast.error("Choisissez un template"); return; }
    if (selectedIds.size === 0) { toast.error("Sélectionnez au moins 1 destinataire"); return; }
    if (selectedIds.size > 500) { toast.error("Maximum 500 destinataires"); return; }
    // Required-vars check
    const missingBody = bodyVars.findIndex((v) => !(v || "").trim());
    if (parsed?.body?.varCount && missingBody !== -1) {
      toast.error(`Variable de corps {{${missingBody + 1}}} requise`); return;
    }
    if (parsed?.header?.format === "TEXT" && parsed.header.varCount > 0) {
      const m = headerVars.findIndex((v) => !(v || "").trim());
      if (m !== -1) { toast.error(`Variable d'en-tête {{${m + 1}}} requise`); return; }
    }

    setSubmitting(true);
    try {
      const body = {
        contact_ids: Array.from(selectedIds),
        template_name: templateName,
        language_code: language,
        variables: bodyVars,
        header_text: parsed?.header?.format === "TEXT" && headerVars.length
          ? headerVars.join(" ")  // Meta only supports 1 text param per HEADER → join, then backend renders
          : undefined,
        // Iter43-fix24aj — Send button_specs (knows actual sub_type) instead
        // of raw button_vars. Avoids Meta error #131009 on QUICK_REPLY templates.
        button_specs: parsed ? buildButtonSpecs(parsed, buttonVars) : null,
      };
      // For HEADER text, Meta accepts only a single positional placeholder per header.
      // Most approved templates have exactly 1 var, so we send the first non-empty value.
      if (parsed?.header?.format === "TEXT" && headerVars.length) {
        body.header_text = headerVars[0] || "";
      }
      if (smsFallback && (smsFallbackMessage || "").trim()) {
        body.sms_fallback = true;
        body.sms_fallback_message = smsFallbackMessage;
        body.sms_fallback_provider = smsProvider || "auto";
        if (smsSender) body.sms_fallback_sender = smsSender.slice(0, 11);
      }
      if (scheduleAt) {
        const dt = new Date(scheduleAt);
        if (isNaN(dt.getTime())) { toast.error("Date invalide"); setSubmitting(false); return; }
        body.scheduled_at = dt.toISOString();
        body.title = `WA bulk ${templateName}`;
      }
      const r = await apiClient.post("/me/whatsapp/bulk", body);
      if (r.data?.scheduled) {
        toast.success(`Planifié pour ${fmtDate(r.data.scheduled_at)} (${r.data.recipients} destinataire(s))`);
      } else {
        const ok = r.data?.sent_ok || 0;
        const ko = r.data?.sent_ko || 0;
        const sk = r.data?.skipped?.length || 0;
        const fbOk = r.data?.fallback_ok || 0;
        const fbCount = r.data?.fallback_results?.length || 0;
        const fbMsg = fbCount > 0 ? ` — Repli SMS : ${fbOk}/${fbCount} envoyé(s)` : "";
        toast.success(`${ok} envoyé(s), ${ko} échec(s)${sk ? `, ${sk} ignoré(s)` : ""}${fbMsg}`);
      }
      setSelectedIds(new Set());
      setScheduleAt("");
      loadAll();
    } catch (err) {
      toast.error(safeText(err?.response?.data?.detail) || "Erreur d'envoi");
    } finally { setSubmitting(false); }
  };

  const cancelSchedule = async (sid) => {
    if (!window.confirm("Annuler cette planification ?")) return;
    try {
      await apiClient.delete(`/me/messaging/schedules/${sid}`);
      toast.success("Planification annulée");
      loadAll();
    } catch (err) {
      toast.error(safeText(err?.response?.data?.detail) || "Erreur");
    }
  };

  return (
    <div className="space-y-6 max-w-full" data-testid="wa-bulk-page">
      <div>
        <h1 className="text-3xl font-display font-bold inline-flex items-center gap-2">
          <MessageCircle className="h-7 w-7 text-emerald-600" /> Envoi WhatsApp — Masse & Planification
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Envoyez un template WhatsApp Business approuvé à plusieurs contacts en une fois, ou planifiez l'envoi pour plus tard.
          Chaque variable peut contenir des jetons de personnalisation (<code className="font-mono">{"{{name}}"}</code>, <code className="font-mono">{"{{company}}"}</code>…) qui seront remplacés par les infos du contact destinataire.
        </p>
      </div>

      {!features.whatsapp && (
        <div className="rounded-lg ring-1 ring-amber-200 bg-amber-50 p-3 text-xs text-amber-900" data-testid="wa-bulk-feature-off">
          La fonctionnalité WhatsApp n'est pas activée pour votre compte. Contactez votre administrateur.
        </div>
      )}
      {!templatesConfigured && (
        <div className="rounded-lg ring-1 ring-rose-200 bg-rose-50 p-3 text-xs text-rose-900">
          WhatsApp Business non configuré côté serveur (token ou WABA ID manquant).
        </div>
      )}

      <div className="grid lg:grid-cols-2 gap-6">
        {/* LEFT — Contacts picker */}
        <div className="rounded-xl ring-1 ring-slate-200 bg-white p-4 flex flex-col" data-testid="wa-bulk-contacts-block">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-display font-semibold inline-flex items-center gap-2">
              <Users className="h-4 w-4" /> Destinataires
              <span className="text-xs bg-emerald-100 text-emerald-900 px-2 py-0.5 rounded-full ml-1">{selectedIds.size}</span>
            </h3>
            <button onClick={toggleAll} className="text-xs text-sawali-blue hover:underline" data-testid="wa-bulk-toggle-all">
              {allSelected ? "Tout désélectionner" : "Tout sélectionner"} ({filtered.length})
            </button>
          </div>
          <div className="relative mb-2">
            <Search className="h-4 w-4 absolute left-2.5 top-2.5 text-slate-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Rechercher (nom, téléphone, code unique, tag…)"
              className="w-full pl-9 pr-3 py-2 rounded-lg border border-slate-300 text-sm"
              data-testid="wa-bulk-contacts-search"
            />
          </div>
          <div className="flex gap-2 mb-3">
            <select
              value={companyFilter}
              onChange={(e) => setCompanyFilter(e.target.value)}
              className="flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
              data-testid="wa-bulk-company-filter"
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
                data-testid="wa-bulk-company-filter-clear"
              >
                ✕ Effacer
              </button>
            )}
          </div>
          {/* Iter40 — Sélecteur de groupes de contacts */}
          {groups.length > 0 && (
            <div className="mb-3" data-testid="wa-bulk-groups-row">
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
                      className={`text-[11px] px-2 py-0.5 rounded-full ring-1 inline-flex items-center gap-1 transition ${active ? "bg-emerald-100 ring-emerald-400 text-emerald-800" : "bg-white ring-slate-200 text-slate-600 hover:ring-emerald-300"}`}
                      data-testid={`wa-bulk-group-${g.id}`}
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
              <p className="text-center text-slate-400 italic py-8 text-sm">Aucun contact avec numéro WhatsApp/Téléphone disponible.</p>
            )}
            {filtered.map((c) => {
              const checked = selectedIds.has(c.id);
              return (
                <label
                  key={c.id}
                  className={`flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-slate-50 ${checked ? "bg-emerald-50" : ""}`}
                  data-testid={`wa-bulk-contact-${c.id}`}
                >
                  <input type="checkbox" checked={checked} onChange={() => toggle(c.id)} className="accent-emerald-600" />
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold text-sm text-slate-800 truncate">{c.name}</div>
                    <div className="text-[11px] text-slate-500 font-mono truncate">
                      {c.whatsapp || c.phone}
                      {c.unique_code ? <span className="text-slate-400"> • {c.unique_code}</span> : null}
                      {c.company ? ` • ${c.company}` : ""}
                    </div>
                  </div>
                </label>
              );
            })}
          </div>
        </div>

        {/* RIGHT — Compose */}
        <div className="rounded-xl ring-1 ring-slate-200 bg-white p-4 flex flex-col" data-testid="wa-bulk-compose-block">
          <h3 className="font-display font-semibold inline-flex items-center gap-2 mb-3">
            <Hash className="h-4 w-4" /> Template & variables
          </h3>
          <label className="text-xs font-semibold mb-2 block">
            Template approuvé
            <select
              value={templateName}
              onChange={(e) => setTemplateName(e.target.value)}
              className="w-full mt-1 rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
              data-testid="wa-bulk-template-select"
            >
              <option value="">— Choisir un template —</option>
              {templates.map((t) => (
                <option key={t.name} value={t.name}>
                  {t.name} ({t.language || "fr"}) — {t.note_description || (t.category || "MARKETING")}
                </option>
              ))}
            </select>
          </label>

          {parsed && (
            <div className="rounded-lg ring-1 ring-emerald-200 bg-emerald-50/40 p-3 text-xs space-y-2 mb-3" data-testid="wa-bulk-template-preview">
              {parsed.header && (
                <div>
                  <span className="text-[10px] uppercase tracking-wider text-emerald-700 font-semibold">En-tête ({parsed.header.format})</span>
                  <p className="text-slate-700 mt-0.5">{parsed.header.text || "[média]"}</p>
                </div>
              )}
              <div>
                <span className="text-[10px] uppercase tracking-wider text-emerald-700 font-semibold">Corps</span>
                <p className="text-slate-700 mt-0.5 whitespace-pre-wrap">{parsed.body.text}</p>
              </div>
              {parsed.footer?.text && (
                <p className="text-[10px] text-slate-500 italic">{parsed.footer.text}</p>
              )}
              {(parsed.buttons || []).length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {parsed.buttons.map((b, i) => (
                    <span key={i} className="text-[10px] rounded-full bg-white ring-1 ring-emerald-300 px-2 py-0.5 text-emerald-800">
                      {b.text} {b.type === "URL" ? `→ ${b.url}` : (b.phone_number ? `☎ ${b.phone_number}` : "")}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Token toolbar */}
          {parsed && (
            <div className="flex flex-wrap gap-1 mb-1.5">
              <span className="text-[10px] uppercase tracking-wider text-slate-400 self-center mr-1">Insérer :</span>
              {TOKENS.map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => insertToken(t)}
                  className="text-[10px] rounded ring-1 ring-slate-200 bg-slate-50 hover:bg-slate-100 px-2 py-0.5 font-mono"
                  data-testid={`wa-bulk-token-${t}`}
                >
                  {`{{${t}}}`}
                </button>
              ))}
            </div>
          )}

          {/* HEADER vars (only TEXT format with placeholders) */}
          {parsed?.header?.format === "TEXT" && parsed.header.varCount > 0 && (
            <div className="space-y-1.5 mb-2" data-testid="wa-bulk-header-vars">
              <p className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">En-tête — variables</p>
              {headerVars.map((v, i) => (
                <input
                  key={i}
                  value={v}
                  onChange={(e) => setHeaderVars((p) => p.map((x, j) => j === i ? e.target.value : x))}
                  onFocus={() => setActiveTokenField({ kind: "header", index: i })}
                  placeholder={`{{${i + 1}}}`}
                  className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm font-mono"
                  data-testid={`wa-bulk-header-var-${i}`}
                />
              ))}
            </div>
          )}

          {/* BODY vars */}
          {parsed?.body?.varCount > 0 && (
            <div className="space-y-1.5 mb-2" data-testid="wa-bulk-body-vars">
              <p className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">Corps — variables</p>
              {bodyVars.map((v, i) => (
                <input
                  key={i}
                  value={v}
                  onChange={(e) => setBodyVars((p) => p.map((x, j) => j === i ? e.target.value : x))}
                  onFocus={() => setActiveTokenField({ kind: "body", index: i })}
                  placeholder={`{{${i + 1}}} — ex. {{name}} ou texte fixe`}
                  className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm font-mono"
                  data-testid={`wa-bulk-body-var-${i}`}
                />
              ))}
            </div>
          )}

          {/* BUTTON vars */}
          {(parsed?.buttons || []).map((b, bi) => b.urlVarCount > 0 && (
            <div key={bi} className="space-y-1.5 mb-2" data-testid={`wa-bulk-btn-vars-${bi}`}>
              <p className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">Bouton « {b.text} » — variables URL</p>
              {(buttonVars[bi] || []).map((v, i) => (
                <input
                  key={i}
                  value={v}
                  onChange={(e) => setButtonVars((p) => p.map((arr, x) => x === bi
                    ? arr.map((y, j) => j === i ? e.target.value : y)
                    : arr,
                  ))}
                  onFocus={() => setActiveTokenField({ kind: "btn", btnIdx: bi, index: i })}
                  placeholder={`{{${i + 1}}} — appended to ${b.url}`}
                  className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm font-mono"
                  data-testid={`wa-bulk-btn-var-${bi}-${i}`}
                />
              ))}
            </div>
          ))}

          {/* SMS fallback toggle — when WA delivery fails, retry via SMS */}
          <div
            className={`mt-3 rounded-xl ring-1 p-3 transition ${smsFallback ? "ring-amber-300 bg-amber-50" : "ring-slate-200 bg-slate-50"}`}
            data-testid="wa-bulk-sms-fallback-block"
          >
            <label className="flex items-start gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={smsFallback}
                onChange={(e) => setSmsFallback(e.target.checked)}
                disabled={!features.sms}
                className="mt-0.5 accent-amber-600"
                data-testid="wa-bulk-sms-fallback-toggle"
              />
              <div className="flex-1">
                <p className="text-xs font-semibold text-slate-800">
                  Repli SMS automatique en cas d'échec WhatsApp
                  {!features.sms && <span className="ml-1 text-[10px] text-rose-600">(SMS non activé)</span>}
                </p>
                <p className="text-[10px] text-slate-500 leading-snug mt-0.5">
                  Si le WhatsApp ne peut être délivré (numéro non WA, hors fenêtre 24 h, erreur Meta…), un SMS sera automatiquement envoyé au numéro <code className="font-mono">phone</code> du contact.
                  Maximise le taux de délivrance tout en gardant WhatsApp en priorité (gratuit en initiation business).
                </p>
              </div>
            </label>
            {smsFallback && (
              <div className="mt-3 space-y-2" data-testid="wa-bulk-sms-fallback-details">
                <div className="grid grid-cols-2 gap-2">
                  <label className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                    Fournisseur SMS
                    <select
                      value={smsProvider}
                      onChange={(e) => setSmsProvider(e.target.value)}
                      className="w-full mt-1 rounded-lg border border-slate-300 px-2 py-1.5 text-xs"
                      data-testid="wa-bulk-sms-fb-provider"
                    >
                      <option value="auto">Auto (selon préfixe)</option>
                      {(smsProviders.active || []).map((p) => (
                        <option key={p} value={p}>
                          {p === "bird" ? "📡 Bird.com" : p.toUpperCase()}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                    Expéditeur (max 11)
                    <input
                      value={smsSender}
                      onChange={(e) => setSmsSender(e.target.value.slice(0, 11))}
                      placeholder="SAWALI"
                      className="w-full mt-1 rounded-lg border border-slate-300 px-2 py-1.5 text-xs"
                      data-testid="wa-bulk-sms-fb-sender"
                    />
                  </label>
                </div>
                <textarea
                  value={smsFallbackMessage}
                  onChange={(e) => setSmsFallbackMessage(e.target.value.slice(0, 800))}
                  onFocus={() => setActiveTokenField({ kind: "sms_fb" })}
                  rows={3}
                  placeholder="Bonjour {{name}}, votre WA n'a pas pu être délivré — voici le message en SMS…"
                  className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-xs font-mono"
                  data-testid="wa-bulk-sms-fb-message"
                />
                <p className="text-[10px] text-slate-500">
                  {smsFallbackMessage.length}/800 caractères. Les jetons <code className="font-mono">{"{{name}}"}</code>, <code className="font-mono">{"{{company}}"}</code>… fonctionnent aussi ici.
                </p>
              </div>
            )}
          </div>

          {/* Schedule + actions */}
          <div className="mt-3 grid grid-cols-2 gap-2">
            <label className="text-xs font-semibold">
              Planifier l'envoi (optionnel)
              <input
                type="datetime-local"
                value={scheduleAt}
                onChange={(e) => setScheduleAt(e.target.value)}
                className="w-full mt-1 rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
                data-testid="wa-bulk-schedule-at"
              />
            </label>
            <div className="flex items-end">
              <button
                onClick={() => setPreviewOpen(true)}
                disabled={selectedIds.size === 0 || !templateName}
                className="w-full inline-flex items-center justify-center gap-1.5 rounded-lg ring-1 ring-slate-300 bg-white hover:bg-slate-50 px-3 py-2 text-sm disabled:opacity-50"
                data-testid="wa-bulk-preview-btn"
              >
                <Eye className="h-4 w-4" /> Aperçu
              </button>
            </div>
          </div>

          <button
            onClick={send}
            disabled={submitting || !features.whatsapp || selectedIds.size === 0 || !templateName}
            className="mt-4 inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2.5 text-sm font-semibold disabled:opacity-50"
            data-testid="wa-bulk-send-btn"
          >
            {scheduleAt ? <CalendarClock className="h-4 w-4" /> : <Send className="h-4 w-4" />}
            {submitting ? "Traitement…" : scheduleAt
              ? `Planifier l'envoi (${selectedIds.size} contact(s))`
              : `Envoyer maintenant (${selectedIds.size})`}
          </button>
        </div>
      </div>

      {/* Schedules list */}
      <div className="rounded-xl ring-1 ring-slate-200 bg-white p-4" data-testid="wa-bulk-schedules-block">
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
                  <th className="text-left px-3 py-2 hidden md:table-cell">Template</th>
                  <th className="text-center px-3 py-2 hidden sm:table-cell">Dest.</th>
                  <th className="text-left px-3 py-2">Statut</th>
                  <th className="text-right px-3 py-2">Action</th>
                </tr>
              </thead>
              <tbody>
                {schedules.map((sc) => {
                  const sb = STATUS_BADGE[sc.status] || STATUS_BADGE.pending;
                  const Icon = sb.icon;
                  return (
                    <tr key={sc.id} className="border-t border-slate-100 hover:bg-slate-50" data-testid={`wa-bulk-sched-${sc.id}`}>
                      <td className="px-3 py-2 whitespace-nowrap text-xs">
                        <div>{fmtDate(sc.scheduled_at)}</div>
                        <div className="md:hidden text-[10px] text-slate-500 mt-0.5 max-w-[160px] truncate" title={sc.template_name}>
                          {sc.template_name}
                        </div>
                        <div className="sm:hidden text-[10px] text-slate-400 mt-0.5">
                          {(sc.recipients || []).length} dest.
                        </div>
                      </td>
                      <td className="px-3 py-2 hidden md:table-cell text-xs text-slate-700 font-mono">
                        {sc.template_name} <span className="text-slate-400">({sc.language_code || "fr"})</span>
                        {sc.title && <div className="text-[10px] text-slate-500">{sc.title}</div>}
                      </td>
                      <td className="px-3 py-2 hidden sm:table-cell text-center font-mono text-xs">
                        {(sc.recipients || []).length}
                        {sc.result_summary?.sent_ok != null && (
                          <span className="text-[10px] text-emerald-700 block">✓ {sc.result_summary.sent_ok}</span>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <span className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded ring-1 ${sb.cls}`}>
                          <Icon className={`h-3 w-3 ${sc.status === "running" ? "animate-spin" : ""}`} />
                          <span className="hidden sm:inline">{sb.label}</span>
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right">
                        {sc.status === "pending" && (
                          <button
                            onClick={() => cancelSchedule(sc.id)}
                            className="text-xs text-rose-600 hover:underline inline-flex items-center gap-1"
                            data-testid={`wa-bulk-sched-cancel-${sc.id}`}
                          >
                            <Trash2 className="h-3 w-3" />
                            <span className="hidden sm:inline">Annuler</span>
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
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={(e) => e.target === e.currentTarget && setPreviewOpen(false)}
          data-testid="wa-bulk-preview-modal"
        >
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[88vh] overflow-y-auto">
            <div className="flex items-center justify-between px-5 py-3 border-b">
              <h3 className="font-display font-bold inline-flex items-center gap-2">
                <Eye className="h-4 w-4" /> Aperçu personnalisé (3 premiers destinataires)
              </h3>
              <button onClick={() => setPreviewOpen(false)} className="text-slate-500"><X className="h-4 w-4" /></button>
            </div>
            <div className="p-5 space-y-3">
              {previews.length === 0 && (
                <p className="text-sm text-slate-400 text-center py-4">Sélectionnez des destinataires et un template pour voir l'aperçu.</p>
              )}
              {previews.map((p, i) => (
                <div key={i} className="rounded-lg ring-1 ring-emerald-200 p-3 bg-emerald-50" data-testid={`wa-bulk-preview-${i}`}>
                  <p className="text-[11px] uppercase tracking-wider text-emerald-700 mb-1">
                    Pour : <strong>{p.contact.name}</strong>
                    <code className="bg-white ring-1 ring-slate-200 px-1 ml-1">{p.contact.whatsapp || p.contact.phone}</code>
                  </p>
                  {p.headerText && <p className="text-sm text-slate-900 font-bold whitespace-pre-wrap">{p.headerText}</p>}
                  <p className="text-sm text-slate-800 whitespace-pre-wrap mt-1">{p.bodyText}</p>
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
