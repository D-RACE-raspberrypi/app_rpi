# Déploiement sur le Pi des caméras — 10 septembre 2026

Pi : `toto@10.215.13.209`.

- Lidar RX : broche physique 24, BCM8 / TXD3.
- Lidar TX : broche physique 21, BCM9 / RXD3.
- Rotation lidar : BCM27, PWM 800 Hz, 70 %.
- SPI0 désactivé, overlay `uart3-pi5` activé ; port `/dev/ttyAMA3` à 115200 bauds.
- Sauvegarde boot : `/boot/firmware/config.txt.before-lidar-20260910-110405`.

Services activés au démarrage : `stereo-depth`, `rc-lidar-scan`,
`rc-lidar-viewer`, `rc-navigation`. La navigation démarre en mode manuel.

Tableau de bord : http://10.215.13.209:8081 ; vision : port 8080 ; lidar : port 8765.
Vision dans `/home/toto/stereo-depth`, lidar et fusion dans `/home/toto/voiture-rc`.
Les réglages de calibration vision existants sont conservés.

Validation : 17 tours de test vers 5 Hz, zéro octet rejeté ; acquisition continue
et détection Hailo vérifiées via API ; 16 tests de navigation réussis sur le Pi.
Les sorties de navigation sont uniquement consultatives : aucun moteur de la
voiture n’est commandé. Distance de suivi à saisir, personne à sélectionner,
puis calcul autonome à activer dans l’interface. Les dimensions précises,
l’empattement et l’orientation du lidar restent à vérifier sur le montage final.

Arrêter la rotation du lidar : `sudo systemctl stop rc-lidar-scan`.
Relancer : `sudo systemctl start rc-lidar-scan`.
État : `systemctl status rc-lidar-scan rc-lidar-viewer rc-navigation`.

## Matériel vérifié le 15 septembre 2026

Pi : 10.215.12.145. IMU sur I²C1, SDA GPIO2 et SCL GPIO3.
Adresse 0x68, WHO_AM_I 0x70 : identifiant MPU-6500. Lecture des six axes vérifiée.
Calibration au repos enregistrée dans autonomy/imu-calibration.json : axe vertical Z inversé. Gyroscope utilisé comme indication de rotation pour le recalage lidar ; position locale estimée par ICP. Recalibrer si le montage change.
PWM du lidar déplacé vers BCM27 (broche physique 13), 800 Hz, 70 %.
Rotation confirmée ensuite par l’utilisateur ; réception vérifiée : scan âgé de 0,16 s, 375 points dont 190 valides. Services lidar et navigation actifs.
Décision utilisateur : aucun coût de sortie du champ caméra dans le score de trajectoire.

16 septembre : essai de rotation déplacé vers GPIO27 (broche physique 13), Pi 10.215.12.70. Absence de réponse UART constatée avant ce changement ; une panne de GPIO18 n’est pas établie.
