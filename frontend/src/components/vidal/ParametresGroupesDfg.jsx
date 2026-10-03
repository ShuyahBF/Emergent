// components/vidal/ParametresGroupesDfg.jsx
// ---------------------------------------------
// Lot 56 (SAWALI) — repris de Ster (lecture seule hors gestionnaire).
// § demande utilisateur : "Rendre ces valeurs normales [du DFG]
// paramétrables avec possibilité de choisir un « Groupe » (paramétrable et
// éditable)." — édition, par le gestionnaire de l'établissement, des groupes de
// référence du DFG : libellé NEUTRE, valeur normale (ml/min/1,73 m²),
// actif, ordre, groupe par défaut ; et des seuils d'interprétation (% de la
// référence). Ces groupes servent UNIQUEMENT à l'appréciation affichée du
// DFG sur l'écran des données cliniques : ils ne modifient jamais le DFG
// calculé et ne sont jamais transmis à VIDAL. Contrôles identiques au
// serveur (PUT /vidal/groupes-dfg -> 422 détaillé).

import { useEffect, useState } from "react";
import { Plus, Save, Trash2, ArrowUp, ArrowDown, Loader2 } from "lucide-react";
import { apiClient as api } from "@/lib/api";
import { messageErreurApi, SEUILS_DFG_DEFAUT } from "@/lib/vidalReferentiels";
import { chargerGroupesDfg } from "./DonneesCliniquesPatient";

function identifiantLibre(groupes) {
  let n = groupes.length + 1;
  while (groupes.some((g) => g.id === `groupe_${n}`)) n += 1;
  return `groupe_${n}`;
}

export default function ParametresGroupesDfg() {
  const [groupes, setGroupes] = useState(null);
  const [seuils, setSeuils] = useState(SEUILS_DFG_DEFAUT);
  const [message, setMessage] = useState("");
  const [enErreur, setEnErreur] = useState(false);
  const [enCours, setEnCours] = useState(false);
  // (SAWALI) Lecture seule pour un praticien : seul le gestionnaire modifie.
  const [modifiable, setModifiable] = useState(false);

  useEffect(() => {
    api.get("/vidal/groupes-dfg")
      .then((r) => { setGroupes(r.data.groupes); setSeuils(r.data.seuils); setModifiable(!!r.data.modifiable); })
      .catch((err) => { setEnErreur(true); setMessage(messageErreurApi(err, "Chargement impossible.")); setGroupes([]); });
  }, []);

  function maj(index, patch) {
    setGroupes((prev) => prev.map((g, i) => (i === index ? { ...g, ...patch } : g)));
  }
  function definirParDefaut(index) {
    setGroupes((prev) => prev.map((g, i) => ({ ...g, par_defaut: i === index, actif: i === index ? true : g.actif })));
  }
  function deplacer(index, sens) {
    setGroupes((prev) => {
      const copie = [...prev];
      const cible = index + sens;
      if (cible < 0 || cible >= copie.length) return prev;
      [copie[index], copie[cible]] = [copie[cible], copie[index]];
      return copie.map((g, i) => ({ ...g, ordre: i + 1 }));
    });
  }

  async function enregistrer() {
    setEnCours(true); setMessage("");
    try {
      const payload = {
        groupes: groupes.map((g, i) => ({ ...g, ordre: i + 1, valeur_normale: Number(g.valeur_normale) })),
        seuils: { normal_pct: Number(seuils.normal_pct), leger_pct: Number(seuils.leger_pct) },
      };
      const r = await api.put("/vidal/groupes-dfg", payload);
      setGroupes(r.data.groupes); setSeuils(r.data.seuils);
      chargerGroupesDfg(true); // § rafraîchit la liste utilisée par l'écran des données cliniques
      setEnErreur(false); setMessage("Groupes de référence du DFG enregistrés.");
    } catch (err) {
      setEnErreur(true); setMessage(messageErreurApi(err, "Enregistrement impossible."));
    }
    setEnCours(false);
  }

  if (groupes === null) return <div className="carte" style={{ color: "var(--vidal-gris)" }}>Chargement…</div>;

  return (
    <div className="carte">
      <div style={{ fontWeight: 700, marginBottom: 4 }}>Groupes de référence du DFG</div>
      <div style={{ fontSize: 12.5, color: "var(--vidal-gris-fonce)", marginBottom: 12 }}>
        Le médecin choisit un groupe pour apprécier le débit de filtration glomérulaire par rapport à la valeur normale de ce groupe.
        Aide visuelle uniquement : le DFG calculé ne change pas et le groupe n'est jamais transmis à VIDAL.
      </div>
      {!modifiable && <div style={{ fontSize: 12, color: "var(--vidal-orange)", marginBottom: 8 }}>Lecture seule : seul le gestionnaire de l'établissement peut modifier ces groupes.</div>}
      <fieldset disabled={!modifiable} style={{ border: "none", padding: 0, margin: 0 }}>
      <table className="tableau-donnees" style={{ marginBottom: 10 }}>
        <thead>
          <tr><th>Ordre</th><th>Libellé</th><th>Valeur normale du DFG (ml/min/1,73 m²)</th><th>Actif</th><th>Par défaut</th><th /></tr>
        </thead>
        <tbody>
          {groupes.map((g, i) => (
            <tr key={g.id}>
              <td style={{ whiteSpace: "nowrap" }}>
                <button className="bouton-secondaire" style={{ padding: "2px 6px" }} onClick={() => deplacer(i, -1)} disabled={i === 0} title="Monter"><ArrowUp size={12} /></button>{" "}
                <button className="bouton-secondaire" style={{ padding: "2px 6px" }} onClick={() => deplacer(i, 1)} disabled={i === groupes.length - 1} title="Descendre"><ArrowDown size={12} /></button>
              </td>
              <td><input className="champ-saisie" value={g.libelle} onChange={(e) => maj(i, { libelle: e.target.value })} placeholder="Libellé du groupe" /></td>
              <td><input type="number" className="champ-saisie" min="1" max="200" step="0.1" value={g.valeur_normale} onChange={(e) => maj(i, { valeur_normale: e.target.value })} style={{ textAlign: "right" }} /></td>
              <td style={{ textAlign: "center" }}><input type="checkbox" checked={!!g.actif} disabled={g.par_defaut} onChange={(e) => maj(i, { actif: e.target.checked })} /></td>
              <td style={{ textAlign: "center" }}><input type="radio" name="groupe-dfg-defaut" checked={!!g.par_defaut} onChange={() => definirParDefaut(i)} /></td>
              <td>
                <button className="bouton-secondaire" style={{ padding: "2px 6px", color: "var(--vidal-rouge)" }} disabled={g.par_defaut || groupes.length === 1}
                  onClick={() => setGroupes(groupes.filter((_, j) => j !== i))} title="Supprimer"><Trash2 size={12} /></button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="bouton-secondaire" style={{ fontSize: 12.5, display: "inline-flex", alignItems: "center", gap: 5, marginBottom: 16 }}
        onClick={() => setGroupes([...groupes, { id: identifiantLibre(groupes), libelle: "", valeur_normale: 84, actif: true, ordre: groupes.length + 1, par_defaut: false }])}>
        <Plus size={12} /> Ajouter un groupe
      </button>

      <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>Seuils d'interprétation</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, marginBottom: 6 }}>
        <div>
          <label style={{ fontSize: 12, fontWeight: 600, display: "block", marginBottom: 3 }}>Normal à partir de (% de la référence)</label>
          <input type="number" className="champ-saisie" min="1" max="150" step="1" value={seuils.normal_pct} onChange={(e) => setSeuils({ ...seuils, normal_pct: e.target.value })} />
        </div>
        <div>
          <label style={{ fontSize: 12, fontWeight: 600, display: "block", marginBottom: 3 }}>Légèrement diminué à partir de (% de la référence)</label>
          <input type="number" className="champ-saisie" min="1" max="150" step="1" value={seuils.leger_pct} onChange={(e) => setSeuils({ ...seuils, leger_pct: e.target.value })} />
        </div>
      </div>
      <div style={{ fontSize: 11.5, color: "var(--vidal-gris)", marginBottom: 12 }}>
        En dessous du seuil « légèrement diminué » : diminué. Valeurs par défaut : 90 % et 60 %.
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <button className="bouton-primaire" onClick={enregistrer} disabled={enCours} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          {enCours ? <Loader2 size={14} className="lucide-tourne" /> : <Save size={14} />} Enregistrer
        </button>
        {message && <span style={{ fontSize: 12.5, color: enErreur ? "var(--vidal-rouge)" : "var(--vidal-vert)" }}>{message}</span>}
      </div>
      </fieldset>
    </div>
  );
}
