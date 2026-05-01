@echo off
set "PROJECT_DIR=%~dp0"
set "ENV_FILE=.env"

cd /d "%PROJECT_DIR%"
start "Domain Autoreg GUI" pythonw.exe -m domain_autoreg.cli --env "%ENV_FILE%" gui
