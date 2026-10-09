// EspaceRequetes.jsx — Lots 86 / 86.1 : formulaire « Nouvelle requête » + tableau de suivi, communs au portail
// connecté (« Mes requêtes ») et à la page publique du lien personnel (/requete/<jeton>).
// Les appels au serveur sont fournis par la page (props « api ») : routes protégées ou routes publiques du lien.
//
// api = {
//   charger()              → Promise<{requetes, categories, etats, resume}>
//   deposer(FormData)      → Promise<requête créée>
//   evaluer(id, corps)     → Promise
//   audio(id)              → Promise<Blob>          (message vocal)
//   image(reqId, img)      → Promise<Blob>          (image jointe)
// }
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import AudioRequete from "@/components/AudioRequete";
import { COULEUR_ETAT, Enregistreur, Evaluation, ImagesRequete, SelecteurImages, dateHeure, erreur } from "@/components/RequeteOutils";

export default function EspaceRequetes({ api, demanderNom = false }) {
  const [donnees, setDonnees] = useState(null);
  const [f, setF] = useState({ categorie: "dysfonctionnement", titre: "", texte: "", logiciel: "", equipement: "", auteur_nom: "" });
  const [audio, setAudio] = useState(null);
  const [images, setImages] = useState([]);   // lot 86.1 : photos, captures, images chargées
  const [envoi, setEnvoi] = useState(false);
  const [ouverte, setOuverte] = useState(null);   // requête dépliée (détail)

  const charger = useCallback(() => {
    api.charger().then(setDonnees).catch((e) => setDonnees({ requetes: [], categories: {}, etats: {}, erreur: erreur(e, "Chargement impossible") }));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => { charger(); }, [charger]);

  // Dépôt de la requête (multipart : texte + message vocal + images)
  const soumettre = async () => {
    setEnvoi(true);
    const attente = toast.loading("Patientez… envoi de votre requête");
    try {
      const fd = new FormData();
      Object.entries(f).forEach(([k, v]) => { if (k !== "auteur_nom" || demanderNom) fd.append(k, v); });
      if (audio) fd.append("audio", audio);
      images.forEach((img) => fd.append("images", img, img.name));
      const r = await api.deposer(fd);
      toast.success(`Requête ${r.numero} enregistrée`, { id: attente });
      setF({ ...f, titre: "", texte: "", logiciel: "", equipement: "" });
      setAudio(null);
      setImages([]);
      charger();
    } catch (e) { toast.error(erreur(e, "Requête non envoyée"), { id: attente }); }
    finally { setEnvoi(false); }
  };

  if (!donnees) return <p className="p-6 text-sm text-slate-500">Patientez…</p>;
  if (donnees.erreur) return <p className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{donnees.erreur}</p>;
  const champ = "mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm";
  return (
    <div className="space-y-5">
      {/* Nouvelle requête */}
      <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
        <p className="font-semibold">Nouvelle requête</p>
        <div className="grid gap-2 sm:grid-cols-3">
          {demanderNom && (
            <label className="text-xs"><span className="font-semibold">Votre nom</span>
              <input value={f.auteur_nom} onChange={(e) => setF({ ...f, auteur_nom: e.target.value })} className={champ} placeholder="Prénom Nom" /></label>
          )}
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
        <SelecteurImages images={images} onImages={setImages} />
        <button type="button" disabled={envoi} onClick={soumettre} className="inline-flex items-center gap-2 rounded-lg bg-sky-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
          {envoi && <Loader2 className="h-4 w-4 animate-spin" />} Envoyer la requête</button>
      </div>

      {/* Suivi des requêtes */}
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <p className="mb-2 font-semibold">Suivi ({donnees.requetes.length}){donnees.resume?.a_evaluer ? ` · ${donnees.resume.a_evaluer} à évaluer` : ""}</p>
        {donnees.requetes.length === 0 ? <p className="text-sm text-slate-500">Aucune requête pour le moment.</p> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-slate-500"><tr><th className="py-1">N°</th><th>Déposée le</th><th>Catégorie</th><th>Titre</th><th>Lot</th><th>État</th></tr></thead>
              <tbody>
                {donnees.requetes.map((r) => (
                  <React.Fragment key={r.id}>
                    <tr className={`cursor-pointer border-t border-slate-100 ${ouverte === r.id ? "ligne-selectionnee" : ""}`} onClick={() => setOuverte(ouverte === r.id ? null : r.id)}>
                      <td className="py-1 font-mono text-xs">{r.numero}</td><td className="text-xs">{dateHeure(r.cree_le)}</td>
                      <td className="text-xs">{r.libelle_categorie}{r.logiciel ? ` · ${r.logiciel}` : ""}{r.equipement ? ` · ${r.equipement}` : ""}</td>
                      <td>{r.titre}{r.a_audio ? " 🎤" : ""}{r.images?.length ? ` 🖼️${r.images.length}` : ""}
                        {r.a_evaluer && <span className="ml-2 rounded-full bg-amber-100 px-2 text-[10px] font-semibold text-amber-800">À évaluer</span>}</td>
                      <td className="text-xs">{r.lot_numero ? `Lot ${r.lot_numero}` : "—"}</td>
                      <td><span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${COULEUR_ETAT[r.etat] || ""}`}>{r.libelle_etat}</span></td>
                    </tr>
                    {ouverte === r.id && (
                      <tr><td colSpan={6} className="bg-slate-50 p-3 text-xs">
                        <p className="text-slate-500">Déposée par {r.auteur_nom || "—"}</p>
                        {r.texte && <p className="whitespace-pre-wrap">{r.texte}</p>}
                        {r.a_audio && <AudioRequete id={r.id} charger={api.audio} />}
                        {r.transcription && <p className="mt-1 italic text-slate-600">Transcription : {r.transcription}</p>}
                        <ImagesRequete images={r.images} charger={(img) => api.image(r.id, img)} />
                        {(r.observations || []).length > 0 && (
                          <div className="mt-2"><p className="font-semibold">Observations de SAWALI</p>
                            <ul className="list-disc pl-5">{r.observations.map((o, i) => <li key={i}>{dateHeure(o.le)} — {o.texte}</li>)}</ul></div>
                        )}
                        {r.evaluation && <p className="mt-2">Votre évaluation : {"★".repeat(r.evaluation.note)}{"☆".repeat(5 - r.evaluation.note)} {r.evaluation.commentaire}</p>}
                        {r.a_evaluer && <Evaluation requete={r} envoyer={(corps) => api.evaluer(r.id, { ...corps, auteur_nom: f.auteur_nom })} onFait={charger} />}
                      </td></tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
