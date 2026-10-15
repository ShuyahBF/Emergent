// Lot 192 — Publier un carrousel WhatsApp sur une Page Facebook CHOISIE avant toute publication.
// La Page est choisie parmi celles du compte Facebook connecté ; chaque image de carte peut être remplacée (envoi d'un fichier
// ou image de la bibliothèque) avant de confirmer. API : /admin/carrousel/facebook/* (backend/routes/carrousel_facebook.py).
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { ExternalLink, Facebook, ImagePlus, Loader2, RotateCcw, X } from "lucide-react";
import { apiClient } from "@/lib/api";
import { Button } from "@/components/ui/button";

export default function FacebookCarrouselModal({ campagne, onClose }) {
  const cartes = campagne.cartes || [];
  const [pages, setPages] = useState([]);
  const [chargement, setChargement] = useState(true);
  const [erreur, setErreur] = useState("");
  const [pageId, setPageId] = useState("");                       // Page choisie (obligatoire avant de publier)
  const [mode, setMode] = useState("photos");                     // « photos » : images des cartes · « lien » : page de présentation
  const [message, setMessage] = useState(campagne.message || "");
  const [images, setImages] = useState(() => cartes.map(() => null));   // images de remplacement par carte (null = d'origine)
  const [bibliotheque, setBibliotheque] = useState(null);         // images déjà disponibles (chargées au premier besoin)
  const [carteChoix, setCarteChoix] = useState(null);             // carte pour laquelle la bibliothèque est ouverte
  const [envoiImage, setEnvoiImage] = useState(null);
  const [confirmer, setConfirmer] = useState(false);              // 2e clic : confirmation de la Page
  const [publication, setPublication] = useState(false);
  const [passees, setPassees] = useState([]);

  const chargerPassees = useCallback(async () => {
    try {
      const { data } = await apiClient.get(`/admin/carrousel/facebook/${campagne.id}/publications`);
      setPassees(data.publications || []);
    } catch { /* l'historique est facultatif */ }
  }, [campagne.id]);

  useEffect(() => {
    let vivant = true;
    (async () => {
      try {
        const { data } = await apiClient.get("/admin/carrousel/facebook/pages");
        if (vivant) setPages(data.pages || []);
      } catch (e) {
        if (vivant) setErreur(e?.response?.data?.detail || "Impossible de lire les Pages Facebook");
      } finally {
        if (vivant) setChargement(false);
      }
    })();
    chargerPassees();
    return () => { vivant = false; };
  }, [chargerPassees]);

  const pageChoisie = pages.find((p) => p.id === pageId);
  const poserImage = (i, url) => setImages((a) => a.map((x, k) => (k === i ? url : x)));

  async function ouvrirBibliotheque(i) {
    setCarteChoix(carteChoix === i ? null : i);
    if (bibliotheque) return;
    try {
      const { data } = await apiClient.get("/admin/whatsapp/carrousel/images");
      setBibliotheque((data.images || []).slice(0, 60));
    } catch { setBibliotheque([]); }
  }

  async function envoyerFichier(i, fichier) {
    if (!fichier) return;
    setEnvoiImage(i);
    try {
      const fd = new FormData();
      fd.append("fichier", fichier);
      const { data } = await apiClient.post("/admin/whatsapp/carrousel/images", fd);
      poserImage(i, data.url);
      toast.success("Image remplacée pour cette publication");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Envoi de l'image impossible");
    } finally { setEnvoiImage(null); }
  }

  async function publier() {
    setPublication(true);
    const attente = toast.loading("Patientez… publication sur Facebook");   // règle « Attentes et chargements »
    try {
      const { data } = await apiClient.post(`/admin/carrousel/facebook/${campagne.id}/publier`,
        { page_id: pageId, mode, message, images, lien: campagne.url_presentation || "" }, { timeout: 120000 });
      toast.success(`Publié sur « ${data.page_nom || pageChoisie?.nom} »`, { id: attente });
      setConfirmer(false);
      chargerPassees();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Publication impossible", { id: attente });
    } finally { setPublication(false); }
  }

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 p-4" onClick={onClose} data-testid="fb-carrousel-modal">
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
          <h3 className="inline-flex items-center gap-2 font-semibold text-slate-800"><Facebook className="h-4 w-4 text-blue-600" /> Publier ce carrousel sur Facebook</h3>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-700" aria-label="Fermer"><X className="h-5 w-5" /></button>
        </header>

        <div className="space-y-4 overflow-y-auto p-5 text-sm">
          {/* 1. Page : choisie AVANT toute publication */}
          <section>
            <label className="block text-xs font-semibold uppercase tracking-wide text-slate-600">1. Page Facebook</label>
            {chargement && <p className="mt-1 text-slate-500"><Loader2 className="mr-1 inline h-4 w-4 animate-spin" />Lecture des Pages…</p>}
            {erreur && <p className="mt-1 text-red-700" data-testid="fb-erreur">{erreur}</p>}
            {!chargement && !erreur && (
              <select value={pageId} onChange={(e) => { setPageId(e.target.value); setConfirmer(false); }}
                      className="mt-1 w-full rounded border border-slate-300 px-3 py-2" data-testid="fb-page">
                <option value="">— Choisissez la Page —</option>
                {pages.map((p) => <option key={p.id} value={p.id}>{p.nom}</option>)}
              </select>
            )}
            {!chargement && !erreur && pages.length === 0 && <p className="mt-1 text-amber-700">Aucune Page : connectez le compte Facebook (Paramètres → Facebook).</p>}
          </section>

          {/* 2. Mode et texte */}
          <section>
            <label className="block text-xs font-semibold uppercase tracking-wide text-slate-600">2. Contenu</label>
            <div className="mt-1 flex flex-wrap gap-4">
              <label className="inline-flex items-center gap-1"><input type="radio" name="fb-mode" checked={mode === "photos"} onChange={() => setMode("photos")} data-testid="fb-mode-photos" /> Photos des cartes + lien</label>
              <label className="inline-flex items-center gap-1"><input type="radio" name="fb-mode" checked={mode === "lien"} onChange={() => setMode("lien")} data-testid="fb-mode-lien" /> Lien de la page de présentation seulement</label>
            </div>
            <textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={3}
                      className="mt-2 w-full rounded border border-slate-300 px-3 py-2" placeholder="Texte de la publication" data-testid="fb-message" />
            {!campagne.url_presentation && <p className="text-xs text-amber-700">Cet envoi n'a pas de page de présentation : le lien ne sera pas ajouté.</p>}
          </section>

          {/* 3. Images : chaque carte peut être remplacée pour CETTE Page */}
          {mode === "photos" && (
            <section>
              <label className="block text-xs font-semibold uppercase tracking-wide text-slate-600">3. Images ({cartes.length} carte(s), 10 au plus)</label>
              <ul className="mt-1 space-y-2">
                {cartes.map((c, i) => {
                  const url = images[i] || c.image_url;
                  return (
                    <li key={i} className="rounded border border-slate-200 p-2" data-testid={`fb-carte-${i}`}>
                      <div className="flex items-center gap-3">
                        {url ? <img src={url} alt="" className="h-16 w-16 rounded object-cover" /> : <div className="h-16 w-16 rounded bg-slate-100" />}
                        <div className="min-w-0 flex-1">
                          <div className="truncate font-medium">{i + 1}. {c.titre || "Sans titre"}</div>
                          <div className="truncate text-xs text-slate-500">{images[i] ? "Image remplacée" : "Image d'origine"}</div>
                        </div>
                        <label className="inline-flex cursor-pointer items-center gap-1 rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50">
                          {envoiImage === i ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ImagePlus className="h-3.5 w-3.5" />} Remplacer
                          <input type="file" accept="image/jpeg,image/png" className="hidden" onChange={(e) => envoyerFichier(i, e.target.files?.[0])} />
                        </label>
                        <Button size="sm" variant="ghost" onClick={() => ouvrirBibliotheque(i)}>Bibliothèque</Button>
                        {images[i] && <Button size="sm" variant="ghost" title="Rétablir l'image d'origine" onClick={() => poserImage(i, null)}><RotateCcw className="h-3.5 w-3.5" /></Button>}
                      </div>
                      {carteChoix === i && (
                        <div className="mt-2 grid grid-cols-5 gap-2 sm:grid-cols-8">
                          {bibliotheque === null && <Loader2 className="h-4 w-4 animate-spin text-slate-400" />}
                          {(bibliotheque || []).map((b) => (
                            <button key={b.url} type="button" title={b.titre || b.origine} onClick={() => { poserImage(i, b.url); setCarteChoix(null); }}>
                              <img src={b.url} alt="" className="h-12 w-12 rounded object-cover ring-1 ring-slate-200 hover:ring-blue-500" />
                            </button>
                          ))}
                          {bibliotheque && bibliotheque.length === 0 && <span className="col-span-full text-xs text-slate-500">Aucune image disponible.</span>}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          )}

          {/* Publications déjà faites pour cet envoi */}
          {passees.length > 0 && (
            <section data-testid="fb-passees">
              <label className="block text-xs font-semibold uppercase tracking-wide text-slate-600">Déjà publié</label>
              <ul className="mt-1 space-y-1 text-xs text-slate-600">
                {passees.map((p) => (
                  <li key={p.id}>
                    {new Date(p.le).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })} · {p.page_nom} · {p.mode === "photos" ? `${p.nb_images} photo(s)` : "lien"}
                    {p.url && <> · <a href={p.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 text-blue-700 underline"><ExternalLink className="h-3 w-3" />voir</a></>}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>

        <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-slate-200 px-5 py-3">
          {confirmer && pageChoisie && (
            <span className="mr-auto rounded bg-amber-50 px-2 py-1 text-xs text-amber-900" data-testid="fb-confirmation">
              Publier sur la Page « <b>{pageChoisie.nom}</b> » ?
            </span>
          )}
          <Button variant="ghost" onClick={onClose}>Fermer</Button>
          {!confirmer ? (
            <Button disabled={!pageId || publication} onClick={() => setConfirmer(true)} data-testid="fb-publier">Publier…</Button>
          ) : (
            <>
              <Button variant="outline" onClick={() => setConfirmer(false)} disabled={publication}>Retour</Button>
              <Button disabled={publication} onClick={publier} data-testid="fb-confirmer">
                {publication ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Facebook className="mr-1 h-4 w-4" />} Confirmer la publication
              </Button>
            </>
          )}
        </footer>
      </div>
    </div>
  );
}
