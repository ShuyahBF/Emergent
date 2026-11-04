// ============================================================================
// Lot 369 — Connexion par empreinte digitale (passkeys / WebAuthn) : réglage et suivi depuis les Paramètres.
//   - interrupteur « activée » : désactivée par défaut, le déploiement ne change RIEN tant qu'on ne l'active pas ;
//   - domaine (RP ID) : une passkey ne marche que sur le domaine où elle a été enregistrée (« sawalismartsystems.com » couvre aussi ses sous-domaines) ;
//   - comptes qui ont des passkeys (nombre, dernière connexion par empreinte) et « Révoquer » (téléphone perdu, départ d'une personne) ;
//   - jamais les clés elles-mêmes : le serveur ne garde que des clés PUBLIQUES et ne reçoit jamais l'empreinte.
// Backend : GET/PUT /api/admin/passkeys(/config), DELETE /api/admin/passkeys/user/{id}. Enregistrement par chaque personne : « Mon compte ».
// ============================================================================
import React, { useCallback, useEffect, useState } from "react";
import { Fingerprint, RefreshCw, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const dateHeure = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");

export default function PasskeysAdminSection() {
  const [etat, setEtat] = useState(null);      // null = chargement en cours
  const [actif, setActif] = useState(false);
  const [domaine, setDomaine] = useState("");
  const [enCours, setEnCours] = useState(false);

  // Lecture de l'état (réglage, domaine effectif, comptes)
  const charger = useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/passkeys");
      setEtat(r.data);
      setActif(!!r.data.enabled);
      setDomaine(r.data.rp_id_reglage || "");
    } catch (e) {
      setEtat({ erreur: e?.response?.data?.detail || "Lecture impossible", comptes: [] });
    }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  async function enregistrer() {
    setEnCours(true);
    try {
      await apiClient.put("/admin/passkeys/config", { enabled: actif, rp_id: domaine.trim() || null });
      toast.success(actif ? "Connexion par empreinte activée." : "Connexion par empreinte désactivée.");
      await charger();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Enregistrement impossible");
    } finally { setEnCours(false); }
  }

  async function revoquer(c) {
    if (!window.confirm(`Révoquer les ${c.nb} passkey(s) de ${c.nom || c.email} ? Cette personne devra se connecter avec son mot de passe, puis enregistrer de nouveau sa passkey.`)) return;
    try {
      await apiClient.delete(`/admin/passkeys/user/${encodeURIComponent(c.user_id)}`);
      toast.success("Passkeys révoquées.");
      await charger();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Révocation impossible");
    }
  }

  if (!etat) return <p className="text-sm text-slate-500">Chargement…</p>;
  return (
    <div className="space-y-4" data-testid="passkeys-admin">
      <p className="text-xs text-slate-600">
        Les personnes se connectent d'un doigt, sans mot de passe ni code : l'empreinte est vérifiée par leur appareil (lecteur d'empreintes avec Windows Hello,
        téléphone, clé de sécurité) et <b>SAWALI ne la reçoit jamais</b>. Chacune enregistre sa passkey depuis « Mon compte » après une connexion normale ; le mot de passe reste toujours possible.
        Sur un poste partagé par plusieurs personnes avec un seul compte Windows, conseillez le téléphone ou une clé de sécurité personnelle.
      </p>
      {etat.erreur && <p className="text-sm text-red-600">{etat.erreur}</p>}
      <label className="flex items-center gap-2 text-sm font-medium text-slate-700">
        <input type="checkbox" checked={actif} onChange={(e) => setActif(e.target.checked)} data-testid="passkeys-actif" />
        <Fingerprint className="h-4 w-4 text-sawali-blue" /> Connexion par empreinte digitale activée
      </label>
      <div>
        <label htmlFor="passkeys-domaine" className="block text-xs font-medium text-slate-600">Domaine des passkeys (laisser vide = automatique)</label>
        <input id="passkeys-domaine" value={domaine} onChange={(e) => setDomaine(e.target.value)} placeholder={etat.rp_id_effectif || "sawalismartsystems.com"}
               className="mt-1 w-full max-w-md rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="passkeys-domaine" />
        <p className="mt-1 text-xs text-slate-500">
          Domaine actuellement utilisé : <b>{etat.rp_id_effectif || "—"}</b>. Une passkey ne marche que sur le domaine où elle a été enregistrée : ne le changez pas une fois les passkeys en service
          (les personnes devraient les enregistrer de nouveau).
        </p>
      </div>
      <div className="boutons-distincts flex flex-wrap gap-2">
        <button type="button" onClick={enregistrer} disabled={enCours} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue px-4 py-2 text-sm font-medium text-white disabled:opacity-50" data-testid="passkeys-enregistrer">
          <Save className="h-4 w-4" /> Enregistrer
        </button>
        <button type="button" onClick={charger} className="inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-sm font-medium text-slate-700" data-testid="passkeys-actualiser">
          <RefreshCw className="h-4 w-4" /> Actualiser
        </button>
      </div>
      <div className="overflow-x-auto rounded-lg ring-1 ring-slate-200">
        <table className="tableau w-full text-sm" data-testid="passkeys-comptes">
          <thead>
            <tr className="bg-slate-50 text-left text-xs text-slate-600">
              <th className="px-3 py-2">Compte</th>
              <th className="px-3 py-2">Rôle</th>
              <th className="px-3 py-2 text-right">Passkeys</th>
              <th className="px-3 py-2">Dernière connexion par empreinte</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {etat.comptes.length === 0 ? (
              <tr><td colSpan={5} className="px-3 py-3 text-xs text-slate-500">Aucun compte n'a encore enregistré de passkey.</td></tr>
            ) : etat.comptes.map((c) => (
              <tr key={c.user_id} className="border-t border-slate-100">
                <td className="px-3 py-2"><b>{c.nom || "—"}</b><div className="text-xs text-slate-500">{c.email}</div></td>
                <td className="px-3 py-2">{c.role}</td>
                <td className="px-3 py-2 text-right tabular-nums">{c.nb}</td>
                <td className="px-3 py-2">{dateHeure(c.dernier_usage)}</td>
                <td className="px-3 py-2 text-right">
                  <button type="button" onClick={() => revoquer(c)} className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-rose-700 hover:bg-rose-50" data-testid={`passkeys-revoquer-${c.user_id}`}>
                    <Trash2 className="h-3.5 w-3.5" /> Révoquer
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
