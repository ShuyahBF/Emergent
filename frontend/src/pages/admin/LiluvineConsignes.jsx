// ============================================================================
// LiluvineConsignes.jsx — Lot 454 : sous-menu Liluvine « Consignes ».
// On écrit une phrase comme à une vraie secrétaire (« Ce matin, pour tout appel au sujet de RDV, informe que je ne suis pas disponible »).
// SAWALI la COMPREND et la MONTRE (nature, texte, dates de début et de fin modifiables) : RIEN n'est actif avant le clic sur « Valider ».
// Une consigne active est ajoutée aux instructions de Liluvine (WhatsApp, appels, agenda, chat) jusqu'à sa date de fin, ou jusqu'à « Arrêter ».
// Accès : administrateur, et superviseur auquel l'élément « Consignes à Liluvine » est partagé. Heures en UTC = heure du Burkina Faso.
// Backend : GET/POST /api/admin/liluvine-consignes, POST …/interpreter, POST …/{id}/arreter.
// ============================================================================
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, Check, RefreshCw, Sparkles, StopCircle, Users, X } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const EXEMPLES = [
  "Ce matin, pour tout appel au sujet de RDV, informe que je ne suis pas disponible.",
  "Jusqu'à lundi prochain, aucune demande d'intervention n'est acceptée entre 12h et 13h.",
  "Envoie un message à tous les RDV pour informer d'un décalage d'1h dans l'heure prévue.",
];
const COLONNES = [["etat", "État"], ["resume", "Consigne"], ["nature", "Nature"], ["debut", "Début"], ["fin", "Fin"], ["creee_par", "Donnée par"]];

// « 2026-11-25T08:00 » → « 25/11/2026 08:00 »
const joliDate = (t) => { const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2})/.exec(t || ""); return m ? `${m[3]}/${m[2]}/${m[1]} ${m[4]}` : "—"; };
// État affiché d'une consigne (texte ET couleur : jamais la couleur seule)
function etatDe(c) {
  if (c.statut === "arretee") return { cle: "4 arrêtée", texte: "Arrêtée", classe: "bg-slate-100 text-slate-700" };
  if (c.active_maintenant) return { cle: "1 active", texte: "● Active maintenant", classe: "bg-emerald-100 text-emerald-800" };
  const maintenant = new Date().toISOString().slice(0, 16);
  if ((c.debut || "") > maintenant) return { cle: "2 planifiée", texte: "◔ Planifiée", classe: "bg-sky-100 text-sky-800" };
  return { cle: "3 terminée", texte: "✓ Terminée", classe: "bg-amber-100 text-amber-800" };
}

export default function LiluvineConsignes() {
  const [donnees, setDonnees] = useState(null);          // null = chargement
  const [texte, setTexte] = useState("");
  const [apercu, setApercu] = useState(null);              // lot 456 : aperçu d'un envoi en masse (qui, combien, quel texte), en attente de confirmation
  const [proposition, setProposition] = useState(null);  // ce que SAWALI a compris, en attente de validation
  const [enCours, setEnCours] = useState(false);
  const [tri, setTri] = useState({ cle: "debut", sens: -1 });

  const charger = useCallback(async (annonce = true) => {
    if (annonce) toast("Actualisation des consignes en cours…");
    try { const r = await apiClient.get("/admin/liluvine-consignes"); setDonnees(r.data); if (annonce) toast.success(`${r.data.consignes.length} consigne(s) relue(s).`); }
    catch (e) { setDonnees({ erreur: e?.response?.data?.detail || "Lecture impossible", consignes: [] }); toast.error("Lecture impossible"); }
  }, []);
  useEffect(() => { charger(false); }, [charger]);

  const comprendre = async () => {
    setEnCours(true); toast("Liluvine comprend votre consigne…");
    try {
      const r = await apiClient.post("/admin/liluvine-consignes/interpreter", { texte });
      setProposition(r.data);
      toast.success(r.data.ia ? "Voici ce que Liluvine a compris." : "Proposition prête (sans IA : votre phrase est reprise telle quelle).");
    } catch (e) { toast.error(e?.response?.data?.detail || "Compréhension impossible"); }
    finally { setEnCours(false); }
  };
  // Lot 456.1 — suivi des envois en masse (derniers envois, résultats, détail des échecs)
  const [envois, setEnvois] = useState(null);
  const [detailEnvoi, setDetailEnvoi] = useState(null);
  const chargerEnvois = useCallback(async (annonce = false) => {
    if (annonce) toast("Actualisation des envois en cours…");
    try { const r = await apiClient.get("/admin/liluvine-consignes/masse/envois"); setEnvois(r.data.envois); if (annonce) toast.success(`${r.data.envois.length} envoi(s) relu(s).`); }
    catch (e) { setEnvois([]); if (annonce) toast.error("Lecture des envois impossible"); }
  }, []);
  useEffect(() => { chargerEnvois(false); }, [chargerEnvois]);
  // Lot 456 — envoi en masse : 1) APERÇU (rien ne part)  2) CONFIRMATION de l'aperçu vu  3) envoi en arrière-plan
  const preparerEnvoi = async () => {
    setEnCours(true); toast("Préparation de l'aperçu en cours…");
    try {
      const r = await apiClient.post("/admin/liluvine-consignes/masse/apercu", { message: proposition.message || proposition.instruction, rdv_du: proposition.rdv_du, rdv_au: proposition.rdv_au });
      setApercu(r.data); toast.success(`Aperçu prêt : ${r.data.total} destinataire(s). Rien n'est encore envoyé.`);
    } catch (e) { toast.error(e?.response?.data?.detail || "Aperçu impossible"); }
    finally { setEnCours(false); }
  };
  const confirmerEnvoi = async () => {
    setEnCours(true); toast("Lancement de l'envoi en cours…");
    try {
      const r = await apiClient.post("/admin/liluvine-consignes/masse/confirmer", { apercu_id: apercu.id, empreinte: apercu.empreinte });
      toast.success(`Envoi lancé pour ${r.data.lot.total} destinataire(s) : il se poursuit en arrière-plan.`); setApercu(null); setProposition(null); setTexte(""); chargerEnvois(false);
    } catch (e) { toast.error(e?.response?.data?.detail || "Envoi impossible"); }
    finally { setEnCours(false); }
  };
  const valider = async () => {
    setEnCours(true); toast("Activation de la consigne en cours…");
    try { await apiClient.post("/admin/liluvine-consignes", { ...proposition, texte }); toast.success("Consigne activée : Liluvine l'applique dès maintenant."); setProposition(null); setTexte(""); await charger(false); }
    catch (e) { toast.error(e?.response?.data?.detail || "Activation impossible"); }
    finally { setEnCours(false); }
  };
  const arreter = async (c) => {
    if (!window.confirm("Arrêter cette consigne tout de suite ? Liluvine reprendra son comportement habituel.")) return;
    try { await apiClient.post(`/admin/liluvine-consignes/${c.id}/arreter`); toast.success("Consigne arrêtée."); await charger(false); }
    catch (e) { toast.error(e?.response?.data?.detail || "Arrêt impossible"); }
  };

  const lignes = useMemo(() => {
    const l = (donnees?.consignes || []).map((c) => ({ ...c, etat: etatDe(c).cle }));
    l.sort((a, b) => {
      const va = a[tri.cle] || "", vb = b[tri.cle] || "";
      if (!va && vb) return 1;                            // les valeurs vides restent en dernier
      if (va && !vb) return -1;
      return String(va).localeCompare(String(vb), "fr", { sensitivity: "base" }) * tri.sens;
    });
    return l;
  }, [donnees, tri]);
  const entete = (cle, titre) => (
    <th key={cle} className="px-2 py-2 text-left font-semibold cursor-pointer select-none" onClick={() => setTri((t) => ({ cle, sens: t.cle === cle ? -t.sens : 1 }))}>
      <span className={tri.cle === cle ? "text-orange-600" : ""}>{titre}</span>{" "}
      {tri.cle === cle ? (tri.sens === 1 ? <ArrowUp className="inline w-3 h-3" /> : <ArrowDown className="inline w-3 h-3" />) : <ArrowUpDown className="inline w-3 h-3 text-slate-400" />}
    </th>);

  if (!donnees) return <p className="p-4 text-sm text-slate-500">Chargement…</p>;
  if (donnees.erreur) return <p className="p-4 text-sm text-red-700">{donnees.erreur}</p>;
  const nonAppliquee = proposition && !proposition.appliquee && !proposition.envoi_masse;
  return (
    <div className="space-y-4 p-4" data-testid="liluvine-consignes">
      <div>
        <h1 className="text-xl font-bold text-slate-900">💬 Consignes à Liluvine</h1>
        <p className="text-sm text-slate-600 mt-1">Donnez vos instructions comme à une vraie secrétaire. Liluvine les comprend, vous les montre, et ne les applique qu'après votre « Valider ». Heures en heure de Ouagadougou (UTC).</p>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-3 space-y-2">
        <label className="text-sm font-semibold text-slate-800" htmlFor="consigne-texte">Votre consigne</label>
        <textarea id="consigne-texte" value={texte} onChange={(e) => setTexte(e.target.value)} rows={3} maxLength={1500}
          placeholder="Ex. : Ce matin, pour tout appel au sujet de RDV, informe que je ne suis pas disponible." className="w-full rounded-lg border border-slate-300 p-2 text-sm" data-testid="consigne-texte" />
        <div className="flex flex-wrap gap-1">
          {EXEMPLES.map((e) => <button key={e} type="button" onClick={() => setTexte(e)} className="rounded-full border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-50">{e.length > 62 ? `${e.slice(0, 60)}…` : e}</button>)}
        </div>
        <button type="button" onClick={comprendre} disabled={enCours || texte.trim().length < 3} data-testid="consigne-comprendre"
          className="inline-flex items-center gap-1 rounded-full bg-sky-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"><Sparkles className="w-4 h-4" /> Faire comprendre à Liluvine</button>
      </div>

      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-slate-900">Consignes données</h2>
        <button type="button" onClick={() => charger(true)} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1 text-sm"><RefreshCw className="w-4 h-4" /> Actualiser</button>
      </div>
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-slate-700"><tr>{COLONNES.map(([c, t]) => entete(c, t))}<th className="px-2 py-2 text-left">Action</th></tr></thead>
          <tbody>
            {lignes.length === 0 && <tr><td colSpan={7} className="px-3 py-4 text-slate-500">Aucune consigne pour le moment.</td></tr>}
            {lignes.map((c) => { const e = etatDe(c); return (
              <tr key={c.id} className="border-t hover:bg-sky-400/15">
                <td className="px-2 py-2"><span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${e.classe}`}>{e.texte}</span></td>
                <td className="px-2 py-2 max-w-md">{c.resume || c.instruction}</td>
                <td className="px-2 py-2 text-xs">{donnees.natures?.[c.nature] || c.nature}</td>
                <td className="px-2 py-2 whitespace-nowrap">{joliDate(c.debut)}</td>
                <td className="px-2 py-2 whitespace-nowrap">{joliDate(c.fin)}</td>
                <td className="px-2 py-2">{c.creee_par || "—"}</td>
                <td className="px-2 py-2">{c.statut === "active" && <button type="button" onClick={() => arreter(c)} className="inline-flex items-center gap-1 rounded-full border border-red-300 px-2 py-0.5 text-xs text-red-700"><StopCircle className="w-3 h-3" /> Arrêter</button>}</td>
              </tr>); })}
          </tbody>
        </table>
      </div>

      {/* Fenêtre « Ce que Liluvine a compris » : dimensions de la règle 11, défilement dans la fenêtre */}
      <section className="rounded-xl border border-slate-200 bg-white p-3" data-testid="envois-masse">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-base font-bold">📣 Envois en masse</h2>
          <button type="button" onClick={() => chargerEnvois(true)} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1 text-sm"><RefreshCw className="w-4 h-4" /> Actualiser</button>
        </div>
        {!envois ? <p className="text-sm text-slate-500 mt-2">Lecture en cours…</p> : envois.length === 0 ? <p className="text-sm text-slate-500 mt-2">Aucun envoi en masse pour le moment.</p> : (
          <div className="mt-2 overflow-x-auto"><table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-slate-500"><th className="px-2 py-1">Date</th><th className="px-2 py-1">Message</th><th className="px-2 py-1 text-right">Prévus</th><th className="px-2 py-1 text-right">Texte libre</th><th className="px-2 py-1 text-right">Modèle</th><th className="px-2 py-1 text-right">Non envoyés</th><th className="px-2 py-1 text-right">Échecs</th><th className="px-2 py-1">État</th><th className="px-2 py-1"></th></tr></thead>
            <tbody>{envois.map((e) => (
              <tr key={e.id} className="border-t" data-testid="envoi-masse">
                <td className="px-2 py-1 whitespace-nowrap">{(e.confirme_le || "").slice(0, 16).replace("T", " ")}</td>
                <td className="px-2 py-1 max-w-xs truncate" title={e.message}>{e.message}</td>
                <td className="px-2 py-1 text-right tabular-nums">{e.total}</td>
                <td className="px-2 py-1 text-right tabular-nums text-emerald-700">{e.envoyes}</td>
                <td className="px-2 py-1 text-right tabular-nums text-sky-700">{e.par_modele || 0}</td>
                <td className="px-2 py-1 text-right tabular-nums text-amber-700">{e.hors_fenetre}</td>
                <td className="px-2 py-1 text-right tabular-nums text-red-700">{e.echecs}</td>
                <td className="px-2 py-1">{e.termine ? "✅ terminé" : "⏳ en cours"}</td>
                <td className="px-2 py-1">{(e.details || []).length > 0 && <button type="button" onClick={() => setDetailEnvoi(e)} className="text-xs underline">Détail</button>}</td>
              </tr>))}</tbody></table></div>
        )}
      </section>
      {proposition && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-3" role="dialog" aria-modal="true" aria-label="Ce que Liluvine a compris">
          <div className="w-full max-w-xl max-h-[85dvh] overflow-y-auto rounded-2xl bg-white p-4 space-y-3" data-testid="consigne-proposition">
            <h3 className="text-lg font-bold text-slate-900">Ce que Liluvine a compris</h3>
            <p className="text-xs text-slate-500">« {texte} »</p>
            <p className="text-sm"><b>Nature :</b> {donnees.natures?.[proposition.nature]}</p>
            {nonAppliquee && <p className="rounded-lg bg-amber-50 p-2 text-sm text-amber-900" role="alert">⚠️ Cette nature de consigne n'est pas encore appliquée par SAWALI (prochain lot) : elle ne peut pas être activée pour le moment. Reformulez-la comme une réponse de Liluvine, ou attendez le prochain lot.</p>}
            <label className="block text-sm font-semibold">Ce que Liluvine fera
              <textarea value={proposition.instruction} onChange={(e) => setProposition({ ...proposition, instruction: e.target.value, resume: e.target.value.slice(0, 200) })} rows={3} className="mt-1 w-full rounded-lg border border-slate-300 p-2 text-sm font-normal" />
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <label className="text-sm font-semibold">Début<input type="datetime-local" value={proposition.debut} onChange={(e) => setProposition({ ...proposition, debut: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 p-2 text-sm font-normal" /></label>
              <label className="text-sm font-semibold">Fin<input type="datetime-local" value={proposition.fin} onChange={(e) => setProposition({ ...proposition, fin: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 p-2 text-sm font-normal" /></label>
            </div>
            {proposition.nature === "blocage" && (
              <div className="grid grid-cols-2 gap-2" data-testid="consigne-creneau">
                <label className="text-sm font-semibold">Créneau bloqué : de<input type="time" value={proposition.creneau_debut || ""} onChange={(e) => setProposition({ ...proposition, creneau_debut: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 p-2 text-sm font-normal" /></label>
                <label className="text-sm font-semibold">à<input type="time" value={proposition.creneau_fin || ""} onChange={(e) => setProposition({ ...proposition, creneau_fin: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 p-2 text-sm font-normal" /></label>
              </div>
            )}
            {proposition.envoi_masse && (
              <div className="space-y-2 rounded-lg bg-sky-50 p-2" data-testid="consigne-masse">
                <p className="text-sm text-sky-900">📣 Envoi à un groupe : rien ne part avant que vous ayez vu la liste des destinataires et confirmé.</p>
                <label className="block text-sm font-semibold">Message à envoyer
                  <textarea value={proposition.message || ""} onChange={(e) => setProposition({ ...proposition, message: e.target.value })} rows={3} className="mt-1 w-full rounded-lg border border-slate-300 p-2 text-sm font-normal" /></label>
                <div className="grid grid-cols-2 gap-2">
                  <label className="text-sm font-semibold">RDV du<input type="date" value={proposition.rdv_du || ""} onChange={(e) => setProposition({ ...proposition, rdv_du: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 p-2 text-sm font-normal" /></label>
                  <label className="text-sm font-semibold">au<input type="date" value={proposition.rdv_au || ""} onChange={(e) => setProposition({ ...proposition, rdv_au: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 p-2 text-sm font-normal" /></label>
                </div>
                <button type="button" onClick={preparerEnvoi} disabled={enCours} data-testid="consigne-apercu-masse"
                  className="inline-flex items-center gap-1 rounded-full bg-sky-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"><Users className="w-4 h-4" /> Voir les destinataires</button>
              </div>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <button type="button" onClick={() => setProposition(null)} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-4 py-2 text-sm"><X className="w-4 h-4" /> Annuler</button>
              <button type="button" onClick={valider} disabled={enCours || nonAppliquee || proposition.envoi_masse || !proposition.instruction.trim()} data-testid="consigne-valider"
                className="inline-flex items-center gap-1 rounded-full bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"><Check className="w-4 h-4" /> Valider et activer</button>
            </div>
          </div>
        </div>
      )}
      {apercu && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-3" role="dialog" aria-modal="true">
          <div className="w-full max-w-xl max-h-[85dvh] overflow-y-auto rounded-2xl bg-white p-4 space-y-3" data-testid="masse-apercu">
            <h2 className="text-lg font-bold">📣 Confirmer l'envoi à {apercu.total} personne(s)</h2>
            <p className="rounded-lg bg-slate-50 p-2 text-sm whitespace-pre-wrap">{apercu.message}</p>
            <p className="text-xs text-slate-600">Rendez-vous du {apercu.du} au {apercu.au}. Exclus : {apercu.exclus.sans_numero} sans numéro, {apercu.exclus.bloques} bloqués (liste noire), {apercu.exclus.annules} annulés, {apercu.exclus.doublons} doublon(s). WhatsApp n'accepte le texte libre que si la personne a écrit depuis moins de 24 h : les autres seront listées « non envoyé ».</p>
            <table className="w-full text-sm"><thead><tr className="text-left text-xs text-slate-500"><th>Nom</th><th>Numéro</th><th>RDV</th></tr></thead>
              <tbody>{apercu.destinataires.map((d, i) => <tr key={i} className="border-t"><td>{d.nom}</td><td className="tabular-nums">{d.telephone}</td><td className="tabular-nums">{d.quand}</td></tr>)}</tbody></table>
            <div className="flex flex-wrap justify-end gap-2">
              <button type="button" onClick={() => setApercu(null)} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold"><X className="w-4 h-4" /> Annuler</button>
              <button type="button" onClick={confirmerEnvoi} disabled={enCours} data-testid="masse-confirmer" className="inline-flex items-center gap-1 rounded-full bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"><Check className="w-4 h-4" /> Confirmer et envoyer</button>
            </div>
          </div>
        </div>
      )}
      {detailEnvoi && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-3" role="dialog" aria-modal="true">
          <div className="w-full max-w-xl max-h-[85dvh] overflow-y-auto rounded-2xl bg-white p-4 space-y-3" data-testid="envoi-detail">
            <h2 className="text-lg font-bold">Détail de l'envoi</h2>
            <p className="rounded-lg bg-slate-50 p-2 text-sm whitespace-pre-wrap">{detailEnvoi.message}</p>
            <table className="w-full text-sm"><tbody>{detailEnvoi.details.map((d, i) => <tr key={i} className="border-t"><td className="py-1 tabular-nums">{d.tel}</td><td className="py-1">{d.etat}</td></tr>)}</tbody></table>
            <div className="flex justify-end"><button type="button" onClick={() => setDetailEnvoi(null)} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold"><X className="w-4 h-4" /> Fermer</button></div>
          </div>
        </div>
      )}
    </div>
  );
}
