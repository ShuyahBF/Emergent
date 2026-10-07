// ConversationsWaSection.jsx — Lot 71.3 : rubrique « 💬 Conversations WhatsApp — transfert et en-tête » des Paramètres.
// Réglages du transfert de messages (lot 71) : modèle approuvé proposé par défaut hors fenêtre de 24 h et
// case « indiquer l'origine » ; rappel des pictogrammes de l'en-tête de conversation (lot 71.1).
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

export default function ConversationsWaSection() {
  const [reglages, setReglages] = useState(null);      // { modele_defaut: {name, language} | null, indiquer_origine }
  const [modeles, setModeles] = useState(null);        // modèles approuvés par Meta
  const [occupe, setOccupe] = useState(false);

  // Lecture des réglages et de la liste des modèles approuvés
  useEffect(() => {
    apiClient.get("/me/wa-transfert/reglages").then((r) => setReglages(r.data)).catch(() => setReglages({ modele_defaut: null, indiquer_origine: true }));
    apiClient.get("/me/whatsapp/templates").then((r) => setModeles(r.data.items || [])).catch(() => setModeles([]));
  }, []);

  // Enregistrement (administrateur ou superviseur)
  const enregistrer = async () => {
    setOccupe(true);
    const t = toast.loading("Patientez…");
    try {
      const r = await apiClient.put("/admin/wa-transfert/reglages", reglages);
      setReglages(r.data);
      toast.success("Réglages du transfert enregistrés", { id: t });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Enregistrement impossible", { id: t });
    } finally {
      setOccupe(false);
    }
  };

  if (!reglages) return <p className="text-sm text-slate-500">Patientez…</p>;
  const valeur = reglages.modele_defaut ? `${reglages.modele_defaut.name}|${reglages.modele_defaut.language}` : "";
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-conversations-wa">
      <h3 className="font-semibold text-slate-900">💬 Transfert de messages WhatsApp</h3>
      <p className="text-xs text-slate-600">
        Dans une conversation (Contacts), « Sélectionner » puis « Transférer » : jusqu'à 20 messages vers 10 contacts.
        Un contact qui n'a pas écrit depuis plus de 24 h ne peut recevoir qu'un <b>modèle approuvé par Meta</b> :
        le texte transféré est placé dans sa variable {"{{1}}"}.
      </p>
      {/* Modèle de repli proposé par défaut dans la fenêtre « Transférer » */}
      <label className="block text-xs font-semibold">Modèle approuvé proposé par défaut (hors fenêtre de 24 h)
        <select value={valeur} disabled={modeles === null}
          onChange={(e) => {
            const [name, language] = e.target.value.split("|");
            setReglages((x) => ({ ...x, modele_defaut: name ? { name, language } : null }));
          }}
          className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm">
          <option value="">{modeles === null ? "Patientez…" : "— aucun (choix à chaque transfert) —"}</option>
          {(modeles || []).map((m) => (
            <option key={`${m.name}|${m.language}`} value={`${m.name}|${m.language}`}>{m.name} ({m.language})</option>
          ))}
        </select>
      </label>
      {modeles && modeles.length === 0 && (
        <p className="text-[11px] text-amber-700">Aucun modèle approuvé : créez-en un dans le gestionnaire WhatsApp de Meta
          (catégorie « Utilitaire », une variable {"{{1}}"} entourée d'au moins une phrase fixe).</p>
      )}
      <label className="flex items-center gap-2 text-xs">
        <input type="checkbox" checked={!!reglages.indiquer_origine}
          onChange={(e) => setReglages((x) => ({ ...x, indiquer_origine: e.target.checked }))} />
        Cocher par défaut « Indiquer l'origine » (« Transféré de &lt;nom&gt; : »)
      </label>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] text-slate-500">
          En-tête de conversation (lot 71.1) : 📞 appeler · 🔔 alerte propriétaire · journal des appels · ↪ sélectionner · ⟳ actualiser.
        </p>
        <div className="flex gap-2">
          <Link to="/portal/contacts" className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">Ouvrir les Contacts ↗</Link>
          <button type="button" onClick={enregistrer} disabled={occupe}
            className="rounded-lg bg-sawali-blue px-4 py-1.5 text-sm font-semibold text-white disabled:opacity-50">Enregistrer</button>
        </div>
      </div>
    </div>
  );
}
