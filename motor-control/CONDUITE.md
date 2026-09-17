# Liaison navigation → moteurs

Ouvrir http://10.215.13.38:8081/, sélectionner la personne, régler la distance,
puis « Démarrer le suivi réel ». L’ESC reste trois secondes au neutre avant
les commandes. « ARRÊTER LES MOTEURS » désarme et remet le calcul en mode manuel.
Un premier essai roues levées permet de vérifier le comportement sans déplacement.
La manette du groupe n’est pas reliée à cet arrêt : ne pas lancer son serveur
en même temps. Aucun réseau Wi-Fi du groupe n’a été reconfiguré.

## Fonctionnement
- Service root rc-motor-drive, démarrage désarmé. La navigation reste sous toto.
- Détection du périphérique **1f00098000.pwm**, jamais d’hypothèse sur pwmchip0.
- GPIO12/broche 32 : ESC. GPIO13/broche 33 : direction. PWM 50 Hz.
- Neutre ESC 1500 µs ; excursion maximale ±75 µs, correspondant au niveau 2
  et à la limitation 0,3 du dépôt du groupe. L’effort varie avec la consigne,
  sans saut vers une puissance minimale. Une faible consigne peut donc être
  sous le seuil de démarrage réel du moteur. La vitesse en m/s n’est pas calibrée.
- Servo : formule du dépôt restaurée, 59–145°, centre 102° (1 566,666 µs). Le centrage physique reste à vérifier. Signe + confirmé à droite par l’utilisateur.
- Séquence de freinage/recul non bloquante, interrompue immédiatement par l’arrêt.
  Le planificateur ne décompte la durée de recul qu’après cette séquence.
- Surveillance des consignes toutes les 20 ms, dans une boucle indépendante de
  la récupération HTTP. Consigne périmée au-delà de 300 ms → neutre.
- Autorisation de l’onglet renouvelée toutes les 400 ms, expire après 1,5 s.
  Onglet masqué/fermé : demande de désarmement ; perte de liaison : expiration.
- Cible perdue, profondeur absente, lidar périmé ou localisation invalide : arrêt.
- Au redémarrage du pilote, son identifiant change : une ancienne autorisation
  ne peut plus entraîner de propulsion. Il faut cliquer de nouveau sur Démarrer.
- Extinction du service : retour au neutre ; ExecStopPost tente également le
  neutre après un plantage. Cela ne garantit pas l’arrêt en cas de panne électrique
  ou de défaillance de l’ESC ; garder sa coupure accessible pendant les essais.

## Trajectoire
À chaque cycle, recalage selon le mouvement, validation des obstacles actuels
et nouveau calcul candidat. L’ancienne trajectoire reste retenue si elle est
libre, rejoint le but à moins de 14 cm et si la nouvelle n’améliore pas suffisamment
le coût (15 % + 0,05). Sinon, remplacement. Pure Pursuit ajuste le braquage à
mesure du déplacement et contrôle l’arc effectivement demandé. Pas de malus
lié au champ de vision. Cadence visée 10 Hz, variable selon la charge ; le
watchdog stoppe la propulsion si le calcul dépasse sa durée de validité.

## Programme de test indépendant
~/test_moteurs.sh reste utilisable quand la conduite réelle est désarmée.
Le pilote et le test partagent un verrou exclusif. Pour un test avec un autre
programme, arrêter rc-motor-drive auparavant et éviter toute commande concurrente.

## Vérification
44 tests navigation/API, 8 tests du pilote moteur, 3 tests du programme sur banc.
Les cas vérifiés incluent perte de consigne, simulation, sens non confirmé,
arrêt dans chaque phase de recul, péremption de session et absence d’armement
automatique. Les performances en conduite au sol restent à valider sur le montage.

Niveaux manuels : croix = 1, carré = 2, triangle = 3, rond = 4, ou sélecteur dans l’interface. Niveau 2 choisi au démarrage. Le facteur 0,3 du dépôt est conservé ; niveau 4 donne au maximum 1 650 µs en avant et 1 350 µs en arrière. Le programme indépendant de test reste au niveau 2.
