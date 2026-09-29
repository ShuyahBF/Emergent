/*
  Lot 41 — nouvelles données reçues sur les formulaires et les sondages.
  - lireNouveautes() : {formulaires, sondages, par_formulaire: {id: n}, par_sondage: {id: n}}
    (puces vertes des listes, bulles verte et bleue de la barre latérale) ;
  - marquerVu(type, id) : à l'ouverture des Données / Stats d'un formulaire ou des Résultats
    d'un sondage ; prévient la barre latérale (événement « sawali:fs-vu ») pour relire ses bulles.
  API : /me/formulaires-sondages/* (backend/routes/nouveautes_formulaires.py).
*/
import { apiClient } from "@/lib/api";

const VIDE = { formulaires: 0, sondages: 0, par_formulaire: {}, par_sondage: {} };

export async function lireNouveautes() {
  try {
    const r = await apiClient.get("/me/formulaires-sondages/nouveautes");
    return { ...VIDE, ...(r.data || {}) };
  } catch {
    return VIDE;            // sans effet sur la page si le serveur ne répond pas
  }
}

export async function marquerVu(type, id) {
  if (!id) return;
  try {
    await apiClient.post("/me/formulaires-sondages/vu", { type, id });
    window.dispatchEvent(new Event("sawali:fs-vu"));
  } catch { /* au mieux : la puce restera jusqu'à la prochaine consultation */ }
}

// Puce verte « nouvelles données » à côté du titre d'un formulaire ou d'un sondage
export function titrePuce(n) {
  return `${n} nouvelle(s) donnée(s) reçue(s) depuis votre dernière consultation`;
}
