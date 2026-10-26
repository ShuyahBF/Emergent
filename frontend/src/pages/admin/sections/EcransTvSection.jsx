/*
 * Lot 289 — Paramètres → « 📺 Écrans TV » : appairer une Smart TV (code affiché par la télé), choisir le client et les
 * contenus, voir quand chaque écran a été vu pour la dernière fois, le modifier ou le révoquer.
 */
import React, { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Copy, Loader2, Tv, Trash2, Link2 } from "lucide-react";

const CONTENUS = [
  { cle: "messagerie", libelle: "Messagerie (fil des messages)" },
  { cle: "support", libelle: "Demandes de support ouvertes" },
  { cle: "hall", libelle: "Consultations du jour (hall : prochain patient, portes)" },
];

// Date lisible « 24/10/2026 14:05 » ou « jamais »
const dateLisible = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "jamais");

export default function EcransTvSection() {
  const [ecrans, setEcrans] = useState([]);
  const [clients, setClients] = useState([]);
  const [chargement, setChargement] = useState(true);
  const [code, setCode] = useState("");
  const [nom, setNom] = useState("");
  const [clientId, setClientId] = useState("");
  const [modules, setModules] = useState({ messagerie: true, support: true, hall: false });
  // Lot 300 : portes (bureaux) des médecins affichées dans le hall
  const [portes, setPortes] = useState([]);                  // [{medecin, porte, autre}]
  const [medecinsConnus, setMedecinsConnus] = useState([]);
  const [savingPortes, setSavingPortes] = useState(false);
  const [envoi, setEnvoi] = useState(false);
  const [erreurChargement, setErreurChargement] = useState("");
  const adresse = `${window.location.origin}/tv`;

  const charger = useCallback(async () => {
    setChargement(true);
    // Lot 302 : les trois lectures sont indépendantes. Si l'une échoue (ex. portes, clients),
    // la liste des écrans appairés reste affichée ; seul le bloc concerné signale l'erreur.
    const [e, c, p] = await Promise.allSettled([
      apiClient.get("/admin/tv/ecrans"),
      apiClient.get("/admin/clients"),
      apiClient.get("/admin/tv/portes"),
    ]);
    const echecs = [];
    if (e.status === "fulfilled") setEcrans(e.value.data?.ecrans || []); else echecs.push("écrans appairés");
    if (p.status === "fulfilled") {
      setPortes((p.value.data?.portes || []).map((l) => ({ ...l })));
      setMedecinsConnus(p.value.data?.medecins_connus || []);
    } else echecs.push("portes des médecins");
    if (c.status === "fulfilled") {
      // Un seul choix par société (plusieurs comptes d'une même société partagent les mêmes messages)
      const parSociete = new Map();
      (c.value.data || []).forEach((u) => { const nom = u.company || u.full_name || u.email; if (nom && !parSociete.has(nom.toLowerCase())) parSociete.set(nom.toLowerCase(), { id: u.id, nom }); });
      setClients(Array.from(parSociete.values()).sort((a, b) => String(a.nom).localeCompare(String(b.nom), "fr")));
    } else echecs.push("liste des clients");
    setErreurChargement(echecs.length ? `Chargement impossible : ${echecs.join(", ")}. Rechargez la page.` : "");
    setChargement(false);
  }, []);
  useEffect(() => { charger(); }, [charger]);

  const copier = async () => {
    try { await navigator.clipboard.writeText(adresse); toast.success("Adresse copiée"); } catch { toast.error("Copie impossible : recopiez l'adresse à la main"); }
  };

  const appairer = async () => {
    if (!code.trim() || !nom.trim() || !clientId) { toast.error("Code, nom de l'écran et client sont obligatoires"); return; }
    setEnvoi(true);
    try {
      await apiClient.post("/admin/tv/appairer", { code: code.trim(), nom: nom.trim(), client_id: clientId, modules });
      toast.success("Écran appairé : la télé démarre dans quelques secondes");
      setCode(""); setNom("");
      charger();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Appairage impossible");
    } finally {
      setEnvoi(false);
    }
  };

  // Lot 303 : photo du médecin — l'image choisie est réduite (160 px, JPEG) dans le navigateur avant d'être enregistrée
  const choisirPhoto = (i, fichier) => {
    if (!fichier) return;
    if (!/^image\//.test(fichier.type)) { toast.error("Choisissez un fichier image"); return; }
    const lecteur = new FileReader();
    lecteur.onload = () => {
      const img = new Image();
      img.onload = () => {
        const cote = Math.min(img.width, img.height), taille = 160;
        const toile = document.createElement("canvas");
        toile.width = taille; toile.height = taille;
        toile.getContext("2d").drawImage(img, (img.width - cote) / 2, (img.height - cote) / 2, cote, cote, 0, 0, taille, taille);
        majPorte(i, { photo: toile.toDataURL("image/jpeg", 0.8) });
      };
      img.onerror = () => toast.error("Image illisible");
      img.src = lecteur.result;
    };
    lecteur.readAsDataURL(fichier);
  };
  const majPorte = (i, patch) => setPortes((ls) => ls.map((l, k) => (k === i ? { ...l, ...patch } : l)));
  const enregistrerPortes = async () => {
    setSavingPortes(true);
    try {
      await apiClient.put("/admin/tv/portes", { portes: portes.filter((l) => l.medecin?.trim() && (l.porte?.trim() || l.profession?.trim() || l.photo)).map((l) => ({ medecin: l.medecin.trim(), porte: l.porte.trim(), profession: (l.profession || "").trim(), photo: l.photo || "" })) });
      toast.success("Portes enregistrées");
      charger();
    } catch (err) { toast.error(err?.response?.data?.detail || "Enregistrement impossible"); }
    finally { setSavingPortes(false); }
  };
  const medecinsProposes = Array.from(new Set([...medecinsConnus, ...portes.map((l) => l.medecin).filter(Boolean)])).sort();

  const changerContenu = async (ecran, cle, valeur) => {
    const nouveaux = { ...ecran.modules, [cle]: valeur };
    setEcrans((l) => l.map((e) => (e.id === ecran.id ? { ...e, modules: nouveaux } : e)));
    try {
      // Lot 303 : on affiche ce que le serveur a réellement enregistré, avec une confirmation visible
      const r = await apiClient.put(`/admin/tv/ecrans/${ecran.id}`, { modules: nouveaux });
      if (r.data?.modules) setEcrans((l) => l.map((e) => (e.id === ecran.id ? { ...e, modules: r.data.modules } : e)));
      toast.success("Contenus de l'écran enregistrés");
    } catch (err) { toast.error(err?.response?.data?.detail || "Modification impossible : le contenu n'a pas été enregistré"); charger(); }
  };

  const revoquer = async (ecran) => {
    if (!window.confirm(`Révoquer l'écran « ${ecran.nom} » ? La télé redemandera un code.`)) return;
    try { await apiClient.delete(`/admin/tv/ecrans/${ecran.id}`); toast.success("Écran révoqué"); charger(); } catch (err) { toast.error(err?.response?.data?.detail || "Révocation impossible"); }
  };

  return (
    <section className="bg-white rounded-2xl border border-slate-200 p-6 space-y-4" data-testid="ecrans-tv-section">
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-lg bg-indigo-100 flex items-center justify-center shrink-0"><Tv className="h-5 w-5 text-indigo-700" /></div>
        <div className="flex-1">
          <h2 className="text-base font-semibold text-slate-800">Écrans TV (Smart TV)</h2>
          <p className="text-sm text-slate-500 mt-0.5">
            Affichez sur une télé le fil de la messagerie et les demandes de support d'un client, sans aucun bouton. Les numéros de téléphone sont masqués.
          </p>
        </div>
      </div>

      <ol className="text-sm text-slate-600 list-decimal ml-5 space-y-1">
        <li>Sur la télé, ouvrez le navigateur internet et allez à l'adresse ci-dessous : un code à 6 caractères s'affiche.</li>
        <li>Saisissez ce code ici, donnez un nom à l'écran, choisissez le client et les contenus, puis « Appairer ».</li>
      </ol>
      <div className="flex gap-2 items-center boutons-distincts">
        <input readOnly value={adresse} className="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono bg-slate-50" data-testid="tv-adresse" />
        <button type="button" onClick={copier} className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-sky-600 hover:bg-sky-700 text-white text-sm"><Copy className="h-4 w-4" />Copier</button>
      </div>

      <div className="rounded-lg bg-slate-50 ring-1 ring-slate-200 p-3 space-y-3">
        <p className="text-sm font-medium text-slate-700">Appairer un nouvel écran</p>
        <div className="grid sm:grid-cols-3 gap-2">
          <label className="text-xs text-slate-600">Code affiché par la télé
            <input value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} maxLength={8} placeholder="K7MQ4X"
                   className="mt-1 w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono tracking-widest" data-testid="tv-code-saisi" />
          </label>
          <label className="text-xs text-slate-600">Nom de l'écran
            <input value={nom} onChange={(e) => setNom(e.target.value)} maxLength={60} placeholder="Hall d'accueil"
                   className="mt-1 w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" data-testid="tv-nom-saisi" />
          </label>
          <label className="text-xs text-slate-600">Client
            <select value={clientId} onChange={(e) => setClientId(e.target.value)} className="mt-1 w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" data-testid="tv-client-saisi">
              <option value="">— Choisir —</option>
              {clients.map((c) => <option key={c.id} value={c.id}>{c.nom}</option>)}
            </select>
          </label>
        </div>
        <div className="flex flex-wrap gap-4">
          {CONTENUS.map((c) => (
            <label key={c.cle} className="flex items-center gap-2 text-sm text-slate-700">
              <input type="checkbox" checked={Boolean(modules[c.cle])} onChange={(e) => setModules((m) => ({ ...m, [c.cle]: e.target.checked }))} />{c.libelle}
            </label>
          ))}
        </div>
        <button type="button" onClick={appairer} disabled={envoi}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm disabled:opacity-50" data-testid="tv-appairer">
          {envoi ? <Loader2 className="h-4 w-4 animate-spin" /> : <Link2 className="h-4 w-4" />}Appairer
        </button>
      </div>

      <div>
        <p className="text-sm font-medium text-slate-700 mb-2">Écrans appairés</p>
        {erreurChargement && (
          <div className="mb-2 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 flex items-center justify-between gap-2">
            <span>{erreurChargement}</span>
            <button type="button" onClick={charger} className="underline">Réessayer</button>
          </div>
        )}
        {chargement ? (
          <div className="flex items-center gap-2 text-slate-500 text-sm"><Loader2 className="h-4 w-4 animate-spin" />Chargement…</div>
        ) : ecrans.length === 0 ? (
          <p className="text-sm text-slate-500">Aucun écran appairé.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="tv-liste">
              <thead><tr className="text-left text-xs text-slate-500"><th className="py-1 pr-3">Écran</th><th className="pr-3">Code d'appairage</th><th className="pr-3">Client</th><th className="pr-3">Contenus</th><th className="pr-3">Vu pour la dernière fois</th><th /></tr></thead>
              <tbody>
                {ecrans.map((e) => (
                  <tr key={e.id} className="border-t border-slate-100">
                    <td className="py-2 pr-3 font-medium">{e.nom}</td>
                    <td className="pr-3 font-mono tracking-widest text-xs" title="Code saisi lors de l'appairage">{e.code || <span className="text-slate-400" title="Écran appairé avant le lot 303 : code non conservé">—</span>}</td>
                    <td className="pr-3">{e.client_nom || e.client_id}</td>
                    <td className="pr-3">
                      <div className="flex flex-wrap gap-3">
                        {CONTENUS.map((c) => (
                          <label key={c.cle} className="flex items-center gap-1 text-xs">
                            <input type="checkbox" checked={Boolean(e.modules?.[c.cle])} onChange={(ev) => changerContenu(e, c.cle, ev.target.checked)} />{{ messagerie: "Messagerie", support: "Support", hall: "Hall" }[c.cle]}
                          </label>
                        ))}
                      </div>
                    </td>
                    <td className="pr-3 text-xs text-slate-600">{dateLisible(e.vu_le)}</td>
                    <td className="text-right"><button type="button" onClick={() => revoquer(e)} title="Révoquer cet écran" className="p-1.5 rounded-lg text-rose-600 hover:bg-rose-50"><Trash2 className="h-4 w-4" /></button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {/* Lot 300 — porte (bureau) de chaque médecin, affichée avec le prochain patient dans le hall */}
      <div className="rounded-lg bg-slate-50 ring-1 ring-slate-200 p-3 space-y-2" data-testid="tv-portes">
        <p className="text-sm font-medium text-slate-700">Portes des médecins (affichage du hall)</p>
        <p className="text-xs text-slate-500">Le hall affiche « N° 12 → Bureau 3 » : le numéro d'ordre (jamais le nom du patient) et la porte du médecin. Les données viennent du Planning des médecins.</p>
        {portes.map((l, i) => (
          <div key={i} className="grid sm:grid-cols-[1fr_12rem_auto] gap-2" data-testid="tv-porte-ligne">
            {l.autre || (l.medecin && !medecinsProposes.includes(l.medecin)) ? (
              <input value={l.medecin} onChange={(e) => majPorte(i, { medecin: e.target.value })} placeholder="Nom du médecin" className="px-3 py-2 border border-slate-300 rounded-lg text-sm" />
            ) : (
              <select value={l.medecin} onChange={(e) => (e.target.value === "__autre__" ? majPorte(i, { autre: true, medecin: "" }) : majPorte(i, { medecin: e.target.value }))}
                      className="px-3 py-2 border border-slate-300 rounded-lg text-sm">
                <option value="">— Médecin —</option>
                {medecinsProposes.map((m) => <option key={m} value={m}>{m}</option>)}
                <option value="__autre__">Autre…</option>
              </select>
            )}
            <input value={l.porte} onChange={(e) => majPorte(i, { porte: e.target.value })} maxLength={30} placeholder="Bureau 3" className="px-3 py-2 border border-slate-300 rounded-lg text-sm" />
            <button type="button" onClick={() => setPortes((ls) => ls.filter((_, k) => k !== i))} title="Retirer" className="p-2 rounded-lg text-rose-600 hover:bg-rose-50"><Trash2 className="h-4 w-4" /></button>
            {/* Lot 303 : profession et photo du médecin, affichées dans le hall */}
            <div className="sm:col-span-3 flex flex-wrap items-center gap-2 -mt-1 mb-1">
              {l.photo
                ? <img src={l.photo} alt="" className="h-10 w-10 rounded-full object-cover ring-1 ring-slate-300" />
                : <span className="h-10 w-10 rounded-full bg-slate-200 text-slate-400 text-xs flex items-center justify-center">photo</span>}
              <label className="text-xs px-2 py-1 rounded-lg bg-white border border-slate-300 hover:bg-slate-50 cursor-pointer">
                {l.photo ? "Changer la photo" : "Charger la photo"}
                <input type="file" accept="image/*" className="hidden" onChange={(e) => { choisirPhoto(i, e.target.files?.[0]); e.target.value = ""; }} />
              </label>
              {l.photo && <button type="button" onClick={() => majPorte(i, { photo: "" })} className="text-xs text-rose-600 hover:underline">Retirer la photo</button>}
              <input value={l.profession || ""} onChange={(e) => majPorte(i, { profession: e.target.value })} maxLength={60} placeholder="Profession (ex. Médecin généraliste)"
                     className="flex-1 min-w-[12rem] px-3 py-1.5 border border-slate-300 rounded-lg text-sm" data-testid="tv-porte-profession" />
            </div>
          </div>
        ))}
        <div className="flex gap-2 boutons-distincts">
          <button type="button" onClick={() => setPortes((ls) => [...ls, { medecin: "", porte: "" }])} className="px-3 py-1.5 rounded-lg bg-white border border-slate-300 hover:bg-slate-50 text-sm text-slate-700" data-testid="tv-porte-ajouter">+ Ajouter un médecin</button>
          <button type="button" onClick={enregistrerPortes} disabled={savingPortes} className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm disabled:opacity-50" data-testid="tv-portes-enregistrer">
            {savingPortes ? "Enregistrement…" : "Enregistrer les portes"}
          </button>
        </div>
      </div>
      <p className="text-[11px] text-slate-500">
        Compatible avec le navigateur d'une télé LG webOS (ou tout navigateur moderne). L'écran se rafraîchit toutes les 8 secondes ; si la liaison est perdue, il garde le dernier contenu et le signale en haut.
      </p>
    </section>
  );
}
