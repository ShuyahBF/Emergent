// sw.js — « service worker » de SAWALI Admin (lot 243, application Android d'administration empaquetée par PWABuilder).
// Rôle UNIQUE : quand l'ouverture d'une PAGE échoue faute d'Internet, afficher « Pas de connexion » (offline.html)
// au lieu de l'erreur du navigateur.
// Garanties de sécurité :
//   - rien d'autre n'est mis en cache : jamais de donnée d'administration, jamais de réponse de l'API ;
//   - les appels à l'API (/api/…), les images, scripts et le temps réel (WebSocket) ne passent PAS par ici ;
//   - le site reste toujours à jour (aucune ancienne version n'est servie).
const CACHE_HORS_LIGNE = "sawali-hors-ligne-1";

// Installation : on garde seulement la page « hors connexion » et son icône (aucune donnée)
self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE_HORS_LIGNE).then((c) => c.addAll(["/offline.html", "/icone-admin-192.png"])).catch(() => {}));
  self.skipWaiting();
});

// Activation : on prend la main tout de suite et on supprime les anciennes versions du cache
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((cles) => Promise.all(cles.filter((c) => c !== CACHE_HORS_LIGNE && c.startsWith("sawali-hors-ligne")).map((c) => caches.delete(c))))
      .then(() => self.clients.claim()),
  );
});

// Chaque requête : on ne s'occupe QUE de l'ouverture d'une page (navigation), hors adresses /api/
self.addEventListener("fetch", (event) => {
  const requete = event.request;
  if (requete.mode !== "navigate") return;
  if (new URL(requete.url).pathname.startsWith("/api/")) return;
  // Réseau d'abord ; seulement en cas d'échec, la page « hors connexion »
  event.respondWith(fetch(requete).catch(() => caches.match("/offline.html").then((r) => r || Response.error())));
});
