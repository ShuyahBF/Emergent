package bf.sawali.loois

// =====================================================================================================================================
// EcransPointage.kt — lot M9 : écrans du POINTAGE HORS CONNEXION (Jetpack Compose), ouverts depuis le premier écran de Loois mobile,
// SANS compte Loois : les auxiliaires d'une boutique n'en ont pas. Le commerce est reconnu par son QR code et son mot de passe.
//   LISTE (inventaires gardés dans le téléphone) → AJOUT (scanner le QR / coller le lien) → MOT_DE_PASSE → PRENOM (et lieu) → COMPTAGE
//   (dictée ou clavier, « Suivant », « Annuler la dernière », exporter / importer un fichier, envoyer à SAWALI quand le réseau est là).
// Règles : pictogrammes usuels avec légende (règles 8 et 15), couleurs (règle 16), mot de passe avec l'œil (règle 22), langue du commerce.
// =====================================================================================================================================
import android.app.Activity
import android.content.Intent
import android.speech.RecognizerIntent
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Login
import androidx.compose.material.icons.automirrored.filled.Undo
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions

/** Point d'entrée du pointage ; `quitter` ramène à l'écran de Loois mobile d'où l'on vient. */
@Composable
fun EcranPointage(pvm: PointageVM, quitter: () -> Unit) {
    val e by pvm.etat.collectAsStateWithLifecycle()
    BackHandler { if (e.ecran == EcranP.LISTE) quitter() else pvm.aller(EcranP.LISTE) }
    Column(Modifier.fillMaxSize()) {
        BarreHaut(e.courant?.titre?.takeIf { e.ecran != EcranP.LISTE && e.ecran != EcranP.AJOUT } ?: e.t("Pointage d'inventaire"),
            retour = { if (e.ecran == EcranP.LISTE) quitter() else pvm.aller(EcranP.LISTE) })
        if (e.message.isNotBlank()) {
            Text(e.message, color = if (e.messageErreur) Couleurs.Rouge else Couleurs.Vert, fontWeight = FontWeight.SemiBold,
                modifier = Modifier.fillMaxWidth().background(if (e.messageErreur) Color(0xFFFEE2E2) else Color(0xFFD1FAE5)).padding(10.dp).clickable { pvm.effacerMessage() })
        }
        when (e.ecran) {
            EcranP.LISTE -> ListeInventaires(e, pvm)
            EcranP.AJOUT -> AjoutInventaire(e, pvm)
            EcranP.MOT_DE_PASSE -> MotDePasseCommerce(e, pvm)
            EcranP.PRENOM -> PrenomEtLieu(e, pvm)
            EcranP.COMPTAGE -> Comptage(e, pvm)
            EcranP.SOUSCRIPTION -> MaSouscription(e, pvm)
        }
    }
}

/** Bouton rond à pictogramme, avec légende (règle du 27/11/2026 : pictogrammes plutôt que gros boutons). */
@Composable
fun Rond(legende: String, icone: ImageVector, couleur: Color, grand: Boolean = false, actif: Boolean = true, onClick: () -> Unit) {
    Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.width(84.dp)) {
        Box(Modifier.size(if (grand) 76.dp else 56.dp).background(if (actif) couleur else Color(0xFFCBD5E1), CircleShape).clickable(enabled = actif) { onClick() },
            contentAlignment = Alignment.Center) { Icon(icone, legende, tint = Color.White, modifier = Modifier.size(if (grand) 38.dp else 26.dp)) }
        Text(legende, fontSize = 11.sp, textAlign = TextAlign.Center, color = Couleurs.Gris, lineHeight = 13.sp)
    }
}

@Composable
private fun ListeInventaires(e: EtatPointage, pvm: PointageVM) {
    LazyColumn(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { Text(e.t("Sans Internet : comptez, exportez, fusionnez, envoyez."), color = Couleurs.Gris) }
        item { BoutonAction(e.t("Ajouter un inventaire"), Icons.Filled.QrCodeScanner) { pvm.aller(EcranP.AJOUT) } }
        // Lot M9.1 : souscription du commerce (semaine, mois, année, illimité) — paiement mobile puis vérification par SAWALI
        item { BoutonAction(e.t("Ma souscription"), Icons.Filled.Verified, plein = false) { pvm.aller(EcranP.SOUSCRIPTION) } }
        if (e.inventaires.isEmpty()) item { Text(e.t("Aucun inventaire dans ce téléphone : ajoutez-en un avec le QR code (connexion nécessaire une seule fois)."), color = Couleurs.Gris) }
        items(e.inventaires) { inv ->
            Row(Modifier.fillMaxWidth().border(1.dp, Color(0xFFE2E8F0), RoundedCornerShape(12.dp)).clickable { pvm.ouvrir(inv) }.padding(12.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Filled.Inventory, null, tint = Couleurs.BleuCiel); Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(inv.titre, fontWeight = FontWeight.Bold)
                    Text("${inv.produits.size} · ${inv.cle}", fontSize = 12.sp, color = Couleurs.Gris)
                }
                Icon(Icons.Filled.ChevronRight, null, tint = Couleurs.Gris)
            }
        }
        item { PiedVersion() }
    }
}

@Composable
private fun AjoutInventaire(e: EtatPointage, pvm: PointageVM) {
    var lien by remember { mutableStateOf("") }
    // Lecteur de QR code intégré (fonctionne sans Internet ; la connexion ne sert qu'à télécharger l'inventaire)
    val scanner = rememberLauncherForActivityResult(ScanContract()) { r -> r.contents?.let { lien = it; pvm.preparer(it) } }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        BoutonAction(e.t("Scanner le QR code"), Icons.Filled.QrCodeScanner, !e.enCours) {
            scanner.launch(ScanOptions().setDesiredBarcodeFormats(ScanOptions.QR_CODE).setBeepEnabled(false).setOrientationLocked(false).setPrompt(""))
        }
        OutlinedTextField(lien, { lien = it }, label = { Text(e.t("Lien ou code du QR")) }, singleLine = true, modifier = Modifier.fillMaxWidth())
        BoutonAction(e.t("Ouvrir"), Icons.Filled.Download, lien.isNotBlank() && !e.enCours) { pvm.preparer(lien) }
        if (e.enCours) CircularProgressIndicator(color = Couleurs.Orange)
    }
}

@Composable
private fun MotDePasseCommerce(e: EtatPointage, pvm: PointageVM) {
    var mdp by remember { mutableStateOf("") }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(e.titreEnAttente.ifBlank { e.courant?.titre.orEmpty() }, fontWeight = FontWeight.Bold, fontSize = 18.sp)
        Row(verticalAlignment = Alignment.CenterVertically) { Icon(Icons.Filled.Key, null, tint = Color(0xFF7C3AED)); Spacer(Modifier.width(6.dp))
            Text("${e.t("Mot de passe du commerce")} · ${e.cleEnAttente}", fontWeight = FontWeight.SemiBold) }
        ChampMotDePasse(mdp, { mdp = it }, e.t("Mot de passe du commerce"), Modifier.fillMaxWidth())
        BoutonAction(e.t("Valider"), Icons.Filled.Check, mdp.length >= 4 && !e.enCours) { pvm.deverrouiller(mdp) }
        if (e.enCours) CircularProgressIndicator(color = Couleurs.Orange)
    }
}

@Composable
private fun PrenomEtLieu(e: EtatPointage, pvm: PointageVM) {
    val inv = e.courant ?: return
    var prenom by remember { mutableStateOf(e.prenom) }
    var lieu by remember { mutableStateOf(e.lieu) }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        OutlinedTextField(prenom, { prenom = it.take(30) }, label = { Text(e.t("Votre prénom")) }, singleLine = true, modifier = Modifier.fillMaxWidth())
        Text(e.t("Lieu que vous comptez"), fontWeight = FontWeight.SemiBold)
        inv.lieux.forEach { l ->
            Row(Modifier.fillMaxWidth().background(if (lieu == l.id) Couleurs.Orange else Color.Transparent, RoundedCornerShape(10.dp))
                .border(1.dp, Color(0xFFE2E8F0), RoundedCornerShape(10.dp)).clickable { lieu = l.id }.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Filled.Place, null, tint = if (lieu == l.id) Couleurs.BleuNuit else Couleurs.OrangeFonce); Spacer(Modifier.width(8.dp))
                Text(l.nom, color = if (lieu == l.id) Couleurs.BleuNuit else Color.Unspecified, fontWeight = if (lieu == l.id) FontWeight.Bold else FontWeight.Normal)
            }
        }
        BoutonAction(e.t("Commencer le pointage"), Icons.Filled.PlayArrow, prenom.trim().length >= 2 && lieu.isNotBlank()) { pvm.commencer(prenom, lieu) }
        TextButton(onClick = { pvm.supprimer(inv) }) { Icon(Icons.Filled.Delete, null, tint = Couleurs.Rouge); Spacer(Modifier.width(4.dp)); Text(e.t("Supprimer"), color = Couleurs.Rouge) }
    }
}

@Composable
private fun Comptage(e: EtatPointage, pvm: PointageVM) {
    val inv = e.courant ?: return
    val contexte = LocalContext.current
    var chrono by remember { mutableStateOf("") }
    var qte by remember { mutableStateOf("") }
    var per by remember { mutableStateOf("") }
    val produit = chrono.toIntOrNull()?.let { inv.produit(it) }
    fun valider() { if (pvm.saisir(chrono.toIntOrNull(), qte.toIntOrNull(), per.ifBlank { null })) { chrono = ""; qte = ""; per = "" } }

    // Dictée : reconnaissance vocale d'Android dans la langue du commerce, HORS CONNEXION si le pack de langue est installé sur le téléphone
    val dictee = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        val phrase = r.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()
        if (r.resultCode == Activity.RESULT_OK && phrase != null) {
            val d = analyserDictee(phrase)
            if (d.commande == "annule") { pvm.annulerDerniere(); return@rememberLauncherForActivityResult }
            d.chrono?.let { chrono = it.toString() }; d.qte?.let { qte = it.toString() }; d.peremption?.let { per = it }
            if (d.commande == "suivant") valider()
        }
    }
    val importeur = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris -> if (uris.isNotEmpty()) pvm.importer(uris) }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        // Qui, où, et ce qui reste à envoyer
        Row(verticalAlignment = Alignment.CenterVertically) {
            Row(Modifier.background(Color(0xFFFFEDD5), RoundedCornerShape(20.dp)).clickable { pvm.aller(EcranP.PRENOM) }.padding(horizontal = 10.dp, vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Filled.Place, e.t("Changer de lieu ou de prénom"), tint = Couleurs.OrangeFonce, modifier = Modifier.size(16.dp))
                Text(" ${inv.lieux.firstOrNull { it.id == e.lieu }?.nom.orEmpty()} · ${e.prenom}", color = Couleurs.OrangeFonce, fontWeight = FontWeight.SemiBold)
            }
            Spacer(Modifier.weight(1f))
            Text(if (e.aEnvoyer == 0) e.t("Tout est envoyé") else e.t("{n} saisie(s), {e} à envoyer", "n" to e.saisies.count { !it.annulee }, "e" to e.aEnvoyer),
                color = if (e.aEnvoyer == 0) Couleurs.Vert else Couleurs.OrangeFonce, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
        }
        // Lot M9.1 : souscription expirée → comptage fermé (export, fusion et envoi restent possibles)
        if (!inv.peutCompter()) Text(e.t("Souscription expirée : le comptage est fermé. Vous pouvez encore exporter, fusionner et envoyer les saisies déjà faites."),
            color = Couleurs.Rouge, fontWeight = FontWeight.SemiBold, modifier = Modifier.fillMaxWidth().background(Color(0xFFFEE2E2), RoundedCornerShape(10.dp)).padding(10.dp))
        // Produit reconnu : le garde-fou contre un mauvais numéro
        Column(Modifier.fillMaxWidth().border(2.dp, when { chrono.isBlank() -> Color(0xFFCBD5E1); produit != null -> Couleurs.Vert; else -> Couleurs.Rouge }, RoundedCornerShape(14.dp)).padding(12.dp)) {
            Text(produit?.libelle ?: if (chrono.isBlank()) e.t("Dites ou tapez le N° de ligne") else e.t("Ligne inconnue"), fontWeight = FontWeight.Bold, fontSize = 18.sp)
            produit?.let { Text("${it.mesure} · N° ${it.chrono}", color = Couleurs.Gris, fontSize = 13.sp) }
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(chrono, { chrono = it.filter(Char::isDigit).take(7) }, label = { Text(e.t("Ligne")) }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.weight(1f))
                OutlinedTextField(qte, { qte = it.filter(Char::isDigit).take(7) }, label = { Text(e.t("Quantité")) }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.weight(1f))
                OutlinedTextField(per, { per = it.take(7) }, label = { Text(e.t("Péremption")) }, placeholder = { Text("MM/AA") }, singleLine = true,
                    modifier = Modifier.weight(1.2f))
            }
        }
        // Actions principales
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceAround, verticalAlignment = Alignment.Bottom) {
            Rond(e.t("Annuler la dernière"), Icons.AutoMirrored.Filled.Undo, Color(0xFFE11D48)) { pvm.annulerDerniere() }
            Rond(e.t("Dicter"), Icons.Filled.Mic, Couleurs.BleuCiel, grand = true) {
                val intention = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                    .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                    .putExtra(RecognizerIntent.EXTRA_LANGUAGE, langueDictee(inv.langue))
                    .putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
                runCatching { dictee.launch(intention) }.onFailure { pvm.effacerMessage() }
            }
            Rond(e.t("Suivant"), Icons.Filled.Check, Couleurs.Vert, grand = true) { valider() }
        }
        // Fichiers et envoi : l'auxiliaire exporte, le responsable importe et fusionne, puis envoie quand le réseau est là
        Text(e.t("Fusionner les fichiers des autres téléphones"), fontWeight = FontWeight.SemiBold, color = Couleurs.Gris, fontSize = 13.sp)
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceAround) {
            Rond(e.t("Exporter"), Icons.Filled.Share, Color(0xFF7C3AED)) {
                pvm.fichierExport()?.let { f ->
                    val uri = FileProvider.getUriForFile(contexte, "${contexte.packageName}.fichiers", f)
                    val envoi = Intent(Intent.ACTION_SEND).setType("application/json").putExtra(Intent.EXTRA_STREAM, uri).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    contexte.startActivity(Intent.createChooser(envoi, e.t("Exporter")))
                }
            }
            Rond(e.t("Importer"), Icons.Filled.FileOpen, Color(0xFF0D9488)) { importeur.launch(arrayOf("application/json", "text/plain", "application/octet-stream", "*/*")) }
            Rond(e.t("Envoyer à SAWALI"), Icons.Filled.CloudUpload, Couleurs.OrangeFonce, actif = !e.enCours && e.aEnvoyer > 0) { pvm.envoyer() }
        }
        // Dernières saisies (toutes, y compris celles fusionnées depuis les autres téléphones)
        Text(e.t("Dernières saisies"), fontWeight = FontWeight.SemiBold)
        e.saisies.asReversed().take(15).forEach { s ->
            Row(Modifier.fillMaxWidth().padding(vertical = 3.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("${s.chrono}", color = Couleurs.BleuCiel, fontWeight = FontWeight.Bold, modifier = Modifier.width(48.dp))
                Text(inv.produit(s.chrono)?.libelle.orEmpty(), modifier = Modifier.weight(1f), maxLines = 1, fontSize = 13.sp)
                Text("${s.qte}${s.peremption?.let { " · $it" } ?: ""}", fontWeight = FontWeight.Bold, fontSize = 13.sp)
                Spacer(Modifier.width(6.dp))
                Text(when { s.annulee -> e.t("annulée"); s.envoyee -> e.t("envoyée"); else -> e.t("à envoyer") } + " · ${s.prenom}", fontSize = 11.sp,
                    color = when { s.annulee -> Couleurs.Gris; s.envoyee -> Couleurs.Vert; else -> Couleurs.OrangeFonce })
            }
        }
        PiedVersion()
    }
}

/** Lot M9.1 : « Ma souscription » — connexion à l'Espace pointage (clé + mot de passe), état, paiement USSD (le clavier du téléphone s'ouvre),
 *  référence de la transaction envoyée à SAWALI qui la rapproche du SMS de paiement. */
@Composable
private fun MaSouscription(e: EtatPointage, pvm: PointageVM) {
    val contexte = LocalContext.current
    var cle by remember { mutableStateOf(e.courant?.cle.orEmpty()) }
    var mdp by remember { mutableStateOf("") }
    var formule by remember { mutableStateOf("") }
    var operateur by remember { mutableStateOf("") }
    var reference by remember { mutableStateOf("") }
    val libelles = mapOf("semaine" to "Semaine", "mois" to "Mois", "annee" to "Année", "illimite" to "Illimité")
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        val s = e.souscription
        if (e.jetonEspace.isBlank() || s == null) {
            OutlinedTextField(cle, { cle = it.uppercase().take(12) }, label = { Text(e.t("Clé de pointage")) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            ChampMotDePasse(mdp, { mdp = it }, e.t("Mot de passe du commerce"), Modifier.fillMaxWidth())
            BoutonAction(e.t("Se connecter"), Icons.AutoMirrored.Filled.Login, cle.length >= 3 && mdp.length >= 4 && !e.enCours) { pvm.connecterEspace(cle, mdp) }
        } else {
            Text(when { s.illimite -> e.t("Souscription illimitée"); s.valide -> e.t("Souscription valide jusqu'au {d}", "d" to s.fin.take(16).replace("T", " "))
                else -> e.t("Sans souscription valide") }, fontWeight = FontWeight.Bold, color = if (s.valide) Couleurs.Vert else Couleurs.Rouge)
            // Formule et opérateur (listes de choix), puis séquence USSD
            Text(e.t("Formule"), fontWeight = FontWeight.SemiBold)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState())) {
                s.operateurs.flatMap { it.offres }.map { it.formule to it.montant }.distinct().forEach { (f, m) ->
                    FilterChip(selected = formule == f, onClick = { formule = f }, label = { Text("${e.t(libelles[f] ?: f)} · $m ${s.devise}", fontSize = 12.sp) })
                }
            }
            Text(e.t("Opérateur"), fontWeight = FontWeight.SemiBold)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                s.operateurs.forEach { o -> FilterChip(selected = operateur == o.id, onClick = { operateur = o.id }, label = { Text(o.nom) }) }
            }
            s.operateurs.firstOrNull { it.id == operateur }?.offres?.firstOrNull { it.formule == formule }?.let { offre ->
                Row(Modifier.fillMaxWidth().background(Color(0xFFF5F3FF), RoundedCornerShape(10.dp)).padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(offre.sequence, fontWeight = FontWeight.Bold, color = Color(0xFF6D28D9), fontSize = 18.sp, modifier = Modifier.weight(1f))
                    Rond(e.t("Composer"), Icons.Filled.Call, Couleurs.Vert) {
                        runCatching { contexte.startActivity(Intent(Intent.ACTION_DIAL, android.net.Uri.parse(offre.lien))) }
                    }
                }
                Text(e.t("Payez avec la séquence, puis saisissez la référence (ID) de la transaction reçue par SMS."), fontSize = 12.sp, color = Couleurs.Gris)
            }
            OutlinedTextField(reference, { reference = it.take(60) }, label = { Text(e.t("Référence de la transaction")) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            BoutonAction(e.t("Envoyer la référence"), Icons.Filled.Check, formule.isNotBlank() && operateur.isNotBlank() && reference.trim().length >= 4 && !e.enCours) {
                pvm.souscrire(formule, operateur, reference); reference = ""
            }
            s.historique.take(6).forEach { h ->
                val statut = mapOf("en_attente" to "En attente de vérification", "verifiee" to "Vérifiée", "refusee" to "Refusée")[h.texte("statut")] ?: h.texte("statut")
                Text("${e.t(statut)} · ${e.t(libelles[h.texte("formule")] ?: h.texte("formule"))} · ${h.optInt("montant")} ${h.texte("devise")} · ${h.texte("reference")}",
                    fontSize = 12.sp, color = if (h.texte("statut") == "verifiee") Couleurs.Vert else Couleurs.OrangeFonce)
            }
        }
        if (e.enCours) CircularProgressIndicator(color = Couleurs.Orange)
    }
}
