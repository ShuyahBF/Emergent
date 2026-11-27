package bf.sawali.loois

import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDate
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

// ============================================================================ modèles (réponses de SAWALI)

data class StatutAppareil(val etat: String, val autorise: Boolean, val nomUtilisateur: String, val zone: String, val base: String, val client: String, val message: String,
                          val serveursLocaux: List<String> = emptyList(), val ticketLocal: String = "")

data class Droits(val administrateur: Boolean, val laboratoire: Boolean, val voirTousLesRecus: Boolean, val caisse: Boolean, val corrections: Boolean, val consultationSeule: Boolean)

data class Utilisateur(val login: String, val groupe: String, val espace: String)

data class Recu(val reference: String, val dateVente: String, val heure: String, val dateHeureIso: String, val codeClient: String, val patient: String, val montant: Double,
                val caissier: String, val ppc: Double, val partAssure: Double, val partAssureur: Double, val lignesACorriger: Int = 0, val aCorriger: Boolean = false)

data class LigneRecu(val codeProduit: String, val designation: String, val domaine: String, val medecin: String, val quantite: Double, val prixUnitaire: Double, val montant: Double,
                     val joursValiditePropre: Int?, val joursValiditeEffective: Int, val necessiteCorrection: Boolean, val dateExpiration: String)

data class DetailRecu(val recu: Recu, val lignes: List<LigneRecu>, val total: Double, val validiteClinique: Int?, val aCorriger: Boolean)

data class ListeRecus(val date: String, val recus: List<Recu>, val total: Double, val tronque: Boolean, val portee: String, val nombreACorriger: Int = 0, val consultationSeule: Boolean = false)

// ============================================================================ lecture JSON

private fun JSONObject.texte(cle: String) = optString(cle, "")
private fun JSONObject.entierOuNul(cle: String): Int? = if (isNull(cle) || !has(cle)) null else optInt(cle)

fun lireStatut(j: JSONObject) = StatutAppareil(j.texte("etat"), j.optBoolean("autorise"), j.texte("nom_utilisateur"), j.texte("zone"), j.texte("base"), j.texte("client_code"), j.texte("message"),
    adressesLocales(j.optJSONArray("serveurs_locaux")), j.texte("ticket_local"))

/** Adresses des passerelles locales : le statut de SAWALI donne des objets {url, poste, serveur_hfsql} ; on ne garde que les adresses autorisées (https, ou http sur réseau local), sans doublon. */
fun adressesLocales(a: JSONArray?): List<String> =
    if (a == null) emptyList() else (0 until a.length()).mapNotNull { a.optJSONObject(it)?.optString("url")?.trim()?.trimEnd('/') }.filter { urlAutorisee(it) }.distinct()

/** Dernier statut gardé sur le téléphone (rien de secret : pas de ticket) et sa relecture. */
fun statutVersJson(s: StatutAppareil): String = JSONObject().put("etat", s.etat).put("autorise", s.autorise).put("nom_utilisateur", s.nomUtilisateur).put("zone", s.zone).put("base", s.base)
    .put("client_code", s.client).put("message", s.message).toString()

fun statutDepuisJson(texte: String): StatutAppareil? = try { if (texte.isBlank()) null else lireStatut(JSONObject(texte)) } catch (e: Exception) { null }

/** Instant d'expiration (secondes Unix) d'un ticket local, lu dans son contenu SANS vérifier la signature (la passerelle la vérifie) ; null si illisible. Sert seulement à l'affichage. */
fun expirationTicket(ticket: String?): Long? = try {
    val morceaux = (ticket ?: "").split(".")
    if (morceaux.size != 3) null else JSONObject(String(java.util.Base64.getUrlDecoder().decode(morceaux[1]), Charsets.UTF_8)).optLong("exp", 0L).takeIf { it > 0 }
} catch (e: Exception) { null }

/** « 30/11/2026 14:05 » (heure du Burkina Faso = UTC) à partir de secondes Unix. */
fun dateHeureDepuisSecondes(s: Long): String = java.time.LocalDateTime.ofEpochSecond(s, 0, ZoneOffset.UTC).format(DateTimeFormatter.ofPattern("dd/MM/yyyy HH:mm"))

fun lireDroits(j: JSONObject) = Droits(j.optBoolean("administrateur"), j.optBoolean("laboratoire"), j.optBoolean("voir_tous_les_recus"), j.optBoolean("caisse"), j.optBoolean("corrections"),
    j.optBoolean("consultation_seule"))

fun lireRecu(j: JSONObject) = Recu(j.texte("reference"), j.texte("date_vente"), j.texte("heure"), j.texte("date_heure_iso"), j.texte("code_client"), j.texte("patient"), j.optDouble("montant", 0.0),
    j.texte("caissier"), j.optDouble("ppc", 0.0), j.optDouble("part_assure", 0.0), j.optDouble("part_assureur", 0.0), j.optInt("lignes_a_corriger", 0), j.optBoolean("a_corriger"))

fun lireLigne(j: JSONObject) = LigneRecu(j.texte("code_produit"), j.texte("designation"), j.texte("domaine"), j.texte("medecin"), j.optDouble("quantite", 0.0), j.optDouble("prix_unitaire", 0.0),
    j.optDouble("montant", 0.0), j.entierOuNul("jours_validite_propre"), j.optInt("jours_validite_effective", 0), j.optBoolean("necessite_correction"), j.texte("date_expiration"))

private fun <T> JSONArray?.liste(f: (JSONObject) -> T): List<T> = if (this == null) emptyList() else (0 until length()).map { f(getJSONObject(it)) }

fun lireListeRecus(j: JSONObject) = ListeRecus(j.texte("date"), j.optJSONArray("recus").liste(::lireRecu), j.optDouble("total_montant", 0.0), j.optBoolean("tronque"), j.texte("portee"),
    j.optInt("nombre_a_corriger", 0), j.optBoolean("consultation_seule"))

fun lireDetail(j: JSONObject) = DetailRecu(lireRecu(j.getJSONObject("recu")), j.optJSONArray("lignes").liste(::lireLigne), j.optDouble("total", 0.0), j.entierOuNul("validite_clinique"), j.optBoolean("a_corriger"))

// ============================================================================ formats (français, heure du Burkina Faso = UTC)

/** « 15000 » → « 15 000 F » ; décimales (virgule) seulement si le montant n'est pas entier. Espaces insécables : le montant ne se coupe jamais en fin de ligne. */
fun formaterMontant(v: Double, avecDevise: Boolean = true): String {
    val entier = v == Math.floor(v)
    val signe = if (v < 0) "-" else ""
    val abs = Math.abs(v)
    val partieEntiere = abs.toLong().toString().reversed().chunked(3).joinToString(" ").reversed()
    val texte = if (entier) partieEntiere else partieEntiere + "," + String.format(java.util.Locale.ROOT, "%.2f", abs - Math.floor(abs)).substring(2)
    return signe + texte + if (avecDevise) " F" else ""
}

/** Quantité sans décimale inutile : 2.0 → « 2 », 1.5 → « 1,5 ». */
fun formaterQuantite(q: Double): String = if (q == Math.floor(q)) q.toLong().toString() else q.toString().replace(".", ",")

private val FORMAT_JOUR = DateTimeFormatter.ofPattern("dd/MM/yyyy")

fun aujourdhui(): String = LocalDate.now(ZoneOffset.UTC).toString()
fun jourFr(iso: String): String = try { LocalDate.parse(iso).format(FORMAT_JOUR) } catch (e: Exception) { iso }
fun decalerJour(iso: String, jours: Long): String = try { LocalDate.parse(iso).plusDays(jours).toString() } catch (e: Exception) { iso }
/** « 2027-01-24 23:59:59 » → « 24/01/2027 23:59 » */
fun dateHeureFr(texte: String): String = if (texte.length >= 16) "${jourFr(texte.substring(0, 10))} ${texte.substring(11, 16)}" else texte

/** Mot de chaque menu avec une majuscule (règle 18) : « historique de caisse » → « Historique De Caisse ». */
fun titreMenu(t: String): String = t.split(" ").joinToString(" ") { m -> if (m.isEmpty()) m else m.substring(0, 1).uppercase() + m.substring(1) }

// ============================================================================ tri des colonnes (règle 19 : 1er clic croissant, 2e décroissant, 3e ordre d'origine ; vides toujours en dernier)

enum class ColonneTri { HEURE, PATIENT, MONTANT, CAISSIER, REFERENCE }
data class Tri(val colonne: ColonneTri? = null, val croissant: Boolean = true)

/** Prochain état du tri quand on touche une colonne. */
fun basculerTri(actuel: Tri, colonne: ColonneTri): Tri = when {
    actuel.colonne != colonne -> Tri(colonne, true)
    actuel.croissant -> Tri(colonne, false)
    else -> Tri()
}

fun trierRecus(recus: List<Recu>, tri: Tri): List<Recu> {
    val col = tri.colonne ?: return recus
    val vides = recus.filter { cle(it, col).let { k -> k is String && k.isBlank() } }
    val pleins = recus - vides.toSet()
    @Suppress("UNCHECKED_CAST")
    val trie = pleins.sortedWith(Comparator { a, b -> (cle(a, col) as Comparable<Any>).compareTo(cle(b, col)) })
    return (if (tri.croissant) trie else trie.reversed()) + vides
}

private fun cle(r: Recu, c: ColonneTri): Any = when (c) {
    ColonneTri.HEURE -> r.dateHeureIso
    ColonneTri.PATIENT -> r.patient.lowercase()
    ColonneTri.MONTANT -> r.montant
    ColonneTri.CAISSIER -> r.caissier.lowercase()
    ColonneTri.REFERENCE -> r.reference
}
