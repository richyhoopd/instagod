#!/usr/bin/env bash
# Guardián de la demo del portal desde la Mac: mantiene viva la API (:8101) y el
# túnel de Cloudflare, y cuando el túnel cambia de URL actualiza API_URL en Vercel
# y redespliega el front. Uso: nohup scripts/deploy/portal_demo_guard.sh &
set -u
ROOT=/Users/ricardo/Work/personal/instagod
W=$ROOT/.claude/worktrees/portal-fase5
FRONT=/Users/ricardo/Work/personal/instagod-web-app-front
LOGDIR=$HOME/.oci; LOG=$LOGDIR/portal_guard.log; TLOG=$LOGDIR/cloudflared.log; ALOG=$LOGDIR/api-8101.log
STATE=$LOGDIR/portal_tunnel_url
log(){ echo "$(date '+%F %T') $*" >> "$LOG"; }

start_api(){
  ( cd "$W" && set -a && . "$ROOT/.env.portal-demo" && set +a && \
    nohup "$ROOT/.venv/bin/uvicorn" api.app:app --host 127.0.0.1 --port 8101 \
      --proxy-headers --forwarded-allow-ips='*' >> "$ALOG" 2>&1 & )
  log "API 8101 arrancada"; sleep 5
}
start_tunnel(){
  pkill -f "cloudflared tunnel --url http://127.0.0.1:8101" 2>/dev/null; sleep 1
  : > "$TLOG"; nohup cloudflared tunnel --url http://127.0.0.1:8101 >> "$TLOG" 2>&1 &
  for i in $(seq 1 30); do
    U=$(grep -a -A2 "quick Tunnel has been created" "$TLOG" | grep -aoE "https://[a-z0-9-]+\.trycloudflare\.com" | head -1)
    [ -n "$U" ] && break; sleep 2
  done
  [ -z "$U" ] && { log "túnel: no obtuve URL"; return 1; }
  log "túnel nuevo: $U"; echo "$U" > "$STATE"
  ( cd "$FRONT" && (vercel env rm API_URL production --yes >/dev/null 2>&1 || true) \
    && printf '%s' "$U" | vercel env add API_URL production >/dev/null 2>&1 \
    && vercel deploy --prod --yes >/dev/null 2>&1 ) && log "Vercel API_URL actualizado + redeploy" || log "ERROR actualizando Vercel"
}

while true; do
  curl -sf -m 4 http://127.0.0.1:8101/health >/dev/null || start_api
  U=$(cat "$STATE" 2>/dev/null || true)
  if [ -z "$U" ] || ! curl -sf -m 15 "$U/health" >/dev/null; then
    # el túnel puede tardar en propagarse; confirma antes de reiniciar
    sleep 20
    if [ -z "$U" ] || ! curl -sf -m 15 "$U/health" >/dev/null; then start_tunnel; fi
  fi
  sleep 60
done
