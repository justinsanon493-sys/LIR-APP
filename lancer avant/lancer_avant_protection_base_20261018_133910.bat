@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Base de donnees de livraisons
set "APP_DIR=%~dp0"
set "DONNEES_DIR=%~dp0Nouveau dossier"
cd /d "%APP_DIR%"

for /f "tokens=1,2,3 delims=|" %%A in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%APP_DIR%choisir_port.ps1" -AppScript "%APP_DIR%app.py" -WSGIScript "%APP_DIR%wsgi.py"') do (
    if "%%A"=="RUNNING" (
        set "APP_EXISTANTE=1"
        set "PORT=%%B"
        set "APP_PID=%%C"
    )
    if "%%A"=="FREE" set "PORT=%%B"
)

if defined APP_EXISTANTE (
    echo L'application fonctionne deja, PID !APP_PID!.
    echo Ouverture de l'application dans le navigateur : http://localhost:!PORT!
    start "" "http://localhost:!PORT!/"
    echo Garde la fenetre du serveur deja ouverte.
    pause
    exit /b 0
)
if not defined PORT (
    echo Aucun port libre entre 5001 et 5100.
    echo Ferme une application que tu reconnais ou contacte le support.
    pause
    exit /b 1
)
set "PORT=%PORT%"

echo Application : %APP_DIR%wsgi.py
echo Base de donnees : %DONNEES_DIR%\livraisons.db
echo Port choisi automatiquement : %PORT%
echo Adresse de l'application : http://localhost:%PORT%
echo Le navigateur s'ouvrira des que le serveur repond.
echo Ne ferme pas cette fenetre pendant l'utilisation.
start "" /b powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%APP_DIR%ouvrir_application.ps1" -Port %PORT%
python "%APP_DIR%wsgi.py"
if errorlevel 1 py "%APP_DIR%wsgi.py"
echo.
echo L'application est arretee.
pause
