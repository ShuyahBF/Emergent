package bf.sawali.loois

// =====================================================================================================================================
// Pointage.kt — lot M9 (Loois mobile 1.8.0) : POINTAGE D'INVENTAIRE HORS CONNEXION. Logique pure (aucun écran, aucun réseau) : testable seule.
//
// Demande du propriétaire (28/11/2026) : « l'Internet étant souvent un luxe et n'étant pas stable, l'application Android pourra faire tout le
// pointage sur téléphones, fusionner les pointages de chaque téléphone par commerce et après remonter les données à SAWALI quand une connexion
// sera disponible. Sinon exporter un fichier de pointage par téléphone et le responsable pourra importer par téléphone et fusionner. »
// Choix du propriétaire : dans Loois mobile ; transfert par FICHIER partagé ; chaque téléphone télécharge l'inventaire EN LIGNE une fois
// (QR code + mot de passe du commerce) ; langue du commerce (français / anglais) pour les écrans, la dictée et les fichiers.
//
// Parallèle WinDev : c'est une base HFSQL Classic locale (une par téléphone) qu'on exporte en fichier, puis qu'on fusionne chez le responsable
// avant une synchronisation (HSynchronise) avec le serveur — chaque saisie a un identifiant unique (uid) : jamais comptée deux fois.
// =====================================================================================================================================
import org.json.JSONArray
import org.json.JSONObject
import java.text.Normalizer
import java.time.Instant
import java.util.UUID

const val FORMAT_FICHIER_POINTAGE = "sawali-pointage"

data class LieuP(val id: String, val nom: String)
data class ProduitP(val chrono: Int, val libelle: String, val mesure: String)

/** Inventaire téléchargé une fois en ligne (après le mot de passe du commerce) ; gardé dans le téléphone pour pointer sans Internet. */
data class InventaireP(
    val jeton: String, val id: String, val numero: String, val codeInv: String, val structure: String, val cle: String,
    val langue: String, val lieux: List<LieuP>, val produits: List<ProduitP>, val jetonTelephone: String, val jetonExpire: String,
    /** Lot M9.1 (SAWALI lot 500) : fin de la souscription du commerce au moment du téléchargement ("" = aucune) ; illimitée = sans fin. */
    val souscriptionFin: String = "", val souscriptionIllimitee: Boolean = false,
) {
    /** Le comptage n'est permis que pendant une souscription vérifiée (heure du téléphone ; SAWALI recontrôle à l'envoi). */
    fun peutCompter(maintenant: Instant = Instant.now()): Boolean =
        souscriptionIllimitee || (souscriptionFin.isNotBlank() && runCatching { Instant.parse(souscriptionFin.replace("+00:00", "Z")) }.getOrNull()?.isAfter(maintenant) == true)
    val titre: String get() = listOf(structure, codeInv.ifBlank { numero }).filter { it.isNotBlank() }.joinToString(" · ")
    fun produit(chrono: Int): ProduitP? = produits.firstOrNull { it.chrono == chrono }
}

/** Une saisie (une ligne comptée dans un lieu). `envoyee` : déjà reçue par SAWALI ; `annulee` : retirée par l'auxiliaire. */
data class SaisieP(
    val uid: String, val chrono: Int, val qte: Int, val lieu: String, val peremption: String?, val prenom: String, val appareil: String,
    val le: String, val envoyee: Boolean = false, val annulee: Boolean = false,
)

// ------------------------------------------------------------------------------------------------------------------------------ JSON
/** Texte d'un champ ; une valeur JSON null (ex. « code_inv » d'une liste CSV) donne "" et non le texte « null ». */
fun JSONObject.texte(cle: String, defaut: String = ""): String = if (!has(cle) || isNull(cle)) defaut else optString(cle, defaut)

fun inventaireDepuisAcces(jeton: String, j: JSONObject): InventaireP = InventaireP(
    jeton = jeton, id = j.texte("id"), numero = j.texte("numero"), codeInv = j.texte("code_inv"), structure = j.texte("structure"),
    cle = j.texte("cle_pointage"), langue = j.texte("langue", "fr").ifBlank { "fr" },
    lieux = (0 until (j.optJSONArray("lieux")?.length() ?: 0)).map { j.getJSONArray("lieux").getJSONObject(it).let { l -> LieuP(l.getString("id"), l.getString("nom")) } },
    produits = (0 until (j.optJSONArray("lignes")?.length() ?: 0)).map {
        j.getJSONArray("lignes").getJSONObject(it).let { p -> ProduitP(p.getInt("c"), p.texte("l"), p.texte("m")) } },
    jetonTelephone = j.texte("jeton_telephone"), jetonExpire = j.texte("jeton_expire"),
    souscriptionFin = j.optJSONObject("souscription")?.texte("fin") ?: j.texte("souscription_fin"),
    souscriptionIllimitee = j.optJSONObject("souscription")?.optBoolean("illimite") ?: j.optBoolean("souscription_illimitee"),
)

fun InventaireP.versJson(): JSONObject = JSONObject().put("jeton", jeton).put("id", id).put("numero", numero).put("code_inv", codeInv)
    .put("structure", structure).put("cle_pointage", cle).put("langue", langue).put("jeton_telephone", jetonTelephone).put("jeton_expire", jetonExpire)
    .put("souscription_fin", souscriptionFin).put("souscription_illimitee", souscriptionIllimitee)
    .put("lieux", JSONArray(lieux.map { JSONObject().put("id", it.id).put("nom", it.nom) }))
    .put("lignes", JSONArray(produits.map { JSONObject().put("c", it.chrono).put("l", it.libelle).put("m", it.mesure) }))

fun inventaireDepuisJson(j: JSONObject): InventaireP = inventaireDepuisAcces(j.getString("jeton"), j)

fun SaisieP.versJson(): JSONObject = JSONObject().put("uid", uid).put("chrono", chrono).put("qte", qte).put("lieu", lieu)
    .put("peremption", peremption ?: JSONObject.NULL).put("prenom", prenom).put("appareil", appareil).put("le", le)
    .put("envoyee", envoyee).put("annulee", annulee)

fun saisieDepuisJson(j: JSONObject): SaisieP = SaisieP(
    uid = j.getString("uid"), chrono = j.getInt("chrono"), qte = j.getInt("qte"), lieu = j.getString("lieu"),
    peremption = j.texte("peremption").ifBlank { null }, prenom = j.texte("prenom"),
    appareil = j.texte("appareil"), le = j.texte("le"), envoyee = j.optBoolean("envoyee"), annulee = j.optBoolean("annulee"),
)

/** Saisie telle que SAWALI l'attend (POST …/saisies) : chaque saisie garde le prénom, l'appareil et l'heure de qui a compté. */
fun SaisieP.versEnvoi(): JSONObject = JSONObject().put("uid", uid).put("chrono", chrono).put("qte", qte).put("lieu", lieu)
    .put("peremption", peremption ?: JSONObject.NULL).put("prenom", prenom).put("appareil", appareil).put("le", le)

// ------------------------------------------------------------------------------------------------------------------------------ fichiers de pointage
/** Fichier exporté par un téléphone et partagé au responsable (Bluetooth, WhatsApp, câble, Fichiers). */
fun fichierPointage(inv: InventaireP, saisies: List<SaisieP>, prenom: String, appareil: String, maintenant: String = Instant.now().toString()): JSONObject =
    JSONObject().put("format", FORMAT_FICHIER_POINTAGE).put("version", 1).put("inventaire_id", inv.id).put("numero", inv.numero)
        .put("structure", inv.structure).put("prenom", prenom).put("appareil", appareil).put("exporte_le", maintenant)
        .put("saisies", JSONArray(saisies.filter { !it.annulee }.map { it.copy(envoyee = false).versJson() }))

/** Résultat de la lecture d'un fichier importé. */
data class LectureFichier(val saisies: List<SaisieP>, val prenom: String, val erreur: String? = null)

/** Lit un fichier de pointage ; refuse un fichier d'un AUTRE inventaire (jamais de mélange entre inventaires ou commerces). */
fun lireFichierPointage(texte: String, inv: InventaireP, t: (String) -> String = { it }): LectureFichier {
    val j = try { JSONObject(texte) } catch (e: Exception) { return LectureFichier(emptyList(), "", t("Fichier illisible : ce n'est pas un fichier de pointage.")) }
    if (j.texte("format") != FORMAT_FICHIER_POINTAGE) return LectureFichier(emptyList(), "", t("Fichier illisible : ce n'est pas un fichier de pointage."))
    if (j.texte("inventaire_id") != inv.id) return LectureFichier(emptyList(), j.optString("prenom"), t("Ce fichier appartient à un autre inventaire."))
    val chronos = inv.produits.map { it.chrono }.toSet()
    val lieux = inv.lieux.map { it.id }.toSet()
    val tab = j.optJSONArray("saisies") ?: JSONArray()
    val saisies = (0 until tab.length()).mapNotNull { i -> runCatching { saisieDepuisJson(tab.getJSONObject(i)) }.getOrNull() }
        .filter { it.chrono in chronos && it.lieu in lieux && it.qte >= 0 }
    return LectureFichier(saisies, j.texte("prenom"))
}

/** Fusion : chaque saisie est identifiée par son uid ; une saisie déjà présente n'est JAMAIS ajoutée deux fois (fichier importé deux fois sans risque).
 *  Renvoie la liste fusionnée et le nombre de saisies réellement ajoutées. */
fun fusionner(locales: List<SaisieP>, importees: List<SaisieP>): Pair<List<SaisieP>, Int> {
    val connus = locales.map { it.uid }.toHashSet()
    val nouvelles = importees.filter { connus.add(it.uid) }
    return (locales + nouvelles) to nouvelles.size
}

/** Totaux par ligne et par lieu (saisies non annulées) : ce que montre l'écran du responsable. */
fun totauxParLigne(saisies: List<SaisieP>): Map<Int, Map<String, Int>> =
    saisies.filter { !it.annulee }.groupBy { it.chrono }.mapValues { (_, l) -> l.groupBy { it.lieu }.mapValues { (_, s) -> s.sumOf { it.qte } } }

fun nouvelUid(): String = UUID.randomUUID().toString().replace("-", "")

/** Jeton de l'inventaire à partir du lien du QR code (« https://…/pointage/<jeton> ») ou du jeton seul. */
fun extraireJeton(texte: String): String? {
    val t = texte.trim()
    val brut = if ("/pointage/" in t) t.substringAfter("/pointage/").substringBefore("?").substringBefore("#").trimEnd('/') else t
    return brut.takeIf { Regex("[A-Za-z0-9_-]{20,64}").matches(it) }
}

/** Péremption saisie → « MM/AAAA » (comme la page web), ou null si vide ; « ? » si invalide. */
fun peremptionNormalisee(texte: String): String? {
    val t = texte.trim()
    if (t.isEmpty()) return null
    val m = Regex("""(\d{1,2})\s*[/.\- ]\s*(\d{2}|\d{4})""").matchEntire(t) ?: return "?"
    val mois = m.groupValues[1].toInt()
    var annee = m.groupValues[2].toInt()
    if (annee < 100) annee += 2000
    return if (mois in 1..12 && annee in 2000..2099) "%02d/%d".format(mois, annee) else "?"
}

// ------------------------------------------------------------------------------------------------------------------------------ dictée
/** Ce qui a été compris d'une phrase : champs entendus (null sinon) et commande « suivant » / « annule ». */
data class Dictee(val chrono: Int? = null, val qte: Int? = null, val peremption: String? = null, val commande: String? = null)

private val UNITES = mapOf("zero" to 0, "un" to 1, "une" to 1, "deux" to 2, "trois" to 3, "quatre" to 4, "cinq" to 5, "six" to 6, "sept" to 7, "huit" to 8,
    "neuf" to 9, "dix" to 10, "onze" to 11, "douze" to 12, "treize" to 13, "quatorze" to 14, "quinze" to 15, "seize" to 16,
    "one" to 1, "two" to 2, "three" to 3, "four" to 4, "five" to 5, "seven" to 7, "eight" to 8, "nine" to 9, "ten" to 10, "eleven" to 11,
    "twelve" to 12, "thirteen" to 13, "fourteen" to 14, "fifteen" to 15, "sixteen" to 16, "seventeen" to 17, "eighteen" to 18, "nineteen" to 19, "oh" to 0)
private val DIZAINES = mapOf("vingt" to 20, "vingts" to 20, "trente" to 30, "quarante" to 40, "cinquante" to 50, "soixante" to 60, "septante" to 70,
    "huitante" to 80, "octante" to 80, "nonante" to 90, "twenty" to 20, "thirty" to 30, "forty" to 40, "fifty" to 50, "sixty" to 60, "seventy" to 70,
    "eighty" to 80, "ninety" to 90)
private val MOIS = mapOf("janvier" to 1, "fevrier" to 2, "mars" to 3, "avril" to 4, "mai" to 5, "juin" to 6, "juillet" to 7, "aout" to 8, "septembre" to 9,
    "octobre" to 10, "novembre" to 11, "decembre" to 12, "january" to 1, "february" to 2, "march" to 3, "april" to 4, "may" to 5, "june" to 6, "july" to 7,
    "august" to 8, "september" to 9, "october" to 10, "november" to 11, "december" to 12)
private val ETIQUETTES = mapOf("ligne" to "chrono", "numero" to "chrono", "n" to "chrono", "no" to "chrono", "ordre" to "chrono", "produit" to "chrono",
    "line" to "chrono", "number" to "chrono", "item" to "chrono", "quantite" to "qte", "qte" to "qte", "nombre" to "qte", "stock" to "qte",
    "quantity" to "qte", "qty" to "qte", "count" to "qte", "peremption" to "per", "perime" to "per", "expire" to "per", "expiration" to "per",
    "date" to "per", "lot" to "per", "expiry" to "per", "expires" to "per", "best" to "per")
private val SUIVANT = setOf("suivant", "suivante", "valider", "valide", "enregistre", "enregistrer", "ok", "okay", "next", "save", "done")
private val ANNULE = setOf("annule", "annuler", "efface", "effacer", "corrige", "corriger", "supprime", "supprimer", "undo", "cancel", "delete")

private sealed class Jeton {
    data class Nombre(val v: Int, val brut: String? = null) : Jeton()
    data class Mois(val v: Int) : Jeton()
    data class Date(val mois: Int, val annee: Int) : Jeton()
    data class Etiquette(val v: String) : Jeton()
    data class Commande(val v: String) : Jeton()
}

private fun normaliserDictee(texte: String): String = Normalizer.normalize(texte, Normalizer.Form.NFD).replace(Regex("\\p{Mn}+"), "").lowercase()
    .replace("n°", " numero ").replace(Regex("""(\d)\s*[/.\-]\s*(\d)"""), "$1/$2").replace(Regex("[^a-z0-9/]+"), " ").trim()

/** Même analyseur que la page web (lib/dicteePointage.js) : nombres en chiffres ou en lettres, français ou anglais, mois, commandes. */
private fun jetons(texte: String): List<Jeton> {
    val sortie = mutableListOf<Jeton>()
    var total: Int? = null; var courant = 0; var dernier: Int? = null
    fun finir() { total?.let { sortie += Jeton.Nombre(it + courant) }; total = null; courant = 0; dernier = null }
    for (mot in normaliserDictee(texte).split(Regex("\\s+")).filter { it.isNotEmpty() }) {
        if ((mot == "et" || mot == "and") && total != null) continue
        val u = UNITES[mot]; val d = DIZAINES[mot]
        when {
            u != null -> {
                val nouveau = total != null && dernier != null && dernier!! < 20 && !(dernier == 10 && u < 10) && dernier != 100
                if (nouveau) finir()
                if (total == null) total = 0
                courant += u; dernier = u
            }
            d != null -> {
                if (total == null) total = 0
                if (d == 20 && courant % 100 == 4 && dernier == 4) courant = courant - 4 + 80
                else if (dernier != null && dernier != 100) { finir(); total = 0; courant = d }
                else courant += d
                dernier = 20
            }
            mot == "cent" || mot == "cents" || mot == "hundred" -> { if (total == null) total = 0; courant = (if (courant == 0) 1 else courant) * 100; dernier = 100 }
            mot == "mille" || mot == "thousand" -> { if (total == null) total = 0; total = total!! + (if (courant == 0) 1 else courant) * 1000; courant = 0; dernier = 100 }
            else -> {
                finir()
                val date = Regex("""(\d{1,2})/(\d{2}|\d{4})""").matchEntire(mot)
                when {
                    date != null -> sortie += Jeton.Date(date.groupValues[1].toInt(), date.groupValues[2].toInt())
                    mot.all { it.isDigit() } && mot.length <= 9 -> sortie += Jeton.Nombre(mot.toInt(), mot)
                    mot in MOIS -> sortie += Jeton.Mois(MOIS.getValue(mot))
                    mot in ETIQUETTES -> sortie += Jeton.Etiquette(ETIQUETTES.getValue(mot))
                    mot in SUIVANT -> sortie += Jeton.Commande("suivant")
                    mot in ANNULE -> sortie += Jeton.Commande("annule")
                }
            }
        }
    }
    finir()
    return sortie
}

private fun moisAnnee(mois: Int, annee: Int): String? { val a = if (annee < 100) annee + 2000 else annee; return if (mois in 1..12 && a in 2000..2099) "%02d/%d".format(mois, a) else null }

/** « ligne 245, 12, mars 2027, suivant » / « line 245, twelve, March 2027, next » → Dictee(245, 12, "03/2027", "suivant"). */
fun analyserDictee(texte: String): Dictee {
    val js = jetons(texte)
    var chrono: Int? = null; var qte: Int? = null; var per: String? = null; var commande: String? = null; var cible: String? = null
    var i = 0
    while (i < js.size) {
        when (val j = js[i]) {
            is Jeton.Commande -> commande = j.v
            is Jeton.Etiquette -> cible = j.v
            is Jeton.Date -> { moisAnnee(j.mois, j.annee)?.let { per = it }; cible = null }
            is Jeton.Mois -> { val a = (js.getOrNull(i + 1) as? Jeton.Nombre)?.v; if (a != null) { i++; moisAnnee(j.v, a)?.let { per = it } }; cible = null }
            is Jeton.Nombre -> {
                val champ = cible ?: when { chrono == null -> "chrono"; qte == null -> "qte"; per == null -> "per"; else -> null }
                cible = null
                when (champ) {
                    "chrono" -> chrono = j.v
                    "qte" -> qte = j.v
                    "per" -> {
                        val suivant = js.getOrNull(i + 1) as? Jeton.Nombre
                        val d = suivant?.let { moisAnnee(j.v, it.v) }
                        if (d != null) { per = d; i++ }
                        else if (j.brut?.length == 6) moisAnnee(j.brut.substring(0, 2).toInt(), j.brut.substring(2).toInt())?.let { per = it }
                    }
                }
            }
        }
        i++
    }
    return Dictee(chrono, qte, per, commande)
}

// ------------------------------------------------------------------------------------------------------------------------------ langue
/** Textes du pointage en anglais (le français est la clé, comme sur la page web : lib/i18nPointage.js). */
private val EN = mapOf(
    "Pointage d'inventaire" to "Stock count", "Sans Internet : comptez, exportez, fusionnez, envoyez." to "No Internet needed: count, export, merge, send.",
    "Ajouter un inventaire" to "Add a count", "Scanner le QR code" to "Scan the QR code", "Lien ou code du QR" to "QR link or code",
    "Ouvrir" to "Open", "Mot de passe du commerce" to "Shop password", "Valider" to "Confirm", "Votre prénom" to "Your first name",
    "Lieu que vous comptez" to "Location you are counting", "Commencer le pointage" to "Start counting", "Ligne" to "Line", "Quantité" to "Quantity",
    "Péremption" to "Expiry", "Dicter" to "Dictate", "Suivant" to "Next", "Annuler la dernière" to "Undo last", "Exporter" to "Export",
    "Importer" to "Import", "Envoyer à SAWALI" to "Send to SAWALI", "Supprimer" to "Delete", "Retour" to "Back",
    "Dites ou tapez le N° de ligne" to "Say or type the line number", "Ligne inconnue" to "Unknown line", "Quantité manquante" to "Quantity missing",
    "Enregistré" to "Saved", "{n} saisie(s), {e} à envoyer" to "{n} entry(ies), {e} to send", "Tout est envoyé" to "Everything sent",
    "Envoi impossible : pas de connexion. Les saisies restent dans le téléphone." to "Cannot send: no connection. Entries stay on the phone.",
    "{n} saisie(s) envoyée(s) à SAWALI." to "{n} entry(ies) sent to SAWALI.", "{n} saisie(s) ajoutée(s) depuis {p}." to "{n} entry(ies) added from {p}.",
    "Fichier illisible : ce n'est pas un fichier de pointage." to "Unreadable file: not a count file.",
    "Ce fichier appartient à un autre inventaire." to "This file belongs to another count.",
    "Mot de passe du commerce à ressaisir." to "Please enter the shop password again.",
    "Aucun inventaire dans ce téléphone : ajoutez-en un avec le QR code (connexion nécessaire une seule fois)." to
        "No count on this phone: add one with the QR code (connection needed only once).",
    "Lignes comptées" to "Counted lines", "Dernières saisies" to "Latest entries", "Changer de lieu ou de prénom" to "Change location or name",
    "Fusionner les fichiers des autres téléphones" to "Merge files from other phones", "Supprimer cet inventaire du téléphone ?" to "Delete this count from the phone?",
    "Dictée indisponible sur ce téléphone : utilisez le clavier." to "Dictation not available on this phone: use the keyboard.",
    "Patientez…" to "Please wait…",
    "Souscription expirée : le comptage est fermé. Vous pouvez encore exporter, fusionner et envoyer les saisies déjà faites." to
        "Subscription expired: counting is closed. You can still export, merge and send entries already made.",
    "Ma souscription" to "My subscription", "Clé de pointage" to "Count key", "Se connecter" to "Sign in", "Formule" to "Plan", "Opérateur" to "Operator",
    "Composer" to "Dial", "Référence de la transaction" to "Transaction reference", "Envoyer la référence" to "Send the reference",
    "Payez avec la séquence, puis saisissez la référence (ID) de la transaction reçue par SMS." to "Pay with the code, then enter the transaction reference (ID) received by SMS.",
    "Souscription valide jusqu'au {d}" to "Subscription valid until {d}", "Souscription illimitée" to "Unlimited subscription", "Sans souscription valide" to "No valid subscription",
    "Paiement vérifié : souscription active." to "Payment verified: subscription active.",
    "Demande enregistrée : elle sera vérifiée dès réception du SMS de paiement, ou par SAWALI." to "Request saved: it will be checked as soon as the payment SMS arrives, or by SAWALI.",
    "Semaine" to "Week", "Mois" to "Month", "Année" to "Year", "Illimité" to "Unlimited", "En attente de vérification" to "Awaiting verification", "Vérifiée" to "Verified", "Refusée" to "Rejected",
    "Rouvrez l'inventaire avec le mot de passe pour mettre à jour la souscription." to "Reopen the count with the password to refresh the subscription.", "additionnée" to "added up", "envoyée" to "sent", "à envoyer" to "to send", "annulée" to "undone",
)

/** Texte dans la langue du commerce, avec « {n} » remplacé par la valeur. */
fun traduire(langue: String, fr: String, vararg valeurs: Pair<String, Any>): String {
    var t = if (langue == "en") EN[fr] ?: fr else fr
    valeurs.forEach { (k, v) -> t = t.replace("{$k}", v.toString()) }
    return t
}

/** Langue de la dictée Android. */
fun langueDictee(langue: String) = if (langue == "en") "en-US" else "fr-FR"
