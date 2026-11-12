// Lot 377 (remarques VIDAL 4 et 6) — éditeur du schéma de prise : plusieurs PALIERS (ex. « 2 par jour pendant 5 jours puis 1 par jour »),
// chacun avec ses prises par moment de la journée (matin / midi / soir / coucher / heure précise) et sa position par rapport au repas.
// Le schéma complet est conservé et imprimé ; à VIDAL on n'envoie que le palier à la dose journalière la plus élevée (voir lib/schemaPosologie.js).
import React from "react";
import { Plus, Trash2 } from "lucide-react";
import {
  MOMENTS, REPAS, nouvellePrise, nouveauPalier, doseJournaliere, palierMaximal, tendance, LIBELLE_TENDANCE,
  libelleSchema, validerSchema, champsLigneDepuisSchema,
} from "@/lib/schemaPosologie";

export default function SchemaPosologie({ schema = [], unite = "", onChange }) {
  // Toute modification remet à jour le schéma ET la dose par 24 h de la ligne (palier maximal).
  const maj = (nouveau) => onChange({ schema: nouveau, ...(champsLigneDepuisSchema(nouveau) || {}) });
  const majPalier = (i, patch) => maj(schema.map((p, j) => (j === i ? { ...p, ...patch } : p)));
  const majPrise = (i, k, patch) => majPalier(i, { prises: schema[i].prises.map((x, j) => (j === k ? { ...x, ...patch } : x)) });

  const erreurs = validerSchema(schema);
  const max = palierMaximal(schema);
  const t = tendance(schema);

  return (
    <div style={{ marginTop: 6 }} data-testid="schema-posologie">
      {schema.map((palier, i) => (
        <div key={i} style={{ border: "1px solid var(--vidal-bordure, #d4d4d8)", borderRadius: 8, padding: 8, marginBottom: 8 }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", fontSize: 12 }}>
            <strong>Palier {i + 1}</strong>
            <label>du jour <input type="number" min="1" className="champ-saisie" style={{ width: 64 }} value={(parseInt(palier.debut_jour || 0, 10)) + 1}
              onChange={(e) => majPalier(i, { debut_jour: Math.max(0, (parseInt(e.target.value, 10) || 1) - 1) })} /></label>
            <label>au jour <input type="number" min="1" className="champ-saisie" style={{ width: 64 }} placeholder="fin" value={palier.fin_jour === null || palier.fin_jour === undefined ? "" : parseInt(palier.fin_jour, 10) + 1}
              onChange={(e) => majPalier(i, { fin_jour: e.target.value === "" ? null : Math.max(0, (parseInt(e.target.value, 10) || 1) - 1) })} /></label>
            <span style={{ color: "var(--vidal-gris)" }}>= {doseJournaliere(palier)} {unite} par jour{max === palier && schema.length > 1 ? " (palier envoyé à VIDAL)" : ""}</span>
            <button type="button" title="Retirer ce palier" onClick={() => maj(schema.filter((_, j) => j !== i))} style={{ marginLeft: "auto", border: "none", background: "none", cursor: "pointer" }}><Trash2 size={14} /></button>
          </div>
          {palier.prises.map((prise, k) => (
            <div key={k} style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center", marginTop: 6 }}>
              <input type="number" min="0" step="0.5" className="champ-saisie" style={{ width: 70 }} value={prise.quantite} onChange={(e) => majPrise(i, k, { quantite: e.target.value })} aria-label="Quantité" />
              <span style={{ fontSize: 12 }}>{unite || "unité(s)"}</span>
              <select className="champ-saisie" value={prise.moment} onChange={(e) => majPrise(i, k, { moment: e.target.value })}>
                {MOMENTS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
              {prise.moment === "heure" && <input type="time" className="champ-saisie" value={prise.heure} onChange={(e) => majPrise(i, k, { heure: e.target.value })} />}
              <select className="champ-saisie" value={prise.repas} onChange={(e) => majPrise(i, k, { repas: e.target.value })}>
                {REPAS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
              <button type="button" title="Retirer cette prise" onClick={() => majPalier(i, { prises: palier.prises.filter((_, j) => j !== k) })} style={{ border: "none", background: "none", cursor: "pointer" }}><Trash2 size={13} /></button>
            </div>
          ))}
          <button type="button" onClick={() => majPalier(i, { prises: [...palier.prises, nouvellePrise()] })}
            style={{ marginTop: 6, border: "none", background: "none", cursor: "pointer", fontSize: 12, color: "var(--vidal-bleu)", display: "inline-flex", alignItems: "center", gap: 4 }}>
            <Plus size={12} /> Ajouter une prise
          </button>
        </div>
      ))}
      <button type="button" onClick={() => maj([...schema, nouveauPalier(schema.length ? (parseInt(schema[schema.length - 1].fin_jour ?? schema[schema.length - 1].debut_jour, 10) || 0) + 1 : 0)])}
        style={{ border: "none", background: "none", cursor: "pointer", fontSize: 12, fontWeight: 600, color: "var(--vidal-bleu)", display: "inline-flex", alignItems: "center", gap: 4 }}>
        <Plus size={12} /> Ajouter un palier
      </button>
      {erreurs.map((e) => <div key={e} style={{ color: "#b91c1c", fontSize: 12 }}>{e}</div>)}
      {schema.length > 0 && (
        <div style={{ fontSize: 12, marginTop: 6, whiteSpace: "pre-line" }} data-testid="schema-resume">
          {LIBELLE_TENDANCE[t] ? <strong>{LIBELLE_TENDANCE[t]}</strong> : null}{LIBELLE_TENDANCE[t] ? "\n" : ""}{libelleSchema(schema, unite)}
          {schema.length > 1 ? "\n(VIDAL reçoit la dose du palier le plus élevé ; le schéma complet figure sur l'ordonnance.)" : ""}
        </div>
      )}
    </div>
  );
}
