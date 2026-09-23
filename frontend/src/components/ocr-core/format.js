// ocr-core (module commun, source unique : dépôt ShuyahBF/Claude, dossier ocr-core/).
// Ne pas modifier dans un site : corriger dans ocr-core puis resynchroniser.
//
// Petites fonctions d'affichage partagées par les écrans OCR.

// Montant en FCFA, avec 2 décimales sous 100 FCFA (le coût d'une pièce est
// souvent de quelques FCFA : l'arrondir à l'entier ferait perdre l'info).
export function formatXof(value) {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  const digits = Math.abs(n) < 100 ? 2 : 0;
  return `${n.toLocaleString("fr-FR", { minimumFractionDigits: digits, maximumFractionDigits: digits })} FCFA`;
}

// Ratio 0-1 affiché en pourcentage entier ("—" si pas encore mesuré).
export function formatPercent(ratio) {
  if (ratio === null || ratio === undefined) return "—";
  return `${Math.round(Number(ratio) * 100)} %`;
}

// Durée en secondes avec une décimale.
export function formatDuration(ms) {
  if (!ms) return "—";
  return `${(Number(ms) / 1000).toFixed(1)} s`;
}

// Nom court d'un modèle ("claude-sonnet-5" → "Sonnet 5",
// "claude-haiku-4-5-20251001" → "Haiku 4.5" : la date de version est masquée).
export function shortModel(modelId) {
  if (!modelId) return "—";
  return modelId
    .replace(/^claude-/, "")
    .replace(/-\d{8}$/, "")
    .split("-")
    .map((part, i) => (i === 0 ? part.charAt(0).toUpperCase() + part.slice(1) : part))
    .join(" ")
    .replace(/(\d) (\d)/, "$1.$2");
}

// Valeur d'un champ extrait affichée lisiblement (listes/objets en JSON
// indenté au lieu de "[object Object]", "—" si vide au lieu de "null").
export function displayValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value);
}

// Message d'erreur lisible d'une réponse d'API (FastAPI renvoie `detail`
// en texte, ou en liste d'objets pour une erreur de validation 422).
export function errorMessage(err, fallback = "Une erreur est survenue") {
  const detail = err?.response?.data?.detail;
  if (Array.isArray(detail)) {
    const msgs = detail.map((d) => (typeof d === "string" ? d : d?.msg)).filter(Boolean);
    if (msgs.length) return msgs.join(" · ");
  } else if (typeof detail === "string" && detail) {
    return detail;
  }
  return err?.message || fallback;
}
