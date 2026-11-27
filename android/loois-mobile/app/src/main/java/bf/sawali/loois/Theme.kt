package bf.sawali.loois

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/** Couleurs de Loois mobile (mêmes repères que SAWALI : bleu nuit, bleu ciel, orange pour la sélection). */
object Couleurs {
    val BleuNuit = Color(0xFF0A1E3D)      // texte sur fond orange (contraste 7,7:1, règle 3)
    val Orange = Color(0xFFF6A35B)        // ligne sélectionnée (règle 3)
    val BleuCiel = Color(0xFF0369A1)      // références, actions
    val SurvolBleu = Color(0x2938BDF8)    // fond bleu clair transparent (rgba(56,189,248,0.16))
    val Vert = Color(0xFF047857)          // montants reçus
    val Rouge = Color(0xFFB91C1C)         // refus, retards
    val OrangeFonce = Color(0xFFB45309)   // « à corriger »
    val Gris = Color(0xFF475569)
    val Fond = Color(0xFFF8FAFC)
}

@Composable
fun LooisTheme(contenu: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = lightColorScheme(primary = Couleurs.BleuCiel, onPrimary = Color.White, secondary = Couleurs.OrangeFonce, background = Couleurs.Fond, surface = Color.White,
            onBackground = Color(0xFF0F172A), onSurface = Color(0xFF0F172A), error = Couleurs.Rouge),
        content = contenu,
    )
}
