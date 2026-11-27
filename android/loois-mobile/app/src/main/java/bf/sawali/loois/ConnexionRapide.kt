package bf.sawali.loois

import android.app.Activity
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyPermanentlyInvalidatedException
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.credentials.CreatePublicKeyCredentialRequest
import androidx.credentials.CreatePublicKeyCredentialResponse
import androidx.credentials.CredentialManager
import androidx.credentials.CustomCredential
import androidx.credentials.GetCredentialRequest
import androidx.credentials.GetPublicKeyCredentialOption
import androidx.credentials.PublicKeyCredential
import androidx.credentials.exceptions.CreateCredentialCancellationException
import androidx.credentials.exceptions.GetCredentialCancellationException
import androidx.credentials.exceptions.GetCredentialException
import androidx.credentials.exceptions.CreateCredentialException
import androidx.credentials.exceptions.NoCredentialException
import androidx.fragment.app.FragmentActivity
import com.google.android.libraries.identity.googleid.GetGoogleIdOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import java.security.KeyStore
import java.security.MessageDigest
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.suspendCancellableCoroutine

/** Erreur « normale » d'une connexion rapide (annulation, rien d'enregistré…) : son message est affiché tel quel à l'utilisateur. */
class ErreurRapide(message: String) : Exception(message)

/**
 * BIOMÉTRIE (empreinte / visage). Le secret remis par SAWALI à l'activation est chiffré par une clé du coffre Android (Keystore) qui ne sert QU'APRÈS une
 * authentification biométrique (usage unique par opération, clé invalidée si les empreintes du téléphone changent). Le mot de passe n'est jamais gardé.
 */
object Biometrie {
    fun disponible(activite: Activity): Boolean =
        BiometricManager.from(activite).canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_STRONG) == BiometricManager.BIOMETRIC_SUCCESS

    private fun alias(zone: String, login: String): String =
        "loois_bio_" + MessageDigest.getInstance("SHA-256").digest("$zone|${login.uppercase()}".toByteArray()).take(8).joinToString("") { "%02x".format(it) }

    private fun ks(): KeyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    /** Crée (ou recrée) la clé biométrique de cette zone et de cet identifiant. */
    private fun creerCle(alias: String): SecretKey {
        ks().deleteEntry(alias)
        val g = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        val b = KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setKeySize(256)
            .setUserAuthenticationRequired(true).setInvalidatedByBiometricEnrollment(true)
        if (Build.VERSION.SDK_INT >= 30) b.setUserAuthenticationParameters(0, KeyProperties.AUTH_BIOMETRIC_STRONG) else @Suppress("DEPRECATION") b.setUserAuthenticationValidityDurationSeconds(-1)
        g.init(b.build())
        return g.generateKey()
    }

    fun oublier(zone: String, login: String) { try { ks().deleteEntry(alias(zone, login)) } catch (_: Exception) { } }

    /** Demande l'empreinte / le visage et rend le chiffre prêt à servir (une seule opération). */
    private suspend fun authentifier(activite: FragmentActivity, titre: String, sousTitre: String, chiffre: Cipher): Cipher = suspendCancellableCoroutine { suite ->
        val rappel = object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(resultat: BiometricPrompt.AuthenticationResult) { resultat.cryptoObject?.cipher?.let { if (suite.isActive) suite.resume(it) } ?: suite.resumeWithException(ErreurRapide("Authentification biométrique incomplète.")) }
            override fun onAuthenticationError(code: Int, message: CharSequence) { if (suite.isActive) suite.resumeWithException(ErreurRapide(if (code == BiometricPrompt.ERROR_USER_CANCELED || code == BiometricPrompt.ERROR_NEGATIVE_BUTTON || code == BiometricPrompt.ERROR_CANCELED) "Connexion biométrique annulée." else message.toString())) }
        }
        val info = BiometricPrompt.PromptInfo.Builder().setTitle(titre).setSubtitle(sousTitre).setNegativeButtonText("Utiliser le mot de passe")
            .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG).build()
        BiometricPrompt(activite, ContextCompat.getMainExecutor(activite), rappel).authenticate(info, BiometricPrompt.CryptoObject(chiffre))
    }

    /** ACTIVATION : chiffre le secret après une authentification biométrique ; rend le texte à garder (IV + chiffre, base64). */
    suspend fun chiffrer(activite: FragmentActivity, zone: String, login: String, secret: String): String {
        val cle = creerCle(alias(zone, login))
        val c = authentifier(activite, "Activer la connexion biométrique", "Zone /$zone · $login", Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, cle) })
        return Base64.encodeToString(c.iv + c.doFinal(secret.toByteArray(Charsets.UTF_8)), Base64.NO_WRAP)
    }

    /** CONNEXION : demande l'empreinte / le visage puis rend le secret. */
    suspend fun dechiffrer(activite: FragmentActivity, zone: String, login: String, stocke: String): String {
        val brut = Base64.decode(stocke, Base64.NO_WRAP)
        val cle = try { ks().getKey(alias(zone, login), null) as? SecretKey } catch (_: Exception) { null } ?: throw ErreurRapide("Clé biométrique introuvable : connectez-vous par mot de passe puis réactivez-la.")
        val chiffre = try { Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.DECRYPT_MODE, cle, GCMParameterSpec(128, brut.copyOfRange(0, 12))) } }
        catch (e: KeyPermanentlyInvalidatedException) { oublier(zone, login); throw ErreurRapide("Les empreintes du téléphone ont changé : connectez-vous par mot de passe puis réactivez la connexion biométrique.") }
        val c = authentifier(activite, "Connexion à Loois Mobile", "Zone /$zone · $login", chiffre)
        return String(c.doFinal(brut.copyOfRange(12, brut.size)), Charsets.UTF_8)
    }
}

/** COMPTE GOOGLE et CLÉS D'ACCÈS par le Gestionnaire d'identifiants d'Android (Credential Manager). */
object Identites {
    /** Détail technique ajouté aux erreurs d'Android (ex. « [TYPE_SECURITY_ERROR] ») : permet de distinguer les causes à distance. */
    private fun detail(type: String): String = " [" + type.substringAfterLast('/').substringAfterLast('.') + "]"

    private fun texteErreur(e: Exception): String = when (e) {
        is GetCredentialCancellationException, is CreateCredentialCancellationException -> "Opération annulée."
        is NoCredentialException -> "Aucun compte ou aucune clé d'accès disponible sur ce téléphone."
        is GetCredentialException -> (e.message ?: "Échec de l'identification.") + detail(e.type)
        is CreateCredentialException -> (e.message ?: "Échec de la création.") + detail(e.type)
        else -> e.message ?: "Erreur inattendue."
    }

    /** Jeton d'identité Google (vérifié ensuite par SAWALI auprès de Google). `clientId` = identifiant du client Web Google de SAWALI. */
    suspend fun jetonGoogle(activite: Activity, clientId: String): String {
        try {
            val option = GetGoogleIdOption.Builder().setFilterByAuthorizedAccounts(false).setServerClientId(clientId).setAutoSelectEnabled(false).build()
            val rep = CredentialManager.create(activite).getCredential(activite, GetCredentialRequest.Builder().addCredentialOption(option).build())
            val c = rep.credential
            if (c is CustomCredential && c.type == GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL) return GoogleIdTokenCredential.createFrom(c.data).idToken
            throw ErreurRapide("Réponse Google inattendue.")
        } catch (e: ErreurRapide) { throw e } catch (e: Exception) { throw ErreurRapide(texteErreur(e)) }
    }

    /** Crée une clé d'accès à partir des options WebAuthn de SAWALI ; rend la réponse JSON à renvoyer à SAWALI. */
    suspend fun creerCle(activite: Activity, optionsJson: String): String {
        try {
            val rep = CredentialManager.create(activite).createCredential(activite, CreatePublicKeyCredentialRequest(optionsJson))
            return (rep as CreatePublicKeyCredentialResponse).registrationResponseJson
        } catch (e: ErreurRapide) { throw e } catch (e: Exception) { throw ErreurRapide(texteErreur(e)) }
    }

    /** Signe le défi de SAWALI avec la clé d'accès (empreinte / code du téléphone demandé par Android) ; rend la réponse JSON. */
    suspend fun signerCle(activite: Activity, optionsJson: String): String {
        try {
            val rep = CredentialManager.create(activite).getCredential(activite, GetCredentialRequest.Builder().addCredentialOption(GetPublicKeyCredentialOption(optionsJson)).build())
            return (rep.credential as? PublicKeyCredential)?.authenticationResponseJson ?: throw ErreurRapide("Réponse de la clé d'accès inattendue.")
        } catch (e: ErreurRapide) { throw e } catch (e: Exception) { throw ErreurRapide(texteErreur(e)) }
    }
}
