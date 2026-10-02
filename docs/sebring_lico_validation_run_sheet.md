# Sebring — première validation LICO à deux intensités

Préparation depuis les cinq push propres `sebring_push_20260912_114122`.
Sept approches : T1, T3, T7, T10, T13, T15 et T17. Pas de bip à T5/T16 :
leur effet aval est inclus dans les fenêtres T3–T5 et T15–T16, sans compter
deux fois le même temps. Les numéros suivent le [plan officiel de Sebring](https://www.sebringraceway.com/track-maps/);
les distances sont exclusivement celles de la télémétrie LMU.

## Avant le départ

Même Oreca 07 LMP2, Sebring complet, **55 L au départ des stands**, usure des
pneus nulle, météo constante et setup inchangé. Activer l'enregistrement natif
LMU et vérifier qu'il fonctionne; le switch PowerShell ne l'active pas.
Entrer dans la voiture et rester immobile aux stands pendant le lancement.
Le circuit/la voiture sont à vérifier dans le jeu : le flux live actuel ne
permet pas au lanceur de contrôler automatiquement leur identité.

```powershell
Set-Location 'F:\OneDrive\licor'
& .\data\processed\experimental\sebring_lmp2_transfer_2026_09\lico_validation_pack_v1\start_lico_validation.cmd -ConfirmTelemetryRecording
```

Le lanceur vérifie le pack, détecte automatiquement le prochain numéro de tour
et affiche le calendrier absolu ainsi que le RunId. **Ne pas mettre 1 à la place
du numéro absolu.** Le prochain passage de ligne commence le premier push
compté : faire l'outlap et suivre les sept tours ci-dessous. Ne pas franchir
la ligne pendant que le lanceur se prépare.

## Sept tours comptés, 28 bips

| Tour relatif | Conduite | Bips |
|---|---|---:|
| 1 | Push | 0 |
| 2 | LICO A | 7 |
| 3 | LICO B | 7 |
| 4 | Push | 0 |
| 5 | LICO B | 7 |
| 6 | LICO A | 7 |
| 7 | Push | 0 |

À chaque bip : relâcher complètement, laisser rouler, puis freiner et conduire
le virage normalement. Ne pas compter une durée et ne pas chercher à reproduire
un nombre de mètres. A et B changent automatiquement le point du bip; **A n'est
pas systématiquement le tour faible et B le tour fort**. Ne pas forcer le
maintien d'une consigne si la situation demande une correction.

| Approche | Distance de lift visée A | Distance visée B |
|---|---:|---:|
| T1 | 35 m | 65 m |
| T3 | 70 m | 35 m |
| T7 | 45 m | 95 m |
| T10 | 80 m | 40 m |
| T13 | 30 m | 60 m |
| T15 | 75 m | 35 m |
| T17 | 50 m | 110 m |

Distances avant le freinage push médian, pas avant une borne arbitraire après
le point de corde. Le bip anticipe le lift visé de 0,35 s selon la vitesse
push locale; cette compensation reste une hypothèse opérationnelle, à vérifier
avec le lift réellement exécuté. Ne pas ajouter volontairement ce délai.

En cas d'erreur, conserver l'ordre prévu et noter le tour/virage/phase. Pas de
tour de remplacement ajouté au milieu de ce bloc. Franchir la ligne pour
clôturer le septième tour; les cues s'arrêtent automatiquement. Retourner aux
stands, arrêter/exporter la télémétrie et attendre la fin d'écriture avant
d'appuyer sur Entrée dans PowerShell. Transmettre le **RunId, nombre de bips
entendus et erreurs éventuelles**. Le lanceur conserve tous les fichiers.

## Ce qui est figé et ce qui ne l'est pas

Les prédictions principales utilisent le témoin monotone appris sur Spa,
Paul Ricard et Bahreïn, avec les cibles corrigées à distance fixe. Aucun résultat
LICO de Sebring n'est utilisé. Les observations sources et coefficients sont
figés dans le pack; les résultats ne prouvent pas encore un transfert réussi.
Sur les sept fenêtres additionnées, ce témoin prévoit environ **0,219 L pour
0,573 s en A**, et **0,238 L pour 0,623 s en B**. Ce sont des prédictions à
vérifier, pas des gains garantis ni des objectifs à atteindre au volant.
Les prédictions avec interaction d'accélération sont conservées séparément en
shadow. L'accélération push au point candidat sert déjà de garde-fou : ratio
de lift multiplié par accélération positive <=2,75547. Sa contribution
prédictive reste à tester; aucun ajustement n'a lieu en direct.

Les nouveaux endpoints de Sebring constituent une limite de transfert : T3/T15
incluent leur virage aval. La fenêtre T17 s'arrête à 5800 m, avant la ligne;
un reliquat après la ligne doit être montré séparément et non ajouté après coup
au score figé. Les trois push intercalés servent au score opérationnel. Pour
comparer l'apprentissage après 0/1/2 tours, garder les références du run push
antérieur et toujours réserver les tours relatifs 5/6. Cette comparaison dans
une même session ne prouve pas l'indépendance entre sessions.

## Capture en amont et contrôle hors jeu

L'audit conserve une approche jusqu'à 500 m quand la trace push permet de la
décrire. C'est une limite de recherche, pas une limite physique ni une consigne
de lift de 500 m. Les actions de cette run restent plus petites et dans les
garde-fous; aucune fenêtre après le point de corde ne normalise leur intensité.
Les brèves coupures de `Throttle Pos` lors de changements de rapport ne sont
pas confondues avec des lifts pilote : la disponibilité de l'approche est
contrôlée avec `Throttle Pos Unfiltered`, et l'accélération garde les effets
physiques réels. La corrélation capteur/vitesse est contrôlée par tour.

```powershell
.venv\Scripts\python.exe scripts\build_sebring_lico_validation_pack.py --verify-only
```

Le contrôle utilise un adaptateur audio silencieux et vérifie les 28 cues aux
bons couples tour/plan/zone. Pour reconstruire, choisir un nouveau dossier avec
`--pack-dir`; le script refuse de remplacer un pack figé. Les anciens packs
Bahreïn restent archivés; leur empreinte du runtime peut différer maintenant
que le support des plans A/B a été ajouté. Ne pas réécrire leurs manifestes.
