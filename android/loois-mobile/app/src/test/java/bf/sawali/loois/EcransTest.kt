package bf.sawali.loois

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Tests de fumée de l'interface (sur le PC, sans téléphone) : chaque écran s'affiche avec ses informations clés, sans planter. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], qualifiers = "w411dp-h891dp-xxhdpi")   // taille d'un téléphone courant (sinon l'écran de test est minuscule)
class EcransTest {
    @get:Rule val rule = createComposeRule()

    // Aucun test ne doit parler à SAWALI : sans cela chaque écran de test enregistrerait un faux appareil « robolectric » dans le registre de production
    @org.junit.Before fun sansReseau() { AppViewModel.sansDemarrageReseau = true }

    private val statut = StatutAppareil("autorise", true, "BADINI Awa", "docx=CMC", "myAurora-CMC", "CMC", "")
    private val droitsCaissier = Droits(false, false, false, true, true, false)
    private val recus = listOf(
        Recu("R-0003", "2026-11-26", "10:15", "2026-11-26T10:15:00", "C1", "Awa BADINI", 15000.0, "TASSEMBH", 0.0, 15000.0, 0.0, 1, true),
        Recu("R-0001", "2026-11-26", "08:00", "2026-11-26T08:00:00", "C3", "Fatim SAWADOGO", 2000.0, "TASSEMBH", 0.0, 2000.0, 0.0, 0, false),
    )

    private fun vm(e: UiEtat): AppViewModel = AppViewModel(ApplicationProvider.getApplicationContext()).also { it.forcerEtat(e) }
    private fun afficher(e: UiEtat) { val v = vm(e); rule.setContent { LooisTheme { Racine(v) } } }

    @Test fun connexionAvecOeilEtZoneGrisee() {
        afficher(UiEtat(ecran = Ecran.CONNEXION, statut = statut, serveur = "actif", modeAffiche = "Internet · SQL distantes"))
        rule.onNodeWithText("Loois Mobile").assertIsDisplayed()
        rule.onNodeWithText("Serveur actif").assertIsDisplayed()
        rule.onNodeWithText("Zone /docx=CMC · base myAurora-CMC").assertIsDisplayed()
        rule.onNodeWithText("Se Connecter").assertIsDisplayed()
        rule.onNodeWithText("Version ${BuildConfig.VERSION_NAME}", substring = true).assertIsDisplayed()      // version et date de déploiement toujours visibles (règle 2)
        rule.onNodeWithContentDescription("Afficher la saisie").performClick()                                // l'œil bascule : masqué par défaut, visible au clic (règle 22)
        rule.onNodeWithContentDescription("Masquer la saisie").assertIsDisplayed()
    }

    @Test fun attenteQuandAppareilInterdit() {
        afficher(UiEtat(ecran = Ecran.ATTENTE_AUTORISATION, appareilId = "a1b2c3d4e5f60001", messageAttente = "Accès interdit : cet appareil n'est pas encore autorisé par l'administrateur SAWALI.", serveur = "actif"))
        rule.onNodeWithText("Accès non autorisé").assertIsDisplayed()
        rule.onNodeWithText("Identifiant de l'appareil : a1b2c3d4e5f60001").assertIsDisplayed()
        rule.onNodeWithText("Actualiser").assertIsDisplayed()
    }

    @Test fun menuSelonLesDroits() {
        afficher(UiEtat(ecran = Ecran.MENU, statut = statut, utilisateur = Utilisateur("TASSEMBH", "", "Biolog"), droits = droitsCaissier, serveur = "actif"))
        rule.onNodeWithText("Historique De Caisse").assertIsDisplayed()
        rule.onNodeWithText("Corrections De Reçus").assertIsDisplayed()
        rule.onNodeWithText("Paramètres", substring = false).assertIsDisplayed()
    }

    @Test fun menuSansCorrectionsPourUnCaissierSansDroit() {
        afficher(UiEtat(ecran = Ecran.MENU, statut = statut, utilisateur = Utilisateur("ASI2020", "", "Biolog"), droits = droitsCaissier.copy(corrections = false)))
        rule.onNodeWithText("Historique De Caisse").assertIsDisplayed()
        assertEquals(0, rule.onAllNodesWithTextCount("Corrections De Reçus"))
    }

    @Test fun historiqueListeTotauxEtTri() {
        afficher(UiEtat(ecran = Ecran.HISTORIQUE, statut = statut, utilisateur = Utilisateur("TASSEMBH", "", "Biolog"), droits = droitsCaissier, jour = "2026-11-26",
            historique = ListeRecus("2026-11-26", recus, 17000.0, false, "TASSEMBH")))
        rule.onNodeWithText("Historique De Caisse").assertIsDisplayed()
        rule.onNodeWithText("R-0003").assertIsDisplayed()
        rule.onNodeWithText("Awa BADINI").assertIsDisplayed()
        rule.onNodeWithText("15 000 F").assertIsDisplayed()
        rule.onNodeWithText("2 reçu(s)").assertIsDisplayed()                                                  // ligne de totaux sous la liste (règle 25)
        rule.onNodeWithText("17 000 F").assertIsDisplayed()
        rule.onNodeWithText("26/11/2026").assertIsDisplayed()
        rule.onNodeWithText("Montant").performClick()                                                         // tri : ne plante pas, la liste reste affichée
        rule.onNodeWithText("R-0001").assertIsDisplayed()
    }

    @Test fun correctionsMontreLesRecusACorriger() {
        afficher(UiEtat(ecran = Ecran.CORRECTIONS, statut = statut, utilisateur = Utilisateur("TASSEMBH", "", "Biolog"), droits = droitsCaissier, jour = "2026-11-26",
            corrections = ListeRecus("2026-11-26", recus, 17000.0, false, "", nombreACorriger = 1), seulementACorriger = true))
        rule.onNodeWithText("Corrections De Reçus").assertIsDisplayed()
        rule.onNodeWithText("R-0003").assertIsDisplayed()
        rule.onNodeWithText("1 à corriger", substring = true).assertIsDisplayed()
        assertEquals(0, rule.onAllNodesWithTextCount("R-0001"))                                              // seulement les reçus à corriger
        rule.onNodeWithText("1 reçu(s)").assertIsDisplayed()
    }

    @Test fun detailDuRecuAvecLigneACorriger() {
        val d = DetailRecu(recus[0], listOf(
            LigneRecu("P1", "Consultation pédiatrique", "PEDIATRIE", "OUEDRAOGO Paul", 1.0, 10000.0, 10000.0, 60, 60, true, "2027-01-24 23:59:59"),
            LigneRecu("P2", "Consultation", "CONSULT", "", 2.0, 2500.0, 5000.0, null, 30, false, "2026-12-25 23:59:59")), 15000.0, 30, true)
        afficher(UiEtat(ecran = Ecran.DETAIL, statut = statut, utilisateur = Utilisateur("TASSEMBH", "", "Biolog"), droits = droitsCaissier, detail = d))
        rule.onNodeWithText("Reçu R-0003").assertIsDisplayed()
        rule.onNodeWithText("Consultation pédiatrique").assertIsDisplayed()
        rule.onNodeWithText("expire le 24/01/2027 23:59", substring = true).assertIsDisplayed()
        rule.onNodeWithText("2 ligne(s)").assertIsDisplayed()
    }

    @Test fun tableauDeBordMontreLesIndicateursEtLesCaissiers() {
        val t = TableauJour("2026-11-26", 4, 25600.5, 6400.12, listOf(LigneCaissier("TASSEMBH", 2, 17000.0), LigneCaissier("ASI2020", 2, 8600.5)))
        val sem = Semaine("2026-11-26", listOf(JourSemaine("2026-11-25", 3, 9000.0), JourSemaine("2026-11-26", 4, 25600.5)), 34600.5, 7)
        afficher(UiEtat(ecran = Ecran.TABLEAU, statut = statut, utilisateur = Utilisateur("CLIENT", "", "Biolog"), droits = Droits(false, false, false, false, false, false, true), tableau = t, semaine = sem))
        rule.onNodeWithText("Tableau De Bord").assertIsDisplayed()
        rule.onNodeWithText("Par caissier").assertIsDisplayed()
        rule.onNodeWithText("TASSEMBH").assertIsDisplayed()
        rule.onNodeWithText("7 derniers jours").assertIsDisplayed()
    }

    @Test fun menuMontreLeTableauDeBordPourUnClient() {
        afficher(UiEtat(ecran = Ecran.MENU, statut = statut, utilisateur = Utilisateur("CLIENT", "", "Biolog"), droits = Droits(false, false, false, false, false, false, true), serveur = "actif"))
        rule.onNodeWithText("Tableau De Bord").assertIsDisplayed()
    }

    @Test fun connexionMontreLIdentifiantMemoriseEtLesMethodesRapides() {
        afficher(UiEtat(ecran = Ecran.CONNEXION, statut = statut, serveur = "actif", profil = ProfilZone("tassembh", setOf("biometrie", "cle"), "cle")))
        rule.onNodeWithText("tassembh").assertIsDisplayed()                                         // identifiant retrouvé pour la zone
        rule.onNodeWithText("Mémoriser l'identifiant pour cette zone").assertIsDisplayed()
        rule.onNodeWithText("Connexion rapide — tassembh").assertIsDisplayed()
        rule.onNodeWithText("Empreinte / visage").assertExists(); rule.onNodeWithText("Clé d'accès").assertExists()
        assertEquals(0, rule.onAllNodesWithTextCount("Compte Google"))                              // seulement les méthodes activées pour la zone
    }

    @Test fun connexionSansMethodeRapideNeMontreRien() {
        afficher(UiEtat(ecran = Ecran.CONNEXION, statut = statut, serveur = "actif"))
        assertEquals(0, rule.onAllNodesWithTextCount("Connexion rapide"))
    }

    @Test fun menuProposeLaConnexionRapide() {
        afficher(UiEtat(ecran = Ecran.MENU, statut = statut, utilisateur = Utilisateur("TASSEMBH", "", "Biolog"), droits = droitsCaissier, serveur = "actif"))
        rule.onNodeWithText("Connexion Rapide").assertIsDisplayed()
    }

    @Test fun ecranRapideMontreLEtatDesTroisMethodes() {
        afficher(UiEtat(ecran = Ecran.RAPIDE, statut = statut, utilisateur = Utilisateur("TASSEMBH", "", "Biolog"), droits = droitsCaissier,
            configRapide = ConfigRapide(false, "", "api.sawalismartsystems.com"), rapide = listOf(LiaisonRapide("a1", "biometrie", "", "2026-11-27T03:00:00", ""))))
        rule.onNodeWithText("Connexion Rapide").assertIsDisplayed()
        rule.onNodeWithText("Empreinte / visage").assertIsDisplayed(); rule.onNodeWithText("Compte Google").assertExists(); rule.onNodeWithText("Clé d'accès").assertExists()
        rule.onNodeWithText("Activée").assertExists()                                                // empreinte activée
        rule.onNodeWithText("Pas encore configuré sur SAWALI", substring = true).assertExists()      // Google non configuré : expliqué, pas de bouton
    }

    @Test fun parametresMontrentLaMemorisationDeLaZone() {
        afficher(UiEtat(ecran = Ecran.PARAMETRES, statut = statut, urlSawali = "https://api.sawalismartsystems.com", mode = "auto", profil = ProfilZone("tassembh", setOf("google"))))
        rule.onNodeWithText("Mémorisé pour la zone /docx=CMC").assertIsDisplayed()
        rule.onNodeWithText("Identifiant : tassembh", substring = true).assertIsDisplayed()
        rule.onNodeWithText("Oublier Cette Zone").assertIsDisplayed()
    }

    @Test fun parametresMontrentLesServeursLocauxRecusDeSawali() {
        afficher(UiEtat(ecran = Ecran.PARAMETRES, urlSawali = "https://api.sawalismartsystems.com", mode = "auto", serveursLocaux = listOf("http://192.168.1.10:8750"), ticketExpire = "30/11/2026 14:05"))
        rule.onNodeWithText("Serveurs locaux reçus de SAWALI").assertIsDisplayed()
        rule.onNodeWithText("http://192.168.1.10:8750").assertIsDisplayed()
        rule.onNodeWithText("Accès sans Internet valable jusqu'au 30/11/2026 14:05", substring = true).assertIsDisplayed()
    }

    @Test fun parametresSansServeurLocalExpliquentPourquoi() {
        afficher(UiEtat(ecran = Ecran.PARAMETRES, urlSawali = "https://api.sawalismartsystems.com", mode = "auto"))
        rule.onNodeWithText("Aucun pour l'instant", substring = true).assertIsDisplayed()
    }

    @Test fun parametresAvecModeDeConnexion() {
        afficher(UiEtat(ecran = Ecran.PARAMETRES, urlSawali = "https://api.sawalismartsystems.com", urlLocale = "http://192.168.1.10:8750", mode = "auto", serveur = "injoignable"))
        rule.onNodeWithText("Paramètres").assertIsDisplayed()
        rule.onNodeWithText("Serveur injoignable").assertIsDisplayed()
        rule.onNodeWithText("Enregistrer").assertIsDisplayed()
    }
}

private fun androidx.compose.ui.test.junit4.ComposeContentTestRule.onAllNodesWithTextCount(texte: String): Int =
    onAllNodes(androidx.compose.ui.test.hasText(texte)).fetchSemanticsNodes().size
