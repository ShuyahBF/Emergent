// DecouverteReseau.jsx — Lot 80 : Équipements → « Découverte du réseau » (administrateur).
//
// Loois (sur un Windows Server du client) balaie chaque nuit le réseau local : ping, table ARP, nom d'hôte et SNMP
// en lecture seule (imprimantes, switchs, onduleurs…). Cet écran montre ce qu'il a trouvé :
//   - « À valider » : appareils inconnus du parc. « Valider » crée leur fiche dans le Parc informatique (« À affecter »),
//     « Ignorer » les écarte (téléphone de passage…) ;
//   - « Déjà dans le parc » : appareils reconnus par leur adresse MAC (leur fiche est complétée automatiquement) ;
//   - ALERTES : appareils suivis qui n'ont plus été vus depuis N jours (réglage des Paramètres).
// Les réglages (heure, machines, communauté SNMP) sont dans Paramètres → « 🛰️ Équipements — découverte du réseau ».
import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { RefreshCw, Radar } from "lucide-react";
import { apiClient } from "@/lib/api";

const ONGLETS = [
  { cle: "a_valider", libelle: "À valider" },
  { cle: "connu", libelle: "Déjà dans le parc" },
  { cle: "valide", libelle: "Validés" },
  { cle: "ignore", libelle: "Ignorés" },
];

// « 08/10/2026 02:31 » (vide si absente)
function dateCourte(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }).replace(",", "");
}

// Message d'erreur lisible renvoyé par le serveur
const erreur = (e, defaut) => e?.response?.data?.detail || defaut;

// Jauge circulaire transparente (arc qui tourne) pendant les attentes longues, comme sur le reste de SAWALI
function Jauge() {
  return <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-sky-500/30 border-t-sky-600" aria-label="Patientez…" />;
}

export default function DecouverteReseau() {
  const [onglet, setOnglet] = useState("a_valider");
  const [client, setClient] = useState("");
  const [donnees, setDonnees] = useState(null);
  const [chargement, setChargement] = useState(false);
  const [selection, setSelection] = useState(null);           // ligne sélectionnée (règle 3 des tableaux)
  const [categories, setCategories] = useState({});            // catégorie choisie avant validation, par appareil
  const [recherche, setRecherche] = useState("");

  // Lecture de la liste (onglet + client) ; toast « Patientez… » pendant l'attente
  const charger = useCallback(async () => {
    setChargement(true);
    const attente = toast.loading("Patientez…");
    try {
      const r = await apiClient.get("/admin/equipements/reseau", { params: { statut: onglet, client } });
      setDonnees(r.data);
    } catch (e) {
      toast.error(erreur(e, "Liste indisponible"));
    } finally {
      toast.dismiss(attente);
      setChargement(false);
    }
  }, [onglet, client]);
  useEffect(() => { charger(); }, [charger]);

  // Actions sur un appareil : valider (avec la catégorie choisie), ignorer, remettre « À valider »
  const agir = async (a, action) => {
    try {
      const corps = action === "valider" ? { categorie: categories[a.id] || a.categorie || "autre" } : {};
      const r = await apiClient.post(`/admin/equipements/reseau/${a.id}/${action}`, corps);
      if (action === "valider") toast.success(`Fiche ${r.data.numero_inventaire} créée dans le parc (à affecter à un client)`);
      else toast.success(action === "ignorer" ? "Appareil ignoré" : "Appareil remis « À valider »");
      charger();
    } catch (e) {
      toast.error(erreur(e, "Action impossible"));
    }
  };

  // « Lancer maintenant » : les postes autorisés balaient le réseau à leur prochaine consigne (≤ 15 min)
  const lancer = async () => {
    try {
      await apiClient.post("/admin/equipements/decouverte-lancer");
      toast.success("Demande envoyée : les postes Loois balaieront le réseau d'ici 15 minutes.");
    } catch (e) {
      toast.error(erreur(e, "Demande impossible"));
    }
  };

  const appareils = (donnees?.appareils || []).filter((a) => {
    if (!recherche) return true;
    const t = `${a.ip || ""} ${a.mac || ""} ${a.nom_hote || ""} ${a.snmp?.modele || ""} ${a.snmp?.description || ""} ${a.client_libelle || ""}`;
    return t.toLowerCase().includes(recherche.toLowerCase());
  });
  const categoriesDispo = donnees?.categories || {};
  const absents = donnees?.alertes?.absents || [];

  return (
    <div className="space-y-4 p-4" data-testid="page-decouverte-reseau">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-display font-bold"><Radar className="h-5 w-5" /> Découverte du réseau</h1>
          <p className="text-xs text-slate-500">
            Appareils trouvés par Loois sur le réseau des clients (ping, ARP, SNMP en lecture seule). Réglages :{" "}
            <Link to="/admin/settings#s-decouverte-reseau" className="text-sky-700 underline">Paramètres → Équipements — découverte du réseau</Link>.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={lancer} className="rounded-lg bg-sky-700 px-3 py-1.5 text-sm font-semibold text-white" data-testid="decouverte-lancer">
            Lancer une découverte maintenant
          </button>
          <button type="button" onClick={charger} disabled={chargement} className="rounded-lg border border-slate-300 px-2 py-1.5" title="Actualiser">
            {chargement ? <Jauge /> : <RefreshCw className="h-4 w-4" />}
          </button>
        </div>
      </div>

      {/* ---- Alertes : appareils à valider, appareils suivis absents ---- */}
      {donnees && (donnees.alertes.a_valider > 0 || absents.length > 0) && (
        <div className="space-y-2" data-testid="decouverte-alertes">
          {donnees.alertes.a_valider > 0 && (
            <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              🆕 <b>{donnees.alertes.a_valider}</b> nouvel(le)(s) appareil(s) à valider sur le réseau des clients.
            </div>
          )}
          {absents.length > 0 && (
            <details className="rounded-lg border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-900">
              <summary className="cursor-pointer">⚠️ <b>{absents.length}</b> appareil(s) du parc ne sont plus vus sur le réseau</summary>
              <ul className="mt-1 list-disc pl-5 text-xs">
                {absents.map((a) => (
                  <li key={a.id}>{a.numero_inventaire || "—"} · {a.nom_hote || a.snmp?.modele || a.ip} ({a.mac || a.ip}) · {a.client_libelle} · vu pour la dernière fois le {dateCourte(a.derniere_vue)} ({a.absent_jours} j)</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      {/* ---- Onglets, client, recherche ---- */}
      <div className="flex flex-wrap items-center gap-2">
        {ONGLETS.map((o) => (
          <button key={o.cle} type="button" onClick={() => setOnglet(o.cle)}
            className={`rounded-full px-3 py-1 text-sm ${onglet === o.cle ? "bg-slate-800 text-white" : "border border-slate-300 bg-white"}`}>
            {o.libelle} <span className="ml-1 text-xs opacity-70">{donnees?.compteurs?.[o.cle] ?? ""}</span>
          </button>
        ))}
        <select value={client} onChange={(e) => setClient(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1 text-sm">
          <option value="">Tous les clients</option>
          {(donnees?.clients || []).map((c) => <option key={c.id} value={c.id}>{c.libelle}</option>)}
        </select>
        <input value={recherche} onChange={(e) => setRecherche(e.target.value)} placeholder="Rechercher (IP, MAC, nom, modèle)…"
          className="w-full rounded-lg border border-slate-300 px-3 py-1 text-sm sm:w-72" />
      </div>

      {/* ---- Tableau des appareils ---- */}
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-2 py-2">Appareil</th><th className="px-2 py-2">Adresse IP</th><th className="px-2 py-2">Adresse MAC</th>
              <th className="px-2 py-2">Modèle / n° de série</th><th className="px-2 py-2">Client</th><th className="px-2 py-2">Vu</th>
              <th className="px-2 py-2">{onglet === "a_valider" ? "Catégorie" : "Fiche du parc"}</th><th className="px-2 py-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {appareils.map((a) => {
              const snmp = a.snmp || {};
              return (
                <tr key={a.id} className={`border-t border-slate-100 ${selection === a.id ? "ligne-selectionnee" : ""}`} onClick={() => setSelection(a.id)}>
                  <td className="px-2 py-1.5">
                    <span className="font-medium">{a.nom_hote || snmp.nom || "(sans nom)"}</span>
                    {snmp.description && <span className="block max-w-xs truncate text-[11px] text-slate-500" title={snmp.description}>{snmp.description}</span>}
                    {a.mac_aleatoire && <span className="block text-[11px] text-amber-700">MAC aléatoire : probablement un téléphone ou une tablette</span>}
                    {snmp.pages != null && <span className="block text-[11px] text-slate-500">{snmp.pages.toLocaleString("fr-FR")} pages imprimées</span>}
                    {(snmp.consommables || []).length > 0 && (
                      <span className="block text-[11px] text-slate-500">{snmp.consommables.map((c) => `${c.nom} ${c.pct ?? "?"} %`).join(" · ")}</span>
                    )}
                  </td>
                  <td className="px-2 py-1.5 font-mono text-xs">{a.ip || "—"}</td>
                  <td className="px-2 py-1.5 font-mono text-xs">{a.mac || "—"}</td>
                  <td className="px-2 py-1.5 text-xs">
                    {[snmp.fabricant, snmp.modele].filter(Boolean).join(" ") || "—"}
                    {snmp.numero_serie && <span className="block font-mono text-[11px] text-slate-500">S/N {snmp.numero_serie}</span>}
                  </td>
                  <td className="px-2 py-1.5 text-xs">{a.client_libelle || a.client_code}<span className="block text-[11px] text-slate-500">par {a.vu_par}</span></td>
                  <td className="px-2 py-1.5 text-xs">{dateCourte(a.derniere_vue)}<span className="block text-[11px] text-slate-500">1re fois {dateCourte(a.premiere_vue)}</span></td>
                  <td className="px-2 py-1.5 text-xs" onClick={(e) => e.stopPropagation()}>
                    {onglet === "a_valider" ? (
                      <select value={categories[a.id] || a.categorie || "autre"} onChange={(e) => setCategories((c) => ({ ...c, [a.id]: e.target.value }))}
                        className="rounded border border-slate-300 px-1 py-0.5 text-xs">
                        {Object.entries(categoriesDispo).map(([cle, libelle]) => <option key={cle} value={cle}>{libelle}</option>)}
                      </select>
                    ) : (a.numero_inventaire ? <Link to="/admin/parc" className="text-sky-700 underline">{a.numero_inventaire}</Link> : "—")}
                  </td>
                  <td className="whitespace-nowrap px-2 py-1.5" onClick={(e) => e.stopPropagation()}>
                    {onglet === "a_valider" && (
                      <>
                        <button type="button" onClick={() => agir(a, "valider")} className="mr-1 rounded bg-emerald-600 px-2 py-0.5 text-xs font-semibold text-white">Valider</button>
                        <button type="button" onClick={() => agir(a, "ignorer")} className="rounded border border-slate-300 px-2 py-0.5 text-xs">Ignorer</button>
                      </>
                    )}
                    {(onglet === "ignore" || onglet === "valide") && (
                      <button type="button" onClick={() => agir(a, "remettre")} className="rounded border border-slate-300 px-2 py-0.5 text-xs">Remettre à valider</button>
                    )}
                  </td>
                </tr>
              );
            })}
            {donnees && appareils.length === 0 && (
              <tr><td colSpan={8} className="px-2 py-6 text-center text-sm text-slate-500">Aucun appareil dans cette liste.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* ---- Derniers balayages reçus ---- */}
      {(donnees?.balayages || []).length > 0 && (
        <div className="rounded-xl border border-slate-200 bg-white p-3">
          <p className="mb-1 text-xs font-semibold text-slate-700">Derniers balayages reçus</p>
          <table className="w-full text-xs">
            <thead className="text-left text-slate-500"><tr><th className="py-1">Date</th><th>Client</th><th>Machine</th><th>Réseau(x)</th><th>Appareils</th><th>Nouveaux</th><th>Durée</th></tr></thead>
            <tbody>
              {donnees.balayages.map((b) => (
                <tr key={b.id} className="border-t border-slate-100">
                  <td className="py-1">{dateCourte(b.recu_le)}</td><td>{b.client_libelle || b.client_code}</td><td>{b.machine}</td>
                  <td className="font-mono">{(b.sous_reseaux || []).join(", ") || "—"}</td><td>{b.total}</td><td>{b.nouveaux}</td>
                  <td>{b.duree_s != null ? `${b.duree_s} s` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
