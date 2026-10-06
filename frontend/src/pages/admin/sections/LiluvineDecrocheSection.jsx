// LiluvineDecrocheSection.jsx — Lot 69 : « Liluvine décroche les appels WhatsApp ».
//
// Quand un client appelle un numéro WhatsApp de SAWALI, Liluvine peut décrocher elle-même et
// lui répondre à voix haute avec son prompt système (le même que pour les messages WhatsApp) :
//   • modes : toujours / si personne ne décroche après N secondes / hors heures d'ouverture ;
//   • un humain qui décroche dans le portail a toujours priorité (jamais deux décrochés) ;
//   • transcription, résumé et coût estimé de chaque appel dans le journal des appels ;
//   • « transmettre à un humain » : tâche de rappel + message au propriétaire.
// Ce bloc permet : réglages, état du moteur et des clés, simulation écrite d'une conversation,
// derniers appels pris par Liluvine.
// Lot 69.2 : « Voix et accent » — voix OpenAI + consigne d'accent (gpt-4o-mini-tts), choix d'une voix
// ElevenLabs (compte ou bibliothèque de voix françaises à accent africain), « Écouter un essai ».
import React, { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import TranscriptionAppelLiluvine from "@/components/TranscriptionAppelLiluvine";

// Petite jauge circulaire transparente (attente)
const Jauge = () => (
  <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-violet-300 border-t-transparent align-middle" />
);

// Jours de la semaine (1 = lundi … 7 = dimanche)
const JOURS = [[1, "Lun"], [2, "Mar"], [3, "Mer"], [4, "Jeu"], [5, "Ven"], [6, "Sam"], [7, "Dim"]];

// Pastille d'état (vert = prêt, rouge = manquant)
const Pastille = ({ ok, oui, non, titre }) => (
  <span title={titre || ""} className={`rounded-full px-2 py-0.5 ${ok ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800"}`}>
    {ok ? oui : non}
  </span>
);

export default function LiluvineDecrocheSection() {
  const [donnees, setDonnees] = useState(null);   // réponse de GET /admin/liluvine-decroche
  const [form, setForm] = useState(null);         // réglages modifiables
  const [occupe, setOccupe] = useState("");       // action en cours
  const [simu, setSimu] = useState({ texte: "", historique: [] });   // simulation écrite
  const [deplie, setDeplie] = useState(null);     // dernier appel dont la transcription est ouverte
  // Lot 69.2 — choix d'une voix ElevenLabs (liste affichée) et lecteur de l'essai de voix
  const [choixEl, setChoixEl] = useState(null);   // { source, voix: [...] } ou null (fermé)
  const [accentEl, setAccentEl] = useState("african");
  const [essaiUrl, setEssaiUrl] = useState("");   // adresse locale (blob) du dernier essai
  const essaiRef = useRef(null);

  // Lecture des réglages et de l'état du moteur
  const charger = useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/liluvine-decroche");
      const d = r.data || {};
      const e = d.effectif || {};
      const s = d.reglages || {};
      setDonnees(d);
      setForm({
        liluvine_decroche_actif: !!e.actif,
        liluvine_decroche_lignes: e.lignes || [],
        liluvine_decroche_mode: e.mode || "delai",
        liluvine_decroche_delai_s: e.delai_s || 20,
        liluvine_decroche_ouverture_debut: e.ouverture_debut || "08:00",
        liluvine_decroche_ouverture_fin: e.ouverture_fin || "18:00",
        liluvine_decroche_jours: e.jours || [1, 2, 3, 4, 5, 6],
        liluvine_decroche_accueil: e.accueil || "",
        liluvine_decroche_duree_max_min: Math.round((e.duree_max_s || 300) / 60),
        liluvine_decroche_silence_s: e.silence_s || 20,
        liluvine_decroche_voix: e.voix || "auto",
        liluvine_decroche_voix_elevenlabs: s.liluvine_decroche_voix_elevenlabs || "",
        liluvine_decroche_transfert_actif: e.transfert_actif !== false,
        liluvine_decroche_resume_proprio: e.resume_proprio !== false,
        liluvine_decroche_max_simultanes: e.max_simultanes || 2,
        liluvine_decroche_coupure_parole: e.coupure_parole !== false,
        liluvine_decroche_stt_modele: e.stt_modele || "gpt-4o-mini-transcribe",
        liluvine_decroche_exclus: s.liluvine_decroche_exclus || "",
        // Lot 69.2 — profil de voix (aussi utilisé par « Liluvine appelle le propriétaire »)
        liluvine_decroche_voix_openai: e.voix_openai || "nova",
        liluvine_decroche_modele_openai: e.modele_openai || "gpt-4o-mini-tts",
        liluvine_decroche_accent: s.liluvine_decroche_accent || e.accent || "",
        liluvine_decroche_modele_elevenlabs: e.modele_elevenlabs || "eleven_flash_v2_5",
      });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Réglages indisponibles");
    }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  if (!form) return <p className="text-xs text-slate-500"><Jauge /> Patientez…</p>;
  const maj = (cle, valeur) => setForm((f) => ({ ...f, [cle]: valeur }));

  // Lance une action longue avec le toast « Patientez… »
  const action = async (nom, fn, succes) => {
    setOccupe(nom);
    const t = toast.loading("Patientez…");
    try {
      const r = await fn();
      toast.success(succes(r), { id: t });
      return r;
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Action impossible", { id: t });
      return null;
    } finally {
      setOccupe("");
    }
  };

  // Coche / décoche une valeur dans une liste (lignes, jours)
  const basculer = (cle, valeur) => {
    const liste = form[cle] || [];
    maj(cle, liste.includes(valeur) ? liste.filter((v) => v !== valeur) : [...liste, valeur]);
  };

  // Enregistrement des réglages
  const enregistrer = () => action("enregistrer", async () => {
    await apiClient.put("/admin/liluvine-decroche", {
      ...form,
      liluvine_decroche_jours: (form.liluvine_decroche_jours || []).join(","),
      liluvine_decroche_delai_s: Math.min(45, Math.max(5, Number(form.liluvine_decroche_delai_s) || 20)),
      liluvine_decroche_duree_max_min: Math.min(30, Math.max(1, Number(form.liluvine_decroche_duree_max_min) || 5)),
      liluvine_decroche_silence_s: Math.min(120, Math.max(5, Number(form.liluvine_decroche_silence_s) || 20)),
      liluvine_decroche_max_simultanes: Math.min(5, Math.max(1, Number(form.liluvine_decroche_max_simultanes) || 2)),
    });
    await charger();
  }, () => "Réglages enregistrés");

  // Simulation écrite : ce que Liluvine répondrait au téléphone
  const simuler = async () => {
    if (!simu.texte.trim()) { toast.error("Écrivez ce que dit l'appelant"); return; }
    const r = await action("simuler", () => apiClient.post("/admin/liluvine-decroche/simuler",
      { texte: simu.texte, historique: simu.historique }), () => "Réponse de Liluvine reçue");
    if (r) {
      setSimu({ texte: "", historique: r.data.historique || [], fin: r.data.fin });
    }
  };

  // Lot 69.2 — liste des voix ElevenLabs : compte, ou bibliothèque (voix françaises, accent choisi)
  const listerVoixEl = async (source) => {
    const r = await action("voix-el", () => apiClient.get("/admin/liluvine-decroche/voix-elevenlabs",
      { params: { source, accent: accentEl } }), (x) => `${(x.data.voix || []).length} voix trouvée(s)`);
    if (r) setChoixEl({ source, voix: r.data.voix || [] });
  };

  // Choisit une voix : celle du compte directement ; celle de la bibliothèque est d'abord ajoutée au compte
  const choisirVoixEl = async (v) => {
    let id = v.voice_id;
    if (v.source === "bibliotheque") {
      const r = await action("voix-el", () => apiClient.post("/admin/liluvine-decroche/voix-elevenlabs/ajouter",
        { proprietaire_id: v.proprietaire_id, voice_id: v.voice_id, nom: `Liluvine — ${v.nom || "voix"}` }),
        () => "Voix ajoutée à votre compte ElevenLabs");
      if (!r) return;
      id = r.data.voice_id || id;
    }
    setForm((f) => ({ ...f, liluvine_decroche_voix_elevenlabs: id, liluvine_decroche_voix: "elevenlabs" }));
    toast.success(`Voix « ${v.nom} » choisie : cliquez sur « Écouter un essai » puis « Enregistrer »`);
  };

  // « Écouter un essai » : l'accueil prononcé avec la voix et l'accent du formulaire (même non enregistrés)
  const ecouterEssai = async () => {
    const r = await action("essai", () => apiClient.post("/admin/liluvine-decroche/essai-voix", {
      liluvine_decroche_voix: form.liluvine_decroche_voix,
      liluvine_decroche_voix_elevenlabs: form.liluvine_decroche_voix_elevenlabs,
      liluvine_decroche_voix_openai: form.liluvine_decroche_voix_openai,
      liluvine_decroche_modele_openai: form.liluvine_decroche_modele_openai,
      liluvine_decroche_accent: form.liluvine_decroche_accent,
      liluvine_decroche_modele_elevenlabs: form.liluvine_decroche_modele_elevenlabs,
      texte: form.liluvine_decroche_accueil,
    }, { responseType: "blob" }), () => "Essai prêt : écoute en cours");
    if (!r) return;
    if (essaiUrl) URL.revokeObjectURL(essaiUrl);
    const url = URL.createObjectURL(r.data);
    setEssaiUrl(url);
    setTimeout(() => { try { essaiRef.current?.play(); } catch (_) { /* lecture manuelle */ } }, 50);
  };

  const choixVoix = donnees?.choix_voix || {};
  const moteur = donnees?.moteur || {};
  const effectif = donnees?.effectif || {};
  const champ = "mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm";

  return (
    <div className="space-y-3" data-testid="liluvine-decroche">
      <p className="text-xs text-slate-600">
        Quand un client appelle un numéro WhatsApp de SAWALI, Liluvine peut <strong>décrocher elle-même</strong> et lui répondre
        à voix haute avec <strong>son prompt système</strong> (le même que pour les messages WhatsApp, avec sa base de connaissances).
        Un collègue qui décroche dans le portail a toujours priorité : jamais deux réponses au même appel. Chaque appel est
        transcrit et résumé dans le journal des appels.
      </p>

      {/* État du moteur et des clés (présence seulement, jamais la valeur) */}
      <div className="flex flex-wrap gap-2 text-xs">
        <span className={`rounded-full px-2 py-0.5 ${effectif.actif ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-700"}`}>
          {effectif.actif ? "Décroché automatique actif" : "Décroché automatique désactivé"}
        </span>
        <Pastille ok={moteur.disponible} oui="Moteur d'appel prêt" non="Moteur d'appel absent" titre={moteur.raison} />
        <Pastille ok={moteur.transcription} oui="Écoute (OpenAI) prête" non="Écoute impossible : OPENAI_API_KEY manquante" />
        <Pastille ok={moteur.ia} oui="IA prête" non="IA impossible : ANTHROPIC_API_KEY manquante" />
        {moteur.voix?.length > 0 && <span className="rounded-full bg-violet-100 px-2 py-0.5 text-violet-800">Voix : {moteur.voix.join(" → ")}</span>}
        <span className="rounded-full bg-sky-100 px-2 py-0.5 text-sky-800">Appels en cours : {moteur.en_cours || 0}</span>
      </div>

      <label className="inline-flex items-center gap-2 text-sm font-semibold">
        <input type="checkbox" checked={form.liluvine_decroche_actif} onChange={(e) => maj("liluvine_decroche_actif", e.target.checked)} />
        Liluvine décroche les appels WhatsApp
      </label>

      {/* Mode de décroché */}
      <div className="rounded-lg bg-white/70 p-2 ring-1 ring-slate-200 text-xs space-y-1.5">
        <p className="font-semibold text-slate-700">Quand Liluvine décroche-t-elle ?</p>
        <label className="flex items-center gap-2">
          <input type="radio" name="mode-decroche" checked={form.liluvine_decroche_mode === "toujours"} onChange={() => maj("liluvine_decroche_mode", "toujours")} />
          Toujours (tout de suite)
        </label>
        <label className="flex flex-wrap items-center gap-2">
          <input type="radio" name="mode-decroche" checked={form.liluvine_decroche_mode === "delai"} onChange={() => maj("liluvine_decroche_mode", "delai")} />
          Si personne ne décroche dans le portail après
          <input type="number" min="5" max="45" value={form.liluvine_decroche_delai_s} onChange={(e) => maj("liluvine_decroche_delai_s", e.target.value)}
            className="w-16 rounded border border-slate-300 px-1 py-0.5" /> secondes
        </label>
        <label className="flex flex-wrap items-center gap-2">
          <input type="radio" name="mode-decroche" checked={form.liluvine_decroche_mode === "hors_heures"} onChange={() => maj("liluvine_decroche_mode", "hors_heures")} />
          Hors heures d'ouverture — ouvert de
          <input type="time" value={form.liluvine_decroche_ouverture_debut} onChange={(e) => maj("liluvine_decroche_ouverture_debut", e.target.value)}
            className="rounded border border-slate-300 px-1 py-0.5" /> à
          <input type="time" value={form.liluvine_decroche_ouverture_fin} onChange={(e) => maj("liluvine_decroche_ouverture_fin", e.target.value)}
            className="rounded border border-slate-300 px-1 py-0.5" />
        </label>
        {form.liluvine_decroche_mode === "hors_heures" && (
          <div className="ml-6 flex flex-wrap gap-2">
            {JOURS.map(([n, nom]) => (
              <label key={n} className="inline-flex items-center gap-1">
                <input type="checkbox" checked={(form.liluvine_decroche_jours || []).includes(n)} onChange={() => basculer("liluvine_decroche_jours", n)} />
                {nom}
              </label>
            ))}
          </div>
        )}
      </div>

      {/* Lignes concernées (lot 59) */}
      <div className="text-xs">
        <p className="font-semibold text-slate-700">Lignes concernées (aucune cochée = toutes)</p>
        <div className="mt-1 flex flex-wrap gap-3">
          {(donnees?.lignes || []).map((l) => (
            <label key={l.cle} className="inline-flex items-center gap-1">
              <input type="checkbox" checked={(form.liluvine_decroche_lignes || []).includes(l.cle)} onChange={() => basculer("liluvine_decroche_lignes", l.cle)} />
              {l.libelle}{l.telephone ? ` — ${l.telephone}` : ""}
            </label>
          ))}
        </div>
      </div>

      <label className="block text-xs">
        <span className="font-semibold text-slate-700">Message d'accueil</span>
        <textarea rows={2} value={form.liluvine_decroche_accueil} onChange={(e) => maj("liluvine_decroche_accueil", e.target.value)} className={champ} />
      </label>

      <div className="grid gap-3 sm:grid-cols-3 text-xs">
        <label className="block">
          <span className="font-semibold text-slate-700">Durée maximale d'un appel (minutes)</span>
          <input type="number" min="1" max="30" value={form.liluvine_decroche_duree_max_min} onChange={(e) => maj("liluvine_decroche_duree_max_min", e.target.value)} className={champ} />
        </label>
        <label className="block">
          <span className="font-semibold text-slate-700">Raccrocher après … s sans parole</span>
          <input type="number" min="5" max="120" value={form.liluvine_decroche_silence_s} onChange={(e) => maj("liluvine_decroche_silence_s", e.target.value)} className={champ} />
        </label>
        <label className="block">
          <span className="font-semibold text-slate-700">Appels simultanés au plus</span>
          <input type="number" min="1" max="5" value={form.liluvine_decroche_max_simultanes} onChange={(e) => maj("liluvine_decroche_max_simultanes", e.target.value)} className={champ} />
        </label>
      </div>

      <div className="flex flex-col gap-1 text-xs">
        <label className="inline-flex items-center gap-2">
          <input type="checkbox" checked={form.liluvine_decroche_transfert_actif} onChange={(e) => maj("liluvine_decroche_transfert_actif", e.target.checked)} />
          Transmettre à un humain si l'appelant le demande (tâche de rappel + message au propriétaire)
        </label>
        <label className="inline-flex items-center gap-2">
          <input type="checkbox" checked={form.liluvine_decroche_resume_proprio} onChange={(e) => maj("liluvine_decroche_resume_proprio", e.target.checked)} />
          Envoyer le résumé de chaque appel au propriétaire sur WhatsApp (numéro du bloc « Liluvine appelle le propriétaire »)
        </label>
        <label className="inline-flex items-center gap-2">
          <input type="checkbox" checked={form.liluvine_decroche_coupure_parole} onChange={(e) => maj("liluvine_decroche_coupure_parole", e.target.checked)} />
          L'appelant peut couper la parole à Liluvine (elle se tait dès qu'il parle)
        </label>
      </div>

      <details className="text-xs">
        <summary className="cursor-pointer font-semibold text-slate-700">Réglages avancés (voix, écoute, exclusions)</summary>
        <div className="mt-2 grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="font-semibold text-slate-700">Voix de Liluvine</span>
            <select value={form.liluvine_decroche_voix} onChange={(e) => maj("liluvine_decroche_voix", e.target.value)} className={champ}>
              <option value="auto">Automatique (OpenAI → ElevenLabs → Google)</option>
              <option value="openai">OpenAI (voix et accent ci-dessous)</option>
              <option value="elevenlabs">ElevenLabs (voix ci-contre)</option>
              <option value="google">Google (sans clé)</option>
            </select>
          </label>
          <label className="block">
            <span className="font-semibold text-slate-700">Identifiant de voix ElevenLabs (facultatif)</span>
            <input value={form.liluvine_decroche_voix_elevenlabs} onChange={(e) => maj("liluvine_decroche_voix_elevenlabs", e.target.value)} className={champ} />
          </label>
          <label className="block">
            <span className="font-semibold text-slate-700">Écoute (transcription OpenAI)</span>
            <select value={form.liluvine_decroche_stt_modele} onChange={(e) => maj("liluvine_decroche_stt_modele", e.target.value)} className={champ}>
              <option value="gpt-4o-mini-transcribe">gpt-4o-mini-transcribe (rapide, économique)</option>
              <option value="whisper-1">whisper-1</option>
            </select>
          </label>
          <label className="block">
            <span className="font-semibold text-slate-700">Numéros auxquels Liluvine ne répond jamais</span>
            <input value={form.liluvine_decroche_exclus} onChange={(e) => maj("liluvine_decroche_exclus", e.target.value)}
              placeholder="+226 70 00 00 00, …" className={champ} />
          </label>
        </div>
        {/* Lot 69.2 — Voix et accent (communs aux appels « Liluvine décroche » et « Liluvine appelle le propriétaire ») */}
        <div className="mt-3 space-y-2 rounded-lg bg-violet-50/60 p-2 ring-1 ring-violet-100" data-testid="voix-accent">
          <p className="font-semibold text-violet-900">🎙️ Voix et accent de Liluvine</p>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="block">
              <span className="font-semibold text-slate-700">Voix OpenAI</span>
              <select value={form.liluvine_decroche_voix_openai} onChange={(e) => maj("liluvine_decroche_voix_openai", e.target.value)} className={champ}>
                {(choixVoix.openai || ["nova"]).map((v) => <option key={v} value={v}>{v}</option>)}
              </select>
            </label>
            <label className="block">
              <span className="font-semibold text-slate-700">Modèle OpenAI</span>
              <select value={form.liluvine_decroche_modele_openai} onChange={(e) => maj("liluvine_decroche_modele_openai", e.target.value)} className={champ}>
                <option value="gpt-4o-mini-tts">gpt-4o-mini-tts (suit la consigne d'accent)</option>
                <option value="tts-1">tts-1 (ancien, sans accent)</option>
              </select>
            </label>
            <label className="block">
              <span className="font-semibold text-slate-700">Modèle ElevenLabs</span>
              <select value={form.liluvine_decroche_modele_elevenlabs} onChange={(e) => maj("liluvine_decroche_modele_elevenlabs", e.target.value)} className={champ}>
                <option value="eleven_flash_v2_5">eleven_flash_v2_5 (rapide, conseillé au téléphone)</option>
                <option value="eleven_multilingual_v2">eleven_multilingual_v2 (plus expressif, plus lent)</option>
              </select>
            </label>
          </div>
          <label className="block">
            <span className="font-semibold text-slate-700">Accent / style de voix (consigne donnée à gpt-4o-mini-tts)</span>
            <input value={form.liluvine_decroche_accent} onChange={(e) => maj("liluvine_decroche_accent", e.target.value)}
              placeholder={choixVoix.accent_defaut || "français d'Afrique de l'Ouest, chaleureux et posé"} className={champ} />
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={ecouterEssai} disabled={!!occupe}
              className="rounded-lg border border-violet-300 bg-white px-3 py-1 text-xs font-semibold text-violet-800 hover:bg-violet-50 disabled:opacity-50">
              {occupe === "essai" ? <Jauge /> : "🔊"} Écouter un essai
            </button>
            <button type="button" onClick={() => listerVoixEl("compte")} disabled={!!occupe || !choixVoix.elevenlabs_cle}
              title={choixVoix.elevenlabs_cle ? "" : "ELEVENLABS_API_KEY manquante sur Render"}
              className="rounded-lg border border-slate-300 bg-white px-3 py-1 text-xs hover:bg-slate-50 disabled:opacity-50">
              {occupe === "voix-el" ? <Jauge /> : "🗂️"} Choisir une voix ElevenLabs (mon compte)
            </button>
            <span className="inline-flex items-center gap-1">
              <button type="button" onClick={() => listerVoixEl("bibliotheque")} disabled={!!occupe || !choixVoix.elevenlabs_cle}
                className="rounded-lg border border-slate-300 bg-white px-3 py-1 text-xs hover:bg-slate-50 disabled:opacity-50">
                🌍 Bibliothèque : voix françaises, accent
              </button>
              <input value={accentEl} onChange={(e) => setAccentEl(e.target.value)} className="w-28 rounded border border-slate-300 px-1 py-0.5" />
            </span>
          </div>
          {essaiUrl && <audio ref={essaiRef} src={essaiUrl} controls className="h-8 w-full max-w-md" />}
          {choixEl && (
            <div className="max-h-64 overflow-auto rounded bg-white p-1 ring-1 ring-slate-200">
              {(choixEl.voix || []).length === 0 && (
                <p className="p-1 text-slate-500">Aucune voix trouvée. Dans la « Voice Library » d'ElevenLabs, filtrez Langue = French,
                  ajoutez une voix à « My Voices », puis cliquez sur « mon compte ».</p>
              )}
              <table className="w-full">
                <tbody>
                  {(choixEl.voix || []).map((v) => (
                    <tr key={`${v.proprietaire_id || ""}-${v.voice_id}`} className="border-t border-slate-100"
                      aria-selected={form.liluvine_decroche_voix_elevenlabs === v.voice_id ? "true" : undefined}>
                      <td className="px-1 py-0.5 font-semibold">{v.nom}</td>
                      <td className="px-1 py-0.5">{[v.accent, v.genre, v.locale || v.langue].filter(Boolean).join(" · ")}</td>
                      <td className="px-1 py-0.5">{v.extrait ? <audio src={v.extrait} controls preload="none" className="h-7 w-44" /> : null}</td>
                      <td className="px-1 py-0.5 text-right">
                        <button type="button" onClick={() => choisirVoixEl(v)} disabled={!!occupe}
                          className="rounded border border-violet-300 px-2 py-0.5 text-violet-800 hover:bg-violet-50 disabled:opacity-50">
                          {v.source === "bibliotheque" ? "Ajouter et choisir" : "Choisir"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="text-[11px] text-slate-500">
            Meilleur accent africain : une voix ElevenLabs de la bibliothèque enregistrée par un locuteur d'Afrique de l'Ouest
            (accent naturel). Sinon, OpenAI gpt-4o-mini-tts suit la consigne d'accent (résultat plus approximatif).
            Google (gratuit) reste le dernier recours.
          </p>
        </div>
        <p className="mt-2 text-[11px] text-slate-500">
          Langue : français. Sans clé OpenAI, Liluvine décroche, s'excuse de ne pas pouvoir écouter, crée une demande de rappel
          et raccroche. Une fiche contact peut aussi porter « liluvine_decroche = non ».
        </p>
      </details>

      <button type="button" onClick={enregistrer} disabled={!!occupe}
        className="rounded-lg bg-violet-700 px-4 py-1.5 text-sm font-semibold text-white hover:bg-violet-800 disabled:opacity-50">
        {occupe === "enregistrer" ? <Jauge /> : null} Enregistrer
      </button>

      {/* Simulation écrite d'un appel (même prompt, même modèle, sans voix) */}
      <div className="rounded-lg bg-white/70 p-2 ring-1 ring-slate-200 text-xs">
        <p className="font-semibold text-slate-700">🧪 Simuler un appel (écrit)</p>
        <p className="text-[11px] text-slate-500">Tapez ce que dirait l'appelant : Liluvine répond comme au téléphone.</p>
        {(simu.historique || []).length > 0 && (
          <ol className="mt-1 max-h-48 space-y-1 overflow-auto rounded bg-white p-2 ring-1 ring-slate-100">
            {simu.historique.map((t, i) => (
              <li key={i} className={t.qui === "appelant" ? "" : "text-violet-800"}>
                <strong>{t.qui === "appelant" ? "Appelant" : "Liluvine"} :</strong> {t.texte}
              </li>
            ))}
          </ol>
        )}
        {simu.fin && <p className="mt-1 text-[11px] text-amber-700">{simu.fin === "humain" ? "→ Liluvine transmettrait à un humain et raccrocherait." : "→ Liluvine raccrocherait (au revoir)."}</p>}
        <div className="mt-1 flex gap-2">
          <input value={simu.texte} onChange={(e) => setSimu((x) => ({ ...x, texte: e.target.value }))}
            onKeyDown={(e) => { if (e.key === "Enter") simuler(); }}
            placeholder="Ex. Bonjour, à quelle heure ouvrez-vous ?" className="flex-1 rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
          <button type="button" onClick={simuler} disabled={!!occupe}
            className="rounded-lg border border-violet-300 bg-white px-3 py-1 text-xs font-semibold text-violet-800 hover:bg-violet-50 disabled:opacity-50">
            {occupe === "simuler" ? <Jauge /> : "💬"} Envoyer
          </button>
          <button type="button" onClick={() => setSimu({ texte: "", historique: [] })} disabled={!!occupe}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1 text-xs hover:bg-slate-50 disabled:opacity-50">
            Recommencer
          </button>
        </div>
      </div>

      {/* Derniers appels pris par Liluvine (clic = transcription) */}
      {(donnees?.derniers || []).length > 0 && (
        <table className="w-full text-xs">
          <thead className="bg-slate-50 text-slate-600">
            <tr>
              <th className="px-2 py-1 text-left">Date</th>
              <th className="px-2 py-1 text-left">Appelant</th>
              <th className="px-2 py-1 text-left">Résumé</th>
            </tr>
          </thead>
          <tbody>
            {donnees.derniers.map((a) => (
              <React.Fragment key={a.id}>
                <tr className="cursor-pointer border-t border-slate-100" aria-selected={deplie === a.id ? "true" : undefined}
                  onClick={() => setDeplie(deplie === a.id ? null : a.id)}>
                  <td className="whitespace-nowrap px-2 py-1">{a.created_at ? new Date(a.created_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : ""}</td>
                  <td className="px-2 py-1">{a.contact_nom || `+${a.telephone}`}</td>
                  <td className="px-2 py-1">{a.liluvine?.resume || a.liluvine?.erreur || a.statut}</td>
                </tr>
                {deplie === a.id && a.liluvine && (
                  <tr><td colSpan={3} className="px-2 py-1"><TranscriptionAppelLiluvine l={a.liluvine} /></td></tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
