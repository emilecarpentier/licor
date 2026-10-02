# LICOR : bilan Sebring et apprentissage sur quatre circuits

## Décision

Nous pouvons poursuivre le développement du modèle à faible besoin de données,
sans demander immédiatement un cinquième circuit ou une nouvelle collecte générale.
Le transfert de consommation est encourageant. Le coût en temps reste le principal
verrou : ni une calibration locale supplémentaire ni l'interaction d'accélération
testée ne l'améliorent systématiquement. Aucun modèle n'est promu dans le live cue.

## Qualification des deux sessions Sebring

Les quatre tours A et trois B restent disponibles : 49 passages de zone, dont
trois B, et non un seul. Les erreurs non localisées de la première tentative ne
sont ni effacées ni transformées en certification de tours propres.

`scripts/qualify_sebring_phases.py` distingue trois intervalles spatiaux fixes
(approche, décélération push, sortie) à partir des références push antérieures.
Ce ne sont pas les points de freinage et de corde propres à chaque passage LICO.
Les médianes push sont calculées séparément par phase : leurs contrastes ne
s'additionnent donc pas nécessairement au contraste de la fenêtre complète.

Une extension diagnostique de 100 m après chaque fenêtre est limitée à 25 m avant
le prochain cue. Pour T17, elle va jusqu'à 100 m après la ligne. Ces extensions
peuvent recouvrir la fenêtre suivante : ne pas les ajouter aux économies du tour.
Elles ne prouvent pas que toute différence de vitesse a disparu à leur extrémité.

- T17 : six prolongements exploitables; surcoût temporel additionnel médian
  -0,0035 s, maximum +0,0155 s. Le dernier T17 manque de couverture après la
  ligne (67 m enregistrés, 100 m requis); aucune extrapolation.
- T13 : le contraste B/A médian se situe surtout dans l'approche (+0,064 s)
  et la décélération (+0,125 s), pas dans la sortie (-0,0015 s). Cela est compatible
  avec un lift plus coûteux, sans prouver une causalité ni une erreur pilote.
- Deux extensions de la première tentative méritent une sensibilité particulière :
  tour 2 T1 (+0,086 s) et tour 3 T10 (+0,143 s). Ce ne sont pas des erreurs pilote
  confirmées et elles ne sont pas supprimées automatiquement.

La cohorte restreinte Sebring comprend 12 passages de la reprise : T7, T10, T13
et T15 sur les trois tours complets, avec contrôles techniques et de pédale.
Les 37 autres passages restent exploratoires. Ce masque conservateur est
rétrospectif; `strict_retry` ne signifie ni vérité propre certifiée ni indépendance
d'une nouvelle expérience. T1/T3/T17 sont réservés à la sensibilité structurelle.

## Test du transfert entre circuits

Le benchmark compact utilise une seule copie de chaque observation historique,
issue du pli où son circuit était destination, avec ses références push dédiées.
Il ne remplace pas le pipeline ML v2. Paul Ricard, Bahrain, Spa et Sebring sont
tour à tour entièrement exclus de l'ajustement des coefficients. La confirmation
Paul Ricard verrouillée reste exclue. Aucun prétraitement n'est ajusté sur le test.

Les prédicteurs sont le lift exécuté normalisé par la distance physique de
décélération push, et éventuellement ce ratio multiplié par l'accélération push
positive au point de lift. L'accélération ne provient pas du passage LICO cible.
L'action exécutée rend cette évaluation rétrospective : ce n'est pas encore un
test de sélection autonome des doses annoncées avant conduite.

Les modèles sont des pentes non négatives passant par zéro. La MAE est l'erreur
absolue moyenne **par passage de zone**, pas une erreur par tour. La moyenne
macro donne le même poids aux quatre circuits, malgré leurs effectifs différents.
L'ajustement, lui, donne le même poids à chaque observation : Spa contribue donc
davantage à l'apprentissage que les petits jeux des autres circuits.

| Circuit tenu à l'écart | Passages test restreints | MAE essence, action seule | MAE temps, action seule |
| --- | ---: | ---: | ---: |
| Spa | 107 | 8,01 mL | 0,0540 s |
| Paul Ricard | 40 | 6,35 mL | 0,1057 s |
| Bahrain | 24 | 8,95 mL | 0,0565 s |
| Sebring | 12 | 7,96 mL | 0,0740 s |
| Moyenne des quatre circuits | 183 au total | 7,82 mL | 0,0725 s |

La référence triviale « prédire zéro économie et zéro coût » obtient respectivement
34,88 mL et 0,0954 s en moyenne macro. Le bénéfice est donc beaucoup plus net pour
l'essence que pour le temps; à Sebring, le temps ne passe que de 0,0812 à 0,0740 s.
Ces écarts sont descriptifs, sans test de significativité ni intervalle fiable.

En conservant les 49 passages Sebring, la moyenne macro devient 8,18 mL / 0,0743 s,
et Sebring seul 9,73 mL / 0,0805 s. Le résultat ne repose donc pas uniquement sur
la reprise, mais les observations n'ont pas toutes la même qualité.

L'interaction d'accélération donne 7,86 mL / 0,0738 s en moyenne macro restreinte,
légèrement moins bien que l'action seule. Cela ne réfute pas l'importance physique
de l'accélération : cela ne valide pas cette première forme linéaire. Les méthodes
d'échantillonnage de l'accélération historique et Sebring diffèrent aussi. Garder
la variable et harmoniser sa construction avant d'interpréter son effet.

## Apprendre avec zéro, un ou deux tours locaux

La première tentative conserve les tours 2/3 pour calibration et 5/6 pour test,
soit les mêmes 14 passages test à tous les budgets. La reprise ne les remplace pas.
Le modèle transféré est comparé à une pente purement locale et à une pente locale
ramenée vers le modèle transféré (poids fixé, non choisi d'après les résultats test).

| Tours de calibration | Méthode | MAE essence | MAE temps |
| --- | --- | ---: | ---: |
| 0 | Modèle transféré | 7,78 mL | 0,0610 s |
| 1 | Transfert + adaptation prudente | 7,25 mL | 0,0664 s |
| 2 | Transfert + adaptation prudente | 7,40 mL | 0,0603 s |
| 1 | Ajustement local seul | 22,90 mL | 0,1197 s |
| 2 | Ajustement local seul | 9,34 mL | 0,0942 s |

Le transfert stabilise nettement l'ajustement par rapport à apprendre de zéro avec
très peu de données. En revanche, deux tours ne prouvent pas un apprentissage
rapide systématiquement meilleur que zéro tour. Cette comparaison est provisoire :
erreurs initiales non localisées, même session, références communes, deux doses
seulement par zone. Ce n'est pas une courbe complète de coût/bénéfice.

## Suite recommandée et input pilote

1. Développer hors ligne une version candidate à adaptation locale prudente,
   avec essence et temps séparés; conserver le témoin simple comme seuil minimal.
2. Harmoniser les profils d'accélération issus du push sur les quatre circuits.
   Tester ensuite une forme physique/non linéaire simple pour le coût temporel,
   sans accumuler des variables indisponibles avant la décision de lift.
3. Évaluer les décisions proposées, pas seulement les erreurs de prédiction :
   classement des zones, dose choisie, coût d'une mauvaise recommandation et
   abstention hors domaine. Ne pas transformer les deux doses observées en
   autorisation pour de très grands lifts non validés.
4. Geler le candidat et son protocole avant la prochaine validation prospective.
   Réutiliser les quatre circuits pour développer; Imola restera une option de
   test réellement nouveau, pas une obligation de collecte immédiate. Les scores
   actuels deviennent des résultats de développement si l'on optimise sur eux.

Aucun retour immédiat au simulateur n'est nécessaire pour ces travaux logiciels.
Avant le prochain plan optimisé, demander au pilote la cible opérationnelle :
économie de carburant recherchée par tour ou perte de temps maximale acceptable.
Cette préférence n'est pas nécessaire pour continuer les comparaisons hors ligne.
La généralisation entre pilotes, setups et voitures reste non démontrée.

## Reproduction et contrôles

Scripts : `scripts/qualify_sebring_phases.py` et
`scripts/evaluate_four_circuit_low_data.py`. Ils refusent d'écraser leur destination;
pour une nouvelle exécution utiliser `--output-dir` avec un emplacement neuf,
et `--input` pour transmettre la nouvelle table qualifiée au benchmark.

Sorties : `data/processed/experimental/sebring_lmp2_transfer_2026_09/phase_qualification_v1/`
et `data/processed/experimental/four_circuit_low_data_v1/`. Les manifests conservent
les empreintes des sources et sorties. Les CSV de fits conservent les identifiants
train/calibration/test et les bornes de support. Aucun des 12 tests Sebring
restreints ne dépasse les bornes marginales globales; cela ne garantit pas une
couverture conjointe ni une bonne généralisation physique.

Contrôles : 370 tests passent; `ruff check .` passe. Tests ciblés : frontières
de récupération, couverture incomplète, sélection canonique, identités uniques,
isolation par circuit/run, mêmes cohortes, empoisonnement des cibles test sans
changement des coefficients, calibration chronologique et non-négativité.
Les résultats restent exploratoires, sans promotion de modèle, nouveau refit
des courbes de production ni changement des packs live gelés.

La revue signale un durcissement futur du diagnostic de tour partiel : refuser
explicitement un second reset de distance suivi d'une reprise atteignant 100 m.
Ce scénario n'affecte pas les six prolongements exploités ici; le dernier
enregistrement actuel reste correctement déclaré incomplet. Les résultats
présents ne certifient pas la gestion de tous les scénarios de retour aux stands.
