package bf.sawali.loois

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Lot M9 : pointage hors connexion — dictée, fichiers de pointage, fusion sans doublon, contrat avec SAWALI (sans téléphone ni réseau). */
class PointageTest {
    private val acces = JSONObject("""{"jeton_telephone":"JT","numero":"PT-0001","code_inv":"INV069","langue":"fr","id":"inv1","cle_pointage":"CP-K7MP2Q",
        "structure":"Clinique Philadelphie","lieux":[{"id":"L1","nom":"Salle de vente"},{"id":"L2","nom":"Magasin"}],
        "lignes":[{"c":1,"l":"ACETYL","m":"B/1"},{"c":245,"l":"PARACETAMOL","m":"B/20"}],"jeton_expire":"2026-12-01T09:00:00+00:00"}""")
    private val inv = inventaireDepuisAcces("jeton-de-test-0123456789", acces)

    private fun s(uid: String, c: Int, q: Int, lieu: String = "L1", prenom: String = "Awa") =
        SaisieP(uid, c, q, lieu, null, prenom, "appareil-$prenom", "2026-11-28T09:00:00Z")

    @Test fun dicteeFrancaisEtAnglais() {
        assertEquals(Dictee(245, 12, "03/2027", "suivant"), analyserDictee("ligne 245, 12, mars 2027, suivant"))
        assertEquals(Dictee(245, 12, null, null), analyserDictee("deux cent quarante-cinq douze"))
        assertEquals(Dictee(97, 70, null, null), analyserDictee("ligne quatre-vingt-dix-sept quantité soixante-dix"))
        assertEquals(Dictee(245, 21, "03/2027", "suivant"), analyserDictee("line two hundred and forty five, quantity twenty one, March 2027, next"))
        assertEquals(Dictee(245, 12, "06/2028", null), analyserDictee("245 12 péremption 062028"))
        assertEquals(Dictee(commande = "annule"), analyserDictee("undo"))
    }

    @Test fun inventaireEtJeton() {
        assertEquals("Clinique Philadelphie · INV069", inv.titre)
        assertEquals(inv, inventaireDepuisJson(inv.versJson()))
        assertEquals("abcdefghij0123456789_-", extraireJeton("https://sawalismartsystems.com/pointage/abcdefghij0123456789_-"))
        assertNull(extraireJeton("pas un jeton"))
        assertEquals("03/2027", peremptionNormalisee("3/27")); assertEquals("?", peremptionNormalisee("13/2027")); assertNull(peremptionNormalisee(" "))
    }

    @Test fun fichierExporteImporteEtFusionSansDoublon() {
        val ama = listOf(s("u1", 245, 12, prenom = "Ama"), s("u2", 1, 3, "L2", prenom = "Ama"), s("u3", 1, 9, prenom = "Ama").copy(annulee = true))
        val fichier = fichierPointage(inv, ama, "Ama", "appareil-Ama", "2026-11-28T10:00:00Z").toString()
        val lu = lireFichierPointage(fichier, inv)
        assertNull(lu.erreur); assertEquals("Ama", lu.prenom); assertEquals(2, lu.saisies.size)       // la saisie annulée ne part pas
        val responsable = listOf(s("r1", 245, 4, prenom = "Kofi"))
        val (fusion, ajoutees) = fusionner(responsable, lu.saisies)
        assertEquals(2, ajoutees); assertEquals(3, fusion.size)
        val (encore, zero) = fusionner(fusion, lu.saisies)                                                 // même fichier importé deux fois
        assertEquals(0, zero); assertEquals(3, encore.size)
        assertEquals(mapOf("L1" to 16), totauxParLigne(fusion)[245])
        assertEquals("Ama", fusion.first { it.uid == "u1" }.versEnvoi().getString("prenom"))             // chaque saisie garde qui a compté
    }

    @Test fun fichierRefuse() {
        val autre = inv.copy(id = "autre")
        assertNotNull(lireFichierPointage(fichierPointage(autre, listOf(s("u1", 245, 1)), "Ama", "x").toString(), inv).erreur)
        assertNotNull(lireFichierPointage("{}", inv).erreur)
        assertNotNull(lireFichierPointage("pas du json", inv).erreur)
        // Lignes ou lieux inconnus ignorés
        val f = fichierPointage(inv, listOf(s("u1", 999, 1), s("u2", 245, 1, "L9"), s("u3", 245, 2)), "Ama", "x").toString()
        assertEquals(listOf("u3"), lireFichierPointage(f, inv).saisies.map { it.uid })
    }

    /** Contrat avec SAWALI : vraies réponses du serveur (backend/tests/test_pointage_telephone_routes_lot496.py, ECRIRE_CONTRAT_ANDROID=1). */
    @Test fun contratSawali() {
        val acces = JSONObject(javaClass.getResource("/contrat/pointage_acces.json")!!.readText(Charsets.UTF_8))
        val i = inventaireDepuisAcces("jeton-de-test-0123456789", acces)
        assertEquals("", i.codeInv)                                   // null côté serveur (liste CSV) : jamais le texte « null »
        assertEquals("Corner Shop · PT-0001", i.titre); assertEquals("en", i.langue); assertEquals("JETON-TELEPHONE-DE-TEST", i.jetonTelephone)
        assertEquals(listOf("L1", "L2"), i.lieux.map { it.id }); assertEquals("Soap", i.produit(1)?.libelle)
        assertTrue(i.cle.startsWith("CP-"))
        assertTrue(i.souscriptionIllimitee && i.peutCompter())                    // contrat : le serveur envoie l'état de la souscription
        val envoi = JSONObject(javaClass.getResource("/contrat/pointage_saisies.json")!!.readText(Charsets.UTF_8))
        assertEquals(2, envoi.getJSONArray("acceptees").length()); assertEquals(0, envoi.getJSONArray("refusees").length())
    }

    /** Lot M9.1 : comptage permis seulement pendant la souscription (export, fusion et envoi restent possibles). */
    @Test fun souscription() {
        val maintenant = java.time.Instant.parse("2026-11-28T10:00:00Z")
        assertTrue(inv.copy(souscriptionIllimitee = true).peutCompter(maintenant))
        assertTrue(inv.copy(souscriptionFin = "2026-12-05T10:00:00+00:00").peutCompter(maintenant))
        assertFalse(inv.copy(souscriptionFin = "2026-11-27T10:00:00+00:00").peutCompter(maintenant))
        assertFalse(inv.peutCompter(maintenant))                                  // aucune souscription
        val gardee = inventaireDepuisJson(inv.copy(souscriptionFin = "2026-12-05T10:00:00+00:00").versJson())
        assertTrue(gardee.peutCompter(maintenant))                               // gardée dans le téléphone pour pointer hors connexion
    }

    @Test fun langue() {
        assertEquals("Next", traduire("en", "Suivant")); assertEquals("Suivant", traduire("fr", "Suivant"))
        assertEquals("3 entry(ies) sent to SAWALI.", traduire("en", "{n} saisie(s) envoyée(s) à SAWALI.", "n" to 3))
        assertEquals("en-US", langueDictee("en"))
    }
}
