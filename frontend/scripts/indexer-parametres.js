// indexer-parametres.js — Lot 203 : index de recherche en texte intégral de la page Paramètres.
//
// Rôle : pour chaque rubrique <Filterable title="…"> de src/pages/admin/AdminSettings.jsx, rassembler TOUT le texte
// lisible qu'elle affiche (titres, libellés, aides, placeholders, descriptions…), y compris celui des composants
// importés (src/pages/admin/sections/*.jsx, etc.). Le résultat est écrit dans src/pages/admin/settingsIndex.json,
// lu par la barre de recherche des Paramètres : on retrouve ainsi n'importe quelle rubrique par un mot de son contenu,
// SANS monter les 100+ rubriques (aucune requête serveur, aucun ralentissement de la page).
//
// Exécution : automatique avant « yarn build » (script « prebuild »), ou à la main : node scripts/indexer-parametres.js
// Limite : seuls les textes écrits dans le code sont indexés (pas les données venant du serveur).
// Ce script n'échoue jamais le build : en cas de problème, le dernier index commité est conservé.
const fs = require("fs");
const path = require("path");

const SRC = path.join(__dirname, "..", "src");
const FICHIER = path.join(SRC, "pages", "admin", "AdminSettings.jsx");
const SORTIE = path.join(SRC, "pages", "admin", "settingsIndex.json");
const ATTRIBUTS_TEXTE = new Set(["placeholder", "title", "label", "aria-label", "alt", "description", "hint", "helper", "text"]);
const MAX_PAR_RUBRIQUE = 30000;   // caractères conservés par rubrique

let parser;
try { parser = require("@babel/parser"); } catch (e) { console.warn("[indexer-parametres] @babel/parser introuvable : index conservé tel quel."); process.exit(0); }

const analyser = (code) => parser.parse(code, { sourceType: "module", plugins: ["jsx"], errorRecovery: true });

const normaliser = (t) => String(t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/\s+/g, " ").trim();

// Chaîne qui ressemble à des classes CSS (« flex items-center gap-2 ») : ignorée
const ressembleCss = (s) => {
  const mots = s.split(/\s+/).filter(Boolean);
  if (!mots.length) return true;
  const css = mots.filter((m) => /^[a-z0-9!:\/\[\]\.\-%#_]+$/.test(m) && /[-:\/\[]/.test(m)).length;
  return css / mots.length >= 0.6;
};
const phrase = (s) => {
  const t = String(s || "").replace(/\s+/g, " ").trim();
  return t.length >= 3 && /[A-Za-zÀ-ÿ]{2}/.test(t) && !ressembleCss(t) && !/^https?:\/\//.test(t) ? t : null;
};

// ---- résolution des imports ----
const resoudre = (depuis, spec) => {
  let base;
  if (spec.startsWith("@/")) base = path.join(SRC, spec.slice(2));
  else if (spec.startsWith(".")) base = path.resolve(path.dirname(depuis), spec);
  else return null;
  for (const c of [base, base + ".jsx", base + ".js", path.join(base, "index.jsx"), path.join(base, "index.js")]) {
    if (fs.existsSync(c) && fs.statSync(c).isFile()) return c;
  }
  return null;
};

const cacheFichiers = new Map();
const lireFichier = (f) => {
  if (!cacheFichiers.has(f)) {
    try {
      const ast = analyser(fs.readFileSync(f, "utf8"));
      const imports = {};      // identifiant local → fichier source
      const decls = {};        // composants déclarés à la racine du fichier
      for (const n of ast.program.body) {
        if (n.type === "ImportDeclaration") {
          const cible = resoudre(f, n.source.value);
          if (cible) n.specifiers.forEach((s) => { imports[s.local.name] = cible; });
        }
        const d = n.type === "ExportNamedDeclaration" || n.type === "ExportDefaultDeclaration" ? n.declaration : n;
        if (d && d.type === "FunctionDeclaration" && d.id) decls[d.id.name] = d;
        if (d && d.type === "VariableDeclaration") d.declarations.forEach((v) => { if (v.id && v.id.name && v.init) decls[v.id.name] = v.init; });
      }
      cacheFichiers.set(f, { ast, imports, decls });
    } catch (e) {
      cacheFichiers.set(f, { ast: null, imports: {}, decls: {} });
    }
  }
  return cacheFichiers.get(f);
};

// ---- parcours d'un nœud : textes + composants référencés ----
const parcourir = (noeud, texte, composants, dansAttribut = false) => {
  if (!noeud || typeof noeud !== "object") return;
  if (Array.isArray(noeud)) { noeud.forEach((n) => parcourir(n, texte, composants, dansAttribut)); return; }
  switch (noeud.type) {
    case "JSXText": { const p = phrase(noeud.value); if (p) texte.add(p); return; }
    case "StringLiteral": { if (!dansAttribut) { const p = phrase(noeud.value); if (p && /\s/.test(p)) texte.add(p); } return; }
    case "TemplateLiteral": { noeud.quasis.forEach((q) => { const p = phrase(q.value.cooked); if (p && /\s/.test(p)) texte.add(p); }); noeud.expressions.forEach((e) => parcourir(e, texte, composants)); return; }
    case "JSXAttribute": {
      const nom = noeud.name && noeud.name.name;
      if (noeud.value && noeud.value.type === "StringLiteral") {
        if (ATTRIBUTS_TEXTE.has(nom)) { const p = phrase(noeud.value.value); if (p) texte.add(p); }
        return;
      }
      parcourir(noeud.value, texte, composants, !ATTRIBUTS_TEXTE.has(nom) && nom === "className");
      return;
    }
    case "JSXOpeningElement": {
      if (noeud.name && noeud.name.type === "JSXIdentifier" && /^[A-Z]/.test(noeud.name.name)) composants.add(noeud.name.name);
      parcourir(noeud.attributes, texte, composants);
      return;
    }
    default:
  }
  for (const cle of Object.keys(noeud)) {
    if (cle === "loc" || cle === "start" || cle === "end" || cle === "extra" || cle === "leadingComments" || cle === "trailingComments") continue;
    const v = noeud[cle];
    if (v && typeof v === "object") parcourir(v, texte, composants, dansAttribut);
  }
};

// Texte d'un nœud + de tous les composants qu'il utilise (fichiers importés ou déclarations locales)
const texteComplet = (noeud, fichier, texte, visites, profondeur = 0) => {
  const composants = new Set();
  parcourir(noeud, texte, composants);
  if (profondeur > 4) return;
  const info = lireFichier(fichier);
  for (const nom of composants) {
    if (nom === "Filterable") continue;   // l'enveloppe des rubriques (badge « Nouveau »…) n'est pas du contenu
    if (info.decls[nom]) {
      const cle = `${fichier}#${nom}`;
      if (!visites.has(cle)) { visites.add(cle); texteComplet(info.decls[nom], fichier, texte, visites, profondeur + 1); }
    } else if (info.imports[nom]) {
      const cible = info.imports[nom];
      if (!visites.has(cible)) {
        visites.add(cible);
        const autre = lireFichier(cible);
        if (autre.ast) texteComplet(autre.ast.program, cible, texte, visites, profondeur + 1);
      }
    }
  }
};

// ---- rubriques <Filterable> de AdminSettings.jsx ----
const principal = lireFichier(FICHIER);
if (!principal.ast) { console.warn("[indexer-parametres] AdminSettings.jsx illisible : index conservé."); process.exit(0); }

const rubriques = [];
const trouver = (n) => {
  if (!n || typeof n !== "object") return;
  if (Array.isArray(n)) { n.forEach(trouver); return; }
  if (n.type === "JSXElement" && n.openingElement.name.name === "Filterable") {
    const t = n.openingElement.attributes.find((a) => a.name && a.name.name === "title");
    const v = t && t.value;
    const titre = v && (v.type === "StringLiteral" ? v.value : v.expression && v.expression.type === "StringLiteral" ? v.expression.value : null);
    if (titre) rubriques.push({ titre, noeud: n });
  }
  for (const cle of Object.keys(n)) {
    if (cle === "loc" || cle === "extra") continue;
    const v = n[cle];
    if (v && typeof v === "object") trouver(v);
  }
};
trouver(principal.ast.program);

// Descriptions « Nouveautés » associées aux titres (objet { "titre": "description" } du même fichier)
const descriptions = {};
const chercherDescriptions = (n) => {
  if (!n || typeof n !== "object") return;
  if (Array.isArray(n)) { n.forEach(chercherDescriptions); return; }
  if (n.type === "ObjectProperty" && n.key && n.key.type === "StringLiteral" && n.value && n.value.type === "StringLiteral" && n.value.value.length > 40) {
    (descriptions[n.key.value] = descriptions[n.key.value] || []).push(n.value.value);
  }
  for (const cle of Object.keys(n)) {
    if (cle === "loc" || cle === "extra") continue;
    const v = n[cle];
    if (v && typeof v === "object") chercherDescriptions(v);
  }
};
chercherDescriptions(principal.ast.program);

const sections = {};
for (const { titre, noeud } of rubriques) {
  const texte = new Set();
  texteComplet(noeud, FICHIER, texte, new Set());
  (descriptions[titre] || []).forEach((d) => texte.add(d));
  // Texte d'origine (accents conservés, pour afficher des extraits lisibles) : la recherche le normalise au moment voulu
  sections[titre] = [...texte].join(" · ").replace(/\s+/g, " ").slice(0, MAX_PAR_RUBRIQUE);
}

fs.writeFileSync(SORTIE, JSON.stringify({ genere_par: "scripts/indexer-parametres.js", rubriques: Object.keys(sections).length, sections }, null, 0) + "\n");
const taille = fs.statSync(SORTIE).size;
console.log(`[indexer-parametres] ${Object.keys(sections).length} rubriques indexées, ${(taille / 1024).toFixed(0)} Ko → ${path.relative(process.cwd(), SORTIE)}`);
