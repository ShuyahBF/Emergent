// =====================================================================
// Lot 50 — A. Abonnement du client : période de grâce puis coupure.
// Monté une seule fois dans App.js pour tout utilisateur connecté.
//   - pendant la grâce : bandeau rouge « Abonnement expiré — N jour(s) de grâce
//     restant(s) — Renouveler » (accès normal) ;
//   - après la grâce : écran « Abonnement expiré — renouveler » sans aucune donnée
//     métier (la page dessous est rendue inerte ; le serveur refuse de toute façon
//     les données : 402 « abonnement_expire »). L'écran apparaît à l'heure exacte
//     (décompte local + toute réponse 402 du serveur).
// Rien pour le super-admin, ni quand l'interrupteur « Coupure automatique » est
// désactivé (Paramètres). En « Voir en tant que », un simple bandeau d'aperçu.
// Backend : backend/abonnement_acces.py, GET /api/me/abonnement.
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, LogOut, RefreshCw } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { apiClient, EVENEMENT_ABONNEMENT } from "@/lib/api";

const RELECTURE_MS = 5 * 60 * 1000;
const dateFr = (iso) => {
  if (!iso) return "—";
  try {
    const d = /^\d{4}-\d{2}-\d{2}$/.test(iso) ? new Date(`${iso}T00:00:00Z`) : new Date(iso);
    return d.toLocaleDateString("fr-FR", { timeZone: "UTC" });
  } catch { return iso; }
};
const montant = (c) => (c?.montant ? `${Number(c.montant).toLocaleString("fr-FR")} ${c.devise || ""}`.trim() : null);

export default function AbonnementAcces() {
  const { user, logout } = useAuth() || {};
  const [etat, setEtat] = useState(null);
  const [details, setDetails] = useState(false);

  const lire = useCallback(async () => {
    try {
      const r = await apiClient.get("/me/abonnement", { headers: { "X-Requete-Fond": "1" } });
      setEtat((avant) => {
        // Paiement enregistré pendant que l'écran était affiché : la page est rechargée
        if (avant?.bloque && !r.data?.bloque) setTimeout(() => window.location.reload(), 0);
        return r.data;
      });
    } catch { /* garde le dernier état connu */ }
  }, []);

  useEffect(() => {
    if (!user) { setEtat(null); return undefined; }
    lire();
    const t = setInterval(lire, RELECTURE_MS);
    const surRefus = () => lire();
    window.addEventListener(EVENEMENT_ABONNEMENT, surRefus);
    return () => { clearInterval(t); window.removeEventListener(EVENEMENT_ABONNEMENT, surRefus); };
  }, [user, lire]);

  // Fin de la grâce à l'heure exacte : relecture à l'échéance
  useEffect(() => {
    if (!etat?.actif || etat.statut !== "grace" || !etat.secondes_restantes) return undefined;
    const ms = Math.min(etat.secondes_restantes * 1000 + 1500, 2 ** 31 - 1);
    const t = setTimeout(lire, ms);
    return () => clearTimeout(t);
  }, [etat, lire]);

  if (!user || !etat?.actif) return null;
  if (etat.bloque) return <EcranExpire etat={etat} onVerifier={lire} onDeconnexion={() => { logout && logout(); window.location.assign("/login"); }} />;
  if (etat.apercu_admin && etat.statut === "expire") {
    return (
      <div className="fixed inset-x-0 bottom-0 z-[10020] bg-slate-800 px-4 py-1.5 text-center text-xs text-white print:hidden" role="status">
        Aperçu « Voir en tant que » : l'abonnement de ce client est expiré (grâce terminée) — le client voit l'écran « Abonnement expiré ».
      </div>
    );
  }
  if (etat.statut !== "grace") return null;
  const n = etat.jours_restants || 0;
  return (
    <>
      <div role="alert" className="sticky top-0 z-[10020] bg-red-600 px-4 py-2 text-sm text-white shadow print:hidden" data-testid="bandeau-abonnement-grace">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-center gap-x-3 gap-y-1 text-center">
          <AlertTriangle className="h-4 w-4" />
          <span className="font-semibold">Abonnement expiré — {n} jour{n > 1 ? "s" : ""} de grâce restant{n > 1 ? "s" : ""}</span>
          <button type="button" onClick={() => setDetails(true)} className="rounded-md bg-white px-3 py-0.5 text-xs font-bold text-red-700 hover:bg-red-50"
            data-testid="bouton-renouveler">
            Renouveler
          </button>
        </div>
      </div>
      {details && (
        <div className="fixed inset-0 z-[10060] flex items-center justify-center bg-black/50 p-4" onClick={() => setDetails(false)}>
          <div role="dialog" aria-modal="true" className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-lg font-bold text-red-700">Renouveler votre abonnement</h2>
            <InfosAbonnement etat={etat} />
            <p className="mt-3 text-sm text-slate-600">
              Sans règlement, l'accès à votre espace sera suspendu le <b>{new Date(etat.fin_grace).toLocaleString("fr-FR")}</b>.
            </p>
            <button type="button" className="mt-4 w-full rounded-lg bg-slate-800 px-4 py-2 text-sm font-semibold text-white" onClick={() => setDetails(false)}>
              Fermer
            </button>
          </div>
        </div>
      )}
    </>
  );
}

function InfosAbonnement({ etat }) {
  const c = etat.contrat || {};
  return (
    <div className="mt-3 space-y-2 text-sm text-slate-700">
      <ul className="space-y-1 rounded-lg bg-slate-50 p-3">
        {etat.client_nom && <li>Client : <b>{etat.client_nom}</b></li>}
        {c.numero && <li>Contrat : <b>{c.numero}</b></li>}
        {etat.periodicite_libelle && <li>Abonnement {etat.periodicite_libelle}{montant(c) ? <> — <b>{montant(c)}</b></> : null}</li>}
        <li>Échéance non réglée : <b>{dateFr(etat.echeance)}</b></li>
      </ul>
      <p>
        Pour renouveler, réglez votre échéance auprès de SAWALI SMART SYSTEMS (service facturation). L'accès est rétabli
        dès que votre paiement est enregistré.
      </p>
    </div>
  );
}

/** Écran plein, sans aucune donnée métier : la page dessous est rendue inerte. */
function EcranExpire({ etat, onVerifier, onDeconnexion }) {
  useEffect(() => {
    const racine = document.getElementById("root");
    racine?.setAttribute("inert", "");
    const debordement = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      racine?.removeAttribute("inert");
      document.body.style.overflow = debordement;
    };
  }, []);
  return createPortal(
    <div role="alertdialog" aria-modal="true" aria-labelledby="abonnement-titre" data-testid="ecran-abonnement-expire"
      className="fixed inset-0 z-[10045] flex items-center justify-center overflow-y-auto bg-slate-100 p-4 print:hidden">
      <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl ring-1 ring-red-200">
        <div className="flex items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-red-50">
            <AlertTriangle className="h-6 w-6 text-red-600" />
          </div>
          <h2 id="abonnement-titre" className="text-xl font-extrabold text-red-700">Abonnement expiré — renouveler</h2>
        </div>
        <p className="mt-4 text-sm text-slate-800">{etat.message}</p>
        <InfosAbonnement etat={etat} />
        <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" onClick={onDeconnexion}
            className="inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-sm text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50">
            <LogOut className="h-4 w-4" /> Se déconnecter
          </button>
          <button type="button" onClick={onVerifier}
            className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700">
            <RefreshCw className="h-4 w-4" /> J'ai réglé : vérifier
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
