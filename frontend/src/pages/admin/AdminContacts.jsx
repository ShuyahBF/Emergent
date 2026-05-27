import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { UserPlus, Check, X } from "lucide-react";
import { toast } from "sonner";

const TRACKED_ROLES = ["Consultation", "Edition", "Moderation", "Administrateur", "Superviseur", "Comptable"];

export default function AdminContacts() {
  const [items, setItems] = useState([]);
  const [clients, setClients] = useState([]);
  const [savingFor, setSavingFor] = useState(null); // contact object
  const [form, setForm] = useState({ client_id: "", role: "Consultation", department: "" });
  const [submitting, setSubmitting] = useState(false);

  const load = () => apiClient.get("/admin/contacts").then((r) => setItems(r.data)).catch(() => {});

  useEffect(() => {
    load();
    apiClient.get("/admin/clients").then((r) => setClients(r.data)).catch(() => {});
  }, []);

  const openSave = (contact) => {
    setSavingFor(contact);
    setForm({ client_id: "", role: "Consultation", department: "" });
  };

  const closeSave = () => { setSavingFor(null); };

  const submitSave = async (e) => {
    e.preventDefault();
    if (!form.client_id) { toast.error("Sélectionnez un client"); return; }
    setSubmitting(true);
    try {
      const r = await apiClient.post(`/me/contacts/${savingFor.id}/save-as-tracked-user`, form);
      const pwd = r.data?.generated_password;
      const sent = r.data?.email_sent;
      if (pwd) {
        try { await navigator.clipboard.writeText(pwd); } catch { /* ignore clipboard errors */ }
        toast.success(`Utilisateur suivi créé · mot de passe : ${pwd} ${sent ? "(envoyé par email)" : "(à transmettre)"}`, { duration: 12000 });
      } else {
        toast.success("Utilisateur suivi enregistré");
      }
      closeSave();
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setSubmitting(false); }
  };

  return (
    <div className="space-y-6" data-testid="admin-contacts-page">
      <div><h1 className="text-2xl font-display font-bold">Messages reçus</h1></div>
      <div className="space-y-3">
        {items.length === 0 && <p className="text-slate-500">Aucun message.</p>}
        {items.map((c) => {
          const alreadySaved = !!c.saved_as_tracked_user_id;
          return (
            <div key={c.id} className="rounded-xl border border-slate-200 bg-white p-5" data-testid={`contact-${c.id}`}>
              <div className="flex items-start justify-between flex-wrap gap-2">
                <div className="min-w-0">
                  <p className="font-semibold">
                    {c.name} <span className="text-slate-500 font-normal text-sm">— {c.email}</span>
                    {c.phone && <span className="text-slate-500 font-normal text-sm"> · {c.phone}</span>}
                  </p>
                  {c.subject && <p className="text-sm text-slate-700 mt-1">{c.subject}</p>}
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  <span className="text-xs text-slate-500">{new Date(c.created_at).toLocaleString("fr-FR")}</span>
                  {alreadySaved ? (
                    <span className="inline-flex items-center gap-1 text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-md px-2 py-1 text-xs font-medium" title="Déjà enregistré comme utilisateur suivi">
                      <Check className="h-3.5 w-3.5" /> Enregistré
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => openSave(c)}
                      title="Enregistrer comme utilisateur suivi"
                      className="inline-flex items-center gap-1.5 rounded-md border border-sawali-blue/30 bg-sawali-blue/5 text-sawali-blue hover:bg-sawali-blue hover:text-white transition px-2.5 py-1.5 text-xs font-medium"
                      data-testid={`save-as-tracked-${c.id}`}
                    >
                      <UserPlus className="h-3.5 w-3.5" /> Enregistrer
                    </button>
                  )}
                </div>
              </div>
              <p className="mt-3 text-sm text-slate-600 whitespace-pre-wrap">{c.message}</p>
            </div>
          );
        })}
      </div>

      {savingFor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={closeSave}>
          <div className="bg-white rounded-xl w-full max-w-md" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="font-display font-semibold">Enregistrer comme utilisateur suivi</h3>
              <button onClick={closeSave} aria-label="Fermer"><X className="h-4 w-4" /></button>
            </div>
            <form onSubmit={submitSave} className="p-4 space-y-3" data-testid="save-tracked-form">
              <div className="rounded-lg bg-slate-50 border border-slate-200 p-3 text-xs space-y-1">
                <div><span className="text-slate-500">Nom :</span> <strong>{savingFor.name}</strong></div>
                <div><span className="text-slate-500">Email :</span> <strong>{savingFor.email}</strong></div>
                {savingFor.phone && <div><span className="text-slate-500">Téléphone :</span> {savingFor.phone}</div>}
                {savingFor.company && <div><span className="text-slate-500">Société :</span> {savingFor.company}</div>}
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Client *</label>
                <select required value={form.client_id} onChange={(e) => setForm({ ...form, client_id: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="save-tracked-client">
                  <option value="">— Sélectionner un client —</option>
                  {clients.map((c) => (
                    <option key={c.id} value={c.id}>{c.full_name}{c.company ? ` (${c.company})` : ""}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Rôle *</label>
                <select required value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="save-tracked-role">
                  {TRACKED_ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
                <p className="mt-1 text-xs text-slate-500">Seul le rôle <strong>Superviseur</strong> a accès aux paramètres.</p>
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Service / Département</label>
                <input value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder="Ex. IT, Direction..." />
              </div>
              <button type="submit" disabled={submitting} className="w-full rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light disabled:opacity-50" data-testid="save-tracked-submit">
                {submitting ? "Enregistrement..." : "Enregistrer"}
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
