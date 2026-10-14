// =====================================================================
// Lot 135 — PLUSIEURS POSTES À LA FOIS, EN ONGLETS (item 4).
//
// Pour un développeur WinDev : c'est une « fenêtre MDI » du navigateur. Chaque onglet garde sa propre prise en main
// (connexion, image, vidéo) même quand il n'est pas affiché ; on passe d'un poste à l'autre sans rien couper.
//   - ouvrirPriseEnMain({ id, nom }) : ouvre (ou ramène au premier plan) l'onglet d'un poste, depuis n'importe quel
//     écran de SAWALI (rubrique des Paramètres, chat du support, fiche « service Windows »…) ;
//   - « + » : ajoute un poste choisi dans la liste des postes Loois munis d'une clé client ;
//   - « Réduire » : cache les onglets sans couper les sessions (une pastille en bas à droite les rappelle).
// Le composant se monte tout seul la première fois (racine React à part) : rien à ajouter dans App.js.
// =====================================================================
import React, { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";
import { apiClient } from "@/lib/api";
import { Plus, Minus, X, Monitor, ServerCog, MonitorSmartphone, Search } from "lucide-react";
import ControleDistance from "@/components/ControleDistance";

// ---------------------------------------------------------------------
// Petit « magasin » partagé : liste des onglets, onglet actif, réduit ou non
// ---------------------------------------------------------------------
let etatOnglets = { onglets: [], actif: null, reduit: false };
const abonnes = new Set();
const publier = (maj) => { etatOnglets = { ...etatOnglets, ...maj }; abonnes.forEach((f) => f()); };
const sAbonner = (f) => { abonnes.add(f); return () => abonnes.delete(f); };
const lire = () => etatOnglets;

let racine = null;
function assurerMontage() {
  if (racine || typeof document === "undefined") return;
  const conteneur = document.createElement("div");
  conteneur.id = "sawali-controle-distance-onglets";
  document.body.appendChild(conteneur);
  racine = createRoot(conteneur);
  racine.render(<ControleDistanceOnglets />);
}

/** Ouvre la prise en main d'un poste dans un onglet (ou ramène son onglet au premier plan). */
export function ouvrirPriseEnMain(poste) {
  if (!poste?.id) return;
  assurerMontage();
  const deja = etatOnglets.onglets.find((o) => o.posteId === poste.id);
  if (deja) { publier({ actif: deja.cle, reduit: false }); return; }
  const cle = `${poste.id}-${Date.now()}`;
  publier({
    onglets: [...etatOnglets.onglets, { cle, posteId: poste.id, nom: poste.nom || "Poste Loois", service: Boolean(poste.agent_service), etat: "choix" }],
    actif: cle, reduit: false,
  });
}

/**
 * Lot 143 — DÉCONNEXION : toutes les prises en main sont arrêtées et fermées (onglets, pastille « réduit »). Le démontage des
 * visionneuses envoie « arreter » au poste (la session se termine, l'intervention est clôturée) et ferme leur connexion.
 */
function fermerTout() {
  if (etatOnglets.onglets.length === 0 && !etatOnglets.reduit) return;
  publier({ onglets: [], actif: null, reduit: false });
}
if (typeof window !== "undefined") window.addEventListener("sawali:deconnexion", fermerTout);

function fermerOnglet(cle) {
  const onglets = etatOnglets.onglets.filter((o) => o.cle !== cle);
  const actif = etatOnglets.actif === cle ? (onglets[onglets.length - 1]?.cle ?? null) : etatOnglets.actif;
  publier({ onglets, actif });
}

// Pastille de couleur de l'onglet selon l'état de la prise en main
const COULEUR_ETAT = {
  active: "bg-emerald-400", demande: "bg-amber-400 animate-pulse", connexion: "bg-amber-400 animate-pulse",
  attente_poste: "bg-amber-400 animate-pulse", choix: "bg-slate-400",
};

// ---------------------------------------------------------------------
// Choix d'un poste à ajouter (« + »)
// ---------------------------------------------------------------------
function ChoixPoste({ onChoisir, onFermer }) {
  const [postes, setPostes] = useState([]);
  const [filtre, setFiltre] = useState("");
  useEffect(() => {
    apiClient.get("/controle-distance/postes").then((r) => setPostes(r.data.postes || [])).catch(() => setPostes([]));
  }, []);
  const visibles = postes.filter((p) => !filtre || `${p.nom} ${p.cle_client_libelle || ""}`.toLowerCase().includes(filtre.toLowerCase()));
  return (
    <div className="absolute right-2 top-11 z-30 w-96 rounded-2xl bg-slate-900 p-3 shadow-2xl ring-1 ring-white/15">
      <div className="mb-2 flex items-center gap-2 rounded-lg bg-white/10 px-2">
        <Search className="h-4 w-4 text-slate-400" />
        <input autoFocus value={filtre} onChange={(e) => setFiltre(e.target.value)} placeholder="Rechercher un poste…"
               className="w-full bg-transparent py-1.5 text-sm text-slate-100 outline-none placeholder:text-slate-400" />
        <button type="button" onClick={onFermer} className="text-slate-400 hover:text-white"><X className="h-4 w-4" /></button>
      </div>
      <div className="max-h-80 overflow-auto">
        {visibles.map((p) => {
          const signal = p.signal_controle_distance || p.dernier_contact;
          const enLigne = signal && Date.now() - new Date(signal).getTime() < 2 * 60 * 1000;
          return (
            <button key={p.id} type="button" onClick={() => onChoisir(p)}
                    className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs text-slate-100 hover:bg-white/10">
              <span className={`h-2 w-2 shrink-0 rounded-full ${enLigne ? "bg-emerald-400" : "bg-slate-500"}`} />
              {p.agent_service ? <ServerCog className="h-3.5 w-3.5 shrink-0 text-sky-300" /> : <Monitor className="h-3.5 w-3.5 shrink-0 text-slate-300" />}
              <span className="min-w-0 flex-1 truncate">{p.nom}</span>
              <span className="shrink-0 text-[10px] text-slate-400">{p.cle_client_libelle || p.cle_client_code}</span>
            </button>
          );
        })}
        {visibles.length === 0 && <p className="p-2 text-xs text-slate-400">Aucun poste.</p>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------
// Les onglets
// ---------------------------------------------------------------------
export default function ControleDistanceOnglets() {
  const { onglets, actif, reduit } = useSyncExternalStore(sAbonner, lire);
  const [choixOuvert, setChoixOuvert] = useState(false);
  const suivreEtat = useCallback((cle) => (etat) => {
    const o = etatOnglets.onglets.find((x) => x.cle === cle);
    if (o && o.etat !== etat) publier({ onglets: etatOnglets.onglets.map((x) => (x.cle === cle ? { ...x, etat } : x)) });
  }, []);

  if (onglets.length === 0) return null;
  const enCours = onglets.filter((o) => o.etat === "active").length;

  return (
    <>
      {/* Pastille quand les onglets sont réduits : les sessions continuent */}
      {reduit && (
        <button type="button" onClick={() => publier({ reduit: false })}
                className="fixed bottom-4 right-4 z-[95] inline-flex items-center gap-2 rounded-full bg-sky-600 px-4 py-2 text-sm font-semibold text-white shadow-2xl hover:bg-sky-500"
                title="Revenir aux prises en main">
          <MonitorSmartphone className="h-4 w-4" />
          {onglets.length} prise{onglets.length > 1 ? "s" : ""} en main{enCours ? ` · ${enCours} en cours` : ""}
        </button>
      )}
      <div className={`fixed inset-0 z-[90] flex flex-col bg-slate-950 ${reduit ? "invisible pointer-events-none" : ""}`} data-testid="controle-distance-onglets">
        {/* Barre des onglets */}
        <div className="relative flex items-center gap-1 border-b border-white/10 bg-slate-900 px-2 pt-1.5">
          <div className="flex min-w-0 flex-1 gap-1 overflow-x-auto">
            {onglets.map((o) => (
              <div key={o.cle}
                   className={`group flex max-w-[16rem] shrink-0 items-center gap-1.5 rounded-t-lg px-3 py-1.5 text-xs ${o.cle === actif ? "bg-slate-800 text-white" : "bg-slate-900 text-slate-400 hover:bg-slate-800/60"}`}>
                <button type="button" onClick={() => publier({ actif: o.cle })} className="flex min-w-0 items-center gap-1.5">
                  <span className={`h-2 w-2 shrink-0 rounded-full ${COULEUR_ETAT[o.etat] || "bg-slate-500"}`} title={o.etat} />
                  {o.service ? <ServerCog className="h-3.5 w-3.5 shrink-0" /> : <Monitor className="h-3.5 w-3.5 shrink-0" />}
                  <span className="truncate" title={o.nom}>{o.nom}</span>
                </button>
                <button type="button" onClick={() => fermerOnglet(o.cle)} title="Arrêter et fermer cet onglet"
                        className="rounded p-0.5 text-slate-500 hover:bg-rose-600 hover:text-white">
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
          <button type="button" onClick={() => setChoixOuvert((v) => !v)} title="Prendre la main sur un autre poste"
                  className="grid h-7 w-7 place-items-center rounded-full bg-sky-600 text-white hover:bg-sky-500"><Plus className="h-4 w-4" /></button>
          <button type="button" onClick={() => publier({ reduit: true })} title="Réduire (les prises en main continuent)"
                  className="grid h-7 w-7 place-items-center rounded-full bg-slate-700 text-white hover:bg-slate-600"><Minus className="h-4 w-4" /></button>
          {choixOuvert && (
            <ChoixPoste onFermer={() => setChoixOuvert(false)}
                        onChoisir={(p) => { setChoixOuvert(false); ouvrirPriseEnMain(p); }} />
          )}
        </div>
        {/* Contenu : toutes les visionneuses restent montées (sessions conservées), seule l'active est visible */}
        <div className="relative min-h-0 flex-1">
          {onglets.map((o) => (
            <ControleDistance key={o.cle} embedded visible={o.cle === actif && !reduit} posteId={o.posteId} posteNom={o.nom}
                              onEtat={suivreEtat(o.cle)} onClose={() => fermerOnglet(o.cle)} onOuvrirPoste={ouvrirPriseEnMain} />
          ))}
        </div>
      </div>
    </>
  );
}
