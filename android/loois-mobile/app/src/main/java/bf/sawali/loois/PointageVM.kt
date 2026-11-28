package bf.sawali.loois

// =====================================================================================================================================
// PointageVM.kt — lot M9 : état et actions du POINTAGE HORS CONNEXION (stockage dans le téléphone, réseau, fichiers).
//   - Stockage : un fichier JSON par inventaire dans le dossier privé de l'application (filesDir/pointage/<jeton>.json) :
//     inventaire téléchargé + saisies + prénom + lieu. Rien n'est perdu si le téléphone s'éteint ou n'a plus de réseau.
//   - Réseau (SAWALI, routes PUBLIQUES du pointage, sans le jeton de l'appareil Loois) : GET /api/public/pointage/{jeton},
//     POST …/acces (mot de passe du commerce), POST …/saisies (en-tête X-Pointage-Telephone), par paquets de 200.
//   - Fichiers : export (partage Android) et import (sélecteur de fichiers) ; la fusion ne compte jamais deux fois une saisie (uid).
// Parallèle WinDev : une classe de traitement (procédures globales) séparée des fenêtres, appelée par les boutons.
// =====================================================================================================================================
import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.time.Instant

enum class EcranP { LISTE, AJOUT, MOT_DE_PASSE, PRENOM, COMPTAGE, SOUSCRIPTION }

/** Lot M9.1 : état de la souscription lu dans l'Espace pointage (clé + mot de passe du commerce). */
data class OffreP(val formule: String, val montant: Int, val sequence: String, val lien: String)
data class OperateurP(val id: String, val nom: String, val offres: List<OffreP>)
data class SouscriptionP(val valide: Boolean, val illimite: Boolean, val fin: String, val enAttente: Int, val devise: String,
                         val operateurs: List<OperateurP>, val historique: List<JSONObject>)

/** Ce que montrent les écrans du pointage. */
data class EtatPointage(
    val ecran: EcranP = EcranP.LISTE,
    val inventaires: List<InventaireP> = emptyList(),     // inventaires gardés dans le téléphone
    val courant: InventaireP? = null,
    val saisies: List<SaisieP> = emptyList(),
    val prenom: String = "", val lieu: String = "",
    val jetonEnAttente: String = "", val titreEnAttente: String = "", val cleEnAttente: String = "", val langueEnAttente: String = "fr",
    val enCours: Boolean = false, val message: String = "", val messageErreur: Boolean = false,
    val jetonEspace: String = "", val souscription: SouscriptionP? = null,      // lot M9.1 : écran « Ma souscription »
) {
    val langue: String get() = courant?.langue ?: langueEnAttente
    fun t(fr: String, vararg v: Pair<String, Any>) = traduire(langue, fr, *v)
    val aEnvoyer: Int get() = saisies.count { !it.envoyee && !it.annulee }
}

class PointageVM(app: Application) : AndroidViewModel(app) {
    private val stockage = Stockage(app)
    private val dossier = File(app.filesDir, "pointage").apply { mkdirs() }
    private val prefs = app.getSharedPreferences("pointage", 0)
    /** Identifiant de CE téléphone (pas d'identifiant personnel) : sert à annuler ses propres saisies. */
    val appareil: String = prefs.getString("appareil", null) ?: nouvelUid().also { prefs.edit().putString("appareil", it).apply() }

    private val _etat = MutableStateFlow(EtatPointage())
    val etat: StateFlow<EtatPointage> = _etat.asStateFlow()
    private fun maj(f: (EtatPointage) -> EtatPointage) = _etat.update(f)
    private fun dire(message: String, erreur: Boolean = false) = maj { it.copy(message = message, messageErreur = erreur, enCours = false) }

    init { chargerListe() }

    // ------------------------------------------------------------------------------------------------ stockage local
    private fun fichier(jeton: String) = File(dossier, "$jeton.json")

    private fun chargerListe() = maj { e -> e.copy(inventaires = dossier.listFiles { f -> f.extension == "json" }.orEmpty()
        .mapNotNull { runCatching { inventaireDepuisJson(JSONObject(it.readText()).getJSONObject("inventaire")) }.getOrNull() }.sortedBy { it.titre }) }

    /** Écrit l'inventaire courant et ses saisies (appelé après CHAQUE saisie : rien ne se perd). */
    private fun sauver() {
        val e = _etat.value
        val inv = e.courant ?: return
        val j = JSONObject().put("inventaire", inv.versJson()).put("prenom", e.prenom).put("lieu", e.lieu)
            .put("saisies", JSONArray(e.saisies.map { it.versJson() }))
        val tmp = File(dossier, "${inv.jeton}.tmp")
        tmp.writeText(j.toString())
        tmp.renameTo(fichier(inv.jeton))                      // écriture atomique : jamais de fichier à moitié écrit
    }

    fun ouvrir(inv: InventaireP) {
        val j = runCatching { JSONObject(fichier(inv.jeton).readText()) }.getOrNull()
        val saisies = j?.optJSONArray("saisies")?.let { a -> (0 until a.length()).map { saisieDepuisJson(a.getJSONObject(it)) } } ?: emptyList()
        val prenom = j?.texte("prenom").orEmpty(); val lieu = j?.texte("lieu").orEmpty()
        maj { it.copy(courant = inv, saisies = saisies, prenom = prenom, lieu = lieu, message = "",
            ecran = if (prenom.isNotBlank() && inv.lieux.any { l -> l.id == lieu }) EcranP.COMPTAGE else EcranP.PRENOM) }
    }

    fun supprimer(inv: InventaireP) { fichier(inv.jeton).delete(); maj { it.copy(courant = null, ecran = EcranP.LISTE) }; chargerListe() }
    fun aller(e: EcranP) = maj { it.copy(ecran = e, message = "") }
    fun effacerMessage() = maj { it.copy(message = "") }

    // ------------------------------------------------------------------------------------------------ réseau (SAWALI)
    private suspend fun http(chemin: String, corps: JSONObject? = null, jetonTel: String? = null, jetonEspace: String? = null): JSONObject = withContext(Dispatchers.IO) {
        val cx = URL(stockage.urlSawali.trimEnd('/') + "/api" + chemin).openConnection() as HttpURLConnection
        try {
            cx.requestMethod = if (corps == null) "GET" else "POST"
            cx.connectTimeout = 15_000; cx.readTimeout = 60_000
            cx.setRequestProperty("Accept", "application/json")
            cx.setRequestProperty("User-Agent", "LooisMobile/${BuildConfig.VERSION_NAME}")
            jetonTel?.let { cx.setRequestProperty("X-Pointage-Telephone", it) }
            jetonEspace?.let { cx.setRequestProperty("X-Pointage-Jeton", it) }
            if (corps != null) {
                cx.doOutput = true
                cx.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                cx.outputStream.use { it.write(corps.toString().toByteArray(Charsets.UTF_8)) }
            }
            val code = cx.responseCode
            val texte = (if (code >= 400) cx.errorStream else cx.inputStream)?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            if (code >= 400) throw ErreurApi(code, messageErreur(code, texte))
            if (texte.isBlank()) JSONObject() else JSONObject(texte)
        } catch (e: ErreurApi) { throw e
        } catch (e: IOException) { throw ErreurReseau("Serveur injoignable : vérifiez la connexion.")
        } finally { cx.disconnect() }
    }

    /** 1. Lien ou code du QR → nom du commerce et clé (connexion nécessaire une seule fois). */
    fun preparer(lienOuCode: String) {
        val jeton = extraireJeton(lienOuCode) ?: return dire("Lien du QR code invalide.", true)
        _etat.value.inventaires.firstOrNull { it.jeton == jeton }?.let { return ouvrir(it) }   // déjà dans le téléphone
        maj { it.copy(enCours = true, message = "") }
        viewModelScope.launch {
            try {
                val j = http("/public/pointage/$jeton")
                maj { it.copy(jetonEnAttente = jeton, titreEnAttente = listOf(j.texte("structure"), j.texte("code_inv").ifBlank { j.texte("numero") })
                    .filter { s -> s.isNotBlank() }.joinToString(" · "), cleEnAttente = j.texte("cle_pointage"), langueEnAttente = j.texte("langue", "fr"),
                    ecran = EcranP.MOT_DE_PASSE, enCours = false) }
            } catch (e: Exception) { dire(e.message ?: "Erreur", true) }
        }
    }

    /** 2. Mot de passe du commerce → inventaire complet gardé dans le téléphone (lieux, produits, jeton du téléphone). */
    fun deverrouiller(motDePasse: String) {
        val e0 = _etat.value
        val jeton = e0.jetonEnAttente.ifBlank { e0.courant?.jeton.orEmpty() }
        maj { it.copy(enCours = true, message = "") }
        viewModelScope.launch {
            try {
                val j = http("/public/pointage/$jeton/acces", JSONObject().put("mot_de_passe", motDePasse))
                val inv = inventaireDepuisAcces(jeton, j)
                val dejaLa = e0.courant?.jeton == jeton
                maj { it.copy(courant = inv, saisies = if (dejaLa) it.saisies else emptyList(), enCours = false,
                    ecran = if (dejaLa && it.prenom.isNotBlank()) EcranP.COMPTAGE else EcranP.PRENOM) }
                sauver(); chargerListe()
            } catch (e: Exception) { dire(e.message ?: "Erreur", true) }
        }
    }

    fun commencer(prenom: String, lieu: String) { maj { it.copy(prenom = prenom.trim(), lieu = lieu, ecran = EcranP.COMPTAGE, message = "") }; sauver() }

    // ------------------------------------------------------------------------------------------------ comptage
    /** « Suivant » : contrôle puis enregistrement DANS LE TÉLÉPHONE (aucun réseau nécessaire). Renvoie vrai si la saisie est gardée. */
    fun saisir(chrono: Int?, qte: Int?, peremption: String?): Boolean {
        val e = _etat.value
        val inv = e.courant ?: return false
        // Lot M9.1 : pas de nouveau comptage sans souscription vérifiée (l'export, la fusion et l'envoi restent possibles)
        if (!inv.peutCompter()) { dire(e.t("Souscription expirée : le comptage est fermé. Vous pouvez encore exporter, fusionner et envoyer les saisies déjà faites.") +
            " " + e.t("Rouvrez l'inventaire avec le mot de passe pour mettre à jour la souscription."), true); return false }
        if (chrono == null || inv.produit(chrono) == null) { dire(e.t("Ligne inconnue"), true); return false }
        if (qte == null || qte < 0) { dire(e.t("Quantité manquante"), true); return false }
        val per = peremption?.let { peremptionNormalisee(it) }
        val s = SaisieP(nouvelUid(), chrono, qte, e.lieu, per?.takeIf { it != "?" }, e.prenom, appareil, Instant.now().toString())
        val doublon = e.saisies.any { !it.annulee && it.chrono == chrono && it.lieu == e.lieu }
        maj { it.copy(saisies = it.saisies + s, message = e.t("Enregistré") + " : $chrono · ${inv.produit(chrono)?.libelle} · $qte" +
            if (doublon) " (${e.t("additionnée")})" else "", messageErreur = false) }
        sauver()
        return true
    }

    /** « Annule » : la dernière saisie de ce téléphone est marquée annulée (et retirée de SAWALI au prochain envoi si elle y était déjà). */
    fun annulerDerniere() {
        val derniere = _etat.value.saisies.lastOrNull { !it.annulee && it.appareil == appareil } ?: return
        maj { e -> e.copy(saisies = e.saisies.map { if (it.uid == derniere.uid) it.copy(annulee = true) else it }, message = e.t("annulée") + " : ${derniere.chrono}") }
        sauver()
        if (derniere.envoyee) viewModelScope.launch {                  // déjà reçue par SAWALI : annulation en ligne si possible
            runCatching { _etat.value.courant?.let { http("/public/pointage/${it.jeton}/annuler", JSONObject().put("appareil", appareil).put("uid", derniere.uid), it.jetonTelephone) } }
        }
    }

    // ------------------------------------------------------------------------------------------------ envoi à SAWALI (quand une connexion existe)
    fun envoyer() {
        val e0 = _etat.value
        val inv = e0.courant ?: return
        maj { it.copy(enCours = true, message = e0.t("Patientez…")) }
        viewModelScope.launch {
            var total = 0
            try {
                for (paquet in _etat.value.saisies.filter { !it.envoyee && !it.annulee }.chunked(200)) {
                    val r = http("/public/pointage/${inv.jeton}/saisies", JSONObject().put("prenom", _etat.value.prenom.takeIf { it.length >= 2 } ?: "Responsable")
                        .put("appareil", appareil).put("saisies", JSONArray(paquet.map { it.versEnvoi() })), inv.jetonTelephone)
                    val recues = r.optJSONArray("acceptees")?.let { a -> (0 until a.length()).map { a.getString(it) }.toSet() } ?: emptySet()
                    total += recues.size
                    maj { e -> e.copy(saisies = e.saisies.map { if (it.uid in recues) it.copy(envoyee = true) else it }) }
                    sauver()
                }
                dire(e0.t("{n} saisie(s) envoyée(s) à SAWALI.", "n" to total))
            } catch (e: ErreurApi) {
                if (e.code == 401) maj { it.copy(ecran = EcranP.MOT_DE_PASSE, jetonEnAttente = inv.jeton, titreEnAttente = inv.titre, cleEnAttente = inv.cle,
                    langueEnAttente = inv.langue, enCours = false, message = e0.t("Mot de passe du commerce à ressaisir."), messageErreur = true) }
                else dire(e.message ?: "Erreur", true)
            } catch (e: Exception) { dire(e0.t("Envoi impossible : pas de connexion. Les saisies restent dans le téléphone."), true) }
        }
    }

    // ------------------------------------------------------------------------------------------------ fichiers (sans Internet)
    /** Fichier de pointage de CE téléphone, à partager au responsable. */
    fun fichierExport(): File? {
        val e = _etat.value
        val inv = e.courant ?: return null
        val nom = "pointage_${inv.numero}_${e.prenom.ifBlank { "telephone" }}.json".replace(Regex("[^A-Za-z0-9_.-]"), "_")
        val f = File(File(getApplication<Application>().cacheDir, "partage").apply { mkdirs() }, nom)
        f.writeText(fichierPointage(inv, e.saisies, e.prenom, appareil).toString(2))      // toutes les saisies du téléphone (y compris celles déjà fusionnées)
        return f
    }

    /** Import des fichiers reçus des autres téléphones, puis fusion (sans doublon). */
    fun importer(uris: List<Uri>) {
        val e0 = _etat.value
        val inv = e0.courant ?: return
        val resolveur = getApplication<Application>().contentResolver
        val messages = mutableListOf<String>()
        var saisies = e0.saisies
        for (u in uris) {
            val texte = runCatching { resolveur.openInputStream(u)?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } }.getOrNull().orEmpty()
            val lu = lireFichierPointage(texte, inv) { e0.t(it) }
            if (lu.erreur != null) { messages += lu.erreur; continue }
            val (fusion, ajoutees) = fusionner(saisies, lu.saisies)
            saisies = fusion
            messages += e0.t("{n} saisie(s) ajoutée(s) depuis {p}.", "n" to ajoutees, "p" to lu.prenom.ifBlank { "?" })
        }
        maj { it.copy(saisies = saisies, message = messages.joinToString("\n"), messageErreur = false) }
        sauver()
    }

    // ------------------------------------------------------------------------------------------------ lot M9.1 : souscription (Espace pointage)
    /** Connexion à l'Espace pointage du commerce (clé + mot de passe) pour voir et renouveler la souscription. */
    fun connecterEspace(cle: String, motDePasse: String) {
        maj { it.copy(enCours = true, message = "") }
        viewModelScope.launch {
            try {
                val j = http("/pointage-espace/connexion", JSONObject().put("cle", cle).put("mot_de_passe", motDePasse))
                maj { it.copy(jetonEspace = j.texte("jeton"), langueEnAttente = j.optJSONObject("commerce")?.texte("langue", "fr") ?: "fr") }
                chargerSouscription()
            } catch (e: Exception) { dire(e.message ?: "Erreur", true) }
        }
    }

    fun chargerSouscription() {
        val jeton = _etat.value.jetonEspace.ifBlank { return }
        maj { it.copy(enCours = true) }
        viewModelScope.launch {
            try {
                val j = http("/pointage-espace/souscription", jetonEspace = jeton)
                val etat = j.getJSONObject("etat")
                val ops = j.optJSONArray("operateurs") ?: JSONArray()
                val operateurs = (0 until ops.length()).map { i -> val o = ops.getJSONObject(i); val f = o.optJSONObject("formules") ?: JSONObject()
                    OperateurP(o.texte("id"), o.texte("nom"), f.keys().asSequence().map { k -> val x = f.getJSONObject(k)
                        OffreP(k, x.optInt("montant"), x.texte("sequence"), x.texte("lien")) }.toList()) }
                val h = j.optJSONArray("historique") ?: JSONArray()
                maj { it.copy(enCours = false, souscription = SouscriptionP(etat.optBoolean("valide"), etat.optBoolean("illimite"), etat.texte("fin"),
                    etat.optInt("en_attente"), j.texte("devise", "FCFA"), operateurs, (0 until h.length()).map { i -> h.getJSONObject(i) })) }
            } catch (e: ErreurApi) {
                if (e.code == 401) maj { it.copy(jetonEspace = "", souscription = null) }
                dire(e.message ?: "Erreur", true)
            } catch (e: Exception) { dire(e.message ?: "Erreur", true) }
        }
    }

    /** Après le paiement mobile : la référence est rapprochée du SMS de paiement par SAWALI (ou validée par l'administrateur). */
    fun souscrire(formule: String, operateur: String, reference: String) {
        val e0 = _etat.value
        maj { it.copy(enCours = true, message = "") }
        viewModelScope.launch {
            try {
                val j = http("/pointage-espace/souscription", JSONObject().put("formule", formule).put("operateur", operateur).put("reference", reference.trim()),
                    jetonEspace = e0.jetonEspace)
                val verifiee = j.optJSONObject("souscription")?.texte("statut") == "verifiee"
                dire(if (verifiee) e0.t("Paiement vérifié : souscription active.") else e0.t("Demande enregistrée : elle sera vérifiée dès réception du SMS de paiement, ou par SAWALI."))
                chargerSouscription()
            } catch (e: Exception) { dire(e.message ?: "Erreur", true) }
        }
    }
}
