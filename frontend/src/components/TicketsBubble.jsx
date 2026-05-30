// Iter38r-fix9o (Item 6) — Floating "Open intervention ticket" bubble.
// Same style as the Direct Chat bubble, but positioned at bottom-LEFT (just
// before the sidebar). The black bubble carries a WHITE Ticket icon. Click
// opens a quick-create modal; the underlying ticket is then opened on the
// /portal/interventions page.

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
  const [reasons, setReasons] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [attachHistory, setAttachHistory] = useState(false);
  const [form, setForm] = useState({
    client_id: "",
    reason: "",
    contact_name: "",
    contact_phone: "",
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
      apiClient.get("/me/clients").catch(() => ({ data: { items: [] } })),
      apiClient.get("/me/intervention-reasons").catch(() => ({ data: { items: [] } })),
    ]).then(([cr, rr]) => {
      setClients(cr.data?.items || cr.data || []);
      setReasons(rr.data?.items || rr.data || []);
    });
  }, [open]);

  const submit = async (e) => {
    e.preventDefault();
    if (!form.client_id || !form.reason.trim()) {
      toast.error("Client et motif requis");
      return;
    }
    setSubmitting(true);
    try {
      const payload = {
        client_id: form.client_id,
        reason: form.reason,
        contact_name: form.contact_name || undefined,
        contact_phone: form.contact_phone || undefined,
        incident_at: form.incident_at ? new Date(form.incident_at).toISOString() : undefined,
        software: form.software || undefined,
        notes: form.notes || undefined,
        attach_wa_sms_history: attachHistory,
      };
      const r = await apiClient.post("/me/tickets", payload);
      toast.success("Ticket créé. Modèle WA envoyé au contact si numéro fourni.");
      setOpen(false);
      navigate(`/portal/interventions${r.data?.id ? `?focus=${r.data.id}` : ""}`);
      setForm({ client_id: "", reason: "", contact_name: "", contact_phone: "", incident_at: "", software: "", notes: "" });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur création ticket");
    } finally {
      setSubmitting(false);
    }
  };

  if (!canCreate || !enabled) return null;

  return (
    <>
      {/* Floating bubble — bottom-LEFT, just before the sidebar (z-30 to sit
          under tooltips but above content) */}
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed bottom-6 left-6 z-30 h-12 w-12 rounded-full bg-slate-900 hover:bg-slate-800 text-white shadow-lg ring-2 ring-white/10 transition-transform hover:scale-105 flex items-center justify-center"
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
                <span className="text-xs font-medium text-slate-600">Client en compte *</span>
                <select required value={form.client_id} onChange={(e) => setForm({ ...form, client_id: e.target.value })} className="mt-1 w-full text-sm rounded-lg border border-slate-300 px-3 py-2 bg-white" data-testid="tickets-bubble-client">
                  <option value="">-- Choisir --</option>
                  {clients.map((c) => <option key={c.id} value={c.id}>{c.client_no ? `[${c.client_no}] ` : ""}{c.name || c.company_name}</option>)}
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
              <div className="grid grid-cols-2 gap-3">
                <label className="block">
                  <span className="text-xs font-medium text-slate-600">Contact (nom)</span>
                  <input type="text" value={form.contact_name} onChange={(e) => setForm({ ...form, contact_name: e.target.value })} className="mt-1 w-full text-sm rounded-lg border border-slate-300 px-3 py-2" data-testid="tickets-bubble-contact-name" />
                </label>
                <label className="block">
                  <span className="text-xs font-medium text-slate-600">Téléphone (facultatif, WA si présent)</span>
                  <input type="tel" value={form.contact_phone} onChange={(e) => setForm({ ...form, contact_phone: e.target.value })} placeholder="22670000000" className="mt-1 w-full text-sm rounded-lg border border-slate-300 px-3 py-2 font-mono" data-testid="tickets-bubble-contact-phone" />
                </label>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <label className="block">
                  <span className="text-xs font-medium text-slate-600">Date/heure incident</span>
                  <input type="datetime-local" value={form.incident_at} onChange={(e) => setForm({ ...form, incident_at: e.target.value })} className="mt-1 w-full text-sm rounded-lg border border-slate-300 px-3 py-2" data-testid="tickets-bubble-incident-at" />
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
