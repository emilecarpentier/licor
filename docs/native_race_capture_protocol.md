# Prochain test : vérifier le budget de course natif LMU

## Dernier résultat : lecture visuelle hors ligne

**Décision ultérieure du pilote : OCR mis de côté.** Le prototype et les preuves
restent conservés pour pouvoir y revenir, mais son perfectionnement et son
intégration live ne sont plus la prochaine étape. La priorité est le test hors
ligne « courte qualification push -> plan LICO transféré », avec les données
natives disponibles. Voir la section active de `roadmap.md`. Ne pas relancer
automatiquement la collecte d'images ou demander une course pour l'OCR.

Le test vidéo est effectué; **aucune nouvelle run n'est demandée maintenant**.
Le lecteur expérimental n'alimente ni les bips, ni l'optimisation, ni le ML.
Les instructions de capture plus bas restent un protocole historique réutilisable,
pas une demande immédiate de retourner dans le jeu.

Sources : vidéo OBS `D:/OBS/2026-10-01 21-11-01.mp4`, images1920x1080 et
annotations manuelles. Le moteur Windows.Media.Ocr installé fonctionne sous
Windows PowerShell5.1, sans installation ni service distant. Les sorties sont
dans `data/processed/experimental/hud_ocr_v1/` et `hud_ocr_v2/`.

Reproductibilité des outils archivés : le lecteur PowerShell emploie le moteur
Windows, mais `inspect_race_video.cjs` requiert séparément Playwright/Chromium et
`build_hud_ocr_review_sheet.py` requiert Pillow. Ces dépendances optionnelles ne
font pas partie du pipeline LICOR natif et ne sont pas installées par ce lot.
Le rapport OCR archivé ne remplace pas les priorités actuelles de la roadmap.

- V1 : réglage sur35s, puis14 images réservées. Total exact3/14, autonomie8/14,
  les deux1/14. Les autres lectures sont absentes; aucune mauvaise valeur
  numérique acceptée dans ce petit échantillon.
- V2 : réglage sur35s et nouveaux horodatages choisis avant extraction. Sur14
  images visibles : total9/14, autonomie13/14, les deux9/14. Deux images sans HUD
  sont correctement rejetées. Le statut estimé/final reste inconnu sur12/14.
- Échantillons distincts mais même vidéo et proches voisins : ne pas conclure
  à une amélioration statistiquement établie ni à une fiabilité intersession.
  Aucun essai proche de1,0 tour d'autonomie, total à plusieurs chiffres, HUD
  déplacé, autre résolution ou capture écran temps réel.

V1 : widget supérieur `(1690,20,220,210)` en4x brut; essence
`(1635,1018,215,30)` en2x, pixels blancsRGB>180 convertis en noir sur blanc.
V2 : même essence; libellé `(1707,32,49,30)` rapproché des pixels blancs détectés
dans le champ numérique `x1770:1900,y32:62`, marge2px, fondRGB(18,20,28), zoom2x.
Contact d'un chiffre avec la limite horizontale : abstention. Le champ
`race_crop` V2 décrit le montage résultant, pas le rectangle source détecté.
Les pixels des chiffres ne sont pas synthétisés. Le parseur V2 ignore le texte
des litres précédant les parenthèses mais exige une autonomie décimale et
`laps`; ce contrôle n'est pas une garantie contre tous les faux positifs.

Les ambiguïtés `I/l` ou tirets restent signalées; aucun chiffre n'est corrigé,
aucune décimale insérée et aucune valeur ancienne reconduite. Les empreintes des
scripts du manifeste sont prises au moment de l'audit, pas certifiées à l'instant
d'extraction. Les sorties V1 initiales sont conservées. Les annotations V2 sont
dans `docs/evidence/bahrain_hud_ocr_holdout_v2.json` et le notebook de contrôle
est `notebooks/hud_ocr_feasibility.ipynb`.

Rejouer V2 dans un **nouveau dossier** (ne jamais écraser les preuves) :

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& .\scripts\read_hud_frames.ps1 -FramesDirectory 'data\processed\experimental\hud_ocr_v2\frames' -OutputDirectory 'data\processed\experimental\hud_ocr_v2\recheck' -Seconds 1,60,180,240,248,300,355,410,500,600,700,740,760,780,798,802 -Reader v2"
uv run python scripts/audit_hud_ocr.py --reference docs/evidence/bahrain_hud_ocr_holdout_v2.json --raw data/processed/experimental/hud_ocr_v2/development/raw.jsonl data/processed/experimental/hud_ocr_v2/recheck/raw.jsonl --output data/processed/experimental/hud_ocr_v2/recheck_audit
```

Piste conservée, uniquement si l'OCR est réactivé : stabiliser le marqueur
d'estimation et valider une nouvelle version sur
un échantillon encore réservé, puis contrôler fraîcheur/synchronisation avant
un journal live purement observateur. Les valeurs visibles restent arrondies;
la lecture OCR ne donne pas accès aux décimales internes du jeu et ne garantit
pas une arrivée avec0,1L. Aucun test de performance de capture live n'a été fait.

## Protocole de capture conservé

Statut : enregistreur diagnostic prêt pour validation dans le jeu. Aucun cue,
aucune adaptation, aucun changement des modèles. Ce test ne mesure pas la
qualité du transfert ML et ne requiert pas un nouveau circuit.

## Une session courte suffit pour commencer

Utiliser Sebring ou Bahrain, LMP2 habituelle, météo constante. Conserver 55 L
au départ de la course pour rester comparable aux essais précédents. Ne pas
chercher à terminer avec presque zéro essence. Activer aussi la télémétrie LMU
pour conserver le `.duckdb`; le journal natif ci-dessous est indépendant.

Configurer une course **chronométrée de 8 à 10 minutes**, idéalement avec des IA
et un tour de formation. Une qualification de 8–10 minutes avant la course est
utile si disponible dans cette session, mais facultative pour ce premier test.
Ne pas prolonger pour récolter un nombre imposé de tours propres.

1. Ouvrir LMU et la session. Dans PowerShell, vérifier :

   ```powershell
   Set-Location 'F:\OneDrive\licor'
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_native_race_capture.ps1 -Doctor
   ```

   La mémoire partagée doit être disponible. Si le doctor signale une erreur,
   transmettre sa sortie avant de faire le test.

2. Avant de rejoindre la piste ou la grille, lancer :

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_native_race_capture.ps1 -DurationMinutes 30
   ```

   Le contournement de politique concerne seulement ce processus PowerShell;
   aucune politique Windows permanente n'est modifiée. Ne pas lancer un script
   de bips en parallèle. Le journal reçoit un identifiant automatiquement.

3. Conduire normalement, sans LICO imposé. Aller jusqu'à **ta propre arrivée**,
   pas seulement jusqu'à l'expiration du chrono ou l'arrivée du meneur.
   Attendre environ 15 secondes après l'arrivée, puis Ctrl+C dans PowerShell.
   Le journal est sauvegardé même après cette interruption. Sinon l'enregistreur
   s'arrête après 30 minutes : il ne dépend pas d'un nombre de tours à terminer.
   Ne pas fermer brutalement la fenêtre : les lignes sont vidées à chaque
   écriture, mais le bilan final nécessite un arrêt normal ou Ctrl+C.

## Comparaison visuelle indispensable

Idéalement enregistrer une courte vidéo montrant le HUD, de la grille jusqu'à
l'arrivée. Ne pas manipuler de captures ni prendre de notes en conduisant.
Les points utiles sont : grille, formation, ligne des tours 1, 2 et 3,
expiration du chrono, dernier passage de ligne et arrivée.

À ces points, conserver la valeur exacte du HUD supérieur (`Lap X/Y.y`) et
l'autonomie carburant inférieure (`Z.z` tours). Une vidéo permet de les relever
après coup et de synchroniser par changement du compteur de tour. Si aucune
vidéo n'est possible, transmettre les valeurs dont tu te souviens, en les
signalant approximatives; les conventions non observées resteront à vérifier.

Après le test : dire « terminé », le circuit, si la course a atteint son arrivée,
et signaler trafic important, sortie de piste, pause, arrêt aux stands ou reset.
Joindre la vidéo/captures si disponibles. Il n'est pas nécessaire de mémoriser
le run ID : les dossiers horodatés sont sous
`data/processed/experimental/native_race_capture/`.

## Ce que nous validerons ensuite

- Identité du joueur et du meneur global, phases de course, compteurs de tours,
  carburant réel et évolution des horloges.
- Relation entre HUD fractionnaire, nombre de tours effectivement terminés,
  expiration du temps et drapeau final; aucune règle d'arrondi présupposée.
- Variation d'autonomie du HUD face à la consommation mesurée à la ligne.
- Les changements de contexte, gels et éventuels décalages télémétrie/scoring
  avant toute utilisation dans un replay de budget.

Une deuxième courte course n'est demandée que si un cas reste ambigu (par
exemple un tour de retard ou un changement de meneur). Le prochain circuit
pour tester le démarrage ML depuis la qualification sera choisi après ce verrou;
ce protocole n'active pas encore cette optimisation.

## Contrat technique et limites

`samples.jsonl` : diagnostic à 5 Hz avec UTC et temps depuis lancement,
horloges natives scoring/télémétrie, piste/session/phases, joueur appairé par ID
unique et `is_player`, meneur de position globale 1. Tours courants et tours
complétés restent deux champs différents. Absence ou ambiguïté => joueur null.
`hud_total_laps` et `hud_fuel_laps` restent null : aucune lecture exacte de ces
affichages n'a été établie. `max_laps_raw` n'est pas leur remplacement.

`manifest.json` : mode lecture seule, compteur d'échantillons et motif d'arrêt.
`running` après fermeture forcée ne signifie pas capture complète. Les dossiers
existants ne sont jamais réutilisés. Aucun fichier source n'est déplacé.

Le snapshot utilise la copie mémoire existante, non atomique entre producteurs;
les horloges conservées permettent un audit, pas une garantie de synchronisme.
Les répétitions de clocks sont signalées, mais cela ne prouve pas la fraîcheur
individuelle de chaque champ. Les changements de session/reculs de compteurs et
ravitaillements doivent être segmentés hors ligne avant de mesurer la consommation.
Les valeurs non finies deviennent null, jamais zéro. Aucun de ces journaux bruts
n'est directement une observation ML ni une entrée prête du contrôleur budget.
L'arrêt se fait par durée/Ctrl+C, pas par interprétation encore non validée des
flags de fin. Aucune réserve carburant n'est choisie par cet outil.

## Suite logicielle réalisée après la course de Bahrain

Le replay hors ligne `scripts/replay_native_race_context.py` prend `--samples`
(le JSONL d'origine) et `--output` (un nouveau dossier). Il conserve les sources,
refuse d'écraser un dossier existant, exporte les transitions et passages de
ligne et inscrit le SHA256 source dans son manifeste. Aucun bip, apprentissage
ou changement de plan. Les accidents des derniers tours restent exclus de
l'apprentissage; leur rythme observé peut servir au diagnostic de fin de course,
sans devenir une référence push propre.

Contrôle d'accès à la valeur HUD : absente des 3899 échantillons de cette course,
du schéma télémétrique inspecté et des champs SDK examinés. Le maximum natif vaut
2147483647 ici, pas 6.5. Cela ne démontre pas qu'aucune autre interface LMU ne
peut l'exposer; aucune route alternative n'est encore vérifiée. Les annotations
vidéo restent une source manuelle distincte et ne sont pas injectées dans le flux.

Le nouveau calcul LICOR utilise seulement les passages déjà observés du joueur
et du meneur pour une projection à rythme constant, à partir du deuxième tour
complet observé. Il ne reproduit pas la formule du HUD et ne fournit pas encore
la borne prudente nécessaire au budget carburant. L'intégration opérationnelle
reste donc bloquée volontairement sur cette borne, pas sur une nouvelle collecte
de tours propres. Prochaine étape : borner les scénarios de rythme/tour
supplémentaire et le démarrage depuis la qualification, puis rejouer le budget.

### Mise à jour : choix du risque et piste d'accès REST

La branche longue ne sera pas imposée : un nouveau comparateur de budgets
conditionnels conserve les deux options et laisse le choix au pilote. Le replay
natif exporte également un seuil de basculement du nombre de tours du leader,
sans confondre ce nombre avec celui du joueur ni modifier les cues.

Le mainteneur de [go-lmu-api](https://github.com/snipem/go-lmu-api) documente la
lecture du schéma via `GET http://localhost:6397/swagger-schema.json`. Ses modèles
de réponse sont inférés depuis un état du jeu et ne constituent pas un inventaire
exhaustif. Un unique GET local de ce schéma, avec délai maximal de4s, a reçu une
connexion refusée pendant notre vérification. Aucun jeu lancé ni réglage modifié.
La valeur exacte du HUD reste non raccordée, pas déclarée impossible à obtenir.

Quand LMU sera ouvert, lire ce schéma puis inspecter uniquement des endpoints
de données attestés et pertinents. Ne pas lancer le générateur tiers ni parcourir
tous les GET : certains peuvent déclencher une action. Aucun branchement live
sans comparaison du champ candidat avec le HUD dans la même session. Il n'est
pas nécessaire de refaire une course complète pour cette découverte d'interface.
