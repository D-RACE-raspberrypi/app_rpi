# Stereo Studio

Application locale pour Raspberry Pi 5 avec deux Camera Module 3, base de référence 60 mm. Interface en français sur `http://10.215.11.231:8080` (adapter l’adresse si le réseau change).

## Essayer sans calibration

Dans **Vue en direct**, cliquer sur **Activer le mode essai**. Les images réelles servent immédiatement au calcul avec une géométrie supposée : base de 60 mm, axes parallèles, centre optique au centre de l’image, distorsion nulle et focale de 500 pixels à 640 × 480. Cette focale est une hypothèse de visualisation, pas une caractéristique mesurée des Camera Module 3.

Les distances sont approximatives ; les exports sont nommés `stereo-depth-ESSAI.zip` et incluent les hypothèses dans leurs métadonnées. La couleur permet de tester les correspondances. Viser une scène détaillée, avec les deux caméras dans le même sens. Si la carte reste sombre, vérifier leur ordre G/D et leur alignement ; les corrections fines restent disponibles dans Réglages.

**Quitter le mode essai** réactive la calibration compatible chargée, s’il y en a une. Le mode essai ne remplace aucun fichier de calibration et son état est conservé au redémarrage. Une nouvelle calibration réussie quitte automatiquement le mode essai.

Si le rendu est bruité, ouvrir **Alignement manuel · caméra droite uniquement**. Sur un objet immobile avec des détails distinctifs, régler le décalage vertical et la rotation de l’image droite pour mettre un même détail sur la même ligne verte dans les deux vues. Le décalage horizontal doit être conservé. Ces corrections sont appliquées uniquement à l’image droite en mode essai et conservées au redémarrage. Un nombre positif de pixels descend l’image droite ; un angle positif la tourne dans le sens antihoraire. Vérifier plusieurs endroits de l’image : un simple décalage ne corrige pas toute la distorsion.

Le traitement vérifie désormais chaque correspondance dans les deux sens (gauche vers droite puis droite vers gauche, tolérance 1 pixel) et écarte les zones de faible texture. Cela réduit les fausses couleurs, mais peut augmenter les zones noires lorsque la géométrie ou la scène ne permettent pas une mesure. Des motifs répétitifs peuvent encore produire des correspondances erronées. Le profil Rapide réduit le coût de ce double calcul sur le Pi.

## Alignement manuel de la caméra droite

Dans **Vue en direct → Alignement manuel · caméra droite uniquement**, activer le mode essai. L’image gauche sert de référence fixe : elle est seulement redimensionnée selon le profil et ne subit aucune transformation d’alignement. Les six curseurs transforment exclusivement l’image droite :

- X : déplacement horizontal, ±160 pixels.
- Y : déplacement vertical, ±120 pixels.
- Z : zoom autour du centre, ±60 %. Ce n’est pas une translation physique en millimètres.
- RX / RY : inclinaisons de perspective, ±10°.
- RZ : rotation dans le plan de l’image, ±10°.

Les pixels sont exprimés à la résolution de référence 640 × 480 et adaptés automatiquement au profil Rapide. Les rotations RX/RY utilisent une focale supposée de 500 pixels. Les anciens offsets de pose stéréo TX/TY/TZ/RX/RY/RZ sont ignorés en mode essai pour garantir que la gauche reste fixe ; ils restent utilisables par le moteur de calibration mesurée.

Les changements sont appliqués en direct et sauvegardés automatiquement. **Remettre les corrections à zéro** restaure l’image droite sans transformation. **Superposer les images** affiche la gauche en vert et la droite en magenta ; le bouton permet de revenir à la comparaison côte à côte. Aligner les hauteurs et orientations des détails, sans supprimer toute la disparité horizontale qui porte l’information de profondeur.

Cet alignement visuel ne produit pas une calibration métrique : le zoom, les déplacements et la perspective peuvent modifier l’échelle et l’origine des disparités. Les distances demeurent indicatives. L’export en mode essai signale `metric_scale_valid=false` et enregistre l’homographie de l’image droite. La calibration au damier reste conservée et retrouve son fonctionnement lors de la sortie du mode essai.

## Sensibilité aux faibles détails

Au-dessus de la carte de profondeur, le curseur **Sensibilité aux faibles détails** ajuste le rejet des régions de faible contraste, en mode essai comme en mode calibré. À 0, le rejet est strict ; à 100, le filtre de texture est désactivé. Le réglage par défaut 50 conserve le comportement précédent. Une valeur plus élevée peut montrer davantage de surfaces peu contrastées, mais aussi davantage de bruit. Les contrôles de correspondance gauche/droite, d’unicité et de plage de distance restent actifs : une surface sans correspondance ne sera pas forcément remplie, même à 100. Le réglage est appliqué en direct, sauvegardé et inclus dans les exports.

## Orientation des images

Les deux vues, la comparaison côte à côte, la superposition et la profondeur sont retournées de 180° pour ce montage. La rotation est appliquée après le calcul stéréo : l’ordre des capteurs, les matrices de calibration et les offsets stockés sont conservés. Les tableaux de profondeur/disparité exportés et les coordonnées de clic suivent l’image affichée. Les métadonnées indiquent l’orientation et précisent que la disparité reste définie dans le repère de capture initial.

Les curseurs X/Y et RX/RY sont présentés dans le sens de l’image retournée ; leur signe affiché est inversé par rapport au réglage stocké, sans modifier l’alignement existant. Z et RZ gardent leur signe. `rotate_display` peut être remis à `false` dans `data/settings.json` puis le service redémarré si le montage est retourné physiquement. Le suivi futur d’une personne devra travailler sur la vue rectifiée gauche orientée comme la carte de profondeur, ou convertir explicitement ses coordonnées.

## Première calibration

1. Dans **Vue en direct**, identifier la caméra gauche et la droite (masquer brièvement un objectif). Corriger leur ordre dans **Réglages** si nécessaire. Les deux appareils doivent être orientés dans le même sens.
2. Fixer le montage et choisir une mise au point donnant des images nettes aux distances utiles. Ne plus toucher aux objectifs, aux nappes, au support ou à la mise au point après calibration.
3. Dans **Calibration**, ouvrir la mire : A4 paysage, impression à 100 %, sans mise à l’échelle. Le damier comporte 10 × 7 cases de 25 mm (9 × 6 coins intérieurs). Mesurer la taille réelle d’une case et la saisir dans l’application. Fixer la feuille sur un support plan.
4. Capturer 20 à 30 paires, avec des positions, distances et inclinaisons variées. Conserver le damier entier dans les deux vues et immobile pendant chaque capture. Minimum : 12 paires. Un décalage supérieur à 8 ms bloque la capture.
5. Calculer la calibration, lire les indicateurs RMS, écart vertical et base mesurée. Vérifier que les détails correspondants sont sur les mêmes lignes de la comparaison rectifiée.
6. Ouvrir **Vue en direct** pour afficher la profondeur. Un clic mesure la médiane dans un voisinage de 7 × 7 pixels. Vérifier plusieurs distances connues à la règle avant de s’appuyer sur les mesures.

Le calcul estime les paramètres optiques de chaque caméra ainsi que R et T. Les corrections Tx/Ty/Tz (mm) et Rx/Ry/Rz (degrés) complètent la pose calibrée ; elles ne remplacent pas la calibration au damier. Elles sont remises à zéro lors d’une nouvelle calibration. La base de 60 mm sert au contrôle et n’est pas imposée au solveur.

## Données et limites

- Profondeur Z dans le repère rectifié gauche, en mètres : ce n’est pas la distance radiale jusqu’à l’objectif.
- Export ZIP : tableau NumPy en mètres (NaN invalide), PNG 16 bits en millimètres (0 invalide), disparité, aperçus et métadonnées.
- La calibration et les réglages sont conservés dans `data/`. Les calibrations précédentes sont archivées dans `data/history/`. Les captures sont enregistrées mais la série de travail doit être recommencée après redémarrage.
- Le profil Rapide traite 384 × 288 ; Équilibré et Qualité traitent 640 × 480. Le filtre WLS du profil Qualité dépend d’OpenCV contrib.
- Surfaces unies, reflets, transparence, faible lumière et occultations donnent des zones invalides. La plage proche/lointaine filtre le résultat sans garantir cette portée.
- La synchronisation logicielle se stabilise après le démarrage. Les capteurs sont à obturation déroulante : limiter les mouvements rapides. Mise au point manuelle commune ; exposition automatique indépendante.
- L’interface n’a pas d’authentification et est prévue pour un réseau local de confiance.

## Raspberry Pi

Utiliser les paquets système compatibles avec libcamera/Picamera2 :

```sh
sudo apt-get install python3-picamera2 python3-opencv python3-flask python3-numpy python3-pytest
cd /home/toto/stereo-depth
python3 -m pytest -q
sudo install -m 644 stereo-depth.service /etc/systemd/system/stereo-depth.service
sudo systemctl daemon-reload
sudo systemctl enable --now stereo-depth
```

Diagnostic : `systemctl status stereo-depth`, `journalctl -u stereo-depth -n 60`, `rpicam-hello --list-cameras`. Arrêter le service avec `sudo systemctl stop stereo-depth` avant d’utiliser les caméras dans un autre programme. Toujours éteindre et débrancher l’alimentation du Pi avant de manipuler les nappes.

## Développement sur ordinateur

Créer un environnement Python, installer `requirements.txt`, puis lancer `python app.py --demo --host 127.0.0.1`. La simulation est explicitement signalée et n’autorise pas de calibration matérielle. Tests : `python -m pytest -q`.

Références : [Picamera2](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf), [caméras Raspberry Pi](https://www.raspberrypi.com/documentation/accessories/camera.html).

## Suivi de personne — AI Kit Hailo-8L

L'onglet **Suivi de personne** prépare l'observation sur la RC : YOLOv8 COCO
sur Hailo, association des personnes par Hailo Tracker (JDE), sélection au clic,
distance horizontale et angle de visée. **Aucune interface moteur** n'est appelée.
Le kit n'était pas monté au développement : les tests matériels restent à faire.
Il n'y a ni détection CPU de remplacement ni fausses détections en mode démo.

Après montage du kit (Pi éteint), sur le Pi :

```sh
cd /home/toto/stereo-depth
bash scripts/setup-hailo.sh
sudo reboot
# Après reconnexion :
hailortcli fw-control identify
```

Le script installe les paquets Raspberry Pi `hailo-all`, `hailo-models`,
`python3-hailort`, `python3-hailo-tappas`. Leur installation et le redémarrage
sont différés au montage du kit. Le modèle attendu est
`/usr/share/hailo-models/yolov8s_h8l.hef`, également accepté sous
`models/yolov8s_h8l.hef`. On peut définir `STEREO_HAILO_HEF` dans le service
pour un autre emplacement. Seul un HEF YOLOv8 COCO RGB, 80 classes, avec une
sortie Hailo NMS par classe est pris en charge. Le HEF doit correspondre au
Hailo-8L et aux versions HailoRT/pilote installées. Pas de compilation sur le Pi.
L'absence de matériel, modèle ou bindings est affichée ; nouvelle tentative
automatique toutes les 10 secondes. La vue stéréo continue à fonctionner.

### Utilisation et repères

1. Ouvrir **Suivi de personne** et sélectionner un cadre ou son bouton numéroté.
2. Régler la distance souhaitée et l'orientation de montage des caméras.
   Appuyer sur **Enregistrer**. Les réglages persistent ; la cible doit être
   resélectionnée après une modification ou un redémarrage.
3. Lire la distance horizontale, l'écart à la distance souhaitée et l'angle.
   Un angle positif indique la droite, négatif la gauche. 0° de correction
   signifie que l'axe optique gauche regarde dans l'axe du véhicule.
   Il s'agit d'une direction vers la cible, **pas d'un angle de braquage**.

L'IA reçoit la caméra gauche rectifiée et orientée à 180°, avec la profondeur
de la même capture. Une boîte aux lettres de capacité une image empêche
l'accumulation de retard. Les sorties incluent l'image correspondante ; le
navigateur dessine les cadres sur cette image précise. La conversion des rayons
annule la rectification et prend en compte le montage à 180°.

La distance utilise la médiane d'une région centrale du torse, avec au moins
20 pixels valides et 20 % de couverture. Les mélanges de profondeur et les
personnes fortement superposées invalident la distance. Une boîte de détection
n'est pas un masque de silhouette : une mesure du fond reste possible si la
personne ne couvre pas cette région. Vérifier avec des distances connues.
Le mode essai reste explicitement approximatif (distance **et** angle).

Une cible momentanément perdue conserve sa sélection pendant 2 secondes,
sans extrapoler de distance ni d'angle. Au-delà, une sélection manuelle est
nécessaire. Le suivi JDE peut changer d'identité en cas de croisement ou
d'occultation : cette version n'inclut pas OSNet/ReID et ne promet pas un
verrouillage sur un fragment du corps. Une image âgée de plus d'une seconde
ne fournit plus de mesures. Les corrections de géométrie invalident le suivi.

### API pour une intégration ultérieure

- `GET /api/following` : image JPEG base64 et détections synchronisées,
  `generation`, `sequence`, `age_s`, `fresh`, `approximate`, `selection_state`,
  `target`. `motor_control` est toujours faux.
- `POST /api/following/select` : `{"id": 7, "generation": 3}` ; `id: null`
  libère la cible. Une génération périmée est rejetée.
- `POST /api/following/settings` : champs partiels `enabled`, `confidence`,
  `target_m`, `camera_yaw_deg`.
- `target.distance_m` : distance horizontale caméra-personne ;
  `depth_z_m` : profondeur Z rectifiée ; `bearing_deg` : angle avec correction
  de montage ; `lateral_m` : droite positive ; `forward_m` : avant positif ;
  `distance_error_m` : positif si plus loin que la distance souhaitée.
  Une mesure absente est `null`, jamais zéro ni la dernière valeur connue.
  L'origine reste le centre de la caméra gauche, sans correction du décalage
  entre caméra et centre du véhicule.

Sources : [logiciels Raspberry Pi AI Kit](https://www.raspberrypi.com/documentation/computers/ai.html),
[Hailo Tracker Python](https://github.com/hailo-ai/hailo-apps-core/blob/master/core/hailo/plugins/python/hailo_python_api.cpp),
[configuration YOLOv8 Raspberry Pi](https://github.com/raspberrypi/rpicam-apps/blob/main/assets/hailo_yolov8_inference.json).
