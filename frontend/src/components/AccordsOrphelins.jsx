/*
  Lot 204 — « Accords sans fiche » (administration, page Carrousel WhatsApp).

  Des personnes ont confirmé (bouton « Confirmer », mot-clé) alors que leur numéro ne figure sur aucune fiche : elles ont
  sans doute changé de numéro. Leur accord est bien tracé, mais elles ne reçoivent rien. Cet écran permet, pour chacune :
    1. de choisir le client de la liste auquel rattacher sa fiche (nom modifiable) ;
    2. de créer la fiche — l'accord est repris tel qu'il a été donné (date et moyen d'origine) ;
    3. d'envoyer le carrousel choisi (campagne terminée à laquelle on ajoute ces personnes : elle repart pour elles seules).
  API : GET /admin/whatsapp/carrousel/accords-orphelins, POST …/accords-orphelins/rattacher
  (backend/routes/carrousel_accords_orphelins.py, carrousel_whatsapp.py).
*/
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { Button } from "@/components/ui/button";

const champ = "rounded-md border border-slate-300 bg-white px-2 py-1 text-xs";
const dateFr = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");
const MOYENS = { bouton: "bouton de la demande d'accord", "mot-clé": "mot-clé", lien: "lien d'accord" };

export default function AccordsOrphelins({ onCompte }) {   // onCompte(n) : nombre d'éléments à traiter (la page choisit son onglet d'après lui)
  const [donnees, setDonnees] = useState(null);          // {orphelins, clients, campagnes}
  const [choix, setChoix] = useState({});                // téléphone → { coche, client_id, nom }
  const [clientTous, setClientTous] = useState("");      // client appliqué à toutes les lignes cochées
  const [campagne, setCampagne] = useState("");          // carrousel à envoyer ("" = rattacher seulement)
  const [occupe, setOccupe] = useState(false);

  const [coches, setCoches] = useState({});            // lot 206 : clics à valider cochés (téléphone → true)
  const lire = useCallback(async () => {
    try {
      const { data } = await apiClient.get("/admin/whatsapp/carrousel/accords-orphelins");
      setDonnees(data);
      onCompte?.((data.orphelins || []).length + (data.clics || []).length);
      setCampagne((c) => c || data.campagnes?.[0]?.id || "");
      setChoix((anc) => Object.fromEntries((data.orphelins || []).map((o) => [o.telephone, anc[o.telephone] || { coche: false, client_id: "", nom: o.nom || "" }])));
    } catch { setDonnees({ orphelins: [], clients: [], campagnes: [] }); onCompte?.(0); }
  }, [onCompte]);
  useEffect(() => { lire(); }, [lire]);

  const clics = donnees?.clics || [];
  if (!donnees || (donnees.orphelins.length === 0 && clics.length === 0)) return null;   // rien à traiter : l'encart n'apparaît pas

  const maj = (tel, patch) => setChoix((c) => ({ ...c, [tel]: { ...c[tel], ...patch } }));
  const cochees = donnees.orphelins.filter((o) => choix[o.telephone]?.coche);
  const toutCocher = (v) => setChoix((c) => Object.fromEntries(Object.entries(c).map(([t, x]) => [t, { ...x, coche: v }])));
  const appliquerClient = (id) => {
    setClientTous(id);
    setChoix((c) => Object.fromEntries(Object.entries(c).map(([t, x]) => [t, x.coche ? { ...x, client_id: id } : x])));
  };

  // Lot 206 — clics « Confirmer » reçus sans accord noté : validation en UNE fois (accord noté + carrousel envoyé)
  const clicsCoches = clics.filter((c) => coches[c.telephone]);
  const validerClics = async (envoyer) => {
    if (clicsCoches.length === 0) { toast.error("Cochez au moins une personne."); return; }
    if (envoyer && !campagne) { toast.error("Choisissez le carrousel à envoyer."); return; }
    if (!window.confirm(`Ces ${clicsCoches.length} personne(s) ont cliqué sur le bouton de la demande d'accord. Valider leur accord`
      + (envoyer ? " et leur envoyer le carrousel" : "") + " ?")) return;
    setOccupe(true);
    const attente = toast.loading("Patientez… validation des accords" + (envoyer ? " et envoi du carrousel" : ""));
    try {
      const { data } = await apiClient.post("/admin/whatsapp/carrousel/clics-a-valider/valider", {
        telephones: clicsCoches.map((c) => c.telephone), campagne_id: envoyer ? campagne : null,
      }, { timeout: 60000 });
      const msg = [`${data.valides.length} accord(s) validé(s)`];
      if (data.envoi?.destinataires) msg.push(`carrousel en cours d'envoi à ${data.envoi.destinataires} personne(s)`);
      if (data.envoi?.erreur) toast.error(data.envoi.erreur);
      if (data.sans_fiche) msg.push(`${data.sans_fiche} sans fiche : choisissez leur client plus bas`);
      toast.success(msg.join(" ; "), { id: attente });
      setCoches({});
      await lire();
    } catch (e) {
      toast.error(e?.response?.data?.detail || (e?.response ? `Validation impossible (erreur serveur ${e.response.status})` : "Validation impossible : serveur injoignable"), { id: attente });
    } finally { setOccupe(false); }
  };

  const valider = async (envoyer) => {
    const sansClient = cochees.filter((o) => !choix[o.telephone].client_id);
    if (cochees.length === 0) { toast.error("Cochez au moins une personne."); return; }
    if (sansClient.length) { toast.error(`Choisissez un client pour ${sansClient.length} personne(s).`); return; }
    if (envoyer && !campagne) { toast.error("Choisissez le carrousel à envoyer."); return; }
    setOccupe(true);
    const attente = toast.loading("Patientez… création des fiches" + (envoyer ? " et envoi du carrousel" : ""));
    try {
      const { data } = await apiClient.post("/admin/whatsapp/carrousel/accords-orphelins/rattacher", {
        items: cochees.map((o) => ({ telephone: o.telephone, client_id: choix[o.telephone].client_id, nom: choix[o.telephone].nom })),
        campagne_id: envoyer ? campagne : null,
      }, { timeout: 60000 });
      const msg = [`${data.crees.length} fiche(s) créée(s)`];
      if (data.envoi?.destinataires) msg.push(`carrousel en cours d'envoi à ${data.envoi.destinataires} personne(s)`);
      if (data.envoi?.erreur) toast.error(data.envoi.erreur);
      if (data.refuses?.length) toast.error(`${data.refuses.length} refusée(s) : ${data.refuses[0].motif}`);
      toast.success(msg.join(" ; "), { id: attente });
      await lire();
    } catch (e) {
      toast.error(e?.response?.data?.detail || (e?.response ? `Rattachement impossible (erreur serveur ${e.response.status})` : "Rattachement impossible : serveur injoignable"), { id: attente });
    } finally { setOccupe(false); }
  };

  const selecteurCampagne = (
    <select className={`${champ} max-w-[18rem]`} value={campagne} onChange={(e) => setCampagne(e.target.value)} data-testid="orphelins-campagne">
      <option value="">— Carrousel à envoyer —</option>
      {donnees.campagnes.map((c) => <option key={c.id} value={c.id}>{dateFr(c.cree_le)} · {c.libelle || "(sans message)"} ({c.total})</option>)}
    </select>
  );
  const blocClics = clics.length > 0 && (
    <div className="space-y-2 rounded-md border border-emerald-300 bg-emerald-50/70 p-3 text-xs text-slate-700" data-testid="clics-a-valider">
      <p className="font-semibold text-emerald-900">
        ✅ {clics.length} personne(s) ont cliqué sur « Confirmer » mais leur accord n'est pas noté
      </p>
      <p>Validez-les d'un coup au lieu de les chercher une à une : l'accord est noté sur leur fiche avec la date du clic.
        <b> Décochez les personnes dont le bouton ne concernait pas une demande d'accord</b> (par exemple la confirmation d'une commande).</p>
      <div className="max-h-56 overflow-y-auto rounded-md border border-emerald-200 bg-white">
        <table className="w-full text-xs">
          <tbody>
            {clics.map((c) => (
              <tr key={c.telephone} className="border-t border-slate-100" aria-selected={coches[c.telephone] ? "true" : undefined}>
                <td className="px-2 py-1"><input type="checkbox" checked={!!coches[c.telephone]} onChange={(e) => setCoches((x) => ({ ...x, [c.telephone]: e.target.checked }))} /></td>
                <td className="px-2 py-1 font-medium">{c.nom || "(sans nom)"}</td>
                <td className="px-2 py-1 font-mono">+{c.telephone}</td>
                <td className="px-2 py-1 text-slate-500">« {c.texte} » · {dateFr(c.le)}</td>
                <td className="px-2 py-1">{c.sans_fiche ? <span className="text-amber-700">sans fiche</span> : <span className="text-emerald-700">fiche trouvée</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center gap-2 boutons-distincts">
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={clicsCoches.length === clics.length} onChange={(e) => setCoches(Object.fromEntries(clics.map((c) => [c.telephone, e.target.checked])))} data-testid="clics-tout" />
          Tout cocher
        </label>
        {selecteurCampagne}
        <Button type="button" size="sm" disabled={occupe || clicsCoches.length === 0} onClick={() => validerClics(true)} data-testid="clics-valider-envoyer">
          Valider {clicsCoches.length ? `(${clicsCoches.length}) ` : ""}et envoyer le carrousel
        </Button>
        <Button type="button" size="sm" variant="outline" disabled={occupe || clicsCoches.length === 0} onClick={() => validerClics(false)} data-testid="clics-valider">
          Valider seulement
        </Button>
      </div>
    </div>
  );
  if (donnees.orphelins.length === 0) return <div className="space-y-2">{blocClics}</div>;

  return (
    <div className="space-y-2">
    {blocClics}
    <div className="space-y-2 rounded-md border border-amber-300 bg-amber-50/60 p-3 text-xs text-slate-700" data-testid="accords-orphelins">
      <p className="font-semibold text-amber-900">
        ⚠ {donnees.orphelins.length} personne(s) ont accepté mais n'ont aucune fiche (numéro changé ?)
      </p>
      <p>
        Leur accord est tracé, mais sans fiche elles ne reçoivent pas le carrousel. Choisissez le client de la liste auquel
        rattacher chaque personne : la fiche est créée avec l'accord d'origine (date et moyen), puis le carrousel choisi peut leur être envoyé.
      </p>
      <div className="flex flex-wrap items-center gap-2 boutons-distincts">
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={cochees.length === donnees.orphelins.length} onChange={(e) => toutCocher(e.target.checked)} data-testid="orphelins-tout" />
          Tout cocher
        </label>
        <select className={`${champ} max-w-[16rem]`} value={clientTous} onChange={(e) => appliquerClient(e.target.value)} data-testid="orphelins-client-tous">
          <option value="">Même client pour la sélection…</option>
          {donnees.clients.map((c) => <option key={c.id} value={c.id}>{c.nom}{c.code ? ` (${c.code})` : ""}</option>)}
        </select>
      </div>
      <div className="max-h-72 overflow-y-auto rounded-md border border-amber-200 bg-white">
        <table className="w-full text-xs">
          <thead className="bg-amber-50 text-left uppercase text-slate-600">
            <tr><th className="px-2 py-1" /><th className="px-2 py-1">Numéro</th><th className="px-2 py-1">Nom</th><th className="px-2 py-1">Accord</th><th className="px-2 py-1">Client</th></tr>
          </thead>
          <tbody>
            {donnees.orphelins.map((o) => {
              const c = choix[o.telephone] || {};
              return (
                <tr key={o.telephone} className="border-t border-slate-100" aria-selected={c.coche ? "true" : undefined} data-testid={`orphelin-${o.telephone}`}>
                  <td className="px-2 py-1"><input type="checkbox" checked={!!c.coche} onChange={(e) => maj(o.telephone, { coche: e.target.checked })} /></td>
                  <td className="px-2 py-1 font-mono">+{o.telephone}</td>
                  <td className="px-2 py-1"><input className={`${champ} w-36`} value={c.nom || ""} placeholder="Nom (facultatif)" onChange={(e) => maj(o.telephone, { nom: e.target.value })} /></td>
                  <td className="px-2 py-1 text-slate-500">{dateFr(o.le)} · {MOYENS[o.moyen] || o.moyen}</td>
                  <td className="px-2 py-1">
                    <select className={`${champ} max-w-[14rem]`} value={c.client_id || ""} onChange={(e) => maj(o.telephone, { client_id: e.target.value })}>
                      <option value="">Choisir un client…</option>
                      {donnees.clients.map((cl) => <option key={cl.id} value={cl.id}>{cl.nom}</option>)}
                    </select>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center gap-2 boutons-distincts">
        {selecteurCampagne}
        <Button type="button" size="sm" disabled={occupe || cochees.length === 0} onClick={() => valider(true)} data-testid="orphelins-rattacher-envoyer">
          Rattacher {cochees.length ? `(${cochees.length}) ` : ""}et envoyer le carrousel
        </Button>
        <Button type="button" size="sm" variant="outline" disabled={occupe || cochees.length === 0} onClick={() => valider(false)} data-testid="orphelins-rattacher">
          Rattacher seulement
        </Button>
      </div>
    </div>
    </div>
  );
}
