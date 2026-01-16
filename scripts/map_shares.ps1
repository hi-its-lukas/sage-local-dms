# DMS Netzlaufwerke verbinden (PowerShell)
# Bitte SERVER_IP und PASSWORT anpassen

$SERVER_IP = "10.0.100.10"
$DMS_USER = "dmsuser"
$DMS_PASSWORD = "DmsPass2026"

Write-Host "Verbinde Sage-Archiv als Laufwerk S:..." -ForegroundColor Green
net use S: /delete /yes 2>$null
net use S: "\\$SERVER_IP\sage_archiv" /user:$DMS_USER $DMS_PASSWORD /persistent:yes

Write-Host "Verbinde Manueller-Scan als Laufwerk M:..." -ForegroundColor Green
net use M: /delete /yes 2>$null
net use M: "\\$SERVER_IP\manual_scan" /user:$DMS_USER $DMS_PASSWORD /persistent:yes

Write-Host ""
Write-Host "Fertig! Verbundene Laufwerke:" -ForegroundColor Cyan
Get-PSDrive -PSProvider FileSystem | Where-Object { $_.DisplayRoot -like "*$SERVER_IP*" }
