// Module « app » de Loois mobile.
// SIGNATURE : la clé PERMANENTE de ShuyahStore est lue dans les variables d'environnement (jamais dans le dépôt) :
//   ANDROID_KEYSTORE_FILE, ANDROID_KEYSTORE_PASSWORD, ANDROID_KEY_ALIAS, ANDROID_KEY_PASSWORD.
// Sans ces variables, la version « release » n'est PAS signée (APK à ne jamais livrer).
import java.text.SimpleDateFormat
import java.util.Date
import java.util.TimeZone

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

// Version et numéro de lot affichés dans l'application (règle 1 : mis à jour à CHAQUE publication)
val versionApp = "1.0"
val codeVersion = 1
val lotApp = "477"
// Date et heure de compilation (heure du Burkina Faso = UTC), affichées « déployée le JJ/MM/AAAA HH:MM » (règle 2)
val dateCompilation: String = SimpleDateFormat("dd/MM/yyyy HH:mm").apply { timeZone = TimeZone.getTimeZone("UTC") }.format(Date())

android {
    namespace = "bf.sawali.loois"
    compileSdk = 34

    defaultConfig {
        applicationId = "bf.sawali.loois.mobile"
        minSdk = 26
        targetSdk = 34
        versionCode = codeVersion
        versionName = versionApp
        buildConfigField("String", "DATE_COMPILATION", "\"$dateCompilation\"")
        buildConfigField("String", "LOT", "\"$lotApp\"")
        buildConfigField("String", "URL_SAWALI_PAR_DEFAUT", "\"https://api.sawalismartsystems.com\"")
    }

    val fichierCle = System.getenv("ANDROID_KEYSTORE_FILE")
    signingConfigs {
        if (!fichierCle.isNullOrBlank() && file(fichierCle).exists()) {
            create("shuyahstore") {
                storeFile = file(fichierCle)
                storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("ANDROID_KEY_ALIAS")
                keyPassword = System.getenv("ANDROID_KEY_PASSWORD")
                if (fichierCle.endsWith(".p12", ignoreCase = true) || fichierCle.endsWith(".pfx", ignoreCase = true)) storeType = "PKCS12"
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfigs.findByName("shuyahstore")?.let { signingConfig = it }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    packaging { resources.excludes += "/META-INF/{AL2.0,LGPL2.1}" }
    // Tests de l'interface sur le PC (Robolectric) : les ressources de l'application sont disponibles pour les tests unitaires
    testOptions { unitTests.isIncludeAndroidResources = true }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-compose:1.9.2")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.6")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.6")
    implementation(platform("androidx.compose:compose-bom:2024.09.03"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.8.1")
    testImplementation("org.robolectric:robolectric:4.13")
    testImplementation("androidx.test:core-ktx:1.6.1")
    testImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}
