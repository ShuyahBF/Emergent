import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import MonthlyPresenceCard from "@/components/MonthlyPresenceCard";

export default function ClientUsersTracking() {
  const [items, setItems] = useState([]);
  useEffect(() => { apiClient.get("/me/users").then((r) => setItems(r.data)).catch(() => {}); }, []);
  return (
    <div className="space-y-6" data-testid="client-users-page">
      <div>
        <h1 className="text-2xl font-display font-bold">Suivi de vos utilisateurs</h1>
        <p className="text-sm text-slate-500">Liste des utilisateurs déclarés sur vos logiciels.</p>
      </div>
      <MonthlyPresenceCard />
      <div className="rounded-xl border border-slate-200 bg-white overflow-x-auto">
        <table className="w-full text-sm min-w-[640px]">
          <thead className="bg-slate-50 text-xs uppercase text-slate-600">
            <tr>
              <th className="text-left px-4 py-3">Nom</th>
              <th className="text-left px-4 py-3">Email</th>
              <th className="text-left px-4 py-3">Rôle</th>
              <th className="text-left px-4 py-3">Service</th>
              <th className="text-left px-4 py-3">Dernière activité</th>
              <th className="text-left px-4 py-3">Statut</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={6} className="px-4 py-10 text-center text-slate-500">Aucun utilisateur enregistré.</td></tr>}
            {items.map((u) => (
              <tr key={u.id} className="border-t border-slate-100" data-testid={`user-row-${u.id}`}>
                <td className="px-4 py-3 font-medium">{u.name}</td>
                <td className="px-4 py-3 text-slate-600">{u.email || "-"}</td>
                <td className="px-4 py-3 text-slate-600">{u.role || "-"}</td>
                <td className="px-4 py-3 text-slate-600">{u.department || "-"}</td>
                <td className="px-4 py-3 text-slate-600">{u.last_seen ? new Date(u.last_seen).toLocaleString("fr-FR") : "-"}</td>
                <td className="px-4 py-3">
                  <span className={`text-xs px-2 py-1 rounded ${u.status === "active" ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-700"}`}>{u.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
