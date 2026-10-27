import { messageClavier } from "./outils";

const ev = (o) => ({ key: "", code: "", ctrlKey: false, altKey: false, metaKey: false, ...o });

test("clavier AZERTY : le caractère tapé part tel quel, quelle que soit la disposition du poste", () => {
  // La touche « A » d'un AZERTY est à la place du Q d'un QWERTY : code « KeyQ », caractère « a »
  expect(messageClavier("bas", ev({ key: "a", code: "KeyQ" }))).toEqual({ type: "clavier", action: "bas", code: "", touche: "a" });
  expect(messageClavier("bas", ev({ key: "A", code: "KeyQ" })).touche).toBe("A");                       // majuscule
  expect(messageClavier("bas", ev({ key: "é", code: "Digit2" })).touche).toBe("é");                    // accent
  expect(messageClavier("bas", ev({ key: "@", code: "Digit0", ctrlKey: true, altKey: true, altGraph: true })).code).toBe("");   // AltGr + à = @
});

test("raccourcis : la touche est désignée par sa lettre (Ctrl+A = la touche A de VOTRE clavier)", () => {
  expect(messageClavier("bas", ev({ key: "a", code: "KeyQ", ctrlKey: true }))).toEqual({ type: "clavier", action: "bas", code: "KeyA", touche: "a" });
  expect(messageClavier("haut", ev({ key: "c", code: "KeyC", ctrlKey: true })).code).toBe("KeyC");
  expect(messageClavier("bas", ev({ key: "1", code: "Digit1", metaKey: true })).code).toBe("Digit1");
});

test("touches de commande et espace : code physique ; touches mortes : rien", () => {
  expect(messageClavier("bas", ev({ key: "Enter", code: "Enter" })).code).toBe("Enter");
  expect(messageClavier("bas", ev({ key: "ArrowLeft", code: "ArrowLeft" })).code).toBe("ArrowLeft");
  expect(messageClavier("bas", ev({ key: "Shift", code: "ShiftLeft" })).code).toBe("ShiftLeft");
  expect(messageClavier("bas", ev({ key: " ", code: "Space" })).code).toBe("Space");
  expect(messageClavier("bas", ev({ key: "Dead", code: "BracketLeft" }))).toBeNull();
  expect(messageClavier("bas", ev({ key: "Process", code: "KeyA" }))).toBeNull();
});
