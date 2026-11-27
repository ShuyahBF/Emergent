package bf.sawali.loois

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Tests de la logique pure de Loois mobile : formats, tri des colonnes, lecture des réponses de SAWALI, règles d'adresse. */
class ModelesTest {
    @Test fun montantsAvecEspaceInsecable() {
        assertEquals("15 000 F", formaterMontant(15000.0))
        assertEquals("8 500,50 F", formaterMontant(8500.5))
        assertEquals("1 234 567", formaterMontant(1234567.0, avecDevise = false))
        assertEquals("0 F", formaterMontant(0.0))
        assertEquals("-2 000 F", formaterMontant(-2000.0))
    }

    @Test fun quantitesEtDates() {
        assertEquals("2", formaterQuantite(2.0)); assertEquals("1,5", formaterQuantite(1.5))
        assertEquals("26/11/2026", jourFr("2026-11-26")); assertEquals("2026-11-27", decalerJour("2026-11-26", 1)); assertEquals("2026-11-25", decalerJour("2026-11-26", -1))
        assertEquals("24/01/2027 23:59", dateHeureFr("2027-01-24 23:59:59")); assertEquals("", dateHeureFr(""))
        assertEquals("Historique De Caisse", titreMenu("historique de caisse")); assertEquals("Loois Mobile", titreMenu("Loois mobile"))
    }

    private fun recu(ref: String, heure: String, patient: String, montant: Double, caissier: String = "A") =
        Recu(ref, "2026-11-26", heure.substring(11, 16), heure, "C", patient, montant, caissier, 0.0, 0.0, 0.0)

    @Test fun triDesColonnesTroisTemps() {
        val l = listOf(recu("R-1", "2026-11-26T10:00:00", "Zoé", 500.0), recu("R-2", "2026-11-26T08:00:00", "Awa", 9000.0), recu("R-3", "2026-11-26T09:00:00", "", 100.0))
        var t = Tri()
        t = basculerTri(t, ColonneTri.MONTANT); assertEquals(Tri(ColonneTri.MONTANT, true), t)                                  // 1er toucher : croissant
        assertEquals(listOf("R-3", "R-1", "R-2"), trierRecus(l, t).map { it.reference })
        t = basculerTri(t, ColonneTri.MONTANT); assertEquals(Tri(ColonneTri.MONTANT, false), t)                                 // 2e : décroissant
        assertEquals(listOf("R-2", "R-1", "R-3"), trierRecus(l, t).map { it.reference })
        t = basculerTri(t, ColonneTri.MONTANT); assertEquals(Tri(), t)                                                          // 3e : ordre d'origine
        assertEquals(listOf("R-1", "R-2", "R-3"), trierRecus(l, t).map { it.reference })
        // valeurs vides toujours en dernier, dans les deux sens ; textes sans tenir compte de la casse
        assertEquals(listOf("R-2", "R-1", "R-3"), trierRecus(l, Tri(ColonneTri.PATIENT, true)).map { it.reference })
        assertEquals(listOf("R-1", "R-2", "R-3"), trierRecus(l, Tri(ColonneTri.PATIENT, false)).map { it.reference })
        assertEquals(listOf("R-2", "R-3", "R-1"), trierRecus(l, Tri(ColonneTri.HEURE, true)).map { it.reference })
    }

    @Test fun lectureDesReponsesDeSawali() {
        val j = JSONObject("""{"date":"2026-11-26","nombre":1,"total_montant":15000,"tronque":false,"portee":"TASSEMBH","nombre_a_corriger":1,"consultation_seule":false,
          "recus":[{"reference":"R-0003","date_vente":"2026-11-26","heure":"10:15","date_heure_iso":"2026-11-26T10:15:00","code_client":"C1","patient":"Awa BADINI","montant":15000,
                    "caissier":"TASSEMBH","ppc":0,"part_assure":15000,"part_assureur":0,"lignes_a_corriger":1,"a_corriger":true}]}""")
        val l = lireListeRecus(j)
        assertEquals(1, l.recus.size); assertEquals("R-0003", l.recus[0].reference); assertTrue(l.recus[0].aCorriger); assertEquals(1, l.recus[0].lignesACorriger); assertEquals(1, l.nombreACorriger)
        val d = lireDetail(JSONObject("""{"recu":{"reference":"R-1","montant":10},"total":10,"validite_clinique":30,"a_corriger":true,
          "lignes":[{"code_produit":"P1","designation":"Consult","domaine":"PED","medecin":"X","quantite":1,"prix_unitaire":10,"montant":10,"jours_validite_propre":60,"jours_validite_effective":60,"necessite_correction":true,"date_expiration":"2027-01-24 23:59:59"},
                    {"code_produit":"P2","designation":"","domaine":"C","medecin":"","quantite":1,"prix_unitaire":0,"montant":0,"jours_validite_propre":null,"jours_validite_effective":30,"necessite_correction":false,"date_expiration":""}]}"""))
        assertEquals(60, d.lignes[0].joursValiditePropre); assertNull(d.lignes[1].joursValiditePropre); assertEquals(30, d.validiteClinique); assertTrue(d.aCorriger)
        val s = lireStatut(JSONObject("""{"etat":"autorise","autorise":true,"nom_utilisateur":"Awa","zone":"docx=CMC","base":"myAurora-CMC","client_code":"CMC","message":""}"""))
        assertTrue(s.autorise); assertEquals("myAurora-CMC", s.base)
        assertFalse(lireDroits(JSONObject("""{"corrections":false}""")).corrections)
    }

    @Test fun adressesAutorisees() {
        assertTrue(urlAutorisee("https://api.sawalismartsystems.com"))
        assertTrue(urlAutorisee("http://192.168.1.10:8750")); assertTrue(urlAutorisee("http://10.0.0.5")); assertTrue(urlAutorisee("http://172.20.3.4:80/api"))
        assertFalse(urlAutorisee("http://api.sawalismartsystems.com")); assertFalse(urlAutorisee("http://8.8.8.8")); assertFalse(urlAutorisee("http://172.32.0.1")); assertFalse(urlAutorisee("ftp://192.168.1.1"))
        assertFalse(urlAutorisee("")); assertFalse(urlAutorisee("https://"))
    }

    @Test fun messagesDErreur() {
        assertEquals("Identifiant ou mot de passe incorrect (4 essai(s) restant(s)).", messageErreur(401, """{"detail":"Identifiant ou mot de passe incorrect (4 essai(s) restant(s))."}"""))
        assertEquals("Données invalides.", messageErreur(422, """{"detail":[{"loc":["body"]}]}"""))
        assertEquals("Trop de demandes : patientez un instant.", messageErreur(429, "pas du json"))
        assertEquals("Erreur du serveur (500).", messageErreur(500, ""))
    }

    @Test fun profilDeZoneAllerRetourEtValeursInvalides() {
        val p = ProfilZone("tassembh", setOf("biometrie", "google"), "google", "internet", "http://192.168.1.10:8750")
        assertEquals(p, profilDepuisJson(profilVersJson(p)))
        assertEquals(ProfilZone(), profilDepuisJson(null)); assertEquals(ProfilZone(), profilDepuisJson("pas du json"))
        assertEquals(setOf("cle"), profilDepuisJson("""{"login":"x","methodes":["cle","inconnue"]}""").methodes)     // une méthode inconnue est ignorée
        assertFalse(profilVersJson(p).contains("mot_de_passe", true))                                                // jamais de mot de passe
    }

    @Test fun zonesMemoriseesSeparement() {
        assertEquals("docx_cmc", cleZone("docx=CMC")); assertEquals("doc_cmc", cleZone(" /doc=CMC ")); assertTrue(cleZone("docx=CMC") != cleZone("doc=CMC"))
        assertEquals("Compte Google", libelleMethode("google")); assertEquals("Empreinte / visage", libelleMethode("biometrie"))
    }
}
