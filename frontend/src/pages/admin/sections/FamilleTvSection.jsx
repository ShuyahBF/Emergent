// FamilleTvSection.jsx — Lots 419-420 (420 : dossier du demandeur : téléphone, e-mail vérifié, IP, appareil, indicateurs de risque) : « Télé des familles » (Personnel de maison) — approbation des demandes d'accès et télés offertes.
// Règle du propriétaire (15/11/2026) : l'approbation de SAWALI est TOUJOURS exigée, même pour un seul téléviseur (comme pour l'agenda Google) ; l'abonnement
// n'est nécessaire qu'à partir de 2 télés simultanées (nombre de télés offertes réglable ici). Les formules payantes se créent dans « Formules des plateformes ».
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Tv, RefreshCw, Loader2, Check, X, ShieldCheck, Save, FileSearch } from "lucide-react";
import { Link } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";   // fenêtre modale (règle du 15/11/2026 : détails et corrections en modale)
import ThTri from "@/components/ThTri";            // règle 19 : toutes les colonnes triables
import { useTri } from "@/lib/tri";

// Niveau de risque : pastille de couleur ET texte (jamais la couleur seule)
const NIVEAUX = { faible: ["🟢 Faible", "bg-emerald-100 text-emerald-800"], moyen: ["🟠 Moyen", "bg-amber-100 text-amber-800"], eleve: ["🔴 Élevé", "bg-red-100 text-red-700"] };
const POIDS = { 0: "ℹ️", 1: "⚠️", 2: "⚠️", 3: "⛔" };
const ETATS = { attente: ["⏳ En attente", "bg-amber-100 text-amber-800"], accepte: ["✅ Acceptée", "bg-emerald-100 text-emerald-800"], refuse: ["⛔ Refusée", "bg-red-100 text-red-700"] };

// Degré de fiabilité d'une information du dossier (texte + pictogramme, jamais la couleur seule)
const FIAB = { verifie: ["✔ vérifié par code", "text-emerald-700"], constate: ["👁 relevé par SAWALI", "text-sky-700"], declare: ["✍ déclaré, non vérifiable", "text-amber-700"] };
function Fiab({ k, f }) { const x = FIAB[f?.[k]]; return x ? <span className={`ml-1 text-[11px] ${x[1]}`}>({x[0]})</span> : null; }

export default function FamilleTvSection() {
  const [etat, setEtat] = useState(null);
  const [chargement, setChargement] = useState(false);
  const [offertes, setOffertes] = useState("1");
  const [dossier, setDossier] = useState(null);           // dossier détaillé du demandeur ouvert (indicateurs, demandes liées)
  const tri = useTri(etat?.demandes || [], { quand: (d) => d.cree_le, nom: (d) => d.nom, lieu: (d) => d.lieu, etat: (d) => d.etat, postes: (d) => d.postes }, { cle: "quand", sens: "desc" });

  const charger = useCallback(async (annonce = true) => {
    setChargement(true);
    if (annonce) toast.info("Actualisation en cours…");                 // règle 17 : jamais d'actualisation silencieuse
    try {
      const { data } = await apiClient.get("/admin/famille-tv/etat");
      setEtat(data); setOffertes(String(data.postes_gratuits));
      if (annonce) toast.success(`${data.demandes.length} demande(s), ${data.postes_appaires} télé(s) appairée(s).`);
    } catch (e) { toast.error(e?.response?.data?.detail || "Lecture impossible"); }
    finally { setChargement(false); }
  }, []);
  useEffect(() => { charger(false); }, [charger]);

  const decider = async (d, decision) => {
    if (decision === "refuse" && d.etat === "accepte" && !window.confirm(`Retirer l'accès de ${d.nom || "cet appareil"} ? Ses télés seront déliées.`)) return;
    toast.info(decision === "accepte" ? "Acceptation en cours…" : "Refus en cours…");
    try { await apiClient.post(`/admin/famille-tv/demandes/${d.id}`, { decision }); toast.success(decision === "accepte" ? `Accès accepté pour ${d.nom || "l'appareil"}` : `Accès refusé pour ${d.nom || "l'appareil"}`); await charger(false); }
    catch (e) { toast.error(e?.response?.data?.detail || "Décision non enregistrée"); }
  };
  // Ouvre le dossier complet d'un demandeur (toast « en cours » puis résultat, règle 17)
  const ouvrirDossier = async (d) => {
    toast.info("Ouverture du dossier en cours…");
    try { const { data } = await apiClient.get(`/admin/famille-tv/demandes/${d.id}/dossier`); setDossier(data); toast.success(`Dossier de ${d.nom || "l'appareil"} : risque ${NIVEAUX[data.niveau]?.[0] || data.niveau}`); }
    catch (e) { toast.error(e?.response?.data?.detail || "Dossier illisible"); }
  };
  // Confirme le nouveau lieu d'une télé déplacée (la télé redevient utilisable) puis rouvre le dossier à jour
  const validerLieu = async (t) => {
    if (!window.confirm(`Confirmer le nouvel emplacement de « ${t.nom || "la télé"} » (${[t.observe?.ville, t.observe?.pays].filter(Boolean).join(", ")}) ?`)) return;
    toast.info("Confirmation du lieu en cours…");
    try { await apiClient.post(`/admin/famille-tv/ecrans/${t.id}/valider-lieu`); toast.success("Nouveau lieu confirmé : la télé est de nouveau utilisable"); const { data } = await apiClient.get(`/admin/famille-tv/demandes/${dossier.id}/dossier`); setDossier(data); await charger(false); }
    catch (e) { toast.error(e?.response?.data?.detail || "Confirmation impossible"); }
  };
  const regler = async (corps, message) => {
    toast.info("Enregistrement du réglage en cours…");
    try { await apiClient.put("/admin/famille-tv/reglages", corps); toast.success(message); await charger(false); }
    catch (e) { toast.error(e?.response?.data?.detail || "Réglage non enregistré"); }
  };

  return (
    <div className="space-y-3" data-testid="famille-tv">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-sky-100"><Tv className="h-4 w-4 text-sky-700" /></div>
        <div className="flex-1">
          <h3 className="text-sm font-semibold text-slate-800">Télé des familles (application Personnel de maison)</h3>
          <p className="text-xs text-slate-500">
            Le détenteur d'un téléphone projette des vidéos sur SA télé, lui seul la pilote. Chaque appareil doit d'abord <b>demander l'accès</b> : vous l'acceptez ou le refusez, même pour une seule télé.
            L'<b>abonnement</b> n'est nécessaire qu'à partir de 2 télés simultanées (formules dans <Link to="/admin/settings" className="underline">« Formules des plateformes »</Link>, fonction « Télé »).
            Les vidéos proposées se choisissent dans la télécommande vidéo (« Visible dans Personnel de maison »).
          </p>
        </div>
        <button type="button" onClick={() => charger(true)} disabled={chargement} title="Actualiser" aria-label="Actualiser la télé des familles"
                className="inline-flex items-center gap-1 rounded-lg border border-sky-300 px-3 py-1.5 text-xs font-semibold text-sky-800 hover:bg-sky-50">
          {chargement ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}Actualiser
        </button>
      </div>
      {etat && (<>
        <div className="flex flex-wrap items-center gap-4 rounded-lg border border-slate-200 p-3" data-testid="famille-tv-reglages">
          <span className="flex items-center gap-2 text-sm font-semibold text-slate-800"><ShieldCheck className="h-4 w-4 text-sky-700" />Approbation des appareils
            <button type="button" role="switch" aria-checked={etat.approbation} onClick={() => regler({ approbation: !etat.approbation }, etat.approbation ? "Approbation DÉSACTIVÉE : tout appareil peut utiliser la télé offerte" : "Approbation ACTIVÉE")}
                    className={`rounded-full border px-3 py-1 text-xs font-semibold ${etat.approbation ? "border-emerald-300 bg-emerald-50 text-emerald-800" : "border-slate-300 bg-slate-100 text-slate-600"}`}>
              {etat.approbation ? "Activée" : "Désactivée"}</button></span>
          <label className="flex items-center gap-2 text-sm text-slate-700">Télés offertes sans abonnement
            <input type="number" min={1} max={10} value={offertes} onChange={(e) => setOffertes(e.target.value)} className="w-16 rounded border border-slate-300 px-2 py-1" aria-label="Télés offertes" />
            <button type="button" onClick={() => regler({ postes_gratuits: Number(offertes) }, `${offertes} télé(s) offerte(s) par appareil (enregistré)`)}
                    disabled={Number(offertes) === etat.postes_gratuits} className="inline-flex items-center gap-1 rounded bg-sky-600 px-2 py-1 text-xs font-semibold text-white disabled:opacity-40"><Save className="h-3.5 w-3.5" />Enregistrer</button>
            {Number(offertes) !== etat.postes_gratuits && <span className="text-xs text-amber-700">modifié, non enregistré</span>}</label>
        </div>
        <div className="space-y-2" data-testid="famille-tv-demandes">
          <h4 className="text-sm font-semibold text-slate-800">Demandes d'accès</h4>
          {tri.lignes.length === 0 ? <p className="text-sm text-slate-500">Aucune demande pour l'instant.</p> : (
            <div className="max-h-96 overflow-auto"><table className="tableau w-full text-sm">
              <thead><tr className="text-left">
                <ThTri cle="quand" tri={tri.tri} onTri={tri.basculer}>Demande</ThTri><ThTri cle="nom" tri={tri.tri} onTri={tri.basculer}>Détenteur</ThTri>
                <ThTri cle="postes" tri={tri.tri} onTri={tri.basculer}>Télés</ThTri>
                <ThTri cle="etat" tri={tri.tri} onTri={tri.basculer}>État</ThTri><th className="p-2">Détails</th><th className="p-2" /></tr></thead>
              <tbody>{tri.lignes.map((d) => (
                <tr key={d.id} className="border-t border-slate-100">
                  <td className="whitespace-nowrap p-2 text-xs">{d.cree_le ? new Date(d.cree_le).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—"}</td>
                  <td className="p-2 font-medium">{d.nom || "—"}</td>
                  <td className="p-2 tabular-nums text-right">{d.postes}</td>
                  <td className="p-2"><span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${ETATS[d.etat]?.[1] || ""}`}>{ETATS[d.etat]?.[0] || d.etat}</span></td>
                  <td className="whitespace-nowrap p-2">
                    {/* Lien « Voir les détails » : ouvre la fenêtre du dossier (règle 20) ; la pastille donne le niveau de risque, jamais la couleur seule */}
                    <button type="button" onClick={() => ouvrirDossier(d)} title="Voir les détails venus avec la demande" aria-label={`Détails de la demande de ${d.nom || "l'appareil"}`} className="inline-flex items-center gap-1 text-xs font-semibold text-sky-700 underline"><FileSearch className="h-3.5 w-3.5" />{NIVEAUX[d.niveau]?.[0]?.split(" ")[0]} Voir les détails</button>
                    {d.alerte_tele && <span className="ml-2 rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700" title="Une télé de ce compte a changé de pays">📍 Télé déplacée</span>}
                  </td>
                  <td className="whitespace-nowrap p-2 text-right">
                    {d.etat !== "accepte" && <button type="button" onClick={() => decider(d, "accepte")} className="mr-2 inline-flex items-center gap-1 rounded bg-emerald-600 px-2 py-1 text-xs font-semibold text-white"><Check className="h-3.5 w-3.5" />Accepter</button>}
                    {d.etat !== "refuse" && <button type="button" onClick={() => decider(d, "refuse")} className="inline-flex items-center gap-1 rounded border border-red-300 px-2 py-1 text-xs font-semibold text-red-700"><X className="h-3.5 w-3.5" />{d.etat === "accepte" ? "Retirer l'accès" : "Refuser"}</button>}
                  </td></tr>))}</tbody>
            </table></div>)}
        </div>
        {/* Dossier du demandeur : FENÊTRE MODALE (max-w-xl, 85 % de la hauteur, défilement dans la fenêtre) au lieu d'allonger la page */}
        <Dialog open={!!dossier} onOpenChange={(ouvert) => { if (!ouvert) setDossier(null); }}>
          <DialogContent className="max-h-[85dvh] max-w-xl overflow-y-auto" data-testid="famille-tv-dossier">
            {dossier && (<>
              <DialogHeader><DialogTitle>Dossier de {dossier.nom || "l'appareil"} — risque <span className={`rounded-full px-2 py-0.5 text-xs ${NIVEAUX[dossier.niveau]?.[1] || ""}`}>{NIVEAUX[dossier.niveau]?.[0]}</span> (score {dossier.score})</DialogTitle></DialogHeader>
              {/* Chaque information porte son degré de fiabilité : seule la preuve compte, jamais la seule bonne foi */}
              <ul className="space-y-1 text-xs text-slate-700">
                <li>✉️ E-mail : <b>{dossier.email || "—"}</b> <Fiab k="email" f={dossier.fiabilite} /></li>
                <li>🌐 Connexion : <b>{dossier.ip || "—"}</b> — {[dossier.ip_infos?.ville, dossier.ip_infos?.pays, dossier.ip_infos?.fai].filter(Boolean).join(" · ") || "lieu inconnu"} <Fiab k="ip" f={dossier.fiabilite} /></li>
                <li>🕓 Compte créé le <b>{dossier.compte_cree_le ? new Date(dossier.compte_cree_le).toLocaleDateString("fr-FR") : "—"}</b> · proches vérifiés : <b>{dossier.liens_verifies}</b> <Fiab k="liens_verifies" f={dossier.fiabilite} /></li>
                <li>📱 Téléphone indiqué : <b>{[dossier.appareil?.marque, dossier.appareil?.modele].filter(Boolean).join(" ") || "—"}</b>{dossier.appareil?.android ? ` · Android ${dossier.appareil.android}` : ""} <Fiab k="appareil" f={dossier.fiabilite} /></li>
                {dossier.telephone && <li>📞 Numéro : <b>{dossier.telephone.e164}</b> <Fiab k="telephone" f={dossier.fiabilite} /></li>}
                {dossier.lieu && <li>🏠 Lieu indiqué : <b>{dossier.lieu}</b> <Fiab k="lieu" f={dossier.fiabilite} /></li>}
              </ul>
              <ul className="space-y-1" data-testid="famille-tv-indicateurs">
                {dossier.indicateurs.map((i) => <li key={i.code} className="text-xs text-slate-800">{POIDS[i.poids] || "•"} {i.texte}</li>)}
              </ul>
              {/* Télés de ce compte : lieu relevé par SAWALI lui-même (la demande part du téléphone, pas de la télé) */}
              <div className="space-y-1 rounded border border-slate-200 p-2" data-testid="famille-tv-teles">
                <p className="text-xs font-semibold text-slate-800">📺 Télés de ce compte (lieu relevé par SAWALI)</p>
                {(dossier.teles || []).length === 0 && <p className="text-xs text-slate-500">Aucune télé appairée pour l'instant : le lieu sera relevé à l'appairage.</p>}
                {(dossier.teles || []).map((t) => (
                  <div key={t.id} className="flex flex-wrap items-center gap-2 text-xs text-slate-700">
                    <b>{t.nom || "Télé"}</b>
                    <span>appairée : {[t.ancre?.ville, t.ancre?.pays].filter(Boolean).join(", ") || "lieu inconnu"}</span>
                    <span>· vue : {[t.observe?.ville, t.observe?.pays].filter(Boolean).join(", ") || "pas encore"}</span>
                    {t.deplacee
                      ? <><span className="rounded-full bg-red-100 px-2 py-0.5 font-semibold text-red-700">📍 Déplacée : commandes bloquées</span>
                          <button type="button" onClick={() => validerLieu(t)} className="inline-flex items-center gap-1 rounded bg-sky-600 px-2 py-1 font-semibold text-white"><Check className="h-3.5 w-3.5" />Confirmer ce nouveau lieu</button></>
                      : <span className="text-emerald-700">✔ même pays</span>}
                  </div>))}
              </div>
              {dossier.demandes_liees?.length > 0 && <p className="text-xs text-slate-700">🔗 Demandes liées : {dossier.demandes_liees.map((x) => `${x.nom || x.id} (${x.etat}; ${x.raison.join(", ")})`).join(" · ")}</p>}
              {/* Décision possible directement depuis le dossier (règle 15 : pictogramme + légende) */}
              <div className="flex flex-wrap justify-end gap-2 pt-2">
                {dossier.etat !== "accepte" && <button type="button" onClick={async () => { await decider(dossier, "accepte"); setDossier(null); }} className="inline-flex items-center gap-1 rounded bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white"><Check className="h-3.5 w-3.5" />Accepter</button>}
                {dossier.etat !== "refuse" && <button type="button" onClick={async () => { await decider(dossier, "refuse"); setDossier(null); }} className="inline-flex items-center gap-1 rounded border border-red-300 px-3 py-1.5 text-xs font-semibold text-red-700"><X className="h-3.5 w-3.5" />{dossier.etat === "accepte" ? "Retirer l'accès" : "Refuser"}</button>}
                <button type="button" onClick={() => setDossier(null)} className="inline-flex items-center gap-1 rounded border border-slate-300 px-3 py-1.5 text-xs"><X className="h-3.5 w-3.5" />Fermer</button>
              </div>
            </>)}
          </DialogContent>
        </Dialog>
        <p className="text-sm text-slate-700"><span className="font-semibold">{etat.postes_appaires}</span> télé(s) appairée(s) par des appareils « Personnel de maison ».</p>
      </>)}
    </div>
  );
}
