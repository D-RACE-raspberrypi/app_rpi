#ifndef MOTEUR_H
#define MOTEUR_H
/*
 * Moteur de traction (ESC) — PWM materiel 50 Hz, GPIO12 / canal 0 (rapport §3.2.1)
 *
 * value = -1.0 : marche arrière max (limitée)
 * value =  0.0 : neutre / arrêt
 * value = +1.0 : marche avant max (limitée)
 *
 * La valeur est automatiquement limitée entre -1 et +1.
 */
int moteur_init(void);
void moteur_control(float value);

#endif
