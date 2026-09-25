// =====================================================================
// Iter38r-fix9a — Liluvine PRO : Auto-réponse WhatsApp native
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { Sparkles, MessageCircle, Save, Copy, History, AlertCircle, UserPlus, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const TITLE = "Liluvine PRO — Auto-réponse WhatsApp (sans n8n)";

// Lot 24 — motifs de décision de l'auto-réponse, en clair (journal
// `liluvine_wa_autoreply_log` écrit par le webhook pour chaque message reçu).
// Le prompt système n'est JAMAIS la cause d'un silence : il ne règle que le
// contenu des réponses. Un silence vient toujours d'un de ces motifs.
const REASON_LABELS = {
  sent: ["Répondu", "text-emerald-700 bg-emerald-50 ring-emerald-200"],
  disabled: ["Auto-réponse désactivée", "text-rose-700 bg-rose-50 ring-rose-200"],
  cooldown: ["Anti-flood : le contact avait déjà reçu une réponse il y a moins de N secondes", "text-amber-800 bg-amber-50 ring-amber-200"],
  no_keyword_match: ["Aucun mot-clé déclencheur dans le message", "text-amber-800 bg-amber-50 ring-amber-200"],
  outside_business_hours: ["Hors des heures ouvrables (plage horaire configurée)", "text-amber-800 bg-amber-50 ring-amber-200"],
  inside_business_hours: ["Pendant les heures ouvrables (réglé sur « hors heures »)", "text-amber-800 bg-amber-50 ring-amber-200"],
  not_whitelisted: ["Numéro absent de la liste blanche", "text-amber-800 bg-amber-50 ring-amber-200"],
  denylisted: ["Numéro bloqué", "text-slate-700 bg-slate-50 ring-slate-200"],
  human_takeover_active: ["Un humain a repris la conversation", "text-slate-700 bg-slate-50 ring-slate-200"],
  liluvine_pro_not_enabled: ["Liluvine PRO non activé pour ce compte (SMART Communications)", "text-rose-700 bg-rose-50 ring-rose-200"],
  contract_invalid: ["Contrat du client invalide (décisionnaires prévenus)", "text-rose-700 bg-rose-50 ring-rose-200"],
  contract_invalid_no_decision_maker: ["Contrat du client invalide, aucun décisionnaire à prévenir", "text-rose-700 bg-rose-50 ring-rose-200"],
  access_restricted_outside_hours: ["Accès restreint hors heures ouvrées (formule du client)", "text-amber-800 bg-amber-50 ring-amber-200"],
  prospect_replies_disabled: ["Réponses aux prospects désactivées", "text-amber-800 bg-amber-50 ring-amber-200"],
  non_text_message: ["Message non textuel (vocal, image, document…) : pas de réponse IA", "text-slate-700 bg-slate-50 ring-slate-200"],
  task_ack: ["Accusé de tâche (OK 1, FAIT 2…) traité à part", "text-slate-700 bg-slate-50 ring-slate-200"],
  hr_command: ["Commande RH traitée à part", "text-slate-700 bg-slate-50 ring-slate-200"],
  empty_text: ["Message vide", "text-slate-700 bg-slate-50 ring-slate-200"],
  empty_reply: ["L'IA n'a rien renvoyé", "text-rose-700 bg-rose-50 ring-rose-200"],
  llm_error: ["Erreur de l'IA (clé, quota ou réseau)", "text-rose-700 bg-rose-50 ring-rose-200"],
  EMERGENT_LLM_KEY: ["Clé IA (EMERGENT_LLM_KEY) absente", "text-rose-700 bg-rose-50 ring-rose-200"],
  send_failed: ["Échec d'envoi par Meta (fenêtre 24 h, numéro…)", "text-rose-700 bg-rose-50 ring-rose-200"],
  unknown_fallback_disabled: ["Commande « ! » inconnue, réponse de repli désactivée", "text-amber-800 bg-amber-50 ring-amber-200"],
  crash: ["Erreur interne de l'auto-réponse", "text-rose-700 bg-rose-50 ring-rose-200"],
};
// « cooldown (42s left) » → « cooldown » ; « llm_error: … » → « llm_error »
const reasonKey = (d) => (d.ok ? "sent" : String(d.reason || "unknown").split(/[ :(]/)[0]);
const reasonLabel = (key) => (REASON_LABELS[key] || [key, "text-slate-700 bg-slate-50 ring-slate-200"]);

export default function LiluvineWaAutoreplySection() {
  const [cfg, setCfg] = useState(null);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [history, setHistory] = useState([]);
  const [showHistory, setShowHistory] = useState(false);
  // Lot 24 — journal des décisions (répondu / pourquoi pas)
  const [decisions, setDecisions] = useState(null);

  const load = useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/liluvine-pro/wa-autoreply");
      setCfg(r.data);
      setForm({
        enabled: !!r.data.enabled,
        allow_mode: r.data.allow_mode || "any",
        schedule: r.data.schedule || "always",
        cooldown_seconds: r.data.cooldown_seconds ?? 60,
        signature: r.data.signature || "",
        allow_phones: (r.data.allow_phones || []).join(", "),
        deny_phones: (r.data.deny_phones || []).join(", "),
        keywords: (r.data.keywords || []).join(", "),
        // Iter43-fix24h/j — Catch-all `…` + brand info pour !adresse/!horaires
        unknown_cmd_reply: r.data.unknown_cmd_reply || "",
        unknown_cmd_fallback_enabled: r.data.unknown_cmd_fallback_enabled !== false,
        brand_name: r.data.brand_name || "",
        brand_phone: r.data.brand_phone || "",
        brand_whatsapp: r.data.brand_whatsapp || "",
        brand_email: r.data.brand_email || "",
        brand_address: r.data.brand_address || "",
        brand_city: r.data.brand_city || "",
        brand_country: r.data.brand_country || "",
        brand_location_hint: r.data.brand_location_hint || "",
        brand_latitude: r.data.brand_latitude == null ? "" : String(r.data.brand_latitude),
        brand_longitude: r.data.brand_longitude == null ? "" : String(r.data.brand_longitude),
        brand_hours: r.data.brand_hours || "",
        brand_maps_url: r.data.brand_maps_url || "",
        // Lot 21 — Prospects (expéditeurs non contractuels) + consignes « Mode WhatsApp »
        prospect_enabled: r.data.prospect_enabled !== false,
        prospect_system_prompt: r.data.prospect_system_prompt || "",
        mode_instructions: r.data.mode_instructions || "",
      });
    } catch (e) {
      toast.error("Erreur chargement config auto-réponse");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        enabled: !!form.enabled,
        allow_mode: form.allow_mode,
        schedule: form.schedule,
        cooldown_seconds: parseInt(form.cooldown_seconds || 0, 10),
        signature: form.signature,
        allow_phones: (form.allow_phones || "").split(",").map((s) => s.trim()).filter(Boolean),
        deny_phones: (form.deny_phones || "").split(",").map((s) => s.trim()).filter(Boolean),
        keywords: (form.keywords || "").split(",").map((s) => s.trim()).filter(Boolean),
        // Iter43-fix24h/j
        unknown_cmd_reply: form.unknown_cmd_reply || "",
        unknown_cmd_fallback_enabled: !!form.unknown_cmd_fallback_enabled,
        brand_name: form.brand_name || "",
        brand_phone: form.brand_phone || "",
        brand_whatsapp: form.brand_whatsapp || "",
        brand_email: form.brand_email || "",
        brand_address: form.brand_address || "",
        brand_city: form.brand_city || "",
        brand_country: form.brand_country || "",
        brand_location_hint: form.brand_location_hint || "",
        brand_hours: form.brand_hours || "",
        brand_maps_url: form.brand_maps_url || "",
        // Lot 21
        prospect_enabled: !!form.prospect_enabled,
        prospect_system_prompt: form.prospect_system_prompt || "",
        mode_instructions: form.mode_instructions || "",
      };
      const latStr = (form.brand_latitude ?? "").toString().trim();
      const lonStr = (form.brand_longitude ?? "").toString().trim();
      if (latStr) {
        const n = Number(latStr);
        if (Number.isNaN(n) || n < -90 || n > 90) {
          toast.error("Latitude invalide (doit être entre -90 et 90)");
          setSaving(false);
          return;
        }
        payload.brand_latitude = n;
      }
      if (lonStr) {
        const n = Number(lonStr);
        if (Number.isNaN(n) || n < -180 || n > 180) {
          toast.error("Longitude invalide (doit être entre -180 et 180)");
          setSaving(false);
          return;
        }
        payload.brand_longitude = n;
      }
      await apiClient.put("/admin/liluvine-pro/wa-autoreply", payload);
      toast.success("Configuration enregistrée");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur d'enregistrement");
    } finally {
      setSaving(false);
    }
  };

  const loadHistory = async () => {
    try {
      const r = await apiClient.get("/admin/liluvine-pro/wa-autoreply/history?limit=30");
      setHistory(r.data?.items || []);
      setShowHistory(true);
    } catch {
      toast.error("Erreur chargement historique");
    }
  };

  const loadDecisions = async () => {
    try {
      const r = await apiClient.get("/admin/liluvine-pro/wa-autoreply/decisions?limit=60");
      setDecisions(r.data || { items: [], stats_7d: {} });
    } catch {
      toast.error("Erreur chargement du journal des décisions");
    }
  };

  if (!cfg) return null;

  return (
    <section className="rounded-xl border border-fuchsia-200 bg-gradient-to-br from-fuchsia-50/40 to-white p-5 space-y-4" data-testid="liluvine-wa-autoreply-section">
      <header className="flex items-center justify-between gap-2 flex-wrap">
        <h2 className="text-base font-display font-bold inline-flex items-center gap-2 text-fuchsia-900">
          <Sparkles className="h-5 w-5 text-fuchsia-600" /> {TITLE}
        </h2>
        <button
          type="button"
          onClick={loadHistory}
          className="text-xs inline-flex items-center gap-1 rounded-lg ring-1 ring-slate-300 hover:bg-slate-50 px-2.5 py-1.5"
          data-testid="liluvine-autoreply-history-btn"
        >
          <History className="h-3.5 w-3.5" /> Historique
        </button>
        {/* Lot 24 — pourquoi Liluvine n'a pas répondu */}
        <button
          type="button"
          onClick={loadDecisions}
          className="text-xs inline-flex items-center gap-1 rounded-lg ring-1 ring-amber-300 bg-amber-50 hover:bg-amber-100 text-amber-900 px-2.5 py-1.5"
          data-testid="liluvine-autoreply-decisions-btn"
        >
          <AlertCircle className="h-3.5 w-3.5" /> Pourquoi Liluvine n'a pas répondu ?
        </button>
      </header>

      <p className="text-xs text-slate-600 leading-relaxed">
        Quand cette option est activée, Liluvine PRO répond automatiquement aux messages WhatsApp entrants (sans passer par n8n).
        Pour vos clients, le contexte de votre CRM est injecté via le RAG (contacts, tickets, paiements, RDV, notes) ;
        les prospects, eux, n'en reçoivent rien (voir « Prospects » ci-dessous).
        Un anti-flood limite à <strong>1 réponse / {form.cooldown_seconds || 60}s par numéro</strong>.
      </p>

      {/* Master toggle */}
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={!!form.enabled}
          onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
          className="h-4 w-4 rounded text-fuchsia-600"
          data-testid="liluvine-autoreply-enabled"
        />
        <span className="text-sm font-medium text-slate-800">Activer l'auto-réponse Liluvine PRO sur WhatsApp</span>
      </label>

      {/* Allow / Deny lists */}
      <div className="grid sm:grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-700 mb-1">Numéros autorisés (séparés par virgule)</label>
          <input
            type="text"
            value={form.allow_phones}
            onChange={(e) => setForm({ ...form, allow_phones: e.target.value })}
            placeholder="22890000001, 22890000002"
            className="w-full text-xs rounded-lg border border-slate-300 px-3 py-2 font-mono"
            data-testid="liluvine-autoreply-allow-phones"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-700 mb-1">Numéros bloqués (séparés par virgule)</label>
          <input
            type="text"
            value={form.deny_phones}
            onChange={(e) => setForm({ ...form, deny_phones: e.target.value })}
            placeholder="22890000099"
            className="w-full text-xs rounded-lg border border-slate-300 px-3 py-2 font-mono"
            data-testid="liluvine-autoreply-deny-phones"
          />
        </div>
      </div>

      {/* Mode + Schedule */}
      <div className="grid sm:grid-cols-3 gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-700 mb-1">Mode des numéros autorisés</label>
          <select
            value={form.allow_mode}
            onChange={(e) => setForm({ ...form, allow_mode: e.target.value })}
            className="w-full text-xs rounded-lg border border-slate-300 px-3 py-2"
            data-testid="liluvine-autoreply-mode"
          >
            <option value="any">Tous (sauf bloqués)</option>
            <option value="whitelist">Whitelist stricte</option>
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-700 mb-1">Plage horaire</label>
          <select
            value={form.schedule}
            onChange={(e) => setForm({ ...form, schedule: e.target.value })}
            className="w-full text-xs rounded-lg border border-slate-300 px-3 py-2"
            data-testid="liluvine-autoreply-schedule"
          >
            <option value="always">Toujours répondre</option>
            <option value="business_hours">Heures ouvrables uniquement</option>
            <option value="outside_hours">Hors heures ouvrables (recommandé)</option>
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-700 mb-1">Anti-flood (secondes)</label>
          <input
            type="number"
            min="0"
            max="3600"
            value={form.cooldown_seconds}
            onChange={(e) => setForm({ ...form, cooldown_seconds: e.target.value })}
            className="w-full text-xs rounded-lg border border-slate-300 px-3 py-2"
            data-testid="liluvine-autoreply-cooldown"
          />
        </div>
      </div>

      {/* Keywords */}
      <div>
        <label className="block text-xs font-medium text-slate-700 mb-1">
          Mots-clés déclencheurs <span className="text-slate-400">(facultatif — vide = répond à tous)</span>
        </label>
        <input
          type="text"
          value={form.keywords}
          onChange={(e) => setForm({ ...form, keywords: e.target.value })}
          placeholder="info, tarif, horaire, devis, contact"
          className="w-full text-xs rounded-lg border border-slate-300 px-3 py-2"
          data-testid="liluvine-autoreply-keywords"
        />
      </div>

      {/* Signature */}
      <div>
        <label className="block text-xs font-medium text-slate-700 mb-1">Signature ajoutée à chaque réponse</label>
        <input
          type="text"
          value={form.signature}
          onChange={(e) => setForm({ ...form, signature: e.target.value })}
          placeholder="— 🤖 Réponse automatique Liluvine PRO"
          maxLength={200}
          className="w-full text-xs rounded-lg border border-slate-300 px-3 py-2"
          data-testid="liluvine-autoreply-signature"
        />
        <p className="text-[10px] text-slate-500 mt-1">Laissez vide pour conserver la valeur par défaut. Sera ajoutée à la fin de chaque réponse pour transparence.</p>
      </div>

      {/* Lot 21 — Prospects : expéditeurs non contractuels (numéro inconnu ou contact étiqueté « prospect ») */}
      <div className="rounded-lg ring-1 ring-violet-200 bg-violet-50/40 p-3 space-y-2" data-testid="liluvine-prospect-section">
        <h3 className="text-xs font-semibold text-violet-900 inline-flex items-center gap-1.5">
          <UserPlus className="h-3.5 w-3.5" /> Prospects — expéditeurs non contractuels
        </h3>
        <p className="text-[10px] text-violet-900/80 leading-relaxed">
          Un <strong>prospect</strong> est un numéro inconnu (absent du carnet de contacts et des comptes) ou un contact
          portant l'étiquette <code>prospect</code>. Liluvine lui répond avec le prompt ci-dessous
          (et non le prompt système de votre compte), en s'appuyant uniquement sur la base de connaissance :
          <strong> aucune donnée de votre CRM</strong> (contacts, paiements, tickets…) ne lui est transmise.
        </p>
        <label className="flex items-center gap-2 text-[11px] text-violet-900 cursor-pointer">
          <input
            type="checkbox"
            checked={!!form.prospect_enabled}
            onChange={(e) => setForm({ ...form, prospect_enabled: e.target.checked })}
            data-testid="liluvine-prospect-enabled"
          />
          <strong>Répondre automatiquement aux prospects</strong>
        </label>
        <div className="flex items-center justify-between">
          <span className="text-[10px] uppercase tracking-wider font-semibold text-violet-900">Prompt système des prospects</span>
          {/* Pré-remplit la zone avec le texte par défaut, pour le modifier plutôt que partir de zéro */}
          <button
            type="button"
            onClick={() => setForm({ ...form, prospect_system_prompt: cfg.default_prospect_system_prompt || "" })}
            className="text-[10px] inline-flex items-center gap-1 text-violet-700 hover:underline"
            data-testid="liluvine-prospect-load-default"
          >
            <Copy className="h-3 w-3" /> Partir du texte par défaut
          </button>
        </div>
        <textarea
          value={form.prospect_system_prompt}
          onChange={(e) => setForm({ ...form, prospect_system_prompt: e.target.value })}
          rows={8}
          maxLength={20000}
          placeholder={cfg.default_prospect_system_prompt || ""}
          className="w-full text-xs rounded-lg border border-violet-300 px-3 py-2 bg-white font-mono leading-relaxed"
          data-testid="liluvine-prospect-prompt"
        />
        <p className="text-[10px] text-violet-900/70">Vide = texte par défaut (affiché en grisé).</p>
      </div>

      {/* Lot 21 — Consignes ajoutées à TOUTE réponse WhatsApp (clients et prospects) */}
      <div className="rounded-lg ring-1 ring-sky-200 bg-sky-50/40 p-3 space-y-2" data-testid="liluvine-mode-section">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold text-sky-900 inline-flex items-center gap-1.5">
            <MessageCircle className="h-3.5 w-3.5" /> Consignes du mode WhatsApp (toutes les réponses)
          </h3>
          {/* Vider la zone = retour au texte d'origine */}
          <button
            type="button"
            onClick={() => setForm({ ...form, mode_instructions: "" })}
            className="text-[10px] inline-flex items-center gap-1 text-sky-700 hover:underline"
            data-testid="liluvine-mode-reset"
          >
            <RotateCcw className="h-3 w-3" /> Texte d'origine
          </button>
        </div>
        <p className="text-[10px] text-sky-900/80">
          Ajoutées après le prompt système (du compte ou des prospects), sous l'en-tête
          « [IMPORTANT — Mode auto-réponse WhatsApp] » : longueur, ton, renvoi vers un humain…
        </p>
        <textarea
          value={form.mode_instructions}
          onChange={(e) => setForm({ ...form, mode_instructions: e.target.value })}
          rows={4}
          maxLength={4000}
          placeholder={cfg.default_mode_instructions || ""}
          className="w-full text-xs rounded-lg border border-sky-300 px-3 py-2 bg-white font-mono leading-relaxed"
          data-testid="liluvine-mode-instructions"
        />
      </div>

      {/* Iter43-fix24h — Catch-all "…" pour commandes inconnues */}
      <div className="rounded-lg ring-1 ring-orange-200 bg-orange-50/40 p-3 space-y-2" data-testid="liluvine-unknown-cmd-section">
        <h3 className="text-xs font-semibold text-orange-900 inline-flex items-center gap-1.5">
          <Sparkles className="h-3.5 w-3.5" /> Fallback pour les commandes <code className="px-1 bg-white rounded">!xxx</code> inconnues
        </h3>
        <label className="flex items-start gap-2 text-[11px] text-orange-900 cursor-pointer">
          <input
            type="checkbox"
            checked={!!form.unknown_cmd_fallback_enabled}
            onChange={(e) => setForm({ ...form, unknown_cmd_fallback_enabled: e.target.checked })}
            className="mt-0.5"
            data-testid="liluvine-unknown-fallback-enabled"
          />
          <span>
            <strong>Activer la réponse automatique</strong> pour les <code>!commandes</code> non reconnues (recommandé).
            <br />
            <span className="text-[10px] opacity-80">Sinon Liluvine reste muette sur <code>!Aizenta</code>, <code>!truc</code>, etc. — l'utilisateur ne saura pas si son message a été reçu.</span>
          </span>
        </label>
        <input
          type="text"
          value={form.unknown_cmd_reply}
          onChange={(e) => setForm({ ...form, unknown_cmd_reply: e.target.value })}
          placeholder="…"
          maxLength={500}
          className="w-full text-xs rounded-lg border border-orange-300 px-3 py-2 bg-white"
          data-testid="liluvine-unknown-cmd-reply"
        />
        <p className="text-[10px] text-orange-900/70">Message envoyé pour toute <code>!commande</code> non gérée. Vide = <code>…</code> par défaut.</p>
      </div>

      {/* Iter43-fix24j — Profil marque/HQ pour !adresse, !horaires, !contact */}
      <div className="rounded-lg ring-1 ring-emerald-200 bg-emerald-50/40 p-3 space-y-3" data-testid="liluvine-brand-section">
        <h3 className="text-xs font-semibold text-emerald-900 inline-flex items-center gap-1.5">
          <MessageCircle className="h-3.5 w-3.5" /> Profil enseigne pour les commandes <code className="px-1 bg-white rounded">!adresse</code> / <code className="px-1 bg-white rounded">!horaires</code> / <code className="px-1 bg-white rounded">!contact</code>
        </h3>
        <p className="text-[10px] text-emerald-900/70 -mt-2">
          Ces infos sont envoyées en clair à l'utilisateur WhatsApp + carte map cliquable si latitude/longitude renseignées.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          <label className="block">
            <span className="block text-[10px] uppercase tracking-wider font-semibold text-emerald-900">Nom enseigne</span>
            <input
              type="text" value={form.brand_name}
              onChange={(e) => setForm({ ...form, brand_name: e.target.value })}
              placeholder="SAWALI SMART SYSTEMS"
              maxLength={200}
              className="w-full mt-1 text-xs rounded-lg border border-emerald-300 px-3 py-2 bg-white"
              data-testid="liluvine-brand-name"
            />
          </label>
          <label className="block">
            <span className="block text-[10px] uppercase tracking-wider font-semibold text-emerald-900">Email contact</span>
            <input
              type="email" value={form.brand_email}
              onChange={(e) => setForm({ ...form, brand_email: e.target.value })}
              placeholder="contact@sawalismartsystems.com"
              maxLength={200}
              className="w-full mt-1 text-xs rounded-lg border border-emerald-300 px-3 py-2 bg-white"
              data-testid="liluvine-brand-email"
            />
          </label>
          <label className="block">
            <span className="block text-[10px] uppercase tracking-wider font-semibold text-emerald-900">Téléphone</span>
            <input
              type="text" value={form.brand_phone}
              onChange={(e) => setForm({ ...form, brand_phone: e.target.value })}
              placeholder="+226 25 00 00 00"
              maxLength={40}
              className="w-full mt-1 text-xs rounded-lg border border-emerald-300 px-3 py-2 bg-white"
              data-testid="liluvine-brand-phone"
            />
          </label>
          <label className="block">
            <span className="block text-[10px] uppercase tracking-wider font-semibold text-emerald-900">WhatsApp</span>
            <input
              type="text" value={form.brand_whatsapp}
              onChange={(e) => setForm({ ...form, brand_whatsapp: e.target.value })}
              placeholder="+226 70 00 00 00"
              maxLength={40}
              className="w-full mt-1 text-xs rounded-lg border border-emerald-300 px-3 py-2 bg-white"
              data-testid="liluvine-brand-whatsapp"
            />
          </label>
          <label className="block md:col-span-2">
            <span className="block text-[10px] uppercase tracking-wider font-semibold text-emerald-900">Adresse complète</span>
            <input
              type="text" value={form.brand_address}
              onChange={(e) => setForm({ ...form, brand_address: e.target.value })}
              placeholder="12 Avenue Houphouët-Boigny"
              maxLength={300}
              className="w-full mt-1 text-xs rounded-lg border border-emerald-300 px-3 py-2 bg-white"
              data-testid="liluvine-brand-address"
            />
          </label>
          <label className="block">
            <span className="block text-[10px] uppercase tracking-wider font-semibold text-emerald-900">Ville</span>
            <input
              type="text" value={form.brand_city}
              onChange={(e) => setForm({ ...form, brand_city: e.target.value })}
              placeholder="Ouagadougou"
              maxLength={100}
              className="w-full mt-1 text-xs rounded-lg border border-emerald-300 px-3 py-2 bg-white"
              data-testid="liluvine-brand-city"
            />
          </label>
          <label className="block">
            <span className="block text-[10px] uppercase tracking-wider font-semibold text-emerald-900">Pays</span>
            <input
              type="text" value={form.brand_country}
              onChange={(e) => setForm({ ...form, brand_country: e.target.value })}
              placeholder="Burkina Faso"
              maxLength={100}
              className="w-full mt-1 text-xs rounded-lg border border-emerald-300 px-3 py-2 bg-white"
              data-testid="liluvine-brand-country"
            />
          </label>
          <label className="block md:col-span-2">
            <span className="block text-[10px] uppercase tracking-wider font-semibold text-emerald-900">
              Indication de localisation <span className="opacity-60">(repères visuels — affichés sur la fiche officine)</span>
            </span>
            <input
              type="text" value={form.brand_location_hint}
              onChange={(e) => setForm({ ...form, brand_location_hint: e.target.value })}
              placeholder="À côté de la station Total, en face de la mosquée"
              maxLength={300}
              className="w-full mt-1 text-xs rounded-lg border border-emerald-300 px-3 py-2 bg-white"
              data-testid="liluvine-brand-location-hint"
            />
          </label>
          <label className="block">
            <span className="block text-[10px] uppercase tracking-wider font-semibold text-emerald-900">Latitude (-90 à 90)</span>
            <input
              type="number" step="0.000001" min="-90" max="90"
              value={form.brand_latitude}
              onChange={(e) => setForm({ ...form, brand_latitude: e.target.value })}
              placeholder="12.371428"
              className="w-full mt-1 text-xs rounded-lg border border-emerald-300 px-3 py-2 bg-white font-mono"
              data-testid="liluvine-brand-latitude"
            />
          </label>
          <label className="block">
            <span className="block text-[10px] uppercase tracking-wider font-semibold text-emerald-900">Longitude (-180 à 180)</span>
            <input
              type="number" step="0.000001" min="-180" max="180"
              value={form.brand_longitude}
              onChange={(e) => setForm({ ...form, brand_longitude: e.target.value })}
              placeholder="-1.519582"
              className="w-full mt-1 text-xs rounded-lg border border-emerald-300 px-3 py-2 bg-white font-mono"
              data-testid="liluvine-brand-longitude"
            />
          </label>
          <label className="block md:col-span-2">
            <span className="block text-[10px] uppercase tracking-wider font-semibold text-emerald-900">
              URL Google Maps personnalisée <span className="opacity-60">(optionnel — sinon générée auto depuis lat/lon)</span>
            </span>
            <input
              type="url" value={form.brand_maps_url}
              onChange={(e) => setForm({ ...form, brand_maps_url: e.target.value })}
              placeholder="https://maps.app.goo.gl/abc123…"
              maxLength={500}
              className="w-full mt-1 text-xs rounded-lg border border-emerald-300 px-3 py-2 bg-white"
              data-testid="liluvine-brand-maps-url"
            />
          </label>
          <label className="block md:col-span-2">
            <span className="block text-[10px] uppercase tracking-wider font-semibold text-emerald-900">
              Horaires d'ouverture <span className="opacity-60">(une ligne par jour — le jour courant sera mis en évidence)</span>
            </span>
            <textarea
              value={form.brand_hours}
              onChange={(e) => setForm({ ...form, brand_hours: e.target.value })}
              rows={7}
              maxLength={2000}
              placeholder="Lundi : 08h00 - 19h30&#10;Mardi : 08h00 - 19h30&#10;Mercredi : 08h00 - 19h30&#10;Jeudi : 08h00 - 19h30&#10;Vendredi : 08h00 - 19h30&#10;Samedi : 09h00 - 13h00&#10;Dimanche : Fermé"
              className="w-full mt-1 text-xs rounded-lg border border-emerald-300 px-3 py-2 bg-white font-mono leading-relaxed"
              data-testid="liluvine-brand-hours"
            />
          </label>
        </div>
        <p className="text-[10px] text-emerald-900/70 leading-relaxed">
          💡 <strong>Astuce :</strong> pour récupérer rapidement vos coordonnées GPS, ouvrez Google Maps sur l'emplacement de l'officine,
          faites un clic droit (ou un appui long sur mobile) puis cliquez sur les coordonnées qui s'affichent — elles seront copiées au format <code>12.371428, -1.519582</code>.
        </p>
      </div>

      <div className="flex items-start gap-2 rounded-lg bg-amber-50 ring-1 ring-amber-200 p-3">
        <AlertCircle className="h-4 w-4 text-amber-600 flex-shrink-0 mt-0.5" />
        <p className="text-[11px] text-amber-900">
          <strong>Pré-requis</strong> : Liluvine PRO doit être activé dans SMART Communications pour votre compte
          (Admin → Mon Compte → SMART Communications → Liluvine PRO).
          Sinon, les messages sont ignorés silencieusement.
        </p>
      </div>

      {/* Save */}
      <div className="flex justify-end">
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="inline-flex items-center gap-2 rounded-lg bg-fuchsia-600 hover:bg-fuchsia-700 text-white px-4 py-2 text-sm font-medium disabled:opacity-50"
          data-testid="liluvine-autoreply-save"
        >
          <Save className="h-4 w-4" /> {saving ? "Enregistrement…" : "Enregistrer"}
        </button>
      </div>

      {/* Lot 24 — journal des décisions de l'auto-réponse */}
      {decisions && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 p-4" onClick={() => setDecisions(null)}>
          <div className="bg-white rounded-2xl shadow-2xl max-w-3xl w-full max-h-[85vh] overflow-hidden flex flex-col" onClick={(e) => e.stopPropagation()}
            data-testid="liluvine-autoreply-decisions">
            <header className="px-5 py-3 border-b border-slate-200 flex items-center justify-between">
              <h3 className="font-display font-semibold text-slate-800 inline-flex items-center gap-2">
                <AlertCircle className="h-4 w-4 text-amber-600" /> Pourquoi Liluvine n'a pas répondu ?
              </h3>
              <button onClick={() => setDecisions(null)} className="text-slate-400 hover:text-slate-700 text-xl leading-none">×</button>
            </header>
            <div className="overflow-y-auto p-4 space-y-4 flex-1">
              <p className="text-[11px] text-slate-600">
                Une ligne par message WhatsApp reçu. Le <strong>prompt système</strong> ne provoque jamais de silence : il règle seulement
                le contenu des réponses. Un silence vient toujours d'un réglage ci-dessus (anti-flood, mots-clés, plage horaire, liste
                blanche…) ou d'une erreur indiquée ici.
              </p>
              {/* Répartition sur 7 jours */}
              <div className="flex flex-wrap gap-1.5" data-testid="liluvine-autoreply-decisions-stats">
                {Object.entries(decisions.stats_7d || {}).sort((a, b) => b[1] - a[1]).map(([k, n]) => {
                  const [label, cls] = reasonLabel(k);
                  return <span key={k} className={`text-[11px] rounded-full ring-1 px-2 py-0.5 ${cls}`}>{label} : <strong>{n}</strong></span>;
                })}
                {Object.keys(decisions.stats_7d || {}).length === 0 && <span className="text-xs text-slate-400">Aucun message reçu ces 7 derniers jours.</span>}
              </div>
              <ul className="divide-y divide-slate-100">
                {(decisions.items || []).map((d) => {
                  const [label, cls] = reasonLabel(reasonKey(d));
                  return (
                    <li key={d.id} className="py-2 flex items-start gap-3 text-xs" data-testid={`liluvine-decision-${d.id}`}>
                      <span className="text-[10px] text-slate-400 w-24 shrink-0">{new Date(d.at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}</span>
                      <span className="flex-1 min-w-0">
                        <span className="font-medium text-slate-800">{d.contact_name || `+${d.phone_digits}`}</span>
                        {d.prospect && <span className="ml-1 text-[10px] rounded bg-violet-50 text-violet-700 px-1">prospect</span>}
                        <span className="block text-slate-500 truncate">{d.text || `(${d.message_type})`}</span>
                      </span>
                      <span className={`shrink-0 max-w-[45%] text-right text-[10px] rounded ring-1 px-1.5 py-0.5 ${cls}`} title={d.reason}>{label}</span>
                    </li>
                  );
                })}
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* History modal */}
      {showHistory && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 p-4" onClick={() => setShowHistory(false)}>
          <div className="bg-white rounded-2xl shadow-2xl max-w-3xl w-full max-h-[80vh] overflow-hidden flex flex-col" onClick={(e) => e.stopPropagation()}>
            <header className="px-5 py-3 border-b border-slate-200 flex items-center justify-between">
              <h3 className="font-display font-semibold text-slate-800 inline-flex items-center gap-2">
                <MessageCircle className="h-4 w-4 text-fuchsia-600" /> Historique des réponses auto ({history.length})
              </h3>
              <button onClick={() => setShowHistory(false)} className="text-slate-400 hover:text-slate-700 text-xl leading-none">×</button>
            </header>
            <div className="overflow-y-auto p-4 space-y-3 flex-1">
              {history.length === 0 ? (
                <p className="text-sm text-slate-500 text-center py-8">Aucune réponse automatique envoyée pour le moment.</p>
              ) : (
                history.map((m) => (
                  <div key={m.id} className="rounded-lg ring-1 ring-slate-200 p-3 bg-slate-50/50" data-testid={`autoreply-hist-${m.id}`}>
                    <div className="flex items-center justify-between text-[10px] text-slate-500 mb-2">
                      <span className="font-mono">{m.session_label}</span>
                      <span>{new Date(m.created_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}</span>
                    </div>
                    <p className="text-xs text-slate-700 whitespace-pre-wrap">{m.content}</p>
                    <div className="text-[10px] text-slate-400 mt-2 flex gap-2 flex-wrap">
                      {m.context_injected && <span className="rounded-full bg-sky-50 ring-1 ring-sky-200 px-1.5 py-0.5 text-sky-700">RAG actif</span>}
                      {/* Lot 21 — réponse faite avec le prompt des prospects */}
                      {m.prospect && <span className="rounded-full bg-violet-50 ring-1 ring-violet-200 px-1.5 py-0.5 text-violet-700">Prospect</span>}
                      {m.tokens && <span>~{m.tokens} tokens</span>}
                      {m.wa_message_id_out && <span className="font-mono">wa: {m.wa_message_id_out.slice(-12)}</span>}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
