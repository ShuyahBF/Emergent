// =====================================================================
// Lot 161 — Rubrique des Paramètres « 👥 Contacts des plateformes » : SAWALI récupère les contacts de chaque plateforme
// (ZandGo, portail e-Kol, adLyn…) et les range dans un groupe « Plateforme X » de l'annuaire, pour des messages WhatsApp
// de masse ou des carrousels.
//   GET /api/admin/contacts-plateformes                       état de chaque plateforme
//   PUT /api/admin/contacts-plateformes/{id}                  adresse + activation
//   POST /api/admin/contacts-plateformes/{id}/synchroniser    synchronisation immédiate (sinon chaque nuit à 03 h 20)
// La clé partagée n'est JAMAIS saisie ici : variable CONTACTS_HMAC_<PLATEFORME> sur Render (le tableau montre si elle est saisie).
// Consentement : un contact importé ne reçoit un carrousel qu'après son propre accord (colonne « Consentants »).
// =====================================================================
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const dateCourte = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");

export default function ContactsPlateformesSection() {
  const [etat, setEtat] = useState(null);          // réponse du serveur
  const [saisie, setSaisie] = useState({});        // adresses et activations en cours de saisie : { id: { url, actif } }
  const [occupe, setOccupe] = useState("");        // identifiant de la plateforme en cours de traitement

  const appliquer = (d) => {
    setEtat(d);
    setSaisie(Object.fromEntries(d.plateformes.map((p) => [p.id, { url: p.url, actif: p.actif }])));
  };
  useEffect(() => {
    apiClient.get("/admin/contacts-plateformes").then((r) => appliquer(r.data)).catch(() => toast.error("Contacts des plateformes illisibles"));
  }, []);

  // Enregistre l'adresse et l'activation d'une plateforme
  const enregistrer = async (p) => {
    setOccupe(p.id);
    try {
      const { data } = await apiClient.put(`/admin/contacts-plateformes/${p.id}`, { url: saisie[p.id].url, actif: saisie[p.id].actif, nom: p.nom });
      appliquer(data); toast.success(`${p.nom} enregistrée`);
    } catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible"); } finally { setOccupe(""); }
  };
  // Synchronisation immédiate
  const synchroniser = async (p) => {
    setOccupe(p.id);
    const attente = toast.loading(`Patientez… lecture des contacts de ${p.nom}`);
    try {
      const { data } = await apiClient.post(`/admin/contacts-plateformes/${p.id}/synchroniser`);
      appliquer(data);
      if (data.bilan.ok) toast.success(`${p.nom} : ${data.bilan.recus} contact(s) lus, ${data.bilan.crees} créé(s), ${data.bilan.dans_le_groupe} dans le groupe`, { id: attente });
      else toast.error(data.bilan.erreur || "Synchronisation impossible", { id: attente });
    } catch (e) { toast.error(e?.response?.data?.detail || "Synchronisation impossible", { id: attente }); } finally { setOccupe(""); }
  };

  if (!etat) return <p className="text-sm text-slate-500">Chargement…</p>;
  return (
    <div className="space-y-3 text-sm text-slate-700" data-testid="contacts-plateformes-section">
      <p>
        SAWALI lit chaque nuit (03 h 20) les contacts des plateformes activées et les range dans un groupe <b>« Plateforme … »</b> de
        l'annuaire du compte qui enregistre la plateforme. Ces groupes se choisissent ensuite pour un message WhatsApp de masse ou un carrousel.
      </p>
      <p className="rounded-md bg-amber-50 p-2 text-xs text-amber-900 ring-1 ring-amber-200">
        <b>Consentement :</b> un contact importé ne reçoit un carrousel qu'après son propre accord (bouton « Oui, j'accepte » ou mot-clé
        OUI NOUVEAUTES), ou si la plateforme l'a recueilli à l'inscription. Un STOP déjà enregistré n'est jamais écrasé.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-slate-500"><tr>
            <th className="p-2">Plateforme</th><th className="p-2">Adresse du serveur</th><th className="p-2">Active</th><th className="p-2">Clé</th>
            <th className="p-2 text-right">Contacts</th><th className="p-2 text-right">Consentants</th><th className="p-2">Dernière lecture</th><th className="p-2" />
          </tr></thead>
          <tbody>
            {etat.plateformes.map((p) => {
              const s = saisie[p.id] || { url: "", actif: false };
              const r = p.resultat;
              return (
                <tr key={p.id} className="border-t border-slate-200 align-top" data-testid={`plateforme-${p.id}`}>
                  <td className="p-2 font-semibold">{p.nom}</td>
                  <td className="p-2"><input className="w-56 rounded border border-slate-300 px-2 py-1" placeholder="https://api.exemple.com" value={s.url}
                    onChange={(e) => setSaisie({ ...saisie, [p.id]: { ...s, url: e.target.value } })} /></td>
                  <td className="p-2"><input type="checkbox" checked={s.actif} onChange={(e) => setSaisie({ ...saisie, [p.id]: { ...s, actif: e.target.checked } })} aria-label={`Activer ${p.nom}`} /></td>
                  <td className="p-2">{p.cle_saisie ? <span className="text-emerald-700">✓ saisie</span> : <span className="text-rose-700" title={`Variable à saisir sur Render : ${p.variable}`}>✗ {p.variable}</span>}</td>
                  <td className="p-2 text-right tabular-nums">{p.contacts}</td>
                  <td className="p-2 text-right tabular-nums">{p.consentants}</td>
                  <td className="p-2">{dateCourte(p.derniere_sync)}
                    {r && (r.ok ? <span className="block text-emerald-700">{r.recus} lus · {r.crees} créés · {r.adoptes} déjà connus{r.retires_du_groupe ? ` · ${r.retires_du_groupe} sortis` : ""}</span>
                      : <span className="block max-w-xs text-rose-700">{r.erreur}</span>)}</td>
                  <td className="p-2"><div className="flex flex-wrap gap-1">
                    <button type="button" disabled={occupe === p.id} onClick={() => enregistrer(p)} className="rounded bg-slate-900 px-2 py-1 font-semibold text-white disabled:opacity-50">Enregistrer</button>
                    <button type="button" disabled={occupe === p.id || !p.url || !p.cle_saisie} onClick={() => synchroniser(p)} className="rounded border border-slate-300 px-2 py-1 font-semibold disabled:opacity-40" data-testid={`synchro-${p.id}`}>Synchroniser</button>
                  </div></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-slate-500">
        Chaque plateforme doit exposer <code>GET {etat.chemin}</code> (signé, lecture seule) et connaître la même clé sous le nom
        <code> SAWALI_CONTACTS_HMAC</code>. Les groupes se retrouvent dans <Link to="/admin/contacts" className="text-sky-700 underline">Contacts</Link> et
        dans <Link to="/admin/whatsapp-carrousel" className="text-sky-700 underline">Carrousel WhatsApp</Link>.
      </p>
    </div>
  );
}
