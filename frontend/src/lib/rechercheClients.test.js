import { filtrerClients, libelleClient } from "./rechercheClients";

const clients = [
  { id: "1", client_code: "IPM", full_name: "Institut de Prévention Médicale" },
  { id: "2", client_code: "CMC", full_name: "Clinique Médicale du Centre", company: "CMC SA" },
  { id: "3", client_code: "AMY", full_name: "Pharmacie Amitié Miyougou" },
];

test("une partie d'une valeur suffit, sans casse ni accents", () => {
  expect(filtrerClients(clients, "amiti").map((c) => c.id)).toEqual(["3"]);       // « amiti » trouve « Amitié »
  expect(filtrerClients(clients, "PREVENTION").map((c) => c.id)).toEqual(["1"]);  // accents et casse ignorés
  expect(filtrerClients(clients, "yougo").map((c) => c.id)).toEqual(["3"]);       // au milieu d'un mot
});

test("le code client se cherche aussi, et plusieurs mots doivent tous se retrouver", () => {
  expect(filtrerClients(clients, "cmc").map((c) => c.id)).toEqual(["2"]);
  expect(filtrerClients(clients, "clinique centre").map((c) => c.id)).toEqual(["2"]);
  expect(filtrerClients(clients, "clinique pharmacie")).toEqual([]);
});

test("saisie vide : tous les clients (limités), et libellé « [CODE] Nom »", () => {
  expect(filtrerClients(clients, "  ").length).toBe(3);
  expect(filtrerClients(clients, "", 2).length).toBe(2);
  expect(libelleClient(clients[0])).toBe("[IPM] Institut de Prévention Médicale");
});
