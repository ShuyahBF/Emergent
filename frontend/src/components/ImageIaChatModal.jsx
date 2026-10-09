// ImageIaChatModal.jsx — Lot 87 : image illustrative générée par l'IA dans la fenêtre de support (chat interne).
//
// Ouverte par le bouton 🎨 de la zone de saisie du chat (équipe SAWALI seulement : admin, superviseur, support Loois).
// Étapes :
//   1. DÉCRIRE : on tape la description (prompt), on choisit un style et un format → « Générer » (toast « Patientez… »
//      + jauge circulaire, règle du propriétaire). « Régénérer » refait une image avec la même description.
//   2. RETOUCHER : « ✏️ Annoter » ouvre l'annotateur (flèches, cercles, texte, flou…) comme dans la discussion WhatsApp ;
//      la version annotée remplace l'aperçu.
//   3. ACCEPTER : l'image part dans la discussion ouverte, MAINTENANT ou à une date et une heure PLANIFIÉES.
//   4. TRANSFÉRER à n'importe qui : autre discussion SAWALI (espace + membre), numéro WhatsApp (contact ou numéro saisi)
//      ou adresse e-mail ; maintenant ou planifié.
// Mode « transfert seul » (prop messageId) : ouvert depuis l'agrandissement d'une image du chat (« ↪ Transférer »).
// La liste « Envois planifiés » permet de suivre et d'annuler les envois à venir.
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import ImageAnnotator from "@/components/ImageAnnotator";
// Lot 87.1 — joindre le lien de mes disponibilités (agenda) à la légende de l'image
import CalendrierModal from "@/components/CalendrierModal";

// Libellés des styles et des formats proposés (mêmes clés que le serveur)
const STYLES = { illustration: "Illustration", photo: "Photo réaliste", schema: "Schéma / pictogrammes", libre: "Libre (sans consigne)" };
const FORMATS = { carre: "Carré", paysage: "Paysage", portrait: "Portrait" };
// Libellés des états d'un envoi planifié
const STATUTS = { planifie: "⏰ planifié", en_cours: "… en cours", envoye: "✅ envoyé", echec: "❌ échec", annule: "annulé" };

// Petite jauge circulaire transparente (attente)
const Jauge = () => (
  <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-sky-300 border-t-transparent align-middle" />
);

// Date ISO → « JJ/MM/AAAA HH:MM » (heure locale)
const dateLisible = (iso) => {
  try { return new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }); } catch { return iso; }
};

// Message d'erreur du serveur, sinon message par défaut
const erreur = (e, defaut) => e?.response?.data?.detail || defaut;

// « data:image/png;base64,… » → File (pour l'annotateur)
const fichierDepuisDataUrl = (dataUrl) => {
  const [entete, b64] = dataUrl.split(",");
  const mime = (entete.match(/data:([^;]+)/) || [])[1] || "image/png";
  const octets = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  return new File([octets], `image-ia.${mime.includes("jpeg") ? "jpg" : "png"}`, { type: mime });
};

// Choix « Maintenant / Planifier le … » (commun à l'envoi et au transfert)
function ChoixQuand({ valeur, onChange, id }) {
  return (
    <div className="flex flex-wrap items-center gap-3 text-xs text-slate-700" data-testid={`quand-${id}`}>
      <label className="inline-flex items-center gap-1">
        <input type="radio" name={`quand-${id}`} checked={valeur === null} onChange={() => onChange(null)} /> Maintenant
      </label>
      <label className="inline-flex items-center gap-1">
        <input type="radio" name={`quand-${id}`} checked={valeur !== null} onChange={() => onChange("")} /> Planifier le
      </label>
      {valeur !== null && (
        <input type="datetime-local" value={valeur} onChange={(e) => onChange(e.target.value)}
               className="rounded border border-slate-300 px-2 py-1" data-testid={`quand-date-${id}`} />
      )}
    </div>
  );
}

// Heure locale saisie (datetime-local) → ISO pour le serveur ; null = envoi immédiat
const isoPlanifie = (valeur) => (valeur ? new Date(valeur).toISOString() : null);

export default function ImageIaChatModal({ clientId, threadKey, nomDiscussion, messageId = null, onClose, onEnvoye }) {
  const modeTransfert = Boolean(messageId);           // ouvert depuis une image du chat : transfert seulement
  // --- Étape 1 : description ---
  const [etat, setEtat] = useState(null);             // { par_heure, utilisees, style }
  const [prompt, setPrompt] = useState("");
  const [style, setStyle] = useState("illustration");
  const [format, setFormat] = useState("carre");
  const [generation, setGeneration] = useState(false);
  // --- Étape 2 : aperçu ---
  const [apercu, setApercu] = useState(null);         // { apercu_id, apercu (data URL), annotee }
  const [aAnnoter, setAAnnoter] = useState(null);     // File ouvert dans l'annotateur
  const [legende, setLegende] = useState("");
  const [quandEnvoi, setQuandEnvoi] = useState(null); // null = maintenant ; "AAAA-MM-JJTHH:MM" = planifié
  const [envoi, setEnvoi] = useState(false);
  const [calendrier, setCalendrier] = useState(null);   // lot 87.1 : "envoi" ou "transfert" = légende qui reçoit le lien
  // --- Transfert ---
  const [transfert, setTransfert] = useState(modeTransfert);
  const [canal, setCanal] = useState("chat");
  const [espaces, setEspaces] = useState([]);
  const [espace, setEspace] = useState("");
  const [membres, setMembres] = useState([]);
  const [membre, setMembre] = useState("general");
  const [telephone, setTelephone] = useState("");
  const [recherche, setRecherche] = useState("");
  const [contacts, setContacts] = useState([]);
  const [email, setEmail] = useState("");
  const [legendeT, setLegendeT] = useState("");
  const [quandT, setQuandT] = useState(null);
  const [transfertEnCours, setTransfertEnCours] = useState(false);
  // --- Envois planifiés ---
  const [planifies, setPlanifies] = useState(null);

  // État (limite par heure, style par défaut) au chargement
  useEffect(() => {
    apiClient.get("/me/chat/image-ia/etat").then((r) => {
      setEtat(r.data);
      if (r.data.style) setStyle(r.data.style);
    }).catch(() => setEtat({}));
  }, []);

  // Espaces de discussion visibles (pour transférer dans une autre discussion)
  useEffect(() => {
    if (!transfert || espaces.length) return;
    apiClient.get("/me/chat/clients").then((r) => {
      setEspaces(r.data || []);
      setEspace(clientId || (r.data?.[0]?.id ?? ""));
    }).catch(() => setEspaces([]));
  }, [transfert, espaces.length, clientId]);

  // Membres de l'espace choisi
  useEffect(() => {
    if (!espace) return;
    apiClient.get(`/me/chat/${espace}/members`).then((r) => {
      const liste = (r.data || []).filter((m) => !m.is_self);
      setMembres(liste);
      setMembre(espace === "support-loois" ? (liste[0]?.id || "") : "general");   // pas de #général au support Loois
    }).catch(() => setMembres([]));
  }, [espace]);

  // Recherche de contacts WhatsApp (nom ou numéro) avec l'état de la fenêtre de 24 h
  useEffect(() => {
    if (canal !== "whatsapp" || recherche.trim().length < 2) { setContacts([]); return undefined; }
    const t = setTimeout(() => {
      apiClient.get("/me/wa-transfert/destinataires", { params: { q: recherche.trim() } })
        .then((r) => setContacts(r.data.destinataires || [])).catch(() => setContacts([]));
    }, 350);
    return () => clearTimeout(t);
  }, [canal, recherche]);

  // 1. Générer (ou régénérer) l'image
  const generer = async () => {
    if (!prompt.trim()) { toast.error("Décrivez l'image à générer"); return; }
    setGeneration(true);
    const t = toast.loading("Patientez… l'IA dessine votre image (jusqu'à une minute)");
    try {
      const r = await apiClient.post("/me/chat/image-ia", { prompt, style, format }, { timeout: 180000 });
      setApercu({ ...r.data, annotee: false });
      setEtat((e) => (e ? { ...e, utilisees: (e.utilisees || 0) + 1 } : e));
      toast.success("Image générée : acceptez-la, annotez-la ou régénérez-la", { id: t });
    } catch (e) {
      toast.error(erreur(e, "Génération impossible"), { id: t });
    } finally {
      setGeneration(false);
    }
  };

  // 2. Annoter : la version annotée est enregistrée et remplace l'aperçu
  const terminerAnnotation = async (fichier) => {
    setAAnnoter(null);
    const t = toast.loading("Patientez… enregistrement de l'image annotée");
    try {
      const form = new FormData();
      form.append("image", fichier, fichier.name || "image-annotee.png");
      const r = await apiClient.post(`/me/chat/image-ia/${apercu.apercu_id}/annoter`, form,
        { headers: { "Content-Type": "multipart/form-data" }, timeout: 90000 });
      setApercu(r.data);
      toast.success("Annotations enregistrées", { id: t });
    } catch (e) {
      toast.error(erreur(e, "Annotation non enregistrée"), { id: t });
    }
  };

  // 3. Accepter : envoi dans la discussion ouverte (maintenant ou planifié)
  const envoyer = async () => {
    if (quandEnvoi === "") { toast.error("Choisissez la date et l'heure d'envoi"); return; }
    setEnvoi(true);
    const t = toast.loading("Patientez… envoi de l'image");
    try {
      const r = await apiClient.post(`/me/chat/image-ia/${apercu.apercu_id}/envoyer`, {
        client_id: clientId, recipient_id: threadKey, legende, planifie_le: isoPlanifie(quandEnvoi),
      }, { timeout: 90000 });
      if (r.data.planifie) {
        toast.success(`Envoi planifié le ${dateLisible(r.data.planifie_le)}`, { id: t });
        setPlanifies(null);
      } else {
        toast.success("Image envoyée dans la discussion", { id: t });
        onEnvoye?.();
      }
    } catch (e) {
      toast.error(erreur(e, "Envoi impossible"), { id: t });
    } finally {
      setEnvoi(false);
    }
  };

  // 4. Transférer (discussion SAWALI, WhatsApp, e-mail ; maintenant ou planifié)
  const transferer = async () => {
    if (quandT === "") { toast.error("Choisissez la date et l'heure du transfert"); return; }
    const corps = {
      ...(messageId ? { message_id: messageId } : { apercu_id: apercu?.apercu_id }),
      canal, legende: legendeT, planifie_le: isoPlanifie(quandT),
      ...(canal === "chat" ? { client_id: espace, recipient_id: membre } : {}),
      ...(canal === "whatsapp" ? { telephone } : {}),
      ...(canal === "email" ? { email } : {}),
    };
    setTransfertEnCours(true);
    const t = toast.loading("Patientez… transfert de l'image");
    try {
      const r = await apiClient.post("/me/chat/image-ia/transferer", corps, { timeout: 90000 });
      if (r.data.planifie) {
        toast.success(`Transfert planifié le ${dateLisible(r.data.planifie_le)}`, { id: t });
        setPlanifies(null);
      } else {
        // La modale reste ouverte : on peut transférer la même image à d'autres personnes
        toast.success({ chat: "Image transférée dans la discussion", whatsapp: "Image envoyée sur WhatsApp",
          email: "Image envoyée par e-mail" }[canal], { id: t });
      }
    } catch (e) {
      toast.error(erreur(e, "Transfert impossible"), { id: t });
    } finally {
      setTransfertEnCours(false);
    }
  };

  // Envois planifiés : chargement et annulation
  const chargerPlanifies = () => apiClient.get("/me/chat/image-ia/planifies")
    .then((r) => setPlanifies(r.data.planifies || [])).catch(() => setPlanifies([]));
  const annulerPlanifie = async (id) => {
    if (!window.confirm("Annuler cet envoi planifié ?")) return;
    try {
      await apiClient.delete(`/me/chat/image-ia/planifies/${id}`);
      toast.success("Envoi planifié annulé");
      chargerPlanifies();
    } catch (e) {
      toast.error(erreur(e, "Annulation impossible"));
    }
  };

  const occupe = generation || envoi || transfertEnCours;

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/60 p-3" data-testid="image-ia-modal">
      <div className="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white p-4 shadow-2xl">
        {/* En-tête */}
        <div className="mb-3 flex items-start justify-between gap-2">
          <div>
            <h3 className="text-base font-bold text-slate-900">
              {modeTransfert ? "↪ Transférer l'image" : "🎨 Générer une image illustrative"}
            </h3>
            {!modeTransfert && (
              <p className="text-[11px] text-slate-500">
                Pour la discussion : <b>{nomDiscussion || "discussion ouverte"}</b>
                {etat?.par_heure ? ` · ${etat.utilisees || 0}/${etat.par_heure} images cette heure` : ""}
              </p>
            )}
          </div>
          <button onClick={onClose} disabled={occupe} className="rounded-lg px-2 py-1 text-slate-500 hover:bg-slate-100" aria-label="Fermer"
                  data-testid="image-ia-fermer">✕</button>
        </div>

        {/* 1. Description */}
        {!modeTransfert && (
          <div className="space-y-2">
            <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} maxLength={1000}
                      placeholder="Décrivez l'image : ex. « Un technicien qui branche un câble réseau sur un serveur, style moderne »"
                      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-300"
                      data-testid="image-ia-prompt" disabled={generation} />
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <select value={style} onChange={(e) => setStyle(e.target.value)} className="rounded border border-slate-300 px-2 py-1"
                      data-testid="image-ia-style">
                {Object.entries(STYLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
              <select value={format} onChange={(e) => setFormat(e.target.value)} className="rounded border border-slate-300 px-2 py-1"
                      data-testid="image-ia-format">
                {Object.entries(FORMATS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
              <button onClick={generer} disabled={occupe || !prompt.trim()}
                      className="ml-auto inline-flex items-center gap-2 rounded-lg bg-violet-600 px-3 py-1.5 font-semibold text-white hover:bg-violet-700 disabled:opacity-40"
                      data-testid="image-ia-generer">
                {generation && <Jauge />} {apercu ? "🔁 Régénérer" : "✨ Générer"}
              </button>
            </div>
          </div>
        )}

        {/* 2. Aperçu, annotation et acceptation */}
        {!modeTransfert && apercu && (
          <div className="mt-3 space-y-2 rounded-xl border border-slate-200 p-3">
            <img src={apercu.apercu} alt="Aperçu de l'image générée" className="mx-auto max-h-[45vh] rounded-lg object-contain"
                 data-testid="image-ia-apercu" />
            {apercu.annotee && <p className="text-center text-[11px] text-emerald-700">✏️ Version annotée</p>}
            <input value={legende} onChange={(e) => setLegende(e.target.value)} maxLength={500}
                   placeholder="Légende (facultative)" className="w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
                   data-testid="image-ia-legende" />
            <ChoixQuand valeur={quandEnvoi} onChange={setQuandEnvoi} id="envoi" />
            <div className="flex flex-wrap gap-2">
              <button onClick={() => setAAnnoter(fichierDepuisDataUrl(apercu.apercu))} disabled={occupe}
                      className="rounded-lg bg-slate-100 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-200 disabled:opacity-40"
                      data-testid="image-ia-annoter">✏️ Annoter</button>
              <button onClick={() => setCalendrier("envoi")} disabled={occupe}
                      className="rounded-lg bg-indigo-50 px-3 py-1.5 text-sm font-semibold text-indigo-700 ring-1 ring-indigo-300 hover:bg-indigo-100 disabled:opacity-40"
                      data-testid="image-ia-calendrier">📅 Joindre mes disponibilités</button>
              <button onClick={() => setTransfert((v) => !v)} disabled={occupe}
                      className="rounded-lg bg-sky-100 px-3 py-1.5 text-sm font-semibold text-sky-800 hover:bg-sky-200 disabled:opacity-40"
                      data-testid="image-ia-ouvrir-transfert">↪ Transférer…</button>
              <button onClick={envoyer} disabled={occupe || !clientId || !threadKey}
                      className="ml-auto inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-40"
                      data-testid="image-ia-envoyer">
                {envoi && <Jauge />} {quandEnvoi !== null ? "⏰ Planifier l'envoi" : "✅ Accepter et envoyer dans le chat"}
              </button>
            </div>
          </div>
        )}

        {/* 3. Transfert à n'importe qui */}
        {transfert && (modeTransfert || apercu) && (
          <div className="mt-3 space-y-2 rounded-xl border border-sky-200 bg-sky-50/40 p-3" data-testid="image-ia-transfert">
            <div className="flex gap-1 text-xs">
              {[["chat", "💬 Discussion SAWALI"], ["whatsapp", "🟢 WhatsApp"], ["email", "✉️ E-mail"]].map(([k, v]) => (
                <button key={k} onClick={() => setCanal(k)}
                        className={`rounded-full px-3 py-1 font-semibold ${canal === k ? "bg-sky-700 text-white" : "bg-white text-slate-700 ring-1 ring-slate-200"}`}
                        data-testid={`image-ia-canal-${k}`}>{v}</button>
              ))}
            </div>
            {canal === "chat" && (
              <div className="flex flex-wrap gap-2 text-sm">
                <select value={espace} onChange={(e) => setEspace(e.target.value)} className="rounded border border-slate-300 px-2 py-1"
                        data-testid="image-ia-espace">
                  {espaces.map((c) => <option key={c.id} value={c.id}>{c.company || c.full_name || c.id}</option>)}
                </select>
                <select value={membre} onChange={(e) => setMembre(e.target.value)} className="rounded border border-slate-300 px-2 py-1"
                        data-testid="image-ia-membre">
                  {espace !== "support-loois" && <option value="general"># Général (toute l'équipe)</option>}
                  {membres.map((m) => <option key={m.id} value={m.id}>{m.name}{m.online ? " · en ligne" : ""}</option>)}
                </select>
              </div>
            )}
            {canal === "whatsapp" && (
              <div className="space-y-1 text-sm">
                <input value={recherche} onChange={(e) => setRecherche(e.target.value)} placeholder="Chercher un contact (nom ou numéro)…"
                       className="w-full rounded border border-slate-300 px-2 py-1" data-testid="image-ia-recherche-contact" />
                {contacts.length > 0 && (
                  <div className="max-h-32 overflow-y-auto rounded border border-slate-200 bg-white">
                    {contacts.map((c) => (
                      <button key={`${c.source}-${c.id}`} onClick={() => { setTelephone(c.telephone); setRecherche(""); }}
                              className="flex w-full items-center justify-between px-2 py-1 text-left text-xs hover:bg-sky-50">
                        <span>{c.nom} · +{c.telephone}</span>
                        {!c.fenetre_ouverte && <span className="rounded bg-amber-100 px-1 text-[10px] text-amber-800">fenêtre 24 h fermée</span>}
                      </button>
                    ))}
                  </div>
                )}
                <input value={telephone} onChange={(e) => setTelephone(e.target.value)} placeholder="Numéro WhatsApp (ex. 76 22 22 22 ou +33…)"
                       className="w-full rounded border border-slate-300 px-2 py-1" data-testid="image-ia-telephone" />
                <p className="text-[10px] text-slate-500">WhatsApp n'accepte une image libre que si la personne vous a écrit depuis moins de 24 h.</p>
              </div>
            )}
            {canal === "email" && (
              <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" placeholder="adresse@exemple.com"
                     className="w-full rounded border border-slate-300 px-2 py-1 text-sm" data-testid="image-ia-email" />
            )}
            <input value={legendeT} onChange={(e) => setLegendeT(e.target.value)} maxLength={500} placeholder="Message joint (facultatif)"
                   className="w-full rounded border border-slate-300 px-2 py-1 text-sm" data-testid="image-ia-legende-transfert" />
            <button onClick={() => setCalendrier("transfert")} disabled={occupe}
                    className="text-xs font-semibold text-indigo-700 hover:underline" data-testid="image-ia-calendrier-transfert">
              📅 Joindre mes disponibilités au message
            </button>
            <ChoixQuand valeur={quandT} onChange={setQuandT} id="transfert" />
            <div className="flex justify-end">
              <button onClick={transferer}
                      disabled={occupe || (canal === "chat" && (!espace || !membre)) || (canal === "whatsapp" && !telephone.trim()) || (canal === "email" && !email.trim())}
                      className="inline-flex items-center gap-2 rounded-lg bg-sky-700 px-3 py-1.5 text-sm font-semibold text-white hover:bg-sky-800 disabled:opacity-40"
                      data-testid="image-ia-transferer">
                {transfertEnCours && <Jauge />} {quandT !== null ? "⏰ Planifier le transfert" : "↪ Transférer"}
              </button>
            </div>
          </div>
        )}

        {/* Envois planifiés (suivi et annulation) */}
        <div className="mt-3 border-t border-slate-100 pt-2">
          <button onClick={() => (planifies ? setPlanifies(null) : chargerPlanifies())}
                  className="text-xs font-semibold text-slate-600 hover:text-slate-900" data-testid="image-ia-planifies">
            ⏰ {planifies ? "Masquer" : "Voir"} mes envois planifiés
          </button>
          {planifies && (
            <table className="mt-2 w-full text-xs">
              <tbody>
                {planifies.length === 0 && <tr><td className="py-1 text-slate-500">Aucun envoi planifié.</td></tr>}
                {planifies.map((p) => (
                  <tr key={p.id} className="border-t border-slate-100">
                    <td className="py-1">{dateLisible(p.planifie_le)}</td>
                    <td className="py-1">{p.action === "envoyer" ? "Discussion" : { chat: "Discussion", whatsapp: "WhatsApp", email: "E-mail" }[p.payload?.canal]}
                      {p.payload?.telephone ? ` +${p.payload.telephone}` : ""}{p.payload?.email ? ` ${p.payload.email}` : ""}</td>
                    <td className="py-1" title={p.raison || ""}>{STATUTS[p.statut] || p.statut}</td>
                    <td className="py-1 text-right">
                      {p.statut === "planifie" && (
                        <button onClick={() => annulerPlanifie(p.id)} className="text-rose-600 hover:underline">Annuler</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Lot 87.1 — calendrier : « Partager » ajoute le lien des disponibilités à la légende (image ou transfert) */}
      {calendrier && (
        <CalendrierModal
          contactNom={nomDiscussion}
          onClose={() => setCalendrier(null)}
          onPartager={(t) => {
            const ajouter = (x) => (x ? `${x} — ${t}` : t).slice(0, 500);   // champ d'une ligne
            if (calendrier === "transfert") setLegendeT(ajouter); else setLegende(ajouter);
          }}
        />
      )}
      {/* Annotateur (même outil que la discussion WhatsApp) */}
      {aAnnoter && <ImageAnnotator file={aAnnoter} onCancel={() => setAAnnoter(null)} onDone={terminerAnnotation} />}
    </div>
  );
}
