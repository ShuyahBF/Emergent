import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Users, Calendar, FileText, Wrench, Inbox } from "lucide-react";

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

export default function AdminDashboard() {
  const [stats, setStats] = useState({ clients: 0, appointments: 0, documents: 0, interventions: 0, contacts: 0 });
  useEffect(() => {
    Promise.all([
      apiClient.get("/admin/clients"),
      apiClient.get("/admin/appointments"),
      apiClient.get("/admin/documents"),
      apiClient.get("/admin/interventions"),
      apiClient.get("/admin/contacts"),
    ]).then(([c, a, d, i, ct]) => setStats({ clients: c.data.length, appointments: a.data.length, documents: d.data.length, interventions: i.data.length, contacts: ct.data.length })).catch(() => {});
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
    </div>
  );
}
