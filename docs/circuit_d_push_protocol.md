# Circuit D — Sebring, cinq tours push

Sebring est choisi le 12 septembre 2026 pour la constance attendue du pilote.
Utiliser le tracé complet des 12 Heures. Imola reste un test supplémentaire
possible. COTA est différé : sa diversité est intéressante, mais la variabilité
du pilotage, notamment dans le secteur 3, compliquerait l'évaluation initiale.
Ne pas appliquer le pack Bahreïn à ce nouveau circuit.

## Premier run : cinq tours push

- Même Oreca 07 LMP2, 55 L au départ des stands, usure des pneus à zéro.
- Météo maintenue constante par le pilote; setup inchangé pendant la run.
- Activer la télémétrie native LMU avant le départ et vérifier la création du
  nouveau `.duckdb` avant de consacrer les cinq tours à la mesure.
- Un outlap, puis cinq tours chronométrés push sans LICO volontaire. Les
  modulations normales de conduite sont permises. Jusqu'à deux remplacements
  si nécessaire; conserver tous les tours et toutes les notes d'erreur.
- Franchir la ligne après le dernier tour pour le clôturer. Attendre la fin
  d'écriture du DuckDB et noter immédiatement les erreurs par tour/virage.

## Commande avant le départ

Activer d'abord l'enregistrement natif dans LMU. Le switch ci-dessous confirme
cette action; il ne l'effectue pas et ne prouve pas que l'enregistrement tourne.

```powershell
Set-Location 'F:\OneDrive\licor'
.venv\Scripts\python.exe scripts\build_sebring_push_pack.py --verify-only
& .\data\processed\experimental\sebring_lmp2_transfer_2026_09\push_baseline_pack_v1\start_push_baseline.cmd -ConfirmTelemetryRecording
```

Si le pack n'existe pas sur une autre machine, le construire une fois avec
`.venv\Scripts\python.exe scripts\build_sebring_push_pack.py`.
Le lanceur `.cmd` limite le contournement de la politique PowerShell au processus
appelé; aucun changement permanent de la politique système n'est nécessaire.
Garder la fenêtre ouverte pendant le run. Après le dernier tour, arrêter/exporter
la télémétrie et attendre la fin d'écriture, puis appuyer sur Entrée dans cette
fenêtre. Le lanceur affiche le `RunId` (`sebring_push_...`), crée une fiche de
session et référence le fichier Sebring actualisé s'il est unique. Il ne déplace
ni ne supprime la télémétrie. Un fichier absent ou plusieurs candidats exigent
une liaison manuelle; aucune session n'est alors considérée validée.
Transmettre le RunId et les erreurs par numéro de tour affiché/virage/phase,
ou confirmer qu'il n'y a aucune erreur notable. Ne pas effacer les tours imparfaits.

Il n'y a aucun cue à cette étape. Aucune donnée LICO locale ne peut être utilisée
pour régler la première prédiction prospective.

## Travail LICOR après les push

1. Vérifier la qualité par phase et isoler les freinages répétés.
2. Auditer la capture en amont sur toute l'approche exploitable, en particulier
   avant les gros freinages; afficher la place disponible et les limites de
   recherche du détecteur séparément de l'action recommandée.
3. Calculer l'accélération push au point candidat, la distance de décélération,
   les vitesses d'arrivée/minimale et le soutien de chaque descripteur.
4. Fixer les fenêtres de résultat avant d'observer les effets LICO; identifier
   les sorties encore couplées à la zone suivante et les coûts tronqués.
5. Figer un bloc P/A/B/P/B/A/P à deux intensités conservatrices par zone,
   puis produire le lanceur spécifique et son préflight.

La réussite se juge sur la qualité des propositions, les erreurs essence/temps
sur les passages réservés et le gain obtenu après 0/1/2 tours locaux face au
témoin local seul. Une faible erreur sur une seule dose ne valide pas une
courbe complète ni une autorité adaptative live.
