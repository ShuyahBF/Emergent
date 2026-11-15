// PrivacyApplication.jsx — Lot 407 : politique de confidentialité PROPRE à chaque application Android (adresses /privacy/concentration et /privacy/personnel-maison).
// Google (validation de l'Agenda) et les boutiques d'applications veulent une politique propre à l'application citée : chaque page décrit CE QUE FAIT l'application, les données
// qu'elle traite (sur le téléphone, et envoyées à SAWALI), ses autorisations, l'Agenda Google (facultatif), la conservation, les droits et le contact.
// Un seul composant : le contenu de chaque application est dans le tableau APPLICATIONS ci-dessous (facile à relire et à modifier).
import React, { useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { Shield } from "lucide-react";

const MISE_A_JOUR = "15 novembre 2026";

// Section « Agenda Google » commune (même engagement que la page /privacy de SAWALI, § 2 bis)
const AGENDA = (nomApp) => ({
  titre: "Agenda Google (facultatif)",
  paragraphes: [
    `Dans ${nomApp}, vous pouvez, si vous le souhaitez, lier VOTRE compte Google. SAWALI SMART SYSTEMS sert de passerelle sécurisée : l'application ne reçoit jamais de jeton Google. ` +
    "La liaison passe par la page d'autorisation de Google et ne demande que l'adresse e-mail de votre compte (pour vérifier que c'est bien le compte que vous avez déclaré et que l'administrateur a accepté) " +
    "et l'autorisation « calendar.events » (voir, créer et supprimer des événements de votre agenda principal). Aucune autre donnée Google n'est utilisée.",
    "Vous pouvez voir vos prochains rendez-vous, en créer un à partir d'une note vocale ou tapée (par exemple « samedi 8h15 rdv chez le dentiste ») après avoir relu et confirmé le jour, l'heure et le titre, et en supprimer un. " +
    "Chaque personne ne voit que son propre agenda ; l'administrateur ne peut pas le lire. Vos événements sont lus chez Google au moment où vous les consultez et ne sont pas copiés dans notre base ; le jeton d'actualisation est conservé chiffré ; le texte d'une note est analysé puis oublié.",
    "Ces données ne sont ni vendues, ni partagées, ni utilisées pour de la publicité ou pour entraîner des modèles d'IA, et aucun humain ne les lit sauf avec votre consentement, pour des raisons de sécurité ou pour respecter la loi. " +
    "L'utilisation et le transfert par SAWALI des informations reçues des API Google respectent la politique « Google API Services User Data Policy », y compris les exigences d'usage limité (Limited Use).",
    `English summary: if you choose to link your Google Calendar in ${nomApp}, only your account e-mail and the calendar.events scope are used, solely to show, create (after your confirmation) and delete your own appointments. ` +
    "Google tokens never reach the app, events are not stored by us, and the data is never sold, shared, used for advertising or to train AI models. You can disconnect at any time with the « Délier » button (access is revoked at Google) or at myaccount.google.com/permissions.",
  ],
});

const APPLICATIONS = {
  concentration: {
    nom: "Concentration",
    resume: "Concentration est une application Android éditée par SAWALI SMART SYSTEMS (Burkina Faso). Elle aide à suivre le réseau mobile, le forfait Internet et les paiements Mobile Money d'un téléphone.",
    sections: [
      {
        titre: "1. Ce que fait l'application",
        liste: [
          "Mesure la qualité du réseau mobile et estime la consommation du forfait Internet ; vérifie le solde de l'opérateur par un code USSD que vous lancez ou autorisez.",
          "Construit l'historique des paiements Mobile Money (Orange Money, Moov Money, Telecel Money, banques) à partir des SMS et notifications de paiement, avec chiffres, graphiques et recherche.",
          "Envoie, si vous l'avez réglé, vos paiements à SAWALI (menu « Transactions SMS », réservé à l'administrateur) pour les associer à une plateforme ou un client.",
        ],
      },
      {
        titre: "2. Données traitées et où elles sont gardées",
        liste: [
          "Sur le téléphone (base locale) : mesures de réseau et de forfait, et pour chaque paiement lu : expéditeur du SMS, date, sens (dépense ou recette), montant, bénéficiaire ou expéditeur, solde, numéro de transaction et texte du SMS.",
          "Seuls les SMS de paiement et les messages qui citent un montant en FCFA (promotions, alertes de banque, messages de personnes, marqués d'une pastille grise et non comptés) sont conservés ; les autres SMS sont lus puis oubliés aussitôt.",
          "Envoyé à SAWALI uniquement si vous avez saisi l'identifiant et la clé d'envoi : les paiements de type « transaction » (date, sens, montant, bénéficiaire, solde, numéro de transaction et texte du SMS). Rien n'est envoyé sans ce réglage.",
          "Signal de présence : version de l'application, modèle du téléphone et date de démarrage, pour la supervision technique (aucun contenu).",
          "Agenda : voir la section « Agenda Google ».",
        ],
      },
      {
        titre: "3. Autorisations Android et leur usage",
        liste: [
          "Téléphone / appels : lancer les codes USSD que vous demandez (vérification de solde). État du téléphone : repérer les cartes SIM et le réseau.",
          "SMS (version « SMS » seulement) : lire les SMS de paiement. La version « standard » n'a pas cette autorisation et importe un fichier de sauvegarde que vous choisissez.",
          "Accès aux notifications (facultatif) : lire les notifications de paiement des applications des opérateurs, application fermée. Notifications, alarmes exactes et démarrage : afficher les alertes et reprendre les vérifications planifiées.",
          "Internet : envoyer à SAWALI ce que vous avez réglé et appeler la passerelle Agenda.",
        ],
      },
      { titre: "4. Conservation et suppression", paragraphes: [
        "Les données de la base locale restent sur votre téléphone jusqu'à leur suppression ou la désinstallation de l'application (qui les efface). Les paiements déjà envoyés à SAWALI sont conservés par SAWALI pour l'administrateur ; vous pouvez en demander la suppression à l'adresse ci-dessous.",
      ] },
    ],
  },
  "personnel-maison": {
    nom: "Personnel de maison",
    resume: "Personnel de maison est une application Android éditée par SAWALI SMART SYSTEMS (Burkina Faso). Elle suit les arrivées et départs du personnel de maison, le budget du foyer, les médicaments et les repas, et permet de partager certaines informations avec ses proches.",
    sections: [
      {
        titre: "1. Ce que fait l'application",
        liste: [
          "Pointage des arrivées et départs du personnel (aide ménagère, gardien, chauffeur…), fiches des personnes et des sociétés de placement, bilans et évaluations.",
          "Budget : opérations, pièces justificatives et lecture de tickets (reconnaissance de texte effectuée sur le téléphone).",
          "Médicaments et repas : rappels, prises, partage avec les proches. Ma famille : liens entre proches, messagerie chiffrée, position et caméra partagées si vous les activez.",
          "Fonctions techniques : cartes NFC, balises Bluetooth, récepteur de badges et « Où suis-je ? » (lieux repérés par des balises).",
        ],
      },
      {
        titre: "2. Données traitées et où elles sont gardées",
        liste: [
          "Sur le téléphone : toutes les données du foyer sont gardées dans une base locale CHIFFRÉE ; elles ne quittent pas le téléphone sans une fonction que vous activez.",
          "Ma famille : les échanges (messages, position, caméra, médicaments, repas) sont chiffrés de bout en bout entre les téléphones des proches liés ; le serveur de SAWALI ne fait que les relayer et ne peut pas les lire.",
          "Ma Télé (demande d'accès à la télé) : pour vérifier qu'une demande est authentique et éviter les abus, SAWALI reçoit et garde votre numéro de téléphone, une adresse e-mail vérifiée par un code, l'adresse IP et le lieu approximatif qui en découle, quelques détails techniques du téléphone (marque, modèle, version Android, langue, fuseau, taille d'écran) et le résultat d'un captcha. Ces informations ne servent qu'à décider de l'approbation et à limiter les abus ; elles ne sont jamais vendues ni utilisées à d'autres fins.",
          "Récepteur de badges (si vous l'activez) : l'identifiant des balises entendues et le signal sont envoyés à SAWALI ; les autres appareils Bluetooth ne sont jamais envoyés. « Où suis-je ? » : seul l'identifiant de la balise la plus proche est envoyé pour retrouver le lieu.",
          "Signal de présence : version de l'application et modèle du téléphone, pour la supervision technique (aucun contenu).",
          "Agenda : voir la section « Agenda Google ».",
        ],
      },
      {
        titre: "3. Autorisations Android et leur usage",
        liste: [
          "Bluetooth et localisation : seulement pour voir les balises (Android l'exige) ; la position du téléphone n'est partagée qu'avec les proches que vous avez liés et seulement si vous activez ce partage.",
          "Caméra : lecture de tickets et caméra partagée avec vos proches si vous l'activez. NFC : cartes et étiquettes. Notifications : rappels de médicaments et de repas. Micro : seulement si vous dictez une note d'agenda avec la reconnaissance vocale du téléphone.",
          "Internet : Ma famille, balises, agenda.",
        ],
      },
      { titre: "4. Conservation et suppression", paragraphes: [
        "Les données restent sur votre téléphone jusqu'à leur suppression ou la désinstallation de l'application, qui les efface. Les messages relayés par le serveur sont chiffrés ; vous pouvez demander leur suppression à l'adresse ci-dessous.",
      ] },
    ],
  },
};

export default function PrivacyApplication() {
  const { app } = useParams();
  const contenu = APPLICATIONS[app];
  useEffect(() => {
    if (contenu) document.title = `${contenu.nom} — Privacy Policy — SAWALI SMART SYSTEMS`;
    return () => { document.title = "sawalismartsystems — SAWALI SMART SYSTEMS"; };
  }, [contenu]);

  if (!contenu) {
    return (
      <section className="mx-auto max-w-3xl px-4 py-12 text-slate-200" data-testid="privacy-app-inconnue">
        <p>Application inconnue. <Link to="/privacy" className="underline">Politique de confidentialité de SAWALI</Link></p>
      </section>
    );
  }
  const sections = [...contenu.sections, AGENDA(contenu.nom), {
    titre: "6. Vos droits et contact",
    paragraphes: [
      "Vous pouvez demander l'accès, la rectification ou la suppression de vos données, ou vous opposer à leur traitement, en écrivant à SAWALI SMART SYSTEMS : contact@sawalismartsystems.com (Ouagadougou, Burkina Faso), conformément à la loi n°001-2021/AN du 30 mars 2021 relative à la protection des données personnelles. Vous pouvez aussi saisir la Commission de l'Informatique et des Libertés (CIL) du Burkina Faso.",
      "Vos données ne sont ni vendues, ni louées, ni utilisées à des fins publicitaires.",
    ],
  }];
  return (
    <section className="mx-auto max-w-4xl px-4 sm:px-6 lg:px-8 py-12 lg:py-16 text-slate-200" data-testid="privacy-app-page">
      <header className="mb-10">
        <p className="text-xs uppercase tracking-[0.3em] text-sawali-blue-light mb-2">Privacy Policy</p>
        <h1 className="text-3xl sm:text-4xl font-display font-bold text-white flex items-center gap-3"><Shield className="h-8 w-8 text-sawali-blue-light" />{contenu.nom} — politique de confidentialité</h1>
        <p className="mt-3 text-slate-400 text-sm">Dernière mise à jour : <strong className="text-slate-200">{MISE_A_JOUR}</strong></p>
        <p className="mt-4 text-slate-300 leading-relaxed">{contenu.resume} Cette page est propre à l'application ; la politique générale de SAWALI SMART SYSTEMS est sur <Link to="/privacy" className="underline">/privacy</Link>.</p>
      </header>
      <div className="space-y-8">
        {sections.map((s, i) => (
          <section key={s.titre} className="rounded-xl border border-white/10 bg-white/5 p-5" data-testid={`privacy-app-section-${i}`}>
            <h2 className="text-lg font-semibold text-white mb-2">{s.titre.startsWith("Agenda") ? `5. ${s.titre}` : s.titre}</h2>
            {s.liste && <ul className="list-disc ml-6 space-y-1 text-sm">{s.liste.map((l) => <li key={l}>{l}</li>)}</ul>}
            {s.paragraphes?.map((p) => <p key={p} className="mt-2 text-sm leading-relaxed">{p}</p>)}
          </section>
        ))}
      </div>
    </section>
  );
}
