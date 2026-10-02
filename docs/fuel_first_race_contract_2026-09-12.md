# LICOR : qualification courte, autonomie prioritaire et adaptation en course

## Cas d'usage confirmé par le pilote

Priorité rappelée par le pilote : le transfert multi-circuit sert d'abord à
éviter une collecte dédiée coûteuse sur chaque piste. Le produit recherché est
un premier plan utile dès le premier tour de course après une courte qualification,
puis un apprentissage continu fiable pendant le roulage normal. La proximité
d'un plan de pilote professionnel est un objectif à mesurer, pas une garantie
déjà démontrée. Le démarrage et l'adaptation doivent être évalués ensemble.

Sur un circuit nouveau, utiliser les tours push réalisés pendant 8–10 minutes
de qualification, construire un premier modèle avant la grille, puis adapter
le LICO à l'estimation évolutive de distance de course. L'objectif prioritaire
est de disposer du carburant nécessaire jusqu'à l'arrivée; minimiser le temps
perdu vient ensuite. C'est une cible réaliste de développement, pas une capacité
autonome déjà validée par les quatre circuits actuels.

### Clarification pilote : scénarios parallèles et liberté en fin de course

La suffisance carburant s'évalue **dans le scénario choisi par le pilote**.
LICOR doit comparer une course courte et une course d'un tour supplémentaire,
sans imposer automatiquement la seconde. Pour chacune : consommation cible,
économie nécessaire, plan admissible, coût temporel et déficit éventuel. Une
branche inaccessible reste visible même si le pilote privilégie l'autre.

La cible de 0,1L évoquée par le pilote n'est ni une réserve par défaut ni un
objectif automatique pour les 120 tours d'une course longue. Le pilote peut
choisir d'être plus agressif dans les 10–15 derniers tours et ignorer des cues.
LICOR continue ses calculs avec l'essence réellement mesurée, sans diminuer sa
réserve configurée ni assimiler les recommandations à des actions exécutées.
Une déviation n'est pas automatiquement une anomalie du modèle LICO. Quand
l'action exécutée est inconnue, ne pas apprendre de résidu causal de cette action.
Aucun déclencheur « derniers 15 tours » n'est implémenté.

`analysis/race_scenarios.py` fournit maintenant une comparaison hors ligne de
deux hypothèses adjacentes de tours joueur, avec une réserve et une marge de
consommation explicites et distinctes. Chaque branche minimise le coût parmi
les plans admissibles qui satisfont son propre budget. Sans choix explicite,
aucun plan global n'est sélectionné. Les plans impossibles n'ont pas de
recommandation, mais conservent leur déficit au plafond d'économie admissible.
Ce comparateur ne réentraîne aucun modèle et n'a pas d'autorité live.

## Ordre des décisions

1. Respecter les limites de conduite, de qualité des données et de doses validées.
2. Déterminer un budget permettant d'atteindre l'arrivée, ou le prochain
   ravitaillement d'une stratégie explicitement choisie.
3. Dans chaque scénario, parmi les plans satisfaisant son budget, minimiser le coût temporel.
4. Si aucun plan admissible ne suffit, signaler le déficit et demander davantage
   de carburant ou une révision du ravitaillement. Ne pas annoncer « arrivée
   garantie » et ne pas étendre automatiquement les lifts hors domaine.

Ce n'est ni maximiser l'économie en permanence, ni choisir un compromis libre
où un gain de temps autorise une panne sèche. Le carburant est une contrainte.

## Budget transparent, pas estimation unique du HUD

À une frontière de tour, pour N tours encore à commencer jusqu'à la cible :

```text
carburant disponible = carburant présent - réserve - consommation future hors tours
consommation cible/tour = carburant disponible / borne haute de N
économie requise/tour = max(0, consommation push prudente - consommation cible/tour)
```

`src/licor/analysis/fuel_budget.py` implémente cette arithmétique hors ligne.
La borne haute, la réserve, la consommation prudente et le plafond d'économie
validée sont des entrées explicites : le module ne prétend pas les calibrer.
Il distingue `no_saving_required`, `saving_required` et `target_unreachable`.
Le compteur nominal est conservé, mais la borne haute gouverne la contrainte
de cet ancien calculateur monoscénario. Le nouveau comparateur l'appelle
séparément pour chaque hypothèse fixe (nominal=borne=N dans cette branche),
sans confondre la branche longue avec une borne universelle de durée de course.

Un tour de chauffe encore à effectuer consomme un budget séparé. Une fois cette
essence brûlée et déduite du niveau mesuré, ne pas la soustraire à nouveau.
Le calcul n'est pas valable au milieu d'un tour : il faudra alors représenter
explicitement la portion restante et les zones encore accessibles. À zéro tour,
pas de division; une réserve déjà manquante reste signalée.

Pour une course avec ravitaillement, ne pas créditer l'essence future avant
d'avoir atteint les stands. Chaque relais doit être réalisable séparément; la
fin de course ne se prouve pas avec un simple bilan global de litres disponibles.
L'optimisation d'arrêts reste une couche distincte du premier contrôleur.

### Exemple synthétique, pas une recommandation pour Sebring

55 L présents, 1 L de réserve, push prudent de 3 L/tour et plafond admissible
d'économie de 0,4 L/tour :

- 20 tours : économiser au moins 0,30 L/tour;
- 21 tours possibles : 0,4286 L/tour requis, donc objectif inaccessible avec ce
  plafond; déficit de 0,60 L même en économisant 0,40 L/tour;
- 20 tours et 0,6 L de chauffe encore à brûler : 0,33 L/tour requis.

Ces scénarios montrent pourquoi une révision de distance doit modifier le plan
immédiatement les deux budgets. Cela n'autorise pas un changement silencieux
de scénario, de réserve ou de cues; aucun changement live n'est activé ici.

## Ce que la qualification peut et ne peut pas fournir

Les tours push renseignent les freinages, vitesses, accélérations, consommation
de référence et géométrie de zones. Le transfert appris sur les autres circuits
fournit les premières réponses LICO, avant toute observation LICO locale.
Le nombre de tours propres, pas la durée de la session seule, gouverne la qualité.
Le pipeline actuel utilise un minimum de trois références push pour plusieurs
descripteurs. Si la qualification n'en fournit pas assez, signaler la couverture
faible ou s'abstenir; ne pas inventer cinq tours ou garantir la disponibilité.

La qualification à faible carburant n'est pas identique à un début de course
chargé. Pneus, grip, météo, cartographie, aspiration et trafic peuvent modifier
la consommation et le temps. Les essais à 55 L et sans usure ne prouvent pas
la robustesse dans toutes ces conditions. La disponibilité du modèle dans les
8–10 minutes n'a pas encore fait l'objet d'un test de bout en bout chronométré.

## Deux boucles différentes pendant la course

### Apprentissage continu explicite : première tranche hors ligne

La première tranche est implémentée dans `analysis/continual_learning.py` et
`scripts/replay_continual_learning.py`, sans autorisation de changer les cues live :
conserver le modèle transféré comme référence figée pendant une course et mettre
à jour un petit nombre de corrections locales par zone, séparément pour essence
et temps. Avec peu de passages, les corrections restent proches de la référence;
la répétition de données corrélées ne vaut pas autant de preuves indépendantes.
Le réentraînement du modèle global entre sessions reste une opération contrôlée.

La qualité doit être locale : un tour imparfait peut contenir des phases/zones
utilisables. Ne pas abaisser silencieusement les seuils actuels de référence.
La couverture insuffisante reste visible. Actualiser aussi les descripteurs push
avec les nouveaux passages pertinents; ne pas figer pour toute la course une
mauvaise représentation issue de la qualification. Distinguer mauvaise qualité,
faible efficacité observée et absence d'observation. Ne pas classer un freinage
différent comme erreur simplement parce qu'il est la conséquence normale du LICO.

Une zone jamais liftée peut être réévaluée par les nouveaux descripteurs et le
transfert, mais sa réponse LICO n'est pas directement identifiée. Apprendre
d'abord des variations réellement exécutées et qualifiées, sans confondre variation
naturelle et expérience randomisée. Une exploration intentionnelle par petites
variations reste une option à discuter avec le pilote, jamais une autorisation
implicite de modifier ses cues. Elle nécessiterait des limites d'action, de coût,
de contexte et de faisabilité carburant, avec abstention si elles sont inconnues.

Premier livrable réalisé : replay séquentiel prédiction -> observation -> filtre
qualité -> mise à jour locale, journalisant les refus et états avant/après.
Le prochain plan n'est pas encore recalculé. Le replay compare référence figée et
réponses locales sur les mêmes actions exécutées. Un budget seul adaptatif ne
changeant pas ces prédictions par zone, il ne constitue pas un troisième modèle
dans ce test; sa comparaison exige le pont vers la consommation globale.
Les 12 passages Sebring autorisés gardent leur qualification rétrospective,
commune aux deux cibles. Les autres 37 restent visibles mais ne mettent rien à
jour. Le code permet des filtres essence/temps distincts; les données actuelles
ne justifient pas d'inventer ces annotations. Les descripteurs push et les zones
restent figés dans cette tranche. Voir `continual_learning_replay_2026-10-01.md`.
Les bénéfices de décisions non exécutées restent contrefactuels non validés;
les stress tests synthétiques vérifient le logiciel, pas la physique de course.
Une validation prospective figée reste nécessaire avant toute autorité live.

### Séparer adaptation du budget et apprentissage causal

**Budget global :** le niveau d'essence, la consommation réellement mesurée et
l'horizon restant déterminent si l'autonomie prévue dérive. Une économie moindre
que prévu resserre le budget des prochains tours; une borne de distance plus haute
peut rendre le plan inaccessible. Prévoir une logique anti-oscillation pour
relâcher la contrainte, sans retarder une alerte de déficit.

**Apprentissage par zone :** comparer commande, lift exécuté, freinage et résultats
locaux uniquement lorsque les signaux sont utilisables. Trafic, erreurs, stands,
changements de session et données manquantes ne doivent pas être appris comme
réponses LICO. La baisse de consommation d'un tour n'identifie pas à elle seule
l'économie causée par le LICO; le push contrefactuel en course est inconnu.
Conserver les priors et limiter les corrections avec peu de passages.

Les observations doivent être strictement antérieures à la décision corrigée.
Journaliser les versions et raisons des changements; ne pas déplacer un cue
déjà imminent. Les premières corrections seront rejouées en shadow mode,
sans commander le pilote, avant toute autorité adaptative en direct.

## Intégration LMU encore à établir

Le lecteur actuel `LmuLiveTelemetrySample` expose carburant, distance, tour,
temps et pédales, mais pas l'estimation HUD des tours restants. Le fait que la
structure native contienne des informations de session ne prouve pas que la
valeur exacte affichée par le HUD soit déjà disponible dans LICOR.

La [documentation officielle du MFD LMU](https://guide.lemansultimate.com/hc/en-gb/articles/13202210967055-Understanding-the-MFD-Multi-Function-Display)
décrit les informations d'autonomie, objectifs d'économie et tours/relais
nécessaires pour finir. Elle ne documente pas ici un accès programmatique à cette
estimation. Le pilote confirme le HUD natif LMU : total fractionnaire en haut à
droite et autonomie carburant en bas à droite. Les conventions d'accès et de
conversion restent à vérifier. Voir `fuel_budget_shadow_replay_2026-09-12.md`.

L'estimateur devra distinguer tours de course totaux et tours restants, voiture
du pilote et meneur déterminant l'arrivée, passage de ligne, tours de retard,
horloge expirée et drapeau final. Ne pas ajouter deux fois un « dernier tour »
si le fournisseur l'inclut déjà. Les ressources autres que le carburant, si
applicables au règlement/voiture, restent des contraintes séparées.

## Prochain verrou avant un nouveau circuit

Terminer les tests de décisions hors ligne, définir les marges de carburant à
partir d'erreurs hors apprentissage et d'une sensibilité de distance, puis
rejouer des scénarios chronologiques d'estimation changeante. Ne pas transformer
une MAE ou un p90 descriptif en garantie de probabilité d'arrivée.

Un prochain circuit peut tester le démarrage à partir d'une courte qualification
sans LICO local préalable. Geler d'abord le modèle, les limites, le protocole et
les prédictions. Choisir ensuite Imola, Interlagos ou COTA selon la constance du
pilote; aucun choix de circuit n'est requis pour poursuivre le logiciel.
