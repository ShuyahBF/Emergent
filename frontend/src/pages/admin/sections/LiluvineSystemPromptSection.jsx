// =====================================================================
// Iter38r-fix9o (Item 1) — Liluvine PRO system prompt editor.
// Per-tenant override of the assistant's system prompt + access to the
// default fallback. The configured prompt is read by both web/internal
// chat sessions AND WhatsApp auto-reply, with an escalation rule auto-
// appended server-side.
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { Bot, RotateCcw, Eye, EyeOff } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const LiluvineSystemPromptSection = () => {
  const [prompt, setPrompt] = useState("");
  const [defaultPrompt, setDefaultPrompt] = useState("");
  const [showDefault, setShowDefault] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/liluvine-pro/system-prompt");
      setPrompt(r.data?.system_prompt || "");
      setDefaultPrompt(r.data?.default || "");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setBusy(true);
    try {
      await apiClient.put("/admin/liluvine-pro/system-prompt", { system_prompt: prompt });
      toast.success("Prompt système enregistré");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setBusy(false);
    }
  };

  const resetToDefault = () => {
    if (!window.confirm("Effacer votre prompt personnalisé et réutiliser le prompt par défaut ?")) return;
    setPrompt("");
  };

  return (
    <section className="rounded-2xl ring-1 ring-fuchsia-200 bg-gradient-to-br from-fuchsia-50/40 via-white to-pink-50/30 p-5" data-testid="liluvine-system-prompt-section">
      <header className="flex items-center gap-3 mb-3">
        <div className="rounded-full bg-fuchsia-100 ring-1 ring-fuchsia-200 p-2">
          <Bot className="h-5 w-5 text-fuchsia-700" />
        </div>
        <div>
          <h3 className="font-display font-bold text-slate-900">Liluvine PRO — Prompt système (assistant)</h3>
          <p className="text-xs text-slate-500 mt-0.5">
            Personnalisez le ton, le rôle et les règles de Liluvine pour votre entreprise. La règle d'escalade vers un humain est ajoutée automatiquement côté serveur (token <code className="rounded bg-slate-100 px-1">[ESCALATION_HUMAINE]</code>).
          </p>
        </div>
      </header>

      <div className="space-y-3">
        <div className="rounded-xl bg-white ring-1 ring-fuchsia-100 p-3">
          <div className="flex items-center justify-between mb-2">
            <label className="text-[10px] uppercase tracking-wider text-slate-500">
              Votre prompt personnalisé
            </label>
            <span className="text-[10px] text-slate-400">
              {prompt.length} caractères
              {prompt.trim() === "" && <span className="ml-2 text-amber-600 font-semibold">• prompt par défaut utilisé</span>}
            </span>
          </div>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Ex : Tu es Liluvine, l'assistante de la Clinique CMCO. Tu réponds en français de manière chaleureuse et professionnelle. Ne donne JAMAIS de diagnostic médical, redirige toujours vers un médecin pour les questions cliniques…"
            rows={10}
            disabled={loading}
            className="w-full text-sm font-mono rounded-lg ring-1 ring-slate-300 px-3 py-2 resize-y bg-white"
            data-testid="liluvine-system-prompt-textarea"
          />
          <div className="flex flex-wrap gap-2 mt-3">
            <button
              type="button"
              onClick={save}
              disabled={busy || loading}
              className="text-xs rounded-lg bg-fuchsia-600 hover:bg-fuchsia-700 text-white px-3 py-1.5 disabled:opacity-50"
              data-testid="liluvine-system-prompt-save"
            >
              {busy ? "Enregistrement…" : "Enregistrer"}
            </button>
            <button
              type="button"
              onClick={resetToDefault}
              disabled={busy || !prompt}
              className="text-xs rounded-lg ring-1 ring-slate-300 px-3 py-1.5 hover:bg-slate-50 inline-flex items-center gap-1 disabled:opacity-50"
              data-testid="liluvine-system-prompt-reset"
            >
              <RotateCcw className="h-3 w-3" /> Réinitialiser au prompt par défaut
            </button>
            <button
              type="button"
              onClick={() => setShowDefault((v) => !v)}
              className="text-xs rounded-lg ring-1 ring-slate-300 px-3 py-1.5 hover:bg-slate-50 inline-flex items-center gap-1"
              data-testid="liluvine-system-prompt-toggle-default"
            >
              {showDefault ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
              {showDefault ? "Masquer" : "Afficher"} le prompt par défaut
            </button>
          </div>
        </div>

        {showDefault && (
          <div className="rounded-xl bg-slate-50 ring-1 ring-slate-200 p-3" data-testid="liluvine-system-prompt-default">
            <label className="text-[10px] uppercase tracking-wider text-slate-500">Prompt par défaut (fallback)</label>
            <pre className="mt-1 text-xs text-slate-700 whitespace-pre-wrap break-words font-mono max-h-64 overflow-y-auto">
{defaultPrompt}
            </pre>
          </div>
        )}

        <p className="text-[11px] text-slate-500">
          💡 Le prompt est partagé entre les sessions web (<code>/portal/liluvine</code>) ET l'auto-réponse WhatsApp.
          Pour des cas où Liluvine ne sait pas répondre, elle émettra automatiquement le marqueur <code>[ESCALATION_HUMAINE]</code> + une phrase de transition.
        </p>
      </div>
    </section>
  );
};

export default LiluvineSystemPromptSection;
