import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { Plus, Trash2, Edit, X, KeyRound, ShieldCheck, ShieldOff, Copy } from "lucide-react";
import { toast } from "sonner";
import PasswordInput from "@/components/PasswordInput";

const TRACKED_ROLES = ["Consultation", "Edition", "Moderation", "Administrateur", "Superviseur", "Comptable", "Caissier", "Traducteur", "Médecin", "Secrétaire médicale"];
const TRANSLATOR_LANGS = [
  { code: "en", label: "Anglais (EN)" },
  { code: "ar", label: "Arabe (AR)" },
  { code: "lg1", label: "LG1 — Gulmancema" },
  { code: "lg2", label: "LG2 — Mooré" },
];
const empty = { client_id: "", name: "", email: "", phone: "", whatsapp_number: "", role: "Consultation", department: "", company: "", status: "active" };

export default function AdminTrackedUsers() {
  const [items, setItems] = useState([]);
  const [clients, setClients] = useState([]);
  const [filterClient, setFilterClient] = useState("");
  const [isOpen, setIsOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(empty);
  const [pwdDialog, setPwdDialog] = useState(null); // tracked user being password-managed
  // Iter35g — bulk transfer state
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [transferTarget, setTransferTarget] = useState("");
  const [transferring, setTransferring] = useState(false);

  const load = () => apiClient.get("/admin/tracked-users").then((r) => setItems(r.data));
  useEffect(() => {
    load().catch(() => {});
    apiClient.get("/admin/clients").then((r) => setClients(r.data));
  }, []);
  const open = (it = null) => { setEditing(it); setForm(it ? { ...empty, ...it } : empty); setIsOpen(true); };
  const close = () => { setIsOpen(false); setEditing(null); setForm(empty); };
  const submit = async (e) => {
    e.preventDefault();
    // Iter43-fix24az-r (2026-07-22) — Bug prod : les EmailStr Pydantic
    // refusent la chaîne vide "" → 422. On convertit tous les champs
    // optionnels vides en null AVANT l'envoi.
    const OPT_STRING_FIELDS = ["email", "phone", "whatsapp_number", "department", "company"];
    const payload = { ...form };
    OPT_STRING_FIELDS.forEach((k) => {
      if (payload[k] === "" || payload[k] === undefined) payload[k] = null;
    });
    if (payload.translator_rate_per_word === "" || Number.isNaN(payload.translator_rate_per_word)) {
      payload.translator_rate_per_word = null;
    }
    try {
      if (editing?.id) await apiClient.put(`/admin/tracked-users/${editing.id}`, payload);
      else await apiClient.post("/admin/tracked-users", payload);
      toast.success("Enregistré"); close(); await load();
    } catch (err) {
      // Iter43-fix24az-r — 422 Pydantic renvoie un array `detail`, il faut
      // le formater pour éviter "[object Object]" ou toast vide.
      const raw = err?.response?.data?.detail;
      let msg = "Erreur";
      if (typeof raw === "string") msg = raw;
      else if (Array.isArray(raw) && raw.length > 0) {
        msg = raw.map((e2) => {
          const path = Array.isArray(e2.loc) ? e2.loc.filter((p) => p !== "body").join(".") : "";
          return path ? `${path} : ${e2.msg}` : e2.msg;
        }).join(" · ");
      }
      toast.error(msg);
    }
  };
  const del = async (id) => { if (!window.confirm("Supprimer ?")) return; await apiClient.delete(`/admin/tracked-users/${id}`); await load(); };
  const cName = (id) => clients.find((c) => c.id === id)?.full_name || id;

  // Iter35g — Bulk transfer helpers
  const toggleSelect = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  const toggleSelectGroup = (groupItems, allSelected) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      for (const u of groupItems) {
        if (allSelected) next.delete(u.id); else next.add(u.id);
      }
      return next;
    });
  };
  const clearSelection = () => { setSelectedIds(new Set()); setTransferTarget(""); };
  const doBulkTransfer = async () => {
    if (selectedIds.size === 0) { toast.error("Sélectionnez au moins un utilisateur"); return; }
    if (!transferTarget) { toast.error("Choisissez un client de destination"); return; }
    const targetClient = clients.find((c) => c.id === transferTarget);
    const targetLabel = targetClient ? `${targetClient.full_name}${targetClient.company ? ` (${targetClient.company})` : ""}` : transferTarget;
    if (!window.confirm(`Transférer ${selectedIds.size} utilisateur(s) vers ${targetLabel} ?`)) return;
    setTransferring(true);
    try {
      const r = await apiClient.post("/admin/tracked-users/bulk-transfer", {
        tracked_user_ids: Array.from(selectedIds),
        target_client_id: transferTarget,
      });
      const moved = r.data?.moved_count || 0;
      const skipped = r.data?.skipped_count || 0;
      if (moved > 0) {
        toast.success(`✅ ${moved} utilisateur(s) transféré(s) vers ${targetLabel}${skipped ? ` · ${skipped} ignoré(s)` : ""}`, { duration: 8000 });
      } else {
        toast.warning(`Aucun transfert effectué (${skipped} ignoré(s))`);
      }
      clearSelection();
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec du transfert");
    } finally { setTransferring(false); }
  };

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

      {/* Iter35g — Bulk transfer toolbar (sticky at top when something is selected) */}
      {selectedIds.size > 0 && (
        <div className="sticky top-2 z-30 rounded-xl border-2 border-sawali-blue bg-sawali-blue/5 shadow-lg p-3 flex items-center gap-3 flex-wrap" data-testid="tracked-bulk-toolbar">
          <span className="font-semibold text-sm text-sawali-blue">
            {selectedIds.size} utilisateur(s) sélectionné(s)
          </span>
          <span className="text-xs text-slate-500">→</span>
          <select
            value={transferTarget}
            onChange={(e) => setTransferTarget(e.target.value)}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm bg-white flex-1 min-w-[200px]"
            data-testid="tracked-bulk-target"
          >
            <option value="">Choisir le client de destination…</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.full_name}{c.company ? ` — ${c.company}` : ""}
              </option>
            ))}
          </select>
          <button
            onClick={doBulkTransfer}
            disabled={transferring || !transferTarget}
            className="rounded-lg bg-sawali-blue text-white px-4 py-1.5 text-sm font-semibold hover:bg-sawali-blue-light disabled:opacity-50"
            data-testid="tracked-bulk-transfer-btn"
          >
            {transferring ? "Transfert…" : "Transférer la sélection"}
          </button>
          <button
            onClick={clearSelection}
            className="rounded-lg bg-white text-slate-700 px-3 py-1.5 text-sm border border-slate-300 hover:bg-slate-50"
            data-testid="tracked-bulk-clear"
          >
            Annuler
          </button>
        </div>
      )}

      {groupedByClient.map((group) => {
        const groupIds = group.list.map((u) => u.id);
        const allInGroupSelected = groupIds.length > 0 && groupIds.every((id) => selectedIds.has(id));
        return (
        <div key={group.client_id} className="rounded-xl border border-slate-200 bg-white overflow-x-auto" data-testid={`tracked-group-${group.client_id}`}>
          <div className="px-4 py-3 border-b border-slate-100 bg-slate-50/50 flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={allInGroupSelected}
                onChange={() => toggleSelectGroup(group.list, allInGroupSelected)}
                className="cursor-pointer accent-sawali-blue"
                title={allInGroupSelected ? "Désélectionner tout le groupe" : "Sélectionner tout le groupe"}
                data-testid={`tracked-group-select-all-${group.client_id}`}
              />
              <h2 className="font-semibold text-slate-800">{group.client_name}</h2>
            </div>
            <span className="text-xs text-slate-500">{group.list.length} utilisateur{group.list.length > 1 ? "s" : ""}</span>
          </div>
          <table className="w-full text-sm min-w-[900px]">
            <thead className="bg-white text-xs uppercase text-slate-600">
              <tr>
                <th className="text-left px-3 py-3 w-10"></th>
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
                <tr key={u.id} className={`border-t border-slate-100 ${selectedIds.has(u.id) ? "bg-sawali-blue/5" : ""}`} data-testid={`tracked-row-${u.id}`}>
                  <td className="px-3 py-3">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(u.id)}
                      onChange={() => toggleSelect(u.id)}
                      className="cursor-pointer accent-sawali-blue"
                      data-testid={`tracked-select-${u.id}`}
                    />
                  </td>
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
        );
      })}

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
              {[["name", "Nom *", "text", true], ["email", "Email", "email", false], ["phone", "Téléphone", "tel", false], ["whatsapp_number", "N° WhatsApp (E.164)", "tel", false], ["company", "Société", "text", false], ["department", "Service", "text", false]].map(([k, l, t, req]) => (
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

              {/* 2026-02 — Translator-specific fields */}
              {form.role === "Traducteur" && (
                <div className="rounded-lg ring-1 ring-fuchsia-200 bg-fuchsia-50/40 p-3 space-y-3" data-testid="translator-fields">
                  <div className="text-xs font-semibold text-fuchsia-900">Configuration Traducteur</div>
                  <div>
                    <label className="block text-xs font-semibold mb-1 text-fuchsia-800">Langues autorisées pour édition</label>
                    <div className="flex flex-wrap gap-2">
                      {TRANSLATOR_LANGS.map(({ code, label }) => {
                        const checked = (form.translator_languages || []).includes(code);
                        return (
                          <label key={code} className={`inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs cursor-pointer ${checked ? "bg-fuchsia-600 text-white" : "ring-1 ring-fuchsia-300 text-fuchsia-700 hover:bg-fuchsia-100"}`}>
                            <input
                              type="checkbox"
                              className="sr-only"
                              checked={checked}
                              onChange={(e) => {
                                const cur = form.translator_languages || [];
                                setForm({
                                  ...form,
                                  translator_languages: e.target.checked
                                    ? [...new Set([...cur, code])]
                                    : cur.filter((c) => c !== code),
                                });
                              }}
                              data-testid={`translator-lang-${code}`}
                            />
                            {label}
                          </label>
                        );
                      })}
                    </div>
                    <p className="mt-1 text-[10px] text-fuchsia-600 italic">Le FR est réservé à l'administrateur (source de vérité).</p>
                  </div>
                  <div>
                    <label className="block text-xs font-semibold mb-1 text-fuchsia-800">Base de rémunération (par mot traduit)</label>
                    <input
                      type="number"
                      min={0}
                      step={0.01}
                      value={form.translator_rate_per_word ?? ""}
                      onChange={(e) => setForm({ ...form, translator_rate_per_word: e.target.value === "" ? null : parseFloat(e.target.value) })}
                      placeholder="ex. 5.00"
                      className="w-full rounded-lg border border-fuchsia-300 px-3 py-2 text-sm bg-white"
                      data-testid="translator-rate-input"
                    />
                  </div>
                </div>
              )}

              {/* 2026-02 (#5) — Force logout toggle */}
              <label className="inline-flex items-center gap-2 text-xs cursor-pointer rounded-lg ring-1 ring-amber-200 bg-amber-50/50 px-3 py-2">
                <input
                  type="checkbox"
                  checked={!!form.force_logout_on_idle}
                  onChange={(e) => setForm({ ...form, force_logout_on_idle: e.target.checked })}
                  data-testid="force-logout-toggle"
                />
                <span className="flex-1">
                  <strong>Forcer la déconnexion à l'inactivité</strong>
                  <span className="block text-[10px] text-amber-700 mt-0.5">
                    Si activé, l'utilisateur est déconnecté automatiquement sans demande de confirmation à l'expiration du délai.
                  </span>
                </span>
              </label>

              {/* 2026-02 fork (P4) — Overrides visibilité (Dashboard / Welcome / Notifs) */}
              <fieldset className="rounded-lg ring-1 ring-sawali-blue/20 bg-sawali-blue/5 p-3">
                <legend className="text-xs font-semibold px-1 text-sawali-blue">Visibilité personnalisée</legend>
                <p className="text-[10px] text-slate-600 mb-2">
                  Laissez la case indéterminée pour garder le comportement par défaut du rôle. Cochez pour forcer l'affichage, décochez pour masquer.
                </p>
                {[
                  { key: "show_dashboard", label: "Tableau de bord", hint: "Menu latéral et page d'accueil du portail" },
                  { key: "show_welcome_modal", label: "Modale de bienvenue", hint: "Affichée après la connexion (résumé quotidien)" },
                  { key: "show_messaging_notifs", label: "Notifications du Centre de Messagerie", hint: "Toasts sonores et badge WhatsApp non lu" },
                ].map(({ key, label, hint }) => (
                  <div key={key} className="flex items-center gap-2 py-1" data-testid={`p4-toggle-${key}`}>
                    <select
                      value={form[key] === true ? "on" : form[key] === false ? "off" : "default"}
                      onChange={(e) => {
                        const v = e.target.value;
                        setForm({
                          ...form,
                          [key]: v === "on" ? true : v === "off" ? false : null,
                        });
                      }}
                      className="rounded border border-slate-300 px-2 py-1 text-xs bg-white"
                      data-testid={`p4-select-${key}`}
                    >
                      <option value="default">Défaut du rôle</option>
                      <option value="on">Toujours afficher</option>
                      <option value="off">Toujours masquer</option>
                    </select>
                    <span className="flex-1 text-xs">
                      <strong>{label}</strong>
                      <span className="block text-[10px] text-slate-500">{hint}</span>
                    </span>
                  </div>
                ))}
              </fieldset>
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
