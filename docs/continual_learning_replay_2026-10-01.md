# Première boucle d'apprentissage local — 2026-10-01

## Verdict et périmètre

La boucle hors ligne est implémentée : prédire avec l'état courant, observer le
passage, appliquer le filtre qualité, puis corriger la réponse locale pour les
passages suivants. Le transfert global reste figé. Aucun bip, plan live,
descripteur push ou réglage de production n'est modifié par cette boucle.

Le replay Sebring montre une amélioration modeste des erreurs moyennes, pas une
preuve de meilleure stratégie ni d'arrivée avec le carburant prévu. Il s'agit
d'un témoin d'adaptation sur un circuit exclu de l'ajustement global, avec des
données déjà examinées pendant le développement. Les choix de modèle et de
garde-fous ne constituent pas une nouvelle confirmation indépendante.

## Contrat du test

- Source : `data/processed/experimental/four_circuit_harmonized_v1/`,
  223 observations conservées. Référence initiale ajustée sur 171 observations
  finies appariées Spa/Paul Ricard/Bahrain; trois autres observations historiques
  ont des cibles manquantes et ne sont pas imputées. Aucun résultat Sebring ne
  participe à cet ajustement.
- Ordre explicite : première tentative `sebring_lico_20260912_132042`, tours
  2/3/5/6, puis reprise `sebring_abab_20260912_134132`, tours 8/9/10. L'ordre des
  zones est T1/T3/T7/T10/T13/T15/T17; le tri lexical des noms de runs serait faux.
- Les 49 passages sont journalisés, soit 98 lignes essence/temps. Seuls les
  12 passages `strict_retry` (T7/T10/T13/T15 sur trois tours) mettent à jour les
  modèles et entrent dans la comparaison principale. Les 37 autres restent
  exclus, avec les motifs du fichier de revue existant. Un de ces passages est
  également hors support d'action; il provoque une abstention, pas un écrêtage.
- `strict_retry` est une sensibilité rétrospective restreinte, pas une
  certification de conduite propre. Les annotations existantes sont communes
  à l'essence et au temps. Le code permet des filtres distincts, mais on n'en
  invente pas pour les observations réelles.
- Chaque état est propre à une zone et une cible. Les deux runs partagent ici
  explicitement les mêmes références push figées; ce choix n'établit pas la
  robustesse à un changement de masse d'essence, météo ou setup.
- Les doses exécutées servent à prédire les réponses conditionnelles, les doses
  prévues restent dans une colonne distincte. Ce test ne prédit pas une commande
  live avant d'en connaître l'exécution.

## Mise à jour bornée

Une correction multiplicative commence à 1. Le résidu relatif est limité à
±0,5, puis divisé par `2 + nombre de passages acceptés + 1`. Chaque changement
de correction est limité à 0,1 et le multiplicateur total reste entre 0,5 et
1,5. Ces paramètres sont des garde-fous d'ingénierie fixés avant ce replay,
pas des intervalles de confiance calibrés. Les résultats négatifs restent dans
les scores; seule leur influence sur la mise à jour est limitée.

Pas d'apprentissage en cas de qualité refusée, cible absente, action nulle ou
sortie des bornes marginales d'apprentissage. Une référence prédisant exactement
zéro est signalée séparément : ce correcteur ne peut pas la rendre positive.
Il ne peut pas non plus corriger une erreur supérieure à ses limites de facteur.
La redécouverte d'une zone mal représentée nécessitera la future actualisation
des descripteurs et une réponse observée, pas une affirmation d'inefficacité.

Le témoin empirique reste le modèle simple fondé sur la dose. L'accélération est
conservée et contrôlée pour le support, mais n'influence pas sa valeur prédite.
Le noyau accepte les modèles existants avec interaction d'accélération; ce lot
ne sélectionne pas un nouveau modèle à partir des résultats Sebring. L'importance
physique de l'accélération pour le futur choix de zones n'est pas abandonnée.

## Résultats de développement, prédiction avant mise à jour

MAE = moyenne de l'erreur absolue par passage-zone, sur les mêmes observations
pour les deux modèles. Les 12 passages couvrent quatre zones et trois tours
corrélés, pas douze confirmations indépendantes.

| Mesure | Référence figée | Corrections locales |
| --- | ---: | ---: |
| MAE économie, 12 passages | 7,958 mL | 7,263 mL |
| MAE temps perdu, 12 passages | 0,07400 s | 0,07130 s |
| MAE économie, 8 passages après une première observation locale | 10,196 mL | 9,154 mL |
| MAE temps, ces mêmes 8 passages | 0,07617 s | 0,07211 s |
| Surestimation positive moyenne d'économie, 12 passages | 1,253 mL | 1,238 mL |

La dernière ligne vaut `moyenne(max(prédiction - observation, 0))` sur les
12 passages, et non seulement sur les erreurs positives. Elle expose le risque
de créditer une économie excessive; elle n'est pas une réserve probabiliste.
Les huit prédictions après une première observation améliorent leur MAE essence
d'environ 10,2 %. L'effet reste petit et non uniforme : la MAE de temps du tour9
passe de 0,09380 à 0,09568 s, donc se dégrade malgré l'amélioration globale.
La MAE essence se dégrade aussi légèrement à T10 (4,345 -> 4,444 mL) et T13
(3,399 -> 3,738 mL). Il ne faut donc pas présenter le gain moyen comme un gain
systématique dans chaque virage.

Les totaux exportés par tour ne couvrent que les quatre fenêtres qualifiées.
Ils ne constituent ni la consommation d'un tour complet, ni la faisabilité
carburant d'une course. Un budget adaptatif seul laisserait ces prédictions
locales identiques à la référence; aucun troisième modèle artificiel n'est ajouté.

## Vérification et reproduction

Fichiers de code : `src/licor/analysis/continual_learning.py`,
`scripts/replay_continual_learning.py`. Tests :
`tests/test_continual_learning.py`, `tests/test_continual_learning_replay.py`.

Les tests couvrent prédiction avant résultat courant, empoisonnement des résultats
futurs, invariance des prédictions aux passages exclus, états distincts,
changements de contexte, bornes de mise à jour, valeurs manquantes/non finies,
ordre des runs, jointure exacte des annotations, hashes et refus d'écrasement.

Vérification effectuée : **619 tests passent**, dont 35 nouveaux tests du noyau
et du replay; `ruff check .` passe. Les métriques ont aussi été recalculées
indépendamment avec DuckDB depuis `events.csv` : mêmes résultats, 11/11 hashes
sources/sorties concordants, aucune mutation d'état refusée ni rupture de chaîne.
Le contrôle d'empoisonnement des résultats à partir du tour9 sur les données
réelles ne change pas les prédictions jusqu'au tour9 inclus ni les états temps.
Les échecs d'accès au cache/temporaire Windows par défaut ont été contournés
avec un cache et un nouveau répertoire pytest sous `.tmp/`, sans réduire les tests.

```powershell
uv run python scripts/replay_continual_learning.py --output-dir data/processed/experimental/continual_sebring_replay_recheck
```

Le répertoire de sortie doit être nouveau. La sortie de référence est
`data/processed/experimental/continual_sebring_replay_v1/` : `events.csv`,
`metrics.csv`, `per_lap.csv`, `fits.json`, `manifest.json`. Le manifeste conserve
les identités d'apprentissage, paramètres et empreintes des sources/code/sorties.
Les données générées restent locales et ignorées par Git.

Source canonique SHA256 :
`5b0606a11793aa1e56a1b43e221611ebf70f3e4ce316116354735ebd5c430423`.
Événements SHA256 :
`c704896240ac33db8ce2fae1093fc111797aaa4c202a2cb7508a10fa7d1c9e1a`.
Métriques SHA256 :
`23d30fcf5128e2b99cc3996e95dc93bc1024eb9d67226302e1112084ec161435`.

## Suite, sans nouvelle run immédiate

1. Tester le démarrage qualification push courte -> zones/support -> plan initial,
   avec géométrie, fenêtres et plafonds issus uniquement des données disponibles
   à cet instant. Mesurer la couverture et le délai; signaler les abstentions.
2. Brancher ensuite les corrections à un recalcul de plan **shadow uniquement**,
   en utilisant l'accélération au lift prévu et en validant séparément le pont
   entre économies de fenêtres et consommation globale.
3. Geler ce candidat et un protocole prospectif avant de demander un essai sur
   un nouveau circuit. Ni OCR, ni exploration automatique en course, ni nouvelle
   campagne générale de collecte ne sont nécessaires pour ces étapes logicielles.

Validation analytique : utilisable avec réserves pour le développement logiciel;
pas pour autoriser un pilotage adaptatif. Le replay conserve cinq références
push dédiées et des zones pré-revues; le cas d'usage qualification puis course
sur circuit inconnu reste à valider de bout en bout.
