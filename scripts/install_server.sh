#!/bin/bash
set -e

echo "=============================================="
echo "DMS Server Installation für Ubuntu"
echo "=============================================="
echo ""

if [ "$EUID" -ne 0 ]; then
    echo "Bitte als root ausführen: sudo $0"
    exit 1
fi

DMS_USER="${DMS_USER:-dmsuser}"
DMS_PASSWORD="${DMS_PASSWORD:-$(openssl rand -base64 12)}"
DMS_DIR="${DMS_DIR:-$(pwd)}"
SAGE_ARCHIVE_PATH="${SAGE_ARCHIVE_PATH:-$DMS_DIR/data/sage_archive}"
MANUAL_SCAN_PATH="${MANUAL_SCAN_PATH:-$DMS_DIR/data/manual_input}"

echo ""
echo "Konfiguration:"
echo "  Samba-Benutzer: $DMS_USER"
echo "  Sage-Archiv: $SAGE_ARCHIVE_PATH"
echo "  Manuelle Eingabe: $MANUAL_SCAN_PATH"
echo ""

echo "[1/7] System aktualisieren..."
apt update -qq

echo "[2/7] Abhängigkeiten installieren..."
apt install -y -qq samba docker.io docker-compose

echo "[3/7] Verzeichnisse erstellen..."
mkdir -p "$SAGE_ARCHIVE_PATH"
mkdir -p "$MANUAL_SCAN_PATH"

echo "[4/7] Samba-Benutzer erstellen..."
if ! id "$DMS_USER" &>/dev/null; then
    useradd -M -s /usr/sbin/nologin "$DMS_USER"
fi

(echo "$DMS_PASSWORD"; echo "$DMS_PASSWORD") | smbpasswd -a -s "$DMS_USER"
smbpasswd -e "$DMS_USER"

echo "[5/7] Samba konfigurieren..."
if grep -q "\[sage_archiv\]" /etc/samba/smb.conf; then
    echo "  Samba-Freigaben existieren bereits, überspringe..."
else
    cat >> /etc/samba/smb.conf << EOF

[sage_archiv]
   comment = Sage HR Archiv (Nur Lesen)
   path = $SAGE_ARCHIVE_PATH
   browsable = yes
   read only = yes
   guest ok = no
   valid users = $DMS_USER

[manual_scan]
   comment = Manuelle Scan-Eingabe
   path = $MANUAL_SCAN_PATH
   browsable = yes
   read only = no
   writable = yes
   guest ok = no
   valid users = $DMS_USER
   create mask = 0664
   directory mask = 0775
EOF
fi

echo "[6/7] Berechtigungen setzen..."
chown -R "$DMS_USER:$DMS_USER" "$SAGE_ARCHIVE_PATH" "$MANUAL_SCAN_PATH"
chmod 755 "$SAGE_ARCHIVE_PATH"
chmod 775 "$MANUAL_SCAN_PATH"

echo "[7/7] Dienste starten..."
systemctl restart smbd
systemctl enable smbd

if command -v ufw &>/dev/null; then
    ufw allow samba
fi

testparm -s 2>/dev/null | grep -A5 '\[sage_archiv\]\|\[manual_scan\]'

SERVER_IP=$(hostname -I | awk '{print $1}')

echo ""
echo "=============================================="
echo "INSTALLATION ABGESCHLOSSEN"
echo "=============================================="
echo ""
echo "Samba-Zugangsdaten:"
echo "  Benutzer: $DMS_USER"
echo "  Passwort: $DMS_PASSWORD"
echo ""
echo "Netzwerkpfade (von Windows):"
echo "  \\\\$SERVER_IP\\sage_archiv"
echo "  \\\\$SERVER_IP\\manual_scan"
echo ""
echo "Windows-Befehl zum Verbinden:"
echo "  net use S: \\\\$SERVER_IP\\sage_archiv /user:$DMS_USER $DMS_PASSWORD"
echo "  net use M: \\\\$SERVER_IP\\manual_scan /user:$DMS_USER $DMS_PASSWORD"
echo ""
echo "Nächster Schritt: Docker-Container starten"
echo "  cd ~/sage-local-dms && docker-compose up -d"
echo ""
