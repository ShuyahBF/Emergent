// AppelProprietaireSection.jsx — Lot 67 : « Liluvine appelle le propriétaire » à chaque message d'un client.
//
// À chaque message WhatsApp d'un client (dont la fiche l'autorise — c'est le cas par défaut) :
//   1. Liluvine relaie le message au propriétaire sur son WhatsApp ;
//   2. puis l'appelle (appel WhatsApp depuis le numéro SAWALI choisi) et lui dit qui écrit et
//      la date/heure du dernier message, avant de raccrocher — au plus un appel par client
//      toutes les 30 minutes (réglable), jamais pendant les heures calmes (facultatives).
// Ce bloc permet : réglages, état de l'autorisation d'appel du propriétaire (exigée par Meta),
// envoi de la demande d'autorisation, essai réel, diagnostic réseau (UDP / TURN) et dernières alertes.
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

// Libellés de l'état de l'autorisation d'appel
const ETATS_PERMISSION = {
  accordee: ["Accordée", "bg-emerald-100 text-emerald-800"],
  en_attente: ["En attente", "bg-amber-100 text-amber-800"],
  refusee: ["Refusée", "bg-rose-100 text-rose-800"],
  inconnue: ["Pas encore demandée", "bg-slate-100 text-slate-700"],
};

// Petite jauge circulaire transparente (attente)
const Jauge = () => (
  <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-violet-300 border-t-transparent align-middle" />
);

export default function AppelProprietaireSection() {
  const [donnees, setDonnees] = useState(null);   // réponse de GET /admin/appel-proprietaire
  const [form, setForm] = useState(null);         // réglages modifiables
  const [occupe, setOccupe] = useState("");       // action en cours (enregistrer, essai…)
  const [diag, setDiag] = useState(null);         // résultat du diagnostic réseau

  // Lecture des réglages et de l'état de l'autorisation
  const charger = useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/appel-proprietaire");
      const d = r.data || {};
      const s = d.reglages || {};
      const e = d.effectif || {};
      setDonnees(d);
      setForm({
        appel_proprio_actif: e.actif !== false,
        appel_proprio_numeros: s.appel_proprio_numeros || "",
        appel_proprio_ligne: e.ligne || "principal",
        appel_proprio_fenetre_min: e.fenetre_min || 30,
        appel_proprio_relais_actif: e.relais_actif !== false,
        appel_proprio_appel_actif: e.appel_actif !== false,
        appel_proprio_calme_actif: !!e.calme_actif,
        appel_proprio_calme_debut: e.calme_debut || "22:00",
        appel_proprio_calme_fin: e.calme_fin || "06:00",
        appel_proprio_modele: e.modele || "",
        appel_proprio_modele_langue: e.modele_langue || "fr",
        appel_proprio_voix: e.voix || "auto",
        appel_proprio_voix_elevenlabs: e.voix_elevenlabs || "",
        appel_proprio_repetitions: e.repetitions || 2,
        appel_proprio_sonnerie_s: e.sonnerie_s || 30,
        appel_proprio_exclus: s.appel_proprio_exclus || "",
      });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Réglages indisponibles");
    }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  if (!form) return <p className="text-xs text-slate-500"><Jauge /> Patientez…</p>;
  const maj = (cle, valeur) => setForm((f) => ({ ...f, [cle]: valeur }));

  // Lance une action longue avec le toast « Patientez… »
  const action = async (nom, fn, succes) => {
    setOccupe(nom);
    const t = toast.loading("Patientez…");
    try {
      const r = await fn();
      toast.success(succes(r), { id: t });
      return r;
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Action impossible", { id: t });
      return null;
    } finally {
      setOccupe("");
    }
  };

  // Enregistrement des réglages
  const enregistrer = () => action("enregistrer", async () => {
    await apiClient.put("/admin/appel-proprietaire", {
      ...form,
      appel_proprio_fenetre_min: Math.max(1, Number(form.appel_proprio_fenetre_min) || 30),
      appel_proprio_repetitions: Math.min(3, Math.max(1, Number(form.appel_proprio_repetitions) || 2)),
      appel_proprio_sonnerie_s: Math.min(60, Math.max(10, Number(form.appel_proprio_sonnerie_s) || 30)),
    });
    await charger();
  }, () => "Réglages enregistrés");

  // Demande d'autorisation d'appel envoyée au propriétaire
  const demander = () => action("demander", () => apiClient.post("/admin/appel-proprietaire/demander-autorisation"),
    () => "Demande d'autorisation envoyée sur le WhatsApp du propriétaire");

  // Essai réel : relais + appel avec un message fictif
  const essai = () => action("essai", async () => {
    const r = await apiClient.post("/admin/appel-proprietaire/essai");
    setTimeout(charger, 45000);   // relecture du journal après l'appel
    return r;
  }, (r) => r?.data?.message || "Essai lancé");

  // Diagnostic réseau : l'hébergeur laisse-t-il sortir l'UDP (audio WebRTC) ?
  const diagnostiquer = async () => {
    const r = await action("diag", () => apiClient.post("/admin/appel-proprietaire/diagnostic-reseau"), () => "Diagnostic terminé");
    if (r) setDiag(r.data);
  };

  const effectif = donnees?.effectif || {};
  const moteur = donnees?.moteur || {};
  const champ = "mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm";

  return (
    <div className="space-y-3" data-testid="appel-proprietaire">
      <p className="text-xs text-slate-600">
        À chaque message WhatsApp d'un client, Liluvine vous <strong>relaie le message</strong> sur votre WhatsApp, puis vous
        <strong> appelle</strong> et vous dit : « Bonjour, ici Liluvine. &lt;qui&gt; écrit au support. Son dernier message date du … à … »,
        puis raccroche. Au plus un appel par client toutes les {form.appel_proprio_fenetre_min} minutes. L'alerte se coupe client par
        client sur sa fiche (« Appeler le propriétaire à chaque message », activé par défaut).
      </p>

      {/* État général */}
      <div className="flex flex-wrap gap-2 text-xs">
        <span className={`rounded-full px-2 py-0.5 ${effectif.actif && effectif.numeros?.length ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-700"}`}>
          {effectif.actif ? (effectif.numeros?.length ? "Alerte active" : "Inactive : numéro du propriétaire à renseigner") : "Alerte désactivée"}
        </span>
        {effectif.numeros_source === "environnement" && (
          <span className="rounded-full bg-sky-100 px-2 py-0.5 text-sky-800">Numéro lu dans NUMERO_APPEL_PROPRIETAIRE</span>
        )}
        <span className={`rounded-full px-2 py-0.5 ${moteur.disponible ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800"}`}
          title={moteur.raison || ""}>
          {moteur.disponible ? "Moteur d'appel vocal prêt" : "Moteur d'appel absent : relais seul"}
        </span>
        {moteur.voix?.length > 0 && <span className="rounded-full bg-violet-100 px-2 py-0.5 text-violet-800">Voix : {moteur.voix.join(" → ")}</span>}
      </div>

      {/* Autorisation d'appel du propriétaire (exigée par Meta) */}
      <div className="rounded-lg bg-white/70 p-2 ring-1 ring-slate-200">
        <p className="text-xs font-semibold text-slate-700">Autorisation d'appel du propriétaire</p>
        {(donnees?.permissions || []).length === 0 && <p className="text-xs text-slate-500">Aucun numéro renseigné.</p>}
        {(donnees?.permissions || []).map((p) => {
          const [libelle, couleur] = ETATS_PERMISSION[p.etat] || [p.etat, "bg-slate-100 text-slate-700"];
          return (
            <p key={p.telephone} className="mt-1 text-xs">
              +{p.telephone} : <span className={`rounded-full px-2 py-0.5 ${couleur}`}>{libelle}</span>
              {p.demande_le && <span className="ml-2 text-slate-500">demandée le {new Date(p.demande_le).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}</span>}
            </p>
          );
        })}
        <button type="button" onClick={demander} disabled={!!occupe || !(effectif.numeros || []).length}
          className="mt-2 rounded-lg border border-violet-300 bg-white px-3 py-1 text-xs font-semibold text-violet-800 hover:bg-violet-50 disabled:opacity-50">
          {occupe === "demander" ? <Jauge /> : "📨"} Envoyer la demande d'autorisation
        </button>
      </div>

      <label className="inline-flex items-center gap-2 text-sm font-semibold">
        <input type="checkbox" checked={form.appel_proprio_actif} onChange={(e) => maj("appel_proprio_actif", e.target.checked)} />
        Activer l'alerte du propriétaire
      </label>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-xs">
          <span className="font-semibold text-slate-700">Numéro(s) WhatsApp du propriétaire (séparés par des virgules)</span>
          <input value={form.appel_proprio_numeros} onChange={(e) => maj("appel_proprio_numeros", e.target.value)}
            placeholder="+226 70 00 00 00 (vide = variable NUMERO_APPEL_PROPRIETAIRE)" className={champ} />
        </label>
        <label className="block text-xs">
          <span className="font-semibold text-slate-700">Numéro SAWALI qui relaie et appelle</span>
          <select value={form.appel_proprio_ligne} onChange={(e) => maj("appel_proprio_ligne", e.target.value)} className={champ}>
            {(donnees?.lignes || []).map((l) => (
              <option key={l.cle} value={l.cle}>{l.libelle}{l.telephone ? ` — ${l.telephone}` : ""}</option>
            ))}
          </select>
        </label>
        <label className="block text-xs">
          <span className="font-semibold text-slate-700">Un appel par client au plus toutes les … minutes</span>
          <input type="number" min="1" value={form.appel_proprio_fenetre_min} onChange={(e) => maj("appel_proprio_fenetre_min", e.target.value)} className={champ} />
        </label>
        <div className="flex flex-col justify-end gap-1 text-xs">
          <label className="inline-flex items-center gap-2">
            <input type="checkbox" checked={form.appel_proprio_relais_actif} onChange={(e) => maj("appel_proprio_relais_actif", e.target.checked)} />
            Relayer le message par écrit
          </label>
          <label className="inline-flex items-center gap-2">
            <input type="checkbox" checked={form.appel_proprio_appel_actif} onChange={(e) => maj("appel_proprio_appel_actif", e.target.checked)} />
            Appeler (Liluvine parle)
          </label>
        </div>
      </div>

      {/* Heures calmes : relais seul, pas d'appel */}
      <div className="flex flex-wrap items-end gap-3 text-xs">
        <label className="inline-flex items-center gap-2 font-semibold">
          <input type="checkbox" checked={form.appel_proprio_calme_actif} onChange={(e) => maj("appel_proprio_calme_actif", e.target.checked)} />
          Heures calmes (pas d'appel, relais seul)
        </label>
        <label>de <input type="time" value={form.appel_proprio_calme_debut} onChange={(e) => maj("appel_proprio_calme_debut", e.target.value)}
          className="rounded border border-slate-300 px-1 py-0.5" /></label>
        <label>à <input type="time" value={form.appel_proprio_calme_fin} onChange={(e) => maj("appel_proprio_calme_fin", e.target.value)}
          className="rounded border border-slate-300 px-1 py-0.5" /></label>
      </div>

      <details className="text-xs">
        <summary className="cursor-pointer font-semibold text-slate-700">Réglages avancés (modèle Meta, voix, sonnerie, exclusions)</summary>
        <div className="mt-2 grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="font-semibold text-slate-700">Modèle Meta du relais (hors fenêtre de 24 h)</span>
            <input value={form.appel_proprio_modele} onChange={(e) => maj("appel_proprio_modele", e.target.value)}
              placeholder="ex. alerte_support — 3 variables : qui, extrait, date" className={champ} />
          </label>
          <label className="block">
            <span className="font-semibold text-slate-700">Langue du modèle</span>
            <input value={form.appel_proprio_modele_langue} onChange={(e) => maj("appel_proprio_modele_langue", e.target.value)} className={champ} />
          </label>
          <label className="block">
            <span className="font-semibold text-slate-700">Voix de Liluvine</span>
            <select value={form.appel_proprio_voix} onChange={(e) => maj("appel_proprio_voix", e.target.value)} className={champ}>
              <option value="auto">Automatique (OpenAI → ElevenLabs → Google)</option>
              <option value="openai">OpenAI (voix « nova »)</option>
              <option value="elevenlabs">ElevenLabs (voix ci-contre)</option>
              <option value="google">Google (sans clé)</option>
            </select>
          </label>
          <label className="block">
            <span className="font-semibold text-slate-700">Identifiant de voix ElevenLabs (facultatif)</span>
            <input value={form.appel_proprio_voix_elevenlabs} onChange={(e) => maj("appel_proprio_voix_elevenlabs", e.target.value)} className={champ} />
          </label>
          <label className="block">
            <span className="font-semibold text-slate-700">Message répété … fois (1 à 3)</span>
            <input type="number" min="1" max="3" value={form.appel_proprio_repetitions} onChange={(e) => maj("appel_proprio_repetitions", e.target.value)} className={champ} />
          </label>
          <label className="block">
            <span className="font-semibold text-slate-700">Sonnerie maximale (secondes)</span>
            <input type="number" min="10" max="60" value={form.appel_proprio_sonnerie_s} onChange={(e) => maj("appel_proprio_sonnerie_s", e.target.value)} className={champ} />
          </label>
          <label className="block sm:col-span-2">
            <span className="font-semibold text-slate-700">Numéros jamais relayés (personnel, tests… ; administrateurs et superviseurs déjà exclus)</span>
            <input value={form.appel_proprio_exclus} onChange={(e) => maj("appel_proprio_exclus", e.target.value)} className={champ} />
          </label>
        </div>
      </details>

      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={enregistrer} disabled={!!occupe}
          className="rounded-lg bg-violet-700 px-4 py-1.5 text-sm font-semibold text-white hover:bg-violet-800 disabled:opacity-50">
          {occupe === "enregistrer" ? <Jauge /> : null} Enregistrer
        </button>
        <button type="button" onClick={essai} disabled={!!occupe}
          className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50">
          {occupe === "essai" ? <Jauge /> : "📞"} Essai réel (relais + appel)
        </button>
        <button type="button" onClick={diagnostiquer} disabled={!!occupe}
          className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50">
          {occupe === "diag" ? <Jauge /> : "🛰️"} Diagnostic réseau (UDP / TURN)
        </button>
      </div>

      {diag && (
        <div className={`rounded-lg p-2 text-xs ring-1 ${diag.udp_sortant || diag.turn ? "bg-emerald-50 ring-emerald-200" : "bg-rose-50 ring-rose-200"}`}>
          <p className="font-semibold">{diag.conclusion || diag.raison}</p>
          {diag.candidats && <p className="text-slate-600">Candidats ICE : {Object.entries(diag.candidats).map(([k, v]) => `${k} × ${v}`).join(", ") || "aucun"}</p>}
        </div>
      )}

      {/* Dernières alertes (journal des appels, motif « alerte message ») */}
      {(donnees?.derniers || []).length > 0 && (
        <table className="w-full text-xs">
          <thead className="bg-slate-50 text-slate-600">
            <tr>
              <th className="px-2 py-1 text-left">Date</th>
              <th className="px-2 py-1 text-left">Client</th>
              <th className="px-2 py-1 text-left">Résultat</th>
            </tr>
          </thead>
          <tbody>
            {donnees.derniers.map((a) => (
              <tr key={a.id} className="border-t border-slate-100">
                <td className="whitespace-nowrap px-2 py-1">{a.created_at ? new Date(a.created_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : ""}</td>
                <td className="px-2 py-1">{a.alerte_client_nom || "—"}</td>
                <td className="px-2 py-1">{a.resultat || a.statut}{a.raison ? ` — ${a.raison}` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
