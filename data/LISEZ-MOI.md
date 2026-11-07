# Analyse comparative de marché — données de l'exercice

**DA Python · L2 Computer Science · séance 3**

> Toutes les données sont **fictives** et ont été créées pour cet exercice. Les enseignes Marché Lagune,
> Baobab Shop et Comptoir Ivoire n'existent pas, et les prix ne correspondent à aucun magasin réel.

## Le contexte

Un client veut acheter de l'électronique et de l'électroménager à Abidjan. Il hésite entre trois enseignes :

| Enseigne | Type | Fichier fourni | Format |
|---|---|---|---|
| Marché Lagune | site marchand | `marche_lagune.csv` | CSV, séparateur `;`, export « Excel français » |
| Baobab Shop | application mobile | `baobab_shop.json` | JSON renvoyé par l'API de l'application |
| Comptoir Ivoire | boutique d'Adjamé | `comptoir_ivoire.xlsx` | classeur Excel tenu par le gérant |

Votre programme doit **collecter** les trois sources, les **rapprocher** d'un catalogue commun, **comparer** les prix
et **aider à décider** où acheter.

## Les fichiers

### `catalogue_reference.csv` : 30 produits, la référence commune
| Colonne | Contenu |
|---|---|
| `produit_id` | identifiant unique, de P01 à P30 |
| `nom` | nom complet du produit |
| `categorie` | Smartphone, Informatique ou Électroménager |
| `marque` | marque |

Chaque enseigne écrit les noms à sa façon : c'est à vous de retrouver quel article correspond à quel `produit_id`.

### `marche_lagune.csv`
`reference` · `designation` · `prix` (texte, par exemple `102 900 FCFA`) · `ancien_prix` (prix barré, souvent vide) ·
`disponibilite` (`En stock`, `Stock limité`, `Rupture`) · `note_clients` (virgule décimale) · `nb_avis`.
Le prix affiché inclut la livraison.

### `baobab_shop.json`
Un objet avec `items`, une liste d'articles : `sku`, `title`, `pricing` (`amount` en FCFA, `currency`, `delivery_fee`),
`stock` (quantité disponible), `seller`, `rating` (`average`, `count`).
Le client paie `amount` + `delivery_fee`.

### `comptoir_ivoire.xlsx`
Feuille « Tarifs octobre 2026 » : un titre en ligne 1, les en-têtes en ligne 3, les données à partir de la ligne 4.
Colonnes : `Code` · `Article` · `Rayon` · `Prix catalogue (FCFA)` · `Remise (%)` · `Quantité en rayon` · `Date de mise à jour`.
Le client paie le prix catalogue diminué de la remise, et vient chercher l'article en boutique.

### `historique_prix.csv` : 20 876 lignes
Prix affiché chaque jour du 01/11/2025 au 31/10/2026 : `date` (AAAA-MM-JJ) · `source` · `produit_id` · `prix_fcfa`.
Les produits y sont déjà identifiés par leur `produit_id`. Comptoir Ivoire ne change ses prix qu'une fois par semaine :
il a donc moins de lignes. Pour Comptoir Ivoire, c'est le prix catalogue, sans la remise.

## Ce que votre programme doit produire

1. **Chargement** : lire les trois fichiers d'enseignes (CSV, JSON, Excel) dans une même structure de données.
2. **Nettoyage** : comme toujours avec des données réelles, les fichiers ne sont pas propres. À vous de repérer les
   problèmes, de les traiter et de **les lister dans un journal**.
3. **Rapprochement** : associer chaque article à un `produit_id` du catalogue.
4. **Comparatif** : pour chaque produit disponible dans au moins deux enseignes, donner le prix payé chez chacune,
   l'enseigne la moins chère et l'écart en FCFA et en %. Exporter le tableau en CSV.
5. **Synthèse** :
   - combien de fois chaque enseigne est-elle la moins chère ?
   - quel est l'écart moyen de chaque enseigne par rapport au prix le plus bas ?
   - quels sont les trois produits où il y a le plus à gagner à comparer ?
6. **Panier** : le panier de rentrée contient 1 Tecno Spark 20 (P04), 1 Lenovo IdeaPad 3 (P12), 2 clés USB SanDisk (P14),
   1 disque dur Seagate (P15) et 1 micro-ondes Samsung (P28). Combien coûte-t-il dans chaque enseigne ?
   Et en achetant chaque article là où il est le moins cher ?
7. **Historique** : quand fallait-il acheter ? Comparez, pour chaque enseigne, les prix de la semaine du Black Friday
   (24 au 30 novembre 2025) au prix moyen de l'année.
8. **Complexité** : votre programme cherche des prix dans un historique de plus de 20 000 lignes. Mesurez le temps
   d'exécution et expliquez vos choix de structures de données.

Un produit en rupture de stock, ou sans prix exploitable, ne doit pas être retenu comme « le moins cher ».
