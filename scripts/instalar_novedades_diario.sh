#!/usr/bin/env bash
# Instala (o quita) el LaunchAgent que corre la detección de novedades (releases
# nuevos) a las 09:00. Genera el plist con rutas absolutas del repo actual, lo
# valida con plutil y lo carga con launchctl bootstrap. Idempotente.
#
#   ./scripts/instalar_novedades_diario.sh              instala/recarga
#   ./scripts/instalar_novedades_diario.sh --quitar     desinstala
#   PLIST_DEST=/tmp/x.plist ... --solo-generar          solo escribe el plist (tests)
#
# Spec: docs/superpowers/specs/2026-06-07-fetch-incremental-design.md (Frente C).
set -euo pipefail

LABEL="com.gdlscene.novedades"

# El script vive en <repo>/scripts/; el repo es su directorio padre.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"

PYTHON="$REPO/.venv/bin/python"
LOG="$REPO/data/launchd_novedades.log"

# Destino del plist: override por env (tests) o LaunchAgents del usuario.
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
        <string>src.novedades</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$REPO</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$LOG</string>
    <key>StandardErrorPath</key>
    <string>$LOG</string>
</dict>
</plist>
PLIST

    # Validar antes de intentar cargarlo: un plist mal formado no debe llegar a launchctl.
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
    # bootout previo = idempotente: recargar el plist nuevo sin error si ya existía.
    launchctl bootout "$domain/$LABEL" >/dev/null 2>&1 || true
    launchctl bootstrap "$domain" "$PLIST_DEST"
    echo "Cargado en launchd: corre diario a las 09:00."
    echo "Log de ejecuciones: $LOG"
}

case "${1:-}" in
    --quitar)        quitar ;;
    --solo-generar)  generar_plist; echo "Plist generado: $PLIST_DEST" ;;
    "")              instalar ;;
    *)               echo "Uso: $0 [--quitar | --solo-generar]" >&2; exit 2 ;;
esac
