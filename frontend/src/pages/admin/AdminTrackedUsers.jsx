import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { Plus, Trash2, Edit, X, KeyRound, ShieldCheck, ShieldOff, Copy } from "lucide-react";
import { toast } from "sonner";
import PasswordInput from "@/components/PasswordInput";

const TRACKED_ROLES = ["Consultation", "Edition", "Moderation", "Administrateur", "Superviseur"];
const empty = { client_id: "", name: "", email: "", role: "Consultation", department: "", status: "active" };

export default function AdminTrackedUsers() {
  const [items, setItems] = useState([]);
  const [clients, setClients] = useState([]);
  const [filterClient, setFilterClient] = useState("");
  const [isOpen, setIsOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(empty);
  const [pwdDialog, setPwdDialog] = useState(null); // tracked user being password-managed

  const load = () => apiClient.get("/admin/tracked-users").then((r) => setItems(r.data));
  useEffect(() => {
    load().catch(() => {});
    apiClient.get("/admin/clients").then((r) => setClients(r.data));
  }, []);
  const open = (it = null) => { setEditing(it); setForm(it ? { ...empty, ...it } : empty); setIsOpen(true); };
  const close = () => { setIsOpen(false); setEditing(null); setForm(empty); };
  const submit = async (e) => {
    e.preventDefault();
    try {
      if (editing?.id) await apiClient.put(`/admin/tracked-users/${editing.id}`, form);
      else await apiClient.post("/admin/tracked-users", form);
      toast.success("Enregistré"); close(); await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };
  const del = async (id) => { if (!window.confirm("Supprimer ?")) return; await apiClient.delete(`/admin/tracked-users/${id}`); await load(); };
  const cName = (id) => clients.find((c) => c.id === id)?.full_name || id;

  const revoke = async (u) => {
    if (!window.confirm(`Révoquer l'accès portail de ${u.name} ?`)) return;
    try {
      await apiClient.post(`/admin/tracked-users/${u.id}/revoke-password`);
      toast.success("Accès révoqué");
      await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const filteredItems = useMemo(() => {
    if (!filterClient) return items;
    return items.filter((u) => u.client_id === filterClient);
  }, [items, filterClient]);
  const groupedByClient = useMemo(() => {
    const groups = new Map();
    for (const u of filteredItems) {
      const key = u.client_id || "_none";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(u);
    }
    return Array.from(groups.entries()).map(([cid, list]) => ({
      client_id: cid,
      client_name: cid === "_none" ? "(Sans client)" : cName(cid),
      list,
    }));
  }, [filteredItems, clients]);

  return (
    <div className="space-y-6" data-testid="admin-tracked-page">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-display font-bold">Utilisateurs suivis (par client)</h1>
          <p className="text-sm text-slate-500">Données affichées par client. Définissez un mot de passe pour leur permettre de se connecter au portail.</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <select
            value={filterClient}
            onChange={(e) => setFilterClient(e.target.value)}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm bg-white"
            data-testid="tracked-client-filter"
          >
            <option value="">Tous les clients</option>
            {clients.map((c) => <option key={c.id} value={c.id}>{c.full_name}{c.company ? ` — ${c.company}` : ""}</option>)}
          </select>
          <button onClick={() => open()} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light" data-testid="new-tracked-btn">
            <Plus className="h-4 w-4" /> Nouvel utilisateur
          </button>
        </div>
      </div>

      {filteredItems.length === 0 && (
        <div className="rounded-xl border border-slate-200 bg-white p-10 text-center text-slate-500">
          {filterClient ? "Aucun utilisateur pour ce client." : "Aucun utilisateur."}
        </div>
      )}

      {groupedByClient.map((group) => (
        <div key={group.client_id} className="rounded-xl border border-slate-200 bg-white overflow-x-auto" data-testid={`tracked-group-${group.client_id}`}>
          <div className="px-4 py-3 border-b border-slate-100 bg-slate-50/50 flex items-center justify-between">
            <h2 className="font-semibold text-slate-800">{group.client_name}</h2>
            <span className="text-xs text-slate-500">{group.list.length} utilisateur{group.list.length > 1 ? "s" : ""}</span>
          </div>
          <table className="w-full text-sm min-w-[860px]">
            <thead className="bg-white text-xs uppercase text-slate-600">
              <tr>
                <th className="text-left px-4 py-3">Nom</th>
                <th className="text-left px-4 py-3">Email</th>
                <th className="text-left px-4 py-3">Rôle</th>
                <th className="text-left px-4 py-3">Service</th>
                <th className="text-left px-4 py-3">Accès</th>
                <th className="text-left px-4 py-3">Statut</th>
                <th className="text-right px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {group.list.map((u) => (
                <tr key={u.id} className="border-t border-slate-100" data-testid={`tracked-row-${u.id}`}>
                  <td className="px-4 py-3 font-medium">{u.name}</td>
                  <td className="px-4 py-3 text-slate-600">{u.email || "-"}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded ${u.role === "Superviseur" ? "bg-sawali-blue/10 text-sawali-blue border border-sawali-blue/30" : "bg-slate-100 text-slate-700"}`}>{u.role || "-"}</span>
                  </td>
                  <td className="px-4 py-3 text-slate-600">{u.department || "-"}</td>
                  <td className="px-4 py-3">
                    {u.has_password ? (
                      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-emerald-100 text-emerald-700"><ShieldCheck className="h-3 w-3" /> Activé</span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-slate-100 text-slate-500"><ShieldOff className="h-3 w-3" /> Aucun</span>
                    )}
                  </td>
                  <td className="px-4 py-3">{u.status}</td>
                  <td className="px-4 py-3 text-right whitespace-nowrap">
                    <button
                      onClick={() => setPwdDialog(u)}
                      className="text-slate-500 hover:text-sawali-blue mr-3 inline-flex items-center gap-1"
                      title={u.has_password ? "Réinitialiser le mot de passe" : "Définir un mot de passe"}
                      data-testid={`set-pwd-${u.id}`}
                    >
                      <KeyRound className="h-4 w-4" />
                    </button>
                    {u.has_password && (
                      <button
                        onClick={() => revoke(u)}
                        className="text-slate-500 hover:text-amber-600 mr-3"
                        title="Révoquer l'accès portail"
                        data-testid={`revoke-pwd-${u.id}`}
                      >
                        <ShieldOff className="h-4 w-4 inline" />
                      </button>
                    )}
                    <button onClick={() => open(u)} className="text-slate-500 hover:text-sawali-blue mr-3" title="Modifier"><Edit className="h-4 w-4 inline" /></button>
                    <button onClick={() => del(u.id)} className="text-slate-500 hover:text-rose-600" title="Supprimer"><Trash2 className="h-4 w-4 inline" /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}

      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={close}>
          <div className="bg-white rounded-xl w-full max-w-md" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="font-display font-semibold">{editing?.id ? "Modifier" : "Nouvel utilisateur suivi"}</h3>
              <button onClick={close}><X className="h-4 w-4" /></button>
            </div>
            <form onSubmit={submit} className="p-4 space-y-3">
              <div>
                <label className="block text-xs font-semibold mb-1">Client *</label>
                <select required value={form.client_id} onChange={(e) => setForm({ ...form, client_id: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                  <option value="">— Sélectionner —</option>
                  {clients.map((c) => <option key={c.id} value={c.id}>{c.full_name}{c.company ? ` (${c.company})` : ""}</option>)}
                </select>
              </div>
              {[["name", "Nom *", "text", true], ["email", "Email", "email", false], ["department", "Service", "text", false]].map(([k, l, t, req]) => (
                <div key={k}>
                  <label className="block text-xs font-semibold mb-1">{l}</label>
                  <input type={t} required={req} value={form[k] || ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                </div>
              ))}
              <div>
                <label className="block text-xs font-semibold mb-1">Rôle *</label>
                <select required value={form.role || "Consultation"} onChange={(e) => setForm({ ...form, role: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="tracked-role-select">
                  {TRACKED_ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
                <p className="mt-1 text-xs text-slate-500">Seul le rôle <strong>Superviseur</strong> a accès aux paramètres.</p>
              </div>
              <div>
                <label className="block text-xs font-semibold mb-1">Statut</label>
                <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                  <option value="active">Actif</option><option value="inactive">Inactif</option>
                </select>
              </div>
              <button type="submit" className="w-full rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light">Enregistrer</button>
            </form>
          </div>
        </div>
      )}

      {pwdDialog && (
        <PasswordDialog
          user={pwdDialog}
          onClose={() => setPwdDialog(null)}
          onSaved={async () => { setPwdDialog(null); await load(); }}
        />
      )}
    </div>
  );
}

// ====================================================================
// Password dialog — set or reset password for a tracked user
// ====================================================================
function PasswordDialog({ user, onClose, onSaved }) {
  const [pwd, setPwd] = useState("");
  const [busy, setBusy] = useState(false);

  const generate = () => {
    const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789";
    let p = "";
    for (let i = 0; i < 12; i++) p += chars[Math.floor(Math.random() * chars.length)];
    setPwd(p);
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!user.email) { toast.error("L'utilisateur doit avoir un email pour se connecter"); return; }
    if (!pwd || pwd.length < 8) { toast.error("Mot de passe trop court (min 8 caractères)"); return; }
    setBusy(true);
    try {
      await apiClient.post(`/admin/tracked-users/${user.id}/set-password`, { password: pwd });
      toast.success(user.has_password ? "Mot de passe réinitialisé" : "Accès portail activé");
      await onSaved();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setBusy(false);
    }
  };

  const copyPwd = async () => {
    try { await navigator.clipboard.writeText(pwd); toast.success("Mot de passe copié"); }
    catch { toast.error("Copie impossible"); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={onClose}>
      <div className="bg-white rounded-xl w-full max-w-md" onClick={(e) => e.stopPropagation()} data-testid="password-dialog">
        <div className="flex items-center justify-between p-4 border-b">
          <div>
            <h3 className="font-display font-semibold">
              {user.has_password ? "Réinitialiser le mot de passe" : "Définir un mot de passe"}
            </h3>
            <p className="text-xs text-slate-500 mt-1">{user.name} — <span className="font-mono">{user.email || "(email manquant)"}</span></p>
          </div>
          <button onClick={onClose}><X className="h-4 w-4" /></button>
        </div>
        <form onSubmit={submit} className="p-4 space-y-3">
          {!user.email && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              ⚠ Cet utilisateur n'a pas d'email. Modifiez sa fiche pour ajouter un email avant de définir un mot de passe.
            </div>
          )}
          <div>
            <label className="block text-xs font-semibold mb-1">Mot de passe (min 8 caractères) *</label>
            <div className="flex gap-2">
              <PasswordInput
                value={pwd}
                onChange={(e) => setPwd(e.target.value)}
                className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono focus:border-sawali-blue focus:outline-none"
                placeholder="ex. M0nC0deS3cur1se"
                autoComplete="new-password"
                testid="password-input"
                autoFocus
              />
              <button type="button" onClick={generate} className="rounded-lg border border-slate-300 px-3 py-2 text-xs hover:border-sawali-blue hover:text-sawali-blue" title="Générer">⟲</button>
              {pwd && (
                <button type="button" onClick={copyPwd} className="rounded-lg border border-slate-300 px-3 py-2 text-xs hover:border-sawali-blue hover:text-sawali-blue" title="Copier"><Copy className="h-3.5 w-3.5" /></button>
              )}
            </div>
            <p className="mt-1 text-xs text-slate-500">L'utilisateur se connectera ensuite via <code>/login</code> avec son email et ce mot de passe (OTP envoyé par email).</p>
          </div>
          <button type="submit" disabled={busy || !user.email} className="w-full rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light disabled:opacity-50" data-testid="save-password-btn">
            {busy ? "Enregistrement..." : (user.has_password ? "Réinitialiser" : "Activer l'accès")}
          </button>
        </form>
      </div>
    </div>
  );
}
