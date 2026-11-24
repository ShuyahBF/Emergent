// ============================================================================
// Lot 453 — Liste noire WhatsApp (toutes lignes) : SEUL endroit où elle est visible et modifiable.
//   - on bloque depuis le Centre de Messagerie (bouton « Bloquer » de l'en-tête d'une conversation) ou ici, en saisissant un numéro ;
//   - un contact bloqué ne reçoit plus aucun message de SAWALI (donc aucun « distribué » ni « lu »), aucun agent IA ne lui répond,
//     ses messages sont enregistrés mais retenus (ni non-lu, ni notification) ;
//   - « Débloquer » remet le contact en service tout de suite.
// Backend : GET/POST /api/admin/wa/liste-noire, POST /api/me/wa/liste-noire, DELETE /api/admin/wa/liste-noire/{cle}.
// ============================================================================
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Ban, RefreshCw, Unlock } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const dateHeure = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");
const COLONNES = [["nom", "Contact"], ["numero", "Numéro"], ["motif", "Motif"], ["bloque_le", "Bloqué le"], ["par", "Par"]];

export default function ListeNoireWaAdminSection() {
  const [donnees, setDonnees] = useState(null);       // null = chargement en cours
  const [numero, setNumero] = useState("");
  const [nom, setNom] = useState("");
  const [motif, setMotif] = useState("");
  const [enCours, setEnCours] = useState(false);
  const [tri, setTri] = useState({ cle: "bloque_le", sens: -1 });

  const charger = useCallback(async () => {
    setEnCours(true);
    toast("Actualisation de la liste noire en cours…");
    try { const r = await apiClient.get("/admin/wa/liste-noire"); setDonnees(r.data); toast.success(`Liste noire : ${r.data.total} contact(s) bloqué(s).`); }
    catch (e) { setDonnees({ erreur: e?.response?.data?.detail || "Lecture impossible", entrees: [] }); toast.error("Lecture impossible"); }
    finally { setEnCours(false); }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  const lignes = useMemo(() => {
    const l = [...(donnees?.entrees || [])];
    l.sort((a, b) => {
      const va = a[tri.cle] || "", vb = b[tri.cle] || "";
      if (!va && vb) return 1;                      // les valeurs vides restent en dernier
      if (va && !vb) return -1;
      return String(va).localeCompare(String(vb), "fr", { sensitivity: "base" }) * tri.sens;
    });
    return l;
  }, [donnees, tri]);

  const bloquer = async () => {
    setEnCours(true);
    try { await apiClient.post("/me/wa/liste-noire", { telephone: numero, nom, motif }); toast.success("Contact bloqué sur toutes les lignes."); setNumero(""); setNom(""); setMotif(""); await charger(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Blocage impossible"); setEnCours(false); }
  };
  const debloquer = async (e) => {
    if (!window.confirm(`Débloquer ${e.nom || e.numero} ? Il pourra de nouveau recevoir des messages et des réponses.`)) return;
    try { await apiClient.delete(`/admin/wa/liste-noire/${encodeURIComponent(e.cle)}`); toast.success("Contact débloqué."); await charger(); }
    catch (err) { toast.error(err?.response?.data?.detail || "Déblocage impossible"); }
  };

  if (!donnees) return <p className="text-sm text-slate-500">Chargement…</p>;
  if (donnees.erreur) return <p className="text-sm text-red-700">{donnees.erreur}</p>;
  return (
    <div className="space-y-4" data-testid="liste-noire-wa-admin">
      <p className="text-xs text-slate-600">Un contact bloqué ne reçoit plus aucun message WhatsApp de SAWALI, sur aucune ligne (donc aucun « distribué » ni « lu »). Aucun agent IA ne lui répond ; ses messages sont enregistrés mais retenus, sans notification. Cette liste n'est visible qu'ici ; on bloque aussi depuis le Centre de Messagerie.</p>
      <div className="grid gap-2 sm:grid-cols-4">
        <input className="rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder="Numéro (+226 70 12 34 56)" aria-label="Numéro à bloquer" value={numero} onChange={(e) => setNumero(e.target.value)} />
        <input className="rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder="Nom (facultatif)" aria-label="Nom du contact" maxLength={120} value={nom} onChange={(e) => setNom(e.target.value)} />
        <input className="rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder="Motif (facultatif)" aria-label="Motif du blocage" maxLength={300} value={motif} onChange={(e) => setMotif(e.target.value)} />
        <button type="button" onClick={bloquer} disabled={enCours || numero.replace(/\D/g, "").length < 8} className="inline-flex items-center justify-center gap-2 rounded-lg bg-red-600 px-3 py-2 text-sm text-white disabled:opacity-50"><Ban className="h-4 w-4" />Bloquer ce numéro</button>
      </div>
      <div className="max-h-[28rem] overflow-auto">
        <table className="w-full min-w-[40rem] text-sm">
          <thead className="sticky top-0 bg-white"><tr className="text-left text-slate-600">
            {COLONNES.map(([cle, lib]) => (
              <th key={cle} className="p-2"><button type="button" className={`font-semibold ${tri.cle === cle ? "text-orange-600" : ""}`} onClick={() => setTri((t) => (t.cle === cle ? { cle, sens: -t.sens } : { cle, sens: 1 }))} aria-label={`Trier par ${lib}`}>
                {lib} {tri.cle === cle ? (tri.sens === 1 ? "▲" : "▼") : <span className="text-slate-400">⇅</span>}</button></th>
            ))}
            <th className="p-2" />
          </tr></thead>
          <tbody>
            {lignes.length === 0 && <tr><td colSpan={6} className="p-3 text-slate-500">Aucun contact bloqué.</td></tr>}
            {lignes.map((e) => (
              <tr key={e.cle} className="border-t hover:bg-sky-100/50">
                <td className="p-2 font-semibold">{e.nom || "—"}</td>
                <td className="p-2 tabular-nums">{e.numero}</td>
                <td className="p-2">{e.motif || "—"}</td>
                <td className="p-2 whitespace-nowrap">{dateHeure(e.bloque_le)}</td>
                <td className="p-2">{e.par || "—"}</td>
                <td className="p-2 text-right"><button type="button" onClick={() => debloquer(e)} className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-2 py-1 text-xs" title="Débloquer ce contact"><Unlock className="h-3.5 w-3.5" />Débloquer</button></td>
              </tr>
            ))}
          </tbody>
          <tfoot className="sticky bottom-0 bg-white"><tr className="border-t-2 font-bold"><td className="p-2" colSpan={6}>{donnees.total} contact(s) bloqué(s) sur {donnees.maximum} au plus</td></tr></tfoot>
        </table>
      </div>
      <button type="button" onClick={charger} disabled={enCours} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm disabled:opacity-60"><RefreshCw className={`h-4 w-4 ${enCours ? "animate-spin" : ""}`} />Actualiser</button>
    </div>
  );
}
