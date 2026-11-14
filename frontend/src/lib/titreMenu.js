// titreMenu — règle 18 (14/11/2026) : dans tous les menus et sous-menus, CHAQUE MOT commence par une majuscule, sauf exception précisée.
//   « Gestion des contacts » → « Gestion Des Contacts » ; « Demandes à SAWALI » → « Demandes À SAWALI ».
// Seule la première lettre de chaque mot est forcée : les sigles (SAWALI, DG, OHADA) ne sont jamais abaissés ; un mot qui suit une apostrophe garde sa casse (« L'ordre ») ;
// les pictogrammes, chiffres et signes en tête de mot sont laissés tels quels. `casseLibre` = true : le libellé est rendu tel quel (exception demandée par le propriétaire).
export function titreMenu(libelle, casseLibre = false) {
  if (casseLibre || libelle == null) return libelle;
  return String(libelle)
    .split(/(\s+)/)                                              // garde les espaces d'origine
    .map((mot) => mot.replace(/^([^\p{L}\p{N}]*)(\p{Ll})/u, (_, avant, lettre) => avant + lettre.toLocaleUpperCase("fr")))
    .join("");
}
