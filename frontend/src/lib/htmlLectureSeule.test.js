// Lot 451 — le contenu affiché en lecture seule ne doit rien pouvoir exécuter ni saisir.
import { nettoyerHtml } from "./htmlLectureSeule";

test("la mise en forme est gardée", () => {
  expect(nettoyerHtml("<p>Bonjour <b>Awa</b></p><ul><li>Un</li></ul>")).toBe("<p>Bonjour <b>Awa</b></p><ul><li>Un</li></ul>");
  expect(nettoyerHtml("")).toBe("");
  expect(nettoyerHtml(null)).toBe("");
});

test("les scripts, cadres et champs de saisie sont retirés", () => {
  const sortie = nettoyerHtml('<p>Texte</p><script>alert(1)</script><iframe src="https://x"></iframe><input value="a"><button>OK</button><style>p{}</style>');
  expect(sortie).toBe("<p>Texte</p>");
});

test("les gestionnaires d'événements et les adresses javascript sont retirés", () => {
  const sortie = nettoyerHtml('<p onclick="alert(1)" contenteditable="true">A</p><a href="javascript:alert(1)">lien</a><a href=" JaVaScript:alert(1)">l2</a><img src="x" onerror="alert(1)">');
  expect(sortie).not.toMatch(/onclick|onerror|javascript:|contenteditable/i);
  expect(sortie).toContain("<p>A</p>");
});

test("un lien normal est gardé et s'ouvre dans un nouvel onglet ; une image intégrée est gardée", () => {
  const sortie = nettoyerHtml('<a href="https://sawalismartsystems.com">site</a><img src="data:image/png;base64,AAAA"><a href="data:text/html,<script>1</script>">d</a>');
  expect(sortie).toContain('href="https://sawalismartsystems.com"');
  expect(sortie).toContain('target="_blank"');
  expect(sortie).toContain('rel="noopener noreferrer"');
  expect(sortie).toContain('src="data:image/png;base64,AAAA"');
  expect(sortie).not.toContain("data:text/html");
});
