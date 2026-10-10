// KitFacebookBloc.jsx — Lot 105 : kit de lancement de la Page Facebook beAuthentik.
// Demande du propriétaire (10/10/2026) : « construire la page Facebook pour beAuthentik, elle est vide ».
// Le bloc propose, dans l'ordre où on les utilise :
//   1. la photo de profil et la couverture à télécharger (Facebook ne permet de les poser qu'à la main) ;
//   2. les textes de la section « À propos » avec un bouton « Copier » par texte ;
//   3. « Charger les 8 publications » : elles entrent dans la file ci-dessous, à publier une par une.
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Check, Copy, Download, Loader2 } from "lucide-react";
import { apiClient } from "@/lib/api";

// Ligne « libellé + texte + bouton Copier » (le bouton passe au vert 2 s après la copie)
function TexteACopier({ libelle, texte, multiligne = false }) {
  const [copie, setCopie] = useState(false);
  const copier = async () => {
    try { await navigator.clipboard.writeText(texte); setCopie(true); setTimeout(() => setCopie(false), 2000); }
    catch { toast.error("Copie impossible : sélectionnez le texte à la main"); }
  };
  return (
    <div className="flex items-start gap-2 border-b border-slate-100 py-2 last:border-0">
      <div className="min-w-0 flex-1">
        <p className="text-[11px] font-medium text-slate-500">{libelle}</p>
        <p className={`text-xs text-slate-800 ${multiligne ? "whitespace-pre-line" : "truncate"}`}>{texte}</p>
      </div>
      <button type="button" onClick={copier} aria-label={`Copier : ${libelle}`}
              className={`inline-flex shrink-0 items-center gap-1 rounded border px-2 py-1 text-[11px] ${copie ? "border-emerald-300 bg-emerald-50 text-emerald-700" : "border-slate-300 text-slate-600"}`}>
        {copie ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />} {copie ? "Copié" : "Copier"}
      </button>
    </div>
  );
}

export default function KitFacebookBloc({ pagePropre, onCharge }) {
  const [kit, setKit] = useState(null);          // {a_propos, photo_profil, couverture, publications, charges, publies, total}
  const [ouvert, setOuvert] = useState(false);   // bloc replié par défaut une fois le kit entièrement publié
  const [occupe, setOccupe] = useState(false);

  const lire = async () => {
    try { const r = await apiClient.get("/admin/facebook/animation/kit"); setKit(r.data); setOuvert(r.data.publies < r.data.total); }
    catch { setKit(null); }
  };
  useEffect(() => { lire(); }, []);

  // Met les 8 publications dans la file de validation (toast « Patientez… » pendant l'appel)
  const charger = async () => {
    setOccupe(true);
    const attente = toast.loading("Patientez… chargement des publications de lancement");
    try {
      const r = await apiClient.post("/admin/facebook/animation/kit/charger");
      toast.success(r.data.crees ? `${r.data.crees} publication(s) ajoutée(s) à la file` : "Le kit est déjà dans la file", { id: attente });
      await lire(); await onCharge();
    } catch (err) { toast.error(err?.response?.data?.detail || "Chargement impossible", { id: attente }); }
    finally { setOccupe(false); }
  };

  if (!kit) return null;
  const a = kit.a_propos;
  return (
    <div className="overflow-hidden rounded-xl border border-rose-200" data-testid="kit-facebook">
      {/* En-tête aux couleurs de beAuthentik ; un clic replie / déplie le bloc */}
      <button type="button" onClick={() => setOuvert(!ouvert)}
              className="flex w-full items-center justify-between gap-3 bg-gradient-to-r from-[#f4256a] to-[#ff7a45] px-4 py-3 text-left text-white">
        <span>
          <span className="block text-sm font-semibold">Kit de lancement de la Page beAuthentik</span>
          <span className="block text-[11px] opacity-90">Visuels, textes « À propos » et {kit.total} publications — {kit.publies}/{kit.total} publiées</span>
        </span>
        <span className="text-xs">{ouvert ? "Replier" : "Ouvrir"}</span>
      </button>

      {ouvert && (
        <div className="space-y-4 bg-white p-4">
          {/* Étape 1 — visuels à poser à la main sur Facebook */}
          <section>
            <h5 className="text-xs font-semibold text-slate-800">1. Photo de profil et couverture</h5>
            <p className="mb-2 text-[11px] text-slate-500">Téléchargez-les puis, sur la Page : « Modifier la photo de profil » et « Modifier la photo de couverture ».</p>
            <div className="grid gap-3 sm:grid-cols-[120px_1fr]">
              <a href={kit.photo_profil} download="beauthentik-photo-profil.jpg" target="_blank" rel="noreferrer" className="group block">
                <img src={kit.photo_profil} alt="Photo de profil beAuthentik" className="aspect-square w-full rounded-full border border-slate-200 object-cover" />
                <span className="mt-1 flex items-center justify-center gap-1 text-[11px] text-slate-600 group-hover:text-[#f4256a]"><Download className="h-3 w-3" /> Profil 720 × 720</span>
              </a>
              <a href={kit.couverture} download="beauthentik-couverture.jpg" target="_blank" rel="noreferrer" className="group block">
                <img src={kit.couverture} alt="Couverture beAuthentik" className="aspect-[1640/624] w-full rounded-lg border border-slate-200 object-cover" />
                <span className="mt-1 flex items-center gap-1 text-[11px] text-slate-600 group-hover:text-[#f4256a]"><Download className="h-3 w-3" /> Couverture 1640 × 624</span>
              </a>
            </div>
          </section>

          {/* Étape 2 — textes de la section « À propos » */}
          <section>
            <h5 className="text-xs font-semibold text-slate-800">2. Section « À propos » et bouton d'action</h5>
            <p className="mb-1 text-[11px] text-slate-500">Sur la Page : « Modifier les informations » ; puis « Ajouter un bouton » → {a.bouton.libelle}.</p>
            <div className="rounded-lg border border-slate-200 px-3">
              <TexteACopier libelle="Catégorie" texte={a.categorie} />
              <TexteACopier libelle="Nom d'utilisateur (@)" texte={a.nom_utilisateur} />
              <TexteACopier libelle={`Présentation courte (${a.presentation.length}/101 caractères)`} texte={a.presentation} />
              <TexteACopier libelle="Description" texte={a.description} multiligne />
              <TexteACopier libelle="Site web" texte={a.site_web} />
              <TexteACopier libelle={`Bouton « ${a.bouton.libelle} » — lien`} texte={a.bouton.lien} />
            </div>
          </section>

          {/* Étape 3 — publications de lancement */}
          <section>
            <h5 className="text-xs font-semibold text-slate-800">3. Les {kit.total} publications de lancement</h5>
            <div className="my-2 flex gap-1.5 overflow-x-auto pb-1">
              {kit.publications.map((p) => (
                <img key={p.rang} src={p.image_url} alt={`Publication ${p.rang} : ${p.titre}`} title={`${p.rang}. ${p.titre}`}
                     className="aspect-[4/5] w-16 shrink-0 rounded border border-slate-200 object-cover" />
              ))}
            </div>
            {!pagePropre && (
              <p className="mb-2 rounded bg-amber-50 px-2 py-1 text-[11px] text-amber-800">
                Choisissez d'abord la Page beAuthentik dans « Page de publication » ci-dessus.
              </p>
            )}
            <button type="button" onClick={charger} disabled={occupe || !pagePropre || kit.charges >= kit.total}
                    className="inline-flex items-center gap-2 rounded-lg bg-[#f4256a] px-3.5 py-2 text-xs font-semibold text-white disabled:opacity-50">
              {occupe && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              {kit.charges >= kit.total ? "Kit chargé dans la file" : `Charger les ${kit.total} publications dans la file`}
            </button>
            <p className="mt-1 text-[11px] text-slate-500">
              Elles apparaissent dans « Publications » ci-dessous, à publier dans l'ordre : une ou deux par jour pour commencer.
            </p>
          </section>
        </div>
      )}
    </div>
  );
}
