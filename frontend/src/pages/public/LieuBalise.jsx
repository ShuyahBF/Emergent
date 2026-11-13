// pages/public/LieuBalise.jsx — Lot 388 : page PUBLIQUE d'un lieu (« Vous êtes ici »). Ouverte par le QR code collé près de la balise,
// ou par l'application « Où suis-je ? » (?src=app). Aucun compte : le visiteur voit le nom du lieu, le texte et les liens écrits par le superviseur,
// et peut passer à un autre lieu. L'ouverture est comptée UNE fois par session (qr ou app).
import React, { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Loader2, MapPin } from "lucide-react";
import { apiClient } from "@/lib/api";

export default function LieuBalise() {
  const { code } = useParams();
  const [params] = useSearchParams();
  const [lieu, setLieu] = useState(null);
  const [erreur, setErreur] = useState("");

  useEffect(() => {
    setLieu(null); setErreur("");
    apiClient.get(`/lieux-balises/${code}`).then(({ data }) => {
      setLieu(data);
      // Compte la visite une seule fois par session et par lieu (jamais d'erreur visible)
      let deja = false;
      try { deja = sessionStorage.getItem(`lieu-vu-${code}`) === "1"; sessionStorage.setItem(`lieu-vu-${code}`, "1"); } catch { /* stockage indisponible */ }
      if (!deja) apiClient.post(`/lieux-balises/${code}/visite`, { source: params.get("src") === "app" ? "app" : "qr" }).catch(() => {});
    }).catch(() => setErreur("Ce lieu n'existe plus. Scannez à nouveau le QR code affiché sur place."));
  }, [code, params]);

  if (erreur) return <div className="mx-auto max-w-md p-6 text-center text-slate-700">{erreur}</div>;
  if (!lieu) return <div className="flex justify-center p-10"><Loader2 className="h-6 w-6 animate-spin" aria-label="Chargement" /></div>;

  return (
    <main className="mx-auto max-w-md space-y-5 p-5" data-testid="page-lieu">
      <header className="space-y-1">
        <div className="flex items-center gap-2 text-sm font-medium text-sky-700"><MapPin className="h-4 w-4" /> Vous êtes ici</div>
        <h1 className="text-2xl font-bold">{lieu.nom}</h1>
      </header>
      {lieu.texte && <p className="whitespace-pre-line text-slate-800">{lieu.texte}</p>}
      {lieu.liens.length > 0 && (
        <ul className="space-y-2">
          {lieu.liens.map((l) => (
            <li key={l.url}><a className="block rounded-lg border border-slate-200 px-4 py-3 font-medium text-sky-800 hover:bg-sky-50" href={l.url} target="_blank" rel="noopener noreferrer">{l.libelle}</a></li>
          ))}
        </ul>
      )}
      {lieu.autres.length > 0 && (
        <section className="space-y-2 border-t border-slate-200 pt-4">
          <h2 className="text-sm font-semibold text-slate-600">Autres lieux</h2>
          <ul className="flex flex-wrap gap-2">
            {lieu.autres.map((a) => <li key={a.code}><Link className="rounded-full border border-slate-300 px-3 py-1 text-sm" to={`/lieu/${a.code}`}>{a.nom}</Link></li>)}
          </ul>
        </section>
      )}
    </main>
  );
}
