// SupportPlateformesSection.jsx — Lot 90 : rubrique « 🛟 Support des plateformes web » des Paramètres.
// Pour chaque plateforme enregistrée (émetteurs : sTer, adLyn, beAuthentik, bfmobility…) : activer / désactiver le
// pictogramme d'assistance (le chat apparaît alors dans la liste déroulante du chat sous « <plateforme> - Support »),
// requêtes en attente / en cours / du mois. Règle des tableaux : survol bleu, sélection orange (CSS global).
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";

export default function SupportPlateformesSection() {
  const { user } = useAuth();
  const [plateformes, setPlateformes] = useState(null);
  const [selection, setSelection] = useState(null);
  const [enCours, setEnCours] = useState(null);

  // Lecture des plateformes et de leurs compteurs
  const charger = useCallback(async () => {
    try { setPlateformes((await apiClient.get("/admin/support-plateformes")).data.plateformes || []); }
    catch (e) { toast.error(e?.response?.data?.detail || "Liste indisponible"); setPlateformes([]); }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  // Activation / désactivation du support d'une plateforme (administrateur)
  const basculer = async (p) => {
    setEnCours(p.code);
    try {
      await apiClient.put(`/admin/support-plateformes/${p.code}`, { support_actif: !p.support_actif });
      toast.success(`${p.libelle} : ${!p.support_actif ? "activé" : "désactivé"}`);
      await charger();
    } catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible"); }
    finally { setEnCours(null); }
  };

  // Lot 99 — réponse automatique de Liluvine dans le support de la plateforme (activée par défaut)
  const basculerLiluvine = async (p) => {
    setEnCours(`lili-${p.code}`);
    try {
      await apiClient.put(`/admin/support-plateformes/${p.code}`, { liluvine_auto: !p.liluvine_auto });
      toast.success(`${p.libelle} : Liluvine ${!p.liluvine_auto ? "répond" : "ne répond plus"} automatiquement`);
      await charger();
    } catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible"); }
    finally { setEnCours(null); }
  };

  if (!plateformes) return <p className="text-sm text-slate-500">Patientez…</p>;
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-support-plateformes">
      <p className="text-xs text-slate-600">
        Une fois activé, un petit pictogramme d'assistance apparaît dans la plateforme (barre latérale du portail pour
        sTer et bfmobility, chaque boutique adLyn, l'espace membre beAuthentik). Les messages arrivent dans le chat de
        SAWALI, espace « <b>&lt;plateforme&gt; - Support</b> », un fil par utilisateur, avec un numéro de requête
        (SUP-STER-2026-0001). Pendant une conversation, la barre « ⏳ requêtes en attente » montre les autres demandes.
        La plateforme utilise sa clé d'émetteur (aucune nouvelle clé à saisir).
      </p>
      <p className="text-xs text-slate-600">
        Dans le chat, « <b>↩ Répondre</b> » sous chaque bulle cite le message auquel vous répondez ; un <b>son</b> est
        joué à chaque nouveau message (chat interne, Support Loois et plateformes), même si la connexion en temps réel
        a été coupée (vérification toutes les 30 secondes). Le son démarre après un premier clic sur la page (règle des navigateurs).
      </p>
      {/* Lot 99 — réponse automatique de Liluvine (mêmes règles que le Support Loois) */}
      <p className="text-xs text-slate-600">
        <b>🤖 Liluvine</b> répond d'elle-même tant qu'aucun agent n'a répondu : réponses courtes, au plus 3 échanges
        (dont 2 questions d'éclaircissement), puis elle passe la main à un agent. Sa réponse porte la pastille de
        l'assistant concerné (comptable, technicien…). Si elle ne sait pas, Claude répond à sa place. Dès que vous
        répondez, elle se tait.
      </p>
      {/* Lot 97 — une plateforme n'apparaît ici que si elle est enregistrée comme émetteur Liluvine */}
      <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">
        Une plateforme absente (ex. bfmobility) ? Créez son émetteur dans la rubrique « Liluvine — Transmission WA
        universelle » avec le code attendu par la plateforme (<b>bfmobility</b>), puis saisissez la clé affichée dans la
        variable <b>LILUVINE_WA_HMAC</b> du serveur de la plateforme sur Render. Elle apparaît alors ici ; activez son support.
      </p>
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs text-slate-500">
            <tr><th className="px-2 py-2">Plateforme</th><th className="px-2">Libellé dans le chat</th><th className="px-2">Support</th><th className="px-2">Liluvine</th>
              <th className="px-2">En attente</th><th className="px-2">En cours</th><th className="px-2">Ce mois</th></tr>
          </thead>
          <tbody>
            {plateformes.length === 0 && (
              <tr><td colSpan={7} className="px-2 py-4 text-center text-slate-500">Aucune plateforme enregistrée (menu Émetteurs de Liluvine).</td></tr>
            )}
            {plateformes.map((p) => (
              <tr key={p.code} onClick={() => setSelection(p.code)} aria-selected={selection === p.code}
                  className={`cursor-pointer border-t border-slate-100 ${selection === p.code ? "ligne-selectionnee" : ""}`}>
                <td className="px-2 py-1.5 font-semibold">{p.nom}{!p.actif && <span className="ml-1 text-[11px] text-rose-600">(émetteur désactivé)</span>}</td>
                <td className="px-2">{p.libelle}</td>
                <td className="px-2">
                  {user?.role === "admin" ? (
                    <button onClick={(e) => { e.stopPropagation(); basculer(p); }} disabled={enCours === p.code}
                            className={`rounded-full px-2 py-0.5 text-xs font-semibold ${p.support_actif ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-600"}`}>
                      {enCours === p.code ? "Patientez…" : p.support_actif ? "✅ Activé" : "Désactivé"}
                    </button>
                  ) : (p.support_actif ? "✅ Activé" : "Désactivé")}
                </td>
                <td className="px-2">
                  {user?.role === "admin" ? (
                    <button onClick={(e) => { e.stopPropagation(); basculerLiluvine(p); }} disabled={enCours === `lili-${p.code}`}
                            className={`rounded-full px-2 py-0.5 text-xs font-semibold ${p.liluvine_auto ? "bg-violet-100 text-violet-800" : "bg-slate-100 text-slate-600"}`}>
                      {enCours === `lili-${p.code}` ? "Patientez…" : p.liluvine_auto ? "🤖 Répond" : "Désactivée"}
                    </button>
                  ) : (p.liluvine_auto ? "🤖 Répond" : "Désactivée")}
                </td>
                <td className="px-2">{p.attente}</td><td className="px-2">{p.en_cours}</td><td className="px-2">{p.ce_mois}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
