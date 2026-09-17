"""Bounded wheels-raised test using group repository gear-2 PWM limits.
Does not read navigation or controller packets. No autostart.
"""
import argparse,signal,subprocess,time
from pathlib import Path
ROOT=Path('/sys/class/pwm/pwmchip0')
NEUTRAL=1500000

def pulse(relative,gear=2):
    if not -1<=relative<=1 or gear!=2:raise ValueError('Niveau 2 uniquement')
    return NEUTRAL+round(relative*500000*.3*gear/4)

def steering(value):
    if not -1<=value<=1:raise ValueError('Direction invalide')
    return 1000000+int(102+value*43)*1000000//180

def write(channel,name,value):
    (ROOT/f'pwm{channel}'/name).write_text(str(value))

def interrupt(*args):raise KeyboardInterrupt

def run():
    signal.signal(signal.SIGTERM,interrupt);signal.signal(signal.SIGINT,interrupt)
    try:
        for channel,gpio in ((0,12),(1,13)):
            if not (ROOT/f'pwm{channel}').exists():
                (ROOT/'export').write_text(str(channel));time.sleep(.1)
            write(channel,'enable',0);write(channel,'duty_cycle',0);write(channel,'period',20000000)
            write(channel,'duty_cycle',NEUTRAL if channel==0 else steering(0))
            subprocess.run(['pinctrl','set',str(gpio),'a0'],check=True);write(channel,'enable',1)
        print('Neutre pendant 3 secondes',flush=True);time.sleep(3)
        print('Avant niveau 2 : 0,5 seconde',flush=True);write(0,'duty_cycle',pulse(1));time.sleep(.5)
        write(0,'duty_cycle',NEUTRAL);time.sleep(.8)
        print('Séquence frein/recul niveau 2',flush=True)
        write(0,'duty_cycle',pulse(-1));time.sleep(.5)
        write(0,'duty_cycle',NEUTRAL);time.sleep(.3)
        write(0,'duty_cycle',pulse(-1));time.sleep(.5)
        write(0,'duty_cycle',NEUTRAL);time.sleep(.3)
        print('Direction : petit débattement, puis centre',flush=True)
        for position in (-.2,.2,0):write(1,'duty_cycle',steering(position));time.sleep(.5)
    finally:
        # Stop has no ramp or delay, including on interruption.
        if (ROOT/'pwm0/duty_cycle').exists():write(0,'duty_cycle',NEUTRAL)
        if (ROOT/'pwm1/duty_cycle').exists():write(1,'duty_cycle',steering(0))
        print('FIN : moteur au neutre, direction centrée',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');a=p.parse_args()
    if a.execute:run()
    else:print(dict(neutral=NEUTRAL,forward=pulse(1),reverse=pulse(-1),steering_center=steering(0)))
