// MesRequetes.jsx — Lot 86 : « Mes requêtes » du portail client.
//
// Le client (contractuel ou non) soumet à SAWALI des dysfonctionnements, remarques, problèmes de logiciel ou
// d'équipement, PAR ÉCRIT et/ou PAR MESSAGE VOCAL (enregistré dans le navigateur, transcrit automatiquement).
// Chaque requête est numérotée par client (REQ-<code>-0001…) et horodatée. Le client suit l'état, les observations de
// SAWALI et le lot de correction ; une fois la requête terminée ou déployée, il l'ÉVALUE (note 1 à 5 + commentaire).
import React, { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Loader2, Mic, Square, Star, Trash2 } from "lucide-react";
import { apiClient } from "@/lib/api";
import AudioRequete from "@/components/AudioRequete";

// « 09/10/2026 08:15 »
const dateHeure = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "");
const erreur = (e, defaut) => e?.response?.data?.detail || defaut;

// Couleur de la pastille d'état
const COULEUR_ETAT = {
  nouvelle: "bg-sky-100 text-sky-800", en_cours: "bg-amber-100 text-amber-800",
  attente_client: "bg-purple-100 text-purple-800", terminee: "bg-emerald-100 text-emerald-800",
  deployee: "bg-emerald-600 text-white", rejetee: "bg-slate-200 text-slate-700",
};

// Enregistreur vocal (MediaRecorder) : démarre / arrête, renvoie le fichier audio au parent
function Enregistreur({ audio, onAudio }) {
  const [enregistre, setEnregistre] = useState(false);
  const recorder = useRef(null);
  const morceaux = useRef([]);
  const demarrer = async () => {
    try {
      const flux = await navigator.mediaDevices.getUserMedia({ audio: true });
      const types = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg", "audio/mp4"];
      const mime = types.find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";
      const r = new MediaRecorder(flux, mime ? { mimeType: mime } : undefined);
      morceaux.current = [];
      r.ondataavailable = (e) => e.data.size && morceaux.current.push(e.data);
      r.onstop = () => {
        flux.getTracks().forEach((t) => t.stop());
        const type = r.mimeType || "audio/webm";
        const ext = type.includes("ogg") ? "ogg" : type.includes("mp4") ? "m4a" : "webm";
        onAudio(new File(morceaux.current, `requete.${ext}`, { type }));
      };
      r.start();
      recorder.current = r;
      setEnregistre(true);
    } catch {
      toast.error("Micro indisponible : autorisez le micro dans le navigateur");
    }
  };
  const arreter = () => { recorder.current?.stop(); setEnregistre(false); };
  return (
    <div className="flex flex-wrap items-center gap-2">
      {!enregistre ? (
        <button type="button" onClick={demarrer} className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">
          <Mic className="h-4 w-4 text-rose-600" /> {audio ? "Réenregistrer" : "Message vocal"}</button>
      ) : (
        <button type="button" onClick={arreter} className="inline-flex items-center gap-1 rounded-lg bg-rose-600 px-3 py-1.5 text-sm font-semibold text-white animate-pulse">
          <Square className="h-4 w-4" /> Arrêter l'enregistrement</button>
      )}
      {audio && !enregistre && (
        <>
          <audio controls src={URL.createObjectURL(audio)} className="h-8" />
          <button type="button" onClick={() => onAudio(null)} title="Supprimer le message vocal" className="text-rose-700"><Trash2 className="h-4 w-4" /></button>
        </>
      )}
    </div>
  );
}

// Évaluation par étoiles (1 à 5) + commentaire
function Evaluation({ requete, onFait }) {
  const [note, setNote] = useState(0);
  const [commentaire, setCommentaire] = useState("");
  const envoyer = async () => {
    const attente = toast.loading("Patientez…");
    try {
      await apiClient.post(`/me/requetes/${requete.id}/evaluation`, { note, commentaire });
      toast.success("Merci pour votre évaluation", { id: attente });
      onFait();
    } catch (e) { toast.error(erreur(e, "Évaluation non enregistrée"), { id: attente }); }
  };
  return (
    <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs" data-testid={`evaluer-${requete.numero}`}>
      <p className="font-semibold text-amber-900">Votre avis sur le traitement de cette requête :</p>
      <div className="my-1 flex gap-1">
        {[1, 2, 3, 4, 5].map((n) => (
          <button key={n} type="button" onClick={() => setNote(n)} aria-label={`${n} sur 5`}>
            <Star className={`h-5 w-5 ${n <= note ? "fill-amber-400 text-amber-500" : "text-slate-300"}`} /></button>
        ))}
      </div>
      <input value={commentaire} onChange={(e) => setCommentaire(e.target.value)} placeholder="Commentaire (facultatif)"
        className="w-full rounded border border-slate-300 px-2 py-1" />
      <button type="button" disabled={!note} onClick={envoyer} className="mt-1 rounded bg-amber-600 px-3 py-1 font-semibold text-white disabled:opacity-40">Envoyer mon évaluation</button>
    </div>
  );
}

export default function MesRequetes() {
  const [donnees, setDonnees] = useState(null);
  const [f, setF] = useState({ categorie: "dysfonctionnement", titre: "", texte: "", logiciel: "", equipement: "" });
  const [audio, setAudio] = useState(null);
  const [envoi, setEnvoi] = useState(false);
  const [ouverte, setOuverte] = useState(null);   // requête dépliée (détail)

  const charger = useCallback(() => {
    apiClient.get("/me/requetes").then((r) => setDonnees(r.data)).catch(() => setDonnees({ requetes: [], categories: {}, etats: {} }));
  }, []);
  useEffect(() => { charger(); }, [charger]);

  // Dépôt de la requête (formulaire multipart : texte + message vocal éventuel)
  const soumettre = async () => {
    setEnvoi(true);
    const attente = toast.loading("Patientez… envoi de votre requête");
    try {
      const fd = new FormData();
      Object.entries(f).forEach(([k, v]) => fd.append(k, v));
      if (audio) fd.append("audio", audio);
      const r = await apiClient.post("/me/requetes", fd);
      toast.success(`Requête ${r.data.numero} enregistrée`, { id: attente });
      setF({ ...f, titre: "", texte: "", logiciel: "", equipement: "" });
      setAudio(null);
      charger();
    } catch (e) { toast.error(erreur(e, "Requête non envoyée"), { id: attente }); }
    finally { setEnvoi(false); }
  };

  if (!donnees) return <p className="p-6 text-sm text-slate-500">Patientez…</p>;
  const champ = "mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm";
  return (
    <div className="space-y-5 p-4 md:p-6" data-testid="mes-requetes">
      <div>
        <h1 className="text-2xl font-display font-bold">Mes requêtes</h1>
        <p className="text-sm text-slate-600">Signalez un dysfonctionnement, une remarque, un souci de logiciel ou d'équipement — par écrit ou par message vocal. Chaque requête est numérotée et suivie jusqu'à sa correction, puis vous l'évaluez.</p>
      </div>

      {/* Nouvelle requête */}
      <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
        <p className="font-semibold">Nouvelle requête</p>
        <div className="grid gap-2 sm:grid-cols-3">
          <label className="text-xs"><span className="font-semibold">Catégorie</span>
            <select value={f.categorie} onChange={(e) => setF({ ...f, categorie: e.target.value })} className={champ}>
              {Object.entries(donnees.categories || {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select></label>
          {f.categorie === "logiciel" && (
            <label className="text-xs"><span className="font-semibold">Logiciel concerné</span>
              <input value={f.logiciel} onChange={(e) => setF({ ...f, logiciel: e.target.value })} className={champ} placeholder="Biolog, Aizenta, Loois…" /></label>
          )}
          {f.categorie === "equipement" && (
            <label className="text-xs"><span className="font-semibold">Équipement concerné</span>
              <input value={f.equipement} onChange={(e) => setF({ ...f, equipement: e.target.value })} className={champ} placeholder="Imprimante, poste, automate…" /></label>
          )}
          <label className="text-xs sm:col-span-3"><span className="font-semibold">Titre</span>
            <input value={f.titre} onChange={(e) => setF({ ...f, titre: e.target.value })} className={champ} placeholder="En quelques mots" /></label>
          <label className="text-xs sm:col-span-3"><span className="font-semibold">Description</span>
            <textarea rows={3} value={f.texte} onChange={(e) => setF({ ...f, texte: e.target.value })} className={champ} placeholder="Que se passe-t-il ? Quand ? Sur quel poste ?" /></label>
        </div>
        <Enregistreur audio={audio} onAudio={setAudio} />
        <button type="button" disabled={envoi} onClick={soumettre} className="inline-flex items-center gap-2 rounded-lg bg-sky-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
          {envoi && <Loader2 className="h-4 w-4 animate-spin" />} Envoyer la requête</button>
      </div>

      {/* Requêtes du client */}
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <p className="mb-2 font-semibold">Suivi ({donnees.requetes.length}){donnees.resume?.a_evaluer ? ` · ${donnees.resume.a_evaluer} à évaluer` : ""}</p>
        {donnees.requetes.length === 0 ? <p className="text-sm text-slate-500">Aucune requête pour le moment.</p> : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-slate-500"><tr><th className="py-1">N°</th><th>Déposée le</th><th>Catégorie</th><th>Titre</th><th>Lot</th><th>État</th></tr></thead>
            <tbody>
              {donnees.requetes.map((r) => (
                <React.Fragment key={r.id}>
                  <tr className={`cursor-pointer border-t border-slate-100 ${ouverte === r.id ? "ligne-selectionnee" : ""}`} onClick={() => setOuverte(ouverte === r.id ? null : r.id)}>
                    <td className="py-1 font-mono text-xs">{r.numero}</td><td className="text-xs">{dateHeure(r.cree_le)}</td>
                    <td className="text-xs">{r.libelle_categorie}{r.logiciel ? ` · ${r.logiciel}` : ""}{r.equipement ? ` · ${r.equipement}` : ""}</td>
                    <td>{r.titre}{r.a_evaluer && <span className="ml-2 rounded-full bg-amber-100 px-2 text-[10px] font-semibold text-amber-800">À évaluer</span>}</td>
                    <td className="text-xs">{r.lot_numero ? `Lot ${r.lot_numero}` : "—"}</td>
                    <td><span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${COULEUR_ETAT[r.etat] || ""}`}>{r.libelle_etat}</span></td>
                  </tr>
                  {ouverte === r.id && (
                    <tr><td colSpan={6} className="bg-slate-50 p-3 text-xs">
                      {r.texte && <p className="whitespace-pre-wrap">{r.texte}</p>}
                      {r.a_audio && <AudioRequete id={r.id} />}
                      {r.transcription && <p className="mt-1 italic text-slate-600">Transcription : {r.transcription}</p>}
                      {(r.observations || []).length > 0 && (
                        <div className="mt-2"><p className="font-semibold">Observations de SAWALI</p>
                          <ul className="list-disc pl-5">{r.observations.map((o, i) => <li key={i}>{dateHeure(o.le)} — {o.texte}</li>)}</ul></div>
                      )}
                      {r.evaluation && <p className="mt-2">Votre évaluation : {"★".repeat(r.evaluation.note)}{"☆".repeat(5 - r.evaluation.note)} {r.evaluation.commentaire}</p>}
                      {r.a_evaluer && <Evaluation requete={r} onFait={charger} />}
                    </td></tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
