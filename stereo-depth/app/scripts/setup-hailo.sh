#!/bin/bash
# Run on the Pi after mounting the AI Kit. Does not reboot automatically.
set -euo pipefail
if [ "$(uname -m)" != aarch64 ]; then
  echo 'Ce script doit être exécuté sur le Raspberry Pi OS 64 bits.' >&2
  exit 1
fi
sudo apt-get update
sudo apt-get install -y hailo-all hailo-models python3-hailort python3-hailo-tappas
python3 -c 'import hailo, hailo_platform; assert hasattr(hailo, "HailoTracker"), "Bindings HailoTracker absents"'
test -f /usr/share/hailo-models/yolov8s_h8l.hef
echo 'Installation terminée. Redémarrer le Pi, puis lancer : hailortcli fw-control identify'
echo 'Stereo Studio redémarre automatiquement ; ouvrir Suivi de personne.'
