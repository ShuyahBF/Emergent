package bf.sawali.loois

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Contrat avec SAWALI : les fichiers de `src/test/resources/contrat` sont les VRAIES réponses du serveur (produites par le banc d'essai de SAWALI,
 * backend/tests/test_android_loois_lot475.py). Si SAWALI change un nom de champ, ces tests le signalent avant la publication de l'application.
 */
class ContratSawaliTest {
    private fun charger(nom: String) = JSONObject(javaClass.getResource("/contrat/$nom.json")!!.readText(Charsets.UTF_8))

    @Test fun enregistrementEtStatut() {
        val e = charger("enregistrer")
        assertTrue(e.getString("jeton").isNotBlank()); assertTrue(e.getString("appareil_id").isNotBlank())
        val s = lireStatut(e)
        assertFalse(s.autorise); assertEquals("interdit", s.etat); assertTrue(s.message.contains("interdit", ignoreCase = true))     // nouvel appareil : interdit
        val a = lireStatut(charger("statut"))
        assertTrue(a.autorise); assertEquals("docx=CMC", a.zone); assertEquals("myAurora-CMC", a.base); assertEquals("CMC", a.client); assertEquals("Awa", a.nomUtilisateur)
    }

    @Test fun connexion() {
        val c = charger("connexion")
        assertEquals("JETON-DE-SESSION-DE-TEST", c.getString("session"))
        val u = c.getJSONObject("utilisateur"); assertEquals("tassembh", u.getString("login")); assertEquals("Biolog", u.getString("espace"))
        val d = lireDroits(c.getJSONObject("droits"))
        assertTrue(d.caisse); assertTrue(d.corrections); assertFalse(d.voirTousLesRecus); assertFalse(d.administrateur); assertFalse(d.consultationSeule)
    }

    @Test fun historiqueDeCaisse() {
        val l = lireListeRecus(charger("historique"))
        assertEquals(listOf("R-0003", "R-0001"), l.recus.map { it.reference })
        assertEquals("2026-11-26", l.date); assertEquals(17000.0, l.total, 0.001); assertFalse(l.tronque); assertEquals("TASSEMBH", l.portee)
        val r = l.recus[0]
        assertEquals("10:15", r.heure); assertEquals("2026-11-26", r.dateVente); assertEquals("Awa BADINI", r.patient); assertEquals(15000.0, r.montant, 0.001); assertEquals("TASSEMBH", r.caissier)
    }

    @Test fun detailDuRecu() {
        val d = lireDetail(charger("recu"))
        assertEquals("R-0003", d.recu.reference); assertEquals(15000.0, d.total, 0.001); assertEquals(30, d.validiteClinique); assertTrue(d.aCorriger)
        val (ped, cons) = d.lignes
        assertEquals("Consultation pédiatrique", ped.designation); assertEquals("OUEDRAOGO Paul", ped.medecin); assertEquals(60, ped.joursValiditePropre); assertTrue(ped.necessiteCorrection)
        assertEquals("2027-01-24 23:59:59", ped.dateExpiration); assertEquals(10000.0, ped.montant, 0.001)
        assertNull(cons.joursValiditePropre); assertFalse(cons.necessiteCorrection); assertEquals(30, cons.joursValiditeEffective); assertEquals(5000.0, cons.montant, 0.001); assertEquals(2.0, cons.quantite, 0.001)
    }

    @Test fun correctionsDeRecus() {
        val l = lireListeRecus(charger("corrections"))
        assertEquals(1, l.nombreACorriger); assertEquals(listOf("R-0003", "R-0001"), l.recus.map { it.reference })
        assertTrue(l.recus[0].aCorriger); assertEquals(1, l.recus[0].lignesACorriger); assertFalse(l.recus[1].aCorriger)
    }
}
