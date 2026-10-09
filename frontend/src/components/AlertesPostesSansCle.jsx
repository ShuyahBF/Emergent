// AlertesPostesSansCle.jsx — Lot 89 : alerte « postes Loois sans clé client valable » (administrateur et superviseur).
// Loois n'affiche plus AUCUN message sur le poste (les utilisateurs pourraient se croire suivis ou contrôlés) :
// c'est SAWALI qui prévient. Toutes les 5 minutes, lit /admin/loois-postes-sans-cle et affiche un toast PERSISTANT
// (« 🔑 N poste(s) Loois sans clé client valable ») avec les premiers postes et un bouton vers la rubrique des
// Paramètres. Fermé (×), il ne revient que si la liste change (nouveau poste, autre état) — mémorisé dans le navigateur.
import { useCallback, useEffect, useRef } from "react";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";
import { apiClient } from "@/lib/api";

const INTERVALLE_MS = 5 * 60_000;                       // lecture toutes les 5 minutes
const CLE_FERMEE = "sawali.loois.postes_sans_cle.ferme";  // signature de la liste fermée par l'utilisateur
const ID_TOAST = "loois-postes-sans-cle";
const MAX_LIGNES = 4;                                   // postes montrés dans le toast (le reste : « et N autre(s) »)

// Signature de la liste : change dès qu'un poste apparaît, disparaît ou change d'état
const signature = (postes) => postes.map((p) => `${p.machine}|${p.statut}`).sort().join(";");
const lireFermee = () => { try { return localStorage.getItem(CLE_FERMEE) || ""; } catch { return ""; } };
const ecrireFermee = (v) => { try { localStorage.setItem(CLE_FERMEE, v); } catch { /* navigateur sans stockage */ } };

// admin : vrai pour l'administrateur (bouton « Voir » vers les Paramètres) ; le superviseur n'a pas accès à /admin
export default function AlertesPostesSansCle({ admin = false }) {
  const navigate = useNavigate();
  const signatureAffichee = useRef("");

  // Une lecture : affiche, met à jour ou retire le toast
  const lire = useCallback(async () => {
    let donnees;
    try {
      donnees = (await apiClient.get("/admin/loois-postes-sans-cle")).data;
    } catch {
      return;   // hors ligne ou rôle non autorisé : rien à afficher
    }
    const postes = donnees?.actif ? donnees.postes || [] : [];
    const sig = signature(postes);
    if (!postes.length) {
      toast.dismiss(ID_TOAST);
      signatureAffichee.current = "";
      return;
    }
    if (sig === lireFermee() || sig === signatureAffichee.current) return;   // déjà fermé ou déjà affiché
    signatureAffichee.current = sig;
    const autres = postes.length - MAX_LIGNES;
    toast.warning(`🔑 ${postes.length} poste(s) Loois sans clé client valable`, {
      id: ID_TOAST,
      duration: Infinity,
      description: (
        <div className="space-y-0.5 text-xs" data-testid="alerte-postes-sans-cle">
          {postes.slice(0, MAX_LIGNES).map((p) => (
            <div key={p.machine}>
              <b>{p.machine}</b>{p.site ? ` (${p.site})` : ""} — {p.libelle}{p.en_ligne ? " · en ligne" : ""}
            </div>
          ))}
          {autres > 0 && <div>… et {autres} autre(s)</div>}
          <div className="opacity-80">
            Rien n'est affiché sur ces postes : {admin ? "créez puis saisissez leur clé client." : "prévenez l'administrateur (clé client à créer)."}
          </div>
        </div>
      ),
      ...(admin ? { action: { label: "Voir", onClick: () => navigate("/admin/settings#s-postes-sans-cle") } } : {}),
      onDismiss: () => ecrireFermee(sig),
    });
  }, [navigate, admin]);

  // Première lecture 20 s après l'ouverture du portail (ne gêne pas le chargement), puis toutes les 5 minutes
  useEffect(() => {
    const premier = setTimeout(lire, 20_000);
    const minuterie = setInterval(lire, INTERVALLE_MS);
    return () => { clearTimeout(premier); clearInterval(minuterie); };
  }, [lire]);

  return null;
}
