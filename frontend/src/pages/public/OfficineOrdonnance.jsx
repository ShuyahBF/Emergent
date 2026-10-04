// pages/public/OfficineOrdonnance.jsx
// -------------------------------------
// Lot 57 — même circuit que Ster (demande du propriétaire) : « Le patient va en
// officine avec son ordonnance, l'officine scanne le QR code, modifie les
// quantités servies (s'il y en a) et valide. Le médecin saura en retour si son
// ordonnance a pu être servie. L'officine peut aussi indiquer qu'un produit est
// en rupture. »
// Page PUBLIQUE (aucune connexion : l'officine n'a pas de compte SAWALI), ouverte
// en scannant le QR imprimé sur l'ordonnance A5. Le patient y est ANONYMISÉ
// (jamais son nom ni son numéro). Le nom et la ville de l'officine sont mémorisés
// sur l'appareil (lib/memoirePharmacie.js) pour ne pas les ressaisir.
import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { CheckCircle2, Loader2, Pill, ShieldAlert, ShieldCheck } from "lucide-react";
import { apiClient } from "@/lib/api";
import { effacerOfficineMemorisee, lireOfficineMemorisee, memoriserOfficine } from "@/lib/memoirePharmacie";

// Choix proposés pour chaque produit (ordre d'affichage)
const CHOIX = [
  { valeur: "servi", libelle: "Servi", couleur: "bg-emerald-600" },
  { valeur: "partiel", libelle: "Servi en partie", couleur: "bg-amber-500" },
  { valeur: "rupture", libelle: "En rupture", couleur: "bg-rose-600" },
  { valeur: "non_servi", libelle: "Non servi", couleur: "bg-slate-500" },
];

function dateFr(valeur) {
  if (!valeur) return "";
  try { return new Date(valeur).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }); } catch { return String(valeur); }
}

export default function OfficineOrdonnance() {
  const { jeton } = useParams();
  const [donnees, setDonnees] = useState(null);
  const [erreur, setErreur] = useState("");
  const [chargement, setChargement] = useState(true);

  // Formulaire de l'officine (pré-rempli avec l'officine mémorisée sur cet appareil)
  const [officineMemorisee, setOfficineMemorisee] = useState(() => lireOfficineMemorisee());
  const [nomOfficine, setNomOfficine] = useState(() => officineMemorisee?.nom || "");
  const [ville, setVille] = useState(() => officineMemorisee?.ville || "");
  const [lignes, setLignes] = useState([]);
  const [commentaire, setCommentaire] = useState("");
  const [envoi, setEnvoi] = useState(false);
  const [erreurEnvoi, setErreurEnvoi] = useState("");
  const [resultat, setResultat] = useState(null);

  // Lecture de l'ordonnance (relue en direct : retours des autres officines compris)
  useEffect(() => {
    apiClient.get(`/public/vidal-ordonnance/${jeton}`)
      .then((r) => {
        setDonnees(r.data);
        // Une ligne par produit prescrit, « Servi » par défaut, quantité 1 à ajuster
        setLignes((r.data.lignes || []).map((l) => ({ index: l.index, statut: "servi", quantite_servie: "1" })));
      })
      .catch((err) => setErreur(err?.response?.data?.detail || "Ce lien de vérification est invalide."))
      .finally(() => setChargement(false));
  }, [jeton]);

  const modifier = (i, patch) => setLignes((prev) => prev.map((l, j) => (j === i ? { ...l, ...patch } : l)));

  // Validation du retour de l'officine
  const valider = async () => {
    if (!nomOfficine.trim()) { setErreurEnvoi("Le nom de l'officine est obligatoire."); return; }
    setEnvoi(true); setErreurEnvoi("");
    try {
      const r = await apiClient.post(`/public/vidal-ordonnance/${jeton}/servir`, {
        nom_officine: nomOfficine.trim(), ville: ville.trim() || null, commentaire: commentaire.trim() || null,
        lignes: lignes.map((l) => ({
          index: l.index, statut: l.statut,
          quantite_servie: ["servi", "partiel"].includes(l.statut) && l.quantite_servie !== "" ? Number(l.quantite_servie) : null,
        })),
      });
      memoriserOfficine({ nom: nomOfficine.trim(), ville: ville.trim() });
      setResultat(r.data);
    } catch (err) {
      setErreurEnvoi(err?.response?.data?.detail || "Échec de l'envoi. Réessayez.");
    }
    setEnvoi(false);
  };

  return (
    <div className="min-h-screen bg-slate-50 flex items-start sm:items-center justify-center p-4">
      <div className="w-full max-w-lg bg-white rounded-2xl shadow ring-1 ring-slate-200 p-5">
        <div className="text-center mb-4">
          <div className="font-bold text-[#1c4587]">SAWALI — Ordonnance sécurisée VIDAL</div>
          <div className="text-xs text-slate-500">Vérification et délivrance en officine</div>
        </div>

        {chargement && <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin text-slate-400" /></div>}

        {!chargement && erreur && (
          <div className="text-center py-6">
            <ShieldAlert className="h-10 w-10 mx-auto text-rose-600 mb-2" />
            <div className="font-bold text-rose-700">Ordonnance non vérifiable</div>
            <div className="text-sm text-slate-600 mt-1">{erreur}</div>
          </div>
        )}

        {!chargement && donnees && (
          <>
            <div className="text-center mb-3">
              <ShieldCheck className="h-9 w-9 mx-auto text-emerald-600 mb-1" />
              <div className="font-bold text-emerald-700 text-sm">Ordonnance authentique</div>
            </div>
            <table className="w-full text-sm mb-3">
              <tbody>
                <tr><td className="py-1 text-slate-500">Référence</td><td className="py-1 text-right font-semibold">{donnees.reference}</td></tr>
                <tr><td className="py-1 text-slate-500">Prescripteur</td><td className="py-1 text-right font-semibold">{donnees.prescripteur || "—"}</td></tr>
                <tr><td className="py-1 text-slate-500">Date</td><td className="py-1 text-right font-semibold">{dateFr(donnees.date)}</td></tr>
                <tr><td className="py-1 text-slate-500">Patient</td><td className="py-1 text-right font-semibold">
                  Anonymisé{donnees.patient?.sexe ? ` · ${donnees.patient.sexe}` : ""}{donnees.patient?.date_naissance ? ` · né(e) le ${new Date(donnees.patient.date_naissance).toLocaleDateString("fr-FR")}` : ""}
                </td></tr>
              </tbody>
            </table>

            {/* Retours déjà enregistrés par d'autres officines */}
            {donnees.services?.length > 0 && (
              <div className="mb-3 rounded-lg bg-slate-50 p-3 text-xs">
                <div className="font-semibold mb-1">Déjà présentée à :</div>
                {donnees.services.map((s, i) => (
                  <div key={i} className="mb-1">
                    <b>{s.nom_officine}</b>{s.ville ? ` (${s.ville})` : ""} — {dateFr(s.date_service)} :{" "}
                    {(s.lignes || []).map((l) => `${l.libelle} : ${(donnees.statuts || {})[l.statut] || l.statut}${l.quantite_servie ? ` (${l.quantite_servie})` : ""}`).join(" ; ")}
                  </div>
                ))}
              </div>
            )}

            {resultat ? (
              <div className="text-center py-5 text-emerald-700">
                <CheckCircle2 className="h-8 w-8 mx-auto mb-1" />
                <div className="font-semibold">Merci, votre retour est enregistré ({resultat.libelle}).</div>
                <div className="text-xs text-slate-500 mt-1">Le médecin prescripteur en est informé.</div>
              </div>
            ) : (
              <div className="border-t border-slate-200 pt-3">
                {officineMemorisee && (
                  <div className="text-xs text-slate-600 mb-2">
                    Officine reconnue sur cet appareil : <b>{officineMemorisee.nom}</b>.{" "}
                    <button type="button" className="underline text-[#1c4587]"
                      onClick={() => { effacerOfficineMemorisee(); setOfficineMemorisee(null); setNomOfficine(""); setVille(""); }}>
                      Ce n'est pas votre pharmacie ? Effacer
                    </button>
                  </div>
                )}
                <label className="block text-xs font-semibold text-black mb-1">* Nom de l'officine</label>
                <input value={nomOfficine} onChange={(e) => setNomOfficine(e.target.value.toUpperCase())}
                  className="w-full rounded-lg ring-1 ring-slate-300 px-3 py-2 text-sm font-semibold text-[#1e3a8a] uppercase mb-2" />
                <label className="block text-xs font-semibold text-black mb-1">Ville</label>
                <input value={ville} onChange={(e) => setVille(e.target.value)}
                  className="w-full rounded-lg ring-1 ring-slate-300 px-3 py-2 text-sm font-semibold text-[#1e3a8a] mb-3" />

                <div className="flex items-center gap-1.5 text-xs font-semibold mb-2"><Pill className="h-3.5 w-3.5" /> Pour chaque produit : servi, en partie, en rupture…</div>
                {(donnees.lignes || []).map((l, i) => (
                  <div key={l.index} className="mb-2 rounded-lg bg-slate-50 p-3">
                    <div className="text-sm font-bold">{l.libelle}</div>
                    {l.detail && <div className="text-xs text-slate-500 mb-2">{l.detail}</div>}
                    <div className="flex flex-wrap gap-1.5 mb-2">
                      {CHOIX.map((c) => (
                        <button key={c.valeur} type="button" onClick={() => modifier(i, { statut: c.valeur })}
                          className={`rounded-full px-3 py-1 text-xs font-bold ${lignes[i]?.statut === c.valeur ? `${c.couleur} text-white` : "bg-white ring-1 ring-slate-300 text-slate-700"}`}>
                          {c.libelle}
                        </button>
                      ))}
                    </div>
                    {["servi", "partiel"].includes(lignes[i]?.statut) && (
                      <label className="flex items-center gap-2 text-xs text-black">
                        Quantité servie
                        <input type="number" min="0" max="1000" step="1" value={lignes[i]?.quantite_servie ?? ""}
                          onChange={(e) => modifier(i, { quantite_servie: e.target.value })}
                          className="w-24 rounded-lg ring-1 ring-slate-300 px-2 py-1 text-sm font-semibold text-[#1e3a8a]" />
                      </label>
                    )}
                  </div>
                ))}
                <label className="block text-xs font-semibold text-black mb-1 mt-2">Commentaire (facultatif)</label>
                <textarea rows={2} value={commentaire} onChange={(e) => setCommentaire(e.target.value)}
                  className="w-full rounded-lg ring-1 ring-slate-300 px-3 py-2 text-sm text-[#1e3a8a] mb-3" placeholder="Ex. : générique proposé, retour prévu le…" />
                {erreurEnvoi && <div className="text-sm text-rose-600 mb-2">{erreurEnvoi}</div>}
                <button type="button" onClick={valider} disabled={envoi}
                  className="w-full rounded-xl bg-[#1c4587] text-white font-bold py-2.5 disabled:opacity-60">
                  {envoi ? "Envoi…" : "Valider la délivrance"}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
