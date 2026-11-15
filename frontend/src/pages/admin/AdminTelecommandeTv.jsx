/*
 * Lot 412 — Télécommande vidéo (pensée pour le TÉLÉPHONE) : charger une vidéo, la lire en streaming sur une Smart TV appairée, la piloter.
 * Pour un développeur WinDev : cette page ne parle qu'à SAWALI. Chaque bouton envoie un « ordre » numéroté à la télé (/admin/tv/video/commande) ;
 * la page de la télé l'exécute dans les 2 secondes et renvoie sa position, relue ici toutes les 2 secondes (/admin/tv/video/etat/{écran}).
 * Les vidéos sont celles de la « Bibliothèque de médias » (stockage Cloudflare R2, 300 Mo au plus par fichier).
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Tv, Play, Pause, Square, Rewind, FastForward, RefreshCw, Upload, Loader2, Settings, Film, Wifi, WifiOff } from "lucide-react";
import { apiClient } from "@/lib/api";

const MO = (o) => (o ? `${(o / (1024 * 1024)).toFixed(1)} Mo` : "");
const MIN = (s) => { const n = Math.max(0, Math.floor(s || 0)); return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, "0")}`; };

export default function AdminTelecommandeTv() {
  const [ecrans, setEcrans] = useState([]);
  const [videos, setVideos] = useState([]);
  const [ecranId, setEcranId] = useState("");
  const [etat, setEtat] = useState(null);
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
      setEcrans(e.data.ecrans || []); setVideos(v.data.videos || []);
      setEcranId((cur) => cur || (e.data.ecrans?.[0]?.id ?? ""));
      if (annonce) toast.success(`${(e.data.ecrans || []).length} écran(s), ${(v.data.videos || []).length} vidéo(s).`);
    } catch (err) { toast.error(err?.response?.data?.detail || "Lecture impossible"); }
    finally { setChargement(false); }
  }, []);
  useEffect(() => { charger(false); }, [charger]);

  // L'état de la télé (position, lecture / pause) est relu toutes les 2 s tant que la page est ouverte
  useEffect(() => {
    if (!ecranId) return undefined;
    let actif = true;
    const lire = async () => {
      try { const { data } = await apiClient.get(`/admin/tv/video/etat/${ecranId}`); if (actif) setEtat(data.etat); } catch { /* la prochaine lecture réessaie */ }
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

  const ecran = ecrans.find((e) => e.id === ecranId);
  const lecture = etat?.lecture;
  const enLecture = lecture === "lecture";
  const courante = videos.find((v) => v.id === etat?.video_id);
  const pct = etat?.duree ? Math.min(100, Math.round((etat.position * 100) / etat.duree)) : 0;

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
                {e.en_ligne ? <Wifi className="h-4 w-4 text-emerald-600" /> : <WifiOff className="h-4 w-4 text-slate-400" />}
                {e.nom}<span className="text-xs font-normal">{e.en_ligne ? "en ligne" : "hors ligne"}</span>
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
          <div>
            <div className="h-3 overflow-hidden rounded-full bg-white"><div className="h-full bg-sky-600" style={{ width: `${pct}%` }} /></div>
            <div className="mt-1 flex justify-between text-xs tabular-nums text-slate-600"><span>{MIN(etat?.position)}</span><span>{MIN(etat?.duree)}</span></div>
          </div>
          {etat?.duree > 0 && (
            <input type="range" min={0} max={Math.floor(etat.duree)} defaultValue={Math.floor(etat.position || 0)} key={etat.video_id}
              onMouseUp={(e) => ordre({ action: "position", position: Number(e.target.value) }, "Déplacement")}
              onTouchEnd={(e) => ordre({ action: "position", position: Number(e.target.value) }, "Déplacement")}
              className="w-full" aria-label="Position dans la vidéo" />)}
          <div className="grid grid-cols-4 gap-2">
            <button type="button" onClick={() => ordre({ action: "reculer", delta: 10 }, "Retour de 10 s")} className="flex flex-col items-center gap-1 rounded-xl border border-slate-300 bg-white p-3 text-xs font-semibold"><Rewind className="h-6 w-6 text-slate-700" />−10 s</button>
            <button type="button" onClick={() => ordre({ action: enLecture ? "pause" : "reprendre" }, enLecture ? "Pause" : "Lecture")} className="flex flex-col items-center gap-1 rounded-xl border border-emerald-600 bg-emerald-600 p-3 text-xs font-semibold text-white">
              {enLecture ? <Pause className="h-6 w-6" /> : <Play className="h-6 w-6" />}{enLecture ? "Pause" : "Lecture"}</button>
            <button type="button" onClick={() => ordre({ action: "avancer", delta: 10 }, "Avance de 10 s")} className="flex flex-col items-center gap-1 rounded-xl border border-slate-300 bg-white p-3 text-xs font-semibold"><FastForward className="h-6 w-6 text-slate-700" />+10 s</button>
            <button type="button" onClick={() => ordre({ action: "stop" }, "Arrêt")} className="flex flex-col items-center gap-1 rounded-xl border border-red-300 bg-red-50 p-3 text-xs font-semibold text-red-700"><Square className="h-6 w-6" />Arrêter</button>
          </div>
        </section>)}

      {/* 3. Vidéos */}
      <section className="space-y-2 rounded-2xl border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-700">3. Vidéos</h2>
        {videos.length === 0 ? <p className="text-sm text-slate-500">Aucune vidéo : chargez-en une ci-dessous.</p> : (
          <ul className="divide-y divide-slate-100">
            {videos.map((v) => (
              <li key={v.id} className="flex items-center gap-3 py-2">
                <Film className="h-5 w-5 shrink-0 text-slate-400" />
                <div className="min-w-0 flex-1"><p className="truncate font-medium text-slate-800">{v.title}</p><p className="text-xs text-slate-500">{MO(v.size)} · {v.filename}</p></div>
                <button type="button" disabled={!ecranId} onClick={() => ordre({ action: "lire", video_id: v.id }, `Lecture de « ${v.title} »`)}
                  className="inline-flex items-center gap-1 rounded-lg bg-sky-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-40" data-testid={`lire-${v.id}`}><Play className="h-4 w-4" /> Lire sur la TV</button>
              </li>))}
          </ul>)}
      </section>

      {/* 4. Charger une vidéo */}
      <section className="space-y-2 rounded-2xl border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-700">4. Charger une vidéo</h2>
        <input value={titre} onChange={(e) => setTitre(e.target.value)} maxLength={200} placeholder="Titre de la vidéo" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" aria-label="Titre" />
        <input ref={entree} type="file" accept="video/mp4,video/webm,video/quicktime,video/x-matroska" onChange={(e) => setFichier(e.target.files?.[0] || null)} className="w-full text-sm" aria-label="Fichier vidéo" />
        <p className="text-xs text-slate-500">MP4 (H.264 + AAC) conseillé : il se lit sur toutes les télés. MKV, MOV et WebM dépendent du modèle. 300 Mo au plus.</p>
        {envoi !== null && <div className="h-3 overflow-hidden rounded-full bg-slate-100"><div className="h-full bg-emerald-600" style={{ width: `${envoi}%` }} /></div>}
        <button type="button" onClick={televerser} disabled={envoi !== null} className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" data-testid="televerser">
          {envoi !== null ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />} {envoi !== null ? `Envoi ${envoi} %` : "Charger la vidéo"}
        </button>
      </section>
    </div>
  );
}
