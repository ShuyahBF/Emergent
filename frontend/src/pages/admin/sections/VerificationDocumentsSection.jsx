/*
  Lot 268 — Paramètres : « Authenticité des documents » — QR code chiffré, vérifié uniquement sur SAWALI.
    - Bouton « Générer la clé » : SAWALI crée une paire de clés ; la clé PRIVÉE reste chiffrée sur le serveur (jamais affichée),
      la clé PUBLIQUE s'affiche ici (sans danger) pour être donnée au générateur du document.
    - Remplacer la clé rend invérifiables tous les QR déjà imprimés : une case à cocher l'impose.
    - Zone de test : coller un lien ou un jeton pour voir le contenu déchiffré, comme le fait le téléphone.
  API : GET /admin/verification-documents, POST /admin/verification-documents/generer, GET /public/verifier-document
  (backend/routes/verification_documents.py). Page publique : /verifier-document.
*/
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Copy, KeyRound, Loader2, ShieldCheck } from "lucide-react";
import { apiClient } from "@/lib/api";

const dateFr = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");

export default function VerificationDocumentsSection() {
  const [etat, setEtat] = useState(null);
  const [occupe, setOccupe] = useState(false);
  const [remplacer, setRemplacer] = useState(false);
  const [saisie, setSaisie] = useState("");
  const [resultat, setResultat] = useState(null);

  const lire = useCallback(async () => {
    try { setEtat((await apiClient.get("/admin/verification-documents")).data); }
    catch (e) { toast.error(e?.response?.data?.detail || "Réservé à l'administrateur principal"); }
  }, []);
  useEffect(() => { lire(); }, [lire]);

  // Crée (ou remplace) la paire de clés
  const generer = async () => {
    setOccupe(true);
    try {
      await apiClient.post("/admin/verification-documents/generer", { remplacer: !!etat?.cree });
      toast.success("Clé générée");
      setRemplacer(false);
      await lire();
    } catch (e) { toast.error(e?.response?.data?.detail || "Échec de la génération"); }
    finally { setOccupe(false); }
  };

  const copier = async () => {
    try { await navigator.clipboard.writeText(etat.cle_publique); toast.success("Clé publique copiée"); }
    catch { toast.error("Copie impossible : sélectionnez le texte à la main"); }
  };

  // Teste un lien ou un jeton collé : extrait le paramètre t puis demande le déchiffrement
  const tester = async () => {
    const m = saisie.match(/[?&]t=([^&\s]+)/);
    const jeton = (m ? m[1] : saisie).trim();
    try { setResultat((await apiClient.get("/public/verifier-document", { params: { t: jeton } })).data); }
    catch { toast.error("Vérification impossible"); }
  };

  if (!etat) return <p className="text-sm text-slate-500">Chargement…</p>;
  return (
    <div className="space-y-4 text-sm" data-testid="verification-documents">
      <p className="text-slate-600">
        Chaque page d'un document officiel porte un QR code qui ouvre <b>{etat.site_verification}</b> avec un jeton <b>chiffré</b>.
        Seul SAWALI peut le déchiffrer : la page affiche alors le titre, la version, le copyright, l'exemplaire et la page.
      </p>

      <div className="rounded-lg border border-slate-200 p-3 space-y-2">
        <p className="flex items-center gap-2 font-semibold">
          <KeyRound className="h-4 w-4" /> Clé : {etat.cree ? `créée le ${dateFr(etat.cree_le)}` : "pas encore créée"}
        </p>
        {etat.cree && (
          <div>
            <p className="text-xs text-slate-500">Clé publique (à communiquer pour fabriquer les QR codes — sans danger) :</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 break-all rounded bg-slate-100 p-2 text-xs" data-testid="cle-publique">{etat.cle_publique}</code>
              <button type="button" onClick={copier} className="rounded border px-2 py-1 text-xs" title="Copier la clé publique"><Copy className="h-3.5 w-3.5" /></button>
            </div>
          </div>
        )}
        {etat.cree && (
          <label className="flex items-start gap-2 text-xs text-amber-800">
            <input type="checkbox" checked={remplacer} onChange={(e) => setRemplacer(e.target.checked)} className="mt-0.5" />
            Je comprends que remplacer la clé rend invérifiables tous les QR codes déjà imprimés.
          </label>
        )}
        <button type="button" onClick={generer} disabled={occupe || (etat.cree && !remplacer)}
          className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-3 py-2 text-white disabled:opacity-40" data-testid="verif-generer">
          {occupe && <Loader2 className="h-4 w-4 animate-spin" />}{etat.cree ? "Remplacer la clé" : "Générer la clé"}
        </button>
      </div>

      <div className="rounded-lg border border-slate-200 p-3 space-y-2">
        <p className="flex items-center gap-2 font-semibold"><ShieldCheck className="h-4 w-4" /> Tester un lien ou un jeton</p>
        <input value={saisie} onChange={(e) => setSaisie(e.target.value)} placeholder="Collez ici le lien du QR code"
          className="w-full rounded border border-slate-300 px-3 py-2" data-testid="verif-saisie" />
        <button type="button" onClick={tester} disabled={!saisie.trim()} className="rounded-lg border px-3 py-2 disabled:opacity-40">Vérifier</button>
        {resultat && (resultat.authentique
          ? <p className="rounded bg-emerald-50 p-2 text-emerald-800" data-testid="verif-test-ok">Authentique — {resultat.titre} · version du {resultat.version} · exemplaire {resultat.exemplaire || "—"} · page {resultat.page || "—"}<br />{resultat.droits}</p>
          : <p className="rounded bg-red-50 p-2 text-red-800" data-testid="verif-test-ko">Non reconnu (invalide, modifié ou émis par une autre clé).</p>)}
      </div>
    </div>
  );
}
