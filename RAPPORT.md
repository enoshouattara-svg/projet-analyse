# Analyse comparative de marché — Rapport

**DA Python · L2 Computer Science · séance 3**
Enseignes : Marché Lagune (site), Baobab Shop (appli), Comptoir Ivoire (boutique d'Adjamé). Données fictives.

## 0. Lancer le projet

```bash
pip install pandas numpy matplotlib openpyxl
python analyse_marche.py            # tout, benchmark compris (≈ 2,5 s)
python analyse_marche.py --no-bench # sans le benchmark
```

Le script lit `data/`, écrit les tableaux dans `resultats/` et les graphiques dans `resultats/graphiques/`.

| Fichier produit | Contenu |
|---|---|
| `journal_nettoyage.csv` | tous les problèmes détectés et l'action menée (34 entrées) |
| `rapprochement.csv` | article brut → `produit_id` + score de confiance |
| `offres_nettoyees.csv` | les 76 offres, prix payé, statut, motif d'exclusion |
| `comparatif_prix.csv` | **le comparatif demandé** (23 produits) |
| `synthese_enseignes.csv`, `top3_ecarts.csv` | synthèse |
| `panier_detail.csv`, `panier_totaux.csv` | panier de rentrée |
| `black_friday_*.csv`, `periodes_promotion.csv` | historique |
| `benchmark.csv` | mesures de temps |

## 1. Architecture du code

Une fonction par étape de l'énoncé, appelées dans l'ordre par `main()` :

`charger_*` (1+2) → `rapprocher_tout` (3) → `controler_avec_historique` → `calculer_prix_paye` → `construire_comparatif` (4) → `synthese` (5) → `calculer_panier` (6) → `analyser_historique` (7) → `benchmark` (8).

Structure commune : **un seul DataFrame `offres`**, une ligne par article d'une enseigne, avec les mêmes colonnes quelle que soit la source (`enseigne`, `libelle_brut`, `prix_affiche`, `frais_livraison`, `remise_pct`, `statut`…). C'est ce qui rend le reste du code indépendant du format d'origine.

## 2. Nettoyage : ce qui n'allait pas (journal complet dans le CSV)

| Source | Problème | Traitement |
|---|---|---|
| Marché Lagune | BOM UTF-8, `;`, virgule décimale | `encoding="utf-8-sig"`, `sep=";"` |
| | 2 doublons exacts (ML-1000, ML-1147) | supprimés |
| | prix en texte avec **espaces fines insécables** (U+202F) et « FCFA » | `parse_prix` : on ne garde que les chiffres |
| | **779 000 FCFA** pour le Tecno Spark 20 (ML-1021) | zéro en trop : > 9× l'historique et > ancien prix (88 700). Corrigé en **77 900**, confirmé par l'historique (≈ 78 500) |
| | « Prix sur demande » (écran Samsung), prix vide (mixeur) | prix absent → offre exclue |
| | désignation en minuscules avec espaces parasites | `strip()` + normalisation |
| | 6 ruptures de stock | exclues du « moins cher » |
| Baobab Shop | `amount = null` (fer Philips) | exclu ; l'historique donne ≈ 14 300 mais **on n'invente pas** un prix |
| | 3 articles `stock = 0` | exclus |
| | 8 articles vendus par un « Partenaire vérifié » | conservés (information) |
| Comptoir Ivoire | titre en ligne 1, en-têtes en ligne 3 | `header=2` |
| | prix de la clim LG stocké **en texte** (`'279 300'`) | converti |
| | « Samsun » (faute), noms abrégés (« DD », « Clim », « Frigo ») | rapprochement tolérant (cf. §3) |
| | 2 ruptures (TV Samsung 43", ventilateur) | exclues |
| | 5 prix mis à jour il y a 28 jours | conservés, signalés |

**Prix payé** (règle de l'énoncé) :
Marché Lagune = prix affiché (livraison incluse) · Baobab = `amount + delivery_fee` · Comptoir = `prix catalogue × (1 − remise)`.

## 3. Rapprochement : comment ça marche

Les trois enseignes décrivent le même produit très différemment (« Galaxy A15 128GB - Samsung », « SAMSUNG GALAXY A15 (128GB) », « Samsun Galaxy A15 128Go »). Méthode :

1. **Normaliser** : minuscules, sans accents, ponctuation → espaces, décimale `1,5`→`1.5`, unités unifiées (`128 Go`/`128GB`→`128gb`, `1HP`→`1cv`, `24"`→`24in`), synonymes anglais→français (fridge→réfrigérateur, kettle→bouilloire…).
2. **Noter** chaque produit du catalogue : somme des poids des mots retrouvés / poids total. Un mot avec chiffre (`a15`, `128gb`, `205l`) pèse 3 car il **identifie** le produit ; une marque 2 ; un mot courant 1. Les fautes de frappe sont rattrapées avec `difflib` (« samsun » ≈ « samsung »).
3. **Accepter** si score ≥ 0,45 **et** avance d'au moins 0,10 sur le 2ᵉ candidat. Sinon l'article est ignoré et journalisé (jamais de choix au hasard).

Résultat : **76/76 articles rapprochés**, score minimum 0,50, aucun doublon par enseigne (vérifié par `assert`).
**Validation indépendante** : le prix de chaque article est comparé à l'historique (qui, lui, a déjà les `produit_id`). Après correction du zéro en trop, aucun écart > 3 % : cela prouve que les 76 rapprochements sont corrects.

## 4. Comparatif

23 produits sont disponibles dans au moins 2 enseignes (`comparatif_prix.csv`). Écart = prix max − prix min parmi les offres **disponibles avec prix valide** ; en % : écart / prix min. En cas d'égalité (souris Logitech, fer Philips) les deux enseignes sont indiquées.

## 5. Synthèse

| Enseigne | Produits comparés | Fois la moins chère | Seule moins chère | Écart moyen au minimum |
|---|---|---|---|---|
| Comptoir Ivoire | 18 | **10** | 8 | **2,8 %** (6 667 F) |
| Baobab Shop | 20 | 9 | 9 | 4,7 % (2 702 F) |
| Marché Lagune | 19 | 6 | 4 | 3,8 % (7 771 F) |

Lecture : Comptoir gagne le plus souvent et a l'écart moyen le plus faible. Baobab gagne presque aussi souvent mais, quand il perd, il perd plus (surtout sur les petits prix où ses 1 500 F de livraison pèsent : clé USB +19,7 %). Marché Lagune est rarement le meilleur choix.

**Top 3 des gains à comparer** : HP 250 G9 (**52 800 F**, 14,9 %, Baobab 354 200 vs Comptoir 407 000) · iPhone 13 (26 500 F, 6,4 %) · Climatiseur LG 1 CV (26 000 F, 10,3 %).

## 6. Panier de rentrée (Spark 20, IdeaPad 3, 2× clé USB, Seagate 1 To, micro-ondes)

| Scénario | Total |
|---|---|
| Tout chez Marché Lagune | 504 300 F |
| Tout chez Baobab Shop | 491 500 F |
| Tout chez Comptoir Ivoire | 484 075 F |
| **Meilleur prix article par article** | **477 575 F** |

Acheter au meilleur endroit fait économiser 6 500 F (1,3 %) sur la meilleure enseigne unique et 26 725 F sur la plus chère. Le détail article par article est dans `panier_detail.csv`.
*Hypothèses* : les frais Baobab s'appliquent **par article** (la clé USB ×2 paie 2 × 1 500) ; le retrait à Adjamé n'inclut pas le coût de transport du client ; le gain de 6 500 F est à mettre en balance avec le fait de passer par 3 enseignes.

## 7. Historique : quand acheter ?

| Enseigne | Black Friday vs moyenne annuelle | Black Friday vs 2 semaines avant/après | Tendance sur l'année |
|---|---|---|---|
| Baobab Shop | −11,7 % | **−15,0 %** | −7,9 % |
| Marché Lagune | −11,3 % | **−15,0 %** | −9,0 % |
| Comptoir Ivoire | **+3,7 %** | −0,0 % | −8,0 % |

- **Piège à comprendre** : tous les prix baissent d'environ 8 % sur l'année. Comparer à la *moyenne annuelle* donne donc +3,7 % pour Comptoir alors qu'il n'a **aucune promotion** (−0,0 % face aux semaines voisines). Le vrai effet Black Friday se lit contre le voisinage : **−15 % chez Marché Lagune et Baobab**, rien chez Comptoir.
- Deuxième période de promo, plus faible : **1–20 septembre 2026** (−2,6 % Marché Lagune/Baobab, −2,1 % Comptoir du 7 au 20).
- Pour le panier (prix affichés, meilleure enseigne par article) : 446 329 F pendant le Black Friday contre 483 000 F au 31/10/2026, soit **−7,6 %** (≈ 36 700 F). Il fallait donc acheter la semaine du 24 au 30 novembre 2025, chez Marché Lagune ou Baobab.
- Comptoir ne change ses prix qu'une fois par semaine : sa série a été **propagée jour par jour** (forward fill), ce qui est exact car le prix reste valable jusqu'au changement.
- *Limite* : l'historique contient le prix **affiché** (sans frais Baobab ni remise Comptoir), pas le prix payé.

## 8. Complexité et choix de structures de données

Mesures sur 20 876 lignes, 500 requêtes (`benchmark.csv`, graphique `06_benchmark.png`) :

| Tâche | Méthode | Temps | Complexité |
|---|---|---|---|
| Chargement | module `csv` → liste de tuples | 24 ms | O(n) |
| Chargement | `pandas.read_csv` | 8 ms | O(n) |
| 500 prix (enseigne, produit, date) | balayage de la liste | 98 ms | O(n·q) |
| idem | filtre booléen pandas | 1 142 ms | O(n·q) |
| idem | **dictionnaire** (construction 2,4 ms) | **0,03 ms** la recherche | O(n) + O(1)/requête |
| 500 « prix en vigueur à la date D » | balayage séquentiel | 0,42 ms | O(m·q) |
| idem | **listes triées + `bisect`** | 0,09 ms | O(q·log m) |
| Moyenne Black Friday | boucle + dict / `groupby` | 0,7 / 1,0 ms | O(n) |

**Ce qu'il faut retenir et dire à l'oral :**
- Pour des **recherches répétées**, on construit **une fois** un index `dict` clé→valeur (O(n)), puis chaque recherche est O(1) en moyenne (table de hachage). Gain ≈ ×3 000 par rapport au balayage. Si on ne cherche qu'une fois, le balayage suffit : l'index n'est rentable qu'au-delà de quelques requêtes.
- pandas est excellent pour **charger et agréger** (vectorisé, en C) mais **mauvais pour des recherches ponctuelles en boucle** (chaque filtre rescanne tout le tableau et crée des objets intermédiaires) : 12× plus lent que le balayage naïf ici.
- Pour « le prix valable à une date » (Comptoir, un prix par semaine) : tableau **trié** + recherche dichotomique `bisect` en O(log m). Ici m = 53 points, donc le gain absolu est minuscule ; il deviendrait important pour des séries longues.
- Le rapprochement coûte O(articles × catalogue × mots) ≈ 76 × 30 × 6 : négligeable. Le programme complet tourne en ~2,4 s.

## 9. Questions probables à l'oral

- **Pourquoi ne pas utiliser le prix de l'historique pour combler les prix manquants ?** Parce que c'est un prix *passé* ; l'offre actuelle n'a pas de prix exploitable, l'énoncé interdit de la retenir.
- **Pourquoi corriger 779 000 en 77 900 ?** Trois indices concordants : ordre de grandeur ×10, supérieur à l'ancien prix barré, et 77 900 est dans la tolérance de l'historique.
- **Pourquoi le seuil 0,45 et la marge 0,10 ?** Réglés pour qu'aucun article ne soit ambigu ; la vérification par l'historique confirme qu'il n'y a aucun faux rapprochement.
- **Limites** : données fictives, un seul instantané (31/10/2026), frais Baobab supposés par article, transport vers Adjamé ignoré.
