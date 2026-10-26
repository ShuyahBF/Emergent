/*
 * Lot 289 — Écran TV (Smart TV / navigateur de télé) : page plein écran SANS bouton.
 *  - Première ouverture : affiche un CODE à saisir dans Paramètres → « 📺 Écrans TV » (appairage).
 *  - Ensuite : fil des messages du Centre de Messagerie (les nouveaux arrivent en bas, animés) et demandes de support ouvertes.
 * Pour un développeur WinDev : la télé garde un SECRET dans son stockage local ; le serveur ne connaît que son empreinte.
 * Les numéros de téléphone sont déjà masqués par le serveur.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { API } from "@/lib/api";

const CLE_SECRET = "sawali_tv_secret";
const RYTHME_FLUX_MS = 8000;       // rafraîchissement du contenu
const RYTHME_ATTENTE_MS = 4000;    // attente de l'accord de l'administrateur

// Stockage de la télé (peut échouer sur certaines télés : on retombe sur la mémoire)
let secretEnMemoire = "";
const lireSecret = () => { try { return localStorage.getItem(CLE_SECRET) || secretEnMemoire; } catch { return secretEnMemoire; } };
const ecrireSecret = (v) => { secretEnMemoire = v; try { if (v) localStorage.setItem(CLE_SECRET, v); else localStorage.removeItem(CLE_SECRET); } catch { /* stockage indisponible */ } };

// Secret aléatoire de 48 caractères hexadécimaux
const fabriquerSecret = () => {
  const octets = new Uint8Array(24);
  if (window.crypto?.getRandomValues) window.crypto.getRandomValues(octets);
  else for (let i = 0; i < octets.length; i += 1) octets[i] = Math.floor(Math.random() * 256);
  return Array.from(octets).map((o) => o.toString(16).padStart(2, "0")).join("");
};

const heure = (iso) => { try { return new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }); } catch { return ""; } };
const jourHeure = (iso) => { try { return new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); } catch { return ""; } };

const STYLES = `
.tv-racine{position:fixed;inset:0;background:#0b1220;color:#f1f5f9;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;display:flex;flex-direction:column;overflow:hidden;cursor:none}
.tv-entete{display:flex;justify-content:space-between;align-items:center;padding:1.2vh 2.5vw;background:#111b30;border-bottom:2px solid #1e3a5f;font-size:3vh}
.tv-entete b{font-size:3.4vh;letter-spacing:.02em}
.tv-corps{flex:1;display:flex;min-height:0}
.tv-col{flex:1;display:flex;flex-direction:column;min-width:0;padding:2vh 2vw}
.tv-col + .tv-col{border-left:2px solid #1e3a5f}
.tv-titre{font-size:3.2vh;color:#7dd3fc;margin-bottom:1.5vh}
.tv-fil{flex:1;display:flex;flex-direction:column;justify-content:flex-end;overflow:hidden}
.tv-bulle{max-width:82%;margin-top:1.4vh;padding:1.4vh 1.6vw;border-radius:2vh;font-size:3.1vh;line-height:1.3;word-wrap:break-word}
.tv-entrant{align-self:flex-start;background:#1f2a44;border-bottom-left-radius:.6vh}
.tv-sortant{align-self:flex-end;background:#0f5d4f;border-bottom-right-radius:.6vh}
.tv-nom{font-size:2.2vh;color:#94a3b8;margin-bottom:.4vh}
.tv-nouveau{animation:tvArrivee .7s ease-out}
@keyframes tvArrivee{from{opacity:0;transform:translateY(5vh) scale(.96)}to{opacity:1;transform:none}}
.tv-ticket{background:#1c2540;border-left:1vh solid #f59e0b;border-radius:1.2vh;padding:1.4vh 1.4vw;margin-bottom:1.4vh;font-size:3vh}
.tv-ticket small{display:block;color:#94a3b8;font-size:2.2vh;margin-top:.4vh}
.tv-vide{color:#64748b;font-size:3vh;margin-top:4vh;text-align:center}
.tv-centre{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:4vh}
.tv-code{font-size:16vh;letter-spacing:.35em;font-weight:700;color:#38bdf8;margin:3vh 0;font-family:ui-monospace,Consolas,monospace}
.tv-aide{font-size:3.4vh;color:#cbd5e1;max-width:80vw;line-height:1.5}
@media (prefers-reduced-motion:reduce){.tv-nouveau{animation:none}}
`;

async function appeler(chemin, options = {}) {
  const ctrl = new AbortController();
  const minuterie = setTimeout(() => ctrl.abort(), 15000);
  try {
    return await fetch(`${API}${chemin}`, { ...options, signal: ctrl.signal });
  } finally {
    clearTimeout(minuterie);
  }
}

export default function TvEcran() {
  const [phase, setPhase] = useState(lireSecret() ? "flux" : "code");   // code | flux
  const [code, setCode] = useState("");
  const [flux, setFlux] = useState(null);
  const [hors, setHors] = useState(false);          // serveur injoignable : on garde le dernier contenu affiché
  const [maintenant, setMaintenant] = useState(new Date());
  const vus = useRef(new Set());                     // identifiants de messages déjà affichés (pour animer seulement les nouveaux)
  const dejaCharge = useRef(false);                  // vrai après le premier contenu reçu : seuls les messages suivants sont animés

  // Horloge de l'en-tête
  useEffect(() => {
    const t = setInterval(() => setMaintenant(new Date()), 15000);
    return () => clearInterval(t);
  }, []);

  // Phase « code » : on demande un code, puis on attend que l'administrateur l'ait saisi
  useEffect(() => {
    if (phase !== "code") return undefined;
    let arret = false;
    let minuterie = null;
    const demarrer = async () => {
      const secret = fabriquerSecret();
      try {
        const r = await appeler("/tv/appairage", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ secret }) });
        const d = await r.json();
        if (arret) return;
        setCode(d.code || "");
        const attendre = async () => {
          if (arret) return;
          try {
            const e = await (await appeler(`/tv/appairage/${d.appairage_id}`, { headers: { "X-Tv-Secret": secret } })).json();
            if (e.etat === "ok") { ecrireSecret(secret); setPhase("flux"); return; }
            if (e.etat === "expire") { demarrer(); return; }          // code périmé : on en demande un nouveau
          } catch { /* réseau coupé : on réessaie */ }
          minuterie = setTimeout(attendre, RYTHME_ATTENTE_MS);
        };
        minuterie = setTimeout(attendre, RYTHME_ATTENTE_MS);
      } catch {
        if (!arret) minuterie = setTimeout(demarrer, 10000);
      }
    };
    demarrer();
    return () => { arret = true; clearTimeout(minuterie); };
  }, [phase]);

  // Phase « flux » : on rafraîchit le contenu ; un refus (401) renvoie à l'appairage
  const charger = useCallback(async () => {
    try {
      const r = await appeler("/tv/flux", { headers: { "X-Tv-Secret": lireSecret() } });
      if (r.status === 401) { ecrireSecret(""); setFlux(null); setPhase("code"); return; }
      const d = await r.json();
      setFlux(d);
      setHors(false);
    } catch {
      setHors(true);
    }
  }, []);

  useEffect(() => {
    if (phase !== "flux") return undefined;
    charger();
    const t = setInterval(charger, RYTHME_FLUX_MS);
    return () => clearInterval(t);
  }, [phase, charger]);

  const messages = flux?.messages || [];
  const support = flux?.support || [];
  const modules = flux?.ecran?.modules || {};
  // Les messages du premier affichage ne sont pas animés ; ensuite seuls les nouveaux le sont
  const nouveaux = new Set(messages.filter((m) => !vus.current.has(m.id)).map((m) => m.id));
  useEffect(() => {
    messages.forEach((m) => vus.current.add(m.id));
    if (flux) dejaCharge.current = true;
  });

  return (
    <div className="tv-racine" data-testid="tv-ecran">
      <style>{STYLES}</style>
      {phase === "code" ? (
        <div className="tv-centre">
          <b style={{ fontSize: "5vh" }}>SAWALI — Écran TV</b>
          <div className="tv-code" data-testid="tv-code">{code || "······"}</div>
          <div className="tv-aide">
            Dans SAWALI, ouvrez Paramètres → « Écrans TV », saisissez ce code, choisissez le client et les contenus à afficher.
            Cet écran démarrera aussitôt.
          </div>
        </div>
      ) : (
        <>
          <div className="tv-entete">
            <b>{flux?.ecran?.nom || "SAWALI"}</b>
            <span>{hors ? "⚠ connexion perdue — dernier contenu affiché · " : ""}{maintenant.toLocaleString("fr-FR", { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" })}</span>
          </div>
          <div className="tv-corps">
            {modules.messagerie && (
              <div className="tv-col" style={{ flex: modules.support ? 1.5 : 1 }}>
                <div className="tv-titre">💬 Messagerie</div>
                <div className="tv-fil" data-testid="tv-messages">
                  {messages.length === 0 && <div className="tv-vide">Aucun message récent</div>}
                  {messages.slice(-8).map((m) => (
                    <div key={m.id} className={`tv-bulle ${m.sens === "entrant" ? "tv-entrant" : "tv-sortant"} ${dejaCharge.current && nouveaux.has(m.id) ? "tv-nouveau" : ""}`}>
                      <div className="tv-nom">{m.nom} · {heure(m.date)}</div>
                      {m.texte}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {modules.support && (
              <div className="tv-col">
                <div className="tv-titre">🛟 Demandes de support ouvertes</div>
                <div data-testid="tv-support">
                  {support.length === 0 && <div className="tv-vide">Aucune demande en cours</div>}
                  {support.slice(0, 6).map((t) => (
                    <div key={t.id} className="tv-ticket">
                      <b>{t.numero}</b> — {t.motif}
                      <small>{t.contact ? `${t.contact} · ` : ""}{jourHeure(t.date)}</small>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {flux && !modules.messagerie && !modules.support && <div className="tv-centre"><div className="tv-vide">Aucun contenu choisi pour cet écran</div></div>}
          </div>
        </>
      )}
    </div>
  );
}
