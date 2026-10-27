// =====================================================================
// Lot 135 — VOLET DÉPLIABLE de la visionneuse (items 10, 11 et 1) :
//   - « Poste »    : caractéristiques matérielles et logicielles (inventaire envoyé par Loois) + performances en direct ;
//   - « Chat »     : discussion avec l'utilisateur du poste dans le fil « Support Loois » existant — fonctionne AVANT,
//                    PENDANT et APRÈS la prise en main (même si l'écran n'est pas connecté) ;
//   - « Fichiers » : parcours des dossiers du poste et récupération d'un fichier (l'envoi se fait par glisser-déposer
//                    sur l'écran du poste).
// =====================================================================
import React, { useCallback, useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  Cpu, MemoryStick, HardDrive, Network, Monitor, Package, Send, MessageSquare, FolderOpen, Folder, FileText,
  ArrowUp, RefreshCw, Download, Activity, Info, Home, Copy, Pin, X, RotateCcw, Trash2, TimerReset,
} from "lucide-react";
import { dateLisible, tailleLisible, dureeLisible, autresPostes } from "./outils";
import { CRITERES_TRI, trierEntrees } from "./tri";

// Petite jauge horizontale (pourcentage), couleur selon le niveau
function Jauge({ valeur, libelle, icone: Icone }) {
  const v = Math.max(0, Math.min(100, Number(valeur) || 0));
  const couleur = v >= 90 ? "bg-rose-500" : v >= 70 ? "bg-amber-400" : "bg-emerald-400";
  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between text-[11px] text-slate-300">
        <span className="inline-flex items-center gap-1"><Icone className="h-3.5 w-3.5" />{libelle}</span>
        <span className="font-mono">{v.toFixed(0)} %</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-white/10"><div className={`h-full ${couleur} transition-all`} style={{ width: `${v}%` }} /></div>
    </div>
  );
}

// Ligne « libellé : valeur » (rien si la valeur est vide)
const Ligne = ({ l, v }) => (v === null || v === undefined || v === "" ? null : (
  <div className="flex justify-between gap-2 text-[11px]"><span className="text-slate-400">{l}</span><span className="text-right text-slate-100">{v}</span></div>
));

// ---------------------------------------------------------------------
// Onglet « Poste » : inventaire + performances
// ---------------------------------------------------------------------
function OngletPoste({ infos, perf, onActualiser, actif }) {
  const [filtre, setFiltre] = useState("");
  const inv = infos?.inventaire || {};
  const sys = inv.systeme || {};
  const proc = inv.processeur || {};
  const mem = inv.memoire || {};
  const logiciels = (inv.logiciels || []).filter((l) => !filtre || `${l.nom} ${l.editeur || ""}`.toLowerCase().includes(filtre.toLowerCase()));
  return (
    <div className="space-y-3">
      {/* Performances en direct (toutes les 2 s pendant la session) */}
      <section className="space-y-1.5 rounded-xl bg-white/5 p-2.5 ring-1 ring-white/10">
        <h5 className="flex items-center gap-1 text-xs font-semibold text-sky-300"><Activity className="h-3.5 w-3.5" />Performances {perf ? "" : "(pendant la session)"}</h5>
        {perf && (
          <>
            <Jauge valeur={perf.cpu} libelle="Processeur" icone={Cpu} />
            <Jauge valeur={perf.memoire_pct} libelle={`Mémoire (${(perf.memoire_utilisee_mo / 1024).toFixed(1)} / ${(perf.memoire_totale_mo / 1024).toFixed(1)} Go)`} icone={MemoryStick} />
            <Jauge valeur={perf.disque_pct} libelle={`Disque système (${perf.disque_libre_go} Go libres)`} icone={HardDrive} />
            <Ligne l="Réseau ↓ / ↑" v={`${perf.reseau_recu_ko} / ${perf.reseau_envoye_ko} Ko/s`} />
            <Ligne l="Tâches" v={perf.processus} />
            <Ligne l="Allumé depuis" v={dureeLisible(perf.demarre_depuis_s)} />
            {(perf.gourmands || []).length > 0 && (
              <div className="pt-1 text-[11px] text-slate-300">
                Plus gourmands : {perf.gourmands.map((g) => `${g.nom} (${g.memoire_mo} Mo)`).join(", ")}
              </div>
            )}
          </>
        )}
      </section>

      {/* Caractéristiques (inventaire) */}
      <section className="space-y-1 rounded-xl bg-white/5 p-2.5 ring-1 ring-white/10">
        <h5 className="flex items-center justify-between text-xs font-semibold text-sky-300">
          <span className="inline-flex items-center gap-1"><Monitor className="h-3.5 w-3.5" />Matériel et système</span>
          <button type="button" disabled={!actif} onClick={onActualiser} title="Relire l'inventaire du poste" className="rounded p-0.5 hover:bg-white/10 disabled:opacity-30">
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </h5>
        {!infos && <p className="text-[11px] text-slate-400">Reçu du poste au début de la prise en main.</p>}
        {infos && (
          <>
            <Ligne l="Ordinateur" v={infos.machine} />
            <Ligne l="Utilisateur Windows" v={infos.utilisateur_session || "personne (écran de connexion)"} />
            <Ligne l="Session" v={infos.session_verrouillee ? "verrouillée" : "ouverte"} />
            <Ligne l="Système" v={[sys.nom, sys.version].filter(Boolean).join(" · ")} />
            <Ligne l="Architecture" v={sys.architecture} />
            <Ligne l="Fabricant / modèle" v={[sys.fabricant, sys.modele].filter(Boolean).join(" · ")} />
            <Ligne l="N° de série" v={sys.numero_serie} />
            <Ligne l="Domaine / groupe" v={sys.domaine || sys.groupe_travail} />
            <Ligne l="Processeur" v={proc.nom ? `${proc.nom} (${proc.coeurs_logiques || "?"} cœurs)` : null} />
            <Ligne l="Mémoire" v={mem.totale_go ? `${mem.totale_go} Go (${mem.utilisee_pct ?? "?"} % utilisés)` : null} />
            {(inv.disques || []).map((d) => (
              <Ligne key={d.lettre} l={`Disque ${d.lettre}`} v={`${d.libre_go} / ${d.total_go} Go libres${d.format ? ` · ${d.format}` : ""}`} />
            ))}
            {(inv.reseau || []).map((r) => (
              <Ligne key={r.nom} l={<span className="inline-flex items-center gap-1"><Network className="h-3 w-3" />{r.nom}</span>}
                     v={[(r.ipv4 || []).join(", "), r.mac, r.vitesse_mbps ? `${r.vitesse_mbps} Mb/s` : null].filter(Boolean).join(" · ")} />
            ))}
            <Ligne l="Loois" v={infos.version_loois} />
            <Ligne l="Capture" v={infos.capture === "dxgi" ? "DXGI (carte graphique)" : "GDI (classique)"} />
          </>
        )}
      </section>

      {/* Logiciels installés */}
      {infos && (
        <section className="space-y-1 rounded-xl bg-white/5 p-2.5 ring-1 ring-white/10">
          <h5 className="flex items-center gap-1 text-xs font-semibold text-sky-300"><Package className="h-3.5 w-3.5" />Logiciels installés ({(inv.logiciels || []).length})</h5>
          <input value={filtre} onChange={(e) => setFiltre(e.target.value)} placeholder="Rechercher un logiciel…"
                 className="w-full rounded-md bg-white/10 px-2 py-1 text-[11px] text-slate-100 outline-none placeholder:text-slate-400" />
          <div className="max-h-56 overflow-auto">
            {logiciels.slice(0, 400).map((l, i) => (
              <div key={`${l.nom}-${i}`} className="flex justify-between gap-2 border-b border-white/5 py-0.5 text-[11px]">
                <span className="truncate text-slate-100" title={l.editeur || ""}>{l.nom}</span>
                <span className="shrink-0 text-slate-400">{l.version}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------
// Onglet « Chat » : fil « Support Loois » du poste (chat interne existant)
// ---------------------------------------------------------------------
function OngletChat({ filId }) {
  const [messages, setMessages] = useState([]);
  const [texte, setTexte] = useState("");
  const [envoi, setEnvoi] = useState(false);
  const basRef = useRef(null);

  const lire = useCallback(async () => {
    if (!filId) return;
    try {
      const r = await apiClient.get("/me/chat/support-loois/messages", { params: { with_user: filId, limit: 60 } });
      setMessages(Array.isArray(r.data) ? r.data : []);
    } catch { /* fil indisponible : nouvel essai au prochain tour */ }
  }, [filId]);

  // Lecture toutes les 4 s (le chat continue même sans prise en main en cours)
  useEffect(() => {
    lire();
    const t = setInterval(lire, 4000);
    return () => clearInterval(t);
  }, [lire]);
  useEffect(() => { basRef.current?.scrollIntoView({ block: "end" }); }, [messages.length]);

  const envoyer = async () => {
    const t = texte.trim();
    if (!t || !filId) return;
    setEnvoi(true);
    try {
      await apiClient.post("/me/chat/support-loois/messages", { text: t, recipient_id: filId });
      setTexte("");
      lire();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Message non envoyé");
    } finally {
      setEnvoi(false);
    }
  };

  if (!filId) {
    return <p className="text-[11px] text-slate-400">Aucun utilisateur Loois connu sur ce poste : le chat s'ouvrira dès qu'un utilisateur aura lancé l'icône Loois.</p>;
  }
  return (
    <div className="flex h-full flex-col">
      <p className="mb-2 text-[10px] text-slate-400">
        Fil « Support Loois » du poste : le message ouvre la fenêtre du support chez l'utilisateur, prise en main en cours ou non.
      </p>
      <div className="min-h-0 flex-1 space-y-1.5 overflow-auto pr-1">
        {messages.map((m) => {
          const duPoste = m.sender_id === filId;
          return (
            <div key={m.id} className={`flex ${duPoste ? "justify-start" : "justify-end"}`}>
              <div className={`max-w-[85%] rounded-2xl px-2.5 py-1.5 text-[12px] ${duPoste ? "bg-white/10 text-slate-100" : "bg-sky-600 text-white"}`}>
                {!duPoste && <div className="text-[10px] opacity-75">{m.sender_name}</div>}
                <div className="whitespace-pre-wrap break-words">{m.text}</div>
                <div className="mt-0.5 text-right text-[9px] opacity-60">{dateLisible(m.created_at)}</div>
              </div>
            </div>
          );
        })}
        <div ref={basRef} />
      </div>
      <div className="mt-2 flex items-end gap-1">
        <textarea value={texte} onChange={(e) => setTexte(e.target.value)} rows={2} maxLength={2000}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); envoyer(); } e.stopPropagation(); }}
                  placeholder="Écrire à l'utilisateur du poste…"
                  className="min-w-0 flex-1 resize-none rounded-lg bg-white/10 px-2 py-1 text-[12px] text-slate-100 outline-none placeholder:text-slate-400" />
        <button type="button" onClick={envoyer} disabled={envoi || !texte.trim()} title="Envoyer"
                className="grid h-9 w-9 place-items-center rounded-full bg-sky-500 text-white hover:bg-sky-400 disabled:opacity-40">
          <Send className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------
// Onglet « Fichiers » : dossiers du poste ; un clic sur un fichier le récupère
// ---------------------------------------------------------------------
function OngletFichiers({ liste, transferts, envoyer, actif, posteId, dossiers, onDossierBase, onDemanderFichier, onReprendre, onReprendreTous, onEffacer, onProlonger, onAnnuler }) {
  const [chemin, setChemin] = useState("");
  const [copieDe, setCopieDe] = useState(null);   // fichier dont on choisit le poste de destination
  // Lot 283 : tri de la liste (nom, date/heure, taille ; croissant ou décroissant), mémorisé pendant la session
  const [tri, setTri] = useState({ critere: "nom", sens: "asc" });
  const choisirTri = (critere) => setTri((t) => (t.critere === critere
    ? { critere, sens: t.sens === "asc" ? "desc" : "asc" }          // même critère : on inverse le sens
    : { critere, sens: critere === "nom" ? "asc" : "desc" }));      // nouveau critère : date/taille = plus récent/plus gros d'abord
  const entreesTriees = trierEntrees(liste?.entrees, tri.critere, tri.sens);
  const ouvrir = (c) => { setChemin(c); envoyer({ type: "fichiers_lister", chemin: c }); };
  // Lot 135 : départ = dernier dossier parcouru (mémorisé à la fermeture), sinon le dossier de base, sinon les points de départ
  const depart = dossiers?.dernier_chemin || dossiers?.dossier_base || "";
  const destinations = autresPostes(posteId);
  const parent = () => {
    if (!liste?.chemin) return ouvrir("");
    const morceaux = liste.chemin.replace(/[\\/]+$/, "").split(/[\\/]/);
    if (morceaux.length <= 1) return ouvrir("");
    morceaux.pop();
    return ouvrir(morceaux.join("\\") + (morceaux.length === 1 ? "\\" : ""));
  };
  // Lot 284 : anti double-clic — un même fichier ne peut pas être demandé deux fois en moins de 3 secondes
  const dernierEnvoi = useRef({});
  const lancerTelechargement = (nom) => {
    const maintenant = Date.now();
    if (maintenant - (dernierEnvoi.current[nom] || 0) < 3000) return;
    dernierEnvoi.current[nom] = maintenant;
    onDemanderFichier?.(joindre(nom));
  };
  const joindre = (nom) => (liste?.chemin ? `${liste.chemin.replace(/[\\/]+$/, "")}\\${nom}` : nom);
  return (
    <div className="space-y-2">
      <p className="text-[10px] text-slate-400">
        Envoyer : glissez-déposez des fichiers sur l'écran du poste. Récupérer : parcourez les dossiers et cliquez sur un fichier ;
        « Copier vers » l'envoie à un autre poste contrôlé (autre onglet).
      </p>
      {/* Lot 135 : dossier de base mémorisé pour ce poste (arrivée des fichiers envoyés et point de départ) */}
      <div className="rounded-lg bg-white/5 p-2 text-[11px] ring-1 ring-white/10">
        <div className="flex items-center gap-1 text-slate-300">
          <Home className="h-3.5 w-3.5 text-amber-300" />
          <span className="min-w-0 flex-1 truncate" title={dossiers?.dossier_base || ""}>
            Dossier de base : {dossiers?.dossier_base || "« Reçu du support SAWALI » sur le Bureau"}
          </span>
        </div>
        <div className="mt-1 flex gap-1">
          <button type="button" disabled={!actif || !liste?.chemin} onClick={() => onDossierBase?.(liste.chemin)}
                  className="inline-flex items-center gap-1 rounded bg-amber-600/80 px-1.5 py-0.5 text-white hover:bg-amber-500 disabled:opacity-30"
                  title="Les fichiers envoyés à ce poste arriveront dans le dossier affiché">
            <Pin className="h-3 w-3" />Dossier affiché = dossier de base
          </button>
          {dossiers?.dossier_base && (
            <button type="button" disabled={!actif} onClick={() => ouvrir(dossiers.dossier_base)} className="rounded bg-white/10 px-1.5 py-0.5 hover:bg-white/20 disabled:opacity-30">Ouvrir</button>
          )}
          {dossiers?.dossier_base && (
            <button type="button" onClick={() => onDossierBase?.("")} className="rounded bg-white/10 px-1.5 py-0.5 hover:bg-white/20">Effacer</button>
          )}
        </div>
      </div>
      <div className="flex items-center gap-1">
        <button type="button" disabled={!actif} onClick={parent} title="Dossier parent" className="rounded p-1 hover:bg-white/10 disabled:opacity-30"><ArrowUp className="h-4 w-4" /></button>
        <button type="button" disabled={!actif} onClick={() => ouvrir(liste?.chemin ?? chemin)} title="Actualiser" className="rounded p-1 hover:bg-white/10 disabled:opacity-30"><RefreshCw className="h-4 w-4" /></button>
        <span className="truncate text-[11px] text-slate-300" title={liste?.chemin}>{liste?.chemin || "Points de départ"}</span>
      </div>
      {!actif && <p className="text-[11px] text-slate-400">Disponible pendant une prise en main en mode « Contrôler ».</p>}
      {actif && !liste && (
        <button type="button" onClick={() => ouvrir(depart)} className="inline-flex items-center gap-1 rounded-md bg-sky-600 px-2 py-1 text-[11px] text-white hover:bg-sky-500"
                title={depart ? `Reprendre à : ${depart}` : "Points de départ du poste"}>
          <FolderOpen className="h-3.5 w-3.5" /> Parcourir le poste
        </button>
      )}
      {liste?.erreur && <p className="text-[11px] text-rose-300">{liste.erreur}</p>}
      {/* Lot 283 : barre de tri */}
      {(liste?.entrees || []).length > 1 && (
        <div className="flex items-center gap-1 text-[10px] text-slate-400" data-testid="tri-fichiers">
          <span>Trier :</span>
          {CRITERES_TRI.map((c) => (
            <button key={c.id} type="button" onClick={() => choisirTri(c.id)} aria-pressed={tri.critere === c.id}
                    className={`rounded px-1.5 py-0.5 ${tri.critere === c.id ? "bg-sky-600 text-white" : "bg-white/10 hover:bg-white/20"}`}>
              {c.libelle}{tri.critere === c.id ? (tri.sens === "asc" ? " ▲" : " ▼") : ""}
            </button>
          ))}
        </div>
      )}
      <div className="max-h-[50vh] overflow-auto">
        {entreesTriees.map((e) => (
          <div key={e.nom} className="relative">
            <div className="flex items-center gap-1 rounded px-1 py-0.5 text-[11px] text-slate-100 hover:bg-white/10">
              {/* Lot 284 : un dossier s'ouvre au clic sur son nom ; un fichier ne se télécharge QUE par le pictogramme */}
              {e.dossier ? (
                <button type="button" disabled={!actif} onClick={() => ouvrir(joindre(e.nom))}
                        className="flex min-w-0 flex-1 items-center gap-1.5 text-left" title="Ouvrir">
                  <Folder className="h-3.5 w-3.5 shrink-0 text-amber-300" />
                  <span className="min-w-0 flex-1 truncate">{e.nom}</span>
                  <span className="shrink-0 text-[10px] text-slate-500" title="Dernière modification">{dateLisible(e.modifie)}</span>
                </button>
              ) : (
                <div className="flex min-w-0 flex-1 items-center gap-1.5">
                  <FileText className="h-3.5 w-3.5 shrink-0 text-sky-300" />
                  <span className="min-w-0 flex-1 truncate" title={e.nom}>{e.nom}</span>
                  <span className="shrink-0 text-[10px] text-slate-500" title="Dernière modification">{dateLisible(e.modifie)}</span>
                  <span className="shrink-0 text-slate-400">{tailleLisible(e.taille)}</span>
                  <button type="button" disabled={!actif} onClick={() => lancerTelechargement(e.nom)}
                          className="shrink-0 rounded p-0.5 text-slate-400 hover:bg-white/10 hover:text-white disabled:opacity-30"
                          title="Télécharger ce fichier" data-testid="telecharger-fichier">
                    <Download className="h-3.5 w-3.5" />
                  </button>
                </div>
              )}
              {/* Lot 135 : copie de poste à poste */}
              {!e.dossier && (
                <button type="button" disabled={!actif || destinations.length === 0} onClick={() => setCopieDe(copieDe === e.nom ? null : e.nom)}
                        title={destinations.length ? "Copier vers un autre poste contrôlé" : "Ouvrez un autre poste en mode « Contrôler » (onglet) pour y copier ce fichier"}
                        className="shrink-0 rounded p-0.5 text-slate-400 hover:bg-white/10 hover:text-white disabled:opacity-30">
                  <Copy className="h-3 w-3" />
                </button>
              )}
            </div>
            {copieDe === e.nom && (
              <div className="ml-6 mt-0.5 space-y-0.5 rounded-lg bg-slate-800 p-1 ring-1 ring-white/10">
                <div className="px-1 text-[10px] text-slate-400">Copier vers :</div>
                {destinations.map((d) => (
                  <button key={d.id} type="button" onClick={() => { setCopieDe(null); onDemanderFichier?.(joindre(e.nom), d); }}
                          className="block w-full truncate rounded px-1 py-0.5 text-left text-[11px] text-slate-100 hover:bg-sky-600">
                    {d.nom}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      {/* Lot 281 : prolonger la session (+2 h, plafond 12 h) — la session n'est de toute façon jamais coupée en plein transfert */}
      {actif && (
        <button type="button" onClick={() => onProlonger?.()} title="Ajoute 2 heures à la durée de la session (12 heures au plus). Un transfert en cours n'est jamais coupé."
                className="inline-flex items-center gap-1 rounded-md bg-white/5 px-2 py-1 text-[11px] text-slate-200 hover:bg-white/10" data-testid="prolonger-session">
          <TimerReset className="h-3.5 w-3.5" /> Prolonger la session (+2 h)
        </button>
      )}
      {transferts.length > 0 && (
        <section className="space-y-1 border-t border-white/10 pt-2" data-testid="transferts">
          <div className="flex items-center justify-between gap-2">
            <h5 className="text-[11px] font-semibold text-slate-300">Transferts</h5>
            <div className="flex items-center gap-1">
              {transferts.some((t) => t.interrompu && t.reprenable) && (
                <button type="button" disabled={!actif} onClick={() => onReprendreTous?.()} title="Reprendre tous les transferts interrompus, là où ils se sont arrêtés"
                        className="inline-flex items-center gap-1 rounded bg-sky-600 px-1.5 py-0.5 text-[10px] text-white hover:bg-sky-500 disabled:opacity-30" data-testid="reprendre-tous">
                  <RotateCcw className="h-3 w-3" /> Tout reprendre
                </button>
              )}
              {transferts.some((t) => t.fini || t.erreur) && (
                <button type="button" onClick={() => onEffacer?.()} title="Efface de la liste les transferts terminés ou en échec (les transferts en cours restent)"
                        className="inline-flex items-center gap-1 rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-slate-200 hover:bg-white/20" data-testid="effacer-historique">
                  <Trash2 className="h-3 w-3" /> Effacer l'historique
                </button>
              )}
            </div>
          </div>
          <div className="max-h-[30vh] space-y-1 overflow-auto pr-1">
            {[...transferts].reverse().map((t) => {
              const pct = Math.round((100 * t.fait) / Math.max(1, t.taille));
              return (
                <div key={t.uid ?? `${t.sens}-${t.id}`} className="text-[11px]" data-testid="transfert">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate" title={t.nom}>{t.sens === "envoi" ? "↑" : "↓"} {t.nom}</span>
                    <span className="flex shrink-0 items-center gap-1">
                      <span className={t.interrompu ? "text-amber-300" : t.erreur ? "text-rose-300" : t.fini ? "text-emerald-300" : "text-slate-400"}>
                        {t.interrompu ? `interrompu ${pct} %` : t.erreur ? "échec" : t.fini ? "terminé" : (t.sens === "envoi" && pct >= 100 ? "100 % — confirmation du poste…" : `${pct} %`)}
                      </span>
                      {/* Lot 284 : annuler un transfert en cours */}
                      {!t.fini && !t.erreur && !t.interrompu && (
                        <button type="button" onClick={() => onAnnuler?.(t)} title="Annuler ce transfert (le fichier partiel est abandonné)"
                                className="inline-flex items-center gap-0.5 rounded bg-rose-600/80 px-1 py-0.5 text-[10px] text-white hover:bg-rose-500" data-testid="annuler-transfert"><X className="h-3 w-3" />Annuler</button>
                      )}
                      {t.interrompu && t.reprenable && (
                        <button type="button" disabled={!actif} onClick={() => onReprendre?.(t)} title="Reprendre ce transfert là où il s'est arrêté"
                                className="rounded p-0.5 text-sky-300 hover:bg-white/10 disabled:opacity-30" data-testid="reprendre-transfert"><RotateCcw className="h-3 w-3" /></button>
                      )}
                      {(t.fini || t.erreur) && (
                        <button type="button" onClick={() => onEffacer?.(t)} title="Retirer cette ligne de la liste"
                                className="rounded p-0.5 text-slate-400 hover:bg-white/10 hover:text-white" data-testid="effacer-transfert"><X className="h-3 w-3" /></button>
                      )}
                    </span>
                  </div>
                  <div className="h-1 overflow-hidden rounded bg-white/10"><div className={`h-full ${t.interrompu ? "bg-amber-400" : t.erreur ? "bg-rose-500" : "bg-sky-400"}`} style={{ width: `${Math.min(100, pct)}%` }} /></div>
                  {(t.erreur || t.chemin) && <div className="truncate text-[10px] text-slate-400" title={t.erreur || t.chemin}>{t.erreur || t.chemin}</div>}
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------
// Le volet lui-même
// ---------------------------------------------------------------------
export default function VoletPoste({ onglet, setOnglet, infos, perf, filId, liste, transferts, envoyer, peutAgir, actif,
                                     posteId, dossiers, onDossierBase, onDemanderFichier, onReprendre, onReprendreTous, onEffacer, onProlonger }) {
  const ONGLETS = [["poste", "Poste", Info], ["chat", "Chat", MessageSquare], ["fichiers", "Fichiers", FolderOpen]];
  return (
    <aside className="flex w-80 shrink-0 flex-col border-l border-white/10 bg-slate-950/70 backdrop-blur" data-testid="controle-distance-volet">
      <div className="flex gap-1 p-2">
        {ONGLETS.map(([cle, libelle, Icone]) => (
          <button key={cle} type="button" onClick={() => setOnglet(cle)}
                  className={`inline-flex flex-1 items-center justify-center gap-1 rounded-lg px-2 py-1 text-[11px] font-semibold ${onglet === cle ? "bg-sky-600 text-white" : "bg-white/5 text-slate-300 hover:bg-white/10"}`}>
            <Icone className="h-3.5 w-3.5" />{libelle}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-3 pb-3">
        {onglet === "poste" && <OngletPoste infos={infos} perf={perf} actif={actif} onActualiser={() => envoyer({ type: "infos_demander" })} />}
        {onglet === "chat" && <OngletChat filId={filId} />}
        {onglet === "fichiers" && <OngletFichiers liste={liste} transferts={transferts} envoyer={envoyer} actif={peutAgir} posteId={posteId}
                                                  dossiers={dossiers} onDossierBase={onDossierBase} onDemanderFichier={onDemanderFichier}
                                                  onReprendre={onReprendre} onReprendreTous={onReprendreTous} onEffacer={onEffacer} onProlonger={onProlonger} />}
      </div>
    </aside>
  );
}
