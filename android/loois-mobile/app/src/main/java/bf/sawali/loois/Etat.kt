package bf.sawali.loois

import android.app.Application
import android.os.Build
import android.provider.Settings
import androidx.fragment.app.FragmentActivity
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
enum class Ecran { DEMARRAGE, ATTENTE_AUTORISATION, CONNEXION, MENU, HISTORIQUE, DETAIL, CORRECTIONS, TABLEAU, RAPIDE, PARAMETRES }

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
    val editRegle: Boolean? = null,                   // lot M6 : « Réglé » modifié à l'écran, non enregistré (null = inchangé)
    val editVise: Boolean? = null,                    // « Visé » modifié à l'écran, non enregistré
    val editPartAssure: String? = null,               // lot M7 : part assuré saisie (texte), non enregistrée ; la part assureur en est DÉDUITE (total − part)
    val editPartAssureur: String? = null,
    val confirmerModif: Boolean = false,              // fenêtre de confirmation avant d'écrire dans la base du client
    val recherche: String = "",                       // numéro de reçu tapé (lot M5)
    val resultatsRecherche: List<Recu>? = null,       // plusieurs reçus finissent par ces chiffres : on les propose
    val tableau: TableauJour? = null,                 // tableau de bord du jour
    val semaine: Semaine? = null,                     // 7 derniers jours (chargés à part : le jour s'affiche d'abord)
    val semaineEnCours: Boolean = false,
    val profil: ProfilZone = ProfilZone(),            // mémorisé pour la zone de l'appareil : identifiant, méthodes rapides, méthode préférée (jamais de mot de passe)
    val rapide: List<LiaisonRapide> = emptyList(),    // connexions rapides activées (liste de SAWALI)
    val configRapide: ConfigRapide? = null,
    val retourDetail: Ecran = Ecran.HISTORIQUE,
    val selection: String? = null,                // reçu sélectionné (orange, règle 3)
    val tri: Tri = Tri(),
    val urlSawali: String = "",
    val urlLocale: String = "",
    val mode: String = "auto",
    val serveursLocaux: List<String> = emptyList(),   // passerelles locales du client, reçues de SAWALI (rien à saisir)
    val ticketExpire: String = "",                    // « 30/11/2026 14:05 » : fin de l'accès sans Internet
)

/**
 * Logique de l'application : enregistrement de l'appareil, statut (Autorisé / Interdit), connexion de l'utilisateur, Historique de Caisse, Corrections de reçus.
 * Les appels réseau passent par `appel` : Internet (SQL distantes via SAWALI) si une connexion Internet est détectée, sinon l'adresse du serveur local définie dans les paramètres.
 */
class AppViewModel(app: Application) : AndroidViewModel(app) {
    private val stockage = Stockage(app)
    private val api = ClientApi(stockage)
    private val _etat = MutableStateFlow(UiEtat(urlSawali = stockage.urlSawali, urlLocale = stockage.urlLocale, mode = stockage.mode, appareilId = stockage.appareilId,
        serveursLocaux = stockage.serveursLocaux, ticketExpire = expirationTicket(stockage.ticketLocal)?.let { dateHeureDepuisSecondes(it) } ?: ""))
    val etat: StateFlow<UiEtat> = _etat.asStateFlow()

    companion object {
        /** Tests de l'interface : empêche tout appel réseau au démarrage (sinon chaque test s'enregistrerait auprès de SAWALI). Jamais modifié par l'application. */
        @JvmStatic internal var sansDemarrageReseau = false
    }

    init { if (!sansDemarrageReseau) demarrer() }

    private fun maj(f: (UiEtat) -> UiEtat) = _etat.update(f)

    /** Pour les tests de l'interface : impose un état (jamais utilisé par l'application). */
    internal fun forcerEtat(e: UiEtat) { _etat.value = e }
    fun messageAffiche() = maj { it.copy(message = null) }
    private fun dire(m: String) = maj { it.copy(message = m) }

    // ------------------------------------------------------------------------------------------------------------ réseau : Internet ou serveur local
    /** Adresses des passerelles locales à essayer : celle saisie à la main (Paramètres), puis celles reçues de SAWALI ; sans doublon. */
    private fun basesLocales(): List<String> = (listOf(stockage.urlLocale) + stockage.serveursLocaux).map { it.trim().trimEnd('/') }.filter { it.isNotEmpty() && urlAutorisee(it) }.distinct()

    /** Adresses à essayer, dans l'ordre, selon le mode choisi et la connexion détectée : Internet (SAWALI, SQL distantes) si Internet est détecté, sinon les passerelles locales. */
    private fun bases(): List<String> {
        val internet = stockage.urlSawali
        val locales = basesLocales()
        return when (stockage.mode) {
            "internet" -> listOf(internet)
            "local" -> if (locales.isEmpty()) throw ErreurReseau("Aucun serveur local connu (SAWALI les fournit quand l'appareil est autorisé ; ou saisissez-en un dans les Paramètres).") else locales
            else -> if (internetDisponible(getApplication())) listOf(internet) + locales else locales + internet
        }
    }

    private fun etiquetteMode(base: String): String =
        if (api.estServeurLocal(base)) "Réseau local · ${base.removePrefix("http://").removePrefix("https://")}" else "Internet · SQL distantes"

    private suspend fun <T> appel(bloc: suspend (String) -> T): T {
        var derniere: Exception? = null
        for (base in bases()) {
            try {
                val r = bloc(base)
                maj { it.copy(modeAffiche = etiquetteMode(base)) }
                return r
            } catch (e: ErreurReseau) { derniere = e }      // réseau en panne : on tente l'adresse suivante ; les erreurs du serveur (ErreurApi) remontent telles quelles
        }
        throw derniere ?: ErreurReseau("Serveur injoignable.")
    }

    /** Fonctions réservées à SAWALI (enregistrement, statut) : jamais envoyées à une passerelle locale. */
    private suspend fun <T> appelSawali(bloc: suspend (String) -> T): T {
        val r = bloc(stockage.urlSawali)
        maj { it.copy(modeAffiche = etiquetteMode(stockage.urlSawali)) }
        return r
    }

    /** Traduit une erreur en message pour l'utilisateur ; une session expirée ramène à la connexion, un appareil interdit à l'écran d'attente. */
    private fun gerer(e: Exception) {
        when {
            e is ErreurApi && e.code == 401 && (e.message ?: "").contains("Ticket local", true) -> { api.session = null; maj { it.copy(ecran = Ecran.ATTENTE_AUTORISATION, utilisateur = null, droits = null, messageAttente = e.message ?: "", message = e.message) } }   // ticket de 72 h expiré : Internet requis une fois
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
                // SAWALI : /api/version ; passerelle locale : /api/android/ping
                appel { base -> api.appeler(base, if (api.estServeurLocal(base)) "/api/android/ping" else "/api/version", methode = "GET", avecSession = false, delaiConnexionMs = 6_000, delaiLectureMs = 8_000) }
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
                val r = appelSawali { base -> api.appeler(base, "/api/android/appareil/enregistrer", corps, avecSession = false) }
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
                val r = appelSawali { base -> api.appeler(base, "/api/android/appareil/statut", JSONObject().put("version_app", BuildConfig.VERSION_NAME), avecSession = false) }
                appliquerStatut(lireStatut(r), stockage.appareilId)
            } catch (e: ErreurApi) {
                if (e.code == 401) { stockage.oublierAppareil(); enregistrer() } else maj { it.copy(ecran = Ecran.ATTENTE_AUTORISATION, messageAttente = e.message ?: "", message = e.message) }
            } catch (e: ErreurReseau) {
                // Pas de SAWALI joignable : si l'appareil a déjà été autorisé et connaît une passerelle locale (ticket de 72 h), on continue SANS Internet
                if (!demarrerHorsInternet()) gererDemarrage(e)
            } catch (e: Exception) { gererDemarrage(e) } finally { maj { it.copy(enCours = false) } }
        }
    }

    /** Démarre avec le dernier statut connu quand SAWALI est injoignable. Rend faux si ce n'est pas possible (jamais autorisé, ticket absent ou expiré, aucune passerelle connue). */
    private fun demarrerHorsInternet(): Boolean {
        val s = statutDepuisJson(stockage.dernierStatut)
        val exp = expirationTicket(stockage.ticketLocal)
        if (s == null || !s.autorise || exp == null || exp * 1000 <= System.currentTimeMillis() || basesLocales().isEmpty()) return false
        maj { it.copy(statut = s, profil = stockage.profil(s.zone), ecran = if (it.ecran == Ecran.DEMARRAGE || it.ecran == Ecran.ATTENTE_AUTORISATION) Ecran.CONNEXION else it.ecran, messageAttente = "",
            message = "Sans Internet : accès par le réseau local (ticket valable jusqu'au ${dateHeureDepuisSecondes(exp)}).") }
        verifierServeur()
        return true
    }

    private fun gererDemarrage(e: Exception) = maj { it.copy(ecran = if (it.ecran == Ecran.DEMARRAGE) Ecran.ATTENTE_AUTORISATION else it.ecran, messageAttente = e.message ?: "", message = e.message) }

    private fun appliquerStatut(s: StatutAppareil, id: String) {
        // Mémorise de quoi travailler sans Internet : adresses des passerelles locales, ticket local (chiffré) et dernier statut (zone, base) ; un appareil interdit n'en garde rien
        stockage.serveursLocaux = if (s.autorise) s.serveursLocaux else emptyList()
        stockage.ticketLocal = if (s.autorise) s.ticketLocal else null
        stockage.dernierStatut = statutVersJson(s)
        // Mémorisation PAR ZONE : dès que la zone est connue, on retrouve son identifiant, ses méthodes rapides et ses réglages réseau
        if (s.autorise && s.zone.isNotBlank()) {
            val p = stockage.profil(s.zone)
            if (p.mode.isNotBlank()) stockage.mode = p.mode
            if (p.urlLocale.isNotBlank()) stockage.urlLocale = p.urlLocale
            maj { it.copy(profil = p, mode = stockage.mode, urlLocale = stockage.urlLocale) }
        }
        maj { it.copy(serveursLocaux = stockage.serveursLocaux, ticketExpire = expirationTicket(stockage.ticketLocal)?.let { x -> dateHeureDepuisSecondes(x) } ?: "") }
        mettreAJourStatut(s, id)
    }

    private fun mettreAJourStatut(s: StatutAppareil, id: String) = maj {
        it.copy(statut = s, appareilId = id, messageAttente = s.message,
            ecran = if (s.autorise) (if (it.ecran == Ecran.DEMARRAGE || it.ecran == Ecran.ATTENTE_AUTORISATION) Ecran.CONNEXION else it.ecran) else Ecran.ATTENTE_AUTORISATION)
    }

    // ------------------------------------------------------------------------------------------------------------ connexion de l'utilisateur
    fun connecter(login: String, motDePasse: String, memoriser: Boolean = true) {
        if (login.isBlank() || motDePasse.isEmpty()) { dire("Saisissez l'identifiant et le mot de passe."); return }
        viewModelScope.launch {
            maj { it.copy(enCours = true, message = "Patientez… vérification de l'identifiant en cours") }
            try {
                val r = appel { base -> api.appeler(base, "/api/android/connexion", JSONObject().put("login", login.trim()).put("mot_de_passe", motDePasse), avecSession = false) }
                ouvrirSession(r, "Connecté : ${r.getJSONObject("utilisateur").optString("login")}")
                // Mémorisation PAR ZONE : seul l'identifiant est gardé (jamais le mot de passe) ; case décochée = on l'oublie
                val zone = zone()
                if (zone.isNotBlank()) { stockage.modifierProfil(zone) { it.copy(login = if (memoriser) login.trim() else "") }; maj { it.copy(profil = stockage.profil(zone)) } }
            } catch (e: Exception) { gerer(e) } finally { maj { it.copy(enCours = false) } }
        }
    }

    /** Ouvre la session à partir de la réponse du serveur (mot de passe ou connexion rapide : même réponse). */
    private fun ouvrirSession(r: JSONObject, message: String) {
        api.session = r.getString("session")
        val u = r.getJSONObject("utilisateur")
        maj { it.copy(ecran = Ecran.MENU, utilisateur = Utilisateur(u.optString("login"), u.optString("groupe"), u.optString("espace")), droits = lireDroits(r.getJSONObject("droits")),
            message = message, historique = null, corrections = null, detail = null, selection = null, tableau = null, semaine = null, rapide = emptyList()) }
    }

    private fun zone(): String = _etat.value.statut?.zone ?: ""

    // ------------------------------------------------------------------------------------------------------------ connexion rapide (biométrie, Google, clé d'accès)
    private suspend fun configRapide(): ConfigRapide {
        _etat.value.configRapide?.let { return it }
        val c = lireConfigRapide(appelSawali { base -> api.appeler(base, "/api/android/rapide/config", null, "GET", avecSession = false) })
        maj { it.copy(configRapide = c) }
        return c
    }

    /** Exécute une opération de connexion rapide : toast « Patientez… », annulation = simple message, erreur serveur traduite. */
    private fun rapideOperation(attente: String, bloc: suspend () -> Unit) {
        viewModelScope.launch {
            maj { it.copy(enCours = true, message = "Patientez… $attente") }
            try { bloc() } catch (e: ErreurRapide) { dire(e.message ?: "Opération annulée.") } catch (e: Exception) { gerer(e) } finally { maj { it.copy(enCours = false) } }
        }
    }

    /** CONNEXION RAPIDE depuis l'écran de connexion (Internet requis : SAWALI vérifie la preuve). */
    fun connecterRapide(methode: String, activite: FragmentActivity) {
        val zone = zone(); val p = stockage.profil(zone)
        rapideOperation("connexion rapide en cours") {
            val corps = JSONObject().put("methode", methode).put("login", p.login)
            when (methode) {
                "biometrie" -> corps.put("secret", Biometrie.dechiffrer(activite, zone, p.login, stockage.secretBiometrique(zone, p.login) ?: throw ErreurRapide("Connexion biométrique non activée sur ce téléphone.")))
                "google" -> corps.put("id_token", Identites.jetonGoogle(activite, configRapide().googleClientId.ifBlank { throw ErreurRapide("La connexion par Google n'est pas configurée sur SAWALI.") }))
                "cle" -> {
                    val o = appelSawali { b -> api.appeler(b, "/api/android/rapide/cle/options-connexion", JSONObject().put("login", p.login), avecSession = false) }
                    val rep = Identites.signerCle(activite, o.getJSONObject("options").toString())
                    corps.put("challenge_id", o.getString("challenge_id")).put("credential", JSONObject(rep))
                }
                else -> throw ErreurRapide("Méthode inconnue.")
            }
            val r = appelSawali { b -> api.appeler(b, "/api/android/rapide/connexion", corps, avecSession = false) }
            ouvrirSession(r, "Connecté (${libelleMethode(methode)}) : ${r.getJSONObject("utilisateur").optString("login")}")
            stockage.modifierProfil(zone) { it.copy(preferee = methode) }
            maj { it.copy(profil = stockage.profil(zone)) }
        }
    }

    /** Liste des connexions rapides activées + ce que SAWALI propose (Google configuré ?). */
    fun chargerRapide() = rapideOperation("lecture des connexions rapides") {
        val liste = lireLiaisons(appelSawali { b -> api.appeler(b, "/api/android/rapide/liste", null, "GET") })
        configRapide()
        maj { it.copy(rapide = liste, message = null) }
    }

    private fun apresActivation(zone: String, methode: String, message: String) {
        stockage.modifierProfil(zone) { it.copy(login = _etat.value.utilisateur?.login ?: it.login, methodes = it.methodes + methode, preferee = it.preferee.ifBlank { methode }) }
        maj { it.copy(profil = stockage.profil(zone), message = message) }
    }

    fun activerBiometrie(activite: FragmentActivity) {
        if (!Biometrie.disponible(activite)) { dire("Aucune empreinte ni aucun visage n'est enregistré sur ce téléphone (Réglages Android → Sécurité)."); return }
        val zone = zone(); val login = _etat.value.utilisateur?.login ?: return
        rapideOperation("activation de la connexion biométrique") {
            val r = appelSawali { b -> api.appeler(b, "/api/android/rapide/biometrie/activer", JSONObject()) }
            try { stockage.ecrireSecretBiometrique(zone, login, Biometrie.chiffrer(activite, zone, login, r.getString("secret"))) }
            catch (e: Exception) { try { appelSawali { b -> api.appeler(b, "/api/android/rapide/${r.getString("id")}", null, "DELETE") } } catch (_: Exception) { }; throw e }     // annulé : rien ne reste chez SAWALI
            apresActivation(zone, "biometrie", "Connexion biométrique activée.")
            chargerRapide()
        }
    }

    fun activerGoogle(activite: FragmentActivity) {
        val zone = zone()
        rapideOperation("liaison du compte Google") {
            val cfg = configRapide()
            if (!cfg.google || cfg.googleClientId.isBlank()) throw ErreurRapide("La connexion par Google n'est pas encore configurée sur SAWALI (l'administrateur doit saisir le client Google).")
            val jeton = Identites.jetonGoogle(activite, cfg.googleClientId)
            val r = appelSawali { b -> api.appeler(b, "/api/android/rapide/google/activer", JSONObject().put("id_token", jeton)) }
            apresActivation(zone, "google", "Compte Google lié : ${r.optString("detail")}")
            chargerRapide()
        }
    }

    fun activerCle(activite: FragmentActivity) {
        val zone = zone()
        rapideOperation("création de la clé d'accès") {
            val o = appelSawali { b -> api.appeler(b, "/api/android/rapide/cle/options", JSONObject()) }
            val rep = Identites.creerCle(activite, o.getJSONObject("options").toString())
            appelSawali { b -> api.appeler(b, "/api/android/rapide/cle/activer", JSONObject().put("challenge_id", o.getString("challenge_id")).put("credential", JSONObject(rep)).put("nom", android.os.Build.MODEL ?: "")) }
            apresActivation(zone, "cle", "Clé d'accès enregistrée.")
            chargerRapide()
        }
    }

    /** Retire une connexion rapide (chez SAWALI et sur ce téléphone). */
    fun retirerRapide(l: LiaisonRapide) {
        val zone = zone(); val login = _etat.value.utilisateur?.login ?: ""
        rapideOperation("retrait de la connexion rapide") {
            appelSawali { b -> api.appeler(b, "/api/android/rapide/${l.id}", null, "DELETE") }
            if (l.methode == "biometrie") { Biometrie.oublier(zone, login); stockage.ecrireSecretBiometrique(zone, login, null) }
            stockage.modifierProfil(zone) { it.copy(methodes = it.methodes - l.methode, preferee = if (it.preferee == l.methode) "" else it.preferee) }
            maj { it.copy(profil = stockage.profil(zone), message = "Connexion rapide retirée.") }
            chargerRapide()
        }
    }

    /** Oublie tout ce que le téléphone a mémorisé pour la zone (identifiant, méthodes, réglages réseau) ; les liaisons chez SAWALI se retirent dans « Connexion Rapide ». */
    fun oublierProfil() {
        val zone = zone(); if (zone.isBlank()) return
        val p = stockage.profil(zone)
        if (p.login.isNotBlank()) { Biometrie.oublier(zone, p.login); stockage.ecrireSecretBiometrique(zone, p.login, null) }
        stockage.enregistrerProfil(zone, ProfilZone())
        maj { it.copy(profil = ProfilZone(), message = "Mémorisation de la zone /$zone effacée.") }
    }

    fun deconnecter() { api.session = null; maj { it.copy(ecran = Ecran.CONNEXION, utilisateur = null, droits = null, historique = null, corrections = null, detail = null, tableau = null, semaine = null, selection = null, message = "Déconnecté.") } }

    // ------------------------------------------------------------------------------------------------------------ navigation
    fun aller(e: Ecran) = maj { it.copy(ecran = e) }
    fun retour() = maj {
        it.copy(ecran = when (it.ecran) { Ecran.DETAIL -> it.retourDetail; Ecran.HISTORIQUE, Ecran.CORRECTIONS, Ecran.TABLEAU, Ecran.RAPIDE, Ecran.PARAMETRES -> if (it.utilisateur != null) Ecran.MENU else Ecran.CONNEXION; else -> it.ecran })
    }
    fun changerJour(jour: String) = maj { it.copy(jour = jour) }
    fun changerCaissier(c: String) = maj { it.copy(caissierFiltre = c) }
    // ------------------------------------------------------------------------------------------------------------ lot M6 : le superviseur modifie « Réglé » et « Visé »
    /** Un toucher sur « Réglé » / « Visé » change la valeur À L'ÉCRAN ; rien n'est écrit tant que le superviseur n'a pas confirmé. Revenir à la valeur d'origine annule le changement. */
    fun basculerRegle() = maj { e -> val d = e.detail ?: return@maj e; val actuel = e.editRegle ?: d.infos.regle ?: false; val nouveau = !actuel
        e.copy(editRegle = if (nouveau == d.infos.regle) null else nouveau) }
    fun basculerVise() = maj { e -> val d = e.detail ?: return@maj e; val actuel = e.editVise ?: d.infos.vise ?: false; val nouveau = !actuel
        e.copy(editVise = if (nouveau == d.infos.vise) null else nouveau) }
    fun annulerModifs() = maj { it.copy(editRegle = null, editVise = null, editPartAssure = null, editPartAssureur = null, confirmerModif = false) }
    /** Lot M7 — la personne tape UNE part ; l'autre est calculée tout de suite (total − part). Revenir aux parts d'origine annule le changement. */
    fun changerPartAssure(t: String) = maj { e -> partsModifiees(e, t, true) }
    fun changerPartAssureur(t: String) = maj { e -> partsModifiees(e, t, false) }
    private fun partsModifiees(e: UiEtat, texte: String, assure: Boolean): UiEtat {
        val d = e.detail ?: return e
        val total = d.infos.montantTotal ?: return e.copy(message = "Montant total inconnu : impossible de répartir les parts.")
        val v = lireNombreSaisi(texte)
        val autre = if (v != null && v in 0.0..total) formaterNombreSaisi(total - v) else ""
        val (pa, pr) = if (assure) texte to autre else autre to texte
        val origine = Math.abs((lireNombreSaisi(pa) ?: -1.0) - d.recu.partAssure) < 0.005 && Math.abs((lireNombreSaisi(pr) ?: -1.0) - d.recu.partAssureur) < 0.005
        return if (origine) e.copy(editPartAssure = null, editPartAssureur = null) else e.copy(editPartAssure = pa, editPartAssureur = pr)
    }
    fun demanderConfirmationModif() = maj {
        val parts = it.editPartAssure != null
        val valides = !parts || (lireNombreSaisi(it.editPartAssure) != null && lireNombreSaisi(it.editPartAssureur) != null)
        if (!valides) it.copy(message = "Part invalide : tapez un nombre compris entre 0 et le montant total.")
        else if (it.editRegle != null || it.editVise != null || parts) it.copy(confirmerModif = true) else it
    }
    fun fermerConfirmationModif() = maj { it.copy(confirmerModif = false) }

    /** Écrit les changements dans la base HFSQL du client (via SAWALI), puis relit : on n'affiche « enregistré » que si le serveur l'a confirmé. */
    fun enregistrerModifs() {
        val d = _etat.value.detail ?: return
        val regle = _etat.value.editRegle; val vise = _etat.value.editVise
        val partA = _etat.value.editPartAssure?.let { lireNombreSaisi(it) }; val partR = _etat.value.editPartAssureur?.let { lireNombreSaisi(it) }
        if (_etat.value.enCours || (regle == null && vise == null && partA == null)) return
        viewModelScope.launch {
            maj { it.copy(confirmerModif = false, enCours = true, message = "Patientez… enregistrement dans la base du client en cours") }
            try {
                val corps = JSONObject().put("reference", d.recu.reference)
                if (regle != null) corps.put("regle", regle)
                if (vise != null) corps.put("vise", vise)
                if (partA != null && partR != null) { corps.put("part_assure", partA); corps.put("part_assureur", partR) }      // les deux parts : le serveur vérifie qu'elles font le total
                val r = appel { base -> api.appeler(base, "/api/android/caisse/recu/modifier", corps) }
                val infos = lireInfos(r.optJSONObject("infos"))
                val recuRelu = r.optJSONObject("recu")?.let { lireRecu(it) }
                maj { it.copy(detail = it.detail?.copy(infos = infos, recu = recuRelu ?: it.detail.recu), editRegle = null, editVise = null, editPartAssure = null, editPartAssureur = null, message = "✔ Enregistré dans la base du client : réglé ${if (infos.regle == true) "oui" else "non"}, visé ${if (infos.vise == true) "oui" else "non"}${if (partA != null) " ; parts ${formaterMontant(recuRelu?.partAssure ?: 0.0)} / ${formaterMontant(recuRelu?.partAssureur ?: 0.0)}" else ""}.") }
            } catch (e: Exception) { gerer(e) } finally { maj { it.copy(enCours = false) } }
        }
    }

    fun changerRecherche(t: String) = maj { it.copy(recherche = t, resultatsRecherche = null) }

    /** Lot M5 — retrouve un reçu par son numéro (complet ou fin du numéro). Un seul reçu : il s'ouvre ; plusieurs : liste à choisir ; aucun : message clair. */
    fun rechercherRecu() {
        val saisie = _etat.value.recherche.trim()
        if (_etat.value.enCours) return                                     // jamais deux lectures en même temps
        if (saisie.length < 3) { maj { it.copy(message = "Tapez le numéro du reçu (au moins 3 chiffres, ex. R-202630889) ou d'une facture d'hospitalisation (ex. 0461/2026).") }; return }
        viewModelScope.launch {
            maj { it.copy(enCours = true, message = "Patientez… recherche du reçu $saisie en cours") }
            try {
                val r = lireRecherche(appel { base -> api.appeler(base, "/api/android/caisse/recu/recherche", JSONObject().put("numero", saisie)) })
                when (r.recus.size) {
                    0 -> maj { it.copy(resultatsRecherche = emptyList(), message = "Aucun reçu ne porte le numéro ${r.numero}${if (_etat.value.droits?.voirTousLesRecus == true) "" else " parmi les vôtres"}.") }
                    1 -> { maj { it.copy(resultatsRecherche = null, message = null) }; ouvrirRecu(r.recus[0].reference, Ecran.HISTORIQUE) }
                    else -> maj { it.copy(resultatsRecherche = r.recus, message = "${r.recus.size} reçus correspondent : choisissez-en un.") }
                }
            } catch (e: Exception) { gerer(e) } finally { maj { it.copy(enCours = false) } }
        }
    }
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
                maj { it.copy(detail = d, ecran = Ecran.DETAIL, retourDetail = depuis, message = null, editRegle = null, editVise = null, confirmerModif = false) }
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

    /** Tableau de bord : le JOUR s'affiche d'abord (une requête), puis les 7 derniers jours se chargent à part (7 comptages) sans bloquer l'écran. */
    fun chargerTableau() {
        viewModelScope.launch {
            maj { it.copy(enCours = true, message = "Patientez… lecture du tableau de bord en cours") }
            try {
                val t = lireTableau(appel { base -> api.appeler(base, "/api/android/tableau-de-bord", corpsJour()) })
                maj { it.copy(tableau = t, enCours = false, message = "${t.nombre} reçu(s) — ${formaterMontant(t.total)}") }
            } catch (e: Exception) { maj { it.copy(enCours = false) }; gerer(e); return@launch }
            maj { it.copy(semaineEnCours = true) }
            try {
                val w = lireSemaine(appel { base -> api.appeler(base, "/api/android/tableau-de-bord/semaine", JSONObject().put("date", _etat.value.jour)) })
                maj { it.copy(semaine = w) }
            } catch (e: Exception) { gerer(e) } finally { maj { it.copy(semaineEnCours = false) } }
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
        zone().takeIf { it.isNotBlank() }?.let { z -> stockage.modifierProfil(z) { it.copy(mode = mode, urlLocale = urlLocale) } }      // mémorisés pour la zone
        maj { it.copy(urlSawali = stockage.urlSawali, urlLocale = stockage.urlLocale, mode = stockage.mode, profil = stockage.profil(zone()), message = "Paramètres enregistrés.") }
        verifierServeur()
    }
}
