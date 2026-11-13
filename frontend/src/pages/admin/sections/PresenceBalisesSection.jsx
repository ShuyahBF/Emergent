// PresenceBalisesSection.jsx — Lot 387 : rubrique « 📍 Présence par balises » des Paramètres.
// Cas d'usage : suivre les visiteurs d'un site grâce à des badges (balises Bluetooth). Des RÉCEPTEURS fixes (un téléphone Android, plus tard un PC
// Windows ou un boîtier) écoutent les badges et les envoient à SAWALI ; cette rubrique montre QUI est dans QUELLE zone en direct, et le parcours de
// chaque badge. Tout est configuré ici (site, zones, récepteurs, badges). Contrat d'échange pour brancher un autre récepteur ou un autre écran :
// POST /api/presence-balises/v1/detections (voir routes/presence_balises.py).
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const duree = (s) => (s == null ? "—" : s < 60 ? `${s} s` : s < 3600 ? `${Math.floor(s / 60)} min` : `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`);
const heure = (iso) => new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "medium" });

export default function PresenceBalisesSection() {
  const [sites, setSites] = useState([]);
  const [siteId, setSiteId] = useState("");
  const [etat, setEtat] = useState(null);
  const [nomSite, setNomSite] = useState("");
  const [nomZone, setNomZone] = useState("");
  const [recepteur, setRecepteur] = useState({ nom: "", zone_id: "" });
  const [cleAffichee, setCleAffichee] = useState(null);       // { identifiant, cle } montrée UNE SEULE FOIS
  const [badge, setBadge] = useState({ id: "", libelle: "" });
  const [libellesInconnus, setLibellesInconnus] = useState({});   // libellé saisi pour chaque badge détecté non enregistré
  const [parcoursBadge, setParcoursBadge] = useState("");
  const [passages, setPassages] = useState(null);

  const site = sites.find((s) => s.id === siteId);

  const chargerSites = useCallback(async () => {
    const { data } = await apiClient.get("/admin/presence-balises/sites");
    setSites(data.sites);
    setSiteId((cur) => cur || data.sites[0]?.id || "");
  }, []);
  useEffect(() => { chargerSites().catch(() => toast.error("Chargement impossible")); }, [chargerSites]);

  // État en direct : relu toutes les 5 secondes (les sorties sont détectées à la lecture)
  useEffect(() => {
    if (!siteId) { setEtat(null); return undefined; }
    let actif = true;
    const lire = () => apiClient.get(`/admin/presence-balises/sites/${siteId}/etat`).then((r) => actif && setEtat(r.data)).catch(() => {});
    lire();
    const t = setInterval(lire, 5000);
    return () => { actif = false; clearInterval(t); };
  }, [siteId]);

  const erreur = (e) => toast.error(e?.response?.data?.detail || "Action impossible");
  const configurer = async (corps) => { try { await apiClient.put(`/admin/presence-balises/sites/${siteId}`, corps); await chargerSites(); } catch (e) { erreur(e); } };

  const creerSite = async () => {
    try { const { data } = await apiClient.post("/admin/presence-balises/sites", { nom: nomSite }); setNomSite(""); await chargerSites(); setSiteId(data.id); } catch (e) { erreur(e); }
  };
  const ajouterZone = async () => { if (!nomZone.trim()) return; await configurer({ zones: [...site.zones, { nom: nomZone }] }); setNomZone(""); };
  const retirerZone = (id) => configurer({ zones: site.zones.filter((z) => z.id !== id) });
  const ajouterBadge = async (id, libelle) => { await configurer({ badges: [...site.badges, { id, libelle: libelle || id }] }); setBadge({ id: "", libelle: "" }); };
  const retirerBadge = (id) => configurer({ badges: site.badges.filter((b) => b.id !== id) });
  // Renomme un badge (sans le retirer) : enregistré quand on quitte le champ, seulement si le libellé a changé
  const renommerBadge = (id, libelle) => {
    const nouveau = libelle.trim();
    if (!nouveau || site.badges.find((b) => b.id === id)?.libelle === nouveau) return;
    configurer({ badges: site.badges.map((b) => (b.id === id ? { ...b, libelle: nouveau } : b)) });
  };
  const ajouterRecepteur = async () => {
    try {
      const { data } = await apiClient.post(`/admin/presence-balises/sites/${siteId}/recepteurs`, recepteur);
      setCleAffichee({ identifiant: data.identifiant, cle: data.cle });
      setRecepteur({ nom: "", zone_id: recepteur.zone_id });
      await chargerSites();
    } catch (e) { erreur(e); }
  };
  const retirerRecepteur = async (id) => { try { await apiClient.delete(`/admin/presence-balises/sites/${siteId}/recepteurs/${id}`); await chargerSites(); } catch (e) { erreur(e); } };
  const voirParcours = async (b) => {
    setParcoursBadge(b);
    try { const { data } = await apiClient.get(`/admin/presence-balises/sites/${siteId}/parcours`, { params: { badge: b } }); setPassages(data.passages); } catch (e) { erreur(e); }
  };
  const copier = (t) => { navigator.clipboard.writeText(t); toast.success("Copié"); };

  const champ = "rounded-lg border border-slate-300 px-2 py-1 text-sm";
  const bouton = "rounded-lg bg-sky-700 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50";

  return (
    <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-presence-balises">
      <p className="text-xs text-slate-600">
        Suivi de présence par badges Bluetooth : chaque visiteur porte une balise ; des <b>récepteurs fixes</b> (téléphone Android avec l'application « Personnel de maison »,
        plus tard un PC Windows ou un boîtier) écoutent les badges et les envoient ici. Un badge est dans la zone du récepteur qui l'entend le plus fort ; sans signal pendant
        {" "}{site?.delai_absence_s || 60} s, il est considéré sorti. <b>Vie privée :</b> un badge n'a pas de nom, seulement un libellé ; les passages sont supprimés après {site?.conservation_jours || 30} jours ;
        informez les visiteurs et recueillez leur accord.
      </p>

      <div className="flex flex-wrap items-center gap-2 boutons-distincts">
        <select value={siteId} onChange={(e) => { setSiteId(e.target.value); setPassages(null); }} className={champ} data-testid="presence-site">
          {sites.length === 0 && <option value="">Aucun site</option>}
          {sites.map((s) => <option key={s.id} value={s.id}>{s.nom}</option>)}
        </select>
        <input value={nomSite} onChange={(e) => setNomSite(e.target.value)} placeholder="Nom d'un nouveau site" className={champ} data-testid="presence-nouveau-site" />
        <button type="button" onClick={creerSite} disabled={!nomSite.trim()} className={bouton}>Créer le site</button>
      </div>

      {site && (
        <>
          {/* ---- ÉTAT EN DIRECT, en premier : c'est ce qu'on veut voir ---- */}
          <div className="space-y-2" data-testid="presence-etat">
            <p className="text-sm font-semibold text-slate-800">En direct</p>
            {etat?.zones.length === 0 && <p className="text-xs text-slate-500">Créez d'abord des zones (étape 1 ci-dessous).</p>}
            <div className="grid gap-2 sm:grid-cols-2">
              {etat?.zones.map((z) => (
                <div key={z.id} className="rounded-lg border border-emerald-200 bg-emerald-50 p-2">
                  <p className="text-sm font-semibold text-emerald-900">{z.nom} · {z.presents.length}</p>
                  {z.presents.length === 0 ? <p className="text-xs text-slate-500">Personne</p> : (
                    <ul className="text-xs text-slate-800">
                      {z.presents.map((p) => <li key={p.badge}><button type="button" className="underline" onClick={() => voirParcours(p.badge)}>{p.libelle}</button> · depuis {duree(p.depuis_s)}</li>)}
                    </ul>
                  )}
                </div>
              ))}
            </div>
            {etat && etat.absents.length > 0 && <p className="text-xs text-slate-600">Hors du site : {etat.absents.map((a) => a.libelle).join(", ")}</p>}
            {etat && etat.inconnus.length > 0 && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-2">
                <p className="text-xs font-semibold text-amber-900">Badges détectés, non enregistrés ({etat.inconnus.length})</p>
                <ul className="text-xs text-slate-800">
                  {etat.inconnus.map((i) => (
                    <li key={i.badge} className="flex items-center gap-2">
                      <span className="font-mono">{i.badge}</span> · vu il y a {duree(i.dernier_signal_s)}
                      <input value={libellesInconnus[i.badge] || ""} onChange={(e) => setLibellesInconnus({ ...libellesInconnus, [i.badge]: e.target.value })}
                        placeholder="Libellé (ex. Visiteur 12)" className="w-40 rounded border border-amber-300 px-2 py-0.5" data-testid="presence-libelle-inconnu" />
                      <button type="button" className="rounded bg-amber-600 px-2 py-0.5 text-white" onClick={() => { ajouterBadge(i.badge, libellesInconnus[i.badge] || ""); setLibellesInconnus({ ...libellesInconnus, [i.badge]: "" }); }}>Enregistrer</button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {passages && (
            <div className="rounded-lg border border-slate-200 p-2" data-testid="presence-parcours">
              <p className="text-sm font-semibold">Parcours de {site.badges.find((b) => b.id === parcoursBadge)?.libelle || parcoursBadge}</p>
              {passages.length === 0 ? <p className="text-xs text-slate-500">Aucun passage enregistré.</p> : (
                <ul className="text-xs">{passages.map((p, i) => <li key={i}>{heure(p.t)} : {p.de || "hors du site"} → <b>{p.vers || "sortie du site"}</b></li>)}</ul>
              )}
            </div>
          )}

          {/* ---- 1. ZONES ---- */}
          <div className="space-y-1">
            <p className="text-sm font-semibold text-slate-800">1. Zones (pièces, salles, entrée…)</p>
            <div className="flex flex-wrap gap-2">{site.zones.map((z) => <span key={z.id} className="rounded-full bg-slate-100 px-3 py-1 text-xs">{z.nom} <button type="button" className="ml-1 text-rose-700" onClick={() => retirerZone(z.id)} aria-label={`Retirer ${z.nom}`}>×</button></span>)}</div>
            <div className="flex gap-2 boutons-distincts"><input value={nomZone} onChange={(e) => setNomZone(e.target.value)} placeholder="Nom de la zone (ex. Accueil)" className={champ} /><button type="button" onClick={ajouterZone} className={bouton}>Ajouter la zone</button></div>
          </div>

          {/* ---- 2. RÉCEPTEURS ---- */}
          <div className="space-y-1">
            <p className="text-sm font-semibold text-slate-800">2. Récepteurs (un par zone, ou plus)</p>
            <ul className="text-xs">
              {etat?.recepteurs.map((r) => (
                <li key={r.id} className="flex items-center gap-2">{r.nom} → {site.zones.find((z) => z.id === r.zone_id)?.nom} · dernier envoi : {r.dernier_envoi_s == null ? "jamais" : `il y a ${duree(r.dernier_envoi_s)}`}
                  <button type="button" className="text-rose-700 underline" onClick={() => retirerRecepteur(r.id)}>Retirer</button></li>
              ))}
            </ul>
            <div className="flex flex-wrap gap-2 boutons-distincts">
              <input value={recepteur.nom} onChange={(e) => setRecepteur({ ...recepteur, nom: e.target.value })} placeholder="Nom (ex. Téléphone accueil)" className={champ} />
              <select value={recepteur.zone_id} onChange={(e) => setRecepteur({ ...recepteur, zone_id: e.target.value })} className={champ} data-testid="presence-recepteur-zone">
                <option value="">Zone…</option>{site.zones.map((z) => <option key={z.id} value={z.id}>{z.nom}</option>)}
              </select>
              <button type="button" onClick={ajouterRecepteur} disabled={!recepteur.nom.trim() || !recepteur.zone_id} className={bouton}>Créer le récepteur</button>
            </div>
            {cleAffichee && (
              <div className="rounded-lg border border-rose-300 bg-rose-50 p-2 text-xs" data-testid="presence-cle">
                <p className="font-semibold text-rose-900">À saisir UNE SEULE FOIS dans l'application du récepteur (elle ne sera plus affichée) :</p>
                <p>Identifiant : <span className="font-mono">{cleAffichee.identifiant}</span> <button type="button" className="underline" onClick={() => copier(cleAffichee.identifiant)}>Copier</button></p>
                <p>Clé : <span className="font-mono break-all">{cleAffichee.cle}</span> <button type="button" className="underline" onClick={() => copier(cleAffichee.cle)}>Copier</button></p>
                <button type="button" className="mt-1 underline" onClick={() => setCleAffichee(null)}>J'ai noté la clé</button>
              </div>
            )}
          </div>

          {/* ---- 3. BADGES ---- */}
          <div className="space-y-1">
            <p className="text-sm font-semibold text-slate-800">3. Badges (balises remises aux visiteurs)</p>
            <ul className="space-y-1 text-xs">{site.badges.map((b) => (
              <li key={b.id} className="flex flex-wrap items-center gap-2">
                <input defaultValue={b.libelle} key={b.libelle} onBlur={(e) => renommerBadge(b.id, e.target.value)} onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
                  className="w-40 rounded border border-slate-300 px-2 py-0.5 font-semibold" aria-label={`Libellé du badge ${b.id}`} data-testid="presence-libelle-badge" />
                <span className="font-mono text-slate-500">{b.id}</span>
                <button type="button" className="text-sky-700 underline" onClick={() => voirParcours(b.id)}>Parcours</button>
                <button type="button" className="text-rose-700 underline" onClick={() => retirerBadge(b.id)}>Retirer</button>
              </li>))}</ul>
            <p className="text-[11px] text-slate-500">Pour renommer un badge, modifiez son libellé puis quittez le champ (ou Entrée).</p>
            <div className="flex flex-wrap gap-2 boutons-distincts">
              <input value={badge.id} onChange={(e) => setBadge({ ...badge, id: e.target.value })} placeholder="Identifiant (ex. ib:…) — ou « Enregistrer » ci-dessus" className={`${champ} w-72`} />
              <input value={badge.libelle} onChange={(e) => setBadge({ ...badge, libelle: e.target.value })} placeholder="Libellé (ex. Visiteur 12)" className={champ} />
              <button type="button" onClick={() => ajouterBadge(badge.id, badge.libelle)} disabled={!badge.id.trim()} className={bouton}>Ajouter le badge</button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
