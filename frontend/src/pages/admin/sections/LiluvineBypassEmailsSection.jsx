// =====================================================================
// Bypass list Liluvine PRO (2026-02)
// Admin gère une liste d'emails autorisés à utiliser Liluvine PRO
// même quand la feature `ai_liluvine_pro` est désactivée sur leur tenant.
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { KeyRound, Save, Loader2, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

export default function LiluvineBypassEmailsSection() {
  const [raw, setRaw] = useState("");
  const [original, setOriginal] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/liluvine-pro/bypass-emails");
      const list = (r.data?.emails || []).join(" ");
      setRaw(list);
      setOriginal(list);
    } catch {
      toast.error("Erreur chargement de la liste bypass");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      const emails = raw.split(/[\s,;]+/).map((e) => e.trim()).filter(Boolean);
      const r = await apiClient.patch("/admin/liluvine-pro/bypass-emails", { emails });
      toast.success(`Liste mise à jour : ${r.data?.count || 0} email${(r.data?.count || 0) > 1 ? "s" : ""}`);
      const list = (r.data?.emails || []).join(" ");
      setRaw(list);
      setOriginal(list);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur d'enregistrement");
    } finally {
      setSaving(false);
    }
  };

  const dirty = raw !== original;
  const count = raw.split(/[\s,;]+/).filter((e) => e.trim()).length;

  return (
    <div className="space-y-3" data-testid="liluvine-bypass-section">
      <div className="flex items-start gap-3 rounded-lg bg-fuchsia-50/50 ring-1 ring-fuchsia-200 p-3">
        <ShieldCheck className="h-5 w-5 text-fuchsia-700 mt-0.5 shrink-0" />
        <div className="text-xs text-fuchsia-900 space-y-1">
          <p>
            <strong>Comment ça marche :</strong> les utilisateurs dont l'email figure
            dans cette liste peuvent utiliser <strong>Liluvine PRO</strong> (chat web,
            chat avec image, et auto-réponse WhatsApp) <strong>même si la fonctionnalité
            « ai_liluvine_pro » est désactivée</strong> sur leur tenant parent dans
            « SMART Communications ».
          </p>
          <p className="text-fuchsia-800">
            Cas typique : un modérateur (ex. <code className="rounded bg-white px-1">rabo.f@sawalismartsystems.com</code>)
            dont le tenant n'a pas encore migré, mais qui doit utiliser l'assistant
            pour son travail de support quotidien.
          </p>
        </div>
      </div>

      <label className="block text-xs font-semibold text-slate-700" htmlFor="bypass-emails-input">
        Emails autorisés <span className="text-slate-400 font-normal">(séparés par espace, virgule ou point-virgule)</span>
      </label>
      <textarea
        id="bypass-emails-input"
        rows={3}
        value={raw}
        onChange={(e) => setRaw(e.target.value)}
        disabled={loading || saving}
        placeholder="rabo.f@sawalismartsystems.com  autre.user@exemple.com"
        className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono focus:border-fuchsia-500 focus:ring-1 focus:ring-fuchsia-500 disabled:bg-slate-50"
        data-testid="bypass-emails-textarea"
      />
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] text-slate-500" data-testid="bypass-emails-count">
          {loading ? "Chargement…" : `${count} email${count > 1 ? "s" : ""} dans la liste`}
        </span>
        <button
          type="button"
          onClick={save}
          disabled={!dirty || saving || loading}
          className="inline-flex items-center gap-1.5 rounded-lg bg-fuchsia-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-fuchsia-700 disabled:opacity-50 disabled:cursor-not-allowed"
          data-testid="bypass-emails-save"
        >
          {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
          {saving ? "Enregistrement…" : "Enregistrer"}
        </button>
      </div>

      <p className="text-[10px] text-slate-400 inline-flex items-center gap-1">
        <KeyRound className="h-3 w-3" /> Action réservée admin/superviseur. Validation
        au format email obligatoire.
      </p>
    </div>
  );
}
