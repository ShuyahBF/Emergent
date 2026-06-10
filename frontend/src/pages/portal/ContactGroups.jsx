// Iter40 (2026-02) — Page de gestion des Groupes de contacts.
// Permet de créer/éditer/supprimer des groupes et d'y ajouter des contacts
// existants. Un contact peut appartenir à plusieurs groupes. La sélection
// dans le composer SMS/WA Bulk consomme `POST /me/contact-groups/resolve`.
import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  Loader2, Users, Plus, Trash2, Pencil, Save, X, Search, UserPlus,
} from "lucide-react";
import TenantSharingToggle from "@/components/TenantSharingToggle";

const DEFAULT_COLORS = ["#6366f1", "#ec4899", "#10b981", "#f59e0b", "#0ea5e9", "#ef4444", "#8b5cf6"];

export default function ContactGroups() {
  const [groups, setGroups] = useState([]);
  const [contacts, setContacts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null); // {id?, name, color, description, contact_ids}
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerGroup, setPickerGroup] = useState(null);
  const [pickerSearch, setPickerSearch] = useState("");
  const [pickerSelection, setPickerSelection] = useState([]);

  const loadAll = async () => {
    try {
      setLoading(true);
      const [g, c] = await Promise.all([
        apiClient.get("/me/contact-groups"),
        apiClient.get("/me/contacts?limit=500"),
      ]);
      setGroups(g.data || []);
      const cl = c.data?.items || c.data || [];
      setContacts(Array.isArray(cl) ? cl : []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur chargement");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadAll(); }, []);

  const startCreate = () => setEditing({ name: "", color: DEFAULT_COLORS[0], description: "", contact_ids: [], shared_with_tenant: false, editable_by_tenant: false });
  const startEdit = (g) => setEditing({ id: g.id, name: g.name, color: g.color || DEFAULT_COLORS[0], description: g.description || "", shared_with_tenant: !!g.shared_with_tenant, editable_by_tenant: !!g.editable_by_tenant });

  const save = async () => {
    if (!editing.name.trim()) { toast.error("Nom requis"); return; }
    try {
      const sharePayload = {
        shared_with_tenant: !!editing.shared_with_tenant,
        editable_by_tenant: !!editing.editable_by_tenant,
      };
      if (editing.id) {
        await apiClient.put(`/me/contact-groups/${editing.id}`, {
          name: editing.name, color: editing.color, description: editing.description,
          ...sharePayload,
        });
        toast.success("Groupe mis à jour");
      } else {
        await apiClient.post("/me/contact-groups", {
          name: editing.name, color: editing.color, description: editing.description,
          contact_ids: editing.contact_ids || [],
          ...sharePayload,
        });
        toast.success("Groupe créé");
      }
      setEditing(null);
      await loadAll();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur enregistrement");
    }
  };

  const remove = async (g) => {
    if (!window.confirm(`Supprimer le groupe « ${g.name} » ?\n\nLes contacts ne seront pas supprimés.`)) return;
    try {
      await apiClient.delete(`/me/contact-groups/${g.id}`);
      toast.success("Groupe supprimé");
      await loadAll();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
  };

  const openPicker = (g) => {
    setPickerGroup(g);
    setPickerSearch("");
    setPickerSelection([]);
    setPickerOpen(true);
  };

  const addContactsToGroup = async () => {
    if (!pickerSelection.length) { setPickerOpen(false); return; }
    try {
      const r = await apiClient.post(`/me/contact-groups/${pickerGroup.id}/contacts`, {
        contact_ids: pickerSelection,
      });
      toast.success(`${(r.data.added || []).length} ajouté(s) · ${r.data.total} au total`);
      setPickerOpen(false);
      await loadAll();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
  };

  const removeFromGroup = async (g, cid) => {
    if (!window.confirm("Retirer ce contact du groupe ?")) return;
    try {
      await apiClient.delete(`/me/contact-groups/${g.id}/contacts/${cid}`);
      await loadAll();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
  };

  const contactById = useMemo(() => {
    const m = {};
    for (const c of contacts) m[c.id] = c;
    return m;
  }, [contacts]);

  const filteredPickerContacts = useMemo(() => {
    if (!pickerOpen || !pickerGroup) return [];
    const already = new Set(pickerGroup.contact_ids || []);
    const q = pickerSearch.toLowerCase();
    return contacts
      .filter((c) => !already.has(c.id))
      .filter((c) => {
        if (!q) return true;
        return (c.name || "").toLowerCase().includes(q)
          || (c.phone || "").includes(q)
          || (c.whatsapp || "").includes(q)
          || (c.company || "").toLowerCase().includes(q)
          || (c.email || "").toLowerCase().includes(q);
      })
      .slice(0, 100);
  }, [pickerOpen, pickerGroup, pickerSearch, contacts]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-slate-500 p-6"><Loader2 className="h-4 w-4 animate-spin" /> Chargement…</div>
    );
  }

  return (
    <div className="space-y-6 p-4" data-testid="contact-groups-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold flex items-center gap-2">
            <Users className="h-6 w-6 text-fuchsia-600" />
            Groupes de contacts
          </h1>
          <p className="text-sm text-slate-600 mt-1">
            Regroupez vos contacts pour cibler vos campagnes SMS/WhatsApp.
            Un contact peut appartenir à plusieurs groupes.
          </p>
        </div>
        <button
          type="button"
          onClick={startCreate}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-fuchsia-600 hover:bg-fuchsia-700 text-white text-sm"
          data-testid="cg-create-btn"
        >
          <Plus className="h-4 w-4" /> Nouveau groupe
        </button>
      </div>

      {/* Edit modal */}
      {editing && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" data-testid="cg-edit-modal">
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-5 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-slate-800 flex items-center gap-2">
                {editing.id ? <Pencil className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
                {editing.id ? "Modifier le groupe" : "Nouveau groupe"}
              </h2>
              <button onClick={() => setEditing(null)} className="text-slate-400 hover:text-slate-700"><X className="h-4 w-4" /></button>
            </div>
            <label className="text-xs">
              <span className="block text-slate-600 mb-1">Nom</span>
              <input value={editing.name} onChange={(e) => setEditing((s) => ({ ...s, name: e.target.value }))}
                     className="w-full px-2 py-1.5 text-sm rounded ring-1 ring-slate-300" data-testid="cg-name-input" />
            </label>
            <label className="text-xs">
              <span className="block text-slate-600 mb-1">Description (facultative)</span>
              <textarea value={editing.description} onChange={(e) => setEditing((s) => ({ ...s, description: e.target.value }))}
                        rows={2} className="w-full px-2 py-1.5 text-sm rounded ring-1 ring-slate-300" data-testid="cg-desc-input" />
            </label>
            <div className="text-xs">
              <span className="block text-slate-600 mb-1">Couleur</span>
              <div className="flex gap-1.5">
                {DEFAULT_COLORS.map((c) => (
                  <button key={c} type="button" onClick={() => setEditing((s) => ({ ...s, color: c }))}
                          className={`h-7 w-7 rounded-full ring-2 transition ${editing.color === c ? "ring-slate-700" : "ring-transparent"}`}
                          style={{ background: c }} data-testid={`cg-color-${c.slice(1)}`} />
                ))}
              </div>
            </div>
            <TenantSharingToggle
              shared={editing.shared_with_tenant}
              editable={editing.editable_by_tenant}
              onChange={(next) => setEditing((s) => ({ ...s, ...next }))}
              testidPrefix="cg-tenant-sharing"
            />
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => setEditing(null)} className="text-xs px-3 py-1.5 rounded ring-1 ring-slate-300 hover:bg-slate-50">Annuler</button>
              <button onClick={save} className="text-xs px-3 py-1.5 rounded bg-fuchsia-600 hover:bg-fuchsia-700 text-white inline-flex items-center gap-1" data-testid="cg-save-btn">
                <Save className="h-3.5 w-3.5" /> Enregistrer
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Picker modal */}
      {pickerOpen && pickerGroup && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" data-testid="cg-picker-modal">
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl p-5 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-slate-800 flex items-center gap-2">
                <UserPlus className="h-4 w-4" /> Ajouter des contacts à « {pickerGroup.name} »
              </h2>
              <button onClick={() => setPickerOpen(false)} className="text-slate-400 hover:text-slate-700"><X className="h-4 w-4" /></button>
            </div>
            <div className="relative">
              <Search className="absolute left-2 top-2 h-4 w-4 text-slate-400" />
              <input value={pickerSearch} onChange={(e) => setPickerSearch(e.target.value)}
                     placeholder="Rechercher un contact (nom, tel, email)…"
                     className="w-full pl-8 pr-2 py-1.5 text-sm rounded ring-1 ring-slate-300"
                     data-testid="cg-picker-search" />
            </div>
            <div className="max-h-72 overflow-y-auto ring-1 ring-slate-200 rounded divide-y" data-testid="cg-picker-list">
              {filteredPickerContacts.length === 0 && (
                <div className="text-xs text-slate-500 p-3">Aucun contact à ajouter.</div>
              )}
              {filteredPickerContacts.map((c) => {
                const checked = pickerSelection.includes(c.id);
                return (
                  <label key={c.id} className="flex items-center gap-2 px-2 py-1.5 hover:bg-slate-50 cursor-pointer text-xs">
                    <input type="checkbox" checked={checked} onChange={(e) => {
                      setPickerSelection((s) => e.target.checked ? [...s, c.id] : s.filter((x) => x !== c.id));
                    }} className="h-3.5 w-3.5 text-fuchsia-600" />
                    <span className="font-medium text-slate-700">{c.name || "(sans nom)"}</span>
                    <span className="text-slate-500">{c.phone || c.whatsapp || c.email || ""}</span>
                    {c.company && <span className="text-[10px] text-slate-400 ml-auto">{c.company}</span>}
                  </label>
                );
              })}
            </div>
            <div className="flex justify-between items-center pt-2">
              <span className="text-xs text-slate-500">{pickerSelection.length} sélectionné(s)</span>
              <div className="flex gap-2">
                <button onClick={() => setPickerOpen(false)} className="text-xs px-3 py-1.5 rounded ring-1 ring-slate-300 hover:bg-slate-50">Annuler</button>
                <button onClick={addContactsToGroup} disabled={!pickerSelection.length}
                        className="text-xs px-3 py-1.5 rounded bg-fuchsia-600 hover:bg-fuchsia-700 text-white disabled:opacity-50"
                        data-testid="cg-picker-confirm">
                  Ajouter ({pickerSelection.length})
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Groups list */}
      {groups.length === 0 && (
        <div className="text-center text-slate-500 py-12 text-sm">
          <Users className="h-12 w-12 mx-auto text-slate-300 mb-2" />
          Aucun groupe. Cliquez sur « Nouveau groupe » pour commencer.
        </div>
      )}
      <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
        {groups.map((g) => (
          <div key={g.id} className="rounded-xl ring-1 ring-slate-200 bg-white p-4 space-y-3" data-testid={`cg-card-${g.id}`}>
            <div className="flex items-start gap-2">
              <div className="h-3 w-3 rounded-full mt-1.5 flex-shrink-0" style={{ background: g.color || "#6366f1" }} />
              <div className="flex-1 min-w-0">
                <h3 className="font-semibold text-slate-800 truncate">{g.name}</h3>
                {g.description && <p className="text-[11px] text-slate-500 mt-0.5">{g.description}</p>}
              </div>
              <span className="text-[10px] text-slate-500 bg-slate-100 rounded-full px-2 py-0.5">
                {g.contact_count} contact{g.contact_count > 1 ? "s" : ""}
              </span>
            </div>
            <div className="max-h-32 overflow-y-auto text-[11px] space-y-0.5">
              {(g.contact_ids || []).slice(0, 20).map((cid) => {
                const c = contactById[cid];
                return (
                  <div key={cid} className="flex items-center gap-1 text-slate-600 group">
                    <span className="truncate flex-1">{c ? (c.name || c.phone || cid) : `(supprimé)`}</span>
                    <button onClick={() => removeFromGroup(g, cid)} className="text-slate-300 hover:text-rose-600 opacity-0 group-hover:opacity-100" data-testid={`cg-remove-${g.id}-${cid}`}>
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                );
              })}
              {(g.contact_ids || []).length > 20 && (
                <div className="text-[10px] text-slate-400 italic">+ {(g.contact_ids || []).length - 20} de plus</div>
              )}
            </div>
            <div className="flex gap-1.5 pt-2 border-t border-slate-100">
              <button onClick={() => openPicker(g)} className="text-[11px] px-2 py-1 rounded bg-fuchsia-50 text-fuchsia-700 hover:bg-fuchsia-100 inline-flex items-center gap-1 flex-1 justify-center" data-testid={`cg-add-${g.id}`}>
                <UserPlus className="h-3 w-3" /> Ajouter
              </button>
              <button onClick={() => startEdit(g)} className="text-[11px] px-2 py-1 rounded ring-1 ring-slate-200 hover:bg-slate-50 inline-flex items-center gap-1" data-testid={`cg-edit-${g.id}`}>
                <Pencil className="h-3 w-3" />
              </button>
              <button onClick={() => remove(g)} className="text-[11px] px-2 py-1 rounded ring-1 ring-rose-200 text-rose-600 hover:bg-rose-50 inline-flex items-center gap-1" data-testid={`cg-delete-${g.id}`}>
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
