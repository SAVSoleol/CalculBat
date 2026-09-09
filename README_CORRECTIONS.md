# Calculateur de batterie — version corrigée du 9 septembre 2026

Cette livraison remplace les **huit modules Python ensemble**. Elle intègre les corrections de l'audit et un SOC minimum réglable dans les trois modes. Le vieillissement et les consommations auxiliaires supplémentaires sont exclus conformément à la demande. Les pertes de conversion liées au rendement aller-retour restent calculées.

## Installation

1. Décompresser l'archive dans un dossier de travail et conserver une copie de la version précédente.
2. Placer les huit fichiers `.py` au même niveau, avec leurs noms exacts : `app.py`, `loaders.py`, `simulation.py`, `recommend.py`, `energy_dashboard.py`, `grd_profiles.py`, `i18n.py`, `report.py`.
3. Installer les dépendances, puis lancer le programme :

```sh
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

L'environnement vérifié utilise Python 3.12. Les versions des dépendances directes sont fournies. Si l'ancien paquet `fpdf` est présent, le retirer avant de réinstaller `fpdf2` : les deux paquets occupent le même nom d'import Python.

`logo_soleol.png` et `Schema.png` sont facultatifs. Conserver ces images à côté de `report.py` pour les inclure. Elles n'ont pas été fournies et ne sont pas dans l'archive ; le PDF fonctionne sans elles. Les polices du PDF proviennent de Matplotlib et sont incorporées au document.

Les API internes ont été simplifiées : éviter de mélanger un module corrigé avec les autres modules de l'ancienne version. Les anciens README décrivant le SOC fixe, Swissolar ou le Peak Shaving ne décrivent plus cette version.

## Réglages à connaître

- **SOC minimum** : réglable de 0 à 95 %, par pas de 1 %, dans chaque mode. Valeurs initiales : 5 % en résidentiel et PME ; 30 % en C&I, en conservant la précédente limite d'autoconsommation. La plage utilisable est `[SOC minimum, 100 %]`. Adapter cette limite à la fiche technique du matériel.
- **Capacité utile** : capacité nominale × `(1 − SOC minimum / 100)`. À 20 kWh et 30 %, la simulation utilise 14 kWh. Le stock initial utilisable vaut zéro : le SOC commence au minimum choisi.
- **Courbe active** : les fichiers de deux clients se sélectionnent séparément. La combinaison exige des périodes du même point de mesure. Les contenus répétés et les périodes qui se chevauchent sont refusés.
- **Horodatage** : préciser début ou fin d'intervalle. Le réglage initial « fin » correspond à l'interprétation retenue pour les deux exports fournis, à confirmer avec leur exporteur. Les index cumulés Huawei sont affectés à la fin de l'intervalle entre lectures.
- **Tarifs** : les montants sont des préremplissages à vérifier sur le contrat. L'année tarifaire est séparée de l'année de mesure. Le scénario unique applique les mêmes paramètres aux dates de la courbe source ; le calendrier permet des changements de prix et horaires à des dates précises. Fin de période exclue, couverture sans trous ni chevauchements.
- **Coût installé** : facultatif, renseigné pour la configuration étudiée. Zéro signifie absent. Aucun coût fixe ni prix par kWh caché n'est appliqué.
- **PDF** : cliquer sur « Préparer le rapport PDF », puis télécharger. Toute modification de l'étude invalide le rapport préparé ; les seules modifications de l'affichage des graphiques ne changent pas le dimensionnement.

## Données manquantes et changements d'heure

Les dates sont conservées avec fuseau : chronologie physique UTC, affichage et tarifs en `Europe/Zurich`. Une journée de printemps peut contenir 92 quarts d'heure, une journée d'automne 100. Les deux occurrences de l'heure d'automne restent distinctes lorsque l'export les fournit.

Si l'export ne contient qu'une occurrence d'une heure ambiguë, le chargement le signale. Le choix « première occurrence (été) » ou « seconde occurrence (hiver) » constitue une hypothèse explicite ; il ne reconstitue pas une mesure. Les heures locales inexistantes au printemps ne sont jamais décalées automatiquement.

Dans le fichier résidentiel fourni, les 100 lignes « Manquant » correspondent, avec l'hypothèse de fin d'intervalle, à **03.11.2025 00:00 → 04.11.2025 01:00**, soit 25 heures. Avec le choix « première occurrence (été) », l'absence de deuxième heure d'automne représente quatre autres intervalles sur la chronologie physique. Ces deux catégories sont présentées séparément dans le contrôle de qualité. Le fichier C&I fourni contient les deux occurrences et n'a pas de trou de mesure identifié.

Trois traitements sont disponibles :

| Choix | Comportement |
|---|---|
| Attendre des données complètes | Aucun dimensionnement n'est lancé tant qu'il reste des trous. |
| Calculer les segments mesurés | Les trous restent vides. Chaque segment repart au SOC minimum. Le stock final du segment précédent est comptabilisé comme non transféré, séparément des pertes de conversion. |
| Estimer par jours comparables | Médiane des mesures du même jour de semaine et du même horaire dans les 28 jours avant/après. Au moins trois jours donneurs distincts sont requis. Minimum 95 % de mesures. Les estimations restent marquées et ne remplacent pas le taux de complétude mesuré. |

Le programme n'interprète jamais une valeur illisible comme un zéro. Les valeurs négatives import/export deviennent des intervalles à examiner. Les nombres à virgule et séparateurs suisses de milliers sont lus. Un pas variable ou des grilles incompatibles sont refusés : demander un export régulier plutôt que répartir arbitrairement son énergie.

## Méthode de calcul

### Flux, rendement et stock

La simulation utilise les **énergies AC par intervalle**, après conversion des puissances moyennes kW/W avec le pas détecté. Le rendement de charge et celui de décharge valent chacun la racine carrée du rendement aller-retour renseigné.

Le stock interne évolue selon :

`stock_fin = stock_début + charge_AC × rendement_charge − décharge_AC / rendement_décharge`.

Pour un même convertisseur bidirectionnel, `charge_AC + décharge_AC ≤ puissance_AC × durée_intervalle`. L'ordre initial est « décharge puis charge » ; le choix inverse permet une étude de sensibilité. Ces deux conventions ne sont pas des bornes mathématiques garanties du comportement réel. Des mesures plus fines sont nécessaires pour connaître l'ordre des échanges à l'intérieur du quart d'heure.

Le bilan complet distingue surplus capté, énergie restituée, pertes de conversion, stock utilisable final et stock non transféré aux interruptions. L'énergie captée et l'énergie restituée ne sont plus additionnées sous une quantité unique « valorisée ».

### Pilotage et économies

La stratégie est l'**autoconsommation immédiate** : charger avec le surplus et couvrir les besoins réseau avec le stock disponible. Les tarifs valorisent cette stratégie ; ils ne constituent pas un pilotage prédictif. Aucun arbitrage réseau, gain de Peak Shaving ni prévision EMS n'est annoncé. Un pilotage tarifaire prédictif éventuel nécessiterait un mode et une validation séparés.

`Économie = achats réseau évités − recette de reprise abandonnée`.

Les tarifs sont intégrés à la minute dans chaque intervalle, en supposant le flux réparti uniformément à l'intérieur de celui-ci. Les limites d'horaires doivent donc être alignées à la minute. Le calendrier historique permet des prix et horaires différents par période ; une seule année de scénario ne prétend pas reconstituer des factures anciennes.

### Dimensionnement

La grille physique est fixe par mode : 1 kWh/1 kW en résidentiel, 5 kWh/5 kW en PME, 10 kWh/10 kW en C&I. Les bornes techniques exactes sont incluses. En PME et C&I, la contrainte 0,5C inclut son extrémité exacte pour chaque capacité : par exemple 150 kWh/75 kW, 170 kWh/85 kW.

Pour chaque capacité, le programme retient la **plus petite puissance testée procurant au moins 99 % du meilleur gain** à cette capacité. Le repérage de la saturation utilise l'enveloppe des gains maximaux par capacité, une fenêtre de 5/20/50 kWh selon le mode et un seuil de 30 % de la meilleure valeur marginale lissée. La référence et le critère d'arrêt sont lissés avec la même largeur physique.

Le programme examine tous les candidats admissibles au seuil de cycles. Un plateau conserve la plus petite taille suffisante. Une configuration en bordure de plage, sans gain, à gain annuel faible ou sans candidat au seuil de cycles est signalée. Les limites **techniques** contraignent le calcul ; les limites et espacements **d'affichage** agissent uniquement sur les graphiques. Les tailles ne sont pas présentées comme des modules disponibles dans un catalogue constructeur.

Cette méthode est une heuristique de dimensionnement énergétique. Elle ne démontre pas que l'investissement est rentable. L'option « pas de batterie » conserve zéro économie et zéro investissement ; si les gains batterie sont non positifs, aucune configuration n'est validée. Le seuil de faible économie annuelle est visible et modifiable, avec 10 CHF/an comme valeur initiale.

### Cycles, années et retour simple

`Cycles sur capacité utile = énergie interne déchargée DC / capacité utile`.

La table conserve aussi les cycles rapportés à la capacité nominale. Les seuils initiaux de 150/130/100 cycles/an sont des critères internes modifiables, explicitement distincts d'une garantie constructeur. Un SOC minimum élevé réduit le dénominateur utile : il faut donc comparer les cycles avec la même convention.

Les valeurs principales portent toujours sur la **période analysée**. Un équivalent annuel sur 365 jours est séparé : disponible à partir de 330 jours avec les 12 mois représentés, au moins 98 % de mesures et au moins 90 % dans chaque mois présent. Une année civile complète est annualisée par défaut ; une période incomplète nécessite de choisir l'extrapolation. Elle ne remplace pas les mesures manquantes et ne garantit pas la représentativité saisonnière.

Le retour simple vaut `coût installé / économie annuelle positive`. Sans coût ou sans base annuelle exploitable, il reste non calculable. La projection suppose des paramètres constants, sans actualisation, vieillissement ni auxiliaires ajoutés.

## Corrections par fichier

| Module | Rôle et corrections |
|---|---|
| `app.py` | Interface française, champs PV supprimés, SOC réglable, sélection de courbe sûre, hypothèses visibles, grille et simulation en cache, calcul uniquement de la vue choisie, PDF à la demande et invalidation du rapport périmé. |
| `loaders.py` | Dates UTC/Zurich, unités et nombres locaux, détection de trous/doublons/pas incompatibles, estimation explicite, index Huawei assemblés avant différences, remises à zéro signalées, agrégation de compteurs distincts explicitement choisie. |
| `simulation.py` | Un seul calcul partagé par simulation et grille ; budget du convertisseur, SOC et bilans DC/AC, validation des paramètres, calendrier tarifaire, résultats de période et annualisation séparés ; ancienne branche Peak Shaving retirée. |
| `recommend.py` | Grille physique fixe, puissance à 99 %, lissage en kWh, critères de cycles cohérents, plateaux et absence de gains gérés, alertes en bordure de plage. |
| `energy_dashboard.py` | SOC issu du moteur, dates suisses, année/mois distincts, trous préservés, variation de stock séparée des pertes. |
| `grd_profiles.py` | Préremplissages identifiés comme indicatifs ; année explicite et plages modifiables. |
| `i18n.py` | Français uniquement ; messages, hypothèses et réserves communs à l'interface et au PDF ; textes de l'ancienne méthode supprimés. |
| `report.py` | Sections réellement sélectionnables, bilans sans double comptage, paramètres réels dont SOC/rendement, alertes, années séparées, ressources relatives au module, polices incorporées. |

Les noms de fichiers chargés ne deviennent pas des chemins d'écriture. Les fichiers identiques sont identifiés par leur contenu. Des limites de taille des fichiers, de décompression XLSX, de chronologie et de grille réduisent les risques de saturation. Cela reste un outil de simulation local : aucun mécanisme d'authentification ou d'hébergement public n'est ajouté.

## Vérifications

```sh
python -m pip install -r requirements-tests.txt
python -m pytest -q
```

Les tests autonomes couvrent conversions, dates et transitions été/hiver, nombres locaux, chevauchements, périodes incomplètes, estimation, index cumulés Huawei, SOC, rendement, budget de puissance, bilans énergétiques/monétaires, calendrier tarifaire, absence de gain, dimensionnement, cycles, sélection PDF et interface Streamlit avec un vrai chargement de fichier de test.

Pour rejouer aussi les régressions avec les deux XLSX fournis, les conserver dans un dossier privé et renseigner `BATTERY_TEST_DATA_DIR`. Les données clients ne sont pas incluses dans l'archive.

```sh
# macOS / Linux
BATTERY_TEST_DATA_DIR=/chemin/vers/les/xlsx python -m pytest -q -s
```

Les formats Huawei et les cas limites sont couverts par des fichiers synthétiques. Les deux exports résidentiel et C&I ont été testés en entier. Les mises en page du PDF ont été contrôlées sur des rapports produits à partir de ces profils, sans les deux images non fournies. La validation de cette version ne remplace pas une comparaison avec le fonctionnement d'une batterie réelle ou avec chaque variante d'export d'un fournisseur.

### Résultats de validation de cette livraison

**47 tests réussis**, dont les trois régressions utilisant les fichiers clients. En complément, le parcours complet a été exécuté sur les deux vrais fichiers : sélection séparée, refus de leur combinaison, traitement des trous, SOC à 95 % dans chaque mode, vues jour/semaine/mois/année, calendrier tarifaire, PDF et scénario sans économie positive. Le noyau accéléré Numba a été comparé au même noyau exécuté en Python.

Les grilles par défaut comportent 920 configurations résidentielles et 2 408 configurations C&I, soit **3 328 configurations**. Les bilans physiques ont été contrôlés sur les configurations sélectionnées, sur plusieurs SOC minimums et sur les cas synthétiques ; il ne s'agit pas d'une certification de chaque système matériel.

| Cas de régression | SOC minimum | Capacité / puissance retenues par la règle | Gain sur la période |
|---|---:|---:|---:|
| Résidentiel, segments mesurés | 5 % | 14 kWh / 4 kW | 442,09 CHF |
| Résidentiel, 104 intervalles estimés | 5 % | 14 kWh / 4 kW | 442,41 CHF |
| C&I, année complète | 30 % | 830 kWh / 310 kW | 13 696,25 CHF |

Ces chiffres sont des **repères de test**, pas une offre de batterie : tarifs du scénario Groupe E 2026 préremplis, rendements respectifs 92 % et 80 %, horodatages en fin d'intervalle, décharge avant charge. L'heure d'automne résidentielle est affectée à sa première occurrence. Les contrôles annuels sont activés pour cette comparaison ; ils restent facultatifs pour la source résidentielle incomplète dans l'interface.

Le changement des tailles par rapport à l'ancienne version provient notamment du lissage physique corrigé, des cycles DC, du partage de puissance et de la règle de puissance à 99 %. Changer l'ordre des flux à taille constante donne 442,01 CHF pour le cas résidentiel segmenté et 13 729,03 CHF pour le C&I : cette sensibilité est mesurée, sans être présentée comme un encadrement garanti.

## Références techniques

Les horodatages naïfs sont localisés avec gestion explicite des heures ambiguës/inexistantes, puis convertis en UTC : [documentation pandas](https://pandas.pydata.org/docs/reference/api/pandas.DatetimeIndex.tz_localize.html).

Les horaires Groupe E 2025/2026 s'appuient sur l'annonce de changement de plages : [Groupe E, tarifs en baisse et nouveautés](https://www.groupe-e.ch/fr/decouvrir-groupe-e/medias/communiques-de-presse/tarifs-en-baisse). Cette référence ne valide pas les montants du contrat client.

Les parcours d'interface ont été exécutés avec l'outil de test officiel : [Streamlit AppTest](https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest).
