// Iter43-fix24ai (2026-06-17) — Configurable WhatsApp reply template for `!garde`.
//
// Two textareas (header + body template) + live preview against a sample officine.
// Syntax:
//   {field}  → plain text value of the field
//   [field]  → clickable link version (phone → digits, whatsapp → wa.me, email → mailto)
//   [latitude,longitude] → composite → Google Maps URL
// Whitespace between fields = space separator. Newline = new line in the rendered reply.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Phone, RotateCcw, ListChecks } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const DEFAULT_HEADER =
  "🏥 *Officines de garde — Semaine {week}* ({monday} au {sunday})\n*Groupe {gg}* — {count} officine{plural}";

const DEFAULT_BODY =
  "• *{name}*\n  📍 {location_hint} {city}\n  📞 [phone]\n  📍 [latitude,longitude]";

const SAMPLE_OFFICINE = {
  name: "Pharmacie WEND DENDA",
  intitule: "Pharmacie WEND DENDA",
  phone: "+22670112233",
  whatsapp: "+22670112233",
  address: "Avenue de la Liberté",
  city: "Ouagadougou",
  location_hint: "à côté de la station Total",
  latitude: 12.3686,
  longitude: -1.5275,
  email: "wend.denda@example.bf",
  contact_name: "Dr. Salia OUEDRAOGO",
};

const SAMPLE_HEADER_CTX = {
  week: 25,
  year: 2026,
  monday: "16/06",
  sunday: "22/06",
  gg: 3,
  count: 1,
  plural: "",
};

function renderHeader(template, ctx) {
  return (template || "").replace(/\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g, (m, k) => {
    return ctx[k] !== undefined ? String(ctx[k]) : m;
  });
}

function renderBody(template, o) {
  const phoneDigits = String(o.phone || "").replace(/[^\d+]/g, "");
  const waDigits = String(o.whatsapp || "").replace(/[^\d]/g, "");
  const mapsUrl = (() => {
    const lat = Number(o.latitude);
    const lng = Number(o.longitude);
    if (!isFinite(lat) || !isFinite(lng)) return "";
    return `https://maps.google.com/?q=${lat},${lng}`;
  })();
  const plain = {
    name: o.intitule || o.name || "—",
    phone: o.phone || "",
    whatsapp: o.whatsapp || "",
    address: o.address || "",
    city: o.city || "",
    location_hint: o.location_hint || "",
    email: o.email || "",
    contact_name: o.contact_name || "",
    latitude: o.latitude == null ? "" : String(o.latitude),
    longitude: o.longitude == null ? "" : String(o.longitude),
  };
  // 1. Replace [field] (link form)
  let out = (template || "").replace(/\[([^\[\]]+)\]/g, (m, key) => {
    const k = key.trim();
    if (k.includes(",")) {
      const keys = k.split(",").map((s) => s.trim());
      if (keys.length === 2 && keys.includes("latitude") && keys.includes("longitude")) {
        return mapsUrl;
      }
      return keys.map((kk) => plain[kk] || "").join(",");
    }
    if (k === "phone") return phoneDigits;
    if (k === "whatsapp") return waDigits ? `https://wa.me/${waDigits}` : "";
    if (k === "email") return o.email ? `mailto:${o.email}` : "";
    if (k === "latitude" || k === "longitude") return mapsUrl;
    return plain[k] || "";
  });
  // 2. Replace {field} (plain form)
  out = out.replace(/\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g, (m, key) => plain[key.trim()] ?? "");
  // 3. Collapse multiple spaces per line; drop empty lines
  return out
    .split("\n")
    .map((line) => line.replace(/ +/g, " ").trim())
    .filter((line) => line.length > 0)
    .join("\n");
}

const FIELD_DOCS = [
  { f: "name", h: "Nom (intitule ou name)" },
  { f: "phone", h: "Téléphone — `[phone]` = numéro tappable WA" },
  { f: "whatsapp", h: "WhatsApp — `[whatsapp]` = lien wa.me" },
  { f: "address", h: "Adresse complète" },
  { f: "city", h: "Ville" },
  { f: "location_hint", h: "Repère géo (« à côté de… »)" },
  { f: "email", h: "Email — `[email]` = mailto:" },
  { f: "contact_name", h: "Nom du responsable" },
  { f: "latitude,longitude", h: "Composite → `[latitude,longitude]` = lien Maps" },
];

export default function GardeReplyTemplateSection() {
  const [header, setHeader] = useState("");
  const [body, setBody] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/settings");
      setHeader(r.data?.garde_reply_header || "");
      setBody(r.data?.garde_reply_template || "");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur chargement template !garde");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      await apiClient.put("/admin/settings", {
        garde_reply_header: header || "",
        garde_reply_template: body || "",
      });
      toast.success("Template !garde enregistré");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de sauvegarde");
    } finally {
      setSaving(false);
    }
  };

  const resetDefaults = () => {
    if (!window.confirm("Réinitialiser le template !garde aux valeurs par défaut ?")) return;
    setHeader(DEFAULT_HEADER);
    setBody(DEFAULT_BODY);
  };

  const previewHeader = useMemo(
    () => renderHeader(header || DEFAULT_HEADER, SAMPLE_HEADER_CTX),
    [header],
  );
  const previewBody = useMemo(
    () => renderBody(body || DEFAULT_BODY, SAMPLE_OFFICINE),
    [body],
  );
  const fullPreview = `${previewHeader}\n\n${previewBody}`;

  if (loading) return <p className="text-sm text-slate-500 italic">Chargement…</p>;

  return (
    <section
      className="rounded-2xl ring-1 ring-emerald-200 bg-gradient-to-br from-emerald-50/40 via-white to-teal-50/30 p-5 space-y-4"
      data-testid="garde-reply-template-section"
    >
      <header className="flex items-center gap-3">
        <div className="rounded-full bg-emerald-100 ring-1 ring-emerald-200 p-2">
          <Phone className="h-5 w-5 text-emerald-700" />
        </div>
        <div className="flex-1">
          <h3 className="font-display font-bold text-slate-900">
            Template de réponse WhatsApp <code className="text-emerald-700">!garde</code>
          </h3>
          <p className="text-xs text-slate-500 mt-0.5">
            Personnalise le rendu envoyé aux contacts qui tapent <code className="bg-slate-100 px-1 rounded">!garde</code>{" "}
            sur ton numéro WhatsApp Business.{" "}
            <code className="bg-emerald-100 px-1 rounded">{`{champ}`}</code> = valeur texte,{" "}
            <code className="bg-emerald-100 px-1 rounded">[champ]</code> = lien cliquable.
          </p>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Editor */}
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              En-tête (header) — placeholders {`{week}`} {`{monday}`} {`{sunday}`} {`{gg}`} {`{count}`} {`{plural}`}
            </label>
            <textarea
              value={header}
              onChange={(e) => setHeader(e.target.value)}
              placeholder={DEFAULT_HEADER}
              rows={3}
              className="w-full px-3 py-2 rounded-lg ring-1 ring-slate-300 focus:ring-2 focus:ring-emerald-400 outline-none font-mono text-xs"
              data-testid="garde-reply-header-input"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Template d&apos;une officine (body) — répété pour chaque officine
            </label>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder={DEFAULT_BODY}
              rows={8}
              className="w-full px-3 py-2 rounded-lg ring-1 ring-slate-300 focus:ring-2 focus:ring-emerald-400 outline-none font-mono text-xs"
              data-testid="garde-reply-body-input"
            />
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={save}
              disabled={saving}
              className="text-sm px-4 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-semibold disabled:opacity-50"
              data-testid="garde-reply-save"
            >
              {saving ? "Enregistrement…" : "💾 Enregistrer"}
            </button>
            <button
              type="button"
              onClick={resetDefaults}
              className="text-xs px-3 py-1.5 rounded-lg bg-rose-50 hover:bg-rose-100 ring-1 ring-rose-200 text-rose-700 inline-flex items-center gap-1"
              data-testid="garde-reply-reset"
            >
              <RotateCcw className="h-3 w-3" /> Défauts
            </button>
          </div>
          {/* Field doc */}
          <details className="text-xs">
            <summary className="cursor-pointer font-semibold text-slate-700 inline-flex items-center gap-1">
              <ListChecks className="h-3 w-3" /> Champs disponibles
            </summary>
            <div className="mt-2 rounded ring-1 ring-slate-200 bg-white p-2 space-y-1 font-mono text-[11px]">
              {FIELD_DOCS.map(({ f, h }) => (
                <div key={f} className="flex items-baseline gap-2">
                  <code className="text-emerald-700 min-w-[140px]">{`{${f}}`}</code>
                  <span className="text-slate-600">{h}</span>
                </div>
              ))}
            </div>
          </details>
        </div>

        {/* Preview */}
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">
            Aperçu — données démo (1 officine fictive)
          </label>
          <pre
            className="bg-emerald-50/50 ring-1 ring-emerald-200 rounded-lg p-3 text-xs font-mono whitespace-pre-wrap break-words min-h-[200px] max-h-[400px] overflow-auto"
            data-testid="garde-reply-preview"
          >
            {fullPreview}
          </pre>
          <p className="text-[10px] text-slate-500 italic mt-1">
            WhatsApp transforme automatiquement les numéros en boutons tappables et les URLs
            en aperçus. <code>*texte*</code> est affiché en <strong>gras</strong>,{" "}
            <code>_texte_</code> en <em>italique</em>.
          </p>
        </div>
      </div>
    </section>
  );
}
