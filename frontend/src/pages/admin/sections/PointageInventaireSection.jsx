// ============================================================================
// PointageInventaireSection.jsx — Lot 496 : Paramètres → « 📱 Pointage D'Inventaire Par Téléphone ».
// Le responsable crée un inventaire (structure ayant une clé de suivi SAWALI, export JSON d'Aizenta, lieux de stockage rattachés
// chacun à la colonne « INV SV » ou « INV Mag »), affiche le QR code aux auxiliaires, suit le comptage en direct, puis exporte le
// JSON complété (format WinDev, réimportable dans Aizenta).
// Backend : /api/admin/pointage-inventaires (routes/pointage_telephone.py), administrateur seul.
// ============================================================================
import React, { useCallback, useEffect, useMemo, useState } from "react";
import QRCode from "qrcode";
import { AlertTriangle, Copy, Download, Eye, Lock, LockOpen, Plus, QrCode, RefreshCw, Trash2, Upload, X } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { useTri } from "@/lib/tri";
import ThTri from "@/components/ThTri";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

const nombre = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("fr-FR"));
const dateCourte = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");
const peremption = (p) => (p ? `${p.slice(4, 6)}/${p.slice(0, 4)}` : "");   // « 20270301 » → « 03/2027 »
const COLONNES = [{ v: "SV", l: "INV SV (salle de vente)" }, { v: "MG", l: "INV Mag (magasin)" }];

/** Bouton rond à pictogramme seul (règle du 27/11/2026) : info-bulle et libellé d'accessibilité. */
function Picto({ titre, Icone, onClick, couleur = "bg-sky-600 text-white", disabled = false, testid }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} title={titre} aria-label={titre} data-testid={testid}
            className={`inline-flex h-11 w-11 items-center justify-center rounded-full shadow-sm disabled:opacity-40 ${couleur}`}>
      <Icone className="h-5 w-5" aria-hidden="true" />
    </button>
  );
}

export default function PointageInventaireSection() {
  const [inventaires, setInventaires] = useState([]);
  const [creation, setCreation] = useState(false);
  const [ouvert, setOuvert] = useState(null);       // id de l'inventaire affiché dans la fenêtre de suivi

  const charger = useCallback(async (avecToast = false) => {
    const t = avecToast ? toast.loading("Actualisation en cours…") : null;
    try {
      const { data } = await apiClient.get("/admin/pointage-inventaires");
      setInventaires(data.inventaires || []);
      if (t) toast.success(`${data.inventaires.length} inventaire(s) relu(s).`, { id: t });
    } catch (e) {
      if (t) toast.error(e.response?.data?.detail || "Lecture impossible.", { id: t });
    }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  const { lignes, tri, basculer } = useTri(inventaires, {
    numero: (i) => i.numero, structure: (i) => i.structure?.libelle || i.structure?.code, code: (i) => i.code_inv,
    lignes: (i) => i.lignes_total, comptees: (i) => i.lignes_comptees, progression: (i) => i.progression,
    etat: (i) => i.etat, cree: (i) => i.cree_le,
  });

  return (
    <div className="space-y-3" data-testid="pointage-inventaire">
      <p className="text-sm text-slate-600">
        Les auxiliaires scannent le QR code avec leur téléphone, puis dictent « ligne, quantité, péremption, suivant ».
        Le JSON complété se réimporte dans Aizenta.
      </p>
      <div className="flex items-center gap-2">
        <Picto titre="Nouvel inventaire" Icone={Plus} onClick={() => setCreation(true)} couleur="bg-emerald-600 text-white" testid="pointage-nouveau" />
        <Picto titre="Actualiser la liste" Icone={RefreshCw} onClick={() => charger(true)} couleur="bg-slate-100 text-slate-700" />
      </div>
      <div className="overflow-x-auto rounded-xl border">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr>
              <ThTri cle="numero" tri={tri} onTri={basculer}>N°</ThTri>
              <ThTri cle="structure" tri={tri} onTri={basculer}>Structure</ThTri>
              <ThTri cle="code" tri={tri} onTri={basculer}>Inventaire</ThTri>
              <ThTri cle="lignes" tri={tri} onTri={basculer} droite>Lignes</ThTri>
              <ThTri cle="comptees" tri={tri} onTri={basculer} droite>Comptées</ThTri>
              <ThTri cle="progression" tri={tri} onTri={basculer} droite>Avancement</ThTri>
              <ThTri cle="etat" tri={tri} onTri={basculer}>État</ThTri>
              <ThTri cle="cree" tri={tri} onTri={basculer}>Créé le</ThTri>
              <th className="p-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {lignes.map((i) => (
              <tr key={i.id} className="border-t">
                <td className="p-2 font-semibold text-sky-700">{i.numero}</td>
                <td className="p-2">{i.structure?.libelle || i.structure?.code}</td>
                <td className="p-2">{i.code_inv || "—"}{i.base ? <span className="text-slate-500"> · {i.base}</span> : null}</td>
                <td className="p-2 text-right tabular-nums">{nombre(i.lignes_total)}</td>
                <td className="p-2 text-right tabular-nums text-emerald-700">{nombre(i.lignes_comptees)}</td>
                <td className="p-2 text-right tabular-nums">{i.progression} %</td>
                <td className="p-2">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${i.etat === "ouvert" ? "bg-emerald-100 text-emerald-800" : "bg-slate-200 text-slate-700"}`}>
                    {i.etat === "ouvert" ? "● En cours" : "■ Clôturé"}
                  </span>
                </td>
                <td className="p-2 whitespace-nowrap">{dateCourte(i.cree_le)}</td>
                <td className="p-2">
                  <button type="button" onClick={() => setOuvert(i.id)} title="Suivre / QR code / exporter" aria-label="Suivre, QR code et export"
                          className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-sky-100 text-sky-700"><Eye className="h-4 w-4" aria-hidden="true" /></button>
                </td>
              </tr>
            ))}
            {!lignes.length && <tr><td colSpan={9} className="p-4 text-center text-slate-500">Aucun inventaire : créez-en un avec le pictogramme +.</td></tr>}
          </tbody>
          {/* Règle 25 : totaux des colonnes de quantités sous le tableau */}
          <tfoot className="border-t-2 bg-slate-50 font-semibold">
            <tr>
              <td className="p-2" colSpan={3}>{lignes.length} inventaire(s)</td>
              <td className="p-2 text-right tabular-nums">{nombre(lignes.reduce((s, i) => s + (i.lignes_total || 0), 0))}</td>
              <td className="p-2 text-right tabular-nums">{nombre(lignes.reduce((s, i) => s + (i.lignes_comptees || 0), 0))}</td>
              <td colSpan={4} />
            </tr>
          </tfoot>
        </table>
      </div>
      {creation && <FenetreCreation onFermer={() => setCreation(false)} onCree={(inv) => { setCreation(false); charger(); setOuvert(inv.id); }} />}
      {ouvert && <FenetreSuivi ident={ouvert} onFermer={() => { setOuvert(null); charger(); }} />}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------------------
// Création : structure (liste déroulante), fichier JSON d'Aizenta, lieux de stockage
// ---------------------------------------------------------------------------------------------------------------------------
function FenetreCreation({ onFermer, onCree }) {
  const [structures, setStructures] = useState([]);
  const [structureId, setStructureId] = useState("");
  const [fichier, setFichier] = useState(null);      // {nom, export, lignes}
  const [lieux, setLieux] = useState([{ nom: "Salle de vente", colonne: "SV" }, { nom: "Magasin", colonne: "MG" }]);
  const [envoi, setEnvoi] = useState(false);

  useEffect(() => { apiClient.get("/admin/pointage-inventaires/structures").then(({ data }) => setStructures(data.structures || [])).catch(() => toast.error("Structures illisibles.")); }, []);

  const lireFichier = async (f) => {
    if (!f) return;
    try {
      const texte = (await f.text()).replace(/^﻿/, "");          // export WinDev : BOM éventuel
      const exp = JSON.parse(texte);
      const n = exp?.["REQ_DétailInventaire"]?.length;
      if (!n) throw new Error("tableau REQ_DétailInventaire absent");
      setFichier({ nom: f.name, export: exp, lignes: n });
    } catch (e) { toast.error(`Fichier refusé : ${e.message}`); setFichier(null); }
  };

  const creer = async () => {
    setEnvoi(true);
    const t = toast.loading("Création de l'inventaire en cours…");
    try {
      const { data } = await apiClient.post("/admin/pointage-inventaires", { structure_id: structureId, lieux, nom_fichier: fichier.nom, export: fichier.export });
      toast.success(`Inventaire ${data.numero} créé (${data.lignes_total} lignes).`, { id: t });
      onCree(data);
    } catch (e) { toast.error(e.response?.data?.detail || "Création impossible.", { id: t }); setEnvoi(false); }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onFermer()}>
      <DialogContent className="max-h-[85dvh] max-w-xl overflow-y-auto" data-testid="pointage-creation">
        <DialogHeader><DialogTitle>Nouvel inventaire par téléphone</DialogTitle></DialogHeader>
        <label className="block text-sm font-semibold">Structure (clé de suivi SAWALI)
          <select value={structureId} onChange={(e) => setStructureId(e.target.value)} className="mt-1 w-full rounded-lg border px-3 py-2">
            <option value="">— Choisir —</option>
            {structures.map((s) => <option key={s.id} value={s.id}>{s.libelle || s.code} ({s.code})</option>)}
          </select>
        </label>
        {!structures.length && <p className="text-xs text-orange-700">Aucune structure : créez d'abord sa clé (Plateformes → Loois → Synchro → Clés clients).</p>}

        <label className="mt-2 flex cursor-pointer items-center gap-3 rounded-xl border-2 border-dashed p-3 hover:bg-sky-50">
          <Upload className="h-6 w-6 text-sky-600" aria-hidden="true" />
          <span className="text-sm">{fichier ? <><b className="text-sky-700">{fichier.nom}</b> · {nombre(fichier.lignes)} lignes</> : "Export JSON d'Aizenta (InventaireSélectionné_…_INVxxx.json)"}</span>
          <input type="file" accept=".json,application/json" className="sr-only" onChange={(e) => lireFichier(e.target.files?.[0])} />
        </label>

        <p className="mt-2 text-sm font-semibold">Lieux de stockage et colonne Aizenta</p>
        <p className="text-xs text-slate-500">Aizenta n'a que deux colonnes de comptage : chaque lieu s'y additionne. Le détail par lieu reste visible ici.</p>
        <div className="space-y-2">
          {lieux.map((l, i) => (
            <div key={i} className="flex items-center gap-2">
              <input value={l.nom} maxLength={40} placeholder="Réservés" onChange={(e) => setLieux(lieux.map((x, j) => (j === i ? { ...x, nom: e.target.value } : x)))}
                     className="min-w-0 flex-1 rounded-lg border px-3 py-2" aria-label={`Nom du lieu ${i + 1}`} />
              <select value={l.colonne} onChange={(e) => setLieux(lieux.map((x, j) => (j === i ? { ...x, colonne: e.target.value } : x)))}
                      className="rounded-lg border px-2 py-2" aria-label={`Colonne Aizenta du lieu ${i + 1}`}>
                {COLONNES.map((c) => <option key={c.v} value={c.v}>{c.l}</option>)}
              </select>
              <button type="button" onClick={() => setLieux(lieux.filter((_, j) => j !== i))} disabled={lieux.length <= 1}
                      title="Retirer ce lieu" aria-label="Retirer ce lieu" className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-rose-100 text-rose-700 disabled:opacity-40">
                <Trash2 className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
          ))}
          {lieux.length < 8 && (
            <button type="button" onClick={() => setLieux([...lieux, { nom: "", colonne: "MG" }])} className="inline-flex items-center gap-1 text-sm font-semibold text-emerald-700">
              <Plus className="h-4 w-4" aria-hidden="true" />Ajouter un lieu
            </button>
          )}
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Picto titre="Fermer" Icone={X} onClick={onFermer} couleur="bg-slate-100 text-slate-700" />
          <Picto titre="Créer l'inventaire" Icone={Plus} onClick={creer} couleur="bg-emerald-600 text-white" testid="pointage-creer"
                 disabled={envoi || !structureId || !fichier || lieux.some((l) => !l.nom.trim())} />
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------------------------------------------------------
// Suivi : QR code, avancement par lieu et par auxiliaire, alertes, lignes ; export, clôture
// ---------------------------------------------------------------------------------------------------------------------------
function FenetreSuivi({ ident, onFermer }) {
  const [d, setD] = useState(null);
  const [qr, setQr] = useState("");
  const [onglet, setOnglet] = useState("suivi");
  const [filtre, setFiltre] = useState("non_comptees");
  const lien = d?.jeton ? `${window.location.origin}/pointage/${d.jeton}` : "";

  const charger = useCallback(async (avecToast = false) => {
    const t = avecToast ? toast.loading("Actualisation en cours…") : null;
    try {
      const { data } = await apiClient.get(`/admin/pointage-inventaires/${ident}`);
      setD(data);
      if (t) toast.success(`${data.lignes_comptees} ligne(s) comptée(s) sur ${data.lignes_total}, ${data.alertes.length} alerte(s).`, { id: t });
    } catch (e) { if (t) toast.error(e.response?.data?.detail || "Lecture impossible.", { id: t }); }
  }, [ident]);
  useEffect(() => { charger(); const x = setInterval(() => charger(), 15000); return () => clearInterval(x); }, [charger]);   // suivi en direct : relu toutes les 15 s
  useEffect(() => { if (lien) QRCode.toDataURL(lien, { errorCorrectionLevel: "M", width: 260, margin: 1 }).then(setQr); else setQr(""); }, [lien]);

  const action = async (chemin, message) => {
    const t = toast.loading("En cours…");
    try { await apiClient.post(`/admin/pointage-inventaires/${ident}/${chemin}`); toast.success(message, { id: t }); charger(); }
    catch (e) { toast.error(e.response?.data?.detail || "Action impossible.", { id: t }); }
  };
  const exporter = async () => {
    const t = toast.loading("Préparation du JSON complété…");
    try {
      const r = await apiClient.get(`/admin/pointage-inventaires/${ident}/export`, { responseType: "blob" });
      const nom = /filename="([^"]+)"/.exec(r.headers["content-disposition"] || "")?.[1] || "inventaire.pointe.json";
      const a = document.createElement("a"); a.href = URL.createObjectURL(r.data); a.download = nom; a.click(); URL.revokeObjectURL(a.href);
      toast.success(`${nom} téléchargé : à réimporter dans Aizenta.`, { id: t });
    } catch { toast.error("Export impossible.", { id: t }); }
  };

  const lignesFiltrees = useMemo(() => {
    const l = d?.lignes || [];
    if (filtre === "non_comptees") return l.filter((x) => x.compte === null);
    if (filtre === "comptees") return l.filter((x) => x.compte !== null);
    return l;
  }, [d, filtre]);
  const { lignes: triees, tri, basculer } = useTri(lignesFiltrees, {
    chrono: (x) => x.chrono, libelle: (x) => x.libelle, avant: (x) => x.avant, sv: (x) => x.sv, mg: (x) => x.mg,
    compte: (x) => x.compte, ecart: (x) => x.ecart, peremption: (x) => x.peremption, par: (x) => x.par.join(", "),
  });

  return (
    <Dialog open onOpenChange={(o) => !o && onFermer()}>
      <DialogContent className="max-h-[85dvh] max-w-xl overflow-y-auto" data-testid="pointage-suivi">
        <DialogHeader><DialogTitle>{d ? `${d.numero} · ${d.structure?.libelle || d.structure?.code} · ${d.code_inv || ""}` : "Patientez…"}</DialogTitle></DialogHeader>
        {d && (
          <>
            {/* Avancement */}
            <div>
              <div className="flex justify-between text-sm"><span><b className="text-emerald-700">{nombre(d.lignes_comptees)}</b> / {nombre(d.lignes_total)} lignes comptées</span><b>{d.progression} %</b></div>
              <div className="mt-1 h-3 rounded-full bg-slate-200"><div className="h-3 rounded-full bg-emerald-500" style={{ width: `${d.progression}%` }} /></div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Picto titre="Actualiser" Icone={RefreshCw} onClick={() => charger(true)} couleur="bg-slate-100 text-slate-700" />
              <Picto titre="Exporter le JSON complété (Aizenta)" Icone={Download} onClick={exporter} couleur="bg-emerald-600 text-white" testid="pointage-export" />
              {d.etat === "ouvert" ? <>
                <Picto titre="Nouveau QR code (l'ancien ne marche plus)" Icone={QrCode} onClick={() => action("jeton", "Nouveau QR code créé.")} couleur="bg-violet-100 text-violet-700" />
                <Picto titre="Clôturer l'inventaire" Icone={Lock} onClick={() => window.confirm("Clôturer ? Les téléphones ne pourront plus saisir.") && action("cloturer", "Inventaire clôturé.")} couleur="bg-rose-100 text-rose-700" />
              </> : <Picto titre="Rouvrir l'inventaire" Icone={LockOpen} onClick={() => action("rouvrir", "Inventaire rouvert : nouveau QR code.")} couleur="bg-amber-100 text-amber-800" />}
            </div>
            {/* Onglets */}
            <div className="flex gap-1 border-b text-sm" role="tablist">
              {[["suivi", "Suivi"], ["alertes", `Alertes (${d.alertes.length})`], ["lignes", "Lignes"]].map(([k, l]) => (
                <button key={k} type="button" role="tab" aria-selected={onglet === k} onClick={() => setOnglet(k)}
                        className={`px-3 py-2 font-semibold ${onglet === k ? "border-b-2 border-orange-500 text-orange-700" : "text-slate-500"}`}>{l}</button>
              ))}
            </div>
            {onglet === "suivi" && (
              <div className="space-y-3">
                {d.etat === "ouvert" && qr ? (
                  <div className="flex flex-col items-center gap-2 rounded-xl border bg-white p-3">
                    <img src={qr} alt="QR code du pointage" className="h-56 w-56" />
                    <div className="flex w-full items-center gap-2">
                      <code className="min-w-0 flex-1 truncate rounded bg-slate-100 px-2 py-1 text-xs">{lien}</code>
                      <button type="button" title="Copier le lien" aria-label="Copier le lien" onClick={() => navigator.clipboard?.writeText(lien).then(() => toast.success("Lien copié."))}
                              className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-sky-100 text-sky-700"><Copy className="h-4 w-4" aria-hidden="true" /></button>
                    </div>
                    <p className="text-xs text-slate-500">Valable jusqu'au {dateCourte(d.jeton_expire)}. À montrer aux auxiliaires : un scan avec le téléphone ouvre le pointage.</p>
                  </div>
                ) : <p className="rounded-lg bg-slate-100 p-3 text-sm">Inventaire clôturé : le QR code ne fonctionne plus.</p>}
                <TableauSimple titre="Par lieu" colonnes={["Lieu", "Colonne", "Lignes", "Saisies", "Quantité"]}
                               lignes={d.par_lieu.map((l) => [l.lieu, l.colonne === "SV" ? "INV SV" : "INV Mag", l.lignes, l.saisies, l.quantite])} nombres={[2, 3, 4]} />
                <TableauSimple titre="Par auxiliaire (prénom déclaré, non vérifiable)" colonnes={["Prénom", "Saisies", "Dernière"]}
                               lignes={d.par_auxiliaire.map((a) => [a.prenom, a.saisies, dateCourte(a.derniere)])} nombres={[1]} />
              </div>
            )}
            {onglet === "alertes" && (
              <ul className="space-y-1 text-sm">
                {d.alertes.map((a, i) => (
                  <li key={i} className={`flex gap-2 rounded-lg p-2 ${{ perime: "bg-red-50 text-red-800", ecart: "bg-orange-50 text-orange-800", doublon: "bg-amber-50 text-amber-800", proche: "bg-yellow-50 text-yellow-800" }[a.type]}`}>
                    <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" /><span><b className="text-sky-700">{a.chrono}</b> · {a.libelle} — {a.message}</span>
                  </li>
                ))}
                {!d.alertes.length && <li className="text-slate-500">Aucune alerte.</li>}
              </ul>
            )}
            {onglet === "lignes" && (
              <>
                <select value={filtre} onChange={(e) => setFiltre(e.target.value)} className="rounded-lg border px-2 py-1 text-sm" aria-label="Lignes affichées">
                  <option value="non_comptees">Lignes non comptées</option>
                  <option value="comptees">Lignes comptées</option>
                  <option value="toutes">Toutes les lignes</option>
                </select>
                <div className="overflow-x-auto rounded-lg border">
                  <table className="w-full text-xs">
                    <thead className="bg-slate-50"><tr>
                      <ThTri cle="chrono" tri={tri} onTri={basculer} droite>N°</ThTri>
                      <ThTri cle="libelle" tri={tri} onTri={basculer}>Produit</ThTri>
                      <ThTri cle="avant" tri={tri} onTri={basculer} droite>Avant</ThTri>
                      <ThTri cle="sv" tri={tri} onTri={basculer} droite>SV</ThTri>
                      <ThTri cle="mg" tri={tri} onTri={basculer} droite>Mag</ThTri>
                      <ThTri cle="ecart" tri={tri} onTri={basculer} droite>Écart</ThTri>
                      <ThTri cle="peremption" tri={tri} onTri={basculer}>Pérempt.</ThTri>
                      <ThTri cle="par" tri={tri} onTri={basculer}>Par</ThTri>
                    </tr></thead>
                    <tbody>
                      {triees.map((x) => (
                        <tr key={x.chrono} className="border-t">
                          <td className="p-1 text-right font-semibold text-sky-700 tabular-nums">{x.chrono}</td>
                          <td className="p-1">{x.libelle} <span className="text-slate-400">{x.mesure}</span></td>
                          <td className="p-1 text-right tabular-nums">{x.avant}</td>
                          <td className="p-1 text-right tabular-nums">{x.sv ?? ""}</td>
                          <td className="p-1 text-right tabular-nums">{x.mg ?? ""}</td>
                          <td className={`p-1 text-right tabular-nums font-semibold ${x.ecart > 0 ? "text-emerald-700" : x.ecart < 0 ? "text-red-700" : ""}`}>{x.ecart ?? ""}</td>
                          <td className="p-1 text-orange-700">{peremption(x.peremption)}</td>
                          <td className="p-1">{x.par.join(", ")}</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot className="border-t-2 bg-slate-50 font-semibold"><tr>
                      <td className="p-1" colSpan={2}>{triees.length} ligne(s)</td>
                      <td className="p-1 text-right tabular-nums">{nombre(triees.reduce((s, x) => s + x.avant, 0))}</td>
                      <td className="p-1 text-right tabular-nums">{nombre(triees.reduce((s, x) => s + (x.sv || 0), 0))}</td>
                      <td className="p-1 text-right tabular-nums">{nombre(triees.reduce((s, x) => s + (x.mg || 0), 0))}</td>
                      <td className="p-1 text-right tabular-nums">{nombre(triees.reduce((s, x) => s + (x.ecart || 0), 0))}</td>
                      <td colSpan={2} />
                    </tr></tfoot>
                  </table>
                </div>
              </>
            )}
          </>
        )}
        <div className="flex justify-end"><Picto titre="Fermer" Icone={X} onClick={onFermer} couleur="bg-slate-100 text-slate-700" /></div>
      </DialogContent>
    </Dialog>
  );
}

/** Petit tableau à colonnes triables, avec ligne de totaux sous les colonnes de nombres (règles 19 et 25). */
function TableauSimple({ titre, colonnes, lignes, nombres = [] }) {
  const acces = Object.fromEntries(colonnes.map((_, i) => [`c${i}`, (l) => l[i]]));
  const { lignes: triees, tri, basculer } = useTri(lignes, acces);
  return (
    <div>
      <p className="mb-1 text-sm font-semibold">{titre}</p>
      <table className="w-full rounded-lg border text-sm">
        <thead className="bg-slate-50"><tr>{colonnes.map((c, i) => <ThTri key={c} cle={`c${i}`} tri={tri} onTri={basculer} droite={nombres.includes(i)}>{c}</ThTri>)}</tr></thead>
        <tbody>{triees.map((l, k) => <tr key={k} className="border-t">{l.map((v, i) => <td key={i} className={`p-2 ${nombres.includes(i) ? "text-right tabular-nums" : ""} ${i === 0 ? "font-semibold text-sky-700" : ""}`}>{typeof v === "number" ? nombre(v) : v}</td>)}</tr>)}</tbody>
        <tfoot className="border-t-2 bg-slate-50 font-semibold"><tr>{colonnes.map((_, i) => (
          <td key={i} className={`p-2 ${nombres.includes(i) ? "text-right tabular-nums" : ""}`}>
            {i === 0 ? `${triees.length}` : nombres.includes(i) ? nombre(triees.reduce((s, l) => s + (Number(l[i]) || 0), 0)) : ""}
          </td>))}</tr></tfoot>
      </table>
    </div>
  );
}
