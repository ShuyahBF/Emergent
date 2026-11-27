// ============================================================================
// ConnexionsRapidesBloc.jsx — Lot 484 : connexions rapides de « Loois mobile » (biométrie, compte Google, clé d'accès).
// Présenté dans la rubrique « 📱 Appareils Android — Loois mobile » : état (Google configuré ? domaine des clés d'accès), liste des liaisons,
// bouton « Révoquer » (l'utilisateur devra se reconnecter par mot de passe). Aucun secret n'est jamais affiché (SAWALI ne garde que l'empreinte du secret biométrique).
// ============================================================================
import React, { useState } from "react";
import { Fingerprint, KeyRound, Mail, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { useTri } from "@/lib/tri";
import ThTri from "@/components/ThTri";

const METHODES = { biometrie: { texte: "Biométrie", Icone: Fingerprint }, google: { texte: "Compte Google", Icone: Mail }, cle: { texte: "Clé d'accès", Icone: KeyRound } };
const quand = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");

export default function ConnexionsRapidesBloc() {
  const [etat, setEtat] = useState(null);
  const [enCours, setEnCours] = useState(false);
  const lignes = (etat?.liaisons || []).map((l) => ({ ...l, methode_txt: METHODES[l.methode]?.texte || l.methode }));
  const { lignes: lignesTriees, tri, basculer } = useTri(lignes, { methode_txt: (l) => l.methode_txt, login: (l) => l.login, zone: (l) => l.zone, detail: (l) => l.detail, cree_le: (l) => l.cree_le, dernier_usage: (l) => l.dernier_usage });

  const charger = async (avecToast) => {
    setEnCours(true);
    if (avecToast) toast.info("Actualisation des connexions rapides en cours…");
    try { const r = await apiClient.get("/admin/android-rapide"); setEtat(r.data); if (avecToast) toast.success(`${(r.data.liaisons || []).length} connexion(s) rapide(s).`); }
    catch (e) { toast.error(e?.response?.data?.detail || "Lecture impossible."); }
    finally { setEnCours(false); }
  };
  const revoquer = async (l) => {
    if (!window.confirm(`Révoquer la connexion rapide « ${METHODES[l.methode]?.texte} » de ${l.login} (zone ${l.zone}) ? Il devra se reconnecter par mot de passe.`)) return;
    try { await apiClient.delete(`/admin/android-rapide/${l.id}`); toast.success("Connexion rapide révoquée."); charger(false); }
    catch (e) { toast.error(e?.response?.data?.detail || "Révocation impossible."); }
  };

  return (
    <details className="rounded-lg border border-slate-200 p-3" onToggle={(e) => { if (e.currentTarget.open && etat === null) charger(false); }} data-testid="connexions-rapides">
      <summary className="cursor-pointer font-semibold text-slate-800">Connexions rapides (biométrie, compte Google, clé d'accès)</summary>
      <div className="mt-2 space-y-2">
        <p className="text-xs text-slate-600">Après une première connexion par mot de passe, l'utilisateur peut activer l'une de ces méthodes dans Loois mobile (Paramètres). Le mot de passe n'est jamais gardé ; l'identifiant est revérifié chez le client à chaque connexion rapide.</p>
        <button type="button" onClick={() => charger(true)} disabled={enCours} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1.5 text-sm font-semibold"><RefreshCw className="h-4 w-4" /> Actualiser</button>
        {etat && (
          <ul className="space-y-1 text-sm" data-testid="rapide-etat">
            <li>{etat.google_configure ? "✅ Compte Google : configuré (même client Google que Google Agenda)." : "⚠️ Compte Google : non configuré — saisissez l'identifiant client Google dans la rubrique « Connexion par compte Google »."}</li>
            <li>Clés d'accès : domaine <b>{etat.rp_id}</b> ; fichier de liaison à l'application : <code>/.well-known/assetlinks.json</code>.</li>
            <li className="text-xs text-slate-500">Côté Google Cloud : créer un client OAuth « Android » (package <code>bf.sawali.loois.mobile</code>, empreinte SHA-1 du certificat ShuyahStore) dans le même projet que le client web.</li>
          </ul>)}
        {etat && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left"><ThTri cle="methode_txt" tri={tri} onTri={basculer}>Méthode</ThTri><ThTri cle="login" tri={tri} onTri={basculer}>Identifiant</ThTri><ThTri cle="zone" tri={tri} onTri={basculer}>Zone</ThTri><ThTri cle="detail" tri={tri} onTri={basculer}>Détail</ThTri><ThTri cle="cree_le" tri={tri} onTri={basculer}>Activée le</ThTri><ThTri cle="dernier_usage" tri={tri} onTri={basculer}>Dernier usage</ThTri><th className="p-2">Action</th></tr></thead>
              <tbody>
                {lignesTriees.map((l) => {
                  const Ic = METHODES[l.methode]?.Icone || KeyRound;
                  return (
                    <tr key={l.id} className="border-t">
                      <td className="p-2"><span className="inline-flex items-center gap-1 font-semibold text-sky-800"><Ic className="h-4 w-4" />{l.methode_txt}</span></td>
                      <td className="p-2 font-semibold">{l.login}</td><td className="p-2">{l.zone}</td><td className="p-2">{l.detail || "—"}</td>
                      <td className="p-2">{quand(l.cree_le)}</td><td className="p-2">{quand(l.dernier_usage)}</td>
                      <td className="p-2"><button type="button" onClick={() => revoquer(l)} aria-label={`Révoquer ${l.methode_txt} de ${l.login}`} title="Révoquer" className="inline-flex items-center gap-1 rounded-full border border-red-300 px-2 py-1 text-red-800"><Trash2 className="h-4 w-4" /> Révoquer</button></td>
                    </tr>);
                })}
                {lignesTriees.length === 0 && <tr><td colSpan={7} className="p-3 text-slate-500">Aucune connexion rapide activée pour l'instant.</td></tr>}
              </tbody>
            </table>
          </div>)}
      </div>
    </details>
  );
}
