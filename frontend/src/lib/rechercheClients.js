// Recherche d'un client dans une liste, sur TOUT OU PARTIE d'une valeur (demande du propriétaire, 23/11/2026) :
// code client, nom complet, société ou nom ; sans tenir compte des majuscules ni des accents ; plusieurs mots = tous doivent se retrouver (dans n'importe quel ordre).

/** Texte comparable : sans accents, sans casse, espaces réduits. */
export const normaliserRecherche = (t) => String(t ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/\s+/g, " ").trim();

/** Libellé affiché d'un client : « [CODE] Nom ». */
export const libelleClient = (c) => `${c.client_code ? `[${c.client_code}] ` : ""}${c.full_name || c.company || c.name || "(sans nom)"}`;

/** Clients dont le code, le nom complet, la société ou le nom contient CHAQUE mot saisi (partie de valeur acceptée). `max` limite la liste affichée. */
export function filtrerClients(clients, saisie, max = 50) {
  const mots = normaliserRecherche(saisie).split(" ").filter(Boolean);
  const liste = Array.isArray(clients) ? clients : [];
  if (!mots.length) return liste.slice(0, max);
  const trouves = liste.filter((c) => {
    const botte = normaliserRecherche([c.client_code, c.full_name, c.company, c.name].filter(Boolean).join(" "));
    return mots.every((m) => botte.includes(m));
  });
  return trouves.slice(0, max);
}
