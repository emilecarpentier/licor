# Bahreïn circuit C — collecte de cinq tours push

Protocole figé le 10 septembre 2026. Cette session sert uniquement à décrire
le circuit avant toute observation LICO locale. Aucun plan LICO, cue ou beep
n'est utilisé pendant cette collecte.

## Configuration figée

- Circuit : Bahrain International Circuit, tracé Grand Prix standard.
- Voiture : Oreca 07, classe `LMP2_ELMS`, la même que pour Spa et Paul Ricard.
- Session : essais libres sans trafic contrôlé par le pilote.
- Essence au départ des stands : `55 L`.
- Usure des pneus : désactivée (`0`).
- Météo : constante pendant toute la session.
- Setup : inchangé pendant la session; noter son nom s'il existe, sinon
  `constant_not_recorded`.
- Stratégie : full push, sans LICO volontaire.
- Télémétrie LMU native `.duckdb` : activée avant de quitter les stands.

`Full push` signifie qu'il ne faut pas relâcher volontairement en avance pour
économiser du carburant. Les modulations d'accélérateur nécessaires pour
conduire les virages normalement restent permises.

## Préparer et lancer la session

Le pack push ne lance aucun cue, aucun son et aucune télémétrie LICOR parallèle.
Il crée seulement le dossier de session et lie le nouveau fichier LMU après le
run. Depuis la racine du projet :

```powershell
.venv\Scripts\python.exe scripts\build_bahrain_push_pack.py --verify-only
& .\data\processed\experimental\bahrain_lmp2_transfer_2026_09\push_baseline_pack_v1\start_push_baseline.cmd -ConfirmTelemetryRecording
```

Le premier appel vérifie l'intégrité du pack. Le second utilise un wrapper
`.cmd`, donc il fonctionne même lorsque PowerShell interdit l'exécution directe
des scripts `.ps1`. `-ConfirmTelemetryRecording` atteste que l'enregistreur LMU
est réellement activé; le lanceur ne peut pas l'activer à ta place.

Laisse la fenêtre ouverte pendant la conduite. Après le dernier tour, reviens-y
et appuie sur Entrée : le lanceur cherchera le nouveau `.duckdb` et conservera
son chemin dans le dossier de session.

## Séquence de conduite

1. Faire l'outlap normalement et préparer les pneus et freins de manière
   répétable.
2. Passer la ligne et conduire cinq tours chronométrés push consécutifs.
3. En cas d'erreur, ne pas supprimer ni cacher le tour. Noter le tour et le
   virage, puis continuer jusqu'à obtenir cinq tours propres, avec un maximum
   de sept tours chronométrés.
4. Après le dernier tour, repasser la ligne pour le clôturer, puis rentrer aux
   stands et attendre que l'enregistreur ait terminé d'écrire le `.duckdb`.

Ne pas remettre d'essence, changer de setup, modifier la météo ou entrer aux
stands entre les tours mesurés. Le pack de métadonnées peut rester ouvert, mais
aucun live cue ne tourne pendant cette première session.

## Définition d'un tour propre

Un tour entier est propre s'il ne contient pas :

- d'impact, tête-à-queue ou sortie de piste significative;
- de point de freinage clairement manqué;
- de ralentissement inhabituel ou d'interruption comparable à du trafic;
- de passage aux stands ou limiteur;
- de LICO ou coast volontaire avant un freinage.

Une erreur localisée ne rend pas automatiquement inutiles toutes les autres
zones du tour. Note précisément le virage : l'intake pourra exclure la zone
contaminée tout en conservant les autres, mais la cible reste cinq tours
entièrement propres.

## Notes à prendre immédiatement

Après la session, conserver une note courte sous cette forme :

```text
Nombre de tours chronométrés :
Tours entièrement propres :
Erreurs ou doutes : tour relatif + virage + description
Setup :
Météo restée constante : oui/non
55 L au départ : oui/non
Usure des pneus à 0 : oui/non
```

Les numéros relatifs suffisent si les numéros absolus ne sont pas visibles. Ils
seront réconciliés avec le fichier natif.

## Fichier à remettre au projet

Le résultat obligatoire est le nouveau `.duckdb` LMU. Pour retrouver les
fichiers récents après la session :

```powershell
Get-ChildItem 'C:\Program Files (x86)\Steam\steamapps\common\Le Mans Ultimate\UserData\Telemetry' -Filter *.duckdb |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 3 FullName, Length, LastWriteTime
```

Copier le fichier dans `F:\OneDrive\licor\data\` sans modifier l'original,
puis donner à Codex son nom et les notes de conduite. Ne pas renommer un ancien
fichier pour le faire passer pour ce run.

Le lanceur crée aussi
`data/processed/experimental/bahrain_lmp2_transfer_2026_09/sessions/<RunId>/`
avec `run_metadata_template.json`, `lap_notes_template.csv` et la copie du
manifeste exécuté. Complète les notes si possible; sinon indique les erreurs à
Codex directement.

## Contrôles d'intake préenregistrés

Avant toute prédiction LICO, LICOR vérifiera :

- circuit, tracé, voiture, classe et session dans les métadonnées natives;
- présence des canaux carburant, distance, vitesse, accélérateur et frein;
- présence et cohérence du canal d'accélération LMU avec la dérivée de vitesse;
- au moins cinq tours push complets retenus après la revue pilote;
- stabilité du carburant par tour, du temps au tour, des points de freinage et
  des profils d'accélération par zone;
- impacts, pits, trous d'échantillonnage et anomalies de couverture;
- absence de LICO détecté dans les passages utilisés comme références push.

Une fois ces contrôles passés, les zones Bahreïn seront proposées depuis la
télémétrie push. Les prédictions zéro-LICO-shot seront alors générées et gelées
avant le bloc suivant `P / L / L / P / L / L / P`.
