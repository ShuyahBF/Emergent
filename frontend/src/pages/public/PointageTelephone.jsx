// ============================================================================
// PointageTelephone.jsx — Lot 496 : page du TÉLÉPHONE pour le pointage d'inventaire (ouverte par le QR code, sans compte).
// L'auxiliaire donne son prénom et son lieu (salle de vente, magasin…), puis dicte « ligne 245, 12, mars 2027, suivant »
// ou tape les trois valeurs. Le NOM DU PRODUIT s'affiche aussitôt (garde-fou contre un mauvais numéro), « suivant » enregistre.
// Hors connexion : les saisies attendent dans le téléphone (localStorage) et partent dès que le réseau revient, sans double comptage.
// Lot 498 : après le QR code, le MOT DE PASSE DU COMMERCE est demandé (POST …/acces) ; il donne la liste des produits et un jeton du
// téléphone (en-tête X-Pointage-Telephone). Mot de passe changé ou clé révoquée → la page le redemande (réponse 401).
// Lot 499 : interface, dictée et voix dans la LANGUE du commerce (français ou anglais) ; lien vers l'application Android (ShuyahStore).
// Backend : GET /api/public/pointage/{jeton}, POST …/acces, …/saisies, …/annuler (routes/pointage_telephone.py).
// Parallèle WinDev : une fenêtre de saisie avec une file locale (fichier HFSQL Classic) synchronisée avec le serveur par un timer.
// ============================================================================
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { Check, CloudOff, Keyboard, KeyRound, Smartphone, Loader2, MapPin, Mic, PackageSearch, Undo2, Volume2, VolumeX, Wifi } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { analyserDictee } from "@/lib/dicteePointage";
import { URL_APP_ANDROID, langueVoix, traducteur } from "@/lib/i18nPointage";
import PasswordInput from "@/components/PasswordInput";

// --- Petits outils de stockage local (try/catch : navigation privée ou stockage plein ne doivent rien casser) ---------------
const lire = (cle, defaut) => { try { const v = localStorage.getItem(cle); return v ? JSON.parse(v) : defaut; } catch { return defaut; } };
const ecrire = (cle, v) => { try { localStorage.setItem(cle, JSON.stringify(v)); } catch { /* stockage indisponible */ } };
const uid = () => (crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`).replace(/[^A-Za-z0-9_-]/g, "");
const Reconnaissance = typeof window !== "undefined" ? (window.SpeechRecognition || window.webkitSpeechRecognition) : null;

export default function PointageTelephone() {
  const { jeton } = useParams();
  const cle = (k) => `pointage:${jeton}:${k}`;
  const [info, setInfo] = useState(null);               // avant le mot de passe : nom du commerce, numéro, clé de pointage
  const [inv, setInv] = useState(null);                 // après le mot de passe : lieux et lignes (gardés pour le hors connexion)
  const [mdp, setMdp] = useState("");
  const [verif, setVerif] = useState(false);
  const [erreur, setErreur] = useState("");
  const [prenom, setPrenom] = useState(() => lire(`pointage:${jeton}:prenom`, ""));
  const [lieu, setLieu] = useState(() => lire(`pointage:${jeton}:lieu`, ""));
  const [pret, setPret] = useState(() => Boolean(lire(`pointage:${jeton}:prenom`, "") && lire(`pointage:${jeton}:lieu`, "")));
  const [champs, setChamps] = useState({ chrono: "", qte: "", peremption: "" });
  const [entendu, setEntendu] = useState("");           // dernière phrase entendue (affichée)
  const [ecoute, setEcoute] = useState(false);
  const [voix, setVoix] = useState(() => lire("pointage:voix", true));
  const [file, setFile] = useState(() => lire(`pointage:${jeton}:file`, []));        // saisies pas encore reçues par SAWALI
  const [historique, setHistorique] = useState(() => lire(`pointage:${jeton}:histo`, []));
  const [enLigne, setEnLigne] = useState(typeof navigator === "undefined" ? true : navigator.onLine);
  const appareil = useMemo(() => { let a = lire("pointage:appareil", ""); if (!a) { a = uid(); ecrire("pointage:appareil", a); } return a; }, []);
  const reco = useRef(null);
  const champsRef = useRef(champs);
  champsRef.current = champs;
  // Langue du commerce (lot 499) : `t` est STABLE et lit toujours la langue courante (les fonctions mémorisées restent justes)
  const langue = inv?.langue || info?.langue || "fr";
  const tRef = useRef(traducteur(langue));
  tRef.current = traducteur(langue);
  const t = useCallback((fr, vars) => tRef.current(fr, vars), []);

  // --- Chargement de l'inventaire (gardé en mémoire locale : la page s'ouvre même sans réseau) -----------------------------
  useEffect(() => {
    const garde = lire(cle("tel"), "") ? lire(cle("inv"), null) : null;   // déjà déverrouillé sur ce téléphone
    apiClient.get(`/public/pointage/${jeton}`)
      .then(({ data }) => { setInfo(data); if (garde) setInv(garde); })
      .catch((e) => {
        if (garde && !e.response) setInv(garde);            // hors connexion : dernière liste connue
        else setErreur(e.response?.data?.detail || t("Inventaire inaccessible."));
      });
  }, [jeton]);   // eslint-disable-line react-hooks/exhaustive-deps

  // Mot de passe du commerce → jeton du téléphone + liste des produits
  const deverrouiller = async () => {
    setVerif(true);
    try {
      const { data } = await apiClient.post(`/public/pointage/${jeton}/acces`, { mot_de_passe: mdp });
      ecrire(cle("tel"), data.jeton_telephone);
      const reste = { ...data };
      delete reste.jeton_telephone;                          // le jeton est rangé à part, jamais avec la liste des produits
      ecrire(cle("inv"), reste); setInv(reste); setMdp("");
      toast.success(t("Commerce reconnu : vous pouvez pointer."));
    } catch (e) { toast.error(e.response?.data?.detail || t("Vérification impossible sans réseau.")); }
    setVerif(false);
  };
  const entetes = () => ({ headers: { "X-Pointage-Telephone": lire(cle("tel"), "") } });
  // 401 : mot de passe changé ou clé révoquée → retour à l'écran du mot de passe (la file d'attente est GARDÉE)
  const verrouiller = () => { ecrire(cle("tel"), ""); setInv(null); toast.error(t("Mot de passe du commerce à ressaisir.")); };

  const produits = useMemo(() => new Map((inv?.lignes || []).map((l) => [l.c, l])), [inv]);
  const produit = produits.get(Number(champs.chrono));
  const nomLieu = inv?.lieux?.find((l) => l.id === lieu)?.nom || "";

  // --- Voix : relit ce qui a été compris (désactivable) -----------------------------------------------------------------
  const dire = useCallback((texte) => {
    if (!voix || !window.speechSynthesis) return;
    const u = new SpeechSynthesisUtterance(texte);
    u.lang = langueVoix(langue); u.rate = 1.1;
    window.speechSynthesis.cancel(); window.speechSynthesis.speak(u);
  }, [voix, langue]);

  // --- Envoi de la file d'attente (au plus 200 saisies à la fois ; réessayé toutes les 5 s) -------------------------------
  const envoyer = useCallback(async () => {
    const attente = lire(cle("file"), []);
    if (!attente.length || !navigator.onLine) return;
    try {
      const { data } = await apiClient.post(`/public/pointage/${jeton}/saisies`, { prenom, appareil, saisies: attente.slice(0, 200) }, entetes());
      const traitees = new Set([...data.acceptees, ...data.refusees.map((r) => r.uid)]);
      const reste = lire(cle("file"), []).filter((s) => !traitees.has(s.uid));
      ecrire(cle("file"), reste); setFile(reste);
      const histo = lire(cle("histo"), []).map((h) => {
        const refus = data.refusees.find((r) => r.uid === h.uid);
        if (refus) return { ...h, etat: "refusee", erreur: refus.erreur };
        if (data.doublons.some((d) => d.uid === h.uid)) return { ...h, etat: "doublon" };
        return data.acceptees.includes(h.uid) && h.etat === "attente" ? { ...h, etat: "envoyee" } : h;
      });
      ecrire(cle("histo"), histo); setHistorique(histo);
      data.doublons.forEach((d) => toast.warning(t("Ligne {n} déjà comptée dans ce lieu : quantités ADDITIONNÉES.", { n: d.chrono })));
      data.refusees.forEach((r) => toast.error(t("Saisie refusée : {e}", { e: r.erreur })));
    } catch (e) {
      if (e.response?.status === 401) verrouiller();
      else if (e.response?.status === 404) setErreur(t("QR code expiré ou inventaire clôturé : les saisies restantes ne peuvent plus être envoyées."));
    }
  }, [jeton, prenom, appareil]);   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const t = setInterval(envoyer, 5000);
    const haut = () => { setEnLigne(true); envoyer(); };
    const bas = () => setEnLigne(false);
    window.addEventListener("online", haut); window.addEventListener("offline", bas);
    return () => { clearInterval(t); window.removeEventListener("online", haut); window.removeEventListener("offline", bas); };
  }, [envoyer]);

  // --- « Suivant » : contrôle puis mise en file ---------------------------------------------------------------------------
  const valider = useCallback((c = champsRef.current) => {
    const chrono = Number(c.chrono), qte = Number(c.qte);
    if (!c.chrono || !produits.has(chrono)) { toast.error(t("Ligne {n} inconnue dans cet inventaire.", { n: c.chrono || "?" })); dire(t("Ligne {n} inconnue", { n: "" })); return; }
    if (c.qte === "" || !Number.isInteger(qte) || qte < 0) { toast.error(t("Quantité manquante.")); dire(t("Quantité manquante.")); return; }
    const s = { uid: uid(), chrono, qte, lieu, peremption: c.peremption || null, texte: entendu.slice(0, 120) };
    const f = [...lire(cle("file"), []), s];
    ecrire(cle("file"), f); setFile(f);
    const h = [{ ...s, libelle: produits.get(chrono).l, etat: "attente", heure: new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }) },
      ...lire(cle("histo"), [])].slice(0, 50);
    ecrire(cle("histo"), h); setHistorique(h);
    setChamps({ chrono: "", qte: "", peremption: "" }); setEntendu("");
    toast.success(t("Ligne {n} enregistrée : {q}", { n: chrono, q: qte }));
    dire(t("Enregistré. Suivant."));
    setTimeout(envoyer, 50);
  }, [produits, lieu, entendu, dire, envoyer]);   // eslint-disable-line react-hooks/exhaustive-deps

  // --- « Annule » : retire la dernière saisie de CE téléphone (de la file, ou sur SAWALI si déjà envoyée) -----------------
  const annulerDerniere = useCallback(async () => {
    const h = lire(cle("histo"), []);
    const derniere = h.find((x) => x.etat !== "annulee" && x.etat !== "refusee");
    if (!derniere) { toast.info(t("Aucune saisie à annuler.")); return; }
    const f = lire(cle("file"), []);
    if (f.some((s) => s.uid === derniere.uid)) { const reste = f.filter((s) => s.uid !== derniere.uid); ecrire(cle("file"), reste); setFile(reste); }
    else {
      try { await apiClient.post(`/public/pointage/${jeton}/annuler`, { appareil, uid: derniere.uid }, entetes()); }
      catch (e) { if (e.response?.status === 401) verrouiller(); else toast.error(t("Annulation impossible sans réseau : réessayez dans un instant.")); return; }
    }
    const nouv = h.map((x) => (x.uid === derniere.uid ? { ...x, etat: "annulee" } : x));
    ecrire(cle("histo"), nouv); setHistorique(nouv);
    toast.success(t("Ligne {n} annulée.", { n: derniere.chrono })); dire(t("Ligne {n} annulée.", { n: derniere.chrono }));
  }, [jeton, appareil, dire]);   // eslint-disable-line react-hooks/exhaustive-deps

  // --- Dictée : reconnaissance vocale du téléphone (Chrome / Android), en continu tant que le micro est actif -------------
  const traiterPhrase = useCallback((phrase) => {
    setEntendu(phrase);
    const r = analyserDictee(phrase);
    if (r.commande === "annule") { annulerDerniere(); return; }
    const c = { ...champsRef.current };
    if (r.chrono !== undefined) c.chrono = String(r.chrono);
    if (r.qte !== undefined) c.qte = String(r.qte);
    if (r.peremption !== undefined) c.peremption = r.peremption;
    setChamps(c); champsRef.current = c;
    if (r.chrono !== undefined) {
      const p = produits.get(r.chrono);
      dire(p ? `${r.chrono}, ${p.l}${r.qte !== undefined ? `, ${r.qte}` : ""}` : t("Ligne {n} inconnue", { n: r.chrono }));
    }
    if (r.commande === "suivant") valider(c);
  }, [produits, dire, valider, annulerDerniere, t]);

  const basculerMicro = () => {
    if (!Reconnaissance) { toast.error(t("Dictée non disponible sur ce navigateur : utilisez Chrome, ou le clavier.")); return; }
    if (ecoute) { reco.current?.stop(); setEcoute(false); return; }
    const r = new Reconnaissance();
    r.lang = langueVoix(langue); r.continuous = true; r.interimResults = false;
    r.onresult = (ev) => { for (let i = ev.resultIndex; i < ev.results.length; i++) if (ev.results[i].isFinal) traiterPhrase(ev.results[i][0].transcript); };
    r.onerror = (ev) => { if (ev.error === "not-allowed") toast.error(t("Micro refusé : autorisez-le dans le navigateur.")); else if (ev.error === "network") toast.error(t("Dictée impossible sans réseau : utilisez le clavier.")); };
    r.onend = () => { if (reco.current === r && ecouteRef.current) { try { r.start(); } catch { setEcoute(false); } } };   // Chrome coupe après un silence : on relance
    reco.current = r; r.start(); setEcoute(true);
  };
  const ecouteRef = useRef(ecoute);
  ecouteRef.current = ecoute;
  useEffect(() => () => { ecouteRef.current = false; reco.current?.stop(); }, []);

  // ------------------------------------------------------------------------------------------------------------------------
  if (erreur && !inv) return <Ecran><p className="text-center text-red-700 font-semibold">{erreur}</p></Ecran>;
  if (!inv && !info) return <Ecran><Loader2 className="mx-auto h-10 w-10 animate-spin text-sky-600" aria-label="Patientez…" /></Ecran>;

  // Écran 0 : mot de passe du commerce (lot 498)
  if (!inv) {
    return (
      <Ecran t={t} titre={`${info.structure} · ${info.code_inv || info.numero}`}>
        {/* Lot 500 : sans souscription vérifiée du commerce, le pointage est fermé (le message le dit avant même le mot de passe) */}
        {info.souscription && !info.souscription.valide && (
          <p className="mb-3 rounded-xl bg-red-50 p-3 text-sm font-semibold text-red-800">{t("Le pointage de ce commerce est suspendu : souscription expirée ou pas encore vérifiée. Prévenez votre responsable.")}</p>
        )}
        <div className="rounded-2xl border bg-white p-4">
          <p className="flex items-center gap-2 font-semibold text-slate-800"><KeyRound className="h-5 w-5 text-violet-600" aria-hidden="true" />{t("Mot de passe du commerce")}</p>
          <p className="mt-1 text-sm text-slate-600">{t("Clé de pointage {cle}. Demandez le mot de passe à votre responsable.", { cle: info.cle_pointage })}</p>
          <PasswordInput value={mdp} onChange={(e) => setMdp(e.target.value)} placeholder="abcd-1234" autoComplete="off"
                         onKeyDown={(e) => { if (e.key === "Enter" && mdp.length >= 4) deverrouiller(); }}
                         className="mt-3 w-full rounded-xl border px-4 py-3 text-lg tracking-wider" />
          <button type="button" disabled={mdp.length < 4 || verif} onClick={deverrouiller}
                  className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-600 py-4 text-lg font-bold text-white disabled:opacity-40">
            {verif ? <Loader2 className="h-6 w-6 animate-spin" aria-hidden="true" /> : <Check className="h-6 w-6" aria-hidden="true" />}{t("Valider")}
          </button>
        </div>
        {file.length > 0 && <p className="mt-3 text-center text-sm text-amber-700">{t("{n} saisie(s) en attente : elles partiront après le mot de passe.", { n: file.length })}</p>}
        <LienApp t={t} />
      </Ecran>
    );
  }

  // Écran 1 : prénom et lieu
  if (!pret) {
    return (
      <Ecran t={t} titre={`${inv.structure} · ${inv.code_inv || inv.numero}`}>
        <label className="block text-sm font-semibold text-slate-700">{t("Votre prénom")}
          <input value={prenom} onChange={(e) => setPrenom(e.target.value)} placeholder="Awa" maxLength={30}
                 className="mt-1 w-full rounded-xl border px-4 py-3 text-lg" autoComplete="given-name" />
        </label>
        <p className="text-xs text-slate-500 mt-1">{t("Affiché au responsable à côté de vos saisies.")}</p>
        <p className="mt-4 text-sm font-semibold text-slate-700">{t("Lieu que vous comptez")}</p>
        <div className="mt-2 grid gap-2">
          {inv.lieux.map((l) => (
            <button key={l.id} type="button" onClick={() => setLieu(l.id)} aria-pressed={lieu === l.id}
                    className={`flex items-center gap-3 rounded-xl border px-4 py-3 text-left text-lg ${lieu === l.id ? "border-orange-500 bg-orange-50 font-semibold" : ""}`}>
              <MapPin className="h-5 w-5 text-orange-600" aria-hidden="true" />{l.nom}
            </button>
          ))}
        </div>
        <button type="button" disabled={prenom.trim().length < 2 || !lieu}
                onClick={() => { ecrire(cle("prenom"), prenom.trim()); ecrire(cle("lieu"), lieu); setPret(true); }}
                className="mt-6 flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-600 py-4 text-lg font-bold text-white disabled:opacity-40">
          <Check className="h-6 w-6" aria-hidden="true" />{t("Commencer le pointage")}
        </button>
      </Ecran>
    );
  }

  // Écran 2 : pointage
  const attente = file.length;
  return (
    <Ecran t={t} titre={`${inv.structure} · ${inv.code_inv || inv.numero}`}>
      {/* Bandeau : qui, où, réseau */}
      <div className="flex items-center justify-between gap-2 text-sm">
        <button type="button" onClick={() => setPret(false)} className="flex items-center gap-1 rounded-full bg-orange-100 px-3 py-1 font-semibold text-orange-800"
                title={t("Changer de lieu ou de prénom")} aria-label={t("Changer de lieu ou de prénom")}>
          <MapPin className="h-4 w-4" aria-hidden="true" />{nomLieu} · {prenom}
        </button>
        <span className={`flex items-center gap-1 rounded-full px-3 py-1 font-semibold ${enLigne ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-800"}`}>
          {enLigne ? <Wifi className="h-4 w-4" aria-hidden="true" /> : <CloudOff className="h-4 w-4" aria-hidden="true" />}
          {attente ? t("{n} en attente", { n: attente }) : enLigne ? t("Tout est envoyé") : t("Hors connexion")}
        </span>
      </div>
      {erreur && <p className="mt-2 rounded-lg bg-red-50 p-2 text-sm text-red-700">{erreur}</p>}

      {/* Produit reconnu : LE garde-fou (on voit tout de suite si le numéro est faux) */}
      <div className={`mt-4 rounded-2xl border-2 p-4 ${champs.chrono ? (produit ? "border-emerald-500 bg-emerald-50" : "border-red-500 bg-red-50") : "border-dashed border-slate-300"}`}>
        <div className="flex items-start gap-2">
          <PackageSearch className={`h-6 w-6 shrink-0 ${produit ? "text-emerald-700" : "text-slate-400"}`} aria-hidden="true" />
          <div className="min-w-0">
            <p className="text-lg font-bold leading-tight text-slate-900">{produit ? produit.l : champs.chrono ? t("Ligne {n} inconnue", { n: champs.chrono }) : t("Dites ou tapez le N° de ligne")}</p>
            {produit && <p className="text-sm text-slate-600">{produit.m} · N° {produit.c}</p>}
          </div>
        </div>
        <div className="mt-3 grid grid-cols-[1fr_1fr_1.3fr] gap-2">
          {[["chrono", t("Ligne"), "N°", "numeric"], ["qte", t("Quantité"), t("Qté"), "numeric"], ["peremption", t("Péremption"), t("MM/AA"), "text"]].map(([k, lib, ex, mode]) => (
            <label key={k} className="text-xs font-semibold text-slate-600">{lib}
              <input value={champs[k]} inputMode={mode} placeholder={ex} onChange={(e) => setChamps((c) => ({ ...c, [k]: e.target.value }))}
                     onKeyDown={(e) => { if (e.key === "Enter") valider(); }}
                     className={`mt-1 w-full rounded-lg border px-2 py-2 text-right text-xl font-bold tabular-nums placeholder:text-sm placeholder:font-normal placeholder:text-slate-300 ${k === "qte" ? "text-sky-700" : k === "peremption" ? "text-orange-700" : "text-slate-900"}`} />
            </label>
          ))}
        </div>
        {entendu && <p className="mt-2 text-xs italic text-slate-500">{t("Entendu : « {texte} »", { texte: entendu })}</p>}
      </div>

      {/* Actions : pictogrammes ronds (micro, suivant, annuler, voix) */}
      <div className="mt-5 flex items-end justify-around">
        <Rond onClick={annulerDerniere} couleur="bg-rose-100 text-rose-700" legende={t("Annuler la dernière")} Icone={Undo2} />
        <Rond onClick={basculerMicro} couleur={ecoute ? "bg-red-600 text-white animate-pulse" : "bg-sky-600 text-white"} grand
              legende={ecoute ? t("J'écoute… (toucher pour couper)") : t("Dicter")} Icone={Mic} />
        <Rond onClick={() => valider()} couleur="bg-emerald-600 text-white" grand legende={t("Suivant")} Icone={Check} />
        <Rond onClick={() => { setVoix(!voix); ecrire("pointage:voix", !voix); }} couleur="bg-slate-100 text-slate-700"
              legende={voix ? t("Voix active") : t("Voix coupée")} Icone={voix ? Volume2 : VolumeX} />
      </div>
      <p className="mt-3 flex items-center justify-center gap-1 text-center text-xs text-slate-500">
        <Keyboard className="h-3.5 w-3.5" aria-hidden="true" />{t("Dites « ligne 245, 12, mars 2027, suivant » — ou tapez puis touchez ✓. « Annule » efface la dernière.")}
      </p>

      {/* Dernières saisies de ce téléphone */}
      <ul className="mt-5 divide-y rounded-xl border bg-white text-sm">
        {historique.slice(0, 12).map((h) => (
          <li key={h.uid} className={`flex items-center justify-between gap-2 px-3 py-2 ${h.etat === "annulee" ? "line-through opacity-50" : ""}`}>
            <span className="min-w-0 truncate"><b className="text-sky-700">{h.chrono}</b> · {h.libelle}</span>
            <span className="shrink-0 tabular-nums">
              <b>{h.qte}</b>{h.peremption ? <span className="text-orange-700"> · {h.peremption}</span> : null}
              <span className={`ml-2 rounded px-1.5 text-xs ${{ attente: "bg-amber-100 text-amber-800", envoyee: "bg-emerald-100 text-emerald-800",
                doublon: "bg-orange-100 text-orange-800", refusee: "bg-red-100 text-red-800", annulee: "bg-slate-100" }[h.etat]}`}>
                {t({ attente: "en attente", envoyee: "reçue", doublon: "additionnée", refusee: "refusée", annulee: "annulée" }[h.etat])}
              </span>
            </span>
          </li>
        ))}
        {!historique.length && <li className="px-3 py-4 text-center text-slate-400">{t("Aucune saisie pour l'instant.")}</li>}
      </ul>
      <LienApp t={t} />
    </Ecran>
  );
}

/** Mise en page commune : carte centrée, adaptée au téléphone. */
function Ecran({ titre, children, t = (x) => x }) {
  return (
    <main className="min-h-[100dvh] bg-gradient-to-b from-sky-50 to-white px-4 py-5">
      <div className="mx-auto max-w-md">
        <h1 className="mb-4 text-center text-lg font-bold text-slate-800">{t("Pointage d'inventaire")}{titre ? <span className="block text-sm font-semibold text-sky-700">{titre}</span> : null}</h1>
        {children}
      </div>
    </main>
  );
}

/** Bouton rond à pictogramme seul (règle du 27/11/2026), avec légende courte, info-bulle et libellé d'accessibilité. */
function Rond({ onClick, couleur, legende, Icone, grand = false }) {
  return (
    <div className="flex w-20 flex-col items-center gap-1">
      <button type="button" onClick={onClick} title={legende} aria-label={legende}
              className={`flex items-center justify-center rounded-full shadow ${grand ? "h-20 w-20" : "h-14 w-14"} ${couleur}`}>
        <Icone className={grand ? "h-9 w-9" : "h-6 w-6"} aria-hidden="true" />
      </button>
      <span className="text-center text-[11px] leading-tight text-slate-600">{legende}</span>
    </div>
  );
}

/** Lien vers l'application Android (Loois mobile dans ShuyahStore) : pointage complet sans Internet (lot 499). */
function LienApp({ t }) {
  return (
    <a href={URL_APP_ANDROID} target="_blank" rel="noopener noreferrer"
       className="mt-5 flex items-center justify-center gap-2 rounded-xl border border-sky-200 bg-sky-50 px-3 py-2 text-sm font-semibold text-sky-800">
      <Smartphone className="h-4 w-4" aria-hidden="true" />{t("Télécharger l'application Android (pointage hors connexion)")}
    </a>
  );
}
