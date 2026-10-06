// JournalAppelsCarte.jsx — Lot 64 : journal des appels WhatsApp résumé, pour le superviseur
// (tableau de bord du portail et écran de bienvenue).
//
// Affiche les derniers appels (sens, correspondant, ligne, statut, durée, agent) et le bilan
// du jour : nombre d'appels, appels manqués, durée totale. « Voir tout » ouvre le journal
// complet (fenêtre gérée par AppelsWhatsApp.jsx, évènement « sawali:journal-appels »).
import React, { useEffect, useState } from "react";
import { PhoneIncoming, PhoneOutgoing, PhoneMissed } from "lucide-react";
import { apiClient } from "@/lib/api";
import PastilleLigneWa from "./PastilleLigneWa";
import { dureeLisible } from "./AppelsWhatsApp";

// Libellés et couleurs des statuts d'appel
const STATUTS = {
  termine: ["Terminé", "text-emerald-700"],
  en_cours: ["En cours", "text-sky-700"],
  sonne: ["Sonne", "text-amber-700"],
  decroche: ["Décroché", "text-sky-700"],
  appel: ["Appel en cours", "text-sky-700"],
  manque: ["Manqué", "text-rose-700"],
  refuse: ["Refusé", "text-rose-700"],
  sans_reponse: ["Sans réponse", "text-amber-700"],
  echec: ["Échec", "text-rose-700"],   // Lot 67 — alerte du propriétaire non aboutie
};

export default function JournalAppelsCarte({ limite = 6, testid = "journal-appels-carte" }) {
  const [items, setItems] = useState(null);

  // Lecture des derniers appels visibles par l'utilisateur (entreprise + lignes autorisées)
  useEffect(() => {
    apiClient.get("/me/wa-appels", { params: { limit: 50 } })
      .then((r) => setItems(r.data?.items || []))
      .catch(() => setItems([]));
  }, []);

  if (items === null) return null;

  // Bilan du jour (heure locale du navigateur)
  const aujourdhui = new Date().toDateString();
  const duJour = items.filter((a) => a.created_at && new Date(a.created_at).toDateString() === aujourdhui);
  const manques = duJour.filter((a) => a.statut === "manque").length;
  const dureeJour = duJour.reduce((t, a) => t + (Number(a.duree_s) || 0), 0);

  return (
    <section className="rounded-lg ring-1 ring-emerald-200 bg-gradient-to-br from-emerald-50/60 via-white to-sky-50/40 p-3" data-testid={testid}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-emerald-900">📞 Journal des appels WhatsApp</h3>
        <button type="button" onClick={() => window.dispatchEvent(new CustomEvent("sawali:journal-appels", { detail: {} }))}
          className="text-xs font-semibold text-emerald-700 hover:underline">
          Voir tout →
        </button>
      </div>
      {/* Bilan du jour */}
      <div className="mb-2 grid grid-cols-3 gap-2 text-center">
        <div className="rounded bg-white/80 py-1.5 ring-1 ring-slate-100">
          <p className="text-lg font-bold tabular-nums">{duJour.length}</p>
          <p className="text-[10px] text-slate-500">appels aujourd'hui</p>
        </div>
        <div className="rounded bg-white/80 py-1.5 ring-1 ring-slate-100">
          <p className={`text-lg font-bold tabular-nums ${manques ? "text-rose-700" : ""}`}>{manques}</p>
          <p className="text-[10px] text-slate-500">manqué(s)</p>
        </div>
        <div className="rounded bg-white/80 py-1.5 ring-1 ring-slate-100">
          <p className="text-lg font-bold tabular-nums">{dureeLisible(dureeJour)}</p>
          <p className="text-[10px] text-slate-500">durée totale</p>
        </div>
      </div>
      {/* Derniers appels */}
      {items.length === 0 ? (
        <p className="text-xs text-slate-500">Aucun appel WhatsApp pour le moment.</p>
      ) : (
        <ul className="divide-y divide-slate-100 rounded bg-white/80 ring-1 ring-slate-100">
          {items.slice(0, limite).map((a) => {
            const [libelle, couleur] = STATUTS[a.statut] || [a.statut, "text-slate-600"];
            const Icone = a.statut === "manque" ? PhoneMissed : a.direction === "sortant" ? PhoneOutgoing : PhoneIncoming;
            return (
              <li key={a.id} className="flex items-center gap-2 px-2 py-1.5 text-xs">
                <Icone className={`h-3.5 w-3.5 shrink-0 ${couleur}`} />
                <span className="min-w-0 flex-1 truncate font-medium">
                  {a.contact_nom}
                  {/* Lot 67 — motif « alerte message » : client qui a écrit */}
                  {a.motif && !a.liluvine && <span className="ml-1 font-normal text-violet-700">· 🔔 {a.alerte_client_nom || a.motif}</span>}
                  {/* Lot 69 — appel pris par Liluvine : résumé au survol */}
                  {a.liluvine && <span className="ml-1 font-normal text-violet-700" title={a.liluvine.resume || ""}>· 🤖 Liluvine</span>}
                </span>
                {a.ligne && <PastilleLigneWa libelle={a.ligne.libelle} fond={a.ligne.fond} texte={a.ligne.texte} />}
                <span className={`shrink-0 ${couleur}`}>{libelle}</span>
                <span className="w-16 shrink-0 text-right tabular-nums text-slate-600">{a.duree_s ? dureeLisible(a.duree_s) : "—"}</span>
                <span className="hidden w-24 shrink-0 truncate text-right text-slate-500 sm:inline">
                  {a.created_at ? new Date(a.created_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : ""}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
