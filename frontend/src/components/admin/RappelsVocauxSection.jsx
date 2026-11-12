// Lot 374 — Rappels vocaux programmés sur Alexa (Voice Monkey).
// Le propriétaire saisit une phrase, une date et une heure (GMT) ; à l'heure dite, SAWALI la fait annoncer par Alexa.
// Voir backend/services/rappels_vocaux.py et backend/routes/rappels_vocaux.py.
import React, { useEffect, useState } from "react";
import { apiClient } from "../../lib/api";
import { toast } from "sonner";
import { Trash2, Volume2 } from "lucide-react";

const LIBELLE_STATUT = {
  en_attente: { texte: "En attente", classe: "bg-sky-100 text-sky-800" },
  annonce: { texte: "Annoncé", classe: "bg-green-100 text-green-800" },
  echec: { texte: "Échec", classe: "bg-red-100 text-red-800" },
  manque: { texte: "Manqué", classe: "bg-orange-100 text-orange-800" },
};

// « 2026-11-13T09:00:00+00:00 » → « 13/11/2026 09:00 GMT »
function enGmt(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getUTCDate())}/${p(d.getUTCMonth() + 1)}/${d.getUTCFullYear()} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())} GMT`;
}

export default function RappelsVocauxSection() {
  const [donnees, setDonnees] = useState(null);
  const [texte, setTexte] = useState("");
  const [quand, setQuand] = useState("");          // « AAAA-MM-JJTHH:MM », saisi en GMT
  const [repetition, setRepetition] = useState("aucune");
  const [enCours, setEnCours] = useState(false);

  const charger = async () => {
    try {
      const r = await apiClient.get("/admin/rappels-vocaux");
      setDonnees(r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Chargement des rappels vocaux impossible");
    }
  };
  useEffect(() => { charger(); }, []);

  const programmer = async () => {
    setEnCours(true);
    try {
      await apiClient.post("/admin/rappels-vocaux", { texte, quand: quand ? `${quand}:00Z` : "", repetition });   // la saisie est en GMT
      toast.success("Rappel vocal programmé");
      setTexte(""); setQuand(""); setRepetition("aucune");
      await charger();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Programmation impossible");
    } finally { setEnCours(false); }
  };

  const supprimer = async (id) => {
    try { await apiClient.delete(`/admin/rappels-vocaux/${id}`); await charger(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Suppression impossible"); }
  };

  const tester = async () => {
    try {
      await apiClient.post("/admin/rappels-vocaux/tester", { texte: texte || undefined });
      toast.success("Annonce envoyée à Alexa");
    } catch (e) { toast.error(e?.response?.data?.detail || "Annonce impossible"); }
  };

  if (!donnees) return <div className="text-sm text-slate-500">Chargement…</div>;
  const repetitions = Object.entries(donnees.repetitions || {});
  return (
    <div className="space-y-4" data-testid="rappels-vocaux">
      <p className="text-sm text-slate-600">
        Programmez une phrase : à l'heure choisie (<strong>heure GMT</strong>, celle d'Abidjan), Alexa l'annonce à voix haute. Un rappel
        manqué de plus d'une heure (serveur arrêté) n'est pas annoncé en retard.
      </p>
      {!donnees.alexa_pret && (
        <div className="rounded border border-orange-300 bg-orange-50 p-3 text-sm text-orange-900">
          Alexa n'est pas prête : activez-la et renseignez l'adresse Voice Monkey dans les réglages des notifications vocales Alexa
          (rubrique « Notifications vocales Alexa (Voice Monkey) » des Paramètres). Les rappels ne seront pas annoncés tant que ce n'est pas fait.
        </div>
      )}
      <div className="grid gap-3 md:grid-cols-[2fr_1fr_1fr]">
        <label className="text-sm">Phrase à annoncer
          <input className="mt-1 w-full rounded border p-2" maxLength={donnees.texte_max} value={texte}
                 onChange={(e) => setTexte(e.target.value)} placeholder="Ex. : Travailler sur les remarques de la démonstration VIDAL" />
        </label>
        <label className="text-sm">Date et heure (GMT)
          <input type="datetime-local" className="mt-1 w-full rounded border p-2" value={quand} onChange={(e) => setQuand(e.target.value)} />
        </label>
        <label className="text-sm">Répétition
          <select className="mt-1 w-full rounded border p-2" value={repetition} onChange={(e) => setRepetition(e.target.value)}>
            {repetitions.map(([cle, libelle]) => <option key={cle} value={cle}>{libelle}</option>)}
          </select>
        </label>
      </div>
      <div className="flex flex-wrap gap-2 boutons-distincts">
        <button type="button" className="rounded border px-4 py-2 text-sm" disabled={enCours || !texte || !quand} onClick={programmer}>
          Programmer le rappel
        </button>
        <button type="button" className="inline-flex items-center gap-1 rounded border px-4 py-2 text-sm" onClick={tester}>
          <Volume2 className="h-4 w-4" /> Tester Alexa maintenant
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="tableau w-full text-sm">
          <thead>
            <tr className="text-left"><th>Quand (GMT)</th><th>Phrase</th><th>Répétition</th><th>État</th><th /></tr>
          </thead>
          <tbody>
            {(donnees.rappels || []).length === 0 && <tr><td colSpan={5} className="py-3 text-slate-500">Aucun rappel programmé.</td></tr>}
            {(donnees.rappels || []).map((r) => {
              const s = LIBELLE_STATUT[r.statut] || { texte: r.statut, classe: "bg-slate-100 text-slate-800" };
              return (
                <tr key={r.id}>
                  <td className="whitespace-nowrap">{enGmt(r.quand)}</td>
                  <td>{r.texte}{r.motif ? <div className="text-xs text-red-700">{r.motif}</div> : null}</td>
                  <td>{(donnees.repetitions || {})[r.repetition] || r.repetition}</td>
                  <td><span className={`rounded px-2 py-0.5 text-xs ${s.classe}`}>{s.texte}</span></td>
                  <td className="text-right">
                    <button type="button" aria-label="Supprimer ce rappel" onClick={() => supprimer(r.id)}><Trash2 className="h-4 w-4 text-red-600" /></button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
