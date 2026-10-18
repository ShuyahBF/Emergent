// ApplicationAndroidSection.jsx — Lot 243 : rubrique « 📲 Application Android d'administration » des Paramètres.
//
// Réglages / état : l'administration de SAWALI peut s'installer comme une application (icône sur l'écran d'accueil,
// plein écran) et être empaquetée en APK par PWABuilder (voir ANDROID-ADMIN.md à la racine du dépôt).
// Cette rubrique montre l'état (application installée ou non, service worker actif, manifeste lisible),
// le bouton « Installer l'application d'administration » et, à défaut, les gestes à faire à la main.
import React, { useCallback, useEffect, useState } from "react";

export default function ApplicationAndroidSection() {
  // Invitation d'installation gardée par le navigateur (absente si déjà installée ou si le navigateur ne la propose pas)
  const [invite, setInvite] = useState(() => (typeof window !== "undefined" ? window.__sawaliInvite : null) || null);
  const [message, setMessage] = useState("");
  const [etat, setEtat] = useState({ manifeste: null, serviceWorker: null });
  // Ouverte comme application installée (plein écran) : le navigateur l'indique par ce mode d'affichage
  const installee = typeof window !== "undefined" && (
    (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) || window.navigator.standalone === true
  );

  // L'invitation peut arriver après l'ouverture de la page : on l'écoute
  useEffect(() => {
    const maj = () => setInvite(window.__sawaliInvite || null);
    window.addEventListener("sawali:invite-installation", maj);
    return () => window.removeEventListener("sawali:invite-installation", maj);
  }, []);

  // État : le manifeste est-il lisible et le service worker actif ?
  const verifier = useCallback(async () => {
    let manifeste = false;
    try { const r = await fetch("/manifest.json", { cache: "no-store" }); manifeste = r.ok && !!(await r.json()).name; } catch { manifeste = false; }
    let serviceWorker = false;
    try { serviceWorker = "serviceWorker" in navigator && !!(await navigator.serviceWorker.getRegistration("/")); } catch { serviceWorker = false; }
    setEtat({ manifeste, serviceWorker });
  }, []);
  useEffect(() => { verifier(); }, [verifier]);

  // Bouton : déclenche l'invitation d'installation du navigateur
  const installer = async () => {
    if (!invite) return;
    setMessage("");
    try {
      invite.prompt();
      const choix = await invite.userChoice;
      setMessage(choix && choix.outcome === "accepted" ? "Installation lancée." : "Installation annulée.");
    } catch {
      setMessage("Installation impossible depuis ce bouton : suivez les gestes ci-dessous.");
    }
    window.__sawaliInvite = null;
    setInvite(null);
  };

  // Pastille d'état (vert = prêt, gris = pas encore)
  const Pastille = ({ ok, libelle }) => (
    <li className="flex items-center gap-2">
      <span className={`inline-block h-2.5 w-2.5 rounded-full ${ok ? "bg-emerald-500" : "bg-slate-400"}`} aria-hidden="true" />
      {libelle} : <strong>{ok ? "oui" : "non"}</strong>
    </li>
  );

  return (
    <div className="space-y-3 text-sm text-slate-700" data-testid="application-android-section">
      <p>
        L'espace d'administration peut s'installer comme une application sur le téléphone (icône « SAWALI Admin », plein écran).
        Le fichier APK se fabrique sur pwabuilder.com : mode d'emploi dans <code>ANDROID-ADMIN.md</code> (à la racine du dépôt).
      </p>
      <ul className="space-y-1" data-testid="application-android-etat">
        <Pastille ok={etat.manifeste === true} libelle="Manifeste « SAWALI Admin » lisible" />
        <Pastille ok={etat.serviceWorker === true} libelle="Page « Pas de connexion » prête (service worker actif)" />
        <Pastille ok={installee} libelle="Cet écran est ouvert dans l'application installée" />
      </ul>
      <div className="boutons-distincts flex flex-wrap gap-2">
        <button type="button" onClick={installer} disabled={!invite || installee}
          className="rounded-lg bg-sky-600 px-4 py-2 font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
          data-testid="application-android-installer">
          Installer l'application d'administration
        </button>
        <button type="button" onClick={verifier} className="rounded-lg bg-white px-4 py-2 font-semibold text-slate-700">
          Revérifier
        </button>
      </div>
      {message && <p data-testid="application-android-message">{message}</p>}
      {!invite && !installee && (
        <div className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200" data-testid="application-android-gestes">
          <p className="font-semibold">Le bouton est grisé ? Faites le geste à la main :</p>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            <li>Android (Chrome) : menu ⋮ → <em>Installer l'application</em> (ou <em>Ajouter à l'écran d'accueil</em>).</li>
            <li>iPhone / iPad (Safari) : bouton Partager → <em>Sur l'écran d'accueil</em>.</li>
            <li>Ordinateur (Chrome / Edge) : icône d'installation à droite de la barre d'adresse.</li>
          </ul>
          <p className="mt-1">Ouvrez d'abord <code>/admin</code> sur le site, connectez-vous, puis revenez ici.</p>
        </div>
      )}
      <p className="text-xs text-slate-500">
        Sécurité : l'application ne protège pas l'accès, c'est la connexion administrateur qui le protège.
        Ne partagez pas l'APK en dehors de l'équipe. Aucune donnée d'administration n'est gardée sur le téléphone.
      </p>
    </div>
  );
}
