#!/usr/bin/env bash
# Instala (o quita) el LaunchAgent que refresca el token de IG cada semana.
# Corre `python -m src.ig_token --aplicar`: refresca contra Meta, escribe .env y
# actualiza el secret IG_ACCESS_TOKEN del repo con el gh local. Si falla avisa
# por Telegram. Refrescar semanal mantiene el token perpetuamente lejos del
# vencimiento (cada refresh lo extiende 60 días), aguantando semanas de Mac
# apagada.
#
#   ./scripts/instalar_refresh_token.sh              instala/recarga
#   ./scripts/instalar_refresh_token.sh --quitar     desinstala
#   PLIST_DEST=/tmp/x.plist ... --solo-generar       solo escribe el plist (tests)
#
# Contexto: el token expiró el 1-ago-2026 sin aviso (el workflow de Actions que
# debía renovarlo era inválido y nunca corrió) y la publicación a IG quedó
# muerta 5 días. El refresh vive LOCAL porque Actions no puede escribir secrets
# sin un PAT y el .env local también necesita el token fresco.
set -euo pipefail

LABEL="com.gdlscene.refresh-token"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"

PYTHON="$REPO/.venv/bin/python"
LOG="$REPO/data/logs/refresh_token.log"

PLIST_DEST="${PLIST_DEST:-$HOME/Library/LaunchAgents/$LABEL.plist}"

generar_plist() {
    mkdir -p "$(dirname "$PLIST_DEST")"
    cat > "$PLIST_DEST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>-m</string>
        <string>src.ig_token</string>
        <string>--aplicar</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$REPO</string>
    <key>RunAtLoad</key>
    <false/>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>1</integer>
        <key>Hour</key>
        <integer>10</integer>
        <key>Minute</key>
        <integer>15</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$LOG</string>
    <key>StandardErrorPath</key>
    <string>$LOG</string>
</dict>
</plist>
PLIST
    plutil -lint "$PLIST_DEST" >/dev/null
}

quitar() {
    local domain="gui/$(id -u)"
    if launchctl print "$domain/$LABEL" >/dev/null 2>&1; then
        launchctl bootout "$domain/$LABEL"
        echo "Desinstalado: $LABEL"
    else
        echo "No estaba cargado: $LABEL"
    fi
    [ -f "$PLIST_DEST" ] && rm -f "$PLIST_DEST" && echo "Borrado $PLIST_DEST"
}

instalar() {
    generar_plist
    echo "Plist generado y validado: $PLIST_DEST"
    local domain="gui/$(id -u)"
    launchctl bootout "$domain/$LABEL" >/dev/null 2>&1 || true
    launchctl bootstrap "$domain" "$PLIST_DEST"
    echo "Cargado en launchd: refresh del token cada lunes 10:15."
    echo "Log: $LOG"
}

case "${1:-}" in
    --quitar)        quitar ;;
    --solo-generar)  generar_plist; echo "Plist generado: $PLIST_DEST" ;;
    "")              instalar ;;
    *)               echo "Uso: $0 [--quitar | --solo-generar]" >&2; exit 2 ;;
esac
