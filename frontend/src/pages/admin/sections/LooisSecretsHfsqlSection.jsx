// LooisSecretsHfsqlSection.jsx — Lot 79.11 : rubrique « 🔐 Loois — mots de passe HFSQL » des Paramètres.
//
// Le mot de passe du SERVEUR HFSQL et celui des FICHIERS sont saisis UNE fois ici. SAWALI les garde chiffrés et les
// remet à Loois (avec sa clé client) qui les stocke chiffrés sur le poste : plus aucun mot de passe en clair.
// L'écran n'affiche JAMAIS les mots de passe enregistrés : seulement « défini / non défini ». Champ laissé vide = inchangé.
import React, { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import PasswordInput from "@/components/PasswordInput";

export default function LooisSecretsHfsqlSection() {
  const [etat, setEtat] = useState(null);
  const [serveur, setServeur] = useState("");
  const [fichiers, setFichiers] = useState("");
  const [message, setMessage] = useState("");
  const [enCours, setEnCours] = useState(false);

  // Lecture de l'état (défini / non défini, dernières remises)
  const charger = useCallback(() => {
    apiClient.get("/admin/loois-secrets-hfsql").then((r) => setEtat(r.data)).catch(() => setEtat({ erreur: true }));
  }, []);
  useEffect(() => { charger(); }, [charger]);

  // Enregistrement : seuls les champs saisis sont envoyés (vide = inchangé), ou un effacement explicite
  const enregistrer = async (extra = {}) => {
    setEnCours(true);
    setMessage("");
    try {
      const r = await apiClient.put("/admin/loois-secrets-hfsql", {
        mot_de_passe_serveur: serveur, mot_de_passe_fichiers: fichiers, ...extra,
      });
      setEtat(r.data);
      setServeur("");
      setFichiers("");
      setMessage("✅ Enregistré (chiffré). Les postes Loois le recevront à leur prochain besoin.");
    } catch (e) {
      setMessage(e?.response?.data?.detail || "Enregistrement impossible");
    } finally {
      setEnCours(false);
    }
  };

  if (!etat) return <p className="text-sm text-slate-500">Patientez…</p>;
  if (etat.erreur) return <p className="text-sm text-red-700">État indisponible.</p>;

  // Pastille « défini / non défini »
  const Pastille = ({ ok }) => (
    <span className={`ml-2 rounded-full px-2 py-0.5 text-[11px] font-semibold ${ok ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-800"}`}>
      {ok ? "défini" : "non défini"}
    </span>
  );

  return (
    <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-loois-secrets-hfsql">
      <p className="text-xs text-slate-600">
        Saisis une seule fois, ces mots de passe sont <b>chiffrés</b> par SAWALI, puis remis à Loois avec sa <b>clé client</b>
        (jamais la clé commune). Loois les garde chiffrés sur le poste : plus besoin de fichier ni de variable en clair.
        Ils ne sont jamais réaffichés ici ; laissez un champ vide pour ne pas le changer.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-xs">
          <span className="font-semibold text-slate-700">Mot de passe du serveur HFSQL (utilisateur admin)</span>
          <Pastille ok={etat.serveur_defini} />
          <PasswordInput value={serveur} onChange={(e) => setServeur(e.target.value)} autoComplete="new-password"
            placeholder={etat.serveur_defini ? "•••••••• (inchangé)" : "à saisir"} testid="loois-mdp-serveur"
            className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
        </label>
        <label className="block text-xs">
          <span className="font-semibold text-slate-700">Mot de passe des fichiers HFSQL</span>
          <Pastille ok={etat.fichiers_defini} />
          <PasswordInput value={fichiers} onChange={(e) => setFichiers(e.target.value)} autoComplete="new-password"
            placeholder={etat.fichiers_defini ? "•••••••• (inchangé)" : "à saisir"} testid="loois-mdp-fichiers"
            className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" disabled={enCours || (!serveur && !fichiers)} onClick={() => enregistrer()}
          className="rounded-lg bg-sky-700 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50" data-testid="loois-mdp-enregistrer">
          {enCours ? "Patientez…" : "Enregistrer"}
        </button>
        {etat.serveur_defini && (
          <button type="button" disabled={enCours} onClick={() => window.confirm("Effacer le mot de passe du serveur HFSQL ?") && enregistrer({ effacer_serveur: true })}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs hover:bg-slate-50">Effacer « serveur »</button>
        )}
        {etat.fichiers_defini && (
          <button type="button" disabled={enCours} onClick={() => window.confirm("Effacer le mot de passe des fichiers HFSQL ?") && enregistrer({ effacer_fichiers: true })}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs hover:bg-slate-50">Effacer « fichiers »</button>
        )}
        {message && <span className="text-xs text-slate-700">{message}</span>}
      </div>
      {etat.maj_le && (
        <p className="text-[11px] text-slate-500">Modifié le {new Date(etat.maj_le).toLocaleString("fr-FR")} par {etat.maj_par || "—"}.</p>
      )}
      {/* Dernières remises à des postes Loois (client, machine, date) — sans aucun mot de passe */}
      <div>
        <p className="text-xs font-semibold text-slate-700">Dernières remises aux postes Loois</p>
        {etat.livraisons.length === 0 ? (
          <p className="text-xs text-slate-500">Aucune remise pour l'instant.</p>
        ) : (
          <table className="mt-1 w-full text-xs">
            <thead><tr className="text-left text-slate-500"><th className="py-1">Date</th><th>Client</th><th>Machine</th></tr></thead>
            <tbody>
              {etat.livraisons.slice(0, 10).map((l, i) => (
                <tr key={i} className="border-t border-slate-100">
                  <td className="py-1">{new Date(l.le).toLocaleString("fr-FR")}</td><td>{l.client}</td><td>{l.machine || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
