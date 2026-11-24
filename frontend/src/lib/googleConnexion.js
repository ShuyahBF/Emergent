// googleConnexion.js — connexion par compte Google, côté site SAWALI. Déroulé complet : backend/google_auth.py.
// Google remplace le mot de passe, PAS le code de vérification : après Google, le code à 6 chiffres est demandé comme d'habitude.
import { apiClient } from "@/lib/api";

/** Le serveur est-il configuré pour Google ? (le bouton n'est affiché que si oui) */
export const googleDisponible = () => apiClient.get("/auth/google/config").then((r) => !!r.data?.disponible).catch(() => false);

/** Adresse de départ de la connexion (le serveur renvoie ensuite vers Google). */
export const urlConnexionGoogle = () => `${apiClient.defaults.baseURL}/auth/google/demarrer?cible=web`;

/** Messages clairs pour chaque cause d'échec renvoyée par le serveur (?erreur=…). */
export const MESSAGES_GOOGLE = {
  aucun_compte: "Aucun compte SAWALI n'est lié à ce compte Google. Connectez-vous avec votre e-mail, puis liez Google dans « Mon compte ».",
  deja_lie: "Ce compte Google est déjà lié à un autre compte SAWALI.",
  bloque: "Ce compte est bloqué : contactez l'administrateur.",
  refuse: "La connexion par Google a été annulée ou refusée.",
  google: "Google n'a pas pu confirmer votre identité (e-mail vérifié exigé). Réessayez.",
  etat: "Cette demande a expiré. Recommencez la connexion.",
};
