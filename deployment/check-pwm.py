#!/usr/bin/env python3
"""Diagnostic en lecture seule : n'exporte aucun canal, ne déplace aucun moteur."""
from pathlib import Path
import subprocess,sys
chips=list(Path('/sys/class/pwm').glob('pwmchip*'))
for p in chips:print(p,'->',p.resolve())
correct=[p for p in chips if '1f00098000.pwm' in str(p.resolve())]
if len(correct)!=1:
 print('PWM0 absent ou ambigu. Vérifier pwm-2chan dans /boot/firmware/config.txt puis redémarrer.');sys.exit(1)
print('Contrôleur attendu :',correct[0])
for channel,gpio,pin in [(0,12,32),(1,13,33)]:
 print(f'Canal {channel} : GPIO{gpio}, broche physique {pin}')
 for field in ['enable','period','duty_cycle']:
  p=correct[0]/f'pwm{channel}'/field
  print(' ',field,':',p.read_text().strip() if p.exists() else 'non exporté (normal avant initialisation)')
try:subprocess.run(['pinctrl','get','12-13'],check=True)
except (OSError,subprocess.CalledProcessError):print('Vérification pinctrl indisponible.')
print('Ce contrôle logiciel ne prouve pas que le signal arrive au servo : vérifier aussi alimentation et masse commune.')
