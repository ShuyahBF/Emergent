/*
  Lot 268 — Page publique « Vérifier un document » (ouverte en scannant le QR code d'une page du document).
  Le QR contient un lien chiffré (?t=…) : le serveur SAWALI le déchiffre et cette page affiche le contenu EN CLAIR
  (titre, version, copyright, exemplaire, page) avec « Document authentique », ou « non reconnu » si le jeton est faux
  ou modifié. Aucune connexion requise. Pensée pour l'écran d'un téléphone.
*/
import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { BadgeCheck, ShieldAlert, Loader2 } from "lucide-react";
import { apiClient } from "@/lib/api";

export default function VerifierDocument() {
  const [params] = useSearchParams();
  const jeton = params.get("t") || "";
  const [res, setRes] = useState(null);       // null = en cours ; objet = réponse du serveur
  const [erreur, setErreur] = useState(false);

  // Demande le déchiffrement au serveur (une seule fois par jeton)
  useEffect(() => {
    document.title = "Vérification d'un document — SAWALI";
    if (!jeton) { setRes({ authentique: false }); return; }
    apiClient.get("/public/verifier-document", { params: { t: jeton } })
      .then((r) => setRes(r.data))
      .catch(() => setErreur(true));
  }, [jeton]);

  return (
    <main className="mx-auto max-w-lg px-4 py-10" data-testid="verifier-document">
      <h1 className="font-display text-2xl font-bold mb-1">Vérification d'un document</h1>
      <p className="text-sm text-slate-500 mb-6">Contrôle d'authenticité par SAWALI SMART SYSTEMS</p>

      {!res && !erreur && (
        <p className="flex items-center gap-2 text-slate-600"><Loader2 className="h-4 w-4 animate-spin" /> Vérification en cours…</p>
      )}
      {erreur && (
        <p className="rounded-lg bg-amber-50 text-amber-800 p-4 text-sm">Le serveur ne répond pas pour le moment. Réessayez dans un instant.</p>
      )}

      {res && res.authentique && (
        <section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5" data-testid="verif-authentique">
          <p className="flex items-center gap-2 text-emerald-800 font-semibold text-lg">
            <BadgeCheck className="h-6 w-6" /> Document authentique
          </p>
          <dl className="mt-4 space-y-3 text-sm">
            <div><dt className="text-slate-500">Titre</dt><dd className="font-semibold">{res.titre}</dd></div>
            <div><dt className="text-slate-500">Version</dt><dd className="font-semibold">{res.version}</dd></div>
            <div><dt className="text-slate-500">Droits d'auteur</dt><dd className="font-semibold">{res.droits}</dd></div>
            {res.exemplaire && <div><dt className="text-slate-500">Exemplaire</dt><dd className="font-semibold">{res.exemplaire}</dd></div>}
            {res.page && <div><dt className="text-slate-500">Page</dt><dd className="font-semibold">{res.page}</dd></div>}
          </dl>
          <div className="mt-4 rounded-lg bg-white/70 p-3">
            <p className="text-xs text-slate-500 mb-1">Texte déchiffré</p>
            <code className="break-all text-xs" data-testid="verif-texte-clair">{res.texte_clair}</code>
          </div>
        </section>
      )}

      {res && !res.authentique && (
        <section className="rounded-2xl border border-red-200 bg-red-50 p-5" data-testid="verif-refuse">
          <p className="flex items-center gap-2 text-red-800 font-semibold text-lg"><ShieldAlert className="h-6 w-6" /> Document non reconnu</p>
          <p className="mt-2 text-sm text-red-900">Ce code n'a pas pu être vérifié : il est invalide, modifié, ou n'a pas été émis par SAWALI. Ne vous fiez pas à ce document.</p>
        </section>
      )}
    </main>
  );
}
