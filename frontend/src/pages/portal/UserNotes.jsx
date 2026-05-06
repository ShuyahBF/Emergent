import React, { useEffect, useMemo, useRef, useState } from "react";
import { useParams, Navigate } from "react-router-dom";
import { apiClient } from "@/lib/api";
import {
  Plus, Edit, Trash2, X, FileText, ClipboardList, ImagePlus, Star, Lock, Calendar as CalIcon, Paperclip,
  Bold, Italic, Underline, Strikethrough,
  Heading2, Heading3, List, ListOrdered, Quote,
  AlignLeft, AlignCenter, AlignRight,
  Link as LinkIcon, Undo2, Redo2, Eraser, Code,
  Mic, Square, MessageCircle, Loader2,
} from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import { getFileIcon } from "@/lib/fileIcons";

const KIND_META = {
  reports: { label: "Rapports", singular: "rapport", icon: FileText, accent: "#1E90FF" },
  suivis: { label: "Suivis", singular: "suivi", icon: ClipboardList, accent: "#10B981" },
};

const empty = { title: "", content_html: "", tags: [], client_id: "", event_date: "", images: [], is_private: false };

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
  const [clients, setClients] = useState([]);
  const [isOpen, setIsOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(empty);
  const [busy, setBusy] = useState(false);
  const [activeImage, setActiveImage] = useState(null);

  const elevated = isElevated(user);
  const canDelete = canDeleteOrRate(user);

  const load = () => apiClient.get(`/me/notes/${kind}`, {
    params: {
      author: filterAuthor || undefined,
      q: filterQ || undefined,
    },
  }).then((r) => setItems(r.data)).catch(() => {});
  useEffect(() => {
    if (!meta) return;
    load();
    apiClient.get(`/me/notes/${kind}/authors`).then((r) => setAuthors(r.data)).catch(() => {});
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
        {elevated && (
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

      {!elevated && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          La création de {meta.label.toLowerCase()} est réservée aux rôles <strong>Modération</strong>, <strong>Administrateur</strong> ou <strong>Superviseur</strong>.
        </div>
      )}

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
        <button type="submit" className="rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light" data-testid="notes-filter-apply">Filtrer</button>
        {(filterAuthor || filterQ) && (
          <button type="button" onClick={() => { setFilterAuthor(""); setFilterQ(""); setTimeout(load, 0); }} className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-600 hover:border-rose-300 hover:text-rose-600" data-testid="notes-filter-clear">Effacer</button>
        )}
        <span className="text-xs text-slate-500 ml-auto">{items.length} résultat{items.length > 1 ? "s" : ""}</span>
      </form>

      {items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 p-12 text-center text-slate-500" data-testid={`empty-${kind}`}>
          Aucun {meta.singular} encore enregistré.
        </div>
      ) : (
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
          {items.map((n) => (
            <NoteCard
              key={n.id}
              n={n}
              kind={kind}
              meta={meta}
              user={user}
              canDelete={canDelete}
              clients={clients}
              onEdit={() => open(n)}
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

              <div>
                <label className="block text-xs font-semibold mb-1">Contenu</label>
                <p className="text-[11px] text-slate-500 mb-2 inline-flex items-center gap-1">
                  <Mic className="h-3 w-3" /> Astuce : cliquez sur l'icône <strong>micro</strong> en haut à droite de la barre d'outils pour dicter votre {meta.singular} (transcription Whisper).
                </p>
                <RichEditor value={form.content_html} onChange={(v) => setForm({ ...form, content_html: v })} accent={meta.accent} />
              </div>

              {/* WhatsApp picker — append selected messages to the body */}
              <WaMessagesPicker
                clientId={kind === "suivis" ? form.client_id : null}
                onAppend={(html) => setForm((f) => ({ ...f, content_html: (f.content_html || "") + html }))}
                accent={meta.accent}
              />

              <ImageUploader images={form.images} onChange={(images) => setForm({ ...form, images })} accent={meta.accent} />

              <label className="flex items-start gap-3 rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3 cursor-pointer hover:bg-slate-100 transition" data-testid="note-privacy-toggle-wrapper">
                <input
                  type="checkbox"
                  checked={!!form.is_private}
                  onChange={(e) => setForm({ ...form, is_private: e.target.checked })}
                  className="mt-0.5 h-4 w-4 rounded border-slate-300"
                  data-testid="note-privacy-toggle"
                />
                <span className="flex-1">
                  <span className="block text-sm font-semibold text-slate-800 inline-flex items-center gap-1">
                    <Lock className="h-3.5 w-3.5 text-slate-500" /> Note privée
                  </span>
                  <span className="block text-xs text-slate-500 mt-0.5">
                    Si cochée, seul vous-même et les administrateurs pourrez voir cette note.
                    Décochée : visible par les autres utilisateurs suivis du même client.
                  </span>
                </span>
              </label>

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
    </div>
  );
}

// ====================================================================
// Note card with rating UI
// ====================================================================
function NoteCard({ n, kind, meta, user, canDelete, clients, onEdit, onDelete, onRefresh, onImage }) {
  const locked = isLockedForEdit(n, user);
  const clientName = useMemo(() => clients.find((c) => c.id === n.client_id)?.full_name || n.client_id, [clients, n.client_id]);

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
      {n.images && n.images.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1">
          {n.images.slice(0, 6).map((im, i) => <AttachmentThumb key={i} im={im} onOpen={() => onImage(absoluteImg(im.url))} />)}
          {n.images.length > 6 && <span className="text-[10px] text-slate-500 self-center px-1">+{n.images.length - 6}</span>}
        </div>
      )}
      <div className="mt-3 flex items-center justify-between gap-2 text-xs">
        <span className="text-slate-400 truncate">
          {n.owner_email && <>par {n.owner_email}<br /></>}
          {n.created_at && new Date(n.created_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}
        </span>
        <div className="flex gap-2 items-center">
          {!locked && <button onClick={onEdit} className="text-slate-500 hover:text-sawali-blue" title="Modifier" data-testid={`edit-note-${n.id}`}><Edit className="h-3.5 w-3.5" /></button>}
          {canDelete && <button onClick={onDelete} className="text-slate-500 hover:text-rose-600" title="Supprimer" data-testid={`delete-note-${n.id}`}><Trash2 className="h-3.5 w-3.5" /></button>}
        </div>
      </div>
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
// 5-star rater
// ====================================================================
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

function RichEditor({ value, onChange, accent = "#1E90FF" }) {
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
            className="inline-flex items-center gap-1.5 rounded-full bg-rose-600 hover:bg-rose-700 text-white px-2.5 py-1 text-[11px] animate-pulse"
            title="Arrêter l'enregistrement"
            data-testid="rte-mic-stop"
          >
            <Square className="h-3 w-3 fill-white" /> Arrêter
          </button>
        ) : recState === "processing" ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-500 text-white px-2.5 py-1 text-[11px]" data-testid="rte-mic-processing">
            <Loader2 className="h-3 w-3 animate-spin" /> Transcription…
          </span>
        ) : (
          <Btn onClick={startRec} title="Dicter à la voix (transcription Whisper)" testid="rte-mic-start">
            <Mic className="h-3.5 w-3.5" />
          </Btn>
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
