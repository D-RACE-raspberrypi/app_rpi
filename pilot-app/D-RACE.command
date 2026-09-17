#!/bin/zsh
cd "$(dirname "$0")"
printf 'Adresse du Pi [10.215.13.38] : '
read rc_pi_addr
python3 launch.py --pi "${rc_pi_addr:-10.215.13.38}"
