// DecouverteReseauSection.jsx — Lot 80 : rubrique « 🛰️ Équipements — découverte du réseau » des Paramètres.
//
// Réglages de la découverte du réseau des clients par Loois : activée ou non, heure du balayage quotidien,
// machines autorisées (vide = les Windows Server qui ont Loois), jours d'absence avant alerte, communauté SNMP
// (lecture seule, « public » par défaut ; gardée CHIFFRÉE et jamais réaffichée). État : derniers balayages,
// appareils à valider, bouton « Lancer maintenant » et lien vers l'écran Équipements → Découverte du réseau.
import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "@/lib/api";
import PasswordInput from "@/components/PasswordInput";

export default function DecouverteReseauSection() {
  const [etat, setEtat] = useState(null);
  const [form, setForm] = useState(null);
  const [communaute, setCommunaute] = useState("");
  const [message, setMessage] = useState("");
  const [enCours, setEnCours] = useState(false);

  // Lecture des réglages et de l'état ; le formulaire reprend les valeurs enregistrées
  const charger = useCallback(() => {
    apiClient.get("/admin/equipements/decouverte-reglages").then((r) => {
      setEtat(r.data);
      setForm({ actif: r.data.actif, heure: r.data.heure, jours_absence: r.data.jours_absence, postes: (r.data.postes || []).join(", ") });
    }).catch(() => setEtat({ erreur: true }));
  }, []);
  useEffect(() => { charger(); }, [charger]);

  // Enregistrement (communauté vide = inchangée) ou demande de balayage immédiat
  const envoyer = async (requete, ok) => {
    setEnCours(true);
    setMessage("");
    try {
      const r = await requete();
      setEtat(r.data);
      setCommunaute("");
      setMessage(ok);
    } catch (e) {
      setMessage(e?.response?.data?.detail || "Action impossible");
    } finally {
      setEnCours(false);
    }
  };
  const enregistrer = (extra = {}) => envoyer(
    () => apiClient.put("/admin/equipements/decouverte-reglages", { ...form, communaute, ...extra }),
    "✅ Réglages enregistrés.");
  const lancer = () => envoyer(() => apiClient.post("/admin/equipements/decouverte-lancer"),
    "✅ Demande envoyée : les postes autorisés balaieront le réseau d'ici 15 minutes.");

  if (!etat) return <p className="text-sm text-slate-500">Patientez…</p>;
  if (etat.erreur) return <p className="text-sm text-red-700">État indisponible.</p>;
  const date = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR") : "—");

  return (
    <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-decouverte-reseau">
      <p className="text-xs text-slate-600">
        Loois balaie chaque jour le réseau local du client (ping, table ARP, nom d'hôte, <b>SNMP en lecture seule</b>) et
        envoie la liste à SAWALI. Les appareils inconnus du Parc informatique arrivent <b>« À valider »</b> : rien n'entre dans
        le parc sans votre accord. Seule une <b>clé client</b> Loois est acceptée.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={!!form.actif} onChange={(e) => setForm({ ...form, actif: e.target.checked })} />
          Découverte du réseau activée
        </label>
        <label className="block text-xs">
          <span className="font-semibold text-slate-700">Heure du balayage quotidien (heure du Burkina)</span>
          <input type="time" value={form.heure || "02:30"} onChange={(e) => setForm({ ...form, heure: e.target.value })}
            className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
        </label>
        <label className="block text-xs">
          <span className="font-semibold text-slate-700">Machines autorisées à balayer (séparées par des virgules)</span>
          <input value={form.postes} onChange={(e) => setForm({ ...form, postes: e.target.value })} placeholder="vide = les Windows Server qui ont Loois"
            className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
        </label>
        <label className="block text-xs">
          <span className="font-semibold text-slate-700">Alerte si un appareil du parc n'est plus vu depuis (jours)</span>
          <input type="number" min={1} max={365} value={form.jours_absence || 7} onChange={(e) => setForm({ ...form, jours_absence: e.target.value })}
            className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
        </label>
        <label className="block text-xs sm:col-span-2">
          <span className="font-semibold text-slate-700">Communauté SNMP (lecture seule)</span>
          <span className={`ml-2 rounded-full px-2 py-0.5 text-[11px] font-semibold ${etat.communaute_personnalisee ? "bg-emerald-50 text-emerald-800" : "bg-slate-100 text-slate-700"}`}>
            {etat.communaute_personnalisee ? "personnalisée" : "« public » (par défaut)"}
          </span>
          <PasswordInput value={communaute} onChange={(e) => setCommunaute(e.target.value)} autoComplete="new-password"
            placeholder={etat.communaute_personnalisee ? "•••••••• (inchangée)" : "laisser vide pour garder « public »"} testid="decouverte-communaute"
            className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" disabled={enCours} onClick={() => enregistrer()} className="rounded-lg bg-sky-700 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50">
          {enCours ? "Patientez…" : "Enregistrer"}
        </button>
        {etat.communaute_personnalisee && (
          <button type="button" disabled={enCours} onClick={() => enregistrer({ communaute_par_defaut: true })}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs hover:bg-slate-50">Revenir à « public »</button>
        )}
        <button type="button" disabled={enCours} onClick={lancer} className="rounded-lg border border-sky-700 px-3 py-1.5 text-sm text-sky-800 hover:bg-sky-50">
          Lancer une découverte maintenant
        </button>
        <Link to="/admin/decouverte-reseau" className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">
          Ouvrir Équipements → Découverte du réseau {etat.a_valider > 0 && <b className="ml-1 text-amber-700">({etat.a_valider} à valider)</b>}
        </Link>
        {message && <span className="text-xs text-slate-700">{message}</span>}
      </div>
      <div>
        <p className="text-xs font-semibold text-slate-700">Derniers balayages</p>
        {etat.derniers_balayages.length === 0 ? (
          <p className="text-xs text-slate-500">Aucun balayage reçu pour l'instant (il faut la nouvelle version de Loois sur un serveur du client).</p>
        ) : (
          <table className="mt-1 w-full text-xs">
            <thead><tr className="text-left text-slate-500"><th className="py-1">Date</th><th>Client</th><th>Machine</th><th>Appareils</th><th>Nouveaux</th></tr></thead>
            <tbody>
              {etat.derniers_balayages.map((b) => (
                <tr key={b.id} className="border-t border-slate-100">
                  <td className="py-1">{date(b.recu_le)}</td><td>{b.client_libelle || b.client_code}</td><td>{b.machine}</td><td>{b.total}</td><td>{b.nouveaux}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {etat.demande_le && <p className="text-[11px] text-slate-500">Dernière demande « Lancer maintenant » : {date(etat.demande_le)}.</p>}
    </div>
  );
}
