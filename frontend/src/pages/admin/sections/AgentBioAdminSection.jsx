// ============================================================================
// Lot 370 — Agent biométrique Loois (postes partagés) : réglage et suivi depuis les Paramètres.
//   - interrupteur « activée » : désactivée par défaut, le déploiement ne change RIEN tant qu'on ne l'active pas ;
//   - AGENTS (postes) : on colle la clé publique affichée par l'agent (Réglages → « Copier la clé publique ») ; seule une attestation
//     signée par un agent enregistré est acceptée ;
//   - COMPTES LIÉS : chaque compte SAWALI est relié au nom de la personne tel qu'enrôlé dans Loois ;
//   - l'empreinte et les gabarits ne quittent jamais le poste : SAWALI ne reçoit qu'une attestation signée.
// Backend : /api/admin/agent-bio(/config|/agents|/lier|/user/{id}).
// ============================================================================
import React, { useCallback, useEffect, useState } from "react";
import { Fingerprint, Link2, RefreshCw, Save, Trash2, Plus } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const dateHeure = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");
const erreur = (e, defaut) => e?.response?.data?.detail || defaut;

export default function AgentBioAdminSection() {
  const [etat, setEtat] = useState(null);      // null = chargement en cours
  const [actif, setActif] = useState(false);
  const [nomPoste, setNomPoste] = useState("");
  const [cle, setCle] = useState("");
  const [email, setEmail] = useState("");
  const [personne, setPersonne] = useState("");
  const [enCours, setEnCours] = useState(false);

  // Lecture de l'état (réglage, agents, comptes liés)
  const charger = useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/agent-bio");
      setEtat(r.data);
      setActif(!!r.data.enabled);
    } catch (e) {
      setEtat({ erreur: erreur(e, "Lecture impossible"), agents: [], comptes: [] });
    }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  // Exécute une action d'administration puis recharge
  async function agir(action, succes) {
    setEnCours(true);
    try {
      await action();
      toast.success(succes);
      await charger();
      return true;
    } catch (e) {
      toast.error(erreur(e, "Opération impossible"));
      return false;
    } finally { setEnCours(false); }
  }

  const enregistrerReglage = () => agir(() => apiClient.put("/admin/agent-bio/config", { enabled: actif }), actif ? "Connexion par l'agent activée." : "Connexion par l'agent désactivée.");
  const ajouterAgent = async () => {
    if (await agir(() => apiClient.post("/admin/agent-bio/agents", { nom: nomPoste, cle_publique: cle }), "Agent enregistré.")) { setNomPoste(""); setCle(""); }
  };
  const retirerAgent = (a) => window.confirm(`Retirer l'agent « ${a.nom} » ? Ce poste ne pourra plus ouvrir de session par empreinte.`)
    && agir(() => apiClient.delete(`/admin/agent-bio/agents/${encodeURIComponent(a.id)}`), "Agent retiré.");
  const lierCompte = async () => {
    if (await agir(() => apiClient.post("/admin/agent-bio/lier", { email, personne }), "Compte lié.")) { setEmail(""); setPersonne(""); }
  };
  const delier = (c) => agir(() => apiClient.delete(`/admin/agent-bio/user/${encodeURIComponent(c.user_id)}`), "Lien retiré.");

  if (!etat) return <p className="text-sm text-slate-500">Chargement…</p>;
  const champ = "mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm";
  return (
    <div className="space-y-5" data-testid="agent-bio-admin">
      <p className="text-xs text-slate-600">
        Pour les <b>postes partagés</b> (accueil, laboratoire) : le programme <b>LooisBioAgent</b> du poste reconnaît la personne parmi toutes celles enrôlées dans Loois,
        puis remet à SAWALI une <b>attestation signée</b>. SAWALI ne reçoit jamais l'empreinte. Mode d'emploi : 1) lancer l'agent sur le poste et y autoriser ce site ;
        2) copier sa clé publique ici ; 3) lier chaque compte au nom de la personne dans Loois ; 4) activer. Le mot de passe reste toujours possible.
      </p>
      {etat.erreur && <p className="text-sm text-red-600">{etat.erreur}</p>}

      <label className="flex items-center gap-2 text-sm font-medium text-slate-700">
        <input type="checkbox" checked={actif} onChange={(e) => setActif(e.target.checked)} data-testid="agent-bio-actif" />
        <Fingerprint className="h-4 w-4 text-sawali-blue" /> Connexion par l'agent biométrique activée
      </label>
      <div className="boutons-distincts flex flex-wrap gap-2">
        <button type="button" onClick={enregistrerReglage} disabled={enCours} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue px-4 py-2 text-sm font-medium text-white disabled:opacity-50" data-testid="agent-bio-enregistrer">
          <Save className="h-4 w-4" /> Enregistrer
        </button>
        <button type="button" onClick={charger} className="inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-sm font-medium text-slate-700" data-testid="agent-bio-actualiser">
          <RefreshCw className="h-4 w-4" /> Actualiser
        </button>
      </div>

      {/* Agents (postes) */}
      <div>
        <h4 className="text-sm font-semibold text-slate-800">Agents enregistrés ({etat.agents.length} sur {etat.max_agents || 20})</h4>
        <div className="mt-2 overflow-x-auto rounded-lg ring-1 ring-slate-200">
          <table className="tableau w-full text-sm" data-testid="agent-bio-agents">
            <thead><tr className="bg-slate-50 text-left text-xs text-slate-600"><th className="px-3 py-2">Poste</th><th className="px-3 py-2">Identifiant</th><th className="px-3 py-2">Enregistré le</th><th className="px-3 py-2" /></tr></thead>
            <tbody>
              {etat.agents.length === 0 ? (
                <tr><td colSpan={4} className="px-3 py-3 text-xs text-slate-500">Aucun agent enregistré.</td></tr>
              ) : etat.agents.map((a) => (
                <tr key={a.id} className="border-t border-slate-100">
                  <td className="px-3 py-2 font-medium">{a.nom}</td>
                  <td className="px-3 py-2 font-mono text-xs">{a.id}</td>
                  <td className="px-3 py-2">{dateHeure(a.cree_le)}</td>
                  <td className="px-3 py-2 text-right">
                    <button type="button" onClick={() => retirerAgent(a)} className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-rose-700 hover:bg-rose-50" data-testid={`agent-bio-retirer-${a.id}`}>
                      <Trash2 className="h-3.5 w-3.5" /> Retirer
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-[14rem_1fr_auto] sm:items-end">
          <div>
            <label htmlFor="agent-bio-nom" className="block text-xs font-medium text-slate-600">Nom du poste</label>
            <input id="agent-bio-nom" value={nomPoste} onChange={(e) => setNomPoste(e.target.value)} placeholder="Accueil clinique" className={champ} data-testid="agent-bio-nom" />
          </div>
          <div>
            <label htmlFor="agent-bio-cle" className="block text-xs font-medium text-slate-600">Clé publique (agent → Réglages → « Copier la clé publique »)</label>
            <input id="agent-bio-cle" value={cle} onChange={(e) => setCle(e.target.value)} placeholder="MFkwEwYHKoZIzj0CAQYI…" className={`${champ} font-mono`} data-testid="agent-bio-cle" />
          </div>
          <button type="button" onClick={ajouterAgent} disabled={enCours || !nomPoste.trim() || !cle.trim()} className="inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-sm font-medium text-slate-700 ring-1 ring-slate-300 disabled:opacity-50" data-testid="agent-bio-ajouter">
            <Plus className="h-4 w-4" /> Ajouter
          </button>
        </div>
      </div>

      {/* Comptes liés */}
      <div>
        <h4 className="text-sm font-semibold text-slate-800">Comptes liés à une personne enrôlée dans Loois</h4>
        <div className="mt-2 overflow-x-auto rounded-lg ring-1 ring-slate-200">
          <table className="tableau w-full text-sm" data-testid="agent-bio-comptes">
            <thead><tr className="bg-slate-50 text-left text-xs text-slate-600"><th className="px-3 py-2">Compte</th><th className="px-3 py-2">Personne (Loois)</th><th className="px-3 py-2">Dernière connexion par l'agent</th><th className="px-3 py-2" /></tr></thead>
            <tbody>
              {etat.comptes.length === 0 ? (
                <tr><td colSpan={4} className="px-3 py-3 text-xs text-slate-500">Aucun compte lié.</td></tr>
              ) : etat.comptes.map((c) => (
                <tr key={c.user_id} className="border-t border-slate-100">
                  <td className="px-3 py-2"><b>{c.nom || "—"}</b><div className="text-xs text-slate-500">{c.email}</div></td>
                  <td className="px-3 py-2">{c.personne}</td>
                  <td className="px-3 py-2">{dateHeure(c.dernier_usage)}</td>
                  <td className="px-3 py-2 text-right">
                    <button type="button" onClick={() => delier(c)} className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-rose-700 hover:bg-rose-50" data-testid={`agent-bio-delier-${c.user_id}`}>
                      <Trash2 className="h-3.5 w-3.5" /> Délier
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_14rem_auto] sm:items-end">
          <div>
            <label htmlFor="agent-bio-email" className="block text-xs font-medium text-slate-600">E-mail du compte SAWALI</label>
            <input id="agent-bio-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="awa@clinique.bf" className={champ} data-testid="agent-bio-email" />
          </div>
          <div>
            <label htmlFor="agent-bio-personne" className="block text-xs font-medium text-slate-600">Nom de la personne dans Loois</label>
            <input id="agent-bio-personne" value={personne} onChange={(e) => setPersonne(e.target.value)} placeholder="Awa" className={champ} data-testid="agent-bio-personne" />
          </div>
          <button type="button" onClick={lierCompte} disabled={enCours || !email.trim() || !personne.trim()} className="inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-sm font-medium text-slate-700 ring-1 ring-slate-300 disabled:opacity-50" data-testid="agent-bio-lier">
            <Link2 className="h-4 w-4" /> Lier
          </button>
        </div>
      </div>
    </div>
  );
}
