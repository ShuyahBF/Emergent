package bf.sawali.loois

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Stockage local de Loois mobile.
 * - Réglages simples (adresses, mode) : préférences de l'application.
 * - SECRETS (jeton de l'appareil) : chiffrés par une clé AES-256 gardée dans le coffre Android (Keystore) ; la clé ne quitte jamais le téléphone.
 * Le mot de passe de l'utilisateur n'est JAMAIS stocké (ni session, ni mémorisation).
 */
class Stockage(contexte: Context) {
    private val prefs = contexte.getSharedPreferences("loois_mobile", Context.MODE_PRIVATE)

    /** Adresse de SAWALI (SQL distantes par Internet). */
    var urlSawali: String
        get() = prefs.getString("url_sawali", null) ?: BuildConfig.URL_SAWALI_PAR_DEFAUT
        set(v) = prefs.edit().putString("url_sawali", v.trim().trimEnd('/')).apply()

    /** Adresse du serveur local (réseau de l'entreprise), vide = non définie. */
    var urlLocale: String
        get() = prefs.getString("url_locale", "") ?: ""
        set(v) = prefs.edit().putString("url_locale", v.trim().trimEnd('/')).apply()

    /** Mode de connexion : "auto" (Internet si détecté, sinon serveur local), "internet" ou "local". */
    var mode: String
        get() = prefs.getString("mode", "auto") ?: "auto"
        set(v) = prefs.edit().putString("mode", v).apply()

    var appareilId: String
        get() = prefs.getString("appareil_id", "") ?: ""
        set(v) = prefs.edit().putString("appareil_id", v).apply()

    /** Jeton secret de l'appareil (rendu une seule fois par SAWALI à l'enregistrement). */
    var jeton: String?
        get() = lireSecret("jeton")
        set(v) { if (v == null) prefs.edit().remove("jeton").apply() else ecrireSecret("jeton", v) }

    fun oublierAppareil() { prefs.edit().remove("jeton").remove("appareil_id").apply() }

    // ---------------------------------------------------------------- secrets chiffrés (AES-GCM, clé dans le Keystore Android)
    private fun cle(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val g = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        g.init(KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setKeySize(256).build())
        return g.generateKey()
    }

    private fun ecrireSecret(nom: String, valeur: String) {
        val c = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, cle()) }
        val brut = c.iv + c.doFinal(valeur.toByteArray(Charsets.UTF_8))
        prefs.edit().putString("secret_$nom", Base64.encodeToString(brut, Base64.NO_WRAP)).apply()
    }

    private fun lireSecret(nom: String): String? = try {
        val brut = Base64.decode(prefs.getString("secret_$nom", null) ?: return null, Base64.NO_WRAP)
        val c = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.DECRYPT_MODE, cle(), GCMParameterSpec(128, brut.copyOfRange(0, 12))) }
        String(c.doFinal(brut.copyOfRange(12, brut.size)), Charsets.UTF_8)
    } catch (e: Exception) { null }   // clé perdue (réinitialisation du téléphone…) : l'appareil devra se ré-enregistrer

    private companion object { const val ALIAS = "loois_mobile_cle" }
}
