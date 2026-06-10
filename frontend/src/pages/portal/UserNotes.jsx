import React, { useEffect, useMemo, useRef, useState } from "react";
import { useParams, Navigate } from "react-router-dom";
import { apiClient } from "@/lib/api";
import {
  Plus, Edit, Trash2, X, FileText, ClipboardList, ImagePlus, Star, Lock, Calendar as CalIcon, Paperclip,
  Bold, Italic, Underline, Strikethrough,
  Heading2, Heading3, List, ListOrdered, Quote,
  AlignLeft, AlignCenter, AlignRight,
  Link as LinkIcon, Undo2, Redo2, Eraser, Code,
  Mic, Square, MessageCircle, Loader2, Megaphone, Eye,
} from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import { getFileIcon } from "@/lib/fileIcons";
import TenantSharingToggle from "@/components/TenantSharingToggle";

const KIND_META = {
  reports: { label: "Rapports", singular: "rapport", icon: FileText, accent: "#1E90FF" },
  suivis: { label: "Suivis", singular: "suivi", icon: ClipboardList, accent: "#10B981" },
  // Iter35g — personal Notes & Tasks (same UX as reports/suivis, voice + transcription inherited)
  notes: { label: "Notes", singular: "note", icon: FileText, accent: "#A855F7" },
  tasks: { label: "Tâches", singular: "tâche", icon: ClipboardList, accent: "#F59E0B" },
};

const empty = { title: "", content_html: "", tags: [], client_id: "", event_date: "", images: [], is_private: false, target_user_ids: [], task_items: [], shared_with_tenant: false, editable_by_tenant: false };

const ELEVATED_TRACKED = new Set(["Moderation", "Administrateur", "Superviseur"]);
const ADMIN_LEVEL_TRACKED = new Set(["Administrateur", "Superviseur"]);

function isElevated(user) {
  if (!user) return false;
  if (user.role === "admin" || user.role === "superviseur") return true;
  return ELEVATED_TRACKED.has(user.tracked_role);
}
function canDeleteOrRate(user) {
  if (!user) return false;
  if (user.role === "admin" || user.role === "superviseur") return true;
  return ADMIN_LEVEL_TRACKED.has(user.tracked_role);
}
function isLockedForEdit(note, user) {
  if (!note?.created_at) return false;
  if (user?.role === "admin" || user?.role === "superviseur") return false;
  const created = new Date(note.created_at).getTime();
  return Date.now() > created + 3600 * 1000;
}

export default function UserNotesPage() {
  const { kind } = useParams();
  const { user } = useAuth();
  const meta = KIND_META[kind];
  const [items, setItems] = useState([]);
  const [authors, setAuthors] = useState([]);
  const [filterAuthor, setFilterAuthor] = useState("");
  const [filterQ, setFilterQ] = useState("");
  // Iter34y — Filtre par client lié pour les Suivis
  const [filterClient, setFilterClient] = useState("");
  const [clients, setClients] = useState([]);
  const [isOpen, setIsOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(empty);
  const [busy, setBusy] = useState(false);
  const [activeImage, setActiveImage] = useState(null);

  const elevated = isElevated(user);
  const canDelete = canDeleteOrRate(user);
  // Iter38r-fix9f — Tasks/Notes ouverts à tous ; Rapports/Suivis seulement aux profils élevés.
  const canCreate = (kind === "notes" || kind === "tasks") || elevated;
  // Iter38r-fix9h — Honor ?scope=...  URL param so the welcome briefing can deep-link
  const [scope, setScope] = useState(() => {
    try {
      const p = new URLSearchParams(window.location.search).get("scope");
      return ["mine", "shared", "all"].includes(p) ? p : "all";
    } catch { return "all"; }
  });
  // Iter38r-fix9f — Read-only viewer modal (eye icon for items I can't edit)
  const [viewing, setViewing] = useState(null);
  // Iter38r-fix9k — Strict mode for tasks (admin-configurable)
  const [strictTasksOnly, setStrictTasksOnly] = useState(false);

  const load = () => apiClient.get(`/me/notes/${kind}`, {
    params: {
      author: filterAuthor || undefined,
      q: filterQ || undefined,
      scope: scope !== "all" ? scope : undefined,
    },
  }).then((r) => setItems(r.data)).catch(() => {});
  const [smartFeatures, setSmartFeatures] = useState({ ai: true });
  // Iter35m — Targets dropdown for private notes/tasks
  const [targets, setTargets] = useState([]);
  // Iter34y — Filtre client appliqué côté front (l'API ne le supporte pas pour les suivis).
  const filteredItems = useMemo(() => {
    if (!filterClient) return items;
    return items.filter((it) => it.client_id === filterClient);
  }, [items, filterClient]);
  useEffect(() => {
    if (!meta) return;
    load();
    apiClient.get(`/me/notes/${kind}/authors`).then((r) => setAuthors(r.data)).catch(() => {});
    apiClient.get("/me/features").then((r) => setSmartFeatures(r.data?.features || {})).catch(() => {});
    apiClient.get("/me/notes-targets").then((r) => setTargets(r.data?.items || [])).catch(() => {});
    // Iter38r-fix9k — Detect strict tasks mode (tenant-level setting via /me/features)
    apiClient.get("/me/features").then((r) => {
      const f = r.data?.features || {};
      if (f.notes_strict_tasks_only !== undefined) setStrictTasksOnly(!!f.notes_strict_tasks_only);
    }).catch(() => {});
    if (kind === "suivis") {
      apiClient.get("/me/clients").then((r) => setClients(r.data)).catch(() => {});
    }
    // eslint-disable-next-line
  }, [kind]);

  if (!meta) return <Navigate to="/portal" replace />;

  const open = (it = null) => {
    setEditing(it);
    setForm(it ? {
      ...empty,
      ...it,
      tags: it.tags || [],
      images: it.images || [],
      target_user_ids: it.target_user_ids || [],
      task_items: it.task_items || [],
      event_date: it.event_date ? it.event_date.slice(0, 16) : "",
    } : empty);
    setIsOpen(true);
  };
  const close = () => { setIsOpen(false); setEditing(null); setForm(empty); };

  const submit = async (e) => {
    e.preventDefault();
    if (!form.title.trim()) { toast.error("Titre requis"); return; }
    if (kind === "suivis") {
      if (!form.client_id) { toast.error("Client requis pour un suivi"); return; }
      if (!form.event_date) { toast.error("Date de l'événement requise pour un suivi"); return; }
    }
    setBusy(true);
    try {
      const payload = {
        title: form.title,
        content_html: form.content_html,
        tags: form.tags,
        images: form.images,
        is_private: !!form.is_private,
        // Iter35m — Only honored when is_private=true; allows the author to
        // restrict visibility to a specific subset of tracked users / admins.
        target_user_ids: form.is_private ? (form.target_user_ids || []) : [],
        // Iter43 — Cross-tenant share (société + rattachement)
        shared_with_tenant: !!form.shared_with_tenant,
        editable_by_tenant: !!form.editable_by_tenant,
        // Iter38r-fix9k — Checklist items for kind=tasks (Google Keep style)
        ...(kind === "tasks" && form.task_items?.length > 0 ? { task_items: form.task_items } : {}),
        ...(kind === "suivis" ? { client_id: form.client_id, event_date: new Date(form.event_date).toISOString() } : {}),
      };
      if (editing?.id) await apiClient.put(`/me/notes/${kind}/${editing.id}`, payload);
      else await apiClient.post(`/me/notes/${kind}`, payload);
      toast.success("Enregistré"); close(); await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setBusy(false); }
  };

  const del = async (id) => {
    if (!window.confirm("Supprimer cette note ?")) return;
    try {
      await apiClient.delete(`/me/notes/${kind}/${id}`);
      toast.success("Supprimée"); await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const Icon = meta.icon;

  return (
    <div className="space-y-6" data-testid={`notes-${kind}-page`}>
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2">
            <Icon className="h-6 w-6" style={{ color: meta.accent }} /> Mes {meta.label}
          </h1>
          <p className="text-sm text-slate-500">
            {kind === "suivis"
              ? "Saisissez et conservez vos suivis (date + client requis). Numéro auto, IP enregistrée. Verrouillage après 1h."
              : "Vos rapports sont horodatés automatiquement. Numéro auto. Édition limitée à 1h après création."}
          </p>
        </div>
        {canCreate && (
          <button
            onClick={() => open()}
            className="inline-flex items-center gap-2 rounded-lg text-white px-4 py-2 text-sm hover:opacity-90"
            style={{ background: meta.accent }}
            data-testid={`new-${kind}-btn`}
          >
            <Plus className="h-4 w-4" /> Nouveau {meta.singular}
          </button>
        )}
      </div>

      {!canCreate && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          La création de {meta.label.toLowerCase()} est réservée aux rôles <strong>Modération</strong>, <strong>Administrateur</strong> ou <strong>Superviseur</strong>.
        </div>
      )}

      {/* Iter38r-fix9f — Scope tabs (Tous / Mes / Partagés avec moi) */}
      <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-1 inline-flex" data-testid={`notes-scope-tabs-${kind}`}>
        {[
          { id: "all", label: "Tous" },
          { id: "mine", label: "Les miens" },
          { id: "shared", label: "📥 Partagés avec moi" },
        ].map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => { setScope(tab.id); setTimeout(load, 0); }}
            className={`text-xs px-3 py-1.5 rounded-md transition ${scope === tab.id ? "bg-white shadow-sm font-medium text-slate-900" : "text-slate-600 hover:text-slate-900"}`}
            data-testid={`notes-scope-${tab.id}`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <form onSubmit={(e) => { e.preventDefault(); load(); }} className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white p-3" data-testid={`notes-filters-${kind}`}>
        <select
          value={filterAuthor}
          onChange={(e) => { setFilterAuthor(e.target.value); setTimeout(load, 0); }}
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm bg-white"
          data-testid="notes-filter-author"
        >
          <option value="">Tous les auteurs</option>
          {authors.map((a) => <option key={a.email} value={a.email}>{a.name || a.email} ({a.count})</option>)}
        </select>
        <div className="flex-1 min-w-[200px] relative">
          <input
            value={filterQ}
            onChange={(e) => setFilterQ(e.target.value)}
            placeholder="Recherche dans titre, contenu, numéro, tags…"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-sawali-blue focus:outline-none"
            data-testid="notes-filter-q"
          />
        </div>
        {kind === "suivis" && clients.length > 0 && (
          <select
            value={filterClient}
            onChange={(e) => setFilterClient(e.target.value)}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm bg-white"
            data-testid="notes-filter-client"
            title="Filtrer par Client lié"
          >
            <option value="">Tous les clients liés</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>{c.full_name || c.company} ({items.filter((it) => it.client_id === c.id).length})</option>
            ))}
          </select>
        )}
        <button type="submit" className="rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light" data-testid="notes-filter-apply">Filtrer</button>
        {(filterAuthor || filterQ || filterClient) && (
          <button type="button" onClick={() => { setFilterAuthor(""); setFilterQ(""); setFilterClient(""); setTimeout(load, 0); }} className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-600 hover:border-rose-300 hover:text-rose-600" data-testid="notes-filter-clear">Effacer</button>
        )}
        <span className="text-xs text-slate-500 ml-auto">{filteredItems.length} résultat{filteredItems.length > 1 ? "s" : ""}{filterClient ? " (filtré)" : ""}</span>
      </form>

      {filteredItems.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 p-12 text-center text-slate-500" data-testid={`empty-${kind}`}>
          Aucun {meta.singular} encore enregistré.
        </div>
      ) : (
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredItems.map((n) => (
            <NoteCard
              key={n.id}
              n={n}
              kind={kind}
              meta={meta}
              user={user}
              canDelete={canDelete}
              clients={clients}
              onEdit={() => open(n)}
              onView={() => setViewing(n)}
              onDelete={() => del(n.id)}
              onRefresh={load}
              onImage={(img) => setActiveImage(img)}
            />
          ))}
        </div>
      )}

      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={close}>
          <div className="bg-white rounded-xl w-full max-w-3xl max-h-[92vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="font-display font-semibold">
                {editing?.id ? "Modifier" : "Nouveau"} {meta.singular}
              </h3>
              <button onClick={close} aria-label="Fermer"><X className="h-4 w-4" /></button>
            </div>
            <form onSubmit={submit} className="p-4 space-y-3" data-testid="note-form">
              <div>
                <label className="block text-xs font-semibold mb-1">Titre *</label>
                <input
                  required
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-sawali-blue focus:outline-none"
                  data-testid="note-title-input"
                />
              </div>

              {kind === "suivis" && (
                <div className="grid sm:grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-semibold mb-1">Client concerné *</label>
                    <select
                      required
                      value={form.client_id}
                      onChange={(e) => setForm({ ...form, client_id: e.target.value })}
                      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                      data-testid="note-client-select"
                    >
                      <option value="">— Sélectionner —</option>
                      {clients.map((c) => <option key={c.id} value={c.id}>{c.full_name}{c.company ? ` — ${c.company}` : ""}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-semibold mb-1">Date & heure de l'événement *</label>
                    <input
                      type="datetime-local"
                      required
                      value={form.event_date}
                      onChange={(e) => setForm({ ...form, event_date: e.target.value })}
                      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                      data-testid="note-event-date"
                    />
                  </div>
                </div>
              )}

              {/* Iter38r-fix9k — Checklist (Google Keep) for kind=tasks */}
              {kind === "tasks" && (
                <TaskChecklist
                  items={form.task_items || []}
                  onChange={(items) => setForm((f) => ({ ...f, task_items: items }))}
                  accent={meta.accent}
                />
              )}

              {/* Rich content editor — hidden when strict tasks mode is enabled */}
              {!(kind === "tasks" && strictTasksOnly) && (
              <div>
                <label className="block text-xs font-semibold mb-1">{kind === "tasks" ? "Note libre (facultatif)" : "Contenu"}</label>
                <p className="text-[11px] text-slate-500 mb-2 inline-flex items-center gap-1">
                  <Mic className="h-3 w-3" /> Astuce : cliquez sur l'icône <strong>micro</strong> en haut à droite de la barre d'outils pour dicter votre {meta.singular} (transcription Whisper).
                </p>
                <RichEditor
                  value={form.content_html}
                  onChange={(v) => setForm({ ...form, content_html: v })}
                  accent={meta.accent}
                  aiEnabled={smartFeatures.ai !== false}
                />
              </div>
              )}

              {/* WhatsApp picker — append selected messages to the body */}
              <WaMessagesPicker
                clientId={kind === "suivis" ? form.client_id : null}
                onAppend={(html) => setForm((f) => ({ ...f, content_html: (f.content_html || "") + html }))}
                accent={meta.accent}
              />

              <ImageUploader images={form.images} onChange={(images) => setForm({ ...form, images })} accent={meta.accent} />

              <TenantSharingToggle
                shared={form.shared_with_tenant}
                editable={form.editable_by_tenant}
                onChange={(next) => setForm((s) => ({ ...s, ...next }))}
                testidPrefix={`note-tenant-sharing-${kind}`}
              />

              <label className="flex items-start gap-3 rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3 cursor-pointer hover:bg-slate-100 transition" data-testid="note-privacy-toggle-wrapper">
                <input
                  type="checkbox"
                  checked={!!form.is_private}
                  onChange={(e) => setForm({ ...form, is_private: e.target.checked, target_user_ids: e.target.checked ? form.target_user_ids : [] })}
                  className="mt-0.5 h-4 w-4 rounded border-slate-300"
                  data-testid="note-privacy-toggle"
                />
                <span className="flex-1">
                  <span className="block text-sm font-semibold text-slate-800 inline-flex items-center gap-1">
                    <Lock className="h-3.5 w-3.5 text-slate-500" /> Note privée
                  </span>
                  <span className="block text-xs text-slate-500 mt-0.5">
                    Décochée (public) : visible par tous les utilisateurs du client lié.
                    Cochée (privée) : visible par vous, les administrateurs/superviseurs, et — si vous le précisez ci-dessous — par un ou plusieurs utilisateurs ciblés.
                  </span>
                </span>
              </label>

              {/* Iter35m — Multi-select des destinataires quand la note est privée */}
              {form.is_private && targets.length > 0 && (
                <div className="rounded-lg ring-1 ring-fuchsia-200 bg-fuchsia-50/50 p-3 space-y-2" data-testid="note-targets-wrapper">
                  <p className="text-xs font-semibold text-fuchsia-900 inline-flex items-center gap-1.5">
                    <Lock className="h-3.5 w-3.5" /> Adressé à (optionnel)
                  </p>
                  <p className="text-[11px] text-fuchsia-700/80">
                    Sélectionnez les utilisateurs qui pourront voir cette note en plus de vous et des administrateurs. Laissez vide pour la garder strictement personnelle.
                  </p>
                  <div className="grid sm:grid-cols-2 gap-1.5 max-h-44 overflow-y-auto pr-1">
                    {targets.map((t) => {
                      const checked = (form.target_user_ids || []).includes(t.id);
                      return (
                        <label
                          key={t.id}
                          className={`flex items-center gap-2 rounded px-2 py-1.5 text-xs ring-1 transition cursor-pointer ${
                            checked ? "bg-fuchsia-100 ring-fuchsia-300 text-fuchsia-900" : "bg-white ring-slate-200 hover:bg-fuchsia-50"
                          }`}
                          data-testid={`note-target-${t.id}`}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(e) => {
                              const cur = new Set(form.target_user_ids || []);
                              if (e.target.checked) cur.add(t.id); else cur.delete(t.id);
                              setForm({ ...form, target_user_ids: Array.from(cur) });
                            }}
                            className="h-3.5 w-3.5"
                          />
                          <span className="flex-1 truncate">
                            {t.is_self ? <strong className="text-fuchsia-900">Moi-même</strong> : t.full_name}
                            {t.role && !t.is_self && <span className="text-[10px] text-slate-500 ml-1">({t.role})</span>}
                          </span>
                        </label>
                      );
                    })}
                  </div>
                  <p className="text-[10px] text-fuchsia-700/70">
                    {form.target_user_ids?.length || 0} destinataire(s) sélectionné(s)
                  </p>
                </div>
              )}

              <button
                type="submit"
                disabled={busy}
                className="w-full rounded-lg text-white px-4 py-2 text-sm hover:opacity-90 disabled:opacity-50"
                style={{ background: meta.accent }}
                data-testid="save-note-btn"
              >
                {busy ? "Enregistrement..." : "Enregistrer"}
              </button>
            </form>
          </div>
        </div>
      )}

      {activeImage && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/85" onClick={() => setActiveImage(null)}>
          <img src={activeImage} alt="" className="max-h-[90vh] max-w-[95vw] rounded-lg" onClick={(e) => e.stopPropagation()} />
        </div>
      )}

      {/* Iter38r-fix9f — Read-only viewer modal for shared items */}
      {viewing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={() => setViewing(null)}>
          <div className="bg-white rounded-xl w-full max-w-3xl max-h-[92vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b">
              <div>
                <h3 className="font-display font-semibold flex items-center gap-2">
                  <Eye className="h-4 w-4 text-slate-500" /> {viewing.title}
                </h3>
                <p className="text-[10px] uppercase tracking-widest font-mono text-slate-500 mt-0.5">
                  {viewing.numero || "—"} · partagé par {viewing.owner_name || (viewing.owner_email || "").split("@")[0]}
                </p>
              </div>
              <button onClick={() => setViewing(null)} aria-label="Fermer" data-testid="view-note-close"><X className="h-4 w-4" /></button>
            </div>
            <div className="p-5 space-y-3">
              {viewing.tags?.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {viewing.tags.map((t) => <span key={t} className="text-[10px] rounded bg-slate-100 px-1.5 py-0.5">#{t}</span>)}
                </div>
              )}
              <div className="prose prose-sm prose-sawali max-w-none" dangerouslySetInnerHTML={{ __html: viewing.content_html || "<p class=\"text-slate-400 italic\">Aucun contenu</p>" }} />
              {/* S-iter39b — Render task_items when viewing a 'tasks' note
                  (legacy text content_html was empty, the items lived in
                  viewing.task_items[]) so the eye-icon modal is no longer blank. */}
              {Array.isArray(viewing.task_items) && viewing.task_items.length > 0 && (
                <div className="mt-3 space-y-1.5 rounded-lg ring-1 ring-amber-200 bg-amber-50/40 p-3" data-testid="view-note-task-items">
                  <p className="text-[11px] uppercase tracking-widest font-semibold text-amber-800 mb-1">
                    Checklist ({viewing.task_items.filter((x) => x.done).length}/{viewing.task_items.length} faite{viewing.task_items.length > 1 ? "s" : ""})
                  </p>
                  {[...viewing.task_items].sort((a, b) => (a.order || 0) - (b.order || 0)).map((it) => (
                    <div key={it.id || it.text} className={`text-sm flex items-start gap-2 ${it.done ? "text-slate-400 line-through" : "text-slate-800"}`}>
                      <span className={`mt-0.5 inline-flex items-center justify-center h-4 w-4 rounded ring-1 ${it.done ? "bg-emerald-500 ring-emerald-600 text-white" : "ring-slate-300 bg-white"} shrink-0`}>
                        {it.done && <span className="text-[10px] leading-3">✓</span>}
                      </span>
                      <span className="flex-1">{it.text}</span>
                    </div>
                  ))}
                </div>
              )}
              {viewing.images?.length > 0 && (
                <div className="grid grid-cols-3 gap-2">
                  {viewing.images.map((im, i) => (
                    <button key={i} onClick={() => setActiveImage(absoluteImg(im.url))} className="aspect-square overflow-hidden rounded-lg ring-1 ring-slate-200 hover:ring-sawali-blue">
                      <img src={absoluteImg(im.url)} alt="" className="w-full h-full object-cover" />
                    </button>
                  ))}
                </div>
              )}
              <p className="text-[11px] text-slate-400 pt-2 border-t border-slate-100">
                Créé le {new Date(viewing.created_at).toLocaleString("fr-FR", { dateStyle: "long", timeStyle: "short" })}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ====================================================================
// Note card with rating UI
// ====================================================================
function NoteCard({ n, kind, meta, user, canDelete, clients, onEdit, onView, onDelete, onRefresh, onImage }) {
  const locked = isLockedForEdit(n, user);
  const clientName = useMemo(() => clients.find((c) => c.id === n.client_id)?.full_name || n.client_id, [clients, n.client_id]);
  // Iter38r-fix9f — Read-only mode when current user is not the owner
  const isOwner = n.owner_id === user?.id;
  const isAdmin = user?.role === "admin" || user?.role === "superviseur";
  const readOnly = !isOwner && !isAdmin;
  const sharedReason = !isOwner
    ? (n.target_user_ids?.includes(user?.id) ? "Adressé à vous" : !n.is_private ? "Public dans le tenant" : null)
    : null;

  const setRating = async (stars) => {
    try {
      await apiClient.post(`/me/ratings/${kind}/${n.id}`, { stars });
      toast.success(`Note ${stars}/5 enregistrée`);
      await onRefresh();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };
  const clearRating = async () => {
    try {
      await apiClient.delete(`/me/ratings/${kind}/${n.id}`);
      await onRefresh();
    } catch (err) { toast.error("Erreur"); }
  };

  return (
    <article className="rounded-xl border border-slate-200 bg-white p-5 hover:border-sawali-blue/40 transition flex flex-col" data-testid={`note-${n.id}`}>
      <div className="flex items-center justify-between gap-2 mb-2">
        <span className="text-[10px] uppercase tracking-widest font-mono text-slate-500">{n.numero || "—"}</span>
        <span className="flex items-center gap-1.5">
          {sharedReason && (
            <span className="inline-flex items-center gap-1 text-[10px] text-emerald-700 bg-emerald-50 ring-1 ring-emerald-200 px-1.5 py-0.5 rounded" title={sharedReason}>
              📥 partagé
            </span>
          )}
          {n.is_private && (
            <span className="inline-flex items-center gap-1 text-[10px] text-fuchsia-700 bg-fuchsia-50 ring-1 ring-fuchsia-200 px-1.5 py-0.5 rounded" title="Note privée — visible uniquement par vous et les administrateurs">
              <Lock className="h-3 w-3" /> privée
            </span>
          )}
          {locked ? (
            <span className="inline-flex items-center gap-1 text-[10px] text-slate-400" title="Verrouillé (>1h après création)"><Lock className="h-3 w-3" /> verrouillé</span>
          ) : null}
        </span>
      </div>
      <h3 className="font-display font-semibold text-slate-900 truncate" title={n.title}>{n.title}</h3>
      {kind === "suivis" && (
        <div className="mt-1 text-xs text-slate-500 flex items-center gap-1.5 flex-wrap">
          {n.event_date && <span className="inline-flex items-center gap-1"><CalIcon className="h-3 w-3" />{new Date(n.event_date).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" })}</span>}
          {n.client_id && <span className="px-1.5 py-0.5 bg-emerald-50 rounded">{clientName}</span>}
        </div>
      )}
      <div className="mt-2 text-sm text-slate-600 prose-sawali line-clamp-4" dangerouslySetInnerHTML={{ __html: n.content_html || "<p class=\"text-slate-400 italic\">Aucun contenu</p>" }} />
      {kind === "tasks" && Array.isArray(n.task_items) && n.task_items.length > 0 && (
        <div className="mt-2 space-y-0.5" data-testid="task-checklist-preview">
          {[...n.task_items].sort((a, b) => (a.order || 0) - (b.order || 0)).slice(0, 6).map((it) => (
            <div key={it.id || it.text} className={`text-xs flex items-start gap-1.5 ${it.done ? "text-slate-400 line-through" : "text-slate-700"}`}>
              <span className={`mt-0.5 inline-block h-3 w-3 rounded ring-1 ${it.done ? "bg-emerald-500 ring-emerald-600" : "ring-slate-300"} shrink-0`}>
                {it.done && <span className="text-white text-[8px] leading-3">✓</span>}
              </span>
              <span className="truncate">{it.text}</span>
            </div>
          ))}
          {n.task_items.length > 6 && (
            <div className="text-[10px] text-slate-400 italic">+ {n.task_items.length - 6} autre(s)…</div>
          )}
          {(() => {
            const done = n.task_items.filter((x) => x.done).length;
            return done > 0 && (
              <div className="text-[10px] text-emerald-700 font-medium">{done}/{n.task_items.length} réalisée(s)</div>
            );
          })()}
        </div>
      )}
      {n.images && n.images.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1">
          {n.images.slice(0, 6).map((im, i) => <AttachmentThumb key={i} im={im} onOpen={() => onImage(absoluteImg(im.url))} />)}
          {n.images.length > 6 && <span className="text-[10px] text-slate-500 self-center px-1">+{n.images.length - 6}</span>}
        </div>
      )}
      <div className="mt-3 flex items-center justify-between gap-2 text-xs">
        <span className="text-slate-400 truncate inline-flex items-center gap-2 min-w-0">
          {n.owner_email && (
            <AuthorAvatar email={n.owner_email} name={n.owner_name} />
          )}
          <span className="truncate">
            {n.owner_email && <span className="text-slate-600 font-medium" title={n.owner_email}>{n.owner_name || (n.owner_email || "").split("@")[0]}</span>}
            <br />
            {n.created_at && new Date(n.created_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}
          </span>
        </span>
        <div className="flex gap-2 items-center">
          {/* Iter38r-fix9g — Eye icon always visible on non-owned items (even for admin), for quick read-only preview */}
          {!isOwner && (
            <button onClick={onView} className="text-slate-500 hover:text-sawali-blue" title="Consulter (lecture seule)" data-testid={`view-note-${n.id}`}><Eye className="h-3.5 w-3.5" /></button>
          )}
          {!readOnly && !locked && <button onClick={onEdit} className="text-slate-500 hover:text-sawali-blue" title="Modifier" data-testid={`edit-note-${n.id}`}><Edit className="h-3.5 w-3.5" /></button>}
          {!readOnly && canDelete && <button onClick={onDelete} className="text-slate-500 hover:text-rose-600" title="Supprimer" data-testid={`delete-note-${n.id}`}><Trash2 className="h-3.5 w-3.5" /></button>}
        </div>
      </div>
      {/* Iter36d — Note de Service: only for public + numbered notes */}
      {!n.is_private && n.numero && (
        <NoteDeServiceButton noteId={n.id} kind={kind} numero={n.numero} lastSent={n.last_note_service_at} lastCount={n.last_note_service_count} onSent={onRefresh} />
      )}
      {canDeleteOrRate(user) && (
        <div className="mt-3 pt-2 border-t border-slate-100">
          <RatingStars value={n.my_rating?.stars || 0} onChange={setRating} onClear={clearRating} />
          {n.my_rating?.stars ? <span className="text-[10px] text-slate-400 ml-2">votre note</span> : null}
        </div>
      )}
    </article>
  );
}

const BACKEND = process.env.REACT_APP_BACKEND_URL || "";
const absoluteImg = (u) => (!u ? "" : (u.startsWith("http") ? u : `${BACKEND}${u.startsWith("/") ? "" : "/"}${u}`));

// ====================================================================
// Author avatar — colored circular pictogramme with initials.
// Color is derived deterministically from the email so the same author
// always gets the same color, making authorship identifiable at a glance.
// ====================================================================
const AVATAR_PALETTE = [
  { bg: "bg-emerald-500", ring: "ring-emerald-200" },
  { bg: "bg-sky-500", ring: "ring-sky-200" },
  { bg: "bg-violet-500", ring: "ring-violet-200" },
  { bg: "bg-rose-500", ring: "ring-rose-200" },
  { bg: "bg-amber-500", ring: "ring-amber-200" },
  { bg: "bg-fuchsia-500", ring: "ring-fuchsia-200" },
  { bg: "bg-teal-500", ring: "ring-teal-200" },
  { bg: "bg-indigo-500", ring: "ring-indigo-200" },
  { bg: "bg-orange-500", ring: "ring-orange-200" },
  { bg: "bg-cyan-500", ring: "ring-cyan-200" },
];

function paletteFor(seed) {
  if (!seed) return AVATAR_PALETTE[0];
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return AVATAR_PALETTE[h % AVATAR_PALETTE.length];
}

function AuthorAvatar({ email, name, size = 28 }) {
  const seed = (email || name || "?").toLowerCase();
  const p = paletteFor(seed);
  // Build initials (2 chars max) from the friendly name when available, else from local-part of email
  const source = (name || (email || "").split("@")[0] || "?").trim();
  const parts = source.replace(/[._-]+/g, " ").split(/\s+/).filter(Boolean);
  let initials = "?";
  if (parts.length >= 2) initials = (parts[0][0] + parts[1][0]).toUpperCase();
  else if (parts.length === 1) initials = parts[0].slice(0, 2).toUpperCase();
  return (
    <span
      className={`inline-flex items-center justify-center rounded-full text-white font-semibold ring-2 ring-white shadow-sm flex-shrink-0 ${p.bg}`}
      style={{ width: size, height: size, fontSize: Math.max(10, size * 0.4) }}
      title={`Auteur : ${name || email || "inconnu"}`}
      data-testid={`author-avatar-${seed}`}
    >
      {initials}
    </span>
  );
}

// ====================================================================
// 5-star rater
// ====================================================================
// Iter36d — Note de Service: broadcast a public/numbered note to all suivis via WA template
function NoteDeServiceButton({ noteId, kind, numero, lastSent, lastCount, onSent }) {
  const [busy, setBusy] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const send = async () => {
    setBusy(true);
    try {
      const r = await apiClient.post(`/me/notes/${kind}/${noteId}/note-de-service`);
      const { sent_count, skipped_count, total_targets, template } = r.data || {};
      toast.success(
        `Note de Service ${numero} envoyée à ${sent_count}/${total_targets} suivi(s)${skipped_count ? ` (${skipped_count} ignoré)` : ""} — template « ${template} »`,
        { duration: 7000 },
      );
      setConfirmOpen(false);
      if (onSent) onSent();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec de l'envoi");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-2 pt-2 border-t border-slate-100" data-testid={`note-de-service-${noteId}`}>
      {!confirmOpen ? (
        <button
          onClick={() => setConfirmOpen(true)}
          className="w-full inline-flex items-center justify-center gap-1.5 rounded-lg bg-emerald-50 hover:bg-emerald-100 text-emerald-800 ring-1 ring-emerald-200 px-3 py-1.5 text-xs font-medium transition"
          data-testid={`note-de-service-btn-${noteId}`}
          title="Diffuser cette note par WhatsApp à tous les utilisateurs suivis"
        >
          <Megaphone className="h-3.5 w-3.5" />
          Note Service
          {lastSent && (
            <span className="text-[9px] text-emerald-600 ml-1" title={`Dernier envoi : ${new Date(lastSent).toLocaleString("fr-FR")}`}>
              · {lastCount || 0} déjà envoyé(s)
            </span>
          )}
        </button>
      ) : (
        <div className="rounded-lg ring-1 ring-emerald-200 bg-emerald-50 p-2 space-y-2" data-testid={`note-de-service-confirm-${noteId}`}>
          <p className="text-[11px] text-emerald-900">
            Diffuser la note <strong>{numero}</strong> en WhatsApp à tous les utilisateurs suivis du client lié ?
          </p>
          <div className="flex gap-2">
            <button
              onClick={send}
              disabled={busy}
              className="flex-1 inline-flex items-center justify-center gap-1 rounded bg-emerald-600 hover:bg-emerald-700 text-white px-2 py-1 text-xs disabled:opacity-50"
              data-testid={`note-de-service-confirm-yes-${noteId}`}
            >
              {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Megaphone className="h-3 w-3" />}
              Envoyer
            </button>
            <button
              onClick={() => setConfirmOpen(false)}
              disabled={busy}
              className="rounded ring-1 ring-slate-300 bg-white text-slate-700 hover:bg-slate-50 px-2 py-1 text-xs"
              data-testid={`note-de-service-confirm-no-${noteId}`}
            >
              Annuler
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function RatingStars({ value = 0, onChange, onClear }) {
  return (
    <div className="inline-flex items-center gap-0.5" data-testid="rating-stars">
      {[1, 2, 3, 4, 5].map((s) => (
        <button key={s} type="button" onClick={() => onChange(s)} className="p-0.5" title={`${s} étoile${s > 1 ? "s" : ""}`} data-testid={`star-${s}`}>
          <Star className={`h-4 w-4 ${s <= value ? "fill-amber-400 text-amber-500" : "text-slate-300"}`} />
        </button>
      ))}
      {value > 0 && (
        <button type="button" onClick={onClear} className="ml-1 text-[10px] text-slate-400 hover:text-rose-500" title="Effacer">×</button>
      )}
    </div>
  );
}

// ====================================================================
// Attachment thumbnail (image preview or file-icon for non-images)
// ====================================================================
function isImageFile(im) {
  if (!im) return false;
  const url = (im.url || "").toLowerCase();
  const name = (im.filename || "").toLowerCase();
  return /\.(jpe?g|png|gif|webp|heic|heif|bmp|svg)(\?|$)/.test(url) || /\.(jpe?g|png|gif|webp|heic|heif|bmp|svg)$/.test(name);
}

function AttachmentThumb({ im, onOpen, onRemove, size = 48 }) {
  const isImg = isImageFile(im);
  const fi = getFileIcon(im.filename || im.url);
  const Icn = fi.icon;
  const url = absoluteImg(im.url);
  return (
    <div className="relative flex-shrink-0" style={{ height: size, width: size }} data-testid="note-attachment">
      {isImg ? (
        <button onClick={onOpen} className="block h-full w-full rounded overflow-hidden border border-slate-200 bg-slate-50">
          <img src={url} alt="" className="h-full w-full object-cover" />
        </button>
      ) : (
        <a href={url} target="_blank" rel="noreferrer" download={im.filename} className="flex h-full w-full flex-col items-center justify-center rounded border border-slate-200 bg-white text-slate-700 hover:border-sawali-blue" title={im.filename || "Document"}>
          <Icn className="h-5 w-5" style={{ color: fi.color }} />
          <span className="text-[8px] uppercase mt-0.5 font-mono">{(im.filename || "").split(".").pop()?.slice(0, 4) || "doc"}</span>
        </a>
      )}
      {onRemove && (
        <button type="button" onClick={onRemove} className="absolute top-0 right-0 bg-black/60 text-white rounded-bl px-1 text-[10px]" title="Retirer">×</button>
      )}
    </div>
  );
}

// ====================================================================
// Attachment uploader (max 10) — images + PDFs + Office docs
// ====================================================================
const ACCEPTED_TYPES = "image/*,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-powerpoint,application/vnd.openxmlformats-officedocument.presentationml.presentation,text/plain,text/csv";
const MAX_SIZE_BYTES = 25 * 1024 * 1024; // 25 MB per file

function ImageUploader({ images = [], onChange, accent = "#1E90FF" }) {
  const inputRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const list = images || [];

  const upload = async (files) => {
    const remaining = 10 - list.length;
    if (remaining <= 0) { toast.error("Maximum 10 pièces jointes atteintes"); return; }
    const todo = Array.from(files).slice(0, remaining);
    setBusy(true);
    try {
      const next = [...list];
      for (const f of todo) {
        if (f.size > MAX_SIZE_BYTES) { toast.error(`${f.name} dépasse 25 Mo`); continue; }
        const fd = new FormData();
        fd.append("file", f);
        const r = await apiClient.post("/me/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
        next.push({ file_id: r.data.id, url: r.data.url, filename: r.data.filename, content_type: r.data.content_type });
      }
      onChange(next);
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur upload"); }
    finally { setBusy(false); if (inputRef.current) inputRef.current.value = ""; }
  };

  const remove = (i) => onChange(list.filter((_, idx) => idx !== i));

  return (
    <div>
      <label className="block text-xs font-semibold mb-1 flex items-center gap-1.5"><Paperclip className="h-3 w-3" /> Pièces jointes ({list.length}/10)<span className="font-normal text-slate-500">— images, PDF, Word, Excel, PPT</span></label>
      <div className="flex flex-wrap gap-2">
        {list.map((im, i) => <AttachmentThumb key={i} im={im} size={64} onOpen={() => window.open(absoluteImg(im.url), "_blank")} onRemove={() => remove(i)} />)}
        {list.length < 10 && (
          <button
            type="button"
            disabled={busy}
            onClick={() => inputRef.current?.click()}
            className="h-16 w-16 rounded-md border border-dashed border-slate-300 flex flex-col items-center justify-center text-[10px] text-slate-500 hover:border-sawali-blue hover:text-sawali-blue disabled:opacity-50"
            style={{ borderColor: busy ? accent : undefined }}
            data-testid="add-image-btn"
          >
            <ImagePlus className="h-4 w-4" />
            {busy ? "..." : "Ajouter"}
          </button>
        )}
      </div>
      <input ref={inputRef} type="file" hidden multiple accept={ACCEPTED_TYPES} onChange={(e) => e.target.files && upload(e.target.files)} />
    </div>
  );
}

// ====================================================================
// Rich Text Editor — WYSIWYG, contentEditable + execCommand
// ====================================================================
const TEXT_COLORS = ["#0F172A", "#1E90FF", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6", "#0EA5E9"];
const HIGHLIGHTS = ["transparent", "#FEF3C7", "#DBEAFE", "#DCFCE7", "#FEE2E2", "#EDE9FE"];

// S-iter39b — Exported for reuse in MeetingMinutes (PV de réunions)
export function RichEditor({ value, onChange, accent = "#1E90FF", aiEnabled = true }) {
  const ref = useRef(null);
  const [showColors, setShowColors] = useState(false);
  const [showHighlights, setShowHighlights] = useState(false);
  const [recState, setRecState] = useState("idle"); // idle | recording | processing
  const recRef = useRef({ recorder: null, chunks: [], stream: null });

  useEffect(() => {
    if (ref.current && ref.current.innerHTML !== (value || "")) {
      const isEmpty = !ref.current.innerHTML || ref.current.innerHTML === "<br>";
      if (isEmpty) ref.current.innerHTML = value || "";
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const emit = () => { if (ref.current) onChange(ref.current.innerHTML); };
  const exec = (cmd, arg = null) => { ref.current?.focus(); document.execCommand(cmd, false, arg); emit(); };
  const setLink = () => { const url = window.prompt("URL du lien :", "https://"); if (url) exec("createLink", url); };

  const insertText = (text) => {
    if (!text) return;
    ref.current?.focus();
    // Wrap in a paragraph so multiline transcription stays readable
    const html = text.split(/\n+/).map((p) => `<p>${p.replace(/</g, "&lt;").replace(/>/g, "&gt;")}</p>`).join("");
    document.execCommand("insertHTML", false, html);
    emit();
  };

  const startRec = async () => {
    if (recState !== "idle") return;
    if (!navigator.mediaDevices?.getUserMedia || typeof window.MediaRecorder === "undefined") {
      toast.error("Votre navigateur ne supporte pas l'enregistrement audio.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // Pick the first MIME the browser supports — webm/opus everywhere except Safari (mp4)
      const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
      const mime = candidates.find((m) => window.MediaRecorder.isTypeSupported && window.MediaRecorder.isTypeSupported(m)) || "";
      const recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      const chunks = [];
      recorder.ondataavailable = (e) => { if (e.data && e.data.size > 0) chunks.push(e.data); };
      recorder.onstop = async () => {
        try {
          recRef.current.stream?.getTracks().forEach((t) => t.stop());
        } catch { /* noop */ }
        const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
        if (blob.size < 200) { setRecState("idle"); toast.error("Audio trop court."); return; }
        setRecState("processing");
        try {
          const fd = new FormData();
          const ext = (recorder.mimeType || "audio/webm").split(";")[0].split("/")[1] || "webm";
          fd.append("file", blob, `note-audio.${ext}`);
          fd.append("language", "fr");
          const r = await apiClient.post("/transcribe", fd, { headers: { "Content-Type": "multipart/form-data" } });
          const txt = (r.data?.text || "").trim();
          if (txt) { insertText(txt); toast.success("Transcription insérée"); }
          else toast.message("Aucun texte détecté dans l'audio.");
        } catch (err) {
          toast.error(err?.response?.data?.detail || "Erreur de transcription");
        } finally {
          setRecState("idle");
        }
      };
      recRef.current = { recorder, chunks, stream };
      recorder.start();
      setRecState("recording");
    } catch (err) {
      toast.error("Accès au micro refusé.");
    }
  };
  const stopRec = () => {
    const rec = recRef.current.recorder;
    if (rec && rec.state !== "inactive") rec.stop();
  };
  // Cleanup mic on unmount
  useEffect(() => () => {
    try { recRef.current.stream?.getTracks().forEach((t) => t.stop()); } catch { /* noop */ }
  }, []);

  const Btn = ({ onClick, title, children, testid }) => (
    <button type="button" title={title} onMouseDown={(e) => e.preventDefault()} onClick={onClick} className="p-1.5 rounded hover:bg-slate-100 text-slate-600" data-testid={testid}>{children}</button>
  );

  return (
    <div className="rounded-lg border border-slate-300 focus-within:border-sawali-blue overflow-hidden">
      <div className="flex items-center flex-wrap gap-0.5 border-b border-slate-200 bg-slate-50/60 px-2 py-1.5" data-testid="rte-toolbar">
        <Btn onClick={() => exec("bold")} title="Gras" testid="rte-bold"><Bold className="h-3.5 w-3.5" /></Btn>
        <Btn onClick={() => exec("italic")} title="Italique" testid="rte-italic"><Italic className="h-3.5 w-3.5" /></Btn>
        <Btn onClick={() => exec("underline")} title="Souligné" testid="rte-underline"><Underline className="h-3.5 w-3.5" /></Btn>
        <Btn onClick={() => exec("strikeThrough")} title="Barré" testid="rte-strike"><Strikethrough className="h-3.5 w-3.5" /></Btn>
        <span className="w-px h-5 bg-slate-200 mx-1" />
        <Btn onClick={() => exec("formatBlock", "h2")} title="Titre" testid="rte-h2"><Heading2 className="h-3.5 w-3.5" /></Btn>
        <Btn onClick={() => exec("formatBlock", "h3")} title="Sous-titre" testid="rte-h3"><Heading3 className="h-3.5 w-3.5" /></Btn>
        <Btn onClick={() => exec("formatBlock", "blockquote")} title="Citation" testid="rte-quote"><Quote className="h-3.5 w-3.5" /></Btn>
        <Btn onClick={() => exec("formatBlock", "pre")} title="Code" testid="rte-code"><Code className="h-3.5 w-3.5" /></Btn>
        <span className="w-px h-5 bg-slate-200 mx-1" />
        <Btn onClick={() => exec("insertUnorderedList")} title="Liste à puces" testid="rte-ul"><List className="h-3.5 w-3.5" /></Btn>
        <Btn onClick={() => exec("insertOrderedList")} title="Liste numérotée" testid="rte-ol"><ListOrdered className="h-3.5 w-3.5" /></Btn>
        <span className="w-px h-5 bg-slate-200 mx-1" />
        <Btn onClick={() => exec("justifyLeft")} title="Gauche" testid="rte-left"><AlignLeft className="h-3.5 w-3.5" /></Btn>
        <Btn onClick={() => exec("justifyCenter")} title="Centrer" testid="rte-center"><AlignCenter className="h-3.5 w-3.5" /></Btn>
        <Btn onClick={() => exec("justifyRight")} title="Droite" testid="rte-right"><AlignRight className="h-3.5 w-3.5" /></Btn>
        <span className="w-px h-5 bg-slate-200 mx-1" />
        <div className="relative">
          <Btn onClick={() => { setShowColors((v) => !v); setShowHighlights(false); }} title="Couleur" testid="rte-color">
            <span className="inline-flex flex-col items-center leading-none"><span className="font-bold text-[10px]">A</span><span className="block w-3 h-0.5" style={{ background: accent }} /></span>
          </Btn>
          {showColors && (
            <div className="absolute left-0 top-full mt-1 z-10 bg-white border border-slate-200 rounded-lg shadow-lg p-2 flex gap-1">
              {TEXT_COLORS.map((c) => (
                <button key={c} type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => { exec("foreColor", c); setShowColors(false); }} className="h-5 w-5 rounded-full border border-slate-200" style={{ background: c }} title={c} />
              ))}
            </div>
          )}
        </div>
        <div className="relative">
          <Btn onClick={() => { setShowHighlights((v) => !v); setShowColors(false); }} title="Surlignage" testid="rte-highlight">
            <span className="inline-flex flex-col items-center leading-none"><span className="font-bold text-[10px]">H</span><span className="block w-3 h-0.5 bg-yellow-300" /></span>
          </Btn>
          {showHighlights && (
            <div className="absolute left-0 top-full mt-1 z-10 bg-white border border-slate-200 rounded-lg shadow-lg p-2 flex gap-1">
              {HIGHLIGHTS.map((c) => (
                <button key={c} type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => { exec("hiliteColor", c); setShowHighlights(false); }} className="h-5 w-5 rounded-full border border-slate-200" style={{ background: c === "transparent" ? "repeating-linear-gradient(45deg,#fff,#fff 3px,#eee 3px,#eee 6px)" : c }} title={c} />
              ))}
            </div>
          )}
        </div>
        <span className="w-px h-5 bg-slate-200 mx-1" />
        <Btn onClick={setLink} title="Lien" testid="rte-link"><LinkIcon className="h-3.5 w-3.5" /></Btn>
        <Btn onClick={() => exec("removeFormat")} title="Effacer" testid="rte-clear"><Eraser className="h-3.5 w-3.5" /></Btn>
        <span className="w-px h-5 bg-slate-200 mx-1" />
        <Btn onClick={() => exec("undo")} title="Annuler" testid="rte-undo"><Undo2 className="h-3.5 w-3.5" /></Btn>
        <Btn onClick={() => exec("redo")} title="Rétablir" testid="rte-redo"><Redo2 className="h-3.5 w-3.5" /></Btn>
        <span className="w-px h-5 bg-slate-200 mx-1" />
        {recState === "recording" ? (
          <button
            type="button"
            onMouseDown={(e) => e.preventDefault()}
            onClick={stopRec}
            className="inline-flex items-center gap-1.5 rounded-full bg-rose-600 hover:bg-rose-700 text-white px-3 py-1.5 text-[12px] font-semibold animate-pulse shadow"
            title="Arrêter l'enregistrement"
            data-testid="rte-mic-stop"
          >
            <Square className="h-3.5 w-3.5 fill-white" /> Arrêter
          </button>
        ) : recState === "processing" ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-500 text-white px-3 py-1.5 text-[12px] font-semibold" data-testid="rte-mic-processing">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Transcription…
          </span>
        ) : (
          <button
            type="button"
            onMouseDown={(e) => e.preventDefault()}
            onClick={aiEnabled ? startRec : () => toast.message("Fonctionnalité Génération IA non activée — contactez votre administrateur")}
            disabled={!aiEnabled}
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[12px] font-semibold shadow-sm ${
              aiEnabled
                ? "bg-fuchsia-600 hover:bg-fuchsia-700 text-white"
                : "bg-slate-200 text-slate-400 cursor-not-allowed"
            }`}
            title={aiEnabled ? "Dicter à la voix (transcription Whisper)" : "Fonctionnalité Génération IA non activée"}
            data-testid="rte-mic-start"
          >
            <Mic className="h-3.5 w-3.5" /> Dicter
          </button>
        )}
      </div>
      <div ref={ref} contentEditable suppressContentEditableWarning onInput={emit} onBlur={emit} className="prose-sawali min-h-[180px] max-h-[360px] overflow-auto px-3 py-2 text-sm focus:outline-none" style={{ caretColor: accent }} data-testid="rte-content" />
    </div>
  );
}


// ====================================================================
// WhatsApp messages picker — fetch the user's WA history (optionally
// filtered by client) and let them inject selected messages into the
// note body. Useful to consolidate context inside Reports/Suivis.
// ====================================================================
function WaMessagesPicker({ clientId = null, onAppend, accent = "#1E90FF" }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [picked, setPicked] = useState({});

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/me/whatsapp/history", { params: { limit: 100 } });
      let arr = Array.isArray(r.data) ? r.data : [];
      if (clientId) arr = arr.filter((m) => m.client_id === clientId);
      setItems(arr);
    } catch { setItems([]); }
    finally { setLoading(false); }
  };

  useEffect(() => { if (open) load(); /* eslint-disable-next-line */ }, [open, clientId]);

  const append = () => {
    const ids = Object.keys(picked).filter((k) => picked[k]);
    if (ids.length === 0) { toast.error("Sélectionnez au moins un message"); return; }
    const chosen = items.filter((m) => ids.includes(m.id));
    const rows = chosen.map((m) => {
      const ts = m.created_at ? new Date(m.created_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—";
      const dir = m.direction === "inbound" ? "Reçu" : "Envoyé";
      const body = (m.body || "").trim();
      const tpl = m.template_name ? ` <em>(template ${m.template_name})</em>` : "";
      const text = body || (m.template_name ? `Template : ${m.template_name}` : "(sans contenu)");
      const safe = text.replace(/</g, "&lt;").replace(/>/g, "&gt;");
      return `<li><strong>${dir}</strong> · <code>${m.to || m.from || "—"}</code> · <span style="color:#64748b">${ts}</span>${tpl}<br/>${safe}</li>`;
    }).join("");
    const html = `<h3>Messages WhatsApp sélectionnés (${chosen.length})</h3><ul>${rows}</ul>`;
    onAppend(html);
    setPicked({});
    setOpen(false);
    toast.success(`${chosen.length} message(s) ajouté(s) au contenu`);
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-white" data-testid="wa-messages-picker">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 rounded-xl"
        data-testid="wa-picker-toggle"
      >
        <span className="inline-flex items-center gap-2">
          <MessageCircle className="h-4 w-4" style={{ color: accent }} />
          Insérer des messages WhatsApp {clientId ? "(filtré par client)" : ""}
        </span>
        <span className="text-[10px] text-slate-400">{open ? "Réduire" : "Afficher"}</span>
      </button>
      {open && (
        <div className="border-t border-slate-100 px-3 py-3 space-y-2 max-h-72 overflow-auto">
          {loading ? (
            <p className="text-xs italic text-slate-500">Chargement…</p>
          ) : items.length === 0 ? (
            <p className="text-xs italic text-slate-500">Aucun message WhatsApp à afficher.</p>
          ) : (
            <table className="w-full text-xs" data-testid="wa-picker-table">
              <thead className="text-slate-500 text-[10px] uppercase">
                <tr>
                  <th className="text-left px-1 py-1 w-6"></th>
                  <th className="text-left px-1 py-1">Date</th>
                  <th className="text-left px-1 py-1">Sens</th>
                  <th className="text-left px-1 py-1">Destinataire</th>
                  <th className="text-left px-1 py-1">Aperçu</th>
                </tr>
              </thead>
              <tbody>
                {items.map((m) => {
                  const checked = !!picked[m.id];
                  const body = (m.body || "").trim() || (m.template_name ? `Template : ${m.template_name}` : "(sans contenu)");
                  return (
                    <tr key={m.id} className={`border-t border-slate-100 ${checked ? "bg-emerald-50" : "hover:bg-slate-50"}`} data-testid={`wa-picker-row-${m.id}`}>
                      <td className="px-1 py-1">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(e) => setPicked((p) => ({ ...p, [m.id]: e.target.checked }))}
                          data-testid={`wa-picker-check-${m.id}`}
                        />
                      </td>
                      <td className="px-1 py-1 text-slate-600 whitespace-nowrap">
                        {m.created_at ? new Date(m.created_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—"}
                      </td>
                      <td className="px-1 py-1">
                        <span className={`text-[10px] px-1.5 py-0.5 rounded ${m.direction === "inbound" ? "bg-sky-100 text-sky-700" : "bg-emerald-100 text-emerald-700"}`}>
                          {m.direction === "inbound" ? "Reçu" : "Envoyé"}
                        </span>
                      </td>
                      <td className="px-1 py-1 font-mono text-[10px] text-slate-600">{m.to || m.from || "—"}</td>
                      <td className="px-1 py-1 text-slate-700 truncate max-w-[260px]" title={body}>{body.slice(0, 80)}{body.length > 80 ? "…" : ""}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          <div className="flex items-center justify-between pt-2">
            <span className="text-[10px] text-slate-500">
              {Object.values(picked).filter(Boolean).length} sélectionné(s) sur {items.length}
            </span>
            <button
              type="button"
              onClick={append}
              disabled={Object.values(picked).filter(Boolean).length === 0}
              className="text-xs rounded-lg text-white px-3 py-1.5 disabled:opacity-50"
              style={{ background: accent }}
              data-testid="wa-picker-append"
            >
              Insérer dans le contenu
            </button>
          </div>
        </div>
      )}
    </div>
  );
}


// =====================================================================
// Iter38r-fix9k — TaskChecklist (Google Keep style)
// =====================================================================
// Editable list of {id, text, done, order, done_at}. Done items are
// rendered at the bottom of the list, grayed-out and struck-through.
// Reorder is automatic: undone items first (by order), done items at the
// end (most recently done first).
function TaskChecklist({ items, onChange, accent = "#F59E0B" }) {
  const [draft, setDraft] = React.useState("");
  const all = Array.isArray(items) ? items : [];
  const sorted = React.useMemo(() => {
    const undone = all.filter((x) => !x.done).sort((a, b) => (a.order || 0) - (b.order || 0));
    const done = all.filter((x) => x.done).sort((a, b) => String(b.done_at || "").localeCompare(String(a.done_at || "")));
    return [...undone, ...done];
  }, [all]);

  const addItem = () => {
    const text = draft.trim();
    if (!text) return;
    const next = [...all, {
      id: (window.crypto?.randomUUID?.() || `t-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`),
      text,
      done: false,
      order: all.length,
      done_at: null,
    }];
    onChange(next);
    setDraft("");
  };

  const toggle = (id) => {
    const next = all.map((x) => x.id === id ? { ...x, done: !x.done, done_at: !x.done ? new Date().toISOString() : null } : x);
    onChange(next);
  };

  const updateText = (id, text) => onChange(all.map((x) => x.id === id ? { ...x, text } : x));
  const remove = (id) => onChange(all.filter((x) => x.id !== id));

  const undoneCount = all.filter((x) => !x.done).length;
  const doneCount = all.length - undoneCount;

  return (
    <div className="rounded-xl ring-1 ring-slate-200 bg-white p-3 space-y-2" data-testid="task-checklist">
      <div className="flex items-center justify-between text-xs">
        <span className="font-display font-semibold text-slate-700 inline-flex items-center gap-1">
          <ClipboardList className="h-3.5 w-3.5" style={{ color: accent }} /> Liste de tâches
        </span>
        <span className="text-slate-400">{doneCount} fait(s) / {all.length}</span>
      </div>
      {/* New item input */}
      <div className="flex gap-2">
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addItem(); } }}
          placeholder="+ Ajouter un élément (Entrée pour valider)"
          className="flex-1 rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:ring-2 focus:ring-amber-300 outline-none"
          data-testid="task-checklist-add-input"
        />
        <button
          type="button"
          onClick={addItem}
          disabled={!draft.trim()}
          className="rounded-lg px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40"
          style={{ background: accent }}
          data-testid="task-checklist-add-btn"
        >
          Ajouter
        </button>
      </div>
      {/* Items */}
      <ul className="space-y-1">
        {sorted.length === 0 && (
          <li className="text-xs text-slate-400 italic py-2 text-center">Aucune tâche pour le moment.</li>
        )}
        {sorted.map((it) => (
          <li
            key={it.id}
            className={`flex items-center gap-2 rounded-lg px-2 py-1 transition ${it.done ? "bg-slate-50" : "hover:bg-slate-50"}`}
            data-testid={`task-checklist-item-${it.id}`}
          >
            <input
              type="checkbox"
              checked={!!it.done}
              onChange={() => toggle(it.id)}
              className="h-4 w-4 rounded border-slate-300 cursor-pointer"
              style={{ accentColor: accent }}
              data-testid={`task-checklist-toggle-${it.id}`}
            />
            <input
              type="text"
              value={it.text}
              onChange={(e) => updateText(it.id, e.target.value)}
              className={`flex-1 bg-transparent text-sm outline-none border-0 ${it.done ? "line-through text-slate-400" : "text-slate-800"}`}
              data-testid={`task-checklist-text-${it.id}`}
            />
            <button
              type="button"
              onClick={() => remove(it.id)}
              className="text-slate-300 hover:text-rose-500 transition"
              title="Supprimer"
              data-testid={`task-checklist-remove-${it.id}`}
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
