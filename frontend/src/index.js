import React from "react";
import ReactDOM from "react-dom/client";
import "@/index.css";
import App from "@/App";
// Lot 130 (règle 9) — Ctrl + Espace / double-clic : reprendre le texte par défaut d'un champ pour le modifier
import { installerValeurParDefaut } from "@/lib/valeurParDefaut";

installerValeurParDefaut();

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

// Lot 243 (application Android d'administration) — service worker : page « Pas de connexion » quand Internet manque.
// Enregistré DÈS le démarrage (et non après « load ») pour que PWABuilder le voie actif. Il ne met rien d'autre en cache.
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

// Garde l'invitation d'installation de Chrome : la rubrique des Paramètres « Application Android d'administration »
// l'utilise pour son bouton « Installer l'application d'administration », même si l'invitation est arrivée avant son ouverture.
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  window.__sawaliInvite = e;
  window.dispatchEvent(new Event("sawali:invite-installation"));
});
window.addEventListener("appinstalled", () => {
  window.__sawaliInvite = null;
  window.dispatchEvent(new Event("sawali:invite-installation"));
});
