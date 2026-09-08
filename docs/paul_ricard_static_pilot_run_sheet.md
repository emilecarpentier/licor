# Pilote statique Paul Ricard — fiche de run

Préparé le 7 septembre 2026. Le pack est destiné à mesurer ses prédictions en
conduite. La compensation audio de 0,35 s vient de Spa et reste provisoire.

## Plan à exécuter

| Zone | Lift prévu avant la référence de freinage | Économie prédite | Temps prédit |
| --- | ---: | ---: | ---: |
| T03 | 36,6 m | 0,0146 L | 0,056 s |
| T08–T09 | 94,5 m | 0,0414 L | 0,053 s |
| Total par tour LICO | | 0,0560 L | 0,109 s |

Les autres zones restent en push. Le beep est anticipé pour ta réaction : sa
position n'est pas celle du début de lift prévu. Conduis normalement le freinage
et la sortie après le lift. Les deux points ont respectivement six et cinq
observations proches dans deux runs ; le temps de T08 reste bruité. Ces chiffres
sont des prédictions exploratoires, pas des gains déjà confirmés.

## Avant de rouler

Ouvre PowerShell à la racine du projet :

```powershell
Set-Location 'F:\OneDrive\licor'
.venv\Scripts\python.exe scripts\build_paul_ricard_pilot_pack.py --verify-only
.venv\Scripts\python.exe scripts\run_lmu_live_cues.py --doctor
```

Le premier contrôle vérifie le pack, ses sources et les séquences silencieuses.
Le second vérifie l'installation LMU ; hors simulateur, l'absence de mémoire
partagée est attendue. En session, la mémoire partagée doit être disponible.

Vérifie Paul Ricard, l'Oreca 07 LMP2 ELMS, le setup voulu, une météo stable et
l'usure des pneus à zéro. Garde l'enregistreur LMU `.duckdb` actif : le CSV live
complète la télémétrie brute, il ne contient pas tous ses événements de qualité.
Note le setup, l'essence initiale et les conditions dans les métadonnées du run.

Vérifie le son avant de conduire :

```powershell
.venv\Scripts\python.exe scripts\run_lmu_live_cues.py --bench-beep-only
```

Aux stands ou pendant l'outlap, avant la ligne de départ :

```powershell
.venv\Scripts\python.exe scripts\run_lmu_live_cues.py --show-current-lap
```

Ce numéro est le numéro absolu de la télémétrie, qui peut continuer entre runs.
Si le prochain passage de ligne doit commencer le premier tour mesuré, utilise
le numéro affiché + 1 comme `FirstScoredLap`. Ne le déduis pas du compteur de
l'interface. Lance le programme avant ce passage de ligne.

## Lancer le run

Exemple uniquement si le premier tour mesuré est réellement le tour absolu 1 :

```powershell
& .\data\processed\experimental\paul_ricard_pilot_2026_09\pilot_pack\start_pilot.ps1 -FirstScoredLap 1 -ScoredLaps 7 -EmitSystemBeep
```

Adapte `FirstScoredLap` et choisis 5, 6 ou 7 tours. Le lanceur affiche la séquence :

| Tours mesurés | Séquence après l'outlap |
| --- | --- |
| 5 | Push / LICO / Push / LICO / Push |
| 6 | Push / LICO / LICO / Push / Push / LICO |
| 7 | Push / LICO / LICO / Push / LICO / LICO / Push |

Sept tours offrent quatre exécutions LICO encadrées par des tours push. Cinq
ou six restent utiles si le temps manque. Les tours push sont automatiquement
silencieux. Sans `-EmitSystemBeep`, le programme journalise sans émettre de son :
ce mode sert aux vérifications, pas au pilote audio.

Termine le dernier tour mesuré et passe la ligne une fois pour clôturer les
mesures ; le programme s'arrête à l'entrée du tour suivant. `Ctrl+C` permet
d'interrompre. Un cue manqué ou une erreur ne nécessite pas de refaire tout le
run : note simplement le tour/la zone après la session.

## Après le run

Les résultats sont dans
`data/processed/experimental/paul_ricard_pilot_2026_09/sessions/<RunId>/` :

- `events.csv` et son résumé : passages de cue, avec `cue_enabled=false` sur les
  tours push ;
- `telemetry.csv` : échantillons live, dont fuel, vitesse, pédales et tours ;
- `lap_schedule.csv` et `session_config.json` : séquence exacte, audio et hash du
  plan ;
- `run_metadata_template.json` : compléter le chemin du `.duckdb`, setup,
  conditions et incidents ;
- `pack_manifest.json` : référence du pack exécuté.

Conserve le `.duckdb` et donne son chemin ainsi que le `RunId` à Codex. N'édite
pas le pack figé pour y mettre des notes : utilise les fichiers de session.

## Évaluation fixée avant collecte

Comparer d'abord les distances exécutées aux distances prévues et les erreurs
de déclenchement aux positions de cue. Distinguer les cues désactivés, les cues
émis et les cues signalés comme non entendus ; une ligne de log seule ne prouve
pas la perception du son.

Pour le fuel et le temps, mesurer les mêmes zones dans les tours push du run.
La comparaison principale utilise l'interpolation entre les tours push propres
qui encadrent chaque tour LICO. S'il manque une borne (notamment le dernier
tour LICO de la séquence à six), utiliser le push propre le plus proche et
signaler cette comparaison comme moins contrôlée. Montrer aussi les deltas
contre la moyenne des push en sensibilité. L'usure à zéro ne supprime pas les
effets de température et de baisse du carburant.

Rapporter chaque tour, les exclusions et la dispersion ; ne pas promettre une
significativité avec si peu de répétitions. Les valeurs de temps extraites
actuellement restent sensibles aux échantillons de frontière. Le total du tour
sert de sanity complémentaire. Évaluer les prédictions figées avant toute
réestimation ; ne pas entraîner puis évaluer sur les mêmes tours LICO.

Enfin, rejouer les décisions adaptatives uniquement avec l'information passée
disponible à chaque tour. Cela permet d'examiner les changements proposés ; leur
gain réel ne peut pas être déduit des actions statiques effectivement conduites.
