#!/usr/bin/env python3
"""Pi 5 UART3 on physical pins 24/21. Preserve unrelated boot settings."""
from pathlib import Path
from datetime import datetime
import re
p=Path('/boot/firmware/config.txt')
s=p.read_text()
backup=p.with_name('config.txt.before-lidar-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.write_text(s)
s=re.sub(r'(?m)^\s*dtparam=spi=on\s*$', '# SPI0 desactive : GPIO8/9 utilises par UART3 lidar.\ndtparam=spi=off',s)
if not re.search(r'(?m)^\s*dtoverlay=uart3-pi5(?:,.*)?$',s):
 s+='\n# RPLIDAR RX -> pin 24 (GPIO8 TX), TX -> pin 21 (GPIO9 RX)\n[pi5]\ndtoverlay=uart3-pi5\n[all]\n'
p.write_text(s)
print('Sauvegarde :',backup)
