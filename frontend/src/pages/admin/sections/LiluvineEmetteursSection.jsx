/*
  Lot 57.4 — « Transmission WA Universelle Liluvine » : plateformes émettrices.

  Chaque plateforme (Ster, adLyn, ALBARKA, beAuthentik…) a SA PROPRE clé HMAC :
  - « Ajouter » crée l'émetteur et affiche sa clé UNE SEULE FOIS (à copier dans
    la variable LILUVINE_WA_HMAC de la plateforme, sur Render) ;
  - « Regénérer » remplace la clé (l'ancienne cesse aussitôt de fonctionner) ;
  - « Activer / Désactiver » coupe une plateforme sans toucher aux autres ;
  - quota d'envois par jour, envois du jour et dernier envoi ;
  - journal des 50 dernières transmissions (le texte des messages n'est jamais conservé).
  Lot 57.5 : nombre d'émetteurs illimité ; « URL de retour » par plateforme (réponses
  des clients, statuts remis/lu, désinscriptions STOP) ; listes des réponses relayées
  et des numéros désinscrits (avec réinscription).
*/
import React, { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Copy, KeyRound, Plus, RefreshCw, Trash2 } from "lucide-react";

// Date/heure lisible en français
const fmt = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");

// Message d'erreur lisible renvoyé par le serveur
const erreur = (e) => e?.response?.data?.detail || e?.message || "Erreur";

export default function LiluvineEmetteursSection() {
  const [emetteurs, setEmetteurs] = useState([]);
  const [journal, setJournal] = useState([]);
  const [reponses, setReponses] = useState([]);           // réponses de clients relayées
  const [desinscriptions, setDesinscriptions] = useState([]); // numéros STOP
  const [nouveau, setNouveau] = useState({ code: "", nom: "", quota_jour: 500, url_retour: "" });
  const [cleAffichee, setCleAffichee] = useState(null); // {code, cle} : affichée une seule fois
  const [selection, setSelection] = useState(null);     // ligne sélectionnée (règle 3 des tableaux)

  // Chargement des émetteurs et du journal
  const charger = useCallback(async () => {
    try {
      const [a, b, c, d] = await Promise.all([
        apiClient.get("/admin/liluvine-emetteurs"),
        apiClient.get("/admin/liluvine-transmissions", { params: { limite: 50 } }),
        apiClient.get("/admin/liluvine-reponses"),
        apiClient.get("/admin/liluvine-desinscriptions"),
      ]);
      setEmetteurs(a.data.emetteurs || []);
      setJournal(b.data.transmissions || []);
      setReponses(c.data.reponses || []);
      setDesinscriptions(d.data.desinscriptions || []);
    } catch (e) {
      toast.error(erreur(e));
    }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  // Création d'un émetteur : la clé revient une seule fois
  const ajouter = async () => {
    try {
      const { data } = await apiClient.post("/admin/liluvine-emetteurs", nouveau);
      setCleAffichee(data);
      setNouveau({ code: "", nom: "", quota_jour: 500, url_retour: "" });
      charger();
    } catch (e) {
      toast.error(erreur(e));
    }
  };

  // Nouvelle clé pour un émetteur (confirmation : l'ancienne clé est invalidée)
  const regenerer = async (code) => {
    if (!window.confirm(`Regénérer la clé de « ${code} » ? L'ancienne cessera aussitôt de fonctionner.`)) return;
    try {
      const { data } = await apiClient.post(`/admin/liluvine-emetteurs/${code}/regenerer`);
      setCleAffichee(data);
      charger();
    } catch (e) {
      toast.error(erreur(e));
    }
  };

  // Activation / désactivation et quota
  const modifier = async (code, changements) => {
    try {
      await apiClient.patch(`/admin/liluvine-emetteurs/${code}`, changements);
      // Lot 64.8 — confirmation visible : la saisie est enregistrée dès la sortie du champ
      toast.success(`« ${code} » enregistré`);
      charger();
    } catch (e) {
      toast.error(erreur(e));
    }
  };

  // Réinscription manuelle d'un numéro désinscrit (STOP)
  const reinscrire = async (emetteur, numero) => {
    try {
      await apiClient.post("/admin/liluvine-desinscriptions/reinscrire", { emetteur, numero });
      charger();
    } catch (e) {
      toast.error(erreur(e));
    }
  };

  const supprimer = async (code) => {
    if (!window.confirm(`Supprimer l'émetteur « ${code} » ?`)) return;
    try {
      await apiClient.delete(`/admin/liluvine-emetteurs/${code}`);
      charger();
    } catch (e) {
      toast.error(erreur(e));
    }
  };

  // Copie de la clé affichée
  const copier = async () => {
    try {
      await navigator.clipboard.writeText(cleAffichee.cle);
      toast.success("Clé copiée");
    } catch {
      toast.error("Copie impossible : sélectionnez la clé et copiez-la à la main");
    }
  };

  return (
    <div className="space-y-4" data-testid="liluvine-emetteurs">
      <p className="text-xs text-slate-500">
        Une clé par plateforme. Sur Render, dans le service backend de la plateforme, renseigner
        <code className="mx-1">LILUVINE_WA_URL</code>(adresse de ce webhook),
        <code className="mx-1">LILUVINE_WA_EMETTEUR</code>(le code ci-dessous) et
        <code className="mx-1">LILUVINE_WA_HMAC</code>(la clé).
      </p>

      {/* Clé affichée une seule fois, juste après création / régénération */}
      {cleAffichee && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs" data-testid="liluvine-cle-affichee">
          <div className="font-semibold text-amber-900">
            Clé de « {cleAffichee.code} » — affichée une seule fois : copiez-la maintenant dans LILUVINE_WA_HMAC.
          </div>
          <div className="mt-2 flex items-center gap-2">
            <input readOnly value={cleAffichee.cle} onClick={(e) => e.target.select()}
                   className="flex-1 rounded border border-amber-300 bg-white px-2 py-1 font-mono text-[11px]" />
            <button type="button" onClick={copier} className="inline-flex items-center gap-1 rounded bg-slate-900 px-2 py-1 text-white">
              <Copy className="h-3.5 w-3.5" /> Copier
            </button>
            <button type="button" onClick={() => setCleAffichee(null)} className="rounded px-2 py-1 ring-1 ring-slate-300">J'ai copié</button>
          </div>
        </div>
      )}

      {/* Ajout d'une plateforme émettrice */}
      <div className="grid grid-cols-1 gap-2 md:grid-cols-5 items-end">
        <label className="text-xs font-semibold">Code
          <input value={nouveau.code} onChange={(e) => setNouveau({ ...nouveau, code: e.target.value })}
                 placeholder="ster" className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal" />
        </label>
        <label className="text-xs font-semibold">Nom affiché au destinataire
          <input value={nouveau.nom} onChange={(e) => setNouveau({ ...nouveau, nom: e.target.value })}
                 placeholder="Ster" className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal" />
        </label>
        <label className="text-xs font-semibold">Quota / jour
          <input type="number" min="1" value={nouveau.quota_jour}
                 onChange={(e) => setNouveau({ ...nouveau, quota_jour: Number(e.target.value) })}
                 className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal" />
        </label>
        <label className="text-xs font-semibold">URL de retour (facultatif)
          <input value={nouveau.url_retour} onChange={(e) => setNouveau({ ...nouveau, url_retour: e.target.value })}
                 placeholder="https://…/api/webhooks/liluvine-retour" className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal" />
        </label>
        <button type="button" onClick={ajouter} disabled={!nouveau.code || !nouveau.nom}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40"
                data-testid="liluvine-emetteur-ajouter">
          <Plus className="h-3.5 w-3.5" /> Ajouter (génère la clé)
        </button>
      </div>

      {/* Plateformes émettrices */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-slate-500">
              <th className="py-1 pr-2">Code</th><th className="pr-2">Nom</th><th className="pr-2">État</th>
              <th className="pr-2">Quota / jour</th><th className="pr-2">Envois du jour</th>
              <th className="pr-2">Dernier envoi</th><th className="pr-2">Clé générée le</th>
              <th className="pr-2">Réponses des clients</th>
              <th className="pr-2">URL de retour</th><th className="pr-2">URL des statistiques</th>
              <th className="pr-2" title="Liluvine pose à la plateforme les questions de ses clients (statut de commande, produit…). Lot 103 : la commande « !code » (ex. « !zandgo où est ma commande ? », casse indifférente) la joint à tout moment ; conversation de 30 min, « FIN » rend la main à Liluvine.">Adresse de l'assistant</th><th></th>
            </tr>
          </thead>
          <tbody>
            {emetteurs.map((e) => (
              <tr key={e.code} onClick={() => setSelection(e.code)} aria-selected={selection === e.code ? "true" : "false"}
                  className="border-t border-slate-100">
                <td className="py-1 pr-2 font-mono">{e.code}</td>
                <td className="pr-2">{e.nom}</td>
                <td className="pr-2">
                  <button type="button" onClick={(ev) => { ev.stopPropagation(); modifier(e.code, { actif: !e.actif }); }}
                          className={`rounded px-2 py-0.5 font-semibold ${e.actif ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-800"}`}>
                    {e.actif ? "Actif" : "Désactivé"}
                  </button>
                </td>
                <td className="pr-2">
                  <input type="number" min="1" defaultValue={e.quota_jour} onClick={(ev) => ev.stopPropagation()}
                         onBlur={(ev) => Number(ev.target.value) !== e.quota_jour && modifier(e.code, { quota_jour: Number(ev.target.value) })}
                         className="w-20 rounded border border-slate-300 px-1 py-0.5" />
                </td>
                <td className="pr-2">{e.envois_du_jour}</td>
                <td className="pr-2">{fmt(e.dernier_envoi)}</td>
                <td className="pr-2">{fmt(e.cle_regeneree_le)}</td>
                <td className="pr-2">
                  {/* Lot 84 : réponses faites avec « Répondre » sur un message de la plateforme — transmises ou gardées par SAWALI */}
                  <button type="button" onClick={(ev) => { ev.stopPropagation(); modifier(e.code, { reponses_transmises: e.reponses_transmises === false }); }}
                          title={e.reponses_transmises === false
                            ? "Non transmises : la plateforme ne reçoit rien ; les messages portent « merci de ne pas y répondre »"
                            : "Transmises : une réponse faite avec « Répondre » est envoyée à la plateforme"}
                          className={`rounded px-2 py-0.5 font-semibold ${e.reponses_transmises === false ? "bg-slate-200 text-slate-700" : "bg-sky-100 text-sky-800"}`}>
                    {e.reponses_transmises === false ? "Non transmises" : "Transmises"}
                  </button>
                </td>
                <td className="pr-2">
                  {/* URL de retour : réponses, statuts, désinscriptions (enregistrée en quittant le champ) */}
                  <input defaultValue={e.url_retour || ""} onClick={(ev) => ev.stopPropagation()} placeholder="https://…"
                         onBlur={(ev) => ev.target.value !== (e.url_retour || "") && modifier(e.code, { url_retour: ev.target.value })}
                         className="w-56 rounded border border-slate-300 px-1 py-0.5" />
                  {e.dernier_retour_echec && (
                    <div className="text-[10px] text-red-700">Dernier retour en échec : {fmt(e.dernier_retour_echec)}</div>
                  )}
                </td>
                <td className="pr-2">
                  {/* Lot 62 — adresse des statistiques internes (vide = l'URL de retour est utilisée) */}
                  <input defaultValue={e.url_stats || ""} onClick={(ev) => ev.stopPropagation()} placeholder="vide = URL de retour"
                         onBlur={(ev) => ev.target.value !== (e.url_stats || "") && modifier(e.code, { url_stats: ev.target.value })}
                         className="w-48 rounded border border-slate-300 px-1 py-0.5" />
                  {e.derniere_stats_ok && <div className="text-[10px] text-emerald-700">Statistiques reçues : {fmt(e.derniere_stats_ok)}</div>}
                  {e.derniere_stats_echec && (!e.derniere_stats_ok || e.derniere_stats_echec > e.derniere_stats_ok) && (
                    <div className="text-[10px] text-red-700">Dernier échec : {fmt(e.derniere_stats_echec)}</div>
                  )}
                </td>
                <td className="pr-2">
                  {/* Lot 102 — adresse de l'assistant de la plateforme (ex. ZandGo : https://…/api/liluvine/question).
                      Un client qui écrit dans les 72 h suivant un message de la plateforme reçoit la réponse de son
                      assistant ; vide = Liluvine répond elle-même. Enregistrée en quittant le champ. */}
                  <input defaultValue={e.url_assistant || ""} onClick={(ev) => ev.stopPropagation()} placeholder="vide = Liluvine répond"
                         onBlur={(ev) => ev.target.value !== (e.url_assistant || "") && modifier(e.code, { url_assistant: ev.target.value })}
                         className="w-56 rounded border border-slate-300 px-1 py-0.5" />
                </td>
                <td className="whitespace-nowrap">
                  <button type="button" title="Regénérer la clé" onClick={(ev) => { ev.stopPropagation(); regenerer(e.code); }}
                          className="mr-1 inline-flex items-center gap-1 rounded px-2 py-0.5 ring-1 ring-slate-300">
                    <KeyRound className="h-3.5 w-3.5" /> Regénérer HMAC
                  </button>
                  <button type="button" title="Supprimer" onClick={(ev) => { ev.stopPropagation(); supprimer(e.code); }}
                          className="inline-flex items-center rounded px-1.5 py-0.5 text-red-700 ring-1 ring-red-200">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </td>
              </tr>
            ))}
            {emetteurs.length === 0 && (
              <tr><td colSpan={10} className="py-3 text-center text-slate-400">Aucune plateforme émettrice (nombre illimité : ster, adlyn, albarka, beauthentik…).</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Réponses de clients relayées aux plateformes */}
      <div>
        <span className="text-xs font-semibold">Réponses de clients relayées ({reponses.length})</span>
        <div className="max-h-56 overflow-auto">
          <table className="w-full text-xs">
            <thead><tr className="text-left text-slate-500"><th className="py-1 pr-2">Date</th><th className="pr-2">Plateforme</th><th className="pr-2">De</th><th>Message</th></tr></thead>
            <tbody>
              {reponses.map((r, i) => (
                <tr key={`${r.date}-${i}`} className="border-t border-slate-100">
                  <td className="py-1 pr-2">{fmt(r.date)}</td><td className="pr-2">{r.emetteur}</td>
                  <td className="pr-2 font-mono">{r.de}</td><td>{r.texte}{r.media ? " 📎" : ""}</td>
                </tr>
              ))}
              {reponses.length === 0 && <tr><td colSpan={4} className="py-2 text-center text-slate-400">Aucune réponse relayée.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      {/* Numéros désinscrits (STOP), par plateforme */}
      <div>
        <span className="text-xs font-semibold">Numéros désinscrits ({desinscriptions.length})</span>
        <div className="max-h-56 overflow-auto">
          <table className="w-full text-xs">
            <thead><tr className="text-left text-slate-500"><th className="py-1 pr-2">Date</th><th className="pr-2">Plateforme</th><th className="pr-2">Numéro</th><th></th></tr></thead>
            <tbody>
              {desinscriptions.map((d) => (
                <tr key={`${d.emetteur}-${d.numero}`} className="border-t border-slate-100">
                  <td className="py-1 pr-2">{fmt(d.date)}</td><td className="pr-2">{d.emetteur}</td>
                  <td className="pr-2 font-mono">+{d.numero}</td>
                  <td><button type="button" onClick={() => reinscrire(d.emetteur, d.numero)} className="rounded px-2 py-0.5 ring-1 ring-slate-300">Réinscrire</button></td>
                </tr>
              ))}
              {desinscriptions.length === 0 && <tr><td colSpan={4} className="py-2 text-center text-slate-400">Aucun numéro désinscrit.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      {/* Journal des transmissions */}
      <div>
        <div className="mb-1 flex items-center justify-between">
          <span className="text-xs font-semibold">Journal des 50 dernières transmissions</span>
          <button type="button" onClick={charger} className="inline-flex items-center gap-1 text-xs text-slate-600">
            <RefreshCw className="h-3.5 w-3.5" /> Actualiser
          </button>
        </div>
        <div className="max-h-72 overflow-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-slate-500">
                <th className="py-1 pr-2">Date</th><th className="pr-2">Émetteur</th><th className="pr-2">Destinataire</th>
                <th className="pr-2">Mode</th><th className="pr-2">Résultat</th><th className="pr-2">Remise</th><th>Longueur</th>
              </tr>
            </thead>
            <tbody>
              {journal.map((j, i) => (
                <tr key={`${j.date}-${i}`} className="border-t border-slate-100">
                  <td className="py-1 pr-2">{fmt(j.date)}</td>
                  <td className="pr-2">{j.source || j.emetteur}</td>
                  <td className="pr-2 font-mono">{j.to}</td>
                  <td className="pr-2">{j.mode === "modele" ? "Modèle" : "Texte"}{j.media_mode ? ` + média (${j.media_mode})` : ""}</td>
                  <td className="pr-2">{j.ok ? "✅ Envoyé" : `❌ ${j.erreur || "Échec"}`}</td>
                  <td className="pr-2">{{ sent: "Envoyé", delivered: "Remis", read: "Lu", failed: "Échec" }[j.statut] || "—"}</td>
                  <td>{j.longueur}</td>
                </tr>
              ))}
              {journal.length === 0 && (
                <tr><td colSpan={7} className="py-3 text-center text-slate-400">Aucune transmission pour l'instant.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
