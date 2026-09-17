#include "car.h"
#include "utils.h"
#include <stdio.h>
#include <string.h>


Car_t* car_init(Car_t *car) {
    car -> relative_speed   = 0.0;
    car -> direction        = 0.0;
    car -> gear             = 1;
    car -> absolute_speed   = 0.5;  // Valeur initiale de la vitesse absolue (0.5 correspond à une vitesse neutre)
    car -> trigger_accel     = 0.0;
    car -> trigger_brake     = 0.0;
    return car;
}

// Reception des données venant du serveur
// Différents actionners (JGX (left joystick), GG (gachette gauche), GD (gachette droite)))

void car_update_absolute_speed(Car_t *car) {    // Mise à jour de la vitesse absolue en fonction de la vitesse relative et du rapport
    car->absolute_speed = 0.5f + (car->relative_speed * 0.5f * car->gear / 4.0f); // Mise à jour de la vitesse absolue
    moteur_control(car->absolute_speed);
}

void car_display_state(Car_t *car) {  // Affichage de l'état actuel de la voiture
    int debug = env_or("DEBUG", "0")[0] != '\0' && env_or("DEBUG", "0")[0] != '0';
    if (debug) {
        return;
    }

    printf("\033[H\033[J");
    printf("Etat de la voiture :\n");
    printf("   Vitesse relative : %s %0.3f %s\n", CYAN_form, car->relative_speed, RESET_form);
    printf("   Direction : %s %0.3f %s\n", CYAN_form, car->direction, RESET_form);
    printf("   Rapport de vitesse : %s %d %s\n", CYAN_form, car->gear, RESET_form);
    printf("   Vitesse absolue : %s %0.3f %s\n", MAGENTA_form, car->absolute_speed, RESET_form);
    printf("   Gachette accel : %s %0.3f %s\n", GREEN_form, car->trigger_accel, RESET_form);
    printf("   Gachette brake : %s %0.3f %s\n", GREEN_form, car->trigger_brake, RESET_form);
    fflush(stdout);
}

void car_reception(Car_t *car, const char *payload) {
    // Extraction des valeurs de la charge utile (payload)
    char *ptr;

    // Extraction de la direction (JGX)
    if ((ptr = strstr(payload, "JGX:")) != NULL) {
        car->direction = atof(ptr + 4);             // +4 pour sauter "JGX:"
    }

    // Extraction de la gachette d'acceleration (GD)
    if ((ptr = strstr(payload, "GD:")) != NULL) {
        car->trigger_accel = atof(ptr + 3);         // +3 pour sauter "GD:"
    }

    // Extraction de la gachette de freinage (GG)
    if ((ptr = strstr(payload, "GG:")) != NULL) {
        car->trigger_brake = atof(ptr + 3);         // +3 pour sauter "GG:"
    }

    // Extraction du rapport de vitesse (Gear)
    if ((ptr = strstr(payload, "Croix:P")) != NULL) {
        car->gear = 1;
    } else if ((ptr = strstr(payload, "Carre:P")) != NULL) {
        car->gear = 2;
    } else if ((ptr = strstr(payload, "Triangle:P")) != NULL) {
        car->gear = 3;
    } else if ((ptr = strstr(payload, "Rond:P")) != NULL) {
        car->gear = 4;
    }

    // Sécurité des valeurs pour la direction
    if (car->direction < -1.0) {
        car->direction = -1.0;
    } else if (car->direction > 1.0) {
        car->direction = 1.0;
    }
    
    // Calcul de la vitesse relative en fonction des gachettes d'acceleration et de freinage et sécurité des valeurs
    car->relative_speed = car->trigger_accel - car->trigger_brake;
    if (car->relative_speed < -1.0) {
        car->relative_speed = -1.0;
    } else if (car->relative_speed > 1.0) {
        car->relative_speed = 1.0;
    }

    // Mise à jour de la direction du servo et de la vitesse absolue du moteur et affichage de l'état actuel de la voiture
    servo_control(car->direction);
    car_update_absolute_speed(car);
    car_display_state(car);
}