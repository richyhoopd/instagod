# Portal de colaboradores — Fase 4: frontend Next (dashboard)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** El dashboard de colaboradores en `frontend/` (Next App Router): login por magic link, switcher de marcas, dashboard, calendario estilo Buffer, wizard de carruseles con seguimiento de job, biblioteca, settings completos por marca y admin — hablando con la API vía rewrites same-origin.

**Architecture:** `frontend/` autocontenido (Next + TS + Tailwind v4 + shadcn/ui + TanStack Query + react-hook-form/zod + dnd-kit). `next.config.ts` con `rewrites` `/api/:path*` → `${API_URL}/:path*` (cookie httpOnly funciona same-origin). Cliente API tipado en `lib/api.ts` (fetch con `credentials:"include"` — same-origin igual lo manda—, manejo del shape `{error, detalle, campo}`); TanStack Query para estado de servidor; polling de jobs cada 2 s. `middleware.ts` redirige a `/login` sin cookie (presencia de cookie legible: como la cookie es httpOnly el middleware solo comprueba `request.cookies.has("instagod_session")` — el server la puso con path=/; si no está → login). Español en toda la UI. Densidad estilo Linear/Buffer, dark mode por `prefers-color-scheme`, acento por marca vía CSS var `--brand` (color_marca).

**Tech Stack:** Next (App Router, `create-next-app` última estable), TypeScript, Tailwind v4, shadcn/ui, @tanstack/react-query, react-hook-form + zod, @dnd-kit/core, lucide-react, vitest + @testing-library/react + msw (tests).

**Spec:** `docs/superpowers/specs/2026-08-17-portal-colaboradores-design.md` §10-§12. La API (Fases 1-3) expone: auth magic link + cookie; `/me`; brands CRUD + secrets + pruebas telegram/instagram/llm; queue/slots/aprobar/rechazar/regenerar; slideshows→job + jobs; prompts/probar; presets+preview; logo; sources/fotos/topics.

## Global Constraints

- Commits sin firma de Claude; identidad `richyhoopd <theilluminatiduck@gmail.com>`. Mensajes `feat(front): ...`.
- TODO el código nuevo vive bajo `frontend/`; NO tocar Python ni `docs/` salvo el README de frontend. Git: la carpeta `frontend/` entra completa salvo `node_modules/.next` (crear `frontend/.gitignore`).
- UI en español. Componentes funcionales + hooks, sin clases (regla global del usuario). Tailwind para estilos.
- `pnpm` como package manager. Cada task termina con `pnpm build` (y `pnpm test` cuando existan tests) verdes, y commit.
- El cliente API NUNCA guarda tokens en localStorage (cookie httpOnly es la sesión). Errores de la API se muestran con su `detalle`.
- Roles en UI: `admin` ve todo; `manager` settings de sus marcas; `editor` solo contenido (settings ocultos salvo lectura de perfil/estilos) — el gating visual NO sustituye al de la API.
- Estados de fila (colores consistentes): generando (gris animado), borrador (gris), pendiente (ámbar), programado (azul), publicado (verde), rechazado (rojo tenue), error (rojo), descartado (gris tachado).
- Env: `API_URL` (rewrites; default `http://127.0.0.1:8100`). Un solo `frontend/lib/api.ts` centraliza fetch.

## Tareas

### Task 1: Scaffold + auth + shell
`pnpm create next-app@latest frontend` (TS, App Router, Tailwind, src-dir NO, eslint sí) + deps (shadcn init + button/card/dialog/input/label/badge/tabs/select/dropdown-menu/sonner, tanstack-query, rhf+zod, dnd-kit, lucide). `next.config.ts` rewrites a `process.env.API_URL`. `lib/api.ts`: `api<T>(path, init?) -> Promise<T>` lanzando `ApiError {status, error, detalle, campo}`; helpers `get/post/patch/put/del`. `app/providers.tsx` (QueryClient + Toaster). `middleware.ts` (sin cookie → /login; /login y /auth/* públicos). Páginas: `/login` (form email → POST /api/auth/magic-link → "revisa tu correo"; en dev muestra hint de que el link sale en el log de la API), `/auth/callback` informativo. Hook `useMe()` (GET /api/me). Layout raíz con fuente Inter, tema oscuro/claro. **Verifica:** `pnpm build` verde; commit `feat(front): scaffold Next + auth por magic link + cliente API`.

### Task 2: Marcas + dashboard
`/brands`: grid de tarjetas (logo o inicial con color_marca, nombre, @handle, badges de `creds_faltantes`, contador de pendientes vía `GET queue?estado=pendiente`); admin ve botón "Nueva marca" (dialog con form slug/nombre/handle/ciudad/color → POST /brands). Layout `/b/[slug]` con nav lateral (Dashboard, Calendario, Crear, Biblioteca, Ajustes — Ajustes solo manager/admin) y `--brand` desde el color de la marca. Dashboard `/b/[slug]`: próximas publicaciones (queue programado ordenado, 5), pendientes de aprobar (cards con aprobar/rechazar inline), salud (3 chips que llaman a los endpoints `*/test` on-demand con botón), temas sugeridos (topics top 5 con botón "Crear carrusel" → link a /create?topic=). Commit `feat(front): switcher de marcas y dashboard por marca`.

### Task 3: Calendario Buffer
`/b/[slug]/calendar`: vista semana (7 columnas, navegación ← hoy →) y mes (grid). Datos: `GET queue?desde&hasta` + `GET slots/proximos`. Tarjetas con thumbnail (primera URL de imagen_url si es JSON list o la url directa), estado con color, hora. Huecos de la malla como slots punteados con "+ crear". Drag-drop (dnd-kit) de tarjetas programado/pendiente a otro slot → `PATCH {scheduled_datetime}`; 409 → toast + revert; optimistic update con rollback. Click → Drawer/Dialog: carrusel de imágenes (scroll-snap), caption editable (PATCH), botones Aprobar (POST aprobar → muestra slot asignado), Rechazar, Regenerar (tipo slideshow), Eliminar; muestra `error` de la fila si existe y botón "Reintentar" (= PATCH reprogramar al siguiente slot libre). Móvil: lista por día. Commit `feat(front): calendario semanal/mensual con drag-drop y drawer de aprobación`.

### Task 4: Wizard de creación + biblioteca
`/b/[slug]/create` (acepta `?topic=id`): pasos — 1 Tema (input + lista de topics con selección), 2 Formato (chips de m.formatos vía GET /brands/{slug}), 3 Estilo (cards de GET presets con mini-preview si existe archivo), 4 Fuentes (orden actual de sources kind=imagen, toggle), 5 Slides (slider 3-10) → Generar (POST slideshows → job_id) → pantalla de progreso (polling GET jobs/{id} cada 2 s: barra `progreso`, log tail legible) → al `ok` con queue_id: carrusel resultado (GET queue/{qid}) con caption, botones "Aprobar y programar" (muestra próximos slots, elige uno → aprobar + si difiere PATCH) y "Rechazar y regenerar". Errores del job → mensaje y CTA reintentar. `/b/[slug]/library`: tabla/grid con filtros por estado, búsqueda por tema, acción "reusar tema" (→ /create con tema prellenado). Commit `feat(front): wizard de carruseles con seguimiento de job y biblioteca`.

### Task 5: Settings de marca
`/b/[slug]/settings` con tabs: **Perfil** (nombre, handle, ciudad, tz, color con input color, descripcion, sitio_web → PATCH); **Voz y prompts** (voz textarea, caption_extra, por_formato dinámico según formatos, hashtags chips → PUT prompts; botón "Probar" con tema de ejemplo → muestra guion JSON legible); **Estilos** (lista presets global/propio, editor de preset propio como formulario JSON-friendly: campos texto/fondo/overlay + editor crudo JSON con validación, guardar → PUT; botón "Preview" → job + refresco de imagen; borrar propio); **Fuentes** (dos secciones imagen/info: lista ordenable (dnd) → PUT orden, toggle activa, agregar con dialog por provider con campos según config, botón ▶ correr para rss/newsapi/ig_accounts; sección Fotos: grid de GET photos con upload multiple y borrar; sección Temas: lista con descartar); **Conexiones** (secrets list → inputs "configurada ✓ ····ABCD" con reemplazar/borrar; botones Probar telegram/instagram/llm con resultado inline); **Horarios** (slots editables como chips HH:MM, tz, posts/día → PATCH posting_slots... vía PUT /brands/{slug} PATCH campos correspondientes — usar los endpoints existentes: posting_slots se edita por PATCH /brands/{slug}? — NO existe: usar PATCH de accounts vía /brands/{slug} si el campo está permitido; si no está en la API, mostrar solo lectura con nota y registrar el gap en el reporte). Gating por rol (editor: todo lectura). Commit `feat(front): settings completos de marca`.

### Task 6: Admin + pulido
`/admin/users`: tabla usuarios (GET /users), invitar (dialog email+nombre+marcas/rol), editar membresías, activar/desactivar, cerrar sesiones; `/admin/system`: jobs recientes de todas mis marcas (agregado por marca), links a /docs y health. Navbar global: switcher de marca, avatar/email, logout (POST /auth/logout → /login), link Admin si is_admin. Estados vacíos con CTA en todas las vistas; loading skeletons; revisar responsive (calendario → lista). Commit `feat(front): admin de usuarios y pulido de navegación`.

### Task 7: Tests + CI
Vitest + Testing Library + MSW: tests de `lib/api.ts` (error shape), calendario (render de estados, drag → PATCH llamado, 409 → revert+toast), wizard (validación de pasos, polling hasta ok, error de job), settings prompts (PUT payload correcto), gating por rol (editor no ve botones de settings). `frontend/package.json` scripts `test`/`test:watch`. `.github/workflows/ci.yml`: job `frontend` (setup-node 22 + pnpm, install, lint, build, test) SOLO añadiendo el job (no tocar el job Python). Commit `test(front): vitest+msw de calendario, wizard y api client` y `ci: job de frontend`.

### Task 8: README + humo final
`frontend/README.md` (dev: `pnpm dev` con `API_URL`; build; estructura; convenciones). Humo: `pnpm build && pnpm test` verdes; arrancar `pnpm dev` contra la API demo y verificar `/login` responde 200 (curl). Commit `docs(front): README del frontend`.

## Auto-revisión
Spec §10: todas las rutas y features listadas quedan cubiertas (login/callback T1; brands+wizard nueva marca T2; dashboard T2; calendar T3; create T4; library T4; settings 7 tabs T5 — "Horarios" puede quedar lectura si la API no expone posting_slots: registrar gap; admin T6). §12: vitest+MSW+CI T7 (e2e Playwright diferido a F5 con la API en modo test — ruling del controlador). Sin placeholders: cada task nombra endpoints y comportamientos concretos.
