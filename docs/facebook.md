# Facebook por marca

Cada marca publica en SU página de Facebook. No hay credenciales globales: una
marca sin `FB_PAGE_ID` + `FB_PAGE_ACCESS_TOKEN` no intenta FB (ni usa las de
gdlscene).

## Credenciales

| Clave | Qué es |
|---|---|
| `FB_PAGE_ID` | Página de Facebook: ID de la página donde se publica |
| `FB_PAGE_ACCESS_TOKEN` | Acceso a Facebook: token de página con `pages_manage_posts` |

- Portal: Ajustes → Credenciales (cifradas en `brand_secrets`, se muestran como "termina en XXXX").
- Alternativa en env: `FB_PAGE_ID__<SLUG>` y `FB_PAGE_ACCESS_TOKEN__<SLUG>`.
- Orden de resolución: `brand_secrets` → env con sufijo → env global solo para gdlscene
  (`config.account_creds`). Para dejar gdlscene sin env global:
  `docker compose exec -T api python scripts/migrar_fb_gdlscene.py`.
- Botón "Probar Facebook" (`POST /brands/{slug}/facebook/test`): nombre de la
  página, tipo de token (debe ser `PAGE`), permisos (debe traer
  `pages_manage_posts`) y expiración. Cualquier aviso deja `ok: false`.

## Token de página que no expira (usuario del sistema)

1. https://business.facebook.com/settings/system-users → Agregar (rol Admin).
2. "Asignar activos":
   - la página, con control total (o "Crear contenido");
   - la app de Meta que se usa para publicar.
3. "Generar token" con la app y los permisos `pages_manage_posts`,
   `pages_read_engagement`, `pages_show_list`. Expiración: Nunca.
4. Con ese token de usuario del sistema, sacar el de página:
   `curl -s "https://graph.facebook.com/v25.0/<PAGE_ID>?fields=access_token&access_token=<TOKEN_SYSTEM_USER>"`
5. Pegar `access_token` en "Acceso a Facebook" y el ID en "Página de Facebook";
   después "Probar Facebook": debe decir token PAGE y "no expira".

Un token de usuario normal (Graph API Explorer) dura horas o 60 días y `/me/accounts`
puede venir vacío si la página no está asignada: no sirve.

## Publicación

- `src/publisher.py` publica las filas `plataforma='facebook'` vencidas, aprobadas
  y programadas de cada marca con FB configurado. Nunca historias.
- Foto → `/{page}/photos`; carrusel → fotos `published=false` + `/{page}/feed`
  con `attached_media`; video o `formato='reel'` → `/{page}/videos`
  (`file_url`, o subida reanudable para archivos locales > 25 MB).
  `facebook.publicar_reel` existe para `/video_reels` pero el publisher no lo usa.
- IG y FB fallan por separado: cada fila guarda su resultado en
  `destinos_json.{instagram|facebook}` (`ok`, `id`, `url` o `error`) y Telegram
  avisa por destino.
- Reintentos con backoff 1 s, 2 s solo en códigos 1, 2, 4, 17, 341 y HTTP 5xx.
  190 (token), 200 (permiso) y 10 (permiso de app) fallan a la primera.
- Apagado general: `PUBLISHER_FB=0`.
