# Essai moteur sur banc

Source du groupe importée dans ../group-motor-controller, commit
dc3e03018471eb9669f0fa1cbf004174e498e97f.

Câblage confirmé : ESC GPIO12 (broche physique 32), direction GPIO13
(broche physique 33). Le lidar utilise GPIO27 (broche physique 13), distinct.

Le script bench_test.py conserve les formules du groupe : 50 Hz, neutre ESC
1 500 000 ns, vitesse relative pleine au rapport 2 et limitation 0,3 donnant
1 575 000 ns en avant et 1 425 000 ns en arrière. Ce ne sont pas des vitesses
mesurées en m/s. Centre servo 102 degrés = 1 566 666 ns, bornes 59–145 degrés.

Sans argument, le script affiche seulement les valeurs. --execute actionne
réellement les sorties : roues levées, personne présente avec coupure accessible,
aucun autre contrôleur moteur actif. L’essai est borné et repasse immédiatement
au neutre en fin normale ou sur SIGINT/SIGTERM. Une coupure brutale du processus
ou du système ne constitue pas une protection matérielle de l’ESC.

Essai exécuté le 16 septembre 2026 : séquence terminée sans erreur ; sorties
relues à 1 500 000 ns (ESC) et 1 566 666 ns (direction). Le résultat mécanique
nécessite l’observation de l’utilisateur.

La navigation reste consultative. Ne pas lancer le serveur UDP du dépôt tel
quel pour l’autonomie : le timeout réseau n’arrête pas le moteur et le code
mutile les messages au premier ':' avant de les transmettre au parseur.
Son installation configure aussi le réseau et n’a pas été exécutée sur le Pi.
La liaison autonome devra posséder un arrêt sur consigne périmée, un arbitrage
exclusif avec la manette et une validation du sens et de la vitesse réelle.
