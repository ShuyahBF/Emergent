// components/vidal/HistoriqueDonneesCliniques.jsx
// ---------------------------------------------------
// Lot 56 (SAWALI) — repris de Ster ; ouvert depuis la page Sécurisation
// (bouton « Historique clinique » d'un patient enregistré).
//
// § demande utilisateur (validée) : historique des données cliniques du
// patient, en LECTURE SEULE :
//   - tableau des versions du profil clinique VIDAL (date, auteur, origine,
//     champs modifiés surlignés) — GET /vidal/patients/{id}/historique-clinique ;
//   - courbes d'évolution poids (kg), créatininémie (µmol/L), clairance
//     (ml/min), DFG (ml/min/1,73 m²) avec la ligne de référence du groupe
//     (recharts, déjà utilisé par la page Statistiques) ;
//   - périodes de grossesse et d'allaitement ;
//   - sécurisations VIDAL avec leur instantané (données réellement envoyées,
//     résumé des alertes), détail à la demande ;
//   - export PDF (moteur ReportLab du backend, ouvert dans un nouvel onglet).
// Le groupe de référence du DFG est une aide locale : il apparaît ici mais
// n'a jamais été transmis à VIDAL.

import { useEffect, useState } from "react";
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine } from "recharts";
import { FileText, Loader2, X } from "lucide-react";
import { apiClient as api } from "@/lib/api";
import { formatDateFr, ajouterJours, aujourdhuiISO, ALLAITEMENTS, META_SEVERITE, messageErreurApi } from "@/lib/vidalReferentiels";

const ORIGINES = { fiche: "Fiche patient", securisation: "Page Sécurisation", posologie: "Page Posologie", validation_vidal: "Patients fictifs (validation VIDAL)" };

// Colonnes du tableau des versions (clé de version -> libellé avec unité).
const COLONNES = [
  ["poids_kg", "Poids (kg)"], ["taille_cm", "Taille (cm)"], ["creatininemie_umol_l", "Créatininémie (µmol/L)"],
  ["clairance_ml_min", "Clairance (ml/min)"], ["dfg_ml_min_173", "DFG (ml/min/1,73 m²)"], ["groupe_reference_dfg", "Groupe DFG"],
  ["date_dernieres_regles", "DDR"], ["allaitement", "Allaitement"], ["insuffisance_hepatique", "Insuff. hépatique"],
  ["allergies", "Allergies"], ["molecules", "Molécules / excipients"], ["pathologies", "Pathologies (CIM-10)"],
];

const COURBES = [
  ["poids_kg", "Poids (kg)", "#1c4587"],
  ["creatininemie_umol_l", "Créatininémie (µmol/L)", "#9C1616"],
  ["clairance_ml_min", "Clairance de la créatinine (ml/min)", "#d97706"],
  ["dfg_ml_min_173", "DFG (ml/min/1,73 m²)", "#2fa84f"],
];

function texteValeur(cle, v, valeurs) {
  if (v == null || v === "" || (Array.isArray(v) && v.length === 0)) return "—";
  if (Array.isArray(v)) return v.map((e) => e.label || e.ref).join(", ");
  if (cle === "groupe_reference_dfg") return valeurs?.libelle_groupe_dfg || v;
  if (cle === "allaitement") return ALLAITEMENTS[v] || v;
  if (cle.startsWith("date")) return formatDateFr(v);
  return String(v);
}

/** Périodes de grossesse (DDR -> fin estimée ou version suivante) et d'allaitement, déduites des versions. */
function periodes(versions) {
  const resultat = [];
  versions.forEach((v, i) => {
    const suivante = versions[i + 1];
    const finVersion = suivante ? String(suivante.date).slice(0, 10) : null;
    const ddr = v.valeurs.date_dernieres_regles;
    if (ddr && (!versions[i - 1] || versions[i - 1].valeurs.date_dernieres_regles !== ddr)) {
      const terme = ajouterJours(ddr, 42 * 7);
      const fin = suivante && suivante.valeurs.date_dernieres_regles !== ddr ? finVersion : null;
      resultat.push({ type: "Grossesse", debut: ddr, fin: fin || (terme < aujourdhuiISO() ? terme : null) });
    }
    const allaite = v.valeurs.allaitement && v.valeurs.allaitement !== "NONE";
    const allaitaitAvant = versions[i - 1] && versions[i - 1].valeurs.allaitement && versions[i - 1].valeurs.allaitement !== "NONE";
    if (allaite && !allaitaitAvant) {
      const finIndex = versions.findIndex((x, j) => j > i && (!x.valeurs.allaitement || x.valeurs.allaitement === "NONE"));
      resultat.push({
        type: "Allaitement", debut: v.valeurs.date_debut_allaitement || String(v.date).slice(0, 10),
        fin: finIndex > 0 ? String(versions[finIndex].date).slice(0, 10) : null,
      });
    }
  });
  return resultat;
}

export default function HistoriqueDonneesCliniques({ patientId }) {
  const [donnees, setDonnees] = useState(null);
  const [erreur, setErreur] = useState("");
  const [detail, setDetail] = useState(null);
  const [pdfEnCours, setPdfEnCours] = useState(false);

  useEffect(() => {
    if (!patientId) return;
    setDonnees(null); setErreur("");
    api.get(`/vidal/patients/${patientId}/historique-clinique`)
      .then((r) => setDonnees(r.data))
      .catch((err) => setErreur(messageErreurApi(err, "Historique clinique indisponible.")));
  }, [patientId]);

  // § export PDF : même méthode que l'ordonnance sécurisée (blob ouvert dans un nouvel onglet).
  async function ouvrirPdf() {
    setPdfEnCours(true);
    try {
      const r = await api.get(`/vidal/patients/${patientId}/historique-clinique/pdf`, { responseType: "blob" });
      window.open(window.URL.createObjectURL(new Blob([r.data], { type: "application/pdf" })), "_blank");
    } catch (err) {
      setErreur(messageErreurApi(err, "Export PDF impossible."));
    }
    setPdfEnCours(false);
  }

  async function ouvrirDetail(s) {
    setDetail({ chargement: true });
    try {
      const r = await api.get(`/vidal/patients/${patientId}/historique-clinique/securisations/${s.numero_enreg}`);
      setDetail(r.data);
    } catch (err) {
      setDetail({ erreur: messageErreurApi(err, "Détail indisponible.") });
    }
  }

  if (erreur) return <div style={{ color: "var(--vidal-rouge)", fontSize: 13 }}>{erreur}</div>;
  if (!donnees) return <div style={{ color: "var(--vidal-gris)", fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}><Loader2 size={13} className="lucide-tourne" /> Chargement…</div>;

  const versions = donnees.versions || [];
  const securisations = donnees.securisations || [];
  const points = versions.map((v) => ({ date: formatDateFr(String(v.date).slice(0, 10)), ...v.valeurs }));
  const referenceDfg = versions.length ? versions[versions.length - 1].valeurs.valeur_normale_dfg_groupe : null;
  const liste = periodes(versions);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10, flexWrap: "wrap", gap: 8 }}>
        <div style={{ fontSize: 12.5, color: "var(--vidal-gris-fonce)" }}>{versions.length} version{versions.length > 1 ? "s" : ""} du profil clinique — {securisations.length} sécurisation{securisations.length > 1 ? "s" : ""}</div>
        <button className="bouton-secondaire" onClick={ouvrirPdf} disabled={pdfEnCours || (!versions.length && !securisations.length)} style={{ fontSize: 12.5, display: "inline-flex", alignItems: "center", gap: 6 }}>
          {pdfEnCours ? <Loader2 size={13} className="lucide-tourne" /> : <FileText size={13} />} Exporter en PDF
        </button>
      </div>

      {versions.length === 0 ? (
        <div style={{ fontSize: 13, color: "var(--vidal-gris)", marginBottom: 12 }}>Aucune donnée clinique enregistrée pour ce patient.</div>
      ) : (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 12, marginBottom: 14 }}>
            {COURBES.map(([cle, titre, couleur]) => (
              <div key={cle} style={{ border: "1px solid var(--vidal-bordure)", borderRadius: 10, padding: 8 }}>
                <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>{titre}</div>
                <ResponsiveContainer width="100%" height={150}>
                  <LineChart data={points.filter((p) => p[cle] != null)}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#eef2fa" />
                    <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                    <YAxis tick={{ fontSize: 10 }} width={36} domain={["auto", "auto"]} />
                    <Tooltip />
                    <Line type="monotone" dataKey={cle} name={titre} stroke={couleur} strokeWidth={2} dot={{ r: 3 }} />
                    {cle === "dfg_ml_min_173" && referenceDfg && (
                      <ReferenceLine y={referenceDfg} stroke="#2fa84f" strokeDasharray="4 3" label={{ value: `Référence ${referenceDfg} (ml/min/1,73 m²)`, fontSize: 10, position: "insideTopRight" }} />
                    )}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ))}
          </div>

          {liste.length > 0 && (
            <div style={{ marginBottom: 14, fontSize: 12.5 }}>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>Périodes de grossesse et d'allaitement</div>
              {liste.map((p, i) => (
                <div key={i}>{p.type} : du {formatDateFr(p.debut)} {p.fin ? `au ${formatDateFr(p.fin)}` : "— en cours"}</div>
              ))}
            </div>
          )}

          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>Versions du profil clinique (champs modifiés surlignés)</div>
          <div style={{ overflowX: "auto", marginBottom: 16 }}>
            <table className="tableau-donnees" style={{ fontSize: 12 }}>
              <thead>
                <tr><th>Version</th><th>Date</th><th>Auteur</th><th>Origine</th>{COLONNES.map(([cle, libelle]) => <th key={cle}>{libelle}</th>)}</tr>
              </thead>
              <tbody>
                {[...versions].reverse().map((v) => (
                  <tr key={v.numero_version}>
                    <td className="chiffre">{v.numero_version}</td>
                    <td style={{ whiteSpace: "nowrap" }}>{new Date(v.date).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}</td>
                    <td>{v.login}</td>
                    <td>{ORIGINES[v.origine] || v.origine}</td>
                    {COLONNES.map(([cle]) => {
                      const modifie = (v.champs_modifies || []).includes(cle);
                      return (
                        <td key={cle} style={modifie ? { background: "rgba(250,204,21,0.25)", fontWeight: 700 } : undefined} title={modifie ? "Modifié dans cette version" : undefined}>
                          {texteValeur(cle, v.valeurs[cle], v.valeurs)}
                          {cle === "date_dernieres_regles" && v.valeurs.semaines_amenorrhee != null && v.valeurs.date_dernieres_regles ? ` (${v.valeurs.semaines_amenorrhee} SA à cette date)` : ""}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>Sécurisations VIDAL</div>
      {securisations.length === 0 ? (
        <div style={{ fontSize: 13, color: "var(--vidal-gris)" }}>Aucune sécurisation enregistrée pour ce patient.</div>
      ) : (
        <table className="tableau-donnees" style={{ fontSize: 12 }}>
          <thead><tr><th>Date</th><th>Auteur</th><th>Référence</th><th>Médicaments</th><th>Alertes par gravité</th><th /></tr></thead>
          <tbody>
            {securisations.map((s) => (
              <tr key={s.numero_enreg}>
                <td style={{ whiteSpace: "nowrap" }}>{new Date(s.date_creation).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}</td>
                <td>{s.login}</td>
                <td>{s.ordonnance_reference || "—"}</td>
                <td>{(s.lignes_envoyees || []).map((l) => l.label || l.drugRef).join(", ")}</td>
                <td>
                  {Object.entries(s.resume_gravites || {}).map(([g, n]) => (
                    <span key={g} style={{ display: "inline-block", fontSize: 10.5, fontWeight: 700, padding: "1px 7px", borderRadius: 999, color: "white", background: (META_SEVERITE[g] || { couleur: "#94a3b8" }).couleur, marginRight: 4 }}>
                      {(META_SEVERITE[g] || { label: g }).label} : {n}
                    </span>
                  ))}
                  {!Object.keys(s.resume_gravites || {}).length && "Aucune"}
                </td>
                <td><button className="bouton-secondaire" style={{ fontSize: 11.5, padding: "3px 9px" }} onClick={() => ouvrirDetail(s)}>Détail</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {detail && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(20,30,50,0.45)", zIndex: 2000, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }} onClick={() => setDetail(null)}>
          <div className="carte" style={{ width: 720, maxWidth: "100%", maxHeight: "88vh", overflowY: "auto" }} onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <div style={{ fontWeight: 700 }}>Instantané de la sécurisation</div>
              <button onClick={() => setDetail(null)} style={{ border: "none", background: "none", cursor: "pointer", display: "flex" }}><X size={18} /></button>
            </div>
            {detail.chargement && <div style={{ color: "var(--vidal-gris)" }}>Chargement…</div>}
            {detail.erreur && <div style={{ color: "var(--vidal-rouge)" }}>{detail.erreur}</div>}
            {detail.patient_envoye && (
              <>
                <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 4 }}>Données patient réellement envoyées à VIDAL</div>
                <table className="tableau-donnees" style={{ fontSize: 12, marginBottom: 10 }}>
                  <tbody>
                    {Object.entries(detail.patient_envoye).map(([balise, valeur]) => (
                      <tr key={balise}><td style={{ fontFamily: "monospace" }}>&lt;{balise}&gt;</td><td>{valeur == null ? "nil" : Array.isArray(valeur) ? valeur.join(", ") : valeur}</td></tr>
                    ))}
                  </tbody>
                </table>
                <div style={{ fontSize: 12, color: "var(--vidal-gris-fonce)", marginBottom: 10 }}>
                  Groupe de référence du DFG (local, non transmis à VIDAL) : {detail.groupe_reference_dfg_local || "—"}
                </div>
                <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 4 }}>Lignes analysées</div>
                <ul style={{ fontSize: 12, marginTop: 0 }}>
                  {(detail.lignes_envoyees || []).map((l, i) => (
                    <li key={i}>{l.label || l.drugRef}{l.dose != null ? ` — dose ${l.dose}${l.unitLabel ? ` (${l.unitLabel})` : ""}` : ""}{l.duration ? ` — ${l.duration} ${l.durationType}` : ""}{l.groupType === "PREVIOUS_ORDER" ? " — traitement en cours" : ""}</li>
                  ))}
                </ul>
                <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 4 }}>Alertes ({detail.analyse?.alerts?.length || 0})</div>
                <ul style={{ fontSize: 12, marginTop: 0 }}>
                  {(detail.analyse?.alerts || []).map((a, i) => <li key={i}><b>{(META_SEVERITE[a.severity] || { label: a.severity }).label}</b> — {a.title}</li>)}
                </ul>
              </>
            )}
          </div>
        </div>
      )}

    </div>
  );
}
