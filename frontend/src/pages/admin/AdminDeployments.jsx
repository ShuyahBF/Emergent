import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Plus, Edit, Trash2, X, MapPin } from "lucide-react";
import { toast } from "sonner";

const empty = { solution_name: "", country: "", city: "", installations: 1, notes: "" };

export default function AdminDeployments() {
  const [items, setItems] = useState([]);
  const [isOpen, setIsOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(empty);
  const [loading, setLoading] = useState(false);

  const load = () => apiClient.get("/admin/deployments").then((r) => setItems(r.data));
  useEffect(() => { load().catch(() => {}); }, []);

  const open = (it = null) => {
    setEditing(it);
    setForm(it ? { ...empty, ...it } : empty);
    setIsOpen(true);
  };
  const close = () => { setIsOpen(false); setEditing(null); setForm(empty); };

  const submit = async (e) => {
    e.preventDefault(); setLoading(true);
    try {
      const payload = { ...form, installations: parseInt(form.installations || 0, 10) };
      if (editing?.id) await apiClient.put(`/admin/deployments/${editing.id}`, payload);
      else await apiClient.post("/admin/deployments", payload);
      toast.success("Déploiement enregistré");
      close(); await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setLoading(false); }
  };

  const del = async (id) => {
    if (!window.confirm("Supprimer ce déploiement ?")) return;
    await apiClient.delete(`/admin/deployments/${id}`);
    toast.success("Supprimé"); await load();
  };

  const totalCountries = new Set(items.map((i) => i.country)).size;
  const totalInstalls = items.reduce((s, i) => s + (i.installations || 0), 0);
  const totalSolutions = new Set(items.map((i) => i.solution_name)).size;

  return (
    <div className="space-y-6" data-testid="admin-deployments-page">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-display font-bold">Déploiements logiciels</h1>
          <p className="text-sm text-slate-500">Cartographie des installations de nos solutions par pays. Clé unique : (Solution, Pays).</p>
        </div>
        <button onClick={() => open()} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light" data-testid="new-deployment-btn">
          <Plus className="h-4 w-4" /> Nouveau déploiement
        </button>
      </div>

      <div className="grid sm:grid-cols-3 gap-4">
        <Stat label="Pays couverts" value={totalCountries} />
        <Stat label="Solutions distribuées" value={totalSolutions} />
        <Stat label="Installations totales" value={totalInstalls} />
      </div>

      <div className="rounded-xl border border-slate-200 bg-white overflow-x-auto">
        <table className="w-full text-sm min-w-[760px]">
          <thead className="bg-slate-50 text-xs uppercase text-slate-600">
            <tr>
              <th className="text-left px-4 py-3">Solution</th>
              <th className="text-left px-4 py-3">Pays</th>
              <th className="text-left px-4 py-3">Ville</th>
              <th className="text-right px-4 py-3">Installations</th>
              <th className="text-left px-4 py-3">Mis à jour</th>
              <th className="text-right px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={6} className="px-4 py-10 text-center text-slate-500">Aucun déploiement.</td></tr>}
            {items.map((d) => (
              <tr key={d.id} className="border-t border-slate-100" data-testid={`deployment-row-${d.id}`}>
                <td className="px-4 py-3 font-medium">{d.solution_name}</td>
                <td className="px-4 py-3 text-slate-700">
                  <span className="inline-flex items-center gap-1.5"><MapPin className="h-3.5 w-3.5 text-slate-400" />{d.country}</span>
                </td>
                <td className="px-4 py-3 text-slate-600">{d.city || "-"}</td>
                <td className="px-4 py-3 text-right font-mono text-slate-800">{d.installations}</td>
                <td className="px-4 py-3 text-xs text-slate-500">{(d.updated_at || d.created_at) ? new Date(d.updated_at || d.created_at).toLocaleString("fr-FR") : "-"}</td>
                <td className="px-4 py-3 text-right">
                  <button onClick={() => open(d)} className="text-slate-500 hover:text-sawali-blue mr-3"><Edit className="h-4 w-4 inline" /></button>
                  <button onClick={() => del(d.id)} className="text-slate-500 hover:text-rose-600"><Trash2 className="h-4 w-4 inline" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={close}>
          <div className="bg-white rounded-xl w-full max-w-md" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="font-display font-semibold">{editing?.id ? "Modifier le déploiement" : "Nouveau déploiement"}</h3>
              <button onClick={close}><X className="h-4 w-4" /></button>
            </div>
            <form onSubmit={submit} className="p-4 space-y-3" data-testid="deployment-form">
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Solution / Logiciel *</label>
                <input required value={form.solution_name} onChange={(e) => setForm({ ...form, solution_name: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder="ex. Aizenta" />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Pays *</label>
                <input required value={form.country} onChange={(e) => setForm({ ...form, country: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder="ex. Burkina Faso" />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Ville (optionnel)</label>
                <input value={form.city || ""} onChange={(e) => setForm({ ...form, city: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder="ex. Ouagadougou" />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Nombre d'installations *</label>
                <input required type="number" min="0" value={form.installations} onChange={(e) => setForm({ ...form, installations: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Notes</label>
                <textarea rows={2} value={form.notes || ""} onChange={(e) => setForm({ ...form, notes: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
              </div>
              <button type="submit" disabled={loading} className="w-full rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light disabled:opacity-50" data-testid="save-deployment-btn">
                {loading ? "Enregistrement..." : "Enregistrer"}
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

const Stat = ({ label, value }) => (
  <div className="rounded-xl border border-slate-200 bg-white p-5">
    <p className="text-xs uppercase tracking-widest text-slate-500">{label}</p>
    <p className="mt-2 text-3xl font-display font-bold text-slate-900">{value}</p>
  </div>
);
