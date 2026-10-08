// MessagesBloquesWa.jsx — Lot 79.6 : sous-menu Liluvine « Messages bloqués ».
//
// La barrière anti-rafale WhatsApp (lot 63) RETIENT les messages d'un correspondant qui écrit plusieurs fois
// sans réponse : ils sont enregistrés mais n'arrivent ni en non-lu ni à Liluvine. Jusqu'ici on ne les voyait
// que dans la conversation de chaque contact (bandeau du Centre de Messagerie). Cet écran les regroupe TOUS :
//   • un tableau des correspondants bloqués : nom, numéro, nombre de messages retenus, premier / dernier,
//     dernier texte, date de l'avertissement automatique ;
//   • « Remettre dans la conversation » : les messages retenus redeviennent des messages ordinaires ;
//   • « Ouvrir » : la conversation dans le Centre de Messagerie (filtrée sur ce correspondant) ;
//   • en bas, les retenues levées ces 7 derniers jours (qui, quand).
// Accès : administrateurs et superviseurs (un superviseur restreint doit avoir reçu « Messages WhatsApp
// bloqués » dans Paramètres → Liluvine — partage). Utilisable à l'identique depuis /admin et /portal.
import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { siVisible } from "@/lib/visibilite";   // relecture en pause quand l'onglet est masqué

// Date et heure au format JJ/MM/AAAA HH:MM (heure de Ouagadougou = UTC)
function dateHeure(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("fr-FR", { timeZone: "Africa/Ouagadougou", day: "2-digit", month: "2-digit",
      year: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

// Numéro lisible : « +226 70 11 22 33 »
function numeroLisible(chiffres) {
  const c = String(chiffres || "");
  if (c.length < 8) return c || "—";
  const fin = c.slice(-8).replace(/(\d{2})(?=\d)/g, "$1 ");
  return c.length > 8 ? `+${c.slice(0, c.length - 8)} ${fin}` : fin;
}

export default function MessagesBloquesWa() {
  const [donnees, setDonnees] = useState(null);     // { bloques, liberes, total_retenus, barriere_active, seuil }
  const [erreur, setErreur] = useState("");
  const [enCours, setEnCours] = useState("");       // numéro en cours de libération
  const [selection, setSelection] = useState("");   // ligne sélectionnée (règle des tableaux)

  // Lecture de la liste (silencieuse lors des relectures automatiques)
  const charger = useCallback(async (silencieux = false) => {
    try {
      const { data } = await apiClient.get("/liluvine/messages-bloques");
      setDonnees(data);
      setErreur("");
    } catch (err) {
      const detail = err?.response?.data?.detail || "Liste indisponible";
      setErreur(detail);
      if (!silencieux) toast.error(detail);
    }
  }, []);

  // Première lecture, puis toutes les 60 s tant que l'onglet est visible
  useEffect(() => {
    charger();
    const t = setInterval(siVisible(() => charger(true)), 60000);
    return () => clearInterval(t);
  }, [charger]);

  // « Remettre dans la conversation » : les messages retenus de ce numéro redeviennent ordinaires
  const liberer = async (ligne) => {
    if (!window.confirm(`Remettre les ${ligne.retenus} message(s) retenu(s) de ${ligne.nom || numeroLisible(ligne.numero)} dans la conversation ?`)) return;
    setEnCours(ligne.numero);
    const t = toast.loading("Patientez…");
    try {
      const { data } = await apiClient.post("/liluvine/messages-bloques/liberer", null, { params: { numero: ligne.numero } });
      toast.success(`${data.liberes} message(s) remis dans la conversation`, { id: t });
      await charger(true);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Libération impossible", { id: t });
    } finally {
      setEnCours("");
    }
  };

  if (!donnees && !erreur) {
    return <div className="p-6 text-sm text-slate-500" data-testid="messages-bloques-chargement">Patientez…</div>;
  }

  return (
    <div className="p-4 md:p-6 space-y-5" data-testid="page-messages-bloques">
      {/* En-tête : titre, explication, état de la barrière */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Messages WhatsApp bloqués</h1>
          <p className="text-sm text-slate-600 max-w-3xl">
            Messages retenus par la barrière anti-rafale : le correspondant a écrit plusieurs fois sans réponse.
            Ils sont enregistrés mais n'arrivent ni en non-lu ni à Liluvine tant que personne ne lui répond.
            Vous les retrouvez aussi dans la conversation de chaque contact (Centre de Messagerie).
          </p>
        </div>
        <div className="flex items-center gap-2">
          {donnees && (
            <span className={`text-xs px-2 py-1 rounded-full ring-1 ${donnees.barriere_active
              ? "bg-emerald-50 text-emerald-800 ring-emerald-200" : "bg-slate-100 text-slate-600 ring-slate-200"}`}
              data-testid="etat-barriere">
              {donnees.barriere_active ? `Barrière active (seuil ${donnees.seuil})` : "Barrière désactivée"}
            </span>
          )}
          <button type="button" onClick={() => charger()} className="text-sm px-3 py-1.5 rounded-md border border-slate-300 hover:bg-slate-50"
            data-testid="actualiser-messages-bloques">Actualiser</button>
        </div>
      </div>

      {erreur && <div className="p-3 rounded-md bg-red-50 text-red-800 text-sm" data-testid="erreur-messages-bloques">{erreur}</div>}

      {donnees && (
        <>
          {/* Tableau des correspondants bloqués */}
          <section className="bg-white rounded-lg border border-slate-200 overflow-x-auto">
            <div className="px-4 py-2 border-b border-slate-200 text-sm font-semibold text-slate-800">
              {donnees.bloques.length} correspondant(s) bloqué(s) · {donnees.total_retenus} message(s) retenu(s)
            </div>
            {donnees.bloques.length === 0 ? (
              <p className="p-4 text-sm text-slate-500" data-testid="aucun-bloque">Aucun message retenu en ce moment.</p>
            ) : (
              <table className="w-full text-sm" data-testid="table-messages-bloques">
                <thead className="bg-slate-50 text-left text-xs text-slate-600">
                  <tr>
                    <th className="px-3 py-2">Correspondant</th>
                    <th className="px-3 py-2">Numéro</th>
                    <th className="px-3 py-2 text-center">Retenus</th>
                    <th className="px-3 py-2">Premier / dernier</th>
                    <th className="px-3 py-2">Dernier message</th>
                    <th className="px-3 py-2">Averti le</th>
                    <th className="px-3 py-2 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {donnees.bloques.map((l) => (
                    <tr key={l.numero || l.contact_id} onClick={() => setSelection(l.numero)}
                      aria-selected={selection === l.numero ? "true" : "false"}
                      className={`border-t border-slate-100 cursor-pointer ${selection === l.numero ? "ligne-selectionnee" : ""}`}>
                      <td className="px-3 py-2 font-medium">{l.nom || "Sans fiche"}</td>
                      <td className="px-3 py-2 whitespace-nowrap">{numeroLisible(l.numero)}</td>
                      <td className="px-3 py-2 text-center">
                        <span className="inline-block min-w-[1.75rem] px-2 py-0.5 rounded-full bg-blue-700 text-white text-xs font-semibold">{l.retenus}</span>
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap text-xs">{dateHeure(l.premier_le)}<br />{dateHeure(l.dernier_le)}</td>
                      <td className="px-3 py-2 max-w-xs truncate" title={l.dernier_texte}>{l.dernier_texte}</td>
                      <td className="px-3 py-2 whitespace-nowrap text-xs">{dateHeure(l.averti_le)}</td>
                      <td className="px-3 py-2 text-right whitespace-nowrap space-x-2">
                        {/* Conversation dans le Centre de Messagerie, filtrée sur ce correspondant */}
                        <Link to={`/portal/contacts?q=${encodeURIComponent(l.nom || l.numero.slice(-8))}`}
                          onClick={(e) => e.stopPropagation()}
                          className="px-2 py-1 rounded-md border border-slate-300 hover:bg-slate-50 text-xs">Ouvrir</Link>
                        <button type="button" disabled={enCours === l.numero}
                          onClick={(e) => { e.stopPropagation(); liberer(l); }}
                          className="px-2 py-1 rounded-md bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 text-xs"
                          data-testid={`liberer-${l.numero}`}>
                          {enCours === l.numero ? "Patientez…" : "Remettre dans la conversation"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          {/* Retenues levées ces 7 derniers jours (traçabilité) */}
          <section className="bg-white rounded-lg border border-slate-200 overflow-x-auto">
            <div className="px-4 py-2 border-b border-slate-200 text-sm font-semibold text-slate-800">
              Remis dans la conversation (7 derniers jours)
            </div>
            {donnees.liberes.length === 0 ? (
              <p className="p-4 text-sm text-slate-500">Aucun.</p>
            ) : (
              <table className="w-full text-sm" data-testid="table-messages-liberes">
                <thead className="bg-slate-50 text-left text-xs text-slate-600">
                  <tr>
                    <th className="px-3 py-2">Correspondant</th>
                    <th className="px-3 py-2">Numéro</th>
                    <th className="px-3 py-2 text-center">Messages</th>
                    <th className="px-3 py-2">Le</th>
                    <th className="px-3 py-2">Par</th>
                  </tr>
                </thead>
                <tbody>
                  {donnees.liberes.map((l) => (
                    <tr key={`lib-${l.numero}`} className="border-t border-slate-100">
                      <td className="px-3 py-2">{l.nom || "Sans fiche"}</td>
                      <td className="px-3 py-2 whitespace-nowrap">{numeroLisible(l.numero)}</td>
                      <td className="px-3 py-2 text-center">{l.messages}</td>
                      <td className="px-3 py-2 whitespace-nowrap">{dateHeure(l.libere_le)}</td>
                      <td className="px-3 py-2">{l.libere_par || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
    </div>
  );
}
