@file:OptIn(ExperimentalMaterial3Api::class)

package bf.sawali.loois

import androidx.activity.compose.BackHandler
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
    BackHandler(enabled = e.ecran in setOf(Ecran.HISTORIQUE, Ecran.DETAIL, Ecran.CORRECTIONS, Ecran.PARAMETRES)) { vm.retour() }
    Scaffold(snackbarHost = { SnackbarHost(snack) }, containerColor = Couleurs.Fond) { marge ->
        Box(Modifier.padding(marge).fillMaxSize()) {
            when (e.ecran) {
                Ecran.DEMARRAGE -> EcranDemarrage()
                Ecran.ATTENTE_AUTORISATION -> EcranAttente(e, vm)
                Ecran.CONNEXION -> EcranConnexion(e, vm)
                Ecran.MENU -> EcranMenu(e, vm)
                Ecran.HISTORIQUE -> EcranListe(e, vm, corrections = false)
                Ecran.CORRECTIONS -> EcranListe(e, vm, corrections = true)
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
    var login by remember { mutableStateOf("") }
    var mdp by remember { mutableStateOf("") }
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
                BoutonAction("Se Connecter", Icons.AutoMirrored.Filled.Login, !e.enCours) { vm.connecter(login, mdp) }
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
            if (e.droits?.caisse == true) {
                TuileMenu("Historique de Caisse", "Reçus du jour, détail et totaux", Icons.Filled.Receipt, Couleurs.BleuCiel) { vm.aller(Ecran.HISTORIQUE); if (e.historique == null) vm.chargerHistorique() }
            }
            if (e.droits?.corrections == true) {
                TuileMenu("Corrections de Reçus", "Reçus dont la validité est à corriger", Icons.Filled.FactCheck, Couleurs.OrangeFonce) { vm.aller(Ecran.CORRECTIONS); if (e.corrections == null) vm.chargerCorrections() }
            }
            if (e.droits?.caisse != true) Text("La caisse n'est pas disponible pour cette zone (${e.utilisateur?.espace ?: ""}).", color = Couleurs.Gris)
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
@Composable
fun EcranDetail(e: UiEtat, vm: AppViewModel) {
    val d = e.detail
    Column(Modifier.fillMaxSize()) {
        BarreHaut("Reçu ${d?.recu?.reference ?: ""}", { vm.retour() })
        if (d == null) { Box(Modifier.weight(1f).fillMaxWidth(), Alignment.Center) { Text("Patientez…") }; PiedVersion(); return }
        val r = d.recu
        LazyColumn(Modifier.weight(1f)) {
            item {
                Column(Modifier.padding(12.dp)) {
                    Text(r.patient.ifBlank { "—" }, fontWeight = FontWeight.Bold, fontSize = 20.sp)
                    Text("${jourFr(r.dateVente)} à ${r.heure} · caissier ${r.caissier} · client ${r.codeClient}", color = Couleurs.Gris, fontSize = 12.sp)
                    Spacer(Modifier.height(6.dp))
                    Row { Text("Réglé : ", fontWeight = FontWeight.SemiBold); Text(formaterMontant(r.montant), color = Couleurs.Vert, fontWeight = FontWeight.Bold) }
                    if (r.partAssure > 0 || r.partAssureur > 0) Text("Part assuré ${formaterMontant(r.partAssure)} · part assureur ${formaterMontant(r.partAssureur)}", fontSize = 12.sp)
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
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                BoutonAction("Enregistrer", Icons.Filled.Save) { vm.sauverParametres(sawali, locale, mode) }
                BoutonAction("Tester Le Serveur", Icons.Filled.Refresh, plein = false) { vm.verifierServeur() }
            }
            PastilleServeur(e.serveur, e.modeAffiche)
            if (e.appareilId.isNotBlank()) Text("Identifiant de l'appareil : ${e.appareilId}", color = Couleurs.BleuCiel, fontSize = 12.sp)
        }
        PiedVersion()
    }
}
