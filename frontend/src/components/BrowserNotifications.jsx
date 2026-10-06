// S046 #2 (2026-02) — Browser notifications & title blinking.
//
// Two complementary user-feedback channels for when the SAWALI tab is in
// background / minimized :
//
//   1. Lot 64.2 — le titre de l'onglet affiche EN PERMANENCE (et rafraîchit toutes les 15 s)
//      le nombre de messages reçus non lus (WhatsApp, y compris expéditeurs inconnus) et
//      d'appels WhatsApp manqués non rattrapés, par ex. « (💬 3 · 📞 1) SAWALI ».
//      Avant, il affichait la somme des compteurs de notifications (erreurs comprises).
//      Onglet en arrière-plan : le titre clignote quand l'un des deux nombres augmente.
//
//   2. Native Notification API : a Windows / macOS / Android system toast
//      is fired the first time the unread count GROWS while the tab is
//      hidden. Requires user permission (asked once on first sign-in).
//
// The component is mounted globally inside `PortalLayout` so every signed-in
// route gets this behaviour for free.
//
// 2026-02 fork iter108 — S164 (Emmy) — Respects the admin global switch
// `browser_notifications_enabled` (via /public/ui-flags) AND the per-user
// opt-out flag (user.browser_notifications_optout) so users who find the
// alerts intrusive can silence them from their profile settings.
import { useEffect, useRef } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { apiClient } from "@/lib/api";
import { useUIFlags } from "@/lib/useUIFlags";

const POLL_MS = 15_000;
const BLINK_MS = 1_200;
const BASE_TITLE = "SAWALI · Espace Loois";
// Préfixe ajouté par ce composant (retiré avant d'en poser un nouveau)
const PREFIXE_RE = /^\((?:💬|📞)[^)]*\)\s*/;
const CLIGNOTANT_RE = /^🔔 /;

// Titre de base : titre actuel sans nos compteurs (le nom de marque peut changer après le chargement)
function titreDeBase() {
  const t = (document.title || "").replace(PREFIXE_RE, "");
  return !t || CLIGNOTANT_RE.test(t) ? BASE_TITLE : t;
}

// « (💬 3 · 📞 1) » — seulement les compteurs non nuls
function prefixe(messages, appels) {
  const parties = [];
  if (messages > 0) parties.push(`💬 ${messages}`);
  if (appels > 0) parties.push(`📞 ${appels}`);
  return parties.length ? `(${parties.join(" · ")}) ` : "";
}

// Texte clair pour le clignotement et la notification système
function phrase(messages, appels) {
  const parties = [];
  if (messages > 0) parties.push(`${messages} message${messages > 1 ? "s" : ""} non lu${messages > 1 ? "s" : ""}`);
  if (appels > 0) parties.push(`${appels} appel${appels > 1 ? "s" : ""} manqué${appels > 1 ? "s" : ""}`);
  return parties.join(" · ");
}

export default function BrowserNotifications() {
  const { user } = useAuth();
  const flags = useUIFlags();
  // S164 — Interrupteur global de l'administrateur (activé par défaut)
  const globalEnabled = flags?.browser_notifications_enabled !== false;
  // S164 — Désactivation par l'utilisateur (mémorisée dans le navigateur)
  const userOptedOut = (() => {
    try { return localStorage.getItem("sawali_browser_notifs_optout") === "1"; }
    catch { return false; }
  })();
  const featureActive = globalEnabled && !userOptedOut;
  const baseRef = useRef(BASE_TITLE);
  const compteursRef = useRef({ messages: 0, appels: 0 });
  const lastShownRef = useRef(0);
  const blinkTimerRef = useRef(null);
  const blinkToggleRef = useRef(false);
  const permRequestedRef = useRef(false);

  // Titre normal : compteurs + titre de base
  const poserTitre = () => {
    const { messages, appels } = compteursRef.current;
    document.title = prefixe(messages, appels) + baseRef.current;
  };

  // Au démontage (déconnexion) : titre sans compteurs
  useEffect(() => {
    baseRef.current = titreDeBase();
    return () => { document.title = baseRef.current; };
  }, []);

  // Demande (une seule fois) l'autorisation des notifications système
  useEffect(() => {
    if (!user || permRequestedRef.current) return;
    if (!featureActive) return;  // S164 — réglage administrateur / utilisateur
    if (typeof window === "undefined" || !("Notification" in window)) return;
    if (Notification.permission === "default") {
      const t = setTimeout(() => {
        try { Notification.requestPermission().catch(() => {}); }
        catch { /* rien */ }
      }, 5000);
      permRequestedRef.current = true;
      return () => clearTimeout(t);
    }
  }, [user, featureActive]);

  // Arrêt du clignotement (retour au titre avec compteurs)
  const stopBlinking = () => {
    if (blinkTimerRef.current) {
      clearInterval(blinkTimerRef.current);
      blinkTimerRef.current = null;
    }
    poserTitre();
  };

  // Clignotement tant que l'onglet est en arrière-plan
  const startBlinking = () => {
    if (blinkTimerRef.current) return;
    blinkToggleRef.current = false;
    blinkTimerRef.current = setInterval(() => {
      if (!document.hidden) { stopBlinking(); return; }
      blinkToggleRef.current = !blinkToggleRef.current;
      const { messages, appels } = compteursRef.current;
      if (blinkToggleRef.current) document.title = `🔔 ${phrase(messages, appels)}`;
      else poserTitre();
    }, BLINK_MS);
  };

  // Lecture des compteurs, mise à jour du titre et alertes
  useEffect(() => {
    if (!user) return undefined;
    let cancelled = false;

    const tick = async () => {
      // Messages reçus non lus (contacts + expéditeurs inconnus) et appels manqués non rattrapés
      const [rMsg, rApp] = await Promise.allSettled([
        apiClient.get("/me/whatsapp/unread"),
        apiClient.get("/me/wa-appels/non-repondus"),
      ]);
      if (cancelled) return;
      const precedent = compteursRef.current;
      const messages = rMsg.status === "fulfilled"
        ? (Number(rMsg.value.data?.total) || 0) + (Number(rMsg.value.data?.unknown) || 0) : precedent.messages;
      const appels = rApp.status === "fulfilled" ? Number(rApp.value.data?.total) || 0 : precedent.appels;
      compteursRef.current = { messages, appels };
      // Le titre de base peut avoir changé (nom de marque chargé entre-temps)
      if (!blinkTimerRef.current) baseRef.current = titreDeBase();
      if (!blinkTimerRef.current) poserTitre();

      const total = messages + appels;
      const aAugmente = messages > precedent.messages || appels > precedent.appels;
      if (aAugmente && document.hidden && featureActive) {
        startBlinking();
        // Notification système, une fois par hausse
        if ("Notification" in window && Notification.permission === "granted" && total > lastShownRef.current) {
          try {
            const n = new Notification(BASE_TITLE, {
              body: `${phrase(messages, appels)}. Cliquez pour ouvrir.`,
              tag: "sawali-unread",
              renotify: true,
              silent: false,
            });
            n.onclick = () => { window.focus(); n.close(); };
            lastShownRef.current = total;
          } catch { /* rien */ }
        }
      } else if (total === 0) {
        stopBlinking();
        lastShownRef.current = 0;
      }
    };

    // Retour sur l'onglet : arrêt du clignotement et relecture immédiate
    const onVisible = () => {
      if (document.hidden) return;
      stopBlinking();
      lastShownRef.current = compteursRef.current.messages + compteursRef.current.appels;
      tick();
    };
    // Relecture immédiate quand une conversation est lue ou un appel traité ailleurs dans le portail
    const onMaj = () => tick();

    tick();
    const timer = setInterval(tick, POLL_MS);
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("sawali:compteurs-maj", onMaj);
    window.addEventListener("sawali:wa-messages-read", onMaj);   // conversation lue (Contacts, Inbox unifiée)
    return () => {
      cancelled = true;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("sawali:compteurs-maj", onMaj);
      window.removeEventListener("sawali:wa-messages-read", onMaj);
      if (blinkTimerRef.current) clearInterval(blinkTimerRef.current);
      blinkTimerRef.current = null;
      document.title = baseRef.current;
    };
  }, [user, featureActive]);  // eslint-disable-line react-hooks/exhaustive-deps

  return null;
}
