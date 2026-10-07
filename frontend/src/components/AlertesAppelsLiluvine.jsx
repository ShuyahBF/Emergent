// AlertesAppelsLiluvine.jsx — Lot 72 : « Liluvine m'informe quand elle appelle un contact ».
// Monté dans le portail pour l'administrateur et le superviseur. Toutes les 10 s, lit les alertes de l'agenda
// (/admin/liluvine-agenda/alertes) et affiche un toast PERSISTANT par appel :
//   - au départ : « 📞 Liluvine appelle <contact> — <type d'évènement> » ;
//   - à la fin : le même toast se met à jour (conversation terminée + résumé, pas de réponse, nouvel essai…).
// Le toast reste jusqu'à ce que l'utilisateur le ferme (×) ; une alerte fermée n'est plus jamais réaffichée
// (mémorisé dans le navigateur), même après un rechargement de la page.
import { useCallback, useEffect, useRef } from "react";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";
import { apiClient } from "@/lib/api";

const INTERVALLE_MS = 10_000;                         // fréquence de lecture des alertes
const CLE_FERMEES = "sawali.liluvine.alertes_fermees";  // alertes fermées par l'utilisateur (navigateur)
const MAX_FERMEES = 200;
const MAX_AU_CHARGEMENT = 5;                          // au plus 5 toasts à l'ouverture du portail

// Lecture / écriture de la liste des alertes fermées (tolère un navigateur sans stockage)
function lireFermees() {
  try { return new Set(JSON.parse(localStorage.getItem(CLE_FERMEES) || "[]")); } catch { return new Set(); }
}
function ecrireFermees(ensemble) {
  try { localStorage.setItem(CLE_FERMEES, JSON.stringify(Array.from(ensemble).slice(-MAX_FERMEES))); } catch { /* ignore */ }
}

// Pictogramme et couleurs selon l'état de l'appel
const STYLES = {
  appel: { icone: "📞", anneau: "ring-emerald-300", titre: "text-emerald-700", fond: "bg-emerald-50" },
  termine: { icone: "✅", anneau: "ring-sky-300", titre: "text-sky-700", fond: "bg-sky-50" },
  nouvelle_tentative: { icone: "🔁", anneau: "ring-amber-300", titre: "text-amber-700", fond: "bg-amber-50" },
  sans_reponse: { icone: "📵", anneau: "ring-amber-300", titre: "text-amber-700", fond: "bg-amber-50" },
  refuse: { icone: "🚫", anneau: "ring-rose-300", titre: "text-rose-700", fond: "bg-rose-50" },
  echec: { icone: "⚠️", anneau: "ring-rose-300", titre: "text-rose-700", fond: "bg-rose-50" },
};

export default function AlertesAppelsLiluvine() {
  const navigate = useNavigate();
  const depuisRef = useRef(null);       // heure serveur de la dernière lecture
  const fermeesRef = useRef(lireFermees());
  const etatsRef = useRef({});          // id → dernier état affiché (évite de redessiner pour rien)

  // Affiche (ou met à jour) le toast d'une alerte ; même id = même toast mis à jour
  const afficher = useCallback((a) => {
    if (fermeesRef.current.has(a.id)) return;
    const cle = `${a.etat}|${a.resultat || ""}`;
    if (etatsRef.current[a.id] === cle) return;
    etatsRef.current[a.id] = cle;
    const st = STYLES[a.etat] || STYLES.appel;
    const fermer = () => {
      fermeesRef.current.add(a.id);
      ecrireFermees(fermeesRef.current);
      toast.dismiss(a.id);
    };
    const heure = new Date(a.le).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
    toast.custom(() => (
      <div className={`flex w-[22rem] max-w-full items-start gap-3 rounded-xl bg-white p-3 shadow-xl ring-2 ${st.anneau}`}
        data-testid={`alerte-appel-liluvine-${a.id}`}>
        <div className={`flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full text-lg ${st.fond}`}>{st.icone}</div>
        <div className="min-w-0 flex-1">
          <p className={`text-[10px] font-semibold uppercase tracking-wider ${st.titre}`}>
            {a.etat === "appel" ? "Liluvine appelle" : "Appel de Liluvine"} · {heure}
          </p>
          <p className="truncate text-sm font-semibold text-slate-900">{a.contact_nom}</p>
          <p className="text-xs text-slate-600">
            {a.type_libelle}{a.titre ? ` — ${a.titre}` : ""}{a.tentative > 1 ? ` · essai ${a.tentative}` : ""}
          </p>
          {a.etat === "appel"
            ? <p className="mt-1 text-xs text-emerald-700">Appel en cours…</p>
            : <p className="mt-1 text-xs font-medium text-slate-800">{a.resultat}</p>}
          {a.resume && <p className="mt-1 line-clamp-3 text-[11px] italic text-slate-600">{a.resume}</p>}
          <button type="button" onClick={() => { fermer(); navigate(`/admin/liluvine-agenda?ev=${encodeURIComponent(a.ev_id)}`); }}
            className="mt-2 text-[11px] font-medium text-sawali-blue hover:underline">Voir l'évènement ↗</button>
        </div>
        <button type="button" onClick={fermer} aria-label="Fermer" title="Fermer cette alerte"
          className="text-lg leading-none text-slate-400 hover:text-slate-700">×</button>
      </div>
    ), { id: a.id, duration: Infinity, position: "top-right" });   // persistant : reste jusqu'à fermeture
  }, [navigate]);

  // Lecture périodique des alertes nouvelles ou modifiées
  const lire = useCallback(async (premiere) => {
    try {
      const r = await apiClient.get("/admin/liluvine-agenda/alertes",
        { params: depuisRef.current ? { since: depuisRef.current } : {} });
      depuisRef.current = r.data?.server_now || depuisRef.current;
      let alertes = (r.data?.alertes || []).filter((a) => !fermeesRef.current.has(a.id));
      if (premiere) alertes = alertes.slice(0, MAX_AU_CHARGEMENT);   // les plus récentes seulement
      alertes.slice().reverse().forEach(afficher);                   // ordre chronologique
    } catch { /* réseau ou droits : on réessaie au tour suivant */ }
  }, [afficher]);

  useEffect(() => {
    lire(true);
    const minuteur = setInterval(() => lire(false), INTERVALLE_MS);
    return () => clearInterval(minuteur);
  }, [lire]);

  return null;   // rien à afficher en dehors des toasts
}
