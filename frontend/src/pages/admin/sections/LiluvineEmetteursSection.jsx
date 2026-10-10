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
  Lot 104 : « Codes de connexion » — modèle WhatsApp d'AUTHENTIFICATION (créé chez Meta en un clic)
  utilisé pour les codes OTP des plateformes : ils arrivent même hors de la fenêtre de 24 h.
  Journal : mode « Code (OTP) » et motif d'échec de remise donné par Meta.
  Lot 104.1 : « Envois des 7 derniers jours par plateforme » (refusés, envoyés, remis, lus, échoués,
  dernier motif d'échec) ; un clic sur une plateforme filtre le journal.
  Lot 104.2 : « Messages des plateformes » — modèle WhatsApp UTILITAIRE à 3 variables (Date/Heure,
  Émetteur, Message) créé chez Meta en un clic : les messages transmis arrivent hors fenêtre de 24 h.
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
  const [otp, setOtp] = useState(null);                 // lot 104 : modèle des codes de connexion
  const [creationOtp, setCreationOtp] = useState(false);
  const [modeleTrans, setModeleTrans] = useState(null); // lot 104.2 : modèle de la Transmission (3 variables)
  const [creationTrans, setCreationTrans] = useState(false);
  const chargerTrans = useCallback(async () => {
    try { setModeleTrans((await apiClient.get("/admin/liluvine-modele-transmission")).data); } catch { setModeleTrans({ nom: "", statut_meta: null }); }
  }, []);
  useEffect(() => { chargerTrans(); }, [chargerTrans]);
  const creerTrans = async () => {
    setCreationTrans(true);
    const attente = toast.loading("Patientez… création du modèle chez Meta");
    try {
      const { data } = await apiClient.post("/admin/liluvine-modele-transmission/creer", {});
      toast.success(`Modèle « ${data.nom} » envoyé à Meta (${data.statut_meta}). Approbation en général en quelques minutes à quelques heures.`, { id: attente });
      chargerTrans();
      window.dispatchEvent(new Event("sawali-reglages-modifies"));   // la page relit ses paramètres
    } catch (e) {
      toast.error(erreur(e), { id: attente });
    } finally { setCreationTrans(false); }
  };
  const [synthese, setSynthese] = useState([]);         // lot 104.1 : envois par plateforme (7 jours)
  const [filtre, setFiltre] = useState("");             // lot 104.1 : plateforme affichée dans le journal

  // Lot 104 : état du modèle d'authentification (nom, langue, statut chez Meta)
  const chargerOtp = useCallback(async () => {
    try { setOtp((await apiClient.get("/admin/liluvine-modele-otp")).data); } catch { setOtp({ nom: "", statut_meta: null }); }
  }, []);
  useEffect(() => { chargerOtp(); }, [chargerOtp]);
  const creerOtp = async () => {
    setCreationOtp(true);
    const attente = toast.loading("Patientez… création du modèle chez Meta");
    try {
      const { data } = await apiClient.post("/admin/liluvine-modele-otp/creer", {});
      toast.success(`Modèle « ${data.nom} » envoyé à Meta (${data.statut_meta}). Approbation en général en quelques minutes.`, { id: attente });
      chargerOtp();
      window.dispatchEvent(new Event("sawali-reglages-modifies"));   // la page relit ses paramètres
    } catch (e) {
      toast.error(erreur(e), { id: attente });
    } finally { setCreationOtp(false); }
  };

  // Chargement des émetteurs et du journal
  // Lot 107.1 — test immédiat de chaque plateforme (statistiques sans cache) puis rechargement du tableau
  const [actualisation, setActualisation] = useState(false);
  const actualiserPlateformes = async () => {
    setActualisation(true);
    const attente = toast.loading("Patientez… interrogation des plateformes");
    try {
      const actifs = emetteurs.filter((x) => x.actif && (x.url_retour || x.url_stats));
      await Promise.allSettled(actifs.map((x) => apiClient.post(`/admin/plateformes-activite/${x.code}/tester`)));
      await charger();
      toast.success(`${actifs.length} plateforme(s) interrogée(s)`, { id: attente });
    } catch {
      toast.error("Actualisation impossible", { id: attente });
    } finally { setActualisation(false); }
  };

  const charger = useCallback(async () => {
    try {
      const [a, b, c, d] = await Promise.all([
        apiClient.get("/admin/liluvine-emetteurs"),
        apiClient.get("/admin/liluvine-transmissions", { params: { limite: 50, ...(filtre ? { emetteur: filtre } : {}) } }),
        apiClient.get("/admin/liluvine-reponses"),
        apiClient.get("/admin/liluvine-desinscriptions"),
      ]);
      setEmetteurs(a.data.emetteurs || []);
      setJournal(b.data.transmissions || []);
      setReponses(c.data.reponses || []);
      setDesinscriptions(d.data.desinscriptions || []);
      // Lot 104.1 : synthèse par plateforme (n'empêche pas l'affichage du reste si elle échoue)
      apiClient.get("/admin/liluvine-transmissions/synthese").then((r) => setSynthese(r.data.plateformes || [])).catch(() => {});
    } catch (e) {
      toast.error(erreur(e));
    }
  }, [filtre]);
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

      {/* Lot 104 : modèle d'authentification pour les codes de connexion (OTP) des plateformes */}
      <div className="rounded-lg border border-sky-200 bg-sky-50/60 p-3 text-xs" data-testid="liluvine-modele-otp">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="font-semibold text-slate-800">Codes de connexion (OTP) des plateformes</div>
            <p className="mt-0.5 text-slate-600">
              Un code envoyé avec le champ <code>code_otp</code> part par un modèle WhatsApp d'<b>authentification</b>
              (bouton « Copier le code ») : il arrive même à un nouveau client qui n'a jamais écrit (hors fenêtre de 24 h).
            </p>
          </div>
          <button type="button" onClick={creerOtp} disabled={creationOtp}
                  className="inline-flex items-center gap-1 rounded bg-slate-900 px-3 py-1.5 text-white disabled:opacity-50">
            <KeyRound className="h-3.5 w-3.5" /> {otp?.nom ? "Recréer / vérifier chez Meta" : "Créer le modèle chez Meta"}
          </button>
        </div>
        <div className="mt-2 text-slate-700">
          {otp === null ? "Lecture…" : otp.nom ? (
            <>Modèle : <b className="font-mono">{otp.nom}</b> ({otp.langue}) — état Meta :{" "}
              <b className={otp.statut_meta === "APPROVED" ? "text-emerald-700" : "text-amber-700"}>
                {{ APPROVED: "✅ approuvé", PENDING: "⏳ en attente d'approbation", REJECTED: "❌ refusé", INTROUVABLE: "❌ introuvable chez Meta" }[otp.statut_meta] || otp.statut_meta || "inconnu"}
              </b></>
          ) : <>⚠️ Aucun modèle : les codes partent en texte libre et n'arrivent qu'aux personnes ayant écrit dans les 24 h.</>}
        </div>
      </div>

      {/* Lot 104.2 : modèle à 3 variables des messages transmis par les plateformes (suivi de commande, rappels…) */}
      <div className="rounded-lg border border-sky-200 bg-sky-50/60 p-3 text-xs" data-testid="liluvine-modele-transmission">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="font-semibold text-slate-800">Messages des plateformes (Transmission universelle)</div>
            <p className="mt-0.5 text-slate-600">
              Les messages des plateformes partent par un modèle WhatsApp <b>utilitaire</b> à 3 variables (Date/Heure, Émetteur, Message) :
              ils arrivent même à quelqu'un qui n'a pas écrit depuis 24 h. Les retours à la ligne du message deviennent « · ».
            </p>
            {modeleTrans?.corps && <p className="mt-1 whitespace-pre-line rounded bg-white/70 px-2 py-1 font-mono text-[11px] text-slate-600">{modeleTrans.corps}</p>}
          </div>
          <button type="button" onClick={creerTrans} disabled={creationTrans}
                  className="inline-flex items-center gap-1 rounded bg-slate-900 px-3 py-1.5 text-white disabled:opacity-50">
            <KeyRound className="h-3.5 w-3.5" /> {modeleTrans?.nom ? "Recréer / vérifier chez Meta" : "Créer le modèle chez Meta"}
          </button>
        </div>
        <div className="mt-2 text-slate-700">
          {modeleTrans === null ? "Lecture…" : modeleTrans.nom ? (
            <>Modèle : <b className="font-mono">{modeleTrans.nom}</b> ({modeleTrans.langue}) — état Meta :{" "}
              <b className={modeleTrans.statut_meta === "APPROVED" ? "text-emerald-700" : "text-amber-700"}>
                {{ APPROVED: "✅ approuvé", PENDING: "⏳ en attente d'approbation", REJECTED: "❌ refusé", INTROUVABLE: "❌ introuvable chez Meta" }[modeleTrans.statut_meta] || modeleTrans.statut_meta || "inconnu"}
              </b></>
          ) : <>⚠️ Aucun modèle : les messages partent en texte libre et n'arrivent qu'aux personnes ayant écrit dans les 24 h.</>}
        </div>
      </div>

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
      {/* Lot 107.1 — « Actualiser » : interroge tout de suite chaque plateforme (statistiques = test de l'adresse de
          retour), puis recharge le tableau ; toast « Patientez… » pendant l'opération */}
      <div className="flex justify-end">
        <button type="button" onClick={actualiserPlateformes} disabled={actualisation}
                className="inline-flex items-center gap-1 rounded border border-slate-300 px-2.5 py-1 text-xs hover:bg-slate-50 disabled:opacity-50">
          <RefreshCw className={`h-3.5 w-3.5 ${actualisation ? "animate-spin" : ""}`} /> Actualiser
        </button>
      </div>
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
                  {/* Lot 107.1 : échec affiché seulement s'il est plus récent que le dernier retour réussi */}
                  {e.dernier_retour_echec && !(e.dernier_retour_ok && e.dernier_retour_ok > e.dernier_retour_echec) ? (
                    <div className="text-[10px] text-red-700">Dernier retour en échec : {fmt(e.dernier_retour_echec)}</div>
                  ) : e.dernier_retour_ok ? (
                    <div className="text-[10px] text-emerald-700">Dernier retour reçu : {fmt(e.dernier_retour_ok)}</div>
                  ) : null}
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

      {/* Lot 104.1 : envois des 7 derniers jours par plateforme, avec leur statut RÉEL de remise */}
      <div data-testid="liluvine-synthese-envois">
        <div className="mb-1 text-xs font-semibold">Envois des 7 derniers jours par plateforme</div>
        {synthese.length === 0 ? <p className="text-xs text-slate-400">Aucun envoi sur la période.</p> : (
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {synthese.map((p) => {
              const echecs = p.echec + p.refuses;
              return (
                <button key={p.emetteur} type="button" onClick={() => setFiltre(filtre === p.emetteur ? "" : p.emetteur)}
                        className={`rounded-lg border p-2.5 text-left text-xs ${filtre === p.emetteur ? "border-sky-400 bg-sky-50" : "border-slate-200 bg-white hover:border-slate-300"}`}>
                  <div className="flex items-center justify-between">
                    <b className="text-slate-800">{p.source || p.emetteur}</b>
                    <span className={echecs ? "font-semibold text-rose-700" : "text-emerald-700"}>{echecs ? `${echecs} échec(s)` : "✅ aucun échec"}</span>
                  </div>
                  {/* Compteurs : refusés par Meta à l'envoi, puis statut de remise renvoyé par Meta */}
                  <div className="mt-1 flex flex-wrap gap-x-3 text-slate-600">
                    <span>{p.total} envoi(s)</span><span>Lus {p.lu}</span><span>Remis {p.remis}</span>
                    <span>Envoyés {p.envoye}</span><span className={p.echec ? "text-rose-700" : ""}>Échoués {p.echec}</span>
                    {p.refuses > 0 && <span className="text-rose-700">Refusés {p.refuses}</span>}
                  </div>
                  {p.dernier_echec && (
                    <div className="mt-1 rounded bg-rose-50 px-2 py-1 text-[11px] text-rose-800">
                      Dernier échec {fmt(p.dernier_echec.date)} vers {p.dernier_echec.to} : {p.dernier_echec.motif}
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Journal des transmissions */}
      <div>
        <div className="mb-1 flex items-center justify-between">
          <span className="text-xs font-semibold">Journal des 50 dernières transmissions{filtre ? ` — ${filtre}` : ""}
            {filtre && <button type="button" onClick={() => setFiltre("")} className="ml-2 font-normal text-sky-700 underline">toutes les plateformes</button>}</span>
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
                  <td className="pr-2">{{ modele: "Modèle", otp: "Code (OTP)" }[j.mode] || "Texte"}{j.media_mode ? ` + média (${j.media_mode})` : ""}</td>
                  <td className="pr-2">{j.ok ? "✅ Envoyé" : `❌ ${j.erreur || "Échec"}`}</td>
                  {/* Lot 104 : motif d'échec de remise donné par Meta (ex. hors fenêtre de 24 h) */}
                  <td className="pr-2">{{ sent: "Envoyé", delivered: "Remis", read: "Lu", failed: "❌ Échec" }[j.statut] || "—"}
                    {j.statut === "failed" && j.erreur_remise && <div className="text-[10px] text-rose-700">{j.erreur_remise}</div>}</td>
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
