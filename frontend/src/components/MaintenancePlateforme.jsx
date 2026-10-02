import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import { apiClient, noterMotifDeconnexion, sessionImpActive } from "@/lib/api";
import { formatDecompte, heureLocale, signalerChangementMaintenance, useEtatMaintenance } from "@/lib/maintenancePlateforme";

// ---------------------------------------------------------------------------
// Lot 50 — Surveillance de la maintenance de la plateforme (règle R8), montée une
// seule fois dans App.js pour TOUT utilisateur connecté (rien pour les visiteurs).
//
// Utilisateurs (clients, utilisateurs suivis, superviseurs, démo) :
//   - annonce      : fenêtre (message + décompte) qu'on peut fermer ; fermée, un
//                    bandeau rouge reste affiché avec le décompte ;
//   - verrouillage : écran entièrement verrouillé (ni Échap, ni clic dehors, ni
//                    tabulation vers la page), message + décompte mm:ss ;
//   - échéance     : déconnexion forcée et retour à la page de connexion.
// Admins (jamais déconnectés) et onglets « Voir en tant que » : bandeau de suivi ;
// le super-admin y a « Annuler » avant l'échéance, puis « Réactiver les connexions ».
// ---------------------------------------------------------------------------
export default function SurveillanceMaintenance() {
  const { user } = useAuth() || {};
  const suivi = useEtatMaintenance(!!user);
  if (!user || !suivi.etat || suivi.phase === "aucune") return null;
  if (user.role === "admin" || sessionImpActive()) return <BandeauAdmin {...suivi} />;
  return <AlerteUtilisateur {...suivi} />;
}

// ---------------------------------------------------------------------------
// Utilisateurs : fenêtre, bandeau, verrouillage puis déconnexion forcée
// ---------------------------------------------------------------------------
function AlerteUtilisateur({ etat, phase, secondes }) {
  const { logout } = useAuth() || {};
  // Fenêtre fermée pour CETTE annonce (une nouvelle annonce la rouvre)
  const [fermeePour, setFermeePour] = useState(null);
  const deconnecte = useRef(false);

  const echeanceAtteinte = phase === "maintenance" || secondes <= 0;
  useEffect(() => {
    if (!echeanceAtteinte || deconnecte.current) return;
    deconnecte.current = true;
    noterMotifDeconnexion("Plateforme en maintenance : vous avez été déconnecté(e). Vous pourrez vous reconnecter dès que l'administrateur aura rétabli l'accès.");
    try { logout && logout(); } catch { /* noop */ }
    // Navigation complète : toutes les fenêtres ouvertes sont démontées
    window.location.assign("/login");
  }, [echeanceAtteinte, logout]);

  if (phase === "verrouillage" || echeanceAtteinte) {
    return <EcranVerrouille etat={etat} secondes={secondes} deconnexionEnCours={echeanceAtteinte} />;
  }
  if (fermeePour !== etat.annonce_le) {
    return (
      <div className="fixed inset-0 z-[10040] flex items-center justify-center bg-black/50 p-4 print:hidden"
        onClick={() => setFermeePour(etat.annonce_le)} data-testid="maintenance-annonce">
        <div role="alertdialog" aria-modal="true" aria-labelledby="maintenance-titre"
          className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
          <div className="mb-3 flex items-start justify-between gap-4">
            <h2 id="maintenance-titre" className="text-lg font-bold text-red-700">⚠️ Déconnexion programmée</h2>
            <button type="button" onClick={() => setFermeePour(etat.annonce_le)} aria-label="Fermer"
              className="rounded-full p-1 text-slate-500 hover:bg-slate-100">✕</button>
          </div>
          <p className="whitespace-pre-line text-slate-800">{etat.message}</p>
          <Decompte secondes={secondes} />
          <p className="text-sm text-slate-600">
            Enregistrez votre travail en cours. L'écran sera verrouillé à {heureLocale(etat.debut_verrouillage)},
            puis vous serez déconnecté(e) à {heureLocale(etat.echeance)}. Vous pourrez vous reconnecter quand
            l'administrateur aura rétabli l'accès.
          </p>
          <button type="button" className="mt-4 w-full rounded-lg bg-sky-700 px-4 py-2 font-semibold text-white hover:bg-sky-800"
            onClick={() => setFermeePour(etat.annonce_le)}>
            J'ai compris
          </button>
        </div>
      </div>
    );
  }
  // Fenêtre fermée : bandeau rouge persistant
  return (
    <div role="status" className="fixed inset-x-0 bottom-0 z-[10030] bg-red-600 px-4 py-2 text-sm text-white shadow-lg print:hidden"
      data-testid="maintenance-bandeau">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-center gap-x-3 gap-y-1 text-center">
        <span className="font-semibold">⚠️ Déconnexion de tous les utilisateurs dans <span className="font-mono">{formatDecompte(secondes)}</span></span>
        <span className="truncate opacity-90">{etat.message}</span>
        <button type="button" className="underline" onClick={() => setFermeePour(null)}>Revoir le message</button>
      </div>
    </div>
  );
}

function Decompte({ secondes, clair = false }) {
  return (
    <div className={`my-4 rounded-xl p-3 text-center ${clair ? "bg-white/10" : "bg-red-50"}`}>
      <p className={`text-xs font-semibold uppercase tracking-wider ${clair ? "text-red-200" : "text-red-700"}`}>Déconnexion forcée dans</p>
      <p className={`font-mono text-4xl font-extrabold tabular-nums ${clair ? "text-white" : "text-red-700"}`} aria-live="off"
        data-testid="maintenance-decompte">
        {formatDecompte(secondes)}
      </p>
    </div>
  );
}

/** Écran verrouillé, impossible à fermer : la page en dessous est rendue inerte. */
function EcranVerrouille({ etat, secondes, deconnexionEnCours }) {
  useEffect(() => {
    const racine = document.getElementById("root");
    racine?.setAttribute("inert", "");
    const debordement = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    // Échap n'a aucun effet (ni sur cet écran, ni sur une fenêtre ouverte dessous)
    const bloquer = (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); } };
    window.addEventListener("keydown", bloquer, true);
    return () => {
      racine?.removeAttribute("inert");
      document.body.style.overflow = debordement;
      window.removeEventListener("keydown", bloquer, true);
    };
  }, []);

  return createPortal(
    <div role="alertdialog" aria-modal="true" aria-labelledby="verrou-titre" data-testid="maintenance-verrou"
      className="fixed inset-0 z-[10050] flex items-center justify-center bg-slate-950/95 p-4 text-white backdrop-blur-sm print:hidden">
      <div className="w-full max-w-lg text-center">
        <p className="text-5xl" aria-hidden="true">🔒</p>
        <h2 id="verrou-titre" className="mt-3 text-2xl font-extrabold">Plateforme en cours de maintenance</h2>
        <p className="mt-4 whitespace-pre-line text-lg text-slate-100">{etat.message}</p>
        {deconnexionEnCours ? (
          <p className="mt-6 text-lg font-semibold text-red-200">Déconnexion en cours…</p>
        ) : (
          <Decompte secondes={secondes} clair />
        )}
        <p className="text-sm text-slate-300">
          Votre session sera fermée à {heureLocale(etat.echeance)}. Vous pourrez vous reconnecter dès que
          l'administrateur aura rétabli l'accès à la plateforme.
        </p>
      </div>
    </div>,
    document.body,
  );
}

// ---------------------------------------------------------------------------
// Admins : suivi ; le super-admin peut annuler puis réactiver
// ---------------------------------------------------------------------------
function BandeauAdmin({ etat, phase, secondes }) {
  const [envoi, setEnvoi] = useState(false);
  // Actions réservées au super-admin : un autre Admin voit le bandeau sans les boutons
  const [peutAgir, setPeutAgir] = useState(false);
  useEffect(() => {
    if (sessionImpActive()) return undefined;
    let arret = false;
    apiClient.get("/admin/deconnexion-generale", { headers: { "X-Requete-Fond": "1" } })
      .then(() => { if (!arret) setPeutAgir(true); })
      .catch(() => { if (!arret) setPeutAgir(false); });
    return () => { arret = true; };
  }, []);

  async function agir(action, succes) {
    setEnvoi(true);
    try {
      await apiClient.post(`/admin/deconnexion-generale/${action}`);
      toast.success(succes);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Action impossible");
    } finally {
      signalerChangementMaintenance();
      setEnvoi(false);
    }
  }

  const enMaintenance = phase === "maintenance";
  return (
    <div role="status" data-testid="maintenance-bandeau-admin"
      className={`fixed inset-x-0 bottom-0 z-[10030] px-4 py-2 text-sm text-white shadow-lg print:hidden ${enMaintenance ? "bg-red-700" : "bg-amber-600"}`}>
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-center gap-x-4 gap-y-2 text-center">
        {enMaintenance ? (
          <span className="font-semibold">🔒 Maintenance en cours — connexions bloquées pour tous les utilisateurs (sauf administrateurs)</span>
        ) : (
          <span className="font-semibold">
            ⏳ Déconnexion générale programmée : {phase === "verrouillage" ? "écrans verrouillés, " : ""}
            déconnexion forcée dans <span className="font-mono">{formatDecompte(secondes)}</span> ({heureLocale(etat.echeance)})
          </span>
        )}
        {peutAgir && <Link to="/admin/settings#s-deconnexion-generale" className="underline">Détails</Link>}
        {peutAgir && (enMaintenance ? (
          <button type="button" disabled={envoi} className="rounded-md bg-white px-3 py-1 text-xs font-semibold text-red-700 hover:bg-red-50"
            onClick={() => agir("reactiver", "Connexions réactivées : chacun peut se reconnecter.")}>
            {envoi ? "…" : "Réactiver les connexions"}
          </button>
        ) : (
          <button type="button" disabled={envoi} className="rounded-md border border-white/60 px-3 py-1 text-xs font-semibold text-white hover:bg-white/10"
            onClick={() => window.confirm("Annuler la déconnexion programmée ? Personne ne sera déconnecté.")
              && agir("annuler", "Déconnexion annulée.")}>
            {envoi ? "…" : "Annuler la déconnexion"}
          </button>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Avis affiché sur la page de connexion
// ---------------------------------------------------------------------------
export function AvisMaintenance() {
  const { etat, phase, secondes } = useEtatMaintenance(true);
  if (!etat || phase === "aucune") return null;
  if (phase === "maintenance") {
    return (
      <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800" data-testid="avis-maintenance">
        <p className="font-bold">🔒 Plateforme en maintenance</p>
        <p className="mt-1 whitespace-pre-line">{etat.message}</p>
        <p className="mt-1 text-xs">Les connexions sont suspendues jusqu'à ce que l'administrateur rétablisse l'accès. Réessayez plus tard.</p>
      </div>
    );
  }
  return (
    <div role="status" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900" data-testid="avis-maintenance">
      <p className="font-bold">⏳ Maintenance prévue dans <span className="font-mono">{formatDecompte(secondes)}</span></p>
      <p className="mt-1 whitespace-pre-line">{etat.message}</p>
    </div>
  );
}
