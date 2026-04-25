import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Download, Trash2, Mail, Search } from "lucide-react";
import { toast } from "sonner";

export default function AdminNewsletter() {
  const [items, setItems] = useState([]);
  const [filter, setFilter] = useState("");

  const load = () => apiClient.get("/admin/newsletter").then((r) => setItems(r.data));
  useEffect(() => { load().catch(() => {}); }, []);

  const del = async (id) => {
    if (!window.confirm("Supprimer cet abonné ?")) return;
    await apiClient.delete(`/admin/newsletter/${id}`);
    await load();
  };
  const exportCsv = async () => {
    const r = await apiClient.get("/admin/newsletter/export", { responseType: "blob" });
    const url = window.URL.createObjectURL(new Blob([r.data], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url; a.download = "newsletter_subscribers.csv";
    document.body.appendChild(a); a.click(); a.remove();
    toast.success("Export téléchargé");
  };

  const filtered = items.filter((x) => !filter || (x.email + " " + (x.name || "")).toLowerCase().includes(filter.toLowerCase()));
  const active = items.filter((x) => x.status === "active").length;

  return (
    <div className="space-y-6" data-testid="admin-newsletter-page">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-display font-bold">Newsletter</h1>
          <p className="text-sm text-slate-500">Gérez vos abonnés et exportez la liste en CSV.</p>
        </div>
        <button onClick={exportCsv} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light" data-testid="newsletter-export">
          <Download className="h-4 w-4" /> Exporter CSV
        </button>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <Stat label="Abonnés actifs" value={active} accent="text-emerald-600" />
        <Stat label="Désabonnés" value={items.length - active} accent="text-slate-500" />
        <Stat label="Total" value={items.length} />
      </div>

      <div className="rounded-xl border border-slate-200 bg-white">
        <div className="p-3 border-b border-slate-100 relative">
          <Search className="absolute left-5 top-5 h-4 w-4 text-slate-400" />
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Rechercher email ou prénom..."
                 className="w-full pl-9 pr-3 py-2 text-sm rounded border border-slate-200 focus:outline-none focus:border-sawali-blue" data-testid="newsletter-search" />
        </div>
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-600">
            <tr>
              <th className="text-left px-4 py-3">Email</th>
              <th className="text-left px-4 py-3">Prénom</th>
              <th className="text-left px-4 py-3">Source</th>
              <th className="text-left px-4 py-3">Statut</th>
              <th className="text-left px-4 py-3">Date</th>
              <th className="text-right px-4 py-3">Action</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && <tr><td colSpan={6} className="px-4 py-10 text-center text-slate-500">Aucun abonné.</td></tr>}
            {filtered.map((s) => (
              <tr key={s.id} className="border-t border-slate-100" data-testid={`subscriber-${s.id}`}>
                <td className="px-4 py-3 font-medium inline-flex items-center gap-2"><Mail className="h-3.5 w-3.5 text-sawali-blue" /> {s.email}</td>
                <td className="px-4 py-3 text-slate-600">{s.name || "-"}</td>
                <td className="px-4 py-3 text-slate-600">{s.source}</td>
                <td className="px-4 py-3">
                  <span className={`text-xs px-2 py-1 rounded ${s.status === "active" ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-700"}`}>
                    {s.status === "active" ? "Actif" : "Désabonné"}
                  </span>
                </td>
                <td className="px-4 py-3 text-slate-500">{new Date(s.created_at).toLocaleDateString("fr-FR")}</td>
                <td className="px-4 py-3 text-right">
                  <button onClick={() => del(s.id)} className="text-rose-600 hover:underline" data-testid={`del-${s.id}`}>
                    <Trash2 className="h-4 w-4 inline" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const Stat = ({ label, value, accent = "text-slate-900" }) => (
  <div className="rounded-xl border border-slate-200 bg-white p-4">
    <p className="text-xs uppercase tracking-[0.2em] text-slate-500">{label}</p>
    <p className={`mt-1 text-2xl font-display font-bold ${accent}`}>{value}</p>
  </div>
);
