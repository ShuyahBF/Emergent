// Iter40 (2026-02) — ACL Liluvine PRO par module (RAG métier).
// Permet à l'admin de saisir, par module (RDV, Tickets, HR, Caisse, Paiements,
// Contacts), la liste des numéros de téléphone autorisés à interroger ce
// module depuis WhatsApp. Le matching est sur les 9 derniers chiffres.
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Loader2, Save, ShieldCheck, Phone } from "lucide-react";

const MODULES = [
  { key: "rdv", label: "RDV (rendez-vous)", hint: "Liste prochains RDV du tenant" },
  { key: "tickets", label: "Tickets (incidents)", hint: "Tickets actifs + !ticket pour ouvrir" },
  { key: "hr", label: "RH (employé)", hint: "Absences/avances/paie de l'employé identifié par téléphone" },
  { key: "caisse", label: "Caisse", hint: "Total caisse du jour (tenant)" },
  { key: "payments", label: "Paiements", hint: "10 derniers paiements du tenant" },
  { key: "contacts", label: "Contacts", hint: "Recherche contact par nom" },
];

function parsePhones(raw) {
  if (!raw) return [];
  return raw
    .split(/[\s,;\n]+/)
    .map((p) => p.replace(/\D+/g, ""))
    .filter((p) => p.length >= 6);
}

export default function LiluvineModuleAclSection() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [acl, setAcl] = useState({});
  const [textValues, setTextValues] = useState({});

  const load = async () => {
    try {
      setLoading(true);
      const r = await apiClient.get("/admin/liluvine-pro/module-acl");
      const next = r.data?.acl || {};
      setAcl(next);
      const tv = {};
      for (const m of MODULES) {
        tv[m.key] = (next[m.key] || []).join("\n");
      }
      setTextValues(tv);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur chargement ACL");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const save = async () => {
    try {
      setSaving(true);
      const cleaned = {};
      for (const m of MODULES) {
        cleaned[m.key] = parsePhones(textValues[m.key] || "");
      }
      const r = await apiClient.put("/admin/liluvine-pro/module-acl", { acl: cleaned });
      setAcl(r.data?.acl || cleaned);
      toast.success("ACL Liluvine enregistrée");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur enregistrement");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-600 py-4">
        <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
      </div>
    );
  }

  return (
    <div className="space-y-3" data-testid="liluvine-module-acl-section">
      <p className="text-xs text-slate-600">
        Pour chaque module métier, déclarez les numéros de téléphone autorisés à
        interroger ce module via WhatsApp (un par ligne, ou séparés par virgules).
        Le matching se fait sur les 9 derniers chiffres (le code pays est ignoré).
      </p>
      <div className="grid md:grid-cols-2 gap-3">
        {MODULES.map((m) => (
          <div key={m.key} className="rounded-lg ring-1 ring-slate-200 bg-white p-3" data-testid={`acl-module-${m.key}`}>
            <div className="flex items-center justify-between mb-1">
              <h4 className="text-sm font-semibold text-slate-800 inline-flex items-center gap-1.5">
                <ShieldCheck className="h-3.5 w-3.5 text-fuchsia-600" />
                {m.label}
              </h4>
              <span className="text-[10px] text-slate-500">
                {parsePhones(textValues[m.key] || "").length} num.
              </span>
            </div>
            <p className="text-[11px] text-slate-500 mb-2 italic">{m.hint}</p>
            <textarea
              value={textValues[m.key] || ""}
              onChange={(e) => setTextValues((s) => ({ ...s, [m.key]: e.target.value }))}
              placeholder="+228 90 12 34 56&#10;+221 77 222 33 44"
              rows={3}
              className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono"
              data-testid={`acl-input-${m.key}`}
            />
          </div>
        ))}
      </div>
      <div className="flex justify-end pt-2">
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="inline-flex items-center gap-2 text-sm px-4 py-2 rounded-lg bg-fuchsia-600 hover:bg-fuchsia-700 text-white disabled:opacity-60"
          data-testid="liluvine-acl-save"
        >
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          Enregistrer
        </button>
      </div>
      <details className="text-[11px] text-slate-500 pt-2">
        <summary className="cursor-pointer hover:text-slate-700 inline-flex items-center gap-1">
          <Phone className="h-3 w-3" /> Commandes WhatsApp disponibles
        </summary>
        <ul className="list-disc list-inside mt-1 space-y-0.5 pl-2">
          <li><code>!absence YYYY-MM-DD [au YYYY-MM-DD] [motif]</code> — Demande d'absence (désactive le portail jusqu'à validation).</li>
          <li><code>!avance MONTANT [motif]</code> — Demande d'avance sur salaire.</li>
          <li><code>!ticket &lt;description&gt;</code> — Ouvre un ticket support (ACL « tickets »).</li>
        </ul>
      </details>
    </div>
  );
}
