// =====================================================================
// Lot 131 — Rubrique des Paramètres « 🖥️ Contrôle à distance Loois » :
// fonctionnement, conditions et journal des prises en main (qui, quel poste, quand, durée, issue).
// Lot 135 — réglages (vidéo, ticket automatique), postes « service Windows », identifiants Windows mémorisés,
// journal enrichi : numéro, ticket, délais mesurés, capture, actions sensibles, vidéo de la session.
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { RefreshCw, MonitorSmartphone, Search, ChevronDown, ChevronUp, ArrowUp, ArrowDown, UserX, ServerCog, KeyRound, PlayCircle, Ticket, X, Trash2, VideoOff } from "lucide-react";
// Lot 135 — prise en main dans les onglets (plusieurs postes à la fois)
import { ouvrirPriseEnMain } from "@/components/ControleDistanceOnglets";
import { FenetreIdentifiants } from "@/components/ControleDistance";
import { dateLisible, dureeLisible } from "@/components/controleDistance/outils";

// Libellés et couleurs des statuts d'une session
const STATUTS = {
  demandee: ["En attente d'accord", "bg-amber-100 text-amber-800"],
  acceptee: ["Acceptée", "bg-sky-100 text-sky-800"],
  en_cours: ["En cours", "bg-emerald-100 text-emerald-800"],
  terminee: ["Terminée", "bg-slate-100 text-slate-700"],
  refusee: ["Refusée", "bg-rose-100 text-rose-700"],
  expiree: ["Sans réponse", "bg-slate-100 text-slate-500"],
};

// Libellés des actions sensibles gardées dans le journal
const ACTIONS = {
  systeme: "Action système", bloquer_entrees: "Clavier / souris", fichier_envoye: "Fichier envoyé",
  fichier_recupere: "Fichier récupéré", identifiants_windows: "Identifiant Windows",
  ticket_modifie: "Ticket modifié",   // lot 282
};

// `lienPage` : dans les Paramètres, bouton vers l'écran Plateformes → Contrôle à distance (absent sur cet écran lui-même)
export default function ControleDistanceSection({ lienPage = true }) {
  const [sessions, setSessions] = useState([]);
  const [chargement, setChargement] = useState(false);
  const [erreur, setErreur] = useState("");
  // Lot 131.1 — postes Loois munis d'une clé client
  const [postes, setPostes] = useState([]);
  // Liste des postes : recherche par nom, filtre par client, tri (par défaut : par client, avec ruptures)
  const [recherche, setRecherche] = useState("");
  const [clientFiltre, setClientFiltre] = useState("");
  const [tri, setTri] = useState("client");          // "client" | "nom" | "signal"
  const [croissant, setCroissant] = useState(true);
  // Un même ordinateur apparaît une fois par session utilisateur + une fois pour le service Windows : par défaut on ne
  // garde que la ligne « service Windows » (elle marche écran verrouillé, session fermée) ; case pour tout afficher
  const [toutesSessions, setToutesSessions] = useState(false);
  // Texte d'aide : 2 lignes par défaut, dépliable (choix mémorisé dans ce navigateur) pour laisser la place à la liste des postes
  const [aideOuverte, setAideOuverte] = useState(() => {
    try { return window.localStorage.getItem("cd_aide_ouverte") === "1"; } catch { return false; }
  });
  const basculerAide = () => setAideOuverte((v) => {
    try { window.localStorage.setItem("cd_aide_ouverte", v ? "0" : "1"); } catch { /* stockage indisponible : sans conséquence */ }
    return !v;
  });
  const [superAdmin, setSuperAdmin] = useState(false);
  // Lot 135 — réglages, identifiant Windows ouvert, vidéo en lecture, détail d'une session
  const [reglages, setReglages] = useState(null);
  const [identifiantsDe, setIdentifiantsDe] = useState(null);
  const [video, setVideo] = useState(null);
  const [detail, setDetail] = useState(null);

  // ---- Lecture du journal, des postes et des réglages (réservé au support SAWALI) ----
  const lire = useCallback(async () => {
    setChargement(true);
    try {
      const [r, p, g] = await Promise.all([
        apiClient.get("/controle-distance/journal", { params: { limite: 50 } }),
        apiClient.get("/controle-distance/postes"),
        apiClient.get("/controle-distance/reglages"),
      ]);
      setSessions(r.data.sessions || []);
      setPostes(p.data.postes || []);
      setSuperAdmin(Boolean(p.data.super_admin));
      setReglages(g.data);
      setErreur("");
    } catch (e) {
      setErreur(e?.response?.status === 403 ? "Journal réservé au support SAWALI." : "Journal indisponible.");
    } finally {
      setChargement(false);
    }
  }, []);
  useEffect(() => { lire(); }, [lire]);

  // ---- Lot 135 : enregistrement d'un réglage ----
  const regler = async (champ, valeur) => {
    try {
      const r = await apiClient.put("/controle-distance/reglages", { ...reglages, [champ]: valeur });
      setReglages(r.data);
      toast.success("Réglage enregistré");
    } catch { toast.error("Réglage non enregistré"); }
  };

  // ---- Lot 135.1 : purge des vidéos plus anciennes que la durée de conservation (sinon chaque nuit à 03:20) ----
  const [purge, setPurge] = useState(false);
  const purgerMaintenant = async () => {
    setPurge(true);
    const attente = toast.loading("Patientez… purge des vidéos");
    try {
      const r = await apiClient.post("/controle-distance/videos/purger");
      toast.success(`${r.data.sessions} vidéo(s) de plus de ${r.data.jours} jours supprimée(s)` +
        (r.data.erreurs ? ` · ${r.data.erreurs} partie(s) à réessayer` : ""), { id: attente });
      lire();
    } catch { toast.error("Purge impossible", { id: attente }); } finally { setPurge(false); }
  };
  const [jours, setJours] = useState("");

  // ---- Liste des postes : filtre (nom / client), tri et ruptures par client ----
  const libelleClient = (p) => p.cle_client_libelle || p.cle_client_code || "(sans client)";
  const clientsPostes = [...new Set(postes.map(libelleClient))].sort((a, b) => a.localeCompare(b, "fr", { sensitivity: "base" }));
  // Fiches « utilisateur » masquées : celles dont l'ordinateur (client + poste) possède une fiche « service Windows »
  const cleMachine = (p) => (p.poste ? `${p.cle_client_code || ""}|${p.poste}`.toLowerCase() : "");
  const machinesAvecService = new Set(postes.filter((p) => p.agent_service && cleMachine(p)).map(cleMachine));
  const estMasque = (p) => !p.agent_service && cleMachine(p) !== "" && machinesAvecService.has(cleMachine(p));
  const nbMasques = postes.filter(estMasque).length;
  const lignesPostes = (() => {
    const q = recherche.trim().toLowerCase();
    const sens = croissant ? 1 : -1;
    const parNom = (a, b) => String(a.nom || "").localeCompare(String(b.nom || ""), "fr", { sensitivity: "base", numeric: true });
    const parClient = (a, b) => libelleClient(a).localeCompare(libelleClient(b), "fr", { sensitivity: "base" });
    const instant = (p) => new Date(p.signal_controle_distance || p.dernier_contact || 0).getTime() || 0;
    return postes
      .filter((p) => toutesSessions || !estMasque(p))
      .filter((p) => (!clientFiltre || libelleClient(p) === clientFiltre)
        && (!q || String(p.nom || "").toLowerCase().includes(q) || libelleClient(p).toLowerCase().includes(q)))
      .sort((a, b) => {
        if (tri === "signal") return sens * (instant(a) - instant(b)) || parNom(a, b);
        if (tri === "nom") return sens * parNom(a, b);
        return sens * parClient(a, b) || parNom(a, b);      // par client : postes classés par nom dans chaque client
      });
  })();
  useEffect(() => { if (reglages) setJours(String(reglages.conservation_jours ?? 90)); }, [reglages]);

  // ---- Lot 135 : lecture de la vidéo d'une session (lien signé de 15 minutes) ----
  const voirVideo = async (s) => {
    try {
      const r = await apiClient.get(`/controle-distance/sessions/${s.id}/video/lien`);
      setVideo({ url: `${process.env.REACT_APP_BACKEND_URL || ""}${r.data.url}`, titre: `${s.numero || ""} — ${s.poste_nom || ""}` });
    } catch (e) { toast.error(e?.response?.data?.detail || "Vidéo indisponible"); }
  };

  return (
    <div className="space-y-3 text-sm text-slate-700" data-testid="controle-distance-section">
      {lienPage && (
        <a href="/admin/controle-distance" className="inline-flex items-center gap-1 rounded-md bg-sky-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-sky-700">
          <MonitorSmartphone className="h-3.5 w-3.5" />Ouvrir Plateformes → Contrôle à distance
        </a>
      )}
      <div>
        <p className={aideOuverte ? "" : "line-clamp-2"}>
          Le support SAWALI peut <b>voir l'écran</b> d'un poste Loois ou <b>en prendre le contrôle</b> (souris, clavier,
          plusieurs écrans, presse-papiers), directement depuis le navigateur. Accord de l'utilisateur obligatoire, sauf poste
          « sans surveillance » ; seuls les postes munis d'une clé client Loois sont concernés.
        </p>
        <button type="button" onClick={basculerAide} aria-expanded={aideOuverte} data-testid="controle-distance-aide"
                className="mt-1 inline-flex items-center gap-1 text-xs font-semibold text-sky-700 hover:underline">
          {aideOuverte ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          {aideOuverte ? "Masquer les détails" : "Afficher les détails"}
        </button>
      </div>
      {aideOuverte && (
      <ul className="list-disc space-y-1 pl-5">
        <li>Où : ici (liste des postes), ou depuis le chat du support (fil du poste) → bouton <b>« Prendre la main »</b>, même sans session d'assistance.</li>
        <li>Accord obligatoire : l'utilisateur du poste accepte (ou réduit à « Voir seulement »), voit un bandeau rouge et peut <b>arrêter</b> à tout moment.</li>
        <li>Seuls les postes munis d'une <b>clé client</b> Loois peuvent être pris en main ; une session dure au plus 4 h.</li>
        <li>Les jetons de connexion servent une seule fois ; le mode « Voir seulement » est imposé par le serveur.</li>
        <li>Côté poste : Loois à jour (icône de la zone de notification lancée).</li>
        <li>
          <UserX className="inline h-4 w-4 text-indigo-600" aria-hidden="true" /> <b>Poste sans surveillance</b> : poste
          installé avec la clé « LKS-… » (Plateformes → Loois → Synchro → Clés clients). Le super-admin seul en prend la main,
          sans accord ni bandeau ; une notification discrète s'affiche sur le poste à chaque accès.
        </li>
        {/* Lot 135 */}
        <li>
          <ServerCog className="inline h-4 w-4 text-sky-600" aria-hidden="true" /> <b>Écran verrouillé, écran de connexion,
          session fermée</b> : fiche « … · service Windows » du poste (agent du service Windows Loois, compte SYSTEM). Le poste
          doit avoir le service Loois à jour ; l'icône Loois doit y avoir tourné une fois avec la clé client. Pour des raisons
          de sécurité, installer Loois et son service sous « Program Files ».
        </li>
        <li><b>Plusieurs postes en onglets</b> ; <b>vidéo</b> de chaque session dans le journal ; <b>clavier virtuel</b> (F1-F12, Windows, raccourcis) ;
          <b> blocage</b> du clavier et de la souris du poste ; <b>Ctrl+Alt+Suppr</b>, verrouiller, <b>déconnecter</b> l'utilisateur, <b>redémarrer</b>, <b>éteindre</b>.</li>
        <li><b>Fichiers</b> : glisser-déposer sur l'écran du poste (dossier « Reçu du support SAWALI » sur son Bureau) ; volet « Fichiers » pour en récupérer.</li>
        <li><b>Image fluide</b> : capture DXGI (carte graphique) quand Windows le permet (Windows 8 / Server 2012 et suivants), cadence et échelle adaptées aux connexions lentes.</li>
        <li><b>Identifiant Windows</b> mémorisé par poste (chiffré, jamais réaffiché) : saisi par le serveur sur l'écran de connexion à chaque nouvelle connexion.</li>
        <li><b>Numéro « CD-… »</b>, <b>ticket automatique</b> du client (clôturé en fin de session, intervention dans la fiche client) et <b>temps de connexion</b> au journal d'activités.</li>
        <li><b>Vidéos</b> supprimées automatiquement chaque nuit (03:20) au-delà de la durée de conservation réglée ci-dessous (90 jours par défaut) ; le journal, lui, est conservé.</li>
        <li>Volet repliable : <b>caractéristiques</b> matérielles et logicielles, <b>performances</b> en direct, <b>chat</b> avec l'utilisateur (même hors prise en main), fichiers.</li>
      </ul>
      )}

      {/* ---- Lot 135 : réglages ---- */}
      {reglages && (
        <div className="flex flex-wrap items-center gap-4 rounded-lg bg-slate-50 px-3 py-2 ring-1 ring-slate-200">
          <label className="inline-flex items-center gap-2">
            <input type="checkbox" checked={Boolean(reglages.enregistrement_video)} onChange={(e) => regler("enregistrement_video", e.target.checked)} />
            Enregistrer la vidéo de chaque session
          </label>
          <label className="inline-flex items-center gap-2">
            Images par seconde de la vidéo
            <select value={reglages.video_ips} onChange={(e) => regler("video_ips", Number(e.target.value))} className="rounded border border-slate-300 px-1 py-0.5 text-xs">
              {[1, 2, 5, 10, 15].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <label className="inline-flex items-center gap-2">
            <input type="checkbox" checked={Boolean(reglages.ticket_automatique)} onChange={(e) => regler("ticket_automatique", e.target.checked)} />
            Ticket automatique du client
          </label>
          {/* Lot 135.1 : durée de conservation des vidéos (purge automatique chaque nuit à 03:20) */}
          <label className="inline-flex items-center gap-2" title="Les vidéos plus anciennes sont supprimées chaque nuit à 03:20 ; le journal est conservé">
            Conserver les vidéos
            <input type="number" min={1} max={3650} value={jours} onChange={(e) => setJours(e.target.value)}
                   onBlur={() => { const n = parseInt(jours, 10); if (n >= 1 && n <= 3650 && n !== reglages.conservation_jours) regler("conservation_jours", n); else setJours(String(reglages.conservation_jours)); }}
                   className="w-20 rounded border border-slate-300 px-1 py-0.5 text-xs" data-testid="controle-distance-conservation" />
            jours
          </label>
          <button type="button" onClick={purgerMaintenant} disabled={purge}
                  className="inline-flex items-center gap-1 rounded-md bg-rose-600 px-2 py-1 text-xs font-semibold text-white hover:bg-rose-700 disabled:opacity-50">
            <Trash2 className="h-3.5 w-3.5" />Purger maintenant
          </button>
        </div>
      )}

      <h4 className="font-semibold text-slate-800">Postes Loois <span className="text-xs font-normal text-slate-500">({lignesPostes.length}{lignesPostes.length !== postes.length ? ` sur ${postes.length}` : ""})</span></h4>
      {postes.length === 0 && !chargement && <p className="text-xs text-slate-500">Aucun poste muni d'une clé client pour l'instant.</p>}
      {postes.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-xs" data-testid="postes-filtres">
          {/* Recherche : nom du poste (ou du client) */}
          <label className="relative">
            <Search className="pointer-events-none absolute left-2 top-1.5 h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
            <input type="search" value={recherche} onChange={(e) => setRecherche(e.target.value)} placeholder="Nom du poste…"
                   className="w-52 rounded border border-slate-300 py-1 pl-7 pr-2" data-testid="postes-recherche" />
          </label>
          {/* Liste déroulante des clients enregistrés */}
          <select value={clientFiltre} onChange={(e) => setClientFiltre(e.target.value)}
                  className="rounded border border-slate-300 px-2 py-1" data-testid="postes-client">
            <option value="">Tous les clients</option>
            {clientsPostes.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <label className="inline-flex items-center gap-1">
            Trier par
            <select value={tri} onChange={(e) => setTri(e.target.value)} className="rounded border border-slate-300 px-2 py-1" data-testid="postes-tri">
              <option value="client">Client (avec ruptures)</option>
              <option value="nom">Nom du poste</option>
              <option value="signal">Dernière connexion</option>
            </select>
          </label>
          <button type="button" onClick={() => setCroissant((v) => !v)} title={croissant ? "Ordre croissant" : "Ordre décroissant"}
                  className="inline-flex items-center gap-1 rounded border border-slate-300 px-2 py-1 hover:bg-slate-50">
            {croissant ? <ArrowUp className="h-3.5 w-3.5" /> : <ArrowDown className="h-3.5 w-3.5" />}{croissant ? "A → Z / ancien → récent" : "Z → A / récent → ancien"}
          </button>
          {nbMasques > 0 && (
            <label className="inline-flex items-center gap-1" title="Un ordinateur muni du service Windows n'est listé qu'une fois (la ligne « service Windows » fonctionne aussi écran verrouillé)">
              <input type="checkbox" checked={toutesSessions} onChange={(e) => setToutesSessions(e.target.checked)} data-testid="postes-toutes-sessions" />
              Afficher aussi les sessions utilisateur ({nbMasques} masquée{nbMasques > 1 ? "s" : ""})
            </label>
          )}
          {(recherche || clientFiltre) && (
            <button type="button" onClick={() => { setRecherche(""); setClientFiltre(""); }} className="text-sky-700 underline">Effacer les critères</button>
          )}
        </div>
      )}
      {postes.length > 0 && lignesPostes.length === 0 && <p className="text-xs text-slate-500">Aucun poste ne correspond aux critères.</p>}
      {lignesPostes.length > 0 && (
        <div className="max-h-96 overflow-auto">
          <table className="min-w-full text-xs">
            <thead className="sticky top-0 bg-white text-left text-slate-500">
              <tr>
                {[["nom", "Poste"], ["client", "Client"], ["signal", "Dernière connexion"]].map(([cle, titre]) => (
                  <th key={cle} className="px-2 py-1">
                    <button type="button" onClick={() => { if (tri === cle) setCroissant((v) => !v); else { setTri(cle); setCroissant(true); } }}
                            className={`inline-flex items-center gap-1 ${tri === cle ? "font-semibold text-slate-800" : ""}`}>
                      {titre}{tri === cle && (croissant ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
                    </button>
                  </th>
                ))}
                <th className="px-2 py-1"></th>
              </tr>
            </thead>
            <tbody>
              {lignesPostes.map((p, i) => {
                // Rupture sur le nom du client (tri par client) : une ligne d'en-tête avant chaque nouveau client
                const clientP = p.cle_client_libelle || p.cle_client_code || "(sans client)";
                const rupture = tri === "client" && (i === 0 || (lignesPostes[i - 1].cle_client_libelle || lignesPostes[i - 1].cle_client_code || "(sans client)") !== clientP);
                const nbClient = rupture ? lignesPostes.filter((q) => (q.cle_client_libelle || q.cle_client_code || "(sans client)") === clientP).length : 0;
                return (<React.Fragment key={p.id}>
                  {rupture && (
                    <tr className="bg-slate-100">
                      <td colSpan={4} className="px-2 py-1 font-semibold text-slate-700">{clientP} <span className="font-normal text-slate-500">· {nbClient} poste{nbClient > 1 ? "s" : ""}</span></td>
                    </tr>
                  )}
                  {(() => {
                const signal = p.signal_controle_distance || p.dernier_contact;
                const enLigne = signal && Date.now() - new Date(signal).getTime() < 2 * 60 * 1000;   // signal toutes les 5 s
                const interdit = p.sans_surveillance && !superAdmin;
                return (
                  <tr key={p.id} className="border-t border-slate-100">
                    <td className="px-2 py-1">
                      <span className={`mr-1 inline-block h-2 w-2 rounded-full ${enLigne ? "bg-emerald-500" : "bg-slate-300"}`} title={enLigne ? "En ligne" : "Hors ligne"} />
                      {p.nom}
                      {p.agent_service && (
                        <span className="ml-1 inline-flex items-center gap-0.5 rounded-full bg-sky-100 px-1.5 text-[10px] font-semibold text-sky-700" title="Agent du service Windows : écran verrouillé, écran de connexion, session fermée">
                          <ServerCog className="h-3 w-3" aria-hidden="true" />service Windows
                        </span>
                      )}
                      {p.sans_surveillance && (
                        <span className="ml-1 inline-flex items-center gap-0.5 rounded-full bg-indigo-100 px-1.5 text-[10px] font-semibold text-indigo-700" title="Clé sans surveillance : prise en main sans accord">
                          <UserX className="h-3 w-3" aria-hidden="true" />sans surveillance
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-1">{p.cle_client_libelle || p.cle_client_code}</td>
                    <td className="px-2 py-1 whitespace-nowrap">{dateLisible(signal)}</td>
                    <td className="px-2 py-1">
                      <span className="flex gap-1">
                        <button type="button" disabled={interdit} onClick={() => ouvrirPriseEnMain(p)}
                                title={interdit ? "Poste sans surveillance : réservé au super-admin" : "Prendre la main"}
                                className="grid h-7 w-7 place-items-center rounded-full bg-sky-600 text-white hover:bg-sky-700 disabled:opacity-30">
                          <MonitorSmartphone className="h-3.5 w-3.5" />
                        </button>
                        <button type="button" onClick={async () => {
                          try { const r = await apiClient.get(`/controle-distance/postes/${encodeURIComponent(p.id)}/identifiants`); setIdentifiantsDe({ poste: p, actuel: r.data }); }
                          catch { toast.error("Identifiant indisponible"); }
                        }} title="Identifiant Windows mémorisé pour ce poste"
                                className="grid h-7 w-7 place-items-center rounded-full bg-emerald-600 text-white hover:bg-emerald-700">
                          <KeyRound className="h-3.5 w-3.5" />
                        </button>
                      </span>
                    </td>
                  </tr>
                );
                  })()}
                </React.Fragment>);
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center gap-2">
        <h4 className="font-semibold text-slate-800">Journal des prises en main</h4>
        <button type="button" onClick={lire} disabled={chargement} title="Actualiser"
                className="rounded-md p-1 text-slate-600 hover:bg-slate-100 disabled:opacity-50">
          <RefreshCw className={`h-4 w-4 ${chargement ? "animate-spin" : ""}`} />
        </button>
      </div>
      {erreur && <p className="text-xs text-rose-600">{erreur}</p>}
      {!erreur && sessions.length === 0 && !chargement && (
        <p className="text-xs text-slate-500">Aucune prise en main pour l'instant.</p>
      )}
      {sessions.length > 0 && (
        <div className="overflow-x-auto">
          <table className="min-w-full text-xs">
            <thead className="text-left text-slate-500">
              <tr>
                <th className="px-2 py-1">N°</th>
                <th className="px-2 py-1">Date</th>
                <th className="px-2 py-1">Poste</th>
                <th className="px-2 py-1">Technicien</th>
                <th className="px-2 py-1">Mode</th>
                <th className="px-2 py-1">Statut</th>
                <th className="px-2 py-1">Accord / connexion</th>
                <th className="px-2 py-1">Durée</th>
                <th className="px-2 py-1">Ticket</th>
                <th className="px-2 py-1">Motif</th>
                <th className="px-2 py-1"></th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => {
                const [libelle, couleur] = STATUTS[s.statut] || [s.statut, "bg-slate-100 text-slate-600"];
                return (
                  <tr key={s.id} className={`cursor-pointer border-t border-slate-100 ${detail?.id === s.id ? "ligne-selectionnee" : ""}`}
                      onClick={() => setDetail(detail?.id === s.id ? null : s)} aria-selected={detail?.id === s.id}>
                    <td className="px-2 py-1 font-mono whitespace-nowrap">{s.numero || "—"}</td>
                    <td className="px-2 py-1 whitespace-nowrap">{dateLisible(s.cree_le)}</td>
                    <td className="px-2 py-1">{s.poste_nom || "—"}</td>
                    <td className="px-2 py-1">{s.technicien_nom || "—"}</td>
                    <td className="px-2 py-1">
                      {s.mode === "voir" ? "Voir seulement" : "Contrôle"}
                      {s.sans_surveillance && <UserX className="ml-1 inline h-3.5 w-3.5 text-indigo-600" title="Sans surveillance (accord automatique)" />}
                      {s.agent_service && <ServerCog className="ml-1 inline h-3.5 w-3.5 text-sky-600" title="Agent du service Windows" />}
                    </td>
                    <td className="px-2 py-1"><span className={`rounded-full px-2 py-0.5 ${couleur}`}>{libelle}</span></td>
                    <td className="px-2 py-1 whitespace-nowrap" title="Délai d'accord de l'utilisateur / d'ouverture des connexions">
                      {s.delai_accord_s !== undefined && s.delai_accord_s !== null ? `${dureeLisible(s.delai_accord_s)} / ${dureeLisible(s.delai_connexion_s)}` : "—"}
                    </td>
                    <td className="px-2 py-1">{dureeLisible(s.duree_s)}</td>
                    <td className="px-2 py-1 whitespace-nowrap">
                      {s.ticket_number ? (
                        <a href={`/portal/tickets?numero=${encodeURIComponent(s.ticket_number)}`} onClick={(e) => e.stopPropagation()}
                           className="inline-flex items-center gap-0.5 text-sky-700 hover:underline"><Ticket className="h-3 w-3" />{s.ticket_number}</a>
                      ) : "—"}
                    </td>
                    <td className="px-2 py-1 text-slate-500">{[s.motif, s.motif_fin].filter(Boolean).join(" · ") || "—"}</td>
                    <td className="px-2 py-1">
                      {s.video && (
                        <button type="button" onClick={(e) => { e.stopPropagation(); voirVideo(s); }} title="Voir la vidéo de la session"
                                className="text-rose-600 hover:text-rose-700"><PlayCircle className="h-4 w-4" /></button>
                      )}
                      {s.video_purgee && (
                        <span title={`Vidéo supprimée le ${dateLisible(s.video_purgee_le)} (durée de conservation dépassée)`}>
                          <VideoOff className="h-4 w-4 text-slate-400" />
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* ---- Lot 135 : détail d'une session (mesures et actions sensibles) ---- */}
      {detail && (
        <div className="rounded-lg bg-slate-50 p-3 text-xs ring-1 ring-slate-200">
          <div className="mb-1 font-semibold text-slate-800">{detail.numero} — {detail.poste_nom} {detail.client_nom ? `· ${detail.client_nom}` : ""}</div>
          {detail.mesures && (
            <p className="text-slate-600">
              1re image : {detail.mesures.premiere_image_ms !== undefined ? `${(detail.mesures.premiere_image_ms / 1000).toFixed(1)} s` : "—"} ·
              latence moyenne : {detail.mesures.latence_moy_ms ?? "—"} ms (max {detail.mesures.latence_max_ms ?? "—"}) ·
              {" "}{detail.mesures.ips_moyen ?? "—"} images/s · débit {detail.mesures.debit_moy_ko ?? "—"} Ko/s ·
              capture {(detail.mesures.capture || "—").toUpperCase()}
            </p>
          )}
          {detail.intervention_number && <p className="text-slate-600">Intervention {detail.intervention_number}</p>}
          {(detail.actions || []).length > 0 ? (
            <ul className="mt-1 list-disc pl-5 text-slate-600">
              {detail.actions.map((a, i) => <li key={i}>{dateLisible(a.le)} — {ACTIONS[a.type] || a.type} : {a.detail}</li>)}
            </ul>
          ) : <p className="text-slate-400">Aucune action sensible.</p>}
        </div>
      )}

      {/* ---- Lot 135 : lecture de la vidéo ---- */}
      {video && (
        <div className="fixed inset-0 z-[95] grid place-items-center bg-black/70 p-4" onClick={() => setVideo(null)}>
          <div className="w-full max-w-5xl rounded-xl bg-slate-900 p-3" onClick={(e) => e.stopPropagation()}>
            <div className="mb-2 flex items-center justify-between text-sm text-white">
              <span>{video.titre}</span>
              <button type="button" onClick={() => setVideo(null)} className="rounded-full p-1 hover:bg-white/10"><X className="h-4 w-4" /></button>
            </div>
            <video src={video.url} controls autoPlay className="max-h-[75vh] w-full rounded bg-black" />
          </div>
        </div>
      )}

      {/* ---- Lot 135 : identifiant Windows d'un poste ---- */}
      {identifiantsDe && (
        <div className="fixed inset-0 z-[95]">
          <FenetreIdentifiants posteId={identifiantsDe.poste.id} actuel={identifiantsDe.actuel} onFermer={() => setIdentifiantsDe(null)} />
        </div>
      )}
    </div>
  );
}
