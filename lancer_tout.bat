@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Base de donnees des livraisons
set "APP_DIR=%~dp0"
set "DONNEES_DIR=%~dp0Nouveau dossier"
cd /d "%APP_DIR%"

if not exist "%DONNEES_DIR%\livraisons.db" (
    if exist "%APP_DIR%livraisons.db" (
        echo ERREUR : la base attendue est absente : %DONNEES_DIR%\livraisons.db
        echo Une autre base existe a la racine : %APP_DIR%livraisons.db
        echo Demarrage interrompu pour eviter d'ouvrir une base vide ou ancienne.
        echo Ne deplace ni ne supprime aucune base. Demande de l'aide avant toute manipulation.
        pause
        exit /b 2
    )
)

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
    echo Ouvre cette adresse dans Chrome : http://localhost:!PORT!
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
echo Ouvre cette adresse dans Chrome : http://localhost:%PORT%
echo Demarrage du tunnel ngrok fixe...
start "Tunnel ngrok" cmd /k ngrok http --url=repave-sworn-equinox.ngrok-free.dev %PORT%
echo Ne ferme pas cette fenetre pendant l'utilisation.
python "%APP_DIR%wsgi.py"
if errorlevel 1 py "%APP_DIR%wsgi.py"
echo.
echo L'application est arretee.
pause
