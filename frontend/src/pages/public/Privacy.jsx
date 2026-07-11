import React, { useEffect, useState } from "react";
import { Shield, Calendar, Database, Share2, Mail, Phone, MapPin } from "lucide-react";
import { apiClient } from "@/lib/api";

// Iter43-fix17 (2026-06) — Page /privacy autonome conforme à la politique
// Google API Services User Data Policy (https://developers.google.com/terms/api-services-user-data-policy),
// notamment l'exigence « Limited Use » pour les scopes Google Workspace (Calendar/Gmail/Drive).
// Une URL courte et directe `/privacy` est exigée par Google Search Console lors
// de la vérification d'un site, et par OAuth Consent Screen pour les apps qui
// demandent des scopes restreints.
export default function PrivacyPage() {
  const [info, setInfo] = useState(null);
  useEffect(() => {
    // Iter43-fix24as (2026-02) — TikTok validation requirement : la page Privacy
    // doit avoir un titre qui contient EXACTEMENT le nom de l'app (« sawalismartsystems »).
    document.title = "sawalismartsystems Privacy Policy";
    apiClient
      .get("/company-info")
      .then((r) => setInfo(r.data))
      .catch(() => {});
    return () => { document.title = "sawalismartsystems — SAWALI SMART SYSTEMS"; };
  }, []);

  const contactEmail = info?.email || "contact@sawalismartsystems.com";
  const contactPhone = info?.phone || "—";
  const contactAddress = [info?.address, info?.city, info?.country].filter(Boolean).join(", ") || "Ouagadougou, Burkina Faso";
  const lastUpdated = "14 juin 2026";

  return (
    <section
      className="mx-auto max-w-4xl px-4 sm:px-6 lg:px-8 py-12 lg:py-16 text-slate-200"
      data-testid="privacy-page"
    >
      <header className="mb-10">
        {/* Iter43-fix24az-h (2026-02-26) — TikTok App Review : afficher l'icône
            sawalismartsystems en tête de page (obligatoire d'après le reviewer). */}
        <div className="flex items-center gap-3 mb-6" data-testid="app-icon-header">
          <img
            src="/logo.png"
            alt="sawalismartsystems app icon"
            className="h-12 w-12 rounded-lg ring-1 ring-white/10 bg-white/5 p-1 object-contain"
            data-testid="app-icon-logo"
          />
          <span className="text-sm sm:text-base font-semibold text-white tracking-tight">
            sawalismartsystems
          </span>
        </div>
        <p className="text-xs uppercase tracking-[0.3em] text-sawali-blue-light mb-2">
          Mentions légales · Privacy Policy
        </p>
        <h1 className="text-3xl sm:text-4xl font-display font-bold text-white flex items-center gap-3">
          <Shield className="h-8 w-8 text-sawali-blue-light" />
          sawalismartsystems Privacy Policy
        </h1>
        <p className="mt-3 text-slate-400 text-sm">
          Dernière mise à jour : <strong className="text-slate-200">{lastUpdated}</strong>
        </p>
        <p className="mt-4 text-slate-300 leading-relaxed">
          La présente politique décrit comment <strong>SAWALI SMART SYSTEMS</strong>
          (« nous », « notre » ou « la Société ») collecte, utilise, conserve et partage les
          données des utilisateurs de ses sites et applications, y compris les données
          accessibles via les <strong>API Google</strong> (Google Agenda, Gmail, Drive, etc.)
          lorsque l'utilisateur connecte son compte Google à notre application.
        </p>
      </header>

      <div className="space-y-8">
        {/* 1. Données collectées */}
        <Section icon={Database} title="1. Données utilisateur collectées">
          <p>
            Selon la fonctionnalité utilisée, nous pouvons collecter les catégories de
            données suivantes :
          </p>
          <ul className="list-disc ml-6 space-y-1 mt-2">
            <li>
              <strong>Identité &amp; contact</strong> : nom complet, adresse email, numéro
              de téléphone, entreprise, photo de profil.
            </li>
            <li>
              <strong>Authentification</strong> : mot de passe (haché bcrypt), jetons OAuth,
              codes OTP (à usage unique, supprimés après usage).
            </li>
            <li>
              <strong>Données métier</strong> : contacts CRM, rendez-vous, tickets d'incident,
              factures, paiements, formations, notes internes, conversations WhatsApp.
            </li>
            <li>
              <strong>Données techniques</strong> : adresse IP, type de navigateur, journaux
              d'audit (login, actions admin), identifiants de session.
            </li>
            <li>
              <strong>Cookies &amp; analytics</strong> : cookies fonctionnels, identifiants
              PostHog (analyse d'usage anonymisée). Voir notre bannière cookies.
            </li>
          </ul>
        </Section>

        {/* 2. Données Google */}
        <Section icon={Calendar} title="2. Données Google Agenda et autres API Google">
          <p>
            Lorsque vous connectez votre compte Google à SAWALI SMART SYSTEMS via OAuth 2.0,
            nous demandons uniquement les <strong>scopes strictement nécessaires</strong> à
            la fonctionnalité que vous utilisez. Conformément à la
            {" "}<a
              href="https://developers.google.com/terms/api-services-user-data-policy"
              target="_blank"
              rel="noopener noreferrer"
              className="text-sawali-blue-light underline hover:text-white"
            >
              Google API Services User Data Policy
            </a>{" "}
            (y compris l'exigence <strong>« Limited Use »</strong>), nous nous engageons à :
          </p>
          <ul className="list-disc ml-6 space-y-2 mt-2">
            <li>
              <strong>Usage limité</strong> : les données Google Agenda (événements,
              participants, dates, lieux) sont utilisées <em>exclusivement</em> pour
              synchroniser vos rendez-vous CRM avec votre calendrier Google, vous afficher
              vos prochains événements dans votre tableau de bord, et créer/modifier les
              événements que vous nous demandez explicitement de créer.
            </li>
            <li>
              <strong>Pas de revente</strong> : nous ne vendons jamais les données obtenues
              via les API Google à des tiers.
            </li>
            <li>
              <strong>Pas de publicité ciblée</strong> : ces données ne sont jamais
              utilisées pour de la publicité personnalisée ni partagées avec des
              annonceurs.
            </li>
            <li>
              <strong>Pas d'entraînement de modèles IA</strong> : les contenus de votre
              Google Agenda, Gmail ou Drive ne sont pas envoyés à des modèles d'IA
              générative pour entraînement, fine-tuning ou amélioration de modèles.
            </li>
            <li>
              <strong>Accès humain restreint</strong> : aucun salarié de SAWALI SMART
              SYSTEMS ne lit vos données Google sauf (a) avec votre consentement explicite
              écrit, (b) pour des raisons de sécurité (lutte contre l'abus), (c) pour
              respecter une obligation légale, ou (d) de manière agrégée et anonymisée
              pour le débogage technique.
            </li>
            <li>
              <strong>Transferts limités</strong> : nous ne transférons les données obtenues
              via les API Google qu'à des sous-traitants techniques nécessaires au
              fonctionnement du service (hébergeur, base de données), sous contrats DPA
              garantissant le même niveau de protection.
            </li>
          </ul>
          <p className="mt-3 text-sm text-slate-400">
            Vous pouvez à tout moment révoquer notre accès à votre compte Google via{" "}
            <a
              href="https://myaccount.google.com/permissions"
              target="_blank"
              rel="noopener noreferrer"
              className="text-sawali-blue-light underline hover:text-white"
            >
              myaccount.google.com/permissions
            </a>
            .
          </p>
        </Section>

        {/* 3. Stockage & conservation */}
        <Section icon={Database} title="3. Stockage et conservation des données">
          <ul className="list-disc ml-6 space-y-1 mt-2">
            <li>
              <strong>Hébergement</strong> : base de données MongoDB chiffrée au repos,
              hébergée chez un prestataire conforme RGPD (Union Européenne ou pays
              disposant d'une décision d'adéquation).
            </li>
            <li>
              <strong>Chiffrement en transit</strong> : toutes les communications avec nos
              serveurs sont chiffrées en TLS 1.2+ (HTTPS obligatoire).
            </li>
            <li>
              <strong>Jetons OAuth Google</strong> : refresh tokens stockés chiffrés
              (algorithme Fernet AES-128) en base. Les access tokens courts sont
              régénérés à la demande.
            </li>
            <li>
              <strong>Durée de conservation</strong> :
              <ul className="list-circle ml-6 mt-1 space-y-0.5">
                <li>Compte actif : tant que vous utilisez le service.</li>
                <li>Compte inactif : suppression automatique des données techniques après <strong>36 mois</strong> sans connexion.</li>
                <li>Données comptables (factures, paiements) : conservation <strong>10 ans</strong> conformément aux obligations légales.</li>
                <li>Journaux d'audit : <strong>24 mois</strong> maximum.</li>
                <li>Jetons OAuth révoqués ou expirés : suppression sous <strong>30 jours</strong>.</li>
              </ul>
            </li>
          </ul>
        </Section>

        {/* 4. Partage avec des tiers */}
        <Section icon={Share2} title="4. Avec qui les données sont partagées">
          <p>
            Nous ne <strong>vendons jamais</strong> vos données. Nous partageons des
            données strictement limitées avec les catégories de tiers suivantes :
          </p>
          <ul className="list-disc ml-6 space-y-1 mt-2">
            <li>
              <strong>Hébergeur cloud</strong> (Emergent Labs / fournisseur Kubernetes) :
              stockage chiffré des données et exécution du service.
            </li>
            <li>
              <strong>Prestataires de communication</strong> : Meta WhatsApp Cloud API
              (envoi de messages), SMTP/Gmail (envoi d'emails), Twilio (SMS).
            </li>
            <li>
              <strong>Prestataires de paiement</strong> : Stripe, PawaPay — uniquement
              les données nécessaires à la transaction (nom, email, montant). Aucune
              donnée bancaire complète ne transite par nos serveurs.
            </li>
            <li>
              <strong>Prestataires IA</strong> : Anthropic (Claude), OpenAI, Google Gemini
              via Emergent Universal Key — les prompts envoyés sont strictement limités
              à la requête de l'utilisateur. Aucun prompt n'est utilisé pour entraîner
              les modèles (politiques zero-retention activées).
            </li>
            <li>
              <strong>Autorités</strong> : sur réquisition judiciaire ou obligation légale.
            </li>
          </ul>
          <p className="mt-3">
            Tous nos sous-traitants sont liés par contrat à respecter au minimum les
            mêmes obligations de confidentialité et de sécurité que celles décrites
            dans cette politique.
          </p>
        </Section>

        {/* 5. Vos droits */}
        <Section icon={Shield} title="5. Vos droits (RGPD)">
          <p>Vous disposez à tout moment des droits suivants sur vos données :</p>
          <ul className="list-disc ml-6 space-y-1 mt-2">
            <li><strong>Droit d'accès</strong> : obtenir une copie de vos données.</li>
            <li><strong>Droit de rectification</strong> : corriger les données inexactes.</li>
            <li>
              <strong>Droit à l'effacement</strong> (« droit à l'oubli ») : suppression
              complète de vos données dans un délai de 30 jours.
            </li>
            <li><strong>Droit à la portabilité</strong> : export de vos données au format JSON/CSV.</li>
            <li><strong>Droit d'opposition</strong> : refus du traitement à des fins marketing.</li>
            <li>
              <strong>Droit de retrait du consentement</strong> : notamment retrait de
              l'accès aux API Google via{" "}
              <a
                href="https://myaccount.google.com/permissions"
                target="_blank"
                rel="noopener noreferrer"
                className="text-sawali-blue-light underline hover:text-white"
              >
                votre compte Google
              </a>
              .
            </li>
          </ul>
          <p className="mt-3 text-sm text-slate-400">
            Pour exercer ces droits, contactez-nous à l'adresse ci-dessous. Délai de
            réponse maximum : 30 jours.
          </p>
        </Section>

        {/* 6. Sécurité */}
        <Section icon={Shield} title="6. Sécurité">
          <ul className="list-disc ml-6 space-y-1 mt-2">
            <li>Chiffrement TLS 1.2+ pour toutes les communications externes.</li>
            <li>Chiffrement AES au repos pour les bases de données et les jetons OAuth.</li>
            <li>Authentification renforcée à deux facteurs (OTP) pour tous les comptes admin.</li>
            <li>Contrôle d'accès basé sur les rôles (RBAC) strict.</li>
            <li>Audit logs immuables pour toute action administrative.</li>
            <li>Sauvegardes automatiques quotidiennes chiffrées.</li>
            <li>Tests de pénétration réguliers et veille sécurité continue.</li>
          </ul>
        </Section>

        {/* 7. Cookies */}
        <Section icon={Database} title="7. Cookies">
          <p>
            Nous utilisons uniquement des cookies <strong>strictement nécessaires</strong> au
            fonctionnement du service (session, sécurité CSRF) et, sur consentement, des
            cookies analytiques (PostHog) anonymisés. Voir la bannière cookies en bas de
            page pour gérer vos préférences.
          </p>
        </Section>

        {/* 8. Modifications */}
        <Section icon={Shield} title="8. Modifications de cette politique">
          <p>
            Nous pouvons mettre à jour cette politique pour refléter les évolutions
            légales ou fonctionnelles. La date de dernière mise à jour figure en haut de
            cette page. Pour les changements substantiels, nous vous notifierons par
            email au moins 30 jours à l'avance.
          </p>
        </Section>

        {/* 9. Contact */}
        <Section icon={Mail} title="9. Contact — Délégué à la protection des données">
          <p>
            Pour toute question relative à cette politique ou pour exercer vos droits,
            contactez-nous :
          </p>
          <ul className="list-none ml-0 space-y-2 mt-3">
            <li className="flex items-center gap-2">
              <Mail className="h-4 w-4 text-sawali-blue-light" />
              <a
                href={`mailto:${contactEmail}`}
                className="text-sawali-blue-light underline hover:text-white"
                data-testid="privacy-contact-email"
              >
                {contactEmail}
              </a>
            </li>
            <li className="flex items-center gap-2">
              <Phone className="h-4 w-4 text-sawali-blue-light" />
              <span data-testid="privacy-contact-phone">{contactPhone}</span>
            </li>
            <li className="flex items-center gap-2">
              <MapPin className="h-4 w-4 text-sawali-blue-light" />
              <span data-testid="privacy-contact-address">{contactAddress}</span>
            </li>
          </ul>
          <p className="mt-4 text-sm text-slate-400">
            Vous pouvez également déposer une réclamation auprès de la CIL Burkina Faso
            (Commission de l'Informatique et des Libertés) si vous estimez que vos droits
            ne sont pas respectés.
          </p>
        </Section>

        {/* Footer Google compliance hint */}
        <div
          className="rounded-xl ring-1 ring-emerald-400/30 bg-emerald-500/5 p-4 text-sm text-slate-300"
          data-testid="privacy-google-disclaimer"
        >
          <p className="font-semibold text-emerald-300 mb-1">
            ✓ Conformité Google API Services User Data Policy
          </p>
          <p>
            L'utilisation par SAWALI SMART SYSTEMS des informations reçues des API
            Google respecte la{" "}
            <a
              href="https://developers.google.com/terms/api-services-user-data-policy"
              target="_blank"
              rel="noopener noreferrer"
              className="underline text-emerald-200 hover:text-white"
            >
              Google API Services User Data Policy
            </a>
            , y compris les exigences <strong>Limited Use</strong>.
          </p>
        </div>
      </div>
    </section>
  );
}

function Section({ icon: Icon, title, children }) {
  return (
    <section className="rounded-xl ring-1 ring-white/10 bg-white/5 p-5 sm:p-6">
      <h2 className="flex items-center gap-2 text-xl font-display font-semibold text-white mb-3">
        {Icon ? <Icon className="h-5 w-5 text-sawali-blue-light" /> : null}
        {title}
      </h2>
      <div className="text-slate-300 text-sm leading-relaxed space-y-2">{children}</div>
    </section>
  );
}
