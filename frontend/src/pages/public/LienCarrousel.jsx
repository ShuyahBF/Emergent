/**
 * Lot 117 — page du site ouverte par le bouton d'une carte de carrousel WhatsApp : <site>/l/<code>.
 *
 * Pourquoi : Meta refusait tous les modèles de carrousel pour « format non conforme » (12/10/2026). L'adresse du
 * bouton pointait vers /api/public/carrousel/l/{{1}}, qui REDIRIGEAIT (302) vers une autre page ; Meta vérifie
 * l'adresse d'exemple du bouton et attend une vraie page. Désormais le bouton ouvre CETTE page du site :
 *   - elle demande au serveur l'adresse finale de la carte (le clic est compté et, pour un carrousel sponsorisé,
 *     facturé à la régie) puis y emmène le visiteur ;
 *   - sans code, ou avec le code d'exemple « exemple » envoyé à Meta, elle affiche une page SAWALI normale.
 */
import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { apiClient } from "@/lib/api";

export default function LienCarrousel() {
  const { code } = useParams();
  const [etat, setEtat] = useState(code && code !== "exemple" ? "ouverture" : "accueil");

  // Code réel : on demande l'adresse finale (clic compté côté serveur) puis on y va sans garder cette page dans l'historique
  useEffect(() => {
    if (!code || code === "exemple") return;
    apiClient.get(`/public/carrousel/destination/${encodeURIComponent(code)}`)
      .then((r) => {
        const url = r.data?.url;
        if (url) window.location.replace(url);
        else setEtat("accueil");
      })
      .catch(() => setEtat("accueil"));
  }, [code]);

  // Pendant la recherche de l'adresse : jauge circulaire (règle « Patientez… »)
  if (etat === "ouverture") {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 text-slate-600">
        <Loader2 className="h-10 w-10 animate-spin text-sky-500" aria-hidden="true" />
        <p>Patientez… ouverture de la présentation</p>
      </div>
    );
  }

  // Page d'accueil du lien (sans code, code d'exemple ou lien expiré)
  return (
    <div className="mx-auto max-w-xl px-4 py-16 text-center">
      <h1 className="text-2xl font-bold text-slate-900">SAWALI</h1>
      <p className="mt-3 text-slate-600">
        Formulaires, sondages et messages WhatsApp pour les entreprises. Cette page ouvre les présentations
        envoyées dans nos carrousels WhatsApp.
      </p>
      <Link to="/" className="mt-6 inline-block rounded-lg bg-sky-600 px-5 py-2.5 font-semibold text-white hover:bg-sky-700">
        Découvrir SAWALI
      </Link>
    </div>
  );
}
