// =====================================================================
// Lot 369 — « Mon compte » : mes passkeys (connexion par empreinte digitale).
// L'empreinte est vérifiée par l'appareil (Windows Hello avec le lecteur d'empreintes, téléphone, clé de sécurité) : SAWALI ne la reçoit jamais.
// Le mot de passe reste toujours possible. Rubrique affichée seulement si l'administrateur a activé la fonction.
// Backend : GET /api/auth/passkeys, DELETE /api/auth/passkeys/{id} ; enregistrement : lib/passkeys.js.
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Fingerprint, Loader2, Trash2 } from "lucide-react";
import { apiClient } from "@/lib/api";
import { enregistrerPasskey, messageErreurPasskey, passkeysSupportees } from "@/lib/passkeys";
import { formatDateHeure } from "@/components/DerniereSauvegarde";

export default function PasskeysSection() {
  const [donnees, setDonnees] = useState(null);
  const [nom, setNom] = useState("");
  const [enCours, setEnCours] = useState(false);

  const charger = useCallback(() => {
    apiClient.get("/auth/passkeys").then((r) => setDonnees(r.data)).catch(() => setDonnees({ enabled: false, passkeys: [] }));
  }, []);
  useEffect(() => { charger(); }, [charger]);

  async function ajouter() {
    setEnCours(true);
    toast("Patientez… validez avec votre empreinte (lecteur, téléphone ou clé de sécurité).");
    try {
      const liste = await enregistrerPasskey(nom.trim());
      setDonnees((d) => ({ ...d, passkeys: liste }));
      setNom("");
      toast.success("Passkey enregistrée : vous pouvez maintenant vous connecter avec votre empreinte.");
    } catch (e) {
      toast.error(messageErreurPasskey(e));
    } finally {
      setEnCours(false);
    }
  }

  async function retirer(p) {
    if (!window.confirm(`Retirer la passkey « ${p.nom} » ? Cet appareil ne pourra plus servir à vous connecter avec l'empreinte.`)) return;
    try {
      await apiClient.delete(`/auth/passkeys/${encodeURIComponent(p.id)}`);
      toast.success("Passkey retirée.");
      charger();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Retrait impossible");
    }
  }

  if (!donnees || !donnees.enabled) return null;   // fonction non activée par l'administrateur : rien à montrer
  const supportee = passkeysSupportees();
  const pleine = donnees.passkeys.length >= (donnees.max || 8);

  return (
    <section className="rounded-2xl bg-white p-5 ring-1 ring-slate-200" data-testid="section-passkeys">
      <h2 className="mb-1 flex items-center gap-2 font-display text-sm font-semibold text-slate-700">
        <Fingerprint className="h-4 w-4 text-sawali-blue" /> Connexion par empreinte digitale (passkeys)
      </h2>
      <p className="mb-3 text-xs text-slate-500">
        Connectez-vous d'un doigt, sans mot de passe ni code. L'empreinte est vérifiée par votre appareil (lecteur d'empreintes avec Windows Hello,
        téléphone Android ou iPhone, clé de sécurité à empreinte) : <b>SAWALI ne la reçoit jamais</b>. Votre mot de passe reste toujours possible.
        Sur un poste partagé par plusieurs personnes avec un seul compte Windows, préférez votre téléphone ou une clé de sécurité personnelle.
      </p>
      {donnees.passkeys.length === 0 ? (
        <p className="mb-3 text-xs text-slate-500" data-testid="passkeys-vide">Aucune passkey enregistrée.</p>
      ) : (
        <ul className="mb-3 divide-y divide-slate-100 rounded-lg ring-1 ring-slate-200" data-testid="passkeys-liste">
          {donnees.passkeys.map((p) => (
            <li key={p.id} className="flex items-center justify-between gap-3 px-3 py-2 text-xs">
              <span>
                <b className="text-slate-700">{p.nom}</b>
                <span className="ml-2 text-slate-500">ajoutée le {formatDateHeure(p.cree_le)} · {p.dernier_usage ? `dernière connexion le ${formatDateHeure(p.dernier_usage)}` : "jamais utilisée"}</span>
              </span>
              <button type="button" onClick={() => retirer(p)} title="Retirer cette passkey" aria-label={`Retirer la passkey ${p.nom}`}
                      className="rounded p-1 text-slate-400 hover:bg-rose-50 hover:text-rose-600" data-testid={`passkey-retirer-${p.id.slice(0, 8)}`}>
                <Trash2 className="h-4 w-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {!supportee ? (
        <p className="text-xs text-amber-700">Ce navigateur ne gère pas les passkeys : utilisez un navigateur récent (Chrome, Edge, Safari, Firefox).</p>
      ) : pleine ? (
        <p className="text-xs text-amber-700">Maximum atteint ({donnees.max} passkeys) : retirez-en une pour en ajouter.</p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <input value={nom} onChange={(e) => setNom(e.target.value)} maxLength={60} placeholder="Nom (ex. Portable de la caisse, Mon téléphone)"
                 aria-label="Nom de la passkey" className="min-w-[16rem] flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="passkey-nom" />
          <button type="button" onClick={ajouter} disabled={enCours}
                  className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue px-4 py-2 text-sm font-medium text-white hover:bg-sawali-blue-light disabled:opacity-50" data-testid="passkey-ajouter">
            {enCours ? <Loader2 className="h-4 w-4 animate-spin" /> : <Fingerprint className="h-4 w-4" />} Ajouter une passkey
          </button>
        </div>
      )}
    </section>
  );
}
