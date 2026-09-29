/*
  Lot 36 — Réponses d'un formulaire Liluvine (« !formulaire »), ouvertes par le lien
  crypté PRIVÉ envoyé au demandeur sur WhatsApp : /fr-resultats/{jeton}.
  Tableau des réponses + téléchargement Excel (CSV). Sans compte ; le lien expire
  avec le formulaire (30 jours). API : GET /public/forms/resultats/{jeton}[/export.csv].
*/
import React, { useEffect, useState } from "react";
import axios from "axios";
import { useParams } from "react-router-dom";
import { Download, Loader2 } from "lucide-react";
import { LOGO_URL } from "@/lib/brand";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Valeur d'une réponse en texte lisible (Oui/Non, lignes de tableau, signature…)
function lisible(v) {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "Oui" : "Non";
  if (Array.isArray(v)) {
    return v.map((e) => (e && typeof e === "object" ? Object.values(e).filter((x) => x !== "").join(" · ") : String(e))).join(" | ");
  }
  if (typeof v === "string" && v.startsWith("data:image")) return "[signature]";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export default function PublicFormResults() {
  const { jeton } = useParams();
  const [res, setRes] = useState(null);
  const [erreur, setErreur] = useState(null);

  useEffect(() => {
    axios.get(`${API}/public/forms/resultats/${jeton}`)
      .then((r) => setRes(r.data))
      .catch((e) => setErreur(e?.response?.data?.detail || "Lien invalide ou expiré"));
  }, [jeton]);

  if (erreur) {
    return (
      <div className="min-h-screen bg-[#0E1F3D] text-white flex items-center justify-center p-6">
        <div className="max-w-md text-center">
          <img src={LOGO_URL} alt="SAWALI" className="h-12 w-12 mx-auto mb-4 rounded-lg ring-1 ring-white/20" />
          <h1 className="text-lg font-display font-bold mb-2">Réponses non accessibles</h1>
          <p className="text-sm text-slate-300">{erreur}</p>
        </div>
      </div>
    );
  }
  if (!res) {
    return <div className="min-h-screen bg-[#0E1F3D] text-white flex items-center justify-center text-sm"><Loader2 className="h-4 w-4 animate-spin mr-2" /> Chargement…</div>;
  }
  const expire = res.expire_le ? new Date(res.expire_le).toLocaleDateString("fr-FR") : null;
  return (
    <div className="min-h-screen bg-slate-50" data-testid="public-form-results">
      <header className="bg-[#0E1F3D] text-white">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center gap-3">
          <img src={LOGO_URL} alt="SAWALI" className="h-9 w-9 rounded-md ring-1 ring-white/20" />
          <div className="flex-1 min-w-0">
            <p className="text-[10px] uppercase tracking-[0.3em] text-sawali-blue-light">Réponses du formulaire</p>
            <h1 className="text-base font-display font-bold truncate">{res.title}</h1>
          </div>
          <a href={`${API}/public/forms/resultats/${jeton}/export.csv`} data-testid="public-results-csv"
            className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 px-3 py-2 text-xs font-semibold">
            <Download className="h-3.5 w-3.5" /> Excel (CSV)
          </a>
        </div>
      </header>
      <main className="max-w-6xl mx-auto px-6 py-6 space-y-3">
        <p className="text-sm text-slate-600">
          <b>{res.reponses.length}</b> réponse(s). Lien privé : ne le partagez pas.{expire && ` Valable jusqu'au ${expire}.`}
        </p>
        <div className="rounded-xl bg-white ring-1 ring-slate-200 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-[11px] uppercase tracking-wider text-slate-500">
              <tr>
                <th className="text-left px-3 py-2 whitespace-nowrap">Date</th>
                <th className="text-left px-3 py-2 whitespace-nowrap">Répondant</th>
                {res.champs.map((c) => <th key={c.id} className="text-left px-3 py-2 min-w-[10rem]">{c.label}</th>)}
              </tr>
            </thead>
            <tbody>
              {res.reponses.length === 0 && (
                <tr><td colSpan={res.champs.length + 2} className="px-3 py-6 text-center text-slate-400 italic">Aucune réponse pour le moment.</td></tr>
              )}
              {res.reponses.map((r, i) => (
                <tr key={i} className="border-t border-slate-100 align-top">
                  <td className="px-3 py-2 whitespace-nowrap text-slate-500">{new Date(r.created_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{r.user_label}</td>
                  {res.champs.map((c) => <td key={c.id} className="px-3 py-2 text-slate-800">{lisible((r.data || {})[c.id])}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </main>
    </div>
  );
}
