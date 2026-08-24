import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { Search, Users } from "lucide-react";

/**
 * P5 (2026-02) — Multi-select des clients autorisés à voir la ressource
 * (Formations / Formulaires / Documents). Liste vide → visible par tous les
 * clients suivis y ayant déjà accès (comportement historique).
 *
 * Props:
 *  - value: string[]  (ids sélectionnés)
 *  - onChange: (ids: string[]) => void
 *  - label?: string
 *  - testIdPrefix?: string  (défaut "access-clients")
 */
export default function ClientAccessSelector({ value, onChange, label = "Clients autorisés", testIdPrefix = "access-clients" }) {
  const [clients, setClients] = useState([]);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const selected = useMemo(() => new Set(value || []), [value]);

  useEffect(() => {
    // 2026-02 fork (bug fix) — Utilise `/me/access-clients-list` (permissif
    // aux admins ET tracked-Administrateur) au lieu de `/admin/clients` qui
    // renvoie 403 pour un tracked-elevated en prod (support@) → liste vide.
    apiClient.get("/me/access-clients-list")
      .then((r) => setClients(Array.isArray(r.data) ? r.data : []))
      .catch(() => setClients([]))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    const query = q.trim().toLowerCase();
    const sortable = [...clients].sort((a, b) => (a.full_name || a.email || "").localeCompare(b.full_name || b.email || ""));
    if (!query) return sortable;
    return sortable.filter((c) => {
      const hay = `${c.full_name || ""} ${c.company || ""} ${c.email || ""}`.toLowerCase();
      return hay.includes(query);
    });
  }, [clients, q]);

  const toggle = (id) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange(Array.from(next));
  };

  const clearAll = () => onChange([]);
  const selectAll = () => onChange(filtered.map((c) => c.id));

  return (
    <div data-testid={`${testIdPrefix}-selector`}>
      <div className="flex items-center justify-between mb-1">
        <label className="block text-xs font-semibold text-slate-700 flex items-center gap-1">
          <Users className="h-3 w-3" /> {label}
        </label>
        <div className="text-[11px] text-slate-500">
          {selected.size === 0 ? (
            <span className="italic">Visible par tous les clients suivis</span>
          ) : (
            <span>{selected.size} client{selected.size > 1 ? "s" : ""} sélectionné{selected.size > 1 ? "s" : ""}</span>
          )}
        </div>
      </div>
      <div className="rounded-lg border border-slate-300 bg-white overflow-hidden">
        <div className="flex items-center gap-2 border-b border-slate-200 px-2.5 py-1.5">
          <Search className="h-3.5 w-3.5 text-slate-400" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Rechercher un client (nom, société, email)…"
            className="flex-1 text-xs bg-transparent focus:outline-none"
            data-testid={`${testIdPrefix}-search`}
          />
          {filtered.length > 0 && (
            <>
              <button
                type="button"
                onClick={selectAll}
                className="text-[11px] text-sawali-blue hover:underline"
                data-testid={`${testIdPrefix}-select-all`}
              >
                Tout cocher
              </button>
              <span className="text-slate-300">|</span>
            </>
          )}
          {selected.size > 0 && (
            <button
              type="button"
              onClick={clearAll}
              className="text-[11px] text-rose-600 hover:underline"
              data-testid={`${testIdPrefix}-clear`}
            >
              Vider
            </button>
          )}
        </div>
        <div className="max-h-48 overflow-y-auto divide-y divide-slate-100">
          {loading && <div className="px-3 py-2 text-xs text-slate-500">Chargement…</div>}
          {!loading && filtered.length === 0 && (
            <div className="px-3 py-2 text-xs text-slate-500 italic">Aucun client ne correspond.</div>
          )}
          {!loading && filtered.map((c) => (
            <label
              key={c.id}
              className={`flex items-center gap-2 px-3 py-1.5 text-xs cursor-pointer hover:bg-slate-50 ${selected.has(c.id) ? "bg-sawali-blue/5" : ""}`}
              data-testid={`${testIdPrefix}-row-${c.id}`}
            >
              <input
                type="checkbox"
                checked={selected.has(c.id)}
                onChange={() => toggle(c.id)}
                className="h-3.5 w-3.5"
                data-testid={`${testIdPrefix}-cb-${c.id}`}
              />
              <span className="truncate flex-1">
                {c.full_name || c.email}
                {c.company && <span className="text-slate-400"> · {c.company}</span>}
              </span>
              {c.role && <span className="text-[10px] uppercase tracking-widest text-slate-400">{c.role}</span>}
            </label>
          ))}
        </div>
      </div>
      <p className="text-[11px] text-slate-500 mt-1">
        Laissez la liste vide pour rendre la ressource visible par tous les utilisateurs suivis y ayant déjà accès.
      </p>
    </div>
  );
}
