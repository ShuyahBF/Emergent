// Iter43-fix24aq (2026-06-17) — Configurable WhatsApp command images.
//
// For every VIDAL/Liluvine `!command`, admin can attach an image (URL or
// uploaded base64). Sent as a 2nd WA message after the text reply.
//
// - `wa_default_cmd_image_url` : fallback image used when no per-command
//   override is set.
// - `wa_cmd_<id>_image_url`    : override per command id (e.g. `garde`,
//   `produits`, `adresse`, `interactions`).
//
// The list of available commands is fetched from `/admin/vidal/actions` so
// the UI stays in sync with the configurable VIDAL actions system.
import React, { useCallback, useEffect, useState } from "react";
import { Image as ImageIcon, RotateCcw, Upload } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const MAX_IMAGE_BYTES = 2_000_000;

// Hard-coded commands that exist outside vidal_actions (handled directly
// in liluvine_wa_autoreply.py: !adresse, !garde, etc.).
const BUILTIN_COMMANDS = [
  { id: "garde", label: "!garde — Officines de garde" },
  { id: "adresse", label: "!adresse — Adresse & contact" },
  { id: "horaires", label: "!horaires — Horaires d'ouverture" },
  { id: "contact", label: "!contact — Coordonnées" },
];

export default function WaCommandImagesSection() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [defaultUrl, setDefaultUrl] = useState("");
  const [defaultCaption, setDefaultCaption] = useState("");
  const [perCommand, setPerCommand] = useState({}); // {cmdId: {url, caption}}
  const [actions, setActions] = useState([]);  // VIDAL actions from API

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, a] = await Promise.all([
        apiClient.get("/admin/settings"),
        apiClient.get("/admin/vidal/actions").catch(() => ({ data: { actions: [] } })),
      ]);
      setDefaultUrl(s.data?.wa_default_cmd_image_url || "");
      setDefaultCaption(s.data?.wa_default_cmd_image_caption || "");
      // Build per-command map from settings (any keys starting with wa_cmd_)
      const pc = {};
      Object.entries(s.data || {}).forEach(([k, v]) => {
        const m = k.match(/^wa_cmd_([a-z0-9_-]+)_image_(url|caption)$/i);
        if (m) {
          const [, cmdId, field] = m;
          if (!pc[cmdId]) pc[cmdId] = { url: "", caption: "" };
          pc[cmdId][field] = v || "";
        }
      });
      setPerCommand(pc);
      setActions((a.data?.actions || []).map((x) => ({ id: x.id, label: x.label || x.id })));
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur chargement images commandes");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Build combined command list (builtins + VIDAL actions, deduplicated by id)
  const allCommands = (() => {
    const seen = new Set(BUILTIN_COMMANDS.map((c) => c.id));
    const out = [...BUILTIN_COMMANDS];
    actions.forEach((a) => {
      if (!seen.has(a.id)) {
        out.push({ id: a.id, label: `!${a.id} — ${a.label}` });
        seen.add(a.id);
      }
    });
    return out;
  })();

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        wa_default_cmd_image_url: defaultUrl || "",
        wa_default_cmd_image_caption: defaultCaption || "",
      };
      // Send each per-command field (Pydantic extra="allow" accepts them)
      Object.entries(perCommand).forEach(([cmdId, v]) => {
        payload[`wa_cmd_${cmdId}_image_url`] = v.url || "";
        payload[`wa_cmd_${cmdId}_image_caption`] = v.caption || "";
      });
      await apiClient.put("/admin/settings", payload);
      toast.success("Images des commandes WhatsApp enregistrées");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de sauvegarde");
    } finally {
      setSaving(false);
    }
  };

  const reset = () => {
    if (!window.confirm("Vider toutes les images de commandes WhatsApp ?")) return;
    setDefaultUrl("");
    setDefaultCaption("");
    setPerCommand({});
  };

  const onPickFile = (cmdId) => (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > MAX_IMAGE_BYTES) {
      toast.error("Fichier trop volumineux (max 2 Mo)");
      e.target.value = "";
      return;
    }
    const reader = new FileReader();
    reader.onload = (ev) => {
      const dataUri = String(ev.target?.result || "");
      if (cmdId === "_default") {
        setDefaultUrl(dataUri);
      } else {
        setPerCommand((prev) => ({
          ...prev,
          [cmdId]: { ...(prev[cmdId] || {}), url: dataUri },
        }));
      }
      toast.success(`Image chargée (${(file.size / 1024).toFixed(0)} Ko)`);
    };
    reader.onerror = () => toast.error("Erreur de lecture du fichier");
    reader.readAsDataURL(file);
    e.target.value = "";
  };

  if (loading) return <p className="text-sm text-slate-500 italic">Chargement…</p>;

  return (
    <section
      className="rounded-2xl ring-1 ring-pink-200 bg-gradient-to-br from-pink-50/40 via-white to-rose-50/30 p-5 space-y-4"
      data-testid="wa-cmd-images-section"
    >
      <header className="flex items-center gap-3">
        <div className="rounded-full bg-pink-100 ring-1 ring-pink-200 p-2">
          <ImageIcon className="h-5 w-5 text-pink-700" />
        </div>
        <div className="flex-1">
          <h3 className="font-display font-bold text-slate-900">
            Images jointes aux réponses WhatsApp <code className="text-pink-700">!commands</code>
          </h3>
          <p className="text-xs text-slate-500 mt-0.5">
            Pour chaque commande (<code>!garde</code>, <code>!produits</code>, etc.), une image
            (URL HTTPS ou téléversement) est envoyée en 2ème message WhatsApp après le texte.
            L&apos;image <strong>spécifique</strong> d&apos;une commande prime, sinon l&apos;image
            <strong> par défaut</strong> ci-dessous.
          </p>
        </div>
        <button
          type="button"
          onClick={reset}
          className="text-xs px-2 py-1 rounded bg-rose-50 hover:bg-rose-100 ring-1 ring-rose-200 text-rose-700 inline-flex items-center gap-1"
          data-testid="wa-cmd-images-reset"
        >
          <RotateCcw className="h-3 w-3" /> Vider
        </button>
      </header>

      {/* Default image */}
      <div className="rounded-lg bg-white ring-1 ring-pink-200 p-3 space-y-2">
        <p className="text-xs font-bold text-pink-700">
          🌍 Image PAR DÉFAUT (utilisée si une commande n&apos;a pas d&apos;image spécifique)
        </p>
        <ImageEditor
          urlValue={defaultUrl}
          captionValue={defaultCaption}
          onUrlChange={setDefaultUrl}
          onCaptionChange={setDefaultCaption}
          onPick={onPickFile("_default")}
          testIdPrefix="wa-cmd-default"
        />
      </div>

      {/* Per-command */}
      <div className="space-y-2">
        <p className="text-xs font-bold text-slate-700">
          🎯 Images spécifiques par commande ({allCommands.length} commandes connues)
        </p>
        {allCommands.map((cmd) => (
          <details
            key={cmd.id}
            className="rounded ring-1 ring-slate-200 bg-white"
            data-testid={`wa-cmd-${cmd.id}-block`}
          >
            <summary className="cursor-pointer px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">
              {cmd.label}
              {perCommand[cmd.id]?.url && (
                <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 ring-1 ring-emerald-200 font-normal">
                  ✓ configurée
                </span>
              )}
            </summary>
            <div className="px-3 py-2 border-t border-slate-100">
              <ImageEditor
                urlValue={perCommand[cmd.id]?.url || ""}
                captionValue={perCommand[cmd.id]?.caption || ""}
                onUrlChange={(v) =>
                  setPerCommand((prev) => ({ ...prev, [cmd.id]: { ...(prev[cmd.id] || {}), url: v } }))
                }
                onCaptionChange={(v) =>
                  setPerCommand((prev) => ({ ...prev, [cmd.id]: { ...(prev[cmd.id] || {}), caption: v } }))
                }
                onPick={onPickFile(cmd.id)}
                testIdPrefix={`wa-cmd-${cmd.id}`}
              />
            </div>
          </details>
        ))}
      </div>

      <button
        type="button"
        onClick={save}
        disabled={saving}
        className="text-sm px-4 py-1.5 rounded-lg bg-pink-600 hover:bg-pink-700 text-white font-semibold disabled:opacity-50"
        data-testid="wa-cmd-images-save"
      >
        {saving ? "Enregistrement…" : "💾 Enregistrer toutes les images"}
      </button>
    </section>
  );
}

function ImageEditor({ urlValue, captionValue, onUrlChange, onCaptionChange, onPick, testIdPrefix }) {
  return (
    <div className="space-y-2">
      <div className="flex flex-col sm:flex-row gap-2">
        <input
          type="text"
          value={urlValue}
          onChange={(e) => onUrlChange(e.target.value)}
          placeholder="https://… (HTTPS uniquement)"
          className="flex-1 px-3 py-1.5 rounded ring-1 ring-slate-300 focus:ring-2 focus:ring-pink-400 outline-none text-xs font-mono"
          data-testid={`${testIdPrefix}-url`}
        />
        <label className="inline-flex items-center justify-center gap-1 px-3 py-1.5 rounded ring-1 ring-pink-300 bg-pink-50 text-pink-700 hover:bg-pink-100 cursor-pointer text-xs font-semibold">
          <Upload className="h-3 w-3" /> Téléverser
          <input type="file" accept="image/*" onChange={onPick} className="hidden" data-testid={`${testIdPrefix}-file`} />
        </label>
      </div>
      <input
        type="text"
        value={captionValue}
        onChange={(e) => onCaptionChange(e.target.value)}
        placeholder="Légende (facultative)"
        className="w-full px-3 py-1.5 rounded ring-1 ring-slate-300 focus:ring-2 focus:ring-pink-400 outline-none text-xs"
        data-testid={`${testIdPrefix}-caption`}
      />
      {urlValue && (
        <img
          src={urlValue}
          alt={captionValue || "Aperçu"}
          className="max-h-24 rounded ring-1 ring-slate-200"
          onError={(e) => { e.currentTarget.style.opacity = "0.3"; }}
          data-testid={`${testIdPrefix}-preview`}
        />
      )}
    </div>
  );
}
