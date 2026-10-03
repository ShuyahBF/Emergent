// components/vidal/ValidationVidal.jsx
// ---------------------------------------
// Lot 56 (SAWALI) — repris de Ster, affiché dans « Paramètres VIDAL » de la
// page Sécurisation. Réglage du mode : gestionnaire de l'établissement ;
// patients fictifs : ceux du praticien connecté ; journal : ses appels
// (le gestionnaire voit ceux de tout l'établissement).
// § décision de l'utilisateur (validation VIDAL) :
//   - mode « Validation VIDAL » (activé par défaut ; désactivation avec
//     confirmation « DESACTIVER ») ;
//   - patients fictifs : créer / remettre à neuf (idempotent, 3 par profil
//     clinique) ou supprimer ;
//   - journal de validation : tableau filtrable (date, profil, type,
//     statut), détail de chaque appel (body et réponse formatés, copier),
//     observation manuelle, exports XLSX et HTML imprimable.

import { useEffect, useState } from "react";
import { FlaskConical, RefreshCw, Trash2, Download, Printer, Copy, X, Loader2 } from "lucide-react";
import { apiClient as api } from "@/lib/api";
import { chargerEtatValidation } from "./BandeauValidationVidal";
import { messageErreurApi } from "@/lib/vidalReferentiels";

/** Télécharge un fichier renvoyé par l'API (jeton d'authentification compris, via apiClient). */
async function telechargerFichier(chemin, nomFichier) {
  const r = await api.get(chemin, { responseType: "blob" });
  const url = window.URL.createObjectURL(r.data);
  const lien = document.createElement("a");
  lien.href = url;
  lien.download = nomFichier;
  document.body.appendChild(lien);
  lien.click();
  lien.remove();
  setTimeout(() => window.URL.revokeObjectURL(url), 1000);
}

/** Document HTML autonome (synthèse imprimable) affiché dans une fenêtre isolée (<iframe srcDoc>). */
function VisionneuseHtml({ document: doc, onFermer }) {
  const [cadre, setCadre] = useState(null);
  if (!doc) return null;
  return (
    <div role="dialog" aria-modal="true" onClick={onFermer}
      style={{ position: "fixed", inset: 0, background: "rgba(15,20,30,0.55)", zIndex: 2100, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}>
      <div className="carte" onClick={(e) => e.stopPropagation()} style={{ width: "min(1100px, 100%)", height: "min(90vh, 960px)", display: "flex", flexDirection: "column", padding: 0, overflow: "hidden" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 14px", borderBottom: "1px solid var(--vidal-bordure)" }}>
          <strong style={{ fontSize: 14 }}>{doc.titre}</strong>
          <span style={{ display: "flex", gap: 8 }}>
            <button className="bouton-secondaire" style={{ fontSize: 12.5 }} disabled={!doc.html} onClick={() => cadre?.contentWindow?.print()}><Printer size={12} /> Imprimer</button>
            <button className="bouton-secondaire" style={{ fontSize: 12.5 }} onClick={onFermer}><X size={12} /> Fermer</button>
          </span>
        </div>
        {doc.chargement ? (
          <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 6, color: "var(--vidal-gris)" }}><Loader2 size={14} className="lucide-tourne" /> Chargement…</div>
        ) : (
          <iframe ref={setCadre} title={doc.titre} srcDoc={doc.html} sandbox="allow-same-origin allow-modals" style={{ flex: 1, border: "none", width: "100%", background: "white" }} />
        )}
      </div>
    </div>
  );
}

/** Indente un XML pour la lecture (affichage seulement). */
function formaterXml(texte) {
  if (!texte || !texte.trim().startsWith("<")) return texte || "";
  let niveau = 0;
  return texte.replace(/>\s*</g, ">\n<").split("\n").map((ligne) => {
    if (/^<\//.test(ligne)) niveau = Math.max(niveau - 1, 0);
    const resultat = "  ".repeat(niveau) + ligne;
    if (/^<[^!?/][^>]*[^/]>$/.test(ligne) && !/<\/[^>]+>$/.test(ligne)) niveau += 1;
    return resultat;
  }).join("\n");
}

function BlocCode({ titre, texte }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 3 }}>
        <span style={{ fontSize: 12, fontWeight: 600 }}>{titre}</span>
        <button className="bouton-secondaire" style={{ fontSize: 11, padding: "2px 8px", display: "inline-flex", alignItems: "center", gap: 4 }}
          onClick={() => navigator.clipboard?.writeText(texte || "")}><Copy size={11} /> Copier</button>
      </div>
      <pre style={{ fontSize: 11, background: "var(--vidal-gris-clair)", borderRadius: 8, padding: 10, maxHeight: 260, overflow: "auto", whiteSpace: "pre-wrap", wordBreak: "break-all", margin: 0 }}>
        {formaterXml(texte) || "—"}
      </pre>
    </div>
  );
}

/** `onChangement` (facultatif) : prévient la page quand le mode ou les patients fictifs changent. */
export default function ValidationVidal({ onChangement }) {
  const [etat, setEtat] = useState(null);
  const [patients, setPatients] = useState([]);
  const [message, setMessage] = useState("");
  const [enCours, setEnCours] = useState(false);
  const [journal, setJournal] = useState({ entrees: [], profils: [], types: [] });
  const [filtres, setFiltres] = useState({ depuis: "", jusqua: "", profil: "", type_appel: "", statut: "" });
  const [detail, setDetail] = useState(null);
  const [observation, setObservation] = useState("");
  const [rapportHtml, setRapportHtml] = useState(null);

  const paramsFiltres = () => Object.fromEntries(Object.entries(filtres).filter(([, v]) => v));

  async function charger() {
    try {
      const [e, p, j] = await Promise.all([
        api.get("/vidal/validation/etat"), api.get("/vidal/validation/patients-fictifs"),
        api.get("/vidal/validation/journal", { params: paramsFiltres() }),
      ]);
      setEtat(e.data); setPatients(p.data.patients); setJournal(j.data);
    } catch (err) {
      setMessage(messageErreurApi(err, "Chargement impossible."));
    }
  }
  useEffect(() => { charger(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function basculerMode() {
    const activer = !etat?.mode_validation;
    let confirmation = null;
    if (!activer) {
      confirmation = window.prompt("Désactiver le mode validation VIDAL permet d'envoyer de VRAIS patients à VIDAL.\nSaisissez DESACTIVER pour confirmer :");
      if (confirmation !== "DESACTIVER") return;
    }
    try {
      await api.put("/vidal/validation/mode", { mode_validation: activer, confirmation });
      chargerEtatValidation(true);
      setMessage(activer ? "Mode validation VIDAL activé." : "Mode validation VIDAL désactivé.");
      charger();
      onChangement?.();
    } catch (err) {
      setMessage(messageErreurApi(err, "Changement impossible."));
    }
  }

  async function genererFictifs() {
    setEnCours(true);
    try {
      const r = await api.post("/vidal/validation/patients-fictifs");
      const d = r.data;
      setMessage(`Patients fictifs : ${d.crees} créé(s), ${d.remis_a_neuf} remis à neuf, ${d.versions_creees} version(s) d'historique, ${d.ordonnances_fictives} ordonnance(s) antérieure(s) fictive(s). `
        + `Références VIDAL (recherches réelles) : ${d.references_trouvees} trouvée(s), ${d.references_a_choisir} à choisir, ${d.references_a_rechercher} à rechercher pendant la recette`
        + (d.vidal_interroge ? "." : ` — VIDAL non interrogé : ${d.message_vidal}.`));
      charger();
      onChangement?.();
    } catch (err) {
      setMessage(messageErreurApi(err, "Génération impossible."));
    }
    setEnCours(false);
  }

  async function supprimerFictifs() {
    if (!window.confirm("Supprimer tous vos patients fictifs de validation, avec leurs sécurisations et leur historique clinique ? (Le journal de validation est conservé.)")) return;
    try {
      const r = await api.delete("/vidal/validation/patients-fictifs");
      setMessage(`${r.data.patients_supprimes} patient(s) fictif(s) supprimé(s).`);
      charger();
      onChangement?.();
    } catch (err) {
      setMessage(messageErreurApi(err, "Suppression impossible."));
    }
  }

  async function ouvrirDetail(numero) {
    try {
      const r = await api.get(`/vidal/validation/journal/${numero}`);
      setDetail(r.data); setObservation(r.data.observation_manuelle || "");
    } catch (err) {
      setMessage(messageErreurApi(err, "Détail indisponible."));
    }
  }

  async function enregistrerObservation() {
    await api.patch(`/vidal/validation/journal/${detail.numero}`, { observation_manuelle: observation });
    setDetail({ ...detail, observation_manuelle: observation });
    charger();
  }

  async function ouvrirSynthese() {
    setRapportHtml({ titre: "Journal de validation VIDAL", chargement: true });
    try {
      const r = await api.get("/vidal/validation/journal/export.html", { params: paramsFiltres(), responseType: "text" });
      setRapportHtml({ titre: "Journal de validation VIDAL", html: r.data });
    } catch (err) {
      setRapportHtml(null); setMessage(messageErreurApi(err, "Synthèse indisponible."));
    }
  }

  const exportXlsx = async () => {
    const query = new URLSearchParams(paramsFiltres()).toString();
    try {
      await telechargerFichier(`/vidal/validation/journal/export.xlsx${query ? `?${query}` : ""}`, `journal_validation_vidal_${new Date().toISOString().slice(0, 10)}.xlsx`);
    } catch (err) {
      setMessage(messageErreurApi(err, "Export impossible."));
    }
  };

  return (
    <div className="carte" style={{ marginBottom: 16 }}>
      <div style={{ fontWeight: 700, marginBottom: 6, display: "flex", alignItems: "center", gap: 6 }}><FlaskConical size={16} /> Validation VIDAL</div>

      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 12, fontSize: 13 }}>
        <span>Mode validation : <strong style={{ color: etat?.mode_validation ? "var(--vidal-orange)" : "var(--vidal-gris-fonce)" }}>{etat?.mode_validation ? "ACTIVÉ — patients fictifs uniquement, appels réels (production)" : "désactivé"}</strong></span>
        {etat?.gestionnaire
          ? <button className="bouton-secondaire" style={{ fontSize: 12 }} onClick={basculerMode}>{etat?.mode_validation ? "Désactiver…" : "Activer"}</button>
          : <span style={{ fontSize: 11.5, color: "var(--vidal-gris)" }}>(réglé par le gestionnaire de l'établissement)</span>}
        {etat && !etat.identifiants_production_configures && <span style={{ color: "var(--vidal-rouge)", fontSize: 12 }}>Identifiants VIDAL de production non configurés (AdminSettings → VIDAL).</span>}
        {etat?.url_production && <span style={{ fontSize: 11.5, color: "var(--vidal-gris)" }}>URL : {etat.url_production}</span>}
      </div>

      <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>Patients fictifs ({patients.length})</div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
        <button className="bouton-primaire" onClick={genererFictifs} disabled={enCours} style={{ fontSize: 12.5, display: "inline-flex", alignItems: "center", gap: 6 }}>
          {enCours ? <Loader2 size={13} className="lucide-tourne" /> : <RefreshCw size={13} />} Créer / remettre à neuf les patients fictifs de validation
        </button>
        <button className="bouton-secondaire" onClick={supprimerFictifs} disabled={!patients.length} style={{ fontSize: 12.5, display: "inline-flex", alignItems: "center", gap: 6, color: "var(--vidal-rouge)" }}>
          <Trash2 size={13} /> Supprimer les patients fictifs
        </button>
      </div>
      {patients.length > 0 && (
        <details style={{ marginBottom: 12, fontSize: 12.5 }}>
          <summary style={{ cursor: "pointer" }}>Voir la liste (3 patients par profil clinique)</summary>
          <table className="tableau-donnees" style={{ fontSize: 12, marginTop: 6 }}>
            <thead><tr><th>Code</th><th>Patient</th><th>Profil</th><th>Prescriptions de test (produit VIDAL)</th><th>Références à résoudre</th></tr></thead>
            <tbody>
              {patients.map((p) => (
                <tr key={p.id}><td>{p.code_fictif}</td><td>{p.name}</td><td>{p.profil_fictif}</td>
                  <td>{(p.prescriptions_test_validation || []).map((t) => `${t.recherche} : ${t.resolution?.statut === "trouve" ? t.resolution.reference.label : t.resolution?.statut === "a_choisir" ? "à choisir" : "à rechercher"}`).join(" ; ")}</td>
                  <td>{(p.references_a_resoudre || []).map((r) => `${r.recherche} (${r.statut === "a_choisir" ? "à choisir" : "à rechercher"})`).join(" ; ") || "—"}</td></tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>Journal de validation ({journal.entrees.length} appel{journal.entrees.length > 1 ? "s" : ""})</div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end", marginBottom: 8, fontSize: 12 }}>
        <label>Depuis<br /><input type="date" className="champ-saisie" style={{ width: 150 }} value={filtres.depuis} onChange={(e) => setFiltres({ ...filtres, depuis: e.target.value })} /></label>
        <label>Jusqu'à<br /><input type="date" className="champ-saisie" style={{ width: 150 }} value={filtres.jusqua} onChange={(e) => setFiltres({ ...filtres, jusqua: e.target.value })} /></label>
        <label>Profil<br />
          <select className="champ-saisie" style={{ width: 220 }} value={filtres.profil} onChange={(e) => setFiltres({ ...filtres, profil: e.target.value })}>
            <option value="">Tous</option>{journal.profils.map((p) => <option key={p}>{p}</option>)}
          </select>
        </label>
        <label>Type<br />
          <select className="champ-saisie" style={{ width: 220 }} value={filtres.type_appel} onChange={(e) => setFiltres({ ...filtres, type_appel: e.target.value })}>
            <option value="">Tous</option>{journal.types.map((t) => <option key={t}>{t}</option>)}
          </select>
        </label>
        <label>Statut<br />
          <select className="champ-saisie" style={{ width: 130 }} value={filtres.statut} onChange={(e) => setFiltres({ ...filtres, statut: e.target.value })}>
            <option value="">Tous</option><option value="succes">Succès</option><option value="erreur">Erreur</option>
          </select>
        </label>
        <button className="bouton-secondaire" onClick={charger} style={{ fontSize: 12 }}>Filtrer</button>
        <button className="bouton-secondaire" onClick={exportXlsx} style={{ fontSize: 12, display: "inline-flex", alignItems: "center", gap: 4 }}><Download size={12} /> Export XLSX</button>
        <button className="bouton-secondaire" onClick={ouvrirSynthese} style={{ fontSize: 12, display: "inline-flex", alignItems: "center", gap: 4 }}><Printer size={12} /> Synthèse imprimable</button>
      </div>
      <div style={{ overflowX: "auto", maxHeight: 420, overflowY: "auto" }}>
        <table className="tableau-donnees" style={{ fontSize: 12 }}>
          <thead><tr><th>N°</th><th>Date/heure (Ouagadougou)</th><th>Type</th><th>Requête (identifiants masqués)</th><th>Statut</th><th>Délai (ms)</th><th>Patient / profil</th><th>Observations</th><th /></tr></thead>
          <tbody>
            {journal.entrees.length === 0 && <tr><td colSpan={9} style={{ color: "var(--vidal-gris)", textAlign: "center" }}>Aucun appel journalisé.</td></tr>}
            {journal.entrees.map((e) => (
              <tr key={e.numero}>
                <td className="chiffre">{e.numero}</td>
                <td style={{ whiteSpace: "nowrap" }}>{e.date_locale}</td>
                <td>{e.type_appel}</td>
                <td style={{ fontFamily: "monospace", fontSize: 11, wordBreak: "break-all", maxWidth: 320 }}>{e.methode} {e.url}</td>
                <td style={{ color: e.statut_http >= 200 && e.statut_http < 400 ? "var(--vidal-vert)" : "var(--vidal-rouge)", fontWeight: 600 }}>{e.statut_http || "—"}</td>
                <td className="chiffre">{e.duree_ms}</td>
                <td>{e.patient_libelle || "—"}<br /><small style={{ color: "var(--vidal-gris)" }}>{e.profil}</small></td>
                <td>{(e.observations_auto || []).join(" ; ")}{e.observation_manuelle ? <div style={{ fontWeight: 600 }}>{e.observation_manuelle}</div> : null}</td>
                <td><button className="bouton-secondaire" style={{ fontSize: 11, padding: "2px 8px" }} onClick={() => ouvrirDetail(e.numero)}>Détail</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {message && <div style={{ fontSize: 12.5, marginTop: 8, color: "var(--vidal-gris-fonce)" }}>{message}</div>}

      {detail && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(20,30,50,0.45)", zIndex: 2000, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }} onClick={() => setDetail(null)}>
          <div className="carte" style={{ width: 900, maxWidth: "100%", maxHeight: "90vh", overflowY: "auto" }} onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <div style={{ fontWeight: 700 }}>Appel n° {detail.numero} — {detail.type_appel}</div>
              <button onClick={() => setDetail(null)} style={{ border: "none", background: "none", cursor: "pointer", display: "flex" }}><X size={18} /></button>
            </div>
            <div style={{ fontSize: 12.5, marginBottom: 8, lineHeight: 1.6 }}>
              {detail.date_locale} (Ouagadougou) — statut <strong>{detail.statut_http}</strong> — délai <strong>{detail.duree_ms} ms</strong> — {detail.patient_libelle || "sans patient"} {detail.profil ? `(${detail.profil})` : ""}
              {detail.resume_gravites && <> — alertes : {Object.entries(detail.resume_gravites).map(([g, n]) => `${g} × ${n}`).join(", ") || "aucune"}</>}
              {detail.reponse_tronquee && <> — <span style={{ color: "var(--vidal-orange)" }}>réponse tronquée (taille {detail.taille_reponse} octets)</span></>}
            </div>
            <BlocCode titre="Requête (identifiants masqués)" texte={`${detail.methode} ${detail.url}\n${Object.entries(detail.entetes || {}).map(([k, v]) => `${k}: ${v}`).join("\n")}`} />
            <BlocCode titre="Body envoyé" texte={detail.corps} />
            <BlocCode titre="Valeur du retour" texte={detail.reponse} />
            <div style={{ fontSize: 12, marginBottom: 4 }}>Observations automatiques : {(detail.observations_auto || []).join(" ; ") || "—"}</div>
            <label style={{ fontSize: 12, fontWeight: 600, display: "block", marginBottom: 3 }}>Observations manuelles</label>
            <textarea className="champ-saisie" rows={2} value={observation} onChange={(e) => setObservation(e.target.value)} />
            <button className="bouton-primaire" style={{ marginTop: 6, fontSize: 12.5 }} onClick={enregistrerObservation}>Enregistrer l'observation</button>
          </div>
        </div>
      )}
      <VisionneuseHtml document={rapportHtml} onFermer={() => setRapportHtml(null)} />
    </div>
  );
}
