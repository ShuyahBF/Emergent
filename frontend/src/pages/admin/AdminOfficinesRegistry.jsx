// Iter42 — Admin: Officines Registry (validation, suspension, link client)
import React from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { CheckCircle, XCircle, RefreshCw, Link as LinkIcon, Unlink, Search, Building2 } from "lucide-react";

const STATUS_LABEL = {
  pending: { text: "En attente", color: "bg-amber-50 text-amber-700 ring-amber-200" },
  active: { text: "Active", color: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  suspended: { text: "Suspendue", color: "bg-rose-50 text-rose-700 ring-rose-200" },
};

export default function AdminOfficinesRegistry() {
  const [items, setItems] = React.useState([]);
  const [counts, setCounts] = React.useState({ pending: 0, active: 0, suspended: 0 });
  const [filter, setFilter] = React.useState("pending");
  const [q, setQ] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [linkingFor, setLinkingFor] = React.useState(null);

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

  return (
    <div className="space-y-5" data-testid="admin-officines-registry">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-display font-bold text-slate-900 inline-flex items-center gap-2">
            <Building2 className="h-6 w-6" /> Registre des Officines
          </h1>
          <p className="text-sm text-slate-600 mt-1">
            Validez les nouvelles pharmacies inscrites au self-service portal et gérez leurs statuts.
          </p>
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
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-left">
              <tr>
                <th className="px-3 py-2 font-medium">Officine</th>
                <th className="px-3 py-2 font-medium">Email / Téléphone</th>
                <th className="px-3 py-2 font-medium">Ville</th>
                <th className="px-3 py-2 font-medium">Statut</th>
                <th className="px-3 py-2 font-medium">Client CRM</th>
                <th className="px-3 py-2 font-medium">Créée</th>
                <th className="px-3 py-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody data-testid="registry-table-body">
              {loading && <tr><td colSpan={7} className="px-3 py-6 text-center text-slate-400">Chargement…</td></tr>}
              {!loading && items.length === 0 && (
                <tr><td colSpan={7} className="px-3 py-6 text-center text-slate-400">Aucune officine.</td></tr>
              )}
              {items.map((it) => {
                const st = STATUS_LABEL[it.status] || { text: it.status, color: "bg-slate-50" };
                return (
                  <tr key={it.id} className="border-t border-slate-100 hover:bg-slate-50" data-testid={`registry-row-${it.id}`}>
                    <td className="px-3 py-2">
                      <p className="font-medium text-slate-900">{it.name}</p>
                      {it.contact_name && <p className="text-[11px] text-slate-500">{it.contact_name}</p>}
                    </td>
                    <td className="px-3 py-2 text-slate-600">
                      <p className="text-xs">{it.email}</p>
                      <p className="text-[11px] text-slate-500">{it.phone}</p>
                    </td>
                    <td className="px-3 py-2 text-slate-600">{it.city || "—"} {it.country && <span className="text-[11px] text-slate-500">({it.country})</span>}</td>
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
                    <td className="px-3 py-2 text-[11px] text-slate-500 tabular-nums">
                      {it.created_at ? new Date(it.created_at).toLocaleDateString("fr-FR") : "—"}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <div className="inline-flex gap-1">
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
                          data-testid={`link-${it.id}`}>
                          <LinkIcon className="h-3 w-3" /> Lier
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
