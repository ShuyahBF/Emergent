// =====================================================================
// Iter38r-fix9e — Liluvine PRO : Branding (nom, avatar, couleur)
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { Bot, Palette, Save, ImagePlus, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const COLORS = [
  { id: "fuchsia", label: "Fuchsia", swatch: "bg-fuchsia-500" },
  { id: "violet", label: "Violet", swatch: "bg-violet-500" },
  { id: "indigo", label: "Indigo", swatch: "bg-indigo-500" },
  { id: "sky", label: "Bleu ciel", swatch: "bg-sky-500" },
  { id: "emerald", label: "Émeraude", swatch: "bg-emerald-500" },
  { id: "amber", label: "Ambre", swatch: "bg-amber-500" },
  { id: "rose", label: "Rose", swatch: "bg-rose-500" },
];

export default function LiluvineBrandingSection() {
  const [form, setForm] = useState({ name: "", avatar_url: "", color: "fuchsia", tagline: "" });
  const [saving, setSaving] = useState(false);
  const [genLoading, setGenLoading] = useState(false);
  const [genPrompt, setGenPrompt] = useState("Un robot mignon style cartoon en couleur fuchsia, fond uni, style icône, expression amicale");

  const load = useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/liluvine-pro/branding");
      setForm({
        name: r.data?.name || "Liluvine PRO",
        avatar_url: r.data?.avatar_url || "",
        color: r.data?.color || "fuchsia",
        tagline: r.data?.tagline || "",
      });
    } catch {
      toast.error("Erreur chargement branding");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      await apiClient.put("/admin/liluvine-pro/branding", form);
      toast.success("Branding enregistré");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur d'enregistrement");
    } finally {
      setSaving(false);
    }
  };

  const generateAvatar = async () => {
    if (!genPrompt?.trim()) { toast.error("Décrivez l'avatar à générer"); return; }
    setGenLoading(true);
    try {
      const r = await apiClient.post("/me/ai/generate-image", {
        prompt: genPrompt, icon_mode: true, aspect: "1:1",
      });
      const url = r.data?.url || r.data?.public_url;
      if (url) {
        setForm({ ...form, avatar_url: url });
        toast.success("Avatar généré ! Cliquez sur Enregistrer pour l'appliquer.");
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur génération avatar");
    } finally {
      setGenLoading(false);
    }
  };

  const uploadAvatar = async (file) => {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    fd.append("label", "liluvine-avatar");
    try {
      const r = await apiClient.post("/me/media-library", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      const url = r.data?.public_url || r.data?.url;
      if (url) {
        setForm({ ...form, avatar_url: url });
        toast.success("Avatar uploadé. Cliquez sur Enregistrer pour l'appliquer.");
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur upload");
    }
  };

  return (
    <section className="rounded-xl border border-pink-200 bg-gradient-to-br from-pink-50/40 to-white p-5 space-y-4" data-testid="liluvine-branding-section">
      <header className="flex items-center gap-2">
        <Palette className="h-5 w-5 text-pink-600" />
        <h2 className="text-base font-display font-bold text-pink-900">Liluvine PRO — Personnalisation visuelle</h2>
      </header>
      <p className="text-xs text-slate-600">
        Définissez le nom, l'avatar et la couleur de votre assistant IA. Visibles dans la page Liluvine PRO et les toasts temps réel.
      </p>

      <div className="grid sm:grid-cols-3 gap-4">
        {/* Preview */}
        <div className="rounded-xl bg-white ring-1 ring-slate-200 p-4 flex flex-col items-center justify-center text-center">
          <div className={`relative h-20 w-20 rounded-full ring-4 ring-${form.color || "fuchsia"}-200 bg-${form.color || "fuchsia"}-100 overflow-hidden flex items-center justify-center`}>
            {form.avatar_url ? (
              <img src={form.avatar_url} alt="avatar" className="absolute inset-0 h-full w-full object-cover" />
            ) : (
              <Bot className={`h-10 w-10 text-${form.color || "fuchsia"}-600`} />
            )}
          </div>
          <p className="mt-2 text-sm font-semibold text-slate-800" data-testid="liluvine-branding-preview-name">{form.name || "Liluvine PRO"}</p>
          {form.tagline && <p className="text-[10px] text-slate-500">{form.tagline}</p>}
        </div>

        {/* Fields */}
        <div className="sm:col-span-2 space-y-3">
          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">Nom affiché</label>
            <input type="text" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
              maxLength={80} placeholder="Liluvine PRO"
              className="w-full text-sm rounded-lg border border-slate-300 px-3 py-2"
              data-testid="liluvine-branding-name" />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">Tagline (sous le nom)</label>
            <input type="text" value={form.tagline} onChange={(e) => setForm({ ...form, tagline: e.target.value })}
              maxLength={160} placeholder="Assistant IA SAWALI · disponible 24/7"
              className="w-full text-sm rounded-lg border border-slate-300 px-3 py-2"
              data-testid="liluvine-branding-tagline" />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">Couleur d'accent</label>
            <div className="flex flex-wrap gap-2">
              {COLORS.map((c) => (
                <button key={c.id} type="button"
                  onClick={() => setForm({ ...form, color: c.id })}
                  className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs ring-2 transition ${form.color === c.id ? "ring-slate-900" : "ring-transparent hover:ring-slate-300"}`}
                  data-testid={`liluvine-branding-color-${c.id}`}>
                  <span className={`h-4 w-4 rounded-full ${c.swatch}`} />
                  {c.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">URL avatar (optionnel)</label>
            <input type="text" value={form.avatar_url} onChange={(e) => setForm({ ...form, avatar_url: e.target.value })}
              maxLength={2000} placeholder="https://… ou /api/files/…"
              className="w-full text-sm rounded-lg border border-slate-300 px-3 py-2 font-mono"
              data-testid="liluvine-branding-avatar-url" />
          </div>
        </div>
      </div>

      {/* Generate / upload */}
      <div className="rounded-lg bg-pink-50/60 ring-1 ring-pink-200 p-3 space-y-2">
        <p className="text-xs font-medium text-pink-900 flex items-center gap-1">
          <Sparkles className="h-3.5 w-3.5" /> Générer l'avatar avec l'IA Gemini Nano Banana
        </p>
        <textarea value={genPrompt} onChange={(e) => setGenPrompt(e.target.value)} rows={2}
          className="w-full text-xs rounded-lg border border-pink-300 px-3 py-2 bg-white"
          data-testid="liluvine-branding-gen-prompt" />
        <div className="flex gap-2 flex-wrap">
          <button type="button" onClick={generateAvatar} disabled={genLoading}
            className="inline-flex items-center gap-1 rounded-lg bg-pink-600 hover:bg-pink-700 text-white text-xs px-3 py-1.5 disabled:opacity-50"
            data-testid="liluvine-branding-gen-avatar">
            <Sparkles className="h-3.5 w-3.5" /> {genLoading ? "Génération…" : "Générer"}
          </button>
          <label className="inline-flex items-center gap-1 rounded-lg ring-1 ring-pink-300 hover:bg-pink-50 text-pink-700 text-xs px-3 py-1.5 cursor-pointer">
            <ImagePlus className="h-3.5 w-3.5" /> Uploader une image
            <input type="file" accept="image/*" className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadAvatar(f); e.target.value = ""; }} />
          </label>
        </div>
      </div>

      <div className="flex justify-end">
        <button type="button" onClick={save} disabled={saving}
          className="inline-flex items-center gap-2 rounded-lg bg-pink-600 hover:bg-pink-700 text-white px-4 py-2 text-sm font-medium disabled:opacity-50"
          data-testid="liluvine-branding-save">
          <Save className="h-4 w-4" /> {saving ? "Enregistrement…" : "Enregistrer le branding"}
        </button>
      </div>
    </section>
  );
}
