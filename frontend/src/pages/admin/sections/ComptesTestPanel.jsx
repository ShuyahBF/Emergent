// Lot 44 — Comptes de test en un clic (Admin).
// « Créer / remettre à neuf les comptes de test » : compte client TEST SAWALI (code
// TEST) + un utilisateur suivi par rôle de suivi, aux adresses test.<rôle>@<domaine
// interne> (code OTP affiché à l'écran). Le mot de passe saisi ici est haché côté
// serveur, jamais stocké en clair ni renvoyé. « Supprimer les comptes de test »
// efface uniquement les documents marqués est_test (et leurs données).
import React, { useState } from "react";
import { toast } from "sonner";
import { Beaker, Copy, Trash2, X } from "lucide-react";
import { apiClient } from "@/lib/api";
import PasswordInput from "@/components/PasswordInput";

export default function ComptesTestPanel({ onChange }) {
  const [ouvert, setOuvert] = useState(false);
  const [mdp, setMdp] = useState("");
  const [enCours, setEnCours] = useState(false);
  const [resultat, setResultat] = useState(null);

  const fermer = () => { setOuvert(false); setMdp(""); setResultat(null); };

  const creer = async (e) => {
    e.preventDefault();
    if (mdp.length < 10) { toast.error("Mot de passe : 10 caractères minimum"); return; }
    setEnCours(true);
    try {
      const r = await apiClient.post("/admin/comptes-test", { mot_de_passe: mdp });
      setResultat(r.data);
      setMdp("");   // le mot de passe n'est pas gardé dans la page
      toast.success(`${r.data.comptes.length} comptes de test prêts`);
      if (onChange) onChange();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Création impossible");
    } finally { setEnCours(false); }
  };

  const supprimer = async () => {
    if (!window.confirm("Supprimer TOUS les comptes de test (est_test) et les données qu'ils ont créées ?")) return;
    try {
      const r = await apiClient.delete("/admin/comptes-test");
      toast.success(`${r.data.comptes_supprimes} compte(s) de test supprimé(s)`);
      if (onChange) onChange();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Suppression impossible");
    }
  };

  const texteACopier = () => (resultat?.comptes || [])
    .map((c) => `${c.role}\t${c.email}\t${c.lien}`).join("\n");

  const copier = async () => {
    try {
      await navigator.clipboard.writeText(texteACopier());
      toast.success("Liste copiée");
    } catch {
      toast.error("Copie impossible : sélectionnez le texte à la main");
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOuvert(true)}
        className="inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 text-amber-800 px-3 py-2 text-sm hover:bg-amber-100"
        data-testid="comptes-test-btn"
      >
        <Beaker className="h-4 w-4" /> Créer / remettre à neuf les comptes de test
      </button>
      <button
        type="button"
        onClick={supprimer}
        className="inline-flex items-center gap-2 rounded-lg border border-rose-200 bg-white text-rose-700 px-3 py-2 text-sm hover:bg-rose-50"
        data-testid="comptes-test-supprimer"
      >
        <Trash2 className="h-4 w-4" /> Supprimer les comptes de test
      </button>

      {ouvert && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={fermer}>
          <div className="bg-white rounded-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="font-display font-semibold">Comptes de test (TEST SAWALI)</h3>
              <button onClick={fermer} aria-label="Fermer"><X className="h-4 w-4" /></button>
            </div>
            {!resultat ? (
              <form onSubmit={creer} className="p-4 space-y-3">
                <p className="text-sm text-slate-600">
                  Crée (ou remet à neuf) le compte client « TEST SAWALI » (code TEST) et un utilisateur suivi
                  par rôle de suivi. Les adresses sont au domaine interne : le code OTP s'affiche à l'écran.
                  Fonctions activées sur le client TEST : Formulaires et Sondages, OCR sur Pièces,
                  Ordonnances et stock, Maintenance des équipements, WhatsApp, discussion interne.
                </p>
                <div>
                  <label className="block text-xs font-semibold mb-1">Mot de passe commun (10 caractères minimum)</label>
                  <PasswordInput value={mdp} onChange={(e) => setMdp(e.target.value)} required minLength={10}
                                 autoComplete="new-password" testid="comptes-test-mdp"
                                 className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                  <p className="text-[11px] text-slate-500 mt-1">Haché côté serveur, jamais stocké en clair ni affiché ensuite.</p>
                </div>
                <div className="flex justify-end gap-2">
                  <button type="button" onClick={fermer} className="rounded-lg border border-slate-300 px-4 py-2 text-sm">Annuler</button>
                  <button type="submit" disabled={enCours} className="rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm disabled:opacity-50" data-testid="comptes-test-valider">
                    {enCours ? "Création…" : "Créer / remettre à neuf"}
                  </button>
                </div>
              </form>
            ) : (
              <div className="p-4 space-y-3">
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <p className="text-sm text-slate-600">
                    {resultat.comptes.length} comptes au domaine <strong>{resultat.domaine}</strong>. Ouvrez un lien
                    dans une fenêtre de navigation privée (sinon votre session Admin redirige vers l'administration).
                  </p>
                  <button onClick={copier} className="inline-flex items-center gap-1.5 rounded-lg bg-sawali-blue text-white px-3 py-1.5 text-sm" data-testid="comptes-test-copier">
                    <Copy className="h-4 w-4" /> Copier
                  </button>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm min-w-[520px]">
                    <thead className="text-xs uppercase text-slate-500">
                      <tr><th className="text-left py-1 pr-3">Rôle</th><th className="text-left py-1 pr-3">E-mail</th><th className="text-left py-1">Connexion</th></tr>
                    </thead>
                    <tbody>
                      {resultat.comptes.map((c) => (
                        <tr key={c.email} className="border-t border-slate-100">
                          <td className="py-1.5 pr-3">{c.role}</td>
                          <td className="py-1.5 pr-3 font-mono text-xs break-all">{c.email}</td>
                          <td className="py-1.5"><a href={c.lien} target="_blank" rel="noreferrer" className="text-sawali-blue hover:underline text-xs">Ouvrir</a></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
