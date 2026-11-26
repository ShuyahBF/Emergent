# sonde_reseau.py — Lot 470 : SONDE RÉSEAU (logique pure : fiches, statistiques, verdict, rapport HTML partageable).
#
# Pourquoi : le 26/11/2026, la connexion du propriétaire (box de l'opérateur) perdait 43 % des paquets et ne donnait que 0,9 Mb/s, alors qu'un partage de
# connexion mobile donnait 34 Mb/s. Il faut une PREUVE DANS LE TEMPS (pas un test isolé) à présenter à l'opérateur.
#
# Principe : une page des Paramètres (« 📶 Sonde réseau ») ouverte dans un navigateur sur le PC branché à la box (ou sur un téléphone) mesure toutes les
# 15 minutes la latence, la perte, les connexions HTTPS réelles, le débit descendant / montant et la lecture d'un flux vidéo, VERS CLOUDFLARE (jamais vers
# SAWALI : aucune charge pour le site). Chaque mesure est envoyée ici en arrière-plan. Ce module range les mesures, calcule les statistiques et fabrique le
# RAPPORT HTML autonome (courbes en SVG, aucune bibliothèque) que le propriétaire peut envoyer à l'opérateur.
#
# Stockage : UNE fiche de `settings` (`_id = "sonde_reseau"`), tableau `mesures` plafonné (les plus anciennes disparaissent) : aucune nouvelle collection
# (cluster MongoDB plein) et aucune écriture hors des mesures elles-mêmes (règle 7 : jamais d'écriture inutile).
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

DOC_ID = "sonde_reseau"
MAX_MESURES = 3000                 # ≈ 31 jours à une mesure toutes les 15 minutes pour un poste
DELAI_MIN_S = 50                   # un même poste ne peut pas envoyer plus d'une mesure toutes les 50 s (anti-abus)
SEUIL_PERTE_ATTENTION = 2.0        # % de perte : au-delà, connexion « instable »
SEUIL_PERTE_CRITIQUE = 10.0        # % de perte : au-delà, connexion « très dégradée »
DEBIT_FAIBLE_MBPS = 5.0            # sous ce débit descendant, la connexion est signalée « lente »


def maintenant_iso() -> str:
    """Instant présent en UTC, au format ISO (triable comme du texte : sert aux filtres de période)."""
    return datetime.now(timezone.utc).isoformat()


def nom_poste(brut: str) -> str:
    """Nom de poste sûr : lettres, chiffres, espace, tiret, souligné ; 40 caractères ; jamais vide (sert de clé dans la fiche)."""
    propre = re.sub(r"[^0-9A-Za-zÀ-ÿ _-]", "", str(brut or "")).strip()[:40]
    return propre or "Poste"


# ----------------------------------------------------------------------------------------------------------------------- statistiques
def _valeurs(mesures: List[dict], cle: str) -> List[float]:
    """Valeurs numériques présentes (les mesures sans cette valeur, par exemple débit non mesuré ce quart d'heure, sont ignorées)."""
    return [float(m[cle]) for m in mesures if m.get(cle) is not None]


def _moyenne(vals: List[float]) -> Optional[float]:
    return round(sum(vals) / len(vals), 1) if vals else None


def _centile(vals: List[float], p: int) -> Optional[float]:
    """Centile « rang le plus proche » (p = 95 → 95 % des mesures sont plus rapides)."""
    if not vals:
        return None
    triees = sorted(vals)
    rang = max(1, -(-len(triees) * p // 100))        # plafond de n*p/100, au moins 1
    return round(triees[min(rang, len(triees)) - 1], 1)


def filtrer(mesures: List[dict], jours: int, poste: Optional[str] = None, maintenant: Optional[str] = None) -> List[dict]:
    """Mesures des `jours` derniers jours (et d'un seul poste si demandé), de la plus ancienne à la plus récente."""
    fin = datetime.fromisoformat(maintenant) if maintenant else datetime.now(timezone.utc)
    debut = (fin - timedelta(days=max(1, jours))).isoformat()
    sortie = [m for m in mesures if str(m.get("le") or "") >= debut and (not poste or m.get("poste") == poste)]
    return sorted(sortie, key=lambda m: str(m.get("le") or ""))


def verdict(perte_pct: Optional[float], debit_moy: Optional[float]) -> Tuple[str, str]:
    """(niveau, phrase) : « ok » / « attention » / « critique » / « inconnu ». La perte prime ; un débit trop faible déclasse « ok » en « attention »."""
    if perte_pct is None:
        return "inconnu", "Pas encore assez de mesures pour juger la connexion."
    if perte_pct >= SEUIL_PERTE_CRITIQUE:
        return "critique", f"Connexion très dégradée : {perte_pct} % des paquets sont perdus (seuil critique {SEUIL_PERTE_CRITIQUE:g} %)."
    if perte_pct >= SEUIL_PERTE_ATTENTION:
        return "attention", f"Connexion instable : {perte_pct} % des paquets sont perdus (seuil d'alerte {SEUIL_PERTE_ATTENTION:g} %)."
    if debit_moy is not None and debit_moy < DEBIT_FAIBLE_MBPS:
        return "attention", f"Pertes faibles, mais débit descendant moyen très bas : {debit_moy} Mb/s."
    return "ok", "Connexion stable sur la période."


def resume(mesures: List[dict]) -> Dict[str, Any]:
    """Statistiques d'une liste de mesures (déjà filtrée par période et par poste)."""
    essais = sum(int(m.get("essais") or 0) for m in mesures)
    perdus = sum(int(m.get("perdus") or 0) for m in mesures)
    https_ok = sum(int(m.get("https_ok") or 0) for m in mesures)
    https_total = sum(int(m.get("https_total") or 0) for m in mesures)
    perte = round(100.0 * perdus / essais, 1) if essais else None
    desc = _valeurs(mesures, "debit_desc_mbps")
    mont = _valeurs(mesures, "debit_mont_mbps")
    lat = _valeurs(mesures, "latence_moy_ms")
    niveau, phrase = verdict(perte, _moyenne(desc))
    pires = sorted((m for m in mesures if (m.get("essais") or 0) > 0),
                   key=lambda m: (m.get("perdus") or 0) / m["essais"], reverse=True)[:5]
    return {
        "mesures": len(mesures), "essais": essais, "perdus": perdus, "perte_pct": perte,
        "latence_moy_ms": _moyenne(lat), "latence_p95_ms": _centile(lat, 95), "latence_max_ms": max(lat) if lat else None,
        "https_ok": https_ok, "https_total": https_total,
        "https_pct": round(100.0 * https_ok / https_total, 1) if https_total else None,
        "debit_desc_moy": _moyenne(desc), "debit_desc_min": round(min(desc), 1) if desc else None,
        "debit_mont_moy": _moyenne(mont),
        "premiere": mesures[0].get("le") if mesures else None, "derniere": mesures[-1].get("le") if mesures else None,
        "niveau": niveau, "verdict": phrase,
        "pires": [{"le": m.get("le"), "poste": m.get("poste"), "perdus": m.get("perdus"), "essais": m.get("essais")} for m in pires],
    }


def pct_perte(m: dict) -> Optional[float]:
    """Perte d'UNE mesure en % (None si aucun essai)."""
    return round(100.0 * (m.get("perdus") or 0) / m["essais"], 1) if (m.get("essais") or 0) > 0 else None


# ----------------------------------------------------------------------------------------------------------------------- rapport HTML
def _date_fr(iso: Optional[str]) -> str:
    """JJ/MM/AAAA HH:MM (l'heure UTC est l'heure du Burkina Faso)."""
    try:
        d = datetime.fromisoformat(str(iso))
        return d.strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return ""


def _n(v: Any, unite: str = "") -> str:
    """Nombre au format français (virgule), « — » si absent."""
    if v is None:
        return "—"
    if isinstance(v, float):
        txt = f"{v:.1f}"
        if txt.endswith(".0"):
            txt = txt[:-2]                       # 12.0 -> « 12 »
        txt = txt.replace(".", ",")              # virgule décimale française
    else:
        txt = f"{v:,}".replace(",", " ")         # entiers : espace entre les milliers
    return txt + unite


def _courbe(points: List[Optional[float]], couleur: str, titre: str, unite: str, seuil: Optional[float] = None) -> str:
    """Courbe SVG autonome (une ligne, valeur maximale rappelée) ; « — » si moins de 2 points."""
    vals = [(i, v) for i, v in enumerate(points) if v is not None]
    if len(vals) < 2:
        return f'<div class="courbe"><h4>{html.escape(titre)}</h4><p class="vide">Pas assez de points pour tracer la courbe.</p></div>'
    L, H = 640, 120
    vmax = max(v for _, v in vals) or 1.0
    vmax = max(vmax, seuil or 0) or 1.0
    x = lambda i: i * L / (len(points) - 1)                    # noqa: E731
    y = lambda v: H - (v / vmax) * (H - 12)                    # noqa: E731
    ligne = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in vals)
    repere = (f'<line x1="0" x2="{L}" y1="{y(seuil):.1f}" y2="{y(seuil):.1f}" stroke="#d97706" stroke-dasharray="5 4"/>' if seuil else "")
    return (f'<div class="courbe"><h4>{html.escape(titre)} <small>(maximum {_n(round(vmax, 1))} {html.escape(unite)})</small></h4>'
            f'<svg viewBox="0 0 {L} {H + 4}" role="img" aria-label="{html.escape(titre)}">{repere}'
            f'<polyline fill="none" stroke="{couleur}" stroke-width="2" points="{ligne}"/></svg></div>')


_COULEURS = {"ok": ("#065f46", "#d1fae5"), "attention": ("#92400e", "#fef3c7"), "critique": ("#991b1b", "#fee2e2"), "inconnu": ("#334155", "#e2e8f0")}


def rapport_html(mesures: List[dict], jours: int, poste: Optional[str], genere_le: Optional[str] = None) -> str:
    """Rapport HTML AUTONOME (styles et courbes intégrés, aucune ressource externe) : à enregistrer, joindre à un e-mail ou imprimer en PDF."""
    r = resume(mesures)
    texte_c, fond_c = _COULEURS.get(r["niveau"], _COULEURS["inconnu"])
    titre_poste = html.escape(poste) if poste else "tous les postes"
    derniers = list(reversed(mesures))[:100]                        # tableau : les 100 plus récentes d'abord
    lignes = "".join(
        f'<tr><td>{_date_fr(m.get("le"))}</td><td>{html.escape(str(m.get("poste") or ""))}</td>'
        f'<td>{"Mobile" if m.get("type") == "mobile" else "PC"}</td>'
        f'<td class="d">{_n(m.get("latence_moy_ms"))}</td><td class="d{" rouge" if (pct_perte(m) or 0) >= SEUIL_PERTE_CRITIQUE else ""}">{_n(pct_perte(m))}</td>'
        f'<td class="d">{m.get("https_ok", 0)}/{m.get("https_total", 0)}</td>'
        f'<td class="d">{_n(m.get("debit_desc_mbps"))}</td><td class="d">{_n(m.get("debit_mont_mbps"))}</td></tr>'
        for m in derniers)
    pires = "".join(f'<li>{_date_fr(p["le"])} · {html.escape(str(p["poste"] or ""))} : {p["perdus"]} paquet(s) perdu(s) sur {p["essais"]}</li>' for p in r["pires"]) or "<li>Aucune</li>"
    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rapport de la sonde réseau</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;color:#1b2a41;margin:0;background:#f3f5f9}} .page{{max-width:820px;margin:0 auto;padding:20px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;border-bottom:2px solid #f6a35b;padding-bottom:4px;margin-top:26px}} h4{{margin:14px 0 4px;font-size:13px}} small{{font-weight:normal;color:#5b6b82}}
.entete{{background:#0A1E3D;color:#fff;border-radius:10px;padding:16px 20px}} .entete p{{margin:2px 0;color:#c7d6ee;font-size:13px}}
.verdict{{margin-top:14px;border-radius:8px;padding:10px 14px;font-weight:600;color:{texte_c};background:{fond_c}}}
.cartes{{display:flex;flex-wrap:wrap;gap:10px;margin-top:12px}} .carte{{flex:1 1 150px;background:#fff;border:1px solid #dde3ee;border-radius:8px;padding:10px}}
.carte b{{display:block;font-size:20px}} .carte span{{font-size:12px;color:#5b6b82}}
table{{width:100%;border-collapse:collapse;font-size:12px;background:#fff}} th{{background:#0A1E3D;color:#fff;text-align:left;padding:6px}} td{{padding:5px 6px;border-top:1px solid #e3e8f0}}
.d{{text-align:right;font-variant-numeric:tabular-nums}} th.d{{text-align:right}} .rouge{{color:#b91c1c;font-weight:700}} .vide{{color:#5b6b82;font-size:12px}}
.courbe svg{{width:100%;height:auto;background:#fff;border:1px solid #dde3ee;border-radius:6px}} .note{{font-size:12px;color:#5b6b82}}
@media print{{body{{background:#fff}} .page{{padding:0}}}}
</style></head><body><div class="page">
<div class="entete"><h1>Rapport de la sonde réseau</h1>
<p>Poste : <b>{titre_poste}</b> · Période : {jours} dernier(s) jour(s) · du {_date_fr(r["premiere"])} au {_date_fr(r["derniere"])} (heure du Burkina Faso)</p>
<p>Généré le {_date_fr(genere_le or maintenant_iso())} par SAWALI · {r["mesures"]} mesure(s)</p></div>
<div class="verdict">{html.escape(r["verdict"])}</div>
<div class="cartes">
<div class="carte"><b>{_n(r["perte_pct"], " %")}</b><span>Perte de paquets ({r["perdus"]} sur {r["essais"]})</span></div>
<div class="carte"><b>{_n(r["latence_moy_ms"], " ms")}</b><span>Latence moyenne (95 % sous {_n(r["latence_p95_ms"], " ms")})</span></div>
<div class="carte"><b>{_n(r["debit_desc_moy"], " Mb/s")}</b><span>Débit descendant moyen (minimum {_n(r["debit_desc_min"], " Mb/s")})</span></div>
<div class="carte"><b>{_n(r["debit_mont_moy"], " Mb/s")}</b><span>Débit montant moyen</span></div>
<div class="carte"><b>{_n(r["https_pct"], " %")}</b><span>Connexions HTTPS réussies ({r["https_ok"]}/{r["https_total"]})</span></div>
</div>
<h2>Évolution dans le temps</h2>
{_courbe([m.get("latence_moy_ms") for m in mesures], "#2563eb", "Latence moyenne", "ms")}
{_courbe([pct_perte(m) for m in mesures], "#dc2626", "Perte de paquets", "%", SEUIL_PERTE_ATTENTION)}
{_courbe([m.get("debit_desc_mbps") for m in mesures], "#059669", "Débit descendant", "Mb/s", DEBIT_FAIBLE_MBPS)}
<h2>Les 5 pires mesures</h2><ul class="note">{pires}</ul>
<h2>Détail des mesures (100 dernières)</h2>
<table><thead><tr><th>Date</th><th>Poste</th><th>Type</th><th class="d">Latence (ms)</th><th class="d">Perte (%)</th><th class="d">HTTPS</th><th class="d">Débit ↓ (Mb/s)</th><th class="d">Débit ↑ (Mb/s)</th></tr></thead>
<tbody>{lignes or '<tr><td colspan="8">Aucune mesure sur la période.</td></tr>'}</tbody></table>
<h2>Méthode</h2>
<p class="note">Mesures faites toutes les 15 minutes depuis le navigateur du poste vers les serveurs publics de Cloudflare : 10 requêtes de latence (une requête sans réponse en 2 secondes compte comme un paquet perdu),
connexions HTTPS vers 3 services publics, puis, une fois par heure, un téléchargement et un envoi de données pour le débit. La perte est donc une estimation fondée sur des requêtes HTTPS, pas sur un « ping » système ;
elle reste représentative de l'expérience réelle de navigation. Seuils : instable à partir de {SEUIL_PERTE_ATTENTION:g} % de perte, très dégradée à partir de {SEUIL_PERTE_CRITIQUE:g} %.</p>
</div></body></html>"""
