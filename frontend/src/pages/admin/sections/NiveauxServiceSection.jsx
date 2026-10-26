// NiveauxServiceSection.jsx — Lot 314 : rubrique « 📅 Niveaux de service (disponibilité en image) » des Paramètres.
// La disponibilité est vendue comme un ENGAGEMENT de prise en charge (contrat / standard / EXPRESS), pas comme un créneau horaire :
// le propriétaire règle ici les délais (listes déroulantes, « Autre… » pour une valeur libre), le tarif EXPRESS (affichage au choix)
// et peut PRÉVISUALISER l'image qui sera envoyée aux contacts depuis le calendrier de la discussion WhatsApp.
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import { apiClient } from "@/lib/api";
import { genererImageNiveaux } from "@/lib/niveauxImage";

const NIVEAUX = [["contrat", "Client sous contrat à jour (puce verte)"], ["standard", "Client sans contrat"], ["express", "⚡ EXPRESS (prestation payante)"]];

export default function NiveauxServiceSection() {
  const [config, setConfig] = useState(null);
  const [delais, setDelais] = useState([]);
  const [autre, setAutre] = useState({});            // niveau → saisie libre ouverte ?
  const [enCours, setEnCours] = useState(false);
  const [apercu, setApercu] = useState("");

  useEffect(() => {
    apiClient.get("/admin/niveaux-service").then((r) => { setConfig(r.data.config); setDelais(r.data.delais || []); })
      .catch((e) => toast.error(e?.response?.data?.detail || "Réglages indisponibles"));
  }, []);

  if (!config) return <div className="p-4"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>;

  const maj = (patch) => setConfig((c) => ({ ...c, ...patch }));
  const majNiveau = (cle, patch) => setConfig((c) => ({ ...c, niveaux: { ...c.niveaux, [cle]: { ...c.niveaux[cle], ...patch } } }));

  const enregistrer = async () => {
    setEnCours(true);
    try {
      const r = await apiClient.put("/admin/niveaux-service", config);
      setConfig(r.data.config);
      toast.success(r.data.config.configure ? "Niveaux de service enregistrés" : "Enregistré — renseignez les trois délais et activez pour proposer l'image dans les discussions");
    } catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible"); }
    finally { setEnCours(false); }
  };

  const previsualiser = async () => {
    try {
      const f = await genererImageNiveaux({ config });
      setApercu((ancien) => { if (ancien) URL.revokeObjectURL(ancien); return URL.createObjectURL(f); });
    } catch (e) { toast.error(e?.message || "Aperçu impossible"); }
  };

  return (
    <div className="space-y-4" data-testid="niveaux-service-section">
      <p className="text-sm text-slate-600">
        La disponibilité se vend comme un engagement de prise en charge, pas comme une heure précise. Réglez ici les trois niveaux ;
        l'image est ensuite envoyée au contact depuis le calendrier de la discussion (bouton « ⚡ Niveaux de service »), la même pour tous les contacts.
        Tant que les trois délais ne sont pas renseignés et la fonction activée, le bouton reste inactif : aucun engagement n'est annoncé par défaut.
      </p>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={config.actif} onChange={(e) => maj({ actif: e.target.checked })} /> Proposer l'image « Niveaux de service » dans les discussions
      </label>
      <label className="block text-xs text-slate-600">Titre de l'image (société)
        <input value={config.societe} maxLength={60} onChange={(e) => maj({ societe: e.target.value })} placeholder="SAWALI SMART SYSTEMS"
               className="mt-1 block w-full max-w-md px-3 py-2 border border-slate-300 rounded-lg text-sm" />
      </label>
      {NIVEAUX.map(([cle, titre]) => {
        const n = config.niveaux[cle];
        const libre = autre[cle] || (n.delai && !delais.includes(n.delai));
        return (
          <div key={cle} className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3 space-y-2" data-testid={`niveau-${cle}`}>
            <p className="text-sm font-medium text-slate-700">{titre}</p>
            <div className="grid sm:grid-cols-3 gap-2">
              <label className="text-xs text-slate-600">Intitulé
                <input value={n.libelle} maxLength={40} onChange={(e) => majNiveau(cle, { libelle: e.target.value })} className="mt-1 block w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" /></label>
              <label className="text-xs text-slate-600 sm:col-span-2">Description
                <input value={n.description} maxLength={80} onChange={(e) => majNiveau(cle, { description: e.target.value })} className="mt-1 block w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" /></label>
              <label className="text-xs text-slate-600">Délai de prise en charge
                {libre ? (
                  <input value={n.delai} maxLength={40} onChange={(e) => majNiveau(cle, { delai: e.target.value })} placeholder="ex. 3 heures ouvrées" className="mt-1 block w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" />
                ) : (
                  <select value={n.delai} onChange={(e) => (e.target.value === "__autre__" ? (setAutre((a) => ({ ...a, [cle]: true })), majNiveau(cle, { delai: "" })) : majNiveau(cle, { delai: e.target.value }))}
                          className="mt-1 block w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" data-testid={`niveau-delai-${cle}`}>
                    <option value="">— Choisir —</option>
                    {delais.map((d) => <option key={d} value={d}>{d}</option>)}
                    <option value="__autre__">Autre…</option>
                  </select>
                )}
              </label>
              {cle === "express" && (
                <>
                  <label className="text-xs text-slate-600">Tarif EXPRESS
                    <input value={n.tarif || ""} maxLength={40} onChange={(e) => majNiveau(cle, { tarif: e.target.value })} placeholder="ex. 25 000 FCFA ou « sur devis »" className="mt-1 block w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" /></label>
                  <label className="flex items-center gap-2 text-xs text-slate-700 sm:pt-5">
                    <input type="checkbox" checked={!!n.afficher_tarif} onChange={(e) => majNiveau(cle, { afficher_tarif: e.target.checked })} /> Afficher le tarif dans l'image (sinon : à traiter en conversation)
                  </label>
                </>
              )}
            </div>
          </div>
        );
      })}
      <label className="block text-xs text-slate-600">Mention en bas de l'image
        <input value={config.mention} maxLength={120} onChange={(e) => maj({ mention: e.target.value })} className="mt-1 block w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" /></label>
      <div className="flex flex-wrap gap-2 boutons-distincts">
        <button type="button" onClick={enregistrer} disabled={enCours} className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm disabled:opacity-50" data-testid="niveaux-enregistrer">
          {enCours ? "Enregistrement…" : "Enregistrer"}
        </button>
        <button type="button" onClick={previsualiser} className="px-3 py-1.5 rounded-lg bg-white border border-slate-300 hover:bg-slate-50 text-sm text-slate-700" data-testid="niveaux-apercu">Prévisualiser l'image</button>
      </div>
      <p className="text-xs text-slate-500">État : {config.configure ? "✅ prêt (activé, trois délais renseignés)" : "⏸ pas encore proposé dans les discussions"}</p>
      {apercu && <img src={apercu} alt="Aperçu des niveaux de service" className="max-w-sm rounded-lg ring-1 ring-slate-300" />}
    </div>
  );
}
