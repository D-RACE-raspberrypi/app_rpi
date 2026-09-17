# Navigation — fusion du suivi de personne et du lidar

> État au 16 septembre : le lidar et les moteurs sont maintenant reliés. Les mentions de fonctionnement uniquement consultatif ci-dessous décrivent les étapes précédentes. Le calcul seul reste sans propulsion ; « Démarrer le suivi réel » autorise le pilote séparé, avec expiration de session et de consigne. Voir [CONDUITE.md](../motor-control/CONDUITE.md). La manette reste hors intégration.


Ce module combine les deux applications importées dans `voiture-rc`.
Il calcule une **proposition** : arrêt, avance ou recul, vitesse signée et
braquage. Les caméras gauche/droite, la profondeur, la sélection de personne
et la carte lidar sont consultables dans une même interface.

Le lidar n'est pas encore connecté. Les tests actuels utilisent des scénarios
synthétiques. Ce module ne commande aucun moteur : la propulsion et la manette
sont hors périmètre, et le code C du servo reste inchangé.

## Tester maintenant sur le Mac

Python standard, sans nouvelle dépendance :

```bash
cd /Users/tm8/Documents/voiture-rc/autonomy
python3 server.py --demo
```

Ouvrir **http://127.0.0.1:8081**. Saisir la distance souhaitée, l'enregistrer puis
activer le calcul autonome. Les scénarios proposent : passage libre, obstacle
à droite, avant bloqué/arrière libre, arrière inconnu, voiture coincée, cible
perdue, lidar périmé et obstacle trop proche.

Le bandeau SIMULATION reste affiché. La cible est synthétique ; aucun flux caméra
n'est fabriqué. Les réglages démo sont enregistrés dans `config-demo.json`.
Un redémarrage repart toujours en mode manuel, sans reprise automatique d'une
ancienne manœuvre. Les scénarios sont statiques : le véhicule ne se déplace pas
réellement dans cette démonstration. Deux reculs peuvent donc aboutir à « bloqué ».

## Raccorder les vrais capteurs ensuite

Démarrer les applications existantes :

1. `stereo-depth/app/app.py` sur la Pi avec les deux caméras et le Hailo (port 8080).
2. `rplidar/app/viewer_server.py` (port 8765) et une acquisition `scan_test.py`
   selon le README lidar, **lorsque le lidar sera connecté**.
3. Démarrer le serveur de fusion, par exemple sur le Pi réunissant tout :

```bash
cd /chemin/voiture-rc/autonomy
python3 server.py --host 0.0.0.0 \
  --vision-url http://127.0.0.1:8080 \
  --lidar-url http://127.0.0.1:8765
```

Ouvrir `http://IP_DU_PI:8081`. Pour des capteurs sur deux Pi, remplacer les deux
URL par leurs adresses. Les URL sont définies au lancement, pas par des pages
externes. Le serveur reste sur le réseau local de confiance ; pas d'authentification.

Sans lidar : le flux de suivi et les vues caméra restent consultables, mais la
proposition autonome est **ARRÊT**. Les scans historiques importés avec le code
ne deviennent jamais des scans frais. L'âge du scan est vérifié à partir de son
timestamp Unix ; les horloges des Pi doivent être synchronisées. L'âge de la vision
vient de son API et est augmenté du temps écoulé localement et du trajet de requête.

Le proxy `/stream/left`, `/stream/right`, `/stream/depth` permet au navigateur de
consulter les flux via la machine de fusion. Les liens vers Stereo Studio donnent
accès aux réglages et à la calibration complets.

## Décisions

- Une personne doit être sélectionnée, visible et accompagnée d'une distance valide.
- La distance souhaitée est demandée dans l'interface ; aucune valeur n'est imposée
  pour un premier lancement réel. Elle appartient au module de fusion. Le curseur
  historique de distance dans Stereo Studio n'est pas la référence de cette fusion.
- Arrêt à la distance souhaitée, tolérance de 15 cm et hystérésis de reprise de 10 cm.
  Si la personne est trop proche, arrêt ; pas de recul automatique vers l'inconnu.
- Neuf braquages sont évalués entre les butées. Un modèle vélo génère des arcs,
  avec un disque englobant le véhicule et sa marge. Le déplacement du gabarit est
  testé dans les secteurs observés. Les inconnues ne sont jamais considérées libres.
- Parmi les arcs permis, le classement privilégie la cible, la longueur libre,
  l'éloignement des obstacles et la continuité du braquage. L'affichage et la sortie
  API utilisent **le même calcul Python**, pas les anciens scores du navigateur lidar.
- La vitesse proposée est limitée par la distance disponible pour s'arrêter et par
  l'écart à la distance de suivi. Les paramètres de freinage sont encore supposés.
- Si l'avant reste bloqué par un obstacle, arrêt d'au moins une seconde. Un recul
  n'est proposé que si son trajet arrière est observé libre. Le sens du braquage
  tient compte de la marche arrière.
- Recul limité à une seconde à 0,12 m/s par défaut, puis pause de 0,5 seconde avant
  changement de sens. Vérification de l'arrière à chaque nouveau calcul.
- Deux tentatives maximum par sélection/session, puis intervention manuelle.
  Une simple perte momentanée du capteur n'efface pas le compteur de tentatives.
- Obstacle dans le gabarit et sa marge, cible perdue, distance invalide, scan absent,
  périmé ou daté dans le futur : arrêt. Aucun recul aveugle pour « essayer ».

## Géométrie et limites connues

Valeurs provisoires fournies : **30 × 20 cm, lidar au milieu**. Empattement 20 cm,
braquage des roues ±25°, marge 10 cm : à mesurer dans les réglages.
L'origine de planification est le milieu entre les essieux, supposé au centre du
rectangle. Les offsets des capteurs sont réglables par rapport à ce centre.
Les coordonnées sont en mètres, avant positif, droite positive ; angles positifs
à droite. L'orientation de la caméra se règle dans Stereo Studio, celle du lidar
ici. Les deux repères doivent être vérifiés physiquement.

Le disque est volontairement conservateur : il peut refuser des passages étroits.
Les retours de chaque secteur de 2° sont réduits à leur minimum, avec inflation
pour l'échantillonnage des arcs. Ce n'est pas une reconstruction volumétrique :
le lidar ne voit que son plan, les obstacles mobiles et surplombants ne sont pas
prédits. Pas de SLAM, de carte, d'odométrie ni de garantie de sortir d'un cul-de-sac.

Les reculs sont bornés **en durée de proposition**, sans retour de déplacement.
Avant raccordement des moteurs, il faudra associer vitesse réelle, odométrie,
freinage mesuré et supervision de l'actionneur. La profondeur en mode essai reste
approximative ; `readiness` le signale. Même avec des paramètres confirmés,
`advisory_only` et `motor_control: false` restent imposés par cette version.

## API pour le groupe

Voir [CONTRACT.md](CONTRACT.md). L'API expose les modes pour que le module manette
puisse les utiliser plus tard. Aucun code PS4/Bluetooth/USB n'est ajouté.
Le serveur n'importe ni n'appelle `motor_ctl/servo_simple.c`.

## Vérification

```bash
cd /chemin/voiture-rc/autonomy
python3 -m unittest discover -s tests -v
```

Scénarios de suivi, évitement, hystérésis, recul, blocage, perte capteur, conversion
des repères et expiration des propositions. Essai terrain avec les deux capteurs
et la cinématique réelle restant à faire.

Le lidar réel regroupe au maximum trois tours distincts. Chaque tour expire au
bout de 0,6 s (ou avant si la limite d’âge configurée est inférieure). Le calcul
conserve le retour valide le plus proche par secteur ; les secteurs sans retour
sur les trois tours restent inconnus. L’âge affiché est celui du plus vieux tour
retenu. Cette accumulation n’est pas compensée par l’odométrie : elle sert au
montage de test immobile actuel et devra tenir compte du mouvement avant pilotage.

Les petits trous de mesure ne bloquent plus les trajectoires avant : leur part
maximale dans le passage vérifié retire jusqu’à 15 × cette proportion au score.
Au-delà de 35 % de secteurs inconnus, le passage reste refusé. Tout obstacle
mesuré reste bloquant, et le recul exige toujours des secteurs observés. Le
champ `unknown_fraction` et le motif affiché signalent une trajectoire incertaine.

Le curseur « Malus des zones sans mesure » règle `unknown_cost` de 0 à 100
(valeur initiale 15), sauvegardé dans config.json. Le malus effectif est
`unknown_cost × unknown_fraction`. Le seuil de refus 35 % est inchangé.
Les scores numériques apparaissent autour de la carte : rouge à vert pour le
classement relatif des candidats autorisés, gris pour les candidats refusés.
Ils ne représentent pas une probabilité de sécurité. Les candidats apparaissent
lorsque le calcul autonome est actif et qu’une cible valide est disponible.
Pi depuis le 11 septembre : http://10.215.12.49:8081/.

Deux autres curseurs sauvegardés règlent le score : `alignment_slope` (0–5,
initialement 1 point par degré d’écart à la cible) et `obstacle_cost` (0–5,
multiplicateur initial 1 du coût de proximité/manque de dégagement). Le bonus
angulaire vaut 50 − pente × écart absolu en degrés et peut devenir négatif.
Les collisions mesurées restent interdites même avec obstacle_cost=0.

Profil latéral des obstacles : `obstacle_x` (0–200, défaut 30) sur le rayon
candidat, `obstacle_y` (0–200, défaut 0) à 20 cm de ce rayon. Interpolation
linéaire, nulle au-delà de 20 cm ; si Y est non nul, la coupure est discontinue.
Les points derrière le rayon ou au-delà de horizon_m + rayon du gabarit en
projection longitudinale sont exclus. Le maximum des influences est multiplié
par obstacle_cost. Le bonus de longueur praticable et les collisions du gabarit
restent séparés. Les valeurs sont sauvegardées par les deux curseurs X/Y.

Le bonus de longueur praticable a été supprimé du score en avant et en recul.
La longueur sert toujours à vérifier la faisabilité et à limiter la vitesse.
Le score avant combine désormais le bonus angulaire, les malus obstacles et
inconnu, et la petite pénalité de changement de braquage existante.

Le seuil de 35 % d’inconnu est désormais supprimé en marche avant : la proportion
inconnue intervient uniquement dans unknown_penalty. Les collisions mesurées,
les scans absents/périmés et les scans sans aucune mesure valide restent bloquants.
Le recul conserve la nécessité d’observer le passage. Cette règle concerne les
propositions consultatives actuelles ; aucune commande moteur n’est envoyée.


## Nouveau calcul vers le point d’arrêt

La route verte est une suite de segments de braquage calculés par une recherche
hybrid A* bornée (1800 nœuds, 160 ms). Elle peut tourner, contre-braquer et revenir
vers le point situé à la distance de suivi de la personne. Le cercle cyan marque
ce point. La distance de suivi est mesurée depuis le centre du véhicule.
Le calcul affiche explicitement les routes partielles. L’ancien horizon est
renommé « Détour supplémentaire autorisé » et limite la longueur supplémentaire
du trajet, sans déplacer le point d’arrivée. Les obstacles après ce point n’ont
pas de coût de proximité ; une collision avec le gabarit reste toutefois testée.
Le calcul ne commande toujours aucun moteur. Les tests de détour sont effectués
sur des scans synthétiques ; le comportement sur voiture en mouvement n’est pas
validé, notamment la compensation des trois tours lidar et la dynamique du servo.
Voir CONTRACT.md pour les segments, leur repère et les limites d’exécution.

Sauvegarde antérieure complète de l’application :
`../backups/20260914T140422Z/voiture-rc-20260914T140422Z.tar.gz`, accompagnée
d’une copie extraite consultable et de la vérification SHA-256.

## Suivi du mouvement et stabilité — 15 septembre 2026

La navigation nécessite maintenant NumPy (paquet Raspberry Pi `python3-numpy`).
`imu.py` lit le MPU6500 sur I²C1/0x68. Sa calibration au repos est conservée dans
`imu-calibration.json` ; ne la réutiliser que pour le même capteur et montage.
La calibration choisit l’axe vertical et son signe à partir de la gravité ; un montage
incliné ou mobile est refusé. Relancer `python3 imu.py --calibrate`, service navigation
arrêté, si le montage change. Le gyroscope ne fournit pas une position absolue.

`odometry.py` aligne les scans consécutifs par ICP robuste avec une indication de
rotation du gyroscope. Les scènes trop pauvres, résidus élevés et déplacements
incohérents invalident le repère. Les trois tours sont compensés dans le repère du
dernier scan ; une rupture de localisation élimine les anciens tours. Il n’y a pas
encore de correction du mouvement à l’intérieur de chaque tour, ni de SLAM global.

La cible métrique est filtrée dans le repère odométrique, puis replacée devant la
voiture. Les distances « supérieures au maximum » restent des bornes, jamais des
mesures exactes filtrées. La trajectoire précédente est recalée puis entièrement
revérifiée avec les obstacles actuels. Elle reste préférée jusqu’à une amélioration
de coût de plus de 15 % + 0,05, à condition de rester à moins de 14 cm du nouveau but.
Aucun coût de champ de vision n’a été ajouté. En cas d’incertitude de localisation,
la mémoire de trajet est abandonnée et le calcul local reprend.

Le braquage proposé utilise Pure Pursuit (point anticipé à 16–28 cm depuis l’axe
arrière), à chaque cycle de fusion. L’arc effectivement commandé est contrôlé contre
les obstacles sur sa distance d’arrêt. Un arc non libre provoque un arrêt et un
nouveau calcul. La vitesse diminue dans les virages. API consultative uniquement,
TTL 300 ms inchangé ; aucun pilote des moteurs de la voiture n’est connecté.

La vision conserve pendant 60 secondes une mémoire OSNet de la personne sélectionnée,
distincte de l’ID numérique du tracker. OSNet produit une signature apprise de 512
valeurs (modèle Market1501 publié par Hailo, exécuté par OpenCV sur CPU). La
segmentation reste accélérée par Hailo. La comparaison par couleurs a été retirée
après constat de fausses correspondances sur le terrain.

Réassociation après six détections concordantes : similarité cosinus >= 0,92,
similarité à l’ancre d’origine >= 0,90, marge >= 0,12 par rapport au deuxième candidat
et aux personnes non sélectionnées mémorisées au moment du clic. L’ancre d’origine
est conservée. Au plus quatre personnes sont encodées par image ; si une personne
visible ne peut être encodée, la réassociation reste bloquée. Ces seuils sont
provisoires et conservateurs, pas des probabilités d’identité. Un changement marqué
de pose, l’occlusion ou des personnes très semblables peuvent encore empêcher ou
fausser une correspondance : validation en conditions réelles nécessaire.

Pendant la perte, la confirmation ou l’ambiguïté, l’intention est l’arrêt. Les états
`lost`, `confirming`, `ambiguous`, `reselect` sont affichés. Aucune extrapolation de
position n’autorise une avance sans cible confirmée visible. Désélection ou
modification de géométrie efface la mémoire. Les signatures restent en RAM.

Validation : 59 tests vision et 40 navigation sur le Pi, lecture réelle du gyroscope,
ICP sur scans réels. La précision dynamique et la ré-identification en situation réelle
restent à vérifier ; ce système n’est pas encore validé en conduite motorisée.

Essai utilisateur du 15 septembre : après remplacement par OSNet, la bonne personne est retrouvée lors du retour dans le champ. Validation qualitative ponctuelle ; les cas de foule, occlusion et conduite motorisée restent à tester.

## Seuil de similarité réglable — 16 septembre
Dans « Caméras et personne suivie », le curseur règle le seuil de retour de
0,50 à 0,99 (initialement 0,92). La valeur est persistée dans tracking.json sans
effacer la sélection en cours. Le suivi continu utilise seuil − 0,07 ; l’ancre
seuil − 0,12 en continu ou seuil − 0,02 au retour (plancher 0,50). Les marges
d’ambiguïté et les six confirmations restent actives. Le score observé n’est
pas une probabilité. API proxy POST /api/similarity : {similarity_threshold: nombre}.
Validation : 61 tests vision et 40 tests navigation.
