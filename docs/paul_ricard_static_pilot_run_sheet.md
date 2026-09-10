# Validation statique Paul Ricard — fiche de run

Révisé le 9 septembre 2026. Le pack sert à mesurer prospectivement les
prédictions des six zones candidates. La compensation de réaction audio de
0,35 s vient de Spa et reste provisoire. Le premier run à six zones est terminé;
les instructions restent valables pour un éventuel run de confirmation.

## Plan à exécuter

| Zone | Lift prévu avant la référence de freinage | Économie prédite | Temps prédit |
| --- | ---: | ---: | ---: |
| T01–T02 | 34,0 m | 0,0141 L | 0,000 s* |
| T03 | 36,6 m | 0,0146 L | 0,056 s |
| T08–T09 | 94,5 m | 0,0414 L | 0,053 s |
| T11 | 59,6 m | 0,0187 L | 0,210 s |
| T12 | 36,4 m | 0,0221 L | 0,033 s |
| T14 | 32,9 m | 0,0177 L | 0,020 s |
| Somme descriptive par tour LICO | | 0,1286 L | 0,372 s |

Les distances sont les centres des bins LICO positifs les plus densément
observés sous les plafonds pilote : 3 à 9 passages par zone. Le profil couvre
les six candidates au lieu de réutiliser le plan stratégique minimal à
`0,05 L/tour`, qui s'arrêtait logiquement après T03 et T08–T09. T05, T07 et T15
restent hors LICO selon la revue pilote.

Le beep est anticipé pour ta réaction : sa position n'est pas celle du début de
lift prévu. Conduis normalement le freinage et la sortie après le lift. Les
chiffres restent des prédictions exploratoires. En particulier, `0,000 s` à
T01–T02 signifie que le modèle monotone a écrasé un signal temps local négatif
et bruité; ce n'est pas une promesse de LICO gratuit. La somme descriptive
n'est pas un plan optimal de course ni une cible carburant.

## Avant de rouler

Ouvre PowerShell à la racine du projet :

```powershell
Set-Location 'F:\OneDrive\licor'
.venv\Scripts\python.exe scripts\build_paul_ricard_pilot_pack.py --verify-only --pack-dir .\data\processed\experimental\paul_ricard_prediction_validation_2026_09\pilot_pack_confirmation_01
.venv\Scripts\python.exe scripts\run_lmu_live_cues.py --doctor
```

Le premier contrôle vérifie le pack, ses sources et les séquences silencieuses.
Le second vérifie l'installation LMU ; hors simulateur, l'absence de mémoire
partagée est attendue. En session, la mémoire partagée doit être disponible.

Vérifie Paul Ricard, la LMP2 habituelle, 55 L au départ, une météo stable et
l'usure des pneus à zéro. Le setup est hors périmètre pour cette validation.
Garde l'enregistreur LMU `.duckdb` actif : le CSV live
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
Le lanceur le relit automatiquement et utilise le prochain tour comme premier
tour mesuré. Lance le programme avant le passage de la ligne de départ. L'option
`-FirstScoredLap` reste disponible pour planifier un départ plus tardif ; le
lanceur refuse un numéro déjà passé.

## Lancer le run

Utilise le lanceur `.cmd`, compatible avec les systèmes où l'exécution directe
des fichiers `.ps1` est désactivée :

```powershell
& .\data\processed\experimental\paul_ricard_prediction_validation_2026_09\pilot_pack_confirmation_01\start_pilot.cmd -ScoredLaps 5 -ConfirmTelemetryRecording -EmitSystemBeep
```

Le `.cmd` applique `ExecutionPolicy Bypass` uniquement au processus PowerShell
qu'il ouvre ; il ne modifie pas la politique de la machine ou de ton compte.
Choisis 5, 6 ou 7 tours. Le lanceur affiche le numéro absolu détecté et la séquence :

| Tours mesurés | Séquence après l'outlap |
| --- | --- |
| 5 | Push / LICO / Push / LICO / Push |
| 6 | Push / LICO / LICO / Push / Push / LICO |
| 7 | Push / LICO / LICO / Push / LICO / LICO / Push |

Le run de confirmation utilise cinq tours pour limiter le temps simulateur tout
en encadrant les deux tours LICO par des tours push. Les tours push sont automatiquement
silencieux. Sans `-EmitSystemBeep`, le programme journalise sans émettre de son :
ce mode sert aux vérifications, pas au pilote audio.

Le lanceur refuse maintenant de démarrer sans `-ConfirmTelemetryRecording`.
Ce drapeau atteste que tu as activé l'enregistreur LMU; il ne peut pas actionner
le contrôle du simulateur à ta place. Après le run, le lanceur cherche un nouveau
`.duckdb` dans `UserData\Telemetry` et inscrit automatiquement son chemin dans
les métadonnées de session lorsqu'il le trouve.

Termine le dernier tour mesuré et passe la ligne une fois pour clôturer les
mesures ; le programme s'arrête à l'entrée du tour suivant. `Ctrl+C` permet
d'interrompre. Un cue manqué ou une erreur ne nécessite pas de refaire tout le
run : note simplement le tour/la zone après la session.

## Après le run

Les résultats sont dans
`data/processed/experimental/paul_ricard_prediction_validation_2026_09/sessions/<RunId>/` :

- `events.csv` et son résumé : passages de cue, avec `cue_enabled=false` sur les
  tours push ;
- `telemetry.csv` : échantillons live, dont fuel, vitesse, pédales et tours ;
- `lap_schedule.csv` et `session_config.json` : séquence exacte, audio et hash du
  plan ;
- `run_metadata_template.json` : vérifier le chemin du `.duckdb` ajouté par le
  lanceur et compléter les incidents ou tours imparfaits ;
- `pack_manifest.json` : référence du pack exécuté.

Conserve le `.duckdb` et donne son chemin ainsi que le `RunId` à Codex. N'édite
pas le pack figé pour y mettre des notes : utilise les fichiers de session.

Lance ensuite l'analyse figée depuis la racine du projet. Pour le premier run à
six zones, la commande exacte est :

```powershell
.venv\Scripts\python.exe scripts\analyze_paul_ricard_live_validation.py --session-dir .\data\processed\experimental\paul_ricard_prediction_validation_2026_09\sessions\paul_pilot_20260909_220534
```

L'outil vérifie le hash du plan et la couverture des cues, reprojette la
distance avec la même méthode que le runtime, puis compare chaque tour LICO aux
tours push propres qui l'encadrent. Il écrit `lap_validation.csv`,
`zone_execution_observations.csv`, `zone_execution_summary.csv`,
`plan_used.csv`, `track_zones_used.json`, `validation_manifest.json` et
`validation_report.md` dans le sous-dossier `validation/`. Il score le plan
figé sans réestimer les courbes.

## Premier run six zones — résultat provisoire

La session `paul_pilot_20260909_220534` contient sept tours mesurés : push aux
tours absolus 13, 16 et 19; LICO aux tours 14, 15, 17 et 18. Les 24 cues attendus
ont été journalisés — six zones sur chacun des quatre tours LICO — et les 24
sont dans la tolérance. L'erreur absolue maximale de déclenchement est de
`1,331 m`.

Avec projection de distance et interpolation linéaire entre les push 13/16 ou
16/19, le résultat moyen par tour LICO est provisoirement de `0,1584 L`
économisé pour `0,3191 s` perdu. Le plan figé prédisait `0,12855 L` et
`0,37222 s`. Cet accord apparent reste descriptif : les métadonnées opérateur,
le `.duckdb` autoritatif et le débrief pilote manquent encore. Aucun refit n'est
autorisé à partir de cette session dans cet état.

Le pilote a confirmé avoir entendu les 24 bips. La validation opérationnelle
des cues passe donc. En revanche, l'enregistreur LMU n'était pas actif et aucun
`.duckdb` n'existe. Comme certains tours n'étaient pas propres sans que leurs
numéros puissent être identifiés, les chiffres fuel/temps ci-dessus sont
désormais classés descriptifs non scorables et aucun refit n'est autorisé.

Le CSV comporte aussi 24 interruptions d'échantillonnage de `0,100` à
`0,129 s`, chacune immédiatement après un cue audible. Elles proviennent de
l'ancien beep système bloquant. L'émission sonore a depuis été déplacée en
arrière-plan pour les futurs runs; cette correction ne répare pas les trous du
run déjà enregistré.

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

Le runtime projette la distance entre les mises à jour du scoring LMU à partir
de la vitesse live. Cette correction traite les sauts observés de 13 à 16 m
dans le premier run à deux zones; son replay ramenait ses six erreurs de cue à
une moyenne absolue de 0,68 m et un maximum de 1,51 m. Le run à six zones
confirme la couverture logicielle avec 24 cues dans la tolérance et un maximum
de 1,331 m; le débrief confirme que les 24 ont été entendus.

Enfin, rejouer les décisions adaptatives uniquement avec l'information passée
disponible à chaque tour. Cela permet d'examiner les changements proposés ; leur
gain réel ne peut pas être déduit des actions statiques effectivement conduites.

## Run de confirmation cinq tours

La session `paul_pilot_20260909_232207` couvre les tours absolus 22 à 26, avec
LICO aux tours 23 et 25. Le `.duckdb` natif a été trouvé et validé. Le pilote a
signalé une erreur à T1 et probablement à T13 pendant le premier tour LICO.
L'analyse exclut donc le tour23 du score tour complet, T01–T02/23 du score zone,
et prudemment T14/23 parce que l'erreur T13 peut contaminer son approche. Les
quatre autres zones du tour23 sont conservées.

Le tour LICO 25, seul tour LICO entièrement propre, mesure `0,1823 L` économisé
pour `0,6800 s` perdu contre `0,12855 L` et `0,37222 s` prédits. Dix observations
de zone sur douze restent incluses. Ce résultat est autoritatif mais trop petit
pour un refit; il sert de validation prospective tenue à l'écart du modèle. Le
pilote confirme avoir entendu les 12 bips. Le verdict réconcilié avec les quatre
runs historiques classe T03/T11 robustes pour le profil testé, T01–T02/T08–T09
prometteuses, T12 instable sur le coût temps et T14 insuffisante. La suite est
consignée dans le
[decision record du 10 septembre](decision_record_2026-09-10_cross_circuit.md).
