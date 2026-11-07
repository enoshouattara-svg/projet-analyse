#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analyse comparative de marché : Marché Lagune / Baobab Shop / Comptoir Ivoire
=============================================================================
DA Python · L2 Computer Science · séance 3

Pipeline (même ordre que l'énoncé) :
    1. Chargement      -> 3 sources hétérogènes (CSV `;`, JSON, Excel) => 1 DataFrame
    2. Nettoyage       -> chaque problème est consigné dans un JOURNAL
    3. Rapprochement   -> chaque article reçoit un `produit_id` du catalogue
    4. Comparatif      -> prix payé par enseigne, moins cher, écart
    5. Synthèse        -> victoires, écart moyen, top 3 des écarts
    6. Panier          -> 1 enseigne vs meilleur prix article par article
    7. Historique      -> semaine du Black Friday vs moyenne de l'année
    8. Complexité      -> benchmark de structures de données

Utilisation :  python analyse_marche.py            (tout, avec benchmark)
               python analyse_marche.py --no-bench (sans le benchmark)
"""
from __future__ import annotations

import argparse
import bisect
import csv
import difflib
import json
import random
import re
import sys
import time
import unicodedata
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # pas de fenêtre : on enregistre les figures en PNG
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Constantes
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = ROOT / "resultats"
FIG = OUT / "graphiques"

ML, BB, CI = "Marché Lagune", "Baobab Shop", "Comptoir Ivoire"
ENSEIGNES = [ML, BB, CI]
COULEURS = {ML: "#2E86AB", BB: "#E07A1F", CI: "#3A9D5D"}

SEUIL_STOCK_LIMITE = 5          # <= 5 unités => "Stock limité" (hypothèse, Baobab/Comptoir)
SEUIL_RAPPROCHEMENT = 0.45      # score minimal pour accepter un rapprochement
MARGE_RAPPROCHEMENT = 0.10      # écart minimal avec le 2e meilleur candidat
TOLERANCE_HISTORIQUE = 0.03     # écart toléré entre prix du fichier et historique récent

PANIER = {"P04": 1, "P12": 1, "P14": 2, "P15": 1, "P28": 1}
BF_DEBUT, BF_FIN = pd.Timestamp("2025-11-24"), pd.Timestamp("2025-11-30")


def fcfa(n) -> str:
    """Formate un entier en '102 900'."""
    return "n/d" if pd.isna(n) else f"{int(round(n)):,}".replace(",", " ")


# --------------------------------------------------------------------------
# Journal de nettoyage
# --------------------------------------------------------------------------
class Journal:
    """Liste de tous les problèmes de qualité détectés et de l'action menée."""

    def __init__(self):
        self.lignes: list[dict] = []

    def add(self, source, ref, probleme, detail, action):
        self.lignes.append(dict(source=source, reference=ref, probleme=probleme,
                                detail=detail, action=action))

    def to_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.lignes)


# ==========================================================================
# 1 + 2. CHARGEMENT ET NETTOYAGE
# ==========================================================================
def parse_prix(valeur):
    """'102 900 FCFA' / '279 300' / 102500 / None / 'Prix sur demande' -> int ou None.

    On supprime tout ce qui n'est pas un chiffre : cela élimine d'un coup les espaces
    normaux, les espaces insécables (U+00A0), les espaces fines insécables (U+202F,
    présentes dans les fichiers !) et le suffixe 'FCFA'.
    """
    if valeur is None or (isinstance(valeur, float) and np.isnan(valeur)):
        return None
    if isinstance(valeur, (int, float, np.integer, np.floating)):
        return int(valeur)
    chiffres = re.sub(r"\D", "", str(valeur))
    return int(chiffres) if chiffres else None


def statut_depuis_quantite(q) -> str:
    if q <= 0:
        return "Rupture"
    return "Stock limité" if q <= SEUIL_STOCK_LIMITE else "En stock"


def charger_marche_lagune(J: Journal) -> pd.DataFrame:
    J.add(ML, "(fichier)", "Format", "BOM UTF-8, séparateur ';', fins de ligne CRLF, virgule décimale",
          "lecture avec encoding='utf-8-sig' et sep=';'")
    brut = pd.read_csv(DATA / "marche_lagune.csv", sep=";", encoding="utf-8-sig", dtype=str)

    # --- doublons exacts (même référence, mêmes valeurs)
    dup = brut.duplicated(keep="first")
    for ref in brut.loc[dup, "reference"]:
        J.add(ML, ref, "Doublon", "ligne strictement identique à une ligne précédente", "ligne supprimée")
    brut = brut[~dup].reset_index(drop=True)
    assert brut["reference"].is_unique

    # --- espaces superflus en début/fin de désignation
    for i, r in brut.iterrows():
        if r["designation"] != r["designation"].strip():
            J.add(ML, r["reference"], "Espaces superflus", f"« {r['designation']} »", "strip() appliqué")
            brut.at[i, "designation"] = r["designation"].strip()

    # --- casse incohérente (le site écrit en MAJUSCULES, une ligne en minuscules)
    for _, r in brut.iterrows():
        if r["designation"] != r["designation"].upper():
            J.add(ML, r["reference"], "Casse incohérente", f"« {r['designation']} »",
                  "normalisation (minuscules sans accents) avant rapprochement")

    lignes = []
    for _, r in brut.iterrows():
        prix = parse_prix(r["prix"])
        if prix is None:
            J.add(ML, r["reference"], "Prix non exploitable", f"prix = « {r['prix'] if isinstance(r['prix'], str) else '(vide)'} »",
                  "prix mis à vide : offre non retenue pour le « moins cher »")
        if r["disponibilite"] == "Rupture":
            J.add(ML, r["reference"], "Rupture de stock", f"{r['designation']} : « Rupture »", "offre non retenue")
        ancien = parse_prix(r["ancien_prix"])
        note = float(r["note_clients"].replace(",", ".")) if isinstance(r["note_clients"], str) else np.nan
        lignes.append(dict(
            enseigne=ML, ref_source=r["reference"], libelle_brut=r["designation"],
            prix_affiche=prix, ancien_prix=ancien, frais_livraison=0, remise_pct=0.0,
            statut=r["disponibilite"], note=note, nb_avis=int(r["nb_avis"]),
            mode="livraison incluse", date_maj=pd.NaT))
    return pd.DataFrame(lignes)


def charger_baobab(J: Journal) -> pd.DataFrame:
    with open(DATA / "baobab_shop.json", encoding="utf-8") as f:
        doc = json.load(f)
    if doc["count"] != len(doc["items"]):
        J.add(BB, "(fichier)", "Incohérence", f"count={doc['count']} mais {len(doc['items'])} articles", "ignoré")
    date_gen = pd.Timestamp(doc["generated_at"]).tz_localize(None).normalize()
    lignes = []
    tiers = 0
    for it in doc["items"]:
        p = it["pricing"]
        if p["amount"] is None:
            J.add(BB, it["sku"], "Prix non exploitable", f"{it['title']} : amount = null",
                  "offre non retenue pour le « moins cher »")
        if it["stock"] == 0:
            J.add(BB, it["sku"], "Rupture de stock", f"{it['title']} : stock = 0", "offre non retenue")
        if it["seller"] != "Baobab Shop":
            tiers += 1
        if it["rating"]["count"] < 30:
            J.add(BB, it["sku"], "Note peu fiable", f"{it['rating']['count']} avis seulement",
                  "conservé, signalé (information)")
        lignes.append(dict(
            enseigne=BB, ref_source=it["sku"], libelle_brut=it["title"],
            prix_affiche=parse_prix(p["amount"]), ancien_prix=None,
            frais_livraison=p["delivery_fee"], remise_pct=0.0,
            statut=statut_depuis_quantite(it["stock"]), note=it["rating"]["average"],
            nb_avis=it["rating"]["count"], mode="livraison payante" if p["delivery_fee"] else "livraison offerte",
            date_maj=date_gen))
    J.add(BB, "(fichier)", "Information", f"{tiers} articles vendus par un « Partenaire vérifié » (pas par Baobab)",
          "conservés (même prix payé par le client)")
    return pd.DataFrame(lignes)


def charger_comptoir(J: Journal) -> pd.DataFrame:
    J.add(CI, "(fichier)", "Format", "titre en ligne 1, ligne 2 vide, en-têtes en ligne 3",
          "lecture avec header=2")
    brut = pd.read_excel(DATA / "comptoir_ivoire.xlsx", sheet_name=0, header=2)
    brut.columns = ["code", "article", "rayon", "prix", "remise", "quantite", "date_maj"]
    brut = brut.dropna(subset=["code"])
    lignes = []
    for _, r in brut.iterrows():
        if isinstance(r["prix"], str):
            J.add(CI, r["code"], "Prix stocké en texte", f"« {r['prix']!r} » (espace fine insécable)",
                  "converti en entier")
        prix = parse_prix(r["prix"])
        q = int(r["quantite"])
        if q == 0:
            J.add(CI, r["code"], "Rupture de stock", f"{r['article']} : quantité en rayon = 0", "offre non retenue")
        age = (pd.Timestamp("2026-10-31") - pd.Timestamp(r["date_maj"])).days
        if age > 21:
            J.add(CI, r["code"], "Prix potentiellement ancien", f"mis à jour il y a {age} jours",
                  "conservé, signalé (information)")
        lignes.append(dict(
            enseigne=CI, ref_source=r["code"], libelle_brut=r["article"],
            prix_affiche=prix, ancien_prix=None, frais_livraison=0,
            remise_pct=float(r["remise"]), statut=statut_depuis_quantite(q), note=np.nan,
            nb_avis=0, mode="retrait en boutique", date_maj=pd.Timestamp(r["date_maj"])))
    return pd.DataFrame(lignes)


# ==========================================================================
# 3. RAPPROCHEMENT avec le catalogue
# ==========================================================================
# Les trois enseignes décrivent le même produit différemment (langue, casse, abréviations,
# unités). On ramène tout à une forme canonique, puis on note chaque candidat du catalogue
# par recouvrement de mots pondérés.
STOPWORDS = {"a", "de", "du", "la", "le", "les", "sur", "pc", "portable", "laptop", "et", "-"}
PHRASES = [("air conditioner", "climatiseur"), ("steam iron", "fer repasser"),
           ("fer a repasser", "fer repasser"), ("microwave", "micro ondes"),
           ("disque dur", "disque dur")]
SYNONYMES = {"fridge": "refrigerateur", "frigo": "refrigerateur", "clim": "climatiseur",
             "ventilo": "ventilateur", "mouse": "souris", "blender": "mixeur", "kettle": "bouilloire",
             "electric": "electrique", "monitor": "ecran", "printer": "imprimante", "router": "routeur",
             "freezer": "congelateur", "dd": "disque dur", "wireless": "sans fil"}
UNITES = [(r"(\d+)\s*\"", r"\1 pouces"),
          (r"(\d+(?:\.\d+)?)\s*(?:go|gb|gigaoctets?)\b", r"\1gb"),
          (r"(\d+(?:\.\d+)?)\s*(?:to|tb|teraoctets?)\b", r"\1tb"),
          (r"(\d+(?:\.\d+)?)\s*(?:litres?|l)\b", r"\1l"),
          (r"(\d+(?:\.\d+)?)\s*(?:cv|hp|chevaux)\b", r"\1cv"),       # 1HP (anglais) = 1CV
          (r"(\d+)\s*(?:pouces?|inch|in)\b", r"\1in")]


def sans_accents(t: str) -> str:
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()


def tokens(texte: str) -> list[str]:
    """Texte brut -> liste de mots canoniques (minuscules, sans accents, unités unifiées)."""
    t = sans_accents(texte).lower()
    t = re.sub(r"(\d),(\d)", r"\1.\2", t)             # 1,5 -> 1.5
    for motif, rempl in UNITES:                       # '128 Go' / '128GB' -> '128gb'
        t = re.sub(motif, rempl, t)
    t = re.sub(r"[^a-z0-9.\"]+", " ", t)              # ponctuation -> espace ('micro-ondes' -> 'micro ondes')
    t = re.sub(r"(?<![0-9])\.|\.(?![0-9])", " ", t)   # points isolés
    for a, b in PHRASES:
        t = t.replace(a, b)
    out = []
    for mot in t.split():
        out.extend(SYNONYMES.get(mot, mot).split())
    return [m for m in out if m not in STOPWORDS]


def poids(mot: str, marques: set[str]) -> int:
    """Un mot avec un chiffre (a15, 128gb, 205l) identifie le produit : poids 3.
    Une marque : 2. Un mot ordinaire : 1."""
    if any(c.isdigit() for c in mot):
        return 3
    return 2 if mot in marques else 1


def preparer_catalogue(cat: pd.DataFrame) -> tuple[dict, set]:
    marques = {sans_accents(m).lower() for m in cat["marque"]}
    index = {r.produit_id: set(tokens(r.nom)) for r in cat.itertuples()}
    return index, marques


def rapprocher(libelle: str, index: dict, marques: set):
    """Renvoie (produit_id, score, corrections_fuzzy) ou (None, meilleur_score, []).
    Complexité : O(|catalogue| x |mots|) par article, soit ~30 x 6 : négligeable."""
    mots = tokens(libelle)
    scores = []
    for pid, cat_mots in index.items():
        trouves, fuzzy = set(), []
        for m in mots:
            if m in cat_mots:
                trouves.add(m)
            elif m.isalpha() and len(m) >= 5:        # faute de frappe ? ('samsun' ~ 'samsung')
                proche = difflib.get_close_matches(m, cat_mots, n=1, cutoff=0.85)
                if proche:
                    trouves.add(proche[0])
                    fuzzy.append((m, proche[0]))
        total = sum(poids(c, marques) for c in cat_mots)
        ok = sum(poids(c, marques) for c in trouves)
        en_trop = sum(poids(m, marques) for m in mots
                      if m not in cat_mots and not any(m == f[0] for f in fuzzy))
        scores.append((ok / (total + 0.5 * en_trop), pid, fuzzy))
    scores.sort(reverse=True)
    (s1, pid1, fz), s2 = scores[0], scores[1][0]
    if s1 >= SEUIL_RAPPROCHEMENT and (s1 - s2) >= MARGE_RAPPROCHEMENT:
        return pid1, s1, fz
    return None, s1, []


def rapprocher_tout(offres: pd.DataFrame, cat: pd.DataFrame, J: Journal) -> pd.DataFrame:
    index, marques = preparer_catalogue(cat)
    pids, scores = [], []
    for r in offres.itertuples():
        pid, s, fuzzy = rapprocher(r.libelle_brut, index, marques)
        for brut, corrige in fuzzy:
            J.add(r.enseigne, r.ref_source, "Faute de frappe", f"« {brut} » reconnu comme « {corrige} »",
                  "corrigé par similarité de chaînes (difflib)")
        if pid is None:
            J.add(r.enseigne, r.ref_source, "Rapprochement impossible", f"« {r.libelle_brut} » (score {s:.2f})",
                  "article ignoré")
        pids.append(pid)
        scores.append(round(s, 2))
    offres = offres.copy()
    offres["produit_id"], offres["score_rapprochement"] = pids, scores
    offres = offres.dropna(subset=["produit_id"])
    # un produit ne doit apparaître qu'une fois par enseigne
    dup = offres.duplicated(["enseigne", "produit_id"], keep=False)
    assert not dup.any(), offres[dup]
    return offres.merge(cat[["produit_id", "nom", "categorie"]], on="produit_id", how="left")


# ==========================================================================
# Contrôles croisés avec l'historique + prix payé + statut final
# ==========================================================================
def controler_avec_historique(offres: pd.DataFrame, hist: pd.DataFrame, J: Journal) -> pd.DataFrame:
    """Compare chaque prix du fichier au prix médian des 28 derniers jours de l'historique.
    - Écart énorme (x10) => faute de saisie : on teste /10 et x10 et on garde la correction
      seulement si elle retombe dans la tolérance de l'historique.
    - Prix manquant => on le signale mais on NE l'invente PAS."""
    recents = hist[hist["date"] >= "2026-10-04"]
    ref = recents.groupby(["source", "produit_id"])["prix_fcfa"].median().rename("prix_ref")
    offres = offres.join(ref, on=["enseigne", "produit_id"])
    for i, r in offres.iterrows():
        if pd.isna(r.prix_ref):
            continue
        if r.prix_affiche is None or pd.isna(r.prix_affiche):
            J.add(r.enseigne, r.ref_source, "Prix de référence (historique)", f"prix du fichier absent ; l'historique donne ~{fcfa(r.prix_ref)} FCFA",
                  "NON utilisé (on n'invente pas un prix) : offre exclue")
            continue
        ratio = r.prix_affiche / r.prix_ref
        if ratio > 2 or ratio < 0.5:
            for nom, cand in (("/10", r.prix_affiche / 10), ("x10", r.prix_affiche * 10)):
                if abs(cand / r.prix_ref - 1) <= TOLERANCE_HISTORIQUE:
                    detail = f"{fcfa(r.prix_affiche)} = {ratio:.1f}x la valeur de l'historique"
                    if r.ancien_prix is not None and not pd.isna(r.ancien_prix):
                        detail += f" et supérieur à l'ancien prix ({fcfa(r.ancien_prix)})"
                    J.add(r.enseigne, r.ref_source, "Prix aberrant (zéro en trop)", detail,
                          f"corrigé en {fcfa(cand)} (confirmé par l'historique ~{fcfa(r.prix_ref)})")
                    offres.at[i, "prix_affiche"] = cand
                    break
            else:
                J.add(r.enseigne, r.ref_source, "Prix aberrant", f"{fcfa(r.prix_affiche)} vs historique {fcfa(r.prix_ref)}",
                      "aucune correction fiable : offre exclue")
                offres.at[i, "prix_affiche"] = np.nan
        elif abs(ratio - 1) > TOLERANCE_HISTORIQUE:
            J.add(r.enseigne, r.ref_source, "Écart avec l'historique",
                  f"{fcfa(r.prix_affiche)} vs ~{fcfa(r.prix_ref)} ({(ratio - 1) * 100:+.1f} %)",
                  "conservé (information)")
    return offres


def calculer_prix_paye(offres: pd.DataFrame) -> pd.DataFrame:
    """Prix PAYÉ par le client, selon la règle de chaque enseigne :
       Marché Lagune : prix affiché (livraison incluse)
       Baobab Shop   : amount + delivery_fee
       Comptoir      : prix catalogue x (1 - remise)  [retrait en boutique, pas de livraison]"""
    o = offres.copy()
    o["prix_affiche"] = pd.to_numeric(o["prix_affiche"], errors="coerce")
    o["prix_paye"] = np.round(o["prix_affiche"] * (1 - o["remise_pct"] / 100) + o["frais_livraison"])
    o["disponible"] = o["statut"].ne("Rupture")
    o["retenue"] = o["disponible"] & o["prix_paye"].notna()

    def motif(r):
        if r.retenue:
            return ""
        return "rupture de stock" if not r.disponible else "prix non exploitable"
    o["motif_exclusion"] = o.apply(motif, axis=1)
    return o


# ==========================================================================
# 4. COMPARATIF
# ==========================================================================
def construire_comparatif(offres: pd.DataFrame) -> pd.DataFrame:
    ret = offres[offres["retenue"]]
    piv = ret.pivot(index="produit_id", columns="enseigne", values="prix_paye").reindex(columns=ENSEIGNES)
    piv["nb_offres"] = piv[ENSEIGNES].notna().sum(axis=1)
    piv = piv[piv["nb_offres"] >= 2].copy()          # au moins deux enseignes
    mini = piv[ENSEIGNES].min(axis=1)
    maxi = piv[ENSEIGNES].max(axis=1)
    piv["moins_cher"] = piv[ENSEIGNES].apply(
        lambda ligne: " / ".join(e for e in ENSEIGNES if ligne[e] == ligne[ENSEIGNES].min()), axis=1)
    piv["prix_min"], piv["prix_max"] = mini, maxi
    piv["ecart_fcfa"] = maxi - mini
    piv["ecart_pct"] = ((maxi - mini) / mini * 100).round(1)

    ecartes = (offres[~offres["retenue"]]
               .assign(txt=lambda d: d["enseigne"] + " (" + d["motif_exclusion"] + ")")
               .groupby("produit_id")["txt"].apply(" ; ".join))
    piv = piv.join(ecartes.rename("offres_ecartees"))
    cat = offres.drop_duplicates("produit_id").set_index("produit_id")[["nom", "categorie"]]
    piv = cat.join(piv, how="inner")
    piv = piv.rename(columns={ML: "prix_marche_lagune", BB: "prix_baobab_shop", CI: "prix_comptoir_ivoire"})
    piv["offres_ecartees"] = piv["offres_ecartees"].fillna("")
    piv.index.name = "produit_id"
    return piv.reset_index()


# ==========================================================================
# 5. SYNTHESE
# ==========================================================================
def synthese(comp: pd.DataFrame, offres: pd.DataFrame):
    cols = {ML: "prix_marche_lagune", BB: "prix_baobab_shop", CI: "prix_comptoir_ivoire"}
    victoires = {e: int(comp["moins_cher"].str.contains(e, regex=False).sum()) for e in ENSEIGNES}
    seul = {e: int((comp["moins_cher"] == e).sum()) for e in ENSEIGNES}
    lignes = []
    for e, c in cols.items():
        sub = comp[comp[c].notna()]
        ecart_fcfa = sub[c] - sub["prix_min"]
        ecart_pct = ecart_fcfa / sub["prix_min"] * 100
        lignes.append(dict(enseigne=e, produits_comparés=len(sub), fois_moins_cher=victoires[e],
                           dont_seule_moins_chère=seul[e],
                           ecart_moyen_pct=round(ecart_pct.mean(), 2), ecart_moyen_fcfa=round(ecart_fcfa.mean())))
    synth = pd.DataFrame(lignes)
    top3 = comp.sort_values("ecart_fcfa", ascending=False).head(3)[
        ["produit_id", "nom", "moins_cher", "prix_min", "prix_max", "ecart_fcfa", "ecart_pct"]]
    return synth, top3


# ==========================================================================
# 6. PANIER
# ==========================================================================
def calculer_panier(offres: pd.DataFrame, cat: pd.DataFrame):
    noms = cat.set_index("produit_id")["nom"]
    ret = offres[offres["retenue"]].set_index(["produit_id", "enseigne"])["prix_paye"]
    par_enseigne = {}
    for e in ENSEIGNES:
        manquants = [p for p in PANIER if (p, e) not in ret.index]
        par_enseigne[e] = None if manquants else sum(ret[(p, e)] * q for p, q in PANIER.items())
    detail = []
    for p, q in PANIER.items():
        prix = {e: ret.get((p, e), np.nan) for e in ENSEIGNES}
        meilleur = min((e for e in ENSEIGNES if not np.isnan(prix[e])), key=lambda e: prix[e])
        detail.append(dict(produit_id=p, article=noms[p], quantite=q, **{e: prix[e] for e in ENSEIGNES},
                           meilleure_enseigne=meilleur, prix_unitaire_min=prix[meilleur],
                           sous_total=prix[meilleur] * q))
    detail = pd.DataFrame(detail)
    mixte = detail["sous_total"].sum()
    return par_enseigne, detail, mixte


# ==========================================================================
# 7. HISTORIQUE
# ==========================================================================
def analyser_historique(hist: pd.DataFrame):
    """Pour comparer des enseignes qui n'ont pas la même fréquence, on passe tout en série
    QUOTIDIENNE : Comptoir Ivoire (1 prix / semaine) est propagé jusqu'au prochain changement
    (forward fill), car son prix reste valable toute la semaine."""
    large = hist.pivot_table(index="date", columns=["source", "produit_id"], values="prix_fcfa")
    large = large.reindex(pd.date_range("2025-11-01", "2026-10-31"))
    large = large.ffill()                      # utile seulement pour Comptoir (les autres sont déjà complets)

    bf = large.loc[BF_DEBUT:BF_FIN].mean()
    annee = large.mean()
    avant = large.loc[BF_DEBUT - pd.Timedelta(days=14):BF_DEBUT - pd.Timedelta(days=1)]
    apres = large.loc[BF_FIN + pd.Timedelta(days=1):BF_FIN + pd.Timedelta(days=14)]
    voisin = pd.concat([avant, apres]).mean()
    debut, fin = large.iloc[2], large.iloc[-1]   # 3 nov : 1er prix connu de Comptoir

    par_produit = pd.DataFrame({
        "prix_moyen_black_friday": bf.round(0), "prix_moyen_annee": annee.round(0),
        "ecart_vs_annee_pct": ((bf / annee - 1) * 100).round(2),
        "ecart_vs_voisinage_pct": ((bf / voisin - 1) * 100).round(2),
        "tendance_annuelle_pct": ((fin / debut - 1) * 100).round(2),
    }).reset_index()
    par_enseigne = par_produit.groupby("source").agg(
        produits=("produit_id", "count"),
        ecart_vs_annee_pct=("ecart_vs_annee_pct", "mean"),
        ecart_vs_voisinage_pct=("ecart_vs_voisinage_pct", "mean"),
        tendance_annuelle_pct=("tendance_annuelle_pct", "mean")).round(2).reset_index()

    # Indice quotidien « détendancé » : prix du jour / médiane glissante centrée de 61 jours.
    # On enlève ainsi la baisse tendancielle de l'année et on ne voit que les PROMOTIONS.
    rel = large / large.rolling(61, center=True, min_periods=30).median() - 1
    indice = rel.T.groupby(level=0).mean().T[ENSEIGNES] * 100

    promos = []
    for e in ENSEIGNES:
        bas = indice[e] <= -1.0                       # au moins 1 % sous la normale
        groupe = (bas != bas.shift()).cumsum()
        for _, bloc in indice[e][bas].groupby(groupe[bas]):
            promos.append(dict(enseigne=e, debut=bloc.index.min().date(), fin=bloc.index.max().date(),
                               jours=len(bloc), baisse_max_pct=round(bloc.min(), 1)))
    promos = pd.DataFrame(promos)

    # Panier : prix AFFICHÉS (sans frais ni remise) pendant le Black Friday vs au 31/10/2026
    lignes = []
    for p, q in PANIER.items():
        bf_p = min(bf[(e, p)] for e in ENSEIGNES if (e, p) in bf.index)
        fin_p = min(fin[(e, p)] for e in ENSEIGNES if (e, p) in fin.index)
        lignes.append((q * bf_p, q * fin_p))
    panier_bf = (sum(a for a, _ in lignes), sum(b for _, b in lignes))
    return large, par_produit, par_enseigne, indice, promos, panier_bf


# ==========================================================================
# 8. COMPLEXITE : benchmark
# ==========================================================================
def chrono(fonction, repetitions=3):
    """Meilleur temps (en secondes) sur `repetitions` exécutions : limite le bruit."""
    meilleur = float("inf")
    for _ in range(repetitions):
        t0 = time.perf_counter()
        resultat = fonction()
        meilleur = min(meilleur, time.perf_counter() - t0)
    return meilleur, resultat


def benchmark(n_requetes=500, graine=42):
    random.seed(graine)
    resultats = []

    # --- A. chargement du CSV de 20 876 lignes
    def charge_csv():
        with open(DATA / "historique_prix.csv", newline="", encoding="utf-8") as f:
            return [(r["date"], r["source"], r["produit_id"], int(r["prix_fcfa"])) for r in csv.DictReader(f)]
    t_csv, lignes = chrono(charge_csv)
    t_pd, h = chrono(lambda: pd.read_csv(DATA / "historique_prix.csv"))
    resultats += [("Chargement", "module csv (liste de tuples)", t_csv, "O(n)"),
                  ("Chargement", "pandas.read_csv", t_pd, "O(n)")]
    n = len(lignes)

    # --- B. « Quel est le prix de (enseigne, produit, date) ? »  x n_requetes
    requetes = random.sample(lignes, n_requetes)
    cles = [(s, p, d) for d, s, p, _ in requetes]

    def recherche_lineaire():                         # O(n) par requête -> O(n.q)
        total = 0
        for s, p, d in cles:
            for ld, ls, lp, prix in lignes:
                if ld == d and ls == s and lp == p:
                    total += prix
                    break
        return total

    def recherche_pandas():                           # filtre booléen : O(n) par requête (vectorisé)
        total = 0
        for s, p, d in cles:
            total += int(h.loc[(h["date"] == d) & (h["source"] == s) & (h["produit_id"] == p), "prix_fcfa"].iloc[0])
        return total

    def construire_dict():                            # construction une seule fois : O(n)
        return {(s, p, d): prix for d, s, p, prix in lignes}
    t_build, index = chrono(construire_dict)

    def recherche_dict():                             # O(1) par requête -> O(q)
        return sum(index[k] for k in cles)

    t_lin, r1 = chrono(recherche_lineaire, 1)
    t_pdq, r2 = chrono(recherche_pandas, 1)
    t_dic, r3 = chrono(recherche_dict, 5)
    assert r1 == r2 == r3, "les trois méthodes doivent donner le même total"
    resultats += [(f"{n_requetes} recherches exactes", "balayage de la liste", t_lin, "O(n·q)"),
                  (f"{n_requetes} recherches exactes", "filtre pandas", t_pdq, "O(n·q)"),
                  (f"{n_requetes} recherches exactes", "dictionnaire (+ construction)", t_dic + t_build, "O(n + q)"),
                  (f"{n_requetes} recherches exactes", "dictionnaire (recherche seule)", t_dic, "O(q)")]

    # --- C. « Prix en vigueur à une date quelconque » (Comptoir : 1 prix par semaine)
    series = {}
    for d, s, p, prix in sorted(lignes):
        series.setdefault((s, p), ([], []))
        series[(s, p)][0].append(d)
        series[(s, p)][1].append(prix)
    cles_ci = [(CI, p) for (s, p) in series if s == CI]
    jours = [str(d.date()) for d in pd.date_range("2025-11-03", "2026-10-31")]
    q_asof = [(random.choice(cles_ci), random.choice(jours)) for _ in range(n_requetes)]

    def asof_bisect():                                # O(log m) par requête, m = 53 points
        tot = 0
        for k, d in q_asof:
            dates, prix = series[k]
            tot += prix[bisect.bisect_right(dates, d) - 1]
        return tot

    def asof_balayage():                              # O(m) par requête
        tot = 0
        for k, d in q_asof:
            dates, prix = series[k]
            dernier = None
            for dd, pp in zip(dates, prix):
                if dd <= d:
                    dernier = pp
                else:
                    break
            tot += dernier
        return tot
    t_bi, a1 = chrono(asof_bisect, 5)
    t_ba, a2 = chrono(asof_balayage, 3)
    assert a1 == a2
    resultats += [(f"{n_requetes} « prix à la date D »", "balayage séquentiel", t_ba, "O(m·q)"),
                  (f"{n_requetes} « prix à la date D »", "listes triées + bisect", t_bi, "O(q·log m)")]

    # --- D. Agrégation : prix moyen par (enseigne, produit) sur la semaine du Black Friday
    d0, d1 = str(BF_DEBUT.date()), str(BF_FIN.date())

    def agreg_boucle():
        somme, nb = {}, {}
        for d, s, p, prix in lignes:
            if d0 <= d <= d1:
                somme[(s, p)] = somme.get((s, p), 0) + prix
                nb[(s, p)] = nb.get((s, p), 0) + 1
        return {k: somme[k] / nb[k] for k in somme}

    hd = h.assign(date=pd.to_datetime(h["date"]))

    def agreg_pandas():
        m = (hd["date"] >= BF_DEBUT) & (hd["date"] <= BF_FIN)
        return hd[m].groupby(["source", "produit_id"])["prix_fcfa"].mean()
    t_ab, g1 = chrono(agreg_boucle)
    t_ap, g2 = chrono(agreg_pandas)
    assert abs(g1[(ML, "P01")] - g2[(ML, "P01")]) < 1e-6
    resultats += [("Agrégation Black Friday", "boucle Python + dict", t_ab, "O(n)"),
                  ("Agrégation Black Friday", "pandas groupby", t_ap, "O(n)")]

    return pd.DataFrame(resultats, columns=["tâche", "méthode", "secondes", "complexité"]), n


# ==========================================================================
# Graphiques
# ==========================================================================
def style():
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.alpha": .25, "axes.axisbelow": True,
                         "figure.dpi": 130, "savefig.bbox": "tight"})


def graphique_synthese(synth):
    fig, ax = plt.subplots(1, 2, figsize=(10, 4))
    c = [COULEURS[e] for e in synth["enseigne"]]
    ax[0].bar(synth["enseigne"], synth["fois_moins_cher"], color=c)
    ax[0].set_title("Nombre de fois où l'enseigne est la moins chère")
    for i, v in enumerate(synth["fois_moins_cher"]):
        ax[0].text(i, v + .2, str(v), ha="center", fontweight="bold")
    ax[1].bar(synth["enseigne"], synth["ecart_moyen_pct"], color=c)
    ax[1].set_title("Écart moyen au prix le plus bas (%)")
    for i, v in enumerate(synth["ecart_moyen_pct"]):
        ax[1].text(i, v + .1, f"{v:.1f} %", ha="center", fontweight="bold")
    fig.tight_layout()
    fig.savefig(FIG / "01_synthese.png")
    plt.close(fig)


def graphique_panier(par_enseigne, mixte):
    etiquettes = list(ENSEIGNES) + ["Meilleur prix\nà chaque article"]
    vals = [par_enseigne[e] or 0 for e in ENSEIGNES] + [mixte]
    cols = [COULEURS[e] for e in ENSEIGNES] + ["#7B2D8E"]
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(etiquettes, vals, color=cols)
    for i, v in enumerate(vals):
        ax.text(i, v + 1500, f"{fcfa(v)}", ha="center", fontweight="bold")
    ax.set_ylim(min(vals) * 0.8, max(vals) * 1.05)
    ax.set_title("Panier de rentrée (6 articles) : coût total en FCFA")
    fig.savefig(FIG / "02_panier.png")
    plt.close(fig)


def graphique_historique(large, pid="P04", titre="Tecno Spark 20"):
    fig, ax = plt.subplots(figsize=(10, 4))
    for e in ENSEIGNES:
        if (e, pid) in large.columns:
            ax.plot(large.index, large[(e, pid)], label=e, color=COULEURS[e], lw=1.6)
    ax.axvspan(BF_DEBUT, BF_FIN, color="gold", alpha=.35, label="Black Friday 2025")
    ax.set_title(f"Prix affiché au fil de l'année — {titre}")
    ax.set_ylabel("FCFA")
    ax.legend()
    fig.savefig(FIG / "03_historique_p04.png")
    plt.close(fig)


def graphique_black_friday(par_enseigne):
    fig, ax = plt.subplots(figsize=(9, 4))
    x = np.arange(len(par_enseigne))
    w = 0.38
    ax.bar(x - w / 2, par_enseigne["ecart_vs_annee_pct"], w, label="vs moyenne de l'année", color="#999999")
    ax.bar(x + w / 2, par_enseigne["ecart_vs_voisinage_pct"], w, label="vs 2 semaines avant/après", color="#C0392B")
    ax.set_xticks(x, par_enseigne["source"])
    ax.axhline(0, color="black", lw=.8)
    ax.set_ylim(par_enseigne[["ecart_vs_annee_pct", "ecart_vs_voisinage_pct"]].min().min() - 2.5,
                par_enseigne[["ecart_vs_annee_pct", "ecart_vs_voisinage_pct"]].max().max() + 2)
    ax.set_title("Semaine du Black Friday : écart de prix moyen (%)")
    ax.legend()
    for i, (a, b) in enumerate(zip(par_enseigne["ecart_vs_annee_pct"], par_enseigne["ecart_vs_voisinage_pct"])):
        ax.text(i - w / 2, a + (.3 if a >= 0 else -1.0), f"{a:+.1f}", ha="center", fontsize=9)
        ax.text(i + w / 2, b + (.3 if b >= 0 else -1.0), f"{b:+.1f}", ha="center", fontsize=9)
    fig.savefig(FIG / "04_black_friday.png")
    plt.close(fig)


def graphique_indice(indice):
    fig, ax = plt.subplots(figsize=(10, 4))
    for e in ENSEIGNES:
        ax.plot(indice.index, indice[e], label=e, color=COULEURS[e], lw=1.6)
    ax.axhline(0, color="black", lw=.8)
    ax.set_title("Promotions : écart du prix à sa médiane glissante de 61 jours (moyenne des produits, %)")
    ax.set_ylabel("%")
    ax.legend()
    fig.savefig(FIG / "05_promotions.png")
    plt.close(fig)


def graphique_benchmark(bench):
    b = bench[bench["tâche"].str.contains("recherches|prix à la date|Agrégation")].copy()
    b["label"] = b["tâche"].str.replace(" ", "\n", n=1) + "\n" + b["méthode"]
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.bar(range(len(b)), b["secondes"] * 1000, color="#34495E")
    ax.set_yscale("log")
    ax.set_xticks(range(len(b)), [m.replace(" ", "\n", 2) for m in b["méthode"]], fontsize=8)
    ax.set_ylabel("millisecondes (échelle log)")
    ax.set_title("Benchmark : choix de structure de données (500 requêtes sur 20 876 lignes)")
    fig.savefig(FIG / "06_benchmark.png")
    plt.close(fig)


# ==========================================================================
# PROGRAMME PRINCIPAL
# ==========================================================================
def titre(txt):
    print("\n" + "=" * 78 + f"\n{txt}\n" + "=" * 78)


def main(avec_benchmark=True):
    t_global = time.perf_counter()
    style()
    OUT.mkdir(exist_ok=True)
    FIG.mkdir(exist_ok=True)
    J = Journal()

    # 1-2. chargement + nettoyage ------------------------------------------
    titre("1-2. CHARGEMENT ET NETTOYAGE")
    cat = pd.read_csv(DATA / "catalogue_reference.csv")
    hist = pd.read_csv(DATA / "historique_prix.csv", parse_dates=["date"])
    offres = pd.concat([charger_marche_lagune(J), charger_baobab(J), charger_comptoir(J)], ignore_index=True)
    print(f"{len(offres)} lignes chargées : " + ", ".join(f"{e}={n}" for e, n in offres['enseigne'].value_counts().items()))

    # 3. rapprochement -------------------------------------------------------
    titre("3. RAPPROCHEMENT AVEC LE CATALOGUE")
    offres = rapprocher_tout(offres, cat, J)
    print(f"{len(offres)} articles rapprochés ; score min = {offres['score_rapprochement'].min():.2f}")
    offres = controler_avec_historique(offres, hist, J)
    offres = calculer_prix_paye(offres)
    colonnes = ["enseigne", "ref_source", "libelle_brut", "produit_id", "nom", "categorie", "score_rapprochement",
                "prix_affiche", "remise_pct", "frais_livraison", "prix_paye", "statut", "disponible", "retenue",
                "motif_exclusion", "mode", "note", "nb_avis", "date_maj"]
    offres = offres[colonnes].sort_values(["produit_id", "enseigne"]).reset_index(drop=True)
    offres.to_csv(OUT / "offres_nettoyees.csv", index=False)
    offres[["enseigne", "ref_source", "libelle_brut", "produit_id", "nom", "score_rapprochement"]] \
        .to_csv(OUT / "rapprochement.csv", index=False)
    jdf = J.to_df()
    jdf.to_csv(OUT / "journal_nettoyage.csv", index=False)
    print(f"Journal : {len(jdf)} entrées")
    print(jdf.groupby("probleme").size().sort_values(ascending=False).to_string())

    # 4. comparatif ----------------------------------------------------------
    titre("4. COMPARATIF DES PRIX (prix payé, offres disponibles uniquement)")
    comp = construire_comparatif(offres)
    comp.to_csv(OUT / "comparatif_prix.csv", index=False)
    print(f"{len(comp)} produits disponibles dans au moins 2 enseignes")
    print(comp[["produit_id", "nom", "prix_marche_lagune", "prix_baobab_shop", "prix_comptoir_ivoire",
                "moins_cher", "ecart_fcfa", "ecart_pct"]].to_string(index=False))

    # 5. synthèse ------------------------------------------------------------
    titre("5. SYNTHESE")
    synth, top3 = synthese(comp, offres)
    synth.to_csv(OUT / "synthese_enseignes.csv", index=False)
    top3.to_csv(OUT / "top3_ecarts.csv", index=False)
    print(synth.to_string(index=False))
    print("\nTop 3 des produits où comparer rapporte le plus :")
    print(top3.to_string(index=False))

    # 6. panier --------------------------------------------------------------
    titre("6. PANIER DE RENTREE")
    par_ens, detail, mixte = calculer_panier(offres, cat)
    detail.to_csv(OUT / "panier_detail.csv", index=False)
    print(detail.to_string(index=False))
    for e, v in par_ens.items():
        print(f"  Tout chez {e:<16}: {fcfa(v)} FCFA")
    meilleur_unique = min(v for v in par_ens.values() if v)
    print(f"  Meilleur prix article par article : {fcfa(mixte)} FCFA "
          f"(économie de {fcfa(meilleur_unique - mixte)} FCFA, {(meilleur_unique - mixte) / meilleur_unique * 100:.1f} %"
          f" vs meilleure enseigne unique)")
    pd.DataFrame([{"scenario": f"Tout chez {e}", "total_fcfa": v} for e, v in par_ens.items()] +
                 [{"scenario": "Meilleur prix article par article", "total_fcfa": mixte}]) \
        .to_csv(OUT / "panier_totaux.csv", index=False)

    # 7. historique ----------------------------------------------------------
    titre("7. HISTORIQUE : QUAND ACHETER ?")
    large, par_prod, par_ens_h, indice, promos, panier_bf = analyser_historique(hist)
    par_prod.to_csv(OUT / "black_friday_par_produit.csv", index=False)
    par_ens_h.to_csv(OUT / "black_friday_synthese.csv", index=False)
    promos.to_csv(OUT / "periodes_promotion.csv", index=False)
    print(par_ens_h.to_string(index=False))
    print("\nPériodes de promotion détectées (prix >= 1 % sous la normale) :")
    print(promos.to_string(index=False))
    bf_tot, fin_tot = panier_bf
    print(f"\nPanier (prix affichés, meilleure enseigne par article) : Black Friday {fcfa(bf_tot)} FCFA"
          f" vs 31/10/2026 {fcfa(fin_tot)} FCFA -> {fcfa(fin_tot - bf_tot)} FCFA d'écart ({(bf_tot / fin_tot - 1) * 100:+.1f} %)")

    # graphiques -------------------------------------------------------------
    graphique_synthese(synth)
    graphique_panier(par_ens, mixte)
    graphique_historique(large)
    graphique_black_friday(par_ens_h)
    graphique_indice(indice)

    # 8. complexité ----------------------------------------------------------
    if avec_benchmark:
        titre("8. COMPLEXITE : BENCHMARK")
        bench, n = benchmark()
        bench["millisecondes"] = (bench["secondes"] * 1000).round(3)
        bench.to_csv(OUT / "benchmark.csv", index=False)
        print(f"n = {n} lignes dans l'historique")
        print(bench[["tâche", "méthode", "millisecondes", "complexité"]].to_string(index=False))
        graphique_benchmark(bench)

    duree = time.perf_counter() - t_global
    titre(f"TERMINE en {duree:.1f} s — résultats dans {OUT}")


if __name__ == "__main__":
    # Console Windows : forcer l'UTF-8 pour que les accents s'affichent correctement
    for flux in (sys.stdout, sys.stderr):
        if hasattr(flux, "reconfigure"):
            flux.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-bench", action="store_true", help="ne pas lancer le benchmark")
    main(avec_benchmark=not ap.parse_args().no_bench)
