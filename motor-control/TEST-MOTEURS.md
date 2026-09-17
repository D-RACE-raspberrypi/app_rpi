# Tester les moteurs indépendamment

Dans un terminal du Pi :

```sh
~/test_moteurs.sh
```

Mettre les roues motrices hors du sol, brancher une batterie chargée, allumer l’ESC
et garder sa coupure accessible. Ne pas lancer un autre contrôleur simultanément.
Écrire TEST puis Entrée. Le programme configure les sorties au neutre et attend
3 secondes pour l’ESC. Choisir un numéro puis Entrée :

- 1 : avancer au niveau 2 pendant 1 seconde, puis neutre.
- 2 : séquence frein/recul, puis neutre.
- 3 / 4 : petit mouvement de direction, puis centre.
- 5 : rester au neutre 3 secondes pour réarmer l’ESC.
- 0 : neutre et centre.
- d : durée de l’essai, de 0,1 à 3 secondes.
- q : quitter au neutre.

Ctrl+C interrompt l’essai et remet au neutre. « s » puis Entrée interrompt aussi
une impulsion en cours. Une coupure brutale du Pi ne remplace pas une coupure
électrique du moteur ; le logiciel ne peut garantir le comportement de l’ESC
sans signal.

Câblage : ESC GPIO12 = broche physique 32 ; direction GPIO13 = broche physique 33.
La broche physique 13 du lidar est distincte (GPIO27).
Les valeurs viennent du dépôt du groupe : 50 Hz, ESC 1500 µs au neutre,
1575 µs en avant et 1425 µs en arrière (niveau 2). Le code ne prétend pas mesurer
une vitesse en m/s. Les côtés de direction 3/4 restent à identifier sur le montage.

Fichier indépendant : /home/toto/voiture-rc/motor-control/test_moteurs.py.
Bibliothèque standard Python, pas de dépendance avec l’application ou la manette.
Pour vérifier seulement le menu, sans aucun signal matériel :

```sh
python3 ~/voiture-rc/motor-control/test_moteurs.py --simulation
```
