// WaLignesPanel.jsx — Lot 59 : plusieurs numéros WhatsApp SAWALI (« lignes » Liluvine).
//
// Affiché dans Administration → Paramètres → WhatsApp Business API.
// - Ligne principale : le Phone Number ID déjà saisi au-dessus (nom modifiable,
//   ex. « Liluvine Standard ») ;
// - Lignes supplémentaires : même compte WhatsApp (même jeton), chacune avec son
//   Phone Number ID, son nom, son numéro affiché et ses options :
//     • VIP : servie aux clients dont le montant du contrat atteint le seuil VIP ;
//     • Prospects : Liluvine y répond avec le prompt prospects (ex. numéro des publicités) ;
//     • Consignes : texte ajouté au prompt de Liluvine pour cette ligne ;
//     • Couleurs (lot 59.1) : fond et texte de la pastille affichée sur les messages reçus.
// Les valeurs sont enregistrées avec le bouton « Enregistrer » général de la page.
import React from "react";
import { Plus, Trash2 } from "lucide-react";
import PastilleLigneWa from "./PastilleLigneWa";   // Lot 59.1

// Lot 59.1 — couleurs proposées par défaut aux lignes supplémentaires (même ordre que le serveur)
const COULEURS_DEFAUT = [["#f59e0b", "#000000"], ["#2563eb", "#ffffff"], ["#7c3aed", "#ffffff"], ["#059669", "#ffffff"]];

// Lot 59.1 — choix des couleurs d'une pastille (fond + texte) avec aperçu
function ChoixCouleurs({ libelle, fond, texte, onFond, onTexte, testid }) {
  return (
    <div className="flex flex-wrap items-center gap-3 text-xs" data-testid={testid}>
      <label className="inline-flex items-center gap-1.5">
        Fond
        <input type="color" value={fond} onChange={(e) => onFond(e.target.value)} className="h-6 w-8 cursor-pointer rounded border border-slate-300" />
      </label>
      <label className="inline-flex items-center gap-1.5">
        Texte
        <input type="color" value={texte} onChange={(e) => onTexte(e.target.value)} className="h-6 w-8 cursor-pointer rounded border border-slate-300" />
      </label>
      {/* Aperçu de la pastille telle qu'elle apparaîtra sur les messages reçus */}
      <span className="text-slate-500">Aperçu :</span>
      <PastilleLigneWa libelle={libelle || "Ligne"} fond={fond} texte={texte} />
    </div>
  );
}

export default function WaLignesPanel({ s, upd }) {
  // Liste des lignes supplémentaires (tableau d'objets dans les paramètres globaux)
  const lignes = Array.isArray(s.wa_numeros) ? s.wa_numeros : [];

  // Remplace la liste entière dans l'état de la page (enregistrée au clic sur « Enregistrer »)
  const majLignes = (nouvelles) => upd("wa_numeros", nouvelles);

  // Modifie un champ d'une ligne donnée
  const majChamp = (index, champ, valeur) =>
    majLignes(lignes.map((l, i) => (i === index ? { ...l, [champ]: valeur } : l)));

  // Ajoute une ligne vide
  const ajouter = () =>
    majLignes([...lignes, {
      id: "", libelle: "", telephone: "", vip: false, prospects: false, complement_prompt: "",
      // Lot 59.1 — couleurs proposées selon le rang de la ligne
      couleur_fond: COULEURS_DEFAUT[lignes.length % COULEURS_DEFAUT.length][0],
      couleur_texte: COULEURS_DEFAUT[lignes.length % COULEURS_DEFAUT.length][1],
    }]);

  // Supprime une ligne (après confirmation)
  const supprimer = (index) => {
    if (!window.confirm("Supprimer cette ligne WhatsApp ? Les contacts qui lui étaient affectés repasseront en automatique.")) return;
    majLignes(lignes.filter((_, i) => i !== index));
  };

  return (
    <div className="rounded-xl ring-1 ring-emerald-200 bg-emerald-50/40 p-4 space-y-3" data-testid="wa-lignes-panel">
      <p className="text-sm font-semibold text-emerald-900">Lignes WhatsApp de Liluvine (plusieurs numéros)</p>
      <p className="text-xs text-slate-600">
        Ajoutez ici les autres numéros du <strong>même compte WhatsApp</strong> (même jeton). Liluvine répond toujours
        depuis le numéro qui a reçu le message. Dans le Centre de messagerie, chaque utilisateur suivi ne voit que les
        lignes qui lui sont attribuées (fiche de l'utilisateur suivi) ; superviseurs et administrateurs voient tout.
      </p>

      {/* Ligne principale : nom et numéro affiché */}
      <div className="grid sm:grid-cols-3 gap-3 items-end">
        <label className="block text-xs">
          <span className="font-medium text-slate-700">Nom de la ligne principale</span>
          <input
            className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
            value={s.wa_principal_libelle || ""}
            placeholder="Liluvine Standard"
            onChange={(e) => upd("wa_principal_libelle", e.target.value)}
            data-testid="wa-principal-libelle"
          />
        </label>
        <label className="block text-xs">
          <span className="font-medium text-slate-700">Numéro affiché (ligne principale)</span>
          <input
            className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
            value={s.wa_principal_telephone || ""}
            placeholder="+226 25 65 81 65"
            onChange={(e) => upd("wa_principal_telephone", e.target.value)}
            data-testid="wa-principal-telephone"
          />
        </label>
        <label className="block text-xs">
          <span className="font-medium text-slate-700">Seuil VIP — montant du contrat (vide = désactivé)</span>
          <input
            type="number"
            min="0"
            className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
            value={s.wa_seuil_vip || ""}
            placeholder="ex. 150000"
            // Vide = 0 = règle VIP désactivée (0 est bien enregistré, contrairement à une valeur vide)
            onChange={(e) => upd("wa_seuil_vip", e.target.value === "" ? 0 : Number(e.target.value))}
            data-testid="wa-seuil-vip"
          />
        </label>
      </div>
      {/* Lot 59.1 — couleurs de la pastille de la ligne principale (défaut : texte noir sur fond blanc) */}
      <ChoixCouleurs
        libelle={s.wa_principal_libelle || "Liluvine Standard"}
        fond={s.wa_principal_couleur_fond || "#ffffff"}
        texte={s.wa_principal_couleur_texte || "#000000"}
        onFond={(v) => upd("wa_principal_couleur_fond", v)}
        onTexte={(v) => upd("wa_principal_couleur_texte", v)}
        testid="wa-principal-couleurs"
      />

      {/* Lignes supplémentaires */}
      {lignes.map((l, i) => (
        <div key={i} className="rounded-lg bg-white ring-1 ring-slate-200 p-3 space-y-2" data-testid={`wa-ligne-${i}`}>
          <div className="grid sm:grid-cols-3 gap-2">
            <label className="block text-xs">
              <span className="font-medium text-slate-700">Phone Number ID (Meta)</span>
              <input
                className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm font-mono"
                value={l.id || ""}
                placeholder="1297304103473320"
                onChange={(e) => majChamp(i, "id", e.target.value.trim())}
              />
            </label>
            <label className="block text-xs">
              <span className="font-medium text-slate-700">Nom de la ligne</span>
              <input
                className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
                value={l.libelle || ""}
                placeholder="Liluvine VIP"
                onChange={(e) => majChamp(i, "libelle", e.target.value)}
              />
            </label>
            <label className="block text-xs">
              <span className="font-medium text-slate-700">Numéro affiché</span>
              <input
                className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
                value={l.telephone || ""}
                placeholder="+226 73 88 49 99"
                onChange={(e) => majChamp(i, "telephone", e.target.value)}
              />
            </label>
          </div>
          <div className="flex flex-wrap items-center gap-4 text-xs">
            <label className="inline-flex items-center gap-1.5">
              <input type="checkbox" checked={!!l.vip} onChange={(e) => majChamp(i, "vip", e.target.checked)} />
              Ligne VIP (clients au-dessus du seuil)
            </label>
            <label className="inline-flex items-center gap-1.5">
              <input type="checkbox" checked={!!l.prospects} onChange={(e) => majChamp(i, "prospects", e.target.checked)} />
              Ligne prospects (publicités : prompt prospects)
            </label>
            <button
              type="button"
              onClick={() => supprimer(i)}
              className="ml-auto inline-flex items-center gap-1 text-rose-600 hover:text-rose-800"
            >
              <Trash2 className="w-3.5 h-3.5" /> Supprimer
            </button>
          </div>
          {/* Lot 59.1 — couleurs de la pastille de cette ligne */}
          <ChoixCouleurs
            libelle={l.libelle}
            fond={l.couleur_fond || COULEURS_DEFAUT[i % COULEURS_DEFAUT.length][0]}
            texte={l.couleur_texte || COULEURS_DEFAUT[i % COULEURS_DEFAUT.length][1]}
            onFond={(v) => majChamp(i, "couleur_fond", v)}
            onTexte={(v) => majChamp(i, "couleur_texte", v)}
            testid={`wa-ligne-couleurs-${i}`}
          />
          <label className="block text-xs">
            <span className="font-medium text-slate-700">Consignes de Liluvine pour cette ligne (facultatif)</span>
            <textarea
              rows={2}
              className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
              value={l.complement_prompt || ""}
              placeholder="Ex. : client VIP — accueil personnalisé, proposer un rappel par un conseiller dédié."
              onChange={(e) => majChamp(i, "complement_prompt", e.target.value)}
            />
          </label>
        </div>
      ))}

      <button
        type="button"
        onClick={ajouter}
        className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700"
        data-testid="wa-ligne-ajouter"
      >
        <Plus className="w-3.5 h-3.5" /> Ajouter un numéro WhatsApp
      </button>
    </div>
  );
}
