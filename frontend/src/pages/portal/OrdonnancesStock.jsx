/*
  Lot 39 — Portail → « Ordonnances et stock ».
  Le pharmacien photographie une ordonnance : l'IA lit les médicaments prescrits (jamais
  l'identité du patient), le serveur les rapproche du stock de SON client (code client,
  un ou plusieurs dépôts : PHL → PPH et PLB) et affiche pour chaque ligne la
  disponibilité (salle, magasin, réservé), l'alerte de péremption, les équivalents
  VIDAL présents en stock, puis réserve les quantités jusqu'à la vente.
  API : /stock-produits (stock) et /ordonnances-stock (backend/routes/ordonnances_stock.py).
  Fonction activable « Ordonnances et stock » (SMART Communications).
  Lot 54 — Auxiliaire en Pharmacie : scan + OCR uniquement (ni dépôts, ni stock, ni réservations,
  ni suppression) et historique de SES ordonnances scannées ; le serveur applique la même règle.
*/
import React, { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  Camera, CheckCircle2, ClipboardList, Loader2, PackageSearch, Pill, Search, Trash2, XCircle,
} from "lucide-react";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { estPhoto, reduirePhoto } from "@/lib/photos";

const MAX_PHOTOS = 4;

// Statut de disponibilité → libellé et couleurs du badge
const STATUTS = {
  disponible: { label: "Disponible", cls: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  insuffisant: { label: "Stock insuffisant", cls: "bg-amber-50 text-amber-800 ring-amber-200" },
  rupture: { label: "Rupture", cls: "bg-red-50 text-red-700 ring-red-200" },
  absent: { label: "Absent du stock", cls: "bg-slate-100 text-slate-700 ring-slate-200" },
  non_compte: { label: "Stock inconnu", cls: "bg-slate-100 text-slate-600 ring-slate-200" },
  a_confirmer: { label: "Produit à confirmer", cls: "bg-sky-50 text-sky-700 ring-sky-200" },
};

// Messages de la recherche d'équivalents (VIDAL)
const ETATS_EQUIVALENTS = {
  vidal_indisponible: "Module VIDAL non disponible sur la plateforme.",
  vidal_refuse: "VIDAL n'est pas activé pour votre compte.",
  vidal_erreur: "VIDAL n'a pas répondu, réessayez plus tard.",
  vidal_aucun_resultat: "VIDAL ne connaît pas ce médicament.",
  aucun_en_stock: "Aucun équivalent VIDAL n'est présent dans votre stock.",
};

const erreur = (e, defaut) => e?.response?.data?.detail || defaut;
// « 20280601 » → « 06/28 »
const perem = (p) => (p ? `${p.slice(4, 6)}/${p.slice(2, 4)}` : "—");
const dateFr = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "");

function Badge({ statut }) {
  const s = STATUTS[statut] || STATUTS.absent;
  return <span className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ${s.cls}`}>{s.label}</span>;
}

function Peremption({ produit }) {
  if (!produit?.peremption) return <span className="text-slate-400">—</span>;
  const a = produit.alerte_peremption;
  const cls = a === "perime" ? "text-red-700 font-semibold" : a === "proche" ? "text-amber-700 font-semibold" : "text-slate-600";
  return <span className={cls}>{perem(produit.peremption)}{a === "perime" ? " · périmé" : a === "proche" ? " · < 3 mois" : ""}</span>;
}

// Stock d'un produit : salle / magasin / disponible (après réservations des autres ordonnances)
function Stock({ produit }) {
  if (!produit) return <span className="text-slate-400">—</span>;
  if (!produit.compte) return <span className="text-slate-500 text-xs">non compté</span>;
  return (
    <span className="tabular-nums text-xs text-slate-700">
      Salle {produit.isalle} · Mag. {produit.imagasin}
      <b className="ml-1 text-slate-900">→ {produit.disponible} dispo</b>
      {produit.reserve_autres > 0 && <span className="text-slate-500"> ({produit.reserve_autres} réservé ailleurs)</span>}
    </span>
  );
}

// Lot 54 — lecture OCR seule (vue de l'Auxiliaire en Pharmacie)
function LignesOcr({ ordo }) {
  return (
    <section className="rounded-xl bg-white ring-1 ring-slate-200 overflow-hidden" data-testid="ordonnance-resultat-ocr">
      <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-3">
        <ClipboardList className="h-4 w-4 text-slate-500" />
        <p className="text-sm font-semibold text-slate-800 flex-1">
          Ordonnance {ordo.date_ordonnance ? `du ${ordo.date_ordonnance}` : ""} · lue le {dateFr(ordo.cree_le)}
        </p>
      </div>
      {ordo.lignes.length === 0 && <p className="px-4 py-3 text-sm text-slate-500">Aucun médicament lu.</p>}
      <div className="divide-y divide-slate-100">
        {ordo.lignes.map((l) => (
          <div key={l.index} className="px-4 py-3" data-testid={`ligne-ocr-${l.index}`}>
            <p className="text-sm font-semibold text-slate-900">
              {l.nom} {l.dosage && <span className="font-normal text-slate-600">{l.dosage}</span>}
              {l.forme && <span className="font-normal text-slate-500"> · {l.forme}</span>}
              {l.quantite ? <span className="font-normal text-slate-500"> · qté {l.quantite}</span> : null}
            </p>
            {l.posologie && <p className="text-xs text-slate-500">{l.posologie}</p>}
            {l.incertain && <p className="text-xs text-amber-700">Lecture douteuse{l.note ? ` : ${l.note}` : ""}</p>}
          </div>
        ))}
      </div>
    </section>
  );
}

export default function OrdonnancesStock() {
  const { user } = useAuth();
  const ocrSeul = (user?.tracked_role || "") === "Auxiliaire en Pharmacie";
  const [depots, setDepots] = useState([]);          // [{code_depot, produits, maj_le}]
  const [choisis, setChoisis] = useState([]);        // dépôts cochés (vide = tous)
  const [historique, setHistorique] = useState([]);
  const [ordo, setOrdo] = useState(null);            // ordonnance affichée
  const [photos, setPhotos] = useState([]);
  const [analyse, setAnalyse] = useState(false);
  const [occupe, setOccupe] = useState("");          // action en cours ("eq:2", "reserver"…)
  const [q, setQ] = useState("");
  const [trouves, setTrouves] = useState(null);
  const inputRef = useRef(null);

  const chargerHistorique = useCallback(() => {
    apiClient.get("/ordonnances-stock").then((r) => setHistorique(r.data || [])).catch(() => {});
  }, []);

  useEffect(() => {
    if (!ocrSeul) {
      apiClient.get("/stock-produits/depots")
        .then((r) => setDepots(r.data?.depots || []))
        .catch((e) => toast.error(erreur(e, "Impossible de charger votre stock")));
    }
    chargerHistorique();
  }, [chargerHistorique, ocrSeul]);

  // Photos choisies (appareil photo du téléphone ou fichiers) : réduites avant l'envoi
  const ajouterPhotos = async (liste) => {
    const fichiers = Array.from(liste || []).filter((f) => estPhoto(f) || f.type === "application/pdf");
    if (!fichiers.length) return;
    const reduites = await Promise.all(fichiers.map((f) => (estPhoto(f) ? reduirePhoto(f) : f)));
    setPhotos((p) => [...p, ...reduites].slice(0, MAX_PHOTOS));
  };

  const analyser = async () => {
    if (!photos.length) return toast.error("Photographiez d'abord l'ordonnance");
    const form = new FormData();
    photos.forEach((p) => form.append("photos", p));
    if (choisis.length) form.append("depots", choisis.join(","));
    setAnalyse(true);
    try {
      const r = await apiClient.post("/ordonnances-stock", form, { headers: { "Content-Type": "multipart/form-data" } });
      setOrdo(r.data);
      setPhotos([]);
      chargerHistorique();
      if (!r.data.lignes.length) toast.warning("Aucun médicament lu sur la photo : reprenez-la plus nette.");
    } catch (e) {
      toast.error(erreur(e, "Lecture de l'ordonnance impossible"));
    } finally {
      setAnalyse(false);
    }
  };

  // Action sur l'ordonnance affichée (le serveur renvoie l'ordonnance recalculée)
  const action = async (cle, requete, succes) => {
    setOccupe(cle);
    try {
      const r = await requete();
      setOrdo(r.data.ordonnance || r.data);
      if (succes) toast.success(typeof succes === "function" ? succes(r.data) : succes);
    } catch (e) {
      toast.error(erreur(e, "Action impossible"));
    } finally {
      setOccupe("");
    }
  };

  const choisir = (i, produit_id) => action(`choix:${i}`,
    () => apiClient.put(`/ordonnances-stock/${ordo.id}/lignes/${i}`, { produit_id: produit_id || null }));
  const quantite = (i, produit_id, valeur) => action(`qte:${i}`,
    () => apiClient.put(`/ordonnances-stock/${ordo.id}/lignes/${i}`, { produit_id, quantite: Math.max(1, Number(valeur) || 1) }));
  const equivalents = (i) => action(`eq:${i}`, () => apiClient.post(`/ordonnances-stock/${ordo.id}/lignes/${i}/equivalents`));
  const reserver = () => action("reserver", () => apiClient.post(`/ordonnances-stock/${ordo.id}/reserver`),
    (d) => (d.reservations?.length ? `${d.reservations.length} produit(s) réservé(s)` : "Rien de plus à réserver"));
  const cloturer = (rid, quoi) => action(`resa:${rid}`,
    () => apiClient.post(`/ordonnances-stock/${ordo.id}/reservations/${rid}/${quoi}`),
    quoi === "vendue" ? "Vente enregistrée" : "Réservation annulée");

  const ouvrir = async (id) => {
    try {
      setOrdo((await apiClient.get(`/ordonnances-stock/${id}`)).data);
    } catch (e) {
      toast.error(erreur(e, "Ordonnance introuvable"));
    }
  };

  const supprimer = async (id) => {
    if (!window.confirm("Supprimer cette ordonnance ? Ses réservations en cours seront annulées.")) return;
    try {
      await apiClient.delete(`/ordonnances-stock/${id}`);
      if (ordo?.id === id) setOrdo(null);
      chargerHistorique();
    } catch (e) {
      toast.error(erreur(e, "Suppression impossible"));
    }
  };

  // Recherche libre dans le stock (vérification rapide au comptoir)
  const rechercher = async (e) => {
    e.preventDefault();
    if (q.trim().length < 2) return;
    const params = new URLSearchParams({ q: q.trim(), limit: "30" });
    if (choisis.length === 1) params.set("depot", choisis[0]);
    try {
      setTrouves((await apiClient.get(`/stock-produits?${params}`)).data.produits);
    } catch (err) {
      toast.error(erreur(err, "Recherche impossible"));
    }
  };

  const basculerDepot = (code) => setChoisis((c) => (c.includes(code) ? c.filter((x) => x !== code) : [...c, code]));
  const aReserver = ordo?.lignes.some((l) => l.produit && !l.reservation && l.produit.compte && l.produit.disponible > 0
    && l.produit.alerte_peremption !== "perime");

  return (
    <div className="max-w-6xl space-y-5" data-testid="ordonnances-stock-page">
      <div>
        <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Pharmacie</p>
        <h1 className="text-2xl font-display font-bold flex items-center gap-2">
          <Pill className="h-5 w-5 text-emerald-600" /> Ordonnances et stock
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          {ocrSeul
            ? "Photographiez ou scannez l'ordonnance puis lancez la lecture (OCR) des médicaments prescrits. La photo n'est pas conservée."
            : "Photographiez l'ordonnance : chaque médicament est recherché dans votre stock (salle et magasin), avec la péremption et les équivalents VIDAL disponibles. La photo n'est pas conservée."}
        </p>
      </div>

      {/* Dépôts du client : cochés = recherche limitée à ces dépôts (aucun coché = tous) */}
      {!ocrSeul && (
      <section className="rounded-xl bg-white ring-1 ring-slate-200 p-4 space-y-2">
        <p className="text-sm font-semibold text-slate-700">Dépôts</p>
        {depots.length === 0 ? (
          <p className="text-sm text-slate-500">Aucun stock enregistré pour votre compte (envoi Loois ou liste de pointage à traiter).</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {depots.map((d) => (
              <button key={d.code_depot} type="button" onClick={() => basculerDepot(d.code_depot)}
                data-testid={`depot-${d.code_depot}`}
                className={`rounded-lg px-3 py-1.5 text-xs ring-1 transition ${choisis.includes(d.code_depot)
                  ? "bg-emerald-600 text-white ring-emerald-600" : "bg-white text-slate-700 ring-slate-300 hover:bg-slate-50"}`}>
                <b>{d.code_depot}</b> · {d.produits} produits · stock du {dateFr(d.maj_le)}
              </button>
            ))}
          </div>
        )}
      </section>
      )}

      <div className="grid gap-5 lg:grid-cols-[1fr_18rem]">
        <div className="space-y-5 min-w-0">
          {/* Prise de photo */}
          <section className="rounded-xl bg-white ring-1 ring-slate-200 p-4 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <input ref={inputRef} type="file" accept="image/*,application/pdf" capture="environment" multiple hidden
                data-testid="ordonnance-photos" onChange={(e) => { ajouterPhotos(e.target.files); e.target.value = ""; }} />
              <Button type="button" variant="outline" onClick={() => inputRef.current?.click()} disabled={photos.length >= MAX_PHOTOS}>
                <Camera className="h-4 w-4 mr-1.5" /> Photographier l'ordonnance
              </Button>
              <Button type="button" onClick={analyser} disabled={!photos.length || analyse} data-testid="ordonnance-analyser"
                className="bg-emerald-600 hover:bg-emerald-700">
                {analyse ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : <PackageSearch className="h-4 w-4 mr-1.5" />}
                {ocrSeul ? "Lancer l'OCR" : "Vérifier la disponibilité"}
              </Button>
              {photos.length > 0 && (
                <span className="text-xs text-slate-500">
                  {photos.length} photo(s) · <button type="button" className="underline" onClick={() => setPhotos([])}>effacer</button>
                </span>
              )}
            </div>
            <p className="text-xs text-slate-400">Jusqu'à {MAX_PHOTOS} photos (recto, verso…) ou un PDF.</p>
          </section>

          {/* Résultat */}
          {ordo && ordo.ocr_seulement && <LignesOcr ordo={ordo} />}
          {ordo && !ordo.ocr_seulement && (
            <section className="rounded-xl bg-white ring-1 ring-slate-200 overflow-hidden" data-testid="ordonnance-resultat">
              <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-4 py-3">
                <ClipboardList className="h-4 w-4 text-slate-500" />
                <p className="text-sm font-semibold text-slate-800 flex-1">
                  Ordonnance {ordo.date_ordonnance ? `du ${ordo.date_ordonnance}` : ""} · lue le {dateFr(ordo.cree_le)}
                  {ordo.depots?.length ? ` · dépôt(s) ${ordo.depots.join(", ")}` : ""}
                </p>
                <Button size="sm" onClick={reserver} disabled={!aReserver || occupe === "reserver"} data-testid="ordonnance-reserver">
                  {occupe === "reserver" && <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />}
                  Réserver les quantités disponibles
                </Button>
              </div>
              {ordo.stock_vide && (
                <p className="bg-amber-50 px-4 py-2 text-xs text-amber-800">Votre stock est vide : aucun produit n'a pu être rapproché.</p>
              )}
              <div className="divide-y divide-slate-100">
                {ordo.lignes.map((l) => (
                  <div key={l.index} className="px-4 py-3 space-y-2" data-testid={`ligne-${l.index}`}>
                    <div className="flex flex-wrap items-start gap-2">
                      <div className="flex-1 min-w-[12rem]">
                        <p className="text-sm font-semibold text-slate-900">
                          {l.nom} {l.dosage && <span className="font-normal text-slate-600">{l.dosage}</span>}
                          {l.forme && <span className="font-normal text-slate-500"> · {l.forme}</span>}
                        </p>
                        {l.posologie && <p className="text-xs text-slate-500">{l.posologie}</p>}
                        {l.incertain && <p className="text-xs text-amber-700">Lecture douteuse{l.note ? ` : ${l.note}` : ""}</p>}
                      </div>
                      <Badge statut={l.statut} />
                      {l.produit?.alerte_peremption === "perime" && (
                        <span className="inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 bg-red-50 text-red-700 ring-red-200">
                          Périmé : non réservé
                        </span>
                      )}
                    </div>

                    {/* Produit retenu, ou choix parmi les candidats */}
                    <div className="grid gap-2 sm:grid-cols-[1fr_auto] items-center">
                      <select className="w-full rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm"
                        value={l.produit?.produit_id || ""} disabled={occupe === `choix:${l.index}` || Boolean(l.reservation)}
                        onChange={(e) => choisir(l.index, e.target.value)} data-testid={`choix-${l.index}`}>
                        <option value="">{l.candidats.length ? "— Choisir le produit du stock —" : "— Aucun produit correspondant —"}</option>
                        {[l.produit, ...l.candidats, ...l.equivalents].filter(Boolean)
                          .filter((p, k, liste) => liste.findIndex((x) => x.produit_id === p.produit_id) === k)
                          .map((p) => (
                            <option key={p.produit_id} value={p.produit_id}>
                              {p.libelle} [{p.mesure || "-"}] · {p.code_depot} · {p.compte ? `${p.disponible} dispo` : "non compté"}
                              {p.titre_vidal ? " · équivalent VIDAL" : ""}
                            </option>
                          ))}
                      </select>
                      <label className="flex items-center gap-1 text-xs text-slate-500">
                        Qté
                        <input type="number" min={1} defaultValue={l.demande} key={`${l.index}-${l.demande}`}
                          disabled={!l.produit || Boolean(l.reservation)}
                          onBlur={(e) => Number(e.target.value) !== l.demande && quantite(l.index, l.produit?.produit_id, e.target.value)}
                          className="w-16 rounded border border-slate-300 px-1.5 py-1 text-sm tabular-nums" />
                      </label>
                    </div>
                    {l.produit && (
                      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
                        <Stock produit={l.produit} />
                        <span>Péremption : <Peremption produit={l.produit} /></span>
                        {l.produit.prix_public != null && <span className="text-slate-500">{l.produit.prix_public} FCFA</span>}
                      </div>
                    )}

                    {/* Équivalents VIDAL présents en stock */}
                    {l.statut !== "disponible" && (
                      <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-slate-700">Équivalents (VIDAL)</span>
                          <button type="button" className="text-emerald-700 underline disabled:opacity-50"
                            disabled={occupe === `eq:${l.index}`} onClick={() => equivalents(l.index)} data-testid={`equivalents-${l.index}`}>
                            {occupe === `eq:${l.index}` ? "recherche…" : l.equivalents_etat ? "relancer" : "rechercher"}
                          </button>
                        </div>
                        {ETATS_EQUIVALENTS[l.equivalents_etat] && <p className="text-slate-500">{ETATS_EQUIVALENTS[l.equivalents_etat]}</p>}
                        {l.equivalents.map((e) => (
                          <div key={e.produit_id} className="flex flex-wrap items-center gap-2">
                            <span className="text-slate-800">{e.libelle}</span>
                            <span className="text-slate-500">({e.titre_vidal})</span>
                            <Stock produit={e} /> <Peremption produit={e} />
                            <button type="button" className="text-emerald-700 underline" onClick={() => choisir(l.index, e.produit_id)}>choisir</button>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Réservation en cours */}
                    {l.reservation && (
                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-emerald-700 ring-1 ring-emerald-200">
                          {l.reservation.quantite} réservé(s) jusqu'au {dateFr(l.reservation.expire_le)}
                        </span>
                        <button type="button" className="inline-flex items-center gap-1 text-emerald-700" onClick={() => cloturer(l.reservation.id, "vendue")}>
                          <CheckCircle2 className="h-3.5 w-3.5" /> Vendue
                        </button>
                        <button type="button" className="inline-flex items-center gap-1 text-red-600" onClick={() => cloturer(l.reservation.id, "annuler")}>
                          <XCircle className="h-3.5 w-3.5" /> Annuler
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>

        {/* Colonne droite : recherche dans le stock + ordonnances récentes */}
        <aside className="space-y-5">
          {!ocrSeul && (
          <section className="rounded-xl bg-white ring-1 ring-slate-200 p-3 space-y-2">
            <form onSubmit={rechercher} className="flex gap-1.5">
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Chercher dans le stock…"
                className="min-w-0 flex-1 rounded-lg border border-slate-300 px-2 py-1.5 text-sm" data-testid="stock-recherche" />
              <Button type="submit" size="sm" variant="outline"><Search className="h-4 w-4" /></Button>
            </form>
            {trouves && (
              <ul className="max-h-72 overflow-y-auto divide-y divide-slate-100 text-xs">
                {trouves.length === 0 && <li className="py-2 text-slate-500">Aucun produit.</li>}
                {trouves.map((p) => (
                  <li key={p.id} className="py-1.5">
                    <p className="font-medium text-slate-800">{p.libelle} <span className="text-slate-400">{p.code_depot}</span></p>
                    <p className="text-slate-500">
                      {p.compte ? `Salle ${p.isalle} · Mag. ${p.imagasin} · ${p.disponible} dispo` : "non compté"} · pér. <Peremption produit={p} />
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </section>
          )}
          <section className="rounded-xl bg-white ring-1 ring-slate-200 p-3">
            <p className="text-sm font-semibold text-slate-700 mb-2">{ocrSeul ? "Mes ordonnances scannées" : "Ordonnances récentes"}</p>
            {historique.length === 0 && <p className="text-xs text-slate-500">Aucune ordonnance.</p>}
            <ul className="space-y-1.5">
              {historique.map((h) => (
                <li key={h.id} className={`flex items-start gap-2 rounded-lg px-2 py-1.5 text-xs ${ordo?.id === h.id ? "bg-emerald-50" : "hover:bg-slate-50"}`}>
                  <button type="button" className="flex-1 text-left" onClick={() => ouvrir(h.id)}>
                    <p className="font-medium text-slate-800">{dateFr(h.cree_le)} · {h.lignes} ligne(s)</p>
                    <p className="text-slate-500 truncate">{h.noms.filter(Boolean).join(", ")}</p>
                  </button>
                  {!ocrSeul && (
                  <button type="button" onClick={() => supprimer(h.id)} aria-label="Supprimer" className="text-slate-400 hover:text-red-600">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                  )}
                </li>
              ))}
            </ul>
          </section>
        </aside>
      </div>
    </div>
  );
}
