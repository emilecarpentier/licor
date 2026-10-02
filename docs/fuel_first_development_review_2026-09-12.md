# Bilan du développement fuel-first — 12 septembre 2026

## Résultat et décision

Le cas d'usage « qualification courte -> plan initial -> autonomie prioritaire ->
adaptation en course » est désormais le contrat de développement. Voir
`fuel_first_race_contract_2026-09-12.md`. Les travaux de ce lot restent hors ligne;
aucune estimation HUD, marge probabiliste ou adaptation live n'est activée.

Trois étapes annoncées sont exécutées : harmonisation de l'accélération,
comparaison de formes de coût temporel, et audit des choix de doses/plans.
Un calculateur pur de budget carburant complète cette chaîne.

## Accélération harmonisée sans nouvelle collecte

`scripts/build_harmonized_four_circuit_inputs.py` conserve les 223 observations
canoniques, leurs cibles et leurs qualifications. Les 49 Sebring utilisent
désormais la même méthode que l'historique : médianes push à cinq ratios
physiques, puis interpolation. Les cinq tours push 8–12 préexistants suffisent.
L'ancienne accélération est conservée; écart absolu moyen 0,0434 m/s².
L'accélération au point de lift prévu est exportée séparément pour Sebring.
Elle ne doit pas être remplacée par celle au lift effectivement réalisé du test.

Sortie : `data/processed/experimental/four_circuit_harmonized_v1/`.
Les profils épars restent une approximation; cette harmonisation ne corrige pas
les différences de fenêtres de résultat ou les erreurs pilote non localisées.

## Modèles de coût : amélioration modeste, pas promotion

`src/licor/analysis/low_data_response.py` compare quatre formes positives passant
par zéro : dose seule, dose × accélération, dose + dose², et dose +
dose² × (1 + accélération positive / 1 m/s²). Coefficients ajustés uniquement
sur les autres circuits, sans tuning sur le circuit test. La convexité vaut
à accélération fixée, pas automatiquement le long d'une approche réelle.

| Forme | MAE temps macro restreinte | MAE essence macro restreinte |
| --- | ---: | ---: |
| Dose seule | 0,07253 s | 7,817 mL |
| Dose × accélération | 0,07378 s | 7,853 mL |
| Dose + dose² | 0,07031 s | 7,929 mL |
| Dose + dose² pondérée par accélération | 0,07131 s | 7,817 mL |

MAE par passage de zone; moyenne non pondérée des quatre MAE de circuit.
183 passages test au total (Spa107, Paul40, Bahrain24, Sebring12). Le fit reste
pondéré par observation, pas par circuit. La sensibilité à tous les passages
Sebring conserve 220 lignes test et donne 0,07429/0,07362 s pour dose seule/quadratique.
Les 223 lignes canoniques comprennent trois observations historiques sans cible
finie, exclues identiquement pour les modèles comparés.

Ces circuits ont déjà été examinés : les résultats sont du développement,
pas une nouvelle confirmation indépendante. L'écart n'établit aucune supériorité
statistique. L'essence n'est pas automatiquement mieux prédite par une forme plus
complexe; ne pas sacrifier sa robustesse au seul gain de MAE temporelle.

Sortie finale : `four_circuit_response_candidates_v2` sous le dossier experimental.
La version v1 est conservée; v2 ajoute le contrôle de support positif et la
provenance du solveur sans modifier les prédictions sur les données présentes.

## Choisir un plan pour atteindre une économie

`scripts/evaluate_sebring_fuel_first_decisions.py` apprend uniquement sur
Spa/Paul/Bahrain. Les doses prévues A/B sont lues dans les tours de calibration
2/3, sans ajustement local des réponses dans ce premier audit. Les décisions
sont prises avant de joindre les résultats des tours test 5(B)/6(A).
Les variables d'exécution des tours test ne servent pas à choisir les plans.

Deux menus sont distingués : A/B complets (chacun réellement exécuté une fois)
et combinaisons par zone (recomposition hypothétique de deux tours).
La référence push zéro n'est pas un troisième tour push contemporain observé.

Pour une cible exploratoire de 0,20 L sur les sept fenêtres de zone, les modèles
dose seule et quadratique pondéré choisissent A. Sa prédiction essence est
0,22607 L; le résultat de référence est 0,25560 L, pour +0,54949 s.
B atteint aussi la cible dans son unique observation : 0,24647 L pour +0,27660 s.
Le choix A laisse donc 0,27289 s de regret descriptif dans ce menu observé.
Ce n'est ni une différence causale établie ni une erreur par tour de course.

À 0,25 L, le modèle signale « inaccessible » et choisit B comme économie prédite
maximale. B manque la cible de 0,00353 L alors que A l'atteint dans l'observation
disponible : le classement de l'économie reste lui aussi imparfait. À 0,30 L,
aucun des deux plans complets observés ne suffit. Les simulations mixtes ne
prouvent pas qu'un plan jamais conduit atteindrait cette cible.

Les cibles 0/0,15/0,20/0,25/0,30 L sont une grille de diagnostic, pas des budgets
de course calculés. Les résultats sont des sommes des sept fenêtres gelées,
pas une consommation totale du tour. Aucun taux de fiabilité de course n'est
estimé à partir de ces deux observations ou des 49 passages corrélés.

Sortie finale : `sebring_fuel_first_decisions_v2_final` sous experimental.
Versions v1 et v1_final conservées; v2 complète la provenance transitive du solveur.

## Suite et besoin du pilote

La prochaine étape logicielle est de relier budget prudent, erreurs de prédiction
et corrections locales dans un replay chronologique, en testant hausses de tours
restants, sous-économies, données manquantes et changements de contexte. Définir
les marges avant de donner autorité au contrôleur. Tester ensuite le démarrage
depuis une courte qualification, avec une sortie explicite si les tours push
sont trop peu nombreux ou le modèle n'est pas prêt avant la grille.

Pas de nouvelle run générale nécessaire maintenant. Le seul input technique
immédiat demandé est le HUD utilisé. Le choix Imola/Interlagos/COTA peut attendre
le gel du prochain protocole. Une confirmation fraîche devra tester le candidat
figé; ne pas réutiliser les présents résultats comme preuve finale après tuning.

## Vérification et limites d'outillage

456 tests passent; `ruff check .` passe et les dix fichiers Python de ce lot
respectent `ruff format --check`. Le notebook compagnon
`notebooks/fuel_first_development_audit.ipynb` vérifie les empreintes de toutes
les sources/sorties finales, la conservation des identités/cibles et recalcule
les MAE en SQL depuis les prédictions. Ses cellules passent séquentiellement
avec Python en mode UTF-8; le noyau Jupyter n'a pas été exécuté, car nbformat,
nbclient et ipykernel ne sont pas installés. Aucun paquet n'a été installé.

Tests : isolation des circuits, cibles test empoisonnées, prédicteurs test
modifiés sans changement de choix, priorités essence/temps, abstention hors
support d'action, cas de tours supplémentaires/réserve/formation et entrée
invalide. Les sources et sorties sont empreintées, sans réécriture des packs live.

`uv run --no-sync` ne fonctionne pas ici (trampoline/cache Windows). Les contrôles
sont donc exécutés avec `.venv/Scripts/python.exe -m pytest` et `-m ruff`, sans
installation ni mise à jour de dépendances. Le premier pytest ciblé a également
rencontré un refus d'accès au dossier temporaire global; il a été relancé avec
un dossier temporaire neuf dans le projet.

Durcissement futur non bloquant pour le pack gelé : rejeter explicitement les
clés nulles d'événements dans le helper d'harmonisation. Les événements utilisés
ici sont empreintés et ne présentent aucune clé nulle. Les garanties de support
marginal ne sont pas des garanties de couverture physique conjointe.
