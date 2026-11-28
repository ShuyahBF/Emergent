package bf.sawali.loois

import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.fragment.app.FragmentActivity

/** Point d'entrée : une seule activité, l'interface (Jetpack Compose) change d'écran selon l'état du ViewModel.
 *  FragmentActivity (et non ComponentActivity) : requis par BiometricPrompt (connexion par empreinte / visage). */
class MainActivity : FragmentActivity() {
    private val vm: AppViewModel by viewModels()
    private val pvm: PointageVM by viewModels()      // lot M9 : pointage d'inventaire hors connexion

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { LooisTheme { Racine(vm, pvm) } }
    }
}
