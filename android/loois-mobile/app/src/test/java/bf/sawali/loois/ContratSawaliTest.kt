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

    @Test fun statutAvecServeursLocauxEtTicket() {
        val s = lireStatut(charger("statut_local"))
        assertTrue(s.autorise)
        assertEquals(listOf("http://192.168.1.11:8750", "http://192.168.1.10:8750"), s.serveursLocaux)                       // adresses de passerelle remontées par Loois, la plus récente d'abord
        assertTrue(s.ticketLocal.startsWith("eyJ"))
        assertEquals(4102444800L, expirationTicket(s.ticketLocal))                                                           // échéance lue dans le ticket (affichage seulement)
        assertEquals("01/01/2100 00:00", dateHeureDepuisSecondes(4102444800L))
        // le statut gardé sur le téléphone ne contient JAMAIS le ticket
        val garde = statutVersJson(s)
        assertFalse(garde.contains("ticket")); val relu = statutDepuisJson(garde)!!
        assertEquals("myAurora-CMC", relu.base); assertEquals("docx=CMC", relu.zone); assertEquals("", relu.ticketLocal); assertTrue(relu.autorise)
    }

    @Test fun adressesLocalesFiltreesEtTicketIllisible() {
        val a = org.json.JSONArray("""[{"url":"http://192.168.1.10:8750/"},{"url":"http://8.8.8.8:8750"},{"url":"http://192.168.1.10:8750"},{"url":"https://passerelle.exemple.bf"},{"poste":"sans url"}]""")
        assertEquals(listOf("http://192.168.1.10:8750", "https://passerelle.exemple.bf"), adressesLocales(a))                  // publique refusée, doublon et barre finale nettoyés
        assertEquals(emptyList<String>(), adressesLocales(null))
        assertNull(expirationTicket(null)); assertNull(expirationTicket("pas.un.ticket")); assertNull(expirationTicket("a.b.c")); assertNull(statutDepuisJson("pas du json")); assertNull(statutDepuisJson(""))
        // un statut sans accès local (aucun service Loois ne s'est signalé) : aucune adresse, aucun ticket
        val sans = lireStatut(charger("statut"))
        assertEquals(emptyList<String>(), sans.serveursLocaux); assertEquals("", sans.ticketLocal)
    }

    @Test fun tableauDeBordDuJour() {
        // Connexion d'un profil « client » : le droit du tableau de bord est lu
        assertTrue(lireDroits(charger("connexion_client").getJSONObject("droits")).tableauDeBord)
        val t = lireTableau(charger("tableau"))
        assertEquals("2026-11-26", t.date); assertEquals(4, t.nombre)
        assertEquals(25600.5, t.total, 0.001); assertEquals(3, t.parCaissier.size)
        assertEquals("TASSEMBH", t.parCaissier[0].caissier); assertEquals(17000.0, t.parCaissier[0].montant, 0.001)
    }

    @Test fun tableauDeBordSemaine() {
        val w = lireSemaine(charger("semaine"))
        assertEquals(7, w.jours.size); assertEquals("2026-11-26", w.jours.last().date); assertEquals(4, w.jours.last().nombre)
    }

    @Test fun montantsCourtsDesGraphiques() {
        assertEquals("800", formaterMontantCourt(800.0)); assertEquals("25,6 k", formaterMontantCourt(25600.0)); assertEquals("1,3 M", formaterMontantCourt(1250000.0))
        assertEquals("26/11", jourCourt("2026-11-26"))
    }

    @Test fun connexionRapideConfigListeEtSession() {
        val cfg = lireConfigRapide(charger("rapide_config"))
        assertTrue(cfg.google); assertEquals("cid.apps.googleusercontent.com", cfg.googleClientId); assertEquals("api.sawalismartsystems.com", cfg.rpId)
        val l = lireLiaisons(charger("rapide_liste"))
        assertEquals(setOf("google", "biometrie"), l.map { it.methode }.toSet())
        assertEquals("a***@gmail.com", l.first { it.methode == "google" }.detail)
        // La connexion rapide rend la MÊME réponse que la connexion par mot de passe
        val r = charger("rapide_connexion")
        assertTrue(r.getString("session").isNotBlank()); assertEquals("tassembh", r.getJSONObject("utilisateur").getString("login")); assertTrue(lireDroits(r.getJSONObject("droits")).caisse)
    }
}
