// Projet Android « Loois mobile » (SAWALI Smart Systems) — application Kotlin / Jetpack Compose.
pluginManagement {
    repositories { google(); mavenCentral(); gradlePluginPortal() }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories { google(); mavenCentral() }
}
rootProject.name = "loois-mobile"
include(":app")
