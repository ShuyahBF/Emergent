import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Link } from "react-router-dom";
import { Users, Calendar, FileText, Wrench, Inbox, ClipboardList, ArrowRight } from "lucide-react";
import AdminAICostChart from "./AdminAICostChart";
import AdminLlmUsageChart from "./AdminLlmUsageChart";
import PlanningDigestAnalytics from "./PlanningDigestAnalytics";

const Card = ({ icon: Icon, label, value, testid }) => (
  <div className="rounded-xl border border-slate-200 bg-white p-5" data-testid={testid}>
    <div className="flex items-center gap-3">
      <div className="h-10 w-10 rounded-lg bg-sawali-blue/10 flex items-center justify-center">
        <Icon className="h-5 w-5 text-sawali-blue" />
      </div>
      <div>
        <p className="text-xs uppercase tracking-[0.2em] text-slate-500">{label}</p>
        <p className="text-2xl font-display font-bold">{value}</p>
      </div>
    </div>
  </div>
);

const NoteCard = ({ to, label, accent, count, lastUpdated, icon: Icon, testid }) => (
  <Link
    to={to}
    className="group rounded-xl border border-slate-200 bg-white p-5 hover:border-current transition flex items-start gap-4"
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
    <ArrowRight className="h-4 w-4" style={{ color: accent }} />
  </Link>
);

export default function AdminDashboard() {
  const [stats, setStats] = useState({ clients: 0, appointments: 0, documents: 0, interventions: 0, contacts: 0 });
  const [notes, setNotes] = useState({ reports: { count: 0, last_updated: null }, suivis: { count: 0, last_updated: null } });
  const [features, setFeatures] = useState({ show_reports_button: true, show_suivis_button: true });

  useEffect(() => {
    Promise.all([
      apiClient.get("/admin/clients"),
      apiClient.get("/admin/appointments"),
      apiClient.get("/admin/documents"),
      apiClient.get("/admin/interventions"),
      apiClient.get("/admin/contacts"),
    ]).then(([c, a, d, i, ct]) => setStats({
      clients: c.data.length, appointments: a.data.length, documents: d.data.length,
      interventions: i.data.length, contacts: ct.data.length,
    })).catch(() => {});
    apiClient.get("/me/notes-summary").then((r) => setNotes(r.data)).catch(() => {});
    apiClient.get("/company-info").then((r) => {
      if (r.data?.portal_features) setFeatures(r.data.portal_features);
    }).catch(() => {});
  }, []);

  return (
    <div className="space-y-6" data-testid="admin-dashboard">
      <div>
        <p className="text-xs uppercase tracking-[0.2em] text-sawali-blue">Console Administrateur</p>
        <h1 className="text-3xl font-display font-bold">Tableau de bord</h1>
        <p className="text-sm text-slate-500 mt-1">Vue globale du portail SAWALI.</p>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <Card icon={Users} label="Clients" value={stats.clients} testid="admin-stat-clients" />
        <Card icon={Calendar} label="RDV" value={stats.appointments} testid="admin-stat-appointments" />
        <Card icon={FileText} label="Documents" value={stats.documents} testid="admin-stat-documents" />
        <Card icon={Wrench} label="Interventions" value={stats.interventions} testid="admin-stat-interventions" />
        <Card icon={Inbox} label="Messages" value={stats.contacts} testid="admin-stat-contacts" />
      </div>

      {(features.show_reports_button || features.show_suivis_button) && (
        <div className="grid sm:grid-cols-2 gap-4" data-testid="admin-notes-section">
          {features.show_reports_button && (
            <NoteCard to="/admin/notes/reports" label="rapports" accent="#1E90FF" count={notes.reports.count} lastUpdated={notes.reports.last_updated} icon={FileText} testid="admin-reports-btn" />
          )}
          {features.show_suivis_button && (
            <NoteCard to="/admin/notes/suivis" label="suivis" accent="#10B981" count={notes.suivis.count} lastUpdated={notes.suivis.last_updated} icon={ClipboardList} testid="admin-suivis-btn" />
          )}
        </div>
      )}

      {/* S-iter39n — Universal Key daily consumption chart (S032 sister) */}
      <AdminLlmUsageChart />

      {/* 2026-02 fork (analytics) — Planning médecin WA digest metrics */}
      <PlanningDigestAnalytics />

      {/* Iter38r-fix9z5 — AI monthly cost chart */}
      <AdminAICostChart />
    </div>
  );
}
