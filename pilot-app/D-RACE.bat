@echo off
setlocal
cd /d "%~dp0"
py -3 --version >nul 2>&1
if not errorlevel 1 (
    py -3 launch.py --ask-ip
    goto done
)
python --version >nul 2>&1
if not errorlevel 1 (
    python launch.py --ask-ip
    goto done
)
echo Python 3 est requis. Installez Python 3 avec le lanceur py ou ajoutez-le au PATH.
:done
pause
