@echo off
cd /d "%~dp0"
python tools\update.py
if errorlevel 1 goto failed
echo.
echo Fichiers disponibles dans output\domestic et publication GitHub si configuree.
pause
exit /b 0
:failed
echo.
echo Mise a jour interrompue. Consulter le message ci-dessus.
pause
exit /b 1
