// DetailsPoste.jsx — Lot 66 : lien « Détails » d'un poste dans « Postes et serveurs — versions déployées ».
//
// Fenêtre qui réunit tout ce que Loois envoie sur une machine (inventaire joint au signal de présence,
// au plus toutes les 30 minutes) et se relit toute seule toutes les 60 secondes tant qu'elle est ouverte :
//   - identité : machine, site(s), utilisateurs, composants (Loois, service, zone de notification…) avec
//     leur version et leur dernier signal ;
//   - système : Windows, fabricant / modèle, durée depuis le démarrage, domaine, dossier de Loois, .NET ;
//   - processeur et mémoire vive (jauge), disques (barre d'espace libre, rouge sous 10 %) ;
//   - réseau : cartes actives avec adresse MAC, IPv4 / IPv6, passerelle, DNS ;
//   - tâches en cours : tableau triable (mémoire, nom) avec recherche ;
//   - lien vers la fiche de l'équipement dans « Parc informatique » (créée automatiquement).
// API : GET /api/admin/versions-deployees/poste-details?machine=…&application=… (backend/routes/versions_deployees.py)
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Loader2, RefreshCw, X } from "lucide-react";
import { apiClient } from "@/lib/api";

const INTERVALLE_MS = 60000;   // relecture automatique toutes les 60 secondes

// « 06/10/2026 10:44 » (vide si la date est absente ou illisible)
function dateCourte(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }).replace(",", "");
}

// « il y a 3 min » / « il y a 2 h » / date complète au-delà d'un jour
function depuis(iso) {
  const d = new Date(iso);
  if (!iso || Number.isNaN(d.getTime())) return "—";
  const min = Math.round((Date.now() - d.getTime()) / 60000);
  if (min < 1) return "à l'instant";
  if (min < 60) return `il y a ${min} min`;
  if (min < 24 * 60) return `il y a ${Math.round(min / 60)} h`;
  return dateCourte(iso);
}

// Durée depuis le démarrage de Windows : « 3 j 4 h », « 2 h 15 min »
function duree(minutes) {
  if (minutes === null || minutes === undefined) return "—";
  const j = Math.floor(minutes / 1440);
  const h = Math.floor((minutes % 1440) / 60);
  const m = minutes % 60;
  if (j > 0) return `${j} j ${h} h`;
  return h > 0 ? `${h} h ${String(m).padStart(2, "0")} min` : `${m} min`;
}

// Nombre au format français (« 12,4 »), tiret si absent
const nombre = (v, suffixe = "") => (v === null || v === undefined ? "—" : `${Number(v).toLocaleString("fr-FR")}${suffixe}`);

// Barre horizontale de remplissage (pourcentage 0-100) ; couleur imposée par l'appelant
function Barre({ pct, couleur }) {
  const p = Math.max(0, Math.min(100, Number(pct) || 0));
  return (
    <div className="h-2.5 w-full overflow-hidden rounded-full bg-slate-200">
      <div className={`h-full rounded-full ${couleur}`} style={{ width: `${p}%` }} />
    </div>
  );
}

// Bloc titré de la fenêtre (même style de carte que la page)
function Bloc({ titre, children, className = "" }) {
  return (
    <div className={`rounded-xl bg-white p-3 ring-1 ring-slate-200 ${className}`}>
      <h4 className="mb-2 text-sm font-semibold text-slate-700">{titre}</h4>
      {children}
    </div>
  );
}

// Ligne « libellé : valeur » des blocs système / processeur
const Ligne = ({ libelle, valeur }) => (
  <div className="flex justify-between gap-3 py-0.5 text-sm">
    <span className="text-slate-500">{libelle}</span>
    <span className="text-right font-medium break-all">{valeur || "—"}</span>
  </div>
);

export default function DetailsPoste({ machine, application, onClose }) {
  const [donnees, setDonnees] = useState(null);
  const [erreur, setErreur] = useState("");
  const [chargement, setChargement] = useState(false);
  const [recherche, setRecherche] = useState("");                     // filtre des tâches en cours
  const [tri, setTri] = useState({ colonne: "memoire_mo", sens: -1 });  // tri des tâches (mémoire décroissante)
  const [selection, setSelection] = useState(null);                   // ligne sélectionnée (règle des tableaux)
  const premiere = useRef(true);

  // Lecture des détails ; la toute première lecture affiche le toast « Patientez… »
  const lire = useCallback(async () => {
    const attente = premiere.current ? toast.loading("Patientez…") : null;
    setChargement(true);
    try {
      const r = await apiClient.get("/admin/versions-deployees/poste-details", { params: { machine, application } });
      setDonnees(r.data); setErreur("");
      if (attente) toast.dismiss(attente);
    } catch (err) {
      const message = err?.response?.data?.detail || "Détails du poste indisponibles";
      setErreur(message);
      if (attente) toast.error(message, { id: attente });
    } finally {
      premiere.current = false;
      setChargement(false);
    }
  }, [machine, application]);

  // Relecture toutes les 60 secondes tant que la fenêtre est ouverte (et l'onglet visible)
  useEffect(() => {
    lire();
    const t = setInterval(() => { if (!document.hidden) lire(); }, INTERVALLE_MS);
    return () => clearInterval(t);
  }, [lire]);

  // Touche Échap : fermeture de la fenêtre
  useEffect(() => {
    const touche = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", touche);
    return () => window.removeEventListener("keydown", touche);
  }, [onClose]);

  const inv = donnees?.inventaire || null;
  const systeme = inv?.systeme || {};
  const memoire = inv?.memoire || {};

  // Tâches en cours : recherche par nom ou PID, puis tri sur la colonne choisie
  const taches = useMemo(() => {
    const q = recherche.trim().toLowerCase();
    const liste = (inv?.processus || []).filter((p) => !q || (p.nom || "").toLowerCase().includes(q) || String(p.pid).includes(q));
    const { colonne, sens } = tri;
    return [...liste].sort((a, b) => {
      const x = a[colonne]; const y = b[colonne];
      if (typeof x === "string" || typeof y === "string") return sens * String(x || "").localeCompare(String(y || ""), "fr");
      return sens * ((x || 0) - (y || 0));
    });
  }, [inv, recherche, tri]);

  // Clic sur un en-tête : même colonne = sens inversé ; autre colonne = tri par défaut de cette colonne
  const trier = (colonne) => setTri((t) => (t.colonne === colonne ? { colonne, sens: -t.sens } : { colonne, sens: colonne === "nom" ? 1 : -1 }));
  const fleche = (colonne) => (tri.colonne === colonne ? (tri.sens < 0 ? " ▼" : " ▲") : "");

  // Identité : sites et utilisateurs vus sur la machine (tous composants confondus)
  const composants = donnees?.composants || [];
  const sites = [...new Set(composants.map((c) => c.site).filter(Boolean))];
  const utilisateurs = [...new Set(composants.map((c) => c.utilisateur).filter(Boolean))];
  const enLigne = composants.some((c) => c.en_ligne);
  const equipement = donnees?.equipement;

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 p-2 sm:p-4" onClick={onClose}>
      <div className="max-h-[94vh] w-full max-w-5xl space-y-3 overflow-y-auto rounded-2xl bg-slate-50 p-4 shadow-xl sm:p-5"
        onClick={(e) => e.stopPropagation()} data-testid="details-poste">
        {/* En-tête : machine, état, date du dernier inventaire, actualisation, fermeture */}
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h3 className="flex items-center gap-2 text-lg font-display font-bold">
              <span className={`inline-block h-3 w-3 rounded-full ${enLigne ? "bg-emerald-500" : "bg-slate-300"}`}
                title={enLigne ? "En cours d'exécution" : "Aucun signal récent"} />
              🖥️ {donnees?.machine || machine}
            </h3>
            <p className="text-xs text-slate-500">
              {donnees?.inventaire_le
                ? <>Inventaire actualisé {depuis(donnees.inventaire_le)} ({dateCourte(donnees.inventaire_le)}, envoyé par {donnees.inventaire_composant || "Loois"}) · relu automatiquement toutes les minutes</>
                : "Aucun inventaire reçu pour ce poste : il arrive avec la nouvelle version de Loois (premier signal, puis toutes les 30 minutes)."}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={lire} title="Actualiser" className="rounded-lg p-1.5 text-slate-600 hover:bg-slate-200" disabled={chargement}>
              {chargement ? <Loader2 className="h-5 w-5 animate-spin" /> : <RefreshCw className="h-5 w-5" />}
            </button>
            <button type="button" onClick={onClose} title="Fermer" className="rounded-lg p-1.5 text-slate-600 hover:bg-slate-200"><X className="h-5 w-5" /></button>
          </div>
        </div>

        {erreur && <p className="rounded-lg bg-rose-50 p-3 text-sm text-rose-800">{erreur}</p>}
        {/* Jauge circulaire d'attente (première lecture) */}
        {!donnees && !erreur && (
          <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500"><Loader2 className="h-6 w-6 animate-spin" /> Patientez…</div>
        )}

        {donnees && (
          <>
            {/* ---- Identité et fiche du parc ---- */}
            <div className="grid gap-3 md:grid-cols-2">
              <Bloc titre="Identité">
                <Ligne libelle="Machine" valeur={donnees.machine} />
                <Ligne libelle="Site(s)" valeur={sites.join(", ")} />
                <Ligne libelle="Utilisateur(s) Windows" valeur={utilisateurs.join(", ")} />
                <Ligne libelle="Type" valeur={{ serveur: "Serveur", portable: "PC portable", poste: "PC de bureau" }[inv?.type_poste] || ""} />
                <Ligne libelle="Adresse IP publique" valeur={donnees.adresse_ip_publique} />
              </Bloc>
              <Bloc titre="Parc informatique">
                {equipement ? (
                  <div className="space-y-1 text-sm">
                    <p>
                      Fiche <strong className="font-mono">{equipement.numero_inventaire}</strong> ({equipement.categorie})
                      {equipement.a_affecter
                        ? <span className="ml-1 rounded bg-amber-100 px-1.5 text-[11px] font-semibold text-amber-800">client à affecter</span>
                        : <> — {equipement.client_nom}</>}
                    </p>
                    <Link to={`/admin/parc?equipement=${encodeURIComponent(equipement.id)}`} className="text-sky-700 underline" data-testid="details-poste-parc">
                      Ouvrir la fiche de l'équipement
                    </Link>
                    <p className="text-[11px] text-slate-500">Créée et complétée automatiquement par Loois ; vos saisies (client, lieu, notes…) ne sont jamais écrasées.</p>
                  </div>
                ) : <p className="text-sm text-slate-500">Pas encore de fiche : elle est créée au premier inventaire reçu.</p>}
              </Bloc>
            </div>

            {/* ---- Composants vus sur la machine ---- */}
            <Bloc titre={`Composants (${composants.length})`}>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
                    <tr><th className="px-2 py-1.5">Composant</th><th className="px-2 py-1.5">Version</th><th className="px-2 py-1.5">Utilisateur</th>
                      <th className="px-2 py-1.5">Site</th><th className="px-2 py-1.5">Lancé le</th><th className="px-2 py-1.5">Dernier signal</th></tr>
                  </thead>
                  <tbody>
                    {composants.map((c) => {
                      const cle = `c:${c.application}:${c.composant}`;
                      return (
                        <tr key={cle} className={selection === cle ? "ligne-selectionnee" : ""} onClick={() => setSelection(cle)}>
                          <td className="px-2 py-1.5 font-medium">
                            <span className={`mr-2 inline-block h-2.5 w-2.5 rounded-full ${c.en_ligne ? "bg-emerald-500" : "bg-slate-300"}`} />
                            {c.composant}{c.composant !== c.application && <span className="text-xs text-slate-500"> ({c.application})</span>}
                          </td>
                          <td className="px-2 py-1.5">{c.version}</td>
                          <td className="px-2 py-1.5">{c.utilisateur || "—"}</td>
                          <td className="px-2 py-1.5">{c.site || "—"}</td>
                          <td className="px-2 py-1.5">{dateCourte(c.demarre_le) || "—"}</td>
                          <td className="px-2 py-1.5 text-slate-500">{depuis(c.vu_le)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Bloc>

            {inv && (
              <>
                {/* ---- Système, processeur et mémoire ---- */}
                <div className="grid gap-3 md:grid-cols-2">
                  <Bloc titre="Système">
                    <Ligne libelle="Windows" valeur={[systeme.nom, systeme.version].filter(Boolean).join(" ")} />
                    <Ligne libelle="Architecture" valeur={systeme.architecture} />
                    <Ligne libelle="Fabricant / modèle" valeur={[systeme.fabricant, systeme.modele].filter(Boolean).join(" · ")} />
                    <Ligne libelle="N° de série" valeur={systeme.numero_serie} />   {/* lot 80 : lu dans le BIOS */}
                    <Ligne libelle="Allumé depuis" valeur={duree(systeme.demarre_depuis_min)} />
                    <Ligne libelle={systeme.domaine ? "Domaine" : "Groupe de travail"} valeur={systeme.domaine || systeme.groupe_travail} />
                    <Ligne libelle="Dossier de Loois" valeur={systeme.dossier_loois} />
                    <Ligne libelle=".NET" valeur={systeme.dotnet} />
                  </Bloc>
                  <Bloc titre="Processeur et mémoire">
                    <Ligne libelle="Processeur" valeur={inv.processeur?.nom} />
                    <Ligne libelle="Cœurs logiques" valeur={nombre(inv.processeur?.coeurs_logiques)} />
                    <div className="mt-2 space-y-1">
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-500">Mémoire vive</span>
                        <span className="font-medium">
                          {memoire.totale_go != null && memoire.disponible_go != null
                            ? `${nombre(Math.round((memoire.totale_go - memoire.disponible_go) * 10) / 10)} Go utilisés sur ${nombre(memoire.totale_go)} Go`
                            : `${nombre(memoire.totale_go, " Go")}`}
                          {memoire.utilisee_pct != null && ` (${memoire.utilisee_pct} %)`}
                        </span>
                      </div>
                      {/* Jauge : orange au-delà de 80 %, rouge au-delà de 90 % */}
                      {memoire.utilisee_pct != null && (
                        <Barre pct={memoire.utilisee_pct}
                          couleur={memoire.utilisee_pct >= 90 ? "bg-rose-500" : memoire.utilisee_pct >= 80 ? "bg-amber-500" : "bg-sky-500"} />
                      )}
                    </div>
                  </Bloc>
                </div>

                {/* ---- Disques : espace libre (rouge sous 10 %) ---- */}
                <Bloc titre={`Disques (${(inv.disques || []).length})`}>
                  <div className="grid gap-3 sm:grid-cols-2">
                    {(inv.disques || []).map((d) => {
                      const critique = d.libre_pct != null && d.libre_pct < 10;
                      return (
                        <div key={d.lettre} className="space-y-1">
                          <div className="flex justify-between text-sm">
                            <span className="font-medium">{d.lettre} {d.libelle && <span className="text-slate-500">« {d.libelle} »</span>} <span className="text-xs text-slate-400">{d.format}</span></span>
                            <span className={critique ? "font-semibold text-rose-700" : "text-slate-600"}>
                              {nombre(d.libre_go)} Go libres sur {nombre(d.total_go)} Go{d.libre_pct != null && ` (${d.libre_pct} %)`}
                            </span>
                          </div>
                          {/* Barre = espace OCCUPÉ ; rouge si moins de 10 % libres */}
                          <Barre pct={d.libre_pct != null ? 100 - d.libre_pct : 0} couleur={critique ? "bg-rose-500" : "bg-emerald-500"} />
                        </div>
                      );
                    })}
                    {(inv.disques || []).length === 0 && <p className="text-sm text-slate-500">Aucun disque mesuré.</p>}
                  </div>
                </Bloc>

                {/* ---- Réseau : cartes actives ---- */}
                <Bloc titre={`Réseau (${(inv.reseau || []).length} carte(s) active(s))`}>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
                        <tr><th className="px-2 py-1.5">Carte</th><th className="px-2 py-1.5">Adresse MAC</th><th className="px-2 py-1.5">IPv4</th>
                          <th className="px-2 py-1.5">IPv6</th><th className="px-2 py-1.5">Passerelle</th><th className="px-2 py-1.5">DNS</th><th className="px-2 py-1.5">Débit</th></tr>
                      </thead>
                      <tbody>
                        {(inv.reseau || []).map((c, i) => {
                          const cle = `r:${i}`;
                          return (
                            <tr key={cle} className={selection === cle ? "ligne-selectionnee" : ""} onClick={() => setSelection(cle)}>
                              <td className="px-2 py-1.5"><span className="font-medium">{c.nom}</span><span className="block text-[11px] text-slate-500">{c.type}{c.description ? ` · ${c.description}` : ""}</span></td>
                              <td className="px-2 py-1.5 font-mono text-xs">{c.mac || "—"}</td>
                              <td className="px-2 py-1.5 font-mono text-xs">{(c.ipv4 || []).join(", ") || "—"}</td>
                              <td className="px-2 py-1.5 font-mono text-[11px]">{(c.ipv6 || []).join(", ") || "—"}</td>
                              <td className="px-2 py-1.5 font-mono text-xs">{(c.passerelles || []).join(", ") || "—"}</td>
                              <td className="px-2 py-1.5 font-mono text-xs">{(c.dns || []).join(", ") || "—"}</td>
                              <td className="px-2 py-1.5 text-xs">{c.vitesse_mbps ? `${nombre(c.vitesse_mbps)} Mb/s` : "—"}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </Bloc>

                {/* ---- Lot 80 : logiciels installés (nom, version, éditeur), filtrés par la même recherche ---- */}
                {(inv.logiciels || []).length > 0 && (
                  <Bloc titre={`Logiciels installés (${(inv.logiciels || []).length})`}>
                    <div className="max-h-72 overflow-auto">
                      <table className="w-full text-sm">
                        <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
                          <tr><th className="px-2 py-1.5">Logiciel</th><th className="px-2 py-1.5">Version</th><th className="px-2 py-1.5">Éditeur</th></tr>
                        </thead>
                        <tbody>
                          {(inv.logiciels || [])
                            .filter((l) => !recherche || `${l.nom} ${l.editeur || ""}`.toLowerCase().includes(recherche.toLowerCase()))
                            .map((l, i) => {
                              const cle = `l:${i}`;
                              return (
                                <tr key={cle} className={selection === cle ? "ligne-selectionnee" : ""} onClick={() => setSelection(cle)}>
                                  <td className="px-2 py-1.5">{l.nom}</td>
                                  <td className="px-2 py-1.5 font-mono text-xs">{l.version || "—"}</td>
                                  <td className="px-2 py-1.5 text-xs text-slate-600">{l.editeur || "—"}</td>
                                </tr>
                              );
                            })}
                        </tbody>
                      </table>
                    </div>
                  </Bloc>
                )}

                {/* ---- Tâches en cours : recherche + tri ---- */}
                <Bloc titre={`Tâches en cours (${(inv.processus || []).length} affichées sur ${nombre(inv.processus_total)}, les plus gourmandes en mémoire)`}>
                  <input className="mb-2 w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm sm:w-72" placeholder="Rechercher une tâche (nom ou PID)…"
                    value={recherche} onChange={(e) => setRecherche(e.target.value)} data-testid="details-poste-recherche" />
                  <div className="max-h-96 overflow-auto">
                    <table className="w-full text-sm">
                      <thead className="sticky top-0 bg-white text-left text-xs uppercase tracking-wide text-slate-500">
                        <tr>
                          <th className="cursor-pointer px-2 py-1.5" onClick={() => trier("nom")}>Nom{fleche("nom")}</th>
                          <th className="cursor-pointer px-2 py-1.5 text-right" onClick={() => trier("pid")}>PID{fleche("pid")}</th>
                          <th className="cursor-pointer px-2 py-1.5 text-right" onClick={() => trier("memoire_mo")}>Mémoire (Mo){fleche("memoire_mo")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {taches.map((p) => {
                          const cle = `p:${p.pid}`;
                          return (
                            <tr key={cle} className={selection === cle ? "ligne-selectionnee" : ""} onClick={() => setSelection(cle)}>
                              <td className="px-2 py-1">{p.nom}</td>
                              <td className="px-2 py-1 text-right font-mono text-xs">{p.pid}</td>
                              <td className="px-2 py-1 text-right">{nombre(p.memoire_mo)}</td>
                            </tr>
                          );
                        })}
                        {taches.length === 0 && <tr><td colSpan={3} className="px-2 py-3 text-center text-slate-400">Aucune tâche.</td></tr>}
                      </tbody>
                    </table>
                  </div>
                </Bloc>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
