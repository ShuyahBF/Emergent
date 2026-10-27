import { alerteAEmettre } from "./suiviAlertes";

test("alerte « prochain » une seule fois, puis « c'est à vous » une seule fois", () => {
  const attente2 = { etat: "attente", devant: 2 }, attente0 = { etat: "attente", devant: 0 }, encours = { etat: "en_cours", devant: 0 };
  expect(alerteAEmettre(null, attente2)).toBeNull();                       // loin de son tour : silence
  expect(alerteAEmettre(attente2, { etat: "attente", devant: 1 })).toBeNull();
  expect(alerteAEmettre({ etat: "attente", devant: 1 }, attente0).cle).toBe("prochain");
  expect(alerteAEmettre(attente0, attente0)).toBeNull();                   // pas de répétition à chaque rafraîchissement
  expect(alerteAEmettre(attente0, encours).cle).toBe("en_cours");
  expect(alerteAEmettre(encours, encours)).toBeNull();
  expect(alerteAEmettre(encours, { etat: "fait", devant: 0 })).toBeNull();
  expect(alerteAEmettre(null, attente0).cle).toBe("prochain");             // ouverture de la page alors qu'il est déjà le prochain
});
