import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Plus, Edit, Trash2, X, Star, StarOff } from "lucide-react";
import { toast } from "sonner";

const empty = { email: "", full_name: "", password: "", phone: "", company: "", client_code: "", account_status: "active", role: "client" };

export default function AdminClients() {
  const [items, setItems] = useState([]);
  const [isOpen, setIsOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(empty);
  const [loading, setLoading] = useState(false);

  const load = () => apiClient.get("/admin/clients").then((r) => setItems(r.data));
  useEffect(() => { load().catch(() => {}); }, []);

  const open = (it = null) => {
    setEditing(it);
    setForm(it ? { ...empty, ...it, password: "" } : empty);
    setIsOpen(true);
  };
  const close = () => { setIsOpen(false); setEditing(null); setForm(empty); };

  const submit = async (e) => {
    e.preventDefault(); setLoading(true);
    try {
      if (editing?.id) {
        const payload = { ...form };
        if (!payload.password) delete payload.password;
        await apiClient.put(`/admin/clients/${editing.id}`, payload);
        toast.success("Client mis à jour");
      } else {
        await apiClient.post("/admin/clients", form);
        toast.success("Client créé");
      }
      close(); await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setLoading(false); }
  };

  const del = async (id) => {
    if (!window.confirm("Supprimer ce client ?")) return;
    await apiClient.delete(`/admin/clients/${id}`);
    toast.success("Client supprimé");
    await load();
  };

  const setPrimary = async (id) => {
    if (!window.confirm("Désigner ce client comme Client Primaire ? Il sera automatiquement promu Superviseur.")) return;
    try {
      await apiClient.post(`/admin/clients/${id}/set-primary`);
      toast.success("Client primaire défini");
      await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const unsetPrimary = async (id) => {
    if (!window.confirm("Retirer le statut Client Primaire ? Le rôle reviendra à 'Client'.")) return;
    try {
      await apiClient.post(`/admin/clients/${id}/unset-primary`);
      toast.success("Statut retiré");
      await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  return (
    <div className="space-y-6" data-testid="admin-clients-page">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-display font-bold">Clients</h1>
          <p className="text-sm text-slate-500">Gérez les comptes des clients ayant accès au portail.</p>
        </div>
        <button onClick={() => open()} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light" data-testid="new-client-button">
          <Plus className="h-4 w-4" /> Nouveau client
        </button>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white overflow-x-auto">
        <table className="w-full text-sm min-w-[860px]">
          <thead className="bg-slate-50 text-xs uppercase text-slate-600">
            <tr>
              <th className="text-left px-4 py-3">Nom</th>
              <th className="text-left px-4 py-3">Email</th>
              <th className="text-left px-4 py-3">Entreprise</th>
              <th className="text-left px-4 py-3">Rôle</th>
              <th className="text-left px-4 py-3">Statut</th>
              <th className="text-right px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={6} className="px-4 py-10 text-center text-slate-500">Aucun client.</td></tr>}
            {items.map((c) => (
              <tr key={c.id} className={`border-t border-slate-100 ${c.is_primary_client ? "bg-sawali-blue/5" : ""}`} data-testid={`client-row-${c.id}`}>
                <td className="px-4 py-3 font-medium">
                  <div className="flex items-center gap-2">
                    {c.is_primary_client && (
                      <span title="Client primaire (Superviseur)" className="inline-flex items-center justify-center text-amber-500">
                        <Star className="h-4 w-4 fill-amber-400" />
                      </span>
                    )}
                    <span>{c.full_name}</span>
                  </div>
                </td>
                <td className="px-4 py-3 text-slate-600">{c.email}</td>
                <td className="px-4 py-3 text-slate-600">{c.company || "-"}</td>
                <td className="px-4 py-3">
                  <span className={`text-xs px-2 py-0.5 rounded border ${c.role === "superviseur" ? "bg-sawali-blue/10 text-sawali-blue border-sawali-blue/30" : c.role === "admin" ? "bg-amber-50 text-amber-700 border-amber-200" : "bg-slate-100 text-slate-700 border-slate-200"}`}>{c.role}</span>
                </td>
                <td className="px-4 py-3">
                  <span className={`text-xs px-2 py-1 rounded ${c.account_status === "active" ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-700"}`}>{c.account_status}</span>
                </td>
                <td className="px-4 py-3 text-right">
                  {c.is_primary_client ? (
                    <button onClick={() => unsetPrimary(c.id)} title="Retirer le statut primaire" className="text-amber-500 hover:text-amber-600 mr-3" data-testid={`unset-primary-${c.id}`}>
                      <StarOff className="h-4 w-4 inline" />
                    </button>
                  ) : (
                    <button onClick={() => setPrimary(c.id)} title="Désigner comme client primaire (Superviseur)" className="text-slate-400 hover:text-amber-500 mr-3" data-testid={`set-primary-${c.id}`}>
                      <Star className="h-4 w-4 inline" />
                    </button>
                  )}
                  <button onClick={() => open(c)} className="text-slate-500 hover:text-sawali-blue mr-3" data-testid={`edit-client-${c.id}`}><Edit className="h-4 w-4 inline" /></button>
                  <button onClick={() => del(c.id)} className="text-slate-500 hover:text-rose-600" data-testid={`del-client-${c.id}`}><Trash2 className="h-4 w-4 inline" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {isOpen && (
        <Modal onClose={close} title={editing?.id ? "Modifier le client" : "Nouveau client"}>
          <form onSubmit={submit} className="space-y-3" data-testid="client-form">
            <Input label="Nom complet *" value={form.full_name} onChange={(v) => setForm({ ...form, full_name: v })} required />
            <Input label="Email *" type="email" value={form.email} onChange={(v) => setForm({ ...form, email: v })} required />
            <Input label={editing?.id ? "Mot de passe (laisser vide pour ne pas changer)" : "Mot de passe *"} type="password" value={form.password} onChange={(v) => setForm({ ...form, password: v })} required={!editing?.id} />
            <Input label="Téléphone" value={form.phone || ""} onChange={(v) => setForm({ ...form, phone: v })} />
            <Input label="Entreprise" value={form.company || ""} onChange={(v) => setForm({ ...form, company: v })} />
            <Input label="Code client (utilisé pour la numérotation des interventions, ex. ACME)" value={form.client_code || ""} onChange={(v) => setForm({ ...form, client_code: v.toUpperCase() })} />
            <div className="grid grid-cols-2 gap-3">
              <Select label="Rôle" value={form.role} onChange={(v) => setForm({ ...form, role: v })} options={[{ v: "client", l: "Client" }, { v: "admin", l: "Admin (client)" }, { v: "superviseur", l: "Superviseur" }]} />
              <Select label="Statut" value={form.account_status} onChange={(v) => setForm({ ...form, account_status: v })} options={[{ v: "active", l: "Actif" }, { v: "disabled", l: "Désactivé" }]} />
            </div>
            <button type="submit" disabled={loading} className="w-full rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light disabled:opacity-50" data-testid="save-client-button">
              {loading ? "Enregistrement..." : "Enregistrer"}
            </button>
          </form>
        </Modal>
      )}
    </div>
  );
}

const Input = ({ label, type = "text", value, onChange, required }) => (
  <div>
    <label className="block text-xs font-semibold text-slate-700 mb-1">{label}</label>
    <input type={type} required={required} value={value} onChange={(e) => onChange(e.target.value)}
           className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:border-sawali-blue" />
  </div>
);
const Select = ({ label, value, onChange, options }) => (
  <div>
    <label className="block text-xs font-semibold text-slate-700 mb-1">{label}</label>
    <select value={value} onChange={(e) => onChange(e.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
      {options.map((o) => <option key={o.v} value={o.v}>{o.l}</option>)}
    </select>
  </div>
);
const Modal = ({ children, onClose, title }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={onClose}>
    <div className="bg-white rounded-xl w-full max-w-md max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
      <div className="flex items-center justify-between p-4 border-b">
        <h3 className="font-display font-semibold">{title}</h3>
        <button onClick={onClose} className="text-slate-500"><X className="h-4 w-4" /></button>
      </div>
      <div className="p-4">{children}</div>
    </div>
  </div>
);
