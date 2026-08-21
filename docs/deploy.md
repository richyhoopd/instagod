# Deploy de la API de instagod (Oracle Cloud Always Free)

Backend contenerizado (`api` + `worker` + `publisher` + `caddy`, y `daemon` opcional)
corriendo en una VM ARM gratuita de Oracle Cloud. El front vive en Vercel
(`richyhoopd/instagod-web-app-front`) y habla con esta API vía `API_URL`.

Recursos (medidos): API ~90 MB, publisher ~70 MB, worker ~550 MB pico en render,
pipeline de fotos +400–600 MB. `data/` ≈ 4 GB (fotos). Imagen Docker ≈ 2 GB.
La VM Always Free ARM (hasta 4 OCPU / 24 GB / 200 GB) sobra.

---

## 1. Crear la VM en Oracle Cloud (manual, ~15 min)

1. Cuenta en <https://cloud.oracle.com> → **Start for free**. Piden tarjeta
   (verificación, no cobran mientras uses sólo recursos *Always Free*).
   Elige la **home region** con cuidado: no se puede cambiar. Para México,
   `US West (Phoenix)` o `US East (Ashburn)`; `Brazil East (São Paulo)` suele tener
   más capacidad ARM.
2. Menú ☰ → **Compute → Instances → Create instance**:
   - **Image**: Ubuntu 24.04 (Canonical) — *aarch64* al elegir shape ARM.
   - **Shape**: `Ampere` → `VM.Standard.A1.Flex` → **4 OCPU / 24 GB** (tope gratis;
     si marca "Out of capacity", baja a 2/12 o reintenta más tarde / otra AD).
   - **Networking**: crea VCN nueva con subred pública; **asignar IPv4 pública: sí**.
   - **SSH keys**: sube tu `~/.ssh/id_ed25519.pub` (o genera y descarga la privada).
   - **Boot volume**: 100 GB (hasta 200 GB gratis en total).
3. Abre puertos en la red de Oracle (además del firewall de Ubuntu, que abre el
   script): **Networking → Virtual cloud networks → tu VCN → Security Lists →
   Default** → **Add Ingress Rules**:
   - Source `0.0.0.0/0`, protocol TCP, destination port `80`
   - Source `0.0.0.0/0`, protocol TCP, destination port `443`
4. Anota la **IP pública**. Opcional pero recomendado: **reserved public IP**
   (Networking → IP management → Reserved public IPs) para que no cambie.

## 2. Preparar la VM

```bash
ssh ubuntu@<IP>
curl -fsSL https://raw.githubusercontent.com/<tu-usuario>/instagod/master/scripts/deploy/bootstrap_oracle.sh -o bootstrap.sh
sudo bash bootstrap.sh          # Docker + Compose, abre 80/443 en iptables, swap 4G, /opt/instagod
exit && ssh ubuntu@<IP>         # re-login para que aplique el grupo docker
```

Si el repo es privado, en vez de `curl` copia el script con
`scp scripts/deploy/bootstrap_oracle.sh ubuntu@<IP>:`.

## 3. Subir el código, el `.env` y los datos

Desde tu Mac (checkout principal de instagod):

```bash
IP=<IP>
# código (sin .venv/data/out/secrets; respeta .gitignore + .dockerignore)
rsync -az --delete --exclude-from=.dockerignore --exclude .git ./ ubuntu@$IP:/opt/instagod/
# credenciales — .env local + bloque de servidor
scp .env ubuntu@$IP:/opt/instagod/.env
scp -r secrets/ ubuntu@$IP:/opt/instagod/secrets/
# datos (SQLite + fotos ≈ 4 GB; tarda según tu subida). Repetible: sólo copia lo nuevo.
rsync -az --info=progress2 data/ ubuntu@$IP:/opt/instagod/data/
```

En la VM, edita `/opt/instagod/.env` y agrega/ajusta el bloque de
`.env.server.example` (`ENV=prod`, `DB_PATH=/app/data/gdlscene.db`,
`INSTAGOD_MASTER_KEY`, `APP_URL`, `API_URL`, `API_DOMAIN`, `RESEND_API_KEY`,
`MAIL_FROM`). Si no tienes master key:

```bash
cd /opt/instagod && docker compose run --rm api python -m api.bootstrap --nueva-master-key
```

**Respalda `INSTAGOD_MASTER_KEY` fuera del servidor** (gestor de contraseñas):
sin ella los secretos cifrados por marca son irrecuperables.

## 4. Levantar

```bash
cd /opt/instagod
docker compose up -d --build        # primera vez: ~5–10 min (Chromium, OpenCV, onnxruntime)
docker compose ps
curl -s http://127.0.0.1/health     # vía Caddy → {"ok":true,...}
docker compose logs -f api worker publisher
```

Crear el primer admin (e importar a DB los secretos de gdlscene del `.env`):

```bash
docker compose run --rm api python -m api.bootstrap --admin tu@correo.com --nombre "Ricardo"
docker compose run --rm api python -m api.bootstrap --importar-env
```

## 5. Dominio y HTTPS

- Sin dominio: `API_DOMAIN=:80` → la API responde en `http://<IP>` (sin TLS).
  Vale para probar, **pero la cookie de sesión en `ENV=prod` es `Secure`** y el
  navegador no la guarda por HTTP → el login real no funciona hasta tener HTTPS.
- Con dominio: registro **A** `api.tudominio.com → <IP>`, pon
  `API_DOMAIN=api.tudominio.com` y `API_URL=https://api.tudominio.com` en `.env`,
  `docker compose up -d caddy`. Caddy saca el certificado solo (Let's Encrypt).
  Dominio gratis: un subdominio de DuckDNS (`xxx.duckdns.org`) también sirve.

## 6. Conectar el front (Vercel)

```bash
cd ~/Work/personal/instagod-web-app-front
vercel env add API_URL production      # https://api.tudominio.com
vercel deploy --prod --yes
```

`APP_URL` en el `.env` del servidor debe ser exactamente el origen del front
(`https://instagod-web-app-front.vercel.app`): se usa en CORS y en los links de
los magic links.

## 7. Migración de gdlscene (cuando el server esté verificado)

Hoy gdlscene corre en la Mac (launchd) y publica vía GitHub Actions
(`publish.yml`, porque tiene `SHEET_ID`). El publisher del server **salta** las
marcas con `SHEET_ID`, así que no hay doble publicación mientras conviven.

1. `rsync data/` final con la Mac apagada de tareas (para no perder filas).
2. Daemon de Telegram: sólo uno puede escuchar al bot. En la Mac
   `launchctl bootout gui/$(id -u)/com.gdlscene.approval-daemon` (o el
   `instalar_*.sh --desinstalar` correspondiente), luego en la VM
   `docker compose --profile gdlscene up -d daemon`.
3. Cuando quieras que el publisher del server publique gdlscene: quita
   `SHEET_ID` del `.env` del server y desactiva `publish.yml` en Actions.

## 8. Operación

```bash
docker compose pull && docker compose up -d --build   # actualizar código (tras rsync/git pull)
docker compose restart worker                          # reiniciar un servicio
docker compose logs --tail 200 worker                  # logs
docker system prune -f                                 # limpiar imágenes viejas
```

Backup diario mínimo (cron en la VM): `sqlite3 data/gdlscene.db ".backup
/opt/backups/gdlscene-$(date +%F).db"` + rsync de `data/` a un bucket
(Oracle Object Storage trae 20 GB gratis, o Backblaze B2 / Cloudflare R2).

Límites de memoria por servicio (`mem_limit` en compose): api 768 MB, worker
2 GB, publisher/daemon 512 MB. Ajusta si la VM es de 2/12 en vez de 4/24.
