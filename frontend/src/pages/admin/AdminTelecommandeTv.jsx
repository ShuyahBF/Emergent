/*
 * Lot 412 — Télécommande vidéo (pensée pour le TÉLÉPHONE) : charger une vidéo, la lire en streaming sur une Smart TV appairée, la piloter.
 * Pour un développeur WinDev : cette page ne parle qu'à SAWALI. Chaque bouton envoie un « ordre » numéroté à la télé (/admin/tv/video/commande) ;
 * la page de la télé l'exécute dans les 2 secondes et renvoie sa position, relue ici toutes les 2 secondes (/admin/tv/video/etat/{écran}).
 * Les vidéos sont celles de la « Bibliothèque de médias » (stockage Cloudflare R2, 300 Mo au plus par fichier).
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Tv, Play, Pause, Square, Rewind, FastForward, RefreshCw, Upload, Loader2, Settings, Film, Wifi, WifiOff, Trash2, CheckSquare, HardDrive } from "lucide-react";
import { apiClient } from "@/lib/api";

// Taille lisible : « 120 Mo » jusqu'à 1 Go, puis « 1,5 Go » (même règle que le serveur)
const TAILLE = (o) => { const mo = (o || 0) / (1024 * 1024); if (mo < 1024) return `${mo >= 10 || Number.isInteger(mo) ? Math.round(mo) : mo.toFixed(1).replace(".", ",")} Mo`; const go = mo / 1024; return `${Number.isInteger(go) ? go : go.toFixed(1).replace(".", ",")} Go`; };
const MIN = (s) => { const n = Math.max(0, Math.floor(s || 0)); return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, "0")}`; };

export default function AdminTelecommandeTv() {
  const [ecrans, setEcrans] = useState([]);
  const [videos, setVideos] = useState([]);
  const [quota, setQuota] = useState(null);                       // { utilise, max, libelle } : espace des vidéos « 120 Mo / 2 Go »
  const [choix, setChoix] = useState([]);                         // vidéos cochées pour la suppression
  const [suppression, setSuppression] = useState(false);
  const [ecranId, setEcranId] = useState("");
  const [etat, setEtat] = useState(null);
  const [enLigne, setEnLigne] = useState(null);                    // état « en ligne » relu toutes les 2 s (null : pas encore lu)
  const [glisse, setGlisse] = useState(null);                      // position choisie en faisant glisser le curseur (null : le curseur suit la lecture)
  const [chargement, setChargement] = useState(false);
  const [titre, setTitre] = useState("");
  const [fichier, setFichier] = useState(null);
  const [envoi, setEnvoi] = useState(null);                        // pourcentage d'envoi, ou null
  const entree = useRef(null);

  // Écrans (avec « Vidéos ») et vidéos de la bibliothèque ; règle 17 : toast « en cours » puis résultat
  const charger = useCallback(async (annonce = true) => {
    setChargement(true);
    if (annonce) toast.info("Actualisation en cours…");
    try {
      const [e, v] = await Promise.all([apiClient.get("/admin/tv/video/ecrans"), apiClient.get("/admin/tv/video/videos")]);
      setEcrans(e.data.ecrans || []); setVideos(v.data.videos || []); setQuota(v.data.quota || null);
      setChoix((cur) => cur.filter((id) => (v.data.videos || []).some((x) => x.id === id)));
      setEcranId((cur) => cur || (e.data.ecrans?.[0]?.id ?? ""));
      if (annonce) toast.success(`${(e.data.ecrans || []).length} écran(s), ${(v.data.videos || []).length} vidéo(s).`);
    } catch (err) { toast.error(err?.response?.data?.detail || "Lecture impossible"); }
    finally { setChargement(false); }
  }, []);
  useEffect(() => { charger(false); }, [charger]);

  // L'état de la télé (position, lecture / pause) est relu toutes les 2 s tant que la page est ouverte
  useEffect(() => {
    if (!ecranId) return undefined;
    setEnLigne(null); setEtat(null); setGlisse(null);               // on change d'écran : rien de l'écran précédent ne reste affiché
    let actif = true;
    const lire = async () => {
      try { const { data } = await apiClient.get(`/admin/tv/video/etat/${ecranId}`); if (actif) { setEtat(data.etat); setEnLigne(data.en_ligne); } } catch { /* la prochaine lecture réessaie */ }
    };
    lire(); const t = setInterval(lire, 2000);
    return () => { actif = false; clearInterval(t); };
  }, [ecranId]);

  const ordre = async (corps, message) => {
    if (!ecranId) { toast.error("Choisissez d'abord un écran."); return; }
    toast.info(`${message} en cours…`);
    try { await apiClient.post("/admin/tv/video/commande", { ecran_id: ecranId, ...corps }); toast.success(`${message} : ordre envoyé à la télé.`); }
    catch (err) { toast.error(err?.response?.data?.detail || "Ordre non envoyé"); }
  };

  // Chargement d'une vidéo dans la bibliothèque de médias (même route que l'écran « Bibliothèque de médias »)
  const televerser = async () => {
    if (!fichier || !titre.trim()) { toast.error("Indiquez un titre et choisissez un fichier vidéo."); return; }
    if (fichier.size > 300 * 1024 * 1024) { toast.error("Fichier trop volumineux : 300 Mo au plus."); return; }
    if (quota && quota.utilise + fichier.size > quota.max) { toast.error(`Espace insuffisant : ${quota.libelle} utilisés, cette vidéo fait ${TAILLE(fichier.size)}. Supprimez des vidéos.`); return; }
    const f = new FormData();
    f.append("file", fichier); f.append("title", titre.trim()); f.append("kind", "video"); f.append("public", "false");
    setEnvoi(0); toast.info("Chargement de la vidéo en cours… ne fermez pas la page.");
    try {
      await apiClient.post("/admin/media-library", f, { timeout: 0, onUploadProgress: (p) => setEnvoi(p.total ? Math.round((p.loaded * 100) / p.total) : 0) });
      toast.success(`Vidéo « ${titre.trim()} » chargée.`);
      setTitre(""); setFichier(null); if (entree.current) entree.current.value = "";
      await charger(false);
    } catch (err) { toast.error(err?.response?.data?.detail || "Chargement impossible"); }
    finally { setEnvoi(null); }
  };

  // Suppression des vidéos cochées : confirmation, puis toast « en cours » et résultat (règle 17)
  const basculer = (id) => setChoix((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]));
  const supprimer = async () => {
    if (!choix.length) return;
    const noms = videos.filter((v) => choix.includes(v.id)).map((v) => `« ${v.title} »`).join(", ");
    if (!window.confirm(`Supprimer définitivement ${choix.length} vidéo(s) : ${noms} ?\nLes fichiers sont effacés du stockage, l'espace est rendu.`)) return;
    setSuppression(true); toast.info(`Suppression de ${choix.length} vidéo(s) en cours…`);
    try {
      const { data } = await apiClient.post("/admin/tv/video/supprimer", { ids: choix });
      if (data.echecs?.length) toast.error(`${data.supprimees.length} supprimée(s), ${data.echecs.length} échec(s) : ${data.echecs.map((e) => e.raison).join(" ; ")}`);
      else toast.success(`${data.supprimees.length} vidéo(s) supprimée(s). Espace : ${data.quota.libelle}.`);
      setChoix([]); await charger(false);
    } catch (err) { toast.error(err?.response?.data?.detail || "Suppression impossible"); }
    finally { setSuppression(false); }
  };
  const pctQuota = quota ? Math.min(100, Math.round((quota.utilise * 100) / quota.max)) : 0;
  const couleurQuota = pctQuota >= 100 ? "bg-red-600" : pctQuota >= 80 ? "bg-amber-500" : "bg-emerald-600";
  const ecran = ecrans.find((e) => e.id === ecranId);
  const lecture = etat?.lecture;
  const enLecture = lecture === "lecture";
  const courante = videos.find((v) => v.id === etat?.video_id);

  return (
    <div className="mx-auto max-w-3xl space-y-5 p-4" data-testid="telecommande-tv">
      <div className="flex items-center justify-between gap-2">
        <h1 className="flex items-center gap-2 text-xl font-bold text-slate-800"><Tv className="h-6 w-6 text-sky-600" /> Télécommande vidéo</h1>
        <button type="button" onClick={() => charger(true)} disabled={chargement} className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium">
          {chargement ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />} Actualiser
        </button>
      </div>

      {/* 1. Écran */}
      <section className="space-y-2 rounded-2xl border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-700">1. Écran de télévision</h2>
        {ecrans.length === 0 ? (
          <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
            Aucun écran n'a le contenu « Vidéos ». Ouvrez la télé sur la page <b>/tv</b>, appairez-la, puis cochez « Vidéos » dans{" "}
            <Link to="/admin/settings" className="font-semibold underline"><Settings className="inline h-4 w-4" /> Paramètres → Écrans TV</Link>.
          </p>
        ) : (
          <div className="flex flex-wrap gap-2" role="group" aria-label="Écrans">
            {ecrans.map((e) => (
              <button key={e.id} type="button" onClick={() => setEcranId(e.id)} data-testid={`ecran-${e.id}`}
                className={`inline-flex items-center gap-2 rounded-xl border-2 px-3 py-2 text-sm font-semibold ${e.id === ecranId ? "border-sky-600 bg-sky-50 text-sky-900" : "border-slate-200 bg-white text-slate-700"}`}>
                {(e.id === ecranId && enLigne !== null ? enLigne : e.en_ligne) ? <Wifi className="h-4 w-4 text-emerald-600" /> : <WifiOff className="h-4 w-4 text-slate-400" />}
                {e.nom}<span className="text-xs font-normal">{(e.id === ecranId && enLigne !== null ? enLigne : e.en_ligne) ? "en ligne" : "hors ligne"}</span>
              </button>))}
          </div>)}
      </section>

      {/* 2. Télécommande */}
      {ecran && (
        <section className="space-y-3 rounded-2xl border-2 border-sky-300 bg-sky-50 p-4" data-testid="panneau-lecture">
          <h2 className="text-sm font-semibold text-sky-900">2. Lecture sur « {ecran.nom} »</h2>
          <p className="text-lg font-bold text-slate-800">{lecture && lecture !== "arret" ? (courante?.title || "Vidéo en cours") : "Rien en lecture"}
            <span className="ml-2 text-sm font-normal text-slate-600">{lecture === "pause" ? "⏸ en pause" : enLecture ? "▶ en lecture" : ""}</span></p>
          {etat?.erreur && <p className="rounded-lg bg-red-50 p-2 text-sm text-red-700">⚠ {etat.erreur}</p>}
          {/* UNE seule jauge : elle avance avec la lecture ; on peut la faire glisser pour aller à un autre moment (l'ordre part au relâchement) */}
          <div>
            <input type="range" min={0} max={Math.max(1, Math.floor(etat?.duree || 0))} value={Math.floor(glisse ?? etat?.position ?? 0)} disabled={!(etat?.duree > 0)}
              onChange={(e) => setGlisse(Number(e.target.value))}
              onPointerUp={async (e) => { const v = Number(e.target.value); await ordre({ action: "position", position: v }, "Déplacement"); setGlisse(null); }}
              className="h-3 w-full accent-sky-600" aria-label="Position dans la vidéo" data-testid="jauge-position" />
            <div className="mt-1 flex justify-between text-xs tabular-nums text-slate-600"><span>{MIN(glisse ?? etat?.position)}</span><span>{MIN(etat?.duree)}</span></div>
          </div>
          <div className="grid grid-cols-4 gap-2">
            <button type="button" onClick={() => ordre({ action: "reculer", delta: 10 }, "Retour de 10 s")} className="flex flex-col items-center gap-1 rounded-xl border border-slate-300 bg-white p-3 text-xs font-semibold"><Rewind className="h-6 w-6 text-slate-700" />−10 s</button>
            <button type="button" onClick={() => ordre({ action: enLecture ? "pause" : "reprendre" }, enLecture ? "Pause" : "Lecture")} className="flex flex-col items-center gap-1 rounded-xl border border-emerald-600 bg-emerald-600 p-3 text-xs font-semibold text-white">
              {enLecture ? <Pause className="h-6 w-6" /> : <Play className="h-6 w-6" />}{enLecture ? "Pause" : "Lecture"}</button>
            <button type="button" onClick={() => ordre({ action: "avancer", delta: 10 }, "Avance de 10 s")} className="flex flex-col items-center gap-1 rounded-xl border border-slate-300 bg-white p-3 text-xs font-semibold"><FastForward className="h-6 w-6 text-slate-700" />+10 s</button>
            <button type="button" onClick={() => ordre({ action: "stop" }, "Arrêt")} className="flex flex-col items-center gap-1 rounded-xl border border-red-300 bg-red-50 p-3 text-xs font-semibold text-red-700"><Square className="h-6 w-6" />Arrêter</button>
          </div>
        </section>)}

      {/* 3. Vidéos : espace utilisé / maximum, cases à cocher et suppression */}
      <section className="space-y-2 rounded-2xl border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-slate-700">3. Vidéos</h2>
          {quota && <span className="inline-flex items-center gap-1 text-sm font-bold tabular-nums text-slate-800" data-testid="quota-videos"><HardDrive className="h-4 w-4 text-slate-500" /> {quota.libelle}</span>}
        </div>
        {quota && <div className="h-2 overflow-hidden rounded-full bg-slate-100" role="progressbar" aria-valuenow={pctQuota} aria-valuemin={0} aria-valuemax={100} aria-label="Espace des vidéos"><div className={`h-full ${couleurQuota}`} style={{ width: `${pctQuota}%` }} /></div>}
        {quota && pctQuota >= 80 && <p className={`text-xs ${pctQuota >= 100 ? "text-red-700" : "text-amber-700"}`}>{pctQuota >= 100 ? "⛔ Espace plein : supprimez des vidéos pour en charger d'autres." : "⚠ Espace presque plein."}</p>}
        {videos.length === 0 ? <p className="text-sm text-slate-500">Aucune vidéo : chargez-en une ci-dessous.</p> : (<>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={() => setChoix(choix.length === videos.length ? [] : videos.map((v) => v.id))} className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700">
              <CheckSquare className="h-4 w-4" /> {choix.length === videos.length ? "Tout désélectionner" : "Tout sélectionner"}</button>
            <button type="button" onClick={supprimer} disabled={!choix.length || suppression} data-testid="supprimer-videos"
              className="inline-flex items-center gap-1 rounded-lg bg-red-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40">
              {suppression ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />} Supprimer{choix.length ? ` (${choix.length})` : ""}</button>
          </div>
          <ul className="divide-y divide-slate-100">
            {videos.map((v) => (
              <li key={v.id} className={`flex items-center gap-3 py-2 ${choix.includes(v.id) ? "bg-red-50" : ""}`}>
                <input type="checkbox" checked={choix.includes(v.id)} onChange={() => basculer(v.id)} className="h-5 w-5 shrink-0 accent-red-600" aria-label={`Sélectionner ${v.title}`} data-testid={`choix-${v.id}`} />
                <Film className="h-5 w-5 shrink-0 text-slate-400" />
                <div className="min-w-0 flex-1"><p className="truncate font-medium text-slate-800">{v.title}</p><p className="text-xs text-slate-500">{TAILLE(v.size)} · {v.filename}</p></div>
                <button type="button" disabled={!ecranId} onClick={() => ordre({ action: "lire", video_id: v.id }, `Lecture de « ${v.title} »`)}
                  className="inline-flex items-center gap-1 rounded-lg bg-sky-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-40" data-testid={`lire-${v.id}`}><Play className="h-4 w-4" /> Lire sur la TV</button>
              </li>))}
          </ul></>)}
      </section>

      {/* 4. Charger une vidéo */}
      <section className="space-y-2 rounded-2xl border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-700">4. Charger une vidéo</h2>
        <input value={titre} onChange={(e) => setTitre(e.target.value)} maxLength={200} placeholder="Titre de la vidéo" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" aria-label="Titre" />
        <input ref={entree} type="file" accept="video/mp4,video/webm,video/quicktime,video/x-matroska" onChange={(e) => setFichier(e.target.files?.[0] || null)} className="w-full text-sm" aria-label="Fichier vidéo" />
        {quota && <p className="text-xs font-semibold tabular-nums text-slate-700">Espace : {quota.libelle}{fichier ? ` · cette vidéo : ${TAILLE(fichier.size)}` : ""}</p>}
        <p className="text-xs text-slate-500">MP4 (H.264 + AAC) conseillé : il se lit sur toutes les télés. MKV, MOV et WebM dépendent du modèle. 300 Mo au plus.</p>
        {envoi !== null && <div className="h-3 overflow-hidden rounded-full bg-slate-100"><div className="h-full bg-emerald-600" style={{ width: `${envoi}%` }} /></div>}
        <button type="button" onClick={televerser} disabled={envoi !== null || (quota && fichier && quota.utilise + fichier.size > quota.max)} className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" data-testid="televerser">
          {envoi !== null ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />} {envoi !== null ? `Envoi ${envoi} %` : "Charger la vidéo"}
        </button>
      </section>
    </div>
  );
}
