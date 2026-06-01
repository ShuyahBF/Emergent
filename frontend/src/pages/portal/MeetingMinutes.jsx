// S-iter39b — PV de réunions internes (Procès-Verbal) — création, édition,
// liste, impression et export PDF.
import React, { useEffect, useMemo, useState, useRef } from "react";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import {
  ClipboardList, Plus, Edit, Trash2, X, Search, FileText, Printer, Eye, Save, Loader2, Clock,
} from "lucide-react";
import { RichEditor } from "@/pages/portal/UserNotes";
import { useNavigate, useParams } from "react-router-dom";
import PdfViewer from "@/components/PdfViewer";

function todayDate() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function nowIso() {
  return new Date().toISOString();
}
function fmtTime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  } catch { return "—"; }
}
function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("fr-FR", { dateStyle: "long" });
  } catch { return "—"; }
}

const EMPTY = {
  meeting_date: todayDate(),
  started_at: nowIso(),
  title: "",
  attendees: "",
  body_html: "",
};

export default function MeetingMinutes() {
  const { user } = useAuth() || {};
  const navigate = useNavigate();
  const { id } = useParams();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState(null);  // existing doc for edit
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [viewing, setViewing] = useState(null);  // doc for read-only view
  const [pdfDoc, setPdfDoc] = useState(null);
  const [aiEnabled, setAiEnabled] = useState(true);

  const isAdminOrSup = user?.role === "admin" || user?.role === "superviseur";
  const elevatedTracked = ["Administrateur", "Superviseur", "Moderation"].includes(user?.tracked_role || "");
  const canDelete = isAdminOrSup || ["Administrateur", "Superviseur"].includes(user?.tracked_role || "");

  const load = async () => {
    try {
      setLoading(true);
      const r = await apiClient.get("/me/meetings", { params: q ? { q } : {} });
      setItems(r.data?.items || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur chargement");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [q]);

  // Detect ai_liluvine / Whisper feature availability
  useEffect(() => {
    apiClient.get("/me/features").then((r) => {
      const f = r.data?.features || r.data || {};
      setAiEnabled(!!(f.ai || f.whisper || f.transcribe || isAdminOrSup));
    }).catch(() => setAiEnabled(true));
  }, [isAdminOrSup]);

  // Deep-link /portal/meetings/:id → open view
  useEffect(() => {
    if (!id) return;
    apiClient.get(`/me/meetings/${id}`).then((r) => setViewing(r.data)).catch(() => navigate("/portal/meetings"));
  }, [id, navigate]);

  const openNew = () => {
    setEditing(null);
    setForm({ ...EMPTY, started_at: nowIso(), meeting_date: todayDate() });
    setEditorOpen(true);
  };

  const openEdit = async (m) => {
    try {
      const r = await apiClient.get(`/me/meetings/${m.id}`);
      setEditing(r.data);
      setForm({
        meeting_date: r.data.meeting_date || todayDate(),
        started_at: r.data.started_at || nowIso(),
        title: r.data.title || "",
        attendees: r.data.attendees || "",
        body_html: r.data.body_html || "",
      });
      setEditorOpen(true);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
  };

  const closeEditor = () => {
    if (saving) return;
    setEditorOpen(false);
    setEditing(null);
    setForm(EMPTY);
  };

  const save = async () => {
    if (!form.title.trim()) { toast.error("Donnez un titre au PV."); return; }
    setSaving(true);
    try {
      if (editing?.id) {
        // For edits the backend keeps ended_at unless explicitly set; we
        // preserve the existing ended_at and just push the new body.
        const r = await apiClient.put(`/me/meetings/${editing.id}`, {
          meeting_date: form.meeting_date,
          started_at: form.started_at,
          title: form.title.trim(),
          attendees: form.attendees,
          body_html: form.body_html,
        });
        toast.success(`PV ${r.data.numero || ""} mis à jour`);
      } else {
        const r = await apiClient.post("/me/meetings", {
          meeting_date: form.meeting_date,
          started_at: form.started_at,
          title: form.title.trim(),
          attendees: form.attendees,
          body_html: form.body_html,
        });
        toast.success(`PV ${r.data.numero} créé (heure de fin enregistrée : ${fmtTime(r.data.ended_at)})`);
      }
      closeEditor();
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur enregistrement");
    } finally {
      setSaving(false);
    }
  };

  const del = async (m) => {
    if (!window.confirm(`Supprimer le PV « ${m.numero} » ?`)) return;
    try {
      await apiClient.delete(`/me/meetings/${m.id}`);
      toast.success("PV supprimé");
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
  };

  const openPdf = async (m) => {
    const apiBase = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");
    setPdfDoc({
      src: `${apiBase}/api/me/meetings/${m.id}/pdf`,
      title: `${m.numero} — ${m.title}`,
    });
  };

  const printDoc = (m) => {
    const apiBase = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");
    window.open(`${apiBase}/api/me/meetings/${m.id}/pdf`, "_blank", "noopener");
  };

  // --- VIEW MODE ---
  if (viewing) {
    return (
      <div className="space-y-4" data-testid="meeting-view">
        <button
          onClick={() => { setViewing(null); navigate("/portal/meetings"); }}
          className="text-xs inline-flex items-center gap-1 px-2 py-1 rounded ring-1 ring-slate-200 hover:bg-slate-50"
          data-testid="meeting-back"
        >
          ← Retour à la liste
        </button>
        <article className="rounded-2xl ring-1 ring-slate-200 bg-white p-6">
          <header className="flex items-start justify-between gap-2 flex-wrap mb-4">
            <div>
              <p className="text-[10px] uppercase tracking-widest font-mono text-slate-500">{viewing.numero}</p>
              <h1 className="text-2xl font-display font-bold text-slate-900 mt-1">{viewing.title}</h1>
              <p className="text-xs text-slate-500 mt-1">
                {fmtDate(viewing.meeting_date)} · {fmtTime(viewing.started_at)} → {fmtTime(viewing.ended_at)}
                {" "}· par <strong>{viewing.author_name || viewing.author_email}</strong>
              </p>
              {viewing.attendees && (
                <p className="text-xs text-slate-600 mt-1"><strong>Participants :</strong> {viewing.attendees}</p>
              )}
            </div>
            <div className="flex items-center gap-1">
              {(isAdminOrSup || elevatedTracked || viewing.author_id === user?.id) && (
                <button onClick={() => openEdit(viewing)} className="px-3 py-1.5 rounded ring-1 ring-slate-200 hover:bg-slate-50 text-xs inline-flex items-center gap-1" data-testid="meeting-edit-from-view">
                  <Edit className="h-3.5 w-3.5" /> Modifier
                </button>
              )}
              <button onClick={() => printDoc(viewing)} className="px-3 py-1.5 rounded ring-1 ring-slate-200 hover:bg-slate-50 text-xs inline-flex items-center gap-1" data-testid="meeting-print">
                <Printer className="h-3.5 w-3.5" /> Imprimer
              </button>
              <button onClick={() => openPdf(viewing)} className="px-3 py-1.5 rounded bg-sawali-blue text-white text-xs inline-flex items-center gap-1" data-testid="meeting-pdf">
                <FileText className="h-3.5 w-3.5" /> Voir PDF
              </button>
            </div>
          </header>
          <div className="prose prose-sawali max-w-none" dangerouslySetInnerHTML={{ __html: viewing.body_html || "<p class='text-slate-400 italic'>Aucun contenu</p>" }} />
        </article>
        {pdfDoc && (
          <div className="fixed inset-0 z-50 bg-black/70 p-4" data-testid="meeting-pdf-modal">
            <div className="h-full bg-white rounded-xl overflow-hidden">
              <PdfViewer src={pdfDoc.src} title={pdfDoc.title} onClose={() => setPdfDoc(null)} />
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-5" data-testid="meeting-minutes-page">
      <header className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-display font-bold text-slate-900 inline-flex items-center gap-2">
            <ClipboardList className="h-6 w-6 text-fuchsia-600" />
            PV de réunions internes
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Procès-verbaux autonumérotés. Heure de fin = horodatage du clic « Enregistrer ».
          </p>
        </div>
        <button onClick={openNew} className="inline-flex items-center gap-2 rounded-lg bg-fuchsia-600 hover:bg-fuchsia-700 text-white px-4 py-2 text-sm" data-testid="meeting-new-button">
          <Plus className="h-4 w-4" /> Nouveau PV
        </button>
      </header>

      <div className="relative max-w-sm">
        <Search className="h-3.5 w-3.5 absolute left-2.5 top-2.5 text-slate-400" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Rechercher (titre, numéro, participants)…"
          className="w-full pl-8 pr-3 py-2 rounded-lg ring-1 ring-slate-300 text-sm bg-white"
          data-testid="meeting-search-input"
        />
      </div>

      {loading ? (
        <p className="text-sm text-slate-500">Chargement…</p>
      ) : items.length === 0 ? (
        <div className="rounded-2xl ring-1 ring-slate-200 bg-white p-10 text-center text-slate-500 text-sm" data-testid="meeting-empty">
          Aucun PV pour le moment. Cliquez sur « Nouveau PV » pour commencer.
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="meeting-list">
          {items.map((m) => (
            <article key={m.id} className="rounded-xl ring-1 ring-slate-200 bg-white p-4 hover:ring-2 hover:ring-fuchsia-300 transition" data-testid={`meeting-card-${m.id}`}>
              <p className="text-[10px] uppercase tracking-widest font-mono text-fuchsia-700">{m.numero}</p>
              <h3 className="text-sm font-display font-semibold text-slate-900 mt-1 line-clamp-2" title={m.title}>{m.title}</h3>
              <p className="text-xs text-slate-500 mt-2 inline-flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {fmtDate(m.meeting_date)} · {fmtTime(m.started_at)} → {fmtTime(m.ended_at)}
              </p>
              {m.attendees && <p className="text-[11px] text-slate-500 mt-1 line-clamp-1">👥 {m.attendees}</p>}
              <p className="text-[11px] text-slate-400 mt-2">par {m.author_name || m.author_email}</p>
              <div className="mt-3 flex items-center justify-end gap-1.5">
                <button onClick={() => navigate(`/portal/meetings/${m.id}`)} className="text-slate-500 hover:text-sawali-blue p-1.5 rounded hover:bg-slate-50" title="Consulter" data-testid={`meeting-view-${m.id}`}>
                  <Eye className="h-3.5 w-3.5" />
                </button>
                {(isAdminOrSup || elevatedTracked || m.author_id === user?.id) && (
                  <button onClick={() => openEdit(m)} className="text-slate-500 hover:text-sawali-blue p-1.5 rounded hover:bg-slate-50" title="Modifier" data-testid={`meeting-edit-${m.id}`}>
                    <Edit className="h-3.5 w-3.5" />
                  </button>
                )}
                <button onClick={() => openPdf(m)} className="text-slate-500 hover:text-emerald-600 p-1.5 rounded hover:bg-slate-50" title="Voir le PDF" data-testid={`meeting-pdf-${m.id}`}>
                  <FileText className="h-3.5 w-3.5" />
                </button>
                {canDelete && (
                  <button onClick={() => del(m)} className="text-slate-500 hover:text-rose-600 p-1.5 rounded hover:bg-slate-50" title="Supprimer" data-testid={`meeting-delete-${m.id}`}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            </article>
          ))}
        </div>
      )}

      {pdfDoc && (
        <div className="fixed inset-0 z-50 bg-black/70 p-4" data-testid="meeting-pdf-modal">
          <div className="h-full bg-white rounded-xl overflow-hidden">
            <PdfViewer src={pdfDoc.src} title={pdfDoc.title} onClose={() => setPdfDoc(null)} />
          </div>
        </div>
      )}

      {editorOpen && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-start justify-center p-3 overflow-y-auto" onClick={closeEditor} data-testid="meeting-editor">
          <div className="w-full max-w-3xl bg-white rounded-2xl shadow-2xl my-4" onClick={(e) => e.stopPropagation()}>
            <header className="flex items-center justify-between px-5 py-3 border-b border-slate-200">
              <h2 className="font-display font-bold text-slate-900 inline-flex items-center gap-2">
                <ClipboardList className="h-5 w-5 text-fuchsia-600" />
                {editing ? `Modifier ${editing.numero}` : "Nouveau PV de réunion"}
              </h2>
              <button onClick={closeEditor} disabled={saving} className="text-slate-400 hover:text-slate-700"><X className="h-4 w-4" /></button>
            </header>
            <div className="p-5 space-y-3">
              <input
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                placeholder="Titre / Objet de la réunion…"
                className="w-full px-3 py-2 rounded-lg ring-1 ring-slate-300 focus:ring-2 focus:ring-fuchsia-400 outline-none text-sm font-medium"
                data-testid="meeting-form-title"
              />
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[11px] font-semibold text-slate-600">Date de la réunion *</label>
                  <input
                    type="date"
                    value={form.meeting_date}
                    onChange={(e) => setForm({ ...form, meeting_date: e.target.value })}
                    className="w-full mt-0.5 px-3 py-2 rounded-lg ring-1 ring-slate-300 text-sm"
                    data-testid="meeting-form-date"
                  />
                </div>
                <div>
                  <label className="text-[11px] font-semibold text-slate-600">Heure de début (auto)</label>
                  <input
                    type="time"
                    value={(form.started_at || "").substring(11, 16)}
                    onChange={(e) => {
                      const [h, m] = e.target.value.split(":");
                      const d = new Date(form.started_at || nowIso());
                      d.setHours(Number(h || 0), Number(m || 0), 0, 0);
                      setForm({ ...form, started_at: d.toISOString() });
                    }}
                    className="w-full mt-0.5 px-3 py-2 rounded-lg ring-1 ring-slate-300 text-sm"
                    data-testid="meeting-form-start"
                  />
                </div>
              </div>
              <input
                value={form.attendees}
                onChange={(e) => setForm({ ...form, attendees: e.target.value })}
                placeholder="Participants (libre) — ex : Jean D., Marie L., Yves K."
                className="w-full px-3 py-2 rounded-lg ring-1 ring-slate-300 text-sm"
                data-testid="meeting-form-attendees"
              />
              <RichEditor
                value={form.body_html}
                onChange={(html) => setForm((f) => ({ ...f, body_html: html }))}
                accent="#c026d3"
                aiEnabled={aiEnabled}
              />
              <p className="text-[11px] text-slate-500 inline-flex items-center gap-1 italic">
                <Clock className="h-3 w-3" />
                L'heure de fin sera automatiquement enregistrée lors du clic sur « Enregistrer ».
              </p>
            </div>
            <footer className="px-5 py-3 border-t border-slate-200 flex justify-end gap-2">
              <button onClick={closeEditor} disabled={saving} className="px-4 py-2 rounded-lg ring-1 ring-slate-200 hover:bg-slate-50 text-sm" data-testid="meeting-form-cancel">
                Annuler
              </button>
              <button onClick={save} disabled={saving} className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-fuchsia-600 hover:bg-fuchsia-700 text-white text-sm disabled:opacity-60" data-testid="meeting-form-save">
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                Enregistrer
              </button>
            </footer>
          </div>
        </div>
      )}
    </div>
  );
}
