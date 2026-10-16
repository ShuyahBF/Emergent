// =====================================================================
// Lot 163 — Rubrique des Paramètres « 🧩 Offre du client — Liluvine » : refus d'assistance quand le contrat du client n'est
// pas à jour.   GET / PUT /api/admin/offre-client/reglages  { actif, message }
// - L'offre de chaque client se saisit sur sa fiche (SMART Communications) ; Liluvine l'utilise toujours (sans effet si vide).
// Lot 210 — RAPPELS D'ÉCHÉANCE : GET / PUT /api/admin/offre-client/rappels  { actif, modele, langue, message } et
//   POST /api/admin/offre-client/rappels/executer { simuler } (simulation par défaut : rien n'est envoyé).
//   Chaque ligne de l'offre d'un client a une durée, une date de début, des jours de rappel et une alerte AUTORISÉE ; chaque matin
//   (07 h 30), Liluvine prévient tous les décisionnaires du client. Interrupteur général DÉSACTIVÉ par défaut.
// - Le refus est DÉSACTIVÉ par défaut. Activé : un contact lié à un client dont le contrat n'est pas à jour (orange / rouge ;
//   pseudo-contrat compris) et qui demande assistance, maintenance, dépannage… reçoit le texte ci-dessous, signé par l'assistant IA ;
//   un ticket est ouvert (ou la demande rattachée au ticket ouvert) et l'administrateur est alerté.
// =====================================================================
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

export default function OffreClientSection() {
  const [etat, setEtat] = useState(null);        // réponse du serveur
  const [actif, setActif] = useState(false);
  const [message, setMessage] = useState("");
  const [occupe, setOccupe] = useState(false);
  // Lot 210 — rappels d'échéance
  const [rappels, setRappels] = useState(null);   // réponse du serveur (réglages + dernier passage)
  const [rActif, setRActif] = useState(false);
  const [rModele, setRModele] = useState("");
  const [rLangue, setRLangue] = useState("fr");
  const [rMessage, setRMessage] = useState("");
  const [rOccupe, setROccupe] = useState("");     // "" | "enregistrer" | "simuler" | "envoyer"
  const [apercu, setApercu] = useState(null);     // résultat d'une simulation ou d'un passage manuel

  const chargerRappels = () => apiClient.get("/admin/offre-client/rappels").then((r) => {
    setRappels(r.data); setRActif(!!r.data.actif); setRModele(r.data.modele || ""); setRLangue(r.data.langue || "fr"); setRMessage(r.data.message || "");
  }).catch(() => toast.error("Réglages des rappels illisibles"));
  useEffect(() => { chargerRappels(); }, []);

  // Enregistre les réglages des rappels (le texte libre doit contenir {liste})
  const enregistrerRappels = async () => {
    setROccupe("enregistrer");
    try {
      const { data } = await apiClient.put("/admin/offre-client/rappels", { actif: rActif, modele: rModele, langue: rLangue, message: rMessage === rappels?.message_defaut ? "" : rMessage });
      setRappels(data); toast.success("Réglages des rappels enregistrés");
    } catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible"); } finally { setROccupe(""); }
  };
  // Simulation (rien n'est envoyé) ou passage manuel de Liluvine (envoie vraiment, après confirmation)
  const lancer = async (simuler) => {
    if (!simuler && !window.confirm("Envoyer MAINTENANT les rappels du jour aux décisionnaires concernés ?")) return;
    setROccupe(simuler ? "simuler" : "envoyer");
    try {
      const { data } = await apiClient.post("/admin/offre-client/rappels/executer", { simuler });
      setApercu(data);
      if (!simuler) { toast.success(`${data.envoyes} message(s) envoyé(s), ${data.echecs} échec(s)`); chargerRappels(); }
    } catch (e) { toast.error(e?.response?.data?.detail || "Passage impossible"); } finally { setROccupe(""); }
  };

  useEffect(() => {
    apiClient.get("/admin/offre-client/reglages").then((r) => { setEtat(r.data); setActif(!!r.data.actif); setMessage(r.data.message || ""); })
      .catch(() => toast.error("Réglages de l'offre du client illisibles"));
  }, []);

  // Enregistre l'activation et le texte (le texte doit contenir {objet})
  const enregistrer = async () => {
    setOccupe(true);
    try {
      const { data } = await apiClient.put("/admin/offre-client/reglages", { actif, message });
      setEtat(data); setMessage(data.message || ""); toast.success("Réglages enregistrés");
    } catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible"); } finally { setOccupe(false); }
  };

  if (!etat) return <p className="text-sm text-slate-500">Chargement…</p>;
  return (
    <div className="space-y-3 text-sm text-slate-700" data-testid="offre-client-section">
      <p>
        Chaque client a sa liste de <b>logiciels, produits et services</b> (fiche client → SMART Communications ; {etat.clients_avec_offre} client(s) renseigné(s)).
        Liluvine s'en sert pour ne plus poser de questions sur nos produits, mieux orienter ses réponses, demander des précisions si elle ne
        comprend pas, sinon escalader vers un humain.
      </p>
      {/* Lot 169 — copie d'une liste d'un client à un autre */}
      <p className="rounded-md bg-sky-50 p-2 text-xs text-sky-900 ring-1 ring-sky-200" data-testid="note-copie-offre">
        <b>Copie (lot 169) :</b> sur la fiche d'un client, le bouton « Copier la liste d'un client à un autre » reprend la liste d'un autre client dans
        l'éditeur (à enregistrer), ou envoie la liste enregistrée vers plusieurs clients à la fois — en ajoutant les lignes absentes (sans doublon)
        ou en remplaçant leur liste. Les listes copiées restent indépendantes de la source.
      </p>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={actif} onChange={(e) => setActif(e.target.checked)} data-testid="offre-refus-actif" />
        <span>Refuser l'assistance aux clients dont le contrat n'est pas à jour (ticket + escalade)</span>
      </label>
      <label className="block text-xs font-medium text-slate-700">
        Texte du refus — <code>{"{objet}"}</code> = ce que Liluvine a détecté (ex. « la maintenance de SAWALI CRM »). Signé par l'assistant IA.
        <textarea rows={2} maxLength={500} value={message} onChange={(e) => setMessage(e.target.value)} placeholder={etat.message_defaut}
          className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm" data-testid="offre-refus-message" />
      </label>
      <button type="button" onClick={enregistrer} disabled={occupe} className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-700 disabled:opacity-50" data-testid="offre-refus-enregistrer">
        {occupe ? "Patientez…" : "Enregistrer"}
      </button>

      {/* Lot 210 — rappels d'échéance des produits et services, par WhatsApp, aux décisionnaires du client */}
      <div className="space-y-3 rounded-lg border border-amber-200 bg-amber-50/40 p-3" data-testid="offre-rappels">
        <h4 className="text-sm font-semibold text-slate-900">🔔 Rappels d'échéance (WhatsApp aux décisionnaires)</h4>
        <p className="text-xs text-slate-600">
          Sur la fiche d'un client, chaque ligne a une <b>date de début</b>, une <b>durée</b> (30 = un mois) et des <b>jours de rappel</b> (ex. 7, 3) ;
          cochez « 🔔 Alerte autorisée » pour les lignes à rappeler. Chaque matin à 07 h 30, Liluvine inspecte les lignes autorisées et prévient
          <b> tous les contacts décisionnaires</b> du client (un message par décisionnaire, toutes les échéances du jour regroupées).
          {rappels ? <> {rappels.clients_avec_alerte} client(s) ont au moins une alerte autorisée.</> : null}
        </p>
        {rappels && (
          <>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={rActif} onChange={(e) => setRActif(e.target.checked)} data-testid="offre-rappel-actif" />
              <span>Activer l'envoi quotidien des rappels (désactivé par défaut)</span>
            </label>
            <div className="grid gap-2 md:grid-cols-[2fr_1fr]">
              <label className="block text-xs font-medium text-slate-700">
                Modèle WhatsApp approuvé par Meta (3 variables : {"{{1}}"} contact, {"{{2}}"} client, {"{{3}}"} liste des produits)
                <input value={rModele} onChange={(e) => setRModele(e.target.value)} maxLength={100} placeholder="ex. rappel_echeance_produits"
                  className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm" data-testid="offre-rappel-modele" />
              </label>
              <label className="block text-xs font-medium text-slate-700">Langue du modèle
                <input value={rLangue} onChange={(e) => setRLangue(e.target.value)} maxLength={10} className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm" />
              </label>
            </div>
            <p className="rounded-md bg-white p-2 text-xs text-amber-900 ring-1 ring-amber-200">
              <b>Important :</b> WhatsApp n'autorise un message à un contact qui n'a pas écrit depuis 24 h que par un <b>modèle approuvé</b>.
              Sans modèle renseigné, le texte libre ci-dessous n'arrive que si le décisionnaire a écrit récemment.
            </p>
            <label className="block text-xs font-medium text-slate-700">
              Texte libre — <code>{"{contact}"}</code> <code>{"{client}"}</code> <code>{"{liste}"}</code> (obligatoire)
              <textarea rows={3} maxLength={700} value={rMessage} onChange={(e) => setRMessage(e.target.value)} placeholder={rappels.message_defaut}
                className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm" data-testid="offre-rappel-message" />
            </label>
            <div className="flex flex-wrap items-center gap-2 boutons-distincts">
              <button type="button" onClick={enregistrerRappels} disabled={!!rOccupe} className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-700 disabled:opacity-50" data-testid="offre-rappel-enregistrer">
                {rOccupe === "enregistrer" ? "Patientez…" : "Enregistrer"}
              </button>
              <button type="button" onClick={() => lancer(true)} disabled={!!rOccupe} className="rounded-md bg-sky-100 px-3 py-1.5 text-xs font-semibold text-sky-900 hover:bg-sky-200 disabled:opacity-50" data-testid="offre-rappel-simuler">
                {rOccupe === "simuler" ? "Patientez…" : "👁️ Simuler (rien n'est envoyé)"}
              </button>
              <button type="button" onClick={() => lancer(false)} disabled={!!rOccupe || !rappels.actif} className="rounded-md bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-amber-700 disabled:opacity-40" data-testid="offre-rappel-envoyer"
                title={rappels.actif ? "Envoie les rappels du jour maintenant" : "Activez et enregistrez d'abord l'envoi quotidien"}>
                {rOccupe === "envoyer" ? "Patientez…" : "Envoyer maintenant"}
              </button>
            </div>
            {/* Résultat d'une simulation ou du dernier passage de Liluvine */}
            {(() => {
              const r = apercu || rappels.dernier;
              if (!r) return <p className="text-xs text-slate-500">Aucun passage de Liluvine enregistré pour l'instant.</p>;
              return (
                <div className="space-y-1 rounded-md bg-white p-2 text-xs ring-1 ring-slate-200" data-testid="offre-rappel-bilan">
                  <p className="font-semibold">
                    {r.simule ? "Simulation" : "Dernier passage"} du {new Date(r.le).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })} :
                    {" "}{r.clients} client(s) à rappeler, {r.messages} message(s){r.simule ? " à envoyer" : `, ${r.envoyes} envoyé(s), ${r.echecs} échec(s)`}.
                  </p>
                  {r.sans_decisionnaire > 0 && <p className="text-rose-700">⚠ {r.sans_decisionnaire} client(s) sans décisionnaire joignable : marquez un contact « décisionnaire » avec un numéro WhatsApp.</p>}
                  {!r.simule && !r.actif && <p className="text-slate-500">L'envoi quotidien était désactivé : rien n'est parti.</p>}
                  {(r.details || []).map((d, i) => (
                    <div key={i} className="border-t border-slate-100 pt-1">
                      <b>{d.client}</b> — {(d.produits || []).join(" ; ")}
                      {d.alerte && <div className="text-rose-700">{d.alerte}</div>}
                      {(d.destinataires || []).map((x, k) => (
                        <div key={k} className={x.ok === false ? "text-rose-700" : "text-slate-600"}>
                          → {x.nom || "décisionnaire"} {x.telephone}{x.ok === true ? " : envoyé ✓" : x.ok === false ? ` : échec (${x.erreur || "—"})` : " : serait prévenu"}
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              );
            })()}
          </>
        )}
      </div>
    </div>
  );
}
