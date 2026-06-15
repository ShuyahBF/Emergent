// Iter43-fix22 (2026-06) — Tableau de suivi des interrogations WhatsApp à Liluvine.
// Accessible aux Admin / Superviseur / Modérateurs.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Inbox, Search, FileDown, UserPlus, RefreshCcw, Phone, Clock } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch { return iso; }
}

function fmtSeconds(s) {
  if (s == null) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

export default function AdminLiluvineWaRequests() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(() => new Set());
  const [importing, setImporting] = useState(false);
  const [exporting, setExporting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ group_by_phone: "true", limit: "1000" });
      if (search.trim()) params.set("search", search.trim());
      const r = await apiClient.get(`/admin/liluvine-pro/wa-requests?${params.toString()}`);
      setItems(r.data?.items || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur chargement");
    } finally { setLoading(false); }
  }, [search]);
  useEffect(() => { load(); }, [load]);

  const toggleAll = () => {
    if (selected.size === items.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(items.map((it) => it.phone)));
    }
  };
  const toggle = (phone) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(phone)) next.delete(phone); else next.add(phone);
      return next;
    });
  };

  const importContacts = async () => {
    if (selected.size === 0) return;
    if (!window.confirm(`Importer ${selected.size} contact(s) dans le groupe « Interrogations WA » ?`)) return;
    setImporting(true);
    try {
      const r = await apiClient.post("/admin/liluvine-pro/wa-requests/import-to-contacts", {
        phones: Array.from(selected), group_name: "Interrogations WA",
      });
      toast.success(`${r.data.created} créés, ${r.data.updated} mis à jour, ${r.data.skipped} ignorés`);
      setSelected(new Set());
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec import");
    } finally { setImporting(false); }
  };

  const exportPdf = async () => {
    if (selected.size === 0) return;
    setExporting(true);
    try {
      const phones = Array.from(selected).join(",");
      const url = `${apiClient.defaults.baseURL}/admin/liluvine-pro/wa-requests/export.pdf?phones=${encodeURIComponent(phones)}`;
      const tokenHeader = apiClient.defaults.headers.common?.Authorization;
      const resp = await fetch(url, { headers: tokenHeader ? { Authorization: tokenHeader } : {} });
      if (!resp.ok) throw new Error("export failed");
      const blob = await resp.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `liluvine-wa-requests-${new Date().toISOString().slice(0,10)}.pdf`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch {
      toast.error("Échec export PDF");
    } finally { setExporting(false); }
  };

  const total = items.length;
  const stats = useMemo(() => {
    const totReq = items.reduce((sum, it) => sum + (it.request_count || 0), 0);
    const withRt = items.filter((it) => it.avg_response_time_seconds != null);
    const avgRt = withRt.length ? withRt.reduce((s, it) => s + it.avg_response_time_seconds, 0) / withRt.length : null;
    return { totReq, avgRt };
  }, [items]);

  return (
    <div className="p-6 max-w-7xl mx-auto" data-testid="liluvine-wa-requests-page">
      <header className="flex items-center gap-3 mb-4">
        <Inbox className="h-6 w-6 text-sawali-blue" />
        <div>
          <h1 className="text-2xl font-display font-bold">Exclamations Reçues</h1>
          <p className="text-xs text-slate-500">
            Ne contient que les commandes <code className="px-1 bg-slate-100 rounded">!Garde</code>,{" "}
            <code className="px-1 bg-slate-100 rounded">!Meteo</code>, <code className="px-1 bg-slate-100 rounded">!Aizenta</code>, etc.
            envoyées via WhatsApp ou SMS. Les conversations Liluvine PRO classiques ne sont pas listées ici.
          </p>
        </div>
      </header>

      <div className="grid sm:grid-cols-3 gap-3 mb-5">
        <StatCard label="Numéros distincts" value={total} />
        <StatCard label="Requêtes totales" value={stats.totReq} />
        <StatCard label="Temps réponse moyen" value={fmtSeconds(stats.avgRt)} />
      </div>

      <div className="rounded-xl ring-1 ring-slate-200 bg-white p-3 mb-4 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[240px]">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input value={search} onChange={(e) => setSearch(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && load()}
                 placeholder="Rechercher numéro, nom, profil…"
                 className="w-full pl-8 pr-3 py-2 rounded-lg border border-slate-300 text-sm"
                 data-testid="wa-search-input" />
        </div>
        <button onClick={load} className="text-xs px-3 py-2 rounded bg-white ring-1 ring-slate-300 hover:bg-slate-50">
          <RefreshCcw className="h-3 w-3 inline mr-1" /> Rafraîchir
        </button>
        {selected.size > 0 && (
          <>
            <button onClick={importContacts} disabled={importing}
                    className="text-xs px-3 py-2 rounded bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 inline-flex items-center gap-1"
                    data-testid="wa-import-btn">
              <UserPlus className="h-3 w-3" /> {importing ? "Import…" : `Importer ${selected.size} → Contacts`}
            </button>
            <button onClick={exportPdf} disabled={exporting}
                    className="text-xs px-3 py-2 rounded bg-rose-600 text-white hover:bg-rose-700 disabled:opacity-50 inline-flex items-center gap-1"
                    data-testid="wa-export-pdf-btn">
              <FileDown className="h-3 w-3" /> {exporting ? "Export…" : `Imprimer PDF (${selected.size})`}
            </button>
          </>
        )}
      </div>

      <div className="rounded-xl ring-1 ring-slate-200 bg-white overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-600">
            <tr>
              <th className="px-3 py-2 text-left">
                <input type="checkbox"
                       checked={total > 0 && selected.size === total}
                       onChange={toggleAll}
                       data-testid="wa-select-all" />
              </th>
              <th className="text-left px-3 py-2">Numéro WA</th>
              <th className="text-left px-3 py-2">Identité affichée</th>
              <th className="text-right px-3 py-2">Requêtes</th>
              <th className="text-left px-3 py-2">Première</th>
              <th className="text-left px-3 py-2">Dernière</th>
              <th className="text-left px-3 py-2">Temps réponse moyen</th>
              <th className="text-left px-3 py-2">Dernier message</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={8} className="p-6 text-center text-slate-400">Chargement…</td></tr>
            )}
            {!loading && items.length === 0 && (
              <tr><td colSpan={8} className="p-6 text-center text-slate-400">Aucune interrogation reçue</td></tr>
            )}
            {!loading && items.map((it) => {
              const sel = selected.has(it.phone);
              return (
                <tr key={it.phone} className={`border-t ${sel ? "bg-sawali-blue/5" : ""}`}
                    data-testid={`wa-row-${it.phone}`}>
                  <td className="px-3 py-2">
                    <input type="checkbox" checked={sel} onChange={() => toggle(it.phone)}
                           data-testid={`wa-select-${it.phone}`} />
                  </td>
                  <td className="px-3 py-2 font-mono">
                    <Phone className="h-3 w-3 inline mr-1 text-slate-400" />+{it.phone}
                  </td>
                  <td className="px-3 py-2">
                    <span className="font-semibold">{it.profile_name || it.contact_name || "—"}</span>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <span className="inline-block min-w-[2rem] text-center font-bold text-sawali-blue">
                      {it.request_count}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-slate-600 text-xs">{fmtDate(it.first_seen)}</td>
                  <td className="px-3 py-2 text-slate-600 text-xs">{fmtDate(it.last_seen)}</td>
                  <td className="px-3 py-2 text-slate-600 text-xs">
                    <Clock className="h-3 w-3 inline mr-1 text-slate-400" />
                    {fmtSeconds(it.avg_response_time_seconds)}
                    {it.responded_count > 0 && (
                      <span className="ml-1 text-[10px] text-slate-400">({it.responded_count} rép.)</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-slate-600 text-xs italic max-w-[280px] truncate" title={it.last_message}>
                    {it.last_message || "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StatCard({ label, value }) {
  return (
    <div className="rounded-xl ring-1 ring-slate-200 bg-white px-4 py-3">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="text-2xl font-display font-bold text-sawali-blue tabular-nums">{value}</p>
    </div>
  );
}
