# Editor v2: índice de planes y contrato de interfaces

Spec: `docs/superpowers/specs/2026-10-06-editor-escena-v2-design.md` (commit e87942f).
Rama: `feat/editor-v2` (worktree `.claude/worktrees/editor-v2`, sale de `master` 38f30e9).

## Orden

| # | Plan | Depende de | Entrega por sí solo |
|---|---|---|---|
| 1 | `2026-10-06-editor-v2-01-escena-backend.md` | — | Escena v2 validada, v1→v2, `a_html` v2, formato 1:1, la API acepta y devuelve v2, `estado=todas` |
| 2 | `2026-10-06-editor-v2-02-editor-frontend.md` | 1 | Editor tipo Figma que guarda, previsualiza y activa. **Arregla la pantalla rota** |
| 3 | `2026-10-06-editor-v2-03-assets.md` | 1, 2 | `brand_assets`, proveedores gratis de foto y video, quitar fondo, panel de assets, Fontsource |
| 4 | `2026-10-06-editor-v2-04-chat-ia.md` | 1, 2, 3 | Kinds Jinja, cliente Claude con herramientas y visión, extracción a capas, chat que crea y edita |
| 5 | `2026-10-06-editor-v2-05-ig-seguidos.md` | 3 | Fuente «Seguidos de IG» para cualquier marca |

Los planes 3 y 5 pueden ir en paralelo con el 4 una vez que el 3 entregue `brand_assets`.

## Verificaciones previas (hechas 2026-10-06)

- `react-moveable` 0.56.0 y `react-selecto` 1.26.3: MIT. Último publish 2023-12, último push 2024-06, 454 issues abiertos. Sin `findDOMNode`. ⚠️ No probadas en React 19.2: el Task 1 del plan 2 es un smoke test en navegador, y si fallan se usa el plan B (manijas propias a partir de `lienzo.tsx` v1).
- `zustand` 5.0.15 e `immer` 11.1.21: MIT y mantenidas.

## Hechos del repo en los que se apoyan todos los planes

- Pytest: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest` desde la raíz del worktree. El fixture `api_cliente` vive en `tests/conftest.py` y devuelve `(cli, cx, H)`, con `H.usuario(email, *, admin=False, marcas=((account_id, rol),))`, `H.login(uid)` y `H.logout()`. No hay `H.marca`: las marcas se insertan con `db.insert(cx, "accounts", ...)`. Roles: `manager` y `editor` (`src/users.py:17`). `init_db` siembra la cuenta 1 `gdlscene`. Los jobs se leen con `db.get(cx, "jobs", id)`.
- Lint: `/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/`.
- DB: `src/db.py`. Las columnas nuevas van en `_MIGRATIONS` **y** en la allowlist `TABLES`. Las tablas nuevas van en `src/schema.sql` (`CREATE TABLE IF NOT EXISTS`). Para cambiar un CHECK hay que reconstruir la tabla; el patrón es `_migrar_check_tipo_queue` (`db.py:389`).
- Servicio de plantillas: `src/plantillas/__init__.py`. Se guarda con `nueva_version(...)`; `_validado` recompila el HTML desde el layout.
- Router: `api/routers/plantillas.py`, `prefix="/brands/{slug}"`. Usa `marca_para(slug, cx, user, minimo="manager")` y `_plantilla_de_marca`.
- Jobs: se encolan con `jobs.crear(cx, tipo, account_id, payload, creado_por=)`. El handler `(cx, job) -> dict` se registra en `HANDLERS` (`src/jobs/handlers.py:744`).
- Frontend: `frontend/`, pnpm 11, Next 16.3.1, React 19.2. El editor está en `app/b/[slug]/templates/[id]/`. El cliente HTTP es `lib/api.ts` (`get/post/patch/put/del/postForm`). Para jobs, `hooks/use-job.ts` (`useJob`).

## Contrato de interfaces entre planes

Si un plan necesita cambiar un nombre de esta lista, se cambia aquí primero.

### Plan 1 → todos (Python, `src/plantillas/escena.py`)
```python
FORMATOS: dict[str, tuple[int, int]] = {"4x5": (1080, 1350), "1x1": (1080, 1080), "9x16": (1080, 1920)}
ASPECTO_DE_FORMATO = {"4x5": "4:5", "1x1": "1:1", "9x16": "9:16"}   # columna brand_templates.aspecto
TIPOS = ("text", "image", "video", "shape", "svg", "group")
MAX_CAPAS = 80
class EscenaInvalida(ContratoInvalido): ...
def validar(escena: dict, contrato: dict, *, familias: set[str] | None = None) -> None
def v1_a_v2(layout: dict, aspecto: str) -> dict
def normalizar(layout: dict | None, aspecto: str) -> dict          # siempre devuelve v2
def a_html(escena: dict, contrato: dict, *, fuentes: list[dict] | None = None) -> str
def reformatear(escena: dict, formato: str) -> dict                # usa capa["anclaje"]
def _font_faces(capas: list[dict], fuentes: list[dict] | None) -> str   # lo reusa el plan 4
# src/plantillas/__init__.py
def escena_de(fila: dict) -> dict | None                           # v2 normalizada; None si legacy. layout_de queda crudo
def compilar(layout: dict, contrato: dict, *, fuentes: list[dict] | None = None) -> str   # despacha v1/v2
# src/plantillas/contrato.py: CAMPOS_SISTEMA = ("fonts_dir", "fotos_dir", "assets_dir"); render.contexto(..., assets_dir=None)
```
- Capa v2: los campos del spec §1. Los `id` siguen el regex v1 `^[a-z][a-z0-9_-]{0,31}$`. `group` lleva `hijos: list[str]` (ids). Los colores aceptan `#rrggbb`, `rgba(...)` o `token:<nombre>`.
- `src` de imagen y video: ruta relativa `assets/<archivo>` (→ `{{ assets_dir }}`) o `fotos/<archivo>` (→ `{{ fotos_dir }}`, lo que deja `v1_a_v2`).
- `GET /brands/{slug}/files/assets/{archivo}` es del **plan 1** (Task 9), rol `manager`. Lista blanca: `.png .jpg .jpeg .webp .gif .svg .mp4 .webm`; `.svg` con CSP `sandbox`. El plan 3 llena la carpeta y no redefine la ruta.

### Plan 2 → planes 3 y 4 (TypeScript)
- `frontend/lib/escena.ts`: tipos `Escena`, `Capa`, `CapaTexto`, `CapaImagen`, `Formato`, `Op` y la función `aplicarOps(escena, ops): Escena`.
  ```ts
  type Op = { op: "set"; capa: string; ruta: string; valor: unknown }   // ruta con puntos: "estilo.color"
          | { op: "add"; capa: Capa; indice?: number }
          | { op: "del"; capa: string };
  ```
- `frontend/stores/editor.ts`: hook zustand `useEditor` con las acciones `cargar(escena)`, `aplicar(ops: Op[], etiqueta?: string)` (un paso de deshacer), `agregarCapa(capa: Capa)`, `seleccionar(ids: string[])`, `deshacer()`, `rehacer()`, y los campos `escena`, `seleccion`, `sucio`.
- `frontend/app/b/[slug]/templates/[id]/_components/panel-lateral.tsx`: `PanelLateral({ pestanas }: { pestanas: { id: string; etiqueta: string; contenido: ReactNode }[] })`. Los planes 3 y 4 solo agregan una pestaña en `page.tsx`.

### Plan 3 → planes 4 y 5 (Python, paquete `src/assets/`)
```python
# src/assets/__init__.py
BRANDS_DIR = config.BASE_DIR / "data" / "brands"   # monkeypatcheable; los submódulos lo leen como assets.BRANDS_DIR
@dataclass
class Candidata:                                    # from src.assets import Candidata
    proveedor: str; id_origen: str; tipo: str          # "imagen" | "video"
    url: str; preview_url: str; ancho: int | None; alto: int | None
    autor: str | None; licencia: str | None; url_origen: str | None
    ig_handle: str | None = None; source_post_id: str | None = None
    def a_dict(self) -> dict
# src/assets/buscar.py
def buscar_con_avisos(cx, account_id: int, slug: str, q: str, *, tipo: str = "imagen",
                      proveedores: list[str] | None = None, n: int = 20) -> tuple[list[Candidata], list[str]]
def buscar(...) -> list[Candidata]                  # mismos args; solo las candidatas
# src/assets/biblioteca.py
class AssetInvalido(ValueError)
def descargar(url: str, *, hosts: tuple[str, ...] | None, tope: int) -> bytes
def importar(cx, account_id: int, slug: str, cand: Candidata, *, tags=None) -> dict   # fila; dedup por sha
#   url "local:assets/<archivo>" -> fila existente de ESA marca (AssetInvalido si no); "local:fotos/<x>" -> copia
def ruta_de(slug: str, archivo: str) -> Path                             # assets.BRANDS_DIR/<slug>/assets/<archivo>
# src/assets/recorte.py
def quitar_fondo(origen: Path, destino: Path) -> Path                    # rembg; recorta al contenido
# Registro: src/assets/proveedores/__init__.py
PROVEEDORES: dict[str, type[Proveedor]]   # {c.nombre: c for c in (...)}
# src/assets/proveedores/base.py
class Proveedor:
    nombre: str; tipos: tuple[str, ...]; llave: str | None; hosts: tuple[str, ...] | None; de_pago: bool
    def __init__(self, *, cx=None, account_id=None, slug="", creds=None, config=None)
    def buscar(self, q: str, *, tipo: str = "imagen", n: int = 20) -> list[Candidata]
```
- Candidatas locales (`carpeta`, `ig_seguidos`): `url="local:assets/<archivo>"`, `preview_url="/brands/<slug>/files/assets/<archivo>"` (sin `/api`).
- Tabla `brand_assets` según el spec §4 (`archivo` es el nombre dentro de `assets/`; `recorte_archivo` es opcional).
- `brand_sources.kind` acepta `'video'`. El proveedor `ig_seguidos` se registra en el plan 5.

### Plan 4 (Python)
```python
# src/llm_claude.py
def pedir_herramienta(*, system: str, mensajes: list[dict], herramienta: dict,
                      imagenes: list[Path] = (), modelo: str | None = None,
                      uso: list[dict] | None = None, max_tokens: int = 8192) -> dict
# config.DISENO_MODELO = os.getenv("DISENO_MODELO", "claude-sonnet-5-5")
# src/plantillas/ops.py
def aplicar(escena: dict, ops: list[dict]) -> dict     # misma semántica que aplicarOps de TS
# src/plantillas/kinds/__init__.py
KINDS: tuple[str, ...]   # side, stat, vs, compare, list, cta, meme, historia, cita, propiedad
# src/plantillas/extraer.py
def extraer(html: str, *, slug: str, tokens: dict, fuente: str) -> tuple[bytes, dict, dict]   # png, escena, muestras
# src/plantillas/chat.py
def crear(cx, marca, mensaje, *, formato="4x5", uso=None) -> tuple[dict, dict, dict]      # escena, contrato, meta
def editar(cx, marca, escena, contrato, mensaje, *, uso=None) -> tuple[list, dict, dict]  # ops, escena, meta
```
- Job `diseno.chat`. Resultado: `{"escena": {...}}` al crear y `{"ops": [...]}` al editar.

### Plan 5 (Python)
- Tabla `brand_ig_cuentas`. Proveedor `ig_seguidos(base.Proveedor)` (busca en `brand_assets` con `proveedor='ig_seguidos'`; se suma solo vía `buscar._proveedores_extra` si la marca tiene assets de IG). Jobs `ig.importar_seguidos` e `ig.ingerir`.

## Reglas comunes a todos los planes

- TDD: primero la prueba que falla, luego el código mínimo, luego verde. Un commit por task.
- Nada de push ni de deploy a la VM. Solo commits locales en `feat/editor-v2`.
- No se toca `src/image_sources.py` ni `layout.py` v1, salvo para despachar por versión. El slideshow y los diseños v1 siguen funcionando sin cambios.
- Las pruebas sin red usan respuestas grabadas en `tests/fixtures/assets/`. Las de red llevan `@pytest.mark.lento`.
