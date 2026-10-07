// LiluvinePartageSection.jsx — Lot 73 : rubrique « 🤖 Liluvine — partage avec les superviseurs » des Paramètres.
// L'administrateur choisit, pour chaque superviseur (ex. support@sawalismartsystems.com), les éléments de Liluvine
// qu'il partage avec lui : Agenda d'appels, notifications « Liluvine appelle … », Liluvine PRO, Historique.
// « Par défaut » = aucune restriction (le superviseur voit tout, comme avant) ; sinon seuls les éléments cochés.
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

export default function LiluvinePartageSection() {
  const [donnees, setDonnees] = useState(null);     // { elements: {cle: libellé}, superviseurs: [{email, nom, partage}] }
  const [brouillon, setBrouillon] = useState({});   // email → liste cochée (null = par défaut)
  const [nouvel, setNouvel] = useState("");          // e-mail ajouté à la main
  const [occupe, setOccupe] = useState("");

  // Lecture des superviseurs et de ce qui est partagé avec chacun
  const charger = () => apiClient.get("/admin/liluvine-partage").then((r) => {
    setDonnees(r.data);
    const b = {};
    (r.data.superviseurs || []).forEach((x) => { b[x.email] = x.partage; });
    setBrouillon(b);
  }).catch((err) => setDonnees({ erreur: err?.response?.data?.detail || "Rubrique indisponible" }));
  useEffect(() => { charger(); }, []);

  // Enregistrement pour un superviseur (elements = null : par défaut, tout est visible)
  const enregistrer = async (email, elements) => {
    setOccupe(email);
    const t = toast.loading("Patientez…");
    try {
      await apiClient.put("/admin/liluvine-partage", { email, elements });
      toast.success(elements === null ? `${email} : tout Liluvine (par défaut)` : `${email} : partage enregistré`, { id: t });
      await charger();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Enregistrement impossible", { id: t });
    } finally {
      setOccupe("");
    }
  };

  if (!donnees) return <p className="text-sm text-slate-500">Patientez…</p>;
  if (donnees.erreur) return <p className="text-sm text-red-700">{donnees.erreur}</p>;
  const cles = Object.keys(donnees.elements || {});
  // Coche / décoche un élément pour un superviseur (partir de « tout » si la ligne était par défaut)
  const basculer = (email, cle) => setBrouillon((b) => {
    const actuel = b[email] == null ? cles : b[email];
    return { ...b, [email]: actuel.includes(cle) ? actuel.filter((c) => c !== cle) : [...actuel, cle] };
  });
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-liluvine-partage">
      <h3 className="font-semibold text-slate-900">🤖 Ce que Liluvine partage avec chaque superviseur</h3>
      <p className="text-xs text-slate-600">
        Cochez ce que chaque superviseur peut voir dans le menu « Liluvine ». « Par défaut » : aucune restriction
        (il voit tout, comme avant). L'agenda et ses notifications sont aussi refusés par le serveur s'ils ne sont pas partagés.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-slate-500">
              <th className="py-1 pr-2">Superviseur</th>
              {cles.map((c) => <th key={c} className="px-2 text-center">{donnees.elements[c]}</th>)}
              <th className="px-2" />
            </tr>
          </thead>
          <tbody>
            {(donnees.superviseurs || []).map((x) => {
              const coches = brouillon[x.email];
              const parDefaut = coches == null;
              return (
                <tr key={x.email} className="border-t border-slate-100">
                  <td className="py-1.5 pr-2">
                    <div className="font-medium text-slate-800">{x.nom}</div>
                    <div className="text-[11px] text-slate-500">{x.email}{parDefaut ? " · par défaut (tout)" : ""}</div>
                  </td>
                  {cles.map((c) => (
                    <td key={c} className="px-2 text-center">
                      <input type="checkbox" checked={parDefaut || coches.includes(c)} onChange={() => basculer(x.email, c)}
                        aria-label={`${donnees.elements[c]} pour ${x.email}`} />
                    </td>
                  ))}
                  <td className="whitespace-nowrap px-2 text-right">
                    <button type="button" disabled={occupe === x.email || parDefaut} onClick={() => enregistrer(x.email, coches)}
                      className="mr-1 rounded bg-sawali-blue px-2 py-0.5 font-semibold text-white disabled:opacity-40">Enregistrer</button>
                    {x.partage != null && (
                      <button type="button" disabled={occupe === x.email} onClick={() => enregistrer(x.email, null)}
                        className="rounded border border-slate-300 px-2 py-0.5 hover:bg-slate-50" title="Rendre tout Liluvine à ce superviseur">
                        Par défaut
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {(donnees.superviseurs || []).length === 0 && <p className="text-xs text-slate-500">Aucun superviseur trouvé.</p>}
      {/* Superviseur absent de la liste (compte à venir) : réglage par son e-mail, sans aucun élément au départ */}
      <div className="flex flex-wrap items-center gap-2">
        <input value={nouvel} onChange={(e) => setNouvel(e.target.value)} placeholder="support@sawalismartsystems.com"
          className="w-72 rounded-lg border border-slate-300 px-2 py-1 text-xs" />
        <button type="button" disabled={!nouvel.includes("@") || !!occupe} onClick={() => { enregistrer(nouvel.trim().toLowerCase(), []); setNouvel(""); }}
          className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50 disabled:opacity-40">
          ➕ Ajouter ce superviseur (rien de partagé au départ)
        </button>
      </div>
    </div>
  );
}
