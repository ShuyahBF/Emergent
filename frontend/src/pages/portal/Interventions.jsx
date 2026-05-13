import React, { useEffect, useMemo, useRef, useState } from "react";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Plus, X, RefreshCw, Trash2, Wrench, Mic, MicOff, Square, Play, Pause, Building2 } from "lucide-react";
import { toast } from "sonner";

const ELEVATED = new Set(["Moderation", "Administrateur", "Superviseur"]);
const ADMIN_LEVEL = new Set(["Administrateur", "Superviseur"]);
function isElevated(user) {
  if (!user) return false;
  if (user.role === "admin" || user.role === "superviseur") return true;
  return ELEVATED.has(user.tracked_role);
}
function canDelete(user) {
  if (!user) return false;
  if (user.role === "admin" || user.role === "superviseur") return true;
  return ADMIN_LEVEL.has(user.tracked_role);
}

const STATUSES = [
  { value: "planned", label: "Planifiée", color: "bg-sky-100 text-sky-700" },
  { value: "in_progress", label: "En cours", color: "bg-amber-100 text-amber-700" },
  { value: "completed", label: "Terminée", color: "bg-emerald-100 text-emerald-700" },
  { value: "cancelled", label: "Annulée", color: "bg-slate-100 text-slate-600" },
];

export default function ClientInterventions() {
  const { user } = useAuth();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [clients, setClients] = useState([]);
  // Iter34y — Filtre par client lié (en-tête de colonne)
  const [clientFilter, setClientFilter] = useState("all");

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/me/interventions");
      setItems(r.data || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally { setLoading(false); }
  };
  const loadClients = async () => {
    try {
      const r = await apiClient.get("/me/clients");
      setClients(r.data || []);
    } catch { /* noop */ }
  };
  useEffect(() => { load(); loadClients(); }, []);

  const clientLabel = (cid) => {
    const c = clients.find((x) => x.id === cid);
    return c ? (c.company || c.full_name || c.id?.slice(0, 8)) : "—";
  };

  const filtered = useMemo(() => {
    if (clientFilter === "all") return items;
    return items.filter((i) => i.client_id === clientFilter);
  }, [items, clientFilter]);

  const distinctClientIds = useMemo(() => {
    const set = new Set();
    items.forEach((i) => i.client_id && set.add(i.client_id));
    return Array.from(set);
  }, [items]);

  const del = async (id) => {
    if (!window.confirm("Supprimer cette intervention ?")) return;
    try {
      await apiClient.delete(`/me/interventions/${id}`);
      toast.success("Intervention supprimée");
      await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const elevated = isElevated(user);
  const deletable = canDelete(user);

  return (
    <div className="space-y-6" data-testid="client-interventions-page">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-display font-bold">Historique de nos interventions</h1>
          <p className="text-sm text-slate-500">Détail de toutes les interventions réalisées — sélectionnez le Client lié pour filtrer.</p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button onClick={load} disabled={loading} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 px-3 py-2 text-sm disabled:opacity-60" data-testid="interventions-refresh">
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Actualiser
          </button>
          {elevated && (
            <button onClick={() => setShowCreate(true)} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light" data-testid="interventions-create-btn">
              <Plus className="h-4 w-4" /> Nouvelle intervention
            </button>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white overflow-x-auto">
        <table className="w-full text-sm min-w-[860px]">
          <thead className="bg-slate-50 text-xs uppercase text-slate-600">
            <tr>
              <th className="text-left px-4 py-3">Référence</th>
              <th className="text-left px-4 py-3">Titre</th>
              <th className="text-left px-4 py-3">
                <div className="flex items-center gap-2">
                  <Building2 className="h-3 w-3" />
                  <span>Client lié</span>
                  <select
                    value={clientFilter}
                    onChange={(e) => setClientFilter(e.target.value)}
                    className="rounded border border-slate-300 px-1.5 py-0.5 text-[10px] font-normal normal-case bg-white"
                    data-testid="interventions-filter-client"
                    title="Filtrer par Client lié"
                  >
                    <option value="all">Tous ({items.length})</option>
                    {distinctClientIds.map((cid) => (
                      <option key={cid} value={cid}>{clientLabel(cid)} ({items.filter((i) => i.client_id === cid).length})</option>
                    ))}
                  </select>
                </div>
              </th>
              <th className="text-left px-4 py-3">Date</th>
              <th className="text-left px-4 py-3">Technicien</th>
              <th className="text-left px-4 py-3">Statut</th>
              <th className="text-left px-4 py-3">Note vocale</th>
              {deletable && <th className="text-right px-4 py-3">Actions</th>}
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={8} className="px-4 py-10 text-center text-slate-500">Chargement…</td></tr>}
            {!loading && filtered.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-10 text-center text-slate-500">{clientFilter === "all" ? "Aucune intervention enregistrée." : "Aucune intervention pour ce client."}</td></tr>
            )}
            {filtered.map((i) => {
              const status = STATUSES.find((s) => s.value === i.status) || { label: i.status, color: "bg-slate-100 text-slate-700" };
              return (
                <tr key={i.id} className="border-t border-slate-100 hover:bg-sky-50/60" data-testid={`intervention-row-${i.id}`}>
                  <td className="px-4 py-3 text-xs font-mono text-slate-500">{i.intervention_number || "—"}</td>
                  <td className="px-4 py-3 font-medium text-slate-800">
                    {i.title}
                    {i.description && <p className="text-xs text-slate-500 font-normal mt-0.5 line-clamp-1">{i.description}</p>}
                  </td>
                  <td className="px-4 py-3 text-slate-600 text-xs">
                    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 ring-1 ring-emerald-200" data-testid={`intervention-client-${i.id}`}>
                      <Building2 className="h-3 w-3" /> {clientLabel(i.client_id)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-600">{i.intervention_date && new Date(i.intervention_date).toLocaleDateString("fr-FR")}</td>
                  <td className="px-4 py-3 text-slate-600">{i.technician || "-"}</td>
                  <td className="px-4 py-3"><span className={`text-xs px-2 py-1 rounded ${status.color}`}>{status.label}</span></td>
                  <td className="px-4 py-3">
                    {i.voice_note_url ? (
                      <audio controls src={i.voice_note_url} className="h-8 max-w-[180px]" data-testid={`intervention-audio-${i.id}`} />
                    ) : <span className="text-[10px] text-slate-400">—</span>}
                  </td>
                  {deletable && (
                    <td className="px-4 py-3 text-right">
                      <button onClick={() => del(i.id)} className="inline-flex items-center gap-1 text-xs text-rose-600 hover:underline" data-testid={`intervention-delete-${i.id}`}>
                        <Trash2 className="h-3.5 w-3.5" /> Supprimer
                      </button>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {showCreate && (
        <CreateInterventionModal
          user={user}
          clients={clients}
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); load(); }}
        />
      )}
    </div>
  );
}

// ============================================================
// Iter34y — Create intervention modal with Client picker + voice note
// ============================================================
const CreateInterventionModal = ({ user, clients, onClose, onCreated }) => {
  const [form, setForm] = useState({
    title: "",
    description: "",
    intervention_date: new Date().toISOString().slice(0, 10),
    technician: "",
    status: "completed",
    duration_hours: "",
    client_id: user?.client_id || user?.parent_client_id || user?.id || "",
    voice_note_url: "",
  });
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!form.client_id) { toast.error("Client lié requis"); return; }
    if (!form.title.trim()) { toast.error("Le titre est requis"); return; }
    if (!form.intervention_date) { toast.error("Date requise"); return; }
    setSaving(true);
    try {
      const payload = {
        client_id: form.client_id,
        title: form.title.trim(),
        description: form.description || null,
        status: form.status,
        intervention_date: new Date(form.intervention_date).toISOString(),
        technician: form.technician || null,
        duration_hours: form.duration_hours ? Number(form.duration_hours) : null,
        attachments: [],
        voice_note_url: form.voice_note_url || null,
      };
      await apiClient.post("/me/interventions", payload);
      toast.success("Intervention créée");
      onCreated();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur lors de la création");
    } finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40" onClick={(e) => e.target === e.currentTarget && onClose()} data-testid="intervention-create-modal">
      <div className="w-full max-w-lg rounded-2xl bg-white shadow-2xl p-6 space-y-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-display font-bold inline-flex items-center gap-2">
            <Wrench className="h-5 w-5 text-sawali-blue" /> Nouvelle intervention
          </h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900" data-testid="intervention-create-close"><X className="h-4 w-4" /></button>
        </div>
        <div>
          <label className="block text-xs font-semibold mb-1 inline-flex items-center gap-1">
            <Building2 className="h-3 w-3 text-sawali-blue" /> Client lié *
          </label>
          <select
            value={form.client_id}
            onChange={(e) => setForm({ ...form, client_id: e.target.value })}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            data-testid="intervention-field-client"
          >
            <option value="">— Sélectionnez un client —</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>{c.company || c.full_name}{c.client_code ? ` · ${c.client_code}` : ""}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-semibold mb-1">Titre *</label>
          <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Mise à jour du logiciel comptable" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="intervention-field-title" />
        </div>
        <div>
          <label className="block text-xs font-semibold mb-1">Description</label>
          <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} rows={3} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="intervention-field-description" />
        </div>
        <div className="grid sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-semibold mb-1">Date *</label>
            <input type="date" value={form.intervention_date} onChange={(e) => setForm({ ...form, intervention_date: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="intervention-field-date" />
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">Statut</label>
            <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="intervention-field-status">
              {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">Technicien</label>
            <input value={form.technician} onChange={(e) => setForm({ ...form, technician: e.target.value })} placeholder="Nom du technicien" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="intervention-field-technician" />
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">Durée (heures)</label>
            <input type="number" step="0.25" value={form.duration_hours} onChange={(e) => setForm({ ...form, duration_hours: e.target.value })} placeholder="2.5" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="intervention-field-duration" />
          </div>
        </div>

        <VoiceNoteRecorder
          value={form.voice_note_url}
          onChange={(url) => setForm({ ...form, voice_note_url: url })}
        />

        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="text-sm rounded-lg bg-slate-100 hover:bg-slate-200 px-4 py-2">Annuler</button>
          <button onClick={submit} disabled={saving} className="text-sm rounded-lg bg-sawali-blue hover:bg-sawali-blue-light text-white px-4 py-2 disabled:opacity-50" data-testid="intervention-create-save">
            {saving ? "Création…" : "Créer"}
          </button>
        </div>
      </div>
    </div>
  );
};

// ============================================================
// Iter34y — Voice note recorder (MediaRecorder → /me/upload-audio)
// Returns the absolute URL of the stored audio in onChange.
// ============================================================
function VoiceNoteRecorder({ value, onChange }) {
  const [recording, setRecording] = useState(false);
  const [uploading, setUploading] = useState(false);
  const mediaRef = useRef(null);
  const chunksRef = useRef([]);

  const start = async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof window.MediaRecorder === "undefined") {
      toast.error("Votre navigateur ne supporte pas l'enregistrement audio.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
      const mime = candidates.find((m) => window.MediaRecorder.isTypeSupported && window.MediaRecorder.isTypeSupported(m)) || "";
      const rec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      chunksRef.current = [];
      rec.ondataavailable = (e) => e.data && e.data.size && chunksRef.current.push(e.data);
      rec.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: rec.mimeType || "audio/webm" });
        stream.getTracks().forEach((t) => t.stop());
        setUploading(true);
        try {
          const fd = new FormData();
          const ext = (rec.mimeType || "audio/webm").split(";")[0].split("/")[1] || "webm";
          fd.append("file", blob, `intervention-${Date.now()}.${ext}`);
          const r = await apiClient.post("/me/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
          if (r.data?.public_url || r.data?.url) {
            onChange(r.data.public_url || r.data.url);
            toast.success("Note vocale enregistrée");
          } else {
            toast.error("Upload échoué");
          }
        } catch (err) {
          toast.error(err?.response?.data?.detail || "Erreur upload audio");
        } finally { setUploading(false); }
      };
      rec.start();
      mediaRef.current = rec;
      setRecording(true);
    } catch (err) {
      toast.error("Accès au micro refusé");
    }
  };
  const stop = () => {
    if (mediaRef.current && mediaRef.current.state !== "inactive") {
      mediaRef.current.stop();
      mediaRef.current = null;
    }
    setRecording(false);
  };

  return (
    <div className="rounded-lg ring-1 ring-amber-200 bg-amber-50/50 p-3 space-y-2" data-testid="intervention-voice-note">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <label className="text-xs font-semibold inline-flex items-center gap-1 text-amber-900">
          <Mic className="h-3.5 w-3.5" /> Note vocale (facultative)
        </label>
        {!recording && !uploading && (
          <button type="button" onClick={start} className="inline-flex items-center gap-1.5 rounded-lg bg-amber-600 text-white text-xs px-3 py-1.5 hover:bg-amber-700" data-testid="intervention-voice-start">
            <Mic className="h-3 w-3" /> Démarrer
          </button>
        )}
        {recording && (
          <button type="button" onClick={stop} className="inline-flex items-center gap-1.5 rounded-lg bg-rose-600 text-white text-xs px-3 py-1.5 hover:bg-rose-700 animate-pulse" data-testid="intervention-voice-stop">
            <Square className="h-3 w-3" /> Arrêter
          </button>
        )}
        {uploading && (
          <span className="inline-flex items-center gap-1.5 text-xs text-amber-700"><RefreshCw className="h-3 w-3 animate-spin" /> Upload en cours…</span>
        )}
      </div>
      {value && (
        <div className="flex items-center gap-2">
          <audio controls src={value} className="flex-1 h-8" data-testid="intervention-voice-preview" />
          <button type="button" onClick={() => onChange("")} className="text-xs text-rose-600 hover:underline inline-flex items-center gap-1" data-testid="intervention-voice-remove">
            <MicOff className="h-3 w-3" /> Supprimer
          </button>
        </div>
      )}
    </div>
  );
}
