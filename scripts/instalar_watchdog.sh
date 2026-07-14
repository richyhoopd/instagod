#!/usr/bin/env bash
# Instala (o quita) el LaunchAgent del watchdog del approval-daemon. Corre cada
# 2 min: si el daemon deja de latir (poller zombie), lo reinicia y avisa por TG.
# Genera el plist con rutas absolutas del repo actual, lo valida con plutil y lo
# carga con launchctl bootstrap. Idempotente.
#
#   ./scripts/instalar_watchdog.sh              instala/recarga
#   ./scripts/instalar_watchdog.sh --quitar     desinstala
#   PLIST_DEST=/tmp/x.plist ... --solo-generar  solo escribe el plist (tests)
#
# Contexto: incidente 14/jul — un error de red sin manejar mató el poller sin
# que el proceso saliera; KeepAlive no lo recupera (sólo revive al SALIR).
set -euo pipefail

LABEL="com.gdlscene.daemon-watchdog"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"

PYTHON="$REPO/.venv/bin/python"
LOG="$REPO/data/logs/daemon_watchdog.log"

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
        <string>src.daemon_watchdog</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$REPO</string>
    <key>RunAtLoad</key>
    <true/>
    <key>StartInterval</key>
    <integer>120</integer>
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
    echo "Cargado en launchd: revisa el daemon cada 120s."
    echo "Log: $LOG"
}

case "${1:-}" in
    --quitar)        quitar ;;
    --solo-generar)  generar_plist; echo "Plist generado: $PLIST_DEST" ;;
    "")              instalar ;;
    *)               echo "Uso: $0 [--quitar | --solo-generar]" >&2; exit 2 ;;
esac
