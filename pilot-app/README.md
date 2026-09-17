# D-RACE — application de pilotage sur le PC

L’interface PC fonctionne sous **Windows, Linux et macOS**, avec Python 3.10 ou
plus récent et un navigateur compatible Gamepad API. Aucun paquet Python externe.
Les pilotes caméra, lidar et PWM restent exécutés sur le Raspberry Pi Linux.

| Système du PC | Lancement dans le dossier `pilot-app` |
|---|---|
| Windows | Double-cliquer sur **D-RACE.bat** |
| Linux | `sh D-RACE.sh` dans un terminal |
| macOS | Double-cliquer sur **D-RACE.command** |

Saisir l’adresse actuelle du Pi ou Entrée pour garder la valeur proposée.
Garder le terminal ouvert. L’application s’ouvre sur http://localhost:8090/.
Le PC et le Pi doivent être sur un réseau permettant leur communication.

En terminal, sans question interactive :

```sh
# Windows (PowerShell ou cmd)
py -3 launch.py --pi 10.215.13.38

# Linux / macOS
python3 launch.py --pi 10.215.13.38
```

Sous Windows, le lanceur essaie `py -3`, puis `python`. Sous Linux/macOS, il
utilise `python3`. Si le navigateur ne s’ouvre pas, ouvrir localhost:8090 manuellement.

La manette PS4 se connecte au **PC par Bluetooth**. Appuyer sur un bouton dans
l’onglet pour la faire apparaître. Si le navigateur intégré ne l’expose pas,
ouvrir la même adresse dans Chrome/Edge. L’application doit rester visible.
Le service local permet de lire la manette depuis localhost et relaie les données
au Pi ; ouvrir directement une page HTTP distante ne fournit pas le même contexte.

## Utilisation

- Consulter la caméra et cliquer dans un cadre pour sélectionner une personne.
- Régler la distance à maintenir ; réglages stéréo conservés.
- Choisir Manuel / Automatique à l’écran ou cliquer sur le pavé tactile.
- Le changement de mode seul ne démarre pas les moteurs. Cliquer sur
  **Activer les commandes**, gâchettes relâchées. Trois secondes au neutre.
- Manuel : stick gauche horizontal = direction ; R2 = avance ; L2 = frein/recul.
  Les deux gâchettes sont soustraites comme GD − GG dans le dépôt.
- Automatique : trajectoire du suivi existant. Perte de cible, profondeur,
  localisation ou lidar = arrêt. L’autonomie au sol reste à valider.
- Au changement de mode actif : 0,4 s au neutre, puis gâchettes relâchées requises.
- **ARRÊTER** désarme. La fermeture/masquage de l’onglet et la déconnexion de la
  manette arrêtent les commandes ; une perte réseau expire en 0,5 s maximum,
  avec validité des entrées manuelles limitée à 0,35 s.
- Une nouvelle activation est nécessaire après déconnexion ; pas de reprise seule.

Le pavé tactile est le bouton 17 du mapping standard par défaut. Dans « Connexion
et réglages », les boutons pressés sont affichés et le numéro peut être ajusté,
moteurs désarmés. Certains navigateurs n’exposent pas ce bouton : utiliser alors
les boutons de mode de l’application. Le changement est déclenché au début de
l’appui, jamais à chaque image tant que le bouton reste enfoncé.


## Architecture et validation

`launch.py` : serveur local 127.0.0.1 uniquement, relais vers un Pi fixé au
lancement, contrôle Host/Origin, liste fermée de routes. Pas de relais arbitraire.
`pilot.js` : Gamepad API, caméra et choix des modes. `map.js` réutilise la carte
existante. `autonomy/pilot_session.py` : séquences d’entrée, détection d’appui,
neutralisation au changement. `/api/pilot` : start/input/mode/stop/preview.
Le pilote moteur garde son verrou matériel et sa surveillance indépendante.
La navigation continue à calculer une proposition en mode manuel de pilotage,
mais seule la commande de la manette est transmise aux moteurs dans ce mode.

Tests : transitions, maintien du bouton, déclencheur relâché, séquences périmées,
propriétaire de session, déconnexion, démarrage désarmé, commande manuelle sans
capteurs et expiration. Tests navigation/API et moteurs exécutés sur le Pi.
Caméra et carte vérifiées dans le navigateur. L’utilisateur a confirmé que la manette Bluetooth est reconnue et que le pavé
tactile bascule les modes. Les mouvements de direction et l’autonomie au sol
restent à valider.
Sauvegarde avant installation : `../backups/rc-before-pilot-app.tar.gz`.

La validation physique Bluetooth a été faite sur le Mac du montage. Le workflow CI vérifie le serveur local sur Windows, Linux et macOS ; il ne valide pas les pilotes Bluetooth ou les moteurs.

Niveaux manuels : croix = 1, carré = 2, triangle = 3, rond = 4, ou sélecteur dans l’interface. Niveau 2 choisi au démarrage. Le facteur 0,3 du dépôt est conservé ; niveau 4 donne au maximum 1 650 µs en avant et 1 350 µs en arrière. Le programme indépendant de test reste au niveau 2.
