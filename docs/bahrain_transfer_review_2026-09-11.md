# Bahreïn : validation corrigée et apprentissage avec peu de tours

## Décision

Un quatrième circuit suffit pour développer et mettre à l'épreuve un premier
modèle LMP2 avec peu de calibration locale. Il ne suffit pas à garantir que le
modèle apprendra rapidement n'importe quel circuit, ni à valider les gros lifts
sur toutes les zones. Le bon critère est la performance sur des observations
réservées après 0, 1 puis 2 tours de calibration, comparée à un modèle local
simple. Le nombre de circuits est une source de diversité, pas un seuil de
réussite automatique. Pilotes, setups et autres voitures restent des axes
d'évaluation futurs.

Bahreïn a vérifié la pertinence de six propositions et leur répétabilité à une
intensité par zone. Quatre répétitions d'une intensité ne permettent pas
d'identifier la courbure de sa relation essence/temps ni sa limite rentable.

## Correction du score prospectif

Le calcul v1 interpolait entre le dernier échantillon répétant une distance et
la distance suivante. Or la distance de scoring LMU se renouvelle environ
toutes les 0,2 s, alors que la trame live est à 50 Hz. Cela comprimait
artificiellement l'intervalle d'interpolation. La correction utilise les
premiers timestamps des mises à jour de `Lap Dist`, puis interpole carburant
et vitesse sur leurs propres grilles natives. Le live corrigé concorde avec le
natif à environ 0,002 s sur les médianes locales. Cette concordance ne crée pas
une précision physique de 0,002 s : les deux sources partagent le scoring LMU.

La source des bornes est désormais la copie figée `session/track_zones.json`.
Les prédictions originales sont vérifiées par hash et restent inchangées.
Les résultats v1 restent archivés et sont explicitement dépassés.

| Zone | Coût, bornes figées | Coût, diagnostic prolongé | Essence, diagnostic |
|---|---:|---:|---:|
| T01–T03 | −0,0844 s | −0,0801 s | 0,02869 L |
| T04 | 0,0484 s | 0,0484 s | 0,02919 L |
| T08 | 0,0408 s | 0,0384 s | 0,01852 L |
| T10 | 0,1328 s | 0,1984 s | 0,03391 L |
| T11 | 0,0417 s | 0,0527 s | 0,03030 L |
| T14–T15 | 0,1221 s | 0,1228 s | 0,03349 L |

Les pertes T10 prolongées sont 0,121 / 0,212 / 0,184 / 0,305 s. La valeur v1
de 0,295 s de médiane était erronée. T10 reste moins intéressant à l'intensité
testée; une courte action reste une hypothèse à tester. Le delta T1 négatif
reflète la conduite et le contexte observés; il ne prouve pas que le LICO fasse
gagner du temps causalement. Les zones silencieuses ne fournissent pas de
réponses LICO et leur variation ne doit pas être attribuée automatiquement à
une action précédente.

Sur l'intervalle commun 100–5350 m : **0,17186 L économisé et 0,41367 s perdu**.
Sur les durées officielles des tours : **+0,400 s**. La prédiction figée était
0,21856 L / 0,58204 s pour le plan. Les tours push 23/26/29 servent à ce score;
les tours LICO sont 24/25/27/28. Les 24 déclenchements étaient à temps. Le
drapeau d'impact natif du tour 29 reste une note d'audit, conformément au retour
pilote sans erreur notable.

## Place pour des lifts plus importants

Les distances ci-dessous sont des avances de lever par rapport au freinage
**push**, et non la distance de coast jusqu'au freinage réalisé en LICO.

| Zone | Avance testée | Fenêtre v1 disponible | Plafond de ratio v1 | Enveloppe de capture proposée |
|---|---:|---:|---:|---:|
| T01–T03 | 75 m | 201 m | 141 m | 476 m |
| T04 | 60 m | 200 m | 117 m | 483 m |
| T11 | 55 m | 202 m | 108 m | 497 m |
| T14–T15 | 70 m | 200 m | 126 m | 499 m |

Les cinq tours push possèdent une approche à pleine charge compatible avec
l'examen de cette enveloppe plus large. L'audit tolère les coupures de passage
de rapport de moins de 0,25 s, garde une seconde de contexte avant l'action et
25 m de marge, puis applique la limite actuelle de recherche de 500 m. Les
autres contraintes du détecteur, dont ses 8 s de recherche, et la trajectoire
dans la sortie précédente doivent être vérifiées avant un gros lift.

La capture large est enregistrée dans
`config/track_zones/bahrain_lmp2_capture_envelope_v2.json`. Elle n'est pas un
plan live et ne remplace pas les bornes de scoring. Une grille de candidats
tous les 25 m échantillonne directement l'accélération des tours push avant
chaque lever envisagé; elle couvre les ratios supérieurs à 1,5 sans les ramener
artificiellement à la dernière valeur de l'ancien profil. Le domaine de capture,
le domaine des actions apprises et la fenêtre du résultat sont séparés.

Les observations historiques atteignent environ 297 m à Spa et 195 m à Paul
Ricard, mais elles ne couvrent pas uniformément chaque type de zone. Les
avances exécutées à Bahreïn sont environ 41–82 m. Les candidats vers 400–500 m
sont donc clairement extrapolés, même si la télémétrie permet de les examiner.

## Trois circuits : évaluation rétrospective

Le pack `cross_circuit_ml_v2_release` contient 759 observations et trois
évaluations où le circuit destination est entièrement absent de l'entraînement
de la réponse. Chaque fichier brut reste dans un seul rôle. Seuls les tours
push du run antérieur servent à calibrer le circuit destination; les push du
run test ne participent pas aux références du benchmark.

| Circuit réservé | Erreur absolue moyenne essence | Erreur absolue moyenne temps | Passages test |
|---|---:|---:|---:|
| Bahreïn, appris depuis Spa + Paul | 0,00755 L | 0,05700 s | 24 |
| Paul, appris depuis Spa + Bahreïn | 0,00647 L | 0,10561 s | 40 |
| Spa, appris depuis Paul + Bahreïn | 0,00805 L | 0,05145 s | 138 |

Ce sont des diagnostics rétrospectifs sur l'action exécutée et les bornes
figées, pas de nouvelles prédictions prospectives. Les corrections de méthode
ont été décidées après avoir vu Bahreïn. Le modèle à deux termes avec
accélération n'améliore pas Bahreïn/Paul sur les mêmes lignes; il dégrade le
temps Spa (0,05383 → 0,05962 s). La variable reste nécessaire dans le contrat,
mais sa forme actuelle n'a pas démontré de gain prédictif.

Les faux coasts sur les push et dans les zones silencieuses restent des
diagnostics; le calendrier détermine les actions. Les masques de phase
préservent les approches propres et retirent les cibles contaminées. Les
descripteurs d'accélération dépendant d'un apex erroné sont également masqués,
tout en conservant l'accélération au freinage. Six lignes du tour Spa 32 de
`controlled_random_02` restent dans la table avec cibles nulles car la distance
n'est pas monotone; elles n'entrent pas dans les erreurs du modèle.

## Combien apprend-on avec un ou deux tours ?

Une expérience distincte utilise le tour 24 puis le tour 25 comme calibration
locale et garde toujours les tours 27–28 en test (12 passages, six zones).
Le poids du modèle initial est fixé avant le calcul; aucune cible test ne
participe au réglage. Les références push proviennent du run antérieur.

| Modèle | Tours locaux | Erreur essence | Erreur temps |
|---|---:|---:|---:|
| Transfert initial Spa/Paul | 0 | 0,00678 L | 0,06463 s |
| Transfert adapté | 1 | 0,00397 L | 0,06770 s |
| Transfert adapté | 2 | 0,00330 L | 0,05925 s |
| Local seul | 1 | 0,00280 L | 0,08100 s |
| Local seul | 2 | 0,00336 L | 0,05855 s |

L'essence s'adapte rapidement dans cette run. Le temps bénéficie peu de deux
tours et se dégrade légèrement après un seul. Le transfert n'a pas encore
prouvé un avantage net sur l'estimation locale simple. Cette étude partage
une même run et une même dose entre calibration et test : elle n'établit pas
la généralisation à une autre intensité ou à une session indépendante.

## Circuit D et prochaine collecte

Le choix entre Imola, COTA, Sebring et Interlagos attend la comparaison de
constance du pilote. Aucun classement de constance n'est inventé. Le protocole
de cinq push est prêt dans `docs/circuit_d_push_protocol.md`; le circuit et le
lanceur propre à celui-ci seront liés dès ce choix reçu.

Après ces push, préparer une validation de sept tours **P/A/B/P/B/A/P** :
deux intensités figées et répétées par zone, choisies depuis la géométrie push,
l'accélération et le domaine déjà observé. Répartir les actions plus fortes
entre zones pour éviter une transformation excessive d'un seul tour. Il faut
conserver deux observations par intensité et la même cohorte de test pour
comparer les budgets locaux. Les gros lifts peuvent faire partie d'une
calibration graduelle, avec statut d'extrapolation explicite.

Ce quatrième circuit doit permettre de décider si un modèle hiérarchique
simple des réponses essence/temps améliore le démarrage et réduit réellement
le budget local. La validation de l'avantage devra utiliser des sessions ou
circuits indépendants et des intensités nouvelles; la fatigue et le nombre
total de tours ne remplacent pas ces critères.

## Reproduction et preuves suivies par Git

Les petits tableaux de résultats et le manifeste du score corrigé sont dans
`docs/evidence/`. Les DuckDB et les gros packs restent ignorés par Git.

```powershell
.venv\Scripts\python.exe scripts\analyze_bahrain_transfer_v2.py --output-dir data\processed\experimental\bahrain_score_rebuild
.venv\Scripts\python.exe scripts\build_cross_circuit_ml_table_v2.py --output-dir data\processed\experimental\cross_circuit_ml_v2_rebuild
.venv\Scripts\python.exe scripts\evaluate_bahrain_few_lap_adaptation.py --help
```

Choisir un nouveau dossier à chaque reconstruction. Les scripts refusent
l'écrasement; le score prospectif original reste traçable par hash.
