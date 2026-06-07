// Iter42 — Officine portal Dashboard: KPIs + welcome
import React from "react";
import { Link } from "react-router-dom";
import { officineApi, loadOfficineSession } from "@/lib/officineApi";
import { Boxes, KeyRound, History, AlertTriangle } from "lucide-react";

export default function OfficineDashboard() {
  const { officine } = loadOfficineSession();
  const [stats, setStats] = React.useState({ inventory: 0, history: 0, expiring_soon: 0 });
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    (async () => {
      try {
        const [inv, hist] = await Promise.all([
          officineApi.get("/officines-portal/inventory"),
          officineApi.get("/officines-portal/history", { params: { limit: 1 } }),
        ]);
        const items = inv.data?.items || [];
        const now = new Date();
        const in30 = new Date(now.getTime() + 30 * 86400 * 1000);
        const expiring = items.filter((it) => {
          if (!it.expiry_date) return false;
          try {
            const d = new Date(it.expiry_date);
            return d <= in30 && d >= now;
          } catch { return false; }
        }).length;
        setStats({
          inventory: items.length,
          history: hist.data?.count || 0,
          expiring_soon: expiring,
        });
      } finally { setLoading(false); }
    })();
  }, []);

  return (
    <div className="space-y-6" data-testid="officine-dashboard">
      <div>
        <h1 className="text-2xl font-display font-bold text-slate-900">
          Bienvenue, {officine?.name || "Pharmacie"}
        </h1>
        <p className="text-sm text-slate-600 mt-1">
          Gérez votre inventaire, votre clé HMAC et consultez votre historique.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          icon={Boxes} label="Items en stock" value={stats.inventory}
          color="sky" to="/officines/inventory" loading={loading}
          testid="kpi-inventory"
        />
        <StatCard
          icon={AlertTriangle} label="À expirer (30j)" value={stats.expiring_soon}
          color={stats.expiring_soon > 0 ? "amber" : "emerald"}
          to="/officines/inventory" loading={loading}
          testid="kpi-expiring"
        />
        <StatCard
          icon={History} label="Activités enregistrées" value={stats.history}
          color="violet" to="/officines/history" loading={loading}
          testid="kpi-history"
        />
      </div>

      <div className="bg-white rounded-xl shadow-sm ring-1 ring-slate-200 p-5">
        <h2 className="font-display font-semibold text-slate-900">Actions rapides</h2>
        <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-3">
          <Link to="/officines/inventory" className="block p-4 rounded-lg bg-sky-50 hover:bg-sky-100 ring-1 ring-sky-100 transition" data-testid="quick-inventory">
            <Boxes className="h-5 w-5 text-sky-700" />
            <p className="mt-2 text-sm font-medium text-slate-900">Mettre à jour l&apos;inventaire</p>
            <p className="text-xs text-slate-600">Ajouter, modifier ou supprimer des médicaments.</p>
          </Link>
          <Link to="/officines/secret" className="block p-4 rounded-lg bg-emerald-50 hover:bg-emerald-100 ring-1 ring-emerald-100 transition" data-testid="quick-secret">
            <KeyRound className="h-5 w-5 text-emerald-700" />
            <p className="mt-2 text-sm font-medium text-slate-900">Régénérer la clé HMAC</p>
            <p className="text-xs text-slate-600">Pour signer vos requêtes API publiques.</p>
          </Link>
          <Link to="/officines/history" className="block p-4 rounded-lg bg-violet-50 hover:bg-violet-100 ring-1 ring-violet-100 transition" data-testid="quick-history">
            <History className="h-5 w-5 text-violet-700" />
            <p className="mt-2 text-sm font-medium text-slate-900">Consulter l&apos;historique</p>
            <p className="text-xs text-slate-600">Téléchargez votre journal en CSV.</p>
          </Link>
        </div>
      </div>
    </div>
  );
}

function StatCard({ icon: Icon, label, value, color, to, loading, testid }) {
  const tone = {
    sky: "bg-sky-50 text-sky-700 ring-sky-200",
    emerald: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    amber: "bg-amber-50 text-amber-700 ring-amber-200",
    violet: "bg-violet-50 text-violet-700 ring-violet-200",
  }[color];
  return (
    <Link to={to} className={`block rounded-xl p-4 ring-1 transition hover:shadow-md ${tone}`} data-testid={testid}>
      <Icon className="h-6 w-6" />
      <p className="mt-2 text-xs uppercase tracking-wider opacity-80">{label}</p>
      <p className="mt-1 text-2xl font-bold tabular-nums">
        {loading ? "…" : value}
      </p>
    </Link>
  );
}
