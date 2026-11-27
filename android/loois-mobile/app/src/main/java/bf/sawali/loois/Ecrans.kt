@file:OptIn(ExperimentalMaterial3Api::class)

package bf.sawali.loois

import android.content.Context
import android.content.ContextWrapper
import androidx.activity.compose.BackHandler
import androidx.compose.ui.platform.LocalContext
import androidx.fragment.app.FragmentActivity
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Login
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset

/** Libellé de version affiché sur la connexion et sur les pages connectées (règle 2) : « Version X · déployée le JJ/MM/AAAA HH:MM ». */
fun libelleVersion() = "Version ${BuildConfig.VERSION_NAME} · déployée le ${BuildConfig.DATE_COMPILATION}"

// ================================================================================================================ racine : navigation entre les écrans
@Composable
fun Racine(vm: AppViewModel) {
    val e by vm.etat.collectAsStateWithLifecycle()
    val snack = remember { SnackbarHostState() }
    LaunchedEffect(e.message) { e.message?.let { snack.showSnackbar(it); vm.messageAffiche() } }
    BackHandler(enabled = e.ecran in setOf(Ecran.HISTORIQUE, Ecran.DETAIL, Ecran.CORRECTIONS, Ecran.TABLEAU, Ecran.RAPIDE, Ecran.PARAMETRES)) { vm.retour() }
    Scaffold(snackbarHost = { SnackbarHost(snack) }, containerColor = Couleurs.Fond) { marge ->
        Box(Modifier.padding(marge).fillMaxSize()) {
            when (e.ecran) {
                Ecran.DEMARRAGE -> EcranDemarrage()
                Ecran.ATTENTE_AUTORISATION -> EcranAttente(e, vm)
                Ecran.CONNEXION -> EcranConnexion(e, vm)
                Ecran.MENU -> EcranMenu(e, vm)
                Ecran.HISTORIQUE -> EcranListe(e, vm, corrections = false)
                Ecran.CORRECTIONS -> EcranListe(e, vm, corrections = true)
                Ecran.TABLEAU -> EcranTableau(e, vm)
                Ecran.RAPIDE -> EcranRapide(e, vm)
                Ecran.DETAIL -> EcranDetail(e, vm)
                Ecran.PARAMETRES -> EcranParametres(e, vm)
            }
            if (e.enCours) LinearProgressIndicator(Modifier.fillMaxWidth().align(Alignment.TopCenter), color = Couleurs.Orange)   // attente visible (règle « Patientez… »)
        }
    }
}

// ================================================================================================================ composants communs
@Composable
fun BarreHaut(titre: String, retour: (() -> Unit)?, actions: @Composable RowScope.() -> Unit = {}) {
    Row(Modifier.fillMaxWidth().background(Couleurs.BleuNuit).padding(horizontal = 4.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        if (retour != null) IconButton(onClick = retour) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Retour", tint = Color.White) } else Spacer(Modifier.width(12.dp))
        Text(titre, color = Color.White, fontWeight = FontWeight.Bold, fontSize = 18.sp, modifier = Modifier.weight(1f))
        actions()
    }
}

/** Bouton avec pictogramme ET légende (règle 15). */
@Composable
fun BoutonAction(texte: String, icone: ImageVector, actif: Boolean = true, plein: Boolean = true, onClick: () -> Unit) {
    if (plein) Button(onClick = onClick, enabled = actif) { Icon(icone, null, Modifier.size(18.dp)); Spacer(Modifier.width(6.dp)); Text(texte) }
    else OutlinedButton(onClick = onClick, enabled = actif) { Icon(icone, null, Modifier.size(18.dp)); Spacer(Modifier.width(6.dp)); Text(texte) }
}

/** Champ de mot de passe avec pictogramme « œil » (règle 22) : masqué par défaut. */
@Composable
fun ChampMotDePasse(valeur: String, onChange: (String) -> Unit, etiquette: String, modifier: Modifier = Modifier) {
    var visible by remember { mutableStateOf(false) }
    OutlinedTextField(valeur, onChange, modifier = modifier, label = { Text(etiquette) }, singleLine = true,
        leadingIcon = { Icon(Icons.Filled.Lock, null) },
        visualTransformation = if (visible) VisualTransformation.None else PasswordVisualTransformation(),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
        trailingIcon = { IconButton(onClick = { visible = !visible }, modifier = Modifier.size(48.dp)) { Icon(if (visible) Icons.Filled.VisibilityOff else Icons.Filled.Visibility, if (visible) "Masquer la saisie" else "Afficher la saisie") } })
}

@Composable
fun PastilleServeur(serveur: String, mode: String) {
    val (texte, couleur, icone) = when (serveur) {
        "actif" -> Triple("Serveur actif", Couleurs.Vert, Icons.Filled.CheckCircle)
        "lent" -> Triple("Serveur lent", Couleurs.OrangeFonce, Icons.Filled.Warning)
        "injoignable" -> Triple("Serveur injoignable", Couleurs.Rouge, Icons.Filled.CloudOff)
        else -> Triple("Vérification du serveur…", Couleurs.Gris, Icons.Filled.Cloud)
    }
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Row(verticalAlignment = Alignment.CenterVertically) { Icon(icone, null, tint = couleur, modifier = Modifier.size(16.dp)); Spacer(Modifier.width(4.dp)); Text(texte, color = couleur, fontSize = 13.sp, fontWeight = FontWeight.SemiBold) }
        if (mode.isNotBlank()) Text(mode, color = Couleurs.Gris, fontSize = 11.sp)
    }
}

@Composable
fun PiedVersion() = Text(libelleVersion(), color = Couleurs.Gris, fontSize = 11.sp, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(8.dp))

// ================================================================================================================ démarrage, attente d'autorisation
@Composable
fun EcranDemarrage() = Box(Modifier.fillMaxSize(), Alignment.Center) { Column(horizontalAlignment = Alignment.CenterHorizontally) { CircularProgressIndicator(color = Couleurs.Orange); Spacer(Modifier.height(12.dp)); Text("Patientez…") } }

@Composable
fun EcranAttente(e: UiEtat, vm: AppViewModel) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        Icon(Icons.Filled.GppBad, null, tint = Couleurs.Rouge, modifier = Modifier.size(64.dp))
        Spacer(Modifier.height(8.dp))
        Text("Accès non autorisé", fontSize = 22.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(8.dp))
        Text(e.messageAttente.ifBlank { "Cet appareil n'est pas encore autorisé par l'administrateur SAWALI." }, textAlign = TextAlign.Center)
        Spacer(Modifier.height(12.dp))
        if (e.appareilId.isNotBlank()) Text("Identifiant de l'appareil : ${e.appareilId}", fontWeight = FontWeight.SemiBold, color = Couleurs.BleuCiel)
        Text("Communiquez cet identifiant à l'administrateur : il renseignera votre nom, votre zone et votre base, puis autorisera l'appareil.", fontSize = 13.sp, color = Couleurs.Gris, textAlign = TextAlign.Center)
        Spacer(Modifier.height(16.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            BoutonAction("Actualiser", Icons.Filled.Refresh, !e.enCours) { vm.verifierServeur(); vm.rafraichirStatut() }
            BoutonAction("Paramètres", Icons.Filled.Settings, plein = false) { vm.aller(Ecran.PARAMETRES) }
        }
        Spacer(Modifier.height(12.dp))
        PastilleServeur(e.serveur, e.modeAffiche)
        PiedVersion()
    }
}

// ================================================================================================================ connexion
@Composable
fun EcranConnexion(e: UiEtat, vm: AppViewModel) {
    // Identifiant mémorisé pour la zone de l'appareil (jamais le mot de passe) ; la zone change => on retrouve l'identifiant de la nouvelle zone
    var login by remember(e.profil.login, e.statut?.zone) { mutableStateOf(e.profil.login) }
    var mdp by remember { mutableStateOf("") }
    var memoriser by remember { mutableStateOf(true) }
    val activite = LocalContext.current.activiteFragment()
    val rapides = (listOf(e.profil.preferee) + METHODES_RAPIDES).distinct().filter { it in e.profil.methodes }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        Card(colors = CardDefaults.cardColors(containerColor = Color.White), elevation = CardDefaults.cardElevation(4.dp), modifier = Modifier.fillMaxWidth().widthIn(max = 420.dp)) {
            Column(Modifier.padding(20.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Icon(Icons.Filled.PhoneAndroid, null, tint = Couleurs.BleuCiel, modifier = Modifier.size(48.dp))
                Text("Loois Mobile", fontSize = 24.sp, fontWeight = FontWeight.Bold)
                Text("SAWALI Smart Systems", color = Couleurs.Gris, fontSize = 12.sp)
                Spacer(Modifier.height(8.dp))
                PastilleServeur(e.serveur, e.modeAffiche)
                Spacer(Modifier.height(8.dp))
                e.statut?.let { s ->
                    // Zone et base imposées par l'administrateur : affichées, jamais modifiables ici (comme le choix grisé de Loois)
                    AssistChip(onClick = {}, enabled = false, label = { Text("Zone /${s.zone} · base ${s.base}", fontSize = 12.sp) }, leadingIcon = { Icon(Icons.Filled.Storage, null, Modifier.size(16.dp)) })
                    if (s.nomUtilisateur.isNotBlank()) Text("Appareil de ${s.nomUtilisateur}", fontSize = 12.sp, color = Couleurs.Gris)
                }
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(login, { login = it }, label = { Text("Utilisateur") }, singleLine = true, leadingIcon = { Icon(Icons.Filled.Person, null) }, modifier = Modifier.fillMaxWidth())
                Spacer(Modifier.height(8.dp))
                ChampMotDePasse(mdp, { mdp = it }, "Mot de passe", Modifier.fillMaxWidth())
                Spacer(Modifier.height(12.dp))
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                    Checkbox(memoriser, { memoriser = it }); Text("Mémoriser l'identifiant pour cette zone", fontSize = 13.sp)
                }
                BoutonAction("Se Connecter", Icons.AutoMirrored.Filled.Login, !e.enCours) { vm.connecter(login, mdp, memoriser) }
                // Connexion rapide : seulement les méthodes activées pour cette zone (méthode préférée en premier) ; Internet requis, le mot de passe reste le secours
                if (rapides.isNotEmpty() && e.profil.login.isNotBlank()) {
                    Spacer(Modifier.height(10.dp))
                    Text("Connexion rapide — ${e.profil.login}", color = Couleurs.Gris, fontSize = 12.sp)
                    rapides.forEach { m ->
                        OutlinedButton(onClick = { if (activite != null) vm.connecterRapide(m, activite) }, enabled = !e.enCours && activite != null, modifier = Modifier.fillMaxWidth().padding(top = 4.dp)) {
                            Icon(iconeMethode(m), null, Modifier.size(18.dp)); Spacer(Modifier.width(8.dp)); Text(libelleMethode(m))
                        }
                    }
                }
                Spacer(Modifier.height(4.dp))
                Row { TextButton(onClick = { vm.verifierServeur(); vm.rafraichirStatut() }) { Icon(Icons.Filled.Refresh, null, Modifier.size(16.dp)); Spacer(Modifier.width(4.dp)); Text("Actualiser") }
                    TextButton(onClick = { vm.aller(Ecran.PARAMETRES) }) { Icon(Icons.Filled.Settings, null, Modifier.size(16.dp)); Spacer(Modifier.width(4.dp)); Text("Paramètres") } }
            }
        }
        PiedVersion()
    }
}

// ================================================================================================================ menu
@Composable
fun EcranMenu(e: UiEtat, vm: AppViewModel) {
    Column(Modifier.fillMaxSize()) {
        BarreHaut(titreMenu("loois mobile"), null) { IconButton(onClick = { vm.deconnecter() }) { Icon(Icons.AutoMirrored.Filled.Logout, "Se déconnecter", tint = Color.White) } }
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Filled.Person, null, tint = Couleurs.BleuCiel); Spacer(Modifier.width(8.dp))
                Column { Text(e.utilisateur?.login ?: "", fontWeight = FontWeight.Bold, fontSize = 18.sp)
                    Text("${e.utilisateur?.espace ?: ""} · base ${e.statut?.base ?: ""}${if (e.droits?.administrateur == true) " · administrateur" else if (e.droits?.laboratoire == true) " · laboratoire (consultation)" else ""}", color = Couleurs.Gris, fontSize = 12.sp) }
            }
            PastilleServeur(e.serveur, e.modeAffiche)
            TuileMenu("Connexion Rapide", "Empreinte / visage, compte Google, clé d'accès", Icons.Filled.Fingerprint, Couleurs.OrangeFonce) { vm.aller(Ecran.RAPIDE); vm.chargerRapide() }
            if (e.droits?.tableauDeBord == true) {
                TuileMenu("Tableau de Bord", "Reçus et montants du jour, par caissier, 7 derniers jours", Icons.Filled.Dashboard, Couleurs.Vert) { vm.aller(Ecran.TABLEAU); if (e.tableau == null) vm.chargerTableau() }
            }
            if (e.droits?.caisse == true) {
                TuileMenu("Historique de Caisse", "Reçus du jour, détail et totaux", Icons.Filled.Receipt, Couleurs.BleuCiel) { vm.aller(Ecran.HISTORIQUE); if (e.historique == null) vm.chargerHistorique() }
            }
            if (e.droits?.corrections == true) {
                TuileMenu("Corrections de Reçus", "Reçus dont la validité est à corriger", Icons.Filled.FactCheck, Couleurs.OrangeFonce) { vm.aller(Ecran.CORRECTIONS); if (e.corrections == null) vm.chargerCorrections() }
            }
            if (e.droits?.caisse != true && e.droits?.tableauDeBord != true) Text("La caisse n'est pas disponible pour cette zone (${e.utilisateur?.espace ?: ""}).", color = Couleurs.Gris)
            TuileMenu("Paramètres", "Adresses du serveur et mode de connexion", Icons.Filled.Settings, Couleurs.Gris) { vm.aller(Ecran.PARAMETRES) }
        }
        PiedVersion()
    }
}

@Composable
fun TuileMenu(titre: String, soustitre: String, icone: ImageVector, couleur: Color, onClick: () -> Unit) {
    Card(onClick = onClick, colors = CardDefaults.cardColors(containerColor = Color.White), border = BorderStroke(1.5.dp, couleur), modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(icone, null, tint = couleur, modifier = Modifier.size(36.dp)); Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) { Text(titreMenu(titre.lowercase().replaceFirstChar { it.uppercase() }), fontWeight = FontWeight.Bold, fontSize = 17.sp); Text(soustitre, color = Couleurs.Gris, fontSize = 12.sp) }
            Icon(Icons.Filled.ChevronRight, null, tint = couleur)
        }
    }
}

// ================================================================================================================ Historique de Caisse et Corrections de reçus (même écran : liste d'un jour)
@Composable
fun SelecteurJour(jour: String, onChange: (String) -> Unit) {
    var ouvert by remember { mutableStateOf(false) }
    Row(verticalAlignment = Alignment.CenterVertically) {
        IconButton(onClick = { onChange(decalerJour(jour, -1)) }) { Icon(Icons.Filled.ChevronLeft, "Jour précédent") }
        OutlinedButton(onClick = { ouvert = true }) { Icon(Icons.Filled.CalendarMonth, null, Modifier.size(18.dp)); Spacer(Modifier.width(6.dp)); Text(jourFr(jour), fontWeight = FontWeight.Bold) }
        IconButton(onClick = { onChange(decalerJour(jour, 1)) }) { Icon(Icons.Filled.ChevronRight, "Jour suivant") }
    }
    if (ouvert) {
        val etat = rememberDatePickerState(initialSelectedDateMillis = try { LocalDate.parse(jour).atStartOfDay().toInstant(ZoneOffset.UTC).toEpochMilli() } catch (x: Exception) { null })
        DatePickerDialog(onDismissRequest = { ouvert = false },
            confirmButton = { TextButton(onClick = { etat.selectedDateMillis?.let { onChange(Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate().toString()) }; ouvert = false }) { Text("Valider") } },
            dismissButton = { TextButton(onClick = { ouvert = false }) { Text("Annuler") } }) { DatePicker(etat) }
    }
}

/** Lot M8 — choix de la date de vente : les jours APRÈS aujourd'hui ne sont pas sélectionnables (règle : jamais supérieure à la date système). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SelecteurDateVente(jour: String, modifiee: Boolean, onChange: (String) -> Unit) {
    var ouvert by remember { mutableStateOf(false) }
    val plafond = LocalDate.now(ZoneOffset.UTC).atStartOfDay().toInstant(ZoneOffset.UTC).toEpochMilli()
    OutlinedButton(onClick = { ouvert = true }, border = BorderStroke(if (modifiee) 2.dp else 1.dp, if (modifiee) Couleurs.OrangeFonce else Color(0xFFCBD5E1))) {
        Icon(Icons.Filled.CalendarMonth, null, Modifier.size(18.dp)); Spacer(Modifier.width(6.dp)); Text("Date : ${jourFr(jour)}", fontWeight = FontWeight.Bold)
        Spacer(Modifier.width(6.dp)); Icon(Icons.Filled.Edit, "Modifier la date de vente", Modifier.size(14.dp))
    }
    if (ouvert) {
        val etat = rememberDatePickerState(initialSelectedDateMillis = try { LocalDate.parse(jour).atStartOfDay().toInstant(ZoneOffset.UTC).toEpochMilli() } catch (x: Exception) { null },
            selectableDates = object : SelectableDates { override fun isSelectableDate(utcTimeMillis: Long) = utcTimeMillis <= plafond })
        DatePickerDialog(onDismissRequest = { ouvert = false },
            confirmButton = { TextButton(onClick = { etat.selectedDateMillis?.let { onChange(Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate().toString()) }; ouvert = false }) { Text("Valider") } },
            dismissButton = { TextButton(onClick = { ouvert = false }) { Text("Annuler") } }) { DatePicker(etat) }
    }
}

@Composable
fun EcranListe(e: UiEtat, vm: AppViewModel, corrections: Boolean) {
    val liste = if (corrections) e.corrections else e.historique
    val titre = if (corrections) "Corrections De Reçus" else "Historique De Caisse"
    val voirTous = e.droits?.voirTousLesRecus == true
    val affichage = remember(liste, e.tri, e.seulementACorriger, corrections) {
        val base = liste?.recus ?: emptyList()
        trierRecus(if (corrections && e.seulementACorriger) base.filter { it.aCorriger } else base, e.tri)
    }
    Column(Modifier.fillMaxSize()) {
        BarreHaut(titre, { vm.retour() }) { IconButton(onClick = { if (corrections) vm.chargerCorrections() else vm.chargerHistorique() }, enabled = !e.enCours) { Icon(Icons.Filled.Refresh, "Actualiser", tint = Color.White) } }
        Column(Modifier.padding(horizontal = 12.dp, vertical = 6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                SelecteurJour(e.jour) { vm.changerJour(it) }
                Spacer(Modifier.weight(1f))
                BoutonAction("Afficher", Icons.Filled.Search, !e.enCours) { if (corrections) vm.chargerCorrections() else vm.chargerHistorique() }
            }
            if (voirTous) OutlinedTextField(e.caissierFiltre, { vm.changerCaissier(it) }, label = { Text("Caissier (vide = tous)") }, singleLine = true, leadingIcon = { Icon(Icons.Filled.Person, null) }, modifier = Modifier.fillMaxWidth())
            // Lot M5 — retrouver un reçu par son numéro (complet ou fin du numéro) puis l'ouvrir
            if (!corrections) Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 4.dp)) {
                OutlinedTextField(e.recherche, { vm.changerRecherche(it) }, label = { Text("Numéro du reçu ou de la facture (R-202630889, 0461/2026)") }, singleLine = true,
                    leadingIcon = { Icon(Icons.Filled.Search, null) }, modifier = Modifier.weight(1f),
                    keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(imeAction = androidx.compose.ui.text.input.ImeAction.Search),
                    keyboardActions = androidx.compose.foundation.text.KeyboardActions(onSearch = { vm.rechercherRecu() }))
                Spacer(Modifier.width(8.dp))
                BoutonAction("Ouvrir", Icons.Filled.Search, !e.enCours && e.recherche.trim().length >= 3) { vm.rechercherRecu() }
            }
            e.resultatsRecherche?.takeIf { it.isNotEmpty() }?.let { trouves ->
                Text("Reçus trouvés (touchez pour ouvrir) :", fontWeight = FontWeight.SemiBold, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
                trouves.forEach { r -> LigneListe(r, e.selection == r.reference, false) { vm.ouvrirRecu(r.reference, Ecran.HISTORIQUE) } }
            }
            if (corrections) {
                if (liste?.consultationSeule == true) Text("Consultation seule (laboratoire).", color = Couleurs.Gris, fontSize = 12.sp)
                Row(verticalAlignment = Alignment.CenterVertically) { Switch(e.seulementACorriger, { vm.filtrerACorriger(it) }); Spacer(Modifier.width(8.dp)); Text("Reçus à corriger seulement") }
            }
            // En-têtes triables (règle 19) : 1er toucher croissant ▲, 2e décroissant ▼, 3e ordre d'origine
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf(ColonneTri.HEURE to "Heure", ColonneTri.PATIENT to "Patient", ColonneTri.MONTANT to "Montant", ColonneTri.CAISSIER to "Caissier").forEach { (c, nom) ->
                    val actif = e.tri.colonne == c
                    FilterChip(selected = actif, onClick = { vm.basculerTriColonne(c) }, label = { Text(nom) },
                        trailingIcon = { Icon(if (!actif) Icons.Filled.UnfoldMore else if (e.tri.croissant) Icons.Filled.ArrowUpward else Icons.Filled.ArrowDownward, null, Modifier.size(16.dp)) })
                }
            }
        }
        if (liste == null) Box(Modifier.weight(1f).fillMaxWidth(), Alignment.Center) { Text(if (e.enCours) "Patientez…" else "Touchez « Afficher » pour lire les reçus.", color = Couleurs.Gris) }
        else LazyColumn(Modifier.weight(1f)) {
            items(affichage) { r -> LigneListe(r, e.selection == r.reference, corrections) { vm.ouvrirRecu(r.reference, if (corrections) Ecran.CORRECTIONS else Ecran.HISTORIQUE) } }
            if (affichage.isEmpty()) item { Text(if (corrections && e.seulementACorriger) "Aucun reçu à corriger ce jour-là." else "Aucun reçu ce jour-là.", Modifier.padding(16.dp), color = Couleurs.Gris) }
        }
        // Ligne de TOTAUX toujours visible sous la liste (règle 25) : nombre de reçus à gauche, montants alignés à droite
        liste?.let {
            Row(Modifier.fillMaxWidth().background(Color(0xFFE0F2FE)).padding(horizontal = 12.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("${affichage.size} reçu(s)", fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                if (it.tronque) Text("limité à 200 ", color = Couleurs.OrangeFonce, fontSize = 11.sp)
                Text(formaterMontant(affichage.sumOf { r -> r.montant }), fontWeight = FontWeight.Bold, color = Couleurs.Vert, textAlign = TextAlign.End)
            }
        }
        PiedVersion()
    }
}

/** Une ligne de reçu. Sélectionnée = fond orange + texte bleu nuit (règle 3). Référence en bleu, montant en vert, « à corriger » en orange avec pictogramme (règle 16). */
@Composable
fun LigneListe(r: Recu, selectionnee: Boolean, corrections: Boolean, onClick: () -> Unit) {
    val fond = if (selectionnee) Couleurs.Orange else Color.White
    val texte = if (selectionnee) Couleurs.BleuNuit else Color(0xFF0F172A)
    Row(Modifier.fillMaxWidth().background(fond).border(BorderStroke(0.5.dp, Color(0xFFE2E8F0))).clickable(onClick = onClick).padding(horizontal = 12.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(r.reference, color = if (selectionnee) Couleurs.BleuNuit else Couleurs.BleuCiel, fontWeight = FontWeight.Bold)
                Spacer(Modifier.width(8.dp)); Text(r.heure, color = texte, fontSize = 12.sp)
                if (corrections && r.aCorriger) { Spacer(Modifier.width(8.dp)); Icon(Icons.Filled.Warning, null, tint = Couleurs.OrangeFonce, modifier = Modifier.size(16.dp)); Text(" ${r.lignesACorriger} à corriger", color = if (selectionnee) Couleurs.BleuNuit else Couleurs.OrangeFonce, fontSize = 12.sp, fontWeight = FontWeight.SemiBold) }
            }
            Text(r.patient.ifBlank { "—" }, color = texte)
            Text(r.caissier, color = if (selectionnee) Couleurs.BleuNuit else Couleurs.Gris, fontSize = 11.sp)
        }
        Text(formaterMontant(r.montant), color = if (selectionnee) Couleurs.BleuNuit else Couleurs.Vert, fontWeight = FontWeight.Bold, textAlign = TextAlign.End)
    }
}

// ================================================================================================================ détail d'un reçu
/** Réglé / Visé : « Oui » (vert, coche) / « Non » (rouge, croix) / « — » (inconnu) : l'état est TOUJOURS écrit, la couleur ne suffit jamais. */
@Composable
fun EtatOuiNon(libelle: String, valeur: Boolean?, onClick: (() -> Unit)? = null, modifie: Boolean = false) {
    val (texte, couleur, icone) = when (valeur) {
        true -> Triple("Oui", Couleurs.Vert, Icons.Filled.CheckCircle)
        false -> Triple("Non", Color(0xFFB91C1C), Icons.Filled.Cancel)
        null -> Triple("—", Couleurs.Gris, Icons.Filled.Info)
    }
    // Modifiable : toute la zone se touche (au moins 48 dp), encadrée d'un filet orange tant que la valeur n'est pas enregistrée
    val zone = if (onClick == null) Modifier else Modifier.heightIn(min = 48.dp).border(BorderStroke(if (modifie) 2.dp else 1.dp, if (modifie) Couleurs.OrangeFonce else Color(0xFFCBD5E1)), RoundedCornerShape(8.dp)).clickable { onClick() }.padding(horizontal = 10.dp)
    Row(verticalAlignment = Alignment.CenterVertically, modifier = zone) {
        Text("$libelle : ", fontWeight = FontWeight.SemiBold)
        Icon(icone, null, tint = couleur, modifier = Modifier.size(18.dp)); Spacer(Modifier.width(4.dp))
        Text(texte, color = couleur, fontWeight = FontWeight.Bold)
        if (onClick != null) { Spacer(Modifier.width(6.dp)); Icon(Icons.Filled.Edit, "Modifier $libelle", tint = Couleurs.Gris, modifier = Modifier.size(14.dp)) }
    }
}

@Composable
fun EcranDetail(e: UiEtat, vm: AppViewModel) {
    val d = e.detail
    Column(Modifier.fillMaxSize()) {
        BarreHaut("Reçu ${d?.recu?.reference ?: ""}", { vm.retour() })
        if (d == null) { Box(Modifier.weight(1f).fillMaxWidth(), Alignment.Center) { Text("Patientez…") }; PiedVersion(); return }
        val r = d.recu
        if (e.confirmerModif) AlertDialog(
            onDismissRequest = { vm.fermerConfirmationModif() },
            icon = { Icon(Icons.Filled.Warning, null, tint = Couleurs.OrangeFonce) },
            title = { Text("Écrire dans la base du client ?") },
            text = { Text("Reçu ${r.reference}\n" + (e.editDate?.let { "Date de vente : ${jourFr(r.dateVente)} → ${jourFr(it)} (heure ${r.heure} conservée)\n" } ?: "") + (e.editRegle?.let { "Réglé : ${if (d.infos.regle == true) "oui" else "non"} → ${if (it) "oui" else "non"}\n" } ?: "") +
                (e.editVise?.let { "Visé : ${if (d.infos.vise == true) "oui" else "non"} → ${if (it) "oui" else "non"}\n" } ?: "") +
                (if (e.editPartAssure != null) "Part assuré : ${formaterMontant(r.partAssure)} → ${formaterMontant(lireNombreSaisi(e.editPartAssure) ?: 0.0)}\nPart assureur : ${formaterMontant(r.partAssureur)} → ${formaterMontant(lireNombreSaisi(e.editPartAssureur) ?: 0.0)}\n(montant total ${formaterMontant(d.infos.montantTotal ?: 0.0)}, inchangé)\n" else "") + "\nLa modification sera enregistrée dans HFSQL et notée dans le journal.") },
            confirmButton = { Button(onClick = { vm.enregistrerModifs() }) { Icon(Icons.Filled.Save, null, Modifier.size(18.dp)); Spacer(Modifier.width(6.dp)); Text("Confirmer l'enregistrement") } },
            dismissButton = { OutlinedButton(onClick = { vm.fermerConfirmationModif() }) { Icon(Icons.Filled.Close, null, Modifier.size(18.dp)); Spacer(Modifier.width(6.dp)); Text("Annuler") } })
        LazyColumn(Modifier.weight(1f)) {
            item {
                Column(Modifier.padding(12.dp)) {
                    Text(r.patient.ifBlank { "—" }, fontWeight = FontWeight.Bold, fontSize = 20.sp)
                    val peutModifier = e.droits?.administrateur == true && e.droits?.consultationSeule == false
                    // Lot M8 — date de vente : le superviseur la change (jamais après aujourd'hui), l'heure de la vente est conservée
                    if (peutModifier) Row(verticalAlignment = Alignment.CenterVertically) {
                        SelecteurDateVente(e.editDate ?: r.dateVente, e.editDate != null) { vm.changerDateVente(it) }
                        Text("  à ${r.heure} · client ${r.codeClient}", color = Couleurs.Gris, fontSize = 12.sp)
                    } else Text("${jourFr(r.dateVente)} à ${r.heure} · client ${r.codeClient}", color = Couleurs.Gris, fontSize = 12.sp)
                    Spacer(Modifier.height(6.dp))
                    // Lot M5 — caissier, VID (vendeur), réglé et visé : écrits en toutes lettres (jamais la couleur seule)
                    Text("Caissier : ${r.caissier.ifBlank { "—" }}  ·  VID : ${d.infos.vid.ifBlank { "—" }}", fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                    // Lot M6 : le SUPERVISEUR touche « Réglé » / « Visé » pour changer la valeur, puis « Enregistrer » (avec confirmation) ; les autres utilisateurs ne font que lire
                    val regleAffiche = e.editRegle ?: d.infos.regle
                    val viseAffiche = e.editVise ?: d.infos.vise
                    Row(horizontalArrangement = Arrangement.spacedBy(16.dp), modifier = Modifier.padding(top = 4.dp)) {
                        EtatOuiNon("Réglé", regleAffiche, if (peutModifier) ({ vm.basculerRegle() }) else null, e.editRegle != null)
                        EtatOuiNon("Visé", viseAffiche, if (peutModifier) ({ vm.basculerVise() }) else null, e.editVise != null)
                    }
                    if (peutModifier) {
                        val modifie = e.editRegle != null || e.editVise != null || e.editDate != null || e.editPartAssure != null
                        Text(if (modifie) "✏ Modifié, non enregistré" else "Superviseur : changez la date, « Réglé », « Visé » ou une part, puis « Enregistrer ».", color = if (modifie) Couleurs.OrangeFonce else Couleurs.Gris, fontSize = 12.sp, modifier = Modifier.padding(top = 4.dp))
                        if (modifie) Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 4.dp)) {
                            BoutonAction("Enregistrer", Icons.Filled.Save, !e.enCours) { vm.demanderConfirmationModif() }
                            BoutonAction("Annuler", Icons.Filled.Close, !e.enCours, plein = false) { vm.annulerModifs() }
                        }
                    }
                    Spacer(Modifier.height(6.dp))
                    // Lot M7 — montant total, PPC et parts assuré / assureur (patient assuré) : le superviseur tape UNE part, l'autre est calculée (total − part)
                    val total = d.infos.montantTotal ?: (r.partAssure + r.partAssureur).takeIf { it > 0 } ?: r.montant
                    Row { Text("Montant total : ", fontWeight = FontWeight.SemiBold); Text(formaterMontant(total), color = Couleurs.Vert, fontWeight = FontWeight.Bold) }
                    d.infos.montantRegle?.let { Text("Montant réglé : ${formaterMontant(it)}", fontSize = 12.sp) }
                    if (r.ppc > 0 || r.partAssure > 0 || r.partAssureur > 0) {
                        Text("Prise en charge (PPC) : ${formaterNombreSaisi(r.ppc)} %", fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 6.dp))
                        val partsModifiees = e.editPartAssure != null
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 4.dp)) {
                            if (peutModifier) {
                                OutlinedTextField(e.editPartAssure ?: formaterNombreSaisi(r.partAssure), { vm.changerPartAssure(it) }, label = { Text("Part assuré") }, singleLine = true,
                                    modifier = Modifier.weight(1f), keyboardOptions = KeyboardOptions(keyboardType = androidx.compose.ui.text.input.KeyboardType.Decimal))
                                OutlinedTextField(e.editPartAssureur ?: formaterNombreSaisi(r.partAssureur), { vm.changerPartAssureur(it) }, label = { Text("Part assureur") }, singleLine = true,
                                    modifier = Modifier.weight(1f), keyboardOptions = KeyboardOptions(keyboardType = androidx.compose.ui.text.input.KeyboardType.Decimal))
                            } else {
                                Column(Modifier.weight(1f)) { Text("Part assuré", fontSize = 11.sp, color = Couleurs.Gris); Text(formaterMontant(r.partAssure), fontWeight = FontWeight.Bold) }
                                Column(Modifier.weight(1f)) { Text("Part assureur", fontSize = 11.sp, color = Couleurs.Gris); Text(formaterMontant(r.partAssureur), fontWeight = FontWeight.Bold) }
                            }
                        }
                        if (peutModifier) Text(if (partsModifiees) "✏ L'autre part est calculée : assuré + assureur = ${formaterMontant(total)}" else "Changez une part : l'autre est calculée (assuré + assureur = montant total).",
                            fontSize = 11.sp, color = if (partsModifiees) Couleurs.OrangeFonce else Couleurs.Gris)
                    }
                    if (d.aCorriger) Row(Modifier.padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Filled.Warning, null, tint = Couleurs.OrangeFonce); Spacer(Modifier.width(6.dp))
                        Text("Une ou plusieurs lignes ont une validité propre différente de celle de la clinique${d.validiteClinique?.let { " ($it jours)" } ?: ""}.", color = Couleurs.OrangeFonce, fontSize = 13.sp)
                    }
                }
            }
            items(d.lignes) { l ->
                Column(Modifier.fillMaxWidth().background(if (l.necessiteCorrection) Color(0xFFFFF7ED) else Color.White).border(BorderStroke(0.5.dp, Color(0xFFE2E8F0))).padding(12.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(l.designation.ifBlank { l.codeProduit }, fontWeight = FontWeight.SemiBold)
                            Text("${l.codeProduit} · ${l.domaine}${if (l.medecin.isNotBlank()) " · ${l.medecin}" else ""}", color = Couleurs.Gris, fontSize = 11.sp)
                        }
                        Text(formaterMontant(l.montant), color = Couleurs.Vert, fontWeight = FontWeight.Bold, textAlign = TextAlign.End)
                    }
                    Text("${formaterQuantite(l.quantite)} × ${formaterMontant(l.prixUnitaire)}", fontSize = 12.sp, color = Couleurs.Gris)
                    if (l.joursValiditeEffective > 0) Row(verticalAlignment = Alignment.CenterVertically) {
                        if (l.necessiteCorrection) Icon(Icons.Filled.Warning, null, tint = Couleurs.OrangeFonce, modifier = Modifier.size(14.dp))
                        Text(" Validité ${l.joursValiditeEffective} j${if (l.necessiteCorrection) " (propre à la prestation)" else ""} · expire le ${dateHeureFr(l.dateExpiration)}", fontSize = 12.sp,
                            color = if (l.necessiteCorrection) Couleurs.OrangeFonce else Couleurs.Gris, fontWeight = if (l.necessiteCorrection) FontWeight.SemiBold else FontWeight.Normal)
                    }
                }
            }
        }
        // Total des lignes, collé sous la liste (règle 25)
        Row(Modifier.fillMaxWidth().background(Color(0xFFE0F2FE)).padding(horizontal = 12.dp, vertical = 10.dp)) {
            Text("${d.lignes.size} ligne(s)", fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            Text(formaterMontant(d.total), fontWeight = FontWeight.Bold, color = Couleurs.Vert, textAlign = TextAlign.End)
        }
        PiedVersion()
    }
}

// ================================================================================================================ paramètres : adresses et mode de connexion
@Composable
fun EcranParametres(e: UiEtat, vm: AppViewModel) {
    var sawali by remember { mutableStateOf(e.urlSawali) }
    var locale by remember { mutableStateOf(e.urlLocale) }
    var mode by remember { mutableStateOf(e.mode) }
    var liste by remember { mutableStateOf(false) }
    val modes = listOf("auto" to "Automatique (Internet si détecté, sinon serveur local)", "internet" to "Toujours Internet (SQL distantes via SAWALI)", "local" to "Toujours le serveur local")
    Column(Modifier.fillMaxSize()) {
        BarreHaut("Paramètres", { vm.retour() })
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Quand une connexion Internet est détectée, l'essentiel des transactions passe par SAWALI (SQL distantes). Sinon, l'application utilise l'adresse du serveur local ci-dessous.", color = Couleurs.Gris, fontSize = 13.sp)
            ExposedDropdownMenuBox(expanded = liste, onExpandedChange = { liste = it }) {
                OutlinedTextField(modes.first { it.first == mode }.second, {}, readOnly = true, label = { Text("Mode de connexion") }, trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(liste) },
                    modifier = Modifier.menuAnchor().fillMaxWidth())
                ExposedDropdownMenu(expanded = liste, onDismissRequest = { liste = false }) { modes.forEach { (k, t) -> DropdownMenuItem(text = { Text(t) }, onClick = { mode = k; liste = false }) } }
            }
            OutlinedTextField(sawali, { sawali = it }, label = { Text("Adresse de SAWALI (Internet)") }, singleLine = true, leadingIcon = { Icon(Icons.Filled.Cloud, null) }, modifier = Modifier.fillMaxWidth(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri))
            OutlinedTextField(locale, { locale = it }, label = { Text("Adresse du serveur local (ex. http://192.168.1.10:8750)") }, singleLine = true, leadingIcon = { Icon(Icons.Filled.Dns, null) },
                modifier = Modifier.fillMaxWidth(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri))
            Text("Le serveur local doit exposer la passerelle Loois (même API). https:// est obligatoire pour Internet ; http:// n'est accepté que pour une adresse du réseau local.", color = Couleurs.Gris, fontSize = 12.sp)
            // Passerelles locales reçues de SAWALI quand l'appareil est autorisé : rien à saisir (la saisie ci-dessus reste possible pour une adresse particulière)
            Text("Serveurs locaux reçus de SAWALI", fontWeight = FontWeight.SemiBold)
            if (e.serveursLocaux.isEmpty()) Text("Aucun pour l'instant : ils arrivent quand l'appareil est autorisé et qu'un service Loois à jour s'est signalé à SAWALI.", color = Couleurs.Gris, fontSize = 12.sp)
            else e.serveursLocaux.forEach { Row(verticalAlignment = Alignment.CenterVertically) { Icon(Icons.Filled.Dns, null, tint = Couleurs.BleuCiel, modifier = Modifier.size(16.dp)); Spacer(Modifier.width(6.dp)); Text(it, fontSize = 13.sp) } }
            if (e.ticketExpire.isNotBlank()) Text("Accès sans Internet valable jusqu'au ${e.ticketExpire} (renouvelé à chaque connexion à Internet).", color = Couleurs.Gris, fontSize = 12.sp)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                BoutonAction("Enregistrer", Icons.Filled.Save) { vm.sauverParametres(sawali, locale, mode) }
                BoutonAction("Tester Le Serveur", Icons.Filled.Refresh, plein = false) { vm.verifierServeur() }
            }
            PastilleServeur(e.serveur, e.modeAffiche)
            // Mémorisation par zone (lot M4) : ce que le téléphone retient pour la zone de l'appareil
            val zoneTxt = e.statut?.zone ?: ""
            if (zoneTxt.isNotBlank()) {
                Text("Mémorisé pour la zone /$zoneTxt", fontWeight = FontWeight.SemiBold)
                Text(if (e.profil.login.isBlank() && e.profil.methodes.isEmpty()) "Rien pour l'instant : l'identifiant est mémorisé à la prochaine connexion (case « Mémoriser l'identifiant »)."
                    else "Identifiant : ${e.profil.login.ifBlank { "—" }} · connexion rapide : ${if (e.profil.methodes.isEmpty()) "aucune" else e.profil.methodes.joinToString(", ") { libelleMethode(it) }}. Le mot de passe n'est jamais enregistré.", color = Couleurs.Gris, fontSize = 12.sp)
                if (e.profil != ProfilZone()) BoutonAction("Oublier Cette Zone", Icons.Filled.DeleteSweep, plein = false) { vm.oublierProfil() }
            }
            if (e.appareilId.isNotBlank()) Text("Identifiant de l'appareil : ${e.appareilId}", color = Couleurs.BleuCiel, fontSize = 12.sp)
        }
        PiedVersion()
    }
}

// ================================================================================================================ tableau de bord de suivi
/** Une barre : hauteur proportionnelle à `part` (0 à 1) ; le meilleur jour est en vert, les autres en bleu ciel. */
@Composable
fun BarreGraphique(part: Float, meilleur: Boolean, hauteurMax: Int = 110) {
    Box(Modifier.width(26.dp).height((hauteurMax * part.coerceIn(0.03f, 1f)).dp).background(if (meilleur) Couleurs.Vert else Couleurs.BleuCiel, RoundedCornerShape(topStart = 4.dp, topEnd = 4.dp)))
}

@Composable
fun CarteIndicateur(titre: String, valeur: String, couleur: Color, modifier: Modifier = Modifier) {
    Card(colors = CardDefaults.cardColors(containerColor = Color.White), border = BorderStroke(1.dp, Color(0xFFE2E8F0)), modifier = modifier) {
        Column(Modifier.padding(12.dp)) { Text(titre, color = Couleurs.Gris, fontSize = 12.sp); Text(valeur, color = couleur, fontWeight = FontWeight.Bold, fontSize = 18.sp) }
    }
}

@Composable
fun EcranTableau(e: UiEtat, vm: AppViewModel) {
    val t = e.tableau
    Column(Modifier.fillMaxSize()) {
        BarreHaut("Tableau De Bord", { vm.retour() }) { IconButton(onClick = { vm.chargerTableau() }, enabled = !e.enCours) { Icon(Icons.Filled.Refresh, "Actualiser", tint = Color.White) } }
        Row(Modifier.padding(horizontal = 12.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            SelecteurJour(e.jour) { vm.changerJour(it) }
            Spacer(Modifier.weight(1f))
            BoutonAction("Afficher", Icons.Filled.Search, !e.enCours) { vm.chargerTableau() }
        }
        if (t == null) { Box(Modifier.weight(1f).fillMaxWidth(), Alignment.Center) { Text(if (e.enCours) "Patientez…" else "Touchez « Afficher » pour lire le tableau de bord.", color = Couleurs.Gris) }; PiedVersion(); return }
        LazyColumn(Modifier.weight(1f), contentPadding = PaddingValues(horizontal = 12.dp)) {
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    CarteIndicateur("Reçus", t.nombre.toString(), Couleurs.BleuCiel, Modifier.weight(1f))
                    CarteIndicateur("Montant réglé", formaterMontant(t.total), Couleurs.Vert, Modifier.weight(1.4f))
                    CarteIndicateur("Panier moyen", formaterMontant(t.panierMoyen), Couleurs.BleuNuit, Modifier.weight(1.2f))
                }
                Spacer(Modifier.height(12.dp))
                Text("Par caissier", fontWeight = FontWeight.Bold, fontSize = 16.sp)
                Spacer(Modifier.height(4.dp))
            }
            if (t.parCaissier.isEmpty()) item { Text("Aucun reçu ce jour-là.", color = Couleurs.Gris, modifier = Modifier.padding(vertical = 8.dp)) }
            items(t.parCaissier) { c ->
                val part = if (t.total > 0) (c.montant / t.total).toFloat() else 0f
                Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(c.caissier, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f)); Text("${c.nombre} reçu(s)", color = Couleurs.Gris, fontSize = 12.sp)
                        Spacer(Modifier.width(10.dp)); Text(formaterMontant(c.montant), color = Couleurs.Vert, fontWeight = FontWeight.Bold, textAlign = TextAlign.End)
                    }
                    Box(Modifier.fillMaxWidth().height(6.dp).background(Color(0xFFE2E8F0), RoundedCornerShape(3.dp))) { Box(Modifier.fillMaxWidth(part.coerceIn(0f, 1f)).height(6.dp).background(Couleurs.BleuCiel, RoundedCornerShape(3.dp))) }
                }
            }
            item {
                Spacer(Modifier.height(16.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("7 derniers jours", fontWeight = FontWeight.Bold, fontSize = 16.sp, modifier = Modifier.weight(1f))
                    if (e.semaineEnCours) { CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp, color = Couleurs.Orange); Spacer(Modifier.width(6.dp)); Text("Chargement…", color = Couleurs.Gris, fontSize = 12.sp) }
                }
                val w = e.semaine
                if (w == null) { if (!e.semaineEnCours) Text("Non disponible.", color = Couleurs.Gris, fontSize = 12.sp) }
                else {
                    val maxi = (w.jours.maxOfOrNull { it.montant } ?: 0.0).coerceAtLeast(1.0)
                    val meilleur = w.jours.maxByOrNull { it.montant }?.date
                    Row(Modifier.fillMaxWidth().padding(top = 8.dp), horizontalArrangement = Arrangement.SpaceEvenly, verticalAlignment = Alignment.Bottom) {
                        w.jours.forEach { j ->
                            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                Text(formaterMontantCourt(j.montant), fontSize = 10.sp, color = Couleurs.Gris)
                                BarreGraphique((j.montant / maxi).toFloat(), j.date == meilleur && j.montant > 0)
                                Text(jourCourt(j.date), fontSize = 10.sp)
                            }
                        }
                    }
                }
                Spacer(Modifier.height(8.dp))
            }
        }
        // Totaux collés sous la liste (règle 25) : jour, puis 7 jours
        Column(Modifier.fillMaxWidth().background(Color(0xFFE0F2FE)).padding(horizontal = 12.dp, vertical = 8.dp)) {
            Row { Text("${t.parCaissier.size} caissier(s) · ${t.nombre} reçu(s)", fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f)); Text(formaterMontant(t.total), fontWeight = FontWeight.Bold, color = Couleurs.Vert, textAlign = TextAlign.End) }
            e.semaine?.let { w -> Row { Text("7 jours · ${w.nombre} reçu(s)", color = Couleurs.Gris, fontSize = 12.sp, modifier = Modifier.weight(1f)); Text(formaterMontant(w.total), color = Couleurs.Vert, fontSize = 12.sp, textAlign = TextAlign.End) } }
        }
        PiedVersion()
    }
}

// ================================================================================================================ connexion rapide
/** Retrouve la FragmentActivity (exigée par BiometricPrompt) derrière le contexte de l'interface ; nul dans les tests sans activité adaptée. */
fun Context.activiteFragment(): FragmentActivity? { var c: Context? = this; while (c is ContextWrapper) { if (c is FragmentActivity) return c; c = c.baseContext }; return null }

fun iconeMethode(m: String) = when (m) { "biometrie" -> Icons.Filled.Fingerprint; "google" -> Icons.Filled.AccountCircle; else -> Icons.Filled.VpnKey }

/** Une méthode : état (activée / non), bouton Activer ou Retirer. `indisponible` explique pourquoi elle ne peut pas être activée. */
@Composable
fun CarteMethode(methode: String, titre: String, aide: String, liaisons: List<LiaisonRapide>, indisponible: String?, enCours: Boolean, activer: () -> Unit, retirer: (LiaisonRapide) -> Unit) {
    Card(colors = CardDefaults.cardColors(containerColor = Color.White), border = BorderStroke(1.dp, Color(0xFFE2E8F0)), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(iconeMethode(methode), null, tint = Couleurs.BleuCiel); Spacer(Modifier.width(8.dp))
                Text(titre, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                Text(if (liaisons.isEmpty()) "Non activée" else "Activée", color = if (liaisons.isEmpty()) Couleurs.Gris else Couleurs.Vert, fontWeight = FontWeight.SemiBold, fontSize = 12.sp)
            }
            Text(aide, color = Couleurs.Gris, fontSize = 12.sp, modifier = Modifier.padding(top = 4.dp))
            liaisons.forEach { l ->
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 6.dp)) {
                    Text(listOf(l.detail, "depuis le ${l.creeLe.take(10)}").filter { it.isNotBlank() }.joinToString(" · "), fontSize = 12.sp, modifier = Modifier.weight(1f))
                    TextButton(onClick = { retirer(l) }, enabled = !enCours) { Icon(Icons.Filled.Delete, null, Modifier.size(16.dp)); Spacer(Modifier.width(4.dp)); Text("Retirer") }
                }
            }
            if (indisponible != null) Text(indisponible, color = Couleurs.OrangeFonce, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp))
            else Spacer(Modifier.height(6.dp))
            if (indisponible == null) BoutonAction(if (liaisons.isEmpty()) "Activer" else "Réactiver", Icons.Filled.Check, !enCours, plein = liaisons.isEmpty()) { activer() }
        }
    }
}

@Composable
fun EcranRapide(e: UiEtat, vm: AppViewModel) {
    val activite = LocalContext.current.activiteFragment()
    fun de(m: String) = e.rapide.filter { it.methode == m }
    Column(Modifier.fillMaxSize()) {
        BarreHaut("Connexion Rapide", { vm.retour() }) { IconButton(onClick = { vm.chargerRapide() }, enabled = !e.enCours) { Icon(Icons.Filled.Refresh, "Actualiser", tint = Color.White) } }
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Connectez-vous sans retaper votre mot de passe. Il n'est jamais enregistré : chaque méthode est liée à ce téléphone, à la zone /${e.statut?.zone ?: ""} et à l'identifiant ${e.utilisateur?.login ?: ""}, et SAWALI revérifie l'identifiant chez le client à chaque connexion. Elles demandent Internet ; le mot de passe reste le secours.", color = Couleurs.Gris, fontSize = 13.sp)
            val act = activite
            CarteMethode("biometrie", "Empreinte / visage", "L'empreinte, le visage ou, à défaut, le code du téléphone déverrouille un secret gardé dans le coffre Android.", de("biometrie"), if (act == null) "Indisponible dans ce contexte." else null, e.enCours,
                { act?.let { vm.activerBiometrie(it) } }, { vm.retirerRapide(it) })
            CarteMethode("google", "Compte Google", "Liez votre compte Google : il remplace le mot de passe, jamais le contrôle de l'identifiant chez le client.", de("google"),
                if (e.configRapide?.google == false) "Pas encore configuré sur SAWALI (l'administrateur doit saisir le client Google)." else if (act == null) "Indisponible dans ce contexte." else null, e.enCours,
                { act?.let { vm.activerGoogle(it) } }, { vm.retirerRapide(it) })
            CarteMethode("cle", "Clé d'accès", "Une clé d'accès (passkey) créée sur ce téléphone, protégée par son empreinte ou son code d'écran.", de("cle"), if (act == null) "Indisponible dans ce contexte." else null, e.enCours,
                { act?.let { vm.activerCle(it) } }, { vm.retirerRapide(it) })
        }
        PiedVersion()
    }
}
