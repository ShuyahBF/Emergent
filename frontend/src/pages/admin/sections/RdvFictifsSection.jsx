// =====================================================================
// Lot 211 — Rubrique des Paramètres « 📅 Rendez-vous fictifs — Liluvine ».
// Chaque matin dès 6 h, Liluvine prépare 2 à 4 rendez-vous FICTIFS par jour ouvré (réunions, formations, dépannages, suivis,
// assistances, démonstrations…) pour les prochains jours, dans le Google Agenda relié à SAWALI (sup.alphasofti@gmail.com).
//   GET / PUT /api/admin/rdv-fictifs        réglages, agenda relié, rendez-vous à venir, dernier passage
//   POST /api/admin/rdv-fictifs/generer      génère maintenant les jours qui n'ont pas encore de programme
//   POST /api/admin/rdv-fictifs/supprimer    supprime les rendez-vous fictifs créés par Liluvine (et eux seulement)
// Sans invité ni notification. Par défaut ils ne bloquent PAS les créneaux de réservation des vrais clients. Désactivé par défaut.
// =====================================================================
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."];

export default function RdvFictifsSection() {
  const [etat, setEtat] = useState(null);          // réponse du serveur
  const [actif, setActif] = useState(false);
  const [mini, setMini] = useState(2);
  const [maxi, setMaxi] = useState(4);
  const [jours, setJours] = useState(7);
  const [bloquent, setBloquent] = useState(false);
  const [agenda, setAgenda] = useState("");
  const [occupe, setOccupe] = useState("");        // "" | "enregistrer" | "generer" | "supprimer"
  const [bilan, setBilan] = useState(null);        // résultat d'une génération manuelle

  const charger = () => apiClient.get("/admin/rdv-fictifs").then((r) => {
    const d = r.data; setEtat(d); setActif(!!d.actif); setMini(d.mini); setMaxi(d.maxi); setJours(d.jours); setBloquent(!!d.bloquent); setAgenda(d.agenda || "");
  }).catch(() => toast.error("Réglages des rendez-vous fictifs illisibles"));
  useEffect(() => { charger(); }, []);

  // Enregistre les réglages
  const enregistrer = async () => {
    setOccupe("enregistrer");
    try { const { data } = await apiClient.put("/admin/rdv-fictifs", { actif, mini, maxi, jours, bloquent, agenda }); setEtat(data); toast.success("Réglages enregistrés"); }
    catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible"); } finally { setOccupe(""); }
  };
  // Génère maintenant les jours qui n'ont pas encore de programme
  const generer = async () => {
    setOccupe("generer");
    try {
      const { data } = await apiClient.post("/admin/rdv-fictifs/generer");
      setBilan(data);
      if (data.erreur) toast.error(data.erreur); else toast.success(`${data.evenements} rendez-vous créé(s) sur ${data.jours} jour(s)`);
      charger();
    } catch (e) { toast.error(e?.response?.data?.detail || "Génération impossible"); } finally { setOccupe(""); }
  };
  // Supprime les rendez-vous fictifs créés par Liluvine (confirmation demandée)
  const supprimer = async () => {
    if (!window.confirm("Supprimer de l'agenda TOUS les rendez-vous fictifs créés par Liluvine ? (les autres rendez-vous ne sont pas touchés)")) return;
    setOccupe("supprimer");
    try { const { data } = await apiClient.post("/admin/rdv-fictifs/supprimer"); toast.success(`${data.supprimes} rendez-vous supprimé(s)${data.restants ? `, ${data.restants} restant(s)` : ""}`); charger(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Suppression impossible"); } finally { setOccupe(""); }
  };

  if (!etat) return <p className="text-sm text-slate-500">Chargement…</p>;
  const mauvaisAgenda = etat.agenda_relie && etat.agenda_relie !== (etat.agenda || "").toLowerCase();
  return (
    <div className="space-y-3 text-sm text-slate-700" data-testid="rdv-fictifs-section">
      <p>
        Chaque matin à <b>06 h 00</b>, Liluvine prépare <b>{etat.mini} à {etat.maxi} rendez-vous fictifs par jour ouvré</b> pour les {etat.jours} prochains jours
        (réunions, formations, dépannages à distance, suivis, assistances, démonstrations…), dans l'horaire d'ouverture ({etat.ouverture}–{etat.fermeture};
        jours : {(etat.jours_ouvres || []).map((j) => JOURS[j]).join(" ")}). Un jour déjà préparé n'est jamais refait. Les rendez-vous
        <b> n'ont aucun invité et ne déclenchent aucune notification</b> ; leur description précise qu'ils sont fictifs.
      </p>
      <p className="text-xs text-slate-600">Agenda Google actuellement relié à SAWALI : <b>{etat.agenda_relie}</b></p>
      {mauvaisAgenda && (
        <p className="rounded-md bg-rose-50 p-2 text-xs text-rose-800 ring-1 ring-rose-200" data-testid="rdv-fictifs-agenda-alerte">
          ⚠ L'agenda relié n'est pas « {etat.agenda} » : par sécurité, rien ne sera créé. Reliez le bon compte (Paramètres → Google Agenda) ou changez l'agenda visé ci-dessous.
        </p>
      )}
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={actif} onChange={(e) => setActif(e.target.checked)} data-testid="rdv-fictifs-actif" />
        <span>Activer la préparation quotidienne (désactivée par défaut)</span>
      </label>
      <div className="grid gap-2 md:grid-cols-4">
        <label className="block text-xs font-medium text-slate-700">Minimum par jour
          <input type="number" min={1} max={6} value={mini} onChange={(e) => setMini(Math.max(1, Math.min(6, Number(e.target.value) || 1)))} className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm" />
        </label>
        <label className="block text-xs font-medium text-slate-700">Maximum par jour
          <input type="number" min={1} max={6} value={maxi} onChange={(e) => setMaxi(Math.max(1, Math.min(6, Number(e.target.value) || 1)))} className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm" />
        </label>
        <label className="block text-xs font-medium text-slate-700">Jours à préparer d'avance
          <input type="number" min={1} max={14} value={jours} onChange={(e) => setJours(Math.max(1, Math.min(14, Number(e.target.value) || 1)))} className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm" />
        </label>
        <label className="block text-xs font-medium text-slate-700">Agenda visé
          <input value={agenda} onChange={(e) => setAgenda(e.target.value)} maxLength={120} className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm" data-testid="rdv-fictifs-agenda" />
        </label>
      </div>
      <label className="flex items-start gap-2 text-xs">
        <input type="checkbox" className="mt-0.5" checked={bloquent} onChange={(e) => setBloquent(e.target.checked)} data-testid="rdv-fictifs-bloquent" />
        <span>Marquer ces rendez-vous comme « occupés » dans Google. <b>Attention :</b> les créneaux correspondants ne seraient alors plus proposés aux vrais clients
          pour la prise de rendez-vous en ligne. Décoché (conseillé) : ils restent « disponibles » et ne bloquent rien.</span>
      </label>
      <div className="flex flex-wrap items-center gap-2 boutons-distincts">
        <button type="button" onClick={enregistrer} disabled={!!occupe} className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-700 disabled:opacity-50" data-testid="rdv-fictifs-enregistrer">
          {occupe === "enregistrer" ? "Patientez…" : "Enregistrer"}
        </button>
        <button type="button" onClick={generer} disabled={!!occupe} className="rounded-md bg-sky-100 px-3 py-1.5 text-xs font-semibold text-sky-900 hover:bg-sky-200 disabled:opacity-50" data-testid="rdv-fictifs-generer">
          {occupe === "generer" ? "Patientez…" : "⚙️ Générer maintenant"}
        </button>
        <button type="button" onClick={supprimer} disabled={!!occupe} className="rounded-md bg-rose-100 px-3 py-1.5 text-xs font-semibold text-rose-800 hover:bg-rose-200 disabled:opacity-50" data-testid="rdv-fictifs-supprimer">
          {occupe === "supprimer" ? "Patientez…" : "🗑️ Supprimer les rendez-vous fictifs"}
        </button>
      </div>
      {bilan?.erreur && <p className="text-xs text-rose-700" data-testid="rdv-fictifs-erreur">{bilan.erreur}</p>}
      {/* Rendez-vous fictifs à venir, par jour */}
      <div className="space-y-1 rounded-md bg-white p-2 text-xs ring-1 ring-slate-200" data-testid="rdv-fictifs-liste">
        <p className="font-semibold">Rendez-vous fictifs à venir ({etat.a_venir.reduce((n, j) => n + j.evenements.length, 0)})</p>
        {etat.a_venir.length === 0 && <p className="text-slate-500">Aucun pour l'instant.</p>}
        {etat.a_venir.map((j) => (
          <div key={j.jour} className="border-t border-slate-100 pt-1">
            <b>{new Date(`${j.jour}T00:00:00`).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" })}</b>
            {j.evenements.map((e) => (
              <div key={e.id} className="text-slate-600">{String(e.debut).slice(11, 16)}–{String(e.fin).slice(11, 16)} · {e.titre}</div>
            ))}
          </div>
        ))}
      </div>
      {etat.dernier && (
        <p className="text-xs text-slate-500">Dernier passage : {new Date(etat.dernier.le).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })} — {etat.dernier.evenements} rendez-vous créé(s) sur {etat.dernier.jours} jour(s){etat.dernier.erreur ? ` — ${etat.dernier.erreur}` : ""}.</p>
      )}
    </div>
  );
}
