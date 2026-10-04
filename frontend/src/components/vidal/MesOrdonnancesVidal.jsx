// components/vidal/MesOrdonnancesVidal.jsx
// ------------------------------------------------
// Lot 57 — « Le médecin saura en retour si son ordonnance a pu être servie au
// patient » : liste des ordonnances émises par le médecin connecté, avec le
// retour des officines (servie, servie en partie, produit en rupture, en
// attente). Pastille « nouveau » tant que les retours n'ont pas été consultés.
// L'ordonnance peut être revue en aperçu intégré (A5, jamais un nouvel onglet).
import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, FileText, Loader2, RefreshCw, Store } from "lucide-react";
import { apiClient as api } from "@/lib/api";
import ApercuPdfIntegre from "./ApercuPdfIntegre";

// Couleur de l'état de l'ordonnance
const COULEURS = {
  servie: { fond: "#dcfce7", texte: "#166534" },
  partielle: { fond: "#fef3c7", texte: "#92400e" },
  rupture: { fond: "#fee2e2", texte: "#991b1b" },
  non_servie: { fond: "#e2e8f0", texte: "#334155" },
  en_attente: { fond: "#f1f5f9", texte: "#475569" },
};

function dateFr(valeur) {
  try { return new Date(valeur).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }); } catch { return String(valeur || ""); }
}

export default function MesOrdonnancesVidal({ cleRafraichissement = 0 }) {
  const [ouvert, setOuvert] = useState(false);
  const [donnees, setDonnees] = useState(null);
  const [chargement, setChargement] = useState(false);
  const [detail, setDetail] = useState(null);       // id de l'ordonnance dépliée
  const [apercu, setApercu] = useState(null);       // aperçu PDF intégré

  // Chargement (au montage pour la pastille, puis à chaque ouverture / nouvelle ordonnance)
  const charger = () => {
    setChargement(true);
    return api.get("/vidal/ordonnances").then((r) => setDonnees(r.data)).catch(() => {}).finally(() => setChargement(false));
  };
  useEffect(() => { charger(); }, [cleRafraichissement]); // eslint-disable-line react-hooks/exhaustive-deps

  // Ouvrir la liste vaut lecture des retours : la pastille « nouveau » disparaît
  const basculer = async () => {
    const nouveau = !ouvert;
    setOuvert(nouveau);
    if (nouveau) {
      await charger();
      if (donnees?.retours_non_lus) api.post("/vidal/ordonnances/retours-lus").catch(() => {});
    }
  };

  const voirPdf = async (o) => {
    try {
      const r = await api.get(`/vidal/ordonnances/${o.id}/pdf`, { responseType: "blob" });
      setApercu({ src: window.URL.createObjectURL(new Blob([r.data], { type: "application/pdf" })), titre: `Ordonnance ${o.reference}` });
    } catch { /* aperçu indisponible : rien à afficher */ }
  };

  const nonLus = donnees?.retours_non_lus || 0;
  const statuts = donnees?.statuts || {};

  return (
    <div className="carte" style={{ padding: 0 }}>
      <ApercuPdfIntegre apercu={apercu} onFermer={() => setApercu(null)} />
      <button type="button" onClick={basculer}
        style={{ width: "100%", display: "flex", alignItems: "center", gap: 6, border: "none", background: "transparent", padding: "12px 16px", cursor: "pointer", fontWeight: 700, color: "var(--vidal-texte)" }}>
        {ouvert ? <ChevronDown size={14} /> : <ChevronRight size={14} />} <Store size={14} /> Mes ordonnances — retour des officines
        {nonLus > 0 && <span className="badge" style={{ background: "#e0392b", color: "white", marginLeft: 6 }}>{nonLus} nouveau{nonLus > 1 ? "x" : ""}</span>}
      </button>
      {ouvert && (
        <div style={{ padding: "0 16px 16px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8, fontSize: 12, color: "var(--vidal-gris)" }}>
            <span>L'officine scanne le QR code de l'ordonnance A5 et indique ce qu'elle a servi, ou un produit en rupture.</span>
            <button type="button" className="bouton-secondaire" style={{ fontSize: 11.5 }} onClick={charger}>
              {chargement ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />} Actualiser
            </button>
          </div>
          {(donnees?.ordonnances || []).length === 0 && <div style={{ fontSize: 13, color: "var(--vidal-gris)" }}>Aucune ordonnance imprimée pour l'instant.</div>}
          <div style={{ display: "grid", gap: 6 }}>
            {(donnees?.ordonnances || []).map((o) => {
              const c = COULEURS[o.resume?.etat] || COULEURS.en_attente;
              return (
                <div key={o.id} style={{ border: "1px solid var(--vidal-bordure)", borderRadius: 10, padding: "8px 10px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", cursor: "pointer" }} onClick={() => setDetail(detail === o.id ? null : o.id)}>
                    <span style={{ fontWeight: 700, fontSize: 13 }}>{o.reference}</span>
                    <span style={{ fontSize: 12, color: "var(--vidal-gris)" }}>{dateFr(o.date)}{o.patient_name ? ` — ${o.patient_name}` : ""}</span>
                    <span className="badge" style={{ background: c.fond, color: c.texte, fontWeight: 700 }}>{o.resume?.libelle}</span>
                    {o.resume?.ruptures?.length > 0 && <span className="badge" style={{ background: "#fee2e2", color: "#991b1b" }}>{o.resume.ruptures.length} rupture{o.resume.ruptures.length > 1 ? "s" : ""}</span>}
                    {!o.retour_lu && <span className="badge" style={{ background: "#e0392b", color: "white" }}>nouveau</span>}
                    <button type="button" className="bouton-secondaire" style={{ fontSize: 11, marginLeft: "auto" }}
                      onClick={(e) => { e.stopPropagation(); voirPdf(o); }}><FileText size={12} /> Aperçu</button>
                  </div>
                  {detail === o.id && (
                    <div style={{ marginTop: 6, fontSize: 12.5 }}>
                      <div style={{ color: "var(--vidal-gris)", marginBottom: 4 }}>Prescrit : {o.lignes.join(" ; ")}</div>
                      {o.services.length === 0 && <div>Pas encore de retour d'officine.</div>}
                      {o.services.map((s, i) => (
                        <div key={i} style={{ marginBottom: 4 }}>
                          <b>{s.nom_officine}</b>{s.ville ? ` (${s.ville})` : ""} — {dateFr(s.date_service)}
                          <ul style={{ margin: "2px 0 0 18px" }}>
                            {(s.lignes || []).map((l, j) => (
                              <li key={j} style={{ color: l.statut === "rupture" ? "#b91c1c" : undefined }}>
                                {l.libelle} : <b>{statuts[l.statut] || l.statut}</b>{l.quantite_servie ? ` — quantité ${l.quantite_servie}` : ""}
                              </li>
                            ))}
                          </ul>
                          {s.commentaire && <div style={{ fontStyle: "italic", color: "var(--vidal-gris)" }}>« {s.commentaire} »</div>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
