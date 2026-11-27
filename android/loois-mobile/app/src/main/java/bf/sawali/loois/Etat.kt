package bf.sawali.loois

import android.app.Application
import android.os.Build
import android.provider.Settings
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.util.UUID

/** Écrans de l'application. */
enum class Ecran { DEMARRAGE, ATTENTE_AUTORISATION, CONNEXION, MENU, HISTORIQUE, DETAIL, CORRECTIONS, PARAMETRES }

/** Tout ce que l'interface affiche (un seul objet : l'écran se redessine quand il change). */
data class UiEtat(
    val ecran: Ecran = Ecran.DEMARRAGE,
    val enCours: Boolean = false,
    val message: String? = null,                  // message bref (toast) ; l'écran l'affiche puis l'efface
    val serveur: String = "verification",         // verification, actif, lent, injoignable
    val modeAffiche: String = "",                 // « Internet (SQL distantes) » ou « Réseau local »
    val appareilId: String = "",
    val statut: StatutAppareil? = null,
    val messageAttente: String = "",
    val utilisateur: Utilisateur? = null,
    val droits: Droits? = null,
    val jour: String = aujourdhui(),
    val caissierFiltre: String = "",
    val historique: ListeRecus? = null,
    val corrections: ListeRecus? = null,
    val seulementACorriger: Boolean = true,
    val detail: DetailRecu? = null,
    val retourDetail: Ecran = Ecran.HISTORIQUE,
    val selection: String? = null,                // reçu sélectionné (orange, règle 3)
    val tri: Tri = Tri(),
    val urlSawali: String = "",
    val urlLocale: String = "",
    val mode: String = "auto",
)

/**
 * Logique de l'application : enregistrement de l'appareil, statut (Autorisé / Interdit), connexion de l'utilisateur, Historique de Caisse, Corrections de reçus.
 * Les appels réseau passent par `appel` : Internet (SQL distantes via SAWALI) si une connexion Internet est détectée, sinon l'adresse du serveur local définie dans les paramètres.
 */
class AppViewModel(app: Application) : AndroidViewModel(app) {
    private val stockage = Stockage(app)
    private val api = ClientApi(stockage)
    private val _etat = MutableStateFlow(UiEtat(urlSawali = stockage.urlSawali, urlLocale = stockage.urlLocale, mode = stockage.mode, appareilId = stockage.appareilId))
    val etat: StateFlow<UiEtat> = _etat.asStateFlow()

    init { demarrer() }

    private fun maj(f: (UiEtat) -> UiEtat) = _etat.update(f)

    /** Pour les tests de l'interface : impose un état (jamais utilisé par l'application). */
    internal fun forcerEtat(e: UiEtat) { _etat.value = e }
    fun messageAffiche() = maj { it.copy(message = null) }
    private fun dire(m: String) = maj { it.copy(message = m) }

    // ------------------------------------------------------------------------------------------------------------ réseau : Internet ou serveur local
    /** Adresses à essayer, dans l'ordre, selon le mode choisi et la connexion détectée. */
    private fun bases(): List<String> {
        val internet = stockage.urlSawali
        val local = stockage.urlLocale
        return when (stockage.mode) {
            "internet" -> listOf(internet)
            "local" -> if (local.isBlank()) throw ErreurReseau("Adresse du serveur local non définie (Paramètres).") else listOf(local)
            else -> if (internetDisponible(getApplication())) listOfNotNull(internet, local.ifBlank { null }) else listOfNotNull(local.ifBlank { null }, internet)
        }
    }

    private suspend fun <T> appel(bloc: suspend (String) -> T): T {
        var derniere: Exception? = null
        for (base in bases()) {
            try {
                val r = bloc(base)
                maj { it.copy(modeAffiche = if (base == stockage.urlLocale && base != stockage.urlSawali) "Réseau local · $base" else "Internet · SQL distantes") }
                return r
            } catch (e: ErreurReseau) { derniere = e }      // réseau en panne : on tente l'adresse suivante ; les erreurs du serveur (ErreurApi) remontent telles quelles
        }
        throw derniere ?: ErreurReseau("Serveur injoignable.")
    }

    /** Traduit une erreur en message pour l'utilisateur ; une session expirée ramène à la connexion, un appareil interdit à l'écran d'attente. */
    private fun gerer(e: Exception) {
        when {
            e is ErreurApi && e.code == 401 && api.session != null -> { api.session = null; maj { it.copy(ecran = Ecran.CONNEXION, utilisateur = null, droits = null, message = "Session expirée : reconnectez-vous.") } }
            e is ErreurApi && e.code == 403 && (e.message ?: "").contains("interdit", true) -> { api.session = null; maj { it.copy(ecran = Ecran.ATTENTE_AUTORISATION, messageAttente = e.message ?: "", message = e.message) } }
            else -> dire(e.message ?: "Erreur inattendue.")
        }
    }

    // ------------------------------------------------------------------------------------------------------------ démarrage, enregistrement, statut
    fun demarrer() {
        viewModelScope.launch {
            verifierServeur()
            if (stockage.jeton == null) enregistrer() else rafraichirStatut()
        }
    }

    /** « Serveur actif » / « lent » / « injoignable » (comme la page de connexion de SAWALI). */
    fun verifierServeur() {
        viewModelScope.launch {
            maj { it.copy(serveur = "verification") }
            val debut = System.currentTimeMillis()
            try {
                appel { base -> api.appeler(base, "/api/version", methode = "GET", avecSession = false, delaiConnexionMs = 6_000, delaiLectureMs = 8_000) }
                val ms = System.currentTimeMillis() - debut
                maj { it.copy(serveur = if (ms > 2500) "lent" else "actif") }
            } catch (e: Exception) { maj { it.copy(serveur = "injoignable") } }
        }
    }

    private fun identifiantAndroid(): String {
        val brut = Settings.Secure.getString(getApplication<Application>().contentResolver, Settings.Secure.ANDROID_ID)
        return if (brut != null && brut.length >= 8) brut else "LM-" + UUID.randomUUID().toString().replace("-", "")
    }

    /** Premier lancement : SAWALI crée la fiche de l'appareil « Interdit » et rend son jeton secret (une seule fois). */
    fun enregistrer() {
        viewModelScope.launch {
            maj { it.copy(enCours = true) }
            try {
                val corps = JSONObject().put("android_id", identifiantAndroid()).put("modele", "${Build.MANUFACTURER} ${Build.MODEL}".take(80)).put("version_app", BuildConfig.VERSION_NAME)
                val r = appel { base -> api.appeler(base, "/api/android/appareil/enregistrer", corps, avecSession = false) }
                stockage.jeton = r.getString("jeton")
                stockage.appareilId = r.optString("appareil_id")
                appliquerStatut(lireStatut(r), r.optString("appareil_id"))
            } catch (e: ErreurApi) {
                maj { it.copy(ecran = Ecran.ATTENTE_AUTORISATION, messageAttente = e.message ?: "", message = e.message) }
            } catch (e: Exception) { gererDemarrage(e) } finally { maj { it.copy(enCours = false) } }
        }
    }

    /** Demande à SAWALI l'état de l'appareil (Autorisé / Interdit) : l'IP vue par le serveur est notée ; rend zone, base et nom d'utilisateur quand l'accès est autorisé. */
    fun rafraichirStatut() {
        viewModelScope.launch {
            maj { it.copy(enCours = true) }
            try {
                val r = appel { base -> api.appeler(base, "/api/android/appareil/statut", JSONObject().put("version_app", BuildConfig.VERSION_NAME), avecSession = false) }
                appliquerStatut(lireStatut(r), stockage.appareilId)
            } catch (e: ErreurApi) {
                if (e.code == 401) { stockage.oublierAppareil(); enregistrer() } else maj { it.copy(ecran = Ecran.ATTENTE_AUTORISATION, messageAttente = e.message ?: "", message = e.message) }
            } catch (e: Exception) { gererDemarrage(e) } finally { maj { it.copy(enCours = false) } }
        }
    }

    private fun gererDemarrage(e: Exception) = maj { it.copy(ecran = if (it.ecran == Ecran.DEMARRAGE) Ecran.ATTENTE_AUTORISATION else it.ecran, messageAttente = e.message ?: "", message = e.message) }

    private fun appliquerStatut(s: StatutAppareil, id: String) = maj {
        it.copy(statut = s, appareilId = id, messageAttente = s.message,
            ecran = if (s.autorise) (if (it.ecran == Ecran.DEMARRAGE || it.ecran == Ecran.ATTENTE_AUTORISATION) Ecran.CONNEXION else it.ecran) else Ecran.ATTENTE_AUTORISATION)
    }

    // ------------------------------------------------------------------------------------------------------------ connexion de l'utilisateur
    fun connecter(login: String, motDePasse: String) {
        if (login.isBlank() || motDePasse.isEmpty()) { dire("Saisissez l'identifiant et le mot de passe."); return }
        viewModelScope.launch {
            maj { it.copy(enCours = true, message = "Patientez… vérification de l'identifiant en cours") }
            try {
                val r = appel { base -> api.appeler(base, "/api/android/connexion", JSONObject().put("login", login.trim()).put("mot_de_passe", motDePasse), avecSession = false) }
                api.session = r.getString("session")
                val u = r.getJSONObject("utilisateur")
                maj { it.copy(ecran = Ecran.MENU, utilisateur = Utilisateur(u.optString("login"), u.optString("groupe"), u.optString("espace")), droits = lireDroits(r.getJSONObject("droits")),
                    message = "Connecté : ${u.optString("login")}", historique = null, corrections = null, detail = null, selection = null) }
            } catch (e: Exception) { gerer(e) } finally { maj { it.copy(enCours = false) } }
        }
    }

    fun deconnecter() { api.session = null; maj { it.copy(ecran = Ecran.CONNEXION, utilisateur = null, droits = null, historique = null, corrections = null, detail = null, selection = null, message = "Déconnecté.") } }

    // ------------------------------------------------------------------------------------------------------------ navigation
    fun aller(e: Ecran) = maj { it.copy(ecran = e) }
    fun retour() = maj {
        it.copy(ecran = when (it.ecran) { Ecran.DETAIL -> it.retourDetail; Ecran.HISTORIQUE, Ecran.CORRECTIONS, Ecran.PARAMETRES -> if (it.utilisateur != null) Ecran.MENU else Ecran.CONNEXION; else -> it.ecran })
    }
    fun changerJour(jour: String) = maj { it.copy(jour = jour) }
    fun changerCaissier(c: String) = maj { it.copy(caissierFiltre = c) }
    fun basculerTriColonne(c: ColonneTri) = maj { it.copy(tri = basculerTri(it.tri, c)) }
    fun filtrerACorriger(v: Boolean) = maj { it.copy(seulementACorriger = v) }

    // ------------------------------------------------------------------------------------------------------------ Historique de Caisse, détail, corrections
    private fun corpsJour(): JSONObject = JSONObject().put("date", _etat.value.jour).put("caissier", _etat.value.caissierFiltre.trim())

    fun chargerHistorique() {
        viewModelScope.launch {
            maj { it.copy(enCours = true, message = "Patientez… lecture de l'historique de caisse en cours") }
            try {
                val r = lireListeRecus(appel { base -> api.appeler(base, "/api/android/caisse/historique", corpsJour()) })
                maj { it.copy(historique = r, tri = Tri(), message = "${r.recus.size} reçu(s) — ${formaterMontant(r.total)}${if (r.tronque) " (liste limitée à 200 : filtrez par caissier)" else ""}") }
            } catch (e: Exception) { gerer(e) } finally { maj { it.copy(enCours = false) } }
        }
    }

    fun ouvrirRecu(reference: String, depuis: Ecran) {
        viewModelScope.launch {
            maj { it.copy(enCours = true, selection = reference, message = "Patientez… lecture du reçu $reference") }
            try {
                val d = lireDetail(appel { base -> api.appeler(base, "/api/android/caisse/recu", JSONObject().put("reference", reference)) })
                maj { it.copy(detail = d, ecran = Ecran.DETAIL, retourDetail = depuis, message = null) }
            } catch (e: Exception) { gerer(e) } finally { maj { it.copy(enCours = false) } }
        }
    }

    fun chargerCorrections() {
        viewModelScope.launch {
            maj { it.copy(enCours = true, message = "Patientez… recherche des reçus à corriger en cours") }
            try {
                val r = lireListeRecus(appel { base -> api.appeler(base, "/api/android/corrections/liste", corpsJour()) })
                maj { it.copy(corrections = r, message = "${r.nombreACorriger} reçu(s) à corriger sur ${r.recus.size}") }
            } catch (e: Exception) { gerer(e) } finally { maj { it.copy(enCours = false) } }
        }
    }

    // ------------------------------------------------------------------------------------------------------------ paramètres
    /** Enregistre les adresses et le mode ; refuse une adresse non sécurisée (http:// hors réseau local). */
    fun sauverParametres(urlSawali: String, urlLocale: String, mode: String) {
        if (urlSawali.isNotBlank() && !urlAutorisee(urlSawali)) { dire("Adresse SAWALI refusée : https:// obligatoire."); return }
        if (urlLocale.isNotBlank() && !urlAutorisee(urlLocale)) { dire("Adresse locale refusée : https://, ou http:// avec une adresse privée (192.168…, 10…, 172.16…)."); return }
        stockage.urlSawali = urlSawali.ifBlank { BuildConfig.URL_SAWALI_PAR_DEFAUT }
        stockage.urlLocale = urlLocale
        stockage.mode = mode
        maj { it.copy(urlSawali = stockage.urlSawali, urlLocale = stockage.urlLocale, mode = stockage.mode, message = "Paramètres enregistrés.") }
        verifierServeur()
    }
}
