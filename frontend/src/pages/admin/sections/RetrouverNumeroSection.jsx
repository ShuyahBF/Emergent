/*
  Lot 104.3 — « Retrouver un numéro » (administrateur / superviseur).

  Un message relayé sur WhatsApp mais absent du Centre de messagerie ? On saisit le numéro :
  - SAWALI dit où sont rangés ses messages (mon espace ou un autre, avec ou sans fiche contact,
    retenus par la barrière anti-rafale, ligne WhatsApp non autorisée, « contact à enregistrer ») ;
  - « Rattacher à mon espace » : la fiche du numéro est ramenée (ou créée) dans mon espace et
    tous ses messages y sont rattachés ; la conversation apparaît dans le Centre de messagerie.
*/
import React, { useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Search, Link2 } from "lucide-react";

// Date/heure lisible en français
const fmt = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");
const erreur = (e) => e?.response?.data?.detail || e?.message || "Erreur";

export default function RetrouverNumeroSection() {
  const [numero, setNumero] = useState("");
  const [resultat, setResultat] = useState(null);
  const [attente, setAttente] = useState(false);

  // Diagnostic du numéro saisi
  const chercher = async (e) => {
    e?.preventDefault();
    if (!numero.trim()) return;
    setAttente(true);
    const t = toast.loading("Patientez… recherche du numéro");
    try {
      setResultat((await apiClient.get("/me/retrouver-numero", { params: { numero: numero.trim() } })).data);
      toast.dismiss(t);
    } catch (err) { toast.error(erreur(err), { id: t }); }
    finally { setAttente(false); }
  };

  // Réparation : fiche + messages rattachés à mon espace, puis nouveau diagnostic
  const rattacher = async () => {
    const t = toast.loading("Patientez… rattachement des messages");
    try {
      const { data } = await apiClient.post("/me/retrouver-numero/rattacher", { numero: numero.trim() });
      toast.success(`${data.rattaches} message(s) rattaché(s) à la fiche « ${data.fiche_nom} »${data.fiche_deplacee ? " (fiche ramenée dans votre espace)" : ""}.`, { id: t });
      await chercher();
    } catch (err) { toast.error(erreur(err), { id: t }); }
  };

  const m = resultat?.messages;
  return (
    <div className="space-y-3 text-sm" data-testid="retrouver-numero">
      <p className="text-xs text-slate-500">
        Un message relayé sur votre WhatsApp n'apparaît pas dans le Centre de messagerie ? Saisissez le numéro :
        SAWALI indique où ses messages sont rangés et pourquoi ils sont invisibles, puis les rattache à votre espace.
      </p>
      <form onSubmit={chercher} className="flex flex-wrap gap-2">
        <input value={numero} onChange={(e) => setNumero(e.target.value)} placeholder="+226 55 85 96 15" inputMode="tel"
               className="w-56 rounded-lg px-3 py-2 ring-1 ring-slate-300" data-testid="retrouver-numero-champ" />
        <button type="submit" disabled={attente} className="inline-flex items-center gap-1 rounded-lg bg-slate-900 px-3 py-2 text-white disabled:opacity-50">
          <Search className="h-4 w-4" /> Rechercher
        </button>
      </form>

      {resultat && (
        <div className="space-y-3 rounded-lg border border-slate-200 bg-white p-3">
          {/* Diagnostic en phrases simples */}
          <ul className="space-y-1">
            {resultat.causes.map((c) => <li key={c} className="text-slate-800">• {c}</li>)}
          </ul>
          <div className="flex flex-wrap gap-x-4 text-xs text-slate-600">
            <span>{m.total} message(s)</span><span>Hors de votre espace : {m.hors_espace}</span>
            <span>Sans fiche : {m.sans_fiche}</span><span>Retenus : {m.retenus}</span>
          </div>
          {resultat.fiches.length > 0 && (
            <div className="text-xs">
              <b>Fiche(s) :</b>{" "}
              {resultat.fiches.map((f) => (
                <span key={f.id} className="mr-3">{f.nom} ({f.numero}) — {f.dans_mon_espace ? "votre espace" : "autre espace"}
                  {!f.ligne_visible && " · ligne non autorisée"}{f.source === "auto" && " · créée par Liluvine"}</span>
              ))}
            </div>
          )}
          {m.derniers.length > 0 && (
            <table className="w-full text-xs">
              <thead><tr className="text-left text-slate-500"><th className="py-1 pr-2">Date</th><th className="pr-2">Sens</th><th className="pr-2">Message</th><th>Rangement</th></tr></thead>
              <tbody>
                {m.derniers.map((d, i) => (
                  <tr key={i} className="border-t border-slate-100">
                    <td className="py-1 pr-2 whitespace-nowrap">{fmt(d.date)}</td>
                    <td className="pr-2">{d.sens === "inbound" ? "Reçu" : "Envoyé"}</td>
                    <td className="pr-2">{d.extrait}</td>
                    <td className={d.dans_mon_espace && d.avec_fiche ? "text-emerald-700" : "text-rose-700"}>
                      {d.dans_mon_espace ? "Votre espace" : "Autre espace"}{!d.avec_fiche && " · sans fiche"}{d.retenu && " · retenu"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {resultat.reparable && (
            <button type="button" onClick={rattacher} className="inline-flex items-center gap-1 rounded-lg bg-emerald-700 px-3 py-2 text-white" data-testid="retrouver-numero-rattacher">
              <Link2 className="h-4 w-4" /> Rattacher à mon espace
            </button>
          )}
        </div>
      )}
    </div>
  );
}
