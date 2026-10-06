// TransfertMessagesWa.jsx — Lot 71 : transférer un ou plusieurs messages WhatsApp à d'autres contacts.
//
// Ouvert depuis une bulle de la conversation (« ↪ Transférer », ou appui long sur mobile) ou depuis la
// barre de sélection multiple. Le dialogue permet :
//   • de chercher et cocher jusqu'à 10 destinataires (contacts WhatsApp visibles ; clients pour
//     l'administrateur et le superviseur) — chaque destinataire affiche sa ligne d'envoi et l'état de la
//     fenêtre de 24 h (badge « fenêtre fermée » AVANT l'envoi) ;
//   • pour un destinataire hors fenêtre : envoyer un modèle approuvé à la place, ou l'ignorer ;
//   • d'ajouter un commentaire, d'indiquer l'origine (« Transféré de <nom> : ») et de choisir la ligne ;
//   • de lire le résultat par destinataire (envoyé, partiel, refusé + motif, ignoré).
// Attente : toast « Patientez… » + jauge circulaire (règle du propriétaire).
import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

// Nombre maximal de destinataires par transfert (même limite que le serveur)
const MAX_DESTINATAIRES = 10;
// Libellé et couleur de chaque résultat
const RESULTATS = {
  envoye: { libelle: "envoyé", classe: "bg-emerald-100 text-emerald-800" },
  partiel: { libelle: "partiel", classe: "bg-amber-100 text-amber-800" },
  refuse: { libelle: "refusé", classe: "bg-rose-100 text-rose-800" },
  ignore: { libelle: "ignoré", classe: "bg-slate-100 text-slate-600" },
};
// Nature lisible d'un message (aperçu en tête du dialogue)
const natureLisible = (m) => {
  if (m.media_url) return { image: "🖼️ image", audio: "🎤 audio", video: "🎬 vidéo" }[m.media_kind] || "📄 document";
  if (/^\[position /.test(m.body || "")) return "📍 position";
  return "💬 texte";
};

// Petite jauge circulaire transparente (attente)
const Jauge = () => (
  <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-sky-300 border-t-transparent align-middle" />
);

export default function TransfertMessagesWa({ messages, onClose }) {
  const [recherche, setRecherche] = useState("");
  const [trouves, setTrouves] = useState([]);              // résultats de la recherche
  const [choisis, setChoisis] = useState([]);              // destinataires cochés
  const [chargement, setChargement] = useState(false);
  const [lignes, setLignes] = useState([]);                // lignes WhatsApp utilisables
  const [ligneCle, setLigneCle] = useState("");            // "" = ligne de la conversation du destinataire
  const [commentaire, setCommentaire] = useState("");
  const [origine, setOrigine] = useState(true);            // « Transféré de <nom> : » (activé par défaut)
  const [repli, setRepli] = useState({});                  // destinataire hors fenêtre → "modele" | "ignorer"
  const [modeles, setModeles] = useState(null);            // modèles approuvés (chargés à la demande)
  const [modele, setModele] = useState(null);
  const [envoi, setEnvoi] = useState(false);
  const [resultat, setResultat] = useState(null);

  // Lignes WhatsApp autorisées à l'utilisateur
  useEffect(() => {
    apiClient.get("/me/wa-transfert/lignes").then((r) => setLignes(r.data.lignes || [])).catch(() => setLignes([]));
  }, []);

  // Recherche des destinataires (nom ou numéro), relancée quand la ligne choisie change
  useEffect(() => {
    const t = setTimeout(async () => {
      setChargement(true);
      try {
        const r = await apiClient.get("/me/wa-transfert/destinataires", { params: { q: recherche, ligne_cle: ligneCle || undefined } });
        const liste = r.data.destinataires || [];
        setTrouves(liste);
        // Fenêtre et ligne des destinataires déjà cochés mises à jour (la ligne d'envoi a pu changer)
        setChoisis((avant) => avant.map((c) => liste.find((x) => x.id === c.id && x.source === c.source) || c));
      } catch { setTrouves([]); } finally { setChargement(false); }
    }, 300);
    return () => clearTimeout(t);
  }, [recherche, ligneCle]);

  // Destinataires hors fenêtre de 24 h et besoin d'un modèle
  const fermes = useMemo(() => choisis.filter((c) => !c.fenetre_ouverte), [choisis]);
  const besoinModele = fermes.some((c) => repli[c.id] === "modele");
  useEffect(() => {
    if (!besoinModele || modeles !== null) return;
    apiClient.get("/me/whatsapp/templates").then((r) => setModeles(r.data.items || [])).catch(() => setModeles([]));
  }, [besoinModele, modeles]);

  // Cocher / décocher un destinataire (10 au plus)
  const basculer = (d) => {
    setChoisis((avant) => {
      if (avant.some((c) => c.id === d.id && c.source === d.source)) return avant.filter((c) => !(c.id === d.id && c.source === d.source));
      if (avant.length >= MAX_DESTINATAIRES) { toast.error(`${MAX_DESTINATAIRES} destinataires au plus`); return avant; }
      return [...avant, d];
    });
  };

  // Envoi du transfert → résultat par destinataire
  const envoyer = async () => {
    if (!choisis.length) { toast.error("Choisissez au moins un destinataire"); return; }
    if (besoinModele && !modele) { toast.error("Choisissez le modèle approuvé à envoyer hors fenêtre"); return; }
    setEnvoi(true);
    const t = toast.loading("Patientez…");
    try {
      const r = await apiClient.post("/me/wa-transfert", {
        message_ids: messages.map((m) => m.id),
        destinataires: choisis.map((c) => ({ id: c.id, source: c.source, nom: c.nom })),
        commentaire, indiquer_origine: origine, ligne_cle: ligneCle || null,
        repli, modele: besoinModele && modele ? { name: modele.name, language: modele.language, components: modele.components } : null,
      });
      setResultat(r.data);
      const ok = (r.data.resultats || []).filter((x) => x.statut === "envoye").length;
      toast.success(`Transfert terminé : ${ok} / ${(r.data.resultats || []).length} destinataire(s) servis`, { id: t });
    } catch (err) {
      const d = err?.response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Transfert impossible", { id: t });
    } finally {
      setEnvoi(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center overflow-y-auto bg-black/40 p-4" onClick={onClose}>
      <div className="w-full max-w-2xl space-y-3 rounded-2xl bg-white p-4 shadow-xl" onClick={(e) => e.stopPropagation()} data-testid="dialogue-transfert">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-slate-800">↪ Transférer {messages.length > 1 ? `${messages.length} messages` : "le message"}</h2>
          <button type="button" onClick={onClose} className="rounded px-2 text-xl text-slate-400 hover:bg-slate-100">×</button>
        </div>
        {/* Aperçu des messages transférés */}
        <ul className="max-h-24 overflow-auto rounded bg-slate-50 p-2 text-xs text-slate-700">
          {messages.map((m) => (
            <li key={m.id} className="truncate">{natureLisible(m)} — {m.media_caption || m.body || m.media_filename || ""}</li>
          ))}
        </ul>

        {resultat ? (
          // Résultat par destinataire : rien n'échoue en silence
          <div data-testid="resultat-transfert">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase text-slate-600">
                <tr><th className="px-2 py-1">Destinataire</th><th className="px-2 py-1">Résultat</th><th className="px-2 py-1">Détail</th></tr>
              </thead>
              <tbody>
                {(resultat.resultats || []).map((x) => (
                  <tr key={`${x.source}-${x.id}`} className="border-t border-slate-100">
                    <td className="px-2 py-1">{x.nom}{x.telephone ? <span className="text-[11px] text-slate-500"> · +{x.telephone}</span> : null}</td>
                    <td className="px-2 py-1"><span className={`rounded px-1.5 py-0.5 text-[11px] ${(RESULTATS[x.statut] || {}).classe || ""}`}>{(RESULTATS[x.statut] || {}).libelle || x.statut}</span></td>
                    <td className="px-2 py-1 text-xs text-slate-600">
                      {x.mode === "modele" ? "modèle approuvé · " : ""}{x.total ? `${x.envoyes}/${x.total} envoi(s)` : ""}{x.ligne ? ` · ${x.ligne}` : ""}{x.raison ? ` — ${x.raison}` : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="mt-3 flex justify-end">
              <button type="button" onClick={onClose} className="rounded-lg bg-sky-700 px-4 py-1.5 text-sm font-semibold text-white hover:bg-sky-800">Fermer</button>
            </div>
          </div>
        ) : (
          <>
            {/* Recherche et choix des destinataires */}
            <div>
              <input value={recherche} onChange={(e) => setRecherche(e.target.value)} placeholder="Rechercher un contact (nom, entreprise ou numéro)"
                className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" data-testid="transfert-recherche" />
              <div className="mt-1 max-h-48 overflow-auto rounded border border-slate-200">
                {chargement && <p className="px-2 py-1 text-xs text-slate-500"><Jauge /> Patientez…</p>}
                {!chargement && trouves.length === 0 && <p className="px-2 py-1 text-xs text-slate-500">Aucun contact trouvé.</p>}
                {trouves.map((d) => {
                  const coche = choisis.some((c) => c.id === d.id && c.source === d.source);
                  // Ligne cochée : fond orange et police blanche (règle 3 des tableaux du propriétaire)
                  return (
                    <label key={`${d.source}-${d.id}`} className={`flex cursor-pointer items-center gap-2 px-2 py-1 text-sm hover:bg-sky-50 ${coche ? "bg-[#f6a35b] text-white hover:bg-[#f6a35b]" : ""}`}>
                      <input type="checkbox" checked={coche} onChange={() => basculer(d)} />
                      <span className="flex-1 truncate">{d.nom} <span className="text-[11px] opacity-70">+{d.telephone}{d.source === "client" ? " · client" : ""}{d.ligne_libelle ? ` · ${d.ligne_libelle}` : ""}</span></span>
                      {d.fenetre_ouverte
                        ? <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] text-emerald-800">fenêtre ouverte</span>
                        : <span className="rounded bg-rose-100 px-1.5 py-0.5 text-[10px] text-rose-800" title="Le contact n'a pas écrit à cette ligne depuis 24 h : Meta refuse les messages libres">fenêtre fermée</span>}
                    </label>
                  );
                })}
              </div>
              <p className="mt-1 text-[11px] text-slate-500">{choisis.length} / {MAX_DESTINATAIRES} destinataire(s) choisi(s)</p>
            </div>

            {/* Destinataires hors fenêtre de 24 h : modèle approuvé ou ignorer */}
            {fermes.length > 0 && (
              <div className="rounded-lg bg-rose-50 p-2 text-sm" data-testid="transfert-fenetres-fermees">
                <p className="text-xs font-semibold text-rose-900">Fenêtre de 24 h fermée : Meta refusera un message libre. Que faire ?</p>
                {fermes.map((c) => (
                  <div key={c.id} className="mt-1 flex flex-wrap items-center gap-2">
                    <span className="flex-1 truncate">{c.nom}</span>
                    <select value={repli[c.id] || ""} onChange={(e) => setRepli((r) => ({ ...r, [c.id]: e.target.value }))} className="rounded border border-slate-300 px-2 py-0.5 text-xs">
                      <option value="">— choisir —</option>
                      <option value="modele">Envoyer un modèle approuvé</option>
                      <option value="ignorer">Ignorer ce destinataire</option>
                    </select>
                  </div>
                ))}
                {besoinModele && (
                  <label className="mt-2 block text-xs font-semibold">Modèle approuvé (le texte transféré va dans sa première variable)
                    <select value={modele ? `${modele.name}|${modele.language}` : ""} className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm"
                      onChange={(e) => setModele((modeles || []).find((x) => `${x.name}|${x.language}` === e.target.value) || null)}>
                      <option value="">{modeles === null ? "Patientez…" : "— choisir un modèle —"}</option>
                      {(modeles || []).map((x) => <option key={`${x.name}|${x.language}`} value={`${x.name}|${x.language}`}>{x.name} ({x.language})</option>)}
                    </select>
                  </label>
                )}
              </div>
            )}

            {/* Options : commentaire, origine, ligne d'envoi */}
            <label className="block text-xs font-semibold">Commentaire (facultatif, envoyé avant les messages)
              <textarea rows={2} value={commentaire} maxLength={1000} onChange={(e) => setCommentaire(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
            </label>
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="inline-flex items-center gap-2 text-sm">
                <input type="checkbox" checked={origine} onChange={(e) => setOrigine(e.target.checked)} />
                Indiquer l'origine (« Transféré de … : »)
              </label>
              <label className="block text-xs font-semibold">Ligne d'envoi
                <select value={ligneCle} onChange={(e) => setLigneCle(e.target.value)} className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm">
                  <option value="">Ligne de la conversation de chaque destinataire</option>
                  {lignes.map((l) => <option key={l.cle} value={l.cle}>{l.libelle}</option>)}
                </select>
              </label>
            </div>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={onClose} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm">Annuler</button>
              <button type="button" onClick={envoyer} disabled={envoi || !choisis.length} className="rounded-lg bg-sky-700 px-4 py-1.5 text-sm font-semibold text-white hover:bg-sky-800 disabled:opacity-50" data-testid="transfert-envoyer">
                {envoi ? <Jauge /> : "↪"} Transférer
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
