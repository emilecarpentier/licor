# Sebring — reprise de quatre tours ABAB

La première tentative `sebring_lico_20260912_132042` reste conservée. Le pilote
signale des passages LICO imparfaits et un dernier push abandonné après une
erreur T1. Les tours LICO ne sont pas étiquetés propres par défaut; leur revue
par zone reste à faire. Aucune prédiction ni intensité n'est modifiée.

## Arrêter la tentative précédente

Le lanceur attendait la clôture du tour absolu7 : le dernier état lu était
encore au tour7, voiture immobile. Appuyer une fois sur Ctrl+C dans sa fenêtre
PowerShell pour arrêter l'écoute, puis arrêter/exporter la télémétrie dans LMU.
Répondre à l'invite éventuelle. Si Ctrl+C rend directement la main, conserver
simplement les fichiers : la liaison manuelle restera possible. Ne pas lancer
de seconde écoute tant que la première tourne. Ne pas supprimer les logs.

## Nouvelle tentative

Repartir des stands avec 55 L, même LMP2, météo constante et usure nulle.
Activer un nouvel enregistrement natif, entrer dans la voiture et rester immobile
pendant le lancement. Faire l'outlap, puis **A / B / A / B**, sans push compté.
Sept bips par tour, 28 au total. Les points sont exactement ceux du pack initial.

```powershell
Set-Location 'F:\OneDrive\licor'
& .\data\processed\experimental\sebring_lmp2_transfer_2026_09\lico_abab_retry_pack_v1\start_lico_validation.cmd -ConfirmTelemetryRecording
```

Le prochain passage de ligne commence A. À chaque bip, relâcher complètement,
puis adapter le freinage à la vitesse réelle : le repère push est une référence,
pas une obligation de freiner à un endroit devenu inadapté. La stabilité du
passage prime sur la recherche d'un freinage tardif. Ne pas modifier soi-même
les distances de lift. Conserver les erreurs et les noter par tour/virage/phase.

Franchir la ligne pour clôturer le quatrième tour, puis rentrer et terminer la
télémétrie avant de répondre à l'invite PowerShell. En cas d'abandon, Ctrl+C
arrête l'écoute; une session incomplète ne doit pas être déclarée complète.
Transmettre le RunId `sebring_abab_...`, le nombre de bips et les erreurs.

## Portée de cette reprise

C'est une répétition des consignes et une familiarisation pilote, pas le
remplacement silencieux du test initial. Aucun modèle n'a été réappris. Sans
push intercalé, les anciens push servent de référence avec davantage
d'incertitude entre sessions, masses d'essence et apprentissage pilote. Les
résultats ne seront pas présentés comme une preuve isolée d'apprentissage ML.
Les manifestes du premier pack restent archivés; celui de reprise enregistre
explicitement quatre tours ABAB. Contrôle reproductible sans son :

```powershell
.venv\Scripts\python.exe scripts\build_sebring_abab_retry_pack.py --verify-only
```
