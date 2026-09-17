# D-RACE — application complète Raspberry Pi + PC

Caméras stéréo, profondeur, détection et suivi de personne, réidentification OSNet,
lidar, estimation du déplacement, planification et commandes manuelles/automatiques.
L’interface du PC affiche la caméra avec sélection de personne et la trajectoire.
La manette PS4 est connectée au **PC par Bluetooth** : le pavé tactile bascule les modes.

## Dossiers

| Dossier | Rôle |
|---|---|
| `stereo-depth/app` | Stereo Studio, calcul de profondeur, Hailo et OSNet, modèles, réglages actuels |
| `rplidar/app` | Acquisition UART du lidar, rotation et visualisation |
| `autonomy` | Fusion, odométrie lidar/IMU, trajectoires et arbitrage manuel/automatique |
| `motor-control` | Pilote PWM unique, surveillance des commandes et test indépendant |
| `pilot-app` | Application D-RACE à lancer sur le PC, manette Bluetooth |
| `deployment` | Services systemd et instructions d’installation |
| `group-motor-controller` | Sources manuelles du groupe servant de référence |
| `motor_ctl` | Ancien exemple de commande de direction |

## Ouvrir l’application sur le PC

Python 3 installé, depuis la racine :

```sh
python3 pilot-app/launch.py --pi 10.215.13.38
```

Sur Mac, double-cliquer sur `pilot-app/D-RACE.command`.
Ouvrir **http://localhost:8090/**, connecter la manette et appuyer sur un bouton.
Le serveur local relaie les données du Pi et permet au navigateur de lire la manette.
En cas de changement d’adresse, renseigner la nouvelle IP au lancement.

- Stick gauche : direction. R2 : avancer. L2 : frein / recul.
- Manuel / Automatique : boutons de l’interface ou pavé tactile.
- Le choix du mode n’active pas les moteurs : cliquer sur **Activer les commandes**.
- Au démarrage : trois secondes au neutre. Au changement de mode : relâcher les gâchettes.
- **ARRÊTER** désarme ; perte de connexion, manette ou onglet visible : expiration des commandes.
- Le calcul de trajet peut rester visible en manuel ; il ne commande pas les moteurs dans ce mode.

La commande utilise le **niveau 2 maximum** et la formule servo du dépôt du groupe
(59–145°, centre 102°). Ces angles concernent le servo, pas une mesure de l’angle des roues.

## Installation Raspberry Pi

Voir [deployment/INSTALL.md](deployment/INSTALL.md), puis
[pilot-app/README.md](pilot-app/README.md) pour le fonctionnement détaillé.
Les services fournis utilisent l’utilisateur `toto` et les emplacements historiques.
Les réglages actuels sont inclus : conserver sa propre calibration lors d’une mise à jour.

## Matériel du montage

- Raspberry Pi 5, deux caméras IMX708, écart de 65 mm ; inversion des caméras et rotation réglables.
- AI Kit Hailo-8L : YOLOv5n segmentation ; OSNet sur CPU pour la réidentification.
- IMU détectée comme MPU-6500, I²C1 : SDA GPIO2, SCL GPIO3.
- Lidar : UART3, TX Pi GPIO8 (broche 24) vers RX lidar ; RX Pi GPIO9 (broche 21) depuis TX lidar.
- CTRL rotation lidar : **GPIO27, broche 13**.
- ESC : **GPIO12, broche 32**. Servo : **GPIO13, broche 33**.
- PWM matériel recherché par adresse `1f00098000.pwm`, pas par numéro pwmchip supposé.

## État vérifié / limites

La caméra, le lidar et l’interface ont été vérifiés en direct ; l’utilisateur a confirmé
la reconnaissance Bluetooth de la manette et la bascule via pavé tactile.
Les tests logiciels de navigation/API et de commande moteurs ont passé sur le Pi.
Le programme de test indépendant peut bloquer le pilote s’il reste ouvert : quitter
avec `q` avant d’utiliser l’application. Le pilote affiche désormais explicitement ce conflit.

La direction physique et la conduite autonome au sol restent à valider. Les distances
stéréo en mode essai sont approximatives ; les vitesses proposées ne sont pas une mesure
réelle de vitesse. Commencer les essais moteurs roues levées.

## Origine

Sources du groupe : https://github.com/D-RACE-raspberrypi/demo-repository
(version consultée : `2d3b202`). Les modèles tiers restent soumis à leurs licences
respectives ; voir `stereo-depth/app/models/`. Aucune licence supplémentaire n’est
attribuée ici aux contributions des membres du groupe.

Les anciennes sauvegardes, images de test, journaux et caches ne sont pas versionnés.
Ce dépôt contient l’application et ses réglages, pas une image complète du système Pi.
