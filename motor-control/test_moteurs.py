#!/usr/bin/env python3
"""Test indépendant ESC/servo : GPIO12/13, niveau 2 du dépôt D-RACE.
Bibliothèque standard uniquement. Aucun lien avec la navigation ou le lidar.
"""
import argparse
import fcntl
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time

PWM=Path('/sys/class/pwm/pwmchip0')
NEUTRE=1500000
AVANT=1575000
ARRIERE=1425000
CENTRE=1566666  # Centre du dépôt GitHub : 102 degrés.

class Sorties:
    def __init__(self,simulation=False):self.simulation=simulation;self.lock=None;self.ready=False
    def ecrire(self,canal,nom,valeur):
        if self.simulation:
            if nom=='duty_cycle':print(f'  [simulation] canal {canal} : {valeur/1000:.1f} µs')
        else:(PWM/f'pwm{canal}'/nom).write_text(str(valeur))
    def initialiser(self):
        global PWM
        if not self.simulation:
            candidates=[p for p in Path('/sys/class/pwm').glob('pwmchip*') if '1f00098000.pwm' in str(p.resolve())]
            if len(candidates)!=1:raise RuntimeError('Contrôleur PWM0 1f00098000.pwm absent.')
            PWM=candidates[0]
            if os.geteuid()!=0:raise RuntimeError('Lancer avec sudo.')
            if not PWM.exists():raise RuntimeError('Contrôleur PWM absent : vérifier la configuration du Pi.')
            self.lock=open('/run/rc-motor-test.lock','w')
            try:fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError('Un autre exemplaire du test est actif.')
            for p in Path('/proc').glob('[0-9]*/comm'):
                try:name=p.read_text().strip()
                except OSError:continue
                if name=='serveur_pi':raise RuntimeError('Arrêter le serveur de commande manuelle avant ce test.')
        self.ready=True
        for canal,gpio,neutre in ((0,12,NEUTRE),(1,13,CENTRE)):
            if not self.simulation and not (PWM/f'pwm{canal}').exists():
                (PWM/'export').write_text(str(canal));time.sleep(.15)
            self.ecrire(canal,'enable',0)
            self.ecrire(canal,'duty_cycle',0)
            self.ecrire(canal,'period',20000000)
            self.ecrire(canal,'duty_cycle',neutre)
            if not self.simulation:subprocess.run(['pinctrl','set',str(gpio),'a0'],check=True)
            self.ecrire(canal,'enable',1)
    def arreter(self):
        if not self.ready:return
        errors=[]
        for canal,valeur in ((0,NEUTRE),(1,CENTRE)):
            try:self.ecrire(canal,'duty_cycle',valeur)
            except OSError as e:errors.append(str(e))
        if errors:print('ATTENTION : impossible de confirmer le neutre : '+'; '.join(errors),file=sys.stderr)
    def attendre(self,secondes):
        if self.simulation:return True
        fin=time.monotonic()+secondes
        while time.monotonic()<fin:
            # s ou 0 + Entrée interrompt même une impulsion en cours.
            if select.select([sys.stdin],[],[],min(.05,max(0,fin-time.monotonic())))[0]:
                ligne=sys.stdin.readline()
                if not ligne or ligne.strip().lower() in ('q','quitter'):raise KeyboardInterrupt
                if ligne.strip().lower() in ('s','0','stop'):return False
        return True
    def impulsion(self,valeur,duree):
        try:
            self.ecrire(0,'duty_cycle',valeur)
            return self.attendre(duree)
        finally:self.ecrire(0,'duty_cycle',NEUTRE)
    def action(self,choix,duree):
        if not .1<=duree<=3:raise ValueError('Durée autorisée : 0,1 à 3 secondes.')
        try:
            if choix=='1':
                print(f'AVANT, niveau 2, {duree:g} seconde(s)',flush=True)
                self.impulsion(AVANT,duree)
            elif choix=='2':
                print('Frein/recul : impulsion 0,5 s, neutre 0,3 s, puis recul.',flush=True)
                if not self.impulsion(ARRIERE,.5):return
                if not self.attendre(.3):return
                self.impulsion(ARRIERE,duree)
            elif choix in ('3','4'):
                valeur=1327777 if choix=='3' else 1805555  # servo_control(-1/+1), comme dans le dépôt
                print('Braquage complet du dépôt, puis retour au centre.',flush=True)
                self.ecrire(1,'duty_cycle',valeur);self.attendre(duree)
            elif choix=='5':
                print('Neutre pendant 3 secondes pour laisser armer l’ESC.',flush=True)
                self.arreter();self.attendre(3)
            elif choix=='0':pass
            else:raise ValueError('Choisir 0 à 5, d ou q.')
        finally:self.arreter();print('NEUTRE — aucun ordre de propulsion.',flush=True)
    def fermer(self):
        self.arreter()
        if self.lock:self.lock.close()

def interrompre(*_):raise KeyboardInterrupt

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulation',action='store_true',help='tester le menu sans accéder au matériel')
    args=parser.parse_args();sorties=Sorties(args.simulation)
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,interrompre)
    try:
        print('ESC : GPIO12 / broche 32. Direction : GPIO13 / broche 33.')
        print('Roues motrices levées, batterie chargée, ESC allumé. Aucun autre contrôleur actif.')
        print('Arrêt : Ctrl+C ; pendant un essai : s puis Entrée. Coupure électrique accessible.')
        if input('Écrire TEST pour initialiser au neutre : ').strip()!='TEST':return
        sorties.initialiser();sorties.action('5',1);duree=1.
        while True:
            print(f'\n1 Avant | 2 Frein/recul | 3 Direction − | 4 Direction + | 5 Armer au neutre')
            print(f'0 Arrêt/centre | d Durée ({duree:g} s, maximum 3 s) | q Quitter')
            choix=input('Choix : ').strip().lower()
            if choix=='q':break
            if choix=='d':
                try:
                    valeur=float(input('Durée en secondes (0,1 à 3) : ').replace(',','.'))
                    if not .1<=valeur<=3:raise ValueError
                    duree=valeur
                except ValueError:print('Durée invalide, ancienne valeur conservée.')
            elif choix in ('0','1','2','3','4','5'):sorties.action(choix,duree)
            else:print('Choix inconnu.')
    except (KeyboardInterrupt,EOFError):print('\nTest interrompu.')
    except Exception as e:print(f'ERREUR : {e}',file=sys.stderr);return 1
    finally:sorties.fermer()
    print('Programme terminé, sorties au neutre.');return 0

if __name__=='__main__':sys.exit(main())
