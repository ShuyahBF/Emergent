import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Globe, MapPin, Eye } from "lucide-react";

export default function AdminVisits() {
  const [items, setItems] = useState([]);
  const [stats, setStats] = useState(null);

  useEffect(() => {
    apiClient.get("/admin/visits?limit=200").then((r) => setItems(r.data)).catch(() => {});
    apiClient.get("/admin/visits/stats").then((r) => setStats(r.data)).catch(() => {});
  }, []);

  return (
    <div className="space-y-6" data-testid="admin-visits-page">
      <div>
        <h1 className="text-2xl font-display font-bold">Trafic & Visites</h1>
        <p className="text-sm text-slate-500">Suivi des accès au site (date/heure, IP, pays/ville).</p>
      </div>

      {stats && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <Stat icon={Eye} label="Visites totales" value={stats.total} />
          <Stat icon={Globe} label="Pays uniques" value={stats.unique_countries} />
          <div className="rounded-xl border border-slate-200 bg-white p-4 col-span-2">
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Top pays</p>
            <ul className="mt-2 space-y-1 text-sm">
              {stats.top_countries.slice(0, 5).map((c) => (
                <li key={c.country} className="flex items-center justify-between">
                  <span>{c.country}</span>
                  <span className="text-sawali-blue font-display font-bold">{c.count}</span>
                </li>
              ))}
              {stats.top_countries.length === 0 && <li className="text-slate-500">Aucune donnée</li>}
            </ul>
          </div>
        </div>
      )}

      {stats && stats.top_pages.length > 0 && (
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <h2 className="font-display font-semibold mb-3">Pages les plus consultées</h2>
          <div className="grid sm:grid-cols-2 gap-2 text-sm">
            {stats.top_pages.map((p) => (
              <div key={p.page} className="flex items-center justify-between border-b border-slate-100 pb-1">
                <code className="text-slate-700">{p.page}</code>
                <span className="text-sawali-blue font-display font-bold">{p.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="rounded-xl border border-slate-200 bg-white overflow-x-auto">
        <table className="w-full text-sm min-w-[820px]">
          <thead className="bg-slate-50 text-xs uppercase text-slate-600">
            <tr>
              <th className="text-left px-4 py-3">Date / Heure</th>
              <th className="text-left px-4 py-3">IP</th>
              <th className="text-left px-4 py-3">Pays / Ville</th>
              <th className="text-left px-4 py-3">Page</th>
              <th className="text-left px-4 py-3">Référent</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={5} className="px-4 py-10 text-center text-slate-500">Aucune visite enregistrée.</td></tr>}
            {items.map((v) => (
              <tr key={v.id} className="border-t border-slate-100" data-testid={`visit-${v.id}`}>
                <td className="px-4 py-3 text-slate-600 whitespace-nowrap">{new Date(v.datetime).toLocaleString("fr-FR")}</td>
                <td className="px-4 py-3 font-mono text-xs">{v.ip || "-"}</td>
                <td className="px-4 py-3"><span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3 text-sawali-blue" />{[v.city, v.country].filter(Boolean).join(", ") || "—"}</span></td>
                <td className="px-4 py-3"><code className="text-xs text-slate-700">{v.page}</code></td>
                <td className="px-4 py-3 text-xs text-slate-500 truncate max-w-[220px]">{v.referrer || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const Stat = ({ icon: Icon, label, value }) => (
  <div className="rounded-xl border border-slate-200 bg-white p-4">
    <div className="flex items-center gap-3">
      <div className="h-9 w-9 rounded-lg bg-sawali-blue/10 grid place-items-center"><Icon className="h-4 w-4 text-sawali-blue" /></div>
      <div>
        <p className="text-xs uppercase tracking-[0.2em] text-slate-500">{label}</p>
        <p className="text-2xl font-display font-bold">{value}</p>
      </div>
    </div>
  </div>
);
