# Sebring push — intake du 12 septembre 2026

Run `sebring_push_20260912_114122` : les cinq tours natifs 8–12 sont retenus
pour la conception des zones. Le pilote confirme aucune erreur notable.
Le tour 7 est un outlap partiel avec présence aux stands; le tour 13 commence
mais n'est pas clôturé. Pas de collecte push supplémentaire requise à ce stade.

## Contrôles et limites

- Durées entre événements Lap : 107,620 / 107,060 / 107,180 / 106,960 /
  107,380 s. Moyenne 107,240 s; écart-type échantillon 0,264 s; étendue 0,660 s.
  Ces durées diffèrent de quelques millisecondes de l'événement Lap Time.
- Consommation approximative moyenne : 3,0706 L/tour, premier moins dernier
  échantillon du tour. Ce n'est pas la mesure à distance fixe des futurs effets LICO.
- Les 25 couples tour/canal essentiel passent la couverture des bornes à deux
  périodes près et ne contiennent aucune valeur non finie. Pas de recul de
  distance >1 m ni de hausse d'essence >0,01 L entre échantillons.
- Aucun passage aux stands sur 8–12, aucun nouvel événement d'impact. Le signal
  d'impact est booléen ici : il ne mesure pas une magnitude physique.
- 48 segments de freinage; neuf freinages principaux (pic >=20 %) répétés sur
  chacun des cinq tours. Trois reprises légères génèrent des flags LICO dont
  le début est dans un freinage antérieur : aucune action LICO intentionnelle
  ne doit être ajoutée à la table ML à partir de ces flags.
- Les positions et vitesses des freinages sont exploratoires, avec distances
  alignées par asof pour la détection. Les minima de freinage ne sont pas des
  vitesses au point de corde. Aucun cue n'est autorisé par ces seules positions.
- La plage 5800–5900 m contrôle la coordonnée native de fin de tour observée;
  elle n'est pas une affirmation sur la longueur nominale du circuit.

## Données et reproduction

Copie dans `data/Sebring International Raceway_P_2026-09-12T15_41_46Z.duckdb`;
original conservé dans LMU. Empreintes SHA-256 identiques :
`8c29be2086faf8f790c0fe0de176527e8c6111f187ed3229799deba264708e13`.
Voiture native : Oreca 07 ELMS Custom Team 2025 #397, LMP2_ELMS.

Sidecar actif : `config/datasets/sebring_lmp2_circuit_d_reviewed_2026-09-12.json`.
L'ancien sidecar vide reste inchangé pour préserver le pack de collecte figé.
Validation des métadonnées : ready. Le manifeste de session d'origine reste intact.

```powershell
.venv\Scripts\python.exe scripts\inspect_sebring_push_run.py
```

Sorties : dossier `intake_v1` de la session, avec résumé des tours, profils
des canaux, événements, segments, revue des flags et repères exploratoires.
Le script et la source sont empreintés dans le manifeste d'intake.
L'analyse repose sur le pipeline existant et un script reproductible plutôt
que sur un notebook distinct. Aucun prétraitement ML ou ajustement de réponse
n'a été effectué. Les futurs résultats LICO de Sebring restent inconnus.

## Prochaine étape

Auditer les neuf approches et leurs sorties; calculer l'accélération aux points
de lift candidats et la décélération push de référence; distinguer capture en
amont et intensité de cue. Fixer les fenêtres de résultat et vérifier
`zone_start_zero_throttle`, puis geler les prédictions et le bloc P/A/B/P/B/A/P.
Les contrôles par zone sont en attente, pas implicitement validés par les tours.
55 L, usure nulle et météo constante restent les conditions du protocole pilote.

Présentation : comparaison de cinq tours par barres d'écart au meilleur du bloc,
axe zéro, une seule série, ordre chronologique. Pas de courbe de tendance inférée
à partir de ces cinq observations. Le rapport accompagne cette trace technique.
