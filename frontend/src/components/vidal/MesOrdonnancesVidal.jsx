// components/vidal/MesOrdonnancesVidal.jsx
// ------------------------------------------------
// Lot 57 — « Le médecin saura en retour si son ordonnance a pu être servie au
// patient » : liste des ordonnances émises par le médecin connecté, avec le
// retour des officines (servie, servie en partie, produit en rupture, en
// attente). Pastille « nouveau » tant que les retours n'ont pas été consultés.
// L'ordonnance peut être revue en aperçu intégré (A5, jamais un nouvel onglet).
import { useEffect, useState } from "react";
import { Ban, ChevronDown, ChevronRight, FileText, History, Loader2, Radio, RefreshCw, Store } from "lucide-react";
import { apiClient as api } from "@/lib/api";
import ApercuPdfIntegre from "./ApercuPdfIntegre";
import EtiquetteNfcOrdonnance from "./EtiquetteNfcOrdonnance";   // lot 383 : écrire le lien de l'officine sur une étiquette NFC

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
  const [nfcPour, setNfcPour] = useState(null);      // lot 383 : id de l'ordonnance dont on écrit l'étiquette NFC
  const [journal, setJournal] = useState({});        // lot 383 : journal d'accès chargé par ordonnance

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
      setApercu({ src: window.URL.createObjectURL(new Blob([r.data], { type: "application/pdf" })), titre: `Ordonnance ${o.reference}`, telechargement: true });
    } catch { /* aperçu indisponible : rien à afficher */ }
  };

  // Lot 383 — révoquer / rétablir une ordonnance, et lire son journal d'accès
  const revoquer = async (o) => {
    if (!window.confirm(`Annuler l'ordonnance ${o.reference} ? Aucune officine ne pourra plus la lire ni la servir.`)) return;
    await api.post(`/vidal/ordonnances/${o.id}/revoquer`, { motif: "annulée par le prescripteur" }).catch(() => {});
    charger();
  };
  const retablir = async (o) => { await api.post(`/vidal/ordonnances/${o.id}/retablir`).catch(() => {}); charger(); };
  const voirJournal = async (o) => {
    const r = await api.get(`/vidal/ordonnances/${o.id}/acces`).catch(() => null);
    if (r) setJournal((prec) => ({ ...prec, [o.id]: r.data }));
  };
  const LIBELLES_ACTION = { lecture: "Lecture de la page", service: "Retour de l'officine", etiquette_ecrite: "Étiquette NFC écrite", revoquee: "Ordonnance annulée", retablie: "Ordonnance rétablie",
    refus_expiree: "Refusé : expirée", refus_revoquee: "Refusé : annulée", refus_cloturee: "Refusé : déjà servie" };

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
                    {o.etat_acces?.code === "revoquee" && <span className="badge" style={{ background: "#fee2e2", color: "#991b1b", fontWeight: 700 }}>Annulée</span>}
                    {o.etat_acces?.code === "expiree" && <span className="badge" style={{ background: "#e2e8f0", color: "#334155", fontWeight: 700 }}>Expirée</span>}
                    {o.etat_acces?.code === "ok" && o.etat_acces?.expire_le && <span style={{ fontSize: 11, color: "var(--vidal-gris)" }}>valable jusqu'au {new Date(o.etat_acces.expire_le).toLocaleDateString("fr-FR")}</span>}
                    {o.acces?.suspect && <span className="badge" style={{ background: "#fef3c7", color: "#92400e", fontWeight: 700 }} title={o.acces.motif}>⚠ réutilisation suspecte</span>}
                    <button type="button" className="bouton-secondaire" style={{ fontSize: 11, marginLeft: "auto" }}
                      onClick={(e) => { e.stopPropagation(); voirPdf(o); }}><FileText size={12} /> Aperçu</button>
                  </div>
                  {detail === o.id && (
                    <div style={{ marginTop: 6, fontSize: 12.5 }}>
                      <div style={{ color: "var(--vidal-gris)", marginBottom: 4 }}>Prescrit : {o.lignes.join(" ; ")}</div>
                      {/* Lot 383 : étiquette NFC, annulation, journal d'accès */}
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", margin: "6px 0" }}>
                        {!o.revoquee && o.etat_acces?.code !== "expiree" && (
                          <button type="button" className="bouton-secondaire" style={{ fontSize: 11.5 }} onClick={() => setNfcPour(nfcPour === o.id ? null : o.id)} data-testid="nfc-ouvrir"><Radio size={12} /> Écrire sur une étiquette NFC</button>)}
                        {o.revoquee
                          ? <button type="button" className="bouton-secondaire" style={{ fontSize: 11.5 }} onClick={() => retablir(o)}>Rétablir l'ordonnance</button>
                          : <button type="button" className="bouton-secondaire" style={{ fontSize: 11.5, color: "#b91c1c" }} onClick={() => revoquer(o)}><Ban size={12} /> Annuler l'ordonnance</button>}
                        <button type="button" className="bouton-secondaire" style={{ fontSize: 11.5 }} onClick={() => voirJournal(o)}><History size={12} /> Journal d'accès ({o.acces?.nombre || 0})</button>
                      </div>
                      {nfcPour === o.id && <EtiquetteNfcOrdonnance ordonnanceId={o.id} onFermer={() => setNfcPour(null)} />}
                      {journal[o.id] && (
                        <div style={{ margin: "6px 0", padding: 8, background: "#f8fafc", borderRadius: 8 }}>
                          {journal[o.id].resume?.suspect && <div style={{ color: "#92400e", fontWeight: 700, marginBottom: 4 }}>⚠ Réutilisation suspecte : {journal[o.id].resume.motif}</div>}
                          {(journal[o.id].evenements || []).length === 0 && <div>Aucun accès enregistré.</div>}
                          {(journal[o.id].evenements || []).slice(0, 15).map((e, k) => (
                            <div key={k} style={{ fontSize: 12 }}>{dateFr(e.date)} — {LIBELLES_ACTION[e.action] || e.action}{e.canal === "nfc" ? " (NFC)" : ""}{e.officine ? ` — ${e.officine}` : ""} <span style={{ color: "var(--vidal-gris)" }}>· {e.ip_masquee}</span></div>
                          ))}
                        </div>
                      )}
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
