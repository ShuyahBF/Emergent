// =====================================================================
// Lot 131 — Contrôle à distance Loois : visionneuse du technicien SAWALI.
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
//
// Lot 135 (propriétaire, 12/10/2026) — extensions :
//   - fichiers : glisser-déposer sur l'écran = envoi au poste ; volet « Fichiers » = récupération depuis le poste ;
//   - échelle de l'image (connexions lentes), capture DXGI signalée, cadence adaptée côté poste ;
//   - écran de connexion / verrouillé : fiche « service Windows » du poste (agent système) ;
//   - onglets (plusieurs postes, voir ControleDistanceOnglets.jsx) et vidéo de la session envoyée au journal ;
//   - clavier virtuel, blocage du clavier et de la souris du poste, actions système (déconnecter, verrouiller,
//     redémarrer, éteindre, Ctrl+Alt+Suppr) avec confirmation ;
//   Lot 142 : les pictogrammes d'action forment une barre VERTICALE à gauche de l'écran du poste (plus de place pour l'image) ;
//   - identifiant Windows mémorisé (saisi par le SERVEUR sur le poste, jamais montré ici) ;
//   - mesures de la session (1re image, latence, images/s, débit) envoyées au journal à la fin ;
//   - numéro « CD-… », client et ticket automatique ; volet repliable : caractéristiques, performances, chat.
// =====================================================================
import React, { useCallback, useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  X, Maximize, Minimize, Monitor, Eye, EyeOff, MousePointer2, ClipboardPaste, RefreshCw, Keyboard, Activity, Gauge,
  Timer, Film, ArrowDownToLine, PenLine, Send, Handshake, Plug, TimerOff, ShieldX, CheckCircle2, WifiOff,
  RotateCcw, Lock, UserX, Power, KeyRound, Ban, PanelRightOpen, PanelRightClose, Scaling, Upload, ServerCog,
  Ticket, Circle, ShieldAlert, Cpu, Loader2,
} from "lucide-react";
import ClavierVirtuel from "@/components/controleDistance/ClavierVirtuel";
import VoletPoste from "@/components/controleDistance/VoletPoste";
import {
  TRAME_TUILE, TRAME_FICHIER_VERS_TECHNICIEN, TAILLE_MAX_FICHIER, envoyerFichier, lireTrameFichier, telecharger,
  mesuresFinales, ACTIONS_SYSTEME, ACTIONS_MAINTENANCE, registrePostes, tailleLisible,
} from "@/components/controleDistance/outils";
// Lot 281 : reprise et historique des transferts de fichiers
import {
  clePartiel, debutReception, departDemande, effacerTransferts, interrompre, oublierPartiels, partielsReception,
} from "@/components/controleDistance/transferts";

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

// Lot 135 — échelles proposées (connexions lentes : moins de pixels à envoyer)
const ECHELLES = [[100, "Taille réelle"], [75, "Image à 75 %"], [50, "Image à 50 % (connexion lente)"], [25, "Image à 25 % (très lente)"]];

// Conseils affichés dans la boîte de dialogue d'échec, selon le message reçu (le détail du poste est toujours montré tel quel)
function conseilEchec(detail) {
  const t = String(detail || "").toLowerCase();
  if (t.includes("verrouill") || t.includes("écran du poste indisponible")) {
    return "Le poste ne peut pas capturer son écran : la session Windows est probablement verrouillée, déconnectée ou sur l'écran de connexion. "
      + "Sur un Windows Server, une session Bureau à distance fermée sans « Se déconnecter » reste déconnectée. "
      + "Solutions : ouvrir la session sur le poste, ou installer le service Windows Loois (il permet la prise en main écran verrouillé), puis réessayer.";
  }
  if (t.includes("refus")) return "Le poste (ou son utilisateur) a refusé la prise en main.";
  if (t.includes("liaison") || t.includes("connexion")) return "Vérifiez que Loois est lancé sur le poste, qu'il a Internet, puis réessayez.";
  return "";
}

export default function ControleDistance({ posteId, posteNom, onClose, embedded = false, visible = true, onEtat, onOuvrirPoste }) {
  const [etat, setEtat] = useState("choix");          // choix → demande → connexion → attente_poste → active → terminee
  const [mode, setMode] = useState("controler");      // mode demandé puis mode accordé par le poste
  const [motif, setMotif] = useState("");             // motif de l'intervention (journal)
  const [ecrans, setEcrans] = useState([]);           // écrans du poste [{index, largeur, hauteur}]
  const [ecranActif, setEcranActif] = useState(0);
  const [qualite, setQualite] = useState(85);         // qualité JPEG demandée au poste (85 par défaut depuis le lot 141 : texte plus net)
  const [stats, setStats] = useState({ ips: 0, latence: null, debit: 0 });
  const [pleinEcran, setPleinEcran] = useState(false);
  const [motifFin, setMotifFin] = useState("");
  // Échec de connexion : boîte de dialogue propre à l'onglet, qui reste affichée jusqu'au clic sur « Compris »
  // (le toast disparaissait trop vite pour être lu). { detail, conseil } ou null.
  const [echec, setEchec] = useState(null);
  // Lot 131.1 — poste sans surveillance (clé LKS-) : il accepte seul, sans bandeau ; réservé au super-admin
  const [sansSurveillance, setSansSurveillance] = useState(false);
  // Lot 135 — fiche du poste (service Windows, chat, client, identifiant mémorisé), réglages, numéro et ticket
  const [fiche, setFiche] = useState(null);
  const [reglages, setReglages] = useState({ enregistrement_video: true, video_ips: 5 });
  const [clients, setClients] = useState([]);
  const [clientChoisi, setClientChoisi] = useState("");
  const [numero, setNumero] = useState("");
  const [ticket, setTicket] = useState("");
  // Lot 135 — affichage et outils
  const [echelle, setEchelle] = useState(100);
  const [clavierOuvert, setClavierOuvert] = useState(false);
  const [voletOuvert, setVoletOuvert] = useState(false);
  const [ongletVolet, setOngletVolet] = useState("poste");
  const [infos, setInfos] = useState(null);           // inventaire envoyé par le poste
  const [perf, setPerf] = useState(null);             // performances (toutes les 2 s)
  const [bureau, setBureau] = useState(null);         // {nom, securise, session_ouverte}
  const [moteur, setMoteur] = useState("");           // « dxgi » ou « gdi »
  const [entreesBloquees, setEntreesBloquees] = useState(false);
  const [menuSysteme, setMenuSysteme] = useState(false);
  const [confirmation, setConfirmation] = useState(null);   // action système à confirmer
  // Lot 282 : fenêtre « Modifier le ticket » (motif + note de rappel) et rappel laissé à la dernière intervention sur ce poste
  const [ticketEdition, setTicketEdition] = useState(null);   // {motif, note} pendant la saisie
  const [rappelMasque, setRappelMasque] = useState(false);
  // Lot 140 : maintenance du disque (outils Windows) — confirmation {action, volume} et avancement des tâches {id, action, libelle, volume, etat, resume}
  const [confirmationMaint, setConfirmationMaint] = useState(null);
  const [maintenances, setMaintenances] = useState([]);
  const [identifiantsOuvert, setIdentifiantsOuvert] = useState(false);
  const [listeFichiers, setListeFichiers] = useState(null);
  const [transferts, setTransferts] = useState([]);
  const [survolDepot, setSurvolDepot] = useState(false);
  const [enregistre, setEnregistre] = useState(false);
  // Lot 135 — dossiers des transferts mémorisés pour ce poste : dossier de base + dernier dossier parcouru
  const [dossiers, setDossiers] = useState({ dossier_base: "", dernier_chemin: "" });

  const chargerFiche = useCallback(async () => {
    if (!posteId) return;
    try {
      const r = await apiClient.get(`/controle-distance/postes/${encodeURIComponent(posteId)}`);
      setFiche(r.data);
      setSansSurveillance(Boolean(r.data?.sans_surveillance));
      if (!r.data?.client_id) {
        apiClient.get("/support-loois/clients").then((c) => setClients(c.data || [])).catch(() => {});
      }
    } catch { /* fiche indisponible : la prise en main reste possible */ }
  }, [posteId]);
  useEffect(() => {
    chargerFiche();
    apiClient.get("/controle-distance/reglages").then((r) => setReglages(r.data || {})).catch(() => {});
    if (posteId) {
      apiClient.get(`/controle-distance/postes/${encodeURIComponent(posteId)}/dossiers`)
        .then((r) => { setDossiers(r.data); dernierCheminRef.current = r.data.dernier_chemin || ""; }).catch(() => {});
    }
  }, [chargerFiche, posteId]);

  const sessionRef = useRef(null);       // identifiant de la session
  const wsRef = useRef(null);            // WebSocket du relais
  const canvasRef = useRef(null);        // canvas où l'on dessine l'écran du poste
  const cadreRef = useRef(null);         // conteneur (pour le plein écran)
  const compteurRef = useRef({ images: 0, octets: 0, pingEnvoye: 0 });
  const mesuresRef = useRef(null);       // lot 135 : mesures de la session (latences, images/s, 1re image…)
  const modeRef = useRef(mode);
  const dernierMouvementRef = useRef(0); // limite l'envoi des déplacements de souris (~60 / s)
  const enregistreurRef = useRef(null);  // lot 135 : MediaRecorder de la vidéo
  const partieVideoRef = useRef(0);
  const receptionsRef = useRef(new Map());   // lot 135 : fichiers reçus du poste en cours {id → {nom, taille, morceaux, recu}}
  const prochainFichierRef = useRef(1);
  const demandesRef = useRef([]);        // lots 135 et 281 : pour chaque fichier demandé au poste (dans l'ordre) : { destination (autre poste ou null = téléchargement), cle, chemin, uid }
  const connexionRef = useRef(0);        // lot 281 : numéro de la connexion en cours (les identifiants de fichier du poste redémarrent à 1 à chaque prise en main)
  const uidRef = useRef(0);              // lot 281 : identifiant UNIQUE de chaque ligne de l'historique des transferts
  const envoisRef = useRef(new Map());   // lot 281 : identifiant de fichier envoyé → uid de la ligne (connexion en cours)
  const pretsRef = useRef(new Map());    // lot 281 : réponses « fichier_pret » attendues pour une reprise d'envoi (id → fonction)
  const dernierCheminRef = useRef("");   // lot 135 : dernier dossier parcouru, mémorisé à la fermeture
  const cheminEnregistreRef = useRef("");
  const moteurRef = useRef("");
  const echelleRef = useRef(100);
  modeRef.current = mode;
  moteurRef.current = moteur;
  echelleRef.current = echelle;

  // Lot 135 — l'onglet qui héberge la visionneuse suit son état (pastille de couleur)
  useEffect(() => { onEtat?.(etat); }, [etat, onEtat]);

  // ---- Envoi d'une commande JSON au poste (via le relais) ----
  // Affiche l'échec dans la boîte de dialogue de l'onglet (reste jusqu'au clic sur « Compris »)
  const signalerEchec = useCallback((detail) => {
    setEchec({ detail: String(detail || "Erreur du poste"), conseil: conseilEchec(detail) });
  }, []);

  const envoyer = useCallback((message) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(message));
  }, []);

  // ---- Lot 135 : fin de l'enregistrement vidéo (la dernière partie part au serveur) ----
  const arreterVideo = useCallback(() => {
    const rec = enregistreurRef.current;
    enregistreurRef.current = null;
    try { if (rec && rec.state !== "inactive") rec.stop(); } catch { /* déjà arrêté */ }
    setEnregistre(false);
  }, []);

  // ---- Lot 135 : mesures de la session envoyées une fois, à la fin ----
  const envoyerMesures = useCallback((sid) => {
    const c = mesuresRef.current;
    mesuresRef.current = null;
    if (!sid || !c) return;
    apiClient.post(`/controle-distance/sessions/${sid}/mesures`, mesuresFinales(c, moteurRef.current, echelleRef.current)).catch(() => {});
  }, []);

  // ---- Lot 135 : dernier dossier parcouru, mémorisé pour ce poste (repris à la prochaine ouverture) ----
  const memoriserDernierChemin = useCallback(() => {
    const chemin = dernierCheminRef.current;
    if (!posteId || !chemin || chemin === cheminEnregistreRef.current) return;
    cheminEnregistreRef.current = chemin;
    apiClient.put(`/controle-distance/postes/${encodeURIComponent(posteId)}/dossiers`, { dernier_chemin: chemin }).catch(() => {});
  }, [posteId]);

  // ---- Fermeture propre : prévient le serveur et ferme la connexion ----
  const arreter = useCallback(async (silencieux = false) => {
    const sid = sessionRef.current;
    memoriserDernierChemin();
    arreterVideo();
    envoyerMesures(sid);
    try { envoyer({ type: "arreter" }); } catch { /* connexion déjà fermée */ }
    try { wsRef.current?.close(); } catch { /* noop */ }
    wsRef.current = null;
    sessionRef.current = null;            // arrête aussi l'attente de l'accord
    if (sid) {
      try { await apiClient.post(`/controle-distance/sessions/${sid}/arreter`); } catch { /* déjà terminée */ }
    }
    if (!silencieux) setEtat("terminee");
  }, [envoyer, arreterVideo, envoyerMesures, memoriserDernierChemin]);

  // Arrêt automatique si la visionneuse est fermée (démontage du composant)
  useEffect(() => () => { arreter(true); }, [arreter]);

  // Lot 135 — fin de session côté poste ou serveur : vidéo et mesures bouclées
  useEffect(() => {
    if (["terminee", "erreur"].includes(etat)) {
      memoriserDernierChemin();
      arreterVideo();
      envoyerMesures(sessionRef.current);
    }
  }, [etat, arreterVideo, envoyerMesures, memoriserDernierChemin]);

  // ---- Dessin d'une tuile JPEG reçue du poste ----
  const dessinerTuile = useCallback(async (tampon) => {
    const vue = new DataView(tampon);
    if (vue.byteLength < 11 || vue.getUint8(0) !== TRAME_TUILE) return;
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
    // Lot 135 : délai de la première image et volume reçu (mesures de fin de session)
    const m = mesuresRef.current;
    if (m) {
      m.octetsTotal += tampon.byteLength;
      if (m.premiereImageMs === null && m.tDebut) m.premiereImageMs = performance.now() - m.tDebut;
    }
  }, []);

  // ---- Lot 135 : morceau d'un fichier envoyé par le poste (trame de type 3) ----
  // Lot 281 : les morceaux s'ajoutent au « partiel » gardé en mémoire (reprise possible si la liaison tombe)
  const majTransfert = useCallback((uid, patch) => {
    setTransferts((liste) => liste.map((x) => (x.uid === uid ? { ...x, ...(typeof patch === "function" ? patch(x) : patch) } : x)));
  }, []);

  const recevoirMorceau = useCallback((tampon) => {
    const t = lireTrameFichier(tampon);
    if (!t) return;
    const r = receptionsRef.current.get(t.id);
    if (!r) return;
    r.partiel.morceaux.push(t.donnees);
    r.partiel.recu += t.donnees.byteLength;
    const fait = r.partiel.recu;
    setTransferts((liste) => liste.map((x) => (x.uid === r.uid ? { ...x, fait } : x)));
  }, []);

  // ---- Lot 135 : messages JSON du poste ----
  const traiterMessage = useCallback((m) => {
    if (m.type === "pret") { setMode(m.mode); setEtat("attente_poste"); }
    else if (m.type === "debut") {
      setEtat("active");
      toast.success("Vous voyez l'écran du poste");
      mesuresRef.current = { tDebut: performance.now(), premiereImageMs: null, latences: [], ips: [], octetsTotal: 0, debutAffichage: Date.now() };
    }
    else if (m.type === "ecrans") {
      const liste = Array.isArray(m.liste) ? m.liste : [];
      setEcrans(liste);
      const actif = liste.find((e) => e.index === (m.actif ?? 0)) || liste[0];
      if (actif && canvasRef.current) { canvasRef.current.width = actif.largeur; canvasRef.current.height = actif.hauteur; }
      if (actif) setEcranActif(actif.index);
    }
    else if (m.type === "pong") {
      const envoi = compteurRef.current.pingEnvoye;
      if (envoi) {
        const latence = Date.now() - envoi;
        setStats((s) => ({ ...s, latence }));
        mesuresRef.current?.latences.push(latence);
      }
    }
    else if (m.type === "presse_papiers" && typeof m.texte === "string") {
      navigator.clipboard?.writeText(m.texte).then(() => toast.info("Presse-papiers du poste copié"), () => {});
    }
    else if (m.type === "infos_poste") setInfos(m);
    else if (m.type === "perf") setPerf(m);
    else if (m.type === "bureau") setBureau(m);
    else if (m.type === "capture") setMoteur(m.moteur || "");
    else if (m.type === "entrees_bloquees") { setEntreesBloquees(Boolean(m.valeur)); if (m.detail) toast.info(m.detail); }
    else if (m.type === "maintenance_etat") {
      // Lot 140 : avancement d'une maintenance du disque (une ligne par tâche, la dernière information remplace la précédente)
      setMaintenances((liste) => {
        const reste = liste.filter((x) => x.id !== m.id);
        return [...reste, { id: m.id, action: m.action, libelle: m.libelle, volume: m.volume, etat: m.etat, resume: m.resume || "" }].slice(-6);
      });
      if (m.etat === "termine") toast.success(`${m.libelle} (${m.volume}) : terminé`);
      else if (m.etat === "echec") toast.error(`${m.libelle} (${m.volume}) : ${(m.resume || "échec").split("\n")[0]}`);
    }
    else if (m.type === "systeme_resultat") (m.ok ? toast.success : toast.error)(m.detail || "Action système");
    else if (m.type === "fichiers_liste") {
      setListeFichiers(m);
      if (m.chemin && !m.erreur) dernierCheminRef.current = m.chemin;   // lot 135 : mémorisé à la fermeture
    }
    else if (m.type === "fichier_recu") {
      // Accusé du poste pour un fichier ENVOYÉ (lot 281 : la ligne est retrouvée par son identifiant unique)
      const uid = envoisRef.current.get(m.id);
      const reprise = !m.ok && String(m.detail || "").includes("reprise possible");
      if (uid !== undefined) {
        majTransfert(uid, (x) => ({ fini: Boolean(m.ok), erreur: m.ok ? "" : (m.detail || "refusé"), chemin: m.chemin || "",
                                    interrompu: reprise, reprenable: reprise && Boolean(x.fichier) }));
      }
      if (m.ok) toast.success(`Fichier déposé sur le poste : ${m.chemin}`); else toast.error(m.detail || "Fichier refusé par le poste");
    }
    else if (m.type === "fichier_pret") pretsRef.current.get(m.id)?.(Number(m.octets) || 0);   // lot 281 : reprise d'un envoi
    else if (m.type === "fichier_debut") {
      // Lots 135 et 281 : fichier demandé au poste ; destination choisie (autre poste contrôlé) ou téléchargement (null) ;
      // le partiel déjà reçu est CONTINUÉ si le poste reprend exactement à sa position
      const dem = demandesRef.current.shift() || { destination: null, cle: clePartiel(posteId, m.nom), chemin: "" };
      const { partiel } = debutReception(partielsReception, dem.cle, m);
      const uid = dem.uid ?? ++uidRef.current;
      receptionsRef.current.set(m.id, { uid, cle: dem.cle, partiel, destination: dem.destination });
      const ligne = { uid, sens: "reception", id: m.id, cx: connexionRef.current, nom: m.nom, taille: m.taille, fait: partiel.recu,
                      cle: dem.cle, chemin: dem.chemin, destination: dem.destination, fini: false, erreur: "", interrompu: false, reprenable: false };
      setTransferts((liste) => (liste.some((x) => x.uid === uid) ? liste.map((x) => (x.uid === uid ? { ...x, ...ligne } : x)) : [...liste, ligne]));
    }
    else if (m.type === "fichier_fin") {
      const r = receptionsRef.current.get(m.id);
      receptionsRef.current.delete(m.id);
      if (!r) demandesRef.current.shift();   // échec avant tout envoi : la demande est abandonnée
      const complet = Boolean(r && m.ok && r.partiel.recu === r.partiel.taille);
      if (complet) {
        const contenu = new Blob(r.partiel.morceaux);
        partielsReception.delete(r.cle);   // terminé : plus rien à reprendre
        if (r.destination) {
          // Lot 135 : copie de poste à poste — le fichier part vers le poste de l'autre onglet
          r.destination.recevoir(contenu, r.partiel.nom)
            .then(() => toast.success(`${r.partiel.nom} copié vers ${r.destination.nom}`))
            .catch(() => toast.error(`Copie vers ${r.destination.nom} impossible (prise en main fermée ?)`));
        } else {
          telecharger(contenu, r.partiel.nom);
          toast.success(`Fichier récupéré : ${r.partiel.nom}`);
        }
      } else if (m.detail) toast.error(m.detail);
      if (r) {
        // Échec : les octets déjà reçus sont gardés, « Reprendre » demandera la fin du fichier
        majTransfert(r.uid, () => ({ fini: complet, erreur: complet ? "" : (m.detail || "échec"), fait: r.partiel.recu,
                                      interrompu: !complet, reprenable: !complet && r.partiel.recu > 0 && r.partiel.recu < r.partiel.taille }));
      }
    }
    else if (m.type === "info") toast.info(m.detail || "");
    else if (m.type === "refuse") toast.warning(m.detail || "Commande refusée");
    else if (m.type === "erreur") { signalerEchec(m.detail || "Erreur du poste"); }
    else if (m.type === "fin") { setMotifFin(m.motif || ""); setEtat("terminee"); }
  }, [signalerEchec, majTransfert, posteId]);

  // ---- Connexion au relais avec le jeton à usage unique ----
  const connecter = useCallback((sid, jeton) => {
    setEtat("connexion");
    // Lot 281 : nouvelle connexion → les identifiants de fichier du poste repartent de 1 : on oublie ceux de la précédente
    connexionRef.current += 1;
    envoisRef.current.clear(); pretsRef.current.clear(); receptionsRef.current.clear(); demandesRef.current = [];
    const ws = new WebSocket(adresseRelais());
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: "auth", role: "technicien", session_id: sid, jeton }));
    ws.onmessage = (ev) => {
      if (typeof ev.data !== "string") {
        // Lot 135 : octet 0 = type de trame (1 = tuile de l'écran, 3 = morceau de fichier)
        const type = ev.data.byteLength ? new DataView(ev.data).getUint8(0) : 0;
        if (type === TRAME_FICHIER_VERS_TECHNICIEN) recevoirMorceau(ev.data);
        else dessinerTuile(ev.data);
        return;
      }
      let m;
      try { m = JSON.parse(ev.data); } catch { return; }
      traiterMessage(m);
    };
    ws.onclose = () => {
      setEtat((e) => (e === "active" || e === "attente_poste" || e === "connexion" ? "terminee" : e));
      // Lot 281 : la liaison est tombée → les transferts en cours deviennent « interrompus » (reprenables à la prochaine prise en main)
      setTransferts((liste) => interrompre(liste));
    };
    ws.onerror = () => setEtat((e) => {
      if (e === "connexion") signalerEchec("Connexion au poste impossible (liaison interrompue avant l'ouverture de l'écran).");
      return e === "connexion" ? "erreur" : e;
    });
  }, [dessinerTuile, recevoirMorceau, traiterMessage]);

  // ---- 1. Demande de prise en main ----
  const demander = async (modeChoisi) => {
    setMode(modeChoisi);
    setEchec(null);
    setEtat("demande");
    setInfos(null); setPerf(null); setBureau(null); setMaintenances([]); setListeFichiers(null); setEntreesBloquees(false); setTicket("");
    setRappelMasque(false); chargerFiche();   // lot 282 : le rappel laissé à la prise en main précédente est relu et affiché
    const attente = toast.loading("Patientez… demande envoyée au poste");
    try {
      const r = await apiClient.post("/controle-distance/sessions", {
        poste_id: posteId, mode: modeChoisi, motif, client_id: clientChoisi || undefined,
      });
      sessionRef.current = r.data.session_id;
      setNumero(r.data.numero || "");
    } catch (e) {
      toast.dismiss(attente);
      signalerEchec(e?.response?.data?.detail || "Demande impossible");
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
    if (sessionRef.current === sid) setEtat("expiree");
  };

  // ---- Statistiques : images par seconde, débit et latence (ping toutes les 2 s) ; numéro de ticket ----
  useEffect(() => {
    if (etat !== "active") return undefined;
    const t = setInterval(() => {
      const c = compteurRef.current;
      const ips = Math.round(c.images / 2);
      setStats((s) => ({ ...s, ips, debit: Math.round(c.octets / 2048) }));
      mesuresRef.current?.ips.push(c.images / 2);
      c.images = 0; c.octets = 0; c.pingEnvoye = Date.now();
      envoyer({ type: "ping" });
    }, 2000);
    // Lot 135 : le ticket est créé par le serveur au début de la session
    const sid = sessionRef.current;
    const lireTicket = setTimeout(() => {
      if (sid) apiClient.get(`/controle-distance/sessions/${sid}`).then((r) => setTicket(r.data.ticket_number || "")).catch(() => {});
    }, 1500);
    return () => { clearInterval(t); clearTimeout(lireTicket); };
  }, [etat, envoyer]);

  // ---- Lot 135 : enregistrement vidéo de la session (parties de 30 s envoyées au serveur) ----
  useEffect(() => {
    if (etat !== "active" || !reglages.enregistrement_video || enregistreurRef.current) return;
    const sid = sessionRef.current;
    const canvas = canvasRef.current;
    if (!sid || !canvas?.captureStream || typeof MediaRecorder === "undefined") return;
    try {
      const flux = canvas.captureStream(Math.max(1, Math.min(15, reglages.video_ips || 5)));
      const types = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"];
      const mimeType = types.find((t) => MediaRecorder.isTypeSupported?.(t)) || "";
      const rec = new MediaRecorder(flux, { ...(mimeType ? { mimeType } : {}), videoBitsPerSecond: 300000 });
      partieVideoRef.current = 0;
      rec.ondataavailable = (ev) => {
        if (!ev.data || !ev.data.size) return;
        const index = partieVideoRef.current++;
        apiClient.post(`/controle-distance/sessions/${sid}/video/${index}`, ev.data, { headers: { "Content-Type": "video/webm" } })
          .catch(() => { if (index === 0) toast.warning("Vidéo non enregistrée (stockage indisponible)"); });
      };
      rec.start(30000);
      enregistreurRef.current = rec;
      setEnregistre(true);
    } catch { /* navigateur sans enregistrement vidéo : la prise en main continue */ }
  }, [etat, reglages]);

  // ---- Position de la souris dans les pixels de l'image (à l'échelle : Loois convertit en pixels réels) ----
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

  // Combinaison envoyée en un geste (Ctrl+Alt+Suppr passe par le menu des actions système)
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

  // ---- Lot 135 : fichiers déposés sur l'écran du poste → envoyés au poste ----
  const deposer = async (ev) => {
    ev.preventDefault();
    setSurvolDepot(false);
    if (!peutAgir) { toast.warning("Envoi de fichiers : prise en main en mode « Contrôler » seulement"); return; }
    const fichiers = Array.from(ev.dataTransfer?.files || []);
    for (const f of fichiers) {
      if (f.size > TAILLE_MAX_FICHIER) { toast.error(`${f.name} : 2 Go au plus`); continue; }
      setVoletOuvert(true);
      setOngletVolet("fichiers");
      await envoyerAuPoste(f);
    }
  };

  // ---- Lot 135 : envoi d'un fichier à CE poste (dépôt ou copie depuis un autre poste), dans le dossier de base ----
  const dossierBaseRef = useRef("");
  dossierBaseRef.current = dossiers.dossier_base;
  // Lot 281 : chaque envoi a sa ligne (uid unique) ; avec `reprise`, le poste dit combien d'octets il a déjà et l'envoi repart de là
  // (poste sans reprise : nouvelle tentative depuis le début) ; la ligne garde le fichier pour pouvoir « Reprendre » après une coupure
  const envoyerAuPoste = useCallback(async (f, { reprise = false, uid: uidExistant = null } = {}) => {
    const uid = uidExistant ?? ++uidRef.current;
    const lancer = async (avecReprise) => {
      const id = prochainFichierRef.current++;
      envoisRef.current.set(id, uid);
      const ligne = { uid, sens: "envoi", id, cx: connexionRef.current, nom: f.name, taille: f.size, fait: 0, fichier: f,
                      fini: false, erreur: "", interrompu: false, reprenable: false };
      setTransferts((liste) => (liste.some((x) => x.uid === uid) ? liste.map((x) => (x.uid === uid ? { ...x, ...ligne } : x)) : [...liste, ligne]));
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return false;
      const attendrePret = (idFichier, delai) => new Promise((ok) => {
        const minuterie = setTimeout(() => { pretsRef.current.delete(idFichier); ok(null); }, delai);
        pretsRef.current.set(idFichier, (octets) => { clearTimeout(minuterie); pretsRef.current.delete(idFichier); ok(octets); });
      });
      return envoyerFichier(ws, id, f, (fait) => majTransfert(uid, { fait }), dossierBaseRef.current, { reprise: avecReprise, attendrePret });
    };
    let ok = await lancer(reprise);
    if (ok === "repli") ok = await lancer(false);   // ancien Loois sans reprise : on recommence depuis le début
    if (!ok) majTransfert(uid, { erreur: "connexion interrompue", interrompu: true, reprenable: true });
    return Boolean(ok);
  }, [majTransfert]);

  // ---- Lot 135 : ce poste s'inscrit comme destination des copies de poste à poste (mode « Contrôler » seulement) ----
  const peutRecevoir = etat === "active" && mode === "controler";
  useEffect(() => {
    if (!peutRecevoir || !posteId) return undefined;
    registrePostes.set(posteId, {
      nom: posteNom || fiche?.poste_nom || "Poste Loois",
      recevoir: async (blob, nom) => { if (!(await envoyerAuPoste(new File([blob], nom)))) throw new Error("connexion fermée"); },
    });
    return () => registrePostes.delete(posteId);
  }, [peutRecevoir, posteId, posteNom, fiche, envoyerAuPoste]);

  // ---- Lots 135 et 281 : demande d'un fichier au poste, pour le télécharger (destination null) ou le copier vers un autre poste ----
  // Lot 281 : si des octets de ce fichier sont déjà gardés (liaison tombée), on demande seulement la FIN (depuis, modifie)
  const demanderFichier = (chemin, destination = null, uid = null) => {
    const cle = clePartiel(posteId, chemin);
    const { depuis, modifie } = departDemande(partielsReception, cle);
    demandesRef.current.push({ destination, cle, chemin, uid });
    envoyer({ type: "fichier_demander", chemin, depuis, modifie });
    if (depuis > 0) toast.info(`Reprise du fichier à ${tailleLisible(depuis)}`);
  };

  // ---- Lot 281 : « Reprendre » un transfert interrompu (ou tous), « Effacer » une ligne ou tout l'historique, « Prolonger » la session ----
  const reprendreTransfert = (t) => {
    if (etat !== "active" || !peutAgir) { toast.warning("Reprise possible pendant une prise en main en mode « Contrôler »"); return; }
    if (t.sens === "envoi" && t.fichier) envoyerAuPoste(t.fichier, { reprise: true, uid: t.uid });
    else if (t.sens === "reception" && t.chemin) demanderFichier(t.chemin, t.destination || null, t.uid);
  };
  const reprendreTous = () => transferts.filter((t) => t.interrompu && t.reprenable).forEach(reprendreTransfert);
  const effacerHistorique = (t = null) => {
    setTransferts((liste) => {
      const { liste: reste, retires } = effacerTransferts(liste, t ? { uid: t.uid } : { tout: true });
      oublierPartiels(retires);   // les octets gardés en mémoire pour une reprise sont libérés
      return reste;
    });
  };
  const prolongerSession = () => envoyer({ type: "prolonger" });

  // ---- Lot 282 : clic sur le ticket → modifier son motif et laisser une note (ajoutée à l'intervention, rappelée à la prochaine prise en main) ----
  const ouvrirTicket = async () => {
    const sid = sessionRef.current;
    if (!sid) return;
    try {
      const r = await apiClient.get(`/controle-distance/sessions/${sid}`);
      setTicketEdition({ motif: r.data.ticket_motif || "", note: r.data.note_intervention || "" });
    } catch { toast.error("Ticket illisible"); }
  };
  const enregistrerTicket = async () => {
    const sid = sessionRef.current;
    if (!sid || !ticketEdition) return;
    if (!ticketEdition.motif.trim()) { toast.warning("Le motif du ticket ne peut pas être vide"); return; }
    try {
      await apiClient.put(`/controle-distance/sessions/${sid}/ticket`, { motif: ticketEdition.motif, note: ticketEdition.note });
      setTicketEdition(null);
      toast.success(ticketEdition.note.trim() ? "Ticket modifié — la note sera rappelée à la prochaine prise en main de ce poste" : "Ticket modifié");
    } catch (e) { toast.error(e?.response?.data?.detail || "Ticket non modifié"); }
  };
  const supprimerRappel = async () => {
    try {
      await apiClient.delete(`/controle-distance/postes/${encodeURIComponent(posteId)}/rappel`);
      setFiche((f) => (f ? { ...f, rappel: null } : f));
      toast.success("Rappel supprimé");
    } catch { toast.error("Rappel non supprimé"); }
  };

  // ---- Lot 135 : dossier de base des transferts pour ce poste ----
  const definirDossierBase = async (chemin) => {
    try {
      const r = await apiClient.put(`/controle-distance/postes/${encodeURIComponent(posteId)}/dossiers`, { dossier_base: chemin || "" });
      setDossiers(r.data);
      toast.success(chemin ? `Dossier de base : ${chemin}` : "Dossier de base effacé (« Reçu du support SAWALI » sur le Bureau)");
    } catch { toast.error("Dossier de base non enregistré"); }
  };

  // ---- Lot 135 : blocage du clavier et de la souris du poste ----
  const basculerBlocage = () => envoyer({ type: "bloquer_entrees", valeur: entreesBloquees ? 0 : 1 });

  // ---- Lot 135 : échelle de l'image (la visionneuse redimensionne le canvas à l'annonce « ecrans ») ----
  const echelleSuivante = () => {
    const i = ECHELLES.findIndex((e) => e[0] === echelle);
    const suivante = ECHELLES[(i + 1) % ECHELLES.length];
    setEchelle(suivante[0]);
    envoyer({ type: "echelle", valeur: suivante[0] });
    toast.info(suivante[1]);
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
  const NIVEAUX = [[40, "Qualité basse (connexion lente)", "bg-amber-500"], [85, "Qualité normale", "bg-sky-500"], [95, "Haute qualité", "bg-emerald-500"]];
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
  // Écran sécurisé affiché sur un poste suivi par l'icône de l'utilisateur : l'image n'est pas disponible
  const ecranSecuriseInaccessible = etat === "active" && bureau?.securise && !fiche?.agent_service;

  const racine = embedded
    ? `absolute inset-0 flex flex-col overflow-hidden ${visible ? "" : "invisible pointer-events-none"}`
    : "fixed inset-0 z-[90] flex flex-col overflow-hidden";

  return (
    <div ref={cadreRef} className={`${racine} bg-[radial-gradient(ellipse_at_top,_#1e3a8a_0%,_#0f172a_45%,_#020617_100%)] text-slate-100`} data-testid="controle-distance">
      {/* ---- Échec de connexion : boîte de dialogue persistante, propre à l'onglet ---- */}
      {echec && (
        <div className="fixed inset-0 z-[100] grid place-items-center bg-black/60 p-4" data-testid="controle-distance-echec">
          <div role="alertdialog" aria-modal="true" aria-labelledby="cd-echec-titre"
               className="w-full max-w-md rounded-2xl bg-slate-900 p-5 text-slate-100 shadow-2xl ring-1 ring-rose-400/50">
            <h3 id="cd-echec-titre" className="text-base font-semibold text-rose-300">Connexion impossible{posteNom ? ` — ${posteNom}` : ""}</h3>
            <p className="mt-3 text-sm font-medium">{echec.detail}</p>
            {echec.conseil && <p className="mt-2 text-xs leading-relaxed text-slate-300">{echec.conseil}</p>}
            <div className="mt-4 flex justify-end">
              <button type="button" autoFocus onClick={() => setEchec(null)}
                      className="rounded-lg bg-sky-500 px-4 py-1.5 text-sm font-semibold text-white hover:bg-sky-400" data-testid="controle-distance-echec-ok">
                Compris
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ---- Lot 282 : rappel laissé lors de la dernière intervention sur ce poste (pas celui de la session en cours) ---- */}
      {fiche?.rappel && !rappelMasque && fiche.rappel.session_id !== sessionRef.current && (
        <div className="mx-4 mt-3 flex items-start gap-2 rounded-xl bg-amber-500/15 px-3 py-2 text-xs text-amber-100 ring-1 ring-amber-400/40" data-testid="rappel-intervention">
          <PenLine className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="min-w-0 flex-1">
            <p className="font-semibold">Rappel de la dernière intervention sur ce poste{fiche.rappel.session_numero ? ` (${fiche.rappel.session_numero})` : ""}</p>
            <p className="mt-0.5 whitespace-pre-wrap break-words">{fiche.rappel.note}</p>
            <p className="mt-0.5 text-[10px] text-amber-200/70">{[fiche.rappel.par, fiche.rappel.le ? new Date(fiche.rappel.le).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : ""].filter(Boolean).join(" · ")}</p>
          </div>
          <button type="button" onClick={() => setRappelMasque(true)} className="shrink-0 rounded px-2 py-0.5 text-[11px] hover:bg-white/10" title="Masquer pour cette prise en main (le rappel reste pour la prochaine)">Masquer</button>
          <button type="button" onClick={supprimerRappel} className="shrink-0 rounded bg-amber-500/30 px-2 py-0.5 text-[11px] hover:bg-amber-500/50" data-testid="rappel-supprimer" title="Supprime le rappel : il ne sera plus affiché aux prochaines prises en main">Supprimer le rappel</button>
        </div>
      )}

      {/* ---- En-tête : poste, mode et mesures (pictogrammes) ---- */}
      <div className="flex flex-wrap items-center gap-2 px-4 pt-3">
        <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-sky-400 to-indigo-600 shadow-lg" aria-hidden="true">
          {fiche?.agent_service ? <ServerCog className="h-5 w-5" /> : <Monitor className="h-5 w-5" />}
        </span>
        <span className="text-sm font-semibold">{posteNom || fiche?.poste_nom || "Poste Loois"}</span>
        {numero && <span className="rounded-full bg-white/10 px-2 py-0.5 font-mono text-[11px] text-slate-200" title="Numéro de la prise en main">{numero}</span>}
        {ticket && (
          <button type="button" onClick={ouvrirTicket} data-testid="ticket-modifier"
                  className="inline-flex items-center gap-1 rounded-full bg-amber-500/20 px-2 py-0.5 text-[11px] text-amber-200 ring-1 ring-amber-400/40 hover:bg-amber-500/30"
                  title="Ticket du client ouvert automatiquement — cliquer pour modifier son motif ou ajouter une note de rappel">
            <Ticket className="h-3 w-3" />{ticket}<PenLine className="h-3 w-3 opacity-70" />
          </button>
        )}
        {fiche?.client_nom && <span className="text-[11px] text-slate-400">{fiche.client_nom}</span>}
        {sansSurveillance && (
          <span className="inline-flex items-center gap-1 rounded-full bg-indigo-500/20 px-2.5 py-1 text-xs font-semibold text-indigo-200 ring-1 ring-indigo-400/40"
                title="Poste sans surveillance : accord automatique, aucun bandeau sur le poste (notification discrète seulement)">
            <UserX className="h-3.5 w-3.5" aria-hidden="true" />
          </span>
        )}
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
            {moteur && <span className="inline-flex items-center gap-1" title={moteur === "dxgi" ? "Capture DXGI (carte graphique, fluide)" : "Capture GDI (classique)"}><Cpu className="h-3.5 w-3.5 text-violet-300" />{moteur.toUpperCase()}</span>}
          </span>
        )}
        {enregistre && (
          <span className="inline-flex items-center gap-1 rounded-full bg-rose-600/30 px-2 py-0.5 text-[11px] font-semibold text-rose-200" title="Session enregistrée (vidéo dans le journal)">
            <Circle className="h-2.5 w-2.5 animate-pulse fill-rose-400 text-rose-400" />REC
          </span>
        )}
        {entreesBloquees && (
          <span className="inline-flex items-center gap-1 rounded-full bg-orange-500/25 px-2 py-0.5 text-[11px] font-semibold text-orange-200" title="Clavier et souris du poste bloqués">
            <Ban className="h-3 w-3" />Entrées bloquées
          </span>
        )}
        <span className="ml-auto inline-flex items-center gap-1 text-[11px] text-slate-400" title="Connexion chiffrée, accord de l'utilisateur du poste, journal">
          <Lock className="h-3.5 w-3.5 text-emerald-400" />
        </span>
      </div>

      {/* ---- Zone d'affichage + volet repliable ---- */}
      <div className="flex min-h-0 flex-1">
      {/* ---- Barre d'actions latérale (pictogrammes ronds et colorés, lot 142 : à gauche de l'écran du poste) ---- */}
      {/* Lot 142 : barre latérale GAUCHE (verticale, défilante si l'écran est bas) : l'écran du poste gagne toute la largeur du bandeau */}
      <div className="relative z-20 my-2 ml-2 flex min-h-0 shrink-0 flex-col">
      <div className="flex min-h-0 flex-col items-center gap-1.5 overflow-y-auto rounded-2xl bg-white/5 p-1.5 ring-1 ring-white/10 backdrop-blur [scrollbar-width:none]">
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
            <button type="button" className={picto(echelle === 100 ? "bg-teal-600" : "bg-amber-600")} onClick={echelleSuivante}
                    title={`${(ECHELLES.find((e) => e[0] === echelle) || ECHELLES[0])[1]} — cliquer pour changer`}>
              <Scaling className="h-4 w-4" />
              {echelle !== 100 && <span className="absolute -bottom-1 -right-1 rounded-full bg-white px-1 text-[8px] font-bold text-amber-700">{echelle}</span>}
            </button>
            <button type="button" className={picto("bg-cyan-500")} onClick={() => envoyer({ type: "image_complete" })} title="Rafraîchir l'écran complet"><RefreshCw className="h-4 w-4" /></button>
            <button type="button" className={picto("bg-violet-500")} disabled={!peutAgir} onClick={collerTexte} title="Coller votre presse-papiers sur le poste"><ClipboardPaste className="h-4 w-4" /></button>
            <button type="button" className={picto(clavierOuvert ? "bg-fuchsia-500 ring-2 ring-white" : "bg-fuchsia-700")} disabled={!peutAgir}
                    onClick={() => setClavierOuvert((v) => !v)} title="Clavier virtuel (touches de fonction, Windows, raccourcis)"><Keyboard className="h-4 w-4" /></button>
            <button type="button" className={picto("bg-pink-500")} disabled={!peutAgir} onClick={() => combinaison(["ControlLeft", "ShiftLeft", "Escape"])} title="Gestionnaire des tâches (Ctrl+Maj+Échap)"><Activity className="h-4 w-4" /></button>
            <button type="button" className={picto("bg-blue-600")} disabled={!peutAgir} onClick={() => combinaison(["MetaLeft"])} title="Touche Windows"><IconeWindows /></button>
            <button type="button" className={picto(entreesBloquees ? "bg-orange-500 ring-2 ring-white" : "bg-orange-700")} disabled={!peutAgir}
                    onClick={basculerBlocage} title={entreesBloquees ? "Débloquer le clavier et la souris du poste" : "Bloquer le clavier et la souris du poste"}>
              <Ban className="h-4 w-4" />
            </button>
            <button type="button" className={picto("bg-emerald-700")} disabled={!peutAgir || !fiche?.identifiants?.enregistre}
                    onClick={() => envoyer({ type: "identifiants_windows" })}
                    title={fiche?.identifiants?.enregistre ? `Saisir l'identifiant Windows mémorisé (${fiche.identifiants.utilisateur || "mot de passe"})` : "Aucun identifiant Windows mémorisé"}>
              <KeyRound className="h-4 w-4" />
            </button>
            <button type="button" className={picto("bg-red-700")} disabled={!peutAgir} onClick={() => setMenuSysteme((v) => !v)} title="Actions système : Ctrl+Alt+Suppr, verrouiller, déconnecter, redémarrer, éteindre">
              <Power className="h-4 w-4" />
            </button>
          </>
        )}
        <button type="button" className={picto("bg-slate-600")} onClick={() => setIdentifiantsOuvert(true)} title="Identifiant Windows mémorisé pour ce poste">
          <Lock className="h-4 w-4" />
        </button>
        <button type="button" className={picto(voletOuvert ? "bg-sky-600 ring-2 ring-white" : "bg-slate-600")} onClick={() => setVoletOuvert((v) => !v)}
                title={voletOuvert ? "Replier le volet" : "Caractéristiques, performances, chat et fichiers du poste"}>
          {voletOuvert ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
        </button>
        <button type="button" className={picto("bg-slate-600")} onClick={basculerPleinEcran} title={pleinEcran ? "Quitter le plein écran" : "Plein écran"}>
          {pleinEcran ? <Minimize className="h-4 w-4" /> : <Maximize className="h-4 w-4" />}
        </button>
        <button type="button" className={picto("bg-rose-600")} onClick={fermer} title="Arrêter la prise en main et fermer" data-testid="controle-distance-fermer">
          <X className="h-5 w-5" />
        </button>
      </div>
        {/* Menu des actions système (confirmation ensuite) */}
        {menuSysteme && peutAgir && (
          <div className="absolute left-full top-0 z-30 ml-2 w-64 overflow-hidden rounded-xl bg-slate-900 shadow-2xl ring-1 ring-white/15">
            {Object.entries(ACTIONS_SYSTEME).map(([action, a]) => (
              <button key={action} type="button" onClick={() => { setMenuSysteme(false); setConfirmation(action); }}
                      className={`block w-full px-3 py-2 text-left text-xs hover:bg-white/10 ${a.danger ? "text-rose-300" : "text-slate-100"}`}>
                {a.titre}
              </button>
            ))}
            {/* Lot 140 : maintenance du disque (outils Windows seulement) */}
            <div className="border-t border-white/10 px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">Maintenance du disque</div>
            {Object.entries(ACTIONS_MAINTENANCE).map(([action, a]) => (
              <button key={action} type="button" onClick={() => { setMenuSysteme(false); setConfirmationMaint({ action, volume: "C:" }); }}
                      className="block w-full px-3 py-2 text-left text-xs text-slate-100 hover:bg-white/10">
                {a.titre}
              </button>
            ))}
          </div>
        )}
      </div>

        <div className={`relative flex min-h-0 min-w-0 flex-1 flex-col ${survolDepot ? "ring-4 ring-inset ring-sky-400/70" : ""}`}
             onDragOver={(e) => { if (etat === "active") { e.preventDefault(); setSurvolDepot(true); } }}
             onDragLeave={() => setSurvolDepot(false)}
             onDrop={deposer}>
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
                {/* Lot 135 : client du ticket automatique, si le poste n'est encore rattaché à aucun client */}
                {fiche && !fiche.client_id && clients.length > 0 && (
                  <label className="mx-auto mt-2 flex max-w-md items-center gap-2 rounded-full bg-white/10 px-4 py-2 ring-1 ring-white/15">
                    <Ticket className="h-4 w-4 shrink-0 text-amber-300" aria-hidden="true" />
                    <select value={clientChoisi} onChange={(e) => setClientChoisi(e.target.value)}
                            className="w-full bg-transparent text-sm text-slate-100 outline-none">
                      <option value="" className="text-slate-900">Client SAWALI du ticket (facultatif)</option>
                      {clients.map((c) => <option key={c.id} value={c.id} className="text-slate-900">{c.nom}</option>)}
                    </select>
                  </label>
                )}
                <div className="mt-5 grid gap-4 sm:grid-cols-2">
                  <button type="button" onClick={() => demander("controler")} data-testid="controle-distance-controler"
                          className="group rounded-3xl bg-gradient-to-br from-emerald-400 via-teal-500 to-cyan-600 p-6 text-left shadow-2xl shadow-emerald-900/40 transition hover:-translate-y-1 hover:shadow-emerald-500/30">
                    <span className="flex gap-2"><MousePointer2 className="h-9 w-9" /><Keyboard className="h-9 w-9 opacity-80" /></span>
                    <span className="mt-4 block text-lg font-bold">Contrôler</span>
                    <span className="block text-xs text-white/80">Souris, clavier, fichiers, actions système</span>
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
                  {sansSurveillance
                    ? "Poste sans surveillance : connexion sans accord, une notification discrète s'affiche sur le poste."
                    : "L'utilisateur du poste accepte, voit un bandeau et peut arrêter à tout moment."}
                </p>
                {fiche?.agent_service && (
                  <p className="mt-1 flex items-center justify-center gap-1.5 text-center text-[11px] text-sky-300">
                    <ServerCog className="h-3.5 w-3.5" aria-hidden="true" />
                    Fiche « service Windows » : fonctionne aussi écran verrouillé, à l'écran de connexion et session fermée.
                  </p>
                )}
                {reglages.enregistrement_video && (
                  <p className="mt-1 flex items-center justify-center gap-1.5 text-center text-[11px] text-rose-300">
                    <Circle className="h-2.5 w-2.5 fill-rose-400" aria-hidden="true" />La session sera enregistrée (vidéo dans le journal).
                  </p>
                )}
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
                  <p className="text-sm text-slate-200">
                    {etat === "demande" && sansSurveillance ? "Poste sans surveillance — connexion automatique…" : LIBELLES[etat]}
                  </p>
                  {motifFin && <p className="text-xs text-slate-400">{motifFin}</p>}
                  {!enCours && (
                    <div className="flex gap-6">
                      <button type="button" onClick={() => { setMotifFin(""); setEtat("choix"); chargerFiche(); }} title="Nouvelle demande (reprendre la main)"
                              className="flex flex-col items-center gap-1 text-[11px] text-slate-300 hover:text-white">
                        <span className={picto("bg-sky-500")}><RotateCcw className="h-4 w-4" /></span>Reprendre la main
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

            {/* Lot 135 : écran de connexion / verrouillé sur un poste suivi par l'icône de l'utilisateur */}
            {ecranSecuriseInaccessible && (
              <div className="absolute inset-x-0 top-6 z-10 mx-auto flex max-w-lg flex-col items-center gap-2 rounded-2xl bg-slate-900/95 p-4 text-center text-xs shadow-2xl ring-1 ring-amber-400/40">
                <ShieldAlert className="h-6 w-6 text-amber-300" />
                <p>Le poste affiche l'écran de connexion ou de verrouillage : l'icône Loois de l'utilisateur ne peut pas le montrer.</p>
                {fiche?.fiche_service ? (
                  <button type="button" onClick={() => onOuvrirPoste?.({ id: fiche.fiche_service.id, nom: fiche.fiche_service.nom })}
                          className="inline-flex items-center gap-1 rounded-full bg-sky-600 px-3 py-1 font-semibold text-white hover:bg-sky-500">
                    <ServerCog className="h-3.5 w-3.5" />Ouvrir la fiche « service Windows » de ce poste
                  </button>
                ) : (
                  <p className="text-slate-400">Installez le service Windows Loois sur ce poste pour le prendre en main session fermée.</p>
                )}
              </div>
            )}

            {survolDepot && (
              <div className="pointer-events-none absolute inset-0 z-10 grid place-items-center bg-sky-500/10">
                <span className="inline-flex items-center gap-2 rounded-full bg-sky-600 px-4 py-2 text-sm font-semibold text-white shadow-2xl">
                  <Upload className="h-4 w-4" />Déposer pour envoyer au poste
                </span>
              </div>
            )}

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
          {clavierOuvert && etat === "active" && (
            <ClavierVirtuel envoyer={envoyer} actif={peutAgir} onFermer={() => setClavierOuvert(false)} />
          )}
        </div>
        {voletOuvert && (
          <VoletPoste onglet={ongletVolet} setOnglet={setOngletVolet} infos={infos} perf={perf} filId={fiche?.fil_id}
                      liste={listeFichiers} transferts={transferts} envoyer={envoyer} peutAgir={peutAgir} actif={etat === "active"}
                      posteId={posteId} dossiers={dossiers} onDossierBase={definirDossierBase} onDemanderFichier={demanderFichier}
                      onReprendre={reprendreTransfert} onReprendreTous={reprendreTous} onEffacer={effacerHistorique} onProlonger={prolongerSession} />
        )}
      </div>

      {/* ---- Lot 282 : modifier le motif du ticket et laisser une note de rappel ---- */}
      {ticketEdition && (
        <div className="absolute inset-0 z-20 grid place-items-center bg-black/60 p-4" data-testid="ticket-fenetre">
          <div className="w-full max-w-md rounded-2xl bg-slate-900 p-5 shadow-2xl ring-1 ring-white/15">
            <h4 className="flex items-center gap-2 text-sm font-bold text-slate-100"><Ticket className="h-4 w-4 text-amber-300" />Ticket {ticket}</h4>
            <label className="mt-3 block text-[11px] font-semibold text-slate-300">Motif du ticket
              <textarea value={ticketEdition.motif} maxLength={300} rows={2} onChange={(e) => setTicketEdition({ ...ticketEdition, motif: e.target.value })}
                        className="mt-1 w-full rounded-lg bg-white/10 p-2 text-xs text-slate-100 outline-none ring-1 ring-white/10 focus:ring-sky-400" data-testid="ticket-motif" />
            </label>
            <label className="mt-3 block text-[11px] font-semibold text-slate-300">Note de l'intervention (rappel à la prochaine prise en main de ce poste)
              <textarea value={ticketEdition.note} maxLength={1000} rows={4} onChange={(e) => setTicketEdition({ ...ticketEdition, note: e.target.value })}
                        placeholder="Ex. : refaire la sauvegarde sur le disque D vendredi…"
                        className="mt-1 w-full rounded-lg bg-white/10 p-2 text-xs text-slate-100 outline-none ring-1 ring-white/10 placeholder:text-slate-500 focus:ring-sky-400" data-testid="ticket-note" />
            </label>
            <p className="mt-1 text-[10px] text-slate-400">La note est ajoutée à l'intervention à la fin de la prise en main et affichée en rappel la prochaine fois. Vide = pas de rappel.</p>
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" onClick={() => setTicketEdition(null)} className="rounded-lg bg-white/10 px-3 py-1.5 text-xs hover:bg-white/20">Annuler</button>
              <button type="button" onClick={enregistrerTicket} className="rounded-lg bg-sky-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-sky-500" data-testid="ticket-enregistrer">Enregistrer</button>
            </div>
          </div>
        </div>
      )}

      {/* ---- Confirmation d'une action système ---- */}
      {confirmation && (
        <div className="absolute inset-0 z-20 grid place-items-center bg-black/60 p-4">
          <div className="w-full max-w-sm rounded-2xl bg-slate-900 p-5 shadow-2xl ring-1 ring-white/15">
            <h4 className={`flex items-center gap-2 text-sm font-bold ${ACTIONS_SYSTEME[confirmation].danger ? "text-rose-300" : "text-slate-100"}`}>
              <Power className="h-4 w-4" />{ACTIONS_SYSTEME[confirmation].titre}
            </h4>
            <p className="mt-2 text-xs text-slate-300">{ACTIONS_SYSTEME[confirmation].texte}</p>
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" onClick={() => setConfirmation(null)} className="rounded-lg bg-white/10 px-3 py-1.5 text-xs hover:bg-white/20">Annuler</button>
              <button type="button" onClick={() => { envoyer({ type: "systeme", action: confirmation }); setConfirmation(null); }}
                      className={`rounded-lg px-3 py-1.5 text-xs font-semibold text-white ${ACTIONS_SYSTEME[confirmation].danger ? "bg-rose-600 hover:bg-rose-500" : "bg-sky-600 hover:bg-sky-500"}`}>
                Confirmer
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ---- Lot 140 : confirmation d'une maintenance du disque (choix du lecteur) ---- */}
      {confirmationMaint && (
        <div className="absolute inset-0 z-20 grid place-items-center bg-black/60 p-4">
          <div className="w-full max-w-sm rounded-2xl bg-slate-900 p-5 shadow-2xl ring-1 ring-white/15">
            <h4 className="flex items-center gap-2 text-sm font-bold text-slate-100"><ServerCog className="h-4 w-4" />{ACTIONS_MAINTENANCE[confirmationMaint.action].titre}</h4>
            <p className="mt-2 text-xs text-slate-300">{ACTIONS_MAINTENANCE[confirmationMaint.action].texte}</p>
            {ACTIONS_MAINTENANCE[confirmationMaint.action].disque && (
              <label className="mt-3 block text-xs text-slate-300">Lecteur
                <select value={confirmationMaint.volume} onChange={(e) => setConfirmationMaint({ ...confirmationMaint, volume: e.target.value })}
                        className="ml-2 rounded bg-slate-800 px-2 py-1 text-slate-100 ring-1 ring-white/15">
                  {((infos?.inventaire?.disques || []).map((d) => d.lettre).filter(Boolean).length
                    ? (infos.inventaire.disques || []).map((d) => `${String(d.lettre).replace(/[:\\/]+$/, "")}:`)
                    : ["C:"]).map((v) => <option key={v} value={v}>{v}</option>)}
                </select>
              </label>
            )}
            <p className="mt-2 text-[11px] text-slate-400">La tâche réussie sera inscrite dans l'intervention de cette prise en main.</p>
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" onClick={() => setConfirmationMaint(null)} className="rounded-lg bg-white/10 px-3 py-1.5 text-xs hover:bg-white/20">Annuler</button>
              <button type="button"
                      onClick={() => { envoyer({ type: "maintenance", id: Math.floor(Date.now() % 2147483647), action: confirmationMaint.action, chemin: confirmationMaint.volume }); setConfirmationMaint(null); }}
                      className="rounded-lg bg-sky-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-sky-500">Lancer</button>
            </div>
          </div>
        </div>
      )}

      {/* ---- Lot 140 : avancement des maintenances du disque ---- */}
      {maintenances.length > 0 && (
        <div className="absolute bottom-3 left-3 z-10 w-80 max-w-[calc(100%-1.5rem)] space-y-1 rounded-xl bg-slate-900/90 p-3 text-xs text-slate-100 shadow-xl ring-1 ring-white/15">
          <div className="flex items-center justify-between font-semibold">
            <span className="inline-flex items-center gap-1"><ServerCog className="h-3.5 w-3.5" /> Maintenance du disque</span>
            <button type="button" aria-label="Masquer" onClick={() => setMaintenances((l) => l.filter((x) => x.etat === "demarre" || x.etat === "en_cours"))}><X className="h-3.5 w-3.5" /></button>
          </div>
          {maintenances.map((x) => (
            <div key={x.id} className="rounded-lg bg-white/5 p-2">
              <div className="flex items-center gap-1 font-medium">
                {x.etat === "termine" ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                  : x.etat === "echec" ? <ShieldX className="h-3.5 w-3.5 text-rose-400" />
                    : <Loader2 className="h-3.5 w-3.5 animate-spin text-sky-300" />}
                <span className="truncate">{x.libelle} ({x.volume})</span>
              </div>
              {x.resume && <p className="mt-1 whitespace-pre-line break-words text-[11px] text-slate-300">{x.etat === "en_cours" || x.etat === "demarre" ? x.resume : x.resume.split("\n").slice(0, 3).join("\n")}</p>}
            </div>
          ))}
        </div>
      )}

      {/* ---- Identifiant Windows mémorisé (le mot de passe n'est jamais réaffiché) ---- */}
      {identifiantsOuvert && (
        <FenetreIdentifiants posteId={posteId} actuel={fiche?.identifiants}
                             onFermer={(maj) => { setIdentifiantsOuvert(false); if (maj) setFiche((f) => ({ ...f, identifiants: maj })); }} />
      )}
    </div>
  );
}

// =====================================================================
// Lot 135 — fenêtre « Identifiant Windows » (item 7) : enregistré chiffré par SAWALI, saisi par le serveur sur le poste
// (bouton « clé » ou automatiquement à l'écran de connexion). Le champ mot de passe a son pictogramme « œil ».
// =====================================================================
export function FenetreIdentifiants({ posteId, actuel, onFermer }) {
  const [utilisateur, setUtilisateur] = useState(actuel?.utilisateur || "");
  const [domaine, setDomaine] = useState(actuel?.domaine || "");
  const [motDePasse, setMotDePasse] = useState("");
  const [voir, setVoir] = useState(false);
  const [saisieAuto, setSaisieAuto] = useState(actuel?.saisie_auto ?? true);
  const [occupe, setOccupe] = useState(false);

  const enregistrer = async () => {
    setOccupe(true);
    try {
      const r = await apiClient.put(`/controle-distance/postes/${encodeURIComponent(posteId)}/identifiants`,
        { utilisateur, domaine, mot_de_passe: motDePasse || null, saisie_auto: saisieAuto });
      toast.success("Identifiant Windows mémorisé (chiffré)");
      onFermer(r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Enregistrement impossible");
    } finally {
      setOccupe(false);
    }
  };
  const oublier = async () => {
    setOccupe(true);
    try {
      const r = await apiClient.delete(`/controle-distance/postes/${encodeURIComponent(posteId)}/identifiants`);
      toast.success("Identifiant Windows oublié");
      onFermer(r.data);
    } catch { toast.error("Suppression impossible"); } finally { setOccupe(false); }
  };

  const champ = "w-full rounded-lg bg-white/10 px-3 py-1.5 text-sm text-slate-100 outline-none ring-1 ring-white/15 focus:ring-sky-400";
  return (
    <div className="absolute inset-0 z-20 grid place-items-center bg-black/60 p-4" onKeyDown={(e) => e.stopPropagation()}>
      <div className="w-full max-w-md rounded-2xl bg-slate-900 p-5 shadow-2xl ring-1 ring-white/15">
        <h4 className="flex items-center gap-2 text-sm font-bold"><KeyRound className="h-4 w-4 text-emerald-300" />Identifiant Windows du poste</h4>
        <p className="mt-1 text-[11px] text-slate-400">
          Gardé chiffré par SAWALI pour cet ordinateur, jamais réaffiché. À chaque prise en main, le serveur le saisit sur
          l'écran de connexion (fiche « service Windows ») : bouton « clé » ou saisie automatique.
        </p>
        <div className="mt-3 space-y-2">
          <input className={champ} value={utilisateur} onChange={(e) => setUtilisateur(e.target.value)} placeholder="Utilisateur Windows (ex. marie ou PHARMA\marie)" autoComplete="off" />
          <input className={champ} value={domaine} onChange={(e) => setDomaine(e.target.value)} placeholder="Domaine (facultatif)" autoComplete="off" />
          <div className="relative">
            <input className={`${champ} pr-10`} type={voir ? "text" : "password"} value={motDePasse} onChange={(e) => setMotDePasse(e.target.value)}
                   placeholder={actuel?.enregistre ? "Mot de passe (laisser vide pour garder l'actuel)" : "Mot de passe Windows"} autoComplete="new-password" />
            <button type="button" onClick={() => setVoir((v) => !v)} title={voir ? "Masquer" : "Voir"}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-300 hover:text-white">
              {voir ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
          <label className="flex items-center gap-2 text-xs text-slate-300">
            <input type="checkbox" checked={saisieAuto} onChange={(e) => setSaisieAuto(e.target.checked)} />
            Saisie automatique dès que l'écran de connexion est affiché
          </label>
          {actuel?.maj_le && <p className="text-[10px] text-slate-500">Mis à jour le {new Date(actuel.maj_le).toLocaleString("fr-FR")} par {actuel.maj_par}</p>}
        </div>
        <div className="mt-4 flex justify-between gap-2">
          <button type="button" disabled={occupe || !actuel?.enregistre} onClick={oublier} className="rounded-lg bg-rose-600/20 px-3 py-1.5 text-xs text-rose-200 hover:bg-rose-600/40 disabled:opacity-30">Oublier</button>
          <span className="flex gap-2">
            <button type="button" onClick={() => onFermer(null)} className="rounded-lg bg-white/10 px-3 py-1.5 text-xs hover:bg-white/20">Annuler</button>
            <button type="button" disabled={occupe} onClick={enregistrer} className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-500 disabled:opacity-50">Enregistrer</button>
          </span>
        </div>
      </div>
    </div>
  );
}
