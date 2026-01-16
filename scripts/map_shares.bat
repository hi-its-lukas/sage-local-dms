@echo off
REM DMS Netzlaufwerke verbinden
REM Bitte SERVER_IP und PASSWORT anpassen

set SERVER_IP=10.0.100.10
set DMS_USER=dmsuser
set DMS_PASSWORD=DmsPass2026

echo Verbinde Sage-Archiv als Laufwerk S:...
net use S: /delete /yes 2>nul
net use S: \\%SERVER_IP%\sage_archiv /user:%DMS_USER% %DMS_PASSWORD% /persistent:yes

echo Verbinde Manueller-Scan als Laufwerk M:...
net use M: /delete /yes 2>nul
net use M: \\%SERVER_IP%\manual_scan /user:%DMS_USER% %DMS_PASSWORD% /persistent:yes

echo.
echo Fertig! Laufwerke verbunden:
net use S:
net use M:
pause
