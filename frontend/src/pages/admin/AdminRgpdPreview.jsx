import React, { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { ShieldCheck, ArrowLeft, Eye, EyeOff, RefreshCw } from "lucide-react";

/*
  /admin/clients/:client_id/rgpd-preview
  Preview side-by-side what a non-privileged user of this client would see
  vs the original record. Used to audit anonymization before a deployment
  (or before granting access to a new tracked user).
*/
export default function AdminRgpdPreview() {
  const { client_id } = useParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const reload = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get(`/admin/rgpd-preview/${client_id}`);
      setData(r.data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally { setLoading(false); }
  };
  useEffect(() => { reload(); /* eslint-disable-next-line */ }, [client_id]);

  if (loading) return <div className="text-sm text-slate-500 italic">Chargement…</div>;
  if (!data) return null;

  const flagsActive = Object.values(data.flags || {}).filter(Boolean).length;

  return (
    <div className="space-y-6 max-w-full" data-testid="rgpd-preview-page">
      <div>
        <Link to={`/admin/clients/${client_id}/features`} className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-sawali-blue">
          <ArrowLeft className="h-3 w-3" /> Retour aux fonctionnalités
        </Link>
        <h1 className="text-2xl font-display font-bold flex items-center gap-2 mt-2">
          <ShieldCheck className="h-5 w-5 text-rose-600" /> Audit RGPD — Aperçu
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Aperçu de ce qu'un utilisateur non-privilégié (rôle <code>utilisateur</code>) verrait dans le portail de
          <strong className="ml-1">{data.client_name || client_id}</strong>.
          Les rôles <strong>Modérateur / Admin / Superviseur</strong> voient toujours en clair.
        </p>
      </div>

      {/* Active flags banner */}
      <div className="rounded-xl ring-1 ring-rose-200 bg-rose-50 p-4">
        <p className="text-xs uppercase tracking-wider text-rose-700 font-bold flex items-center gap-2">
          <ShieldCheck className="h-4 w-4" /> Flags actifs : {flagsActive} / 4
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-3">
          {Object.entries(data.flags || {}).map(([k, v]) => (
            <div key={k} className={`rounded-lg px-3 py-2 ring-1 text-xs ${v ? "bg-rose-100 ring-rose-300 text-rose-900" : "bg-white ring-slate-200 text-slate-500"}`} data-testid={`flag-${k}`}>
              <p className="text-[10px] uppercase tracking-wider opacity-70">{k.replace("anon_", "")}</p>
              <p className="font-semibold flex items-center gap-1">
                {v ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
                {v ? "Anonymisé" : "Visible"}
              </p>
            </div>
          ))}
        </div>
        <button onClick={reload} className="mt-3 text-xs text-sawali-blue hover:underline inline-flex items-center gap-1" data-testid="rgpd-reload">
          <RefreshCw className="h-3 w-3" /> Rafraîchir
        </button>
      </div>

      {flagsActive === 0 && (
        <div className="rounded-xl ring-1 ring-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          Aucun flag d'anonymisation n'est activé pour ce client. L'aperçu serait identique à la vue admin.
          Activez les flags depuis l'onglet « Fonctionnalités » avant de relancer l'audit.
        </div>
      )}

      <PreviewSection
        title="Contacts"
        items={data.contacts}
        columns={[
          { key: "name", label: "Nom" },
          { key: "company", label: "Société" },
          { key: "phone", label: "Téléphone", mono: true },
          { key: "whatsapp", label: "WhatsApp", mono: true },
          { key: "email", label: "Email" },
        ]}
      />
      <PreviewSection
        title="Rendez-vous"
        items={data.appointments}
        columns={[
          { key: "name", label: "Client" },
          { key: "company", label: "Société" },
          { key: "phone", label: "Téléphone", mono: true },
          { key: "email", label: "Email" },
          { key: "scheduled_at", label: "Date" },
        ]}
      />
      <PreviewSection
        title="Interventions"
        items={data.interventions}
        columns={[
          { key: "title", label: "Titre" },
          { key: "technician", label: "Technicien" },
          { key: "intervention_date", label: "Date" },
        ]}
      />
      <PreviewSection
        title="Documents"
        items={data.documents}
        columns={[
          { key: "title", label: "Titre" },
          { key: "uploaded_by_name", label: "Déposé par (nom)" },
          { key: "uploaded_by_email", label: "Déposé par (email)" },
        ]}
      />
    </div>
  );
}

const PreviewSection = ({ title, items, columns }) => {
  return (
    <div className="rounded-xl ring-1 ring-slate-200 bg-white p-4 overflow-x-auto" data-testid={`section-${title.toLowerCase()}`}>
      <h2 className="text-sm font-semibold text-slate-700 mb-3">{title} <span className="text-xs text-slate-400">({items.length} échantillon{items.length > 1 ? "s" : ""})</span></h2>
      {items.length === 0 ? (
        <p className="text-xs text-slate-400 italic py-2">Aucun enregistrement pour cet échantillon.</p>
      ) : (
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-[10px] uppercase text-slate-500">
            <tr>
              <th className="text-left px-3 py-2">Vue</th>
              {columns.map((c) => (<th key={c.key} className="text-left px-3 py-2">{c.label}</th>))}
            </tr>
          </thead>
          <tbody>
            {items.map((row, idx) => (
              <React.Fragment key={idx}>
                <tr className="border-t border-slate-100">
                  <td className="px-3 py-2 text-[10px] uppercase tracking-wider text-emerald-700 font-bold">Admin (clair)</td>
                  {columns.map((c) => <td key={c.key} className={`px-3 py-1 text-xs text-slate-700 ${c.mono ? "font-mono" : ""}`}>{row.original?.[c.key] || "—"}</td>)}
                </tr>
                <tr className="bg-rose-50/40">
                  <td className="px-3 py-2 text-[10px] uppercase tracking-wider text-rose-700 font-bold">Utilisateur (anonyme)</td>
                  {columns.map((c) => <td key={c.key} className={`px-3 py-1 text-xs ${c.mono ? "font-mono" : ""} ${row.original?.[c.key] !== row.masked?.[c.key] ? "text-rose-700 font-semibold bg-rose-100" : "text-slate-700"}`}>{row.masked?.[c.key] || "—"}</td>)}
                </tr>
              </React.Fragment>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
};
