package bf.sawali.loois

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels

/** Point d'entrée : une seule activité, l'interface (Jetpack Compose) change d'écran selon l'état du ViewModel. */
class MainActivity : ComponentActivity() {
    private val vm: AppViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { LooisTheme { Racine(vm) } }
    }
}
