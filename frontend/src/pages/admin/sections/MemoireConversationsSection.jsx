// MemoireConversationsSection.jsx — Lot 344 : mémoire des conversations WhatsApp dans Qdrant.
//
// 1. Réglages : activer l'indexation (messages, PDF, images — jamais les vocaux), contenu des images, mémoire donnée à l'IA.
// 2. Recherche par similarité (numéro facultatif) dans les échanges déjà indexés.
// 3. Enrichissement de la base de connaissances : chaque réponse d'un humain à une question de client devient une
//    « question / réponse candidate » anonymisée ; elle n'entre dans une collection qu'après VOTRE validation.
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const champ = "w-full rounded-md border border-slate-300 px-2 py-1 text-sm";
const bouton = "text-xs font-semibold px-3 py-1.5 rounded-md bg-blue-700 text-white hover:bg-blue-800 disabled:opacity-50";

export default function MemoireConversationsSection() {
  const [etat, setEtat] = useState(null);
  const [reglages, setReglages] = useState(null);
  const [collections, setCollections] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [brouillons, setBrouillons] = useState({});   // id → { question, reponse, collection } (corrections avant publication)
  const [requete, setRequete] = useState("");
  const [numero, setNumero] = useState("");
  const [resultats, setResultats] = useState(null);
  const [jours, setJours] = useState(30);
  const [occupe, setOccupe] = useState(false);

  // Chargement de l'état, des collections de la base de connaissances et des candidates à relire
  const charger = useCallback(async () => {
    try {
      const [e, c, q] = await Promise.all([
        apiClient.get("/admin/wa-memoire/etat"),
        apiClient.get("/admin/qdrant/collections").catch(() => ({ data: [] })),
        apiClient.get("/admin/wa-memoire/candidates").catch(() => ({ data: { items: [] } })),
      ]);
      setEtat(e.data);
      setReglages(e.data.reglages);
      const liste = Array.isArray(c.data) ? c.data : (c.data?.collections || c.data?.items || []);
      setCollections(liste.map((x) => x.name).filter((n) => n && n !== "wa_conversations"));
      setCandidates(q.data?.items || []);
    } catch {
      toast.error("Mémoire des conversations indisponible");
    }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  if (!etat || !reglages) return <p className="text-xs text-slate-500">Patientez…</p>;
  const maj = (cle, valeur) => setReglages((r) => ({ ...r, [cle]: valeur }));

  // Enregistrement des réglages
  const enregistrer = async () => {
    setOccupe(true);
    try {
      await apiClient.put("/admin/settings", {
        wa_memoire_active: reglages.actif, wa_memoire_images: reglages.images, wa_memoire_ia: reglages.ia,
        wa_memoire_ia_reponses_equipe: reglages.ia_reponses_equipe, wa_memoire_images_par_jour: Math.max(0, Number(reglages.images_par_jour) || 0),
      });
      toast.success("Réglages enregistrés");
      await charger();
    } catch (err) { toast.error(err?.response?.data?.detail || "Enregistrement impossible"); } finally { setOccupe(false); }
  };

  // Indexe aussi l'historique des N derniers jours (reprise par lots en arrière-plan)
  const rattraper = async () => {
    setOccupe(true);
    try {
      await apiClient.post("/admin/wa-memoire/historique", { jours: Number(jours) || 0 });
      toast.success(`L'historique des ${jours} derniers jours sera indexé en arrière-plan`);
      await charger();
    } catch (err) { toast.error(err?.response?.data?.detail || "Impossible"); } finally { setOccupe(false); }
  };

  // Recherche par similarité
  const chercher = async () => {
    if (requete.trim().length < 2) { toast.error("Saisissez une recherche"); return; }
    setOccupe(true);
    try {
      const r = await apiClient.post("/admin/wa-memoire/rechercher", { requete, numero: numero || null, top_k: 10 });
      setResultats(r.data.items || []);
    } catch (err) { setResultats(null); toast.error(err?.response?.data?.detail || "Recherche impossible"); } finally { setOccupe(false); }
  };

  const brouillon = (c) => ({ question: c.question, reponse: c.reponse, collection: collections[0] || "", ...(brouillons[c.id] || {}) });
  const corriger = (c, cle, v) => setBrouillons((b) => ({ ...b, [c.id]: { ...brouillon(c), [cle]: v } }));

  // Publication (après relecture) dans la collection choisie, ou refus
  const valider = async (c) => {
    const b = brouillon(c);
    if (!b.collection) { toast.error("Choisissez une collection"); return; }
    try {
      await apiClient.post(`/admin/wa-memoire/candidates/${c.id}/valider`, b);
      toast.success(`Ajoutée à « ${b.collection} »`);
      setCandidates((l) => l.filter((x) => x.id !== c.id));
    } catch (err) { toast.error(err?.response?.data?.detail || "Publication impossible"); }
  };
  const refuser = async (c) => {
    try { await apiClient.post(`/admin/wa-memoire/candidates/${c.id}/refuser`); setCandidates((l) => l.filter((x) => x.id !== c.id)); }
    catch (err) { toast.error(err?.response?.data?.detail || "Impossible"); }
  };

  return (
    <div className="space-y-4" data-testid="memoire-conversations">
      <p className="text-xs text-slate-600">
        Les messages (texte, PDF, images — jamais les vocaux) des clients et des réponses de votre équipe sont indexés dans Qdrant pour
        retrouver un échange par numéro ou par sujet. Les fichiers restent sur R2. L'IA ne reçoit que l'historique du <strong>même numéro</strong>.
        Les réponses de l'équipe deviennent des questions / réponses à valider avant d'enrichir votre base de connaissances.
      </p>

      {/* Réglages */}
      <div className="space-y-2">
        <label className="flex items-center gap-2 text-sm font-semibold">
          <input type="checkbox" checked={reglages.actif} onChange={(e) => maj("actif", e.target.checked)} data-testid="memoire-active" />
          Activer la mémoire des conversations
        </label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={reglages.images} onChange={(e) => maj("images", e.target.checked)} />
          Lire aussi le contenu des images (texte et description par l'IA — consomme des requêtes)</label>
        <label className="flex items-center gap-2 text-sm">Images analysées par jour au plus
          <input type="number" min={0} className="w-24 rounded-md border border-slate-300 px-2 py-1 text-sm" value={reglages.images_par_jour}
            onChange={(e) => maj("images_par_jour", e.target.value)} /></label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={reglages.ia} onChange={(e) => maj("ia", e.target.checked)} />
          Donner à l'IA l'historique pertinent du même numéro</label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={reglages.ia_reponses_equipe} onChange={(e) => maj("ia_reponses_equipe", e.target.checked)} />
          Donner aussi à l'IA des réponses déjà données par l'équipe à d'autres clients (anonymes)</label>
        <button type="button" className={bouton} onClick={enregistrer} disabled={occupe} data-testid="memoire-enregistrer">Enregistrer</button>
      </div>

      {/* État */}
      <div className="rounded-md bg-slate-50 border border-slate-200 p-3 text-xs space-y-1" data-testid="memoire-etat">
        <div>Qdrant : <strong>{etat.qdrant_active ? "actif" : "désactivé (activez-le dans la rubrique Qdrant)"}</strong>
          {etat.serveur_assez_grand === false && <span className="text-red-700"> — serveur trop petit pour le modèle d'indexation</span>}</div>
        <div>Points indexés : <strong>{etat.points ?? "—"}</strong> · messages traités : <strong>{etat.total_messages}</strong></div>
        <div>Dernier passage : {etat.derniere_execution ? new Date(etat.derniere_execution).toLocaleString("fr-FR") : "—"}
          {etat.derniere_erreur && <span className="text-red-700"> · erreur : {etat.derniere_erreur}</span>}</div>
        <div className="flex flex-wrap items-center gap-2 pt-1">
          Indexer aussi l'historique des
          <input type="number" min={0} max={3650} className="w-20 rounded-md border border-slate-300 px-2 py-1" value={jours} onChange={(e) => setJours(e.target.value)} />
          derniers jours <button type="button" className={bouton} onClick={rattraper} disabled={occupe}>Lancer</button>
        </div>
      </div>

      {/* Recherche */}
      <div className="space-y-2">
        <h4 className="text-sm font-semibold">Rechercher dans les échanges</h4>
        <div className="flex flex-wrap gap-2">
          <input className={champ + " sm:flex-1"} placeholder="Sujet : prix du bilan, résultat d'analyse, rendez-vous…" value={requete} onChange={(e) => setRequete(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && chercher()} data-testid="memoire-requete" />
          <input className={champ + " sm:w-48"} placeholder="Numéro (facultatif)" value={numero} onChange={(e) => setNumero(e.target.value)} />
          <button type="button" className={bouton} onClick={chercher} disabled={occupe}>Chercher</button>
        </div>
        {resultats && (resultats.length === 0 ? <p className="text-xs text-slate-500">Aucun échange proche.</p> : (
          <ul className="space-y-2">
            {resultats.map((h, i) => (
              <li key={i} className="rounded-md border border-slate-200 p-2 text-xs">
                <div className="text-slate-500">{(h.created_at || "").slice(0, 10)} · +{h.phone_digits} {h.contact_name ? `(${h.contact_name})` : ""} · {h.direction === "inbound" ? "client" : (h.sender_label || "équipe")} · {h.nature} · score {h.score}</div>
                <div className="whitespace-pre-wrap">{h.text}</div>
                {h.media_url && <a className="text-blue-700 underline" href={h.media_url} target="_blank" rel="noreferrer">{h.media_filename || "Fichier"}</a>}
              </li>
            ))}
          </ul>
        ))}
      </div>

      {/* Questions / réponses candidates */}
      <div className="space-y-2" data-testid="memoire-candidates">
        <h4 className="text-sm font-semibold">Questions / réponses à valider pour la base de connaissances ({candidates.length})</h4>
        {candidates.length === 0 && <p className="text-xs text-slate-500">Rien à relire pour le moment.</p>}
        {candidates.map((c) => {
          const b = brouillon(c);
          return (
            <div key={c.id} className="rounded-md border border-slate-200 p-2 space-y-1">
              <label className="text-xs font-semibold">Question</label>
              <textarea rows={2} className={champ} value={b.question} onChange={(e) => corriger(c, "question", e.target.value)} />
              <label className="text-xs font-semibold">Réponse</label>
              <textarea rows={3} className={champ} value={b.reponse} onChange={(e) => corriger(c, "reponse", e.target.value)} />
              <div className="flex flex-wrap items-center gap-2">
                <select className="rounded-md border border-slate-300 px-2 py-1 text-sm" value={b.collection} onChange={(e) => corriger(c, "collection", e.target.value)}>
                  {collections.map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
                <button type="button" className={bouton} onClick={() => valider(c)}>Ajouter à la base</button>
                <button type="button" className="text-xs font-semibold px-3 py-1.5 rounded-md border border-slate-300 hover:bg-slate-50" onClick={() => refuser(c)}>Écarter</button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
