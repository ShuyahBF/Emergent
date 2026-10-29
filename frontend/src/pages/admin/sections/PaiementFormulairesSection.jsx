// PaiementFormulairesSection.jsx — Lot 361 : moyens de paiement actifs sur le lien de paiement des formulaires et sondages.
//
// Règle du propriétaire : PawaPay est TOUJOURS actif par défaut. Orange, Moov, Telecel sont des opérateurs encaissés PAR PawaPay ;
// PI-SPI (virement instantané bancaire) n'a pas d'API : le client déclare son virement, puis l'administrateur CONFIRME ici
// la réception, ce qui lance la mise en ligne du formulaire. Seuls les moyens cochés s'affichent sur le lien de paiement.
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

export default function PaiementFormulairesSection() {
  const [etat, setEtat] = useState(null);
  const [actifs, setActifs] = useState([]);
  const [texte, setTexte] = useState("");
  const [enregistrement, setEnregistrement] = useState(false);

  // Lecture du réglage et des paiements PI-SPI en attente
  const lire = () => apiClient.get("/admin/paiement-formulaires").then((r) => {
    setEtat(r.data);
    setActifs(r.data.actifs || []);
    setTexte(r.data.pispi_texte || "");
  }).catch(() => toast.error("Réglage indisponible"));
  useEffect(() => { lire(); }, []);

  if (!etat) return <p className="text-xs text-slate-500">Patientez…</p>;
  const bascule = (code) => setActifs((a) => (a.includes(code) ? a.filter((c) => c !== code) : [...a, code]));

  // Enregistrement : PawaPay est remis d'office si plus rien n'est coché (règle du propriétaire)
  const enregistrer = async () => {
    setEnregistrement(true);
    try {
      const r = await apiClient.put("/admin/paiement-formulaires", { moyens: actifs, pispi_texte: texte });
      setActifs(r.data.actifs);
      toast.success("Moyens de paiement enregistrés");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Enregistrement impossible");
    } finally {
      setEnregistrement(false);
    }
  };

  // Confirmation manuelle d'un paiement PI-SPI : la mise en ligne du formulaire se lance
  const confirmer = async (slug) => {
    try {
      await apiClient.post(`/admin/paiement-formulaires/pispi/${slug}/confirmer`);
      toast.success("Paiement confirmé : le formulaire est mis en ligne");
      lire();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Confirmation impossible");
    }
  };

  return (
    <div className="space-y-3" data-testid="paiement-formulaires">
      <p className="text-xs text-slate-600">
        Moyens proposés sur le lien de paiement des formulaires et sondages. Orange, Moov et Telecel sont encaissés par PawaPay ;
        PI-SPI est confirmé à la main. Par défaut : PawaPay seul (Orange, Moov et Telecel).
      </p>
      <div className="flex flex-wrap gap-4 text-sm">
        {etat.methodes.map((m) => (
          <label key={m.code} className="inline-flex items-center gap-2">
            <input type="checkbox" checked={actifs.includes(m.code)} onChange={() => bascule(m.code)} data-testid={`paiement-${m.code}`} />
            {m.libelle}
          </label>
        ))}
      </div>
      {actifs.includes("PISPI") && (
        <label className="flex flex-col gap-1 text-sm">
          Texte affiché au client (coordonnées bancaires, consignes)
          <textarea rows={4} value={texte} onChange={(e) => setTexte(e.target.value)} maxLength={1500}
            className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm" data-testid="paiement-pispi-texte" />
        </label>
      )}
      <button type="button" onClick={enregistrer} disabled={enregistrement}
        className="rounded-md bg-blue-700 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-60" data-testid="paiement-enregistrer">
        {enregistrement ? "Enregistrement…" : "Enregistrer"}
      </button>
      <div>
        <h4 className="text-sm font-semibold">Paiements PI-SPI à confirmer ({etat.pispi_en_attente.length})</h4>
        {etat.pispi_en_attente.length === 0 ? (
          <p className="text-xs text-slate-500">Aucun paiement PI-SPI en attente.</p>
        ) : (
          <table className="w-full text-xs mt-1">
            <thead><tr className="text-left text-slate-500"><th>Déclaré le</th><th>Formulaire</th><th>Payeur</th><th className="text-right">Montant</th><th></th></tr></thead>
            <tbody>
              {etat.pispi_en_attente.map((p) => (
                <tr key={p.slug}>
                  <td>{(p.pispi_declare_le || "").slice(0, 16).replace("T", " ")}</td>
                  <td>{p.label}</td>
                  <td>{p.pispi_payeur || p.prefill_phone || "—"}</td>
                  <td className="text-right tabular-nums">{Number(p.amount || 0).toLocaleString("fr-FR")} {p.currency || "XOF"}</td>
                  <td><button type="button" onClick={() => confirmer(p.slug)} className="rounded bg-emerald-700 px-2 py-1 text-white" data-testid={`paiement-confirmer-${p.slug}`}>Confirmer la réception</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
