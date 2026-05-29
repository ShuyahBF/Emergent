// =====================================================================
// Iter38r-fix9a — Liluvine PRO : Auto-réponse WhatsApp native
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { Sparkles, MessageCircle, Save, Copy, History, AlertCircle } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const TITLE = "Liluvine PRO — Auto-réponse WhatsApp (sans n8n)";

export default function LiluvineWaAutoreplySection() {
  const [cfg, setCfg] = useState(null);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [history, setHistory] = useState([]);
  const [showHistory, setShowHistory] = useState(false);

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
      };
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
      </header>

      <p className="text-xs text-slate-600 leading-relaxed">
        Quand cette option est activée, Liluvine PRO répond automatiquement aux messages WhatsApp entrants (sans passer par n8n).
        Le contexte de votre CRM est injecté via le RAG (contacts, tickets, paiements, RDV, notes).
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
