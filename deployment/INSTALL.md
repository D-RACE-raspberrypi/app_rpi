# Installer sur le Pi du montage

Raspberry Pi OS 64 bits, utilisateur `toto`. Ces instructions conservent les
emplacements des services existants. Adapter les chemins et User= si nécessaire.

## Dépendances

```sh
sudo apt update
sudo apt install python3-flask python3-numpy python3-opencv python3-picamera2 python3-serial python3-gpiozero python3-lgpio python3-pytest python3-gi gir1.2-gstreamer-1.0 rsync git
sudo apt install hailo-all hailo-models python3-hailort python3-hailo-tappas
```

Les paquets Hailo doivent venir du dépôt compatible avec la version de Raspberry
Pi OS. Vérifier `hailortcli fw-control identify` et `python3 -c 'import hailo'`.
La segmentation utilise le plugin GStreamer `hailonet`, le post-traitement
`/usr/lib/aarch64-linux-gnu/hailo/tappas/post_processes/libyolov5seg_post.so`
et le modèle YOLOv5n Hailo-8L fourni. Les variantes Hailo-8 nécessitent leur HEF adapté.

## Matériel et overlays

Dans `/boot/firmware/config.txt`, fusionner les réglages suivants avec ceux du
montage (ne pas écraser le fichier complet), puis redémarrer le Pi :

```ini
dtparam=i2c_arm=on
dtparam=spi=off
dtoverlay=uart3-pi5
dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4
```

Vérifier la présence de `/dev/ttyAMA3`, `/dev/i2c-1` et du contrôleur PWM
`1f00098000.pwm`. Le lidar et la voiture utilisent des GPIO distincts : voir README.
Les réglages stéréo fournis correspondent au montage de 65 mm et doivent être
ajustés si les caméras ou leur pose changent.

## Fichiers et services

Depuis le dépôt cloné sur le Pi :

```sh
mkdir -p /home/toto/voiture-rc /home/toto/stereo-depth
rsync -a autonomy rplidar motor-control pilot-app deployment /home/toto/voiture-rc/
rsync -a --exclude data/ stereo-depth/app/ /home/toto/stereo-depth/
# Sur une nouvelle installation uniquement, copier les réglages fournis :
# cp -r stereo-depth/app/data /home/toto/stereo-depth/
sudo mkdir -p /usr/share/hailo-models
sudo cp stereo-depth/app/models/yolov5n_seg_h8l_mz.hef stereo-depth/app/models/yolov5seg.json /usr/share/hailo-models/
sudo cp deployment/*.service /etc/systemd/system/
sudo systemctl daemon-reload
```

Avant mise à jour, sauvegarder les réglages locaux (`data/`, `autonomy/config.json`,
`drive-config.json`, `imu-calibration.json`) : la première commande rsync peut
remplacer la configuration de navigation. Ne pas lancer deux programmes moteurs.
Le pilote de conduite et le programme de test partagent un verrou exclusif.

Quand le matériel est prêt :

```sh
sudo systemctl enable --now stereo-depth rc-lidar-scan rc-lidar-viewer rc-navigation rc-motor-drive
```

Cette commande démarre les caméras et **la rotation du lidar**. Le pilote de la
voiture démarre désarmé. L’interface du Pi est sur le port 8081 ; le PC se connecte
avec `pilot-app/launch.py`. Le point d’accès Wi-Fi du dépôt du groupe n’est pas requis.

Arrêt : `sudo systemctl stop rc-motor-drive` ; arrêt rotation lidar :
`sudo systemctl stop rc-lidar-scan`.

## Tests sans propulsion

```sh
(cd autonomy && python3 -m unittest discover -s tests)
(cd motor-control && python3 -m unittest discover -p 'test_*.py')
(cd stereo-depth/app && python3 -m pytest tests)
```

Le programme indépendant `sudo python3 motor-control/test_moteurs.py` actionne
réellement le matériel après validation TEST. Quitter avec `q` avant le pilotage.

## Correction PWM qui a débloqué le montage

Le fichier [boot-config.fragment.txt](boot-config.fragment.txt) contient les lignes
vérifiées sur le Pi. La ligne indispensable est :

```ini
dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4
```

Avant cette correction, seul le bloc `1f0009c000.pwm` était exposé : écrire dans
son canal 1 ne commandait pas le signal PWM0 du GPIO13. `pinctrl set 13 a0` ne
suffisait donc pas. Après application de l’overlay et redémarrage, le montage a :

```text
pwmchip0 -> 1f00098000.pwm  (PWM0, utilisé)
pwmchip1 -> 1f0009c000.pwm  (autre bloc)
GPIO12 -> PWM0_CHAN0 -> ESC, broche physique 32
GPIO13 -> PWM0_CHAN1 -> servo, broche physique 33
```

Le numéro pwmchip peut changer : le pilote recherche l’adresse matérielle.
Période : 20 000 000 ns (50 Hz). Neutre ESC : 1 500 000 ns.
Direction du dépôt : minimum 1 327 777 ns, centre 1 566 666 ns, maximum 1 805 555 ns.
Le centre demandé de 102° correspond à la formule du groupe ; vérifier son
alignement physique. Aucun changement du rapport PWM n’est nécessaire dans le boot.

Diagnostic **sans mouvement et sans modification** :

```sh
python3 deployment/check-pwm.py
```

Une sortie PWM déclarée active ne valide pas l’alimentation, le câblage ni le servo.
