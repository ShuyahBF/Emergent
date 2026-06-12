// S-iter39b — PV de réunions internes (Procès-Verbal) — création, édition,
// liste, impression et export PDF.
import React, { useEffect, useMemo, useState, useRef } from "react";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import {
  ClipboardList, Plus, Edit, Trash2, X, Search, FileText, Printer, Eye, Save, Loader2, Clock, ShieldCheck, Lock, Undo2,
} from "lucide-react";
import { RichEditor } from "@/pages/portal/UserNotes";
import { useNavigate, useParams } from "react-router-dom";
import PdfViewer from "@/components/PdfViewer";
import TenantSharingToggle from "@/components/TenantSharingToggle";

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
  signers: [],
  participants: [],
  shared_with_tenant: false,
  editable_by_tenant: false,
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
  // S-iter39d (fix #1) — Tenant users (for signers + participants dropdowns)
  const [tenantUsers, setTenantUsers] = useState([]);

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

  // S-iter39d (fix #1) — Pull tenant users for signer/participant dropdowns
  useEffect(() => {
    apiClient.get("/me/tenant-users")
      .then((r) => setTenantUsers(r.data?.items || []))
      .catch(() => setTenantUsers([]));
  }, []);

  // Cached id → label resolver for view + card display
  const userLabel = (id) => {
    if (typeof id === "string" && id.includes("@")) return `✉ ${id} (externe)`;
    const u = tenantUsers.find((x) => x.value === id);
    return u ? u.label : id;
  };

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
        signers: r.data.signers || [],
        participants: r.data.participants || [],
        shared_with_tenant: !!r.data.shared_with_tenant,
        editable_by_tenant: !!r.data.editable_by_tenant,
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
          signers: form.signers,
          participants: form.participants,
          shared_with_tenant: !!form.shared_with_tenant,
          editable_by_tenant: !!form.editable_by_tenant,
        });
        toast.success(`PV ${r.data.numero || ""} mis à jour`);
      } else {
        const r = await apiClient.post("/me/meetings", {
          meeting_date: form.meeting_date,
          started_at: form.started_at,
          title: form.title.trim(),
          attendees: form.attendees,
          body_html: form.body_html,
          signers: form.signers,
          participants: form.participants,
          shared_with_tenant: !!form.shared_with_tenant,
          editable_by_tenant: !!form.editable_by_tenant,
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

  // S017 — Signature électronique du PV (admin/superviseur uniquement)
  const sign = async (m) => {
    if (!window.confirm(`Signer le PV « ${m.numero} » ?\n\nLe document sera verrouillé : aucune modification ne sera plus possible tant que la signature n'est pas annulée.`)) return;
    try {
      const r = await apiClient.post(`/me/meetings/${m.id}/sign`);
      toast.success(`PV signé par ${r.data?.signed_by_name || "vous"}`);
      if (viewing?.id === m.id) setViewing(r.data);
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
  };
  const unsign = async (m) => {
    if (!window.confirm(`Annuler la signature du PV « ${m.numero} » ?\n\nLe document redeviendra modifiable.`)) return;
    try {
      const r = await apiClient.post(`/me/meetings/${m.id}/unsign`);
      toast.success("Signature annulée — PV à nouveau modifiable");
      if (viewing?.id === m.id) setViewing(r.data);
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
  };

  const openPdf = async (m) => {
    try {
      // Iter43-fix — Le PDF est protégé par JWT. On le télécharge en blob
      // via apiClient (qui ajoute le header Authorization), puis on crée un
      // Object URL pour le passer à PdfViewer / window.open.
      const r = await apiClient.get(`/me/meetings/${m.id}/pdf`, { responseType: "blob" });
      const blobUrl = URL.createObjectURL(r.data);
      setPdfDoc({ src: blobUrl, title: `${m.numero} — ${m.title}`, _revoke: blobUrl });
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Impossible de charger le PDF");
    }
  };

  const printDoc = async (m) => {
    try {
      const r = await apiClient.get(`/me/meetings/${m.id}/pdf`, { responseType: "blob" });
      const blobUrl = URL.createObjectURL(r.data);
      const w = window.open(blobUrl, "_blank", "noopener");
      // Révoque l'URL après ouverture (5 s) pour libérer la mémoire
      if (w) setTimeout(() => URL.revokeObjectURL(blobUrl), 5000);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Impossible d'ouvrir le PDF");
    }
  };

  // Révoque l'Object URL quand le viewer est fermé
  useEffect(() => () => {
    if (pdfDoc?._revoke) URL.revokeObjectURL(pdfDoc._revoke);
  }, [pdfDoc?._revoke]);

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
                <p className="text-xs text-slate-600 mt-1"><strong>Participants (libre) :</strong> {viewing.attendees}</p>
              )}
              {/* S-iter39d (fix #1) — Listes structurées des signataires + participants */}
              {Array.isArray(viewing.signers) && viewing.signers.length > 0 && (
                <p className="text-xs text-slate-600 mt-1" data-testid="meeting-view-signers">
                  <strong>Signataires obligatoires :</strong>{" "}
                  {viewing.signers.map(userLabel).join(", ")}
                </p>
              )}
              {Array.isArray(viewing.participants) && viewing.participants.length > 0 && (
                <p className="text-xs text-slate-600 mt-1" data-testid="meeting-view-participants">
                  <strong>Autres participants :</strong>{" "}
                  {viewing.participants.map(userLabel).join(", ")}
                </p>
              )}
              {/* S017 — Signature badge in the view modal header */}
              {viewing.signed_at && (
                <p className="mt-2 text-xs inline-flex items-center gap-1 bg-emerald-50 ring-1 ring-emerald-300 text-emerald-800 rounded-full px-2 py-0.5" data-testid="meeting-signed-badge">
                  <ShieldCheck className="h-3.5 w-3.5" />
                  Signé par <strong>{viewing.signed_by_name || viewing.signed_by_email}</strong> le {new Date(viewing.signed_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}
                  <Lock className="h-3 w-3 ml-0.5" />
                </p>
              )}
            </div>
            <div className="flex items-center gap-1">
              {(isAdminOrSup || elevatedTracked || viewing.author_id === user?.id) && !viewing.signed_at && (
                <button onClick={() => openEdit(viewing)} className="px-3 py-1.5 rounded ring-1 ring-slate-200 hover:bg-slate-50 text-xs inline-flex items-center gap-1" data-testid="meeting-edit-from-view">
                  <Edit className="h-3.5 w-3.5" /> Modifier
                </button>
              )}
              {/* S017 — Sign / Unsign (admin/sup only) */}
              {canDelete && !viewing.signed_at && (
                <button onClick={() => sign(viewing)} className="px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-700 text-white text-xs inline-flex items-center gap-1" data-testid="meeting-sign-from-view">
                  <ShieldCheck className="h-3.5 w-3.5" /> Valider et signer
                </button>
              )}
              {canDelete && viewing.signed_at && (
                <button onClick={() => unsign(viewing)} className="px-3 py-1.5 rounded ring-1 ring-amber-300 bg-amber-50 hover:bg-amber-100 text-amber-800 text-xs inline-flex items-center gap-1" data-testid="meeting-unsign-from-view" title="Annuler la signature pour pouvoir modifier le PV">
                  <Undo2 className="h-3.5 w-3.5" /> Annuler la signature
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
            <article key={m.id} className={`rounded-xl ring-1 bg-white p-4 transition ${m.signed_at ? "ring-emerald-300 hover:ring-2 hover:ring-emerald-400" : "ring-slate-200 hover:ring-2 hover:ring-fuchsia-300"}`} data-testid={`meeting-card-${m.id}`}>
              <div className="flex items-center justify-between gap-2">
                <p className="text-[10px] uppercase tracking-widest font-mono text-fuchsia-700">{m.numero}</p>
                {m.signed_at && (
                  <span className="text-[9px] inline-flex items-center gap-0.5 bg-emerald-100 text-emerald-800 ring-1 ring-emerald-300 rounded-full px-1.5 py-0.5 font-semibold" data-testid={`meeting-signed-badge-${m.id}`} title={`Signé par ${m.signed_by_name || m.signed_by_email} le ${new Date(m.signed_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}`}>
                    <ShieldCheck className="h-2.5 w-2.5" /> SIGNÉ
                  </span>
                )}
              </div>
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
                {(isAdminOrSup || elevatedTracked || m.author_id === user?.id) && !m.signed_at && (
                  <button onClick={() => openEdit(m)} className="text-slate-500 hover:text-sawali-blue p-1.5 rounded hover:bg-slate-50" title="Modifier" data-testid={`meeting-edit-${m.id}`}>
                    <Edit className="h-3.5 w-3.5" />
                  </button>
                )}
                {/* S017 — Sign button on list card (admin/sup only, when not yet signed) */}
                {canDelete && !m.signed_at && (
                  <button onClick={() => sign(m)} className="text-emerald-600 hover:text-emerald-800 p-1.5 rounded hover:bg-emerald-50" title="Valider et signer ce PV (verrouille toute modification)" data-testid={`meeting-sign-${m.id}`}>
                    <ShieldCheck className="h-3.5 w-3.5" />
                  </button>
                )}
                {canDelete && m.signed_at && (
                  <button onClick={() => unsign(m)} className="text-amber-600 hover:text-amber-800 p-1.5 rounded hover:bg-amber-50" title="Annuler la signature pour pouvoir modifier" data-testid={`meeting-unsign-${m.id}`}>
                    <Undo2 className="h-3.5 w-3.5" />
                  </button>
                )}
                <button onClick={() => openPdf(m)} className="text-slate-500 hover:text-emerald-600 p-1.5 rounded hover:bg-slate-50" title="Voir le PDF" data-testid={`meeting-pdf-${m.id}`}>
                  <FileText className="h-3.5 w-3.5" />
                </button>
                {canDelete && !m.signed_at && (
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
                placeholder="Participants (libre, optionnel) — ex : Jean D., Marie L."
                className="w-full px-3 py-2 rounded-lg ring-1 ring-slate-300 text-sm"
                data-testid="meeting-form-attendees"
              />
              {/* S-iter39d (fix #1) — Signers (ligne 1) + Other participants (ligne 2) */}
              <MultiUserPicker
                label="Signataires obligatoires (ligne 1) — signature requise"
                accent="emerald"
                options={tenantUsers}
                value={form.signers}
                onChange={(arr) => {
                  // Remove from participants if added to signers
                  setForm((f) => ({
                    ...f,
                    signers: arr,
                    participants: (f.participants || []).filter((id) => !arr.includes(id)),
                  }));
                }}
                testIdPrefix="meeting-signers"
              />
              <MultiUserPicker
                label="Autres participants (ligne 2) — sans signature"
                accent="slate"
                options={tenantUsers.filter((u) => !(form.signers || []).includes(u.value))}
                value={form.participants}
                onChange={(arr) => setForm((f) => ({ ...f, participants: arr }))}
                testIdPrefix="meeting-participants"
              />
              <RichEditor
                value={form.body_html}
                onChange={(html) => setForm((f) => ({ ...f, body_html: html }))}
                accent="#c026d3"
                aiEnabled={aiEnabled}
              />
              <TenantSharingToggle
                shared={form.shared_with_tenant}
                editable={form.editable_by_tenant}
                onChange={(next) => setForm((f) => ({ ...f, ...next }))}
                testidPrefix="meeting-tenant-sharing"
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

// S-iter39d (fix #1) — Reusable multi-select picker for tenant users.
// Renders a search input + clickable chip list for selected items + a
// suggestions popover. Compact (suitable for embedded inline use).
function MultiUserPicker({ label, options, value, onChange, accent = "slate", testIdPrefix }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const accentMap = {
    emerald: { ring: "ring-emerald-300", bg: "bg-emerald-50", txt: "text-emerald-900", chip: "bg-emerald-100 text-emerald-800 ring-emerald-300" },
    slate: { ring: "ring-slate-300", bg: "bg-slate-50", txt: "text-slate-700", chip: "bg-slate-100 text-slate-700 ring-slate-300" },
  };
  const c = accentMap[accent] || accentMap.slate;
  const valueIds = value || [];
  const selected = options.filter((o) => valueIds.includes(o.value));
  // 2026-02 — Support free-form email entries that don't map to a tenant user
  const externalEmails = valueIds.filter((v) => typeof v === "string" && v.includes("@") && !options.some((o) => o.value === v));
  const filtered = options.filter((o) => {
    if (valueIds.includes(o.value)) return false;
    if (!q) return true;
    const s = q.toLowerCase();
    return (o.label || "").toLowerCase().includes(s)
      || (o.email || "").toLowerCase().includes(s)
      || (o.role || "").toLowerCase().includes(s);
  }).slice(0, 50);

  const isEmailQuery = q.includes("@") && q.split("@")[1]?.includes(".");

  const add = (id) => {
    onChange([...(valueIds), id]);
    setQ("");
  };
  const addEmail = () => {
    const em = q.trim().toLowerCase();
    if (!em || !em.includes("@") || valueIds.includes(em)) return;
    onChange([...(valueIds), em]);
    setQ("");
  };
  const remove = (id) => onChange(valueIds.filter((x) => x !== id));

  return (
    <div className={`rounded-lg ring-1 ${c.ring} ${c.bg} p-2.5 space-y-2`} data-testid={testIdPrefix}>
      <label className={`text-[11px] font-semibold ${c.txt}`}>{label}</label>
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5" data-testid={`${testIdPrefix}-chips`}>
          {selected.map((u) => (
            <span key={u.value} className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full ring-1 ${c.chip}`} data-testid={`${testIdPrefix}-chip-${u.value}`}>
              {u.label}
              <span className="text-[9px] opacity-60">({u.role})</span>
              <button type="button" onClick={() => remove(u.value)} className="hover:bg-black/10 rounded-full p-0.5" aria-label={`Retirer ${u.label}`}>
                <X className="h-2.5 w-2.5" />
              </button>
            </span>
          ))}
        </div>
      )}
      {externalEmails.length > 0 && (
        <div className="flex flex-wrap gap-1.5" data-testid={`${testIdPrefix}-email-chips`}>
          {externalEmails.map((em) => (
            <span key={em} className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full ring-1 bg-violet-100 text-violet-800 ring-violet-300" data-testid={`${testIdPrefix}-email-chip-${em}`}>
              <span className="text-[9px] opacity-60">✉</span>
              {em}
              <span className="text-[9px] opacity-60">(externe)</span>
              <button type="button" onClick={() => remove(em)} className="hover:bg-black/10 rounded-full p-0.5" aria-label={`Retirer ${em}`}>
                <X className="h-2.5 w-2.5" />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="relative">
        <div className="flex items-center gap-1.5">
          <input
            type="text"
            value={q}
            onFocus={() => setOpen(true)}
            onChange={(e) => { setQ(e.target.value); setOpen(true); }}
            onBlur={() => setTimeout(() => setOpen(false), 150)}
            placeholder="Rechercher un utilisateur ou saisir un email externe…"
            className="flex-1 text-xs rounded-md ring-1 ring-slate-300 px-2 py-1.5 bg-white"
            data-testid={`${testIdPrefix}-input`}
            onKeyDown={(e) => {
              if (e.key === "Enter" && isEmailQuery) {
                e.preventDefault();
                addEmail();
              }
            }}
          />
          {isEmailQuery && (
            <button
              type="button"
              onMouseDown={(e) => { e.preventDefault(); addEmail(); }}
              className="text-[11px] px-2 py-1.5 rounded-md bg-violet-600 hover:bg-violet-700 text-white"
              data-testid={`${testIdPrefix}-add-email`}
            >
              + Ajouter email
            </button>
          )}
        </div>
        {open && filtered.length > 0 && (
          <div className="absolute z-30 left-0 right-0 top-full mt-1 max-h-60 overflow-y-auto bg-white rounded-md shadow-lg ring-1 ring-slate-200" data-testid={`${testIdPrefix}-suggestions`}>
            {filtered.map((u) => (
              <button
                key={u.value}
                type="button"
                onMouseDown={(e) => { e.preventDefault(); add(u.value); }}
                className="w-full text-left text-xs px-2.5 py-1.5 hover:bg-slate-50 flex items-center justify-between"
                data-testid={`${testIdPrefix}-option-${u.value}`}
              >
                <span>{u.label}</span>
                <span className="text-[10px] text-slate-400">{u.role}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
