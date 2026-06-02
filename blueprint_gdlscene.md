# Blueprint — Pipeline de memes automatizado (@gdlscene)

> **Propósito de este documento:** especificación técnica completa para construir el sistema con Claude Code. Está escrito para que un agente de código lo pueda implementar módulo por módulo sin ambigüedad. Léelo de arriba a abajo; el orden refleja el orden de construcción recomendado.

---

## 1. Resumen ejecutivo

Sistema que genera imágenes-meme estilo *The Onion* sobre la escena musical underground de Guadalajara, las pasa por aprobación humana vía Telegram, y las publica en Instagram en horarios calendarizados — con mínima intervención manual.

**Stack elegido:**

| Capa | Tecnología | Por qué |
|------|-----------|---------|
| Panel de control / cola | Google Sheets | Visual, barato, editable a mano |
| Lenguaje | Python 3.11+ | Flexibilidad total |
| Generación de caption | DeepSeek V4 Flash (API OpenAI-compatible), intercambiable con Claude | El más barato del mercado; módulo agnóstico |
| Composición de imagen | HTML/CSS → PNG con Playwright (headless) | Pixel-perfect, tipografía serif fácil |
| Hosting de imagen pública | Cloudinary (free tier) | IG Graph API exige `image_url` público |
| Aprobación | Bot de Telegram (polling) con botones inline | Apruebas desde el celular con un tap |
| Publicación | Instagram Graph API (Content Publishing) | Vía oficial de Meta |
| Scheduler de publicación | GitHub Actions (cron gratis) | Always-on sin servidor que mantener |

**Decisión arquitectónica central:** el sistema se parte en **dos procesos independientes** que NO corren al mismo tiempo:

- **Proceso A — Sesión de generación (local, on-demand, 1×/semana):** generas y apruebas el lote completo de la semana/mes en una sentada. Corre en tu máquina.
- **Proceso B — Worker de publicación (GitHub Actions, automático):** dispara solo en los horarios programados y publica lo ya aprobado, aunque tu computadora esté apagada.

Esto desacopla "trabajo creativo" (interactivo, esporádico) de "publicación" (desatendida, recurrente). Es la razón por la que NO necesitas un servidor prendido 24/7.

---

## 2. Diagrama de flujo

```
┌──────────────────────────────────────────────────────────────────────┐
│  PROCESO A — SESIÓN DE GENERACIÓN  (local, tú lo corres 1×/semana)     │
│                                                                        │
│  Google Sheet                                                          │
│  (rows status=pending) ──► generate.py                                 │
│       │                        │                                       │
│       │                        ├─1─► caption.py    (DeepSeek/Claude)   │
│       │                        ├─2─► compose.py     (HTML→PNG)         │
│       │                        ├─3─► host.py        (sube a Cloudinary)│
│       │                        └─4─► telegram_bot.py (envía a aprobar) │
│       │                                   │                            │
│       │                          ┌────────┴────────┐                   │
│       │                          ▼        ▼        ▼                   │
│       │                      ✅ Aprobar ❌ Rechazar 🔄 Regenerar       │
│       │                          │                                     │
│       └──────────◄───────────────┘                                     │
│   (escribe en el Sheet: status=approved, scheduled_datetime,           │
│    caption_final, imagen_url)                                          │
└──────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼  (la cola vive en el Sheet)
┌──────────────────────────────────────────────────────────────────────┐
│  PROCESO B — WORKER DE PUBLICACIÓN  (GitHub Actions cron, automático)  │
│                                                                        │
│  cron (cada hora) ──► publish.py                                       │
│                          │                                             │
│                          ├─ lee Sheet: status=approved                 │
│                          │   AND scheduled_datetime <= ahora           │
│                          ├─ instagram.py: crea container + publica     │
│                          └─ marca status=published, guarda ig_post_id  │
└──────────────────────────────────────────────────────────────────────┘

  PROCESO C — REFRESH DE TOKEN (GitHub Actions cron, cada ~50 días)
  refresca el long-lived token de Instagram antes de que expire (60 días).
```

---

## 3. Esquema de datos (el Google Sheet = cola + panel de control)

Una sola hoja, una fila por meme. Columnas:

| Columna | Tipo | Quién la llena | Descripción |
|---------|------|----------------|-------------|
| `id` | int | auto | Identificador único de la fila |
| `fecha_captura` | date | tú | Cuándo agregaste el material |
| `banda` | text | tú | Nombre real de la banda (ej. "Noisy Room") |
| `integrante` | text | tú | Nombre del miembro (ej. "Carlos Virgen") |
| `rol` | text | tú | Instrumento/rol (ej. "guitarrista") |
| `foto_url` | url | tú | Foto pública de la banda (input) |
| `foto_inset_url` | url | tú (opcional) | Imagen del círculo (objeto random); si vacío, se omite el inset |
| `tema_semilla` | text | tú (opcional) | Pista de tema para el caption; si vacío, IA elige libre |
| `caption_generado` | text | sistema | Lo que generó la IA |
| `caption_final` | text | sistema | El aprobado (puede diferir si regeneraste) |
| `imagen_compuesta_url` | url | sistema | PNG final hosteado en Cloudinary |
| `status` | enum | sistema | `pending` → `approved` → `published` / `rejected` / `error` |
| `scheduled_datetime` | datetime | sistema/tú | Cuándo debe publicarse (ISO 8601, tz America/Mexico_City) |
| `ig_post_id` | text | sistema | ID del post publicado (para auditoría) |
| `notas` | text | libre | Errores, comentarios |

**Lógica de calendarización:** en la sesión de generación, conforme apruebas, el sistema asigna `scheduled_datetime` automáticamente (ej. "siguiente slot disponible: 1 post/día a las 19:00, empezando mañana"). Configurable. El worker B solo mira `status=approved AND scheduled_datetime <= now()`.

---

## 4. Estructura del repositorio

```
gdlscene-bot/
├── README.md
├── requirements.txt
├── .env.example                 # plantilla de variables (NO subir el .env real)
├── .gitignore                   # ignora .env, __pycache__, *.png temporales
├── config.py                    # carga env vars, constantes (slots, tz, etc.)
│
├── src/
│   ├── sheets.py                # cliente Google Sheets (gspread)
│   ├── caption.py               # generación de caption (LLM agnóstico)
│   ├── compose.py               # render HTML→PNG (Playwright)
│   ├── host.py                  # upload a Cloudinary
│   ├── telegram_bot.py          # envío + manejo de aprobaciones
│   ├── instagram.py             # Graph API: container + publish
│   ├── scheduler.py             # asigna scheduled_datetime a aprobados
│   └── ig_token.py              # refresh del long-lived token
│
├── templates/
│   ├── meme.html                # plantilla de la imagen (HTML/CSS)
│   └── assets/
│       ├── fonts/               # fuente serif (ej. Tinos/PT Serif)
│       └── badge.svg            # opcional
│
├── generate.py                  # ENTRYPOINT Proceso A (local)
├── publish.py                   # ENTRYPOINT Proceso B (GitHub Actions)
│
└── .github/workflows/
    ├── publish.yml              # cron del worker de publicación
    └── refresh-token.yml        # cron del refresh de token
```

---

## 5. Especificación módulo por módulo

### 5.1 `config.py`
Carga variables de entorno con `python-dotenv`. Expone constantes:
- Credenciales (ver sección 7).
- `POSTING_SLOTS`: lista de horas de publicación por día (ej. `["19:00"]`).
- `POSTS_PER_DAY`: cuántos por día (default 1).
- `TIMEZONE = "America/Mexico_City"`.
- `LLM_PROVIDER`: `"deepseek"` | `"claude"` (selecciona el cliente en `caption.py`).

### 5.2 `sheets.py`
- Autentica con Service Account de Google (JSON key) vía `gspread`.
- `get_pending_rows()` → filas con `status=pending`.
- `get_due_rows()` → filas con `status=approved AND scheduled_datetime <= now`.
- `update_row(id, **fields)` → escribe cambios.
- Idempotencia: cada update por `id`, nunca por índice de fila.

### 5.3 `caption.py` — el corazón del proyecto
**Diseño agnóstico de proveedor:** DeepSeek expone una API **compatible con OpenAI**, así que usa el SDK `openai` apuntando a `base_url=https://api.deepseek.com`. Para cambiar a Claude, solo cambias cliente + `LLM_PROVIDER`.

```python
# pseudo-firma
def generate_caption(banda: str, integrante: str, rol: str,
                     tema_semilla: str | None = None) -> str: ...
```

**Prompt (estructura, few-shot):** el sistema sigue un patrón fijo aprendido de los ejemplos reales:
> *[Integrante real + banda real] + [afirmación mundana, absurda o sin relación] redactada con tono de nota seria/periodística.*

Few-shot con los ejemplos existentes (incluir en el prompt):
1. "El guitarrista de Noisy Room, Carlos Virgen, asegura que preferiría fumar crack antes que ver Stranger Things."
2. "Autoridades locales de Azerbaiyán investigan por qué los vendedores siguen citando al guitarrista de Kabala, Cesar, cuando se les pregunta por los precios de los dulces."
3. "El baterista de Lefnes, Álvaro, cuestiona si las cocinas modernas están diseñadas para un uso real."

Parámetros: `temperature` alta (0.9–1.1) para creatividad; devolver **1 caption** por llamada (la regeneración pide otro). Reglas en el system prompt: español, tono deadpan, sin emojis, longitud ~1-3 líneas, evitar afirmaciones difamatorias graves sobre personas reales (ver sección 8).

### 5.4 `compose.py` — render de la imagen
- Usa **Playwright** (Chromium headless).
- Carga `templates/meme.html`, inyecta variables (foto de fondo, inset, badge, caption) vía query params o reemplazo de plantilla (usar Jinja2).
- Renderiza a PNG a **1080×1350 px** (formato vertical 4:5 de Instagram).
- Guarda PNG temporal en disco, devuelve la ruta.

**Anatomía de la plantilla (`meme.html`):** replica el estilo de referencia:
- Foto de la banda ocupando ~2/3 superiores (cover, sin deformar).
- Inset circular abajo-izquierda con anillo verde (`border: 6px solid #1b5e3f`), recortado en círculo (`border-radius:50%; overflow:hidden`).
- Badge verde centrado sobre la línea divisoria: texto blanco "Año Anual 2025" (o "Our Annual Year 2025"), fondo `#1b5e3f`, esquinas redondeadas.
- Zona blanca inferior con el **titular en serif negrita** (fuente tipo Times/Georgia — usar **Tinos** o **PT Serif**, libres y embebibles), centrado.
- Footer: línea verde + handle "@gdlscene" en verde negrita serif.

### 5.5 `host.py`
- Sube el PNG a **Cloudinary** (SDK oficial, free tier ~25 GB/mes — sobra).
- Devuelve la URL pública `https://res.cloudinary.com/...` que IG necesita.
- Alternativas si prefieres: Cloudflare R2 + dominio público, o un bucket S3 público.

### 5.6 `telegram_bot.py`
- Librería: `python-telegram-bot`.
- En la sesión de generación corre en **polling** (no requiere servidor; vive solo mientras `generate.py` está activo).
- Por cada meme: envía la imagen compuesta + caption como caption del mensaje + teclado inline:
  - ✅ **Aprobar** → marca `approved`, dispara `scheduler.assign_slot()`.
  - ❌ **Rechazar** → marca `rejected` (y guarda el caption rechazado para feedback del prompt).
  - 🔄 **Regenerar** → llama `caption.generate_caption()` de nuevo, recompone, reenvía.
- El script espera a resolver todo el lote antes de terminar.

### 5.7 `instagram.py`
Flujo de 2 pasos de la Graph API (v21.0+):
1. `POST /{ig-user-id}/media` con `image_url` + `caption` → devuelve `creation_id` (container).
2. `POST /{ig-user-id}/media_publish` con `creation_id` → publica.
- Manejar el estado del container (a veces hay que esperar a que esté `FINISHED`).
- Reintentos con backoff; en fallo marca `status=error` + `notas`.

### 5.8 `scheduler.py`
- `assign_slot(row_id)`: encuentra el siguiente `scheduled_datetime` libre según `POSTING_SLOTS`/`POSTS_PER_DAY`, sin colisionar con otros aprobados.

### 5.9 `ig_token.py`
- Intercambia/refresca el long-lived token (válido 60 días) usando el endpoint de refresh de Meta.
- Lo corre Proceso C cada ~50 días.

### 5.10 Entrypoints
- `generate.py` (Proceso A): `sheets.get_pending_rows()` → loop {caption → compose → host → telegram} → al cerrar el lote, termina.
- `publish.py` (Proceso B): `sheets.get_due_rows()` → loop {instagram.publish → marca published}. Sin interacción.

---

## 6. GitHub Actions (Proceso B y C, gratis)

### `.github/workflows/publish.yml`
- Trigger: `schedule: cron` (ej. `"0 * * * *"` = cada hora; el filtro real es `scheduled_datetime <= now`).
- Pasos: checkout → setup-python → `pip install -r requirements.txt` → `python publish.py`.
- Secrets vía `${{ secrets.* }}` (ver sección 7). **No** se necesita Playwright aquí (la imagen ya está compuesta y hosteada).

### `.github/workflows/refresh-token.yml`
- Trigger: `cron` cada ~50 días (`"0 0 1 */1 *"` mensual es más seguro).
- Corre `python -m src.ig_token` y actualiza el secret (vía `gh` CLI / API de GitHub, o notifica para refresco manual).

> Repos públicos: minutos de Actions ilimitados. Privados: 2,000 min/mes gratis — un publish toma segundos, sobra.

---

## 7. Secrets y credenciales necesarias

Reúne esto ANTES de construir (ponlo en `.env` local y en GitHub Secrets para el worker):

| Variable | De dónde sale |
|----------|---------------|
| `DEEPSEEK_API_KEY` | platform.deepseek.com (o `ANTHROPIC_API_KEY` si usas Claude) |
| `GOOGLE_SA_JSON` | Google Cloud → Service Account → JSON key; comparte el Sheet con ese email |
| `SHEET_ID` | el ID de la URL del Google Sheet |
| `CLOUDINARY_URL` | dashboard de Cloudinary |
| `TELEGRAM_BOT_TOKEN` | @BotFather en Telegram |
| `TELEGRAM_CHAT_ID` | tu chat id (para que el bot te escriba solo a ti) |
| `IG_USER_ID` | ID de la cuenta de IG Business |
| `IG_ACCESS_TOKEN` | long-lived token de la app de Meta |
| `META_APP_ID` / `META_APP_SECRET` | Meta for Developers (para refresh de token) |

---

## 8. Prerrequisitos de Meta / Instagram (el cuello de botella de setup)

Esto es lo que más fricción tiene; resuélvelo primero:

1. Convierte la cuenta de IG a **Business** (o Creator) y vincúlala a una **página de Facebook**.
2. Crea una **App en Meta for Developers**.
3. Agrega el producto **Instagram Graph API** y solicita el permiso **`instagram_content_publish`**.
4. Para publicar en TU propia cuenta puedes operar en modo desarrollo agregándote como tester/admin; para uso pleno/estable Meta pide **App Review** del permiso. Documenta el flujo de tokens.
5. La imagen DEBE estar en una URL pública al momento de publicar (por eso Cloudinary).
6. Límites operativos: **25 publicaciones / 24h** por cuenta y **200 requests/hora** — irrelevante para 1 post/día.
7. El token de larga duración vence a los **60 días**: el refresh automático (Proceso C) es obligatorio o el bot se cae solo.

> Nota: la "calendarización nativa" de Instagram (hasta 75 días) vive en Meta Business Suite/app, no es un parámetro confiable de la API de publicación. Por eso usamos nuestra propia cola + cron: control total.

---

## 9. Riesgo a manejar desde el día 1 (no técnico, pero crítico)

El sistema pone **afirmaciones falsas en boca de personas reales identificables** usando sus fotos. Es sátira (modelo *The Onion*), pero los blancos son músicos locales reales, no figuras públicas grandes. Riesgos: difamación, quemar la relación con la escena que es tu audiencia. Mitigaciones a codificar como política:
- Marca de sátira/parodia visible en el perfil y/o las imágenes.
- Mantener el absurdo *evidentemente* ficticio (lo de los dulces y las cocinas funciona; afirmaciones sobre drogas reales atribuidas a una persona nombrada son las más riesgosas — considéralo en las reglas del prompt).
- Vía rápida de "bajar este post" si alguien lo pide.
- Definir esto ANTES de automatizar: a escala, los errores también se automatizan.

---

## 10. Loop de mejora del caption (el diferenciador real)

Cada caption que **rechazas** se guarda; cada **aprobado** también. Periódicamente, alimenta los aprobados como nuevos ejemplos few-shot y los rechazados como ejemplos negativos en el prompt de `caption.py`. En 2–3 semanas la voz editorial se afina sola. Aquí está el 70% del valor del proyecto — invierte tiempo en el prompt, no en la plomería.

---

## 11. Orden de construcción sugerido (para Claude Code)

1. **Setup Meta/Instagram** (sección 8) — fuera de código, pero bloquea todo lo demás.
2. `config.py` + `.env.example` + estructura de repo.
3. `sheets.py` + crear el Google Sheet con el esquema de la sección 3.
4. `caption.py` (DeepSeek) — probar aislado con datos dummy.
5. `templates/meme.html` + `compose.py` — iterar hasta clonar el estilo de referencia.
6. `host.py` (Cloudinary).
7. `instagram.py` — probar publicación manual de UNA imagen primero.
8. `telegram_bot.py` + `scheduler.py`.
9. `generate.py` (Proceso A completo, end-to-end local).
10. `publish.py` + `.github/workflows/publish.yml`.
11. `ig_token.py` + `.github/workflows/refresh-token.yml`.
12. Loop de feedback (sección 10).

---

## 12. requirements.txt (base)

```
python-dotenv
gspread
google-auth
openai            # cliente para DeepSeek (OpenAI-compatible) y/o anthropic
anthropic         # solo si usas Claude
playwright
jinja2
cloudinary
python-telegram-bot
requests
pytz
```
(tras instalar Playwright: `playwright install chromium`)
