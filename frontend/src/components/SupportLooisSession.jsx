// =====================================================================
// Lot 58 — « Support Loois » : bandeau de SESSION d'assistance au-dessus du fil d'un poste Loois,
// et affichage des fichiers (vidéos de l'écran, documents) dans les bulles du chat.
//
// Cycle d'une session (voir backend/routes/support_loois_sessions.py) :
//   attente  → l'agent choisit le client SAWALI puis « Accepter » (ticket créé) ou « Refuser » (motif)
//   active   → ticket, client, temps restant ; « ✨ Suggestion Liluvine », « 📎 Fichier », « Terminer la session »
//   terminee → ticket clôturé, intervention créée, « 📝 Détails du Support » rédigés par Liluvine
// =====================================================================
import React, { useCallback, useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Loader2, FileText, Download, Sparkles, Paperclip } from "lucide-react";

// Durée mm:ss (temps restant de la session)
function formaterDuree(secondes) {
  const s = Math.max(0, Math.floor(secondes || 0));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

// Fichier envoyé au poste : documents, vidéos et images (20 à 50 Mo selon le type, contrôlé par le serveur)
const TYPES_ACCEPTES = "image/*,video/mp4,video/webm,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv";

export function SupportLooisBandeau({ posteId, lastEvent, onSuggestion }) {
  const [session, setSession] = useState(null);          // session en cours ou dernière session du poste
  const [clients, setClients] = useState([]);            // clients SAWALI proposés pour le ticket
  const [clientId, setClientId] = useState("");          // client choisi à l'acceptation
  const [motif, setMotif] = useState("");                // motif du ticket (facultatif)
  const [occupe, setOccupe] = useState(false);           // action en cours (« Patientez… »)
  const [dureeMax, setDureeMax] = useState(1800);
  const [maintenant, setMaintenant] = useState(Date.now());
  const [voirDetails, setVoirDetails] = useState(false);
  const fichierRef = useRef(null);
  // Lot 58.3 — sessions précédentes du poste (ticket, intervention, détails) : restent consultables
  const [historique, setHistorique] = useState([]);
  const [voirHistorique, setVoirHistorique] = useState(false);
  const [detailsOuverts, setDetailsOuverts] = useState(null);   // id de la session dont on lit les détails

  // ---- Chargement de la session du poste (et du client retenu pour ce poste) ----
  const charger = useCallback(async () => {
    if (!posteId) return;
    try {
      const r = await apiClient.get(`/support-loois/postes/${posteId}/session`);
      setSession(r.data.session || null);
      setDureeMax(r.data.duree_max_s || 1800);
      if (r.data.client_id_suggere) setClientId((c) => c || r.data.client_id_suggere);
    } catch {
      setSession(null);
    }
    try {
      const h = await apiClient.get(`/support-loois/postes/${posteId}/historique`);
      setHistorique(h.data || []);
    } catch {
      setHistorique([]);
    }
  }, [posteId]);

  useEffect(() => { setClientId(""); setMotif(""); setVoirDetails(false); charger(); }, [posteId, charger]);

  // ---- Liste des clients, chargée seulement quand une demande attend ----
  useEffect(() => {
    if (session?.statut !== "attente" || clients.length) return;
    apiClient.get("/support-loois/clients").then((r) => setClients(r.data || [])).catch(() => {});
  }, [session?.statut, clients.length]);

  // ---- Mise à jour en direct (WebSocket du chat interne) ----
  useEffect(() => {
    if (lastEvent?.type === "support_loois_session" && lastEvent.session?.poste_id === posteId) {
      setSession(lastEvent.session);
      // l'historique (ticket clôturé, intervention, détails) est relu à chaque changement d'état
      apiClient.get(`/support-loois/postes/${posteId}/historique`).then((h) => setHistorique(h.data || [])).catch(() => {});
    }
  }, [lastEvent, posteId]);

  // ---- Horloge du temps restant (session active seulement) ----
  useEffect(() => {
    if (session?.statut !== "active") return undefined;
    const t = setInterval(() => setMaintenant(Date.now()), 1000);
    return () => clearInterval(t);
  }, [session?.statut]);

  // ---- Appel d'une action avec toast « Patientez… » ----
  const agir = async (chemin, corps, succes) => {
    setOccupe(true);
    const attente = toast.loading("Patientez…");
    try {
      const r = await apiClient.post(`/support-loois/sessions/${session.id}/${chemin}`, corps || {});
      setSession(r.data);
      toast.success(succes, { id: attente });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Action impossible", { id: attente });
      charger();
    } finally {
      setOccupe(false);
    }
  };

  // Lot 58.1 — le client choisi est associé TOUT DE SUITE au poste : Liluvine répond avec son prompt
  const associer = async (id) => {
    setClientId(id);
    if (!id) return;
    try {
      await apiClient.post(`/support-loois/postes/${posteId}/client`, { client_id: id });
      toast.success("Client associé au poste : Liluvine utilise son prompt");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Association impossible");
    }
  };

  const accepter = () => {
    if (!clientId) { toast.error("Choisissez le client SAWALI de ce poste."); return; }
    agir("accepter", { client_id: clientId, motif }, "Session acceptée : ticket créé");
  };
  const refuser = () => {
    const m = window.prompt("Motif du refus (affiché dans Loois) :", "Le support n'est pas disponible pour le moment.");
    if (m === null) return;
    agir("refuser", { motif: m }, "Demande refusée");
  };
  const terminer = () => {
    if (!window.confirm("Terminer la session ? Le ticket sera clôturé et l'intervention créée.")) return;
    agir("terminer", {}, "Session terminée : ticket clôturé, intervention créée");
  };

  // ---- Lot 58.2 — Liluvine (re)génère les « Détails du Support » d'une session terminée ----
  const genererDetails = async (sid = session?.id) => {
    setOccupe(true);
    const attente = toast.loading("Patientez… Liluvine résume l'assistance");
    try {
      const r = await apiClient.post(`/support-loois/sessions/${sid}/details`);
      if (sid === session?.id) { setSession(r.data); setVoirDetails(true); }
      setHistorique((h) => h.map((x) => (x.id === sid ? { ...x, details_support: r.data.details_support } : x)));
      setDetailsOuverts(sid);
      toast.success("Détails du Support enregistrés (ticket et intervention)", { id: attente });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Résumé impossible", { id: attente });
    } finally {
      setOccupe(false);
    }
  };

  // ---- Liluvine propose la prochaine réponse (placée dans la zone de saisie, à relire) ----
  const suggerer = async () => {
    setOccupe(true);
    const attente = toast.loading("Patientez… Liluvine rédige une suggestion");
    try {
      const r = await apiClient.post(`/support-loois/postes/${posteId}/suggestion`);
      onSuggestion?.(r.data.texte || "");
      toast.success("Suggestion placée dans la zone de saisie", { id: attente });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Liluvine indisponible", { id: attente });
    } finally {
      setOccupe(false);
    }
  };

  // ---- Envoi d'un document / d'une vidéo au poste ----
  const envoyerFichier = async (fichier) => {
    if (!fichier) return;
    setOccupe(true);
    const attente = toast.loading(`Patientez… envoi de ${fichier.name}`);
    try {
      const form = new FormData();
      form.append("fichier", fichier, fichier.name);
      await apiClient.post(`/support-loois/postes/${posteId}/fichier`, form);
      toast.success("Fichier envoyé", { id: attente });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Envoi impossible", { id: attente });
    } finally {
      setOccupe(false);
      if (fichierRef.current) fichierRef.current.value = "";
    }
  };

  if (!session && historique.length === 0) return null;
  const statut = session?.statut;
  const restant = statut === "active" && session?.acceptee_le
    ? dureeMax - (maintenant - new Date(session.acceptee_le).getTime()) / 1000 : null;
  const bouton = "inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-semibold disabled:opacity-50";

  return (
    <div className="mx-4 mt-3 mb-1 rounded-lg ring-1 px-3 py-2 text-xs bg-white ring-slate-200" data-testid="support-loois-bandeau">
      {statut === "attente" && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-amber-700">⏳ Demande d'assistance en attente</span>
          <select
            value={clientId}
            onChange={(e) => associer(e.target.value)}
            className="rounded-md border border-slate-300 px-2 py-1 text-xs max-w-[220px]"
            data-testid="support-loois-client"
          >
            <option value="">— Client SAWALI du ticket —</option>
            {clients.map((c) => <option key={c.id} value={c.id}>{c.nom}</option>)}
          </select>
          <input
            value={motif}
            onChange={(e) => setMotif(e.target.value)}
            placeholder="Motif (facultatif)"
            className="rounded-md border border-slate-300 px-2 py-1 text-xs w-40"
          />
          <button onClick={accepter} disabled={occupe} className={`${bouton} bg-emerald-600 text-white hover:bg-emerald-700`} data-testid="support-loois-accepter">
            {occupe && <Loader2 className="h-3 w-3 animate-spin" />} Accepter
          </button>
          <button onClick={refuser} disabled={occupe} className={`${bouton} bg-rose-100 text-rose-700 hover:bg-rose-200`} data-testid="support-loois-refuser">
            Refuser
          </button>
        </div>
      )}

      {statut === "active" && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-slate-800">🎫 Ticket {session.ticket_number}</span>
          <span className="text-slate-500">{session.client_nom} · {session.acceptee_par_nom}</span>
          <span
            className={`rounded-full px-2 py-0.5 font-mono font-semibold text-white ${restant !== null && restant <= 300 ? "bg-rose-600" : "bg-emerald-600"}`}
            title="Temps restant de la session"
          >
            {formaterDuree(restant)}
          </span>
          <span className="ml-auto flex flex-wrap gap-1">
            <button onClick={suggerer} disabled={occupe} className={`${bouton} bg-violet-100 text-violet-700 hover:bg-violet-200`} data-testid="support-loois-suggestion">
              <Sparkles className="h-3 w-3" /> Suggestion Liluvine
            </button>
            <input ref={fichierRef} type="file" accept={TYPES_ACCEPTES} className="hidden"
                   onChange={(e) => envoyerFichier(e.target.files?.[0])} />
            <button onClick={() => fichierRef.current?.click()} disabled={occupe} className={`${bouton} bg-slate-100 text-slate-700 hover:bg-slate-200`} data-testid="support-loois-fichier">
              <Paperclip className="h-3 w-3" /> Fichier
            </button>
            <button onClick={terminer} disabled={occupe} className={`${bouton} bg-slate-900 text-white hover:bg-black`} data-testid="support-loois-terminer">
              Terminer la session
            </button>
          </span>
        </div>
      )}

      {statut === "terminee" && (
        <div>
          <div className="flex flex-wrap items-center gap-2 text-slate-600">
            <span className="font-semibold text-slate-800">✅ Session terminée</span>
            {session.ticket_number && <span>Ticket {session.ticket_number} clôturé</span>}
            {session.intervention_number && <span>· Intervention {session.intervention_number}</span>}
            {/* Lot 58.2 — le ticket clôturé reste consultable (la liste des tickets n'affiche que les ouverts par défaut) */}
            {session.ticket_number && (
              <a
                href={`/portal/tickets?numero=${encodeURIComponent(session.ticket_number)}`}
                className={`${bouton} bg-slate-100 text-slate-700 hover:bg-slate-200`}
                data-testid="support-loois-voir-ticket"
              >
                🎫 Voir le ticket
              </a>
            )}
            {session.details_support ? (
              <button onClick={() => setVoirDetails((v) => !v)} className={`${bouton} ml-auto bg-sky-50 text-sky-700 hover:bg-sky-100`}>
                📝 Détails du Support
              </button>
            ) : (
              <button onClick={() => genererDetails()} disabled={occupe} className={`${bouton} ml-auto bg-violet-100 text-violet-700 hover:bg-violet-200`}
                      title="Liluvine résume la conversation (si le résumé automatique n'est pas arrivé)">
                {occupe && <Loader2 className="h-3 w-3 animate-spin" />} 📝 Générer les Détails du Support
              </button>
            )}
          </div>
          {voirDetails && session.details_support && (
            <pre className="mt-2 whitespace-pre-wrap font-sans text-[11px] text-slate-700 bg-slate-50 rounded-md p-2 max-h-60 overflow-y-auto">
              {session.details_support}
            </pre>
          )}
        </div>
      )}

      {(statut === "refusee" || statut === "abandonnee") && (
        <span className="text-slate-500">
          {statut === "refusee" ? `⛔ Dernière demande refusée : ${session.motif_refus || ""}` : "Dernière demande abandonnée par le poste."}
        </span>
      )}

      {/* Lot 58.3 — historique des sessions du poste avec leur ticket (même après une nouvelle demande) */}
      {historique.some((h) => h.ticket) && (
        <div className="mt-2 border-t border-slate-100 pt-2">
          <button onClick={() => setVoirHistorique((v) => !v)} className="text-[11px] font-semibold text-slate-600 hover:text-slate-900"
                  data-testid="support-loois-historique">
            {voirHistorique ? "▾" : "▸"} 🗂 Sessions et tickets de ce poste ({historique.filter((h) => h.ticket).length})
          </button>
          {voirHistorique && (
            <table className="mt-1 w-full text-[11px]">
              <thead>
                <tr className="text-left text-slate-500">
                  <th className="py-1 pr-2">Date</th><th className="pr-2">Ticket</th><th className="pr-2">État du ticket</th>
                  <th className="pr-2">Intervention</th><th>Détails du Support</th>
                </tr>
              </thead>
              <tbody>
                {historique.filter((h) => h.ticket).map((h) => (
                  <React.Fragment key={h.id}>
                    <tr className="border-t border-slate-100">
                      <td className="py-1 pr-2 whitespace-nowrap">{new Date(h.acceptee_le || h.demande_le).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}</td>
                      <td className="pr-2">
                        <a className="text-sky-700 underline" href={`/portal/tickets?numero=${encodeURIComponent(h.ticket.number || "")}`}>
                          🎫 {h.ticket.number}
                        </a>
                      </td>
                      <td className="pr-2">
                        {{ open: "Ouvert", in_progress: "En cours", suspended: "Suspendu", done: "Terminé", cancelled: "Annulé" }[h.ticket.status] || h.ticket.status}
                        {h.ticket.archived && " (corbeille)"}
                      </td>
                      <td className="pr-2">{h.ticket.intervention_number || "—"}</td>
                      <td>
                        {h.details_support ? (
                          <button className="text-sky-700 underline" onClick={() => setDetailsOuverts(detailsOuverts === h.id ? null : h.id)}>📝 Voir</button>
                        ) : h.statut === "terminee" ? (
                          <button className="text-violet-700 underline disabled:opacity-50" disabled={occupe} onClick={() => genererDetails(h.id)}>📝 Générer</button>
                        ) : "—"}
                      </td>
                    </tr>
                    {detailsOuverts === h.id && h.details_support && (
                      <tr>
                        <td colSpan={5}>
                          <pre className="my-1 whitespace-pre-wrap font-sans text-[11px] text-slate-700 bg-slate-50 rounded-md p-2 max-h-60 overflow-y-auto">{h.details_support}</pre>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

// =====================================================================
// Fichier dans une bulle : vidéo lisible sur place, document téléchargeable
// (les adresses des médias exigent le jeton : lecture par apiClient puis adresse « blob: »)
// =====================================================================
export function ChatFichier({ message, mine }) {
  const [url, setUrl] = useState(null);
  const [erreur, setErreur] = useState(false);
  const estVideo = message.media_kind === "video";
  const chemin = (message.media_url || "").replace(/^\/api/, "");

  // Vidéo : chargée tout de suite pour être lue dans la bulle
  useEffect(() => {
    if (!estVideo) return undefined;
    let actif = true;
    let cree = null;
    apiClient.get(chemin, { responseType: "blob" })
      .then((r) => { if (actif) { cree = URL.createObjectURL(r.data); setUrl(cree); } })
      .catch(() => actif && setErreur(true));
    return () => { actif = false; if (cree) URL.revokeObjectURL(cree); };
  }, [estVideo, chemin]);

  // Document : téléchargé au clic
  const telecharger = async () => {
    try {
      const r = await apiClient.get(chemin, { responseType: "blob" });
      const lien = document.createElement("a");
      lien.href = URL.createObjectURL(r.data);
      lien.download = message.file_name || "document";
      lien.click();
      setTimeout(() => URL.revokeObjectURL(lien.href), 5000);
    } catch {
      toast.error("Téléchargement impossible");
    }
  };

  if (estVideo) {
    if (erreur) return <p className="text-xs italic">🎥 Vidéo indisponible</p>;
    if (!url) return <div className="h-32 w-56 flex items-center justify-center bg-slate-100 rounded-lg mb-1"><Loader2 className="h-4 w-4 animate-spin text-slate-400" /></div>;
    return <video src={url} controls className="block mb-1 rounded-lg max-w-[280px] max-h-[220px] bg-black" />;
  }
  return (
    <button
      type="button"
      onClick={telecharger}
      className={`mb-1 flex items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs ring-1 ${mine ? "ring-white/40 bg-white/10" : "ring-slate-200 bg-slate-50"}`}
      title="Télécharger le document"
    >
      <FileText className="h-4 w-4 shrink-0" />
      <span className="truncate max-w-[180px]">{message.file_name || "Document"}</span>
      <Download className="h-3.5 w-3.5 shrink-0" />
    </button>
  );
}
