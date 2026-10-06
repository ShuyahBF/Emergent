// ListeNoireCommandesSection.jsx — Lot 61 : liste noire des numéros interdits aux commandes « ! ».
//
// Administration → Paramètres → « ⛔ Liste noire des commandes « ! » ».
// - Ajouter un numéro (avec un nom et un motif facultatifs) ;
// - Retirer un numéro (il retrouve l'accès aux commandes) ;
// - Modifier le message que Liluvine répond à ces numéros (vide = message par défaut).
// Un numéro bloqué peut toujours écrire normalement : seules les commandes « ! » / « / » sont refusées.
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

export default function ListeNoireCommandesSection() {
  const [items, setItems] = useState([]);
  const [message, setMessage] = useState("");
  const [messageDefaut, setMessageDefaut] = useState("");
  const [nouveau, setNouveau] = useState({ telephone: "", nom: "", motif: "" });
  const [occupe, setOccupe] = useState(false);
  const [voirRetires, setVoirRetires] = useState(false);

  // Lecture de la liste et du message
  const charger = async () => {
    try {
      const r = await apiClient.get("/admin/liluvine-commandes-bloquees");
      setItems(r.data?.items || []);
      setMessage(r.data?.message || "");
      setMessageDefaut(r.data?.message_defaut || "");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Liste noire indisponible");
    }
  };
  useEffect(() => { charger(); }, []);

  // Ajout d'un numéro
  const ajouter = async (e) => {
    e.preventDefault();
    setOccupe(true);
    try {
      await apiClient.post("/admin/liluvine-commandes-bloquees", nouveau);
      toast.success("Numéro ajouté à la liste noire");
      setNouveau({ telephone: "", nom: "", motif: "" });
      await charger();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Ajout impossible");
    } finally {
      setOccupe(false);
    }
  };

  // Retrait d'un numéro
  const retirer = async (it) => {
    if (!window.confirm(`Rendre l'accès aux commandes « ! » au ${it.telephone}${it.nom ? ` (${it.nom})` : ""} ?`)) return;
    try {
      await apiClient.delete(`/admin/liluvine-commandes-bloquees/${it.chiffres}`);
      toast.success("Numéro retiré de la liste noire");
      await charger();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Retrait impossible");
    }
  };

  // Enregistrement du message de refus
  const enregistrerMessage = async () => {
    try {
      await apiClient.put("/admin/liluvine-commandes-bloquees/message", { message });
      toast.success("Message enregistré");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Enregistrement impossible");
    }
  };

  const visibles = items.filter((it) => voirRetires || it.actif);

  return (
    <div className="space-y-4" data-testid="liste-noire-commandes">
      <p className="text-xs text-slate-600">
        Les numéros de cette liste ne peuvent plus utiliser les commandes Liluvine commençant par « ! » (ou « / »)
        : !garde, !meteo, !doc, !formulaire, !ticket… Liluvine leur répond le message ci-dessous, au plus une fois
        toutes les 10 minutes. Leurs messages ordinaires restent reçus.
      </p>

      {/* Message de refus */}
      <div className="space-y-1">
        <label className="block text-xs font-semibold text-slate-700">Message de Liluvine aux numéros bloqués</label>
        <textarea
          rows={2}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder={messageDefaut}
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          data-testid="liste-noire-message"
        />
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-slate-500">Vide = message par défaut (affiché en gris).</span>
          <button type="button" onClick={enregistrerMessage}
            className="rounded-lg bg-sawali-blue px-3 py-1.5 text-xs font-semibold text-white hover:bg-sawali-blue-light">
            Enregistrer le message
          </button>
        </div>
      </div>

      {/* Ajout d'un numéro */}
      <form onSubmit={ajouter} className="grid gap-2 sm:grid-cols-[1fr_1fr_2fr_auto] items-end">
        <label className="block text-xs">
          <span className="font-semibold text-slate-700">Numéro (avec indicatif)</span>
          <input required value={nouveau.telephone} onChange={(e) => setNouveau({ ...nouveau, telephone: e.target.value })}
            placeholder="+226 70 00 00 00" className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
            data-testid="liste-noire-telephone" />
        </label>
        <label className="block text-xs">
          <span className="font-semibold text-slate-700">Nom (facultatif)</span>
          <input value={nouveau.nom} onChange={(e) => setNouveau({ ...nouveau, nom: e.target.value })}
            className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
        </label>
        <label className="block text-xs">
          <span className="font-semibold text-slate-700">Motif (facultatif)</span>
          <input value={nouveau.motif} onChange={(e) => setNouveau({ ...nouveau, motif: e.target.value })}
            placeholder="ex. abus de commandes, harcèlement…" className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
        </label>
        <button type="submit" disabled={occupe}
          className="rounded-lg bg-rose-600 px-3 py-2 text-xs font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
          data-testid="liste-noire-ajouter">
          {occupe ? "Patientez…" : "⛔ Bloquer"}
        </button>
      </form>

      {/* Liste */}
      <div className="overflow-x-auto rounded-lg ring-1 ring-slate-200">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs text-slate-500">
            <tr>
              <th className="px-3 py-2 text-left">Numéro</th>
              <th className="px-3 py-2 text-left">Nom</th>
              <th className="px-3 py-2 text-left">Motif</th>
              <th className="px-3 py-2 text-left">Bloqué le / par</th>
              <th className="px-3 py-2 text-right">Tentatives</th>
              <th className="px-3 py-2 text-left">Dernière commande</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {visibles.length === 0 ? (
              <tr><td colSpan={7} className="px-3 py-4 text-center text-xs text-slate-500">Aucun numéro bloqué.</td></tr>
            ) : visibles.map((it) => (
              <tr key={it.chiffres} className={`border-t border-slate-100 ${it.actif ? "" : "opacity-50"}`}>
                <td className="px-3 py-2 font-mono">{it.telephone}</td>
                <td className="px-3 py-2">{it.nom || "—"}</td>
                <td className="px-3 py-2">{it.motif || "—"}</td>
                <td className="px-3 py-2 text-xs">{it.le ? new Date(it.le).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : ""} · {it.par || ""}</td>
                <td className="px-3 py-2 text-right tabular-nums">{it.tentatives || 0}</td>
                <td className="px-3 py-2 font-mono text-xs">{it.derniere_commande || "—"}</td>
                <td className="px-3 py-2 text-right">
                  {it.actif ? (
                    <button type="button" onClick={() => retirer(it)} className="text-xs text-emerald-700 hover:underline">Débloquer</button>
                  ) : <span className="text-[10px] text-slate-400">retiré</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <label className="inline-flex items-center gap-1.5 text-xs text-slate-600">
        <input type="checkbox" checked={voirRetires} onChange={(e) => setVoirRetires(e.target.checked)} />
        Afficher aussi les numéros débloqués
      </label>
    </div>
  );
}
