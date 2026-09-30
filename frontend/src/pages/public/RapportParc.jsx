/*
  Lot 47 — Page publique /rapport-parc/:jeton : rapport d'intervention sur le parc informatique,
  en lecture seule, à lire puis signer par le responsable du client (même parcours que la
  signature d'un PV : nom, signature tracée, date/heure ; le serveur ajoute l'adresse IP, le
  navigateur et l'empreinte SHA-256 du contenu lu). Après signature le rapport est verrouillé.
  Lien aléatoire, non indexé (balise robots + en-tête X-Robots-Tag), signable 30 jours.
  API : GET /public/parc-rapport/{jeton}, POST …/signer, GET …/pdf.
*/
import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { CheckCircle2, Clock, Download, Loader2, PenLine, Printer } from "lucide-react";
import { API, apiClient } from "@/lib/api";
import SignatureField from "@/components/SignatureField";

const dateHeure = (d) => (d ? new Date(d).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short", timeZone: "UTC" }) : "—");
const erreurDe = (e, d) => { const x = e?.response?.data?.detail; return Array.isArray(x) ? x.map((i) => i.msg).join(" ; ") : x || d; };

// Ligne « libellé : valeur » du tableau d'informations
const Ligne = ({ l, v }) => (
  <tr className="border-b border-slate-100 align-top">
    <td className="py-1.5 pr-3 font-semibold text-slate-600 w-40 print:w-32">{l}</td>
    <td className="py-1.5 whitespace-pre-line text-slate-800">{v || "—"}</td>
  </tr>
);

const Section = ({ titre, texte }) => (texte ? (
  <section className="space-y-1">
    <h3 className="text-sm font-semibold text-indigo-800">{titre}</h3>
    <p className="whitespace-pre-line text-sm text-slate-800">{texte}</p>
  </section>
) : null);

export default function RapportParc() {
  const { jeton } = useParams();
  const [r, setR] = useState(null);
  const [erreur, setErreur] = useState("");
  const [nom, setNom] = useState("");
  const [fonction, setFonction] = useState("");
  const [image, setImage] = useState(null);
  const [lu, setLu] = useState(false);
  const [occupe, setOccupe] = useState(false);

  // Page privée : jamais indexée par les moteurs de recherche
  useEffect(() => {
    const meta = document.createElement("meta");
    meta.name = "robots";
    meta.content = "noindex, nofollow, noarchive";
    document.head.appendChild(meta);
    return () => { document.head.removeChild(meta); };
  }, []);

  useEffect(() => {
    apiClient.get(`/public/parc-rapport/${jeton}`)
      .then((x) => { setR(x.data); setNom(x.data.responsable?.nom || ""); setFonction(x.data.responsable?.fonction || ""); })
      .catch((e) => setErreur(erreurDe(e, "Lien de rapport inconnu ou expiré")));
  }, [jeton]);

  const signer = async () => {
    setOccupe(true);
    try {
      // L'empreinte envoyée est celle du contenu affiché : le serveur refuse si le rapport a changé
      const x = await apiClient.post(`/public/parc-rapport/${jeton}/signer`, {
        nom: nom.trim(), fonction: fonction.trim() || null, image, empreinte: r.empreinte_sha256, accepte: lu });
      setR(x.data);
    } catch (e) { setErreur(erreurDe(e, "Signature impossible")); }
    finally { setOccupe(false); }
  };

  if (erreur && !r) return <div className="min-h-screen flex items-center justify-center p-6 text-slate-600">{erreur}</div>;
  if (!r) return <div className="min-h-screen flex items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-slate-400" /></div>;
  const sig = r.signature;
  return (
    <div className="min-h-screen bg-slate-100 px-3 py-6 print:bg-white print:p-0">
      <article className="mx-auto max-w-3xl space-y-5 rounded-xl bg-white p-5 shadow ring-1 ring-slate-200 sm:p-8 print:shadow-none print:ring-0" data-testid="rapport-parc">
        {/* En-tête : prestataire, numéro, état de la signature */}
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 pb-4">
          <div className="flex items-center gap-3">
            {r.prestataire?.logo_url && <img src={r.prestataire.logo_url} alt="" className="h-12 w-auto max-w-[140px] object-contain" />}
            <div>
              <p className="font-bold text-slate-800">{r.prestataire?.nom}</p>
              <p className="text-xs text-slate-500">{r.prestataire?.email} · {r.prestataire?.telephone}</p>
            </div>
          </div>
          <div className="text-right">
            <h1 className="text-lg font-bold text-indigo-900">Rapport d'intervention</h1>
            <p className="font-mono text-sm">{r.numero}</p>
            {sig ? (
              <span className="mt-1 inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-700"><CheckCircle2 className="h-3.5 w-3.5" /> Signé</span>
            ) : (
              <span className="mt-1 inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800"><Clock className="h-3.5 w-3.5" /> En attente de signature</span>
            )}
          </div>
        </header>

        <div className="flex flex-wrap gap-2 print:hidden">
          <button type="button" onClick={() => window.print()} className="inline-flex items-center gap-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"><Printer className="h-4 w-4" /> Imprimer</button>
          <a href={`${API}/public/parc-rapport/${jeton}/pdf`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"><Download className="h-4 w-4" /> PDF</a>
        </div>

        <div className="flex items-start gap-3">
          {r.client_logo_url && <img src={r.client_logo_url} alt="" className="h-10 w-auto max-w-[120px] object-contain" />}
          <table className="w-full text-sm">
            <tbody>
              <Ligne l="Client" v={r.client} />
              <Ligne l="Type" v={r.type_libelle} />
              <Ligne l="Début" v={dateHeure(r.debut)} />
              <Ligne l="Fin" v={r.fin ? dateHeure(r.fin) : r.statut} />
              {r.duree_minutes != null && <Ligne l="Durée" v={r.duree_minutes >= 60 ? `${Math.floor(r.duree_minutes / 60)} h ${String(r.duree_minutes % 60).padStart(2, "0")} min` : `${r.duree_minutes} min`} />}
              <Ligne l="Équipe" v={(r.equipe || []).join(", ")} />
              <Ligne l="Responsable" v={[r.responsable?.nom, r.responsable?.fonction].filter(Boolean).join(" — ")} />
            </tbody>
          </table>
        </div>

        <section className="space-y-1">
          <h3 className="text-sm font-semibold text-indigo-800">Équipements concernés</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-left text-slate-500">
                <tr><th className="p-1.5">Inventaire</th><th className="p-1.5">Équipement</th><th className="p-1.5">N° de série</th><th className="p-1.5">MAC</th><th className="p-1.5">IP</th></tr>
              </thead>
              <tbody>
                {(r.equipements || []).map((e) => (
                  <tr key={e.numero_inventaire} className="border-t border-slate-100 align-top">
                    <td className="p-1.5 font-mono">{e.numero_inventaire}</td>
                    <td className="p-1.5">{[e.categorie, e.fabricant, e.modele].filter(Boolean).join(" ")}{e.lieu && <span className="block text-slate-500">{e.lieu}</span>}</td>
                    <td className="p-1.5 font-mono">{e.numero_serie || "—"}</td>
                    <td className="p-1.5 font-mono">{e.adresse_mac || "—"}</td>
                    <td className="p-1.5 font-mono">{e.adresse_ip || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <Section titre="Problème constaté" texte={r.probleme} />
        <Section titre="Actions réalisées" texte={r.actions} />
        {(r.pieces || []).length > 0 && (
          <section className="space-y-1">
            <h3 className="text-sm font-semibold text-indigo-800">Pièces remplacées</h3>
            <ul className="list-disc pl-5 text-sm">
              {r.pieces.map((p, i) => <li key={i}>{p.quantite} × {p.designation}{p.reference ? ` (réf. ${p.reference})` : ""}</li>)}
            </ul>
          </section>
        )}
        <Section titre="Résultat" texte={r.resultat} />
        <Section titre="Recommandations" texte={r.recommandations} />
        {r.etat_apres_libelle && <p className="text-sm">État des équipements après intervention : <b>{r.etat_apres_libelle}</b></p>}

        {(r.photos || []).length > 0 && (
          <section className="space-y-1">
            <h3 className="text-sm font-semibold text-indigo-800">Photos</h3>
            <div className="flex flex-wrap gap-2">
              {r.photos.map((p) => <a key={p.url} href={p.url} target="_blank" rel="noreferrer"><img src={p.url} alt={p.nom || ""} className="h-28 w-28 rounded object-cover ring-1 ring-slate-200" /></a>)}
            </div>
          </section>
        )}

        <p className="break-all text-[10px] text-slate-400">Empreinte SHA-256 du contenu : {r.empreinte_sha256}</p>

        {/* Signature : preuve affichée si signé, sinon formulaire (tant que le lien est valable) */}
        {sig ? (
          <section className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-emerald-400 bg-emerald-50 p-4 text-sm text-emerald-900" data-testid="rapport-signe">
            <div>
              <p className="font-semibold">✓ Rapport signé électroniquement</p>
              <p>par <b>{sig.nom}</b>{sig.fonction ? ` (${sig.fonction})` : ""}</p>
              <p>le <b>{dateHeure(sig.signe_le)} (UTC)</b> — adresse IP {sig.ip || "—"}</p>
              <p className="break-all text-[10px] text-slate-500">Empreinte signée : {sig.empreinte}</p>
              <p className="text-[10px] text-slate-500">Document verrouillé après signature.</p>
            </div>
            {sig.image && <img src={sig.image} alt="Signature" className="h-20 w-auto rounded bg-white ring-1 ring-emerald-200" />}
          </section>
        ) : r.signable ? (
          <section className="space-y-3 rounded-lg border border-indigo-200 bg-indigo-50/50 p-4 print:hidden" data-testid="rapport-signer">
            <p className="flex items-center gap-1.5 font-semibold text-indigo-900"><PenLine className="h-4 w-4" /> Signature du responsable</p>
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="text-xs text-slate-600">Nom et prénom *
                <input className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm" value={nom} maxLength={120} onChange={(e) => setNom(e.target.value)} />
              </label>
              <label className="text-xs text-slate-600">Fonction
                <input className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm" value={fonction} maxLength={120} onChange={(e) => setFonction(e.target.value)} />
              </label>
            </div>
            <SignatureField value={image} onChange={setImage} />
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-1" checked={lu} onChange={(e) => setLu(e.target.checked)} data-testid="rapport-lu" />
              J'ai lu le rapport ci-dessus et je confirme l'intervention décrite.
            </label>
            {erreur && <p className="rounded bg-rose-50 p-2 text-sm text-rose-700">{erreur}</p>}
            <button type="button" onClick={signer} disabled={occupe || !lu || !image || nom.trim().length < 2}
              className="inline-flex items-center gap-1 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50" data-testid="rapport-signer-btn">
              {occupe && <Loader2 className="h-4 w-4 animate-spin" />} Signer le rapport
            </button>
            <p className="text-[11px] text-slate-500">Votre nom, votre signature, la date et l'heure, votre adresse IP et votre navigateur sont enregistrés avec l'empreinte du rapport. Après signature, le rapport ne peut plus être modifié.</p>
          </section>
        ) : (
          <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">Ce lien de signature a expiré. Demandez un nouveau lien à votre prestataire.</p>
        )}
        {/* Emplacement de la signature sur la version imprimée d'un rapport non signé */}
        {!sig && <p className="hidden pt-10 text-xs text-slate-500 print:block">Signature du responsable :</p>}
      </article>
    </div>
  );
}
