// =====================================================================
// Lot 131 — Contrôle à distance Loois : visionneuse plein écran du technicien SAWALI.
//
// Déroulé (voir backend/routes/controle_distance.py) :
//   1. POST /controle-distance/sessions        → la demande part vers le poste Loois ;
//   2. GET  /controle-distance/sessions/{sid}  → on attend l'accord de l'utilisateur du poste
//                                                 (le jeton du technicien n'est remis qu'une fois) ;
//   3. WebSocket /api/ws/controle-distance     → premier message {type:"auth", role:"technicien", …} ;
//      le poste envoie des tuiles JPEG (binaire), on les dessine sur un canvas ;
//      la souris et le clavier repartent en JSON (refusés par le serveur en mode « voir seulement »).
//
// Trame binaire d'une tuile : octet 0 = 1 ; puis u16 petit-boutiste : écran, x, y, largeur, hauteur ; puis le JPEG.
// =====================================================================
import React, { useCallback, useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  X, Maximize, Minimize, Monitor, Eye, MousePointer2, ClipboardPaste, RefreshCw, Keyboard, Activity, Gauge,
  Timer, Film, ArrowDownToLine, PenLine, Send, Handshake, Plug, TimerOff, ShieldX, CheckCircle2, WifiOff,
  RotateCcw, Lock,
} from "lucide-react";

const BACKEND = process.env.REACT_APP_BACKEND_URL || "";

// Adresse du relais WebSocket (même principe que hooks/useInternalChat.js)
function adresseRelais() {
  const base = BACKEND || window.location.origin;
  const proto = base.startsWith("https") ? "wss" : "ws";
  return `${proto}://${base.replace(/^https?:\/\//, "")}/api/ws/controle-distance`;
}

// Bouton de la souris (MouseEvent.button) → nom envoyé au poste
const BOUTONS = { 0: "gauche", 1: "milieu", 2: "droit" };

// Libellés des états de la session
const LIBELLES = {
  demande: "Demande envoyée au poste — en attente de l'accord de l'utilisateur…",
  connexion: "Accord reçu — connexion au poste…",
  attente_poste: "Connexion établie — en attente du poste…",
  active: "",
  refusee: "L'utilisateur du poste a refusé la prise en main.",
  expiree: "Le poste n'a pas répondu à temps (2 minutes).",
  terminee: "Session terminée.",
  erreur: "La connexion au poste a échoué.",
};

export default function ControleDistance({ posteId, posteNom, onClose }) {
  const [etat, setEtat] = useState("choix");          // choix → demande → connexion → attente_poste → active → terminee
  const [mode, setMode] = useState("controler");      // mode demandé puis mode accordé par le poste
  const [motif, setMotif] = useState("");             // motif de l'intervention (journal)
  const [ecrans, setEcrans] = useState([]);           // écrans du poste [{index, largeur, hauteur}]
  const [ecranActif, setEcranActif] = useState(0);
  const [qualite, setQualite] = useState(70);         // qualité JPEG demandée au poste
  const [stats, setStats] = useState({ ips: 0, latence: null, debit: 0 });
  const [pleinEcran, setPleinEcran] = useState(false);
  const [motifFin, setMotifFin] = useState("");

  const sessionRef = useRef(null);       // identifiant de la session
  const wsRef = useRef(null);            // WebSocket du relais
  const canvasRef = useRef(null);        // canvas où l'on dessine l'écran du poste
  const cadreRef = useRef(null);         // conteneur (pour le plein écran)
  const compteurRef = useRef({ images: 0, octets: 0, pingEnvoye: 0 });
  const modeRef = useRef(mode);
  const dernierMouvementRef = useRef(0); // limite l'envoi des déplacements de souris (~60 / s)
  modeRef.current = mode;

  // ---- Envoi d'une commande JSON au poste (via le relais) ----
  const envoyer = useCallback((message) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(message));
  }, []);

  // ---- Fermeture propre : prévient le serveur et ferme la connexion ----
  const arreter = useCallback(async (silencieux = false) => {
    const sid = sessionRef.current;
    try { envoyer({ type: "arreter" }); } catch { /* connexion déjà fermée */ }
    try { wsRef.current?.close(); } catch { /* noop */ }
    wsRef.current = null;
    sessionRef.current = null;            // arrête aussi l'attente de l'accord
    if (sid) {
      try { await apiClient.post(`/controle-distance/sessions/${sid}/arreter`); } catch { /* déjà terminée */ }
    }
    if (!silencieux) setEtat("terminee");
  }, [envoyer]);

  // Arrêt automatique si la visionneuse est fermée (démontage du composant)
  useEffect(() => () => { arreter(true); }, [arreter]);

  // ---- Dessin d'une tuile JPEG reçue du poste ----
  const dessinerTuile = useCallback(async (tampon) => {
    const vue = new DataView(tampon);
    if (vue.byteLength < 11 || vue.getUint8(0) !== 1) return;
    const x = vue.getUint16(3, true), y = vue.getUint16(5, true);
    const jpeg = new Blob([tampon.slice(11)], { type: "image/jpeg" });
    const canvas = canvasRef.current;
    if (!canvas) return;
    try {
      const image = await createImageBitmap(jpeg);
      // Le canvas prend la taille de l'écran du poste (annoncée par « ecrans » ou déduite des tuiles)
      if (canvas.width < x + image.width) canvas.width = x + image.width;
      if (canvas.height < y + image.height) canvas.height = y + image.height;
      canvas.getContext("2d").drawImage(image, x, y);
      image.close();
    } catch { /* tuile illisible : ignorée */ }
    compteurRef.current.images += 1;
    compteurRef.current.octets += tampon.byteLength;
  }, []);

  // ---- Connexion au relais avec le jeton à usage unique ----
  const connecter = useCallback((sid, jeton) => {
    setEtat("connexion");
    const ws = new WebSocket(adresseRelais());
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: "auth", role: "technicien", session_id: sid, jeton }));
    ws.onmessage = (ev) => {
      if (typeof ev.data !== "string") { dessinerTuile(ev.data); return; }
      let m;
      try { m = JSON.parse(ev.data); } catch { return; }
      if (m.type === "pret") { setMode(m.mode); setEtat("attente_poste"); }
      else if (m.type === "debut") { setEtat("active"); toast.success("Vous voyez l'écran du poste"); }
      else if (m.type === "ecrans") {
        const liste = Array.isArray(m.liste) ? m.liste : [];
        setEcrans(liste);
        const actif = liste.find((e) => e.index === (m.actif ?? 0)) || liste[0];
        if (actif && canvasRef.current) { canvasRef.current.width = actif.largeur; canvasRef.current.height = actif.hauteur; }
        if (actif) setEcranActif(actif.index);
      }
      else if (m.type === "pong") {
        const envoi = compteurRef.current.pingEnvoye;
        if (envoi) setStats((s) => ({ ...s, latence: Date.now() - envoi }));
      }
      else if (m.type === "presse_papiers" && typeof m.texte === "string") {
        navigator.clipboard?.writeText(m.texte).then(() => toast.info("Presse-papiers du poste copié"), () => {});
      }
      else if (m.type === "refuse") toast.warning(m.detail || "Commande refusée");
      else if (m.type === "erreur") { toast.error(m.detail || "Erreur du poste"); }
      else if (m.type === "fin") { setMotifFin(m.motif || ""); setEtat("terminee"); }
    };
    ws.onclose = () => { setEtat((e) => (e === "active" || e === "attente_poste" || e === "connexion" ? "terminee" : e)); };
    ws.onerror = () => setEtat((e) => (e === "connexion" ? "erreur" : e));
  }, [dessinerTuile]);

  // ---- 1. Demande de prise en main ----
  const demander = async (modeChoisi) => {
    setMode(modeChoisi);
    setEtat("demande");
    const attente = toast.loading("Patientez… demande envoyée au poste");
    try {
      const r = await apiClient.post("/controle-distance/sessions", { poste_id: posteId, mode: modeChoisi, motif });
      sessionRef.current = r.data.session_id;
    } catch (e) {
      toast.dismiss(attente);
      toast.error(e?.response?.data?.detail || "Demande impossible");
      setEtat("choix");
      return;
    }
    // 2. On interroge l'état toutes les 2 s jusqu'à l'accord, le refus ou l'expiration
    const sid = sessionRef.current;
    const limite = Date.now() + 130000;
    while (Date.now() < limite && sessionRef.current === sid) {
      await new Promise((ok) => setTimeout(ok, 2000));
      let s;
      try { s = (await apiClient.get(`/controle-distance/sessions/${sid}`)).data; } catch { continue; }
      if (s.statut === "acceptee" && s.jeton) {
        toast.dismiss(attente);
        setMode(s.mode);
        connecter(sid, s.jeton);
        return;
      }
      if (["refusee", "expiree", "terminee"].includes(s.statut)) {
        toast.dismiss(attente);
        setMotifFin(s.motif_fin || "");
        setEtat(s.statut);
        return;
      }
    }
    toast.dismiss(attente);
    setEtat("expiree");
  };

  // ---- Statistiques : images par seconde, débit et latence (ping toutes les 2 s) ----
  useEffect(() => {
    if (etat !== "active") return undefined;
    const t = setInterval(() => {
      const c = compteurRef.current;
      setStats((s) => ({ ...s, ips: Math.round(c.images / 2), debit: Math.round(c.octets / 2048) }));
      c.images = 0; c.octets = 0; c.pingEnvoye = Date.now();
      envoyer({ type: "ping" });
    }, 2000);
    return () => clearInterval(t);
  }, [etat, envoyer]);

  // ---- Position de la souris dans les pixels de l'écran du poste ----
  const position = (ev) => {
    const canvas = canvasRef.current;
    const r = canvas.getBoundingClientRect();
    return {
      x: Math.round(((ev.clientX - r.left) / r.width) * canvas.width),
      y: Math.round(((ev.clientY - r.top) / r.height) * canvas.height),
    };
  };
  const peutAgir = etat === "active" && mode === "controler";

  const souris = (action) => (ev) => {
    if (!peutAgir) return;
    if (action === "deplacer") {
      const t = performance.now();
      if (t - dernierMouvementRef.current < 16) return;   // ~60 déplacements par seconde au plus
      dernierMouvementRef.current = t;
    } else {
      ev.preventDefault();
      canvasRef.current?.focus();
    }
    envoyer({ type: "souris", action, bouton: BOUTONS[ev.button] || "gauche", ecran: ecranActif, ...position(ev) });
  };

  const molette = (ev) => {
    if (!peutAgir) return;
    envoyer({ type: "souris", action: "molette", delta: Math.round(-ev.deltaY), ecran: ecranActif, ...position(ev) });
  };

  // ---- Clavier : chaque touche (code physique + caractère) part vers le poste ----
  const clavier = (action) => (ev) => {
    if (!peutAgir) return;
    ev.preventDefault();
    envoyer({ type: "clavier", action, code: ev.code, touche: ev.key });
  };

  // Combinaison envoyée en un geste (Ctrl+Alt+Suppr n'est pas simulable par Windows : on propose le Gestionnaire)
  const combinaison = (codes) => {
    codes.forEach((code) => envoyer({ type: "clavier", action: "bas", code }));
    [...codes].reverse().forEach((code) => envoyer({ type: "clavier", action: "haut", code }));
  };

  // Coller le presse-papiers du technicien sur le poste (le texte est saisi au clavier sur le poste)
  const collerTexte = async () => {
    try {
      const texte = await navigator.clipboard.readText();
      if (texte) { envoyer({ type: "texte", texte }); toast.success("Texte envoyé au poste"); }
    } catch { toast.error("Le navigateur n'autorise pas la lecture du presse-papiers"); }
  };

  // ---- Plein écran du navigateur ----
  const basculerPleinEcran = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await cadreRef.current?.requestFullscreen();
    } catch { /* refusé par le navigateur */ }
  };
  useEffect(() => {
    const suivi = () => setPleinEcran(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", suivi);
    return () => document.removeEventListener("fullscreenchange", suivi);
  }, []);

  // ---- Habillage : chaque action est un pictogramme rond et coloré (infobulle au survol), sans bouton texte ----
  const picto = (couleur) =>
    `group relative grid h-9 w-9 place-items-center rounded-full ${couleur} text-white shadow-lg shadow-black/30 ` +
    "transition hover:scale-110 focus-visible:outline focus-visible:outline-2 focus-visible:outline-white disabled:pointer-events-none disabled:opacity-30";
  // Qualité : un seul pictogramme qui passe en revue basse → normale → haute (couleur = niveau)
  const NIVEAUX = [[40, "Qualité basse (connexion lente)", "bg-amber-500"], [70, "Qualité normale", "bg-sky-500"], [90, "Haute qualité", "bg-emerald-500"]];
  const niveau = NIVEAUX.find((n) => n[0] === qualite) || NIVEAUX[1];
  const qualiteSuivante = () => {
    const suivant = NIVEAUX[(NIVEAUX.indexOf(niveau) + 1) % NIVEAUX.length];
    setQualite(suivant[0]);
    envoyer({ type: "qualite", valeur: suivant[0] });
    toast.info(suivant[1]);
  };
  // Pictogramme usuel de la touche Windows (quatre carreaux)
  const IconeWindows = () => (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor" aria-hidden="true">
      <path d="M3 5.5 10.5 4.5v7H3zM11.5 4.4 21 3v8.5h-9.5zM3 12.5h7.5v7L3 18.5zM11.5 12.5H21V21l-9.5-1.4z" />
    </svg>
  );
  // Écrans d'attente et de fin : grand pictogramme dans un halo coloré
  const ECRANS_ETAT = {
    demande: [Send, "from-sky-500 to-indigo-600", true],
    connexion: [Handshake, "from-emerald-500 to-teal-600", true],
    attente_poste: [Plug, "from-violet-500 to-fuchsia-600", true],
    refusee: [ShieldX, "from-rose-500 to-red-700", false],
    expiree: [TimerOff, "from-slate-500 to-slate-700", false],
    terminee: [CheckCircle2, "from-emerald-500 to-green-700", false],
    erreur: [WifiOff, "from-orange-500 to-rose-600", false],
  };
  const fermer = async () => { await arreter(true); onClose?.(); };

  return (
    <div ref={cadreRef} className="fixed inset-0 z-[90] flex flex-col overflow-hidden bg-[radial-gradient(ellipse_at_top,_#1e3a8a_0%,_#0f172a_45%,_#020617_100%)] text-slate-100" data-testid="controle-distance">
      {/* ---- En-tête : poste, mode et mesures (pictogrammes) ---- */}
      <div className="flex flex-wrap items-center gap-2 px-4 pt-3">
        <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-sky-400 to-indigo-600 shadow-lg" aria-hidden="true">
          <Monitor className="h-5 w-5" />
        </span>
        <span className="text-sm font-semibold">{posteNom || "Poste Loois"}</span>
        {etat === "active" && (
          <span title={mode === "controler" ? "Vous contrôlez le poste" : "Vous voyez le poste sans agir"}
                className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ${mode === "controler" ? "bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-400/40" : "bg-amber-500/20 text-amber-300 ring-1 ring-amber-400/40"}`}>
            {mode === "controler" ? <><MousePointer2 className="h-3.5 w-3.5" /><Keyboard className="h-3.5 w-3.5" /></> : <Eye className="h-3.5 w-3.5" />}
          </span>
        )}
        {etat === "active" && (
          <span className="flex items-center gap-3 rounded-full bg-white/5 px-3 py-1 text-[11px] text-slate-300 ring-1 ring-white/10">
            <span className="inline-flex items-center gap-1" title="Images par seconde"><Film className="h-3.5 w-3.5 text-fuchsia-400" />{stats.ips}</span>
            <span className="inline-flex items-center gap-1" title="Latence aller-retour (ms)"><Timer className={`h-3.5 w-3.5 ${stats.latence > 250 ? "text-rose-400" : "text-emerald-400"}`} />{stats.latence ?? "—"}</span>
            <span className="inline-flex items-center gap-1" title="Débit reçu (Ko/s)"><ArrowDownToLine className="h-3.5 w-3.5 text-sky-400" />{stats.debit}</span>
          </span>
        )}
        <span className="ml-auto inline-flex items-center gap-1 text-[11px] text-slate-400" title="Connexion chiffrée, accord de l'utilisateur du poste, journal">
          <Lock className="h-3.5 w-3.5 text-emerald-400" />
        </span>
      </div>

      {/* ---- Dock d'actions (pictogrammes ronds et colorés) ---- */}
      <div className="mx-auto mt-2 flex flex-wrap items-center justify-center gap-2 rounded-2xl bg-white/5 px-3 py-2 ring-1 ring-white/10 backdrop-blur">
        {etat === "active" && ecrans.length > 1 && ecrans.map((e) => (
          <button key={e.index} type="button" title={`Écran ${e.index + 1} (${e.largeur}×${e.hauteur})`}
                  onClick={() => { setEcranActif(e.index); envoyer({ type: "choix_ecran", index: e.index }); }}
                  className={picto(e.index === ecranActif ? "bg-indigo-500 ring-2 ring-white" : "bg-indigo-900")}>
            <Monitor className="h-4 w-4" />
            <span className="absolute -bottom-1 -right-1 grid h-4 w-4 place-items-center rounded-full bg-white text-[9px] font-bold text-indigo-700">{e.index + 1}</span>
          </button>
        ))}
        {etat === "active" && (
          <>
            <button type="button" className={picto(niveau[2])} onClick={qualiteSuivante} title={`${niveau[1]} — cliquer pour changer`}><Gauge className="h-4 w-4" /></button>
            <button type="button" className={picto("bg-cyan-500")} onClick={() => envoyer({ type: "image_complete" })} title="Rafraîchir l'écran complet"><RefreshCw className="h-4 w-4" /></button>
            <button type="button" className={picto("bg-violet-500")} disabled={!peutAgir} onClick={collerTexte} title="Coller votre presse-papiers sur le poste"><ClipboardPaste className="h-4 w-4" /></button>
            <button type="button" className={picto("bg-pink-500")} disabled={!peutAgir} onClick={() => combinaison(["ControlLeft", "ShiftLeft", "Escape"])} title="Gestionnaire des tâches (Ctrl+Maj+Échap)"><Activity className="h-4 w-4" /></button>
            <button type="button" className={picto("bg-blue-600")} disabled={!peutAgir} onClick={() => combinaison(["MetaLeft"])} title="Touche Windows"><IconeWindows /></button>
          </>
        )}
        <button type="button" className={picto("bg-slate-600")} onClick={basculerPleinEcran} title={pleinEcran ? "Quitter le plein écran" : "Plein écran"}>
          {pleinEcran ? <Minimize className="h-4 w-4" /> : <Maximize className="h-4 w-4" />}
        </button>
        <button type="button" className={picto("bg-rose-600")} onClick={fermer} title="Arrêter la prise en main et fermer" data-testid="controle-distance-fermer">
          <X className="h-5 w-5" />
        </button>
      </div>

      {/* ---- Zone d'affichage ---- */}
      <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden p-3">
        {/* Choix du mode : deux grandes tuiles colorées ; un clic envoie directement la demande */}
        {etat === "choix" && (
          <div className="w-full max-w-xl">
            <label className="mx-auto flex max-w-md items-center gap-2 rounded-full bg-white/10 px-4 py-2 ring-1 ring-white/15 focus-within:ring-sky-400">
              <PenLine className="h-4 w-4 shrink-0 text-sky-300" aria-hidden="true" />
              <input value={motif} onChange={(e) => setMotif(e.target.value)} maxLength={200}
                     placeholder="Motif de l'intervention (facultatif)"
                     className="w-full bg-transparent text-sm outline-none placeholder:text-slate-400" />
            </label>
            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <button type="button" onClick={() => demander("controler")} data-testid="controle-distance-controler"
                      className="group rounded-3xl bg-gradient-to-br from-emerald-400 via-teal-500 to-cyan-600 p-6 text-left shadow-2xl shadow-emerald-900/40 transition hover:-translate-y-1 hover:shadow-emerald-500/30">
                <span className="flex gap-2"><MousePointer2 className="h-9 w-9" /><Keyboard className="h-9 w-9 opacity-80" /></span>
                <span className="mt-4 block text-lg font-bold">Contrôler</span>
                <span className="block text-xs text-white/80">Souris, clavier, écrans, presse-papiers</span>
              </button>
              <button type="button" onClick={() => demander("voir")} data-testid="controle-distance-voir"
                      className="group rounded-3xl bg-gradient-to-br from-amber-400 via-orange-500 to-rose-500 p-6 text-left shadow-2xl shadow-orange-900/40 transition hover:-translate-y-1 hover:shadow-orange-500/30">
                <Eye className="h-9 w-9" />
                <span className="mt-4 block text-lg font-bold">Voir seulement</span>
                <span className="block text-xs text-white/80">Aucune action sur le poste</span>
              </button>
            </div>
            <p className="mt-4 flex items-center justify-center gap-1.5 text-center text-[11px] text-slate-400">
              <Handshake className="h-3.5 w-3.5 text-emerald-400" aria-hidden="true" />
              L'utilisateur du poste accepte, voit un bandeau et peut arrêter à tout moment.
            </p>
          </div>
        )}

        {/* Attente et fin : grand pictogramme dans un halo coloré ; actions en pictogrammes */}
        {ECRANS_ETAT[etat] && (() => {
          const [Icone, degrade, enCours] = ECRANS_ETAT[etat];
          return (
            <div className="flex max-w-md flex-col items-center gap-4 text-center">
              <div className="relative grid h-28 w-28 place-items-center">
                {enCours && (
                  <svg className="absolute inset-0 h-28 w-28 animate-spin text-white/70" viewBox="0 0 50 50" aria-hidden="true">
                    <circle cx="25" cy="25" r="23" fill="none" stroke="currentColor" strokeOpacity="0.12" strokeWidth="2" />
                    <path d="M25 2 a23 23 0 0 1 23 23" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
                  </svg>
                )}
                <span className={`grid h-20 w-20 place-items-center rounded-full bg-gradient-to-br ${degrade} shadow-2xl`}>
                  <Icone className="h-10 w-10" aria-hidden="true" />
                </span>
              </div>
              <p className="text-sm text-slate-200">{LIBELLES[etat]}</p>
              {motifFin && <p className="text-xs text-slate-400">{motifFin}</p>}
              {!enCours && (
                <div className="flex gap-6">
                  <button type="button" onClick={() => { setMotifFin(""); setEtat("choix"); }} title="Nouvelle demande"
                          className="flex flex-col items-center gap-1 text-[11px] text-slate-300 hover:text-white">
                    <span className={picto("bg-sky-500")}><RotateCcw className="h-4 w-4" /></span>Recommencer
                  </button>
                  <button type="button" onClick={() => onClose?.()} title="Fermer"
                          className="flex flex-col items-center gap-1 text-[11px] text-slate-300 hover:text-white">
                    <span className={picto("bg-slate-600")}><X className="h-4 w-4" /></span>Fermer
                  </button>
                </div>
              )}
            </div>
          );
        })()}

        {/* Le canvas reste monté pour garder l'image entre deux rendus ; masqué hors session active */}
        <canvas
          ref={canvasRef}
          width={1280}
          height={720}
          tabIndex={0}
          className={`max-h-full max-w-full rounded-lg bg-black shadow-2xl shadow-black/60 ring-1 ring-white/10 outline-none ${etat === "active" ? "" : "hidden"} ${peutAgir ? "cursor-crosshair" : "cursor-default"}`}
          style={{ objectFit: "contain" }}
          onMouseMove={souris("deplacer")}
          onMouseDown={souris("bas")}
          onMouseUp={souris("haut")}
          onWheel={molette}
          onContextMenu={(e) => e.preventDefault()}
          onKeyDown={clavier("bas")}
          onKeyUp={clavier("haut")}
          data-testid="controle-distance-ecran"
        />
      </div>
    </div>
  );
}
