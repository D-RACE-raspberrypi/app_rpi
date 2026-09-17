#ifndef SERVO_SIMPLE_H
#define SERVO_SIMPLE_H

// Controle le servo de direction avec une seule fonction.
// value : -1.0 = butee gauche, 0.0 = centre, 1.0 = butee droite.
// L'initialisation du PWM se fait automatiquement au tout premier appel.
void servo_control(float value);

#endif
