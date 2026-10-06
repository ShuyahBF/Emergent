// AppelsDansConversation.jsx — Lot 64.3 : les appels WhatsApp (reçus et émis) apparaissent
// dans le fil de conversation d'un contact, à leur place chronologique parmi les messages.
//
// - useAppelsWa(telephone) : lit le journal des appels de ce numéro (/me/wa-appels?telephone=…)
//   et le relit toutes les 15 s (et après un décroché / refus / raccroché, évènement « sawali:appels-maj ») ;
// - fusionnerAppels(messages, appels) : liste unique triée par date, les appels étant marqués
//   « __appel » (les messages eux-mêmes ne sont pas modifiés) ;
// - BulleAppelWa : carte centrée « 📞 Appel reçu · Terminé · 1 min 35 s · décroché par … ».
import React, { useCallback, useEffect, useState } from "react";
import { PhoneIncoming, PhoneOutgoing, PhoneMissed, PhoneOff } from "lucide-react";
import { apiClient } from "@/lib/api";
import { dureeLisible } from "./AppelsWhatsApp";

const RELECTURE_MS = 15000;

// Libellés et couleurs des statuts d'appel
const STATUTS = {
  termine: ["Terminé", "bg-emerald-50 text-emerald-800 ring-emerald-200"],
  en_cours: ["En cours", "bg-sky-50 text-sky-800 ring-sky-200"],
  decroche: ["Décroché", "bg-sky-50 text-sky-800 ring-sky-200"],
  sonne: ["Sonne…", "bg-amber-50 text-amber-800 ring-amber-200"],
  appel: ["Appel en cours", "bg-sky-50 text-sky-800 ring-sky-200"],
  manque: ["Manqué", "bg-rose-50 text-rose-800 ring-rose-200"],
  refuse: ["Refusé", "bg-rose-50 text-rose-800 ring-rose-200"],
  sans_reponse: ["Sans réponse", "bg-amber-50 text-amber-800 ring-amber-200"],
};

// Lecture (et relecture périodique) des appels d'un numéro
export function useAppelsWa(telephone) {
  const [appels, setAppels] = useState([]);
  const lire = useCallback(async () => {
    const chiffres = String(telephone || "").replace(/\D/g, "");
    if (chiffres.length < 6) { setAppels([]); return; }
    try {
      const r = await apiClient.get("/me/wa-appels", { params: { telephone: chiffres, limit: 100 } });
      setAppels(r.data?.items || []);
    } catch {
      /* journal indisponible : la conversation reste affichée sans les appels */
    }
  }, [telephone]);
  useEffect(() => {
    setAppels([]);
    lire();
    const t = setInterval(() => { if (!document.hidden) lire(); }, RELECTURE_MS);
    // Décroché, refusé ou raccroché dans le portail : relecture après le traitement par Meta
    const surAppel = () => { setTimeout(lire, 1500); setTimeout(lire, 6000); };
    window.addEventListener("sawali:appels-maj", surAppel);
    return () => { clearInterval(t); window.removeEventListener("sawali:appels-maj", surAppel); };
  }, [lire]);
  return appels;
}

// Date de tri d'un élément (message ou appel)
const dateDe = (x) => new Date(x.sonne_le || x.created_at || x.received_at || x.timestamp || 0).getTime() || 0;

// Messages + appels dans l'ordre chronologique (tri stable : l'ordre des messages est conservé)
export function fusionnerAppels(messages, appels) {
  if (!appels || appels.length === 0) return messages || [];
  const items = (appels || []).map((a) => ({ ...a, __appel: true, id: `appel-${a.id}` }));
  return [...(messages || []), ...items]
    .map((x, i) => ({ x, i, t: dateDe(x) }))
    .sort((a, b) => (a.t - b.t) || (a.i - b.i))
    .map((e) => e.x);
}

// Carte d'un appel dans le fil de conversation
export function BulleAppelWa({ a }) {
  const sortant = a.direction === "sortant";
  const [libelle, couleurs] = STATUTS[a.statut] || [a.statut || "—", "bg-slate-50 text-slate-700 ring-slate-200"];
  const Icone = a.statut === "manque" ? PhoneMissed
    : a.statut === "refuse" || a.statut === "sans_reponse" ? PhoneOff
      : sortant ? PhoneOutgoing : PhoneIncoming;
  const quand = dateDe(a)
    ? new Date(dateDe(a)).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "";
  return (
    <div className="flex justify-center" data-testid={`appel-dans-fil-${a.id}`}>
      <div className={`inline-flex max-w-[90%] flex-wrap items-center gap-x-2 gap-y-0.5 rounded-full px-3 py-1 text-xs ring-1 ${couleurs}`}>
        <Icone className="h-3.5 w-3.5 shrink-0" />
        <span className="font-semibold">{sortant ? "Appel émis" : "Appel reçu"}</span>
        <span>· {libelle}</span>
        {Number(a.duree_s) > 0 && <span>· {dureeLisible(a.duree_s)}</span>}
        {a.decroche_par_nom && <span className="opacity-80">· {sortant ? "par" : "décroché par"} {a.decroche_par_nom}</span>}
        {a.ligne?.libelle && <span className="opacity-70">· {a.ligne.libelle}</span>}
        {quand && <span className="opacity-60">· {quand}</span>}
      </div>
    </div>
  );
}
