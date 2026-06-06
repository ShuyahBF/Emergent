// S057 Day 3+ (2026-02) — Section unique d'habillage complet
// Pliable en 3 groupes : Sidebar, Login, Blocs publics.
// Preview modal avec aperçu en direct (sans sauvegarder).
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Loader2, Save, Eye, X, Paintbrush, LayoutDashboard, LogIn, Image as ImageIcon, ChevronDown, ChevronRight } from "lucide-react";

const BLOCKS = [
  { key: "hero", label: "Accueil (Hero)" },
  { key: "missions", label: "Missions" },
  { key: "specialisations", label: "Spécialisations" },
  { key: "experience", label: "Expérience / Études de cas" },
  { key: "about", label: "À propos" },
];

const DEFAULTS = {
  sidebar_bg_color: "#0E1F3D",
  sidebar_text_color: "#FFFFFF",
  sidebar_accent_color: "#1E90FF",
  login_bg_color: "#F8FAFC",
  login_text_color: "#FFFFFF",
  login_card_bg: "#FFFFFF",
  login_card_text_color: "#0F172A",
  login_button_bg: "#1E90FF",
  login_button_text_color: "#FFFFFF",
};

function ColorField({ label, value, onChange, testid }) {
  return (
    <label className="block text-xs">
      <span className="block text-slate-600 mb-1">{label}</span>
      <div className="flex items-center gap-2">
        <input
          type="color"
          value={value || "#000000"}
          onChange={(e) => onChange(e.target.value)}
          className="h-7 w-12 rounded ring-1 ring-slate-300 cursor-pointer"
          data-testid={testid}
        />
        <input
          type="text"
          value={value || ""}
          onChange={(e) => onChange(e.target.value)}
          placeholder="#RRGGBB"
          className="flex-1 text-xs px-2 py-1 rounded ring-1 ring-slate-300 font-mono"
        />
        {value && (
          <button type="button" onClick={() => onChange(null)} className="text-[10px] text-rose-500 hover:text-rose-700">✕</button>
        )}
      </div>
    </label>
  );
}

function Group({ title, icon: Icon, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="ring-1 ring-slate-200 rounded-lg bg-white" data-testid={`s057-group-${title.toLowerCase().replace(/\s+/g, "-")}`}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-3 py-2 text-sm font-semibold text-slate-800 hover:bg-slate-50"
      >
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        <Icon className="h-4 w-4 text-fuchsia-600" />
        {title}
      </button>
      {open && <div className="px-4 pb-4 pt-1 space-y-3 border-t border-slate-100">{children}</div>}
    </div>
  );
}

export default function S057ThemingSection() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [form, setForm] = useState({});

  const load = async () => {
    let next;
    try {
      const r = await apiClient.get("/admin/settings");
      next = {
        sidebar_bg_color: r.data?.sidebar_bg_color || "",
        sidebar_text_color: r.data?.sidebar_text_color || "",
        sidebar_accent_color: r.data?.sidebar_accent_color || "",
        login_bg_mode: r.data?.login_bg_mode || "default",
        login_bg_color: r.data?.login_bg_color || "",
        login_bg_image_url: r.data?.login_bg_image_url || "",
        login_text_color: r.data?.login_text_color || "",
        login_card_bg: r.data?.login_card_bg || "",
        login_card_text_color: r.data?.login_card_text_color || "",
        login_button_bg: r.data?.login_button_bg || "",
        login_button_text_color: r.data?.login_button_text_color || "",
        public_blocks_theme: r.data?.public_blocks_theme || {},
      };
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
    // Defer setState to next tick — keeps the eslint hooks rule happy and
    // gives React a clean batched update.
    setTimeout(() => {
      if (next) setForm(next);
      setLoading(false);
    }, 0);
  };

  useEffect(() => { load(); }, []);

  const setField = (k, v) => setForm((s) => ({ ...s, [k]: v || null }));
  const updateBlock = (block, k, v) => {
    setForm((s) => ({
      ...s,
      public_blocks_theme: {
        ...(s.public_blocks_theme || {}),
        [block]: { ...((s.public_blocks_theme || {})[block] || {}), [k]: v || undefined },
      },
    }));
  };

  const save = async () => {
    setSaving(true);
    try {
      await apiClient.put("/admin/settings", form);
      toast.success("Habillage enregistré (rafraîchissez l'onglet pour voir l'effet)");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
    setTimeout(() => setSaving(false), 0);
  };

  if (loading) return (<div className="flex items-center gap-2 text-sm text-slate-600 py-4"><Loader2 className="h-4 w-4 animate-spin" /> Chargement…</div>);

  return (
    <div className="space-y-3" data-testid="s057-theming-section">
      <p className="text-xs text-slate-600">
        Personnalisez l&apos;apparence : <strong>Sidebar</strong> (couleurs portail), <strong>Login</strong> (page publique d&apos;accueil)
        et <strong>Blocs publics</strong> (chacun peut overrider l&apos;arrière-plan + texte). Les valeurs vides reviennent au défaut SAWALI.
      </p>

      <div className="flex justify-end gap-2">
        <button onClick={() => setPreviewOpen(true)} className="text-xs px-3 py-1.5 rounded ring-1 ring-slate-300 hover:bg-slate-50 inline-flex items-center gap-1" data-testid="s057-preview-btn">
          <Eye className="h-3 w-3" /> Aperçu (sans sauver)
        </button>
        <button onClick={save} disabled={saving} className="text-xs px-3 py-1.5 rounded bg-fuchsia-600 hover:bg-fuchsia-700 text-white inline-flex items-center gap-1 disabled:opacity-60" data-testid="s057-save-btn">
          {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />} Enregistrer
        </button>
      </div>

      <Group title="Sidebar du portail" icon={LayoutDashboard} defaultOpen>
        <div className="grid sm:grid-cols-3 gap-3">
          <ColorField label="Fond" value={form.sidebar_bg_color} onChange={(v) => setField("sidebar_bg_color", v)} testid="s057-sidebar-bg" />
          <ColorField label="Texte" value={form.sidebar_text_color} onChange={(v) => setField("sidebar_text_color", v)} testid="s057-sidebar-text" />
          <ColorField label="Accent (lien actif)" value={form.sidebar_accent_color} onChange={(v) => setField("sidebar_accent_color", v)} testid="s057-sidebar-accent" />
        </div>
        <p className="text-[10px] text-slate-500 italic">
          Défaut : fond <code>{DEFAULTS.sidebar_bg_color}</code>, texte <code>{DEFAULTS.sidebar_text_color}</code>, accent <code>{DEFAULTS.sidebar_accent_color}</code>.
        </p>
      </Group>

      <Group title="Page de connexion (/login)" icon={LogIn}>
        <div className="grid sm:grid-cols-2 gap-3">
          <ColorField label="Fond" value={form.login_bg_color} onChange={(v) => setField("login_bg_color", v)} testid="s057-login-bg" />
          <ColorField label="Texte côté gauche (slogan)" value={form.login_text_color} onChange={(v) => setField("login_text_color", v)} testid="s057-login-text" />
          <ColorField label="Fond carte connexion" value={form.login_card_bg} onChange={(v) => setField("login_card_bg", v)} testid="s057-login-card-bg" />
          <ColorField label="Texte carte" value={form.login_card_text_color} onChange={(v) => setField("login_card_text_color", v)} testid="s057-login-card-text" />
          <ColorField label="Bouton (fond)" value={form.login_button_bg} onChange={(v) => setField("login_button_bg", v)} testid="s057-login-btn-bg" />
          <ColorField label="Bouton (texte)" value={form.login_button_text_color} onChange={(v) => setField("login_button_text_color", v)} testid="s057-login-btn-text" />
        </div>
        <label className="block text-xs mt-2">
          <span className="block text-slate-600 mb-1">Image de fond (URL — fallback couleur)</span>
          <input type="text" value={form.login_bg_image_url || ""} onChange={(e) => setField("login_bg_image_url", e.target.value)}
                 placeholder="https://…/login-bg.webp"
                 className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono"
                 data-testid="s057-login-bg-image-url" />
        </label>
      </Group>

      <Group title="Blocs publics (page d'accueil)" icon={Paintbrush}>
        <p className="text-[10px] text-slate-500 italic mb-2">
          Pour chaque bloc, vous pouvez choisir un fond + une couleur de texte différents.
          Si laissé vide, le défaut global s&apos;applique.
        </p>
        {BLOCKS.map((b) => {
          const cfg = (form.public_blocks_theme || {})[b.key] || {};
          return (
            <div key={b.key} className="grid sm:grid-cols-3 gap-3 items-end py-2 border-b border-slate-100 last:border-0" data-testid={`s057-block-${b.key}`}>
              <div className="text-xs font-semibold text-slate-700">{b.label}</div>
              <ColorField label="Fond" value={cfg.bg_color || ""} onChange={(v) => updateBlock(b.key, "bg_color", v)} testid={`s057-block-${b.key}-bg`} />
              <ColorField label="Texte" value={cfg.text_color || ""} onChange={(v) => updateBlock(b.key, "text_color", v)} testid={`s057-block-${b.key}-text`} />
            </div>
          );
        })}
      </Group>

      {previewOpen && <PreviewModal form={form} onClose={() => setPreviewOpen(false)} />}
    </div>
  );
}

function PreviewModal({ form, onClose }) {
  const blocks = form.public_blocks_theme || {};
  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" data-testid="s057-preview-modal">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-5xl max-h-[90vh] overflow-y-auto p-5 space-y-4">
        <div className="flex items-center justify-between sticky top-0 bg-white pb-2 border-b border-slate-100">
          <h2 className="font-semibold text-slate-800 inline-flex items-center gap-2"><Eye className="h-4 w-4" /> Aperçu (non sauvegardé)</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700"><X className="h-4 w-4" /></button>
        </div>

        {/* Sidebar preview */}
        <div>
          <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-1">Sidebar</h3>
          <div className="flex gap-3 ring-1 ring-slate-200 rounded-lg overflow-hidden h-40">
            <div className="w-40 p-3 text-xs" style={{
              background: form.sidebar_bg_color || DEFAULTS.sidebar_bg_color,
              color: form.sidebar_text_color || DEFAULTS.sidebar_text_color,
            }}>
              <div className="font-bold mb-2">SAWALI</div>
              <div className="space-y-1">
                <div className="px-2 py-1 rounded" style={{ background: form.sidebar_accent_color || DEFAULTS.sidebar_accent_color, color: "#fff" }}>Dashboard</div>
                <div className="px-2 py-1 rounded opacity-80">Contacts</div>
                <div className="px-2 py-1 rounded opacity-80">Tickets</div>
              </div>
            </div>
            <div className="flex-1 bg-slate-50 p-3 text-xs text-slate-500 italic">Zone de contenu</div>
          </div>
        </div>

        {/* Login preview */}
        <div>
          <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-1">Login</h3>
          <div className="grid grid-cols-2 ring-1 ring-slate-200 rounded-lg overflow-hidden h-48">
            <div className="p-4 flex flex-col justify-end" style={{
              background: form.login_bg_color || "#081226",
              color: form.login_text_color || "#FFFFFF",
            }}>
              <h4 className="font-bold">Bienvenue Loois</h4>
              <p className="text-[10px] opacity-80">Accédez à votre espace.</p>
            </div>
            <div className="p-3 flex items-center justify-center bg-slate-50">
              <div className="rounded-lg p-3 w-full max-w-[200px] ring-1 ring-slate-200" style={{
                background: form.login_card_bg || "#FFFFFF",
                color: form.login_card_text_color || "#0F172A",
              }}>
                <p className="text-[10px] font-semibold mb-2">Connexion</p>
                <div className="text-[10px] mb-1 ring-1 ring-slate-200 px-1.5 py-1 rounded">demo@…</div>
                <div className="text-[10px] mb-2 ring-1 ring-slate-200 px-1.5 py-1 rounded">••••••</div>
                <button className="w-full text-[10px] px-2 py-1.5 rounded" style={{
                  background: form.login_button_bg || "#1E90FF",
                  color: form.login_button_text_color || "#FFFFFF",
                }}>Se connecter</button>
              </div>
            </div>
          </div>
        </div>

        {/* Public blocks preview */}
        <div>
          <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-1">Blocs publics</h3>
          <div className="space-y-2">
            {BLOCKS.map((b) => {
              const cfg = blocks[b.key] || {};
              return (
                <div key={b.key} className="rounded-lg p-3 ring-1 ring-slate-200" style={{
                  background: cfg.bg_color || "#0a1730",
                  color: cfg.text_color || "#FFFFFF",
                }} data-testid={`s057-preview-block-${b.key}`}>
                  <div className="font-bold text-sm">{b.label}</div>
                  <div className="text-[10px] opacity-80">Aperçu du contenu de ce bloc.</div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="flex justify-end sticky bottom-0 bg-white pt-2 border-t border-slate-100">
          <button onClick={onClose} className="text-xs px-3 py-1.5 rounded ring-1 ring-slate-300 hover:bg-slate-50">Fermer</button>
        </div>
      </div>
    </div>
  );
}
