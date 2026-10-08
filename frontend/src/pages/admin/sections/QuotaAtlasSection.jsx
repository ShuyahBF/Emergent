// QuotaAtlasSection.jsx — Lot 79.8 : rubrique « 🗄️ Base Atlas — collections du cluster » des Paramètres.
//
// Un cluster Atlas Flex (ou M0) accepte au plus 500 collections pour TOUT le cluster, toutes bases confondues
// (SAWALI, ALBARKA, DentalCare, adLyn… partagent Cluster0). Au-delà, plus aucune plateforme ne peut créer
// de collection. Cette rubrique affiche :
//   • une jauge circulaire : collections utilisées / limite (lot 79.9 : vert < 45 %, orange ≥ 45 %, rouge ≥ 90 %) ;
//   • le détail par base (barres horizontales, la base de SAWALI signalée) ;
//   • la limite et le seuil d'alerte, réglables (alerte WhatsApp au super-admin une fois par jour au-delà du seuil).
import React, { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api";

// Couleurs par niveau (vert, orange, rouge)
const COULEURS = {
  ok: { arc: "#059669", fond: "bg-emerald-50", texte: "text-emerald-800", libelle: "Marge confortable" },
  attention: { arc: "#d97706", fond: "bg-amber-50", texte: "text-amber-800", libelle: "Plus de 45 % utilisés" },   // lot 79.9
  plein: { arc: "#dc2626", fond: "bg-red-50", texte: "text-red-800", libelle: "Il reste 10 % ou moins : à libérer vite" },   // lot 79.9
};

// Jauge circulaire (SVG) : arc proportionnel au taux d'occupation, repère du seuil d'alerte
function Jauge({ total, limite, seuil, niveau }) {
  const rayon = 54;
  const circonference = 2 * Math.PI * rayon;
  const part = Math.min(1, limite ? total / limite : 0);
  const partSeuil = Math.min(1, limite ? seuil / limite : 0);
  const couleur = COULEURS[niveau]?.arc || COULEURS.ok.arc;
  // Position du repère de seuil sur le cercle (départ en haut, sens horaire)
  const angle = 2 * Math.PI * partSeuil - Math.PI / 2;
  const rx = 70 + rayon * Math.cos(angle);
  const ry = 70 + rayon * Math.sin(angle);
  return (
    <svg viewBox="0 0 140 140" className="w-40 h-40 shrink-0" role="img"
      aria-label={`${total} collections sur ${limite}`} data-testid="jauge-atlas">
      <circle cx="70" cy="70" r={rayon} fill="none" stroke="#e2e8f0" strokeWidth="14" />
      <circle cx="70" cy="70" r={rayon} fill="none" stroke={couleur} strokeWidth="14" strokeLinecap="round"
        strokeDasharray={`${circonference * part} ${circonference}`} transform="rotate(-90 70 70)"
        style={{ transition: "stroke-dasharray 0.6s ease" }} />
      {/* Repère du seuil d'alerte */}
      <circle cx={rx} cy={ry} r="4" fill="#ffffff" stroke="#475569" strokeWidth="2" />
      <text x="70" y="66" textAnchor="middle" className="fill-slate-900" style={{ fontSize: 26, fontWeight: 700 }}>{total}</text>
      <text x="70" y="86" textAnchor="middle" className="fill-slate-500" style={{ fontSize: 11 }}>sur {limite}</text>
    </svg>
  );
}

// Lot 85 — contenu d'une base (collections + documents) et suppression d'une base OBSOLÈTE, nom à retaper.
// Les bases en service (SAWALI, ALBARKA, Ster, adLyn…) sont protégées par le serveur.
function DetailBase({ nom, onSupprimee }) {
  const [detail, setDetail] = useState(null);
  const [saisie, setSaisie] = useState("");
  const [enCours, setEnCours] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    apiClient.get(`/admin/atlas/bases/${encodeURIComponent(nom)}`).then((r) => setDetail(r.data))
      .catch((e) => setMessage(e?.response?.data?.detail || "Contenu illisible"));
  }, [nom]);
  const supprimer = async () => {
    setEnCours(true); setMessage("Patientez…");
    try {
      const r = await apiClient.post(`/admin/atlas/bases/${encodeURIComponent(nom)}/supprimer`, { confirmation: saisie });
      setMessage(`Base purgée : ${r.data.collections_liberees} collections libérées`
        + ((r.data.refusees || []).length ? ` (${r.data.refusees.length} refusées : ${r.data.refusees.join(", ")})` : "") + ".");
      onSupprimee(r.data.mesure);
    } catch (e) {
      setMessage(e?.response?.data?.detail || "Suppression impossible");
    } finally { setEnCours(false); }
  };
  if (!detail) return <p className="text-xs text-slate-500 pl-2">{message || "Patientez…"}</p>;
  return (
    <div className="ml-2 space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-2 text-xs" data-testid={`detail-base-${nom}`}>
      <p><b>{detail.collections.length}</b> collections · <b>{detail.documents.toLocaleString("fr-FR")}</b> documents au total</p>
      <div className="max-h-48 overflow-y-auto">
        <table className="w-full">
          <tbody>
            {detail.collections.map((c) => (
              <tr key={c.nom} className="border-t border-slate-200"><td className="py-0.5 font-mono">{c.nom}</td>
                <td className="text-right tabular-nums">{c.documents ?? "?"}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      {detail.protegee ? (
        <p className="text-slate-600">🔒 Base en service : elle ne peut pas être supprimée.</p>
      ) : (
        <div className="flex flex-wrap items-center gap-2 border-t border-slate-200 pt-2">
          <span className="text-red-700">Supprimer définitivement cette base : retapez son nom</span>
          <input value={saisie} onChange={(e) => setSaisie(e.target.value)} placeholder={nom}
            className="w-40 rounded border border-slate-300 px-2 py-1 font-mono" />
          <button type="button" disabled={enCours || saisie !== nom} onClick={supprimer}
            className="rounded bg-red-600 px-2 py-1 font-semibold text-white disabled:opacity-40">Supprimer la base</button>
        </div>
      )}
      {message && <p className="text-slate-700">{message}</p>}
    </div>
  );
}

export default function QuotaAtlasSection({ reglages, maj }) {
  const [ouverte, setOuverte] = useState(null);   // lot 85 : base dont on affiche le contenu
  const [mesure, setMesure] = useState(null);
  const [erreur, setErreur] = useState("");

  // Lecture de la mesure (comptage en direct sur le cluster)
  const charger = useCallback(() => {
    setErreur("");
    apiClient.get("/admin/atlas/quota").then((r) => setMesure(r.data))
      .catch((e) => setErreur(e?.response?.data?.detail || "Mesure indisponible"));
  }, []);
  useEffect(() => { charger(); }, [charger]);

  if (erreur) return <p className="text-sm text-red-700">{erreur}</p>;
  if (!mesure) return <p className="text-sm text-slate-500">Patientez…</p>;
  const c = COULEURS[mesure.niveau] || COULEURS.ok;
  const plusGrande = Math.max(1, ...mesure.bases.map((b) => b.collections));

  return (
    <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-quota-atlas">
      <div className="flex flex-col sm:flex-row items-center gap-5">
        <Jauge total={mesure.total} limite={mesure.limite} seuil={mesure.seuil} niveau={mesure.niveau} />
        <div className="flex-1 space-y-2 w-full">
          <div className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold ${c.fond} ${c.texte}`}
            data-testid="niveau-atlas">
            {c.libelle} · {mesure.pourcentage} %
          </div>
          <p className="text-sm text-slate-700">
            <b>{mesure.total}</b> collections utilisées sur <b>{mesure.limite}</b> autorisées pour tout le cluster —
            encore <b>{mesure.restantes}</b> avant le blocage. Alerte WhatsApp au-delà de <b>{mesure.seuil}</b>.
          </p>
          {mesure.methode !== "cluster" && (
            <p className="text-xs text-amber-700">
              Seule la base de SAWALI a pu être comptée ({mesure.erreur}) : le total réel du cluster est plus élevé.
            </p>
          )}
          <p className="text-[11px] text-slate-500">
            Mesuré le {new Date(mesure.le).toLocaleString("fr-FR")} · vérification automatique toutes les heures.
            <button type="button" onClick={charger} className="ml-2 rounded border border-slate-300 px-2 py-0.5 hover:bg-slate-50">⟳ Mesurer</button>
          </p>
        </div>
      </div>

      {/* Détail par base : barres proportionnelles */}
      <div className="space-y-1.5" data-testid="bases-atlas">
        {mesure.bases.map((b) => (
          <React.Fragment key={b.nom}>
          <div className="grid grid-cols-[9rem_1fr_3rem_4rem] items-center gap-2 text-xs">
            <span className={`truncate ${b.sawali ? "font-semibold text-slate-900" : "text-slate-600"}`} title={b.nom}>
              {b.nom}{b.sawali ? " (SAWALI)" : ""}
            </span>
            <span className="h-2 rounded-full bg-slate-100 overflow-hidden">
              <span className="block h-full rounded-full" style={{ width: `${(100 * b.collections) / plusGrande}%`,
                background: b.sawali ? "#1d4ed8" : "#94a3b8" }} />
            </span>
            <span className="text-right tabular-nums text-slate-700">{b.collections}</span>
            {/* Lot 85 : voir le contenu (et supprimer une base obsolète) */}
            <button type="button" onClick={() => setOuverte(ouverte === b.nom ? null : b.nom)}
              className="rounded border border-slate-300 px-1.5 py-0.5 hover:bg-slate-50">{ouverte === b.nom ? "Fermer" : "Contenu"}</button>
          </div>
          {ouverte === b.nom && <DetailBase nom={b.nom} onSupprimee={(m) => { setOuverte(null); if (m) setMesure(m); }} />}
          </React.Fragment>
        ))}
      </div>

      {/* Réglages : limite du cluster et seuil d'alerte */}
      <div className="grid sm:grid-cols-2 gap-3 border-t border-slate-100 pt-3">
        <label className="block text-xs">
          <span className="font-semibold text-slate-700">Limite du cluster (Flex / M0 : 500)</span>
          <input type="number" min="1" value={reglages.atlas_limite_collections ?? 500}
            onChange={(e) => maj("atlas_limite_collections", e.target.value === "" ? null : Number(e.target.value))}
            className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" data-testid="atlas-limite" />
        </label>
        <label className="block text-xs">
          <span className="font-semibold text-slate-700">Seuil d'alerte (WhatsApp au super-admin)</span>
          <input type="number" min="1" value={reglages.atlas_seuil_alerte ?? 450}
            onChange={(e) => maj("atlas_seuil_alerte", e.target.value === "" ? null : Number(e.target.value))}
            className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" data-testid="atlas-seuil" />
        </label>
      </div>
      <p className="text-[11px] text-slate-500">
        Les réglages prennent effet après « Enregistrer ». Une copie de secours doit toujours être faite sur un AUTRE
        cluster : sur celui-ci, elle remplit le quota partagé par toutes les plateformes.
      </p>
    </div>
  );
}
