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
