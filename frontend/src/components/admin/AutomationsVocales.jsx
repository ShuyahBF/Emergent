// Lots 374 / 375 — Automations vocales sur Alexa (Voice Monkey), dans la page Automations (administrateur) et dans « Automations vocales »
// (Superviseur). Trois déclencheurs : à une date et une heure (GMT), N minutes avant un rendez-vous, à l'arrivée d'un message WhatsApp.
// Chaque règle s'active / se désactive et se teste. Voir backend/services/rappels_vocaux.py et backend/routes/rappels_vocaux.py.
import React, { useEffect, useState } from "react";
import { apiClient } from "../../lib/api";
import { toast } from "sonner";
import { Trash2, Volume2, Plus } from "lucide-react";

const STATUT = {
  en_attente: { texte: "En attente", classe: "bg-sky-100 text-sky-800" },
  actif: { texte: "Permanente", classe: "bg-sky-100 text-sky-800" },
  annonce: { texte: "Annoncé", classe: "bg-green-100 text-green-800" },
  echec: { texte: "Échec", classe: "bg-red-100 text-red-800" },
  manque: { texte: "Manqué", classe: "bg-orange-100 text-orange-800" },
};

// « 2026-11-13T09:00:00+00:00 » → « 13/11/2026 09:00 GMT »
function enGmt(iso) {
  const d = new Date(iso);
  if (!iso || Number.isNaN(d.getTime())) return "—";
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getUTCDate())}/${p(d.getUTCMonth() + 1)}/${d.getUTCFullYear()} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())} GMT`;
}

export default function AutomationsVocales() {
  const [donnees, setDonnees] = useState(null);
  const [declencheur, setDeclencheur] = useState("date");
  const [texte, setTexte] = useState("");
  const [quand, setQuand] = useState("");              // « AAAA-MM-JJTHH:MM », saisi en GMT
  const [repetition, setRepetition] = useState("aucune");
  const [minutes, setMinutes] = useState("30");
  const [enCours, setEnCours] = useState(false);

  const charger = async () => {
    try { setDonnees((await apiClient.get("/admin/rappels-vocaux")).data); }
    catch (e) { toast.error(e?.response?.data?.detail || "Chargement des automations vocales impossible"); }
  };
  useEffect(() => { charger(); }, []);

  const creer = async () => {
    setEnCours(true);
    try {
      const corps = { declencheur, texte };
      if (declencheur === "date") { corps.quand = quand ? `${quand}:00Z` : ""; corps.repetition = repetition; }   // la saisie est en GMT
      if (declencheur === "rendez_vous") corps.minutes_avant = Number(minutes);
      await apiClient.post("/admin/rappels-vocaux", corps);
      toast.success("Automation vocale créée");
      setTexte(""); setQuand(""); setRepetition("aucune");
      await charger();
    } catch (e) { toast.error(e?.response?.data?.detail || "Création impossible"); }
    finally { setEnCours(false); }
  };

  const agir = async (promesse, ok) => {
    try { await promesse(); if (ok) toast.success(ok); await charger(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Action impossible"); }
  };

  if (!donnees) return <div className="text-sm text-slate-500">Chargement…</div>;
  const declencheurs = Object.entries(donnees.declencheurs || {});
  const jetons = Object.keys((donnees.jetons || {})[declencheur] || {});
  const peutCreer = texte.trim() && (declencheur !== "date" || quand) && (declencheur !== "rendez_vous" || Number(minutes) >= 1);
  return (
    <div className="space-y-4" data-testid="automations-vocales">
      <p className="text-sm text-slate-600">
        Alexa annonce une phrase à voix haute : à une date et une heure (<strong>heure GMT</strong>, celle d'Abidjan), quelques minutes avant un
        rendez-vous, ou dès qu'un message WhatsApp arrive. Chaque règle peut être désactivée sans être supprimée, et testée tout de suite.
      </p>
      {!donnees.alexa_pret && (
        <div className="rounded border border-orange-300 bg-orange-50 p-3 text-sm text-orange-900">
          Alexa n'est pas prête : l'administrateur doit l'activer et renseigner l'adresse Voice Monkey (Paramètres → « Notifications vocales
          Alexa (Voice Monkey) »). Les annonces ne partent pas tant que ce n'est pas fait.
        </div>
      )}
      <div className="grid gap-3 md:grid-cols-[1fr_2fr]">
        <label className="text-sm">Quand l'annoncer ?
          <select className="mt-1 w-full rounded border p-2" value={declencheur} onChange={(e) => setDeclencheur(e.target.value)} data-testid="av-declencheur">
            {declencheurs.map(([cle, libelle]) => <option key={cle} value={cle}>{libelle}</option>)}
          </select>
        </label>
        <label className="text-sm">Phrase à annoncer
          <input className="mt-1 w-full rounded border p-2" maxLength={donnees.texte_max} value={texte} onChange={(e) => setTexte(e.target.value)}
                 placeholder="Ex. : Travailler sur les remarques de la démonstration VIDAL" />
        </label>
      </div>
      <div className="grid gap-3 md:grid-cols-[1fr_1fr_2fr]">
        {declencheur === "date" && (
          <>
            <label className="text-sm">Date et heure (GMT)
              <input type="datetime-local" className="mt-1 w-full rounded border p-2" value={quand} onChange={(e) => setQuand(e.target.value)} />
            </label>
            <label className="text-sm">Répétition
              <select className="mt-1 w-full rounded border p-2" value={repetition} onChange={(e) => setRepetition(e.target.value)}>
                {Object.entries(donnees.repetitions || {}).map(([cle, libelle]) => <option key={cle} value={cle}>{libelle}</option>)}
              </select>
            </label>
          </>
        )}
        {declencheur === "rendez_vous" && (
          <label className="text-sm">Minutes avant le rendez-vous
            <input type="number" min={1} max={donnees.minutes_avant_max} className="mt-1 w-full rounded border p-2" value={minutes} onChange={(e) => setMinutes(e.target.value)} />
          </label>
        )}
        <div className="text-xs text-slate-500 self-end">
          {jetons.length > 0
            ? <>Variables utilisables dans la phrase : {jetons.map((j) => <code key={j} className="mx-1 rounded bg-slate-100 px-1">{`{${j}}`}</code>)}</>
            : "Aucune variable pour ce déclencheur."}
        </div>
      </div>
      <div className="flex flex-wrap gap-2 boutons-distincts">
        <button type="button" className="inline-flex items-center gap-1 rounded border px-4 py-2 text-sm" disabled={enCours || !peutCreer} onClick={creer} data-testid="av-creer">
          <Plus className="h-4 w-4" /> Créer l'automation vocale
        </button>
        <button type="button" className="inline-flex items-center gap-1 rounded border px-4 py-2 text-sm"
                onClick={() => agir(() => apiClient.post("/admin/rappels-vocaux/tester", { texte: texte || undefined }), "Annonce envoyée à Alexa")}>
          <Volume2 className="h-4 w-4" /> Tester Alexa maintenant
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="tableau w-full text-sm">
          <thead><tr className="text-left"><th>Déclencheur</th><th>Phrase</th><th>État</th><th>Dernière annonce</th><th>Actif</th><th /></tr></thead>
          <tbody>
            {(donnees.rappels || []).length === 0 && <tr><td colSpan={6} className="py-3 text-slate-500">Aucune automation vocale.</td></tr>}
            {(donnees.rappels || []).map((r) => {
              const dec = r.declencheur || "date";
              const s = STATUT[r.statut] || { texte: r.statut, classe: "bg-slate-100 text-slate-800" };
              const quandTexte = dec === "date" ? `${enGmt(r.quand)}${r.repetition !== "aucune" ? ` · ${(donnees.repetitions || {})[r.repetition] || r.repetition}` : ""}`
                : dec === "rendez_vous" ? `${r.minutes_avant} min avant un rendez-vous` : "Message WhatsApp reçu";
              return (
                <tr key={r.id} className={r.actif === false ? "opacity-60" : ""}>
                  <td className="whitespace-nowrap">{quandTexte}</td>
                  <td>{r.texte}{r.motif ? <div className="text-xs text-red-700">{r.motif}</div> : null}</td>
                  <td><span className={`rounded px-2 py-0.5 text-xs ${s.classe}`}>{s.texte}</span>{r.nb_declenchements ? <span className="ml-1 text-xs text-slate-500">× {r.nb_declenchements}</span> : null}</td>
                  <td className="whitespace-nowrap text-xs">{r.dernier_declenchement ? enGmt(r.dernier_declenchement) : "—"}</td>
                  <td><input type="checkbox" aria-label="Activer cette automation" checked={r.actif !== false}
                             onChange={(e) => agir(() => apiClient.put(`/admin/rappels-vocaux/${r.id}`, { actif: e.target.checked }))} /></td>
                  <td className="whitespace-nowrap text-right">
                    <button type="button" aria-label="Tester cette automation" className="mr-2" onClick={() => agir(() => apiClient.post(`/admin/rappels-vocaux/${r.id}/tester`), "Annonce de test envoyée à Alexa")}><Volume2 className="h-4 w-4 text-sky-700" /></button>
                    <button type="button" aria-label="Supprimer cette automation" onClick={() => agir(() => apiClient.delete(`/admin/rappels-vocaux/${r.id}`))}><Trash2 className="h-4 w-4 text-red-600" /></button>
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
