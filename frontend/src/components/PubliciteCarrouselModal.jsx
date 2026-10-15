// Lot 193 — Créer une PUBLICITÉ À CARROUSEL « Click-to-WhatsApp » (compte publicitaire Meta) à partir d'un envoi de carrousels.
// Tout est créé EN PAUSE : aucune dépense tant que l'administrateur n'a pas cliqué « Activer » puis confirmé.
// API : /admin/carrousel/publicite/config et /admin/carrousel/{id}/publicite (backend/routes/carrousel_publicite.py).
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { ExternalLink, ImagePlus, Loader2, Megaphone, RotateCcw, X } from "lucide-react";
import { apiClient } from "@/lib/api";
import { Button } from "@/components/ui/button";

const detail = (e, defaut) => e?.response?.data?.detail || defaut;

export default function PubliciteCarrouselModal({ campagne, onClose }) {
  const cartes = campagne.cartes || [];
  const [config, setConfig] = useState({ comptes: [], pages: [] });
  const [chargement, setChargement] = useState(true);
  const [erreur, setErreur] = useState("");
  const [form, setForm] = useState({
    compte_id: "", page_id: "", nom: "", budget: "", jours: "7", pays: "BF", age_min: "18", age_max: "65", whatsapp: "",
    message: campagne.message || "",
  });
  const [images, setImages] = useState(() => cartes.map(() => null));      // images de remplacement par carte
  const [bibliotheque, setBibliotheque] = useState(null);
  const [carteChoix, setCarteChoix] = useState(null);
  const [envoiImage, setEnvoiImage] = useState(null);
  const [confirmer, setConfirmer] = useState(false);
  const [creation, setCreation] = useState(false);
  const [publicites, setPublicites] = useState([]);
  const [statutEn, setStatutEn] = useState(null);                           // campagne en cours d'activation / pause
  const [aActiver, setAActiver] = useState(null);                           // campagne dont l'activation attend sa confirmation

  const maj = (champ) => (e) => { setForm((f) => ({ ...f, [champ]: e.target.value })); setConfirmer(false); };
  const compte = config.comptes.find((c) => c.id === form.compte_id);

  const chargerPublicites = useCallback(async () => {
    try {
      const { data } = await apiClient.get(`/admin/carrousel/${campagne.id}/publicite`);
      setPublicites(data.publicites || []);
    } catch { /* l'historique est facultatif */ }
  }, [campagne.id]);

  useEffect(() => {
    let vivant = true;
    (async () => {
      try {
        const { data } = await apiClient.get("/admin/carrousel/publicite/config");
        if (!vivant) return;
        setConfig(data);
        setForm((f) => ({ ...f, compte_id: data.comptes?.length === 1 ? data.comptes[0].id : f.compte_id,
                          page_id: data.pages?.length === 1 ? data.pages[0].id : f.page_id }));
      } catch (e) {
        if (vivant) setErreur(detail(e, "Impossible de lire le compte publicitaire Meta"));
      } finally { if (vivant) setChargement(false); }
    })();
    chargerPublicites();
    return () => { vivant = false; };
  }, [chargerPublicites]);

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
      toast.success("Image remplacée pour cette publicité");
    } catch (e) { toast.error(detail(e, "Envoi de l'image impossible")); } finally { setEnvoiImage(null); }
  }

  const pret = form.compte_id && form.page_id && Number(form.budget) > 0 && form.pays.trim();

  async function creer() {
    setCreation(true);
    const attente = toast.loading("Patientez… création de la publicité chez Meta");     // règle « Attentes et chargements »
    try {
      await apiClient.post(`/admin/carrousel/${campagne.id}/publicite`, { ...form, images }, { timeout: 180000 });
      toast.success("Publicité créée EN PAUSE : vérifiez-la, puis activez-la", { id: attente });
      setConfirmer(false);
      chargerPublicites();
    } catch (e) { toast.error(detail(e, "Création impossible"), { id: attente }); } finally { setCreation(false); }
  }

  async function changerStatut(p, statut) {
    setStatutEn(p.campagne_meta);
    const attente = toast.loading("Patientez… mise à jour chez Meta");
    try {
      await apiClient.post(`/admin/carrousel/${campagne.id}/publicite/statut`, { campagne_meta: p.campagne_meta, statut }, { timeout: 120000 });
      toast.success(statut === "ACTIVE" ? "Publicité ACTIVE : la dépense a commencé" : "Publicité en pause", { id: attente });
      setAActiver(null);
      chargerPublicites();
    } catch (e) { toast.error(detail(e, "Changement de statut impossible"), { id: attente }); } finally { setStatutEn(null); }
  }

  const champ = "mt-1 w-full rounded border border-slate-300 px-3 py-2";
  const etiquette = "block text-xs font-semibold uppercase tracking-wide text-slate-600";
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 p-4" onClick={onClose} data-testid="pub-carrousel-modal">
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
          <h3 className="inline-flex items-center gap-2 font-semibold text-slate-800"><Megaphone className="h-4 w-4 text-fuchsia-600" /> Publicité à carrousel (Click-to-WhatsApp)</h3>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-700" aria-label="Fermer"><X className="h-5 w-5" /></button>
        </header>

        <div className="space-y-4 overflow-y-auto p-5 text-sm">
          <p className="rounded bg-sky-50 px-3 py-2 text-xs text-sky-900">
            Chaque carte devient une carte de la publicité ; le bouton ouvre WhatsApp. La publicité est créée <b>en pause</b> : rien n'est dépensé tant que vous ne l'activez pas.
            Les personnes qui cliquent arrivent sur WhatsApp, où Liluvine leur répond.
          </p>
          {chargement && <p className="text-slate-500"><Loader2 className="mr-1 inline h-4 w-4 animate-spin" />Lecture du compte publicitaire…</p>}
          {erreur && <p className="text-red-700" data-testid="pub-erreur">{erreur}</p>}

          {!chargement && !erreur && (<>
            <section className="grid gap-3 sm:grid-cols-2">
              <label className={etiquette}>Compte publicitaire
                <select value={form.compte_id} onChange={maj("compte_id")} className={champ} data-testid="pub-compte">
                  <option value="">— Choisissez —</option>
                  {config.comptes.map((c) => <option key={c.id} value={c.id}>{c.nom || c.id} ({c.devise || "?"})</option>)}
                </select>
              </label>
              <label className={etiquette}>Page Facebook
                <select value={form.page_id} onChange={maj("page_id")} className={champ} data-testid="pub-page">
                  <option value="">— Choisissez —</option>
                  {config.pages.map((p) => <option key={p.id} value={p.id}>{p.nom}</option>)}
                </select>
              </label>
              <label className={etiquette}>Nom de la campagne
                <input value={form.nom} onChange={maj("nom")} className={champ} placeholder="Carrousel octobre" maxLength={120} data-testid="pub-nom" />
              </label>
              <label className={etiquette}>Budget par jour {compte?.devise ? `(${compte.devise})` : ""}
                <input value={form.budget} onChange={maj("budget")} className={champ} inputMode="decimal" placeholder="5000" data-testid="pub-budget" />
              </label>
              <label className={etiquette}>Durée en jours (0 = sans fin)
                <input value={form.jours} onChange={maj("jours")} className={champ} inputMode="numeric" data-testid="pub-jours" />
              </label>
              <label className={etiquette}>Pays (codes séparés par des virgules)
                <input value={form.pays} onChange={maj("pays")} className={champ} placeholder="BF, CI" data-testid="pub-pays" />
              </label>
              <label className={etiquette}>Âge minimum
                <input value={form.age_min} onChange={maj("age_min")} className={champ} inputMode="numeric" />
              </label>
              <label className={etiquette}>Âge maximum
                <input value={form.age_max} onChange={maj("age_max")} className={champ} inputMode="numeric" />
              </label>
              <label className={`${etiquette} sm:col-span-2`}>Numéro WhatsApp (vide = celui lié à la Page)
                <input value={form.whatsapp} onChange={maj("whatsapp")} className={champ} placeholder="+226XXXXXXXX" data-testid="pub-whatsapp" />
              </label>
              <label className={`${etiquette} sm:col-span-2`}>Texte de la publicité
                <textarea value={form.message} onChange={maj("message")} rows={3} className={champ} data-testid="pub-message" />
              </label>
            </section>

            <section>
              <label className={etiquette}>Images des cartes ({cartes.length}, 2 à 10 avec une image publique)</label>
              <ul className="mt-1 space-y-2">
                {cartes.map((c, i) => {
                  const url = images[i] || c.image_url;
                  return (
                    <li key={i} className="rounded border border-slate-200 p-2">
                      <div className="flex items-center gap-3">
                        {url ? <img src={url} alt="" className="h-14 w-14 rounded object-cover" /> : <div className="h-14 w-14 rounded bg-slate-100" />}
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
                              <img src={b.url} alt="" className="h-12 w-12 rounded object-cover ring-1 ring-slate-200 hover:ring-fuchsia-500" />
                            </button>
                          ))}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          </>)}

          {/* Publicités déjà créées depuis cet envoi : activer / mettre en pause (avec confirmation) */}
          {publicites.length > 0 && (
            <section data-testid="pub-creees">
              <label className={etiquette}>Publicités créées depuis cet envoi</label>
              <ul className="mt-1 space-y-2">
                {publicites.map((p) => (
                  <li key={p.id} className="rounded border border-slate-200 p-2 text-xs">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`rounded-full px-2 py-0.5 ${p.statut === "ACTIVE" ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"}`}>
                        {p.statut === "ACTIVE" ? "ACTIVE" : "En pause"}
                      </span>
                      <span>{new Date(p.le).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })} · {p.compte_nom} · {p.page_nom} · {p.nb_cartes} cartes · {p.budget_jour} {p.devise}/jour · {(p.pays || []).join(", ")}</span>
                      <a href={p.gestionnaire} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 text-blue-700 underline"><ExternalLink className="h-3 w-3" />Gestionnaire de publicités</a>
                      <span className="ml-auto flex items-center gap-2">
                        {p.statut === "ACTIVE" ? (
                          <Button size="sm" variant="outline" disabled={statutEn === p.campagne_meta} onClick={() => changerStatut(p, "PAUSED")}>Mettre en pause</Button>
                        ) : aActiver === p.campagne_meta ? (
                          <>
                            <span className="rounded bg-amber-50 px-2 py-1 text-amber-900">Activer commence la dépense ({p.budget_jour} {p.devise}/jour). Confirmer ?</span>
                            <Button size="sm" variant="outline" onClick={() => setAActiver(null)}>Non</Button>
                            <Button size="sm" disabled={statutEn === p.campagne_meta} onClick={() => changerStatut(p, "ACTIVE")} data-testid="pub-confirmer-activation">Oui, activer</Button>
                          </>
                        ) : (
                          <Button size="sm" onClick={() => setAActiver(p.campagne_meta)} data-testid="pub-activer">Activer…</Button>
                        )}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>

        <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-slate-200 px-5 py-3">
          {confirmer && (
            <span className="mr-auto rounded bg-amber-50 px-2 py-1 text-xs text-amber-900" data-testid="pub-confirmation">
              Créer la publicité EN PAUSE sur « <b>{compte?.nom || form.compte_id}</b> » ({form.budget} {compte?.devise}/jour, {form.pays}) ?
            </span>
          )}
          <Button variant="ghost" onClick={onClose}>Fermer</Button>
          {!confirmer ? (
            <Button disabled={!pret || creation || !!erreur} onClick={() => setConfirmer(true)} data-testid="pub-creer">Créer la publicité…</Button>
          ) : (
            <>
              <Button variant="outline" onClick={() => setConfirmer(false)} disabled={creation}>Retour</Button>
              <Button disabled={creation} onClick={creer} data-testid="pub-confirmer">
                {creation ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Megaphone className="mr-1 h-4 w-4" />} Confirmer la création
              </Button>
            </>
          )}
        </footer>
      </div>
    </div>
  );
}
