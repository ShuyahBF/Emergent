// =====================================================================
// Lot 52 — Section « Service d'envoi des e-mails (Resend, ZeptoMail, Brevo, SMTP) »
// (Paramètres, onglet Communications ; réservé au super-admin SAWALI).
// - Liste « Service d'envoi » : Resend / ZeptoMail (Zoho) / Brevo / SMTP, plus « Désactivé ».
// - Champs communs : adresse d'expéditeur, nom affiché, interrupteur actif.
// - Selon le choix : clé API (Resend, Brevo), clé API + région (ZeptoMail), champs SMTP existants.
// - Champ secret vide = valeur conservée ; aucune clé n'est jamais renvoyée par le serveur.
// - « Envoyer un essai » : utilise les réglages ENREGISTRÉS et affiche le message du fournisseur.
// Backend : routes/fournisseurs_email.py (/api/admin/email-fournisseur).
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { AlertTriangle, CheckCircle2, Loader2, Send, XCircle } from "lucide-react";
import { apiClient } from "@/lib/api";

const LIBELLES = { resend: "Resend", zeptomail: "ZeptoMail (Zoho)", brevo: "Brevo", smtp: "SMTP", desactive: "Désactivé" };
const REGIONS = { "api.zeptomail.com": "International (.com)", "api.zeptomail.eu": "Europe (.eu)", "api.zeptomail.in": "Inde (.in)" };
const SOURCES = {
  ecran: "réglages de cet écran",
  ancien_smtp: "anciens réglages SMTP",
  "env:RESEND_API_KEY": "variables d'environnement (RESEND_API_KEY)",
  "env:SMTP": "variables d'environnement (SMTP)",
  "env:BREVO_API_KEY": "variables d'environnement (BREVO_API_KEY)",
  "env:ZEPTOMAIL_API_KEY": "variables d'environnement (ZEPTOMAIL_API_KEY)",
};
const erreurDe = (e, d) => { const x = e?.response?.data?.detail; return Array.isArray(x) ? x.map((i) => i.msg).join(" ; ") : x || d; };
const champ = "w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm";

// Saisie initiale à partir de la vue du serveur (les secrets restent vides : vide = conservé)
function saisieDepuis(v) {
  return {
    fournisseur: v.fournisseur, actif: !!v.actif, expediteur: v.expediteur || "", nom_affiche: v.nom_affiche || "",
    cle: "", zeptomail_hote: v.zeptomail_hote || "api.zeptomail.com",
    smtp: { hote: v.smtp.hote || "", port: v.smtp.port || 587, utilisateur: v.smtp.utilisateur || "", mot_de_passe: "", starttls: v.smtp.starttls !== false },
  };
}

export default function EmailFournisseurSection() {
  const [vue, setVue] = useState(null);
  const [saisie, setSaisie] = useState(null);
  const [refuse, setRefuse] = useState(false);
  const [occupe, setOccupe] = useState(false);
  const [destinataire, setDestinataire] = useState("");
  const [essai, setEssai] = useState(null);
  const [journal, setJournal] = useState(null);

  const charger = useCallback(async () => {
    try {
      const [v, j] = await Promise.all([apiClient.get("/admin/email-fournisseur"), apiClient.get("/admin/email-fournisseur/journal?limite=10")]);
      setVue(v.data);
      setSaisie(saisieDepuis(v.data));
      setJournal(j.data);
    } catch (e) {
      if (e?.response?.status === 403) setRefuse(true);
      else toast.error(erreurDe(e, "Chargement impossible"));
    }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  async function enregistrer() {
    setOccupe(true);
    try {
      const corps = { fournisseur: saisie.fournisseur, actif: saisie.actif, expediteur: saisie.expediteur.trim(), nom_affiche: saisie.nom_affiche };
      if (saisie.cle.trim()) corps.cle = saisie.cle.trim();
      if (saisie.fournisseur === "zeptomail") corps.zeptomail_hote = saisie.zeptomail_hote;
      if (saisie.fournisseur === "smtp") {
        const s = saisie.smtp;
        corps.smtp = { hote: s.hote.trim(), port: parseInt(s.port, 10) || 587, utilisateur: s.utilisateur.trim(), starttls: !!s.starttls };
        if (s.mot_de_passe) corps.smtp.mot_de_passe = s.mot_de_passe;
      }
      const r = await apiClient.put("/admin/email-fournisseur", corps);
      setVue(r.data);
      setSaisie(saisieDepuis(r.data));
      toast.success("Service d'envoi enregistré");
      const j = await apiClient.get("/admin/email-fournisseur/journal?limite=10");
      setJournal(j.data);
    } catch (e) {
      toast.error(erreurDe(e, "Enregistrement impossible"));
    } finally {
      setOccupe(false);
    }
  }

  async function envoyerEssai() {
    setOccupe(true);
    setEssai(null);
    try {
      const r = await apiClient.post("/admin/email-fournisseur/essai", destinataire.trim() ? { destinataire: destinataire.trim() } : {});
      setEssai(r.data);
      if (r.data.ok) toast.success(`E-mail d'essai envoyé à ${r.data.destinataire}`);
      const j = await apiClient.get("/admin/email-fournisseur/journal?limite=10");
      setJournal(j.data);
    } catch (e) {
      setEssai({ ok: false, erreur: erreurDe(e, "Essai impossible") });
    } finally {
      setOccupe(false);
    }
  }

  if (refuse) return <Cadre><p className="text-sm text-slate-600">Réservé au super-administrateur SAWALI.</p></Cadre>;
  if (!vue || !saisie) {
    return <Cadre><p className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Chargement…</p></Cadre>;
  }
  const f = saisie.fournisseur;
  const http = ["resend", "zeptomail", "brevo"].includes(f);
  const aCle = http && vue.cles?.[f]?.a_cle;
  const eff = vue.effectif || {};
  const majSmtp = (k, v) => setSaisie({ ...saisie, smtp: { ...saisie.smtp, [k]: v } });

  return (
    <Cadre>
      {/* Service réellement utilisé maintenant (réglages enregistrés, anciens réglages ou repli) */}
      <p className={`rounded-lg border p-2 text-xs ${eff.fournisseur ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-orange-200 bg-orange-50 text-orange-800"}`}
        data-testid="email-fournisseur-effectif">
        {eff.fournisseur
          ? <>Envoi actuel : <strong>{LIBELLES[eff.fournisseur]}</strong> depuis <strong>{eff.expediteur}</strong> ({SOURCES[eff.source] || eff.source}).</>
          : <>Aucun e-mail ne part actuellement : {eff.raison || "aucun service configuré"}.</>}
      </p>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1 text-xs text-slate-600">
          <span className="font-semibold">Service d'envoi</span>
          <select className={champ} value={f} disabled={occupe} data-testid="email-fournisseur-choix"
            onChange={(e) => setSaisie({ ...saisie, fournisseur: e.target.value, cle: "" })}>
            {(vue.choix || []).map((c) => <option key={c.valeur} value={c.valeur}>{LIBELLES[c.valeur] || c.libelle}</option>)}
          </select>
        </label>
        <label className="flex items-start gap-2 pt-5 text-xs text-slate-700">
          <input type="checkbox" className="mt-0.5" checked={saisie.actif} disabled={occupe || f === "desactive"} data-testid="email-fournisseur-actif"
            onChange={(e) => setSaisie({ ...saisie, actif: e.target.checked })} />
          <span>Envoi des e-mails actif</span>
        </label>
      </div>

      {/* Ligne d'aide du fournisseur choisi, avec le lien d'inscription */}
      {vue.aides?.[f] && f !== "smtp" && (
        <p className="text-xs text-slate-500" data-testid="email-fournisseur-aide">
          {vue.aides[f].texte}{" "}
          <a href={vue.aides[f].lien} target="_blank" rel="noreferrer" className="text-sawali-blue underline">S'inscrire</a>
        </p>
      )}

      {f !== "desactive" && (
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1 text-xs text-slate-600">
            <span className="font-semibold">Adresse d'expéditeur</span>
            <input type="email" className={champ} value={saisie.expediteur} disabled={occupe} placeholder="no-reply@votre-domaine.com"
              data-testid="email-fournisseur-expediteur" onChange={(e) => setSaisie({ ...saisie, expediteur: e.target.value })} />
            <span className="block text-[11px] text-slate-400">Sur un domaine validé chez le fournisseur.</span>
          </label>
          <label className="space-y-1 text-xs text-slate-600">
            <span className="font-semibold">Nom affiché</span>
            <input type="text" maxLength={60} className={champ} value={saisie.nom_affiche} disabled={occupe} placeholder="SAWALI SMART SYSTEMS"
              data-testid="email-fournisseur-nom" onChange={(e) => setSaisie({ ...saisie, nom_affiche: e.target.value })} />
          </label>
        </div>
      )}

      {http && (
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1 text-xs text-slate-600">
            <span className="font-semibold">Clé API {LIBELLES[f]}</span>
            <input type="password" autoComplete="new-password" className={champ} value={saisie.cle} disabled={occupe}
              placeholder={aCle ? "(déjà définie — laisser vide pour la conserver)" : "Collez la clé API"}
              data-testid="email-fournisseur-cle" onChange={(e) => setSaisie({ ...saisie, cle: e.target.value })} />
          </label>
          {f === "zeptomail" && (
            <label className="space-y-1 text-xs text-slate-600">
              <span className="font-semibold">Région ZeptoMail</span>
              <select className={champ} value={saisie.zeptomail_hote} disabled={occupe} data-testid="email-fournisseur-region"
                onChange={(e) => setSaisie({ ...saisie, zeptomail_hote: e.target.value })}>
                {(vue.zeptomail_hotes || Object.keys(REGIONS)).map((h) => <option key={h} value={h}>{REGIONS[h] || h}</option>)}
              </select>
            </label>
          )}
        </div>
      )}

      {f === "smtp" && (
        <>
          <p className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800" data-testid="email-fournisseur-avertissement-smtp">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" /> {vue.avertissement_smtp}
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1 text-xs text-slate-600"><span className="font-semibold">Hôte</span>
              <input className={champ} value={saisie.smtp.hote} disabled={occupe} placeholder="smtp.gmail.com" data-testid="smtp-host" onChange={(e) => majSmtp("hote", e.target.value)} /></label>
            <label className="space-y-1 text-xs text-slate-600"><span className="font-semibold">Port</span>
              <input type="number" className={champ} value={saisie.smtp.port} disabled={occupe} placeholder="587" data-testid="smtp-port" onChange={(e) => majSmtp("port", e.target.value)} /></label>
            <label className="space-y-1 text-xs text-slate-600"><span className="font-semibold">Utilisateur</span>
              <input className={champ} value={saisie.smtp.utilisateur} disabled={occupe} data-testid="smtp-user" onChange={(e) => majSmtp("utilisateur", e.target.value)} /></label>
            <label className="space-y-1 text-xs text-slate-600"><span className="font-semibold">Mot de passe</span>
              <input type="password" autoComplete="new-password" className={champ} value={saisie.smtp.mot_de_passe} disabled={occupe} data-testid="smtp-password"
                placeholder={vue.smtp.a_mot_de_passe ? "(déjà défini — laisser vide pour le conserver)" : ""} onChange={(e) => majSmtp("mot_de_passe", e.target.value)} /></label>
          </div>
          <label className="flex items-center gap-2 text-xs text-slate-700">
            <input type="checkbox" checked={saisie.smtp.starttls} disabled={occupe} data-testid="smtp-tls" onChange={(e) => majSmtp("starttls", e.target.checked)} />
            Utiliser STARTTLS (décoché : SSL direct, port 465)
          </label>
        </>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" disabled={occupe} onClick={enregistrer} data-testid="email-fournisseur-enregistrer"
          className="rounded-lg bg-sky-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-sky-800 disabled:opacity-50">
          Enregistrer le service d'envoi
        </button>
        {vue.modifie_le && <span className="text-[11px] text-slate-400">Modifié le {new Date(vue.modifie_le).toLocaleString("fr-FR")} par {vue.modifie_par}</span>}
      </div>

      {/* Essai avec les réglages enregistrés */}
      <div className="space-y-2 rounded-lg border border-slate-200 p-3">
        <p className="text-xs text-slate-600">L'essai utilise les réglages <strong>enregistrés</strong> (enregistrez d'abord vos modifications).</p>
        <div className="flex flex-wrap items-center gap-2">
          <input type="email" className="min-w-[220px] flex-1 rounded-lg border border-slate-300 px-2 py-1.5 text-sm" value={destinataire} disabled={occupe}
            placeholder="Destinataire (par défaut : votre adresse)" data-testid="email-fournisseur-essai-dest" onChange={(e) => setDestinataire(e.target.value)} />
          <button type="button" disabled={occupe} onClick={envoyerEssai} data-testid="email-fournisseur-essai"
            className="inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-semibold text-sky-800 ring-1 ring-sky-300 hover:bg-sky-50 disabled:opacity-50">
            {occupe ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />} Envoyer un essai
          </button>
        </div>
        {essai && (
          <p className={`flex items-start gap-2 text-xs ${essai.ok ? "text-emerald-700" : "text-red-700"}`} data-testid="email-fournisseur-essai-resultat">
            {essai.ok ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5" /> : <XCircle className="mt-0.5 h-3.5 w-3.5" />}
            {essai.ok ? `Envoyé par ${LIBELLES[essai.fournisseur]} à ${essai.destinataire}.` : essai.erreur}
          </p>
        )}
      </div>

      {/* Journal : modifications des réglages et derniers envois */}
      {journal && (
        <details className="text-xs text-slate-600">
          <summary className="cursor-pointer font-semibold">Journal (modifications et derniers envois)</summary>
          <div className="mt-2 grid gap-3 md:grid-cols-2">
            <ul className="space-y-1" data-testid="email-fournisseur-journal-modifs">
              {(journal.modifications || []).length === 0 && <li className="text-slate-400">Aucune modification.</li>}
              {(journal.modifications || []).map((m, i) => (
                <li key={i}>{new Date(m.le).toLocaleString("fr-FR")} — {m.par?.email} — {LIBELLES[m.fournisseur] || m.fournisseur} ({(m.champs || []).join(", ")})</li>
              ))}
            </ul>
            <ul className="space-y-1" data-testid="email-fournisseur-journal-envois">
              {(journal.envois || []).length === 0 && <li className="text-slate-400">Aucun envoi.</li>}
              {(journal.envois || []).map((e, i) => (
                <li key={i} className={e.statut === "ENVOYE" ? "" : "text-red-700"}>
                  {new Date(e.le).toLocaleString("fr-FR")} — {e.statut} — {LIBELLES[e.fournisseur] || "—"} — {e.destinataire}{e.erreur ? ` : ${e.erreur}` : ""}
                </li>
              ))}
            </ul>
          </div>
        </details>
      )}
    </Cadre>
  );
}

function Cadre({ children }) {
  return (
    <section className="space-y-4 rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200" data-testid="section-email-fournisseur">
      <h2 className="font-display text-lg font-bold text-slate-900">✉️ Service d'envoi des e-mails (Resend, ZeptoMail, Brevo, SMTP)</h2>
      {children}
    </section>
  );
}
