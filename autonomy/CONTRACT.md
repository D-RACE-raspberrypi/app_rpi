# Contrat de sortie pour les moteurs et le module manette

> État au 16 septembre : le lidar et les moteurs sont maintenant reliés. Les mentions de fonctionnement uniquement consultatif ci-dessous décrivent les étapes précédentes. Le calcul seul reste sans propulsion ; « Démarrer le suivi réel » autorise le pilote séparé, avec expiration de session et de consigne. Voir [CONDUITE.md](../motor-control/CONDUITE.md). La manette reste hors intégration.


Cette API produit des **intentions de mouvement**, jamais des écritures matérielles.
L'actionneur futur doit effectuer l'arbitrage manuel/autonome, la conversion vers
le matériel et la supervision. Le mode manuel de cette application supprime les
intentions autonomes ; il ne pilote pas la voiture à la place de la manette.

## Lire une proposition

`GET /api/intent` renvoie notamment :

```json
{
  "mode": "autonomous",
  "state": "following",
  "advisory_only": true,
  "motor_control": false,
  "sequence": 123,
  "generated_at_unix": 1788950000.0,
  "intent": {
    "motion": "forward",
    "speed_m_s": 0.2,
    "steering_deg": 12.5,
    "steering_normalized": 0.5,
    "ttl_ms": 240
  }
}
```

- `motion` : stop / forward / reverse ; vitesse négative pour reverse.
- `steering_deg` : angle proposé des roues avant, pas l'angle cible ni l'angle du servo.
- `steering_normalized` : −1 gauche, 0 centre, +1 droite, compatible en convention
  avec `servo_control(float value)`. La correspondance physique servo/roues doit
  être mesurée : ±45° de rotation du servo ne signifie pas ±45° des roues.
- `ttl_ms` : durée restante depuis la production du calcul (300 ms au maximum).
  Lire plusieurs fois la même proposition ne prolonge pas sa validité.
- `sequence` : numéro du calcul pour détecter des réponses répétées.
- `readiness` : réserves sur les mesures et la géométrie ; ce n'est pas une validation
  physique du véhicule. **Aucune proposition de cette version n'autorise à elle seule
  une activation des moteurs**, car `advisory_only` reste vrai.

Le futur contrôleur doit arrêter en cas de timeout réseau, proposition expirée,
stop, perte du mode autonome ou arrêt d'urgence. Le changement de sens demande
un passage à l'arrêt confirmé par l'actionneur : la pause du planificateur seul
ne confirme pas une vitesse réelle nulle.

## Commandes de supervision

- `POST /api/mode` avec `{"mode":"manual"}` ou `{"mode":"autonomous"}`.
  L'activation autonome exige qu'une distance ait été renseignée.
- `POST /api/config` : réglages partiels, par exemple `{"target_m":1.5}`.
  Toute modification réinitialise la manœuvre. Validation des valeurs côté serveur.
- `POST /api/select` : relais vers Stereo Studio, exemple
  `{"id":1,"generation":3}`. Une génération périmée est refusée par la vision.
- `GET /api/state` : état complet pour l'interface (vision, image, lidar, candidats,
  trajectoire retenue, configuration, erreurs de connexion).

Les POST attendent du JSON, et les origines navigateur étrangères sont refusées.
Les processus locaux de confiance peuvent appeler l'API directement. Aucun secret
ou mot de passe n'est embarqué. Le déploiement hors réseau local n'est pas prévu.

## Fichiers existants

`motor_ctl/servo_simple.c` utilise `/sys/class/pwm/pwmchip0`, canal 0, période 20 ms.
Il initialise le PWM au premier appel : **ne pas appeler cette fonction lors d'un
simple aperçu de navigation**. La propulsion et les commandes PS4 restent à
fournir par les autres membres du groupe. Ce module n'ouvre aucun GPIO/UART/PWM.

## Trajectoire à braquage variable — 14 septembre 2026

`goal` donne le point d’arrêt (coordonnées par rapport au centre du véhicule),
placé à `target_m` de la personne sur l’axe d’approche. `goal.reached_by_plan`
indique si la trajectoire calculée le rejoint à 4,5 cm près ; la tolérance de
maintien configurée continue de s’appliquer pendant le déplacement.
`chosen.path` contient les points espacés d’au plus 4 cm de déplacement.
`chosen.segments` décrit les braquages successifs : `steering_deg`, `length_m`,
`end_index` dans `path`. La direction instantanée dans `intent` est uniquement
celle du premier segment. Le futur contrôleur doit consommer des consignes
fraîches, respecter TTL et recalculer ; il ne doit pas exécuter aveuglément la
liste de segments comme une commande différée. Les repères doivent être remis
à jour avec l’odométrie dès que la voiture roule.

La recherche hybrid A* est bornée en temps et en nombre de nœuds. Un résultat
partiel porte `chosen.reached=false`. Les détails sont dans `search`. L’ancien
champ `horizon_m` règle désormais la longueur de détour supplémentaire permise
au-delà de la distance directe au point d’arrêt ; son libellé UI a changé.
La recherche minimise un coût de trajet (distance parcourue, risque, déviation),
sans réintroduire le bonus de longueur praticable supprimé précédemment.
Les anciens arcs à braquage constant restent des diagnostics (`candidates` sans
`segments`) ; leurs scores ne sélectionnent plus à eux seuls la route complète.

Le malus obstacles est évalué le long du trajet, avec le profil X/Y dans les
20 cm au-delà de l’enveloppe de collision. Les points après le plan d’arrêt ne
contribuent pas à ce coût. Ils restent testés pour une collision physique avec
le gabarit au point d’arrivée. La personne n’est jamais retirée arbitrairement
du lidar. Le recul conserve son contrôle strict des zones observées et ses
limites temporelles ; les trajectoires avant peuvent traverser les secteurs
inconnus avec le malus demandé.

### Mouvement et identité
`/api/state` ajoute `odometry` (pose x/y/yaw rad, epoch, valid, résidu et fraction
retenue) et `imu` (calibrated, fresh, error). La pose est locale et repart de zéro
lors d’une rupture (`epoch` change). Ne pas la traiter comme une position absolue.
`plan.controller` contient method, lookahead_point et retained. Le braquage dans
intent est celui du contrôleur de suivi, et non nécessairement le premier segment
du plan. Aucun changement des unités, du TTL ou du caractère consultatif.
`vision.identity_id` est stable tant que la sélection demeure ; `selected_id` peut
changer lors d’une ré-identification. Une cible perdue ou ambiguë ne produit pas
une consigne d’avance fondée sur une prédiction.
