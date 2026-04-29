import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Link } from "react-router-dom";
import { Calendar, Wrench, FileText, ArrowRight, CheckCircle2, Clock, ClipboardList } from "lucide-react";

const StatCard = ({ icon: Icon, label, value, hint, testid }) => (
  <div className="rounded-xl border border-slate-200 bg-white p-5" data-testid={testid}>
    <div className="flex items-center gap-3">
      <div className="h-10 w-10 rounded-lg bg-sawali-blue/10 flex items-center justify-center">
        <Icon className="h-5 w-5 text-sawali-blue" />
      </div>
      <div>
        <p className="text-xs uppercase tracking-[0.2em] text-slate-500">{label}</p>
        <p className="text-2xl font-display font-bold text-slate-900">{value}</p>
        {hint && <p className="text-[11px] text-slate-500 mt-1">{hint}</p>}
      </div>
    </div>
  </div>
);

const NoteCard = ({ to, label, accent, count, lastUpdated, icon: Icon, testid }) => (
  <Link
    to={to}
    className="group rounded-xl border border-slate-200 bg-white p-5 hover:border-current transition flex items-start gap-4"
    style={{ "--brand": accent }}
    data-testid={testid}
  >
    <div className="h-12 w-12 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: accent + "18" }}>
      <Icon className="h-6 w-6" style={{ color: accent }} />
    </div>
    <div className="flex-1 min-w-0">
      <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Mes {label}</p>
      <p className="text-3xl font-display font-bold text-slate-900 leading-tight">{count}</p>
      <p className="text-[11px] text-slate-500 mt-1 truncate">
        {lastUpdated ? `Dernière mise à jour : ${new Date(lastUpdated).toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" })}` : "Aucun enregistrement"}
      </p>
    </div>
    <ArrowRight className="h-4 w-4 text-slate-400 group-hover:translate-x-1 transition-transform" style={{ color: accent }} />
  </Link>
);

export default function ClientDashboard() {
  const [data, setData] = useState(null);
  const [notes, setNotes] = useState({ reports: { count: 0, last_updated: null }, suivis: { count: 0, last_updated: null } });
  const [features, setFeatures] = useState({ show_reports_button: true, show_suivis_button: true });

  useEffect(() => {
    apiClient.get("/me/account").then((r) => setData(r.data)).catch(() => {});
    apiClient.get("/me/notes-summary").then((r) => setNotes(r.data)).catch(() => {});
    apiClient.get("/company-info").then((r) => {
      if (r.data?.portal_features) setFeatures(r.data.portal_features);
    }).catch(() => {});
  }, []);
  if (!data) return <p className="text-slate-500">Chargement...</p>;

  const s = data.stats;
  return (
    <div className="space-y-8" data-testid="client-dashboard">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-sawali-blue">Espace Client</p>
          <h1 className="text-3xl font-display font-bold">Bonjour, {data.user.full_name.split(" ")[0]}</h1>
          <p className="text-sm text-slate-500 mt-1">Voici l'état de votre compte aujourd'hui.</p>
        </div>
        <Link to="/portal/appointments" className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light" data-testid="dashboard-cta-rdv">
          Demander un rendez-vous <ArrowRight className="h-4 w-4" />
        </Link>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard icon={Calendar} label="Rendez-vous" value={s.appointments} hint={`${s.appointments_pending} en attente`} testid="stat-appointments" />
        <StatCard icon={Wrench} label="Interventions" value={s.interventions} testid="stat-interventions" />
        <StatCard icon={FileText} label="Documents" value={s.documents} testid="stat-documents" />
        <StatCard icon={CheckCircle2} label="Statut" value={data.user.account_status === "active" ? "Actif" : "Inactif"} testid="stat-status" />
      </div>

      {(features.show_reports_button || features.show_suivis_button) && (
        <div className="grid sm:grid-cols-2 gap-4" data-testid="dashboard-notes-section">
          {features.show_reports_button && (
            <NoteCard to="/portal/notes/reports" label="rapports" accent="#1E90FF" count={notes.reports.count} lastUpdated={notes.reports.last_updated} icon={FileText} testid="dashboard-reports-btn" />
          )}
          {features.show_suivis_button && (
            <NoteCard to="/portal/notes/suivis" label="suivis" accent="#10B981" count={notes.suivis.count} lastUpdated={notes.suivis.last_updated} icon={ClipboardList} testid="dashboard-suivis-btn" />
          )}
        </div>
      )}

      <div className="grid lg:grid-cols-2 gap-6">
        <div className="rounded-xl border border-slate-200 bg-white p-6" data-testid="recent-appointments">
          <h2 className="font-display font-semibold flex items-center gap-2"><Clock className="h-4 w-4 text-sawali-blue" /> Rendez-vous récents</h2>
          <ul className="mt-4 divide-y divide-slate-100">
            {data.recent_appointments.length === 0 && <p className="text-sm text-slate-500">Aucun rendez-vous.</p>}
            {data.recent_appointments.map((a) => (
              <li key={a.id} className="py-3 flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-slate-800">{a.subject}</p>
                  <p className="text-xs text-slate-500">{new Date(a.scheduled_at).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" })}</p>
                </div>
                <Badge status={a.status} />
              </li>
            ))}
          </ul>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-6" data-testid="recent-interventions">
          <h2 className="font-display font-semibold flex items-center gap-2"><Wrench className="h-4 w-4 text-sawali-blue" /> Interventions récentes</h2>
          <ul className="mt-4 divide-y divide-slate-100">
            {data.recent_interventions.length === 0 && <p className="text-sm text-slate-500">Aucune intervention enregistrée.</p>}
            {data.recent_interventions.map((i) => (
              <li key={i.id} className="py-3 flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-slate-800">{i.title}</p>
                  <p className="text-xs text-slate-500">{i.intervention_date && new Date(i.intervention_date).toLocaleDateString("fr-FR")}</p>
                </div>
                <Badge status={i.status} />
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

const Badge = ({ status }) => {
  const map = {
    pending: ["Attente", "bg-amber-100 text-amber-700"],
    confirmed: ["Confirmé", "bg-sky-100 text-sky-700"],
    cancelled: ["Annulé", "bg-rose-100 text-rose-700"],
    completed: ["Terminé", "bg-emerald-100 text-emerald-700"],
    in_progress: ["En cours", "bg-violet-100 text-violet-700"],
    planned: ["Planifié", "bg-slate-100 text-slate-700"],
  };
  const [label, cls] = map[status] || [status, "bg-slate-100 text-slate-700"];
  return <span className={`text-xs px-2 py-1 rounded ${cls}`}>{label}</span>;
};
