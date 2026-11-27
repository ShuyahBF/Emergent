package bf.sawali.loois

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/** Erreur renvoyée par le serveur (code HTTP + message clair en français, champ « detail »). */
class ErreurApi(val code: Int, message: String) : Exception(message)

/** Le téléphone n'a pas pu joindre le serveur (pas de réseau, délai…). */
class ErreurReseau(message: String) : IOException(message)

/** Adresse du réseau local : 10.x.x.x, 172.16-31.x.x, 192.168.x.x (et localhost). */
fun estAdressePrivee(hote: String): Boolean {
    if (hote == "localhost") return true
    val p = hote.split(".").mapNotNull { it.toIntOrNull() }
    if (p.size != 4 || p.any { it !in 0..255 }) return false
    return p[0] == 10 || (p[0] == 172 && p[1] in 16..31) || (p[0] == 192 && p[1] == 168) || p[0] == 127
}

/** https:// partout ; http:// SEULEMENT pour une adresse du réseau local (jamais d'identifiants en clair sur Internet). */
fun urlAutorisee(url: String): Boolean {
    val u = url.trim().lowercase()
    if (u.startsWith("https://")) return u.length > 8
    if (!u.startsWith("http://")) return false
    val hote = u.removePrefix("http://").substringBefore("/").substringBefore(":")
    return estAdressePrivee(hote)
}

/** Client HTTP minimal (JSON). Toutes les fonctions sont des suspend : jamais d'appel réseau sur le fil de l'interface. */
class ClientApi(private val stockage: Stockage) {
    /** Session de l'utilisateur connecté (en mémoire seulement). */
    @Volatile var session: String? = null

    suspend fun appeler(base: String, chemin: String, corps: JSONObject? = null, methode: String = "POST", avecSession: Boolean = true,
                        delaiConnexionMs: Int = 15_000, delaiLectureMs: Int = 60_000): JSONObject = withContext(Dispatchers.IO) {
        if (!urlAutorisee(base)) throw ErreurReseau("Adresse refusée : utilisez https://, ou http:// seulement pour une adresse du réseau local.")
        val cx = try { URL(base.trimEnd('/') + chemin).openConnection() as HttpURLConnection } catch (e: Exception) { throw ErreurReseau("Adresse du serveur invalide.") }
        try {
            cx.requestMethod = methode
            cx.connectTimeout = delaiConnexionMs
            cx.readTimeout = delaiLectureMs
            cx.setRequestProperty("Accept", "application/json")
            cx.setRequestProperty("User-Agent", "LooisMobile/${BuildConfig.VERSION_NAME}")
            stockage.jeton?.let { cx.setRequestProperty("Authorization", "Bearer $it") }
            if (avecSession) session?.let { cx.setRequestProperty("X-Session", it) }
            if (corps != null) {
                cx.doOutput = true
                cx.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                cx.outputStream.use { it.write(corps.toString().toByteArray(Charsets.UTF_8)) }
            }
            val code = cx.responseCode
            val flux = if (code >= 400) cx.errorStream else cx.inputStream
            val texte = flux?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
            if (code >= 400) throw ErreurApi(code, extraireMessage(code, texte))
            if (texte.isBlank()) JSONObject() else JSONObject(texte)
        } catch (e: ErreurApi) { throw e
        } catch (e: org.json.JSONException) { throw ErreurReseau("Réponse du serveur illisible.")
        } catch (e: java.net.SocketTimeoutException) { throw ErreurReseau("Le serveur met trop de temps à répondre.")
        } catch (e: IOException) { throw ErreurReseau("Serveur injoignable : vérifiez la connexion.")
        } finally { cx.disconnect() }
    }

    /** Message lisible d'une réponse d'erreur : champ « detail » (texte), ou message générique. */
    fun extraireMessage(code: Int, texte: String): String = messageErreur(code, texte)
}

/** Message d'erreur du serveur (FastAPI : {"detail": "..."} ou liste de contrôles) — testable sans Android. */
fun messageErreur(code: Int, texte: String): String {
    val generique = when (code) {
        401 -> "Non reconnu : reconnectez-vous."
        403 -> "Accès refusé."
        404 -> "Introuvable."
        429 -> "Trop de demandes : patientez un instant."
        503 -> "Service indisponible."
        else -> "Erreur du serveur ($code)."
    }
    return try {
        when (val d = JSONObject(texte).opt("detail")) {
            is String -> d.ifBlank { generique }
            is JSONArray -> "Données invalides."
            else -> generique
        }
    } catch (e: Exception) { generique }
}

/** Vrai si le téléphone a une connexion Internet validée (Wi‑Fi ou données mobiles). */
fun internetDisponible(contexte: Context): Boolean {
    val cm = contexte.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    val c = cm.getNetworkCapabilities(cm.activeNetwork ?: return false) ?: return false
    return c.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) && c.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
}
