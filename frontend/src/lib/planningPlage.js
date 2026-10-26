// Lot 325 — tri d'un jour du Planning (fonction pure, testée)
/** Liste d'un jour : RDV classés par heure, puis les patients sans RDV par numéro d'ordre. */
export function trierJour(items) {
  const rdv = (items || []).filter((a) => a.is_rdv !== 0 && a.start_at).sort((x, y) => new Date(x.start_at) - new Date(y.start_at));
  const sans = (items || []).filter((a) => a.is_rdv === 0).sort((x, y) => (Number(x.numero_ordre) || 0) - (Number(y.numero_ordre) || 0));
  return [...rdv, ...sans];
}
