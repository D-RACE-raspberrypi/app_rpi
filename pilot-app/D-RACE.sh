#!/bin/sh
# Lanceur Linux/macOS, indépendant du répertoire courant.
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 est requis. Installez Python 3 puis relancez D-RACE." >&2
  exit 1
fi
exec python3 launch.py --ask-ip "$@"
