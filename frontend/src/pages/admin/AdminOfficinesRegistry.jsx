// Iter43-fix9 (2026-03) — Admin Registre des Officines
// Ajouts : import CSV (séparateur ;), édition fiche complète (logo/intitulé/responsable/WA/géoloc),
// multi-sélection + import contacts (groupe "Officines"), colonnes Intitulé, WA, Activée.
import React from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  CheckCircle, XCircle, RefreshCw, Link as LinkIcon, Unlink, Search, Building2,
  Upload, Pencil, FileSpreadsheet, UserPlus, X, MapPin, Image as ImageIcon,
} from "lucide-react";

const STATUS_LABEL = {
  pending: { text: "En attente", color: "bg-amber-50 text-amber-700 ring-amber-200" },
  active: { text: "Active", color: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  suspended: { text: "Suspendue", color: "bg-rose-50 text-rose-700 ring-rose-200" },
};

const fmtDate = (iso) => {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString("fr-FR"); }
  catch { return "—"; }
};

export default function AdminOfficinesRegistry() {
  const [items, setItems] = React.useState([]);
  const [counts, setCounts] = React.useState({ pending: 0, active: 0, suspended: 0 });
  const [filter, setFilter] = React.useState("pending");
  const [q, setQ] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [linkingFor, setLinkingFor] = React.useState(null);
  const [editingFor, setEditingFor] = React.useState(null);
  const [importingCsv, setImportingCsv] = React.useState(false);
  const [selected, setSelected] = React.useState(() => new Set());
  const [importingContacts, setImportingContacts] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (filter !== "all") params.status = filter;
      if (q) params.q = q;
      const r = await apiClient.get("/admin/officines-registry", { params });
      setItems(r.data?.items || []);
      setCounts(r.data?.counts || {});
    } finally { setLoading(false); }
  }, [filter, q]);

  React.useEffect(() => { load(); }, [load]);

  const doAction = async (oid, action, label) => {
    if (!window.confirm(`Confirmer : ${label} ?`)) return;
    try {
      await apiClient.post(`/admin/officines-registry/${oid}/${action}`);
      toast.success(label);
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec");
    }
  };

  // ---------------- Multi-select ----------------
  const allSelected = items.length > 0 && items.every((it) => selected.has(it.id));
  const toggleSelectAll = () => {
    setSelected((prev) => {
      if (allSelected) return new Set();
      const next = new Set();
      items.forEach((it) => next.add(it.id));
      return next;
    });
  };
  const toggleSelect = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const importSelectionToContacts = async () => {
    if (selected.size === 0) {
      toast.error("Sélectionnez au moins une officine");
      return;
    }
    if (!window.confirm(`Importer ${selected.size} officine(s) dans le répertoire de contacts (groupe « Officines ») ?`)) return;
    setImportingContacts(true);
    try {
      const r = await apiClient.post("/admin/officines-registry/import-to-contacts", {
        officine_ids: Array.from(selected),
        group_name: "Officines",
      });
      const { created, already_existing, total_in_group } = r.data || {};
      toast.success(`${created} nouveau(x) contact(s), ${already_existing} déjà existant(s) — ${total_in_group} dans le groupe « Officines »`);
      setSelected(new Set());
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec import contacts");
    } finally { setImportingContacts(false); }
  };

  return (
    <div className="space-y-5" data-testid="admin-officines-registry">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-display font-bold text-slate-900 inline-flex items-center gap-2">
            <Building2 className="h-6 w-6" /> Registre des Officines
          </h1>
          <p className="text-sm text-slate-600 mt-1">
            Importez en masse via CSV, validez les nouvelles pharmacies et gérez leurs fiches.
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button onClick={() => setImportingCsv(true)}
                  className="inline-flex items-center gap-2 text-sm px-3 py-2 rounded-lg bg-sawali-blue text-white hover:bg-sawali-blue/90"
                  data-testid="csv-import-btn">
            <FileSpreadsheet className="h-4 w-4" /> Importer CSV
          </button>
          {selected.size > 0 && (
            <button onClick={importSelectionToContacts}
                    disabled={importingContacts}
                    className="inline-flex items-center gap-2 text-sm px-3 py-2 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50"
                    data-testid="import-to-contacts-btn">
              <UserPlus className="h-4 w-4" />
              {importingContacts ? "Import…" : `Importer ${selected.size} → Contacts`}
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <Counter label="En attente" value={counts.pending} color="amber" active={filter === "pending"} onClick={() => setFilter("pending")} testid="counter-pending" />
        <Counter label="Actives" value={counts.active} color="emerald" active={filter === "active"} onClick={() => setFilter("active")} testid="counter-active" />
        <Counter label="Suspendues" value={counts.suspended} color="rose" active={filter === "suspended"} onClick={() => setFilter("suspended")} testid="counter-suspended" />
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative max-w-md flex-1">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
          <input value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="Rechercher par nom, email, ville…"
            className="w-full pl-9 pr-3 py-2 border rounded-lg text-sm"
            data-testid="registry-search" />
        </div>
        <button onClick={() => setFilter("all")} className={`text-xs px-3 py-2 rounded-lg ring-1 ${filter === "all" ? "bg-sawali-blue text-white ring-sawali-blue" : "bg-white text-slate-700 ring-slate-200 hover:bg-slate-50"}`} data-testid="filter-all">
          Tous
        </button>
        <button onClick={load} className="text-xs px-3 py-2 rounded-lg bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50" data-testid="registry-refresh">
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="bg-white rounded-xl shadow-sm ring-1 ring-slate-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[1100px]">
            <thead className="bg-slate-50 text-slate-600 text-left">
              <tr>
                <th className="px-3 py-2 w-10">
                  <input type="checkbox" checked={allSelected} onChange={toggleSelectAll}
                         className="h-4 w-4 cursor-pointer"
                         data-testid="registry-select-all"
                         title={allSelected ? "Tout désélectionner" : "Tout sélectionner"} />
                </th>
                <th className="px-3 py-2 font-medium">Officine</th>
                <th className="px-3 py-2 font-medium">Intitulé</th>
                <th className="px-3 py-2 font-medium">Email</th>
                <th className="px-3 py-2 font-medium">Téléphone</th>
                <th className="px-3 py-2 font-medium">WA</th>
                <th className="px-3 py-2 font-medium">Ville</th>
                <th className="px-3 py-2 font-medium">Statut</th>
                <th className="px-3 py-2 font-medium">Client CRM</th>
                <th className="px-3 py-2 font-medium">Créée</th>
                <th className="px-3 py-2 font-medium">Activée</th>
                <th className="px-3 py-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody data-testid="registry-table-body">
              {loading && <tr><td colSpan={12} className="px-3 py-6 text-center text-slate-400">Chargement…</td></tr>}
              {!loading && items.length === 0 && (
                <tr><td colSpan={12} className="px-3 py-6 text-center text-slate-400">Aucune officine.</td></tr>
              )}
              {items.map((it) => {
                const st = STATUS_LABEL[it.status] || { text: it.status, color: "bg-slate-50" };
                const isSel = selected.has(it.id);
                return (
                  <tr key={it.id}
                      className={`border-t border-slate-100 hover:bg-slate-50 ${isSel ? "bg-sky-50/50" : ""}`}
                      data-testid={`registry-row-${it.id}`}>
                    <td className="px-3 py-2">
                      <input type="checkbox" checked={isSel} onChange={() => toggleSelect(it.id)}
                             className="h-4 w-4 cursor-pointer"
                             data-testid={`registry-select-${it.id}`} />
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        {it.logo_url ? (
                          <img src={it.logo_url} alt="" className="h-7 w-7 rounded object-cover ring-1 ring-slate-200" />
                        ) : (
                          <div className="h-7 w-7 rounded bg-slate-100 ring-1 ring-slate-200 flex items-center justify-center">
                            <Building2 className="h-3.5 w-3.5 text-slate-400" />
                          </div>
                        )}
                        <div className="min-w-0">
                          <p className="font-medium text-slate-900 truncate" title={it.name}>{it.name}</p>
                          {it.contact_name && <p className="text-[11px] text-slate-500 truncate">{it.contact_name}</p>}
                          {it.numero_ordre && <p className="text-[10px] text-slate-400">Ordre : {it.numero_ordre}</p>}
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-2 text-slate-700 text-xs">{it.intitule || <span className="italic text-slate-400">—</span>}</td>
                    <td className="px-3 py-2 text-slate-600 text-xs">{it.email || "—"}</td>
                    <td className="px-3 py-2 text-slate-600 text-xs font-mono">{it.phone || "—"}</td>
                    <td className="px-3 py-2 text-slate-600 text-xs font-mono">{it.whatsapp || <span className="italic text-slate-400">—</span>}</td>
                    <td className="px-3 py-2 text-slate-600 text-xs">{it.city || "—"}</td>
                    <td className="px-3 py-2">
                      <span className={`text-[10px] uppercase tracking-wider font-medium px-2 py-1 rounded ring-1 ${st.color}`}>
                        {st.text}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-600">
                      {it.linked_client_id ? (
                        <span className="inline-flex items-center gap-1">
                          <LinkIcon className="h-3 w-3 text-emerald-600" />
                          {it.linked_client_email || it.linked_client_id.slice(0, 8)}
                        </span>
                      ) : "—"}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-slate-500 tabular-nums whitespace-nowrap">
                      {fmtDate(it.created_at)}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-slate-500 tabular-nums whitespace-nowrap">
                      {it.activated_at || it.validated_at ? (
                        <span className="inline-flex items-center gap-1 text-emerald-700">
                          <CheckCircle className="h-3 w-3" /> {fmtDate(it.activated_at || it.validated_at)}
                        </span>
                      ) : <span className="italic text-slate-400">—</span>}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <div className="inline-flex gap-1">
                        <button onClick={() => setEditingFor(it)}
                                className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded bg-sky-50 hover:bg-sky-100 text-sky-700 ring-1 ring-sky-200"
                                data-testid={`edit-${it.id}`}
                                title="Modifier la fiche">
                          <Pencil className="h-3 w-3" />
                        </button>
                        {it.status === "pending" && (
                          <button onClick={() => doAction(it.id, "approve", "Activer")}
                            className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded bg-emerald-600 text-white hover:bg-emerald-700"
                            data-testid={`approve-${it.id}`}>
                            <CheckCircle className="h-3 w-3" /> Activer
                          </button>
                        )}
                        {it.status === "active" && (
                          <button onClick={() => doAction(it.id, "suspend", "Suspendre")}
                            className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded bg-rose-600 text-white hover:bg-rose-700"
                            data-testid={`suspend-${it.id}`}>
                            <XCircle className="h-3 w-3" /> Suspendre
                          </button>
                        )}
                        {it.status === "suspended" && (
                          <button onClick={() => doAction(it.id, "reactivate", "Réactiver")}
                            className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded bg-emerald-600 text-white hover:bg-emerald-700"
                            data-testid={`reactivate-${it.id}`}>
                            <CheckCircle className="h-3 w-3" /> Réactiver
                          </button>
                        )}
                        <button onClick={() => setLinkingFor(it)}
                          className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 ring-1 ring-slate-200"
                          data-testid={`link-${it.id}`}
                          title="Lier à un client CRM">
                          <LinkIcon className="h-3 w-3" />
                        </button>
                        {it.linked_client_id && (
                          <button onClick={() => doAction(it.id, "unlink-client", "Délier")}
                            className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 ring-1 ring-slate-200"
                            data-testid={`unlink-${it.id}`}>
                            <Unlink className="h-3 w-3" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {linkingFor && (
        <LinkClientModal officine={linkingFor} onClose={() => setLinkingFor(null)} onDone={() => { setLinkingFor(null); load(); }} />
      )}
      {editingFor && (
        <EditOfficineModal officine={editingFor} onClose={() => setEditingFor(null)} onSaved={() => { setEditingFor(null); load(); }} />
      )}
      {importingCsv && (
        <CsvImportModal onClose={() => setImportingCsv(false)} onDone={() => { setImportingCsv(false); load(); }} />
      )}
    </div>
  );
}

function Counter({ label, value, color, active, onClick, testid }) {
  const tone = {
    amber: active ? "bg-amber-600 text-white" : "bg-amber-50 text-amber-700 hover:bg-amber-100 ring-1 ring-amber-200",
    emerald: active ? "bg-emerald-600 text-white" : "bg-emerald-50 text-emerald-700 hover:bg-emerald-100 ring-1 ring-emerald-200",
    rose: active ? "bg-rose-600 text-white" : "bg-rose-50 text-rose-700 hover:bg-rose-100 ring-1 ring-rose-200",
  }[color];
  return (
    <button onClick={onClick} className={`block rounded-xl p-4 text-left transition ${tone}`} data-testid={testid}>
      <p className="text-xs uppercase tracking-wider opacity-80">{label}</p>
      <p className="text-2xl font-bold tabular-nums mt-1">{value}</p>
    </button>
  );
}

function LinkClientModal({ officine, onClose, onDone }) {
  const [email, setEmail] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await apiClient.post(`/admin/officines-registry/${officine.id}/link-client`, { client_email: email });
      toast.success("Officine liée au client CRM");
      onDone();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec");
    } finally { setBusy(false); }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4" data-testid="link-client-modal">
      <form onSubmit={submit} className="bg-white rounded-xl shadow-2xl w-full max-w-md">
        <div className="px-5 py-3 border-b">
          <h3 className="font-display font-semibold text-slate-900">Lier à un client CRM</h3>
          <p className="text-xs text-slate-500 mt-0.5">Officine : <span className="font-medium">{officine.name}</span></p>
        </div>
        <div className="p-5 space-y-3">
          <label className="block text-xs font-medium text-slate-700">Email du client CRM existant</label>
          <input required type="email" value={email} onChange={(e) => setEmail(e.target.value)}
            placeholder="client@example.com"
            className="w-full border rounded px-3 py-2 text-sm"
            data-testid="link-client-email" />
        </div>
        <div className="px-5 py-3 border-t bg-slate-50 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="px-3 py-2 rounded text-sm bg-slate-200 hover:bg-slate-300 text-slate-700" data-testid="link-client-cancel">Annuler</button>
          <button type="submit" disabled={busy} className="px-3 py-2 rounded text-sm bg-sawali-blue text-white hover:bg-sawali-blue/90 disabled:opacity-50" data-testid="link-client-submit">
            {busy ? "Liaison…" : "Lier"}
          </button>
        </div>
      </form>
    </div>
  );
}

// ============================================================
// Iter43-fix9 — Édition fiche officine complète
// ============================================================
function EditOfficineModal({ officine, onClose, onSaved }) {
  const [form, setForm] = React.useState({
    name: officine.name || "",
    intitule: officine.intitule || "",
    contact_name: officine.contact_name || "",
    email: officine.email || "",
    phone: officine.phone || "",
    whatsapp: officine.whatsapp || "",
    address: officine.address || "",
    city: officine.city || "",
    country: officine.country || "",
    location_hint: officine.location_hint || "",
    numero_ordre: officine.numero_ordre || "",
    latitude: officine.latitude ?? "",
    longitude: officine.longitude ?? "",
  });
  const [logoUrl, setLogoUrl] = React.useState(officine.logo_url || "");
  const [logoBusy, setLogoBusy] = React.useState(false);
  const [saving, setSaving] = React.useState(false);

  const onChange = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const detectLocation = () => {
    if (!navigator.geolocation) {
      toast.error("Géolocalisation non supportée par ce navigateur");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setForm((f) => ({
          ...f,
          latitude: pos.coords.latitude.toFixed(6),
          longitude: pos.coords.longitude.toFixed(6),
        }));
        toast.success("Coordonnées détectées");
      },
      (err) => toast.error(`Erreur géoloc : ${err.message}`),
    );
  };

  const uploadLogo = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLogoBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await apiClient.post(
        `/admin/officines-registry/${officine.id}/upload-logo`,
        fd,
        { headers: { "Content-Type": "multipart/form-data" } },
      );
      setLogoUrl(r.data?.logo_url || "");
      toast.success("Logo téléversé");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec upload logo");
    } finally { setLogoBusy(false); }
  };

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = { ...form };
      // Sanitize numbers
      payload.latitude = payload.latitude === "" ? null : Number(payload.latitude);
      payload.longitude = payload.longitude === "" ? null : Number(payload.longitude);
      await apiClient.put(`/admin/officines-registry/${officine.id}`, payload);
      toast.success("Fiche mise à jour");
      onSaved();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec mise à jour");
    } finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 py-6" data-testid="edit-officine-modal">
      <form onSubmit={submit} className="bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="px-5 py-3 border-b sticky top-0 bg-white z-10 flex items-center justify-between">
          <div>
            <h3 className="font-display font-semibold text-slate-900 inline-flex items-center gap-2">
              <Pencil className="h-4 w-4 text-sawali-blue" /> Modifier la fiche
            </h3>
            <p className="text-[11px] text-slate-500 mt-0.5">Officine : <span className="font-medium">{officine.name}</span></p>
          </div>
          <button type="button" onClick={onClose} className="text-slate-500 hover:text-slate-900" data-testid="edit-officine-close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-5 space-y-4">
          {/* Logo */}
          <div className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200">
            <label className="block text-xs font-semibold mb-2 inline-flex items-center gap-1">
              <ImageIcon className="h-3 w-3 text-sawali-blue" /> Logo de l'officine
            </label>
            <div className="flex items-center gap-3">
              {logoUrl ? (
                <img src={logoUrl} alt="" className="h-16 w-16 rounded-lg object-cover ring-1 ring-slate-200" data-testid="edit-officine-logo-preview" />
              ) : (
                <div className="h-16 w-16 rounded-lg bg-white ring-1 ring-slate-200 flex items-center justify-center">
                  <ImageIcon className="h-6 w-6 text-slate-300" />
                </div>
              )}
              <label className="text-xs inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-white ring-1 ring-slate-300 hover:bg-slate-50 cursor-pointer">
                <Upload className="h-3 w-3" />
                {logoBusy ? "Téléversement…" : "Téléverser un logo"}
                <input type="file" accept="image/*" className="hidden" onChange={uploadLogo} disabled={logoBusy} data-testid="edit-officine-logo-input" />
              </label>
            </div>
            <p className="text-[10px] text-slate-500 mt-1.5">PNG / JPG / WEBP / SVG, 5 Mo max.</p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field label="Nom (= code)" required value={form.name} onChange={onChange("name")} testid="edit-name" />
            <Field label="Intitulé" value={form.intitule} onChange={onChange("intitule")} testid="edit-intitule" placeholder="Libellé commercial" />
            <Field label="Nom du responsable" value={form.contact_name} onChange={onChange("contact_name")} testid="edit-contact-name" />
            <Field label="Email" type="email" value={form.email} onChange={onChange("email")} testid="edit-email" />
            <Field label="Téléphone" value={form.phone} onChange={onChange("phone")} testid="edit-phone" placeholder="+22670…" />
            <Field label="WhatsApp" value={form.whatsapp} onChange={onChange("whatsapp")} testid="edit-whatsapp" placeholder="+22670…" />
            <Field label="Adresse" value={form.address} onChange={onChange("address")} testid="edit-address" />
            <Field label="Ville" value={form.city} onChange={onChange("city")} testid="edit-city" />
            <Field label="Pays" value={form.country} onChange={onChange("country")} testid="edit-country" />
            <Field label="N° d'ordre" value={form.numero_ordre} onChange={onChange("numero_ordre")} testid="edit-ordre" />
            <Field label="Indications de localisation" value={form.location_hint} onChange={onChange("location_hint")} testid="edit-location-hint" wide />
          </div>

          {/* Géolocalisation */}
          <div className="rounded-lg bg-sky-50 p-3 ring-1 ring-sky-200">
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-semibold inline-flex items-center gap-1 text-sky-900">
                <MapPin className="h-3 w-3" /> Géolocalisation
              </label>
              <button type="button" onClick={detectLocation}
                      className="text-[11px] px-2 py-1 rounded bg-white ring-1 ring-sky-300 hover:bg-sky-100 text-sky-700"
                      data-testid="edit-detect-location">
                Détecter ma position
              </button>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Latitude" value={form.latitude} onChange={onChange("latitude")} testid="edit-latitude" placeholder="12.345678" inline />
              <Field label="Longitude" value={form.longitude} onChange={onChange("longitude")} testid="edit-longitude" placeholder="-1.234567" inline />
            </div>
            {form.latitude && form.longitude && (
              <a href={`https://www.google.com/maps?q=${form.latitude},${form.longitude}`}
                 target="_blank" rel="noopener noreferrer"
                 className="text-[11px] text-sky-700 hover:underline inline-flex items-center gap-1 mt-2"
                 data-testid="edit-map-link">
                Voir sur Google Maps →
              </a>
            )}
          </div>
        </div>
        <div className="px-5 py-3 border-t bg-slate-50 flex justify-end gap-2 sticky bottom-0">
          <button type="button" onClick={onClose} className="px-3 py-2 rounded text-sm bg-slate-200 hover:bg-slate-300 text-slate-700">
            Annuler
          </button>
          <button type="submit" disabled={saving}
                  className="px-3 py-2 rounded text-sm bg-sawali-blue text-white hover:bg-sawali-blue/90 disabled:opacity-50"
                  data-testid="edit-officine-save">
            {saving ? "Enregistrement…" : "Enregistrer"}
          </button>
        </div>
      </form>
    </div>
  );
}

function Field({ label, value, onChange, testid, type = "text", required = false, placeholder = "", wide = false, inline = false }) {
  return (
    <label className={`block ${wide ? "sm:col-span-2" : ""}`}>
      <span className={`block ${inline ? "text-[10px]" : "text-xs"} font-medium text-slate-700 mb-1`}>{label}{required && " *"}</span>
      <input type={type} value={value || ""} onChange={onChange} required={required}
             placeholder={placeholder}
             className="w-full border border-slate-300 rounded px-3 py-2 text-sm"
             data-testid={testid} />
    </label>
  );
}

// ============================================================
// Iter43-fix9 — Import CSV (séparateur `;`)
// ============================================================
function CsvImportModal({ onClose, onDone }) {
  const [file, setFile] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [report, setReport] = React.useState(null);

  const submit = async (e) => {
    e.preventDefault();
    if (!file) {
      toast.error("Sélectionnez un fichier CSV");
      return;
    }
    setBusy(true);
    setReport(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await apiClient.post("/admin/officines-registry/import-csv", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setReport(r.data);
      toast.success(`${r.data?.created || 0} officine(s) importée(s) — ${r.data?.skipped || 0} ignorée(s)`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec import CSV");
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 py-6" data-testid="csv-import-modal">
      <form onSubmit={submit} className="bg-white rounded-xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="px-5 py-3 border-b flex items-center justify-between">
          <h3 className="font-display font-semibold text-slate-900 inline-flex items-center gap-2">
            <FileSpreadsheet className="h-4 w-4 text-sawali-blue" /> Importer un fichier CSV
          </h3>
          <button type="button" onClick={onClose} className="text-slate-500 hover:text-slate-900" data-testid="csv-import-close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-5 space-y-3">
          <div className="rounded-lg bg-amber-50 ring-1 ring-amber-200 p-3 text-xs text-amber-900">
            <p className="font-semibold mb-1">Format attendu (séparateur <code className="px-1 bg-white rounded">;</code>) :</p>
            <code className="block bg-white rounded p-2 ring-1 ring-amber-200 text-[11px] overflow-x-auto whitespace-nowrap">
              Nom de la pharmacie;Téléphone;Ville;Indications de localisation;Numéro d'ordre
            </code>
            <p className="mt-2 text-[11px]">
              Le « Nom de la pharmacie » est également utilisé comme code. Les lignes
              sont importées avec le statut <strong>En attente</strong>.
            </p>
          </div>
          <label className="block">
            <span className="block text-xs font-medium text-slate-700 mb-1">Fichier CSV *</span>
            <input type="file" accept=".csv,text/csv" required
                   onChange={(e) => setFile(e.target.files?.[0] || null)}
                   className="block w-full text-sm"
                   data-testid="csv-import-file" />
          </label>

          {report && (
            <div className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200 max-h-60 overflow-y-auto" data-testid="csv-import-report">
              <p className="text-sm font-semibold text-slate-800">
                Résultat : {report.created} créée(s) · {report.skipped} ignorée(s)
              </p>
              {report.results?.length > 0 && (
                <ul className="mt-2 space-y-1 text-[11px]">
                  {report.results.slice(0, 20).map((r, idx) => (
                    <li key={idx} className={`px-2 py-1 rounded ${r.skipped ? "bg-amber-100 text-amber-800" : "bg-emerald-100 text-emerald-800"}`}>
                      Ligne {r.row} : {r.skipped ? `ignorée — ${r.reason}` : `créée — ${r.name}`}
                    </li>
                  ))}
                  {report.results.length > 20 && (
                    <li className="text-slate-400 italic">…et {report.results.length - 20} autres</li>
                  )}
                </ul>
              )}
            </div>
          )}
        </div>
        <div className="px-5 py-3 border-t bg-slate-50 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="px-3 py-2 rounded text-sm bg-slate-200 hover:bg-slate-300 text-slate-700">
            Fermer
          </button>
          {report ? (
            <button type="button" onClick={onDone}
                    className="px-3 py-2 rounded text-sm bg-sawali-blue text-white hover:bg-sawali-blue/90"
                    data-testid="csv-import-done">
              Voir le registre
            </button>
          ) : (
            <button type="submit" disabled={busy || !file}
                    className="px-3 py-2 rounded text-sm bg-sawali-blue text-white hover:bg-sawali-blue/90 disabled:opacity-50"
                    data-testid="csv-import-submit">
              {busy ? "Import en cours…" : "Lancer l'import"}
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
