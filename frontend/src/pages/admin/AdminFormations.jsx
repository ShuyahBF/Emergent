import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { Plus, Edit, Trash2, X, GraduationCap, Settings as SettingsIcon, Users, Layers, Coins, Power } from "lucide-react";
import { toast } from "sonner";
import PasswordInput from "@/components/PasswordInput";
import ClientAccessSelector from "@/components/ClientAccessSelector";

const STATE_BADGES = {
  inscription: "bg-slate-100 text-slate-700",
  commencée: "bg-blue-100 text-blue-700",
  en_cours: "bg-amber-100 text-amber-700",
  suspendue: "bg-orange-100 text-orange-700",
  annulée: "bg-rose-100 text-rose-700",
  terminée: "bg-emerald-100 text-emerald-700",
};
const stateLabel = (s) => (s || "—").replace("_", " ");

const emptyForm = { name: "", description: "", available: true, access: "free", price: 0, default_credits: 0, cover_image_url: "", access_client_ids: [] };
const emptyModule = { name: "", order: 0, screenshot_url: "", software_path: "", content_html: "", api_url: "", api_auth_type: "none", api_token: "", api_basic_user: "", api_basic_pass: "" };

export default function AdminFormations() {
  const [items, setItems] = useState([]);
  const [isOpen, setIsOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [activeFid, setActiveFid] = useState(null);

  const load = () => apiClient.get("/admin/formations").then((r) => setItems(r.data));
  useEffect(() => { load().catch(() => {}); }, []);

  const open = (it = null) => { setEditing(it); setForm(it ? { ...emptyForm, ...it, access_client_ids: Array.isArray(it.access_client_ids) ? it.access_client_ids : [] } : emptyForm); setIsOpen(true); };
  const close = () => { setIsOpen(false); setEditing(null); setForm(emptyForm); };

  const submit = async (e) => {
    e.preventDefault();
    try {
      if (editing?.id) await apiClient.put(`/admin/formations/${editing.id}`, form);
      else await apiClient.post("/admin/formations", form);
      toast.success("Enregistré"); close(); await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const del = async (id) => { if (!window.confirm("Supprimer cette formation et tous ses modules ?")) return; await apiClient.delete(`/admin/formations/${id}`); await load(); };

  return (
    <div className="space-y-6" data-testid="admin-formations-page">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2"><GraduationCap className="h-6 w-6 text-sawali-blue" /> Formations Spécialisées</h1>
          <p className="text-sm text-slate-500">Catalogue de formations disponibles dans l'espace utilisateurs suivis. Composez chaque formation en modules avec contenu enrichi et API Q/R.</p>
        </div>
        <button onClick={() => open()} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light" data-testid="new-formation-btn">
          <Plus className="h-4 w-4" /> Nouvelle formation
        </button>
      </div>

      <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.map((f) => (
          <article key={f.id} className="rounded-xl border border-slate-200 bg-white p-5 flex flex-col gap-3" data-testid={`formation-${f.id}`}>
            {f.cover_image_url && <div className="h-28 -mx-5 -mt-5 mb-1 bg-slate-100 overflow-hidden"><img src={f.cover_image_url} alt="" className="w-full h-full object-cover" /></div>}
            <div className="flex items-start justify-between gap-2">
              <h3 className="font-display font-semibold flex-1">{f.name}</h3>
              <span className={`text-[10px] uppercase tracking-widest px-2 py-0.5 rounded ${f.available ? "bg-emerald-100 text-emerald-700" : "bg-rose-100 text-rose-700"}`}>{f.available ? "dispo" : "indispo"}</span>
            </div>
            {f.description && <p className="text-xs text-slate-600 line-clamp-2">{f.description}</p>}
            <div className="text-xs text-slate-500 flex items-center gap-3 flex-wrap">
              <span className="inline-flex items-center gap-1"><Layers className="h-3 w-3" /> {f.modules_count} modules</span>
              <span className="inline-flex items-center gap-1"><Users className="h-3 w-3" /> {f.enrolled_count} inscrits</span>
              <span className={`inline-flex items-center gap-1 ${f.access === "paid" ? "text-amber-600" : "text-emerald-600"}`}><Coins className="h-3 w-3" /> {f.access === "paid" ? `${f.price || 0} XOF` : "libre"}</span>
            </div>
            <div className="flex items-center gap-2 mt-auto pt-2 border-t border-slate-100">
              <button onClick={() => setActiveFid(f.id)} className="text-xs px-3 py-1.5 rounded bg-sawali-blue text-white hover:bg-sawali-blue-light" data-testid={`manage-formation-${f.id}`}>Modules</button>
              <button onClick={() => open(f)} className="text-slate-500 hover:text-sawali-blue ml-auto" title="Modifier"><Edit className="h-4 w-4" /></button>
              <button onClick={() => del(f.id)} className="text-slate-500 hover:text-rose-600" title="Supprimer"><Trash2 className="h-4 w-4" /></button>
            </div>
          </article>
        ))}
      </div>

      {items.length === 0 && <div className="rounded-xl border border-dashed border-slate-300 p-12 text-center text-slate-500">Aucune formation. Cliquez sur « Nouvelle formation » pour commencer.</div>}

      {isOpen && (
        <Modal title={editing?.id ? "Modifier la formation" : "Nouvelle formation"} onClose={close}>
          <form onSubmit={submit} className="space-y-3" data-testid="formation-form">
            <Field label="Nom *"><input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="formation-name" /></Field>
            <Field label="Description"><textarea rows={3} value={form.description || ""} onChange={(e) => setForm({ ...form, description: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" /></Field>
            <Field label="Image de couverture (URL)"><input value={form.cover_image_url || ""} onChange={(e) => setForm({ ...form, cover_image_url: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Disponibilité">
                <select value={form.available ? "1" : "0"} onChange={(e) => setForm({ ...form, available: e.target.value === "1" })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                  <option value="1">Disponible</option>
                  <option value="0">Indisponible</option>
                </select>
              </Field>
              <Field label="Accès">
                <select value={form.access} onChange={(e) => setForm({ ...form, access: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                  <option value="free">Libre</option>
                  <option value="paid">Payant</option>
                </select>
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Prix (XOF)"><input type="number" value={form.price || 0} onChange={(e) => setForm({ ...form, price: parseFloat(e.target.value) || 0 })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" /></Field>
              <Field label="Crédits par défaut à l'inscription"><input type="number" value={form.default_credits || 0} onChange={(e) => setForm({ ...form, default_credits: parseInt(e.target.value) || 0 })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" /></Field>
            </div>
            <ClientAccessSelector
              value={form.access_client_ids || []}
              onChange={(ids) => setForm({ ...form, access_client_ids: ids })}
              label="Clients autorisés à voir cette formation"
              testIdPrefix="formation-access-clients"
            />
            <button type="submit" className="w-full rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light">Enregistrer</button>
          </form>
        </Modal>
      )}

      {activeFid && <ModulesPanel fid={activeFid} onClose={() => setActiveFid(null)} />}
    </div>
  );
}

const Field = ({ label, children }) => (
  <div><label className="block text-xs font-semibold mb-1">{label}</label>{children}</div>
);
const Modal = ({ title, onClose, children }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={onClose}>
    <div className="bg-white rounded-xl w-full max-w-2xl max-h-[92vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
      <div className="flex items-center justify-between p-4 border-b">
        <h3 className="font-display font-semibold">{title}</h3>
        <button onClick={onClose}><X className="h-4 w-4" /></button>
      </div>
      <div className="p-4">{children}</div>
    </div>
  </div>
);

// ====================================================================
// Modules + Enrollments panel (per formation)
// ====================================================================
function ModulesPanel({ fid, onClose }) {
  const [modules, setModules] = useState([]);
  const [enrollments, setEnrollments] = useState([]);
  const [tab, setTab] = useState("modules");
  const [editingMod, setEditingMod] = useState(null);
  const [modForm, setModForm] = useState(emptyModule);
  const [modOpen, setModOpen] = useState(false);

  const load = async () => {
    const [m, e] = await Promise.all([
      apiClient.get(`/admin/formations/${fid}/modules`),
      apiClient.get(`/admin/formations/${fid}/enrollments`),
    ]);
    setModules(m.data); setEnrollments(e.data);
  };
  useEffect(() => { load().catch(() => {}); /* eslint-disable-next-line */ }, [fid]);

  const openMod = (it = null) => { setEditingMod(it); setModForm(it ? { ...emptyModule, ...it } : emptyModule); setModOpen(true); };
  const closeMod = () => { setModOpen(false); setEditingMod(null); setModForm(emptyModule); };

  const submitMod = async (e) => {
    e.preventDefault();
    try {
      if (editingMod?.id) await apiClient.put(`/admin/formations/${fid}/modules/${editingMod.id}`, modForm);
      else await apiClient.post(`/admin/formations/${fid}/modules`, modForm);
      toast.success("Module enregistré"); closeMod(); await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };
  const delMod = async (mid) => { if (!window.confirm("Supprimer ce module ?")) return; await apiClient.delete(`/admin/formations/${fid}/modules/${mid}`); await load(); };

  const adjustCredits = async (uid, delta) => {
    const v = window.prompt(`Crédits : valeur > 0 = ajouter, < 0 = consommer`, "10");
    if (!v) return;
    try { await apiClient.post(`/admin/formations/${fid}/enrollments/${uid}/credits`, { credits_delta: parseInt(v, 10) || 0 }); await load(); } catch (err) { toast.error(err?.response?.data?.detail); }
  };
  const setState = async (uid, state) => {
    try { await apiClient.post(`/admin/formations/${fid}/enrollments/${uid}/state`, { state }); await load(); } catch (err) { toast.error(err?.response?.data?.detail); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-stretch justify-end bg-black/60" onClick={onClose}>
      <div className="bg-white w-full max-w-3xl h-full overflow-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b sticky top-0 bg-white z-10">
          <div className="flex items-center gap-3">
            <h3 className="font-display font-semibold">Gestion de la formation</h3>
            <div className="flex gap-1">
              <button onClick={() => setTab("modules")} className={`px-3 py-1.5 text-xs rounded ${tab === "modules" ? "bg-sawali-blue text-white" : "text-slate-600 hover:bg-slate-100"}`}>Modules ({modules.length})</button>
              <button onClick={() => setTab("enrollments")} className={`px-3 py-1.5 text-xs rounded ${tab === "enrollments" ? "bg-sawali-blue text-white" : "text-slate-600 hover:bg-slate-100"}`}>Inscrits ({enrollments.length})</button>
            </div>
          </div>
          <button onClick={onClose}><X className="h-4 w-4" /></button>
        </div>

        {tab === "modules" && (
          <div className="p-4 space-y-3">
            <button onClick={() => openMod()} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-3 py-1.5 text-sm hover:bg-sawali-blue-light" data-testid="new-module-btn"><Plus className="h-4 w-4" /> Nouveau module</button>
            <div className="space-y-2">
              {modules.map((m) => (
                <div key={m.id} className="rounded-lg border border-slate-200 p-3 flex gap-3" data-testid={`module-${m.id}`}>
                  {m.screenshot_url && <img src={m.screenshot_url} alt="" className="h-14 w-20 object-cover rounded" />}
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold truncate flex items-center gap-2">
                      <span className="text-[10px] font-mono px-1.5 py-0.5 bg-slate-100 rounded">#{m.order}</span> {m.name}
                    </div>
                    {m.software_path && <div className="text-[11px] text-slate-500 font-mono truncate">{m.software_path}</div>}
                    {m.api_url && <div className="text-[11px] text-emerald-600 font-mono truncate">⇄ {m.api_url}</div>}
                  </div>
                  <div className="flex flex-col gap-1">
                    <button onClick={() => openMod(m)} className="text-slate-500 hover:text-sawali-blue"><Edit className="h-4 w-4" /></button>
                    <button onClick={() => delMod(m.id)} className="text-slate-500 hover:text-rose-600"><Trash2 className="h-4 w-4" /></button>
                  </div>
                </div>
              ))}
              {modules.length === 0 && <p className="text-sm text-slate-500 text-center py-8">Aucun module pour l'instant.</p>}
            </div>
          </div>
        )}

        {tab === "enrollments" && (
          <div className="p-4 overflow-x-auto">
            <table className="w-full text-sm min-w-[760px]">
              <thead className="bg-slate-50 text-xs uppercase text-slate-600">
                <tr><th className="text-left px-3 py-2">Utilisateur</th><th className="text-left px-3 py-2">État</th><th className="text-left px-3 py-2">Modules vus</th><th className="text-left px-3 py-2">Crédits</th><th className="text-left px-3 py-2">Temps total</th><th className="text-left px-3 py-2">Dernier accès</th><th></th></tr>
              </thead>
              <tbody>
                {enrollments.map((e) => (
                  <tr key={e.id} className="border-t" data-testid={`enrollment-${e.id}`}>
                    <td className="px-3 py-2"><div className="font-medium">{e.user_name || "—"}</div><div className="text-xs text-slate-500">{e.user_email}</div></td>
                    <td className="px-3 py-2"><span className={`text-[11px] px-2 py-0.5 rounded ${STATE_BADGES[e.state] || "bg-slate-100"}`}>{stateLabel(e.state)}</span></td>
                    <td className="px-3 py-2 tabular-nums">{e.modules_seen_count}/{e.modules_total}</td>
                    <td className="px-3 py-2 tabular-nums">{(e.credits_purchased || 0) - (e.credits_consumed || 0)} <span className="text-xs text-slate-400">(/{e.credits_purchased || 0})</span></td>
                    <td className="px-3 py-2 tabular-nums">{((e.total_time_ms || 0) / 60000).toFixed(1)} min</td>
                    <td className="px-3 py-2 text-xs text-slate-500">{e.last_access ? new Date(e.last_access).toLocaleString("fr-FR") : "—"}</td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      <button onClick={() => adjustCredits(e.user_id, 10)} className="text-slate-500 hover:text-amber-600 mx-1" title="Crédits"><Coins className="h-4 w-4" /></button>
                      <button onClick={() => setState(e.user_id, "annulée")} className="text-slate-500 hover:text-rose-600 mx-1" title="Annuler"><Power className="h-4 w-4" /></button>
                    </td>
                  </tr>
                ))}
                {enrollments.length === 0 && <tr><td colSpan={7} className="px-3 py-8 text-center text-slate-500">Aucun inscrit pour l'instant.</td></tr>}
              </tbody>
            </table>
          </div>
        )}

        {modOpen && (
          <Modal title={editingMod?.id ? "Modifier le module" : "Nouveau module"} onClose={closeMod}>
            <form onSubmit={submitMod} className="space-y-3" data-testid="module-form">
              <div className="grid grid-cols-3 gap-3">
                <div className="col-span-2"><Field label="Nom *"><input required value={modForm.name} onChange={(e) => setModForm({ ...modForm, name: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="module-name" /></Field></div>
                <Field label="Ordre"><input type="number" value={modForm.order || 0} onChange={(e) => setModForm({ ...modForm, order: parseInt(e.target.value) || 0 })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" /></Field>
              </div>
              <Field label="Capture d'écran (URL)"><input value={modForm.screenshot_url || ""} onChange={(e) => setModForm({ ...modForm, screenshot_url: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder="https://…" /></Field>
              <Field label="Chemin d'accès dans le logiciel"><input value={modForm.software_path || ""} onChange={(e) => setModForm({ ...modForm, software_path: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" placeholder="Menu > Sous-menu > Action" /></Field>
              <Field label="Contenu (HTML enrichi)"><textarea rows={6} value={modForm.content_html || ""} onChange={(e) => setModForm({ ...modForm, content_html: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" placeholder="<p>...</p>" /></Field>
              <div className="border-t pt-3 space-y-2">
                <p className="text-xs font-semibold flex items-center gap-1"><SettingsIcon className="h-3 w-3" /> API REST Q/R (optionnelle)</p>
                <Field label="URL POST"><input type="url" value={modForm.api_url || ""} onChange={(e) => setModForm({ ...modForm, api_url: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" placeholder="https://votre-api/formation/module/question" /></Field>
                <Field label="Authentification">
                  <select value={modForm.api_auth_type || "none"} onChange={(e) => setModForm({ ...modForm, api_auth_type: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                    <option value="none">Aucune</option><option value="bearer">Bearer Token</option><option value="basic">Basic Auth</option>
                  </select>
                </Field>
                {modForm.api_auth_type === "bearer" && <Field label="Token"><PasswordInput value={modForm.api_token || ""} onChange={(e) => setModForm({ ...modForm, api_token: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" autoComplete="off" /></Field>}
                {modForm.api_auth_type === "basic" && (
                  <div className="grid grid-cols-2 gap-2">
                    <Field label="Utilisateur"><input value={modForm.api_basic_user || ""} onChange={(e) => setModForm({ ...modForm, api_basic_user: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" /></Field>
                    <Field label="Mot de passe"><PasswordInput value={modForm.api_basic_pass || ""} onChange={(e) => setModForm({ ...modForm, api_basic_pass: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" autoComplete="off" /></Field>
                  </div>
                )}
              </div>
              <button type="submit" className="w-full rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light">Enregistrer</button>
            </form>
          </Modal>
        )}
      </div>
    </div>
  );
}
