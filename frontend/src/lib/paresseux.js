// ============================================================================
// Lot 461 — chargement À LA DEMANDE des pages (React.lazy) : le site ne télécharge et ne « lit » plus
// les 8,7 Mo de toutes les pages au démarrage ; chaque page est un petit fichier chargé quand on l'ouvre.
// `paresseux(() => import("@/pages/..."))` remplace `import Page from "@/pages/..."` dans App.js.
//
// Reprise automatique : après un nouveau déploiement, les anciens fichiers n'existent plus sur le serveur. Un onglet resté
// ouvert qui demande une page échoue alors ; on recharge le site UNE fois (le drapeau évite toute boucle), puis il repart normalement.
// ============================================================================
import { lazy } from "react";

const CLE_RECHARGEMENT = "sawali_rechargement_fichier_page";

export function paresseux(importer, nomExport) {
  return lazy(() =>
    importer()
      .then((module) => {
        try { sessionStorage.removeItem(CLE_RECHARGEMENT); } catch { /* stockage indisponible : sans importance */ }
        // Export nommé (ex. { CheckoutSuccess }) : React.lazy attend un export « default »
        return nomExport ? { default: module[nomExport] } : module;
      })
      .catch((erreur) => {
        try {
          if (!sessionStorage.getItem(CLE_RECHARGEMENT)) {
            sessionStorage.setItem(CLE_RECHARGEMENT, "1");
            window.location.reload();
            return new Promise(() => {});            // la page se recharge : on n'affiche rien entre-temps
          }
        } catch { /* stockage indisponible : on laisse l'erreur remonter */ }
        throw erreur;
      })
  );
}
