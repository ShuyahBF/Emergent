import React, { useEffect, useState } from "react";
import { FileText, Scale, AlertTriangle, CreditCard, Ban, Mail, Phone, MapPin } from "lucide-react";
import { apiClient } from "@/lib/api";

// Iter43-fix24as (2026-02) — Page Terms of Service requise par TikTok pour
// la validation de l'app `sawalismartsystems`. La page DOIT :
//   1. Avoir un titre document.title = "sawalismartsystems Terms of Service"
//   2. Être accessible via une URL dédiée (pas un PDF)
//   3. Afficher prominent le nom exact « sawalismartsystems »
export default function TermsOfServicePage() {
  const [info, setInfo] = useState(null);

  useEffect(() => {
    document.title = "sawalismartsystems Terms of Service";
    apiClient
      .get("/company-info")
      .then((r) => setInfo(r.data))
      .catch(() => {});
    return () => { document.title = "sawalismartsystems — SAWALI SMART SYSTEMS"; };
  }, []);

  const contactEmail = info?.email || "contact@sawalismartsystems.com";
  const contactPhone = info?.phone || "—";
  const contactAddress = [info?.address, info?.city, info?.country].filter(Boolean).join(", ") || "Ouagadougou, Burkina Faso";
  const lastUpdated = "26 février 2026";

  return (
    <section
      className="mx-auto max-w-4xl px-4 sm:px-6 lg:px-8 py-12 lg:py-16 text-slate-200"
      data-testid="terms-of-service-page"
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
          Conditions générales · Terms of Service
        </p>
        <h1 className="text-3xl sm:text-4xl font-display font-bold text-white flex items-center gap-3">
          <Scale className="h-8 w-8 text-sawali-blue-light" />
          sawalismartsystems Terms of Service
        </h1>
        <p className="mt-3 text-slate-400 text-sm">
          Dernière mise à jour : <strong className="text-slate-200">{lastUpdated}</strong>
        </p>
        <p className="mt-4 text-slate-300 leading-relaxed">
          Les présentes Conditions Générales d'Utilisation (« Conditions ») régissent l'accès
          et l'utilisation des services proposés par <strong>SAWALI SMART SYSTEMS</strong>
          (« nous », « notre » ou « la Société ») via la plateforme{" "}
          <strong>sawalismartsystems</strong> (incluant le site web sawalismartsystems.com,
          ses sous-domaines, l'application mobile et toutes les API associées).
          En accédant à nos services, vous acceptez sans réserve l'intégralité des présentes
          Conditions.
        </p>
      </header>

      <div className="space-y-8">
        <Section icon={FileText} title="1. Définitions">
          <ul className="list-disc ml-6 space-y-1 mt-2">
            <li><strong>« Service »</strong> : la plateforme sawalismartsystems, ses fonctionnalités CRM, communication multi-canal (WhatsApp, SMS, email), assistant IA Liluvine PRO, gestion d'officines, intégrations VIDAL/Google/Stripe/Bird/Meta, et toute fonction associée.</li>
            <li><strong>« Utilisateur »</strong> : toute personne physique ou morale accédant au Service, qu'elle soit visiteur, client, délégué, supervisé ou administrateur.</li>
            <li><strong>« Compte »</strong> : l'espace personnel créé après inscription, protégé par authentification (email + mot de passe + OTP).</li>
            <li><strong>« Contenu Utilisateur »</strong> : toute donnée (texte, image, audio, vidéo, document) téléversée ou produite via le Service par l'Utilisateur.</li>
          </ul>
        </Section>

        <Section icon={FileText} title="2. Acceptation et modifications">
          <p>
            L'utilisation du Service implique l'acceptation pleine et entière des présentes
            Conditions ainsi que de notre{" "}
            <a href="/privacy-policy" className="text-sawali-blue-light underline hover:text-white" data-testid="terms-privacy-link">
              Politique de confidentialité (Privacy Policy)
            </a>
            .
          </p>
          <p className="mt-2">
            Nous nous réservons le droit de modifier les présentes Conditions à tout moment.
            Toute modification substantielle sera notifiée par email à l'Utilisateur au moins
            30 jours avant son entrée en vigueur. La poursuite de l'utilisation du Service
            après cette période vaut acceptation des nouvelles Conditions.
          </p>
        </Section>

        <Section icon={FileText} title="3. Inscription et compte utilisateur">
          <ul className="list-disc ml-6 space-y-1 mt-2">
            <li>L'Utilisateur s'engage à fournir des informations exactes, complètes et à jour lors de son inscription.</li>
            <li>L'Utilisateur est seul responsable de la confidentialité de ses identifiants et de toute activité réalisée sous son compte.</li>
            <li>L'Utilisateur doit avoir au moins 18 ans (ou l'âge légal de majorité dans sa juridiction).</li>
            <li>La création de comptes multiples par un même Utilisateur dans le but de contourner les limitations du Service est strictement interdite.</li>
            <li>Nous nous réservons le droit de suspendre ou supprimer tout compte qui violerait les présentes Conditions.</li>
          </ul>
        </Section>

        <Section icon={Ban} title="4. Usages interdits">
          <p>L'Utilisateur s'engage à ne pas :</p>
          <ul className="list-disc ml-6 space-y-1 mt-2">
            <li>Utiliser le Service à des fins illégales ou frauduleuses, ou pour porter atteinte aux droits de tiers.</li>
            <li>Envoyer du spam, des messages non sollicités, ou contourner les limitations anti-flood (cooldowns WhatsApp, SMS).</li>
            <li>Tenter de pirater, décompiler, rétro-ingénier, ou accéder sans autorisation aux systèmes ou bases de données.</li>
            <li>Diffuser des virus, logiciels malveillants ou tout code susceptible de nuire au Service ou aux autres Utilisateurs.</li>
            <li>Récolter, scraper ou aspirer les données du Service ou de ses Utilisateurs sans consentement explicite.</li>
            <li>Usurper l'identité d'une personne, d'une organisation, ou d'un agent SAWALI SMART SYSTEMS.</li>
            <li>Diffuser du contenu haineux, pornographique, violent, diffamatoire, ou contraire à l'ordre public.</li>
            <li>Utiliser le Service pour des activités réglementées sans détenir les autorisations légales requises (notamment pour la vente de médicaments via le module Officines).</li>
          </ul>
        </Section>

        <Section icon={FileText} title="5. Propriété intellectuelle">
          <p>
            Le Service, sa marque <strong>SAWALI SMART SYSTEMS / sawalismartsystems</strong>,
            son logo, son code source, son interface graphique, ses contenus éditoriaux et
            sa documentation sont la propriété exclusive de la Société et protégés par le
            droit d'auteur, le droit des marques et tout autre droit de propriété intellectuelle
            applicable.
          </p>
          <p className="mt-2">
            L'Utilisateur conserve l'intégralité des droits sur son Contenu Utilisateur.
            Il accorde à SAWALI SMART SYSTEMS une licence non-exclusive, mondiale et gratuite
            d'utilisation strictement limitée à l'hébergement, au traitement et à l'affichage
            de ce contenu dans le cadre du Service.
          </p>
        </Section>

        <Section icon={CreditCard} title="6. Abonnements, paiements et résiliation">
          <ul className="list-disc ml-6 space-y-1 mt-2">
            <li>Certaines fonctionnalités du Service sont accessibles via des abonnements payants facturés mensuellement ou annuellement.</li>
            <li>Les paiements sont traités via nos prestataires partenaires : <strong>Stripe</strong> (cartes bancaires internationales) et <strong>PawaPay</strong> (mobile money Afrique de l'Ouest). Aucune donnée bancaire complète ne transite ni n'est stockée sur nos serveurs.</li>
            <li>Tout abonnement est résiliable à tout moment depuis votre espace personnel ou en contactant le support. La résiliation prend effet à la fin de la période en cours, sans remboursement prorata sauf disposition légale impérative.</li>
            <li>En cas de non-paiement, l'accès aux fonctionnalités premium peut être suspendu après un délai de grâce de 7 jours.</li>
            <li>Les prix sont indiqués hors taxes ; les taxes applicables (TVA, etc.) sont ajoutées selon la juridiction de l'Utilisateur.</li>
          </ul>
        </Section>

        <Section icon={AlertTriangle} title="7. Limitations de responsabilité">
          <p>
            Le Service est fourni « en l'état » sans garantie d'aucune sorte, expresse ou
            implicite. SAWALI SMART SYSTEMS ne garantit pas que le Service sera ininterrompu,
            exempt d'erreurs, ou parfaitement sécurisé.
          </p>
          <p className="mt-2">
            Dans les limites autorisées par la loi, la responsabilité totale de SAWALI SMART
            SYSTEMS envers l'Utilisateur ne pourra excéder le montant payé par celui-ci au
            titre du Service durant les <strong>12 mois précédant</strong> l'événement à
            l'origine de la réclamation.
          </p>
          <p className="mt-2">
            En aucun cas SAWALI SMART SYSTEMS ne saurait être tenu responsable des dommages
            indirects, perte de chiffre d'affaires, perte de données ou perte d'opportunité.
          </p>
        </Section>

        <Section icon={FileText} title="8. Intégrations tierces">
          <p>
            Le Service intègre des API tierces (Meta WhatsApp, Google Calendar/Gmail, Stripe,
            PawaPay, Bird.com, VIDAL, TikTok, LinkedIn, etc.). L'utilisation de ces intégrations
            est soumise aux conditions générales du tiers concerné. SAWALI SMART SYSTEMS n'est
            pas responsable des modifications, indisponibilités ou changements de tarification
            de ces services tiers.
          </p>
        </Section>

        <Section icon={FileText} title="9. Confidentialité et données personnelles">
          <p>
            Le traitement des données personnelles est régi par notre{" "}
            <a href="/privacy-policy" className="text-sawali-blue-light underline hover:text-white">
              Politique de confidentialité
            </a>
            , conforme au Règlement Général sur la Protection des Données (RGPD) et à la loi
            n°010-2004/AN du Burkina Faso sur la protection des données personnelles.
          </p>
        </Section>

        <Section icon={FileText} title="10. Résiliation par la Société">
          <p>
            SAWALI SMART SYSTEMS se réserve le droit de suspendre ou supprimer le compte d'un
            Utilisateur, sans préavis ni indemnité, en cas de :
          </p>
          <ul className="list-disc ml-6 space-y-1 mt-2">
            <li>Violation grave ou répétée des présentes Conditions.</li>
            <li>Usage frauduleux, abusif, ou contraire à l'ordre public.</li>
            <li>Réquisition judiciaire ou demande administrative légitime.</li>
            <li>Non-paiement persistant après mise en demeure.</li>
          </ul>
          <p className="mt-3">
            En cas de résiliation, l'Utilisateur dispose de 30 jours pour exporter ses données
            via la fonction d'export RGPD avant suppression définitive.
          </p>
        </Section>

        <Section icon={Scale} title="11. Droit applicable et juridiction compétente">
          <p>
            Les présentes Conditions sont régies par le droit du <strong>Burkina Faso</strong>.
            Tout litige relatif à leur interprétation ou exécution relève de la compétence
            exclusive des tribunaux de Ouagadougou, sous réserve des règles impératives de
            protection des consommateurs applicables.
          </p>
          <p className="mt-2">
            Pour les Utilisateurs résidant dans l'Union Européenne, les dispositions
            impératives du droit local (notamment RGPD et droit de la consommation) restent
            applicables.
          </p>
        </Section>

        <Section icon={Mail} title="12. Contact">
          <p>Pour toute question concernant les présentes Conditions, contactez-nous :</p>
          <ul className="list-none ml-0 space-y-2 mt-3">
            <li className="flex items-center gap-2">
              <Mail className="h-4 w-4 text-sawali-blue-light" />
              <a
                href={`mailto:${contactEmail}`}
                className="text-sawali-blue-light underline hover:text-white"
                data-testid="terms-contact-email"
              >
                {contactEmail}
              </a>
            </li>
            <li className="flex items-center gap-2">
              <Phone className="h-4 w-4 text-sawali-blue-light" />
              <span data-testid="terms-contact-phone">{contactPhone}</span>
            </li>
            <li className="flex items-center gap-2">
              <MapPin className="h-4 w-4 text-sawali-blue-light" />
              <span data-testid="terms-contact-address">{contactAddress}</span>
            </li>
          </ul>
        </Section>

        <div
          className="rounded-xl ring-1 ring-sawali-blue-light/30 bg-sawali-blue-light/5 p-4 text-sm text-slate-300"
          data-testid="terms-footer-note"
        >
          <p className="font-semibold text-sawali-blue-light mb-1">
            ✓ Conformité plateformes développeurs
          </p>
          <p>
            La plateforme <strong>sawalismartsystems</strong> est conforme aux exigences des
            plateformes développeurs partenaires : Meta (WhatsApp, Facebook, Instagram),
            Google API Services User Data Policy, TikTok Developer Terms, LinkedIn Developer
            Agreement, Stripe Connected Account Agreement, PawaPay Terms, et Bird.com Terms.
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
