import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Plus, Trash2, ShieldAlert } from "lucide-react";
import { toast } from "sonner";

export default function AdminBlacklist() {
  const [items, setItems] = useState([]);
  const [cidr, setCidr] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => apiClient.get("/admin/blacklisted-ips").then((r) => setItems(r.data));
  useEffect(() => { load().catch(() => {}); }, []);

  const add = async (e) => {
    e.preventDefault();
    if (!cidr.trim()) return;
    setBusy(true);
    try {
      await apiClient.post("/admin/blacklisted-ips", { cidr: cidr.trim(), reason: reason.trim() || null });
      toast.success("IP ajoutée à la blacklist");
      setCidr(""); setReason("");
      await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setBusy(false); }
  };

  const del = async (id, ip) => {
    if (!window.confirm(`Retirer ${ip} de la blacklist ?`)) return;
    await apiClient.delete(`/admin/blacklisted-ips/${id}`);
    toast.success("IP retirée"); await load();
  };

  return (
    <div className="space-y-6" data-testid="admin-blacklist-page">
      <div>
        <h1 className="text-2xl font-display font-bold flex items-center gap-2">
          <ShieldAlert className="h-6 w-6 text-rose-500" /> Blacklist IP
        </h1>
        <p className="text-sm text-slate-500">
          Bloque l'accès au portail (login + APIs) pour les adresses IP listées. Supporte les IP simples et les plages CIDR.
        </p>
      </div>

      <form onSubmit={add} className="rounded-xl border border-slate-200 bg-white p-4 grid sm:grid-cols-[1fr,2fr,auto] gap-3 items-end">
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">IP ou CIDR *</label>
          <input
            value={cidr}
            onChange={(e) => setCidr(e.target.value)}
            placeholder="ex. 192.168.1.42 ou 10.0.0.0/24"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono focus:border-sawali-blue focus:outline-none"
            required
            data-testid="bl-cidr-input"
          />
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">Motif (optionnel)</label>
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="ex. Tentatives de brute force"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-sawali-blue focus:outline-none"
            data-testid="bl-reason-input"
          />
        </div>
        <button type="submit" disabled={busy} className="inline-flex items-center gap-2 rounded-lg bg-rose-600 text-white px-4 py-2 text-sm hover:bg-rose-700 disabled:opacity-50" data-testid="bl-add-btn">
          <Plus className="h-4 w-4" /> Bloquer
        </button>
      </form>

      <div className="rounded-xl border border-slate-200 bg-white overflow-x-auto">
        <table className="w-full text-sm min-w-[640px]">
          <thead className="bg-slate-50 text-xs uppercase text-slate-600">
            <tr>
              <th className="text-left px-4 py-3">IP / CIDR</th>
              <th className="text-left px-4 py-3">Motif</th>
              <th className="text-left px-4 py-3">Ajouté le</th>
              <th className="text-right px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={4} className="px-4 py-10 text-center text-slate-500">Aucune IP bloquée.</td></tr>}
            {items.map((b) => (
              <tr key={b.id} className="border-t border-slate-100" data-testid={`bl-row-${b.id}`}>
                <td className="px-4 py-3 font-mono text-rose-700">{b.cidr}</td>
                <td className="px-4 py-3 text-slate-600">{b.reason || "-"}</td>
                <td className="px-4 py-3 text-xs text-slate-500">{new Date(b.created_at).toLocaleString("fr-FR")}</td>
                <td className="px-4 py-3 text-right">
                  <button onClick={() => del(b.id, b.cidr)} className="text-slate-500 hover:text-rose-600" title="Retirer">
                    <Trash2 className="h-4 w-4 inline" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-slate-500">
        💡 Astuce : utilisez le format <code className="font-mono">a.b.c.d/24</code> pour bloquer un sous-réseau entier (256 IPs).
      </p>
    </div>
  );
}
