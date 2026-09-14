// Réglages sidebar portail : thème clair/sombre (tous les utilisateurs
// connectés) + "Notes VIDAL (admin)" (admin/superviseur uniquement — affiche
// les avertissements techniques sur les champs/endpoints VIDAL non confirmés,
// ex. posology-descriptors jamais testé en réel). Portage du même mécanisme
// que `site-meetafrican/frontend/src/secure/SecureSettingsContext.jsx`,
// adapté au vrai portail (thème appliqué via la classe `dark` sur <html>,
// consommée par les tokens shadcn/ui déjà définis dans index.css).
import { createContext, useContext, useEffect, useState } from "react";

const VidalUiSettingsContext = createContext(null);

function readStored(key, fallback) {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

export function VidalUiSettingsProvider({ children }) {
  const [theme, setTheme] = useState(() => readStored("sawali-portal-theme", "light"));
  const [vidalAdminNotes, setVidalAdminNotes] = useState(
    () => readStored("sawali-vidal-admin-notes", "off") === "on"
  );

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    try {
      localStorage.setItem("sawali-portal-theme", theme);
    } catch {
      /* stockage indisponible (navigation privée…) : le réglage reste actif pour la session */
    }
  }, [theme]);

  useEffect(() => {
    try {
      localStorage.setItem("sawali-vidal-admin-notes", vidalAdminNotes ? "on" : "off");
    } catch {
      /* idem */
    }
  }, [vidalAdminNotes]);

  return (
    <VidalUiSettingsContext.Provider value={{ theme, setTheme, vidalAdminNotes, setVidalAdminNotes }}>
      {children}
    </VidalUiSettingsContext.Provider>
  );
}

export function useVidalUiSettings() {
  const ctx = useContext(VidalUiSettingsContext);
  // Défauts sûrs si un composant est monté hors du provider (ne devrait pas
  // arriver — PortalLayout enveloppe tout le portail) plutôt que de planter.
  if (!ctx) return { theme: "light", setTheme: () => {}, vidalAdminNotes: false, setVidalAdminNotes: () => {} };
  return ctx;
}
