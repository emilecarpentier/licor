# Replay du budget carburant et HUD natif LMU

## Ce qui est implémenté

`src/licor/analysis/fuel_budget_replay.py` ajoute un contrôleur **hors ligne**
aux frontières de tours. Il consomme des litres natifs, des tours complétés,
une estimation nominale et une borne haute explicites des tours restants.
Il choisit dans un menu figé de plans admissibles : atteindre d'abord le budget,
puis minimiser le temps. Si aucun plan ne suffit, il conserve le déficit.

Les sorties incluent le plan shadow, la cible d'économie, le carburant d'arrivée
prévu, le carburant corrigé de l'enveloppe d'erreur, le manque par rapport à la
réserve et les raisons de mise à jour. Pas de génération de nouveaux lifts,
pas d'audio, pas de changement des packs ou du runtime live.

## Conventions du pilote, enregistrées sans les confondre

Le HUD est celui du jeu de base. Le pilote décrit `Lap 12/57.8` comme une
estimation de distance totale avec une proximité du tour supplémentaire, et
l'autonomie en tours du coin inférieur droit comme son contrôle privilégié au
passage de ligne. Le MFD peut recommander un arrêt alors qu'une arrivée avec une
petite quantité physique d'essence reste possible.

Cette information pilote n'est pas une spécification d'API vérifiée. Les champs
`hud_total_laps` et `hud_fuel_laps` sont conservés bruts; ils ne changent ni les
litres mesurés ni les bornes de distance explicites. Aucune conversion silencieuse
`floor(57.8)` ou `ceil(57.8)` n'est utilisée. `Lap 12` n'est pas automatiquement
douze tours complétés. Une autonomie affichée de 10,1 ne promet pas dix tours
si la consommation ou la distance effective change.

Le pilote n'a pas demandé une réserve fixe de 0,2 L. Une arrivée physique,
une réserve volontaire et une incertitude de consommation sont trois notions
distinctes; une réserve non satisfaite ne signifie pas automatiquement panne sèche.

## Mécanismes du replay

- Une hausse du tour absolu d'arrivée prudent s'applique immédiatement.
- Une baisse exige un nombre explicite de confirmations identiques du **tour
  absolu d'arrivée**, pas du nombre de tours restants qui diminue naturellement.
- Un statut d'arrivée confirmé force zéro tour restant et aucun nouveau plan,
  sans attendre les confirmations de baisse. Une réserve manquante reste visible.
- Une observation absente entraîne l'abstention; elle interrompt les confirmations
  de baisse. Aucun statut « carburant suffisant » n'est conservé par défaut.
- Le résidu de consommation utilise deux frontières consécutives, un intervalle
  déclaré utilisable et le **plan réellement exécuté**, jamais la suggestion shadow.
- Une erreur pilote, un intervalle incomplet ou un plan inconnu ne sont pas appris.
  Les litres actuels restent néanmoins pris en compte dans le budget.
- Un ravitaillement demande un nouveau contexte explicite. Pas de carburant
  futur crédité, ni de différence de réservoir apprise comme consommation négative.

L'enveloppe d'erreur est le maximum du plancher initial explicite et des résidus
positifs récents de consommation. Seuls les intervalles utilisables font avancer
la fenêtre; les données invalides ne font pas disparaître un résidu défavorable.
Il s'agit d'une **sensibilité diagnostique**, non d'un quantile calibré ou d'une
garantie de probabilité d'arrivée. Un résidu global du plan A appliqué à B n'est
pas un apprentissage causal de l'efficacité de chaque zone. Un changement de
contexte remet l'enveloppe au prior explicitement fourni : l'appelant doit vérifier
que ce prior et le menu conviennent encore au contexte.

## Scénarios reproductibles

`scripts/replay_fuel_budget_scenarios.py` produit sept scénarios synthétiques,
seize frontières et leurs décisions : tour supplémentaire, sous-économie,
tour inutilisable, entrée manquante, ravitaillement, arrivée, baisse confirmée.
Sorties dans `data/processed/experimental/fuel_budget_shadow_scenarios_v1/`.
Les empreintes des sources et résultats sont enregistrées.

Les valeurs 0,2 L de réserve, 0,05 L/tour d'enveloppe initiale et trois confirmations
sont des valeurs de test, **pas des réglages de course approuvés**. Ce lot ne
revendique aucun résultat empirique supplémentaire sur Sebring ni aucune
amélioration mesurée de probabilité d'arrivée.

Pour relancer sans écraser le résultat :

```powershell
.venv\Scripts\python.exe scripts\replay_fuel_budget_scenarios.py --output-dir data\processed\experimental\fuel_budget_shadow_scenarios_v2
```

## État de l'accès natif

Inspection en lecture seule des headers installés dans
`C:/Program Files (x86)/Steam/steamapps/common/Le Mans Ultimate/Support/SharedMemoryInterface/` :

- `InternalsPlugin.hpp:205` : `mLapNumber`, tour actuel;
- `:254` : `mFuel`, litres présents;
- `:411` : `mTotalLaps`, tours **complétés**, pas estimation de distance totale;
- `:464` : `mEstimatedLapTime`, estimation de temps de tour, pas `57.8`;
- `:499–501` : temps courant, temps de fin, plafond de tours;
- `:507–518` : phases grille/formation/vert/arrêt/fin;
- `:559` : temps de session restant.

Les champs exacts des deux estimations HUD n'ont pas été trouvés dans les headers
inspectés; cela ne prouve pas qu'aucune autre API ne les expose. Le lecteur public
LICOR ne transmet pas encore ce contexte de session/classement au contrôleur.
Le HUD est notamment empaqueté dans `Core/HUD/LMHUD.mas`; aucune extraction ni
modification du jeu n'a été effectuée.

## Prochaine étape et input

Le HUD est identifié : aucune nouvelle question pilote ne bloque la suite.
Prochaine tranche : préparer un enregistrement natif synchronisé session/joueur/
meneur, en lecture seule, puis comparer quelques passages de ligne aux deux
indicateurs HUD lors d'un prochain roulage utile. Ne pas demander une nouvelle
longue collecte LICO pour établir ces conventions.

Ensuite vérifier le démarrage depuis une courte qualification, geler un candidat
et son protocole pour un circuit nouveau. La marge empirique fiable, les effets
charge/pneus/trafic, l'adaptation par zone et l'autorité live restent à valider.
