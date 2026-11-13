// pages/public/OfficinePaiement.jsx — Lot 386 : page PUBLIQUE de paiement mobile au comptoir d'une officine.
// Le client scanne le QR posé au comptoir : il choisit l'opérateur (liste déroulante), saisit le montant et obtient la séquence USSD
// à composer (Orange Money, Moov Money, Telecel Money). AUCUN paiement ne passe par SAWALI : le client compose la séquence
// sur son téléphone et saisit son code secret dans le menu de l'opérateur.
// iPhone : le lien « tel: » ne pré-remplit pas les codes contenant * ou # ; on propose donc de COPIER la séquence.
import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Check, Copy, Loader2, Phone, ShieldCheck, Store } from "lucide-react";
import { apiClient } from "@/lib/api";

const SUR_IOS = /iPhone|iPad|iPod/.test(typeof navigator !== "undefined" ? navigator.userAgent : "");

export default function OfficinePaiement() {
  const { jeton } = useParams();
  const [officine, setOfficine] = useState(null);
  const [erreur, setErreur] = useState("");
  const [operateur, setOperateur] = useState("");
  const [montant, setMontant] = useState("");
  const [occupe, setOccupe] = useState(false);
  const [resultat, setResultat] = useState(null);
  const [copie, setCopie] = useState(false);

  // Charge le nom de la pharmacie et les opérateurs qu'elle accepte
  useEffect(() => {
    apiClient.get(`/officine-paiement/${jeton}`)
      .then(({ data }) => { setOfficine(data); if (data.operateurs.length === 1) setOperateur(data.operateurs[0]); })
      .catch(() => setErreur("Ce QR code de paiement n'est plus valide. Demandez-en un nouveau au comptoir."));
  }, [jeton]);

  // Demande la séquence USSD du paiement
  const obtenir = async (e) => {
    e.preventDefault();
    setOccupe(true); setErreur(""); setResultat(null); setCopie(false);
    try {
      const { data } = await apiClient.post(`/officine-paiement/${jeton}/ussd`, { operateur, montant });
      setResultat(data);
    } catch (err) {
      setErreur(err?.response?.data?.detail || "Impossible d'obtenir le code : réessayez.");
    } finally { setOccupe(false); }
  };

  const copier = async () => {
    try { await navigator.clipboard.writeText(resultat.code_ussd); setCopie(true); } catch { setErreur("Copie impossible : recopiez le code à la main."); }
  };

  if (!officine) {
    return <div className="mx-auto max-w-md p-6 text-center text-sm text-slate-600">{erreur || <Loader2 className="mx-auto h-5 w-5 animate-spin" />}</div>;
  }
  return (
    <div className="mx-auto max-w-md space-y-4 p-4" data-testid="officine-paiement">
      <div className="flex items-center gap-2 text-slate-900">
        <Store className="h-5 w-5 text-emerald-700" />
        <h1 className="text-lg font-bold">Payer à {officine.nom}</h1>
      </div>
      <form onSubmit={obtenir} className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
        <label className="block text-sm font-medium text-slate-700">Opérateur
          <select value={operateur} onChange={(e) => setOperateur(e.target.value)} required
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-base" data-testid="paiement-operateur">
            <option value="">Choisir…</option>
            {officine.operateurs.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </label>
        <label className="block text-sm font-medium text-slate-700">Montant (FCFA)
          <input value={montant} onChange={(e) => setMontant(e.target.value)} inputMode="numeric" required placeholder="Ex. 5000"
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-base" data-testid="paiement-montant" />
        </label>
        <button type="submit" disabled={occupe || !operateur || !montant}
          className="w-full rounded-lg bg-emerald-700 px-4 py-3 text-base font-semibold text-white disabled:opacity-50" data-testid="paiement-obtenir">
          {occupe ? "Patientez…" : "Obtenir le code à composer"}
        </button>
      </form>
      {erreur && <p className="rounded-lg bg-rose-50 p-3 text-sm text-rose-800" data-testid="paiement-erreur">{erreur}</p>}
      {resultat && (
        <div className="space-y-3 rounded-xl border-2 border-emerald-600 bg-emerald-50 p-4" data-testid="paiement-resultat">
          <p className="text-sm text-slate-700">{resultat.operateur} · {Number(resultat.montant).toLocaleString("fr-FR")} FCFA · {resultat.nom}</p>
          <p className="break-all text-center font-mono text-2xl font-bold text-emerald-900" data-testid="paiement-code">{resultat.code_ussd}</p>
          {/* Android : le lien ouvre le composeur avec le code pré-rempli. iPhone : copier puis coller dans le clavier d'appel. */}
          {!SUR_IOS && (
            <a href={resultat.lien_tel} className="flex items-center justify-center gap-2 rounded-lg bg-emerald-700 px-4 py-3 text-base font-semibold text-white" data-testid="paiement-composer">
              <Phone className="h-5 w-5" /> Composer
            </a>
          )}
          <button type="button" onClick={copier} className="flex w-full items-center justify-center gap-2 rounded-lg border border-emerald-700 px-4 py-3 text-base font-semibold text-emerald-800">
            {copie ? <Check className="h-5 w-5" /> : <Copy className="h-5 w-5" />} {copie ? "Code copié" : "Copier le code"}
          </button>
          {SUR_IOS && <p className="text-xs text-slate-600">Sur iPhone : copiez le code, ouvrez le clavier d'appel, collez-le puis appuyez sur appeler.</p>}
          <p className="flex items-start gap-1 text-xs text-slate-600"><ShieldCheck className="mt-0.5 h-4 w-4 flex-shrink-0" /> Vérifiez que le nom affiché est bien celui de la pharmacie. Votre code secret se saisit dans le menu de {resultat.operateur}, jamais ici.</p>
        </div>
      )}
    </div>
  );
}
