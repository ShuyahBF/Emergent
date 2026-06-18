import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { parseTemplate, buildButtonSpecs } from "@/lib/waTemplate";
import { toast } from "sonner";
import {
  MessageCircle, Send, Users, UserCheck, Filter, Search, RefreshCw, CheckCircle2, XCircle, ClockIcon, AlertTriangle, Phone, Settings, CalendarClock, Trash2, Loader2, Wand2, Eye,
  Image as ImageIcon, FileText as FileTextIcon, Video, Upload, X,
} from "lucide-react";
import { Link } from "react-router-dom";

/*
  Admin → Messagerie WhatsApp
  Sélection multi : clients + utilisateurs suivis → template Meta approuvé → envoi groupé immédiat ou planifié,
  avec variables dynamiques personnalisées par destinataire ({{full_name}}, {{company}}, {{today}}…).
*/
export default function AdminMessaging() {
  const [audience, setAudience] = useState({ clients: [], tracked_users: [] });
  const [templates, setTemplates] = useState({ configured: false, items: [], error: null });
  const [history, setHistory] = useState([]);
  const [schedules, setSchedules] = useState([]);
  const [tokens, setTokens] = useState([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [scheduling, setScheduling] = useState(false);

  const [tab, setTab] = useState("clients");
  const [query, setQuery] = useState("");
  // Iter38r-fix9v — Sort contacts: alpha / created_at / last_message_at
  // S-iter39d (fix #5) — Tri par défaut : dernier contact WA/SMS desc, pour
  // que les contacts récemment touchés ou importés remontent en haut.
  const [contactsSort, setContactsSort] = useState("last_message_desc");
  const [selected, setSelected] = useState({}); // `${kind}:${id}` → true
  const [template, setTemplate] = useState("");
  const [language, setLanguage] = useState("fr");
  const [variables, setVariables] = useState([]); // positional body variables
  const [headerText, setHeaderText] = useState("");
  const [headerMedia, setHeaderMedia] = useState(null); // { link, kind, filename }
  const [headerUploading, setHeaderUploading] = useState(false);
  const [buttonVars, setButtonVars] = useState([]); // [[urlVar1,...], ...] indexed by button position
  const [showLibrary, setShowLibrary] = useState(false);
  const [library, setLibrary] = useState([]);
  const [showPreview, setShowPreview] = useState(false);
  const [schedDate, setSchedDate] = useState("");
  const [schedTime, setSchedTime] = useState("");
  const [schedTitle, setSchedTitle] = useState("");

  const loadAll = async () => {
    setLoading(true);
    try {
      const [aud, tpl, hist, sch, tok] = await Promise.all([
        apiClient.get("/admin/messaging/audience"),
        apiClient.get("/admin/whatsapp/templates"),
        apiClient.get("/admin/messaging/history", { params: { limit: 200 } }),
        apiClient.get("/admin/messaging/schedules"),
        apiClient.get("/admin/messaging/variable-tokens"),
      ]);
      setAudience(aud.data || { clients: [], tracked_users: [] });
      setTemplates(tpl.data || { configured: false, items: [] });
      setHistory(hist.data || []);
      setSchedules(sch.data || []);
      setTokens(tok.data?.tokens || []);
      // Preselect first approved template
      const first = (tpl.data?.items || []).find((t) => (t.status || "").toUpperCase() === "APPROVED");
      if (first && !template) {
        setTemplate(first.name);
        setLanguage((first.language || "fr").split("_")[0]);
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { loadAll(); /* eslint-disable-next-line */ }, []);

  // Auto-refresh schedules every 30s so admins see pending→running→done transitions
  // without clicking "Rafraîchir" manually (cron ticks every minute).
  useEffect(() => {
    const t = setInterval(async () => {
      try {
        const [sch, hist] = await Promise.all([
          apiClient.get("/admin/messaging/schedules"),
          apiClient.get("/admin/messaging/history", { params: { limit: 200 } }),
        ]);
        setSchedules(sch.data || []);
        setHistory(hist.data || []);
      } catch { /* noop */ }
    }, 30000);
    return () => clearInterval(t);
  }, []);

  const rows = tab === "clients" ? audience.clients : audience.tracked_users;
  const filtered = rows.filter((r) => {
    if (!query) return true;
    const q = query.toLowerCase();
    return (
      (r.full_name || "").toLowerCase().includes(q) ||
      (r.email || "").toLowerCase().includes(q) ||
      (r.phone || "").toLowerCase().includes(q) ||
      (r.company || "").toLowerCase().includes(q) ||
      (r.client_label || "").toLowerCase().includes(q)
    );
  });
  // Iter38r-fix9v — Apply contact sort (alpha / created_at / last_message_at)
  const sortedFiltered = useMemo(() => {
    const arr = [...filtered];
    if (contactsSort === "alpha") {
      arr.sort((a, b) => (a.full_name || a.email || "").localeCompare(b.full_name || b.email || "", "fr", { sensitivity: "base" }));
    } else if (contactsSort === "created_desc") {
      arr.sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
    } else if (contactsSort === "created_asc") {
      arr.sort((a, b) => String(a.created_at || "").localeCompare(String(b.created_at || "")));
    } else if (contactsSort === "last_message_desc") {
      arr.sort((a, b) => String(b.last_message_at || b.last_interaction_at || "").localeCompare(String(a.last_message_at || a.last_interaction_at || "")));
    }
    return arr;
  }, [filtered, contactsSort]);

  const toggle = (kind, id) => {
    const key = `${kind}:${id}`;
    setSelected((s) => ({ ...s, [key]: !s[key] }));
  };

  const toggleAllVisible = () => {
    const withPhone = sortedFiltered.filter((r) => r.has_phone);
    const allOn = withPhone.every((r) => selected[`${r.kind}:${r.id}`]);
    const patch = {};
    withPhone.forEach((r) => { patch[`${r.kind}:${r.id}`] = !allOn; });
    setSelected((s) => ({ ...s, ...patch }));
  };

  const selectedList = useMemo(() => {
    const out = [];
    Object.entries(selected).forEach(([key, v]) => {
      if (!v) return;
      const [kind, id] = key.split(":");
      const row = [...audience.clients, ...audience.tracked_users].find(
        (r) => r.kind === kind && r.id === id
      );
      if (row && row.has_phone) out.push(row);
    });
    return out;
  }, [selected, audience]);

  const approved = (templates.items || []).filter((t) => (t.status || "").toUpperCase() === "APPROVED");

  // Find the approved template details (components with body / placeholders) to render variable inputs
  const selectedTemplate = useMemo(
    () => approved.find((t) => t.name === template) || null,
    [approved, template]
  );

  const parsed = useMemo(() => parseTemplate(selectedTemplate), [selectedTemplate]);

  // Parse the template's body component for {{N}} placeholders. Number = count of unique numeric tokens.
  const { bodyText, varCount } = useMemo(() => {
    return { bodyText: parsed.body.text, varCount: parsed.body.varCount };
  }, [parsed]);

  // Reset header/button state on template change
  useEffect(() => {
    setHeaderText("");
    setHeaderMedia(null);
    setButtonVars((parsed.buttons || []).map((b) => Array(b.urlVarCount || 0).fill("")));
  }, [parsed]);

  // Sync variables array length to varCount when template changes
  useEffect(() => {
    setVariables((prev) => {
      const next = [...prev];
      if (next.length < varCount) {
        while (next.length < varCount) next.push("");
      } else if (next.length > varCount) {
        next.length = varCount;
      }
      return next;
    });
  }, [varCount]);

  const updateVar = (i, val) => {
    setVariables((prev) => {
      const n = [...prev];
      n[i] = val;
      return n;
    });
  };

  const insertToken = (i, token) => {
    setVariables((prev) => {
      const n = [...prev];
      n[i] = (n[i] || "") + token;
      return n;
    });
  };

  // Header media upload — saves into shared client media library so URL is reusable
  const uploadHeader = async (file, existingMedia = null) => {
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
      const r = await apiClient.post("/me/media-library", fd, { headers: { "Content-Type": "multipart/form-data" } });
      const link = r.data?.public_url;
      if (!link) throw new Error("URL publique manquante");
      setHeaderMedia({ link, kind: r.data?.kind || "document", filename: r.data?.filename || file.name });
      toast.success("Fichier ajouté à la bibliothèque");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec de l'upload");
    } finally {
      setHeaderUploading(false);
    }
  };

  // Lazy-load the library when the picker opens
  useEffect(() => {
    if (!showLibrary) return;
    apiClient.get("/me/media-library").then((r) => setLibrary(r.data || [])).catch(() => {});
  }, [showLibrary]);

  const updateButtonVar = (bi, vi, val) => setButtonVars((prev) => {
    const n = prev.map((x) => [...(x || [])]);
    if (!n[bi]) n[bi] = [];
    n[bi][vi] = val;
    return n;
  });

  // Live preview using the first selected recipient (or "—" placeholder context)
  const previewBody = useMemo(() => {
    if (!bodyText) return "";
    let text = bodyText;
    const ctx = (() => {
      const r = selectedList[0];
      const today = new Date();
      const tomorrow = new Date(today.getTime() + 86400000);
      const fmt = (d) => d.toLocaleDateString("fr-FR");
      if (!r) {
        return { full_name: "[Nom]", company: "[Société]", phone: "[Tél]", email: "[Email]", client_code: "[Code]", today: fmt(today), tomorrow: fmt(tomorrow) };
      }
      return {
        full_name: r.full_name || "",
        company: r.company || r.client_label || "",
        phone: r.phone || "",
        email: r.email || "",
        client_code: r.client_code || "",
        today: fmt(today),
        tomorrow: fmt(tomorrow),
      };
    })();
    // Substitute the user-supplied recipes first into Meta {{N}} placeholders
    variables.forEach((v, i) => {
      const rendered = (v || "").replace(/\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}/g, (_, k) => ctx[k.toLowerCase()] ?? "");
      text = text.replace(new RegExp(`\\{\\{\\s*${i + 1}\\s*\\}\\}`, "g"), rendered);
    });
    return text;
  }, [bodyText, variables, selectedList]);

  const send = async () => {
    if (selectedList.length === 0) {
      toast.error("Sélectionnez au moins un destinataire");
      return;
    }
    if (!template) {
      toast.error("Choisissez un template Meta approuvé");
      return;
    }
    // Pre-flight validation: catch the most common Meta rejection ("paramètres
    // invalides") before hitting the API. We check variable count + button URL
    // params + media-header presence consistency with the parsed template.
    if (varCount > 0) {
      const missing = variables.findIndex((v, i) => i < varCount && !(v || "").trim());
      if (missing !== -1) {
        toast.error(`Variable {{${missing + 1}}} manquante — remplissez tous les champs avant l'envoi.`);
        return;
      }
    }
    if (parsed.header?.format === "TEXT" && parsed.header.varCount > 0 && !(headerText || "").trim()) {
      toast.error("Le template attend un texte pour l'en-tête.");
      return;
    }
    if (parsed.header?.format && parsed.header.format !== "TEXT" && !headerMedia?.link) {
      toast.error(`Le template attend un fichier ${parsed.header.format.toLowerCase()} pour l'en-tête.`);
      return;
    }
    for (let bi = 0; bi < (parsed.buttons || []).length; bi++) {
      const b = parsed.buttons[bi];
      if ((b.urlVarCount || 0) > 0) {
        const bv = (buttonVars && buttonVars[bi]) || [];
        for (let pi = 0; pi < b.urlVarCount; pi++) {
          if (!(bv[pi] || "").trim()) {
            toast.error(`Variable d'URL du bouton ${bi + 1} manquante.`);
            return;
          }
        }
      }
    }
    if (!window.confirm(`Envoyer le template "${template}" à ${selectedList.length} destinataire(s) ?`)) return;
    setSending(true);
    try {
      const r = await apiClient.post("/admin/messaging/bulk-send", {
        recipients: selectedList.map((x) => ({ kind: x.kind, id: x.id, phone: x.phone, label: x.full_name })),
        template_name: template,
        language_code: language || "fr",
        variables: variables.length > 0 ? variables : undefined,
        header_text: headerText || undefined,
        header_media: headerMedia || undefined,
        // Iter43-fix24aj — Use button_specs (knows real sub_type) instead of button_vars.
        button_specs: parsed ? buildButtonSpecs(parsed, buttonVars) : null,
      });
      const { sent_ok = 0, sent_ko = 0, skipped = [], error_summary = [] } = r.data || {};
      if (sent_ok > 0 && sent_ko === 0) {
        toast.success(`${sent_ok} message(s) envoyé(s)`);
      } else if (sent_ok > 0) {
        toast.success(`${sent_ok} envoyé(s), ${sent_ko} en erreur`);
      } else {
        const tail = error_summary.length > 0 ? `\nDétail Meta : ${error_summary[0]}` : "";
        // Use a longer-lasting toast for failures so the user can read the full Meta error
        toast.error(`Aucun envoi — ${sent_ko} erreur(s).${tail}`, { duration: 12000 });
      }
      if (skipped.length > 0) {
        toast.message(`${skipped.length} destinataire(s) ignoré(s) (pas de numéro).`);
      }
      setSelected({});
      await loadAll();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur d'envoi");
    } finally {
      setSending(false);
    }
  };

  const schedule = async () => {
    if (selectedList.length === 0) {
      toast.error("Sélectionnez au moins un destinataire");
      return;
    }
    if (!template) {
      toast.error("Choisissez un template Meta approuvé");
      return;
    }
    if (!schedDate || !schedTime) {
      toast.error("Choisissez une date et une heure");
      return;
    }
    // Local datetime → UTC ISO
    const local = new Date(`${schedDate}T${schedTime}`);
    if (isNaN(local.getTime())) {
      toast.error("Date/heure invalide");
      return;
    }
    if (local.getTime() <= Date.now()) {
      toast.error("La date planifiée doit être dans le futur");
      return;
    }
    setScheduling(true);
    try {
      await apiClient.post("/admin/messaging/schedules", {
        title: schedTitle || `Envoi ${template}`,
        recipients: selectedList.map((x) => ({ kind: x.kind, id: x.id, phone: x.phone, label: x.full_name })),
        template_name: template,
        language_code: language || "fr",
        variables: variables.length > 0 ? variables : undefined,
        header_text: headerText || undefined,
        header_media: headerMedia || undefined,
        // Iter43-fix24aj — Use button_specs instead of button_vars.
        button_specs: parsed ? buildButtonSpecs(parsed, buttonVars) : null,
        scheduled_at: local.toISOString(),
      });
      toast.success(`Planifié pour ${local.toLocaleString("fr-FR")}`);
      setSelected({});
      setSchedDate("");
      setSchedTime("");
      setSchedTitle("");
      await loadAll();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de planification");
    } finally {
      setScheduling(false);
    }
  };

  const cancelSchedule = async (sid) => {
    if (!window.confirm("Annuler / supprimer cette planification ?")) return;
    try {
      await apiClient.delete(`/admin/messaging/schedules/${sid}`);
      toast.success("Planification supprimée");
      await loadAll();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  return (
    <div className="max-w-7xl space-y-6" data-testid="admin-messaging-page">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Messagerie</p>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2">
            <MessageCircle className="h-5 w-5 text-sawali-blue" /> Messagerie WhatsApp
          </h1>
          <p className="text-sm text-slate-500">
            Envoi groupé de templates Meta approuvés aux clients et utilisateurs suivis.
          </p>
        </div>
        <div className="flex gap-2">
          <Link
            to="/admin/settings"
            className="inline-flex items-center gap-1 text-xs rounded-lg border border-slate-300 px-3 py-1.5 hover:bg-slate-50"
            data-testid="messaging-to-settings"
          >
            <Settings className="h-3.5 w-3.5" /> Paramètres WhatsApp
          </Link>
          <button
            onClick={loadAll}
            className="inline-flex items-center gap-1 text-xs rounded-lg border border-slate-300 px-3 py-1.5 hover:bg-slate-50"
            data-testid="messaging-refresh"
          >
            <RefreshCw className="h-3.5 w-3.5" /> Rafraîchir
          </button>
        </div>
      </div>

      {/* Config / template picker */}
      <div
        className={`rounded-xl border p-4 ${templates.configured ? "border-slate-200 bg-white" : "border-amber-300 bg-amber-50"}`}
        data-testid="messaging-config-card"
      >
        {!templates.configured && (
          <div className="flex items-start gap-3 mb-3">
            <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
            <div className="text-sm text-amber-900">
              <strong>WhatsApp Business API non configurée.</strong> Renseignez les identifiants Meta
              dans <Link to="/admin/settings" className="underline font-semibold">Paramètres → WhatsApp Business API</Link>
              &nbsp;(WABA ID, Phone Number ID, App ID, Token). Ensuite, créez et faites approuver vos templates dans Meta Business Suite.
            </div>
          </div>
        )}
        <div className="grid md:grid-cols-3 gap-3 items-end">
          <div>
            <label className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">
              Template Meta ({approved.length} approuvé{approved.length > 1 ? "s" : ""})
            </label>
            <select
              value={template}
              onChange={(e) => {
                setTemplate(e.target.value);
                const t = approved.find((x) => x.name === e.target.value);
                if (t?.language) setLanguage((t.language || "fr").split("_")[0]);
              }}
              disabled={!templates.configured}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm disabled:bg-slate-100 disabled:text-slate-400"
              data-testid="messaging-template-select"
            >
              <option value="">— Sélectionner un template approuvé —</option>
              {approved.map((t) => (
                <option key={t.name} value={t.name}>
                  {t.name} · {t.language || "fr"} · {t.category || "UTILITY"}
                </option>
              ))}
            </select>
            {templates.configured && approved.length === 0 && (
              <p className="text-[11px] text-amber-700 mt-1">
                Aucun template approuvé trouvé côté Meta. Créez-en un dans Meta Business Suite.
              </p>
            )}
          </div>
          <div>
            <label className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Langue</label>
            <input
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              disabled={!templates.configured}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm disabled:bg-slate-100 disabled:text-slate-400"
              placeholder="fr, en, ar…"
              data-testid="messaging-language"
            />
          </div>
          <button
            onClick={send}
            disabled={sending || selectedList.length === 0 || !template || !templates.configured}
            title={!templates.configured ? "Configurez WhatsApp d'abord (Paramètres)" : ""}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-600 text-white px-4 py-2 text-sm hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed"
            data-testid="messaging-send-btn"
          >
            <Send className="h-4 w-4" />
            {sending ? "Envoi…" : `Envoyer à ${selectedList.length}`}
          </button>
        </div>

        {/* Variables dynamiques */}
        {selectedTemplate && (
          <div className="mt-4 pt-4 border-t border-slate-200" data-testid="messaging-variables-section">
            <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
              <div className="flex items-center gap-2">
                <Wand2 className="h-4 w-4 text-amber-600" />
                <h3 className="text-sm font-display font-semibold text-slate-800">
                  Configuration du template
                  {varCount > 0 || parsed.header || (parsed.buttons || []).some((b) => b.urlVarCount) ? (
                    <span className="ml-2 text-[11px] text-slate-500">
                      ({[varCount > 0 ? `${varCount} variable${varCount > 1 ? "s" : ""}` : null,
                          parsed.header ? `en-tête ${parsed.header.format.toLowerCase()}` : null,
                          (parsed.buttons || []).some((b) => b.urlVarCount) ? "boutons d'actions rapides" : null,
                        ].filter(Boolean).join(" + ")})
                    </span>
                  ) : (
                    <span className="ml-2 text-[11px] text-slate-500">(aucun paramètre dynamique)</span>
                  )}
                </h3>
              </div>
              {selectedList.length > 0 && (
                <button
                  type="button"
                  onClick={() => setShowPreview((s) => !s)}
                  className="inline-flex items-center gap-1 text-[11px] rounded border border-slate-300 px-2 py-1 hover:bg-slate-50"
                  data-testid="messaging-preview-toggle"
                >
                  <Eye className="h-3 w-3" /> {showPreview ? "Masquer aperçu" : "Aperçu"}
                </button>
              )}
            </div>

            {bodyText && (
              <div className="text-[11px] text-slate-500 italic mb-3 rounded bg-slate-50 border border-slate-200 px-3 py-2 whitespace-pre-line">
                <strong className="not-italic text-slate-600">Corps du template Meta :</strong>
                <br />{bodyText}
              </div>
            )}

            {/* HEADER block (text variable OR media upload) — same value applied to every recipient */}
            {parsed.header && (
              <div className="mb-3 rounded-lg ring-1 ring-slate-200 bg-white p-3 space-y-2">
                {parsed.header.format === "TEXT" && parsed.header.varCount > 0 && (
                  <>
                    <p className="text-xs font-semibold text-slate-700">En-tête (texte)</p>
                    <p className="text-[11px] text-slate-500 whitespace-pre-wrap bg-slate-50 rounded px-2 py-1">{parsed.header.text}</p>
                    <div className="flex gap-2">
                      <input
                        value={headerText}
                        onChange={(e) => setHeaderText(e.target.value)}
                        placeholder="Valeur de la variable d'en-tête (statique ou tokens)"
                        className="flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-mono"
                        data-testid="messaging-header-text-input"
                      />
                      <select
                        onChange={(e) => {
                          const tk = e.target.value;
                          if (tk) { setHeaderText((p) => (p || "") + tk); e.target.value = ""; }
                        }}
                        className="rounded-lg border border-slate-300 bg-white px-2 py-2 text-[11px]"
                        defaultValue=""
                        data-testid="messaging-header-text-token-picker"
                      >
                        <option value="">+ Token…</option>
                        {tokens.map((t) => <option key={t.token} value={t.token}>{t.label}</option>)}
                      </select>
                    </div>
                  </>
                )}
                {["IMAGE", "DOCUMENT", "VIDEO"].includes(parsed.header.format) && (
                  <>
                    <p className="text-xs font-semibold text-slate-700 inline-flex items-center gap-1.5">
                      {parsed.header.format === "IMAGE" ? <ImageIcon className="h-3.5 w-3.5" /> : parsed.header.format === "VIDEO" ? <Video className="h-3.5 w-3.5" /> : <FileTextIcon className="h-3.5 w-3.5" />}
                      En-tête ({parsed.header.format === "IMAGE" ? "image" : parsed.header.format === "VIDEO" ? "vidéo" : "document PDF"}) — appliqué à tous les destinataires
                    </p>
                    {headerMedia?.link ? (
                      <div className="flex items-center gap-2">
                        {parsed.header.format === "IMAGE" && <img src={headerMedia.link} alt="" className="h-16 w-16 object-cover rounded" />}
                        <div className="flex-1 text-xs">
                          <p className="font-mono break-all text-slate-600">{headerMedia.filename}</p>
                          <a href={headerMedia.link} target="_blank" rel="noreferrer" className="text-[11px] text-sawali-blue hover:underline">Ouvrir</a>
                        </div>
                        <button onClick={() => setHeaderMedia(null)} className="text-xs text-rose-600 hover:underline" data-testid="messaging-header-media-clear">Changer</button>
                      </div>
                    ) : (
                      <div className="flex flex-wrap gap-2">
                        <label className="inline-flex items-center gap-2 text-xs cursor-pointer rounded bg-slate-100 hover:bg-slate-200 px-3 py-2">
                          <Upload className="h-3.5 w-3.5" /> {headerUploading ? "Upload…" : "Uploader nouveau"}
                          <input
                            type="file"
                            accept={parsed.header.format === "IMAGE" ? "image/*" : parsed.header.format === "VIDEO" ? "video/*" : ".pdf,application/pdf"}
                            onChange={(e) => uploadHeader(e.target.files?.[0])}
                            className="hidden"
                            data-testid="messaging-header-media-input"
                          />
                        </label>
                        <button
                          type="button"
                          onClick={() => setShowLibrary((v) => !v)}
                          className="inline-flex items-center gap-2 text-xs rounded ring-1 ring-slate-300 bg-white hover:bg-slate-50 px-3 py-2"
                          data-testid="messaging-header-library-toggle"
                        >
                          <ImageIcon className="h-3.5 w-3.5" /> {showLibrary ? "Masquer" : "Choisir dans la bibliothèque"}
                        </button>
                      </div>
                    )}
                    {!headerMedia?.link && showLibrary && (
                      <div className="rounded ring-1 ring-slate-200 bg-slate-50 p-2 max-h-56 overflow-y-auto">
                        {(library || []).filter((m) => {
                          const k = parsed.header.format === "IMAGE" ? "image" : parsed.header.format === "VIDEO" ? "video" : "document";
                          return m.kind === k;
                        }).length === 0 ? (
                          <p className="text-[11px] text-slate-500 italic">Aucun média dans la bibliothèque pour ce format.</p>
                        ) : (
                          <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
                            {(library || []).filter((m) => {
                              const k = parsed.header.format === "IMAGE" ? "image" : parsed.header.format === "VIDEO" ? "video" : "document";
                              return m.kind === k;
                            }).map((m) => (
                              <button
                                key={m.id}
                                type="button"
                                onClick={() => uploadHeader(null, m)}
                                className="rounded border border-slate-200 bg-white hover:border-sawali-blue p-1.5 text-left"
                                data-testid={`messaging-header-pick-${m.id}`}
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
                        )}
                      </div>
                    )}
                  </>
                )}
              </div>
            )}

            {varCount > 0 ? (
              <div className="space-y-3">
                {Array.from({ length: varCount }).map((_, i) => (
                  <div key={i} className="grid md:grid-cols-[120px_1fr_auto] gap-2 items-center" data-testid={`messaging-variable-row-${i + 1}`}>
                    <label className="text-[11px] uppercase tracking-wider text-slate-500 font-mono">
                      {`{{${i + 1}}}`}
                    </label>
                    <input
                      value={variables[i] || ""}
                      onChange={(e) => updateVar(i, e.target.value)}
                      placeholder="Texte statique ou tokens (ex: Bonjour {{full_name}})"
                      className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-mono"
                      data-testid={`messaging-variable-input-${i + 1}`}
                    />
                    <select
                      onChange={(e) => {
                        const tk = e.target.value;
                        if (tk) {
                          insertToken(i, tk);
                          e.target.value = "";
                        }
                      }}
                      className="rounded-lg border border-slate-300 bg-white px-2 py-2 text-[11px]"
                      data-testid={`messaging-variable-token-picker-${i + 1}`}
                      defaultValue=""
                    >
                      <option value="">+ Insérer…</option>
                      {tokens.map((t) => (
                        <option key={t.token} value={t.token} title={t.example}>
                          {t.label} {t.token}
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-[11px] text-slate-400 italic">
                Ce template Meta n'a pas de variables (placeholders <code className="font-mono">{"{{1}}"}</code>, <code className="font-mono">{"{{2}}"}</code>…).
              </p>
            )}

            {/* BUTTONS with dynamic URL parameters */}
            {(parsed.buttons || []).some((b) => b.type === "URL" && b.urlVarCount > 0) && (
              <div className="mt-3 space-y-3">
                <p className="text-xs font-semibold text-slate-700">Boutons d'action rapide (URL dynamique)</p>
                {parsed.buttons.map((btn, bi) => (
                  btn.type === "URL" && btn.urlVarCount > 0 ? (
                    <div key={bi} className="rounded-lg ring-1 ring-slate-200 bg-white p-3 space-y-2" data-testid={`messaging-button-row-${bi}`}>
                      <p className="text-[11px] text-slate-500">
                        Bouton : <strong className="text-slate-800">{btn.text}</strong>
                        <code className="ml-2 bg-slate-100 px-1 rounded text-[10px]">{btn.url}</code>
                      </p>
                      {Array.from({ length: btn.urlVarCount }).map((_, vi) => (
                        <div key={vi} className="grid md:grid-cols-[120px_1fr_auto] gap-2 items-center">
                          <label className="text-[11px] uppercase tracking-wider text-slate-500 font-mono">{`{{${vi + 1}}}`}</label>
                          <input
                            value={(buttonVars[bi] || [])[vi] || ""}
                            onChange={(e) => updateButtonVar(bi, vi, e.target.value)}
                            placeholder="Statique ou tokens"
                            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-mono"
                            data-testid={`messaging-button-input-${bi}-${vi + 1}`}
                          />
                          <select
                            onChange={(e) => {
                              const tk = e.target.value;
                              if (tk) {
                                updateButtonVar(bi, vi, ((buttonVars[bi] || [])[vi] || "") + tk);
                                e.target.value = "";
                              }
                            }}
                            className="rounded-lg border border-slate-300 bg-white px-2 py-2 text-[11px]"
                            defaultValue=""
                          >
                            <option value="">+ Token…</option>
                            {tokens.map((t) => <option key={t.token} value={t.token}>{t.label}</option>)}
                          </select>
                        </div>
                      ))}
                    </div>
                  ) : null
                ))}
              </div>
            )}

            {showPreview && previewBody && selectedList.length > 0 && (
              <div className="mt-3 rounded border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-900" data-testid="messaging-preview">
                <p className="text-[10px] uppercase tracking-wider text-emerald-700 mb-1">
                  Aperçu pour <strong>{selectedList[0].full_name || selectedList[0].phone}</strong>
                </p>
                <p className="whitespace-pre-line">{previewBody}</p>
              </div>
            )}
          </div>
        )}

        {/* Planification */}
        <div className="mt-4 pt-4 border-t border-slate-200">
          <div className="flex items-center gap-2 mb-2">
            <CalendarClock className="h-4 w-4 text-indigo-600" />
            <h3 className="text-sm font-display font-semibold text-slate-800">Planifier un envoi</h3>
            <span className="text-[11px] text-slate-400">
              (exécution automatique toutes les minutes)
            </span>
          </div>
          <div className="grid md:grid-cols-5 gap-3 items-end">
            <div className="md:col-span-2">
              <label className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Titre (optionnel)</label>
              <input
                value={schedTitle}
                onChange={(e) => setSchedTitle(e.target.value)}
                placeholder="Rappel RDV hebdo"
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                data-testid="messaging-sched-title"
              />
            </div>
            <div>
              <label className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Date</label>
              <input
                type="date"
                value={schedDate}
                onChange={(e) => setSchedDate(e.target.value)}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                data-testid="messaging-sched-date"
              />
            </div>
            <div>
              <label className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Heure</label>
              <input
                type="time"
                value={schedTime}
                onChange={(e) => setSchedTime(e.target.value)}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                data-testid="messaging-sched-time"
              />
            </div>
            <button
              onClick={schedule}
              disabled={scheduling || selectedList.length === 0 || !template || !templates.configured || !schedDate || !schedTime}
              title={!templates.configured ? "Configurez WhatsApp d'abord (Paramètres)" : ""}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 text-white px-4 py-2 text-sm hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
              data-testid="messaging-schedule-btn"
            >
              <CalendarClock className="h-4 w-4" />
              {scheduling ? "…" : "Planifier"}
            </button>
          </div>
        </div>
      </div>

      {/* Audience */}
      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
        <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-slate-200 flex-wrap">
          <div className="flex gap-1">
            <TabBtn active={tab === "clients"} onClick={() => setTab("clients")} testid="tab-clients">
              <Users className="h-3.5 w-3.5" /> Clients ({audience.clients.length})
            </TabBtn>
            <TabBtn active={tab === "tracked"} onClick={() => setTab("tracked")} testid="tab-tracked">
              <UserCheck className="h-3.5 w-3.5" /> Utilisateurs suivis ({audience.tracked_users.length})
            </TabBtn>
          </div>
          <div className="relative flex-1 max-w-xs">
            <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Rechercher nom, email, téléphone…"
              className="w-full pl-8 pr-3 py-1.5 text-sm rounded-lg border border-slate-300 bg-white"
              data-testid="messaging-search"
            />
          </div>
          {/* Iter38r-fix9v — Sort contacts (alpha / created / last message) */}
          <select
            value={contactsSort}
            onChange={(e) => setContactsSort(e.target.value)}
            className="text-xs rounded-lg border border-slate-300 bg-white px-2 py-1.5"
            data-testid="messaging-sort-select"
            title="Trier la liste"
          >
            <option value="last_message_desc">Dernier contact récent (par défaut)</option>
            <option value="default">Tri par défaut (ordre serveur)</option>
            <option value="alpha">Alphabétique (A-Z)</option>
            <option value="created_desc">Création récente d'abord</option>
            <option value="created_asc">Création ancienne d'abord</option>
          </select>
          <button
            onClick={toggleAllVisible}
            className="text-xs rounded-md border border-slate-300 px-2 py-1 hover:bg-slate-50"
            data-testid="messaging-toggle-all"
          >
            <Filter className="h-3 w-3 inline mr-1" /> Tout sélectionner (avec tél.)
          </button>
        </div>

        {loading ? (
          <div className="text-center text-slate-500 py-10">Chargement…</div>
        ) : sortedFiltered.length === 0 ? (
          <div className="text-center text-slate-400 py-10 italic text-sm">Aucun destinataire.</div>
        ) : (
          <div className="max-h-[480px] overflow-y-auto">
            <table className="min-w-full text-sm">
              <thead className="sticky top-0 bg-slate-50 text-[11px] uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="text-left py-2 px-3 w-8"></th>
                  <th className="text-left py-2 px-3">{tab === "clients" ? "Client" : "Utilisateur"}</th>
                  <th className="text-left py-2 px-3">{tab === "clients" ? "Société" : "Rattaché à"}</th>
                  <th className="text-left py-2 px-3">Email</th>
                  <th className="text-left py-2 px-3">WhatsApp</th>
                  <th className="text-left py-2 px-3">Statut</th>
                </tr>
              </thead>
              <tbody>
                {sortedFiltered.map((r) => {
                  const key = `${r.kind}:${r.id}`;
                  const on = !!selected[key];
                  return (
                    <tr
                      key={key}
                      className={`border-t border-slate-100 ${on ? "bg-sawali-blue/5" : "hover:bg-slate-50"}`}
                      data-testid={`messaging-row-${r.kind}-${r.id}`}
                    >
                      <td className="py-2 px-3">
                        <input
                          type="checkbox"
                          checked={on}
                          onChange={() => toggle(r.kind, r.id)}
                          disabled={!r.has_phone}
                          className="accent-sawali-blue disabled:opacity-30"
                          data-testid={`messaging-check-${r.kind}-${r.id}`}
                        />
                      </td>
                      <td className="py-2 px-3">
                        <div className="font-medium text-slate-900">{r.full_name}</div>
                        {r.client_code && <code className="text-[10px] font-mono bg-slate-100 px-1 py-0.5 rounded">{r.client_code}</code>}
                      </td>
                      <td className="py-2 px-3 text-slate-600">{r.company || r.client_label || "—"}</td>
                      <td className="py-2 px-3 text-slate-600">{r.email || "—"}</td>
                      <td className="py-2 px-3">
                        {r.phone ? (
                          <span className="inline-flex items-center gap-1 font-mono text-[11px]" title={r.whatsapp_number ? "N° WhatsApp dédié" : "N° téléphone (utilisé en fallback WhatsApp)"}>
                            {r.whatsapp_number ? (
                              <MessageCircle className="h-3 w-3 text-emerald-500" />
                            ) : (
                              <Phone className="h-3 w-3 text-slate-400" />
                            )}
                            {r.phone}
                          </span>
                        ) : (
                          <span className="text-[11px] text-rose-500" title="Renseignez le N° WhatsApp dans la fiche client">Pas de N° WhatsApp</span>
                        )}
                      </td>
                      <td className="py-2 px-3 text-[11px]">
                        {r.account_status && (
                          <span className={`px-2 py-0.5 rounded ${r.account_status === "active" ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>
                            {r.account_status}
                          </span>
                        )}
                        {r.role && (
                          <span className="px-2 py-0.5 rounded bg-slate-100 text-slate-600 ml-1">{r.role}</span>
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

      {/* Schedules */}
      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden" data-testid="messaging-schedules">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200">
          <h3 className="text-sm font-display font-bold flex items-center gap-2">
            <CalendarClock className="h-4 w-4 text-indigo-600" />
            Envois programmés ({schedules.length})
          </h3>
        </div>
        {schedules.length === 0 ? (
          <div className="text-center text-slate-400 py-8 italic text-sm">
            Aucun envoi programmé. Sélectionnez des destinataires puis utilisez "Planifier".
          </div>
        ) : (
          <div className="max-h-[360px] overflow-y-auto">
            <table className="min-w-full text-xs">
              <thead className="sticky top-0 bg-slate-50 text-[11px] uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="text-left py-2 px-3">Titre</th>
                  <th className="text-left py-2 px-3">Planifié pour</th>
                  <th className="text-left py-2 px-3">Template</th>
                  <th className="text-left py-2 px-3">Destinataires</th>
                  <th className="text-left py-2 px-3">Statut</th>
                  <th className="text-left py-2 px-3">Créé par</th>
                  <th className="text-right py-2 px-3"></th>
                </tr>
              </thead>
              <tbody>
                {schedules.map((s) => {
                  const rs = s.result_summary || {};
                  const statusPill = {
                    pending: ["bg-amber-100 text-amber-800", "En attente"],
                    running: ["bg-indigo-100 text-indigo-800", "En cours"],
                    done: ["bg-emerald-100 text-emerald-800", "Terminé"],
                    failed: ["bg-rose-100 text-rose-700", "Échec"],
                    cancelled: ["bg-slate-100 text-slate-600", "Annulé"],
                  }[s.status] || ["bg-slate-100 text-slate-600", s.status];
                  return (
                    <tr key={s.id} className="border-t border-slate-100" data-testid={`schedule-row-${s.id}`}>
                      <td className="py-1.5 px-3 text-slate-900">{s.title}</td>
                      <td className="py-1.5 px-3 text-slate-600">
                        {s.scheduled_at ? new Date(s.scheduled_at).toLocaleString("fr-FR") : "—"}
                      </td>
                      <td className="py-1.5 px-3 font-mono text-[11px]">{s.template_name}</td>
                      <td className="py-1.5 px-3">
                        {(s.recipients || []).length} destinataire(s)
                        {s.status === "done" && rs.sent_ok !== undefined && (
                          <div className="text-[10px] text-slate-500">
                            ✓ {rs.sent_ok} · ✗ {rs.sent_ko} · ⊘ {rs.skipped_count || 0}
                          </div>
                        )}
                      </td>
                      <td className="py-1.5 px-3">
                        <span className={`px-2 py-0.5 rounded text-[10px] ${statusPill[0]}`}>
                          {s.status === "running" && <Loader2 className="inline h-2.5 w-2.5 mr-1 animate-spin" />}
                          {statusPill[1]}
                        </span>
                      </td>
                      <td className="py-1.5 px-3 text-slate-500">{s.created_by_label || "—"}</td>
                      <td className="py-1.5 px-3 text-right">
                        {(s.status === "pending" || s.status === "running") && (
                          <button
                            onClick={() => cancelSchedule(s.id)}
                            className="inline-flex items-center gap-1 text-[11px] rounded bg-rose-500 text-white px-2 py-1 hover:bg-rose-600"
                            data-testid={`schedule-cancel-${s.id}`}
                            title="Annuler / supprimer"
                          >
                            <Trash2 className="h-3 w-3" />
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

      {/* History */}
      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-200">
          <h3 className="text-sm font-display font-bold">Historique des envois (200 derniers)</h3>
        </div>
        {history.length === 0 ? (
          <div className="text-center text-slate-400 py-10 italic text-sm">Aucun envoi enregistré.</div>
        ) : (
          <div className="max-h-[360px] overflow-y-auto">
            <table className="min-w-full text-xs" data-testid="messaging-history">
              <thead className="sticky top-0 bg-slate-50 text-[11px] uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="text-left py-2 px-3">Date</th>
                  <th className="text-left py-2 px-3">Destinataire</th>
                  <th className="text-left py-2 px-3">Template</th>
                  <th className="text-left py-2 px-3">Expéditeur</th>
                  <th className="text-left py-2 px-3">Statut</th>
                </tr>
              </thead>
              <tbody>
                {history.map((h) => (
                  <tr key={h.id} className="border-t border-slate-100" data-testid={`messaging-history-row-${h.id}`}>
                    <td className="py-1.5 px-3 text-slate-500">
                      {h.created_at ? new Date(h.created_at).toLocaleString("fr-FR") : "—"}
                    </td>
                    <td className="py-1.5 px-3">
                      <div className="text-slate-900">{h.recipient_label || h.to}</div>
                      <div className="text-[10px] font-mono text-slate-400">{h.to}</div>
                    </td>
                    <td className="py-1.5 px-3 font-mono text-[11px]">{h.template_name}</td>
                    <td className="py-1.5 px-3 text-slate-500">{h.sender_label || "—"}</td>
                    <td className="py-1.5 px-3">
                      {h.ok ? (
                        <span className="inline-flex items-center gap-1 text-emerald-700">
                          <CheckCircle2 className="h-3 w-3" /> OK
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-rose-600" title={h.error || ""}>
                          <XCircle className="h-3 w-3" /> {h.status || "KO"}
                        </span>
                      )}
                      {h.bulk && (
                        <span className="ml-2 inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-700 text-[10px]">
                          <ClockIcon className="h-2.5 w-2.5" /> groupé
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function TabBtn({ active, onClick, children, testid }) {
  return (
    <button
      onClick={onClick}
      data-testid={testid}
      className={`inline-flex items-center gap-1 text-xs px-3 py-1.5 rounded-md border transition ${
        active ? "bg-sawali-blue text-white border-sawali-blue" : "bg-white text-slate-700 border-slate-200 hover:bg-slate-50"
      }`}
    >
      {children}
    </button>
  );
}
