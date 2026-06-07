#!/usr/bin/env bash
# Lanzador único de @gdlscene: levanta la GUI de control y abre el navegador.
#
# La GUI es el panel desde el que se dispara TODO (pipeline de datos, memes,
# anuncios, agenda) sin que las piezas choquen. Lo único que NO se lanza aquí es
# `bot.py` (modo "mándale una foto al bot"), porque usa el mismo bot de Telegram
# que la generación y solo uno puede escuchar a la vez: préndelo aparte cuando
# quieras ese modo, y apágalo antes de generar desde la GUI.
#
# Uso:  ./run.sh           (Ctrl+C para apagar)
set -euo pipefail
cd "$(dirname "$0")"

PORT="${GDLSCENE_PORT:-8000}"
PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"

echo "▶ @gdlscene — panel de control en http://127.0.0.1:${PORT}/bandas"
echo "  (bot.py NO se levanta aquí; ver comentario en run.sh)"

# Abre el navegador en cuanto el servidor responda, sin bloquear el arranque.
( for _ in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:${PORT}/bandas" >/dev/null 2>&1; then
      open "http://127.0.0.1:${PORT}/bandas" 2>/dev/null || true
      break
    fi
    sleep 0.5
  done ) &

exec "$PY" -m uvicorn web.app:app --host 127.0.0.1 --port "${PORT}"
