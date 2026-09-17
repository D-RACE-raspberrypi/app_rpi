#ifndef SERVO_H
#define SERVO_H
/*
 * Direction — PWM materiel 50 Hz, GPIO13 / canal 1 (rapport §3.2.1)
 *
 * value = -1.0 : gauche max
 * value =  0.0 : centre
 * value = +1.0 : droite max
 *
 * La valeur est automatiquement limitée entre -1 et +1.
 */
#include <stdlib.h>

void servo_init(void);
void servo_control(float value);

#endif
