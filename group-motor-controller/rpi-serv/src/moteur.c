#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include "utils.h"

#define PWM_CHIP   "/sys/class/pwm/pwmchip0"
#define PWM_DUTY   "/sys/class/pwm/pwmchip0/pwm0/duty_cycle"
#define PWM_PERIOD "/sys/class/pwm/pwmchip0/pwm0/period"
#define PWM_ENABLE "/sys/class/pwm/pwmchip0/pwm0/enable"

#define PULSE_REVERSE_NS 1000000L  
#define PULSE_NEUTRAL_NS 1500000L  
#define PULSE_FORWARD_NS 2000000L  

#define SPEED_LIMIT 0.3f

#define RAMP_STEP_NS   5000L
#define RAMP_DELAY_US  10000L

static long current_pulse_ns = PULSE_NEUTRAL_NS; 
static int last_side = 0; 

static void ramp_to(long target_ns)
{
    while (current_pulse_ns != target_ns) {
        if (current_pulse_ns < target_ns) {
            current_pulse_ns += RAMP_STEP_NS;
            if (current_pulse_ns > target_ns) current_pulse_ns = target_ns;
        } else {
            current_pulse_ns -= RAMP_STEP_NS;
            if (current_pulse_ns < target_ns) current_pulse_ns = target_ns;
        }

        char cmd[200];
        snprintf(cmd, sizeof(cmd), "echo %ld > %s", current_pulse_ns, PWM_DUTY);
        system(cmd);

        usleep(RAMP_DELAY_US);
    }
}

void moteur_control(float commande)
{
    if (commande < 0.0f) commande = 0.0f;
    if (commande > 1.0f) commande = 1.0f;


    long pulse_ns;
    int side;
    if (commande < 0.5f) {
        float t = (0.5f - commande) / 0.5f;
        long full_excursion = PULSE_NEUTRAL_NS - PULSE_REVERSE_NS;
        pulse_ns = PULSE_NEUTRAL_NS - (long)(t * full_excursion * SPEED_LIMIT);
        side = -1;
    } else if (commande > 0.5f) {
        float t = (commande - 0.5f) / 0.5f;
        long full_excursion = PULSE_FORWARD_NS - PULSE_NEUTRAL_NS;
        pulse_ns = PULSE_NEUTRAL_NS + (long)(t * full_excursion * SPEED_LIMIT);
        side = 1;
    } else {
        pulse_ns = PULSE_NEUTRAL_NS;
        side = 0;
    }

    if (side == -1 && last_side == 1) {
        debug_printf("[Changement de sens detecte : sequence de freinage automatique...]\n");
        ramp_to(PULSE_NEUTRAL_NS);
        usleep(400000);
        ramp_to(pulse_ns);   
        usleep(500000);
        ramp_to(PULSE_NEUTRAL_NS);
        usleep(300000);
    }

    ramp_to(pulse_ns);
    last_side = side;

    debug_printf("Commande = %.2f -> impulsion finale = %.3f ms\n", commande, pulse_ns / 1000000.0f);
}


int moteur_init(void) {
    debug_printf("\nInitialisation du PWM moteur...\n");
    system("echo 0 > /sys/class/pwm/pwmchip0/export 2>/dev/null");
    usleep(100000);
    system("echo 0 > /sys/class/pwm/pwmchip0/pwm0/enable 2>/dev/null");
    system("echo 20000000 > /sys/class/pwm/pwmchip0/pwm0/period");
    system("echo 1500000 > /sys/class/pwm/pwmchip0/pwm0/duty_cycle");
    debug_printf("Configuration GPIO12 -> PWM0_CHAN0...\n");
    system("pinctrl set 12 a0");
    debug_printf("\nEtat du GPIO12 :\n");
    system("pinctrl get 12");
    system("echo 1 > /sys/class/pwm/pwmchip0/pwm0/enable");
    debug_printf("\nPWM actif : 50 Hz\n");
    debug_printf("Periode : 20 ms\n");
    debug_printf("GPIO : 12\n");
    debug_printf("Fonction : ALT0 (a0)\n");
    debug_printf("PWM : PWM0_CHAN0\n");
    debug_printf("Canal Linux : pwm0\n");
    debug_printf("Moteur au neutre : 1.500 ms\n");
    debug_printf("\nInitialisation de l'ESC au neutre...\n");
    sleep(3);
    return 0;
}
