# Circuit D — protocole prêt, choix du circuit en attente

Choisir parmi Imola, COTA, Sebring et Interlagos le circuit où le pilote peut
répéter cinq à sept tours avec une constance proche de Bahreïn. La diversité
des freinages départage les circuits qui passent ce critère. Ne pas appliquer
le pack Bahreïn à ce nouveau circuit.

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

Le lanceur et la fiche de session seront liés au circuit choisi avant le run.
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
