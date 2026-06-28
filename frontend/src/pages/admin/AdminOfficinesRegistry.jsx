// Iter43-fix9 (2026-03) — Admin Registre des Officines
// Ajouts : import CSV (séparateur ;), édition fiche complète (logo/intitulé/responsable/WA/géoloc),
// multi-sélection + import contacts (groupe "Officines"), colonnes Intitulé, WA, Activée.
// Iter43-fix12 (2026-03) — Tri alphabétique, colonnes Activité + Nb produits,
// import produits CSV/JSON, modale produits, gestion activités principales.
import React from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  CheckCircle, XCircle, RefreshCw, Link as LinkIcon, Unlink, Search, Building2,
  Upload, Pencil, FileSpreadsheet, UserPlus, X, MapPin, Image as ImageIcon,
  Eye, Package, Tags, Download, Plus, Trash2, FileJson, Tag, Globe2, Loader2,
} from "lucide-react";

const STATUS_LABEL = {
  pending: { text: "En attente", color: "bg-amber-50 text-amber-700 ring-amber-200" },
  active: { text: "Active", color: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  suspended: { text: "Suspendue", color: "bg-rose-50 text-rose-700 ring-rose-200" },
};

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "";
// Iter43-fix10b — Construit l'URL complète d'un logo (endpoint public).
// Accepte les anciennes URLs `/uploads/officines/...` et les nouvelles
// `/officines-registry/{id}/logo`.
const logoSrc = (logoUrl) => {
  if (!logoUrl) return null;
  if (logoUrl.startsWith("http")) return logoUrl;
  if (logoUrl.startsWith("/officines-registry/")) return `${BACKEND_URL}/api${logoUrl}`;
  if (logoUrl.startsWith("/uploads/")) {
    // Ancien format - le backend a une route de migration
    return `${BACKEND_URL}/api${logoUrl}`;
  }
  return `${BACKEND_URL}${logoUrl}`;
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
  const [filterActivite, setFilterActivite] = React.useState(""); // Iter43-fix12 (déprécié dans l'UI)
  const [filterRole, setFilterRole] = React.useState(""); // Iter43-fix23 — Filtre par rôle (remplace activité)
  // Iter43-fix24az-e (2026-02-26) — Filtre par groupe de garde + groupe en
  // garde courante mis en évidence en rouge.
  const [filterGardeGroup, setFilterGardeGroup] = React.useState("");
  const [currentGardeGroup, setCurrentGardeGroup] = React.useState(null);
  const [gardeGroupsAvailable, setGardeGroupsAvailable] = React.useState([]);
  const [activities, setActivities] = React.useState([]); // Iter43-fix12
  const [roles, setRoles] = React.useState([]); // Iter43-fix23 — liste des rôles disponibles
  const [q, setQ] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [linkingFor, setLinkingFor] = React.useState(null);
  const [editingFor, setEditingFor] = React.useState(null);
  const [importingCsv, setImportingCsv] = React.useState(false);
  const [selected, setSelected] = React.useState(() => new Set());
  const [importingContacts, setImportingContacts] = React.useState(false);
  // Iter43-fix12 — Produits + activités
  const [viewingProductsFor, setViewingProductsFor] = React.useState(null);
  const [importingProductsFor, setImportingProductsFor] = React.useState(null);
  const [managingActivities, setManagingActivities] = React.useState(false);
  // Iter43-fix21 — Bulk-assign + gestion rôles
  const [showBulkAssign, setShowBulkAssign] = React.useState(false);
  const [showRolesAdmin, setShowRolesAdmin] = React.useState(false);
  // Iter43-fix23 — Création manuelle d'une officine
  const [showCreate, setShowCreate] = React.useState(false);

  // Iter43-fix24n (2026-06) — Délégation menu Officines (permissions limited/full)
  const [permissions, setPermissions] = React.useState({ can_view: true, edit_mode: "full" });

  const loadPermissions = React.useCallback(async () => {
    try {
      const r = await apiClient.get("/me/officines-permissions");
      setPermissions({
        can_view: !!r.data?.can_view,
        edit_mode: r.data?.edit_mode || "full",
      });
    } catch { /* admin endpoint absent → fallback: full access (legacy) */ }
  }, []);

  React.useEffect(() => { loadPermissions(); }, [loadPermissions]);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (filter !== "all") params.status = filter;
      if (filterRole) params.role = filterRole;
      if (q) params.q = q;
      const r = await apiClient.get("/admin/officines-registry", { params });
      setItems(r.data?.items || []);
      setCounts(r.data?.counts || {});
    } finally { setLoading(false); }
  }, [filter, filterRole, q]);

  // Iter43-fix24az-e — Charge le groupe en garde courante + la liste complète des groupes utilisés
  const loadGardeMeta = React.useCallback(async () => {
    try {
      const [cur, year] = [await apiClient.get("/public/officines/garde/current"), new Date().getFullYear()];
      setCurrentGardeGroup(cur.data?.groupe_garde ?? null);
      // Liste des groupes disponibles (depuis le planning admin pour avoir les comptes)
      const plan = await apiClient.get(`/admin/officines-registry/garde-planning?year=${year}`).catch(() => null);
      const groups = plan?.data?.groups_with_count || [];
      setGardeGroupsAvailable(groups);
    } catch { /* noop */ }
  }, []);

  React.useEffect(() => { loadGardeMeta(); }, [loadGardeMeta]);

  // Filtrage par groupe de garde (client-side, sur les items déjà chargés)
  const filteredItems = React.useMemo(() => {
    if (!filterGardeGroup) return items;
    const target = Number(filterGardeGroup);
    return items.filter((it) => Number(it.groupe_garde) === target);
  }, [items, filterGardeGroup]);

  // Suppression d'un groupe vide
  const deleteEmptyGroup = async (groupNum) => {
    if (!window.confirm(
      `Supprimer le groupe ${groupNum} ?\n\n`
      + "Cette action n'est possible QUE s'il n'y a plus aucune officine assignée à ce groupe. "
      + "Les semaines du planning qui le référençaient seront nettoyées."
    )) return;
    try {
      const r = await apiClient.delete(`/admin/officines-registry/garde-groups/${groupNum}`);
      toast.success(`Groupe ${groupNum} supprimé (${r.data?.planning_rows_cleaned ?? 0} entrées planning nettoyées)`);
      if (Number(filterGardeGroup) === groupNum) setFilterGardeGroup("");
      await loadGardeMeta();
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Suppression impossible");
    }
  };

  const loadActivities = React.useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/officine-activities");
      setActivities(r.data?.activities || []);
    } catch { /* noop */ }
  }, []);

  const loadRoles = React.useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/officines-registry/roles");
      setRoles(r.data?.roles || []);
    } catch { /* noop */ }
  }, []);

  React.useEffect(() => { load(); }, [load]);
  React.useEffect(() => { loadActivities(); loadRoles(); }, [loadActivities, loadRoles]);

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

  // Iter43-fix24aw (2026-02-26) — Géocodage GPS via Google Maps / OSM Nominatim.
  const [geocoding, setGeocoding] = React.useState(false);
  const [geocodeResult, setGeocodeResult] = React.useState(null);
  const [overwriteGps, setOverwriteGps] = React.useState(false);
  const [geocodeProvider, setGeocodeProvider] = React.useState(null);

  // Pre-load provider info (Google vs OSM) on mount
  React.useEffect(() => {
    apiClient.get("/admin/geocode/config")
      .then((r) => setGeocodeProvider(r.data))
      .catch(() => setGeocodeProvider(null));
  }, []);

  const resolveGeolocation = async () => {
    if (selected.size === 0) {
      toast.error("Sélectionnez au moins une officine");
      return;
    }
    const provider = geocodeProvider?.provider === "google_places" ? "Google Maps" : "OpenStreetMap";
    const warn = geocodeProvider?.provider === "osm_nominatim"
      ? "\n\n⚠️ Provider actuel : OpenStreetMap (gratuit). Les pharmacies d'Afrique de l'Ouest sont peu indexées. Pour un meilleur résultat, configurez une clé Google Maps API dans Admin Settings → settings.global.google_maps_api_key."
      : "";
    if (!window.confirm(
      `Lancer la résolution GPS pour ${selected.size} officine(s) via ${provider} ?${warn}\n\n` +
      `${overwriteGps ? "🔄 Mode REMPLACEMENT : les coordonnées existantes seront écrasées." : "💾 Mode CONSERVATEUR : seules les officines sans GPS seront résolues."}\n\n` +
      "Cela peut prendre quelques minutes (OSM = 1 req/sec)."
    )) return;
    setGeocoding(true);
    setGeocodeResult(null);
    try {
      const r = await apiClient.post(
        "/admin/officines-registry/geocode-batch",
        { officine_ids: Array.from(selected), overwrite_existing: overwriteGps },
        { timeout: 600000 },  // 10 min total for big batches
      );
      setGeocodeResult(r.data);
      const { succeeded, failed, skipped, provider: usedProvider } = r.data;
      toast.success(
        `✅ ${succeeded} résolue(s), ❌ ${failed} échec(s), ⏭️ ${skipped} ignorée(s) — Source : ${usedProvider}`
      );
      // Refresh the list to display the new GPS values
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur résolution GPS");
    } finally {
      setGeocoding(false);
    }
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
          <button onClick={() => setShowCreate(true)}
                  className="inline-flex items-center gap-2 text-sm px-3 py-2 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700"
                  data-testid="create-officine-btn">
            <Plus className="h-4 w-4" /> Nouvelle officine
          </button>
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
          {/* Iter43-fix24aw — Bouton Résoudre géolocalisation */}
          {selected.size > 0 && (
            <div className="inline-flex items-stretch rounded-lg overflow-hidden ring-1 ring-cyan-300">
              <button
                onClick={resolveGeolocation}
                disabled={geocoding}
                className="inline-flex items-center gap-2 text-sm px-3 py-2 bg-cyan-600 text-white hover:bg-cyan-700 disabled:opacity-50"
                data-testid="resolve-geolocation-btn"
                title={geocodeProvider?.provider === "google_places"
                  ? "Résoudre les coordonnées GPS via Google Maps Places API"
                  : "Résoudre les coordonnées GPS via OpenStreetMap (gratuit mais peu de pharmacies indexées en Afrique de l'Ouest)"}
              >
                {geocoding ? <Loader2 className="h-4 w-4 animate-spin" /> : <Globe2 className="h-4 w-4" />}
                {geocoding ? "Résolution…" : `🌍 Résoudre géoloc (${selected.size})`}
              </button>
              <label className="inline-flex items-center gap-1 text-[10px] bg-cyan-50 px-2 cursor-pointer hover:bg-cyan-100" title="Écraser même les coordonnées déjà existantes">
                <input
                  type="checkbox"
                  checked={overwriteGps}
                  onChange={(e) => setOverwriteGps(e.target.checked)}
                  className="h-3 w-3"
                  data-testid="geocode-overwrite"
                />
                <span className="text-cyan-700">overwrite</span>
              </label>
            </div>
          )}
          {selected.size > 0 && (
            <button onClick={() => setShowBulkAssign(true)}
                    type="button"
                    className="inline-flex items-center gap-2 text-sm px-3 py-2 rounded-lg bg-violet-600 text-white hover:bg-violet-700"
                    data-testid="bulk-assign-btn">
              <Tag className="h-4 w-4" />
              Affecter rôle/groupe ({selected.size})
            </button>
          )}
          <button onClick={() => setShowRolesAdmin(true)}
                  type="button"
                  className="inline-flex items-center gap-2 text-sm px-3 py-2 rounded-lg bg-white ring-1 ring-slate-300 hover:bg-slate-50"
                  data-testid="manage-roles-btn">
            <Tag className="h-4 w-4 text-slate-500" />
            Gérer les rôles
          </button>
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
        {/* Iter43-fix23 (2026-06) — Filtre par rôle (remplace activité principale) */}
        <select
          value={filterRole}
          onChange={(e) => setFilterRole(e.target.value)}
          className="text-xs px-3 py-2 rounded-lg ring-1 ring-slate-200 bg-white text-slate-700 hover:bg-slate-50"
          data-testid="filter-role"
          title="Filtrer par rôle"
        >
          <option value="">Tous les rôles</option>
          {roles.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        {/* Iter43-fix24az-e — Filtre par groupe de garde + suppression groupe vide */}
        <select
          value={filterGardeGroup}
          onChange={(e) => setFilterGardeGroup(e.target.value)}
          className="text-xs px-3 py-2 rounded-lg ring-1 ring-slate-200 bg-white hover:bg-slate-50"
          data-testid="filter-garde-group"
          title={
            currentGardeGroup
              ? `Filtrer par groupe de garde — Groupe ${currentGardeGroup} est EN GARDE cette semaine`
              : "Filtrer par groupe de garde"
          }
          style={{ color: filterGardeGroup && Number(filterGardeGroup) === currentGardeGroup ? "#be123c" : undefined, fontWeight: filterGardeGroup && Number(filterGardeGroup) === currentGardeGroup ? 700 : undefined }}
        >
          <option value="">Tous les groupes de garde</option>
          {gardeGroupsAvailable.map((g) => {
            const isCurrent = g.groupe_garde === currentGardeGroup;
            return (
              <option
                key={g.groupe_garde}
                value={g.groupe_garde}
                style={isCurrent ? { color: "#be123c", fontWeight: 700 } : undefined}
              >
                {isCurrent ? "● " : ""}Groupe {g.groupe_garde} ({g.count} officines){isCurrent ? " — EN GARDE" : ""}
              </option>
            );
          })}
        </select>
        {filterGardeGroup && (
          (() => {
            const g = gardeGroupsAvailable.find((x) => x.groupe_garde === Number(filterGardeGroup));
            const empty = !g || g.count === 0;
            return empty ? (
              <button
                onClick={() => deleteEmptyGroup(Number(filterGardeGroup))}
                className="text-xs px-3 py-2 rounded-lg bg-rose-50 text-rose-700 ring-1 ring-rose-300 hover:bg-rose-100 inline-flex items-center gap-1"
                data-testid="delete-empty-garde-group"
                title="Supprimer ce groupe vide"
              >
                <Trash2 className="h-3.5 w-3.5" /> Supprimer groupe {filterGardeGroup}
              </button>
            ) : null;
          })()
        )}
        <button
          onClick={() => setShowRolesAdmin(true)}
          className="text-xs px-3 py-2 rounded-lg bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50 inline-flex items-center gap-1"
          data-testid="manage-roles-inline-btn"
          title="Gérer les rôles d'officines"
        >
          <Tag className="h-3.5 w-3.5" /> Gérer rôles
        </button>
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
                <th className="px-3 py-2 font-medium">Rôle</th>
                <th className="px-3 py-2 font-medium">Email</th>
                <th className="px-3 py-2 font-medium">Téléphone</th>
                <th className="px-3 py-2 font-medium">WA</th>
                <th className="px-3 py-2 font-medium">Ville</th>
                <th className="px-3 py-2 font-medium">Produits</th>
                <th className="px-3 py-2 font-medium">Statut</th>
                <th className="px-3 py-2 font-medium">Client CRM</th>
                <th className="px-3 py-2 font-medium">Créée</th>
                <th className="px-3 py-2 font-medium">Activée</th>
                <th className="px-3 py-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody data-testid="registry-table-body">
              {loading && <tr><td colSpan={14} className="px-3 py-6 text-center text-slate-400">Chargement…</td></tr>}
              {!loading && filteredItems.length === 0 && (
                <tr><td colSpan={14} className="px-3 py-6 text-center text-slate-400">
                  {items.length === 0
                    ? "Aucune officine."
                    : `Aucune officine dans le groupe ${filterGardeGroup}.`}
                </td></tr>
              )}
              {filteredItems.map((it) => {
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
                          <img src={logoSrc(it.logo_url)} alt="" className="h-7 w-7 rounded object-cover ring-1 ring-slate-200" />
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
                    <td className="px-3 py-2 text-xs">
                      {it.role ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-violet-50 text-violet-700 ring-1 ring-violet-200" data-testid={`role-${it.id}`}>
                          <Tag className="h-3 w-3" /> {it.role}
                        </span>
                      ) : <span className="italic text-slate-400">—</span>}
                    </td>
                    <td className="px-3 py-2 text-slate-600 text-xs">{it.email || "—"}</td>
                    <td className="px-3 py-2 text-slate-600 text-xs font-mono">{it.phone || "—"}</td>
                    <td className="px-3 py-2 text-slate-600 text-xs font-mono">{it.whatsapp || <span className="italic text-slate-400">—</span>}</td>
                    <td className="px-3 py-2 text-slate-600 text-xs">{it.city || "—"}</td>
                    <td className="px-3 py-2 text-xs">
                      <button
                        onClick={() => setViewingProductsFor(it)}
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded ring-1 hover:bg-slate-50 transition"
                        title={`Voir les ${it.products_count || 0} produit(s)`}
                        data-testid={`view-products-${it.id}`}
                      >
                        <span className="tabular-nums font-semibold text-slate-700">
                          {it.products_count ?? 0}
                        </span>
                        <Eye className="h-3 w-3 text-sky-600" />
                      </button>
                    </td>
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
                        <button onClick={() => setImportingProductsFor(it)}
                                className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded bg-violet-50 hover:bg-violet-100 text-violet-700 ring-1 ring-violet-200"
                                data-testid={`import-products-${it.id}`}
                                title="Importer la liste des produits (CSV ou JSON)">
                          <Package className="h-3 w-3" />
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
        <EditOfficineModal
          officine={editingFor}
          activities={activities}
          editMode={permissions.edit_mode}
          onClose={() => setEditingFor(null)}
          onSaved={() => { setEditingFor(null); load(); }}
        />
      )}
      {importingCsv && (
        <CsvImportModal onClose={() => setImportingCsv(false)} onDone={() => { setImportingCsv(false); load(); }} />
      )}
      {/* Iter43-fix23 — Création manuelle d'une nouvelle officine */}
      {showCreate && (
        <CreateOfficineModal
          roles={roles}
          activities={activities}
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); load(); }}
        />
      )}
      {viewingProductsFor && (
        <ProductsModal
          officine={viewingProductsFor}
          onClose={() => setViewingProductsFor(null)}
          onImport={() => { setViewingProductsFor(null); setImportingProductsFor(viewingProductsFor); }}
        />
      )}
      {importingProductsFor && (
        <ImportProductsModal
          officine={importingProductsFor}
          onClose={() => setImportingProductsFor(null)}
          onDone={() => { setImportingProductsFor(null); load(); }}
        />
      )}
      {managingActivities && (
        <ManageActivitiesModal
          activities={activities}
          onClose={() => setManagingActivities(false)}
          onSaved={(next) => { setActivities(next); setManagingActivities(false); load(); }}
        />
      )}
      {/* Iter43-fix21 — Modals bulk-assign + admin rôles */}
      {showBulkAssign && (
        <BulkAssignModal
          selectedIds={Array.from(selected)}
          onClose={() => setShowBulkAssign(false)}
          onSaved={() => { setShowBulkAssign(false); setSelected(new Set()); load(); }}
        />
      )}
      {showRolesAdmin && (
        <RolesAdminModal
          onClose={() => setShowRolesAdmin(false)}
        />
      )}
      {/* Iter43-fix24aw — Modal résultat de géocodage */}
      {geocodeResult && (
        <GeocodeResultModal
          result={geocodeResult}
          onClose={() => setGeocodeResult(null)}
        />
      )}
    </div>
  );
}

// Iter43-fix24aw — Modal récapitulatif après résolution GPS batch
function GeocodeResultModal({ result, onClose }) {
  const { processed, succeeded, failed, skipped, provider, results } = result;
  const ok = (results || []).filter((r) => r.status === "ok");
  const ko = (results || []).filter((r) => r.status !== "ok" && r.status !== "skipped_has_gps");
  const sk = (results || []).filter((r) => r.status === "skipped_has_gps");
  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" data-testid="geocode-result-modal">
      <div className="bg-white rounded-xl max-w-3xl w-full max-h-[85vh] overflow-hidden flex flex-col">
        <header className="px-5 py-3 border-b border-slate-200 flex items-center justify-between bg-cyan-50">
          <h3 className="text-base font-bold text-slate-800 inline-flex items-center gap-2">
            <Globe2 className="h-5 w-5 text-cyan-600" /> Résultat géocodage GPS
            <span className="text-[10px] font-normal text-slate-500">via {provider}</span>
          </h3>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-700" data-testid="geocode-result-close">
            <X className="h-5 w-5" />
          </button>
        </header>
        <div className="px-5 py-3 grid grid-cols-4 gap-2 border-b border-slate-200 text-center">
          <div className="bg-slate-50 rounded p-2">
            <p className="text-2xl font-bold text-slate-800" data-testid="geocode-total">{processed}</p>
            <p className="text-[10px] text-slate-500">Traitées</p>
          </div>
          <div className="bg-emerald-50 rounded p-2">
            <p className="text-2xl font-bold text-emerald-700" data-testid="geocode-succeeded">{succeeded}</p>
            <p className="text-[10px] text-emerald-700">Résolues</p>
          </div>
          <div className="bg-rose-50 rounded p-2">
            <p className="text-2xl font-bold text-rose-700" data-testid="geocode-failed">{failed}</p>
            <p className="text-[10px] text-rose-700">Échecs</p>
          </div>
          <div className="bg-amber-50 rounded p-2">
            <p className="text-2xl font-bold text-amber-700" data-testid="geocode-skipped">{skipped}</p>
            <p className="text-[10px] text-amber-700">Ignorées (GPS déjà présent)</p>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-3 space-y-3">
          {ok.length > 0 && (
            <details open className="text-xs">
              <summary className="cursor-pointer font-semibold text-emerald-700 mb-1">
                ✅ Résolues ({ok.length})
              </summary>
              <ul className="space-y-1 mt-1">
                {ok.map((r, i) => (
                  <li key={i} className="bg-emerald-50 rounded p-2 ring-1 ring-emerald-200">
                    <p className="font-semibold">{r.name}</p>
                    <p className="font-mono text-[10px]">
                      📍 {r.lat?.toFixed(5)}, {r.lng?.toFixed(5)} ({r.source})
                    </p>
                    {r.formatted_address && (
                      <p className="text-[10px] text-slate-600 mt-0.5">{r.formatted_address}</p>
                    )}
                  </li>
                ))}
              </ul>
            </details>
          )}
          {ko.length > 0 && (
            <details open className="text-xs">
              <summary className="cursor-pointer font-semibold text-rose-700 mb-1">
                ❌ Échecs ({ko.length})
              </summary>
              <ul className="space-y-1 mt-1">
                {ko.map((r, i) => (
                  <li key={i} className="bg-rose-50 rounded p-2 ring-1 ring-rose-200">
                    <p className="font-semibold">{r.name || r.id}</p>
                    <p className="text-[10px] text-rose-700">{r.error || r.status}</p>
                    {r.query && (
                      <p className="font-mono text-[10px] text-slate-600 mt-0.5">Query : {r.query}</p>
                    )}
                  </li>
                ))}
              </ul>
            </details>
          )}
          {sk.length > 0 && (
            <details className="text-xs">
              <summary className="cursor-pointer font-semibold text-amber-700 mb-1">
                ⏭️ Ignorées — GPS déjà présent ({sk.length})
              </summary>
              <ul className="space-y-1 mt-1">
                {sk.map((r, i) => (
                  <li key={i} className="bg-amber-50 rounded p-2 ring-1 ring-amber-200">
                    <p className="font-semibold">{r.name}</p>
                    <p className="font-mono text-[10px]">
                      📍 {Number(r.lat)?.toFixed(5)}, {Number(r.lng)?.toFixed(5)}
                    </p>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
        <footer className="px-5 py-3 border-t border-slate-200 bg-slate-50 flex justify-end">
          <button onClick={onClose} className="text-sm px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-900 text-white" data-testid="geocode-result-done">
            Fermer
          </button>
        </footer>
      </div>
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
// Iter43-fix21 — Modal d'affectation en lot (rôle + groupe de garde)
function BulkAssignModal({ selectedIds, onClose, onSaved }) {
  const [role, setRole] = React.useState("");
  const [groupeGarde, setGroupeGarde] = React.useState("");
  const [roles, setRoles] = React.useState([]);
  const [gardeGroups, setGardeGroups] = React.useState([]);
  const [nextG, setNextG] = React.useState(1);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    apiClient.get("/admin/officines-registry/roles").then((r) => setRoles(r.data?.roles || [])).catch(() => {});
    apiClient.get("/admin/officines-registry/garde-groups").then((r) => {
      setGardeGroups(r.data?.groups || []);
      setNextG(r.data?.next_suggested || 1);
    }).catch(() => {});
  }, []);

  const submit = async () => {
    if (!role && groupeGarde === "") {
      toast.error("Choisissez au moins un rôle ou un groupe de garde");
      return;
    }
    if (!window.confirm(`Affecter ${selectedIds.length} officine(s) ?`)) return;
    setSaving(true);
    try {
      const payload = { officine_ids: selectedIds };
      if (role) payload.role = role;
      if (groupeGarde !== "") payload.groupe_garde = Number(groupeGarde);
      const r = await apiClient.post("/admin/officines-registry/bulk-assign", payload);
      toast.success(`${r.data?.modified ?? 0} officine(s) mises à jour`);
      onSaved();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec de l'affectation");
    } finally { setSaving(false); }
  };

  const addNewG = () => {
    setGardeGroups((arr) => [...arr, { groupe_garde: nextG, count: 0 }].sort((a, b) => a.groupe_garde - b.groupe_garde));
    setGroupeGarde(String(nextG));
    setNextG(nextG + 1);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 py-6" data-testid="bulk-assign-modal">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md">
        <div className="px-5 py-3 border-b flex items-center justify-between">
          <h3 className="font-display font-semibold inline-flex items-center gap-2">
            <Tag className="h-4 w-4 text-violet-600" /> Affecter à {selectedIds.length} officine(s)
          </h3>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-4">
          <p className="text-xs text-slate-600">
            Choisissez le rôle <strong>et/ou</strong> le groupe de garde à appliquer.
            Laissez vide pour ne pas modifier ce champ.
          </p>

          <label className="block text-sm">
            <span className="block text-xs font-semibold text-slate-700 mb-1">Rôle (optionnel)</span>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm bg-white"
              data-testid="bulk-role"
            >
              <option value="">— Ne pas modifier —</option>
              {roles.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>

          <label className="block text-sm">
            <span className="block text-xs font-semibold text-slate-700 mb-1">Groupe de garde (optionnel)</span>
            <div className="flex items-center gap-2">
              <select
                value={groupeGarde}
                onChange={(e) => setGroupeGarde(e.target.value)}
                className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm bg-white"
                data-testid="bulk-groupe-garde"
              >
                <option value="">— Ne pas modifier —</option>
                {gardeGroups.map((g) => (
                  <option key={g.groupe_garde} value={String(g.groupe_garde)}>
                    Groupe {g.groupe_garde}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={addNewG}
                className="text-xs px-2 py-2 rounded bg-emerald-50 ring-1 ring-emerald-300 text-emerald-700 hover:bg-emerald-100"
                data-testid="bulk-add-groupe-garde"
              >
                + Nouveau
              </button>
            </div>
          </label>
        </div>
        <div className="px-5 py-3 border-t bg-slate-50 flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-2 rounded text-sm bg-slate-200 hover:bg-slate-300 text-slate-700">
            Annuler
          </button>
          <button onClick={submit} disabled={saving}
                  className="px-3 py-2 rounded text-sm bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50"
                  data-testid="bulk-assign-submit">
            {saving ? "Affectation…" : "Affecter"}
          </button>
        </div>
      </div>
    </div>
  );
}

// Iter43-fix21 — Modal CRUD des rôles d'officines
function RolesAdminModal({ onClose }) {
  const [roles, setRoles] = React.useState([]);
  const [usage, setUsage] = React.useState({});
  const [newRole, setNewRole] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/officines-registry/roles");
      setRoles(r.data?.roles || []);
      setUsage(r.data?.usage || {});
    } catch {
      toast.error("Erreur chargement");
    } finally { setLoading(false); }
  }, []);
  React.useEffect(() => { load(); }, [load]);

  const add = () => {
    const v = (newRole || "").trim();
    if (!v) return;
    if (roles.some((r) => r.toLowerCase() === v.toLowerCase())) {
      toast.error("Ce rôle existe déjà");
      return;
    }
    setRoles((arr) => [...arr, v]);
    setNewRole("");
  };

  const remove = (r) => {
    if (usage[r]) {
      toast.error(`Ce rôle est utilisé par ${usage[r]} officine(s). Ré-affectez-les d'abord.`);
      return;
    }
    setRoles((arr) => arr.filter((x) => x !== r));
  };

  const save = async () => {
    setSaving(true);
    try {
      await apiClient.put("/admin/officines-registry/roles", { roles });
      toast.success("Rôles enregistrés");
      onClose();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec");
    } finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 py-6" data-testid="roles-admin-modal">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg max-h-[80vh] overflow-y-auto">
        <div className="px-5 py-3 border-b sticky top-0 bg-white z-10 flex items-center justify-between">
          <h3 className="font-display font-semibold inline-flex items-center gap-2">
            <Tag className="h-4 w-4 text-sawali-blue" /> Gérer les rôles d'officines
          </h3>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-4">
          {loading ? <p className="text-sm text-slate-500">Chargement…</p> : (
            <>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), add())}
                  placeholder="Nouveau rôle (ex. Laboratoire)"
                  className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  data-testid="role-new-input"
                />
                <button onClick={add}
                        className="px-3 py-2 rounded text-sm bg-emerald-600 text-white hover:bg-emerald-700"
                        data-testid="role-new-add">
                  Ajouter
                </button>
              </div>
              <ul className="divide-y rounded-lg ring-1 ring-slate-200">
                {roles.map((r) => (
                  <li key={r} className="flex items-center justify-between px-3 py-2 text-sm">
                    <span>
                      <strong>{r}</strong>
                      {usage[r] ? (
                        <span className="ml-2 text-xs text-slate-500">— {usage[r]} officine{usage[r] > 1 ? "s" : ""}</span>
                      ) : null}
                    </span>
                    <button onClick={() => remove(r)}
                            disabled={!!usage[r]}
                            title={usage[r] ? "Utilisé par des officines" : "Supprimer"}
                            className="text-rose-600 hover:text-rose-700 disabled:opacity-30 disabled:cursor-not-allowed"
                            data-testid={`role-remove-${r}`}>
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </li>
                ))}
              </ul>
              <p className="text-[11px] text-slate-500">
                Vous ne pouvez pas supprimer un rôle utilisé par au moins une officine —
                ré-affectez-les d'abord avec « Affecter rôle/groupe ».
              </p>
            </>
          )}
        </div>
        <div className="px-5 py-3 border-t bg-slate-50 flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-2 rounded text-sm bg-slate-200 hover:bg-slate-300 text-slate-700">
            Annuler
          </button>
          <button onClick={save} disabled={saving}
                  className="px-3 py-2 rounded text-sm bg-sawali-blue text-white hover:bg-sawali-blue/90 disabled:opacity-50"
                  data-testid="roles-save">
            {saving ? "Enregistrement…" : "Enregistrer"}
          </button>
        </div>
      </div>
    </div>
  );
}

function EditOfficineModal({ officine, activities = [], editMode = "full", onClose, onSaved }) {
  // Iter43-fix24n (2026-06) — Édition limitée : pour un utilisateur "délégué"
  // (non-admin listé dans settings.officines_menu_allowed_emails), seuls les
  // champs suivants sont éditables. Les autres sont grisés en lecture seule.
  // Iter43-fix24v (2026-06-16) — Ajout email, contact_name (Nom du
  // responsable) et groupe_garde suite à la demande utilisateur.
  const LIMITED_FIELDS = new Set([
    "intitule", "phone", "whatsapp", "latitude", "longitude",
    "location_hint", "activite_principale",
    // fix24v additions
    "email", "contact_name", "groupe_garde",
  ]);
  const isLimited = editMode === "limited";
  const canEdit = (field) => !isLimited || LIMITED_FIELDS.has(field);
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
    activite_principale: officine.activite_principale || "",
    // Iter43-fix21 — Nouveaux champs
    role: officine.role || "",
    groupe_garde: officine.groupe_garde ?? "",
  });
  const [logoUrl, setLogoUrl] = React.useState(officine.logo_url || "");
  const [logoBusy, setLogoBusy] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  // Iter43-fix21 — Rôles + Groupes de garde dynamiques
  const [roles, setRoles] = React.useState([]);
  const [gardeGroups, setGardeGroups] = React.useState([]);
  const [nextGardeGroup, setNextGardeGroup] = React.useState(1);

  React.useEffect(() => {
    apiClient.get("/admin/officines-registry/roles").then((r) => setRoles(r.data?.roles || [])).catch(() => {});
    apiClient.get("/admin/officines-registry/garde-groups").then((r) => {
      setGardeGroups(r.data?.groups || []);
      setNextGardeGroup(r.data?.next_suggested || 1);
    }).catch(() => {});
  }, []);

  const onChange = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const addNewGardeGroup = () => {
    const n = nextGardeGroup;
    setGardeGroups((arr) => {
      if (arr.some((g) => g.groupe_garde === n)) return arr;
      return [...arr, { groupe_garde: n, count: 0 }].sort((a, b) => a.groupe_garde - b.groupe_garde);
    });
    setForm((f) => ({ ...f, groupe_garde: String(n) }));
    setNextGardeGroup(n + 1);
    toast.success(`Groupe de garde ${n} ajouté à cette officine`);
  };

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
      // Iter43-fix21 — Groupe de garde : "" → null (désaffectation), sinon entier
      payload.groupe_garde = payload.groupe_garde === "" ? null : Number(payload.groupe_garde);
      payload.role = payload.role === "" ? null : payload.role;
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
                <img src={logoSrc(logoUrl)} alt="" className="h-16 w-16 rounded-lg object-cover ring-1 ring-slate-200" data-testid="edit-officine-logo-preview" />
              ) : (
                <div className="h-16 w-16 rounded-lg bg-white ring-1 ring-slate-200 flex items-center justify-center">
                  <ImageIcon className="h-6 w-6 text-slate-300" />
                </div>
              )}
              <label className={`text-xs inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-white ring-1 ring-slate-300 ${canEdit("logo_url") ? "hover:bg-slate-50 cursor-pointer" : "opacity-50 cursor-not-allowed"}`}>
                <Upload className="h-3 w-3" />
                {logoBusy ? "Téléversement…" : "Téléverser un logo"}{!canEdit("logo_url") && <span className="text-[9px] text-amber-600 uppercase font-semibold">(lecture seule)</span>}
                <input type="file" accept="image/*" className="hidden" onChange={uploadLogo} disabled={logoBusy || !canEdit("logo_url")} data-testid="edit-officine-logo-input" />
              </label>
            </div>
            <p className="text-[10px] text-slate-500 mt-1.5">
              PNG / JPG / WEBP / SVG, 2 Mo max — stocké en base, persistant après redéploiement.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {isLimited && (
              <div className="sm:col-span-2 rounded-lg bg-amber-50 ring-1 ring-amber-200 p-2.5 text-xs text-amber-900" data-testid="officine-limited-banner">
                ℹ️ <strong>Mode édition limitée</strong> — Vous pouvez modifier seulement : intitulé, téléphone, WhatsApp,
                géolocalisation, indications de localisation et activité principale. Les autres champs sont en lecture seule.
              </div>
            )}
            <Field label="Nom (= code)" required value={form.name} onChange={onChange("name")} testid="edit-name" disabled={!canEdit("name")} />
            <Field label="Intitulé" value={form.intitule} onChange={onChange("intitule")} testid="edit-intitule" placeholder="Libellé commercial" disabled={!canEdit("intitule")} />
            <label className="block text-sm">
              <span className="block text-xs font-semibold text-slate-700 mb-1">Activité principale{!canEdit("activite_principale") && <span className="ml-1 text-[9px] text-amber-600 uppercase font-semibold">(lecture seule)</span>}</span>
              <select
                value={form.activite_principale}
                onChange={onChange("activite_principale")}
                disabled={!canEdit("activite_principale")}
                className={`w-full rounded-lg border px-3 py-2 text-sm ${!canEdit("activite_principale") ? "bg-slate-100 border-slate-200 text-slate-500 cursor-not-allowed" : "border-slate-300 bg-white"}`}
                data-testid="edit-activite_principale"
              >
                <option value="">— Non définie —</option>
                {activities.map((a) => <option key={a} value={a}>{a}</option>)}
                {/* Affiche aussi l'actuelle même si elle a été supprimée de la liste */}
                {form.activite_principale && !activities.includes(form.activite_principale) && (
                  <option value={form.activite_principale}>{form.activite_principale} (obsolète)</option>
                )}
              </select>
            </label>
            {/* Iter43-fix21 — Rôle */}
            <label className="block text-sm">
              <span className="block text-xs font-semibold text-slate-700 mb-1">Rôle{!canEdit("role") && <span className="ml-1 text-[9px] text-amber-600 uppercase font-semibold">(lecture seule)</span>}</span>
              <select
                value={form.role}
                onChange={onChange("role")}
                disabled={!canEdit("role")}
                className={`w-full rounded-lg border px-3 py-2 text-sm ${!canEdit("role") ? "bg-slate-100 border-slate-200 text-slate-500 cursor-not-allowed" : "border-slate-300 bg-white"}`}
                data-testid="edit-officine-role"
              >
                <option value="">— Non défini —</option>
                {roles.map((r) => <option key={r} value={r}>{r}</option>)}
                {form.role && !roles.includes(form.role) && (
                  <option value={form.role}>{form.role} (obsolète)</option>
                )}
              </select>
              <span className="text-[10px] text-slate-500 mt-1 block">
                Gérer la liste : Admin → Officines → Rôles
              </span>
            </label>
            {/* Iter43-fix21 — Groupe de garde */}
            <label className="block text-sm">
              <span className="block text-xs font-semibold text-slate-700 mb-1">Groupe de garde{!canEdit("groupe_garde") && <span className="ml-1 text-[9px] text-amber-600 uppercase font-semibold">(lecture seule)</span>}</span>
              <div className="flex items-center gap-2">
                <select
                  value={form.groupe_garde === null ? "" : String(form.groupe_garde)}
                  onChange={onChange("groupe_garde")}
                  disabled={!canEdit("groupe_garde")}
                  className={`flex-1 rounded-lg border px-3 py-2 text-sm ${!canEdit("groupe_garde") ? "bg-slate-100 border-slate-200 text-slate-500 cursor-not-allowed" : "border-slate-300 bg-white"}`}
                  data-testid="edit-officine-groupe-garde"
                >
                  <option value="">— Aucun —</option>
                  {gardeGroups.map((g) => (
                    <option key={g.groupe_garde} value={String(g.groupe_garde)}>
                      Groupe {g.groupe_garde}{g.count ? ` (${g.count} officine${g.count > 1 ? "s" : ""})` : ""}
                    </option>
                  ))}
                  {form.groupe_garde !== "" && form.groupe_garde !== null
                    && !gardeGroups.some((g) => String(g.groupe_garde) === String(form.groupe_garde)) && (
                    <option value={String(form.groupe_garde)}>Groupe {form.groupe_garde}</option>
                  )}
                </select>
                <button
                  type="button"
                  onClick={addNewGardeGroup}
                  disabled={!canEdit("groupe_garde")}
                  className="text-xs px-2 py-2 rounded bg-emerald-50 ring-1 ring-emerald-300 text-emerald-700 hover:bg-emerald-100 disabled:opacity-50 disabled:cursor-not-allowed"
                  title={`Créer le groupe ${nextGardeGroup}`}
                  data-testid="edit-officine-add-groupe-garde"
                >
                  + Nouveau
                </button>
              </div>
              <span className="text-[10px] text-slate-500 mt-1 block">
                Burkina Faso : généralement 5 groupes. Cliquez « + Nouveau » pour étendre.
              </span>
            </label>
            <Field label="Nom du responsable" value={form.contact_name} onChange={onChange("contact_name")} testid="edit-contact_name" disabled={!canEdit("contact_name")} />
            <Field label="Email" type="email" value={form.email} onChange={onChange("email")} testid="edit-email" disabled={!canEdit("email")} />
            <Field label="Téléphone" value={form.phone} onChange={onChange("phone")} testid="edit-phone" placeholder="+22670…" disabled={!canEdit("phone")} />
            <Field label="WhatsApp" value={form.whatsapp} onChange={onChange("whatsapp")} testid="edit-whatsapp" placeholder="+22670…" disabled={!canEdit("whatsapp")} />
            <Field label="Adresse" value={form.address} onChange={onChange("address")} testid="edit-address" disabled={!canEdit("address")} />
            <Field label="Ville" value={form.city} onChange={onChange("city")} testid="edit-city" disabled={!canEdit("city")} />
            <Field label="Pays" value={form.country} onChange={onChange("country")} testid="edit-country" disabled={!canEdit("country")} />
            <Field label="N° d'ordre" value={form.numero_ordre} onChange={onChange("numero_ordre")} testid="edit-numero_ordre" disabled={!canEdit("numero_ordre")} />
            <Field label="Indications de localisation" value={form.location_hint} onChange={onChange("location_hint")} testid="edit-location_hint" wide disabled={!canEdit("location_hint")} />
          </div>

          {/* Géolocalisation */}
          <div className="rounded-lg bg-sky-50 p-3 ring-1 ring-sky-200">
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-semibold inline-flex items-center gap-1 text-sky-900">
                <MapPin className="h-3 w-3" /> Géolocalisation
              </label>
              <button type="button" onClick={detectLocation}
                      disabled={!canEdit("latitude")}
                      className="text-[11px] px-2 py-1 rounded bg-white ring-1 ring-sky-300 hover:bg-sky-100 text-sky-700 disabled:opacity-50 disabled:cursor-not-allowed"
                      data-testid="edit-detect-location">
                Détecter ma position
              </button>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Latitude" value={form.latitude} onChange={onChange("latitude")} testid="edit-latitude" placeholder="12.345678" inline disabled={!canEdit("latitude")} />
              <Field label="Longitude" value={form.longitude} onChange={onChange("longitude")} testid="edit-longitude" placeholder="-1.234567" inline disabled={!canEdit("longitude")} />
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

function Field({ label, value, onChange, testid, type = "text", required = false, placeholder = "", wide = false, inline = false, disabled = false }) {
  return (
    <label className={`block ${wide ? "sm:col-span-2" : ""}`}>
      <span className={`block ${inline ? "text-[10px]" : "text-xs"} font-medium text-slate-700 mb-1`}>{label}{required && " *"}{disabled && <span className="ml-1 text-[9px] text-amber-600 uppercase font-semibold">(lecture seule)</span>}</span>
      <input type={type} value={value || ""} onChange={onChange} required={required}
             placeholder={placeholder} disabled={disabled} readOnly={disabled}
             className={`w-full border rounded px-3 py-2 text-sm ${disabled ? "bg-slate-100 border-slate-200 text-slate-500 cursor-not-allowed" : "border-slate-300"}`}
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
              ✅ La ligne d'en-tête est <strong>optionnelle</strong> — si elle est absente, toutes les lignes sont traitées comme des données.<br />
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
                {report.header_detected !== undefined && (
                  <span className="ml-2 text-[11px] font-normal text-slate-500">
                    {report.header_detected ? "(en-tête détectée)" : "(pas d'en-tête — toutes lignes traitées comme données)"}
                  </span>
                )}
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


// ============================================================================
// Iter43-fix12 — Modale : Liste des produits d'une officine
// Pagination serveur (jusqu'à 10 000 produits par officine).
// ============================================================================
function ProductsModal({ officine, onClose, onImport }) {
  const [rows, setRows] = React.useState([]);
  const [total, setTotal] = React.useState(0);
  const [offset, setOffset] = React.useState(0);
  const [limit] = React.useState(100);
  const [q, setQ] = React.useState("");
  const [sort, setSort] = React.useState("product_name");
  const [order, setOrder] = React.useState("asc");
  const [loading, setLoading] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const params = { offset, limit, sort, order };
      if (q) params.q = q;
      const r = await apiClient.get(`/admin/officines-registry/${officine.id}/products`, { params });
      setRows(r.data?.items || []);
      setTotal(r.data?.total || 0);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur chargement produits");
    } finally { setLoading(false); }
  }, [officine.id, offset, limit, q, sort, order]);

  React.useEffect(() => { load(); }, [load]);

  const downloadCsv = async () => {
    try {
      const r = await apiClient.get(
        `/admin/officines-registry/${officine.id}/products/export.csv`,
        { responseType: "blob" },
      );
      const url = window.URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `produits_${(officine.name || officine.id).replace(/\s+/g, "_")}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur export");
    }
  };

  const onClearAll = async () => {
    if (!window.confirm(`Supprimer tous les ${total} produits de « ${officine.name} » ?\nCette action est irréversible.`)) return;
    try {
      await apiClient.delete(`/admin/officines-registry/${officine.id}/products`);
      toast.success("Produits supprimés");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
  };

  const onSort = (col) => {
    if (sort === col) setOrder(order === "asc" ? "desc" : "asc");
    else { setSort(col); setOrder("asc"); }
    setOffset(0);
  };

  const totalPages = Math.max(1, Math.ceil(total / limit));
  const page = Math.floor(offset / limit) + 1;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 py-4" data-testid="products-modal">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-5xl max-h-[92vh] flex flex-col">
        <div className="px-5 py-3 border-b flex items-center justify-between sticky top-0 bg-white z-10">
          <div className="min-w-0">
            <h3 className="font-display font-semibold text-slate-900 inline-flex items-center gap-2">
              <Package className="h-4 w-4 text-sawali-blue" /> Produits de l'officine
            </h3>
            <p className="text-[11px] text-slate-500 mt-0.5 truncate">
              <span className="font-medium">{officine.name}</span> · <span className="tabular-nums">{total}</span> produit(s)
            </p>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <button onClick={onImport}
                    className="text-xs inline-flex items-center gap-1 px-3 py-1.5 rounded bg-violet-600 text-white hover:bg-violet-700"
                    data-testid="products-modal-import">
              <Upload className="h-3 w-3" /> Importer
            </button>
            {total > 0 && (
              <button onClick={downloadCsv}
                      className="text-xs inline-flex items-center gap-1 px-3 py-1.5 rounded bg-emerald-600 text-white hover:bg-emerald-700"
                      data-testid="products-modal-export">
                <Download className="h-3 w-3" /> CSV
              </button>
            )}
            {total > 0 && (
              <button onClick={onClearAll}
                      className="text-xs inline-flex items-center gap-1 px-3 py-1.5 rounded bg-rose-50 text-rose-700 hover:bg-rose-100 ring-1 ring-rose-200"
                      data-testid="products-modal-clear" title="Tout supprimer">
                <Trash2 className="h-3 w-3" />
              </button>
            )}
            <button onClick={onClose} className="text-slate-500 hover:text-slate-900 px-2" data-testid="products-modal-close">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
        <div className="px-5 py-2 border-b bg-slate-50 flex items-center gap-2">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-slate-400" />
            <input
              value={q}
              onChange={(e) => { setQ(e.target.value); setOffset(0); }}
              placeholder="Rechercher par produit, CIP ou conditionnement…"
              className="w-full pl-8 pr-3 py-1.5 border rounded text-sm"
              data-testid="products-modal-search"
            />
          </div>
          <span className="text-[11px] text-slate-500 ml-auto">
            Page {page}/{totalPages} · {offset + 1}–{Math.min(offset + limit, total)} / {total}
          </span>
          <button
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - limit))}
            className="text-xs px-2 py-1 rounded bg-white ring-1 ring-slate-200 hover:bg-slate-50 disabled:opacity-40"
            data-testid="products-modal-prev"
          >‹ Préc.</button>
          <button
            disabled={offset + limit >= total}
            onClick={() => setOffset(offset + limit)}
            className="text-xs px-2 py-1 rounded bg-white ring-1 ring-slate-200 hover:bg-slate-50 disabled:opacity-40"
            data-testid="products-modal-next"
          >Suiv. ›</button>
        </div>
        <div className="overflow-y-auto flex-1">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-left sticky top-0">
              <tr>
                <SortHeader col="product_name" current={sort} order={order} onClick={onSort}>Produit</SortHeader>
                <SortHeader col="conditionnement" current={sort} order={order} onClick={onSort}>Conditionnement</SortHeader>
                <SortHeader col="cip" current={sort} order={order} onClick={onSort}>CIP</SortHeader>
                <SortHeader col="stock" current={sort} order={order} onClick={onSort} align="right">Stock</SortHeader>
              </tr>
            </thead>
            <tbody data-testid="products-modal-tbody">
              {loading && <tr><td colSpan={4} className="px-3 py-6 text-center text-slate-400">Chargement…</td></tr>}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={4} className="px-3 py-6 text-center text-slate-400 italic">
                  {q ? "Aucun produit pour cette recherche." : "Aucun produit. Cliquez sur « Importer » pour ajouter des produits."}
                </td></tr>
              )}
              {rows.map((p) => (
                <tr key={p.id} className="border-t border-slate-100 hover:bg-slate-50" data-testid={`product-row-${p.id}`}>
                  <td className="px-3 py-2 text-slate-900">{p.product_name}</td>
                  <td className="px-3 py-2 text-slate-600 text-xs">{p.conditionnement || <span className="italic text-slate-400">—</span>}</td>
                  <td className="px-3 py-2 text-slate-600 text-xs font-mono">{p.cip || <span className="italic text-slate-400">—</span>}</td>
                  <td className="px-3 py-2 text-right tabular-nums font-semibold text-slate-700">{p.stock ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function SortHeader({ col, current, order, onClick, children, align = "left" }) {
  const active = col === current;
  return (
    <th
      className={`px-3 py-2 font-medium cursor-pointer select-none ${active ? "text-sawali-blue" : "hover:text-slate-900"} text-${align}`}
      onClick={() => onClick(col)}
    >
      {children} {active && (order === "asc" ? "▲" : "▼")}
    </th>
  );
}

// ============================================================================
// Iter43-fix12 — Modale : Import des produits CSV/JSON
// ============================================================================
function ImportProductsModal({ officine, onClose, onDone }) {
  const [file, setFile] = React.useState(null);
  const [mode, setMode] = React.useState("replace"); // replace | append
  const [busy, setBusy] = React.useState(false);
  const [report, setReport] = React.useState(null);

  const submit = async (e) => {
    e.preventDefault();
    if (!file) { toast.error("Sélectionnez un fichier"); return; }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("mode", mode);
      const r = await apiClient.post(
        `/admin/officines-registry/${officine.id}/products/import`,
        fd,
        { headers: { "Content-Type": "multipart/form-data" } },
      );
      setReport(r.data);
      toast.success(`${r.data?.created || 0} créés · ${r.data?.updated || 0} mis à jour · ${r.data?.skipped || 0} ignorés`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec import");
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 py-4" data-testid="import-products-modal">
      <form onSubmit={submit} className="bg-white rounded-xl shadow-2xl w-full max-w-lg max-h-[92vh] overflow-y-auto">
        <div className="px-5 py-3 border-b flex items-center justify-between">
          <div>
            <h3 className="font-display font-semibold text-slate-900 inline-flex items-center gap-2">
              <Package className="h-4 w-4 text-violet-600" /> Importer les produits
            </h3>
            <p className="text-[11px] text-slate-500 mt-0.5">Officine : <span className="font-medium">{officine.name}</span></p>
          </div>
          <button type="button" onClick={onClose} className="text-slate-500 hover:text-slate-900" data-testid="import-products-close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-5 space-y-4">
          <div className="rounded-lg bg-sky-50 ring-1 ring-sky-200 p-3 text-xs text-sky-900">
            <p className="font-semibold mb-1 inline-flex items-center gap-1">
              <FileSpreadsheet className="h-3.5 w-3.5" /> Format attendu
            </p>
            <p>
              <strong>CSV</strong> (séparateur <code>,</code> ou <code>;</code> auto-détecté) :
            </p>
            <code className="block bg-white rounded px-2 py-1 mt-1 text-[10px] font-mono break-all">
              Code Officine,Produit,Conditionnement,CIP,Stock
            </code>
            <p className="mt-1.5 inline-flex items-center gap-1">
              <FileJson className="h-3.5 w-3.5" /> <strong>JSON</strong> : liste plate OU structure imbriquée (aplatie automatiquement).
            </p>
            <p className="mt-1 text-[10px] text-sky-700">
              ℹ️ Clé d'unicité : <code>(officine, produit, conditionnement)</code>. Le CIP est optionnel.
            </p>
          </div>

          <label className="block">
            <span className="block text-xs font-semibold text-slate-700 mb-1">Fichier CSV ou JSON</span>
            <input
              type="file"
              accept=".csv,.json,.txt,text/csv,application/json"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="block w-full text-sm file:mr-3 file:py-1.5 file:px-3 file:rounded file:border-0 file:bg-violet-50 file:text-violet-700 hover:file:bg-violet-100"
              data-testid="import-products-file"
            />
            {file && <p className="text-[11px] text-slate-500 mt-1">📄 {file.name} ({Math.round(file.size / 1024)} Ko)</p>}
          </label>

          <div>
            <span className="block text-xs font-semibold text-slate-700 mb-1">Mode d'import</span>
            <div className="grid grid-cols-2 gap-2">
              <button type="button"
                      onClick={() => setMode("replace")}
                      className={`text-xs px-3 py-2 rounded ring-1 text-left ${mode === "replace" ? "bg-violet-600 text-white ring-violet-700" : "bg-white ring-slate-200 hover:bg-slate-50"}`}
                      data-testid="import-products-mode-replace">
                <div className="font-semibold inline-flex items-center gap-1">
                  <Trash2 className="h-3 w-3" /> Remplacer
                </div>
                <div className={`text-[10px] mt-0.5 ${mode === "replace" ? "text-white/80" : "text-slate-500"}`}>
                  Vide la liste puis ré-importe (recommandé)
                </div>
              </button>
              <button type="button"
                      onClick={() => setMode("append")}
                      className={`text-xs px-3 py-2 rounded ring-1 text-left ${mode === "append" ? "bg-violet-600 text-white ring-violet-700" : "bg-white ring-slate-200 hover:bg-slate-50"}`}
                      data-testid="import-products-mode-append">
                <div className="font-semibold inline-flex items-center gap-1">
                  <Plus className="h-3 w-3" /> Ajouter
                </div>
                <div className={`text-[10px] mt-0.5 ${mode === "append" ? "text-white/80" : "text-slate-500"}`}>
                  Ajoute / met à jour les doublons (upsert)
                </div>
              </button>
            </div>
          </div>

          {report && (
            <div className="rounded-lg bg-emerald-50 ring-1 ring-emerald-200 p-3 text-xs space-y-1" data-testid="import-products-report">
              <p className="font-semibold text-emerald-900">✅ Import terminé</p>
              <p><strong>{report.created}</strong> créés · <strong>{report.updated}</strong> mis à jour · <strong>{report.skipped}</strong> ignorés</p>
              <p className="text-[10px] text-emerald-700">Format : {report.format} · Mode : {report.mode}</p>
              {report.errors?.length > 0 && (
                <details className="mt-1">
                  <summary className="cursor-pointer text-rose-700">⚠️ {report.errors.length} avertissements</summary>
                  <ul className="mt-1 space-y-0.5 max-h-32 overflow-y-auto">
                    {report.errors.slice(0, 20).map((e, i) => (
                      <li key={i} className="text-rose-700 text-[10px]">
                        Ligne {e.row} : {e.reason}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}
        </div>
        <div className="px-5 py-3 border-t bg-slate-50 flex justify-end gap-2">
          <button type="button" onClick={onClose}
                  className="px-3 py-2 rounded text-sm bg-slate-200 hover:bg-slate-300 text-slate-700">
            Fermer
          </button>
          {report ? (
            <button type="button" onClick={onDone}
                    className="px-3 py-2 rounded text-sm bg-violet-600 text-white hover:bg-violet-700"
                    data-testid="import-products-done">
              Voir les produits
            </button>
          ) : (
            <button type="submit" disabled={busy || !file}
                    className="px-3 py-2 rounded text-sm bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50"
                    data-testid="import-products-submit">
              {busy ? "Import en cours…" : "Lancer l'import"}
            </button>
          )}
        </div>
      </form>
    </div>
  );
}

// ============================================================================
// Iter43-fix12 — Modale : Gestion des activités principales
// ============================================================================
function ManageActivitiesModal({ activities, onClose, onSaved }) {
  const [list, setList] = React.useState(() => [...activities]);
  const [input, setInput] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const add = () => {
    const v = input.trim();
    if (!v) return;
    if (list.some((a) => a.toLowerCase() === v.toLowerCase())) {
      toast.error("Activité déjà présente");
      return;
    }
    setList([...list, v]);
    setInput("");
  };

  const remove = (a) => setList(list.filter((x) => x !== a));

  const save = async () => {
    if (list.length === 0) { toast.error("Au moins une activité requise"); return; }
    setBusy(true);
    try {
      const r = await apiClient.put("/admin/officine-activities", { activities: list });
      toast.success("Activités mises à jour");
      onSaved(r.data?.activities || list);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec");
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 py-4" data-testid="manage-activities-modal">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md max-h-[90vh] overflow-y-auto">
        <div className="px-5 py-3 border-b flex items-center justify-between">
          <h3 className="font-display font-semibold text-slate-900 inline-flex items-center gap-2">
            <Tags className="h-4 w-4 text-indigo-600" /> Activités principales
          </h3>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900" data-testid="manage-activities-close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-5 space-y-3">
          <p className="text-xs text-slate-500">
            Cette liste alimente le champ « Activité principale » de chaque fiche officine et le filtre du tableau.
          </p>
          <div className="space-y-2">
            {list.map((a) => (
              <div key={a} className="flex items-center gap-2 p-2 rounded ring-1 ring-slate-200 bg-slate-50" data-testid={`activity-item-${a}`}>
                <Tags className="h-3.5 w-3.5 text-indigo-500" />
                <span className="text-sm flex-1">{a}</span>
                <button onClick={() => remove(a)} className="text-rose-600 hover:bg-rose-50 p-1 rounded" data-testid={`remove-activity-${a}`}>
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
            {list.length === 0 && <p className="text-xs text-slate-400 italic text-center py-3">Aucune activité.</p>}
          </div>
          <div className="flex gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
              placeholder="Nouvelle activité (ex: Hôpital)"
              className="flex-1 px-3 py-2 border rounded-lg text-sm"
              data-testid="new-activity-input"
            />
            <button onClick={add} className="inline-flex items-center gap-1 px-3 py-2 rounded bg-indigo-600 text-white text-sm hover:bg-indigo-700"
                    data-testid="add-activity-btn">
              <Plus className="h-3 w-3" /> Ajouter
            </button>
          </div>
        </div>
        <div className="px-5 py-3 border-t bg-slate-50 flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-2 rounded text-sm bg-slate-200 hover:bg-slate-300 text-slate-700">
            Annuler
          </button>
          <button onClick={save} disabled={busy}
                  className="px-3 py-2 rounded text-sm bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
                  data-testid="manage-activities-save">
            {busy ? "Enregistrement…" : "Enregistrer"}
          </button>
        </div>
      </div>
    </div>
  );
}


// Iter43-fix23 — Modal de création d'une nouvelle officine (depuis Registre)
function CreateOfficineModal({ roles = [], activities = [], onClose, onCreated }) {
  const [name, setName] = React.useState("");
  const [intitule, setIntitule] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [phone, setPhone] = React.useState("");
  const [whatsapp, setWhatsapp] = React.useState("");
  const [city, setCity] = React.useState("");
  const [country, setCountry] = React.useState("BF");
  const [address, setAddress] = React.useState("");
  const [locationHint, setLocationHint] = React.useState("");
  const [numeroOrdre, setNumeroOrdre] = React.useState("");
  const [contactName, setContactName] = React.useState("");
  const [role, setRole] = React.useState("");
  const [groupeGarde, setGroupeGarde] = React.useState("");
  const [activite, setActivite] = React.useState("");
  const [status, setStatus] = React.useState("pending");
  const [busy, setBusy] = React.useState(false);

  const submit = async () => {
    if (!name.trim()) { toast.error("Le nom de l'officine est requis"); return; }
    setBusy(true);
    try {
      const payload = {
        name: name.trim(),
        intitule: intitule.trim() || null,
        email: email.trim() || null,
        phone: phone.trim() || null,
        whatsapp: whatsapp.trim() || null,
        city: city.trim() || null,
        country: country.trim() || null,
        address: address.trim() || null,
        location_hint: locationHint.trim() || null,
        numero_ordre: numeroOrdre.trim() || null,
        contact_name: contactName.trim() || null,
        role: role || null,
        groupe_garde: groupeGarde ? parseInt(groupeGarde, 10) : null,
        activite_principale: activite || null,
        status,
      };
      const r = await apiClient.post("/admin/officines-registry", payload);
      toast.success(`Officine « ${r.data?.officine?.name} » créée`);
      onCreated();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec création");
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 py-6" data-testid="create-officine-modal">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-full overflow-auto">
        <div className="px-5 py-3 border-b bg-slate-50 flex items-center justify-between sticky top-0 z-10">
          <h2 className="text-sm font-semibold flex items-center gap-2">
            <Building2 className="h-4 w-4 text-emerald-600" /> Nouvelle officine
          </h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-700" data-testid="create-officine-close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-5 grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
          <label className="block">
            <span className="text-xs text-slate-600">Nom (= code) *</span>
            <input value={name} onChange={(e) => setName(e.target.value)}
                   className="mt-1 w-full px-3 py-2 border rounded-lg" data-testid="create-officine-name"
                   placeholder="Ex. Pharmacie du Centre" />
          </label>
          <label className="block">
            <span className="text-xs text-slate-600">Intitulé long</span>
            <input value={intitule} onChange={(e) => setIntitule(e.target.value)}
                   className="mt-1 w-full px-3 py-2 border rounded-lg" data-testid="create-officine-intitule" />
          </label>
          <label className="block">
            <span className="text-xs text-slate-600">Email</span>
            <input value={email} onChange={(e) => setEmail(e.target.value)}
                   className="mt-1 w-full px-3 py-2 border rounded-lg" type="email"
                   data-testid="create-officine-email" />
          </label>
          <label className="block">
            <span className="text-xs text-slate-600">Téléphone</span>
            <input value={phone} onChange={(e) => setPhone(e.target.value)}
                   className="mt-1 w-full px-3 py-2 border rounded-lg" placeholder="+22670000000"
                   data-testid="create-officine-phone" />
          </label>
          <label className="block">
            <span className="text-xs text-slate-600">WhatsApp</span>
            <input value={whatsapp} onChange={(e) => setWhatsapp(e.target.value)}
                   className="mt-1 w-full px-3 py-2 border rounded-lg" placeholder="+22670000000"
                   data-testid="create-officine-whatsapp" />
          </label>
          <label className="block">
            <span className="text-xs text-slate-600">Ville</span>
            <input value={city} onChange={(e) => setCity(e.target.value)}
                   className="mt-1 w-full px-3 py-2 border rounded-lg" data-testid="create-officine-city" />
          </label>
          <label className="block">
            <span className="text-xs text-slate-600">Pays</span>
            <input value={country} onChange={(e) => setCountry(e.target.value)}
                   className="mt-1 w-full px-3 py-2 border rounded-lg" data-testid="create-officine-country" />
          </label>
          <label className="block sm:col-span-2">
            <span className="text-xs text-slate-600">Adresse</span>
            <input value={address} onChange={(e) => setAddress(e.target.value)}
                   className="mt-1 w-full px-3 py-2 border rounded-lg" data-testid="create-officine-address" />
          </label>
          <label className="block sm:col-span-2">
            <span className="text-xs text-slate-600">Indications de localisation</span>
            <input value={locationHint} onChange={(e) => setLocationHint(e.target.value)}
                   className="mt-1 w-full px-3 py-2 border rounded-lg"
                   placeholder="Ex. À côté du marché central"
                   data-testid="create-officine-location-hint" />
          </label>
          <label className="block">
            <span className="text-xs text-slate-600">Numéro d'ordre</span>
            <input value={numeroOrdre} onChange={(e) => setNumeroOrdre(e.target.value)}
                   className="mt-1 w-full px-3 py-2 border rounded-lg" data-testid="create-officine-numero-ordre" />
          </label>
          <label className="block">
            <span className="text-xs text-slate-600">Responsable</span>
            <input value={contactName} onChange={(e) => setContactName(e.target.value)}
                   className="mt-1 w-full px-3 py-2 border rounded-lg" data-testid="create-officine-contact-name" />
          </label>
          <label className="block">
            <span className="text-xs text-slate-600">Rôle</span>
            <select value={role} onChange={(e) => setRole(e.target.value)}
                    className="mt-1 w-full px-3 py-2 border rounded-lg bg-white" data-testid="create-officine-role">
              <option value="">— Aucun —</option>
              {roles.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="text-xs text-slate-600">Groupe de garde</span>
            <input value={groupeGarde} onChange={(e) => setGroupeGarde(e.target.value)}
                   type="number" min="1" max="100"
                   className="mt-1 w-full px-3 py-2 border rounded-lg" data-testid="create-officine-groupe-garde" />
          </label>
          <label className="block">
            <span className="text-xs text-slate-600">Activité (legacy)</span>
            <select value={activite} onChange={(e) => setActivite(e.target.value)}
                    className="mt-1 w-full px-3 py-2 border rounded-lg bg-white" data-testid="create-officine-activite">
              <option value="">— Aucune —</option>
              {activities.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="text-xs text-slate-600">Statut</span>
            <select value={status} onChange={(e) => setStatus(e.target.value)}
                    className="mt-1 w-full px-3 py-2 border rounded-lg bg-white" data-testid="create-officine-status">
              <option value="pending">En attente</option>
              <option value="active">Active</option>
              <option value="suspended">Suspendue</option>
            </select>
          </label>
        </div>
        <div className="px-5 py-3 border-t bg-slate-50 flex justify-end gap-2 sticky bottom-0">
          <button onClick={onClose} className="px-3 py-2 rounded text-sm bg-slate-200 hover:bg-slate-300 text-slate-700"
                  data-testid="create-officine-cancel">
            Annuler
          </button>
          <button onClick={submit} disabled={busy || !name.trim()}
                  className="px-3 py-2 rounded text-sm bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 inline-flex items-center gap-1"
                  data-testid="create-officine-submit">
            <Plus className="h-3 w-3" /> {busy ? "Création…" : "Créer l'officine"}
          </button>
        </div>
      </div>
    </div>
  );
}
