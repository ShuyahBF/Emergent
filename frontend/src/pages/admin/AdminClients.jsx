import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Plus, Edit, Trash2, X, Star, StarOff, Settings, Edit2, Check, Upload } from "lucide-react";
import { toast } from "sonner";
import IconPicker, { CategoryIcon } from "@/components/IconPicker";

const empty = { email: "", full_name: "", password: "", phone: "", company: "", client_code: "", category_slug: "", country: "", city: "", logo_url: "", account_status: "active", role: "client" };

export default function AdminClients() {
  const [items, setItems] = useState([]);
  const [categories, setCategories] = useState([]);
  const [isOpen, setIsOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(empty);
  const [loading, setLoading] = useState(false);
  const [catManagerOpen, setCatManagerOpen] = useState(false);

  const load = () => apiClient.get("/admin/clients").then((r) => setItems(r.data));
  const loadCats = () => apiClient.get("/admin/client-categories").then((r) => setCategories(r.data));
  useEffect(() => {
    load().catch(() => {});
    loadCats().catch(() => {});
  }, []);

  const catOf = (slug) => categories.find((c) => c.slug === slug);

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
        <div className="flex items-center gap-2">
          <button onClick={() => setCatManagerOpen(true)} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white text-slate-700 hover:border-sawali-blue hover:text-sawali-blue px-3.5 py-2 text-sm" data-testid="manage-client-categories-btn">
            <Settings className="h-4 w-4" /> Catégories
          </button>
          <button onClick={() => open()} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light" data-testid="new-client-button">
            <Plus className="h-4 w-4" /> Nouveau client
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white overflow-x-auto">
        <table className="w-full text-sm min-w-[940px]">
          <thead className="bg-slate-50 text-xs uppercase text-slate-600">
            <tr>
              <th className="text-left px-4 py-3">Nom</th>
              <th className="text-left px-4 py-3">Email</th>
              <th className="text-left px-4 py-3">Catégorie</th>
              <th className="text-left px-4 py-3">Pays</th>
              <th className="text-left px-4 py-3">Rôle</th>
              <th className="text-left px-4 py-3">Statut</th>
              <th className="text-right px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={7} className="px-4 py-10 text-center text-slate-500">Aucun client.</td></tr>}
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
                <td className="px-4 py-3 text-slate-600">
                  {(() => {
                    const cat = catOf(c.category_slug);
                    return cat ? (
                      <span className="inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded" style={{ background: (cat.color || "#1E90FF") + "15", color: cat.color || "#1E90FF" }}>
                        <CategoryIcon name={cat.icon} color={cat.color} className="h-3 w-3" />
                        {cat.label}
                      </span>
                    ) : (c.company || "-");
                  })()}
                </td>
                <td className="px-4 py-3 text-slate-600 text-xs">
                  {c.country ? (
                    <span>{c.country}{c.city ? <span className="text-slate-400"> · {c.city}</span> : null}</span>
                  ) : (
                    <span className="text-slate-400">-</span>
                  )}
                </td>
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
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">Catégorie</label>
              <select value={form.category_slug || ""} onChange={(e) => setForm({ ...form, category_slug: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="client-category-select">
                <option value="">— Aucune —</option>
                {categories.map((c) => <option key={c.id} value={c.slug}>{c.label}</option>)}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Input label="Pays" value={form.country || ""} onChange={(v) => setForm({ ...form, country: v })} />
              <Input label="Ville" value={form.city || ""} onChange={(v) => setForm({ ...form, city: v })} />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">Logo du client (image)</label>
              <div className="flex items-center gap-3">
                {form.logo_url && (
                  <img src={form.logo_url} alt="Logo" className="h-12 w-12 rounded border border-slate-200 object-contain bg-slate-50" />
                )}
                <label className="inline-flex items-center gap-2 cursor-pointer rounded-lg border border-dashed border-slate-300 px-3 py-2 text-xs text-slate-600 hover:border-sawali-blue">
                  <Upload className="h-3.5 w-3.5" /> {form.logo_url ? "Remplacer" : "Téléverser un logo"}
                  <input
                    type="file"
                    hidden
                    accept="image/*"
                    onChange={async (e) => {
                      const file = e.target.files?.[0];
                      if (!file) return;
                      const fd = new FormData(); fd.append("file", file);
                      try {
                        const r = await apiClient.post("/admin/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
                        setForm((prev) => ({ ...prev, logo_url: r.data.url }));
                        toast.success("Logo téléversé");
                      } catch (err) { toast.error("Erreur upload"); }
                    }}
                    data-testid="client-logo-input"
                  />
                </label>
                {form.logo_url && (
                  <button type="button" onClick={() => setForm({ ...form, logo_url: "" })} className="text-xs text-rose-600 hover:underline">Retirer</button>
                )}
              </div>
              <p className="mt-1 text-[11px] text-slate-500">Affiché dans la sidebar du portail à la place du logo SAWALI quand l'utilisateur de ce client est connecté.</p>
            </div>
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

      {catManagerOpen && (
        <ClientCategoryManager
          categories={categories}
          onClose={() => setCatManagerOpen(false)}
          onChanged={async () => { await loadCats(); await load(); }}
        />
      )}
    </div>
  );
}

const ClientCategoryManager = ({ categories, onClose, onChanged }) => {
  const [newLabel, setNewLabel] = useState("");
  const [newIcon, setNewIcon] = useState("Building2");
  const [newColor, setNewColor] = useState("#1E90FF");
  const [editingId, setEditingId] = useState(null);
  const [editLabel, setEditLabel] = useState("");
  const [editSlug, setEditSlug] = useState("");
  const [editIcon, setEditIcon] = useState("");
  const [editColor, setEditColor] = useState("");
  const [busy, setBusy] = useState(false);

  const add = async (e) => {
    e.preventDefault();
    if (!newLabel.trim()) return;
    setBusy(true);
    try {
      await apiClient.post("/admin/client-categories", { label: newLabel.trim(), icon: newIcon, color: newColor });
      toast.success("Catégorie ajoutée");
      setNewLabel(""); setNewIcon("Building2"); setNewColor("#1E90FF");
      await onChanged();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setBusy(false); }
  };

  const startEdit = (c) => {
    setEditingId(c.id); setEditLabel(c.label); setEditSlug(c.slug);
    setEditIcon(c.icon || "Building2"); setEditColor(c.color || "#1E90FF");
  };
  const cancelEdit = () => { setEditingId(null); };

  const saveEdit = async () => {
    setBusy(true);
    try {
      await apiClient.put(`/admin/client-categories/${editingId}`, {
        label: editLabel.trim(), slug: editSlug.trim(), icon: editIcon, color: editColor,
      });
      toast.success("Catégorie mise à jour");
      cancelEdit();
      await onChanged();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setBusy(false); }
  };

  const remove = async (c) => {
    if (!window.confirm(`Supprimer "${c.label}" ?`)) return;
    setBusy(true);
    try {
      await apiClient.delete(`/admin/client-categories/${c.id}`);
      toast.success("Supprimée");
      await onChanged();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={onClose}>
      <div className="bg-white rounded-xl w-full max-w-lg max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b">
          <h3 className="font-display font-semibold">Catégories de clients</h3>
          <button onClick={onClose}><X className="h-4 w-4" /></button>
        </div>
        <div className="p-4 space-y-4">
          <p className="text-xs text-slate-500">
            Ces catégories permettent de typer chaque client (clinique, pharmacie, commerce…) et d'afficher une icône personnalisable.
          </p>
          <form onSubmit={add} className="rounded-lg border border-slate-200 p-3 space-y-3 bg-slate-50/40">
            <div className="flex items-center gap-2">
              <CategoryIcon name={newIcon} color={newColor} className="h-5 w-5" />
              <input value={newLabel} onChange={(e) => setNewLabel(e.target.value)} placeholder="Nouvelle catégorie (ex. Hôpital)" className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="new-client-category-input" />
              <button type="submit" disabled={busy || !newLabel.trim()} className="inline-flex items-center gap-1 rounded-lg bg-sawali-blue text-white px-3 py-2 text-sm hover:bg-sawali-blue-light disabled:opacity-50" data-testid="add-client-category-btn">
                <Plus className="h-4 w-4" /> Ajouter
              </button>
            </div>
            <IconPicker value={newIcon} color={newColor} onChange={setNewIcon} onColorChange={setNewColor} />
          </form>
          <div className="rounded-lg border border-slate-200 divide-y divide-slate-100">
            {categories.map((c) => (
              <div key={c.id} className="p-3" data-testid={`client-category-row-${c.id}`}>
                {editingId === c.id ? (
                  <div className="space-y-3">
                    <div className="flex items-center gap-2">
                      <CategoryIcon name={editIcon} color={editColor} className="h-5 w-5" />
                      <input value={editLabel} onChange={(e) => setEditLabel(e.target.value)} className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm" />
                      <input value={editSlug} onChange={(e) => setEditSlug(e.target.value.toLowerCase().replace(/\s+/g, "-"))} className="w-32 rounded border border-slate-300 px-2 py-1 text-sm font-mono" />
                      <button onClick={saveEdit} disabled={busy} className="text-emerald-600"><Check className="h-4 w-4" /></button>
                      <button onClick={cancelEdit} className="text-slate-400"><X className="h-4 w-4" /></button>
                    </div>
                    <IconPicker value={editIcon} color={editColor} onChange={setEditIcon} onColorChange={setEditColor} />
                  </div>
                ) : (
                  <div className="flex items-center gap-3">
                    <span className="inline-flex items-center justify-center h-8 w-8 rounded-md flex-shrink-0" style={{ background: (c.color || "#1E90FF") + "20" }}>
                      <CategoryIcon name={c.icon} color={c.color} className="h-4 w-4" />
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">
                        {c.label}
                        {c.is_default && <span className="ml-2 text-[10px] uppercase tracking-wider text-slate-400 bg-slate-100 rounded px-1.5 py-0.5">défaut</span>}
                      </p>
                      <p className="text-xs text-slate-400 font-mono">{c.slug}</p>
                    </div>
                    <button onClick={() => startEdit(c)} className="text-slate-400 hover:text-sawali-blue" title="Modifier"><Edit2 className="h-4 w-4" /></button>
                    {!c.is_default && (
                      <button onClick={() => remove(c)} className="text-slate-400 hover:text-rose-600" title="Supprimer"><Trash2 className="h-4 w-4" /></button>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

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
