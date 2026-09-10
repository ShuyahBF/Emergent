// Agents Liluvine — signature nominative des réponses auto-WhatsApp.
// Jusqu'à 5 agents (prénom + rôle/spécialité, 100% paramétrable). Quand
// l'IA répond à un message libre (jamais une commande `!...`), l'agent dont
// la spécialité correspond au contenu du message signe la réponse à sa place.
import React, { useEffect, useState } from "react";
import { apiClient } from "../../lib/api";
import { toast } from "sonner";

const MAX_AGENTS = 5;

export default function LiluvineAgentsSection() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [agents, setAgents] = useState([]);

  const reload = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/liluvine/agents");
      setAgents(r.data?.agents || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Chargement des agents impossible");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const updateAgent = (idx, patch) => {
    setAgents((prev) => prev.map((a, i) => (i === idx ? { ...a, ...patch } : a)));
  };

  const addAgent = () => {
    if (agents.length >= MAX_AGENTS) {
      toast.error(`Maximum ${MAX_AGENTS} agents`);
      return;
    }
    setAgents((prev) => [...prev, { prenom: "", specialite: "" }]);
  };

  const removeAgent = (idx) => {
    setAgents((prev) => prev.filter((_, i) => i !== idx));
  };

  const save = async () => {
    const cleaned = agents.filter((a) => (a.prenom || "").trim() && (a.specialite || "").trim());
    setSaving(true);
    try {
      const r = await apiClient.put("/admin/liluvine/agents", { agents: cleaned });
      toast.success(`${r.data?.count ?? cleaned.length} agent(s) enregistré(s)`);
      setAgents(cleaned);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Sauvegarde impossible");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <p className="text-sm text-slate-500 italic">Chargement…</p>;
  }

  return (
    <div className="space-y-4" data-testid="liluvine-agents-section">
      <div className="text-sm text-slate-700 bg-sky-50 ring-1 ring-sky-200 p-3 rounded leading-relaxed">
        <p className="font-semibold mb-1">🧑‍💼 Agents Liluvine (signature des réponses)</p>
        <p className="text-xs">
          Jusqu&apos;à {MAX_AGENTS} agents. Quand un message <strong>libre</strong> (pas une commande{" "}
          <code className="bg-sky-100 px-1 rounded">!...</code>) reçoit une réponse automatique, l&apos;agent dont
          la spécialité correspond le mieux au contenu du message la signe — même si c&apos;est l&apos;IA qui a
          rédigé le texte. Ex. une question de prix sur un produit sera signée par l&apos;agent
          « Commercial ».
        </p>
      </div>

      <div className="space-y-2 max-w-xl">
        {agents.map((a, idx) => (
          <div key={idx} className="flex items-center gap-2 p-2 rounded ring-1 ring-slate-200" data-testid={`liluvine-agent-${idx}`}>
            <input
              type="text"
              placeholder="Prénom (ex : Awa)"
              value={a.prenom || ""}
              onChange={(e) => updateAgent(idx, { prenom: e.target.value })}
              className="w-36 px-2 py-1 rounded ring-1 ring-slate-300 text-sm"
              data-testid={`liluvine-agent-${idx}-prenom`}
            />
            <input
              type="text"
              placeholder="Rôle / spécialité (ex : Secrétaire)"
              value={a.specialite || ""}
              onChange={(e) => updateAgent(idx, { specialite: e.target.value })}
              className="flex-1 px-2 py-1 rounded ring-1 ring-slate-300 text-sm"
              data-testid={`liluvine-agent-${idx}-specialite`}
            />
            <button
              type="button"
              onClick={() => removeAgent(idx)}
              className="text-xs text-rose-600 hover:text-rose-800 px-1.5 py-0.5 rounded hover:bg-rose-100"
              data-testid={`liluvine-agent-${idx}-remove`}
            >
              🗑
            </button>
          </div>
        ))}
        {agents.length === 0 && (
          <p className="text-xs italic text-slate-400">Aucun agent configuré — la signature générique par défaut reste utilisée.</p>
        )}
      </div>

      <div className="flex items-center gap-2 pt-2 border-t border-slate-200">
        <button
          type="button"
          onClick={addAgent}
          disabled={agents.length >= MAX_AGENTS}
          className="text-xs px-3 py-1.5 rounded bg-slate-100 hover:bg-slate-200 ring-1 ring-slate-300 disabled:opacity-50"
          data-testid="liluvine-agents-add"
        >
          ➕ Ajouter un agent ({agents.length}/{MAX_AGENTS})
        </button>
        <div className="flex-1" />
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="text-sm px-4 py-1.5 rounded bg-sky-600 hover:bg-sky-700 text-white font-semibold disabled:opacity-50"
          data-testid="liluvine-agents-save"
        >
          {saving ? "Enregistrement…" : "💾 Enregistrer les agents"}
        </button>
      </div>
    </div>
  );
}
