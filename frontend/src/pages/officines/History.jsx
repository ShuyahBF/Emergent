// Iter42 — Officine portal: History (audit log + CSV export)
import React from "react";
import { officineApi } from "@/lib/officineApi";
import { Download, History as HistoryIcon } from "lucide-react";
import { toast } from "sonner";

const ACTION_LABELS = {
  register: "Inscription",
  approve: "Compte activé",
  suspend: "Compte suspendu",
  reactivate: "Compte réactivé",
  login_otp: "Connexion OTP",
  login_magic: "Connexion magic link",
  inventory_create: "Item ajouté",
  inventory_update: "Item modifié",
  inventory_delete: "Item supprimé",
  regenerate_secret: "Clé HMAC régénérée",
  link_client: "Lien CRM ajouté",
  unlink_client: "Lien CRM retiré",
};

const ACTION_COLORS = {
  register: "violet", approve: "emerald", suspend: "rose", reactivate: "emerald",
  login_otp: "sky", login_magic: "sky",
  inventory_create: "emerald", inventory_update: "amber", inventory_delete: "rose",
  regenerate_secret: "amber",
  link_client: "violet", unlink_client: "slate",
};

export default function OfficineHistory() {
  const [items, setItems] = React.useState([]);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    (async () => {
      try {
        const r = await officineApi.get("/officines-portal/history");
        setItems(r.data?.items || []);
      } finally { setLoading(false); }
    })();
  }, []);

  const exportCsv = () => {
    const url = `${process.env.REACT_APP_BACKEND_URL}/api/officines-portal/history/export.csv`;
    const token = localStorage.getItem("sawali_officine_token");
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.blob())
      .then((blob) => {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `historique-${new Date().toISOString().slice(0, 10)}.csv`;
        a.click();
      })
      .catch(() => toast.error("Échec téléchargement"));
  };

  return (
    <div className="space-y-4" data-testid="officine-history-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-display font-bold text-slate-900 inline-flex items-center gap-2">
            <HistoryIcon className="h-5 w-5" /> Historique
          </h1>
          <p className="text-sm text-slate-600 mt-1">
            Journal de toutes les activités enregistrées sur votre compte officine.
          </p>
        </div>
        <button
          onClick={exportCsv}
          className="inline-flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 ring-1 ring-slate-200"
          data-testid="history-export-btn"
        >
          <Download className="h-3.5 w-3.5" /> Export CSV
        </button>
      </div>

      <div className="bg-white rounded-xl shadow-sm ring-1 ring-slate-200 overflow-hidden">
        <ul className="divide-y divide-slate-100" data-testid="history-list">
          {loading && <li className="px-4 py-6 text-center text-slate-400">Chargement…</li>}
          {!loading && items.length === 0 && (
            <li className="px-4 py-6 text-center text-slate-400">Aucune activité enregistrée.</li>
          )}
          {items.map((it) => {
            const color = ACTION_COLORS[it.action] || "slate";
            const tone = {
              sky: "bg-sky-50 text-sky-700 ring-sky-200",
              emerald: "bg-emerald-50 text-emerald-700 ring-emerald-200",
              amber: "bg-amber-50 text-amber-700 ring-amber-200",
              rose: "bg-rose-50 text-rose-700 ring-rose-200",
              violet: "bg-violet-50 text-violet-700 ring-violet-200",
              slate: "bg-slate-50 text-slate-700 ring-slate-200",
            }[color];
            return (
              <li key={it.id || it.created_at} className="px-4 py-3 hover:bg-slate-50" data-testid={`history-row-${it.id || ""}`}>
                <div className="flex items-center justify-between gap-3 flex-wrap">
                  <div className="flex items-center gap-3 min-w-0">
                    <span className={`text-[10px] uppercase tracking-wider font-medium px-2 py-1 rounded ring-1 whitespace-nowrap ${tone}`}>
                      {ACTION_LABELS[it.action] || it.action}
                    </span>
                    <div className="min-w-0">
                      <p className="text-xs text-slate-600 truncate">
                        Par <span className="font-medium text-slate-800">{it.actor || "—"}</span>
                      </p>
                      {it.details && Object.keys(it.details).length > 0 && (
                        <p className="text-[11px] text-slate-500 mt-0.5 truncate" title={JSON.stringify(it.details)}>
                          {JSON.stringify(it.details)}
                        </p>
                      )}
                    </div>
                  </div>
                  <time className="text-[11px] text-slate-500 tabular-nums whitespace-nowrap">
                    {new Date(it.created_at).toLocaleString("fr-FR")}
                  </time>
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
