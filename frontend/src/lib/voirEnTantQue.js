// Lot 44 — « Voir en tant que » (super-admin) : ouverture, bascule du mode lecture
// seule et retour au compte de l'Admin. Le stockage des jetons est décrit dans
// lib/api.js (clés CLE_IMP_* du sessionStorage de l'onglet).
import {
  apiClient,
  CLE_IMP_JETON,
  CLE_IMP_USER,
  CLE_IMP_INFO,
  infoImp,
  quitterSessionImp,
} from "@/lib/api";

/**
 * Ouvre une session « en tant que » `cible` (compte client ou utilisateur suivi)
 * après confirmation, puis recharge l'onglet sur la page d'accueil du portail de
 * la cible. `retour` = page admin d'origine (restaurée au retour).
 */
export async function ouvrirVoirEnTantQue(cibleId, cibleNom, retour) {
  const ok = window.confirm(
    `Naviguer en tant que « ${cibleNom} » pendant 30 minutes ?\n\n`
    + "• Lecture seule par défaut (décochable dans le bandeau rouge).\n"
    + "• Mot de passe, e-mail, téléphone, double authentification et suppression du compte restent interdits.\n"
    + "• Toute la session est enregistrée dans le journal.",
  );
  if (!ok) return false;
  const r = await apiClient.post(`/admin/voir-en-tant-que/${cibleId}`, {
    retour: retour || window.location.pathname,
  });
  const d = r.data || {};
  // Jeton et profil de la cible pour CET onglet ; le jeton de l'Admin reste dans le localStorage.
  sessionStorage.setItem(CLE_IMP_JETON, d.access_token);
  sessionStorage.setItem(CLE_IMP_USER, JSON.stringify(d.user || {}));
  sessionStorage.setItem(CLE_IMP_INFO, JSON.stringify({
    session_id: d.session_id,
    cible_nom: d.cible?.nom,
    cible_role: d.cible?.role,
    admin_nom: d.admin_nom,
    ro: d.ro !== false,
    expire_le: d.expire_le,
    retour: d.retour || "/admin",
  }));
  try { sessionStorage.setItem("sawali_welcome_briefing_seen", "1"); } catch { /* noop */ }
  window.location.href = d.accueil || "/portal";
  return true;
}

/** Coche / décoche « Lecture seule » : le serveur renvoie un nouveau jeton (même session). */
export async function basculerLectureSeule(ro) {
  const r = await apiClient.post("/voir-en-tant-que/mode", { ro });
  sessionStorage.setItem(CLE_IMP_JETON, r.data.access_token);
  const info = infoImp() || {};
  sessionStorage.setItem(CLE_IMP_INFO, JSON.stringify({ ...info, ro: r.data.ro }));
  return r.data.ro;
}

/** « Revenir à mon compte » : clôture côté serveur (au mieux) puis retour à la fiche d'origine. */
export async function revenirAMonCompte() {
  try { await apiClient.post("/voir-en-tant-que/fin"); } catch { /* session déjà close ou expirée */ }
  quitterSessionImp();
}
