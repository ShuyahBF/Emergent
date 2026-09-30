// Lot 44 — Bandeau rouge permanent de la session « Voir en tant que ».
// Affiché en haut de TOUTES les pages (portail et administration) tant que cet
// onglet navigue en tant qu'un autre compte :
//   « Vous naviguez en tant que <nom> (<rôle>) — expire à HH:MM »
//   case « Lecture seule » (cochée par défaut) · bouton « Revenir à mon compte ».
// À l'heure d'expiration (ou si le serveur signale la session close), l'onglet
// revient seul au compte de l'Admin.
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Eye, LogOut } from "lucide-react";
import { apiClient, infoImp, sessionImpActive, quitterSessionImp } from "@/lib/api";
import { basculerLectureSeule, revenirAMonCompte } from "@/lib/voirEnTantQue";

const heure = (iso) => {
  try {
    return new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  } catch { return "—"; }
};

export default function BandeauVoirEnTantQue() {
  const [actif] = useState(() => sessionImpActive());
  const [info, setInfo] = useState(() => infoImp());
  const [enCours, setEnCours] = useState(false);
  const ref = useRef(null);

  // Hauteur du bandeau réservée en haut de la page (les mises en page « plein écran »
  // du portail et de l'administration sont réduites d'autant, voir le style ci-dessous).
  useLayoutEffect(() => {
    if (!actif || !ref.current) return undefined;
    const racine = document.documentElement;
    const maj = () => racine.style.setProperty("--imp-h", `${ref.current?.offsetHeight || 0}px`);
    maj();
    racine.classList.add("sawali-imp-actif");
    const obs = typeof ResizeObserver !== "undefined" ? new ResizeObserver(maj) : null;
    if (obs) obs.observe(ref.current);
    return () => {
      if (obs) obs.disconnect();
      racine.classList.remove("sawali-imp-actif");
      racine.style.removeProperty("--imp-h");
    };
  }, [actif]);

  // État tenu à jour par le serveur (lecture seule, heure de fin) ; session close → retour Admin.
  useEffect(() => {
    if (!actif) return undefined;
    let arret = false;
    const verifier = () => apiClient.get("/voir-en-tant-que/etat").then((r) => {
      if (arret) return;
      if (!r.data?.actif) { quitterSessionImp(); return; }
      setInfo((prev) => ({ ...(prev || {}), ro: r.data.ro, expire_le: r.data.expire_le,
                           cible_nom: r.data.cible_nom, cible_role: r.data.cible_role }));
    }).catch(() => { /* 401 : l'intercepteur ramène déjà au compte Admin */ });
    verifier();
    const t = setInterval(verifier, 60_000);
    return () => { arret = true; clearInterval(t); };
  }, [actif]);

  // Retour automatique au compte Admin à l'heure d'expiration du jeton.
  useEffect(() => {
    if (!actif || !info?.expire_le) return undefined;
    const reste = new Date(info.expire_le).getTime() - Date.now();
    const t = setTimeout(() => {
      toast.info("Session « Voir en tant que » expirée : retour à votre compte.");
      quitterSessionImp();
    }, Math.max(0, reste));
    return () => clearTimeout(t);
  }, [actif, info?.expire_le]);

  if (!actif) return null;

  const changerMode = async (e) => {
    const ro = e.target.checked;
    setEnCours(true);
    try {
      const nouveau = await basculerLectureSeule(ro);
      setInfo((prev) => ({ ...(prev || {}), ro: nouveau }));
      toast.success(nouveau ? "Lecture seule activée" : "Écritures autorisées (journalisées)");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Changement de mode impossible");
    } finally { setEnCours(false); }
  };

  const revenir = async () => {
    setEnCours(true);
    await revenirAMonCompte();
  };

  return (
    <>
      <style>{`
        html.sawali-imp-actif body { padding-top: var(--imp-h, 44px); }
        html.sawali-imp-actif .h-screen { height: calc(100vh - var(--imp-h, 44px)); }
        html.sawali-imp-actif .min-h-screen { min-height: calc(100vh - var(--imp-h, 44px)); }
      `}</style>
      <div
        ref={ref}
        role="alert"
        className="fixed top-0 inset-x-0 z-[10000] bg-rose-700 text-white shadow-lg"
        data-testid="bandeau-voir-en-tant-que"
      >
        <div className="px-4 py-2 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
          <span className="inline-flex items-center gap-2 font-semibold min-w-0">
            <Eye className="h-4 w-4 shrink-0" />
            <span className="break-words">
              Vous naviguez en tant que {info?.cible_nom || "—"}
              {info?.cible_role ? ` (${info.cible_role})` : ""} — expire à {heure(info?.expire_le)}
            </span>
          </span>
          <label className="inline-flex items-center gap-2 cursor-pointer select-none" title="Décochez pour tester une action (chaque écriture est journalisée)">
            <input
              type="checkbox"
              checked={info?.ro !== false}
              onChange={changerMode}
              disabled={enCours}
              className="h-4 w-4 accent-white"
              data-testid="bandeau-lecture-seule"
            />
            Lecture seule
          </label>
          <button
            type="button"
            onClick={revenir}
            disabled={enCours}
            className="ml-auto inline-flex items-center gap-1.5 rounded-md bg-white text-rose-700 px-3 py-1 font-semibold hover:bg-rose-50 disabled:opacity-60"
            data-testid="bandeau-revenir"
          >
            <LogOut className="h-4 w-4" /> Revenir à mon compte
          </button>
        </div>
      </div>
    </>
  );
}
