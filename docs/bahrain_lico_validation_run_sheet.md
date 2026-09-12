# Bahreïn circuit C — validation zéro-LICO-shot

Plan figé le 11 septembre 2026 avant toute observation LICO à Bahreïn. Cette
session teste six propositions transférées depuis Spa et Paul Ricard; elle ne
réentraîne rien pendant la conduite.

## Configuration

- Même Oreca 07 `LMP2_ELMS`, 55 L au départ, usure des pneus à 0.
- Météo constante et setup inchangé.
- Télémétrie native LMU `.duckdb` activée avant de lancer le script.
- Sept tours mesurés : `P / L / L / P / L / L / P`.
- Six zones sonores par tour LICO, donc **24 bips attendus**.

Les zones et distances de coast sont : T01–T03 `75 m`, T04 `60 m`, T08
`40 m`, T10 `65 m`, T11 `55 m` et T14–T15 `70 m`. Ces distances représentent
environ `0,35–0,47` de la distance de décélération push propre à chaque zone.
T05–T07 et T13 restent silencieuses dans ce premier bloc.

## Lancement

Depuis `F:\OneDrive\licor`, après avoir activé la télémétrie dans LMU :

```powershell
& .\data\processed\experimental\bahrain_lmp2_transfer_2026_09\lico_validation_pack_v1\start_lico_validation.cmd -ConfirmTelemetryRecording
```

Le wrapper `.cmd` utilise `ExecutionPolicy Bypass` uniquement pour ce lancement;
il ne modifie pas la politique PowerShell de Windows. Le script vérifie les
hashes du pack, détecte le prochain numéro de tour et affiche le calendrier
absolu avant le départ.

À chaque bip, relâcher complètement l'accélérateur, coasting jusqu'au point de
freinage push habituel, puis conduire le virage normalement. Les tours push ne
produisent aucun bip mais restent journalisés. Après le septième tour, le
runner s'arrête en entrant dans le tour suivant; rentrer aux stands, arrêter ou
exporter la télémétrie LMU, puis confirmer dans la fenêtre PowerShell.

## Retour demandé

Donner à Codex le `RunId` affiché, le nombre de bips entendus et toute erreur
avec le tour et le virage. Une erreur locale n'invalide pas automatiquement le
reste du tour. Le dossier de session conserve le plan, les prédictions gelées,
les logs de cue et la télémétrie LICOR parallèle.

## Interprétation préenregistrée

Le résultat sera comparé zone par zone aux trois tours push du même bloc et aux
références push précédentes. Le modèle central est une réponse monotone selon
le ratio physique; l'accélération au point de lift agit comme garde-fou et reste
en modèle shadow, car son interaction n'est pas encore identifiée avec seulement
Spa et Paul Ricard. Aucun seuil de réussite ne sera inventé après le run.
