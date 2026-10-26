// AppelsWhatsApp.jsx — Lot 60 : appels WhatsApp dans le portail SAWALI.
//
// Composant monté une seule fois dans la mise en page du portail (PortalLayout) :
//   • interroge le serveur toutes les 3 s : un appel entrant visible par l'utilisateur fait
//     apparaître la carte « Appel entrant » (sonnerie) avec Décrocher / Refuser ;
//   • Décrocher : micro du navigateur + WebRTC (le son passe directement entre le navigateur
//     et WhatsApp ; le serveur ne transmet que la négociation « SDP ») ;
//   • appel sortant : déclenché depuis une conversation par l'évènement
//     window « sawali:appel-wa » {telephone, contact_id, nom} — vérifie d'abord que le client
//     a autorisé les appels, sinon propose de lui envoyer la demande d'autorisation ;
//   • journal des appels : évènement window « sawali:journal-appels » {telephone?}.
import React, { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Phone, PhoneIncoming, PhoneOff, PhoneOutgoing, Mic, MicOff, Volume2, X } from "lucide-react";
import { apiClient } from "@/lib/api";
import PastilleLigneWa from "./PastilleLigneWa";
import TranscriptionAppelLiluvine from "./TranscriptionAppelLiluvine";   // Lot 69

// Serveurs STUN publics : permettent au navigateur de découvrir son adresse publique (WebRTC)
const ICE_SERVERS = [{ urls: ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"] }];
const INTERROGATION_MS = 3000;

// Lot 296 — sortie audio (haut-parleur) choisie par l'utilisateur, mémorisée dans ce navigateur
const CLE_SORTIE = "sawali_wa_sortie_audio";
const lireSortie = () => { try { return localStorage.getItem(CLE_SORTIE) || ""; } catch { return ""; } };
const ecrireSortie = (v) => { try { if (v) localStorage.setItem(CLE_SORTIE, v); else localStorage.removeItem(CLE_SORTIE); } catch { /* stockage indisponible */ } };
// Le choix de la sortie (setSinkId) n'existe que sur Chrome, Edge et Opera ; Firefox et Safari utilisent la sortie par défaut du système
const sortieChoisissable = () => typeof HTMLMediaElement !== "undefined" && "setSinkId" in HTMLMediaElement.prototype;

// Joue un bip de 1 s SUR la sortie choisie (vide = sortie par défaut) pour vérifier que le haut-parleur répond
async function bipTest(idSortie) {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  const ctx = new Ctx();
  const dest = ctx.createMediaStreamDestination();
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  gain.gain.value = 0.25;
  osc.frequency.value = 660;
  osc.connect(gain); gain.connect(dest);
  const lecteur = new Audio();
  lecteur.srcObject = dest.stream;
  if (idSortie && lecteur.setSinkId) await lecteur.setSinkId(idSortie);
  osc.start();
  await lecteur.play();
  await new Promise((r) => setTimeout(r, 1000));
  osc.stop(); lecteur.pause(); ctx.close();
}

// Attend la fin de la collecte des « candidats ICE » (adresses réseau) — 3 s au plus,
// car WhatsApp attend une description SDP complète (pas d'envoi au fil de l'eau)
function attendreIce(pc, delaiMs = 3000) {
  return new Promise((resolve) => {
    if (pc.iceGatheringState === "complete") { resolve(); return; }
    const fin = () => { pc.removeEventListener("icegatheringstatechange", verifier); resolve(); };
    const verifier = () => { if (pc.iceGatheringState === "complete") fin(); };
    pc.addEventListener("icegatheringstatechange", verifier);
    setTimeout(fin, delaiMs);
  });
}

// Sonnerie générée par le navigateur (deux bips toutes les 2 s), sans fichier audio
function demarrerSonnerie() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return () => {};
    const ctx = new Ctx();
    const bip = (debut) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = 440;
      gain.gain.value = 0.08;
      osc.connect(gain); gain.connect(ctx.destination);
      osc.start(ctx.currentTime + debut); osc.stop(ctx.currentTime + debut + 0.35);
    };
    const jouer = () => { bip(0); bip(0.5); };
    jouer();
    const minuterie = setInterval(jouer, 2000);
    return () => { clearInterval(minuterie); ctx.close().catch(() => {}); };
  } catch {
    return () => {};
  }
}

// Durée lisible : 75 → « 1 min 15 s »
export function dureeLisible(secondes) {
  const s = Math.max(0, Math.round(Number(secondes) || 0));
  if (s < 60) return `${s} s`;
  return `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s`;
}

// Libellés des statuts du journal
const LIBELLES_STATUT = {
  sonne: "Sonne", decroche: "Décroché", en_cours: "En cours", appel: "Appel en cours",
  termine: "Terminé", manque: "Manqué", refuse: "Refusé", sans_reponse: "Sans réponse",
  echec: "Échec",   // Lot 67 — alerte de Liluvine au propriétaire qui n'a pas pu partir
};

export default function AppelsWhatsApp() {
  const [sonnent, setSonnent] = useState([]);        // appels entrants qui sonnent
  const [appel, setAppel] = useState(null);           // appel en cours de l'utilisateur
  const [muet, setMuet] = useState(false);
  const [secondes, setSecondes] = useState(0);
  const [occupe, setOccupe] = useState(false);        // décroché / appel sortant en préparation
  const [journal, setJournal] = useState(null);       // {telephone, items, duree_totale_s} ou null
  const [deplie, setDeplie] = useState(null);         // Lot 69 — appel de Liluvine dont la transcription est dépliée
  const [etatSon, setEtatSon] = useState("");         // Lot 94 — état de la liaison audio (connexion, établie, échec…)
  const [sonBloque, setSonBloque] = useState(false);  // Lot 94 — le navigateur a bloqué la lecture du son
  const [sorties, setSorties] = useState([]);         // Lot 296 — haut-parleurs disponibles [{deviceId, label}]
  const [sortieId, setSortieId] = useState(lireSortie());   // Lot 296 — haut-parleur choisi ("" = celui du système)
  const [recu, setRecu] = useState(null);             // Lot 296 — son réellement reçu de WhatsApp {octets, niveau}
  const pcRef = useRef(null);                          // connexion WebRTC
  const micRef = useRef(null);                         // flux du micro
  const audioRef = useRef(null);                       // lecteur du son du correspondant
  const sonnerieRef = useRef(null);
  const refusesRef = useRef(new Set());                // appels ignorés localement

  // Libère micro et connexion WebRTC
  const fermerMedia = useCallback(() => {
    try { pcRef.current?.close(); } catch { /* déjà fermée */ }
    pcRef.current = null;
    micRef.current?.getTracks().forEach((t) => t.stop());
    micRef.current = null;
    setMuet(false);
    setEtatSon("");
    setSonBloque(false);
  }, []);

  // Crée la connexion WebRTC avec le micro ; le son reçu est joué dans <audio>
  const preparerConnexion = useCallback(async () => {
    const micro = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    micRef.current = micro;
    const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
    micro.getTracks().forEach((t) => pc.addTrack(t, micro));
    // Lot 94 — son du correspondant. Pour un appel SORTANT, la réponse SDP de WhatsApp ne déclare pas toujours
    // de « flux » (pas de ligne msid) : e.streams est alors VIDE et rien n'était branché sur le haut-parleur
    // (le contact décrochait mais on n'entendait rien). On crée donc le flux à partir de la piste reçue,
    // puis on lance la lecture explicitement (si le navigateur la bloque : bouton « Activer le son »).
    pc.ontrack = (e) => {
      const lecteur = audioRef.current;
      if (!lecteur) return;
      const flux = e.streams && e.streams[0] ? e.streams[0] : new MediaStream([e.track]);
      if (lecteur.srcObject !== flux) lecteur.srcObject = flux;
      // Lot 296 : haut-parleur choisi par l'utilisateur
      if (lireSortie() && lecteur.setSinkId) lecteur.setSinkId(lireSortie()).catch(() => { /* sortie disparue : celle du système */ });
      lecteur.play().then(() => setSonBloque(false)).catch(() => setSonBloque(true));
    };
    // Lot 94 — état de la liaison audio affiché dans le panneau de l'appel (aide au diagnostic)
    pc.onconnectionstatechange = () => setEtatSon(pc.connectionState);
    pcRef.current = pc;
    return pc;
  }, []);

  // Lot 296 — liste des haut-parleurs (les noms n'apparaissent qu'après l'autorisation du micro, donc pendant un appel)
  const actualiserSorties = useCallback(async () => {
    try {
      const liste = await navigator.mediaDevices.enumerateDevices();
      setSorties(liste.filter((d) => d.kind === "audiooutput"));
    } catch { setSorties([]); }
  }, []);
  useEffect(() => {
    actualiserSorties();
    navigator.mediaDevices?.addEventListener?.("devicechange", actualiserSorties);   // casque branché / débranché
    return () => navigator.mediaDevices?.removeEventListener?.("devicechange", actualiserSorties);
  }, [actualiserSorties]);

  const choisirSortie = async (id) => {
    setSortieId(id); ecrireSortie(id);
    try { if (audioRef.current?.setSinkId) await audioRef.current.setSinkId(id || ""); }
    catch { toast.error("Ce haut-parleur n'a pas pu être sélectionné."); }
  };
  const testerHautParleur = async () => {
    try { await bipTest(sortieId); toast.success("Bip joué sur le haut-parleur choisi : l'avez-vous entendu ?"); }
    catch { toast.error("Impossible de jouer le bip : vérifiez le volume et la sortie audio du PC."); }
  };

  // Lot 296 — témoin du son REÇU de WhatsApp (toutes les secondes pendant l'appel) : permet de savoir si le silence vient
  // de la liaison (aucun octet reçu) ou du haut-parleur (octets reçus mais rien d'audible)
  useEffect(() => {
    if (!appel) { setRecu(null); return undefined; }
    const t = setInterval(async () => {
      const pc = pcRef.current;
      if (!pc) return;
      try {
        const stats = await pc.getStats();
        stats.forEach((r) => {
          if (r.type === "inbound-rtp" && (r.kind === "audio" || r.mediaType === "audio")) {
            setRecu({ octets: r.bytesReceived || 0, niveau: typeof r.audioLevel === "number" ? r.audioLevel : null });
          }
        });
      } catch { /* statistiques indisponibles */ }
    }, 1000);
    return () => clearInterval(t);
  }, [appel]);

  // Interrogation régulière : appels qui sonnent + état de mon appel
  useEffect(() => {
    let actif = true;
    const lire = async () => {
      if (document.hidden) return;
      try {
        const r = await apiClient.get("/me/wa-appels/en-cours");
        if (!actif) return;
        setSonnent((r.data?.sonnent || []).filter((a) => !refusesRef.current.has(a.id)));
        const mien = r.data?.mon_appel || null;
        setAppel((precedent) => {
          // Appel terminé côté WhatsApp : on libère le micro
          if (precedent && !mien) fermerMedia();
          return mien;
        });
      } catch { /* hors connexion ou non autorisé : on réessaie plus tard */ }
    };
    lire();
    const t = setInterval(lire, INTERROGATION_MS);
    return () => { actif = false; clearInterval(t); };
  }, [fermerMedia]);

  // Sonnerie tant qu'un appel entrant attend et que l'utilisateur n'est pas déjà en ligne
  useEffect(() => {
    const doitSonner = sonnent.length > 0 && !appel;
    if (doitSonner && !sonnerieRef.current) sonnerieRef.current = demarrerSonnerie();
    if (!doitSonner && sonnerieRef.current) { sonnerieRef.current(); sonnerieRef.current = null; }
  }, [sonnent, appel]);
  useEffect(() => () => { sonnerieRef.current?.(); fermerMedia(); }, [fermerMedia]);

  // Chronomètre de l'appel en cours
  useEffect(() => {
    if (appel?.statut !== "en_cours") { setSecondes(0); return undefined; }
    const depart = appel.debut ? new Date(appel.debut).getTime() : Date.now();
    const t = setInterval(() => setSecondes(Math.floor((Date.now() - depart) / 1000)), 1000);
    return () => clearInterval(t);
  }, [appel?.statut, appel?.debut]);

  // Appel sortant : dès que WhatsApp renvoie la réponse SDP du client, on l'applique
  useEffect(() => {
    if (!appel || appel.direction !== "sortant" || !pcRef.current) return undefined;
    if (pcRef.current.remoteDescription) return undefined;
    let actif = true;
    const t = setInterval(async () => {
      try {
        const r = await apiClient.get(`/me/wa-appels/${encodeURIComponent(appel.id)}`);
        if (actif && r.data?.sdp_reponse && pcRef.current && !pcRef.current.remoteDescription) {
          await pcRef.current.setRemoteDescription({ type: "answer", sdp: r.data.sdp_reponse });
        }
      } catch (err) {
        // Lot 94 — réponse SDP refusée par le navigateur : signalée (avant, l'erreur était muette)
        if (err?.name && err.name !== "AxiosError") {
          console.warn("[appel WhatsApp] réponse SDP refusée :", err);
          setEtatSon("failed");
        }
      }
    }, 1500);
    return () => { actif = false; clearInterval(t); };
  }, [appel]);

  // DÉCROCHER un appel entrant
  const decrocher = async (a) => {
    setOccupe(true);
    try {
      const offre = await apiClient.get(`/me/wa-appels/${encodeURIComponent(a.id)}/offre`);
      const pc = await preparerConnexion();
      await pc.setRemoteDescription({ type: "offer", sdp: offre.data.sdp });
      const reponse = await pc.createAnswer();
      await pc.setLocalDescription(reponse);
      await attendreIce(pc);
      await apiClient.post(`/me/wa-appels/${encodeURIComponent(a.id)}/decrocher`, { sdp: pc.localDescription.sdp });
      setSonnent((l) => l.filter((x) => x.id !== a.id));
      setAppel({ ...a, statut: "en_cours", debut: new Date().toISOString() });
      window.dispatchEvent(new Event("sawali:appels-maj"));   // Lot 64.3 — fils de conversation à jour
    } catch (err) {
      fermerMedia();
      const msg = err?.name === "NotAllowedError"
        ? "Micro refusé : autorisez le micro dans le navigateur pour décrocher."
        : (err?.response?.data?.detail || err?.message || "Impossible de décrocher");
      toast.error(msg);
    } finally {
      setOccupe(false);
    }
  };

  // REFUSER un appel entrant
  const refuser = async (a) => {
    refusesRef.current.add(a.id);
    setSonnent((l) => l.filter((x) => x.id !== a.id));
    try { await apiClient.post(`/me/wa-appels/${encodeURIComponent(a.id)}/refuser`); }
    catch (err) { toast.error(err?.response?.data?.detail || "Refus impossible"); }
    window.dispatchEvent(new Event("sawali:appels-maj"));     // Lot 64.3 — fils de conversation à jour
  };

  // Ignorer (laisser sonner chez les collègues, sans refuser)
  const ignorer = (a) => {
    refusesRef.current.add(a.id);
    setSonnent((l) => l.filter((x) => x.id !== a.id));
  };

  // RACCROCHER
  const raccrocher = async () => {
    const id = appel?.id;
    fermerMedia();
    setAppel(null);
    if (id) {
      try { await apiClient.post(`/me/wa-appels/${encodeURIComponent(id)}/raccrocher`); }
      catch { /* l'appel est peut-être déjà terminé */ }
      window.dispatchEvent(new Event("sawali:appels-maj"));   // Lot 64.3 — fils de conversation à jour
    }
  };

  // Couper / rétablir le micro
  const basculerMicro = () => {
    const piste = micRef.current?.getAudioTracks()[0];
    if (!piste) return;
    piste.enabled = !piste.enabled;
    setMuet(!piste.enabled);
  };

  // APPEL SORTANT demandé depuis une conversation
  useEffect(() => {
    const surDemande = async (e) => {
      const { telephone, contact_id: contactId, nom } = e.detail || {};
      if (!telephone) return;
      if (appel) { toast.error("Terminez d'abord l'appel en cours."); return; }
      setOccupe(true);
      try {
        // 1. Le client a-t-il autorisé les appels ?
        const etat = (await apiClient.get("/me/wa-appels-permission", { params: { telephone } })).data || {};
        if (!etat.peut_appeler) {
          if (etat.peut_demander === false) {
            toast.error("Le client n'a pas encore autorisé les appels, et une demande a déjà été envoyée récemment (1 par 24 h, 2 par 7 jours).");
            return;
          }
          if (window.confirm(`${nom || telephone} n'a pas encore autorisé les appels WhatsApp.\n\nLui envoyer la demande d'autorisation maintenant ?`)) {
            await apiClient.post("/me/wa-appels-permission", { telephone, contact_id: contactId });
            toast.success("Demande d'autorisation envoyée. Vous pourrez appeler dès que le client l'aura acceptée.");
          }
          return;
        }
        // 2. Offre SDP du navigateur, puis lancement de l'appel par WhatsApp
        const pc = await preparerConnexion();
        const offre = await pc.createOffer({ offerToReceiveAudio: true });
        await pc.setLocalDescription(offre);
        await attendreIce(pc);
        const r = await apiClient.post("/me/wa-appels/appeler", { telephone, contact_id: contactId, sdp: pc.localDescription.sdp });
        setAppel({ id: r.data.id, direction: "sortant", statut: "appel", contact_nom: nom || telephone, telephone });
      } catch (err) {
        fermerMedia();
        const msg = err?.name === "NotAllowedError"
          ? "Micro refusé : autorisez le micro dans le navigateur pour appeler."
          : (err?.response?.data?.detail || err?.message || "Appel impossible");
        toast.error(msg);
      } finally {
        setOccupe(false);
      }
    };
    window.addEventListener("sawali:appel-wa", surDemande);
    return () => window.removeEventListener("sawali:appel-wa", surDemande);
  }, [appel, preparerConnexion, fermerMedia]);

  // JOURNAL des appels (tous, ou ceux d'un numéro)
  useEffect(() => {
    const ouvrir = async (e) => {
      const telephone = e.detail?.telephone || "";
      setJournal({ telephone, items: null, duree_totale_s: 0 });
      try {
        const r = await apiClient.get("/me/wa-appels", { params: telephone ? { telephone } : {} });
        setJournal({ telephone, items: r.data?.items || [], duree_totale_s: r.data?.duree_totale_s || 0 });
      } catch (err) {
        setJournal(null);
        toast.error(err?.response?.data?.detail || "Journal des appels indisponible");
      }
    };
    window.addEventListener("sawali:journal-appels", ouvrir);
    return () => window.removeEventListener("sawali:journal-appels", ouvrir);
  }, []);

  return (
    <>
      {/* Son du correspondant */}
      <audio ref={audioRef} autoPlay playsInline className="hidden" />

      {/* Cartes « Appel entrant » (en haut à droite) */}
      {!appel && sonnent.length > 0 && (
        <div className="fixed top-4 right-4 z-[1000] flex flex-col gap-2 w-[320px] max-w-[calc(100vw-32px)]" data-testid="appels-entrants">
          {sonnent.map((a) => (
            <div key={a.id} className="rounded-2xl bg-white shadow-2xl ring-2 ring-emerald-400 p-3" data-testid={`appel-entrant-${a.id}`}>
              <div className="flex items-center gap-2">
                <span className="flex h-9 w-9 items-center justify-center rounded-full bg-emerald-500 text-white">
                  <PhoneIncoming className="h-5 w-5" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-[11px] text-slate-500">Appel WhatsApp entrant</p>
                  <p className="truncate font-semibold text-slate-900">{a.contact_nom}</p>
                  <p className="text-[11px] text-slate-500">+{a.telephone}</p>
                </div>
                {a.ligne && <PastilleLigneWa libelle={a.ligne.libelle} fond={a.ligne.fond} texte={a.ligne.texte} />}
              </div>
              <div className="mt-3 flex gap-2">
                <button type="button" disabled={occupe} onClick={() => decrocher(a)}
                  className="flex-1 inline-flex items-center justify-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
                  data-testid={`appel-decrocher-${a.id}`}>
                  <Phone className="h-4 w-4" /> {occupe ? "Patientez…" : "Décrocher"}
                </button>
                <button type="button" onClick={() => refuser(a)}
                  className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-rose-600 px-3 py-2 text-sm font-semibold text-white hover:bg-rose-700"
                  data-testid={`appel-refuser-${a.id}`}>
                  <PhoneOff className="h-4 w-4" /> Refuser
                </button>
                <button type="button" onClick={() => ignorer(a)} title="Masquer (les collègues peuvent encore décrocher)"
                  className="rounded-lg px-2 text-slate-500 hover:bg-slate-100">
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Panneau de l'appel en cours */}
      {appel && (
        <div className="fixed bottom-4 right-4 z-[1000] w-[300px] max-w-[calc(100vw-32px)] rounded-2xl bg-slate-900 p-3 text-white shadow-2xl" data-testid="appel-en-cours">
          <div className="flex items-center gap-2">
            <span className={`flex h-9 w-9 items-center justify-center rounded-full ${appel.statut === "en_cours" ? "bg-emerald-500" : "bg-amber-500"}`}>
              {appel.direction === "sortant" ? <PhoneOutgoing className="h-5 w-5" /> : <Phone className="h-5 w-5" />}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate font-semibold">{appel.contact_nom}</p>
              <p className="text-xs text-slate-300">
                {appel.statut === "en_cours" ? `En ligne · ${dureeLisible(secondes)}` : (LIBELLES_STATUT[appel.statut] || "Connexion…")}
              </p>
              {/* Lot 94 — état de la liaison audio */}
              {etatSon && (
                <p className={`text-[11px] ${etatSon === "connected" ? "text-emerald-300" : etatSon === "failed" ? "text-rose-300" : "text-slate-400"}`}>
                  {{ new: "Son : préparation…", connecting: "Son : connexion…", connected: "Son : établi",
                     disconnected: "Son : coupé (réseau)", failed: "Son : échec de la liaison audio", closed: "Son : fermé" }[etatSon] || ""}
                </p>
              )}
            </div>
            {appel.ligne && <PastilleLigneWa libelle={appel.ligne.libelle} fond={appel.ligne.fond} texte={appel.ligne.texte} />}
          </div>
          {/* Lot 94 — lecture du son bloquée par le navigateur : un clic la relance */}
          {sonBloque && (
            <button type="button"
              onClick={() => audioRef.current?.play().then(() => setSonBloque(false)).catch(() => toast.error("Son toujours bloqué : vérifiez le volume et la sortie audio du PC."))}
              className="mt-3 w-full rounded-lg bg-emerald-500 px-3 py-2 text-sm font-semibold hover:bg-emerald-600">
              🔊 Activer le son
            </button>
          )}
          {/* Lot 296 — son reçu de WhatsApp + choix du haut-parleur + bip de test */}
          <div className="mt-3 rounded-lg bg-slate-800 p-2 text-[11px] space-y-1.5" data-testid="appel-sortie-audio">
            <p className={recu && recu.octets > 0 ? "text-emerald-300" : "text-amber-300"} data-testid="appel-son-recu">
              {recu === null ? "Son reçu : en attente…"
                : recu.octets > 0 ? `Son reçu de WhatsApp : ${Math.round(recu.octets / 1024)} Ko${recu.niveau !== null ? ` · niveau ${Math.round(recu.niveau * 100)} %` : ""}`
                : "Aucun son reçu de WhatsApp pour l'instant"}
            </p>
            {recu && recu.octets > 0 && recu.niveau !== null && (
              <div className="h-1.5 rounded bg-slate-700 overflow-hidden"><div className="h-full bg-emerald-400" style={{ width: `${Math.min(100, Math.round(recu.niveau * 300))}%` }} /></div>
            )}
            {sortieChoisissable() ? (
              <div className="flex gap-1.5 items-center">
                <Volume2 className="h-3.5 w-3.5 shrink-0 text-slate-300" />
                <select value={sortieId} onChange={(e) => choisirSortie(e.target.value)} data-testid="appel-choix-sortie"
                        className="min-w-0 flex-1 rounded bg-slate-700 px-1.5 py-1 text-white">
                  <option value="">Haut-parleur par défaut du système</option>
                  {sorties.filter((d) => d.deviceId && d.deviceId !== "default").map((d) => <option key={d.deviceId} value={d.deviceId}>{d.label || "Haut-parleur"}</option>)}
                </select>
                <button type="button" onClick={testerHautParleur} className="shrink-0 rounded bg-slate-600 px-2 py-1 hover:bg-slate-500" data-testid="appel-test-hp">Tester</button>
              </div>
            ) : (
              <p className="text-slate-400">Ce navigateur utilise toujours la sortie audio du système (choix possible sous Chrome ou Edge).</p>
            )}
          </div>
          <div className="mt-3 flex gap-2">
            <button type="button" onClick={basculerMicro}
              className={`flex-1 inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-sm font-semibold ${muet ? "bg-amber-500" : "bg-slate-700 hover:bg-slate-600"}`}>
              {muet ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />} {muet ? "Micro coupé" : "Micro"}
            </button>
            <button type="button" onClick={raccrocher}
              className="flex-1 inline-flex items-center justify-center gap-1.5 rounded-lg bg-rose-600 px-3 py-2 text-sm font-semibold hover:bg-rose-700"
              data-testid="appel-raccrocher">
              <PhoneOff className="h-4 w-4" /> Raccrocher
            </button>
          </div>
        </div>
      )}

      {/* Journal des appels */}
      {journal && (
        <div className="fixed inset-0 z-[1001] flex items-center justify-center bg-black/40 p-4" onClick={() => setJournal(null)}>
          <div className="max-h-[85vh] w-full max-w-2xl overflow-hidden rounded-2xl bg-white shadow-2xl flex flex-col" onClick={(e) => e.stopPropagation()} data-testid="journal-appels">
            <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
              <h3 className="font-semibold text-slate-900">
                📞 Journal des appels WhatsApp{journal.telephone ? ` — ${journal.telephone}` : ""}
              </h3>
              <button type="button" onClick={() => setJournal(null)} className="rounded p-1 hover:bg-slate-100"><X className="h-4 w-4" /></button>
            </div>
            <div className="overflow-auto">
              {journal.items === null ? (
                <p className="p-6 text-center text-sm text-slate-500">Patientez…</p>
              ) : journal.items.length === 0 ? (
                <p className="p-6 text-center text-sm text-slate-500">Aucun appel.</p>
              ) : (
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-xs text-slate-500">
                    <tr>
                      <th className="px-3 py-2 text-left">Date</th>
                      <th className="px-3 py-2 text-left">Sens</th>
                      <th className="px-3 py-2 text-left">Correspondant</th>
                      <th className="px-3 py-2 text-left">Ligne</th>
                      <th className="px-3 py-2 text-left">Statut</th>
                      <th className="px-3 py-2 text-right">Durée</th>
                      <th className="px-3 py-2 text-left">Agent</th>
                    </tr>
                  </thead>
                  <tbody>
                    {journal.items.map((a) => (
                      <React.Fragment key={a.id}>
                      {/* Lot 69 — un clic sur un appel pris par Liluvine déplie sa transcription */}
                      <tr className={`border-t border-slate-100 ${a.liluvine ? "cursor-pointer" : ""}`}
                        aria-selected={deplie === a.id ? "true" : undefined}
                        onClick={() => a.liluvine && setDeplie(deplie === a.id ? null : a.id)}>
                        <td className="px-3 py-2 whitespace-nowrap">{a.created_at ? new Date(a.created_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : ""}</td>
                        <td className="px-3 py-2">{a.direction === "sortant" ? "↗ Sortant" : "↙ Entrant"}</td>
                        <td className="px-3 py-2">
                          {a.contact_nom}
                          {/* Lot 67 — motif de l'appel (alerte message de Liluvine) et client concerné */}
                          {a.motif && (
                            <span className="block text-[11px] text-violet-700">
                              🔔 {a.motif}{a.alerte_client_nom ? ` · ${a.alerte_client_nom}` : ""}
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2">{a.ligne && <PastilleLigneWa libelle={a.ligne.libelle} fond={a.ligne.fond} texte={a.ligne.texte} />}</td>
                        <td className="px-3 py-2">
                          {LIBELLES_STATUT[a.statut] || a.statut}
                          {/* Lot 67 — résultat de l'alerte (décroché, sans réponse, échec + raison) */}
                          {a.resultat && <span className="block text-[11px] text-slate-500" title={a.raison || ""}>{a.resultat}{a.raison ? " — " + a.raison : ""}</span>}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">{a.duree_s ? dureeLisible(a.duree_s) : "—"}</td>
                        <td className="px-3 py-2">
                          {a.decroche_par_nom || "—"}
                          {a.liluvine && <span className="block text-[11px] text-violet-700">{deplie === a.id ? "▲ masquer" : "▼ transcription"}</span>}
                        </td>
                      </tr>
                      {deplie === a.id && a.liluvine && (
                        <tr className="bg-violet-50/40">
                          <td colSpan={7} className="px-3 py-2"><TranscriptionAppelLiluvine l={a.liluvine} /></td>
                        </tr>
                      )}
                      </React.Fragment>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            {journal.items?.length > 0 && (
              <div className="border-t border-slate-200 px-4 py-2 text-right text-sm text-slate-700">
                Durée totale des appels : <strong>{dureeLisible(journal.duree_totale_s)}</strong>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
