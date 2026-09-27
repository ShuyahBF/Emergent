/*
  SurveyContributors — lot 27 : meilleurs contributeurs aux sondages WhatsApp.

  - Podium des 3 premiers puis tableau : réponses, sondages, taux de réponse,
    délai moyen de réponse, dernière réponse ;
  - période (du … au …) ;
  - admin / Superviseur : « Tous les clients » (classement global) ou un client
    (tenant) précis, et classement des clients par nombre de réponses ;
  - les réponses aux sondages anonymes comptent pour les clients mais ne
    donnent aucun nom.
*/
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Trophy, Medal, Clock, Building2 } from "lucide-react";

const fmtDelay = (h) => (h == null ? "—" : h < 1 ? `${Math.max(1, Math.round(h * 60))} min` : h < 48 ? `${Math.round(h)} h` : `${Math.round(h / 24)} j`);
const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString("fr-FR") : "—");
const PODIUM = [
  ["bg-amber-100 ring-amber-300 text-amber-800", "🥇"],
  ["bg-slate-100 ring-slate-300 text-slate-700", "🥈"],
  ["bg-orange-100 ring-orange-300 text-orange-800", "🥉"],
];

export default function SurveyContributors() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "superviseur";
  const [clientId, setClientId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [roster, setRoster] = useState([]);
  const [data, setData] = useState(null);

  useEffect(() => {
    if (isAdmin) apiClient.get("/me/clients-roster").then((r) => setRoster(Array.isArray(r.data) ? r.data : [])).catch(() => {});
  }, [isAdmin]);

  useEffect(() => {
    const params = { limit: 50 };
    if (clientId) params.client_id = clientId;
    if (dateFrom) params.date_from = dateFrom;
    if (dateTo) params.date_to = dateTo;
    apiClient.get("/me/wa-surveys-contributors", { params })
      .then((r) => setData(r.data)).catch(() => setData({ items: [], tenants: [] }));
  }, [clientId, dateFrom, dateTo]);

  const items = data?.items || [];
  return (
    <div className="space-y-4" data-testid="survey-contributors">
      <div className="flex flex-wrap items-end gap-3 rounded-xl bg-white ring-1 ring-slate-200 p-3 text-sm">
        {isAdmin && (
          <label className="text-xs text-slate-600">Client
            <select value={clientId} onChange={(e) => setClientId(e.target.value)} data-testid="contrib-client"
              className="mt-1 block rounded-lg border border-slate-300 px-2 py-1.5 text-sm min-w-[14rem]">
              <option value="">Tous les clients (classement global)</option>
              {roster.map((c) => <option key={c.id} value={c.id}>{c.company || c.full_name}{c.client_code ? ` · ${c.client_code}` : ""}</option>)}
            </select>
          </label>
        )}
        <label className="text-xs text-slate-600">Du
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="mt-1 block rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
        </label>
        <label className="text-xs text-slate-600">Au
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="mt-1 block rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
        </label>
      </div>

      {!data ? <p className="text-sm text-slate-500">Chargement…</p> : !items.length ? (
        <p className="rounded-xl border-2 border-dashed border-slate-200 p-8 text-center text-sm text-slate-500">
          Aucune réponse sur cette période.
        </p>
      ) : (
        <>
          {/* Podium des 3 premiers */}
          <div className="grid sm:grid-cols-3 gap-3">
            {items.slice(0, 3).map((r, i) => (
              <div key={r.contact_id || r.rank} className={`rounded-2xl ring-1 p-4 ${PODIUM[i][0]}`} data-testid={`contrib-podium-${i}`}>
                <p className="text-3xl">{PODIUM[i][1]}</p>
                <p className="font-bold truncate">{r.name}</p>
                <p className="text-xs opacity-80 truncate">{r.company}{isAdmin && !clientId && r.tenant_name ? ` · ${r.tenant_name}` : ""}</p>
                <p className="mt-2 text-sm"><b className="text-xl tabular-nums">{r.answered}</b> réponse(s) · {r.response_rate} %</p>
                <p className="text-[11px] opacity-80 flex items-center gap-1"><Clock className="h-3 w-3" /> répond en {fmtDelay(r.avg_delay_hours)}</p>
              </div>
            ))}
          </div>
          {/* Tableau complet */}
          <div className="rounded-xl bg-white ring-1 ring-slate-200 overflow-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-[11px] uppercase text-slate-500">
                <tr><th className="px-3 py-2 text-left">#</th><th className="text-left">Contact</th>
                  {isAdmin && !clientId && <th className="text-left">Client</th>}
                  <th className="text-right">Réponses</th><th className="text-right">Sondages</th><th className="text-right">Taux</th>
                  <th className="text-right">Délai moyen</th><th className="text-right px-3">Dernière réponse</th></tr>
              </thead>
              <tbody>
                {items.map((r) => (
                  <tr key={r.contact_id || r.rank} className="border-t border-slate-100">
                    <td className="px-3 py-1.5 tabular-nums">{r.rank <= 3 ? <Medal className="h-4 w-4 text-amber-500" /> : r.rank}</td>
                    <td><p className="font-medium text-slate-800">{r.name}</p><p className="text-[11px] text-slate-400">{r.company} · {r.phone}</p></td>
                    {isAdmin && !clientId && <td className="text-xs text-slate-600">{r.tenant_name}</td>}
                    <td className="text-right font-semibold tabular-nums">{r.answered}</td>
                    <td className="text-right tabular-nums">{r.surveys}</td>
                    <td className="text-right tabular-nums">{r.response_rate} %</td>
                    <td className="text-right tabular-nums">{fmtDelay(r.avg_delay_hours)}</td>
                    <td className="text-right px-3 text-xs">{fmtDate(r.last_answer_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.anonymous_excluded > 0 && (
            <p className="text-[11px] text-slate-500">{data.anonymous_excluded} réponse(s) à des sondages anonymes ne sont pas nominatives et n'apparaissent pas ici.</p>
          )}
        </>
      )}

      {/* Classement des clients (admin, vue globale) */}
      {isAdmin && !clientId && (data?.tenants || []).length > 0 && (
        <div className="rounded-xl bg-white ring-1 ring-slate-200 p-4" data-testid="contrib-tenants">
          <p className="font-semibold text-slate-900 mb-2 flex items-center gap-2"><Trophy className="h-4 w-4 text-amber-500" /> Classement des clients</p>
          <table className="w-full text-sm">
            <thead className="text-[11px] uppercase text-slate-500"><tr><th className="text-left">Client</th><th className="text-right">Envoyés</th>
              <th className="text-right">Réponses</th><th className="text-right">Répondants</th><th className="text-right">Taux</th></tr></thead>
            <tbody>
              {data.tenants.map((t) => (
                <tr key={t.tenant_id || t.name} className="border-t border-slate-100">
                  <td className="py-1 flex items-center gap-1.5"><Building2 className="h-3.5 w-3.5 text-slate-400" /> {t.name}</td>
                  <td className="text-right tabular-nums">{t.sent}</td>
                  <td className="text-right tabular-nums font-semibold">{t.answered}</td>
                  <td className="text-right tabular-nums">{t.respondents}</td>
                  <td className="text-right tabular-nums">{t.response_rate == null ? "—" : `${t.response_rate} %`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
