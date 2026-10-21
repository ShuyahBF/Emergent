/*
  Lot 272 — Paramètres : « Index MongoDB recommandés » — accélérer les pages lentes en un clic.
    - Le conseiller de performance d'Atlas a relevé des requêtes qui parcourent toute une collection faute d'index (export des
      tables e-Kol, journal des incidents, messages WhatsApp). Le cluster n'est PAS trop petit : ajouter ces index coûte moins
      cher qu'un palier Atlas supérieur.
    - L'écran liste les index recommandés avec leur état réel (présent, manquant, collection absente) ; le bouton crée les
      index manquants, en arrière-plan, et la page suit l'avancement. Aucune donnée n'est modifiée ni supprimée.
  API : GET /admin/index-mongo/etat, POST /admin/index-mongo/creer (backend/routes/index_mongo_recommandes.py), administrateur principal.
*/
import React, { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Loader2, RefreshCw, Zap } from "lucide-react";
import { apiClient } from "@/lib/api";

const nombre = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("fr-FR"));
// Pastilles d'état : couleur + libellé
const ETATS = {
  present: { libelle: "Présent", classe: "bg-emerald-100 text-emerald-800" },
  manquant: { libelle: "Manquant", classe: "bg-amber-100 text-amber-800" },
  collection_absente: { libelle: "Collection absente", classe: "bg-slate-100 text-slate-600" },
};

export default function IndexMongoSection() {
  const [donnees, setDonnees] = useState(null);
  const [charge, setCharge] = useState(true);
  const minuteur = useRef(null);

  // Lecture de l'état réel des index (lecture seule)
  const lire = useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/index-mongo/etat");
      setDonnees(r.data);
      return r.data;
    } catch (e) {
      toast.error(e?.response?.data?.detail || "État indisponible (réservé à l'administrateur principal)");
      return null;
    } finally { setCharge(false); }
  }, []);

  // Suivi de l'avancement toutes les 2 s tant que la création tourne
  const suivre = useCallback(() => {
    clearInterval(minuteur.current);
    minuteur.current = setInterval(async () => {
      const d = await lire();
      if (d && !d.creation.en_cours) {
        clearInterval(minuteur.current);
        if (d.creation.erreurs.length) toast.error(`${d.creation.erreurs.length} index n'ont pas pu être créés`);
        else toast.success(`${d.creation.crees} index créé(s)`);
      }
    }, 2000);
  }, [lire]);

  useEffect(() => {
    lire().then((d) => { if (d?.creation?.en_cours) suivre(); });
    return () => clearInterval(minuteur.current);
  }, [lire, suivre]);

  const creer = async () => {
    const n = donnees?.manquants || 0;
    if (!window.confirm(`Créer ${n} index manquant(s) maintenant ?\n\nAucune donnée n'est modifiée. La construction se fait sur le serveur MongoDB sans bloquer le site, mais peut durer quelques minutes : de préférence hors des heures de pointe.`)) return;
    try {
      const r = await apiClient.post("/admin/index-mongo/creer", {});
      if (r.data.rien_a_creer) { toast.message("Tous les index sont déjà présents"); return; }
      toast.message("Patientez… création en cours (arrière-plan)");
      suivre();
    } catch (e) { toast.error(e?.response?.data?.detail || "Lancement impossible"); }
  };

  if (charge) return <Loader2 className="h-5 w-5 animate-spin text-slate-400" />;
  if (!donnees) return <p className="text-sm text-slate-500">Cette rubrique est réservée à l'administrateur principal.</p>;

  const cr = donnees.creation;
  const enCours = !!cr.en_cours;
  const avance = cr.total ? Math.round((cr.fait / cr.total) * 100) : 0;

  return (
    <div className="space-y-4 text-sm" data-testid="index-mongo-section">
      <p className="text-xs text-slate-600">
        Le conseiller de performance d'Atlas a repéré des requêtes qui <b>parcourent toute une collection</b> faute d'index
        (export des tables e-Kol, journal des incidents, messages WhatsApp). <b>Le cluster n'est pas trop petit</b> : ces index
        sont plus économiques qu'un palier supérieur. Cet écran n'ajoute que des index : <b>aucune donnée n'est modifiée ni supprimée</b>.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={creer} disabled={enCours || donnees.manquants === 0} data-testid="index-mongo-creer"
          className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 text-white px-3 py-1.5 text-xs hover:bg-slate-800 disabled:opacity-50">
          {enCours ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
          {donnees.manquants ? `Créer les ${donnees.manquants} index manquants` : "Tous les index sont présents"}
        </button>
        <button type="button" onClick={lire} disabled={enCours} data-testid="index-mongo-actualiser"
          className="inline-flex items-center gap-1.5 rounded-lg bg-white ring-1 ring-slate-300 px-3 py-1.5 text-xs hover:bg-slate-50 disabled:opacity-50">
          <RefreshCw className="h-3.5 w-3.5" /> Actualiser
        </button>
      </div>

      {/* Avancement de la création (jauge) */}
      {enCours && (
        <div className="rounded-lg ring-1 ring-sky-200 bg-sky-50 p-3" data-testid="index-mongo-avancement">
          <div className="flex items-center gap-2 text-xs text-sky-900"><Loader2 className="h-3.5 w-3.5 animate-spin" />
            Patientez… {cr.fait} / {cr.total} {cr.courant && <>— {cr.courant}</>}</div>
          <div className="mt-2 h-2 rounded bg-sky-100"><div className="h-2 rounded bg-sky-500" style={{ width: `${avance}%` }} /></div>
        </div>
      )}
      {!enCours && cr.termine_le && cr.erreurs.length > 0 && (
        <ul className="rounded-lg ring-1 ring-red-200 bg-red-50 p-3 text-xs text-red-800 space-y-1" data-testid="index-mongo-erreurs">
          {cr.erreurs.map((e) => <li key={e.id}><b>{e.id}</b> : {e.erreur}</li>)}
        </ul>
      )}

      <div className="rounded-xl ring-1 ring-slate-200 bg-white overflow-auto">
        <table className="w-full text-xs" data-testid="index-mongo-table">
          <thead className="bg-slate-50 text-[11px] uppercase text-slate-500">
            <tr><th className="px-3 py-2 text-left">Collection</th><th className="px-2 text-left">Index (champs)</th>
              <th className="px-2 text-right">Documents</th><th className="px-2 text-left">Pourquoi</th><th className="px-2 text-left">État</th></tr>
          </thead>
          <tbody>
            {donnees.index.map((l) => (
              <tr key={l.id} className="border-t border-slate-100" data-testid={`index-mongo-ligne-${l.statut}`}>
                <td className="px-3 py-1.5 font-mono break-all">{l.collection}</td>
                <td className="px-2 font-mono">{l.cles.join(" + ")}</td>
                <td className="px-2 text-right tabular-nums">{nombre(l.documents)}</td>
                <td className="px-2 text-slate-600 min-w-[14rem]">{l.raison}</td>
                <td className="px-2"><span className={`rounded-full px-2 py-0.5 ${ETATS[l.statut].classe}`}>{ETATS[l.statut].libelle}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
