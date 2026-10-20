// EnvoiCarrouselContact.jsx — Lot 260 : envoyer un CARROUSEL WhatsApp enregistré à UN contact, depuis la conversation
// du Centre de Messagerie.
//
// Fonctionnement :
//   • un bouton « 🎠 » dans la barre d'outils de la zone de saisie (affiché seulement si la fonction « Carrousel
//     WhatsApp » est activée pour le compte) ouvre une petite fenêtre ;
//   • la fenêtre propose, dans une LISTE DÉROULANTE, les carrousels enregistrés dans « Carrousel WhatsApp → Mes
//     carrousels » (y compris ceux partagés avec le compte), avec un aperçu des cartes ;
//   • « Envoyer » appelle POST /me/whatsapp/carrousel/envoyer-a-contact (même circuit que l'envoi en série :
//     consentement du contact, plages horaires, modèles Meta). L'envoi se fait en arrière-plan ; le résultat se lit
//     dans « Carrousel WhatsApp → Suivi des campagnes ».
//   • Lot 261 — ACCORD DU CONTACT : un carrousel ne peut partir que vers un contact qui a accepté de recevoir vos messages
//     WhatsApp. Si ce n'est pas encore le cas, la fenêtre l'explique en français simple et propose d'envoyer DIRECTEMENT
//     la demande d'accord (message à deux boutons « Oui, j'accepte » / « Non merci »). Si le contact n'a pas écrit depuis
//     plus de 24 h, WhatsApp interdit ce message : la fenêtre donne alors son lien d'accord personnel à lui transmettre.
//     La fenêtre vérifie la réponse toutes les 8 secondes : dès que le contact accepte, « Envoyer » se débloque.
// Attente : toast « Patientez… » pendant l'envoi (règle du propriétaire).
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

// La fonction est demandée une seule fois par session de navigation (évite un appel à chaque conversation ouverte)
let _fonctionActive = null;
const fonctionCarrouselActive = () => {
  if (!_fonctionActive) {
    _fonctionActive = apiClient.get("/me/features")
      .then((r) => !!(r.data?.features?.whatsapp_carrousel && r.data?.features?.whatsapp))
      .catch(() => false);
  }
  return _fonctionActive;
};

// Message lisible d'une erreur du serveur
const messageErreur = (err, defaut) => {
  const d = err?.response?.data?.detail;
  return typeof d === "string" ? d : defaut;
};

export default function EnvoiCarrouselContact({ contact, desactive, onConversationMaj }) {
  const [disponible, setDisponible] = useState(false);   // fonction activée pour ce compte ?
  const [ouvert, setOuvert] = useState(false);
  const [chargement, setChargement] = useState(false);
  const [carrousels, setCarrousels] = useState([]);
  const [choix, setChoix] = useState("");                // identifiant du carrousel choisi
  const [envoi, setEnvoi] = useState(false);
  // Lot 261 — accord du contact : { accepte, demande_le, nom, numero_valide } ; résultat de la demande d'accord envoyée
  const [accord, setAccord] = useState(null);
  const [demande, setDemande] = useState(null);          // { envoyees, fenetre_fermee, lien } après « Envoyer la demande »
  const [demandeEnCours, setDemandeEnCours] = useState(false);

  useEffect(() => { let actif = true; fonctionCarrouselActive().then((ok) => actif && setDisponible(ok)); return () => { actif = false; }; }, []);

  // Lot 261 — état de l'accord du contact (léger) ; erreurs ignorées : la vérification est refaite par le serveur à l'envoi
  const lireAccord = async () => {
    try {
      const r = await apiClient.get(`/me/whatsapp/carrousel/contacts/${contact.id}/accord`);
      setAccord(r.data);
    } catch { /* l'état reste celui d'avant */ }
  };

  // Tant que la fenêtre est ouverte et que l'accord n'est pas reçu : on regarde toutes les 8 secondes
  useEffect(() => {
    if (!ouvert || !accord || accord.accepte) return undefined;
    const t = setInterval(lireAccord, 8000);
    return () => clearInterval(t);
  }, [ouvert, accord?.accepte]); // eslint-disable-line react-hooks/exhaustive-deps

  // Envoie la demande d'accord à ce contact (message à deux boutons) et explique le résultat
  const demanderAccord = async () => {
    setDemandeEnCours(true);
    const attente = toast.loading("Patientez… envoi de la demande d'accord");
    try {
      const r = await apiClient.post(`/me/whatsapp/carrousel/contacts/${contact.id}/demander-accord`);
      const d = r.data || {};
      if (d.accepte) { toast.success("Ce contact a déjà accepté.", { id: attente }); }
      else if (d.envoyees) { toast.success("Demande d'accord envoyée.", { id: attente }); }
      else if ((d.fenetre_fermee || []).length) { toast.message("Message impossible : donnez-lui son lien d'accord.", { id: attente }); }
      else { toast.error((d.erreurs || [])[0] || "La demande n'a pas pu partir.", { id: attente }); }
      setDemande({ envoyees: d.envoyees || 0, fenetre_fermee: (d.fenetre_fermee || []).length > 0,
                   lien: (d.liens || [])[0]?.lien || "", erreur: (d.erreurs || [])[0] || "" });
      await lireAccord();
      // Lot 262 — la conversation se relit tout de suite : la note « Demande d'accord envoyée » y apparaît
      if (onConversationMaj) onConversationMaj();
    } catch (err) {
      toast.error(messageErreur(err, "Demande impossible"), { id: attente });
    } finally {
      setDemandeEnCours(false);
    }
  };

  // Copie le lien d'accord personnel du contact
  const copierLien = async () => {
    try { await navigator.clipboard.writeText(demande.lien); toast.success("Lien copié"); }
    catch { toast.error("Copie impossible : sélectionnez le lien et copiez-le."); }
  };

  // À l'ouverture : lecture des carrousels enregistrés (les plus récents d'abord) et de l'accord du contact
  const ouvrir = async () => {
    setOuvert(true);
    setChargement(true);
    setDemande(null);
    lireAccord();
    try {
      const r = await apiClient.get("/me/whatsapp/carrousel/brouillons");
      const liste = r.data?.carrousels || [];
      setCarrousels(liste);
      setChoix((c) => (liste.some((x) => x.id === c) ? c : ""));
    } catch (err) {
      toast.error(messageErreur(err, "Impossible de charger vos carrousels"));
      setOuvert(false);
    } finally {
      setChargement(false);
    }
  };

  const envoyer = async () => {
    if (!choix) return;
    setEnvoi(true);
    const attente = toast.loading("Patientez… envoi du carrousel");
    try {
      const r = await apiClient.post("/me/whatsapp/carrousel/envoyer-a-contact", { contact_id: contact.id, carrousel_id: choix });
      const programme = ["PROGRAMMEE", "EN_ATTENTE"].includes(r.data?.statut);
      toast.success(programme
        ? "Carrousel programmé : il partira à l'ouverture de la plage horaire d'envoi."
        : `Carrousel envoyé à ${contact.name || "ce contact"}. Résultat dans « Carrousel WhatsApp → Suivi ».`, { id: attente });
      setOuvert(false);
      setChoix("");
    } catch (err) {
      toast.error(messageErreur(err, "Envoi impossible"), { id: attente });
    } finally {
      setEnvoi(false);
    }
  };

  if (!disponible) return null;
  const courant = carrousels.find((c) => c.id === choix);

  return (
    <>
      <button
        type="button"
        onClick={ouvrir}
        disabled={desactive}
        className="inline-flex items-center gap-1 rounded-lg border border-violet-300 bg-violet-50 hover:bg-violet-100 px-2.5 py-2 text-sm text-violet-700 disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
        data-testid="conversation-carrousel-btn"
        title="Envoyer un carrousel enregistré à ce contact"
      >
        <span aria-hidden="true">🎠</span>
      </button>
      {ouvert && (
        // Fenêtre de taille modérée (règle 11) : 28 rem au plus, 85 % de la hauteur, défilement DANS la fenêtre
        <div
          className="fixed inset-0 z-[70] flex items-end sm:items-center justify-center p-4 bg-black/50"
          onClick={(e) => e.target === e.currentTarget && !envoi && setOuvert(false)}
          data-testid="carrousel-contact-modal"
        >
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md max-h-[85dvh] overflow-y-auto p-5">
            <div className="flex items-start justify-between mb-3">
              <h3 className="font-display font-semibold text-slate-900">🎠 Envoyer un carrousel</h3>
              <button type="button" onClick={() => !envoi && setOuvert(false)} className="text-slate-400 hover:text-slate-700 p-1" aria-label="Fermer">✕</button>
            </div>
            <p className="text-xs text-slate-500 mb-3">
              Destinataire : <strong>{contact.name || contact.whatsapp || contact.phone}</strong>
            </p>
            {/* Lot 261 — accord du contact : reçu (vert) ou à demander (orange, avec l'explication et le bouton) */}
            {accord?.accepte && (
              <p className="mb-3 rounded-lg bg-emerald-50 border border-emerald-200 p-2 text-xs text-emerald-800" data-testid="carrousel-contact-accord-ok">
                ✓ Ce contact a accepté de recevoir vos messages WhatsApp : vous pouvez lui envoyer le carrousel.
              </p>
            )}
            {accord && !accord.accepte && (
              <div className="mb-3 rounded-lg bg-amber-50 border border-amber-200 p-3 text-xs text-amber-900" data-testid="carrousel-contact-accord-requis">
                <p className="font-semibold mb-1">Son accord est nécessaire avant l'envoi</p>
                <p className="mb-2">
                  WhatsApp n'autorise l'envoi d'un carrousel (message publicitaire) qu'aux personnes qui ont accepté d'en recevoir ;
                  sans accord, votre numéro risque d'être signalé et bloqué. {accord.nom || "Ce contact"} n'a pas encore accepté.
                </p>
                {!accord.numero_valide ? (
                  <p className="text-rose-700">Ce contact n'a pas de numéro WhatsApp valable : corrigez sa fiche.</p>
                ) : demande?.envoyees || (accord.demande_le && !demande) ? (
                  <p data-testid="carrousel-contact-accord-attente">
                    ⏳ Demande d'accord envoyée{accord.demande_le ? ` le ${new Date(accord.demande_le).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}` : ""}.
                    Dès que {accord.nom || "le contact"} répond « Oui, j'accepte », cette fenêtre se débloque toute seule et vous pourrez envoyer le carrousel.
                  </p>
                ) : null}
                {demande?.fenetre_fermee && (
                  <div className="mt-2" data-testid="carrousel-contact-lien-accord">
                    <p className="mb-1">
                      {accord.nom || "Ce contact"} ne vous a pas écrit depuis plus de 24 h : WhatsApp interdit alors de lui envoyer ce message.
                      Transmettez-lui plutôt ce lien personnel (par SMS, appel…) : en l'ouvrant, il pourra accepter.
                    </p>
                    {demande.lien ? (
                      <div className="flex items-center gap-2">
                        <input readOnly value={demande.lien} onFocus={(e) => e.target.select()} className="min-w-0 flex-1 rounded border border-amber-300 bg-white px-2 py-1 text-[11px]" />
                        <button type="button" onClick={copierLien} className="shrink-0 rounded border border-amber-400 bg-white px-2 py-1 font-semibold hover:bg-amber-100">Copier</button>
                      </div>
                    ) : <p className="text-rose-700">Lien indisponible pour le moment.</p>}
                  </div>
                )}
                {demande && !demande.envoyees && !demande.fenetre_fermee && demande.erreur && <p className="mt-2 text-rose-700">{demande.erreur}</p>}
                {accord.numero_valide && (
                  <button
                    type="button"
                    onClick={demanderAccord}
                    disabled={demandeEnCours}
                    className="mt-2 rounded-lg bg-amber-600 hover:bg-amber-700 px-3 py-1.5 font-semibold text-white disabled:opacity-40"
                    data-testid="carrousel-contact-demander-accord"
                  >
                    {demandeEnCours ? "Envoi…" : accord.demande_le || demande?.envoyees ? "Renvoyer la demande d'accord" : "Envoyer la demande d'accord"}
                  </button>
                )}
              </div>
            )}
            {chargement ? (
              <p className="text-center text-slate-400 italic py-6 text-sm">Chargement…</p>
            ) : carrousels.length === 0 ? (
              <p className="text-sm text-slate-600 py-4">
                Aucun carrousel enregistré. Créez-en un dans{" "}
                <Link to="/portal/whatsapp-carrousel" className="text-violet-700 underline">Carrousel WhatsApp</Link>, puis enregistrez-le sous un nom.
              </p>
            ) : (
              <>
                {/* Liste finie = liste déroulante (règle 10) */}
                <label className="block text-xs font-semibold text-slate-700 mb-1" htmlFor="carrousel-contact-choix">Carrousel</label>
                <select
                  id="carrousel-contact-choix"
                  value={choix}
                  onChange={(e) => setChoix(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-violet-500 focus:ring-1 focus:ring-violet-200 outline-none"
                  data-testid="carrousel-contact-select"
                >
                  <option value="">— Choisir un carrousel —</option>
                  {carrousels.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.nom} ({c.nb_cartes} cartes){c.partage ? " · partagé" : ""}
                    </option>
                  ))}
                </select>
                {courant && (
                  <div className="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-slate-600" data-testid="carrousel-contact-apercu">
                    {courant.message && <p className="mb-2 italic">« {courant.message} »</p>}
                    <ul className="space-y-0.5">
                      {(courant.cartes || []).map((k, i) => <li key={i}>{i + 1}. {k.titre || k.produit_id || "Carte"}</li>)}
                    </ul>
                    {courant.statut_meta && courant.statut_meta !== "APPROVED" && (
                      <p className="mt-2 text-amber-700">Modèle Meta : {courant.statut_meta} — l'envoi peut être refusé tant qu'il n'est pas approuvé.</p>
                    )}
                  </div>
                )}
                <div className="mt-4 flex justify-end gap-2">
                  <button type="button" onClick={() => setOuvert(false)} disabled={envoi} className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50">Annuler</button>
                  <button
                    type="button"
                    onClick={envoyer}
                    disabled={!choix || envoi || !accord?.accepte}
                    title={accord && !accord.accepte ? "Disponible dès que le contact a accepté" : undefined}
                    className="rounded-lg bg-violet-600 hover:bg-violet-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40"
                    data-testid="carrousel-contact-envoyer"
                  >
                    {envoi ? "Envoi…" : "Envoyer"}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
