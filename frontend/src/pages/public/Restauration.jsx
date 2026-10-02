/*
  Lot 49 — Page publique /restauration : restauration initiale d'un site NEUF (aucun compte),
  à partir d'un export complet (.sawali) fait sur l'ancien serveur.
  Le serveur n'accepte que si : la base n'a aucun compte ni donnée, la phrase est correcte, le
  fichier est intact et signé par un serveur ayant le même JWT_SECRET, et l'e-mail + mot de passe
  sont ceux d'un administrateur actif présent DANS la sauvegarde. Tout est contrôlé avant d'écrire.
  API : GET /public/restauration/etat, POST /public/restauration, GET /public/restauration/suivi/{id}.
*/
import React, { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, Loader2, ShieldCheck, Upload, XCircle } from "lucide-react";
import { apiClient } from "@/lib/api";
import PasswordInput from "@/components/PasswordInput";

const erreurDe = (e, d) => { const x = e?.response?.data?.detail; return Array.isArray(x) ? x.map((i) => i.msg).join(" ; ") : x || d; };
const champ = "mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm";

export default function Restauration() {
  const [etat, setEtat] = useState(null);
  const [fichier, setFichier] = useState(null);
  const [phrase, setPhrase] = useState("");
  const [email, setEmail] = useState("");
  const [motDePasse, setMotDePasse] = useState("");
  const [envoi, setEnvoi] = useState(false);
  const [suivi, setSuivi] = useState(null);
  const [erreur, setErreur] = useState("");
  const minuterie = useRef(null);

  useEffect(() => {
    apiClient.get("/public/restauration/etat").then((r) => setEtat(r.data)).catch(() => setEtat({ disponible: false, raison: "Serveur injoignable" }));
    return () => clearTimeout(minuterie.current);
  }, []);

  const suivre = (id, jeton) => {
    const tour = async () => {
      try {
        const r = await apiClient.get(`/public/restauration/suivi/${id}`, { params: { jeton } });
        setSuivi(r.data);
        if (r.data.statut === "EN_COURS") minuterie.current = setTimeout(tour, 2000);
      } catch {
        minuterie.current = setTimeout(tour, 4000);
      }
    };
    tour();
  };

  const envoyer = async (e) => {
    e.preventDefault();
    setErreur("");
    if (!fichier || !phrase || !email || !motDePasse) return setErreur("Tous les champs sont obligatoires");
    setEnvoi(true);
    try {
      const fd = new FormData();
      fd.append("fichier", fichier);
      fd.append("phrase", phrase);
      fd.append("email", email);
      fd.append("mot_de_passe", motDePasse);
      const r = await apiClient.post("/public/restauration", fd, { headers: { "Content-Type": "multipart/form-data" }, timeout: 0 });
      setPhrase(""); setMotDePasse("");
      suivre(r.data.id, r.data.jeton);
    } catch (err) {
      setErreur(erreurDe(err, "Restauration refusée"));
    } finally {
      setEnvoi(false);
    }
  };

  const p = suivi?.progression || {};
  return (
    <div className="min-h-screen bg-slate-50 px-4 py-10">
      <div className="mx-auto max-w-xl space-y-5 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm" data-testid="restauration-page">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-bold"><ShieldCheck className="h-5 w-5 text-indigo-600" /> Restauration initiale</h1>
          <p className="mt-1 text-sm text-slate-600">
            Pour un site neuf, sans aucun compte : importez l'export complet (<code>.sawali</code>) fait sur l'ancien serveur. Il faut sa
            phrase secrète et l'e-mail + mot de passe d'un <strong>administrateur</strong> présent dans la sauvegarde.
          </p>
        </div>

        {!etat && <p className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Vérification…</p>}
        {etat && !etat.disponible && !suivi && (
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700" data-testid="restauration-indisponible">
            Restauration initiale indisponible : {etat.raison || "le site contient déjà des données"}.
          </div>
        )}

        {etat?.disponible && !suivi && (
          <form onSubmit={envoyer} className="space-y-3">
            <label className="block text-xs font-medium text-slate-600">Fichier d'export complet (.sawali)
              <input type="file" accept=".sawali" onChange={(e) => setFichier(e.target.files?.[0] || null)} className="mt-1 block w-full text-sm" data-testid="restauration-fichier" />
            </label>
            <label className="block text-xs font-medium text-slate-600">Phrase secrète du fichier
              <PasswordInput value={phrase} onChange={(e) => setPhrase(e.target.value)} className={champ} autoComplete="off" testid="restauration-phrase" />
            </label>
            <label className="block text-xs font-medium text-slate-600">E-mail d'un administrateur de la sauvegarde
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className={champ} autoComplete="username" data-testid="restauration-email" />
            </label>
            <label className="block text-xs font-medium text-slate-600">Son mot de passe
              <PasswordInput value={motDePasse} onChange={(e) => setMotDePasse(e.target.value)} className={champ} testid="restauration-mot-de-passe" />
            </label>
            {erreur && <p className="rounded bg-red-50 p-2 text-sm text-red-700" data-testid="restauration-erreur">{erreur}</p>}
            <button type="submit" disabled={envoi} className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50" data-testid="restauration-lancer">
              {envoi ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />} {envoi ? "Envoi du fichier…" : "Restaurer"}
            </button>
          </form>
        )}

        {suivi && (
          <div className="space-y-2 rounded-lg border border-slate-200 p-3 text-sm" data-testid="restauration-suivi">
            <p className="flex items-center gap-2 font-semibold">
              {suivi.statut === "EN_COURS" && <Loader2 className="h-4 w-4 animate-spin" />}
              {suivi.statut === "TERMINE" && <CheckCircle2 className="h-4 w-4 text-emerald-600" />}
              {!["EN_COURS", "TERMINE"].includes(suivi.statut) && <XCircle className="h-4 w-4 text-red-600" />}
              {suivi.etape}
            </p>
            {suivi.statut === "EN_COURS" && p.documents_total > 0 && (
              <p className="text-xs text-slate-500">{p.collections_faites || 0} / {p.collections_total} collections · {p.documents || 0} / {p.documents_total} documents</p>
            )}
            {suivi.erreur && <p className="rounded bg-red-50 p-2 text-red-700">{suivi.erreur}</p>}
            {suivi.rapport && (
              <p className="text-xs text-slate-600">
                {suivi.rapport.collections} collections, {suivi.rapport.documents_en_base} / {suivi.rapport.documents_attendus} documents,
                {" "}{(suivi.rapport.anomalies || []).length} anomalie(s){(suivi.rapport.anomalies || []).length ? ` : ${suivi.rapport.anomalies.join(", ")}` : ""}.
              </p>
            )}
            {suivi.statut === "TERMINE" || suivi.statut === "TERMINE_AVEC_ANOMALIES" ? (
              <p className="text-sm">Restauration terminée. Redémarrez le service backend, puis <Link to="/login" className="text-indigo-700 underline">connectez-vous</Link> avec vos identifiants habituels.</p>
            ) : suivi.statut !== "EN_COURS" ? (
              <button type="button" onClick={() => { setSuivi(null); apiClient.get("/public/restauration/etat").then((r) => setEtat(r.data)).catch(() => {}); }} className="text-sm text-indigo-700 underline">Réessayer</button>
            ) : null}
            {(suivi.journal || []).length > 0 && (
              <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-2 text-[11px] text-slate-600">{suivi.journal.join("\n")}</pre>
            )}
          </div>
        )}
        <p className="text-center text-xs"><Link to="/login" className="text-indigo-700 underline">← Connexion</Link></p>
      </div>
    </div>
  );
}
