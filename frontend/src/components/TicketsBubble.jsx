// Iter38r-fix9o-v2 (Item 6) — Floating "Open intervention ticket" bubble.
// Positioned at bottom-right, stacked above the Liluvine assistant and
// Internal Chat buttons (so it sits near the Liluvine bubble as requested).
//
// Required fields (v2): Client lié, Rapporteur, Date incident, AT LEAST one
// of Téléphone / WhatsApp. Once a Client is selected, the Rapporteur input
// becomes a datalist preloaded with that client's existing contacts.

import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Ticket as TicketIcon, X, Send } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";

export default function TicketsBubble() {
  const { user } = useAuth() || {};
  const navigate = useNavigate();
  const role = (user?.role || "").toLowerCase();
  const tracked = (user?.tracked_role || "").toLowerCase();
  const canCreate = ["admin", "superviseur", "moderateur"].includes(role)
    || ["admin", "superviseur", "moderateur"].includes(tracked);

  const [enabled, setEnabled] = useState(false);
  const [open, setOpen] = useState(false);
  const [clients, setClients] = useState([]);
  const [contacts, setContacts] = useState([]);
  const [reasons, setReasons] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [attachHistory, setAttachHistory] = useState(false);
  const [form, setForm] = useState({
    client_id: "",
    reason: "",
    contact_name: "",
    contact_phone: "",
    contact_whatsapp: "",
    incident_at: "",
    software: "",
    notes: "",
  });

  useEffect(() => {
    if (!canCreate) return;
    apiClient.get("/me/features")
      .then((r) => setEnabled(!!r.data?.features?.tickets_bubble))
      .catch(() => {});
  }, [canCreate]);

  useEffect(() => {
    if (!open) return;
    Promise.all([
      apiClient.get("/me/clients").catch(() => ({ data: [] })),
      apiClient.get("/me/intervention-reasons").catch(() => ({ data: { items: [] } })),
      apiClient.get("/me/contacts").catch(() => ({ data: [] })),
    ]).then(([cr, rr, ct]) => {
      setClients(Array.isArray(cr.data) ? cr.data : (cr.data?.items || []));
      setReasons(rr.data?.items || []);
      setContacts(Array.isArray(ct.data) ? ct.data : (ct.data?.items || []));
    });
  }, [open]);

  // When a Client lié is selected, derive the linked contacts (datalist)
  const linkedContacts = useMemo(() => {
    if (!form.client_id) return [];
    return contacts.filter((c) => c.client_id === form.client_id);
  }, [form.client_id, contacts]);

  // Auto-fill phone/whatsapp when the user types/picks an existing contact name
  useEffect(() => {
    if (!form.contact_name || linkedContacts.length === 0) return;
    const hit = linkedContacts.find((c) => (c.name || "").toLowerCase() === form.contact_name.toLowerCase());
    if (hit) {
      setForm((f) => ({
        ...f,
        contact_phone: f.contact_phone || hit.phone || "",
        contact_whatsapp: f.contact_whatsapp || hit.whatsapp || "",
      }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.contact_name, linkedContacts.length]);

  const submit = async (e) => {
    e.preventDefault();
    // Validation v2: client + reason + rapporteur + date
    if (!form.client_id) { toast.error("Sélectionnez un client lié"); return; }
    if (!form.reason.trim()) { toast.error("Le motif est obligatoire"); return; }
    if (!form.contact_name.trim()) { toast.error("Le rapporteur est obligatoire"); return; }
    if (!form.incident_at) { toast.error("La date de l'incident est obligatoire"); return; }
    // 2026-02 fork iter107 — Si aucun téléphone n'est renseigné et qu'aucun
    // contact ne correspond au rapporteur, demander confirmation pour forcer
    // l'enregistrement (au lieu de bloquer).
    const hasPhone = form.contact_phone.trim() || form.contact_whatsapp.trim();
    if (!hasPhone) {
      const matched = linkedContacts.find((c) => (c.name || "").toLowerCase() === form.contact_name.toLowerCase());
      if (!matched) {
        const ok = window.confirm(
          "Aucun numéro (Téléphone ou WhatsApp) n'est renseigné, et le rapporteur ne correspond à aucun contact du client lié.\n\nForcer l'enregistrement du ticket (aucun WA ne sera envoyé) ?"
        );
        if (!ok) return;
      }
    }
    setSubmitting(true);
    try {
      const payload = {
        client_id: form.client_id,
        reason: form.reason,
        contact_name: form.contact_name,
        // backend uses a single `contact_phone` field; pass WA if no phone
        contact_phone: form.contact_phone || form.contact_whatsapp || undefined,
        contact_whatsapp: form.contact_whatsapp || undefined,
        incident_at: new Date(form.incident_at).toISOString(),
        software: form.software || undefined,
        notes: form.notes || undefined,
        attach_wa_sms_history: attachHistory,
      };
      const r = await apiClient.post("/me/tickets", payload);
      toast.success("Ticket créé. Modèle WA envoyé au contact si numéro fourni.");
      // 2026-02 fork iter107 — Proposer d'ajouter le rapporteur au registre des
      // contacts s'il n'existe pas déjà (et si un téléphone a été saisi).
      const matched = linkedContacts.find((c) => (c.name || "").toLowerCase() === form.contact_name.toLowerCase());
      if (!matched && (form.contact_phone.trim() || form.contact_whatsapp.trim())) {
        const save = window.confirm(
          `Le rapporteur "${form.contact_name}" n'existe pas dans le registre des contacts du client lié.\n\nL'ajouter automatiquement pour les prochaines saisies ?`
        );
        if (save) {
          try {
            await apiClient.post("/me/contacts", {
              name: form.contact_name.trim(),
              phone: form.contact_phone.trim() || "",
              whatsapp: form.contact_whatsapp.trim() || "",
              company: (clients.find((c) => c.id === form.client_id)?.company) || "",
              shared: false,
            });
            toast.success("Contact ajouté au registre.");
          } catch (err) {
            toast.warning("Ticket créé mais l'ajout du contact a échoué : " + (err?.response?.data?.detail || "erreur"));
          }
        }
      }
      setOpen(false);
      navigate(`/portal/interventions${r.data?.id ? `?focus=${r.data.id}` : ""}`);
      setForm({ client_id: "", reason: "", contact_name: "", contact_phone: "", contact_whatsapp: "", incident_at: "", software: "", notes: "" });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur création ticket");
    } finally {
      setSubmitting(false);
    }
  };

  if (!canCreate || !enabled) return null;

  return (
    <>
      {/* Floating bubble — bottom-right, stacked above InternalChat + Liluvine
          (mobile: bottom-36, sm+: bottom-44). z-[55] sits just under modals. */}
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed bottom-36 right-4 sm:bottom-44 sm:right-6 z-[55] h-12 w-12 rounded-full bg-slate-900 hover:bg-slate-800 text-white shadow-2xl ring-2 ring-white/10 transition-transform hover:scale-105 flex items-center justify-center"
        title="Ouvrir un ticket d'intervention"
        data-testid="tickets-bubble-trigger"
      >
        <TicketIcon className="h-5 w-5 text-white" />
      </button>

      {open && (
        <div className="fixed inset-0 z-[80] bg-black/50 flex items-center justify-center p-4" onClick={() => setOpen(false)}>
          <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full max-h-[90vh] overflow-hidden flex flex-col" onClick={(e) => e.stopPropagation()} data-testid="tickets-bubble-modal">
            <header className="px-5 py-3 border-b border-slate-200 flex items-center justify-between">
              <h3 className="font-display font-bold text-slate-800 inline-flex items-center gap-2">
                <TicketIcon className="h-4 w-4 text-slate-700" /> Nouveau ticket d'intervention
              </h3>
              <button onClick={() => setOpen(false)} className="text-slate-400 hover:text-slate-700"><X className="h-4 w-4" /></button>
            </header>
            <form onSubmit={submit} className="flex-1 overflow-y-auto p-5 space-y-3">
              <label className="block">
                <span className="text-xs font-medium text-slate-600">Client lié *</span>
                <select required value={form.client_id} onChange={(e) => setForm({ ...form, client_id: e.target.value, contact_name: "" })} className="mt-1 w-full text-sm rounded-lg border border-slate-300 px-3 py-2 bg-white" data-testid="tickets-bubble-client">
                  <option value="">-- Choisir --</option>
                  {clients.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.client_code ? `[${c.client_code}] ` : ""}{c.full_name || c.company || c.name || "(sans nom)"}
                    </option>
                  ))}
                </select>
              </label>

              <label className="block">
                <span className="text-xs font-medium text-slate-600">Motif *</span>
                {reasons.length > 0 ? (
                  <>
                    <select value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} className="mt-1 w-full text-sm rounded-lg border border-slate-300 px-3 py-2 bg-white" data-testid="tickets-bubble-reason-select">
                      <option value="">-- Choisir un motif ou saisir librement --</option>
                      {reasons.map((r) => <option key={r.id || r.label} value={r.label}>{r.label}</option>)}
                    </select>
                    <input type="text" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} placeholder="… ou motif libre" className="mt-1 w-full text-sm rounded-lg border border-slate-300 px-3 py-2" data-testid="tickets-bubble-reason-free" />
                  </>
                ) : (
                  <input type="text" required value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} className="mt-1 w-full text-sm rounded-lg border border-slate-300 px-3 py-2" data-testid="tickets-bubble-reason-free" />
                )}
              </label>

              <label className="block">
                <span className="text-xs font-medium text-slate-600">
                  Rapporteur (contact) *{form.client_id && linkedContacts.length > 0 ? ` — ${linkedContacts.length} contact(s) lié(s)` : ""}
                </span>
                <input
                  type="text"
                  required
                  list="tickets-bubble-rapporteur-list"
                  value={form.contact_name}
                  onChange={(e) => setForm({ ...form, contact_name: e.target.value })}
                  placeholder={form.client_id && linkedContacts.length > 0 ? "Sélectionner ou saisir librement" : "Nom du rapporteur"}
                  className="mt-1 w-full text-sm rounded-lg border border-slate-300 px-3 py-2"
                  data-testid="tickets-bubble-contact-name"
                />
                <datalist id="tickets-bubble-rapporteur-list">
                  {linkedContacts.map((c) => <option key={c.id} value={c.name || ""} />)}
                </datalist>
              </label>

              <div className="grid grid-cols-2 gap-3">
                <label className="block">
                  <span className="text-xs font-medium text-slate-600">Téléphone</span>
                  <input
                    type="tel"
                    value={form.contact_phone}
                    onChange={(e) => setForm({ ...form, contact_phone: e.target.value })}
                    placeholder="+22670000000"
                    className="mt-1 w-full text-sm rounded-lg border border-slate-300 px-3 py-2 font-mono"
                    data-testid="tickets-bubble-contact-phone"
                  />
                </label>
                <label className="block">
                  <span className="text-xs font-medium text-slate-600">WhatsApp</span>
                  <input
                    type="tel"
                    value={form.contact_whatsapp}
                    onChange={(e) => setForm({ ...form, contact_whatsapp: e.target.value })}
                    placeholder="+22670000000"
                    className="mt-1 w-full text-sm rounded-lg border border-slate-300 px-3 py-2 font-mono"
                    data-testid="tickets-bubble-contact-whatsapp"
                  />
                </label>
              </div>
              <p className="text-[10px] text-slate-500 -mt-1">Au moins un des deux numéros est obligatoire.</p>

              <div className="grid grid-cols-2 gap-3">
                <label className="block">
                  <span className="text-xs font-medium text-slate-600">Date/heure incident *</span>
                  <input
                    type="datetime-local"
                    required
                    value={form.incident_at}
                    onChange={(e) => setForm({ ...form, incident_at: e.target.value })}
                    className="mt-1 w-full text-sm rounded-lg border border-slate-300 px-3 py-2"
                    data-testid="tickets-bubble-incident-at"
                  />
                </label>
                <label className="block">
                  <span className="text-xs font-medium text-slate-600">Logiciel utilisé</span>
                  <input type="text" value={form.software} onChange={(e) => setForm({ ...form, software: e.target.value })} placeholder="téléphone / WA / SAWALI…" className="mt-1 w-full text-sm rounded-lg border border-slate-300 px-3 py-2" data-testid="tickets-bubble-software" />
                </label>
              </div>

              <label className="block">
                <span className="text-xs font-medium text-slate-600">Complément d'information</span>
                <textarea rows={3} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className="mt-1 w-full text-sm rounded-lg border border-slate-300 px-3 py-2 resize-y" data-testid="tickets-bubble-notes" />
              </label>

              <label className="flex items-center gap-2 text-xs text-slate-600">
                <input type="checkbox" checked={attachHistory} onChange={(e) => setAttachHistory(e.target.checked)} data-testid="tickets-bubble-attach-history" />
                Joindre l'historique des conversations WA/SMS du contact
              </label>

              <div className="flex justify-end gap-2 pt-2 border-t border-slate-100">
                <button type="button" onClick={() => setOpen(false)} className="text-sm rounded-lg ring-1 ring-slate-300 px-3 py-1.5 hover:bg-slate-50">Annuler</button>
                <button type="submit" disabled={submitting} className="text-sm rounded-lg bg-slate-900 hover:bg-slate-800 text-white px-3 py-1.5 inline-flex items-center gap-1 disabled:opacity-50" data-testid="tickets-bubble-submit">
                  <Send className="h-3.5 w-3.5" /> {submitting ? "Création…" : "Créer le ticket"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
