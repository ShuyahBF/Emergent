// ============================================================================
// Connexion par compte Google — état et réglage depuis les Paramètres (administrateur).
//   - le client Google (identifiant + secret) est CELUI DÉJÀ SAISI pour Google Agenda (ou GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET dans Render) ;
//   - il reste UNE chose à faire chez Google : déclarer l'adresse de retour ci-dessous dans « URI de redirection autorisés » de l'ID client ;
//   - chaque personne lie ensuite son compte Google dans « Mon compte » (aucun compte n'est créé ni rapproché par e-mail) ; le code de vérification reste demandé.
// Backend : GET /api/admin/google-connexion.
// ============================================================================
import React, { useCallback, useEffect, useState } from "react";
import { Copy, Link2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

export default function GoogleConnexionAdminSection() {
  const [etat, setEtat] = useState(null);      // null = chargement en cours
  const [enCours, setEnCours] = useState(false);

  const charger = useCallback(async () => {
    setEnCours(true);
    toast("Actualisation de la connexion par Google en cours…");
    try { const r = await apiClient.get("/admin/google-connexion"); setEtat(r.data); toast.success(`Connexion par Google : ${r.data.configure ? "client configuré" : "client absent"}, ${r.data.comptes_lies} compte(s) lié(s).`); }
    catch (e) { setEtat({ erreur: e?.response?.data?.detail || "Lecture impossible" }); toast.error("Lecture impossible"); }
    finally { setEnCours(false); }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  const copier = async () => { try { await navigator.clipboard.writeText(etat.adresse_retour); toast.success("Adresse copiée"); } catch { toast.error("Copie impossible : sélectionnez l'adresse à la main."); } };

  if (!etat) return <p className="text-sm text-slate-500">Chargement…</p>;
  if (etat.erreur) return <p className="text-sm text-red-700">{etat.erreur}</p>;
  return (
    <div className="space-y-3" data-testid="google-connexion-admin">
      <p className="text-xs text-slate-600">Le bouton « Se connecter avec Google » n'apparaît que si le client Google est configuré. Google remplace le mot de passe, pas le code de vérification.</p>
      <p className="text-sm">{etat.configure ? "✅ Client Google configuré (identifiant et secret déjà saisis)." : "⚠️ Client Google absent : saisissez l'identifiant et le secret dans la rubrique Google Agenda, ou GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET dans Render."}</p>
      <div className="rounded-lg bg-slate-50 p-3 text-sm space-y-1">
        <p className="font-semibold">Adresse de retour à déclarer chez Google (« URI de redirection autorisés ») :</p>
        <p className="flex flex-wrap items-center gap-2"><code className="break-all rounded bg-white px-2 py-1 text-xs" data-testid="google-adresse-retour">{etat.adresse_retour}</code>
          <button type="button" onClick={copier} className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-2 py-1 text-xs"><Copy className="h-3.5 w-3.5" />Copier</button></p>
        <p className="text-xs text-slate-500">Site de retour : {etat.site}</p>
      </div>
      <p className="text-sm flex items-center gap-2"><Link2 className="h-4 w-4" aria-hidden="true" />Comptes liés à Google : <b className="tabular-nums">{etat.comptes_lies}</b></p>
      <button type="button" onClick={charger} disabled={enCours} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm disabled:opacity-60"><RefreshCw className={`h-4 w-4 ${enCours ? "animate-spin" : ""}`} />Actualiser</button>
    </div>
  );
}
