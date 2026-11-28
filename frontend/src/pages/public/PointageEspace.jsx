// ============================================================================
// PointageEspace.jsx — Lot 498 : ESPACE POINTAGE du responsable d'un commerce (page /pointage-espace, sans compte SAWALI).
// Le responsable se connecte avec la CLÉ DE POINTAGE (CP-…) et le MOT DE PASSE de son commerce, transmis par SAWALI ; il crée ses
// inventaires, affiche le QR code aux auxiliaires, suit le comptage et exporte (JSON pour Aizenta, CSV pour Excel). Il ne voit que
// les inventaires de SON commerce (contrôle fait par le serveur).
// Backend : POST /api/pointage-espace/connexion puis /api/pointage-espace/… (jeton en en-tête X-Pointage-Jeton, valable 12 h).
// Lot 499 : l'Espace s'affiche dans la LANGUE du commerce (français ou anglais) ; avant la connexion, sélecteur FR / EN ; lien vers
// l'application Android (Loois mobile dans ShuyahStore : pointage complet sans Internet).
// Parallèle WinDev : une fenêtre de connexion (HOuvreConnexion + contrôle du mot de passe) qui ouvre ensuite la fenêtre principale.
// ============================================================================
import React, { useMemo, useState } from "react";
import { KeyRound, Languages, Loader2, LogIn, LogOut, Smartphone, Store } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import PasswordInput from "@/components/PasswordInput";
import EtatConnexion from "@/components/EtatConnexion";
import PointageInventaireSection from "@/pages/admin/sections/PointageInventaireSection";
import { URL_APP_ANDROID, traducteur } from "@/lib/i18nPointage";

const CLE_SESSION = "pointage:espace";
const lire = () => { try { return JSON.parse(sessionStorage.getItem(CLE_SESSION) || "null"); } catch { return null; } };
const ecrire = (v) => { try { if (v) sessionStorage.setItem(CLE_SESSION, JSON.stringify(v)); else sessionStorage.removeItem(CLE_SESSION); } catch { /* stockage indisponible */ } };

export default function PointageEspace() {
  const [session, setSession] = useState(lire);          // {jeton, commerce} — gardée le temps de l'onglet seulement
  const [cle, setCle] = useState("");
  const [mdp, setMdp] = useState("");
  const [attente, setAttente] = useState(false);
  // Langue : celle du commerce une fois connecté ; avant, celle du navigateur (modifiable)
  const [langueChoisie, setLangueChoisie] = useState(() => ((navigator.language || "fr").startsWith("en") ? "en" : "fr"));
  const langue = session?.commerce?.langue || langueChoisie;
  const t = traducteur(langue);

  const deconnecter = (message) => { ecrire(null); setSession(null); if (message) toast.info(t(message)); };
  // Objet stable passé à la section : jeton + commerce, et retour à la connexion si le serveur répond 401
  const espace = useMemo(() => (session ? { ...session, onExpire: () => deconnecter("Session expirée ou clé révoquée : reconnectez-vous.") } : null), [session]);   // eslint-disable-line react-hooks/exhaustive-deps

  const connecter = async () => {
    setAttente(true);
    const id = toast.loading(t("Patientez…"));
    try {
      const { data } = await apiClient.post("/pointage-espace/connexion", { cle, mot_de_passe: mdp });
      const s = { jeton: data.jeton, commerce: data.commerce };
      ecrire(s); setSession(s); setMdp("");
      toast.success(traducteur(data.commerce.langue)("Bienvenue, {nom}.", { nom: data.commerce.structure?.libelle }), { id });
    } catch (e) { toast.error(e.response?.data?.detail || t("Connexion impossible."), { id }); }
    setAttente(false);
  };

  if (!session) {
    return (
      <main className="flex min-h-[100dvh] items-center justify-center bg-gradient-to-br from-sky-50 via-white to-violet-50 px-4">
        <div className="w-full max-w-md rounded-2xl border bg-white p-6 shadow-lg">
          <div className="mb-4 flex flex-col items-center gap-2 text-center">
            <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-sky-600 text-white"><Store className="h-7 w-7" aria-hidden="true" /></span>
            <h1 className="text-xl font-bold text-slate-900">{t("Espace pointage")}</h1>
            <p className="text-sm text-slate-600">{t("Inventaires de votre commerce, comptés au téléphone.")}</p>
            <label className="flex items-center gap-1 text-xs text-slate-500"><Languages className="h-4 w-4" aria-hidden="true" />
              <select value={langueChoisie} onChange={(e) => setLangueChoisie(e.target.value)} className="rounded border px-1 py-0.5" aria-label="Langue / Language">
                <option value="fr">Français</option><option value="en">English</option>
              </select>
            </label>
          </div>
          <label className="block text-sm font-semibold text-slate-700">{t("Clé de pointage")}
            <input value={cle} onChange={(e) => setCle(e.target.value.toUpperCase())} placeholder="CP-K7MP2Q" maxLength={12} autoComplete="username"
                   className="mt-1 w-full rounded-xl border px-4 py-3 font-mono text-lg tracking-wider" />
          </label>
          <label className="mt-3 block text-sm font-semibold text-slate-700">{t("Mot de passe")}
            <PasswordInput value={mdp} onChange={(e) => setMdp(e.target.value)} placeholder="abcd-1234" autoComplete="current-password"
                           onKeyDown={(e) => { if (e.key === "Enter" && cle && mdp) connecter(); }}
                           className="mt-1 w-full rounded-xl border px-4 py-3 text-lg tracking-wider" />
          </label>
          <button type="button" onClick={connecter} disabled={!cle || mdp.length < 4 || attente}
                  className="mt-5 flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-600 py-3 text-lg font-bold text-white disabled:opacity-40">
            {attente ? <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" /> : <LogIn className="h-5 w-5" aria-hidden="true" />}{t("Se connecter")}
          </button>
          <p className="mt-3 flex items-start gap-2 text-xs text-slate-500"><KeyRound className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            {t("La clé et le mot de passe sont remis par SAWALI à chaque commerce autorisé au pointage.")}</p>
          <a href={URL_APP_ANDROID} target="_blank" rel="noopener noreferrer"
             className="mt-3 flex items-center justify-center gap-2 rounded-xl border border-sky-200 bg-sky-50 px-3 py-2 text-sm font-semibold text-sky-800">
            <Smartphone className="h-4 w-4" aria-hidden="true" />{t("Télécharger l'application Android (pointage hors connexion)")}
          </a>
          {/* État du serveur et version (règle des pages de connexion) */}
          <EtatConnexion className="mt-4 justify-center" compact />
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-[100dvh] bg-slate-50">
      <header className="flex items-center justify-between gap-2 border-b bg-white px-4 py-3">
        <div className="min-w-0">
          <p className="truncate font-bold text-slate-900">{session.commerce.structure?.libelle}</p>
          <p className="text-xs text-slate-500">{session.commerce.structure?.type} · {t("Clé de pointage")} <b className="font-mono text-sky-700">{session.commerce.cle}</b></p>
        </div>
        <button type="button" onClick={() => deconnecter("Déconnecté.")} title={t("Se déconnecter")} aria-label={t("Se déconnecter")}
                className="inline-flex h-11 w-11 items-center justify-center rounded-full bg-rose-100 text-rose-700"><LogOut className="h-5 w-5" aria-hidden="true" /></button>
      </header>
      <div className="mx-auto max-w-5xl p-4">
        <PointageInventaireSection espace={espace} />
        <EtatConnexion className="mt-6 justify-center" compact />
      </div>
    </main>
  );
}
