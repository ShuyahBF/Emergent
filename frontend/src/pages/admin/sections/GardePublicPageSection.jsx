// Iter43-fix24ak (2026-06-17) — Configurable CMS for the public `/garde` page.
//
// Lets the admin override:
//   - Top banner text (e.g. seasonal greeting like "Joyeux Noël !")
//   - Bottom banner text (e.g. "Prompt rétablissement !")
//   - A click-target image (capture/illustration) shown below the list,
//     wrapped in a link to https://sawalismartsystems.com.
//   - An optional caption for the image.
//
// The public-site link is ALWAYS rendered by the page itself, regardless
// of these settings — they only customize the surrounding content.
import React, { useCallback, useEffect, useState } from "react";
import { Globe, RotateCcw, Upload } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const MAX_IMAGE_BYTES = 2_000_000;  // 2 MB cap for the embedded base64 image

export default function GardePublicPageSection() {
  const [header, setHeader] = useState("");
  const [footer, setFooter] = useState("");
  const [imageUrl, setImageUrl] = useState("");
  const [caption, setCaption] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/settings");
      setHeader(r.data?.garde_page_header || "");
      setFooter(r.data?.garde_page_footer || "");
      setImageUrl(r.data?.garde_page_image_url || "");
      setCaption(r.data?.garde_page_image_caption || "");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur chargement page /garde");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      await apiClient.put("/admin/settings", {
        garde_page_header: header || "",
        garde_page_footer: footer || "",
        garde_page_image_url: imageUrl || "",
        garde_page_image_caption: caption || "",
      });
      toast.success("Configuration de la page /garde enregistrée");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de sauvegarde");
    } finally {
      setSaving(false);
    }
  };

  const reset = () => {
    if (!window.confirm("Vider tous les champs de personnalisation /garde ?")) return;
    setHeader("");
    setFooter("");
    setImageUrl("");
    setCaption("");
  };

  const onPickImage = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > MAX_IMAGE_BYTES) {
      toast.error(`Fichier trop volumineux (max ${(MAX_IMAGE_BYTES / 1_000_000).toFixed(1)} Mo)`);
      e.target.value = "";
      return;
    }
    const reader = new FileReader();
    reader.onload = (ev) => {
      setImageUrl(String(ev.target?.result || ""));
      toast.success(`Image chargée (${(file.size / 1024).toFixed(0)} Ko)`);
    };
    reader.onerror = () => toast.error("Erreur de lecture du fichier");
    reader.readAsDataURL(file);
    e.target.value = "";
  };

  if (loading) return <p className="text-sm text-slate-500 italic">Chargement…</p>;

  return (
    <section
      className="rounded-2xl ring-1 ring-sky-200 bg-gradient-to-br from-sky-50/40 via-white to-cyan-50/30 p-5 space-y-4"
      data-testid="garde-public-page-section"
    >
      <header className="flex items-center gap-3">
        <div className="rounded-full bg-sky-100 ring-1 ring-sky-200 p-2">
          <Globe className="h-5 w-5 text-sky-700" />
        </div>
        <div>
          <h3 className="font-display font-bold text-slate-900">
            Page publique <code className="text-sky-700">/garde</code> — Personnalisation
          </h3>
          <p className="text-xs text-slate-500 mt-0.5">
            Configure les bandeaux haut/bas et une image cliquable affichés sur la liste
            publique des pharmacies de garde. Le lien vers{" "}
            <code className="bg-slate-100 px-1 rounded">https://sawalismartsystems.com</code>{" "}
            est toujours affiché — ces champs viennent autour.
          </p>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Text editor */}
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Bandeau du HAUT (affiché au-dessus du titre)
            </label>
            <textarea
              value={header}
              onChange={(e) => setHeader(e.target.value)}
              placeholder="ex : 🎄 Joyeux Noël à tous nos visiteurs !"
              rows={2}
              className="w-full px-3 py-2 rounded-lg ring-1 ring-slate-300 focus:ring-2 focus:ring-sky-400 outline-none text-sm"
              data-testid="garde-page-header-input"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Bandeau du BAS (juste avant le bloc lien/image)
            </label>
            <textarea
              value={footer}
              onChange={(e) => setFooter(e.target.value)}
              placeholder="ex : 💚 Prompt rétablissement et bonne santé !"
              rows={2}
              className="w-full px-3 py-2 rounded-lg ring-1 ring-slate-300 focus:ring-2 focus:ring-sky-400 outline-none text-sm"
              data-testid="garde-page-footer-input"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Image (capture désignant où cliquer) — URL ou téléversement
            </label>
            <div className="flex flex-col sm:flex-row gap-2">
              <input
                type="text"
                value={imageUrl}
                onChange={(e) => setImageUrl(e.target.value)}
                placeholder="https://… ou colle une URL"
                className="flex-1 px-3 py-2 rounded-lg ring-1 ring-slate-300 focus:ring-2 focus:ring-sky-400 outline-none text-xs font-mono"
                data-testid="garde-page-image-url-input"
              />
              <label className="inline-flex items-center justify-center gap-1 px-3 py-2 rounded-lg ring-1 ring-sky-300 bg-sky-50 text-sky-700 hover:bg-sky-100 cursor-pointer text-xs font-semibold">
                <Upload className="h-3 w-3" />
                Téléverser
                <input
                  type="file"
                  accept="image/*"
                  onChange={onPickImage}
                  className="hidden"
                  data-testid="garde-page-image-file"
                />
              </label>
            </div>
            <p className="text-[10px] text-slate-500 italic mt-1">
              Max 2 Mo. Sera encodée en base64 et stockée dans MongoDB settings.
            </p>
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Légende sous l&apos;image (facultative)
            </label>
            <input
              type="text"
              value={caption}
              onChange={(e) => setCaption(e.target.value)}
              placeholder="ex : Cliquez ici pour découvrir nos services"
              className="w-full px-3 py-2 rounded-lg ring-1 ring-slate-300 focus:ring-2 focus:ring-sky-400 outline-none text-sm"
              data-testid="garde-page-image-caption-input"
            />
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={save}
              disabled={saving}
              className="text-sm px-4 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-700 text-white font-semibold disabled:opacity-50"
              data-testid="garde-page-save"
            >
              {saving ? "Enregistrement…" : "💾 Enregistrer"}
            </button>
            <button
              type="button"
              onClick={reset}
              className="text-xs px-3 py-1.5 rounded-lg bg-rose-50 hover:bg-rose-100 ring-1 ring-rose-200 text-rose-700 inline-flex items-center gap-1"
              data-testid="garde-page-reset"
            >
              <RotateCcw className="h-3 w-3" /> Vider
            </button>
          </div>
        </div>

        {/* Preview */}
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">Aperçu</label>
          <div
            className="rounded-lg ring-1 ring-slate-300 bg-slate-900 p-4 space-y-3"
            data-testid="garde-page-preview"
          >
            {header && (
              <div className="rounded ring-1 ring-sky-400/30 bg-sky-400/10 p-2 text-center text-sky-200 text-sm whitespace-pre-wrap">
                {header}
              </div>
            )}
            <div className="text-white text-lg font-display">🏥 Pharmacies de garde</div>
            <div className="text-slate-300 text-xs italic">… la liste des officines apparaît ici …</div>
            {footer && (
              <div className="rounded ring-1 ring-emerald-400/30 bg-emerald-400/10 p-2 text-center text-emerald-200 text-sm whitespace-pre-wrap">
                {footer}
              </div>
            )}
            <div className="rounded ring-1 ring-white/10 bg-white/5 p-3 text-center">
              <p className="text-xs text-slate-300 mb-1">Site officiel :</p>
              <p className="text-sky-300 underline text-sm">https://sawalismartsystems.com</p>
              {imageUrl && (
                <div className="mt-3">
                  <img
                    src={imageUrl}
                    alt={caption || "Aperçu"}
                    className="mx-auto max-h-40 rounded ring-1 ring-white/10"
                    onError={(e) => { e.currentTarget.style.opacity = "0.3"; }}
                  />
                  {caption && <p className="mt-1 text-[10px] text-slate-400 italic">{caption}</p>}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
