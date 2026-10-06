# Editor v2 · Plan 2: editor frontend

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-10-06-editor-escena-v2-design.md` (commit e87942f), §2 (editor) y §7 (pruebas).
**Índice y contrato entre planes:** `docs/superpowers/plans/2026-10-06-editor-v2-00-indice.md`. Depende del plan 1 (`2026-10-06-editor-v2-01-escena-backend.md`): la API ya acepta y devuelve escena v2, `estado=todas` y aspecto `1:1`.

**Goal:** sustituir la pantalla rota del editor de diseños (`app/b/[slug]/templates/[id]/`) por un editor tipo Figma sobre la escena v2. Debe hacer lo siguiente:

- Selección y lazo.
- Mover, redimensionar y rotar con guías.
- Zoom y paneo.
- Panel de capas con orden, ojo y candado.
- Panel de propiedades por tipo.
- Edición de texto en el lienzo, con color por tramo.
- Deshacer y rehacer.
- Atajos de teclado.
- Autoguardado del borrador, versiones, vista previa y activación.

**Architecture:**

- **Modelo puro (`lib/escena.ts`):** tipos, `aplicarOps` (immer) y `reformatear`.
- **Operaciones de edición (`lib/edicion.ts`):** funciones puras que devuelven `Op[]`.
- **Store (`stores/editor.ts`):** zustand. Cada acción es un paso de deshacer, guardado como parches de immer.
- **Componentes en `_components/`:**
  - Lienzo: Moveable para las manijas y Selecto para el lazo.
  - Editor de texto: un `textarea` superpuesto.
  - Panel de capas: dnd-kit.
  - Panel de propiedades.
  - `PanelLateral` con pestañas.
  - Barra superior.
- **Hooks:** `use-autoguardado` y `use-atajos`.
- **Pruebas:** vitest + Testing Library en jsdom para la lógica y los paneles. Playwright para lo que solo existe en un navegador real: manijas, transformaciones y el flujo de punta a punta contra un backend sembrado.

**Tech Stack:** Next 16.3.1, React 19.2.8, TypeScript 5, pnpm 11, react-moveable 0.56.0, react-selecto 1.26.3, zustand 5.0.15, immer 11.1.21, @dnd-kit (ya instalado), shadcn/ui (ya instalado), vitest, @testing-library/react, Playwright.

---

## Global Constraints

- **Dónde se trabaja:**
  - Rama `feat/editor-v2`, worktree `/Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2`.
  - Los comandos de frontend se corren desde `frontend/`; los de Python, desde la raíz del worktree.
- **Comandos de verificación:**
  - Pruebas unitarias: `pnpm test`.
  - E2E: `pnpm e2e`.
  - Tipos: `pnpm exec tsc --noEmit`.
  - Lint: `pnpm lint`.
- **Proceso:**
  - TDD estricto: prueba que falla → código mínimo → verde → commit. Un commit por task.
  - **Nada de push ni deploy a la VM.**
- Antes de cada commit tienen que pasar:
  - `pnpm test`
  - `pnpm exec tsc --noEmit`
  - `pnpm lint`
  - Las e2e de la task, cuando la task las tiene.
  - Si algo ajeno ya fallaba antes de empezar, se anota en el mensaje del commit y no se arregla aquí.
- **Nombres:** los del contrato del índice se usan exactos:
  - `Escena`, `Capa`, `CapaTexto`, `CapaImagen`, `Formato`, `Op`, `aplicarOps`.
  - `useEditor` con `cargar`, `aplicar`, `agregarCapa`, `seleccionar`, `deshacer`, `rehacer`, `escena`, `seleccion`, `sucio`.
  - `PanelLateral({ pestanas })`.
- **Nombres de campos:** los del esquema del plan 1, sin traducir:
  - `opacity`, `rot`, `anclaje`.
  - `estilo.fill`, `estilo.borderWidth`, `estilo.borderColor`, `estilo.objectPosition`.
  - `src`, `ajuste`, `mascara`, `hijos`, `spans{desde,hasta,color}`.
- **Qué no se toca:** `lib/layout.ts` v1, ni el backend Python. La única excepción es `frontend/e2e/sembrar.py`, que solo importa módulos existentes.
- **Lo que se lee:** no se leen `*.local.md` ni valores de `.env`.
- **Estilo:** UI y comentarios en español, con el tono del resto del frontend: frases cortas que dicen qué pasa.
- **Rutas de dev:** las páginas `app/dev/*` llaman `notFound()` cuando `NODE_ENV === "production"`.

## Review Focus

1. **Paridad de `aplicarOps` con el plan 4.** Lo cubre la prueba «casos compartidos» de `lib/__tests__/escena.test.ts` (Task 2), que recorre `lib/__fixtures__/ops-casos.json`, el mismo archivo que debe cargar `src/plantillas/ops.py`. Hay que revisar:
   - que las ops sean atómicas;
   - la cascada que borra grupos vacíos;
   - que `set` no deje tocar `id` ni `tipo`.
2. **Paridad de `reformatear` con Python.** Lo cubre la prueba «reformatear como el plan 1» (Task 2), con los números exactos del plan 1: +570/+285, −270/−135, −840/−420, la capa a sangre y la caja del grupo.
3. **Un paso de deshacer por acción y por gesto.** Lo cubren:
   - las pruebas «aplicar es un paso» y «la caja del grupo va en el mismo paso» (Task 5);
   - la e2e «arrastrar es un paso y deshacer regresa» (Task 7).
4. **Autoguardado.** Lo cubre `hooks/__tests__/use-autoguardado.test.tsx` (Task 11), que verifica:
   - que solo autoguarda en `borrador`;
   - el debounce de 2 s;
   - que una edición durante el guardado deja `sucio`;
   - que los guardados van en serie.
5. **Reset del transform del DOM tras un gesto.** Lo cubre la e2e «arrastrar es un paso y deshacer regresa» (Task 7): la caja en pantalla se mueve 100 px y no 200. Moveable escribe `style.transform` directo en el DOM y React no lo deshace.

## Decisiones de este plan que extienden el spec (revisar)

| # | Decisión | Por qué |
|---|---|---|
| D1 | El autoguardado usa `PATCH /templates/{id}` sin `mensaje`, así que cada autoguardado crea una fila de versión. El diálogo de versiones esconde por defecto las filas con `mensaje === null` | El backend no tiene un «borrador sin versión». Agregarlo es trabajo de backend fuera de este plan |
| D2 | El store tiene `editarEscena(receta)` y `cambiarFormato(f)` fuera de `Op`, para lienzo, fondo y tokens | `Op` solo habla de capas (contrato). Ambas son un paso de deshacer |
| D3 | `del` borra en cascada todo grupo que se queda sin hijos | El validador del plan 1 prohíbe `hijos` vacío. **El plan 4 (`ops.py`) debe replicarlo**, y está en el fixture |
| D4 | `aplicarOps` no recalcula la caja de los grupos. El store sí lo hace, en el mismo paso (`conCajasDeGrupo`) | Mantiene `aplicarOps` mínima y portable a Python |
| D5 | Grupos: se mueven, pero no se redimensionan ni se rotan. Redimensionar y rotar es solo para una capa | Escalar hijos rotados abre casos que el spec no define |
| D6 | El orden en el panel de capas se cambia solo entre hermanos. `z` es un orden global de hojas y la `z` de un grupo se deriva de sus hijos | El render del plan 1 pinta por `z` de hojas. Un grupo no pinta nada |
| D7 | El texto se edita en un `textarea` superpuesto, no en `contentEditable`. Los colores por tramo se aplican al seleccionar y se ven al salir | Con `contentEditable` hay que mapear el DOM a offsets, y eso es frágil. El `textarea` da offsets exactos |
| D8 | El store agrega campos y acciones al contrato: `pasado`, `futuro`, `revision`, `zoom`, `editandoTexto`, `portapapeles`, y `copiar`, `pegar`, `duplicar`, `borrar`, `mover`, etc. | Son aditivos. Los planes 3 y 4 usan solo los del contrato |
| D9 | En el panel de propiedades, los selects son `<select>` nativo con estilo, no Radix Select | Se prueban en jsdom sin trucos y son más rápidos de operar |
| D10 | El lienzo recorta lo que queda fuera (`overflow: hidden`) | WYSIWYG con el PNG. Una capa fuera del lienzo se toma desde el panel de capas |
| D11 | Al editar texto, lo que se escribe solo hereda color si queda estrictamente dentro de un tramo. En los bordes queda sin color | Regla simple, determinística y probada (Task 3) |
| D12 | Autoguardado solo en `borrador`. Un diseño activo se guarda con «Guardar versión». `beforeunload` avisa siempre que haya cambios sin guardar | El PATCH de un activo cambia lo que se publica; ese cambio debe ser a propósito |
| D13 | La vista previa manda el `aspecto` del formato del lienzo, no el de la columna del diseño | Se previsualiza lo que se ve en pantalla, incluso tras cambiar de formato sin guardar |
| D14 | «Restaurar» está deshabilitado mientras se guarda | Un PATCH en vuelo pisaría la versión restaurada |
| D15 | Los atajos aceptan ⌘ o Ctrl y se ignoran en campos de texto, diálogos y edición de texto en el lienzo | Mismo comportamiento en Mac y en lo demás, sin robar teclas a los inputs |
| D16 | Sombra = preset de `drop-shadow` sobre `estilo.filter`, solo en imagen, video, svg y forma. Vincular un campo limpia `spans`; desvincular apaga `resaltar`. «Dato» filtra los campos por tipo | `EstiloTexto` no tiene `filter`; los tramos y el resaltado dependen de si el texto es fijo o viene del dato |

---

## Task 1: infraestructura de pruebas y smoke test de Moveable/Selecto en React 19

**Files:**
- Modify: `frontend/package.json` (scripts y dependencias)
- Create: `frontend/vitest.config.ts`
- Create: `frontend/vitest.setup.ts`
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/sesion.ts`
- Create: `frontend/e2e/moveable.spec.ts`
- Create: `frontend/app/dev/moveable/page.tsx`
- Create: `frontend/app/dev/moveable/banco.tsx`
- Modify: `frontend/.gitignore`

**Interfaces:**
- Scripts: `pnpm test` (vitest run), `pnpm test:watch`, `pnpm e2e` (playwright).
- `cookieFalsa(context)` en `e2e/sesion.ts`: pone una cookie `instagod_session` para que `proxy.ts` deje pasar a las páginas de dev.

Esta task es la **compuerta** del plan:

- Si la e2e de Moveable/Selecto no pasa en React 19.2, se detiene y se avisa.
- En ese caso, el Task 7 se reescribe con el plan B: manijas propias a partir de `lienzo.tsx` v1.

- [ ] **Step 1: instalar dependencias**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm add react-moveable@0.56.0 react-selecto@1.26.3 zustand@5.0.15 immer@11.1.21
pnpm add -D vitest @vitejs/plugin-react jsdom @testing-library/react @testing-library/dom @testing-library/user-event @playwright/test
pnpm exec playwright install chromium
npm pkg set scripts.test="vitest run --passWithNoTests" scripts.test:watch="vitest" scripts.e2e="playwright test"
```

Esperado: `pnpm add` sin errores de peer que bloqueen. Puede advertir que `react-moveable` declara peer `react >=16.8`; eso se acepta. `playwright install` descarga Chromium.

- [ ] **Step 2: configuración de vitest**

`frontend/vitest.config.ts`:

```ts
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL(".", import.meta.url)) } },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["**/*.test.ts", "**/*.test.tsx"],
    exclude: ["node_modules/**", "e2e/**", ".next/**"],
  },
});
```

`frontend/vitest.setup.ts`:

```ts
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => cleanup());

// jsdom no trae estas APIs y Radix/dnd-kit las llaman.
class ResizeObserverFalso {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverFalso as unknown as typeof ResizeObserver;
Element.prototype.scrollIntoView ??= function () {};
Element.prototype.hasPointerCapture ??= () => false;
Element.prototype.setPointerCapture ??= () => {};
Element.prototype.releasePointerCapture ??= () => {};
```

- [ ] **Step 3: configuración de Playwright y cookie falsa**

`frontend/playwright.config.ts`:

```ts
import { defineConfig, devices } from "@playwright/test";

// El frontend de prueba corre en 3100 para no chocar con un `pnpm dev` en 3000.
// API_URL apunta al backend de e2e (Task 15). Hasta entonces, las páginas
// de dev no llaman a la API.
export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  timeout: 60_000,
  use: { baseURL: "http://127.0.0.1:3100", trace: "retain-on-failure" },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
  ],
  webServer: [
    {
      command: "pnpm exec next dev --port 3100 --hostname 127.0.0.1",
      url: "http://127.0.0.1:3100/login",
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      env: { API_URL: "http://127.0.0.1:8102" },
    },
  ],
});
```

`frontend/e2e/sesion.ts`:

```ts
import type { BrowserContext } from "@playwright/test";

// proxy.ts solo revisa que exista la cookie; las páginas /dev no llaman a la API.
export async function cookieFalsa(context: BrowserContext, valor = "e2e") {
  await context.addCookies([{ name: "instagod_session", value: valor, url: "http://127.0.0.1:3100" }]);
}
```

Agregar al final de `frontend/.gitignore`:

```
/test-results/
/playwright-report/
/e2e/.datos/
```

- [ ] **Step 4: escribir la e2e que falla**

`frontend/e2e/moveable.spec.ts`:

```ts
import { expect, test, type Page } from "@playwright/test";
import { cookieFalsa } from "./sesion";

type Estado = { sel: string[]; cajas: { id: string; x: number; y: number }[]; ultimo: number[] | null };

async function estado(page: Page): Promise<Estado> {
  return JSON.parse(await page.getByTestId("estado").innerText());
}

test.beforeEach(async ({ context }) => {
  await cookieFalsa(context);
});

test("moveable arrastra dentro de un escenario con scale(0.5)", async ({ page }) => {
  const errores: string[] = [];
  page.on("pageerror", (e) => errores.push(e.message));
  await page.goto("/dev/moveable");

  const b = page.locator('[data-id="b"]');
  await b.click();
  await expect.poll(async () => (await estado(page)).sel).toEqual(["b"]);

  const caja = (await b.boundingBox())!;
  const cx = caja.x + caja.width / 2;
  const cy = caja.y + caja.height / 2;
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.mouse.move(cx + 50, cy, { steps: 5 });
  await page.mouse.move(cx + 100, cy, { steps: 5 });
  await page.mouse.up();

  // 100 px de pantalla a escala 0.5 son 200 px del escenario: b pasa de x=400 a ~600.
  await expect.poll(async () => (await estado(page)).cajas.find((c) => c.id === "b")!.x).toBeGreaterThan(590);
  const x = (await estado(page)).cajas.find((c) => c.id === "b")!.x;
  expect(x).toBeLessThan(610);
  expect(errores).toEqual([]);
});

test("selecto selecciona con lazo", async ({ page }) => {
  const errores: string[] = [];
  page.on("pageerror", (e) => errores.push(e.message));
  await page.goto("/dev/moveable");

  const marco = (await page.locator("#marco").boundingBox())!;
  // a está en (20,20)-(120,120) y c en (20,200)-(120,300) de pantalla; b empieza en x=200.
  await page.mouse.move(marco.x + 5, marco.y + 5);
  await page.mouse.down();
  await page.mouse.move(marco.x + 80, marco.y + 150, { steps: 5 });
  await page.mouse.move(marco.x + 150, marco.y + 310, { steps: 5 });
  await page.mouse.up();

  await expect.poll(async () => [...(await estado(page)).sel].sort()).toEqual(["a", "c"]);
  expect(errores).toEqual([]);
});
```

- [ ] **Step 5: correrla y ver que falla**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm e2e e2e/moveable.spec.ts
```

Esperado: FAIL con un 404 en `/dev/moveable` (`getByTestId('estado')` no aparece).

- [ ] **Step 6: banco de prueba**

`frontend/app/dev/moveable/page.tsx`:

```tsx
import { notFound } from "next/navigation";
import { Banco } from "./banco";

export default function Page() {
  if (process.env.NODE_ENV === "production") notFound();
  return <Banco />;
}
```

`frontend/app/dev/moveable/banco.tsx`:

```tsx
"use client";

import { useRef, useState } from "react";
import Moveable from "react-moveable";
import Selecto from "react-selecto";

const INICIAL = [
  { id: "a", x: 40, y: 40 },
  { id: "b", x: 400, y: 40 },
  { id: "c", x: 40, y: 400 },
];
const ESCALA = 0.5;

// Banco mínimo: el mismo acomodo que el editor (escenario escalado,
// Moveable como hermano y Selecto sobre el marco). Solo para el smoke test.
export function Banco() {
  const [cajas, setCajas] = useState(INICIAL);
  const [sel, setSel] = useState<string[]>([]);
  const [ultimo, setUltimo] = useState<number[] | null>(null);
  const [marco, setMarco] = useState<HTMLDivElement | null>(null);
  const moveableRef = useRef<Moveable>(null);
  const traslado = useRef<number[] | null>(null);

  return (
    <div style={{ padding: 40 }}>
      <div id="marco" ref={setMarco} style={{ position: "relative", width: 600, height: 600, background: "#eee" }}>
        <div
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            width: 1200,
            height: 1200,
            transform: `scale(${ESCALA})`,
            transformOrigin: "0 0",
          }}
        >
          {cajas.map((c) => (
            <div
              key={c.id}
              data-id={c.id}
              className="capa"
              style={{
                position: "absolute",
                left: c.x,
                top: c.y,
                width: 200,
                height: 200,
                background: sel.includes(c.id) ? "#f90" : "#09f",
              }}
            />
          ))}
        </div>
        <Moveable
          ref={moveableRef}
          target={sel.map((id) => `[data-id="${id}"]`)}
          draggable
          onDragStart={() => {
            traslado.current = null;
          }}
          onDrag={(e) => {
            e.target.style.transform = e.transform;
            traslado.current = e.beforeTranslate;
          }}
          onDragEnd={(e) => {
            const t = traslado.current;
            (e.target as HTMLElement).style.transform = "";
            if (!t) return;
            const id = e.target.getAttribute("data-id");
            setUltimo(t);
            setCajas((cs) => cs.map((c) => (c.id === id ? { ...c, x: Math.round(c.x + t[0]), y: Math.round(c.y + t[1]) } : c)));
          }}
        />
      </div>
      {marco && (
        <Selecto
          dragContainer={marco}
          selectableTargets={[".capa"]}
          hitRate={0}
          selectByClick
          selectFromInside={false}
          toggleContinueSelect={["shift"]}
          onDragStart={(e) => {
            const t = e.inputEvent.target as Element;
            if (moveableRef.current?.isMoveableElement(t) || sel.some((id) => t.closest(`[data-id="${id}"]`))) e.stop();
          }}
          onSelectEnd={(e) => {
            setSel(e.selected.map((el) => el.getAttribute("data-id")!));
            if (e.isDragStart) {
              e.inputEvent.preventDefault();
              moveableRef.current?.waitToChangeTarget().then(() => moveableRef.current?.dragStart(e.inputEvent));
            }
          }}
        />
      )}
      <pre data-testid="estado">{JSON.stringify({ sel, cajas, ultimo })}</pre>
    </div>
  );
}
```

- [ ] **Step 7: correr la e2e y la compuerta**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm e2e e2e/moveable.spec.ts
pnpm test && pnpm exec tsc --noEmit && pnpm lint
```

Esperado:

- `2 passed`.
- `pnpm test` dice «No test files found, exiting with code 0».
- tsc y lint limpios.

**Compuerta:** si alguna de las dos e2e falla (por excepción de React 19, por traslado incorrecto o porque el lazo no selecciona):

- No se sigue con el Task 7 tal como está escrito.
- Se reporta la salida y se propone el plan B.
- Los Tasks 2 a 6 no dependen de Moveable y pueden seguir.

- [ ] **Step 8: commit**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2
git add frontend/package.json frontend/pnpm-lock.yaml frontend/vitest.config.ts frontend/vitest.setup.ts frontend/playwright.config.ts frontend/e2e frontend/app/dev/moveable frontend/.gitignore
git commit -F - <<'EOF'
editor v2: infra de pruebas (vitest, playwright) y smoke test de Moveable/Selecto

Moveable 0.56.0 y Selecto 1.26.3 arrastran y seleccionan con lazo en React 19.2
dentro de un escenario con scale(0.5). Banco en /dev/moveable (solo dev).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

## Task 2: modelo de escena (`lib/escena.ts`), `aplicarOps` y `reformatear`

**Files:**
- Create: `frontend/lib/escena.ts`
- Create: `frontend/lib/__fixtures__/ops-casos.json`
- Create: `frontend/lib/__tests__/escena.test.ts`

**Interfaces:**

Contrato:

```ts
export type Formato = "4x5" | "1x1" | "9x16";
export type Op = { op: "set"; capa: string; ruta: string; valor: unknown }
               | { op: "add"; capa: Capa; indice?: number }
               | { op: "del"; capa: string };
export function aplicarOps(escena: Escena, ops: Op[]): Escena; // atómica: si una op falla, lanza OpInvalida y no devuelve nada
```

Aditivas:

- Tipos y errores: `OpInvalida`, `Caja`, `Tokens`.
- Constantes: `FORMATOS`, `ASPECTO_DE_FORMATO`, `MAX_CAPAS`, `MAX_TEXTO`, `MAX_SPANS`, `ID_RE`.
- Ops y formato:
  - `aplicarEnBorrador(d, op)`
  - `reformatear(escena, formato)`
- Grupos y cajas:
  - `cajasDeGrupo(escena)`
  - `cajaDe(escena, id)`
- Árbol de capas:
  - `ordenadas(escena)`
  - `padreDe(escena, id)`
  - `raizDe(escena, id)`
  - `descendientes(escena, id)`
  - `ocultasEfectivas(escena)`
- Utilidades:
  - `resolverColor(valor, tokens, colorMarca)`
  - `idLibre(escena, base)`
  - `capaNueva(tipo, escena, opciones)`
  - `urlDeAsset(slug, src)`
  - `normalizarAngulo(a)`

**Fixture compartido:** el plan 4 (`src/plantillas/ops.py`) debe cargar `frontend/lib/__fixtures__/ops-casos.json` y pasar los mismos casos. El formato es:

- `base`: la escena de partida.
- `casos`: una lista de `{nombre, ops, error?, ids?, cambiadas?}`.

Cómo se verifica un caso:

- Con `error: true`, `aplicar` lanza y la escena base queda igual.
- Sin error:
  - el orden de ids del resultado es `ids`;
  - cada capa listada en `cambiadas` es igual a la capa completa que ahí aparece;
  - el resto de las capas es igual a su versión en `base`.

- [ ] **Step 1: escribir el fixture**

`frontend/lib/__fixtures__/ops-casos.json`:

```json
{
  "base": {
    "v": 2,
    "lienzo": { "w": 1080, "h": 1350, "formato": "4x5", "fondo": { "tipo": "color", "valor": "#ffffff" } },
    "tokens": { "colores": { "tinta": "#111111" } },
    "capas": [
      { "id": "titulo", "nombre": "Título", "tipo": "text", "x": 80, "y": 196, "w": 920, "h": 300, "rot": 0, "opacity": 1, "z": 3, "bloqueada": false, "oculta": false, "anclaje": "top", "texto": "Hola mundo", "estilo": { "fontFamily": "Inter", "fontWeight": 800, "fontSize": 96, "lineHeight": 1.05, "letterSpacing": "-0.02em", "color": "token:tinta", "textAlign": "left", "textWrap": "balance", "verticalAlign": "top", "textTransform": "none", "spans": [] } },
      { "id": "caja", "nombre": "Caja", "tipo": "shape", "x": 0, "y": 1200, "w": 1080, "h": 150, "rot": 0, "opacity": 1, "z": 1, "bloqueada": false, "oculta": false, "anclaje": "bottom", "forma": "rect", "estilo": { "fill": "token:marca", "radius": 0, "borderWidth": 0 } },
      { "id": "logo", "nombre": "Logo", "tipo": "svg", "x": 900, "y": 1230, "w": 120, "h": 90, "rot": 0, "opacity": 1, "z": 2, "bloqueada": false, "oculta": false, "anclaje": "bottom", "src": "assets/logo.svg", "ajuste": "contain", "estilo": {} },
      { "id": "marca", "nombre": "Marca", "tipo": "group", "x": 0, "y": 1200, "w": 1080, "h": 150, "rot": 0, "opacity": 1, "z": 0, "bloqueada": false, "oculta": false, "anclaje": "bottom", "hijos": ["caja", "logo"], "estilo": {} }
    ]
  },
  "casos": [
    {
      "nombre": "set estilo.fill",
      "ops": [{ "op": "set", "capa": "caja", "ruta": "estilo.fill", "valor": "#00ff00" }],
      "ids": ["titulo", "caja", "logo", "marca"],
      "cambiadas": {
        "caja": { "id": "caja", "nombre": "Caja", "tipo": "shape", "x": 0, "y": 1200, "w": 1080, "h": 150, "rot": 0, "opacity": 1, "z": 1, "bloqueada": false, "oculta": false, "anclaje": "bottom", "forma": "rect", "estilo": { "fill": "#00ff00", "radius": 0, "borderWidth": 0 } }
      }
    },
    {
      "nombre": "set crea intermedios",
      "ops": [{ "op": "set", "capa": "logo", "ruta": "fuente_asset.autor", "valor": "Ana" }],
      "ids": ["titulo", "caja", "logo", "marca"],
      "cambiadas": {
        "logo": { "id": "logo", "nombre": "Logo", "tipo": "svg", "x": 900, "y": 1230, "w": 120, "h": 90, "rot": 0, "opacity": 1, "z": 2, "bloqueada": false, "oculta": false, "anclaje": "bottom", "src": "assets/logo.svg", "ajuste": "contain", "estilo": {}, "fuente_asset": { "autor": "Ana" } }
      }
    },
    {
      "nombre": "set de un objeto completo copia el valor",
      "ops": [{ "op": "set", "capa": "titulo", "ruta": "estilo.spans", "valor": [{ "desde": 0, "hasta": 4, "color": "token:marca" }] }],
      "ids": ["titulo", "caja", "logo", "marca"],
      "cambiadas": {
        "titulo": { "id": "titulo", "nombre": "Título", "tipo": "text", "x": 80, "y": 196, "w": 920, "h": 300, "rot": 0, "opacity": 1, "z": 3, "bloqueada": false, "oculta": false, "anclaje": "top", "texto": "Hola mundo", "estilo": { "fontFamily": "Inter", "fontWeight": 800, "fontSize": 96, "lineHeight": 1.05, "letterSpacing": "-0.02em", "color": "token:tinta", "textAlign": "left", "textWrap": "balance", "verticalAlign": "top", "textTransform": "none", "spans": [{ "desde": 0, "hasta": 4, "color": "token:marca" }] } }
      }
    },
    { "nombre": "set id falla", "ops": [{ "op": "set", "capa": "titulo", "ruta": "id", "valor": "otro" }], "error": true },
    { "nombre": "set tipo falla", "ops": [{ "op": "set", "capa": "titulo", "ruta": "tipo", "valor": "shape" }], "error": true },
    { "nombre": "set capa inexistente falla", "ops": [{ "op": "set", "capa": "nadie", "ruta": "x", "valor": 1 }], "error": true },
    { "nombre": "set ruta vacía falla", "ops": [{ "op": "set", "capa": "titulo", "ruta": "estilo..color", "valor": "#000000" }], "error": true },
    { "nombre": "set a través de un primitivo falla", "ops": [{ "op": "set", "capa": "titulo", "ruta": "texto.largo", "valor": 3 }], "error": true },
    { "nombre": "set con __proto__ falla", "ops": [{ "op": "set", "capa": "titulo", "ruta": "__proto__.x", "valor": 1 }], "error": true },
    {
      "nombre": "add al final",
      "ops": [{ "op": "add", "capa": { "id": "nueva", "nombre": "Nueva", "tipo": "shape", "x": 10, "y": 10, "w": 100, "h": 100, "rot": 0, "opacity": 1, "z": 4, "bloqueada": false, "oculta": false, "anclaje": "top", "forma": "ellipse", "estilo": { "fill": "#ff0000" } } }],
      "ids": ["titulo", "caja", "logo", "marca", "nueva"],
      "cambiadas": {
        "nueva": { "id": "nueva", "nombre": "Nueva", "tipo": "shape", "x": 10, "y": 10, "w": 100, "h": 100, "rot": 0, "opacity": 1, "z": 4, "bloqueada": false, "oculta": false, "anclaje": "top", "forma": "ellipse", "estilo": { "fill": "#ff0000" } }
      }
    },
    {
      "nombre": "add con indice 0",
      "ops": [{ "op": "add", "indice": 0, "capa": { "id": "nueva", "nombre": "Nueva", "tipo": "shape", "x": 10, "y": 10, "w": 100, "h": 100, "rot": 0, "opacity": 1, "z": 4, "bloqueada": false, "oculta": false, "anclaje": "top", "forma": "ellipse", "estilo": { "fill": "#ff0000" } } }],
      "ids": ["nueva", "titulo", "caja", "logo", "marca"],
      "cambiadas": {
        "nueva": { "id": "nueva", "nombre": "Nueva", "tipo": "shape", "x": 10, "y": 10, "w": 100, "h": 100, "rot": 0, "opacity": 1, "z": 4, "bloqueada": false, "oculta": false, "anclaje": "top", "forma": "ellipse", "estilo": { "fill": "#ff0000" } }
      }
    },
    {
      "nombre": "add con indice 99 se acota al final",
      "ops": [{ "op": "add", "indice": 99, "capa": { "id": "nueva", "nombre": "Nueva", "tipo": "shape", "x": 10, "y": 10, "w": 100, "h": 100, "rot": 0, "opacity": 1, "z": 4, "bloqueada": false, "oculta": false, "anclaje": "top", "forma": "ellipse", "estilo": { "fill": "#ff0000" } } }],
      "ids": ["titulo", "caja", "logo", "marca", "nueva"],
      "cambiadas": {
        "nueva": { "id": "nueva", "nombre": "Nueva", "tipo": "shape", "x": 10, "y": 10, "w": 100, "h": 100, "rot": 0, "opacity": 1, "z": 4, "bloqueada": false, "oculta": false, "anclaje": "top", "forma": "ellipse", "estilo": { "fill": "#ff0000" } }
      }
    },
    {
      "nombre": "add con id duplicado falla",
      "ops": [{ "op": "add", "capa": { "id": "caja", "nombre": "Otra", "tipo": "shape", "x": 10, "y": 10, "w": 100, "h": 100, "rot": 0, "opacity": 1, "z": 4, "bloqueada": false, "oculta": false, "anclaje": "top", "forma": "rect", "estilo": { "fill": "#ff0000" } } }],
      "error": true
    },
    { "nombre": "del simple", "ops": [{ "op": "del", "capa": "titulo" }], "ids": ["caja", "logo", "marca"] },
    { "nombre": "del de un grupo borra sus descendientes", "ops": [{ "op": "del", "capa": "marca" }], "ids": ["titulo"] },
    {
      "nombre": "del de un hijo lo quita de hijos y no recalcula la caja",
      "ops": [{ "op": "del", "capa": "logo" }],
      "ids": ["titulo", "caja", "marca"],
      "cambiadas": {
        "marca": { "id": "marca", "nombre": "Marca", "tipo": "group", "x": 0, "y": 1200, "w": 1080, "h": 150, "rot": 0, "opacity": 1, "z": 0, "bloqueada": false, "oculta": false, "anclaje": "bottom", "hijos": ["caja"], "estilo": {} }
      }
    },
    { "nombre": "del de todos los hijos borra el grupo vacío", "ops": [{ "op": "del", "capa": "caja" }, { "op": "del", "capa": "logo" }], "ids": ["titulo"] },
    { "nombre": "del inexistente falla", "ops": [{ "op": "del", "capa": "nadie" }], "error": true },
    {
      "nombre": "las ops son atómicas",
      "ops": [{ "op": "set", "capa": "titulo", "ruta": "texto", "valor": "Cambiado" }, { "op": "del", "capa": "nadie" }],
      "error": true
    }
  ]
}
```

- [ ] **Step 2: escribir las pruebas que fallan**

`frontend/lib/__tests__/escena.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import datos from "../__fixtures__/ops-casos.json";
import {
  OpInvalida,
  aplicarOps,
  cajaDe,
  capaNueva,
  descendientes,
  idLibre,
  normalizarAngulo,
  ocultasEfectivas,
  ordenadas,
  padreDe,
  raizDe,
  reformatear,
  resolverColor,
  urlDeAsset,
  type Capa,
  type Escena,
  type Op,
} from "../escena";

type Caso = { nombre: string; ops: Op[]; error?: boolean; ids?: string[]; cambiadas?: Record<string, Capa> };
const fixture = datos as unknown as { base: Escena; casos: Caso[] };

describe("casos compartidos con ops.py", () => {
  for (const caso of fixture.casos) {
    it(caso.nombre, () => {
      const base = structuredClone(fixture.base);
      const copia = structuredClone(base);
      if (caso.error) {
        expect(() => aplicarOps(base, caso.ops)).toThrow(OpInvalida);
        expect(base).toEqual(copia);
        return;
      }
      const r = aplicarOps(base, caso.ops);
      expect(r.capas.map((c) => c.id)).toEqual(caso.ids);
      for (const c of r.capas) {
        const esperada = caso.cambiadas?.[c.id] ?? copia.capas.find((b) => b.id === c.id);
        expect(c).toEqual(esperada);
      }
      expect(base).toEqual(copia);
    });
  }
});

function capa(id: string, y: number, anclaje: "top" | "center" | "bottom", extra: Partial<Capa> = {}): Capa {
  return {
    id, nombre: id, tipo: "shape", x: 0, y, w: 200, h: 100, rot: 0, opacity: 1, z: 1,
    bloqueada: false, oculta: false, anclaje, forma: "rect", estilo: { fill: "#000000" },
    ...extra,
  } as Capa;
}

function escenaReformato(): Escena {
  return {
    v: 2,
    lienzo: { w: 1080, h: 1350, formato: "4x5", fondo: { tipo: "color", valor: "#ffffff" } },
    tokens: { colores: {} },
    capas: [
      capa("c_fondo", 0, "top", { x: 0, w: 1080, h: 1350 }),
      capa("c_titular", 196, "top"),
      capa("c_foto", 600, "bottom"),
      capa("c_clip", 0, "center", { x: 100, w: 500, h: 300 }),
      capa("c_caja", 1200, "bottom", { w: 1080, h: 150 }),
      capa("c_logo", 1230, "bottom", { x: 900, w: 120, h: 90 }),
      { id: "g_marca", nombre: "Marca", tipo: "group", x: 0, y: 1200, w: 1080, h: 150, rot: 0, opacity: 1, z: 0,
        bloqueada: false, oculta: false, anclaje: "bottom", hijos: ["c_logo", "c_caja"], estilo: {} },
    ],
  };
}

const y = (e: Escena, id: string) => e.capas.find((c) => c.id === id)!.y;

describe("reformatear como el plan 1", () => {
  it("4x5 → 9x16: bottom +570, center +285, top igual", () => {
    const r = reformatear(escenaReformato(), "9x16");
    expect(r.lienzo).toMatchObject({ w: 1080, h: 1920, formato: "9x16" });
    expect(y(r, "c_titular")).toBe(196);
    expect(y(r, "c_foto")).toBe(1170);
    expect(y(r, "c_clip")).toBe(285);
    expect(y(r, "c_caja")).toBe(1770);
    expect(y(r, "c_logo")).toBe(1800);
  });

  it("la capa a sangre se estira y la caja del grupo se recalcula", () => {
    const r = reformatear(escenaReformato(), "9x16");
    expect(cajaDe(r, "c_fondo")).toEqual({ x: 0, y: 0, w: 1080, h: 1920 });
    const g = r.capas.find((c) => c.id === "g_marca")!;
    expect({ x: g.x, y: g.y, w: g.w, h: g.h }).toEqual({ x: 0, y: 1770, w: 1080, h: 150 });
  });

  it("4x5 → 1x1: −270 y −135", () => {
    const r = reformatear(escenaReformato(), "1x1");
    expect(y(r, "c_foto")).toBe(330);
    expect(y(r, "c_clip")).toBe(-135);
    expect(y(r, "c_caja")).toBe(930);
  });

  it("9x16 → 1x1: −840 y −420", () => {
    const r = reformatear(reformatear(escenaReformato(), "9x16"), "1x1");
    expect(y(r, "c_foto")).toBe(330);
    expect(y(r, "c_clip")).toBe(-135);
    expect(y(r, "c_caja")).toBe(930);
  });

  it("ida y vuelta restaura x/y y no muta la entrada", () => {
    const e = escenaReformato();
    const copia = structuredClone(e);
    const r = reformatear(reformatear(e, "9x16"), "4x5");
    expect(r).toEqual(copia);
    expect(e).toEqual(copia);
  });
});

describe("utilidades", () => {
  const e = fixture.base;

  it("árbol: padre, raíz, descendientes, ocultas", () => {
    expect(padreDe(e, "logo")).toBe("marca");
    expect(padreDe(e, "titulo")).toBeNull();
    expect(raizDe(e, "caja")).toBe("marca");
    expect(descendientes(e, "marca").sort()).toEqual(["caja", "logo"]);
    const oculto = aplicarOps(e, [{ op: "set", capa: "marca", ruta: "oculta", valor: true }]);
    expect([...ocultasEfectivas(oculto)].sort()).toEqual(["caja", "logo", "marca"]);
  });

  it("ordenadas va por z ascendente", () => {
    expect(ordenadas(e).map((c) => c.id)).toEqual(["marca", "caja", "logo", "titulo"]);
  });

  it("resolverColor", () => {
    expect(resolverColor("token:marca", e.tokens, "#ff5500")).toBe("#ff5500");
    expect(resolverColor("token:tinta", e.tokens, "#ff5500")).toBe("#111111");
    expect(resolverColor("token:nada", e.tokens, "#ff5500")).toBe("transparent");
    expect(resolverColor("#abcdef", e.tokens, "#ff5500")).toBe("#abcdef");
  });

  it("idLibre limpia acentos y numera", () => {
    expect(idLibre(e, "Título Grande")).toBe("titulo_grande");
    expect(idLibre(e, "titulo")).toBe("titulo_2");
    expect(idLibre(e, "9 vidas")).toBe("c_9_vidas");
    expect(idLibre(e, "x".repeat(40))).toHaveLength(26);
  });

  it("capaNueva centra y sube z", () => {
    const t = capaNueva("text", e, { fuente: "Inter" });
    expect(t).toMatchObject({ tipo: "text", x: 140, y: 595, w: 800, h: 160, z: 4, estilo: { fontFamily: "Inter" } });
    const f = capaNueva("shape", e, { fuente: "Inter" });
    expect(f).toMatchObject({ tipo: "shape", w: 400, h: 400, estilo: { fill: "token:marca" } });
    expect(() => capaNueva("image", e, { fuente: "Inter" })).toThrow();
  });

  it("urlDeAsset y normalizarAngulo", () => {
    expect(urlDeAsset("gdlscene", "assets/foto 1.png")).toBe("/api/brands/gdlscene/files/assets/foto%201.png");
    expect(normalizarAngulo(190)).toBe(-170);
    expect(normalizarAngulo(-190)).toBe(170);
    expect(normalizarAngulo(180)).toBe(180);
  });
});
```

- [ ] **Step 3: correrlas y ver que fallan**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test lib/__tests__/escena.test.ts
```

Esperado: FAIL con `Failed to resolve import "../escena"`.

- [ ] **Step 4: implementar `lib/escena.ts`**

`frontend/lib/escena.ts`:

```ts
import { produce, type Draft } from "immer";

// Escena v2: el mismo esquema que valida src/plantillas/escena.py (plan 1).
// Los nombres de campo NO se traducen: el backend los lee tal cual.

export type Formato = "4x5" | "1x1" | "9x16";
export const FORMATOS: Record<Formato, { w: number; h: number }> = {
  "4x5": { w: 1080, h: 1350 },
  "1x1": { w: 1080, h: 1080 },
  "9x16": { w: 1080, h: 1920 },
};
export const ASPECTO_DE_FORMATO: Record<Formato, "4:5" | "1:1" | "9:16"> = {
  "4x5": "4:5",
  "1x1": "1:1",
  "9x16": "9:16",
};
export const MAX_CAPAS = 80;
export const MAX_TEXTO = 1000;
export const MAX_SPANS = 50;
export const ID_RE = /^[a-z][a-z0-9_-]{0,31}$/;

export type Anclaje = "top" | "center" | "bottom";
export type Fondo = { tipo: "color" | "gradiente" | "imagen"; valor: string };
export type Tokens = { colores: Record<string, string>; fuente?: string };
export type Guias = { cols: number; filas: number; iman: boolean };
export type Span = { desde: number; hasta: number; color: string };

type CapaBase = {
  id: string;
  nombre: string;
  x: number;
  y: number;
  w: number;
  h: number;
  rot: number;
  opacity: number;
  z: number;
  bloqueada: boolean;
  oculta: boolean;
  anclaje: Anclaje;
};

export type EstiloTexto = {
  fontFamily: string;
  fontWeight: number;
  fontSize: number;
  lineHeight: number;
  letterSpacing?: string;
  color: string;
  textAlign: "left" | "center" | "right" | "justify";
  textWrap?: "wrap" | "balance" | "pretty" | "nowrap";
  verticalAlign?: "top" | "center" | "bottom";
  textTransform?: "none" | "uppercase";
  spans?: Span[];
};
export type CapaTexto = CapaBase & {
  tipo: "text";
  texto: string;
  campo?: string | null;
  auto?: boolean;
  resaltar?: boolean;
  estilo: EstiloTexto;
};

export type FuenteAsset = {
  proveedor?: string;
  autor?: string | null;
  licencia?: string | null;
  url?: string | null;
  ig_handle?: string | null;
};
type EstiloMedio = { objectPosition?: string; filter?: string; mixBlendMode?: string };
export type CapaImagen = CapaBase & {
  tipo: "image";
  src: string | null;
  campo?: string | null;
  recorte?: { x: number; y: number; w: number; h: number } | null;
  ajuste: "cover" | "contain";
  mascara: string; // "none" | "circle" | "rounded:N"
  estilo: EstiloMedio;
  fuente_asset?: FuenteAsset | null;
};
export type CapaVideo = Omit<CapaImagen, "tipo"> & { tipo: "video"; poster?: string | null };
export type CapaForma = CapaBase & {
  tipo: "shape";
  forma: "rect" | "ellipse";
  estilo: {
    fill: string;
    radius?: number;
    borderWidth?: number;
    borderColor?: string;
    filter?: string;
    mixBlendMode?: string;
  };
};
export type CapaSvg = CapaBase & {
  tipo: "svg";
  src: string;
  ajuste: "cover" | "contain";
  estilo: { filter?: string; mixBlendMode?: string };
  fuente_asset?: FuenteAsset | null;
};
export type CapaGrupo = CapaBase & { tipo: "group"; hijos: string[]; estilo: Record<string, never> };

export type Capa = CapaTexto | CapaImagen | CapaVideo | CapaForma | CapaSvg | CapaGrupo;
export type TipoCapa = Capa["tipo"];

export type Escena = {
  v: 2;
  lienzo: { w: number; h: number; formato: Formato; fondo: Fondo };
  tokens: Tokens;
  capas: Capa[];
  guias?: Guias;
};

export type Op =
  | { op: "set"; capa: string; ruta: string; valor: unknown }
  | { op: "add"; capa: Capa; indice?: number }
  | { op: "del"; capa: string };

export class OpInvalida extends Error {}

export type Caja = { x: number; y: number; w: number; h: number };

const INTOCABLES = new Set(["id", "tipo"]);
const PELIGROSAS = new Set(["__proto__", "prototype", "constructor"]);

// Aplica una op sobre un borrador de immer. Lanza OpInvalida y deja que
// produce() descarte el borrador completo: las ops son atómicas.
export function aplicarEnBorrador(d: Draft<Escena>, op: Op): void {
  if (op.op === "set") {
    const capa = d.capas.find((c) => c.id === op.capa);
    if (!capa) throw new OpInvalida(`set: no existe la capa «${op.capa}»`);
    const partes = op.ruta.split(".");
    if (partes.some((p) => p === "" || PELIGROSAS.has(p))) throw new OpInvalida(`set: ruta inválida «${op.ruta}»`);
    if (partes.length === 1 && INTOCABLES.has(partes[0])) throw new OpInvalida(`set: «${op.ruta}» no se puede cambiar`);
    let nodo = capa as unknown as Record<string, unknown>;
    for (const p of partes.slice(0, -1)) {
      const sig = nodo[p];
      if (sig === undefined || sig === null) nodo[p] = {};
      else if (typeof sig !== "object" || Array.isArray(sig))
        throw new OpInvalida(`set: «${p}» no es un objeto en la capa «${op.capa}»`);
      nodo = nodo[p] as Record<string, unknown>;
    }
    nodo[partes[partes.length - 1]] = structuredClone(op.valor);
    return;
  }
  if (op.op === "add") {
    if (d.capas.some((c) => c.id === op.capa.id)) throw new OpInvalida(`add: ya existe la capa «${op.capa.id}»`);
    const n = d.capas.length;
    const i = op.indice === undefined ? n : Math.min(Math.max(Math.trunc(op.indice), 0), n);
    d.capas.splice(i, 0, structuredClone(op.capa) as Draft<Capa>);
    return;
  }
  if (!d.capas.some((c) => c.id === op.capa)) throw new OpInvalida(`del: no existe la capa «${op.capa}»`);
  const borrar = new Set([op.capa, ...descendientes(d as Escena, op.capa)]);
  // Un grupo que se queda sin hijos se borra también (el validador prohíbe hijos vacíos).
  let cambio = true;
  while (cambio) {
    cambio = false;
    for (const c of d.capas) {
      if (c.tipo === "group" && !borrar.has(c.id) && c.hijos.length > 0 && c.hijos.every((h) => borrar.has(h))) {
        borrar.add(c.id);
        cambio = true;
      }
    }
  }
  d.capas = d.capas.filter((c) => !borrar.has(c.id));
  for (const c of d.capas) if (c.tipo === "group") c.hijos = c.hijos.filter((h) => !borrar.has(h));
}

export function aplicarOps(escena: Escena, ops: Op[]): Escena {
  return produce(escena, (d) => {
    for (const op of ops) aplicarEnBorrador(d, op);
  });
}

export function descendientes(escena: Escena, id: string): string[] {
  const porId = new Map(escena.capas.map((c) => [c.id, c]));
  const vistos = new Set<string>();
  const pila = [id];
  while (pila.length) {
    const c = porId.get(pila.pop()!);
    if (!c || c.tipo !== "group") continue;
    for (const h of c.hijos) {
      if (vistos.has(h) || h === id) continue;
      vistos.add(h);
      pila.push(h);
    }
  }
  return [...vistos];
}

export function padreDe(escena: Escena, id: string): string | null {
  for (const c of escena.capas) if (c.tipo === "group" && c.hijos.includes(id)) return c.id;
  return null;
}

export function raizDe(escena: Escena, id: string): string {
  let actual = id;
  const vistos = new Set([id]);
  for (let p = padreDe(escena, actual); p && !vistos.has(p); p = padreDe(escena, actual)) {
    vistos.add(p);
    actual = p;
  }
  return actual;
}

// Ids que no se pintan: ocultas ellas mismas o dentro de un grupo oculto.
export function ocultasEfectivas(escena: Escena): Set<string> {
  const out = new Set<string>();
  for (const c of escena.capas) {
    if (!c.oculta) continue;
    out.add(c.id);
    for (const d of descendientes(escena, c.id)) out.add(d);
  }
  return out;
}

// Orden de pintado: z ascendente; en empate, el orden del arreglo.
export function ordenadas(escena: Escena): Capa[] {
  return escena.capas
    .map((c, i) => [c, i] as const)
    .sort((a, b) => a[0].z - b[0].z || a[1] - b[1])
    .map(([c]) => c);
}

// Caja de cada grupo = unión de las cajas de sus hijos (recursivo, sin ciclos).
export function cajasDeGrupo(escena: Escena): Map<string, Caja> {
  const porId = new Map(escena.capas.map((c) => [c.id, c]));
  const memo = new Map<string, Caja | null>();
  const enCurso = new Set<string>();
  const caja = (id: string): Caja | null => {
    if (memo.has(id)) return memo.get(id)!;
    const c = porId.get(id);
    if (!c) return null;
    if (c.tipo !== "group") return { x: c.x, y: c.y, w: c.w, h: c.h };
    if (enCurso.has(id)) return null;
    enCurso.add(id);
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const h of c.hijos) {
      const k = caja(h);
      if (!k) continue;
      x0 = Math.min(x0, k.x);
      y0 = Math.min(y0, k.y);
      x1 = Math.max(x1, k.x + k.w);
      y1 = Math.max(y1, k.y + k.h);
    }
    enCurso.delete(id);
    const r = x0 === Infinity ? null : { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
    memo.set(id, r);
    return r;
  };
  const out = new Map<string, Caja>();
  for (const c of escena.capas) {
    if (c.tipo !== "group") continue;
    const k = caja(c.id);
    if (k) out.set(c.id, k);
  }
  return out;
}

export function cajaDe(escena: Escena, id: string): Caja | null {
  const c = escena.capas.find((k) => k.id === id);
  if (!c) return null;
  if (c.tipo !== "group") return { x: c.x, y: c.y, w: c.w, h: c.h };
  return cajasDeGrupo(escena).get(id) ?? null;
}

// Misma regla que escena.reformatear del plan 1: dy = nuevoH − viejoH;
// top no se mueve, bottom suma dy, center suma round(dy/2); lo que cubre
// todo el lienzo se estira; los grupos se recalculan al final.
export function reformatear(escena: Escena, formato: Formato): Escena {
  const { w: nw, h: nh } = FORMATOS[formato];
  const ow = escena.lienzo.w;
  const oh = escena.lienzo.h;
  const dy = nh - oh;
  return produce(escena, (d) => {
    for (const c of d.capas) {
      if (c.tipo === "group") continue;
      if (c.x <= 0 && c.y <= 0 && c.x + c.w >= ow && c.y + c.h >= oh) {
        Object.assign(c, { x: 0, y: 0, w: nw, h: nh });
        continue;
      }
      if (c.anclaje === "bottom") c.y += dy;
      else if (c.anclaje === "center") c.y += Math.round(dy / 2);
    }
    const cajas = cajasDeGrupo(d as Escena);
    for (const c of d.capas) {
      const k = c.tipo === "group" ? cajas.get(c.id) : undefined;
      if (k) Object.assign(c, k);
    }
    d.lienzo.w = nw;
    d.lienzo.h = nh;
    d.lienzo.formato = formato;
  });
}

export function resolverColor(valor: string, tokens: Tokens, colorMarca: string): string {
  if (!valor.startsWith("token:")) return valor;
  const nombre = valor.slice("token:".length);
  if (nombre === "marca") return colorMarca;
  return tokens.colores[nombre] ?? "transparent";
}

export function idLibre(escena: Escena, base: string): string {
  let s = base
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (!/^[a-z]/.test(s)) s = `c_${s}`;
  s = s.slice(0, 26).replace(/_+$/, "") || "c";
  const usados = new Set(escena.capas.map((c) => c.id));
  if (!usados.has(s)) return s;
  for (let n = 2; ; n++) {
    const id = `${s}_${n}`;
    if (!usados.has(id)) return id;
  }
}

export function capaNueva(
  tipo: "text" | "shape" | "image" | "svg",
  escena: Escena,
  opciones: { fuente: string; src?: string; nombre?: string },
): Capa {
  const { w: W, h: H } = escena.lienzo;
  const z = Math.min(999, Math.max(-1, ...escena.capas.map((c) => c.z)) + 1);
  const base = (nombre: string, w: number, h: number) => ({
    id: idLibre(escena, opciones.nombre ?? nombre),
    nombre: opciones.nombre ?? nombre,
    x: Math.round((W - w) / 2),
    y: Math.round((H - h) / 2),
    w,
    h,
    rot: 0,
    opacity: 1,
    z,
    bloqueada: false,
    oculta: false,
    anclaje: "center" as Anclaje,
  });
  if (tipo === "text") {
    return {
      ...base("texto", 800, 160),
      tipo: "text",
      texto: "Texto",
      estilo: {
        fontFamily: opciones.fuente,
        fontWeight: 700,
        fontSize: 96,
        lineHeight: 1.1,
        letterSpacing: "0em",
        color: "#111111",
        textAlign: "left",
        textWrap: "balance",
        verticalAlign: "top",
        textTransform: "none",
        spans: [],
      },
    };
  }
  if (tipo === "shape") {
    return { ...base("forma", 400, 400), tipo: "shape", forma: "rect", estilo: { fill: "token:marca", radius: 0, borderWidth: 0 } };
  }
  if (!opciones.src) throw new Error(`capaNueva: «${tipo}» necesita src`);
  if (tipo === "svg") {
    return { ...base("svg", 300, 300), tipo: "svg", src: opciones.src, ajuste: "contain", estilo: {} };
  }
  return {
    ...base("imagen", 800, 800),
    tipo: "image",
    src: opciones.src,
    campo: null,
    ajuste: "cover",
    mascara: "none",
    estilo: { objectPosition: "center" },
  };
}

// src es "assets/<archivo>" o "fotos/<archivo>" (plan 1, D2).
export function urlDeAsset(slug: string, src: string): string {
  return `/api/brands/${slug}/files/${src.split("/").map(encodeURIComponent).join("/")}`;
}

export function normalizarAngulo(a: number): number {
  const r = ((((a + 180) % 360) + 360) % 360) - 180;
  return r === -180 && a > 0 ? 180 : r;
}
```

- [ ] **Step 5: correr las pruebas**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test lib/__tests__/escena.test.ts && pnpm exec tsc --noEmit && pnpm lint
```

Esperado: todas en verde (19 casos compartidos + 5 de reformatear + 6 de utilidades), con tsc y lint limpios.

- [ ] **Step 6: commit**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2
git add frontend/lib/escena.ts frontend/lib/__fixtures__/ops-casos.json frontend/lib/__tests__/escena.test.ts
git commit -F - <<'EOF'
editor v2: modelo de escena, aplicarOps atómica y reformatear

Tipos de la escena v2 con los nombres del plan 1. aplicarOps con immer
(set/add/del, cascada de grupos vacíos). reformatear con la regla de
anclaje del backend. Fixture ops-casos.json compartido con ops.py (plan 4).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

## Task 3: color por tramo (`lib/spans.ts`)

**Files:**
- Create: `frontend/lib/spans.ts`
- Create: `frontend/lib/__tests__/spans.test.ts`

**Interfaces:**

```ts
export type Trozo = { texto: string; color: string | null };
export function trozos(texto: string, spans?: Span[]): Trozo[];                  // para pintar
export function ajustarSpans(antes: string, despues: string, spans: Span[]): Span[]; // tras teclear
export function pintarSpan(spans: Span[], desde: number, hasta: number, color: string | null): Span[];
```

Regla D11 de `ajustarSpans`:

- Se calcula el tramo editado: prefijo común `p` y sufijo común `s`.
- Lo que se inserta hereda color **solo** si queda estrictamente dentro de un span (`desde < p < hasta`).
- En los bordes queda sin color.
- Un span que se queda vacío desaparece.

- [ ] **Step 1: pruebas que fallan**

`frontend/lib/__tests__/spans.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { ajustarSpans, pintarSpan, trozos } from "../spans";

const S = (desde: number, hasta: number, color = "#f00") => ({ desde, hasta, color });

describe("trozos", () => {
  it("parte el texto en tramos con y sin color", () => {
    expect(trozos("Hola mundo", [S(5, 10)])).toEqual([
      { texto: "Hola ", color: null },
      { texto: "mundo", color: "#f00" },
    ]);
  });
  it("ignora spans vacíos y fuera de rango", () => {
    expect(trozos("Hola", [S(2, 2), S(3, 99)])).toEqual([
      { texto: "Hol", color: null },
      { texto: "a", color: "#f00" },
    ]);
  });
  it("sin spans devuelve un solo tramo", () => {
    expect(trozos("Hola")).toEqual([{ texto: "Hola", color: null }]);
  });
});

describe("ajustarSpans", () => {
  it("insertar dentro del span lo agranda", () => {
    expect(ajustarSpans("Hola mundo", "Hola muXndo", [S(5, 10)])).toEqual([S(5, 11)]);
  });
  it("insertar antes del span lo recorre", () => {
    expect(ajustarSpans("Hola mundo", "Hola Xmundo", [S(5, 10)])).toEqual([S(6, 11)]);
  });
  it("insertar justo al final del span no hereda color", () => {
    expect(ajustarSpans("Hola mundo", "Hola mundoX", [S(5, 10)])).toEqual([S(5, 10)]);
  });
  it("borrar a caballo del span lo recorta", () => {
    // "Hola mundo" con span "a mu" (3-7); se borra "la m" (2-6) → "Houndo", queda "u".
    expect(ajustarSpans("Hola mundo", "Houndo", [S(3, 7)])).toEqual([S(2, 3)]);
  });
  it("borrar todo el span lo elimina", () => {
    expect(ajustarSpans("Hola mundo", "Hola ", [S(5, 10)])).toEqual([]);
  });
  it("sin cambio devuelve lo mismo", () => {
    const spans = [S(0, 4)];
    expect(ajustarSpans("Hola", "Hola", spans)).toBe(spans);
  });
});

describe("pintarSpan", () => {
  it("agrega un tramo", () => {
    expect(pintarSpan([], 0, 4, "#f00")).toEqual([S(0, 4)]);
  });
  it("parte un span existente al pintar en medio", () => {
    expect(pintarSpan([S(0, 10)], 3, 6, "#00f")).toEqual([S(0, 3), S(3, 6, "#00f"), S(6, 10)]);
  });
  it("une tramos contiguos del mismo color", () => {
    expect(pintarSpan([S(0, 3)], 3, 6, "#f00")).toEqual([S(0, 6)]);
  });
  it("con color null borra el tramo", () => {
    expect(pintarSpan([S(0, 10)], 3, 6, null)).toEqual([S(0, 3), S(6, 10)]);
  });
  it("rango vacío no cambia nada", () => {
    const spans = [S(0, 3)];
    expect(pintarSpan(spans, 2, 2, "#00f")).toBe(spans);
  });
});
```

- [ ] **Step 2: correrlas y ver que fallan**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test lib/__tests__/spans.test.ts
```

Esperado: FAIL con `Failed to resolve import "../spans"`.

- [ ] **Step 3: implementar**

`frontend/lib/spans.ts`:

```ts
import type { Span } from "./escena";

export type Trozo = { texto: string; color: string | null };

export function trozos(texto: string, spans: Span[] = []): Trozo[] {
  const orden = [...spans].sort((a, b) => a.desde - b.desde);
  const out: Trozo[] = [];
  let i = 0;
  for (const s of orden) {
    const desde = Math.max(s.desde, i);
    const hasta = Math.min(s.hasta, texto.length);
    if (hasta <= desde) continue;
    if (desde > i) out.push({ texto: texto.slice(i, desde), color: null });
    out.push({ texto: texto.slice(desde, hasta), color: s.color });
    i = hasta;
  }
  if (i < texto.length) out.push({ texto: texto.slice(i), color: null });
  return out;
}

// Recoloca los spans tras una edición. El tramo editado es lo que queda
// entre el prefijo y el sufijo comunes. Regla D11: lo insertado hereda
// color solo si cae estrictamente dentro de un span.
export function ajustarSpans(antes: string, despues: string, spans: Span[]): Span[] {
  if (antes === despues) return spans;
  const max = Math.min(antes.length, despues.length);
  let p = 0;
  while (p < max && antes[p] === despues[p]) p++;
  let s = 0;
  while (s < max - p && antes[antes.length - 1 - s] === despues[despues.length - 1 - s]) s++;
  const finA = antes.length - s;
  const finD = despues.length - s;
  const delta = finD - finA;
  const desde = (pos: number) => (pos < p ? pos : pos >= finA ? pos + delta : finD);
  const hasta = (pos: number) => (pos <= p ? pos : pos >= finA ? pos + delta : p);
  return spans
    .map((sp) => ({
      ...sp,
      desde: Math.min(Math.max(desde(sp.desde), 0), despues.length),
      hasta: Math.min(Math.max(hasta(sp.hasta), 0), despues.length),
    }))
    .filter((sp) => sp.hasta > sp.desde);
}

export function pintarSpan(spans: Span[], desde: number, hasta: number, color: string | null): Span[] {
  if (hasta <= desde) return spans;
  const out: Span[] = [];
  for (const s of spans) {
    if (s.hasta <= desde || s.desde >= hasta) {
      out.push(s);
      continue;
    }
    if (s.desde < desde) out.push({ ...s, hasta: desde });
    if (s.hasta > hasta) out.push({ ...s, desde: hasta });
  }
  if (color) out.push({ desde, hasta, color });
  out.sort((a, b) => a.desde - b.desde);
  const unidos: Span[] = [];
  for (const s of out) {
    const u = unidos[unidos.length - 1];
    if (u && u.hasta === s.desde && u.color === s.color) u.hasta = s.hasta;
    else unidos.push({ ...s });
  }
  return unidos;
}
```

- [ ] **Step 4: verde**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test lib/__tests__/spans.test.ts && pnpm exec tsc --noEmit && pnpm lint
```

Esperado: 14 passed; tsc y lint limpios.

- [ ] **Step 5: commit**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2
git add frontend/lib/spans.ts frontend/lib/__tests__/spans.test.ts
git commit -F - <<'EOF'
editor v2: color por tramo (trozos, ajustarSpans, pintarSpan)

Lo que se escribe hereda color solo si cae estrictamente dentro de un span.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

## Task 4: operaciones de edición puras (`lib/edicion.ts`)

**Files:**
- Create: `frontend/lib/edicion.ts`
- Create: `frontend/lib/__tests__/edicion.test.ts`

**Interfaces:** todas son funciones puras que devuelven `Op[]`; ninguna toca el store.

Mover y acomodar:

```ts
export function expandir(escena: Escena, ids: string[]): string[];              // hojas (no grupos) de una selección
export function opsMover(escena: Escena, ids: string[], dx: number, dy: number): Op[];
export type ModoAlinear = "izq" | "centro-h" | "der" | "arriba" | "centro-v" | "abajo";
export function opsAlinear(escena: Escena, ids: string[], modo: ModoAlinear): Op[];
export function opsDistribuir(escena: Escena, ids: string[], eje: "h" | "v"): Op[];
```

Grupos, copias y pegado:

```ts
export function opsAgrupar(escena: Escena, ids: string[]): { ops: Op[]; id: string } | null;
export function opsDesagrupar(escena: Escena, id: string): { ops: Op[]; hijos: string[] } | null;
export function clonarConIds(escena: Escena, capas: Capa[], desplazar?: number): { capas: Capa[]; mapa: Map<string, string> };
export function opsDuplicar(escena: Escena, ids: string[]): { ops: Op[]; nuevos: string[] };
export function opsPegar(escena: Escena, capas: Capa[]): { ops: Op[]; nuevos: string[] };
```

Orden en `z`:

```ts
export type ModoZ = "subir" | "bajar" | "frente" | "fondo";
export function opsZ(escena: Escena, ids: string[], modo: ModoZ): Op[];
export function opsReordenar(escena: Escena, hermanosArribaPrimero: string[]): Op[];
```

Cajas de grupo y utilidades:

```ts
export function opsCajasDeGrupo(escena: Escena): Op[];
export function conCajasDeGrupo(escena: Escena, ops: Op[]): Op[];             // ops + recálculo de cajas
export function esCampoDeTexto(t: EventTarget | null): boolean;
```

Modelo de `z` (D6):

- `z` es el orden global de pintado de las **hojas**.
- La `z` guardada en un grupo no se usa para pintar. El panel la deriva como el máximo de sus hojas.
- `opsZ` y `opsReordenar` construyen el nuevo orden de hojas y asignan `z = posición`, de abajo hacia arriba.

- [ ] **Step 1: pruebas que fallan**

`frontend/lib/__tests__/edicion.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import datos from "../__fixtures__/ops-casos.json";
import { aplicarOps, ordenadas, type Escena } from "../escena";
import {
  conCajasDeGrupo,
  esCampoDeTexto,
  expandir,
  opsAgrupar,
  opsAlinear,
  opsDesagrupar,
  opsDistribuir,
  opsDuplicar,
  opsMover,
  opsPegar,
  opsReordenar,
  opsZ,
} from "../edicion";

const base = () => structuredClone((datos as unknown as { base: Escena }).base);
const capa = (e: Escena, id: string) => e.capas.find((c) => c.id === id)!;
const hojas = (e: Escena) => ordenadas(e).filter((c) => c.tipo !== "group").map((c) => c.id);
// Aplica y recalcula cajas de grupo, como hace el store.
const correr = (e: Escena, ops: Parameters<typeof aplicarOps>[1]) => aplicarOps(e, conCajasDeGrupo(e, ops));

describe("mover", () => {
  it("expandir baja a las hojas", () => {
    expect(expandir(base(), ["marca", "titulo"]).sort()).toEqual(["caja", "logo", "titulo"]);
  });
  it("mover un grupo mueve sus hijos y recalcula su caja", () => {
    const e = base();
    const r = correr(e, opsMover(e, ["marca"], 10.4, -20));
    expect(capa(r, "caja")).toMatchObject({ x: 10, y: 1180 });
    expect(capa(r, "logo")).toMatchObject({ x: 910, y: 1210 });
    expect(capa(r, "marca")).toMatchObject({ x: 10, y: 1180, w: 1080, h: 150 });
  });
  it("una capa bloqueada no se mueve", () => {
    const e = aplicarOps(base(), [{ op: "set", capa: "logo", ruta: "bloqueada", valor: true }]);
    expect(opsMover(e, ["marca"], 5, 5).some((o) => o.op === "set" && o.capa === "logo")).toBe(false);
  });
});

describe("alinear y distribuir", () => {
  it("una sola capa se alinea al lienzo", () => {
    const e = base();
    const r = correr(e, opsAlinear(e, ["titulo"], "centro-h"));
    expect(capa(r, "titulo").x).toBe(80); // ya estaba centrada: (1080 − 920) / 2
    const r2 = correr(e, opsAlinear(e, ["titulo"], "abajo"));
    expect(capa(r2, "titulo").y).toBe(1050);
  });
  it("varias se alinean a su unión", () => {
    const e = base();
    const r = correr(e, opsAlinear(e, ["titulo", "logo"], "der"));
    expect(capa(r, "titulo").x + capa(r, "titulo").w).toBe(1020);
    expect(capa(r, "logo").x + capa(r, "logo").w).toBe(1020);
  });
  it("distribuir necesita tres", () => {
    const e = base();
    expect(opsDistribuir(e, ["titulo", "logo"], "h")).toEqual([]);
  });
  it("distribuir reparte el hueco", () => {
    const e = aplicarOps(base(), [
      { op: "set", capa: "titulo", ruta: "w", valor: 100 },
      { op: "set", capa: "titulo", ruta: "x", valor: 0 },
      { op: "set", capa: "caja", ruta: "w", valor: 100 },
      { op: "set", capa: "caja", ruta: "x", valor: 100 },
      { op: "set", capa: "logo", ruta: "w", valor: 100 },
      { op: "set", capa: "logo", ruta: "x", valor: 900 },
    ]);
    const r = aplicarOps(e, opsDistribuir(e, ["titulo", "caja", "logo"], "h"));
    expect(capa(r, "caja").x).toBe(450);
  });
});

describe("grupos", () => {
  it("agrupar crea el grupo con la caja de la unión", () => {
    const e = base();
    const g = opsAgrupar(e, ["caja", "titulo"]);
    expect(g).toBeNull(); // padres distintos: caja está en marca, titulo en la raíz
    const g2 = opsAgrupar(e, ["titulo", "marca"])!;
    const r = correr(e, g2.ops);
    expect(g2.id).toBe("grupo");
    expect(capa(r, "grupo")).toMatchObject({ tipo: "group", hijos: ["titulo", "marca"], x: 0, y: 196, w: 1080, h: 1154 });
  });
  it("agrupar dentro de un grupo reemplaza los hijos del padre", () => {
    const e = base();
    const g = opsAgrupar(e, ["caja", "logo"])!;
    const r = correr(e, g.ops);
    expect(capa(r, "marca")).toMatchObject({ hijos: ["grupo"] });
    expect(capa(r, "grupo")).toMatchObject({ hijos: ["caja", "logo"] });
  });
  it("desagrupar devuelve los hijos al padre y borra el grupo", () => {
    const e = base();
    const d = opsDesagrupar(e, "marca")!;
    const r = correr(e, d.ops);
    expect(d.hijos).toEqual(["caja", "logo"]);
    expect(r.capas.map((c) => c.id)).toEqual(["titulo", "caja", "logo"]);
  });
  it("desagrupar algo que no es grupo es null", () => {
    expect(opsDesagrupar(base(), "titulo")).toBeNull();
  });
});

describe("duplicar y pegar", () => {
  it("duplicar un grupo clona sus hijos con ids nuevos y los sube al frente", () => {
    const e = base();
    const d = opsDuplicar(e, ["marca"]);
    const r = correr(e, d.ops);
    expect(d.nuevos).toEqual(["marca_2"]);
    expect(capa(r, "marca_2")).toMatchObject({ hijos: ["caja_2", "logo_2"], x: 20, y: 1220 });
    expect(capa(r, "caja_2")).toMatchObject({ x: 20, y: 1220 });
    expect(Math.min(capa(r, "caja_2").z, capa(r, "logo_2").z)).toBeGreaterThan(3);
  });
  it("pegar sobre una escena sin esas capas conserva los ids", () => {
    const e = base();
    const vacia = { ...e, capas: [] };
    const p = opsPegar(vacia, [capa(e, "titulo")]);
    expect(p.nuevos).toEqual(["titulo"]);
  });
});

describe("orden z", () => {
  it("frente y fondo", () => {
    const e = base();
    expect(hojas(aplicarOps(e, opsZ(e, ["caja"], "frente")))).toEqual(["logo", "titulo", "caja"]);
    expect(hojas(aplicarOps(e, opsZ(e, ["titulo"], "fondo")))).toEqual(["titulo", "caja", "logo"]);
  });
  it("subir y bajar un paso", () => {
    const e = base();
    expect(hojas(aplicarOps(e, opsZ(e, ["caja"], "subir")))).toEqual(["logo", "caja", "titulo"]);
    expect(hojas(aplicarOps(e, opsZ(e, ["titulo"], "bajar")))).toEqual(["caja", "titulo", "logo"]);
  });
  it("subir lo que ya está arriba no genera ops", () => {
    const e = base();
    expect(opsZ(e, ["titulo"], "subir")).toEqual([]);
  });
  it("reordenar hermanos mueve el bloque del grupo completo", () => {
    const e = base();
    // Raíces de arriba hacia abajo: marca arriba de titulo.
    expect(hojas(aplicarOps(e, opsReordenar(e, ["marca", "titulo"])))).toEqual(["titulo", "caja", "logo"]);
  });
});

describe("esCampoDeTexto", () => {
  it("reconoce input, textarea y contenteditable", () => {
    const div = document.createElement("div");
    div.contentEditable = "true";
    expect(esCampoDeTexto(document.createElement("input"))).toBe(true);
    expect(esCampoDeTexto(document.createElement("textarea"))).toBe(true);
    expect(esCampoDeTexto(document.createElement("button"))).toBe(false);
    expect(esCampoDeTexto(null)).toBe(false);
  });
});
```

Notas sobre los valores esperados:

- `marca` es `0,1200 1080x150`, `titulo` es `80,196 920x300`. La unión es `0,196 → 1080,1350`, es decir `h = 1154`.
- Hojas por `z` en la base: caja (1), logo (2), titulo (3).

- [ ] **Step 2: correrlas y ver que fallan**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test lib/__tests__/edicion.test.ts
```

Esperado: FAIL con `Failed to resolve import "../edicion"`.

- [ ] **Step 3: implementar**

`frontend/lib/edicion.ts`:

```ts
import {
  aplicarOps,
  cajaDe,
  cajasDeGrupo,
  descendientes,
  idLibre,
  ordenadas,
  padreDe,
  type Caja,
  type Capa,
  type CapaGrupo,
  type Escena,
  type Op,
} from "./escena";

const porId = (e: Escena) => new Map(e.capas.map((c) => [c.id, c]));

// Hojas (no grupos) de una selección, sin repetir.
export function expandir(escena: Escena, ids: string[]): string[] {
  const m = porId(escena);
  const out = new Set<string>();
  for (const id of ids) {
    for (const k of [id, ...descendientes(escena, id)]) {
      const c = m.get(k);
      if (c && c.tipo !== "group") out.add(k);
    }
  }
  return [...out];
}

export function opsMover(escena: Escena, ids: string[], dx: number, dy: number): Op[] {
  const m = porId(escena);
  const ops: Op[] = [];
  for (const id of expandir(escena, ids)) {
    const c = m.get(id)!;
    if (c.bloqueada) continue;
    const x = Math.round(c.x + dx);
    const y = Math.round(c.y + dy);
    if (x !== c.x) ops.push({ op: "set", capa: id, ruta: "x", valor: x });
    if (y !== c.y) ops.push({ op: "set", capa: id, ruta: "y", valor: y });
  }
  return ops;
}

function union(cajas: Caja[]): Caja {
  const x0 = Math.min(...cajas.map((k) => k.x));
  const y0 = Math.min(...cajas.map((k) => k.y));
  const x1 = Math.max(...cajas.map((k) => k.x + k.w));
  const y1 = Math.max(...cajas.map((k) => k.y + k.h));
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

export type ModoAlinear = "izq" | "centro-h" | "der" | "arriba" | "centro-v" | "abajo";

// Una capa se alinea al lienzo; varias, a la unión de sus cajas.
export function opsAlinear(escena: Escena, ids: string[], modo: ModoAlinear): Op[] {
  const cajas = ids.map((id) => [id, cajaDe(escena, id)] as const).filter((p): p is [string, Caja] => !!p[1]);
  if (cajas.length === 0) return [];
  const ref = cajas.length === 1 ? { x: 0, y: 0, w: escena.lienzo.w, h: escena.lienzo.h } : union(cajas.map((p) => p[1]));
  return cajas.flatMap(([id, k]) => {
    const dx =
      modo === "izq" ? ref.x - k.x : modo === "der" ? ref.x + ref.w - (k.x + k.w) : modo === "centro-h" ? ref.x + (ref.w - k.w) / 2 - k.x : 0;
    const dy =
      modo === "arriba" ? ref.y - k.y : modo === "abajo" ? ref.y + ref.h - (k.y + k.h) : modo === "centro-v" ? ref.y + (ref.h - k.h) / 2 - k.y : 0;
    return opsMover(escena, [id], dx, dy);
  });
}

export function opsDistribuir(escena: Escena, ids: string[], eje: "h" | "v"): Op[] {
  const cajas = ids.map((id) => [id, cajaDe(escena, id)] as const).filter((p): p is [string, Caja] => !!p[1]);
  if (cajas.length < 3) return [];
  const pos = (k: Caja) => (eje === "h" ? k.x : k.y);
  const tam = (k: Caja) => (eje === "h" ? k.w : k.h);
  cajas.sort((a, b) => pos(a[1]) - pos(b[1]));
  const primera = cajas[0][1];
  const ultima = cajas[cajas.length - 1][1];
  const total = pos(ultima) + tam(ultima) - pos(primera);
  const hueco = (total - cajas.reduce((s, p) => s + tam(p[1]), 0)) / (cajas.length - 1);
  const ops: Op[] = [];
  let cursor = pos(primera) + tam(primera) + hueco;
  for (const [id, k] of cajas.slice(1, -1)) {
    const d = cursor - pos(k);
    ops.push(...opsMover(escena, [id], eje === "h" ? d : 0, eje === "v" ? d : 0));
    cursor += tam(k) + hueco;
  }
  return ops;
}

export function opsAgrupar(escena: Escena, ids: string[]): { ops: Op[]; id: string } | null {
  if (ids.length < 2) return null;
  const padres = new Set(ids.map((id) => padreDe(escena, id)));
  if (padres.size !== 1) return null;
  const padre = [...padres][0];
  const enOrden = escena.capas.filter((c) => ids.includes(c.id)).map((c) => c.id);
  const cajas = enOrden.map((id) => cajaDe(escena, id)).filter((k): k is Caja => !!k);
  const z = Math.max(...expandir(escena, enOrden).map((id) => escena.capas.find((c) => c.id === id)!.z));
  const id = idLibre(escena, "grupo");
  const grupo: CapaGrupo = {
    id,
    nombre: "Grupo",
    tipo: "group",
    ...union(cajas),
    rot: 0,
    opacity: 1,
    z,
    bloqueada: false,
    oculta: false,
    anclaje: "center",
    hijos: enOrden,
    estilo: {},
  };
  const ops: Op[] = [{ op: "add", capa: grupo }];
  if (padre) {
    const p = escena.capas.find((c) => c.id === padre) as CapaGrupo;
    const primero = p.hijos.findIndex((h) => enOrden.includes(h));
    const resto = p.hijos.filter((h) => !enOrden.includes(h));
    resto.splice(Math.min(primero, resto.length), 0, id);
    ops.push({ op: "set", capa: padre, ruta: "hijos", valor: resto });
  }
  return { ops, id };
}

export function opsDesagrupar(escena: Escena, id: string): { ops: Op[]; hijos: string[] } | null {
  const g = escena.capas.find((c) => c.id === id);
  if (!g || g.tipo !== "group") return null;
  const ops: Op[] = [];
  const padre = padreDe(escena, id);
  if (padre) {
    const p = escena.capas.find((c) => c.id === padre) as CapaGrupo;
    ops.push({ op: "set", capa: padre, ruta: "hijos", valor: p.hijos.flatMap((h) => (h === id ? g.hijos : [h])) });
  }
  // Primero se vacía el grupo para que del no se lleve a los hijos.
  ops.push({ op: "set", capa: id, ruta: "hijos", valor: [] }, { op: "del", capa: id });
  return { ops, hijos: [...g.hijos] };
}

export function clonarConIds(escena: Escena, capas: Capa[], desplazar = 20): { capas: Capa[]; mapa: Map<string, string> } {
  const temp: Escena = { ...escena, capas: [...escena.capas] };
  const mapa = new Map<string, string>();
  for (const c of capas) {
    const nuevo = idLibre(temp, c.id);
    mapa.set(c.id, nuevo);
    temp.capas.push({ ...c, id: nuevo });
  }
  const clones = capas.map((c) => {
    const k = structuredClone(c);
    k.id = mapa.get(c.id)!;
    k.x += desplazar;
    k.y += desplazar;
    if (k.tipo === "group") k.hijos = k.hijos.map((h) => mapa.get(h)).filter((h): h is string => !!h);
    return k;
  });
  return { capas: clones, mapa };
}

// Clona y pone las copias arriba de todo, conservando su orden relativo.
function opsClonar(escena: Escena, capas: Capa[], desplazar: number): { ops: Op[]; nuevos: string[] } {
  if (capas.length === 0) return { ops: [], nuevos: [] };
  const { capas: clones, mapa } = clonarConIds(escena, capas, desplazar);
  const tope = Math.max(-1, ...escena.capas.map((c) => c.z));
  const enOrden = [...clones].sort((a, b) => a.z - b.z);
  enOrden.forEach((c, i) => (c.z = Math.min(999, tope + 1 + i)));
  const hijosDeCopia = new Set(clones.flatMap((c) => (c.tipo === "group" ? c.hijos : [])));
  const nuevos = capas.map((c) => mapa.get(c.id)!).filter((id) => !hijosDeCopia.has(id));
  return { ops: clones.map((c) => ({ op: "add", capa: c }) as Op), nuevos };
}

export function opsDuplicar(escena: Escena, ids: string[]): { ops: Op[]; nuevos: string[] } {
  const todos = new Set(ids.flatMap((id) => [id, ...descendientes(escena, id)]));
  return opsClonar(escena, escena.capas.filter((c) => todos.has(c.id)), 20);
}

export function opsPegar(escena: Escena, capas: Capa[]): { ops: Op[]; nuevos: string[] } {
  return opsClonar(escena, capas, 20);
}

export type ModoZ = "subir" | "bajar" | "frente" | "fondo";

const ordenHojas = (e: Escena) => ordenadas(e).filter((c) => c.tipo !== "group").map((c) => c.id);

function opsDeOrden(escena: Escena, orden: string[]): Op[] {
  const m = porId(escena);
  return orden.flatMap((id, i) => (m.get(id)!.z === i ? [] : [{ op: "set", capa: id, ruta: "z", valor: i } as Op]));
}

export function opsZ(escena: Escena, ids: string[], modo: ModoZ): Op[] {
  const sel = new Set(expandir(escena, ids));
  const L = ordenHojas(escena);
  let nuevo: string[];
  if (modo === "frente") nuevo = [...L.filter((id) => !sel.has(id)), ...L.filter((id) => sel.has(id))];
  else if (modo === "fondo") nuevo = [...L.filter((id) => sel.has(id)), ...L.filter((id) => !sel.has(id))];
  else {
    nuevo = [...L];
    if (modo === "subir") {
      for (let i = nuevo.length - 2; i >= 0; i--)
        if (sel.has(nuevo[i]) && !sel.has(nuevo[i + 1])) [nuevo[i], nuevo[i + 1]] = [nuevo[i + 1], nuevo[i]];
    } else {
      for (let i = 1; i < nuevo.length; i++)
        if (sel.has(nuevo[i]) && !sel.has(nuevo[i - 1])) [nuevo[i], nuevo[i - 1]] = [nuevo[i - 1], nuevo[i]];
    }
  }
  if (nuevo.every((id, i) => id === L[i])) return [];
  return opsDeOrden(escena, nuevo);
}

// El panel manda los hermanos de arriba hacia abajo. Cada hermano es un
// bloque de hojas; los bloques se reinsertan donde estaba el más bajo.
export function opsReordenar(escena: Escena, hermanosArribaPrimero: string[]): Op[] {
  const L = ordenHojas(escena);
  const bloques = hermanosArribaPrimero.map((id) => {
    const set = new Set(expandir(escena, [id]));
    return L.filter((h) => set.has(h));
  });
  const enBloques = new Set(bloques.flat());
  const pos = L.findIndex((h) => enBloques.has(h));
  if (pos < 0) return [];
  const resto = L.filter((h) => !enBloques.has(h));
  const antes = L.slice(0, pos).filter((h) => !enBloques.has(h)).length;
  const nuevo = [...resto.slice(0, antes), ...[...bloques].reverse().flat(), ...resto.slice(antes)];
  return opsDeOrden(escena, nuevo);
}

export function opsCajasDeGrupo(escena: Escena): Op[] {
  const cajas = cajasDeGrupo(escena);
  const ops: Op[] = [];
  for (const c of escena.capas) {
    const k = cajas.get(c.id);
    if (!k) continue;
    for (const campo of ["x", "y", "w", "h"] as const)
      if (c[campo] !== k[campo]) ops.push({ op: "set", capa: c.id, ruta: campo, valor: k[campo] });
  }
  return ops;
}

// Lo que manda el store: las ops y el recálculo de cajas, en un solo paso.
export function conCajasDeGrupo(escena: Escena, ops: Op[]): Op[] {
  if (ops.length === 0) return ops;
  return [...ops, ...opsCajasDeGrupo(aplicarOps(escena, ops))];
}

export function esCampoDeTexto(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false;
  return ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName) || t.isContentEditable;
}
```

Nota: en jsdom `isContentEditable` no siempre refleja `contentEditable = "true"`. Si la prueba de `contenteditable` falla solo por eso, se cambia la comparación a `t.isContentEditable || t.getAttribute("contenteditable") === "true"`. La prueba no se cambia.

- [ ] **Step 4: verde**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test lib/__tests__/edicion.test.ts && pnpm exec tsc --noEmit && pnpm lint
```

Esperado: 18 passed; tsc y lint limpios.

- [ ] **Step 5: commit**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2
git add frontend/lib/edicion.ts frontend/lib/__tests__/edicion.test.ts
git commit -F - <<'EOF'
editor v2: operaciones de edición puras (mover, alinear, grupos, z, duplicar)

z es el orden global de hojas; reordenar mueve bloques de hermanos.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

## Task 5: store del editor (`stores/editor.ts`)

**Files:**
- Create: `frontend/stores/editor.ts`
- Create: `frontend/stores/__tests__/editor.test.ts`

**Interfaces:**

```ts
export type Paso = { etiqueta: string; adelante: Patch[]; atras: Patch[] };
export const LIMITE_HISTORIA = 200;
export type EstadoEditor = {
  // contrato del índice
  escena: Escena | null;
  seleccion: string[];
  sucio: boolean;
  cargar(escena: Escena): void;
  aplicar(ops: Op[], etiqueta?: string): void;      // un paso; lanza OpInvalida sin registrar nada
  agregarCapa(capa: Capa): void;                     // un paso; deja la capa seleccionada
  seleccionar(ids: string[]): void;
  deshacer(): void;
  rehacer(): void;
  // extensiones (D2, D8)
  pasado: Paso[];
  futuro: Paso[];
  revision: number;                                  // sube con cada cambio de la escena
  zoom: number;
  editandoTexto: string | null;
  portapapeles: Capa[];
  editarEscena(receta: (d: Draft<Escena>) => void, etiqueta?: string): void;
  cambiarFormato(formato: Formato): void;
  setZoom(zoom: number): void;
  editarTexto(id: string | null): void;
  copiar(): void;
  pegar(): void;
  duplicar(): void;
  borrar(): void;
  mover(dx: number, dy: number): void;
  agrupar(): void;
  desagrupar(): void;
  ordenarZ(modo: ModoZ): void;
  alinear(modo: ModoAlinear): void;
  distribuir(eje: "h" | "v"): void;
  marcarGuardado(revision: number): void;            // sucio = revision actual !== la guardada
  vaciar(): void;
};
export const useEditor: UseBoundStore<StoreApi<EstadoEditor>>;
```

- [ ] **Step 1: escribir la prueba que falla**

`frontend/stores/__tests__/editor.test.ts`:

```ts
import { beforeEach, describe, expect, it } from "vitest";
import datos from "@/lib/__fixtures__/ops-casos.json";
import { capaNueva, OpInvalida, type Escena } from "@/lib/escena";
import { LIMITE_HISTORIA, useEditor } from "../editor";

const base = datos.base as unknown as Escena;
const ed = () => useEditor.getState();
const capa = (id: string) => ed().escena!.capas.find((c) => c.id === id)!;

beforeEach(() => {
  useEditor.setState(useEditor.getInitialState(), true);
  ed().cargar(structuredClone(base));
});

describe("store del editor", () => {
  it("cargar deja la historia vacía y la escena limpia", () => {
    expect(ed().pasado).toEqual([]);
    expect(ed().futuro).toEqual([]);
    expect(ed().sucio).toBe(false);
    expect(ed().seleccion).toEqual([]);
  });

  it("aplicar es un paso", () => {
    ed().aplicar(
      [
        { op: "set", capa: "titulo", ruta: "x", valor: 100 },
        { op: "set", capa: "titulo", ruta: "y", valor: 200 },
      ],
      "Mover",
    );
    expect(ed().pasado).toHaveLength(1);
    expect(ed().pasado[0].etiqueta).toBe("Mover");
    expect(ed().sucio).toBe(true);
    ed().deshacer();
    expect(capa("titulo").x).toBe(80);
    expect(capa("titulo").y).toBe(196);
    expect(ed().futuro).toHaveLength(1);
    ed().rehacer();
    expect(capa("titulo").x).toBe(100);
    expect(capa("titulo").y).toBe(200);
  });

  it("la caja del grupo va en el mismo paso", () => {
    ed().aplicar([{ op: "set", capa: "logo", ruta: "y", valor: 1000 }]);
    expect(ed().pasado).toHaveLength(1);
    expect(capa("marca").y).toBe(1000);
    expect(capa("marca").h).toBe(350);
    ed().deshacer();
    expect(capa("marca").y).toBe(1200);
    expect(capa("marca").h).toBe(150);
    expect(capa("logo").y).toBe(1230);
  });

  it("una op inválida lanza y no registra nada", () => {
    expect(() => ed().aplicar([{ op: "del", capa: "nadie" }])).toThrow(OpInvalida);
    expect(ed().pasado).toEqual([]);
    expect(ed().sucio).toBe(false);
  });

  it("aplicar sin cambios no crea paso", () => {
    ed().aplicar([{ op: "set", capa: "titulo", ruta: "x", valor: 80 }]);
    ed().aplicar([]);
    expect(ed().pasado).toEqual([]);
  });

  it("cambiarFormato es un paso y se deshace", () => {
    ed().cambiarFormato("9x16");
    expect(ed().escena!.lienzo.h).toBe(1920);
    expect(ed().escena!.lienzo.formato).toBe("9x16");
    ed().cambiarFormato("9x16");
    expect(ed().pasado).toHaveLength(1);
    ed().deshacer();
    expect(ed().escena!.lienzo.h).toBe(1350);
    expect(ed().escena!.lienzo.formato).toBe("4x5");
  });

  it("una edición durante el guardado deja sucio", () => {
    ed().aplicar([{ op: "set", capa: "titulo", ruta: "x", valor: 1 }]);
    const enVuelo = ed().revision;
    ed().aplicar([{ op: "set", capa: "titulo", ruta: "x", valor: 2 }]);
    ed().marcarGuardado(enVuelo);
    expect(ed().sucio).toBe(true);
    ed().marcarGuardado(ed().revision);
    expect(ed().sucio).toBe(false);
  });

  it("la selección se filtra a capas existentes, sin repetir", () => {
    ed().seleccionar(["nadie", "caja", "caja", "titulo"]);
    expect(ed().seleccion).toEqual(["caja", "titulo"]);
    ed().aplicar([{ op: "del", capa: "titulo" }]);
    expect(ed().seleccion).toEqual(["caja"]);
  });

  it(`la historia se corta en ${LIMITE_HISTORIA} pasos`, () => {
    for (let i = 0; i < LIMITE_HISTORIA + 5; i++) {
      ed().aplicar([{ op: "set", capa: "titulo", ruta: "x", valor: i + 1000 }]);
    }
    expect(ed().pasado).toHaveLength(LIMITE_HISTORIA);
  });

  it("deshacer o rehacer sin historia no hace nada", () => {
    const antes = ed().escena;
    ed().deshacer();
    ed().rehacer();
    expect(ed().escena).toBe(antes);
    expect(ed().sucio).toBe(false);
  });

  it("agregarCapa es un paso y selecciona la capa", () => {
    const nueva = capaNueva("shape", ed().escena!, { fuente: "Inter" });
    ed().agregarCapa(nueva);
    expect(ed().seleccion).toEqual([nueva.id]);
    expect(capa(nueva.id).tipo).toBe("shape");
    expect(ed().pasado).toHaveLength(1);
  });

  it("copiar y pegar crea capas nuevas y las selecciona", () => {
    ed().seleccionar(["titulo"]);
    ed().copiar();
    ed().pegar();
    expect(ed().escena!.capas).toHaveLength(5);
    expect(ed().seleccion).toHaveLength(1);
    expect(ed().seleccion[0]).not.toBe("titulo");
    expect(ed().pasado).toHaveLength(1);
  });

  it("borrar respeta el candado", () => {
    ed().aplicar([{ op: "set", capa: "titulo", ruta: "bloqueada", valor: true }]);
    ed().seleccionar(["titulo", "marca"]);
    ed().borrar();
    expect(ed().escena!.capas.map((c) => c.id)).toEqual(["titulo"]);
    expect(ed().pasado).toHaveLength(2);
  });

  it("agrupar y desagrupar", () => {
    ed().seleccionar(["titulo", "marca"]);
    ed().agrupar();
    const grupo = ed().seleccion[0];
    expect(capa(grupo).tipo).toBe("group");
    ed().desagrupar();
    expect(ed().escena!.capas.some((c) => c.id === grupo)).toBe(false);
    expect([...ed().seleccion].sort()).toEqual(["marca", "titulo"]);
  });

  it("deshacer cierra la edición de texto", () => {
    ed().aplicar([{ op: "set", capa: "titulo", ruta: "texto", valor: "Adiós" }]);
    ed().editarTexto("titulo");
    ed().deshacer();
    expect(ed().editandoTexto).toBeNull();
  });
});
```

- [ ] **Step 2: correrla y ver que falla**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test stores/__tests__/editor.test.ts
```

Esperado: FAIL con `Failed to resolve import "../editor"`.

- [ ] **Step 3: implementar**

`frontend/stores/editor.ts`:

```ts
"use client";

import { applyPatches, enablePatches, produceWithPatches, type Draft, type Patch } from "immer";
import { create } from "zustand";
import {
  aplicarEnBorrador,
  descendientes,
  padreDe,
  reformatear,
  type Capa,
  type Escena,
  type Formato,
  type Op,
} from "@/lib/escena";
import {
  conCajasDeGrupo,
  opsAgrupar,
  opsAlinear,
  opsDesagrupar,
  opsDistribuir,
  opsDuplicar,
  opsMover,
  opsPegar,
  opsZ,
  type ModoAlinear,
  type ModoZ,
} from "@/lib/edicion";

enablePatches();

export type Paso = { etiqueta: string; adelante: Patch[]; atras: Patch[] };
export const LIMITE_HISTORIA = 200;

export type EstadoEditor = {
  escena: Escena | null;
  seleccion: string[];
  sucio: boolean;
  pasado: Paso[];
  futuro: Paso[];
  revision: number;
  zoom: number;
  editandoTexto: string | null;
  portapapeles: Capa[];
  cargar(escena: Escena): void;
  aplicar(ops: Op[], etiqueta?: string): void;
  agregarCapa(capa: Capa): void;
  seleccionar(ids: string[]): void;
  deshacer(): void;
  rehacer(): void;
  editarEscena(receta: (d: Draft<Escena>) => void, etiqueta?: string): void;
  cambiarFormato(formato: Formato): void;
  setZoom(zoom: number): void;
  editarTexto(id: string | null): void;
  copiar(): void;
  pegar(): void;
  duplicar(): void;
  borrar(): void;
  mover(dx: number, dy: number): void;
  agrupar(): void;
  desagrupar(): void;
  ordenarZ(modo: ModoZ): void;
  alinear(modo: ModoAlinear): void;
  distribuir(eje: "h" | "v"): void;
  marcarGuardado(revision: number): void;
  vaciar(): void;
};

type Receta = (d: Draft<Escena>) => void | Escena;

const existentes = (escena: Escena, ids: string[]) => {
  const hay = new Set(escena.capas.map((c) => c.id));
  return [...new Set(ids)].filter((id) => hay.has(id));
};

// Quita de la selección las capas que ya van dentro de un grupo seleccionado.
function raicesDeSeleccion(escena: Escena, ids: string[]): string[] {
  const sel = new Set(ids);
  return ids.filter((id) => {
    for (let p = padreDe(escena, id); p; p = padreDe(escena, p)) if (sel.has(p)) return false;
    return true;
  });
}

export const useEditor = create<EstadoEditor>()((set, get) => {
  // Un paso de deshacer = un juego de parches de immer. Toda acción que cambia
  // la escena pasa por aquí.
  function registrar(receta: Receta, etiqueta: string) {
    const { escena, pasado, revision, seleccion } = get();
    if (!escena) return;
    const [nueva, adelante, atras] = produceWithPatches(escena, receta);
    if (adelante.length === 0) return;
    set({
      escena: nueva,
      pasado: [...pasado, { etiqueta, adelante, atras }].slice(-LIMITE_HISTORIA),
      futuro: [],
      revision: revision + 1,
      sucio: true,
      seleccion: existentes(nueva, seleccion),
    });
  }

  function viajar(desde: "pasado" | "futuro") {
    const s = get();
    const pila = s[desde];
    const paso = pila.at(-1);
    if (!s.escena || !paso) return;
    const atras = desde === "pasado";
    const escena = applyPatches(s.escena, atras ? paso.atras : paso.adelante);
    set({
      escena,
      pasado: atras ? s.pasado.slice(0, -1) : [...s.pasado, paso],
      futuro: atras ? [...s.futuro, paso] : s.futuro.slice(0, -1),
      revision: s.revision + 1,
      sucio: true,
      seleccion: existentes(escena, s.seleccion),
      editandoTexto: null,
    });
  }

  return {
    escena: null,
    seleccion: [],
    sucio: false,
    pasado: [],
    futuro: [],
    revision: 0,
    zoom: 1,
    editandoTexto: null,
    portapapeles: [],

    cargar: (escena) =>
      set({ escena, seleccion: [], sucio: false, pasado: [], futuro: [], revision: 0, editandoTexto: null }),

    aplicar: (ops, etiqueta = "Editar") => {
      const { escena } = get();
      if (!escena || ops.length === 0) return;
      // conCajasDeGrupo corre aplicarOps: si una op es inválida lanza aquí,
      // antes de registrar nada.
      const todas = conCajasDeGrupo(escena, ops);
      registrar((d) => {
        for (const op of todas) aplicarEnBorrador(d, op);
      }, etiqueta);
    },

    agregarCapa: (capa) => {
      get().aplicar([{ op: "add", capa }], "Agregar capa");
      set({ seleccion: [capa.id] });
    },

    seleccionar: (ids) => {
      const { escena } = get();
      set({ seleccion: escena ? existentes(escena, ids) : [] });
    },

    deshacer: () => viajar("pasado"),
    rehacer: () => viajar("futuro"),

    editarEscena: (receta, etiqueta = "Editar lienzo") => registrar(receta, etiqueta),

    cambiarFormato: (formato) => {
      const { escena } = get();
      if (!escena || escena.lienzo.formato === formato) return;
      registrar(() => reformatear(escena, formato), "Cambiar formato");
    },

    setZoom: (zoom) => set({ zoom: Math.min(4, Math.max(0.1, zoom)) }),
    editarTexto: (id) => set({ editandoTexto: id }),

    copiar: () => {
      const { escena, seleccion } = get();
      if (!escena || seleccion.length === 0) return;
      const ids = new Set(raicesDeSeleccion(escena, seleccion).flatMap((id) => [id, ...descendientes(escena, id)]));
      set({ portapapeles: structuredClone(escena.capas.filter((c) => ids.has(c.id))) });
    },

    pegar: () => {
      const { escena, portapapeles } = get();
      if (!escena || portapapeles.length === 0) return;
      const { ops, nuevos } = opsPegar(escena, portapapeles);
      get().aplicar(ops, "Pegar");
      set({ seleccion: nuevos });
    },

    duplicar: () => {
      const { escena, seleccion } = get();
      if (!escena || seleccion.length === 0) return;
      const { ops, nuevos } = opsDuplicar(escena, raicesDeSeleccion(escena, seleccion));
      get().aplicar(ops, "Duplicar");
      set({ seleccion: nuevos });
    },

    borrar: () => {
      const { escena, seleccion } = get();
      if (!escena) return;
      const porId = new Map(escena.capas.map((c) => [c.id, c]));
      const ops: Op[] = raicesDeSeleccion(escena, seleccion)
        .filter((id) => !porId.get(id)?.bloqueada)
        .map((id) => ({ op: "del", capa: id }));
      get().aplicar(ops, "Borrar");
    },

    mover: (dx, dy) => {
      const { escena, seleccion } = get();
      if (!escena || (dx === 0 && dy === 0)) return;
      get().aplicar(opsMover(escena, seleccion, dx, dy), "Mover");
    },

    agrupar: () => {
      const { escena, seleccion } = get();
      if (!escena) return;
      const r = opsAgrupar(escena, raicesDeSeleccion(escena, seleccion));
      if (!r) return;
      get().aplicar(r.ops, "Agrupar");
      set({ seleccion: [r.id] });
    },

    desagrupar: () => {
      const { escena, seleccion } = get();
      if (!escena || seleccion.length !== 1) return;
      const r = opsDesagrupar(escena, seleccion[0]);
      if (!r) return;
      get().aplicar(r.ops, "Desagrupar");
      set({ seleccion: r.hijos });
    },

    ordenarZ: (modo) => {
      const { escena, seleccion } = get();
      if (escena) get().aplicar(opsZ(escena, seleccion, modo), "Orden");
    },

    alinear: (modo) => {
      const { escena, seleccion } = get();
      if (escena) get().aplicar(opsAlinear(escena, seleccion, modo), "Alinear");
    },

    distribuir: (eje) => {
      const { escena, seleccion } = get();
      if (escena) get().aplicar(opsDistribuir(escena, seleccion, eje), "Distribuir");
    },

    marcarGuardado: (revision) => set({ sucio: get().revision !== revision }),

    vaciar: () => set(useEditor.getInitialState(), true),
  };
});
```

Notas:
- La prueba «borrar respeta el candado» espera 2 pasos: el `set bloqueada` y el `del marca`. `titulo` queda porque tiene candado.
- `agregarCapa` y `pegar` llaman `aplicar` y luego ponen la selección. La selección no entra en la historia, así que siguen siendo un solo paso.
- `opsAgrupar` en la prueba «agrupar y desagrupar» recibe `["titulo", "marca"]`; tras desagrupar, `seleccion` son esos dos hijos. Si `opsDesagrupar` los devuelve en otro orden, la prueba ordena antes de comparar.

- [ ] **Step 4: verde**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test stores/__tests__/editor.test.ts && pnpm test && pnpm exec tsc --noEmit && pnpm lint
```

Esperado: `15 passed` en el archivo; la suite completa en verde; tsc y lint limpios.

- [ ] **Step 5: commit**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2
git add frontend/stores/editor.ts frontend/stores/__tests__/editor.test.ts
git commit -F - <<'EOF'
editor v2: store zustand con deshacer por parches de immer

Cada acción es un paso; la caja de los grupos se recalcula en el mismo paso.
Historia de 200 pasos, selección filtrada a capas existentes, marcarGuardado
por revisión para que una edición en vuelo deje el diseño sucio.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

## Task 6: render de capas v2 (`capa-vista.tsx`)

**Files:**
- Move: `frontend/app/b/[slug]/templates/[id]/_components/capa-vista.tsx` → `_components/v1/capa-vista.tsx`
- Move: `frontend/app/b/[slug]/templates/[id]/_components/lienzo.tsx` → `_components/v1/lienzo.tsx`
- Modify: `frontend/app/b/[slug]/templates/[id]/page.tsx`: solo la ruta del import de `Lienzo`.
- Create: `frontend/app/b/[slug]/templates/[id]/_components/capa-vista.tsx` (v2)
- Create: `frontend/app/b/[slug]/templates/[id]/_components/__tests__/capa-vista.test.tsx`

Por qué se mueven los v1: el `page.tsx` actual importa el `Lienzo` v1, y el v1 importa `CapaVista` con otras props. Así tsc sigue limpio entre el Task 6 y el Task 12. El Task 12 borra la carpeta `v1/`.

**Interfaces:**

```ts
export function radioDeMascara(mascara: string): string | undefined;   // "none" → undefined, "circle" → "50%", "rounded:N" → "Npx"
export function fondoCss(fondo: Fondo, tokens: Tokens, colorMarca: string, slug: string): string;
export function EstilosFuentes(props: { slug: string; familias: string[] }): JSX.Element | null;
export function CapaVista(props: { capa: Capa; tokens: Tokens; slug: string; colorMarca: string; editando?: boolean }): JSX.Element | null;
export function Escenario(props: { escena: Escena; slug: string; colorMarca: string; editandoTexto?: string | null }): JSX.Element;
```

- Cada capa pintada es un `div.capa[data-id]` con posición absoluta en px del lienzo. `Lienzo` (Task 7) y Selecto/Moveable la encuentran por `data-id`.
- Los grupos no pintan nada; las capas ocultas, ni las que viven dentro de un grupo oculto, tampoco.
- `recorte` de imagen **no** se pinta en este plan. Se guarda y el render del plan 1 lo respeta; el editor muestra la imagen completa con `object-fit`. ⚠️ Diferencia WYSIWYG conocida.

- [ ] **Step 1: mover el editor v1**

```bash
cd "/Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend/app/b/[slug]/templates/[id]"
mkdir -p _components/v1
git mv _components/capa-vista.tsx _components/v1/capa-vista.tsx
git mv _components/lienzo.tsx _components/v1/lienzo.tsx
sed -i '' 's#"./_components/lienzo"#"./_components/v1/lienzo"#' page.tsx
grep -n '_components' page.tsx
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend && pnpm exec tsc --noEmit
```

Esperado: el grep muestra `import { Lienzo } from "./_components/v1/lienzo";` y tsc queda limpio. `v1/lienzo.tsx` importa `./capa-vista`, que sigue a su lado.

- [ ] **Step 2: escribir la prueba que falla**

`frontend/app/b/[slug]/templates/[id]/_components/__tests__/capa-vista.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import datos from "@/lib/__fixtures__/ops-casos.json";
import { aplicarOps, type Capa, type Escena, type Op } from "@/lib/escena";
import { Escenario, fondoCss, radioDeMascara } from "../capa-vista";

const base = datos.base as unknown as Escena;
const con = (ops: Op[]) => aplicarOps(base, ops);
const pintar = (escena: Escena) =>
  render(<Escenario escena={escena} slug="gdlscene" colorMarca="#e11d48" />).container;

describe("Escenario", () => {
  it("pinta los tramos de color del texto", () => {
    pintar(con([{ op: "set", capa: "titulo", ruta: "estilo.spans", valor: [{ desde: 0, hasta: 4, color: "#ff0000" }] }]));
    expect(screen.getByText("Hola").style.color).toBe("rgb(255, 0, 0)");
    expect(screen.getByText("mundo", { exact: false }).style.color).toBe("");
  });

  it("no pinta una capa oculta", () => {
    const c = pintar(con([{ op: "set", capa: "titulo", ruta: "oculta", valor: true }]));
    expect(c.querySelector('[data-id="titulo"]')).toBeNull();
    expect(c.querySelector('[data-id="caja"]')).not.toBeNull();
  });

  it("un grupo oculto esconde a sus hijos", () => {
    const c = pintar(con([{ op: "set", capa: "marca", ruta: "oculta", valor: true }]));
    expect(c.querySelector('[data-id="caja"]')).toBeNull();
    expect(c.querySelector('[data-id="logo"]')).toBeNull();
  });

  it("un grupo no pinta nada propio", () => {
    const c = pintar(base);
    expect(c.querySelector('[data-id="marca"]')).toBeNull();
    expect(c.querySelectorAll(".capa")).toHaveLength(3);
  });

  it("una imagen sin src muestra su campo", () => {
    const foto: Capa = {
      id: "foto", nombre: "Foto", tipo: "image", x: 0, y: 0, w: 500, h: 500, rot: 0, opacity: 1, z: 5,
      bloqueada: false, oculta: false, anclaje: "center", src: null, campo: "foto", ajuste: "cover",
      mascara: "none", estilo: {},
    };
    pintar(con([{ op: "add", capa: foto }]));
    expect(screen.getByText("Campo: foto")).toBeTruthy();
  });

  it("elipse redonda y token:marca resuelto", () => {
    const c = pintar(con([{ op: "set", capa: "caja", ruta: "forma", valor: "ellipse" }]));
    const relleno = c.querySelector<HTMLElement>('[data-id="caja"] > div')!;
    expect(relleno.style.borderRadius).toBe("50%");
    expect(relleno.style.backgroundColor).toBe("rgb(225, 29, 72)");
  });
});

describe("helpers de estilo", () => {
  it("fondoCss y radioDeMascara", () => {
    const t = { colores: { tinta: "#111111" } };
    expect(fondoCss({ tipo: "color", valor: "token:tinta" }, t, "#e11d48", "x")).toBe("#111111");
    expect(fondoCss({ tipo: "gradiente", valor: "linear-gradient(#fff, #000)" }, t, "#e11d48", "x")).toBe(
      "linear-gradient(#fff, #000)",
    );
    expect(fondoCss({ tipo: "imagen", valor: "assets/fondo 1.jpg" }, t, "#e11d48", "gdl")).toBe(
      "url('/api/brands/gdl/files/assets/fondo%201.jpg') center/cover no-repeat",
    );
    expect(radioDeMascara("none")).toBeUndefined();
    expect(radioDeMascara("circle")).toBe("50%");
    expect(radioDeMascara("rounded:24")).toBe("24px");
  });
});
```

- [ ] **Step 3: correrla y ver que falla**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test "app/b/\[slug\]/templates/\[id\]/_components/__tests__/capa-vista.test.tsx"
```

Esperado: FAIL con `Failed to resolve import "../capa-vista"`.

- [ ] **Step 4: implementar**

`frontend/app/b/[slug]/templates/[id]/_components/capa-vista.tsx`:

```tsx
"use client";

import type { CSSProperties } from "react";
import { ImageIcon } from "lucide-react";
import {
  ocultasEfectivas,
  ordenadas,
  resolverColor,
  urlDeAsset,
  type Capa,
  type Escena,
  type Fondo,
  type Tokens,
} from "@/lib/escena";
import { trozos } from "@/lib/spans";

const VERTICAL: Record<string, CSSProperties["justifyContent"]> = {
  top: "flex-start",
  center: "center",
  bottom: "flex-end",
};

export function radioDeMascara(mascara: string): string | undefined {
  if (mascara === "circle") return "50%";
  const m = /^rounded:(\d+)$/.exec(mascara);
  return m ? `${m[1]}px` : undefined;
}

// Mismo criterio que _fondo_css del plan 1: el gradiente va tal cual y la
// imagen cubre el lienzo.
export function fondoCss(fondo: Fondo, tokens: Tokens, colorMarca: string, slug: string): string {
  if (fondo.tipo === "gradiente") return fondo.valor;
  if (fondo.tipo === "imagen") return `url('${urlDeAsset(slug, fondo.valor)}') center/cover no-repeat`;
  return resolverColor(fondo.valor, tokens, colorMarca);
}

// Las fuentes de la marca se sirven desde el backend; se declaran solo las
// que usa la escena.
export function EstilosFuentes({ slug, familias }: { slug: string; familias: string[] }) {
  if (familias.length === 0) return null;
  const css = familias
    .map(
      (f) =>
        `@font-face{font-family:'${f.replace(/'/g, "")}';src:url('/api/brands/${slug}/files/fonts/${encodeURIComponent(f)}');font-display:swap;}`,
    )
    .join("\n");
  return <style>{css}</style>;
}

type Props = { capa: Capa; tokens: Tokens; slug: string; colorMarca: string; editando?: boolean };

export function CapaVista({ capa, tokens, slug, colorMarca, editando = false }: Props) {
  if (capa.tipo === "group") return null;
  const color = (v: string) => resolverColor(v, tokens, colorMarca);
  const caja: CSSProperties = {
    position: "absolute",
    left: capa.x,
    top: capa.y,
    width: capa.w,
    height: capa.h,
    transform: `rotate(${capa.rot}deg)`,
    opacity: capa.opacity,
    zIndex: capa.z,
  };

  if (capa.tipo === "text") {
    const e = capa.estilo;
    return (
      <div
        data-id={capa.id}
        className="capa"
        style={{
          ...caja,
          display: "flex",
          flexDirection: "column",
          justifyContent: VERTICAL[e.verticalAlign ?? "top"],
          // Mientras se edita, el textarea (Task 8) ocupa su lugar.
          visibility: editando ? "hidden" : undefined,
        }}
      >
        <div
          style={{
            fontFamily: `'${e.fontFamily}', sans-serif`,
            fontWeight: e.fontWeight,
            fontSize: e.fontSize,
            lineHeight: e.lineHeight,
            letterSpacing: e.letterSpacing,
            color: color(e.color),
            textAlign: e.textAlign,
            textWrap: e.textWrap as CSSProperties["textWrap"],
            textTransform: e.textTransform,
            whiteSpace: "pre-wrap",
            overflowWrap: "break-word",
          }}
        >
          {trozos(capa.texto, e.spans).map((t, i) => (
            <span key={i} style={t.color ? { color: color(t.color) } : undefined}>
              {t.texto}
            </span>
          ))}
        </div>
      </div>
    );
  }

  if (capa.tipo === "shape") {
    const e = capa.estilo;
    const borde = e.borderWidth ?? 0;
    return (
      <div data-id={capa.id} className="capa" style={caja}>
        <div
          style={{
            width: "100%",
            height: "100%",
            boxSizing: "border-box",
            backgroundColor: color(e.fill),
            borderRadius: capa.forma === "ellipse" ? "50%" : (e.radius ?? 0),
            border: borde > 0 ? `${borde}px solid ${color(e.borderColor ?? "#000000")}` : undefined,
            filter: e.filter,
            mixBlendMode: e.mixBlendMode as CSSProperties["mixBlendMode"],
          }}
        />
      </div>
    );
  }

  if (capa.tipo === "svg") {
    return (
      <div data-id={capa.id} className="capa" style={caja}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={urlDeAsset(slug, capa.src)}
          alt=""
          draggable={false}
          style={{
            width: "100%",
            height: "100%",
            objectFit: capa.ajuste,
            filter: capa.estilo.filter,
            mixBlendMode: capa.estilo.mixBlendMode as CSSProperties["mixBlendMode"],
            pointerEvents: "none",
          }}
        />
      </div>
    );
  }

  // image y video
  const medio: CSSProperties = {
    width: "100%",
    height: "100%",
    objectFit: capa.ajuste,
    objectPosition: capa.estilo.objectPosition,
    filter: capa.estilo.filter,
    mixBlendMode: capa.estilo.mixBlendMode as CSSProperties["mixBlendMode"],
    borderRadius: radioDeMascara(capa.mascara),
    pointerEvents: "none",
  };
  if (!capa.src) {
    return (
      <div data-id={capa.id} className="capa" style={caja}>
        <div
          className="flex flex-col items-center justify-center gap-2 bg-muted text-muted-foreground"
          style={{ ...medio, fontSize: Math.max(18, Math.min(capa.w, capa.h) / 12) }}
        >
          <ImageIcon style={{ width: "20%", height: "20%" }} />
          <span>Campo: {capa.campo ?? "imagen"}</span>
        </div>
      </div>
    );
  }
  if (capa.tipo === "video") {
    return (
      <div data-id={capa.id} className="capa" style={caja}>
        <video
          src={urlDeAsset(slug, capa.src)}
          poster={capa.poster ? urlDeAsset(slug, capa.poster) : undefined}
          muted
          playsInline
          style={medio}
        />
      </div>
    );
  }
  return (
    <div data-id={capa.id} className="capa" style={caja}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={urlDeAsset(slug, capa.src)} alt="" draggable={false} style={medio} />
    </div>
  );
}

type PropsEscenario = { escena: Escena; slug: string; colorMarca: string; editandoTexto?: string | null };

// Las capas en orden de pintado. El fondo lo pone quien contiene al escenario.
export function Escenario({ escena, slug, colorMarca, editandoTexto = null }: PropsEscenario) {
  const ocultas = ocultasEfectivas(escena);
  const visibles = ordenadas(escena).filter((c) => c.tipo !== "group" && !ocultas.has(c.id));
  const familias = [...new Set(visibles.flatMap((c) => (c.tipo === "text" ? [c.estilo.fontFamily] : [])))];
  return (
    <>
      <EstilosFuentes slug={slug} familias={familias} />
      {visibles.map((c) => (
        <CapaVista
          key={c.id}
          capa={c}
          tokens={escena.tokens}
          slug={slug}
          colorMarca={colorMarca}
          editando={c.id === editandoTexto}
        />
      ))}
    </>
  );
}
```

- [ ] **Step 5: verde**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test "app/b/\[slug\]/templates/\[id\]/_components/__tests__/capa-vista.test.tsx" && pnpm test && pnpm exec tsc --noEmit && pnpm lint
```

Esperado:
- `7 passed` en el archivo; la suite completa en verde; tsc y lint limpios.
- Si `@next/next/no-img-element` no está activa en la config de lint, quitar los dos comentarios `eslint-disable-next-line` para que lint no reporte «unused eslint-disable».

- [ ] **Step 6: commit**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2
git add "frontend/app/b/[slug]/templates/[id]"
git commit -F - <<'EOF'
editor v2: render de capas v2 (texto con tramos, imagen, video, forma, svg)

El editor v1 se mueve a _components/v1 para que el page actual siga
compilando; se borra al montar el editor nuevo. Los grupos no pintan y las
capas ocultas, ni las de grupos ocultos, tampoco. El recorte de imagen no se
pinta todavía.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

## Task 7: lienzo con Moveable y Selecto (`lienzo.tsx`, `lib/vista.ts`)

**Files:**
- Create: `frontend/lib/vista.ts`
- Create: `frontend/lib/__tests__/vista.test.ts`
- Create: `frontend/app/b/[slug]/templates/[id]/_components/lienzo.tsx` (v2; el v1 ya vive en `_components/v1/`)
- Create: `frontend/app/dev/editor/page.tsx`
- Create: `frontend/app/dev/editor/banco.tsx`
- Create: `frontend/e2e/lienzo.spec.ts`

**Interfaces:**

```ts
// lib/vista.ts
export type Vista = { zoom: number; x: number; y: number };   // x, y: desplazamiento del escenario dentro del marco, en px de pantalla
export const ZOOM_MIN = 0.1;
export const ZOOM_MAX = 4;
export function limitarZoom(z: number): number;
export function encuadre(marco: { w: number; h: number }, lienzo: { w: number; h: number }, margen?: number): Vista;
export function zoomEnPunto(v: Vista, nuevo: number, px: number, py: number): Vista;  // el punto (px, py) del marco no se mueve
export function raicesSeleccionables(escena: Escena, ids: string[]): string[];       // hojas → raíz; fuera las bloqueadas
export function alternar(actual: string[], ids: string[]): string[];                 // shift-clic: quita las que ya estaban, agrega las nuevas

// _components/lienzo.tsx
export function Lienzo(props: { slug: string; colorMarca: string; ajustarAlCargar?: boolean }): JSX.Element | null;
```

- `Lienzo` lee todo del store (`escena`, `seleccion`, `zoom`, `editandoTexto`) y escribe solo con acciones del store. El desplazamiento (pan) es estado local.
- Cada gesto de Moveable termina en **un** paso: al soltar se restaura el DOM desde el store (`left`, `top`, `width`, `height`, `transform`) y luego se llama `mover` o `aplicar`. Sin esa restauración, React no reescribe `transform` (su prop no cambió) y la caja queda desplazada el doble (Review Focus 5).
- Arrastrar vale para cualquier selección. Redimensionar y rotar, solo si la selección es una hoja (D5).
- Moveable no recibe capas bloqueadas ni ocultas. Mientras se edita un texto, no recibe nada.
- `snappable` sale de `escena.guias?.iman ?? true`. ⚠️ El imán bajo `scale()` no tiene e2e; la del banco lo apaga.

- [ ] **Step 1: escribir la prueba que falla de `vista.ts`**

`frontend/lib/__tests__/vista.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import datos from "@/lib/__fixtures__/ops-casos.json";
import type { Escena } from "@/lib/escena";
import { alternar, encuadre, raicesSeleccionables, zoomEnPunto } from "../vista";

const base = datos.base as unknown as Escena;

describe("vista", () => {
  it("encuadre centra el lienzo con margen", () => {
    const v = encuadre({ w: 600, h: 800 }, { w: 1080, h: 1350 });
    expect(v.zoom).toBeCloseTo(536 / 1080, 4);
    expect(v.x).toBe(32);
    expect(v.y).toBe(65);
  });

  it("zoomEnPunto deja quieto el punto del cursor", () => {
    const v = zoomEnPunto({ zoom: 0.5, x: 0, y: 0 }, 1, 100, 100);
    expect(v).toEqual({ zoom: 1, x: -100, y: -100 });
  });

  it("zoomEnPunto respeta los límites", () => {
    expect(zoomEnPunto({ zoom: 1, x: 0, y: 0 }, 10, 0, 0).zoom).toBe(4);
    expect(zoomEnPunto({ zoom: 1, x: 0, y: 0 }, 0.01, 0, 0).zoom).toBe(0.1);
  });

  it("raicesSeleccionables sube a la raíz y quita las bloqueadas", () => {
    const e = structuredClone(base);
    e.capas.find((c) => c.id === "titulo")!.bloqueada = true;
    expect(raicesSeleccionables(e, ["caja", "logo", "titulo"])).toEqual(["marca"]);
  });

  it("alternar quita las repetidas y agrega las nuevas", () => {
    expect(alternar(["a", "b"], ["b", "c"])).toEqual(["a", "c"]);
  });
});
```

- [ ] **Step 2: correrla y ver que falla**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test lib/__tests__/vista.test.ts
```

Esperado: FAIL con `Failed to resolve import "../vista"`.

- [ ] **Step 3: implementar `lib/vista.ts`**

`frontend/lib/vista.ts`:

```ts
import { raizDe, type Escena } from "./escena";

export type Vista = { zoom: number; x: number; y: number };

export const ZOOM_MIN = 0.1;
export const ZOOM_MAX = 4;

export function limitarZoom(z: number): number {
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z));
}

// El zoom que hace caber el lienzo completo, centrado y con margen.
export function encuadre(marco: { w: number; h: number }, lienzo: { w: number; h: number }, margen = 32): Vista {
  const zoom = limitarZoom(Math.min((marco.w - 2 * margen) / lienzo.w, (marco.h - 2 * margen) / lienzo.h));
  return {
    zoom,
    x: Math.round((marco.w - lienzo.w * zoom) / 2),
    y: Math.round((marco.h - lienzo.h * zoom) / 2),
  };
}

export function zoomEnPunto(v: Vista, nuevo: number, px: number, py: number): Vista {
  const zoom = limitarZoom(nuevo);
  return {
    zoom,
    x: px - ((px - v.x) / v.zoom) * zoom,
    y: py - ((py - v.y) / v.zoom) * zoom,
  };
}

// Lo que Selecto toca son hojas; lo que se selecciona es su raíz.
export function raicesSeleccionables(escena: Escena, ids: string[]): string[] {
  const m = new Map(escena.capas.map((c) => [c.id, c]));
  const fuera: string[] = [];
  for (const id of ids) {
    if (!m.has(id) || m.get(id)!.bloqueada) continue;
    const r = raizDe(escena, id);
    if (m.get(r)?.bloqueada || fuera.includes(r)) continue;
    fuera.push(r);
  }
  return fuera;
}

export function alternar(actual: string[], ids: string[]): string[] {
  return [...actual.filter((id) => !ids.includes(id)), ...ids.filter((id) => !actual.includes(id))];
}
```

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test lib/__tests__/vista.test.ts
```

Esperado: `5 passed`.

- [ ] **Step 4: escribir la e2e que falla**

`frontend/e2e/lienzo.spec.ts`:

```ts
import { expect, test, type Page } from "@playwright/test";
import { cookieFalsa } from "./sesion";

type CapaEstado = { id: string; x: number; y: number; w: number; h: number; rot: number; texto?: string };
type Estado = { sel: string[]; pasado: number; editando: string | null; capas: CapaEstado[] };

async function estado(page: Page): Promise<Estado> {
  return JSON.parse(await page.getByTestId("estado").innerText());
}
const capa = async (page: Page, id: string) => (await estado(page)).capas.find((c) => c.id === id)!;

async function arrastrar(page: Page, x: number, y: number, dx: number, dy: number) {
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + dx / 2, y + dy / 2, { steps: 5 });
  await page.mouse.move(x + dx, y + dy, { steps: 5 });
  await page.mouse.up();
}

test.beforeEach(async ({ context, page }) => {
  await cookieFalsa(context);
  const errores: string[] = [];
  page.on("pageerror", (e) => errores.push(e.message));
  await page.goto("/dev/editor");
  await expect(page.locator('#marco .capa[data-id="titulo"]')).toBeVisible();
});

test("arrastrar es un paso y deshacer regresa", async ({ page }) => {
  const titulo = page.locator('#marco .capa[data-id="titulo"]');
  await titulo.click();
  await expect.poll(async () => (await estado(page)).sel).toEqual(["titulo"]);
  const antes = (await titulo.boundingBox())!;
  await arrastrar(page, antes.x + antes.width / 2, antes.y + antes.height / 2, 100, 0);

  // Zoom 0.5: 100 px de pantalla son 200 px del lienzo.
  await expect.poll(async () => (await capa(page, "titulo")).x).toBeGreaterThan(270);
  const t = await capa(page, "titulo");
  expect(t.x).toBeLessThan(290);
  expect((await estado(page)).pasado).toBe(1);

  // Sin restaurar el DOM, la caja quedaría 200 px a la derecha y no 100.
  const despues = (await titulo.boundingBox())!;
  expect(despues.x - antes.x).toBeGreaterThan(95);
  expect(despues.x - antes.x).toBeLessThan(105);

  await page.getByRole("button", { name: "Deshacer" }).click();
  await expect.poll(async () => (await capa(page, "titulo")).x).toBe(80);
});

test("el lazo selecciona la raíz del grupo", async ({ page }) => {
  const marco = (await page.locator("#marco").boundingBox())!;
  // Pantalla y 600–720 son lienzo y 1136–1376: toca caja y logo, no el título.
  await arrastrar(page, marco.x + 5, marco.y + 600, 695, 120);
  await expect.poll(async () => (await estado(page)).sel).toEqual(["marca"]);
});

test("arrastrar un hijo mueve el grupo completo en un paso", async ({ page }) => {
  const caja = page.locator('#marco .capa[data-id="caja"]');
  const b = (await caja.boundingBox())!;
  // El centro de caja (x 540) no cae sobre logo (x 900–1020).
  await page.mouse.click(b.x + b.width / 2, b.y + b.height / 2);
  await expect.poll(async () => (await estado(page)).sel).toEqual(["marca"]);
  await arrastrar(page, b.x + b.width / 2, b.y + b.height / 2, 0, -100);

  await expect.poll(async () => (await capa(page, "caja")).y).toBeLessThan(1010);
  expect((await capa(page, "caja")).y).toBeGreaterThan(990);
  const e = await estado(page);
  const logo = e.capas.find((c) => c.id === "logo")!;
  const marca = e.capas.find((c) => c.id === "marca")!;
  expect(logo.y).toBeGreaterThan(1020);
  expect(logo.y).toBeLessThan(1040);
  expect(marca.y).toBe((await capa(page, "caja")).y);
  expect(e.pasado).toBe(1);
});

test("redimensionar una capa desde la esquina", async ({ page }) => {
  await page.locator('#marco .capa[data-id="titulo"]').click();
  const manija = page.locator(".moveable-control.moveable-se");
  await expect(manija).toBeVisible();
  const m = (await manija.boundingBox())!;
  await arrastrar(page, m.x + m.width / 2, m.y + m.height / 2, 50, 50);

  await expect.poll(async () => (await capa(page, "titulo")).w).toBeGreaterThan(1010);
  const t = await capa(page, "titulo");
  expect(t.w).toBeLessThan(1030);
  expect(t.h).toBeGreaterThan(390);
  expect(t.h).toBeLessThan(410);
  expect((await estado(page)).pasado).toBe(1);
});
```

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm e2e e2e/lienzo.spec.ts
```

Esperado: FAIL, 4 pruebas, por 404 en `/dev/editor` (no aparece `#marco .capa[data-id="titulo"]`).

- [ ] **Step 5: implementar `lienzo.tsx`**

`frontend/app/b/[slug]/templates/[id]/_components/lienzo.tsx`:

```tsx
"use client";

import { Maximize, ZoomIn, ZoomOut } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Moveable from "react-moveable";
import Selecto from "react-selecto";
import { Button } from "@/components/ui/button";
import { expandir } from "@/lib/edicion";
import { normalizarAngulo, ocultasEfectivas, type Escena, type Op } from "@/lib/escena";
import { alternar, encuadre, raicesSeleccionables, zoomEnPunto } from "@/lib/vista";
import { useEditor } from "@/stores/editor";
import { Escenario, fondoCss } from "./capa-vista";

type Props = { slug: string; colorMarca: string; ajustarAlCargar?: boolean };
type Gesto = { t?: number[]; w?: number; h?: number; rot?: number };
type Pan = { x: number; y: number };

const PAN_INICIAL: Pan = { x: 32, y: 32 };
const selector = (id: string) => `#marco .capa[data-id="${id}"]`;

// Moveable escribe directo en el DOM. Al soltar se regresa el nodo a lo que
// dice el store; el commit siguiente pinta la posición nueva.
function restaurar(escena: Escena, el: HTMLElement | SVGElement) {
  const c = escena.capas.find((x) => x.id === el.getAttribute("data-id"));
  if (!c) return;
  el.style.left = `${c.x}px`;
  el.style.top = `${c.y}px`;
  el.style.width = `${c.w}px`;
  el.style.height = `${c.h}px`;
  el.style.transform = `rotate(${c.rot}deg)`;
}

export function Lienzo({ slug, colorMarca, ajustarAlCargar = true }: Props) {
  const escena = useEditor((s) => s.escena);
  const seleccion = useEditor((s) => s.seleccion);
  const zoom = useEditor((s) => s.zoom);
  const editandoTexto = useEditor((s) => s.editandoTexto);

  const [marco, setMarco] = useState<HTMLDivElement | null>(null);
  const [pan, setPan] = useState<Pan>(PAN_INICIAL);
  const panRef = useRef<Pan>(PAN_INICIAL);
  const moveableRef = useRef<Moveable>(null);
  const gesto = useRef<Gesto | null>(null);

  const fijarPan = useCallback((p: Pan) => {
    panRef.current = p;
    setPan(p);
  }, []);

  const ajustar = useCallback(() => {
    const st = useEditor.getState();
    if (!marco || !st.escena) return;
    const r = marco.getBoundingClientRect();
    const v = encuadre({ w: r.width, h: r.height }, st.escena.lienzo);
    st.setZoom(v.zoom);
    fijarPan({ x: v.x, y: v.y });
  }, [marco, fijarPan]);

  // Ajusta al montar, al cambiar de formato y al cambiar el tamaño del marco.
  // El setState ocurre en el callback del observer, no en el cuerpo del efecto.
  const claveLienzo = escena ? `${escena.lienzo.w}x${escena.lienzo.h}` : null;
  useEffect(() => {
    if (!ajustarAlCargar || !marco || !claveLienzo) return;
    const ro = new ResizeObserver(() => ajustar());
    ro.observe(marco);
    return () => ro.disconnect();
  }, [ajustarAlCargar, marco, claveLienzo, ajustar]);

  // Rueda: con ctrl/cmd (o pellizco del trackpad) hace zoom en el cursor; sin, desplaza.
  useEffect(() => {
    if (!marco) return;
    const rueda = (ev: WheelEvent) => {
      ev.preventDefault();
      const st = useEditor.getState();
      if (ev.ctrlKey || ev.metaKey) {
        const r = marco.getBoundingClientRect();
        const v = zoomEnPunto(
          { zoom: st.zoom, ...panRef.current },
          st.zoom * Math.exp(-ev.deltaY / 300),
          ev.clientX - r.left,
          ev.clientY - r.top,
        );
        st.setZoom(v.zoom);
        fijarPan({ x: v.x, y: v.y });
      } else {
        fijarPan({ x: panRef.current.x - ev.deltaX, y: panRef.current.y - ev.deltaY });
      }
    };
    marco.addEventListener("wheel", rueda, { passive: false });
    return () => marco.removeEventListener("wheel", rueda);
  }, [marco, fijarPan]);

  const objetivos = useMemo(() => {
    if (!escena || editandoTexto) return [];
    const ocultas = ocultasEfectivas(escena);
    const m = new Map(escena.capas.map((c) => [c.id, c]));
    return expandir(escena, seleccion).filter((id) => !ocultas.has(id) && !m.get(id)?.bloqueada);
  }, [escena, seleccion, editandoTexto]);
  const unaHoja = objetivos.length === 1 && seleccion.length === 1 && seleccion[0] === objetivos[0];

  // La caja de Moveable se recalcula cuando cambia lo que hay debajo.
  useEffect(() => {
    moveableRef.current?.updateRect();
  }, [escena, zoom, pan]);

  const terminar = (targets: (HTMLElement | SVGElement)[]): Gesto | null => {
    const g = gesto.current;
    gesto.current = null;
    const e = useEditor.getState().escena;
    if (e) targets.forEach((el) => restaurar(e, el));
    return g;
  };

  const confirmarMovimiento = (g: Gesto | null) => {
    if (g?.t) useEditor.getState().mover(Math.round(g.t[0]), Math.round(g.t[1]));
  };

  if (!escena) return null;
  const { w: W, h: H } = escena.lienzo;

  return (
    <div className="relative h-full w-full">
      <div
        id="marco"
        ref={setMarco}
        className="relative h-full w-full overflow-hidden bg-muted"
        onDoubleClick={(ev) => {
          const el = (ev.target as Element).closest("#marco .capa");
          const id = el?.getAttribute("data-id");
          const c = escena.capas.find((x) => x.id === id);
          if (c?.tipo === "text" && !c.bloqueada) useEditor.getState().editarTexto(c.id);
        }}
      >
        <div
          data-testid="escenario"
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            width: W,
            height: H,
            overflow: "hidden",
            background: fondoCss(escena.lienzo.fondo, escena.tokens, colorMarca, slug),
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
            transformOrigin: "0 0",
          }}
        >
          <Escenario escena={escena} slug={slug} colorMarca={colorMarca} editandoTexto={editandoTexto} />
        </div>

        <Moveable
          ref={moveableRef}
          target={objetivos.map(selector)}
          draggable
          resizable={unaHoja}
          rotatable={unaHoja}
          keepRatio={false}
          snappable={escena.guias?.iman ?? true}
          snapThreshold={6}
          elementGuidelines={escena.capas.filter((c) => !objetivos.includes(c.id)).map((c) => selector(c.id))}
          onDragStart={() => {
            gesto.current = null;
          }}
          onDrag={(e) => {
            e.target.style.transform = e.transform;
            gesto.current = { t: e.beforeTranslate };
          }}
          onDragEnd={(e) => confirmarMovimiento(terminar([e.target]))}
          onDragGroupStart={() => {
            gesto.current = null;
          }}
          onDragGroup={(e) => {
            e.events.forEach((ev) => {
              ev.target.style.transform = ev.transform;
            });
            gesto.current = { t: e.events[0]?.beforeTranslate };
          }}
          onDragGroupEnd={(e) => confirmarMovimiento(terminar(e.targets))}
          onResizeStart={() => {
            gesto.current = null;
          }}
          onResize={(e) => {
            e.target.style.width = `${e.width}px`;
            e.target.style.height = `${e.height}px`;
            e.target.style.transform = e.drag.transform;
            gesto.current = { t: e.drag.beforeTranslate, w: e.width, h: e.height };
          }}
          onResizeEnd={(e) => {
            const g = terminar([e.target]);
            const st = useEditor.getState();
            const c = st.escena?.capas.find((x) => x.id === e.target.getAttribute("data-id"));
            if (!g || g.w === undefined || g.h === undefined || !c) return;
            const t = g.t ?? [0, 0];
            const ops: Op[] = [
              { op: "set", capa: c.id, ruta: "x", valor: Math.round(c.x + t[0]) },
              { op: "set", capa: c.id, ruta: "y", valor: Math.round(c.y + t[1]) },
              { op: "set", capa: c.id, ruta: "w", valor: Math.max(1, Math.round(g.w)) },
              { op: "set", capa: c.id, ruta: "h", valor: Math.max(1, Math.round(g.h)) },
            ];
            st.aplicar(ops, "Redimensionar");
          }}
          onRotateStart={() => {
            gesto.current = null;
          }}
          onRotate={(e) => {
            e.target.style.transform = e.drag.transform;
            // ⚠️ En 0.56 `rotation` es el ángulo total del objetivo, no el delta.
            gesto.current = { rot: e.rotation };
          }}
          onRotateEnd={(e) => {
            const g = terminar([e.target]);
            const id = e.target.getAttribute("data-id");
            if (g?.rot === undefined || !id) return;
            useEditor
              .getState()
              .aplicar([{ op: "set", capa: id, ruta: "rot", valor: normalizarAngulo(Math.round(g.rot)) }], "Rotar");
          }}
        />
      </div>

      {marco && (
        <Selecto
          dragContainer={marco}
          selectableTargets={["#marco .capa"]}
          hitRate={0}
          selectByClick
          selectFromInside={false}
          onDragStart={(e) => {
            const t = e.inputEvent.target as Element;
            const st = useEditor.getState();
            if (!st.escena) return e.stop();
            if (t.closest("[data-editor-texto], [data-editor-barra]")) return e.stop();
            if (moveableRef.current?.isMoveableElement(t)) return e.stop();
            const id = t.closest("#marco .capa")?.getAttribute("data-id");
            const yaElegida = !!id && expandir(st.escena, st.seleccion).includes(id);
            if (yaElegida && !(e.inputEvent as MouseEvent).shiftKey) e.stop();
          }}
          onSelectEnd={(e) => {
            const st = useEditor.getState();
            if (!st.escena) return;
            const ids = e.selected.map((el) => el.getAttribute("data-id")!).filter(Boolean);
            const nuevos = raicesSeleccionables(st.escena, ids);
            const shift = (e.inputEvent as MouseEvent).shiftKey;
            st.seleccionar(shift ? alternar(st.seleccion, nuevos) : nuevos);
            if (e.isDragStart && !shift && nuevos.length > 0) {
              e.inputEvent.preventDefault();
              moveableRef.current?.waitToChangeTarget().then(() => moveableRef.current?.dragStart(e.inputEvent));
            }
          }}
        />
      )}

      <div className="absolute bottom-3 left-3 flex items-center gap-1 rounded-md border bg-background p-1 shadow-sm">
        <Button variant="ghost" size="icon-sm" aria-label="Alejar" onClick={() => useEditor.getState().setZoom(zoom / 1.25)}>
          <ZoomOut />
        </Button>
        <span className="w-12 text-center text-xs tabular-nums">{Math.round(zoom * 100)}%</span>
        <Button variant="ghost" size="icon-sm" aria-label="Acercar" onClick={() => useEditor.getState().setZoom(zoom * 1.25)}>
          <ZoomIn />
        </Button>
        <Button variant="ghost" size="icon-sm" aria-label="Ajustar" onClick={ajustar}>
          <Maximize />
        </Button>
      </div>
    </div>
  );
}
```

Notas:
- Si tsc marca `e.targets` en `onDragGroupEnd` o `e.drag` en `onResize`, se revisan los tipos de `react-moveable@0.56.0` (`OnDragGroupEnd`, `OnResize`) y se ajusta el nombre del campo. La semántica no cambia.
- ⚠️ Si `e.rotation` resulta ser el delta del gesto y no el total, el valor que se guarda es `c.rot + e.rotation`. No hay e2e de rotar; se prueba a mano en el banco.
- La barra de zoom vive fuera de `#marco` para que Selecto no arranque un lazo al picarle.

- [ ] **Step 6: banco del editor**

`frontend/app/dev/editor/page.tsx`:

```tsx
import { notFound } from "next/navigation";
import { Banco } from "./banco";

export default function Page() {
  if (process.env.NODE_ENV === "production") notFound();
  return <Banco />;
}
```

`frontend/app/dev/editor/banco.tsx`:

```tsx
"use client";

import { useEffect } from "react";
import { Lienzo } from "@/app/b/[slug]/templates/[id]/_components/lienzo";
import datos from "@/lib/__fixtures__/ops-casos.json";
import type { Escena } from "@/lib/escena";
import { useEditor } from "@/stores/editor";

// Banco del lienzo con la escena del fixture: zoom 0.5, pan (32, 32), sin imán.
// El estado se expone en <pre data-testid="estado"> para la e2e.
export function Banco() {
  const escena = useEditor((s) => s.escena);
  const seleccion = useEditor((s) => s.seleccion);
  const pasado = useEditor((s) => s.pasado.length);
  const editando = useEditor((s) => s.editandoTexto);

  useEffect(() => {
    const st = useEditor.getState();
    const e = structuredClone(datos.base) as unknown as Escena;
    e.guias = { cols: 0, filas: 0, iman: false };
    st.cargar(e);
    st.setZoom(0.5);
    return () => useEditor.getState().vaciar();
  }, []);

  const capas = (escena?.capas ?? []).map((c) => ({
    id: c.id,
    x: c.x,
    y: c.y,
    w: c.w,
    h: c.h,
    rot: c.rot,
    ...(c.tipo === "text" ? { texto: c.texto } : {}),
  }));

  return (
    <div style={{ padding: 24 }}>
      <button type="button" onClick={() => useEditor.getState().deshacer()}>
        Deshacer
      </button>
      <div style={{ width: 800, height: 800, marginTop: 8 }}>
        <Lienzo slug="e2e" colorMarca="#ff3366" ajustarAlCargar={false} />
      </div>
      <pre data-testid="estado">{JSON.stringify({ sel: seleccion, pasado, editando, capas })}</pre>
    </div>
  );
}
```

- `cargar` y `setZoom` son acciones del store, no `setState` de React: `react-hooks/set-state-in-effect` no aplica.

- [ ] **Step 7: verde**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm e2e e2e/lienzo.spec.ts && pnpm e2e e2e/moveable.spec.ts && pnpm test && pnpm exec tsc --noEmit && pnpm lint
```

Esperado: `4 passed` en `lienzo.spec.ts`, `2 passed` en `moveable.spec.ts`, la suite de vitest en verde, tsc y lint limpios.

Si «arrastrar un hijo mueve el grupo» falla porque el primer clic no selecciona `marca`: revisar que `raicesSeleccionables` reciba `caja` (el `data-id` del nodo tocado). Si falla porque Moveable no arrastra el grupo, revisar que `objetivos` sean `["caja", "logo"]` en el `<pre>` agregando `objetivos` temporalmente. No se relaja la prueba.

- [ ] **Step 8: commit**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2
git add frontend/lib/vista.ts frontend/lib/__tests__/vista.test.ts "frontend/app/b/[slug]/templates/[id]/_components/lienzo.tsx" frontend/app/dev/editor frontend/e2e/lienzo.spec.ts
git commit -F - <<'EOF'
editor v2: lienzo con Moveable y Selecto, zoom y pan

Cada gesto es un paso: al soltar se restaura el DOM desde el store y luego
se confirma. El lazo selecciona la raíz del grupo y salta las capas con
candado. Redimensionar y rotar solo con una hoja seleccionada.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

## Task 8: edición de texto en el lienzo (`editor-texto.tsx`)

**Files:**
- Create: `frontend/app/b/[slug]/templates/[id]/_components/editor-texto.tsx`
- Create: `frontend/app/b/[slug]/templates/[id]/_components/__tests__/editor-texto.test.tsx`
- Modify: `frontend/app/b/[slug]/templates/[id]/_components/lienzo.tsx` (pinta `EditorTexto` dentro del escenario)
- Modify: `frontend/e2e/lienzo.spec.ts` (una prueba más)

**Interfaces:**

```ts
export function EditorTexto(props: { capa: CapaTexto; tokens: Tokens; colorMarca: string; zoom: number }): JSX.Element;
```

- Vive dentro del escenario (coordenadas del lienzo), encima de la capa, que `Escenario` ya esconde con `visibility: hidden` mientras `editandoTexto === capa.id` (Task 6).
- Es un `textarea` (D7). El texto y los tramos se guardan en estado local; al salir (blur o Escape) se confirma **un** paso «Editar texto» con lo que cambió y se llama `editarTexto(null)`. Sin cambios, no hay paso.
- `ajustarSpans` (Task 3) corre en cada tecleo, así los tramos siguen al texto (D11).
- La barra de color pinta el rango seleccionado con `pintarSpan`. Sus botones hacen `preventDefault` en `mousedown` para que el textarea no pierda el foco ni la selección. La barra contrarresta el zoom con `scale(1/zoom)` para verse siempre al mismo tamaño.
- `data-editor-texto` y `data-editor-barra` son las marcas que Selecto respeta (Task 7) para no arrancar un lazo encima.

- [ ] **Step 1: escribir la prueba que falla**

`frontend/app/b/[slug]/templates/[id]/_components/__tests__/editor-texto.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import datos from "@/lib/__fixtures__/ops-casos.json";
import type { CapaTexto, Escena } from "@/lib/escena";
import { MAX_TEXTO } from "@/lib/escena";
import { useEditor } from "@/stores/editor";
import { EditorTexto } from "../editor-texto";

const base = datos.base as unknown as Escena;
const titulo = () => useEditor.getState().escena!.capas.find((c) => c.id === "titulo") as CapaTexto;

function montar() {
  const st = useEditor.getState();
  st.cargar(structuredClone(base));
  st.editarTexto("titulo");
  render(<EditorTexto capa={titulo()} tokens={base.tokens} colorMarca="#ff3366" zoom={1} />);
  return screen.getByRole("textbox") as HTMLTextAreaElement;
}

describe("EditorTexto", () => {
  beforeEach(() => useEditor.getState().vaciar());

  it("teclear y salir es un solo paso", () => {
    const ta = montar();
    expect(document.activeElement).toBe(ta);
    fireEvent.change(ta, { target: { value: "Hola mundo!" } });
    fireEvent.change(ta, { target: { value: "Hola mundo!!" } });
    fireEvent.blur(ta);
    expect(titulo().texto).toBe("Hola mundo!!");
    expect(useEditor.getState().pasado).toHaveLength(1);
    expect(useEditor.getState().editandoTexto).toBeNull();
  });

  it("Escape confirma", () => {
    const ta = montar();
    fireEvent.change(ta, { target: { value: "Adiós" } });
    fireEvent.keyDown(ta, { key: "Escape" });
    expect(titulo().texto).toBe("Adiós");
    expect(useEditor.getState().editandoTexto).toBeNull();
  });

  it("sin cambios no hay paso", () => {
    const ta = montar();
    fireEvent.blur(ta);
    expect(useEditor.getState().pasado).toHaveLength(0);
    expect(useEditor.getState().editandoTexto).toBeNull();
  });

  it("pinta el tramo seleccionado", () => {
    const ta = montar();
    ta.setSelectionRange(0, 4);
    const boton = screen.getByRole("button", { name: "Color tinta" });
    fireEvent.mouseDown(boton);
    fireEvent.click(boton);
    fireEvent.blur(ta);
    expect(titulo().estilo.spans).toEqual([{ desde: 0, hasta: 4, color: "token:tinta" }]);
    expect(titulo().texto).toBe("Hola mundo");
    expect(useEditor.getState().pasado).toHaveLength(1);
  });

  it("limita el largo del texto", () => {
    const ta = montar();
    expect(ta.maxLength).toBe(MAX_TEXTO);
  });
});
```

- [ ] **Step 2: correrla y ver que falla**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test "app/b/[slug]/templates/[id]/_components/__tests__/editor-texto.test.tsx"
```

Esperado: FAIL con `Failed to resolve import "../editor-texto"`.

- [ ] **Step 3: implementar `editor-texto.tsx`**

`frontend/app/b/[slug]/templates/[id]/_components/editor-texto.tsx`:

```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { MAX_TEXTO, resolverColor, type CapaTexto, type Op, type Span, type Tokens } from "@/lib/escena";
import { ajustarSpans, pintarSpan } from "@/lib/spans";
import { useEditor } from "@/stores/editor";

type Props = { capa: CapaTexto; tokens: Tokens; colorMarca: string; zoom: number };
type Opcion = { valor: string | null; nombre: string; css: string };

const mismos = (a: Span[], b: Span[]) => JSON.stringify(a) === JSON.stringify(b);

export function EditorTexto({ capa, tokens, colorMarca, zoom }: Props) {
  const [texto, setTexto] = useState(capa.texto);
  const [spans, setSpans] = useState<Span[]>(capa.estilo.spans ?? []);
  const ref = useRef<HTMLTextAreaElement>(null);
  const terminado = useRef(false);

  useEffect(() => {
    ref.current?.focus();
  }, []);

  const confirmar = () => {
    if (terminado.current) return;
    terminado.current = true;
    const ops: Op[] = [];
    if (texto !== capa.texto) ops.push({ op: "set", capa: capa.id, ruta: "texto", valor: texto });
    if (!mismos(spans, capa.estilo.spans ?? [])) ops.push({ op: "set", capa: capa.id, ruta: "estilo.spans", valor: spans });
    const st = useEditor.getState();
    if (ops.length) st.aplicar(ops, "Editar texto");
    st.editarTexto(null);
  };

  const opciones: Opcion[] = Object.keys(tokens.colores).map((k) => ({
    valor: `token:${k}`,
    nombre: k,
    css: resolverColor(`token:${k}`, tokens, colorMarca),
  }));
  if (!("marca" in tokens.colores)) opciones.push({ valor: "token:marca", nombre: "marca", css: colorMarca });

  const pintar = (color: string | null) => {
    const ta = ref.current;
    if (!ta || ta.selectionStart === ta.selectionEnd) return;
    setSpans((s) => pintarSpan(s, ta.selectionStart, ta.selectionEnd, color));
  };

  const e = capa.estilo;
  return (
    <>
      <textarea
        ref={ref}
        data-editor-texto
        aria-label={`Texto de ${capa.nombre}`}
        value={texto}
        maxLength={MAX_TEXTO}
        spellCheck={false}
        onChange={(ev) => {
          const nuevo = ev.target.value;
          setSpans((s) => ajustarSpans(texto, nuevo, s));
          setTexto(nuevo);
        }}
        onBlur={confirmar}
        onKeyDown={(ev) => {
          ev.stopPropagation();
          if (ev.key === "Escape") {
            ev.preventDefault();
            confirmar();
          }
        }}
        style={{
          position: "absolute",
          left: capa.x,
          top: capa.y,
          width: capa.w,
          height: capa.h,
          transform: `rotate(${capa.rot}deg)`,
          zIndex: 10_000,
          margin: 0,
          padding: 0,
          border: "none",
          resize: "none",
          overflow: "hidden",
          background: "transparent",
          outline: `${2 / zoom}px solid #3b82f6`,
          fontFamily: e.fontFamily,
          fontWeight: e.fontWeight,
          fontSize: e.fontSize,
          lineHeight: e.lineHeight,
          letterSpacing: e.letterSpacing,
          textAlign: e.textAlign,
          textTransform: e.textTransform,
          color: resolverColor(e.color, tokens, colorMarca),
        }}
      />
      <div
        style={{
          position: "absolute",
          left: capa.x,
          top: capa.y,
          width: 0,
          height: 0,
          zIndex: 10_001,
          transform: `scale(${1 / zoom})`,
          transformOrigin: "0 0",
        }}
      >
        <div
          data-editor-barra
          className="absolute bottom-2 left-0 flex items-center gap-1 whitespace-nowrap rounded-md border bg-background p-1 shadow-md"
        >
          {opciones.map((o) => (
            <button
              key={o.nombre}
              type="button"
              aria-label={`Color ${o.nombre}`}
              title={o.nombre}
              className="size-6 rounded-sm border"
              style={{ background: o.css }}
              onMouseDown={(ev) => ev.preventDefault()}
              onClick={() => pintar(o.valor)}
            />
          ))}
          <button
            type="button"
            className="h-6 rounded-sm px-2 text-xs hover:bg-muted"
            onMouseDown={(ev) => ev.preventDefault()}
            onClick={() => pintar(null)}
          >
            Quitar
          </button>
        </div>
      </div>
    </>
  );
}
```

Notas:
- `ev.stopPropagation()` en `onKeyDown` impide que los atajos globales (Task 11) vean las teclas; además `useAtajos` ya ignora campos de texto.
- `verticalAlign` del estilo no aplica a un `textarea`: mientras se edita, el texto queda arriba. ⚠️ Diferencia visual conocida, solo durante la edición.
- Si `fireEvent.blur` no dispara `onBlur` en jsdom con React 19, usar `fireEvent.focusOut(ta)`. Es el mismo evento nativo que React escucha.

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test "app/b/[slug]/templates/[id]/_components/__tests__/editor-texto.test.tsx"
```

Esperado: `5 passed`.

- [ ] **Step 4: pintarlo desde el lienzo**

En `lienzo.tsx`, agregar el import:

```tsx
import { EditorTexto } from "./editor-texto";
```

Después de `const { w: W, h: H } = escena.lienzo;`:

```tsx
  const capaEditada = editandoTexto ? escena.capas.find((c) => c.id === editandoTexto) : undefined;
```

Dentro del `div[data-testid="escenario"]`, justo después de `<Escenario … />`:

```tsx
          {capaEditada?.tipo === "text" && (
            <EditorTexto key={capaEditada.id} capa={capaEditada} tokens={escena.tokens} colorMarca={colorMarca} zoom={zoom} />
          )}
```

`key` reinicia el estado local si se pasa de un texto a otro sin salir.

- [ ] **Step 5: la e2e**

Agregar al final de `frontend/e2e/lienzo.spec.ts`:

```ts
test("doble clic edita el texto y Escape lo guarda en un paso", async ({ page }) => {
  await page.locator('#marco .capa[data-id="titulo"]').dblclick();
  const ta = page.locator("[data-editor-texto]");
  await expect(ta).toBeFocused();
  await ta.fill("Hola Guadalajara");
  await ta.press("Escape");

  await expect(ta).toHaveCount(0);
  await expect.poll(async () => (await capa(page, "titulo")).texto).toBe("Hola Guadalajara");
  const e = await estado(page);
  expect(e.editando).toBeNull();
  expect(e.pasado).toBe(1);
});
```

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm e2e e2e/lienzo.spec.ts && pnpm test && pnpm exec tsc --noEmit && pnpm lint
```

Esperado: `5 passed` en la e2e, vitest en verde, tsc y lint limpios.

Si `pasado` sale 2: el primer clic del doble clic arrancó un arrastre de 0 px. `mover(0, 0)` regresa sin paso (Task 5); revisar que `confirmarMovimiento` no se llame con `t` indefinido redondeado a otra cosa.

- [ ] **Step 6: commit**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2
git add "frontend/app/b/[slug]/templates/[id]/_components/editor-texto.tsx" "frontend/app/b/[slug]/templates/[id]/_components/__tests__/editor-texto.test.tsx" "frontend/app/b/[slug]/templates/[id]/_components/lienzo.tsx" frontend/e2e/lienzo.spec.ts
git commit -F - <<'EOF'
editor v2: edición de texto en el lienzo con color por tramo

Doble clic abre un textarea encima de la capa. Escape o salir confirma un
solo paso. La barra pinta el rango seleccionado con los colores de la marca.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

## Task 9: panel de capas (`panel-capas.tsx`)

**Files:**
- Create: `frontend/app/b/[slug]/templates/[id]/_components/panel-capas.tsx`
- Create: `frontend/app/b/[slug]/templates/[id]/_components/__tests__/panel-capas.test.tsx`

**Interfaces:**

```ts
export type Fila = {
  id: string;
  nombre: string;
  tipo: TipoCapa;
  nivel: number;          // 0 = raíz
  padre: string | null;
  oculta: boolean;
  bloqueada: boolean;
};
export function filasDeCapas(escena: Escena): Fila[];                                    // arriba primero, hijos debajo de su grupo
export function reordenarFilas(escena: Escena, activo: string, sobre: string): Op[] | null; // null si no son hermanos
export function PanelCapas(): JSX.Element | null;
```

- Orden de arriba hacia abajo por `z` efectiva: la de una hoja es su `z`; la de un grupo, la mayor de sus hojas (D6).
- Arrastrar solo reordena entre hermanos (D6). Soltar sobre una fila de otro nivel no hace nada.
- El arrastre arranca solo desde la manija (`aria-label="Arrastrar <nombre>"`), así el clic en la fila selecciona y el doble clic renombra.
- Desde el panel sí se puede seleccionar una capa con candado o una hija de un grupo; en el lienzo no (Task 7). Es la vía para quitar el candado o redimensionar una hija.
- Ojo, candado y renombrar son un paso cada uno.

- [ ] **Step 1: escribir la prueba que falla**

`frontend/app/b/[slug]/templates/[id]/_components/__tests__/panel-capas.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import datos from "@/lib/__fixtures__/ops-casos.json";
import { aplicarOps, type Escena } from "@/lib/escena";
import { useEditor } from "@/stores/editor";
import { filasDeCapas, PanelCapas, reordenarFilas } from "../panel-capas";

const base = datos.base as unknown as Escena;
const ids = (e: Escena) => filasDeCapas(e).map((f) => f.id);
const capa = (id: string) => useEditor.getState().escena!.capas.find((c) => c.id === id)!;

describe("filasDeCapas y reordenarFilas", () => {
  it("ordena por z efectiva con los hijos debajo del grupo", () => {
    const f = filasDeCapas(base);
    expect(f.map((x) => x.id)).toEqual(["titulo", "marca", "logo", "caja"]);
    expect(f.map((x) => x.nivel)).toEqual([0, 0, 1, 1]);
    expect(f[2].padre).toBe("marca");
  });

  it("sube un grupo sobre una raíz", () => {
    const ops = reordenarFilas(base, "marca", "titulo")!;
    expect(ids(aplicarOps(base, ops))).toEqual(["marca", "logo", "caja", "titulo"]);
  });

  it("reordena hijos dentro del grupo", () => {
    const ops = reordenarFilas(base, "logo", "caja")!;
    expect(ids(aplicarOps(base, ops))).toEqual(["titulo", "marca", "caja", "logo"]);
  });

  it("no mezcla niveles", () => {
    expect(reordenarFilas(base, "logo", "titulo")).toBeNull();
  });
});

describe("PanelCapas", () => {
  beforeEach(() => {
    useEditor.getState().vaciar();
    useEditor.getState().cargar(structuredClone(base));
    render(<PanelCapas />);
  });

  it("clic selecciona y shift-clic alterna", () => {
    fireEvent.click(screen.getByText("Título"));
    expect(useEditor.getState().seleccion).toEqual(["titulo"]);
    fireEvent.click(screen.getByText("Caja"), { shiftKey: true });
    expect(useEditor.getState().seleccion).toEqual(["titulo", "caja"]);
    fireEvent.click(screen.getByText("Título"), { shiftKey: true });
    expect(useEditor.getState().seleccion).toEqual(["caja"]);
  });

  it("el ojo oculta en un paso", () => {
    fireEvent.click(screen.getByRole("button", { name: "Ocultar Título" }));
    expect(capa("titulo").oculta).toBe(true);
    expect(useEditor.getState().pasado).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Mostrar Título" })).not.toBeNull();
  });

  it("el candado bloquea en un paso", () => {
    fireEvent.click(screen.getByRole("button", { name: "Bloquear Título" }));
    expect(capa("titulo").bloqueada).toBe(true);
    expect(useEditor.getState().pasado).toHaveLength(1);
  });

  it("doble clic renombra con Enter", () => {
    fireEvent.doubleClick(screen.getByText("Título"));
    const input = screen.getByRole("textbox", { name: "Nombre de la capa" });
    fireEvent.change(input, { target: { value: "  Encabezado  " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(capa("titulo").nombre).toBe("Encabezado");
    expect(useEditor.getState().pasado).toHaveLength(1);
  });

  it("Escape cancela el renombre", () => {
    fireEvent.doubleClick(screen.getByText("Título"));
    const input = screen.getByRole("textbox", { name: "Nombre de la capa" });
    fireEvent.change(input, { target: { value: "Otro" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(capa("titulo").nombre).toBe("Título");
    expect(useEditor.getState().pasado).toHaveLength(0);
    expect(screen.queryByRole("textbox")).toBeNull();
  });
});
```

- Sin `@testing-library/jest-dom` (el Task 1 no lo instala): se usa `.not.toBeNull()` en vez de `toBeInTheDocument`.

- [ ] **Step 2: correrla y ver que falla**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test "app/b/[slug]/templates/[id]/_components/__tests__/panel-capas.test.tsx"
```

Esperado: FAIL con `Failed to resolve import "../panel-capas"`.

- [ ] **Step 3: implementar `panel-capas.tsx`**

`frontend/app/b/[slug]/templates/[id]/_components/panel-capas.tsx`:

```tsx
"use client";

import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Eye, EyeOff, Film, Folder, GripVertical, Image as IconoImagen, Lock, Shapes, Square, Type, Unlock } from "lucide-react";
import { useRef, useState } from "react";
import { expandir, opsReordenar } from "@/lib/edicion";
import { padreDe, type Capa, type Escena, type Op, type TipoCapa } from "@/lib/escena";
import { alternar } from "@/lib/vista";
import { cn } from "@/lib/utils";
import { useEditor } from "@/stores/editor";

export type Fila = {
  id: string;
  nombre: string;
  tipo: TipoCapa;
  nivel: number;
  padre: string | null;
  oculta: boolean;
  bloqueada: boolean;
};

const ICONO: Record<TipoCapa, typeof Type> = {
  text: Type,
  image: IconoImagen,
  video: Film,
  shape: Square,
  svg: Shapes,
  group: Folder,
};

function zEfectiva(escena: Escena, c: Capa): number {
  if (c.tipo !== "group") return c.z;
  const zs = expandir(escena, [c.id]).map((id) => escena.capas.find((x) => x.id === id)?.z ?? 0);
  return zs.length ? Math.max(...zs) : c.z;
}

function hermanos(escena: Escena, padre: string | null): Capa[] {
  const m = new Map(escena.capas.map((c) => [c.id, c]));
  const lista =
    padre === null
      ? escena.capas.filter((c) => padreDe(escena, c.id) === null)
      : ((m.get(padre) as Extract<Capa, { tipo: "group" }>).hijos.map((id) => m.get(id)).filter(Boolean) as Capa[]);
  return [...lista].sort((a, b) => zEfectiva(escena, b) - zEfectiva(escena, a));
}

export function filasDeCapas(escena: Escena): Fila[] {
  const filas: Fila[] = [];
  const bajar = (padre: string | null, nivel: number) => {
    for (const c of hermanos(escena, padre)) {
      filas.push({ id: c.id, nombre: c.nombre, tipo: c.tipo, nivel, padre, oculta: c.oculta, bloqueada: c.bloqueada });
      if (c.tipo === "group") bajar(c.id, nivel + 1);
    }
  };
  bajar(null, 0);
  return filas;
}

export function reordenarFilas(escena: Escena, activo: string, sobre: string): Op[] | null {
  const padre = padreDe(escena, activo);
  if (padre !== padreDe(escena, sobre)) return null;
  const orden = hermanos(escena, padre).map((c) => c.id);
  const de = orden.indexOf(activo);
  const a = orden.indexOf(sobre);
  if (de < 0 || a < 0 || de === a) return null;
  return opsReordenar(escena, arrayMove(orden, de, a));
}

function FilaCapa({ fila, elegida }: { fila: Fila; elegida: boolean }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: fila.id });
  const [renombrando, setRenombrando] = useState(false);
  const [valor, setValor] = useState(fila.nombre);
  const cancelado = useRef(false);
  const Icono = ICONO[fila.tipo];

  const set = (ruta: string, v: unknown, etiqueta: string) =>
    useEditor.getState().aplicar([{ op: "set", capa: fila.id, ruta, valor: v }], etiqueta);

  const renombrar = () => {
    if (cancelado.current) return;
    const n = valor.trim();
    if (n && n !== fila.nombre) set("nombre", n, "Renombrar");
    setRenombrando(false);
  };

  return (
    <div
      ref={setNodeRef}
      data-fila={fila.id}
      data-seleccionada={elegida || undefined}
      style={{ transform: CSS.Transform.toString(transform), transition, paddingLeft: 4 + fila.nivel * 12 }}
      className={cn(
        "group flex h-8 items-center gap-1 rounded-sm pr-1 text-sm select-none",
        elegida ? "bg-primary/10 text-foreground" : "hover:bg-muted",
        fila.oculta && "opacity-50",
        isDragging && "z-10 bg-background shadow-sm",
      )}
      onClick={(ev) => {
        const st = useEditor.getState();
        st.seleccionar(ev.shiftKey ? alternar(st.seleccion, [fila.id]) : [fila.id]);
      }}
    >
      <button
        type="button"
        aria-label={`Arrastrar ${fila.nombre}`}
        className="cursor-grab text-muted-foreground opacity-0 group-hover:opacity-100 focus:opacity-100"
        onClick={(ev) => ev.stopPropagation()}
        {...attributes}
        {...listeners}
      >
        <GripVertical className="size-3.5" />
      </button>
      <Icono className="size-3.5 shrink-0 text-muted-foreground" />
      {renombrando ? (
        <input
          aria-label="Nombre de la capa"
          autoFocus
          maxLength={60}
          value={valor}
          className="h-6 min-w-0 flex-1 rounded-sm border bg-background px-1 text-sm"
          onClick={(ev) => ev.stopPropagation()}
          onChange={(ev) => setValor(ev.target.value)}
          onBlur={renombrar}
          onKeyDown={(ev) => {
            ev.stopPropagation();
            if (ev.key === "Enter") renombrar();
            if (ev.key === "Escape") {
              cancelado.current = true;
              setRenombrando(false);
            }
          }}
        />
      ) : (
        <span
          className="min-w-0 flex-1 truncate"
          onDoubleClick={(ev) => {
            ev.stopPropagation();
            cancelado.current = false;
            setValor(fila.nombre);
            setRenombrando(true);
          }}
        >
          {fila.nombre}
        </span>
      )}
      <button
        type="button"
        aria-label={`${fila.oculta ? "Mostrar" : "Ocultar"} ${fila.nombre}`}
        className="text-muted-foreground hover:text-foreground"
        onClick={(ev) => {
          ev.stopPropagation();
          set("oculta", !fila.oculta, fila.oculta ? "Mostrar" : "Ocultar");
        }}
      >
        {fila.oculta ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
      </button>
      <button
        type="button"
        aria-label={`${fila.bloqueada ? "Desbloquear" : "Bloquear"} ${fila.nombre}`}
        className={cn("text-muted-foreground hover:text-foreground", !fila.bloqueada && "opacity-0 group-hover:opacity-100")}
        onClick={(ev) => {
          ev.stopPropagation();
          set("bloqueada", !fila.bloqueada, fila.bloqueada ? "Desbloquear" : "Bloquear");
        }}
      >
        {fila.bloqueada ? <Lock className="size-3.5" /> : <Unlock className="size-3.5" />}
      </button>
    </div>
  );
}

export function PanelCapas() {
  const escena = useEditor((s) => s.escena);
  const seleccion = useEditor((s) => s.seleccion);
  const sensores = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  if (!escena) return null;
  const filas = filasDeCapas(escena);

  const soltar = ({ active, over }: DragEndEvent) => {
    const e = useEditor.getState().escena;
    if (!e || !over || active.id === over.id) return;
    const ops = reordenarFilas(e, String(active.id), String(over.id));
    if (ops?.length) useEditor.getState().aplicar(ops, "Reordenar capas");
  };

  if (!filas.length) return <p className="p-3 text-sm text-muted-foreground">Sin capas. Agrega un texto o una forma.</p>;

  return (
    <DndContext sensors={sensores} collisionDetection={closestCenter} onDragEnd={soltar}>
      <SortableContext items={filas.map((f) => f.id)} strategy={verticalListSortingStrategy}>
        <div className="flex flex-col gap-0.5 p-1">
          {filas.map((f) => (
            <FilaCapa key={f.id} fila={f} elegida={seleccion.includes(f.id)} />
          ))}
        </div>
      </SortableContext>
    </DndContext>
  );
}
```

Notas:
- `cn` vive en `@/lib/utils` (shadcn). Si no, ajustar el import al que usen los componentes de `components/ui/`.
- La `Fila` del grupo arrastra a sus hijos solo en el modelo (`opsReordenar` mueve todas sus hojas); en pantalla, durante el arrastre, los hijos se quedan. Es aceptable: al soltar se repinta el orden correcto.

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test "app/b/[slug]/templates/[id]/_components/__tests__/panel-capas.test.tsx" && pnpm exec tsc --noEmit && pnpm lint
```

Esperado: `9 passed`, tsc y lint limpios.

- [ ] **Step 4: commit**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2
git add "frontend/app/b/[slug]/templates/[id]/_components/panel-capas.tsx" "frontend/app/b/[slug]/templates/[id]/_components/__tests__/panel-capas.test.tsx"
git commit -F - <<'EOF'
editor v2: panel de capas con orden, ojo, candado y renombre

El orden se cambia arrastrando entre hermanos; z se reasigna en un paso.
Cada toggle y cada renombre es un paso de deshacer.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

## Task 10: panel lateral y panel de propiedades

**Files:**
- Create: `frontend/app/b/[slug]/templates/[id]/_components/panel-lateral.tsx`
- Create: `frontend/app/b/[slug]/templates/[id]/_components/panel-propiedades.tsx`
- Create: `frontend/app/b/[slug]/templates/[id]/_components/__tests__/panel-lateral.test.tsx`
- Create: `frontend/app/b/[slug]/templates/[id]/_components/__tests__/panel-propiedades.test.tsx`

**Interfaces:**

```ts
// panel-lateral.tsx (contrato del índice; los planes 3 y 4 solo agregan pestañas en page.tsx)
export function PanelLateral(props: { pestanas: { id: string; etiqueta: string; contenido: ReactNode }[] }): JSX.Element | null;

// panel-propiedades.tsx
export function PanelPropiedades(props: { colorMarca: string }): JSX.Element | null;
export function CampoNumero(props: {
  etiqueta: string; valor: number; onCommit: (n: number) => void;
  min?: number; max?: number; deshabilitado?: boolean;
}): JSX.Element;
export function CampoColor(props: {
  etiqueta: string; valor: string; tokens: Tokens; colorMarca: string; onCommit: (v: string) => void;
}): JSX.Element;
```

- Sin selección: sección «Lienzo» (formato con `cambiarFormato`, fondo de color con `editarEscena`).
- Varias: «N capas seleccionadas» (alinear y distribuir viven en la barra superior, Task 12).
- Una: posición y tamaño, rotación, opacidad, y lo propio del tipo (texto, forma, imagen/video). X y Y usan `mover`, así un grupo arrastra a sus hijos. Ancho y alto de un grupo están deshabilitados (D5).
- `CampoNumero` confirma en blur o Enter. Un valor inválido o igual regresa al anterior sin paso.
- Selects nativos (D9). Los colores ofrecen los tokens de la marca, `token:marca` y un color propio.

- [ ] **Step 1: escribir las pruebas que fallan**

`frontend/app/b/[slug]/templates/[id]/_components/__tests__/panel-lateral.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PanelLateral } from "../panel-lateral";

const pestanas = [
  { id: "capas", etiqueta: "Capas", contenido: <p>contenido capas</p> },
  { id: "assets", etiqueta: "Assets", contenido: <p>contenido assets</p> },
];

describe("PanelLateral", () => {
  it("abre en la primera pestaña", () => {
    render(<PanelLateral pestanas={pestanas} />);
    expect(screen.queryByText("contenido capas")).not.toBeNull();
    expect(screen.queryByText("contenido assets")).toBeNull();
  });

  it("cambia de pestaña", () => {
    render(<PanelLateral pestanas={pestanas} />);
    // Radix Tabs activa en mousedown con el botón principal.
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Assets" }), { button: 0 });
    expect(screen.queryByText("contenido assets")).not.toBeNull();
  });
});
```

`frontend/app/b/[slug]/templates/[id]/_components/__tests__/panel-propiedades.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import datos from "@/lib/__fixtures__/ops-casos.json";
import type { CapaTexto, Escena } from "@/lib/escena";
import { useEditor } from "@/stores/editor";
import { PanelPropiedades } from "../panel-propiedades";

const base = datos.base as unknown as Escena;
const st = () => useEditor.getState();
const capa = (id: string) => st().escena!.capas.find((c) => c.id === id)!;
const campo = (nombre: string) => screen.getByRole("spinbutton", { name: nombre }) as HTMLInputElement;

function montar(seleccion: string[] = []) {
  st().vaciar();
  st().cargar(structuredClone(base));
  st().seleccionar(seleccion);
  render(<PanelPropiedades colorMarca="#ff3366" />);
}

describe("PanelPropiedades", () => {
  beforeEach(() => st().vaciar());

  it("sin selección cambia el formato del lienzo", () => {
    montar();
    fireEvent.change(screen.getByRole("combobox", { name: "Formato" }), { target: { value: "1x1" } });
    expect(st().escena!.lienzo.formato).toBe("1x1");
    expect(st().escena!.lienzo.h).toBe(1080);
    expect(st().pasado).toHaveLength(1);
  });

  it("sin selección cambia el fondo a un token", () => {
    montar();
    fireEvent.change(screen.getByRole("combobox", { name: "Fondo" }), { target: { value: "token:tinta" } });
    expect(st().escena!.lienzo.fondo).toEqual({ tipo: "color", valor: "token:tinta" });
  });

  it("con varias muestra el conteo", () => {
    montar(["titulo", "marca"]);
    expect(screen.queryByText("2 capas seleccionadas")).not.toBeNull();
  });

  it("X confirma en blur con un paso", () => {
    montar(["titulo"]);
    fireEvent.change(campo("X"), { target: { value: "100" } });
    fireEvent.blur(campo("X"));
    expect(capa("titulo").x).toBe(100);
    expect(st().pasado).toHaveLength(1);
  });

  it("Ancho confirma con Enter", () => {
    montar(["titulo"]);
    fireEvent.change(campo("Ancho"), { target: { value: "500" } });
    fireEvent.keyDown(campo("Ancho"), { key: "Enter" });
    expect(capa("titulo").w).toBe(500);
  });

  it("un valor inválido regresa sin paso", () => {
    montar(["titulo"]);
    fireEvent.change(campo("Ancho"), { target: { value: "" } });
    fireEvent.blur(campo("Ancho"));
    expect(capa("titulo").w).toBe(920);
    expect(campo("Ancho").value).toBe("920");
    expect(st().pasado).toHaveLength(0);
  });

  it("un grupo mueve a sus hijos y no se redimensiona", () => {
    montar(["marca"]);
    expect(campo("Ancho").disabled).toBe(true);
    fireEvent.change(campo("Y"), { target: { value: "1000" } });
    fireEvent.blur(campo("Y"));
    expect(capa("caja").y).toBe(1000);
    expect(capa("logo").y).toBe(1030);
    expect(st().pasado).toHaveLength(1);
  });

  it("opacidad en por ciento", () => {
    montar(["titulo"]);
    fireEvent.change(campo("Opacidad"), { target: { value: "50" } });
    fireEvent.blur(campo("Opacidad"));
    expect(capa("titulo").opacity).toBe(0.5);
  });

  it("color del texto desde los tokens", () => {
    montar(["titulo"]);
    fireEvent.change(screen.getByRole("combobox", { name: "Color" }), { target: { value: "token:marca" } });
    expect((capa("titulo") as CapaTexto).estilo.color).toBe("token:marca");
  });
});
```

- [ ] **Step 2: correrlas y ver que fallan**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test "app/b/[slug]/templates/[id]/_components/__tests__/panel-lateral.test.tsx" "app/b/[slug]/templates/[id]/_components/__tests__/panel-propiedades.test.tsx"
```

Esperado: FAIL, las dos por `Failed to resolve import`.

- [ ] **Step 3: implementar `panel-lateral.tsx`**

`frontend/app/b/[slug]/templates/[id]/_components/panel-lateral.tsx`:

```tsx
"use client";

import type { ReactNode } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

type Pestana = { id: string; etiqueta: string; contenido: ReactNode };

export function PanelLateral({ pestanas }: { pestanas: Pestana[] }) {
  if (!pestanas.length) return null;
  return (
    <Tabs defaultValue={pestanas[0].id} className="flex h-full min-h-0 flex-col gap-0">
      <TabsList className="m-2 w-[calc(100%-1rem)]">
        {pestanas.map((p) => (
          <TabsTrigger key={p.id} value={p.id} className="flex-1">
            {p.etiqueta}
          </TabsTrigger>
        ))}
      </TabsList>
      {pestanas.map((p) => (
        <TabsContent key={p.id} value={p.id} className="min-h-0 flex-1 overflow-y-auto">
          {p.contenido}
        </TabsContent>
      ))}
    </Tabs>
  );
}
```

- [ ] **Step 4: implementar `panel-propiedades.tsx`**

`frontend/app/b/[slug]/templates/[id]/_components/panel-propiedades.tsx`:

```tsx
"use client";

import { useState, type ReactNode } from "react";
import { Label } from "@/components/ui/label";
import { resolverColor, type Capa, type Formato, type Op, type Tokens } from "@/lib/escena";
import { useEditor } from "@/stores/editor";

const SELECT =
  "h-8 w-full rounded-md border border-input bg-background px-2 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50";
const HEX = /^#[0-9a-f]{6}$/i;

const FORMATOS: { valor: Formato; nombre: string }[] = [
  { valor: "4x5", nombre: "Cuadrada alta (4:5)" },
  { valor: "1x1", nombre: "Cuadrada (1:1)" },
  { valor: "9x16", nombre: "Vertical (9:16)" },
];
const PESOS = [300, 400, 500, 600, 700, 800, 900];

export function CampoNumero({
  etiqueta,
  valor,
  onCommit,
  min,
  max,
  deshabilitado = false,
}: {
  etiqueta: string;
  valor: number;
  onCommit: (n: number) => void;
  min?: number;
  max?: number;
  deshabilitado?: boolean;
}) {
  const [texto, setTexto] = useState(String(valor));
  const [previo, setPrevio] = useState(valor);
  // Si el store cambia (deshacer, arrastre), el campo lo sigue. Patrón de
  // «estado derivado de props» de React: se ajusta durante el render.
  if (previo !== valor) {
    setPrevio(valor);
    setTexto(String(valor));
  }

  const confirmar = () => {
    const n = Number(texto);
    if (texto.trim() === "" || !Number.isFinite(n)) return setTexto(String(valor));
    let v = n;
    if (min !== undefined) v = Math.max(min, v);
    if (max !== undefined) v = Math.min(max, v);
    setTexto(String(v));
    if (v !== valor) onCommit(v);
  };

  return (
    <label className="flex flex-col gap-1 text-xs text-muted-foreground">
      {etiqueta}
      <input
        type="number"
        aria-label={etiqueta}
        value={texto}
        disabled={deshabilitado}
        className="h-8 w-full rounded-md border border-input bg-background px-2 text-sm text-foreground tabular-nums disabled:opacity-50"
        onChange={(ev) => setTexto(ev.target.value)}
        onBlur={confirmar}
        onKeyDown={(ev) => {
          if (ev.key === "Enter") confirmar();
        }}
      />
    </label>
  );
}

export function CampoColor({
  etiqueta,
  valor,
  tokens,
  colorMarca,
  onCommit,
}: {
  etiqueta: string;
  valor: string;
  tokens: Tokens;
  colorMarca: string;
  onCommit: (v: string) => void;
}) {
  const nombres = Object.keys(tokens.colores);
  if (!nombres.includes("marca")) nombres.push("marca");
  const esToken = valor.startsWith("token:");
  const resuelto = resolverColor(valor, tokens, colorMarca);
  const [propio, setPropio] = useState(HEX.test(resuelto) ? resuelto : "#000000");

  return (
    <div className="flex flex-col gap-1">
      <Label className="text-xs text-muted-foreground">
        {etiqueta}
        <select
          aria-label={etiqueta}
          className={SELECT}
          value={esToken ? valor : "propio"}
          onChange={(ev) => onCommit(ev.target.value === "propio" ? propio : ev.target.value)}
        >
          {nombres.map((k) => (
            <option key={k} value={`token:${k}`}>
              {k}
            </option>
          ))}
          <option value="propio">Color propio</option>
        </select>
      </Label>
      {!esToken && (
        <input
          type="color"
          aria-label={`${etiqueta} propio`}
          value={HEX.test(valor) ? valor : propio}
          className="h-8 w-full cursor-pointer rounded-md border"
          onChange={(ev) => setPropio(ev.target.value)}
          onBlur={() => propio !== valor && onCommit(propio)}
        />
      )}
    </div>
  );
}

function Seccion({ titulo, children }: { titulo: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2 border-b p-3">
      <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{titulo}</h3>
      {children}
    </section>
  );
}

function Selector<T extends string | number>({
  etiqueta,
  valor,
  opciones,
  onCambio,
}: {
  etiqueta: string;
  valor: T;
  opciones: { valor: T; nombre: string }[];
  onCambio: (v: T) => void;
}) {
  return (
    <Label className="flex flex-col items-stretch gap-1 text-xs text-muted-foreground">
      {etiqueta}
      <select
        aria-label={etiqueta}
        className={SELECT}
        value={String(valor)}
        onChange={(ev) => {
          const o = opciones.find((x) => String(x.valor) === ev.target.value);
          if (o) onCambio(o.valor);
        }}
      >
        {opciones.map((o) => (
          <option key={String(o.valor)} value={String(o.valor)}>
            {o.nombre}
          </option>
        ))}
      </select>
    </Label>
  );
}

export function PanelPropiedades({ colorMarca }: { colorMarca: string }) {
  const escena = useEditor((s) => s.escena);
  const seleccion = useEditor((s) => s.seleccion);
  if (!escena) return null;
  const st = useEditor.getState;
  const tokens = escena.tokens;

  if (seleccion.length === 0) {
    const fondo = escena.lienzo.fondo;
    return (
      <Seccion titulo="Lienzo">
        <Selector
          etiqueta="Formato"
          valor={escena.lienzo.formato}
          opciones={FORMATOS}
          onCambio={(f) => st().cambiarFormato(f)}
        />
        {fondo.tipo === "color" ? (
          <CampoColor
            etiqueta="Fondo"
            valor={fondo.valor}
            tokens={tokens}
            colorMarca={colorMarca}
            onCommit={(v) =>
              st().editarEscena((d) => {
                d.lienzo.fondo = { tipo: "color", valor: v };
              }, "Fondo")
            }
          />
        ) : (
          <p className="text-xs text-muted-foreground">El fondo es {fondo.tipo === "imagen" ? "una imagen" : "un degradado"}.</p>
        )}
      </Seccion>
    );
  }

  if (seleccion.length > 1) {
    return (
      <Seccion titulo="Selección">
        <p className="text-sm">{seleccion.length} capas seleccionadas</p>
      </Seccion>
    );
  }

  const c = escena.capas.find((x) => x.id === seleccion[0]);
  if (!c) return null;
  const set = (ruta: string, valor: unknown, etiqueta = "Propiedades") =>
    st().aplicar([{ op: "set", capa: c.id, ruta, valor } satisfies Op], etiqueta);
  const grupo = c.tipo === "group";

  return (
    <div key={c.id}>
      <Seccion titulo={c.nombre}>
        <div className="grid grid-cols-2 gap-2">
          <CampoNumero etiqueta="X" valor={c.x} onCommit={(n) => st().mover(Math.round(n) - c.x, 0)} />
          <CampoNumero etiqueta="Y" valor={c.y} onCommit={(n) => st().mover(0, Math.round(n) - c.y)} />
          <CampoNumero etiqueta="Ancho" valor={c.w} min={1} deshabilitado={grupo} onCommit={(n) => set("w", Math.round(n))} />
          <CampoNumero etiqueta="Alto" valor={c.h} min={1} deshabilitado={grupo} onCommit={(n) => set("h", Math.round(n))} />
          <CampoNumero etiqueta="Rotación" valor={c.rot} deshabilitado={grupo} onCommit={(n) => set("rot", n)} />
          <CampoNumero
            etiqueta="Opacidad"
            valor={Math.round(c.opacity * 100)}
            min={0}
            max={100}
            onCommit={(n) => set("opacity", n / 100)}
          />
        </div>
      </Seccion>
      <PropiedadesDeTipo capa={c} tokens={tokens} colorMarca={colorMarca} set={set} />
    </div>
  );
}

function PropiedadesDeTipo({
  capa: c,
  tokens,
  colorMarca,
  set,
}: {
  capa: Capa;
  tokens: Tokens;
  colorMarca: string;
  set: (ruta: string, valor: unknown, etiqueta?: string) => void;
}) {
  if (c.tipo === "text") {
    const e = c.estilo;
    return (
      <Seccion titulo="Texto">
        <Label className="flex flex-col items-stretch gap-1 text-xs text-muted-foreground">
          Fuente
          <input
            aria-label="Fuente"
            defaultValue={e.fontFamily}
            className="h-8 rounded-md border border-input bg-background px-2 text-sm text-foreground"
            onBlur={(ev) => {
              const v = ev.target.value.trim();
              if (v && v !== e.fontFamily) set("estilo.fontFamily", v);
            }}
          />
        </Label>
        <div className="grid grid-cols-2 gap-2">
          <CampoNumero etiqueta="Tamaño" valor={e.fontSize} min={6} max={400} onCommit={(n) => set("estilo.fontSize", n)} />
          <Selector
            etiqueta="Peso"
            valor={e.fontWeight}
            opciones={PESOS.map((p) => ({ valor: p, nombre: String(p) }))}
            onCambio={(p) => set("estilo.fontWeight", p)}
          />
          <CampoNumero
            etiqueta="Interlineado"
            valor={e.lineHeight}
            min={0.5}
            max={3}
            onCommit={(n) => set("estilo.lineHeight", n)}
          />
          <Selector
            etiqueta="Alineación"
            valor={e.textAlign}
            opciones={[
              { valor: "left", nombre: "Izquierda" },
              { valor: "center", nombre: "Centro" },
              { valor: "right", nombre: "Derecha" },
              { valor: "justify", nombre: "Justificado" },
            ]}
            onCambio={(v) => set("estilo.textAlign", v)}
          />
        </div>
        <CampoColor
          etiqueta="Color"
          valor={e.color}
          tokens={tokens}
          colorMarca={colorMarca}
          onCommit={(v) => set("estilo.color", v)}
        />
      </Seccion>
    );
  }
  if (c.tipo === "shape") {
    return (
      <Seccion titulo="Forma">
        <CampoColor
          etiqueta="Relleno"
          valor={c.estilo.fill}
          tokens={tokens}
          colorMarca={colorMarca}
          onCommit={(v) => set("estilo.fill", v)}
        />
        <CampoNumero etiqueta="Radio" valor={c.estilo.radius ?? 0} min={0} onCommit={(n) => set("estilo.radius", n)} />
      </Seccion>
    );
  }
  if (c.tipo === "image" || c.tipo === "video" || c.tipo === "svg") {
    return (
      <Seccion titulo={c.tipo === "video" ? "Video" : "Imagen"}>
        <Selector
          etiqueta="Ajuste"
          valor={c.ajuste}
          opciones={[
            { valor: "cover", nombre: "Llenar" },
            { valor: "contain", nombre: "Contener" },
          ]}
          onCambio={(v) => set("ajuste", v)}
        />
      </Seccion>
    );
  }
  return null;
}
```

Notas:
- `key={c.id}` en el contenedor reinicia los campos al cambiar de capa.
- `CampoNumero` ajusta su texto durante el render cuando cambia `valor` (patrón oficial de React para estado derivado). No usa `useEffect` con `setState`, que `react-hooks/set-state-in-effect` prohíbe.
- Si `Label` (Radix) no reenvía el clic al `select` anidado, da igual: el `aria-label` es lo que usan las pruebas.
- La fuente es un campo libre en este plan. El plan 3 la cambia por la lista de Fontsource.

- [ ] **Step 5: verde**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test "app/b/[slug]/templates/[id]/_components/__tests__/panel-lateral.test.tsx" "app/b/[slug]/templates/[id]/_components/__tests__/panel-propiedades.test.tsx" && pnpm exec tsc --noEmit && pnpm lint
```

Esperado: `2 passed` y `9 passed`; tsc y lint limpios.

- [ ] **Step 6: commit**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2
git add "frontend/app/b/[slug]/templates/[id]/_components/panel-lateral.tsx" "frontend/app/b/[slug]/templates/[id]/_components/panel-propiedades.tsx" "frontend/app/b/[slug]/templates/[id]/_components/__tests__/panel-lateral.test.tsx" "frontend/app/b/[slug]/templates/[id]/_components/__tests__/panel-propiedades.test.tsx"
git commit -F - <<'EOF'
editor v2: panel lateral con pestañas y panel de propiedades

El lateral es el punto de extensión de los planes 3 y 4. Propiedades
edita lienzo, posición, tamaño, opacidad y lo propio de cada tipo; cada
cambio es un paso.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

## Task 11: autoguardado y atajos de teclado (`use-autoguardado.ts`, `use-atajos.ts`)

**Files:**
- Create: `frontend/hooks/use-autoguardado.ts`
- Create: `frontend/hooks/use-atajos.ts`
- Create: `frontend/hooks/__tests__/use-autoguardado.test.tsx`
- Create: `frontend/hooks/__tests__/use-atajos.test.tsx`

**Interfaces:**

```ts
// hooks/use-autoguardado.ts
export function useAutoguardado(opciones: {
  activo: boolean;                                              // solo `borrador` y con la escena ya sembrada (D12)
  guardar: (escena: Escena, mensaje?: string) => Promise<unknown>;
  retraso?: number;                                             // 2000 ms
}): {
  guardando: boolean;
  error: Error | null;
  guardarAhora(mensaje?: string): Promise<void>;                // con mensaje: guarda aunque no haya cambios y propaga el error
};

// hooks/use-atajos.ts
export function accionDe(e: KeyboardEvent): ((s: EstadoEditor) => void) | null;
export function useAtajos(): void;
```

- El debounce corre sobre `revision`: cada edición reinicia los 2 s.
- Los guardados van en una cola (`cola.current`): nunca hay dos `PATCH` en vuelo. Al terminar se llama `marcarGuardado(revision)` con la revisión que se mandó, así que una edición hecha mientras se guardaba deja `sucio` en `true` y dispara otro guardado.
- Un autoguardado que falla deja `error` y no reintenta solo. La siguiente edición sí agenda otro.
- `beforeunload` avisa mientras haya cambios sin guardar, esté activo o no el autoguardado.
- Los atajos aceptan ⌘ o Ctrl (D15). No hacen nada con un campo de texto enfocado, dentro de un diálogo ni mientras se edita un texto en el lienzo.

| Tecla | Acción |
|---|---|
| ⌘Z / ⇧⌘Z / ⌘Y | deshacer / rehacer / rehacer |
| ⌘C / ⌘V / ⌘D | copiar / pegar / duplicar |
| ⌘G / ⇧⌘G | agrupar / desagrupar |
| ⌘] / ⇧⌘] | subir / al frente (por `code`, no depende del teclado) |
| ⌘[ / ⇧⌘[ | bajar / al fondo |
| Supr / Retroceso | borrar |
| Esc | quitar la selección |
| Flechas / ⇧+flechas | mover 1 px / 10 px |

- [ ] **Step 1: prueba que falla del autoguardado**

`frontend/hooks/__tests__/use-autoguardado.test.tsx`:

```tsx
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import datos from "@/lib/__fixtures__/ops-casos.json";
import type { Escena } from "@/lib/escena";
import { useEditor } from "@/stores/editor";
import { useAutoguardado } from "../use-autoguardado";

const base = datos.base as unknown as Escena;
const st = () => useEditor.getState();
type Guardar = (e: Escena, m?: string) => Promise<void>;

const avanzar = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
const editar = (x: number) =>
  act(() => st().aplicar([{ op: "set", capa: "titulo", ruta: "x", valor: x }]));
const xGuardada = (g: ReturnType<typeof vi.fn<Guardar>>, llamada: number) =>
  g.mock.calls[llamada][0].capas.find((c) => c.id === "titulo")!.x;

function diferido() {
  let resolver!: () => void;
  let rechazar!: (e: Error) => void;
  const promesa = new Promise<void>((res, rej) => {
    resolver = res;
    rechazar = rej;
  });
  return { promesa, resolver, rechazar };
}

function montar(guardar: Guardar, activo = true) {
  return renderHook((p: { activo: boolean }) => useAutoguardado({ activo: p.activo, guardar }), {
    initialProps: { activo },
  });
}

describe("useAutoguardado", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    st().vaciar();
    st().cargar(structuredClone(base));
  });
  afterEach(() => vi.useRealTimers());

  it("inactivo no guarda", async () => {
    const guardar = vi.fn<Guardar>().mockResolvedValue(undefined);
    montar(guardar, false);
    editar(90);
    await avanzar(10_000);
    expect(guardar).not.toHaveBeenCalled();
    expect(st().sucio).toBe(true);
  });

  it("espera 2 s desde la última edición", async () => {
    const guardar = vi.fn<Guardar>().mockResolvedValue(undefined);
    montar(guardar);
    editar(90);
    await avanzar(1000);
    editar(110);
    await avanzar(1999);
    expect(guardar).not.toHaveBeenCalled();
    await avanzar(1);
    expect(guardar).toHaveBeenCalledTimes(1);
    expect(xGuardada(guardar, 0)).toBe(110);
    expect(st().sucio).toBe(false);
  });

  it("una edición durante el guardado deja sucio y vuelve a guardar", async () => {
    const primero = diferido();
    const guardar = vi.fn<Guardar>().mockReturnValueOnce(primero.promesa).mockResolvedValue(undefined);
    montar(guardar);
    editar(110);
    await avanzar(2000);
    expect(guardar).toHaveBeenCalledTimes(1);
    editar(120);
    primero.resolver();
    await avanzar(0);
    expect(st().sucio).toBe(true);
    await avanzar(2000);
    expect(guardar).toHaveBeenCalledTimes(2);
    expect(xGuardada(guardar, 1)).toBe(120);
    expect(st().sucio).toBe(false);
  });

  it("los guardados van en serie", async () => {
    const primero = diferido();
    const guardar = vi.fn<Guardar>().mockReturnValueOnce(primero.promesa).mockResolvedValue(undefined);
    montar(guardar);
    editar(110);
    await avanzar(2000);
    editar(120);
    await avanzar(2000);
    expect(guardar).toHaveBeenCalledTimes(1);
    primero.resolver();
    await avanzar(0);
    expect(guardar).toHaveBeenCalledTimes(2);
  });

  it("un error deja sucio y no reintenta solo", async () => {
    const guardar = vi.fn<Guardar>().mockRejectedValue(new Error("500"));
    const { result } = montar(guardar);
    editar(110);
    await avanzar(2000);
    expect(result.current.error?.message).toBe("500");
    expect(st().sucio).toBe(true);
    await avanzar(10_000);
    expect(guardar).toHaveBeenCalledTimes(1);
  });

  it("guardarAhora con mensaje guarda aunque no haya cambios", async () => {
    const guardar = vi.fn<Guardar>().mockResolvedValue(undefined);
    const { result } = montar(guardar);
    await act(() => result.current.guardarAhora("Portada lista"));
    expect(guardar).toHaveBeenCalledWith(expect.objectContaining({ v: 2 }), "Portada lista");
  });

  it("guardarAhora con mensaje propaga el error", async () => {
    const guardar = vi.fn<Guardar>().mockRejectedValue(new Error("409"));
    const { result } = montar(guardar);
    await act(async () => {
      await expect(result.current.guardarAhora("Portada lista")).rejects.toThrow("409");
    });
    expect(result.current.error?.message).toBe("409");
  });

  it("beforeunload avisa solo con cambios sin guardar", () => {
    const guardar = vi.fn<Guardar>().mockResolvedValue(undefined);
    montar(guardar, false);
    const limpio = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(limpio);
    expect(limpio.defaultPrevented).toBe(false);
    editar(90);
    const sucio = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(sucio);
    expect(sucio.defaultPrevented).toBe(true);
  });
});
```

- [ ] **Step 2: correr y ver que falla**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test hooks/__tests__/use-autoguardado.test.tsx
```

Esperado: falla con `Failed to resolve import "../use-autoguardado"`.

- [ ] **Step 3: implementar `use-autoguardado.ts`**

`frontend/hooks/use-autoguardado.ts`:

```ts
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Escena } from "@/lib/escena";
import { useEditor } from "@/stores/editor";

type Guardar = (escena: Escena, mensaje?: string) => Promise<unknown>;

// Guarda la escena 2 s después de la última edición. Los guardados van en
// fila: nunca hay dos PATCH en vuelo, y el que termina marca como guardada
// la revisión que mandó, no la actual.
export function useAutoguardado({
  activo,
  guardar,
  retraso = 2000,
}: {
  activo: boolean;
  guardar: Guardar;
  retraso?: number;
}) {
  const sucio = useEditor((s) => s.sucio);
  const revision = useEditor((s) => s.revision);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  // La mutación cambia de identidad en cada render; el temporizador no debe
  // reiniciarse por eso.
  const guardarRef = useRef(guardar);
  useEffect(() => {
    guardarRef.current = guardar;
  });
  const cola = useRef<Promise<void>>(Promise.resolve());

  const guardarAhora = useCallback((mensaje?: string): Promise<void> => {
    const correr = async () => {
      const { escena, sucio, revision } = useEditor.getState();
      if (!escena || (!sucio && !mensaje)) return;
      setGuardando(true);
      try {
        await guardarRef.current(escena, mensaje);
        useEditor.getState().marcarGuardado(revision);
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e : new Error(String(e)));
        // Un autoguardado que falla se queda en `error`; el que pidió la
        // persona con mensaje necesita saber que falló.
        if (mensaje) throw e;
      } finally {
        setGuardando(false);
      }
    };
    const p = cola.current.then(correr);
    cola.current = p.catch(() => {});
    return p;
  }, []);

  useEffect(() => {
    if (!activo || !sucio) return;
    const t = setTimeout(() => void guardarAhora(), retraso);
    return () => clearTimeout(t);
  }, [activo, sucio, revision, retraso, guardarAhora]);

  useEffect(() => {
    if (!sucio) return;
    const avisar = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", avisar);
    return () => window.removeEventListener("beforeunload", avisar);
  }, [sucio]);

  return { guardando, error, guardarAhora };
}
```

Notas:
- Un error no reprograma nada porque `error` no está en las dependencias del debounce. La siguiente edición cambia `revision` y sí agenda otro intento.
- `cola.current = p.catch(() => {})` evita que un rechazo corte la fila; quien llamó sigue recibiendo `p` con su error.

- [ ] **Step 4: prueba que falla de los atajos**

`frontend/hooks/__tests__/use-atajos.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import datos from "@/lib/__fixtures__/ops-casos.json";
import { ordenadas, type Escena } from "@/lib/escena";
import { useEditor } from "@/stores/editor";
import { useAtajos } from "../use-atajos";

const base = datos.base as unknown as Escena;
const st = () => useEditor.getState();
const capa = (id: string) => st().escena!.capas.find((c) => c.id === id)!;
const hojas = (e: Escena) => ordenadas(e).filter((c) => c.tipo !== "group").map((c) => c.id);
const tecla = (key: string, extra: Partial<KeyboardEventInit> & { code?: string } = {}) =>
  fireEvent.keyDown(window, { key, ...extra });

function Arnes() {
  useAtajos();
  return <input aria-label="nombre" />;
}

describe("useAtajos", () => {
  beforeEach(() => {
    st().vaciar();
    st().cargar(structuredClone(base));
    render(<Arnes />);
  });

  it("deshacer y rehacer con ⌘ o Ctrl", () => {
    st().aplicar([{ op: "set", capa: "titulo", ruta: "x", valor: 10 }]);
    tecla("z", { metaKey: true });
    expect(capa("titulo").x).toBe(80);
    tecla("Z", { metaKey: true, shiftKey: true });
    expect(capa("titulo").x).toBe(10);
    tecla("z", { ctrlKey: true });
    expect(capa("titulo").x).toBe(80);
    tecla("y", { ctrlKey: true });
    expect(capa("titulo").x).toBe(10);
  });

  it("las flechas mueven 1 px y con shift 10 px", () => {
    st().seleccionar(["titulo"]);
    tecla("ArrowRight");
    expect(capa("titulo").x).toBe(81);
    tecla("ArrowDown", { shiftKey: true });
    expect(capa("titulo").y).toBe(206);
  });

  it("Escape quita la selección", () => {
    st().seleccionar(["titulo"]);
    tecla("Escape");
    expect(st().seleccion).toEqual([]);
  });

  it("Supr borra", () => {
    st().seleccionar(["titulo"]);
    tecla("Delete");
    expect(st().escena!.capas).toHaveLength(3);
  });

  it("⌘D duplica y evita el atajo del navegador", () => {
    st().seleccionar(["titulo"]);
    const siguio = tecla("d", { metaKey: true });
    expect(siguio).toBe(false);
    expect(st().escena!.capas).toHaveLength(5);
  });

  it("⌘G agrupa y ⇧⌘G desagrupa", () => {
    st().seleccionar(["titulo", "marca"]);
    tecla("g", { metaKey: true });
    expect(st().escena!.capas).toHaveLength(5);
    tecla("G", { metaKey: true, shiftKey: true });
    expect(st().escena!.capas).toHaveLength(4);
  });

  it("⌘[ baja por code, no por key", () => {
    st().seleccionar(["titulo"]);
    tecla("[", { metaKey: true, code: "BracketLeft" });
    expect(hojas(st().escena!)).toEqual(["caja", "titulo", "logo"]);
  });

  it("⌘C y ⌘V pegan una copia", () => {
    st().seleccionar(["titulo"]);
    tecla("c", { metaKey: true });
    tecla("v", { metaKey: true });
    expect(st().escena!.capas).toHaveLength(5);
  });

  it("no actúa con un campo de texto enfocado", () => {
    st().seleccionar(["titulo"]);
    const siguio = fireEvent.keyDown(screen.getByRole("textbox", { name: "nombre" }), { key: "Backspace" });
    expect(siguio).toBe(true);
    expect(st().escena!.capas).toHaveLength(4);
  });

  it("no actúa mientras se edita un texto en el lienzo", () => {
    st().seleccionar(["titulo"]);
    st().editarTexto("titulo");
    tecla("Delete");
    expect(st().escena!.capas).toHaveLength(4);
  });
});
```

- [ ] **Step 5: correr y ver que falla**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test hooks/__tests__/use-atajos.test.tsx
```

Esperado: falla con `Failed to resolve import "../use-atajos"`.

- [ ] **Step 6: implementar `use-atajos.ts`**

`frontend/hooks/use-atajos.ts`:

```ts
"use client";

import { useEffect } from "react";
import { esCampoDeTexto } from "@/lib/edicion";
import { useEditor, type EstadoEditor } from "@/stores/editor";

type Accion = (s: EstadoEditor) => void;

const FLECHAS: Record<string, [number, number]> = {
  ArrowLeft: [-1, 0],
  ArrowRight: [1, 0],
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
};

// Traduce una tecla a una acción del store. ⌘ en Mac y Ctrl en lo demás
// hacen lo mismo. Los corchetes se leen por `code` porque en teclados en
// español `key` no es "[".
export function accionDe(e: KeyboardEvent): Accion | null {
  if (e.metaKey || e.ctrlKey) {
    if (e.altKey) return null;
    if (e.code === "BracketRight") return (s) => s.ordenarZ(e.shiftKey ? "frente" : "subir");
    if (e.code === "BracketLeft") return (s) => s.ordenarZ(e.shiftKey ? "fondo" : "bajar");
    switch (e.key.toLowerCase()) {
      case "z":
        return e.shiftKey ? (s) => s.rehacer() : (s) => s.deshacer();
      case "y":
        return (s) => s.rehacer();
      case "c":
        return (s) => s.copiar();
      case "v":
        return (s) => s.pegar();
      case "d":
        return (s) => s.duplicar();
      case "g":
        return e.shiftKey ? (s) => s.desagrupar() : (s) => s.agrupar();
      default:
        return null;
    }
  }
  if (e.altKey) return null;
  if (e.key === "Delete" || e.key === "Backspace") return (s) => s.borrar();
  if (e.key === "Escape") return (s) => s.seleccionar([]);
  const flecha = FLECHAS[e.key];
  if (flecha) {
    const paso = e.shiftKey ? 10 : 1;
    return (s) => s.mover(flecha[0] * paso, flecha[1] * paso);
  }
  return null;
}

function ignorar(e: KeyboardEvent, s: EstadoEditor): boolean {
  if (!s.escena || s.editandoTexto) return true;
  if (esCampoDeTexto(e.target)) return true;
  return e.target instanceof Element && e.target.closest('[role="dialog"],[role="alertdialog"]') !== null;
}

export function useAtajos() {
  useEffect(() => {
    const alTeclear = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return;
      const s = useEditor.getState();
      if (ignorar(e, s)) return;
      const accion = accionDe(e);
      if (!accion) return;
      e.preventDefault();
      accion(s);
    };
    window.addEventListener("keydown", alTeclear);
    return () => window.removeEventListener("keydown", alTeclear);
  }, []);
}
```

Notas:
- `fireEvent.keyDown(window, …)` llega con `target === window`, que no es `Element`: no se ignora. En el navegador, sin foco, el `target` es `body`.
- El `textarea` del editor de texto (Task 8) y el renombrado del panel de capas (Task 9) ya hacen `stopPropagation`; `editandoTexto` y `esCampoDeTexto` cubren el resto.

- [ ] **Step 7: verde**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test hooks/__tests__/use-autoguardado.test.tsx hooks/__tests__/use-atajos.test.tsx && pnpm exec tsc --noEmit && pnpm lint
```

Esperado: `8 passed` y `10 passed`; tsc y lint limpios.

- [ ] **Step 8: commit**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2
git add frontend/hooks/use-autoguardado.ts frontend/hooks/use-atajos.ts frontend/hooks/__tests__/use-autoguardado.test.tsx frontend/hooks/__tests__/use-atajos.test.tsx
git commit -F - <<'EOF'
editor v2: autoguardado en serie y atajos de teclado

El autoguardado espera 2 s desde la última edición, manda un PATCH a la
vez y marca guardada la revisión que mandó: lo que se edita mientras
guarda queda pendiente. Los atajos aceptan ⌘ o Ctrl y no se meten con
campos de texto ni diálogos.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

## Task 12: el editor completo (`page.tsx`, barra superior, versiones, vista previa)

**Files:**
- Create: `frontend/app/b/[slug]/templates/[id]/_components/barra-superior.tsx`
- Create: `frontend/app/b/[slug]/templates/[id]/_components/dialogo-versiones.tsx`
- Create: `frontend/app/b/[slug]/templates/[id]/_components/vista-previa.tsx`
- Create: `frontend/app/b/[slug]/templates/[id]/_components/__tests__/barra-superior.test.tsx`
- Create: `frontend/app/b/[slug]/templates/[id]/_components/__tests__/dialogo-versiones.test.tsx`
- Modify: `frontend/app/b/[slug]/templates/[id]/page.tsx` (se reescribe)
- Modify: `frontend/hooks/use-disenos.ts` (tipos: `Layout` → `Escena`, `Aspecto` con 1:1)
- Delete: `frontend/app/b/[slug]/templates/[id]/_components/v1/` (la movió el Task 6)

**Interfaces:**

```ts
// hooks/use-disenos.ts (cambios)
export type Aspecto = "4:5" | "1:1" | "9:16";
export interface Diseno { /* … */ aspecto: Aspecto; estado: PlantillaLista["estado"]; layout: Escena | null; /* … */ }
// useCrearDiseno, useGuardarDiseno y usePreviaDiseno reciben `layout: Escena`.

// _components/barra-superior.tsx
export function BarraSuperior(props: {
  estado: Diseno["estado"];
  guardando: boolean;
  errorGuardado?: Error | null;
  onGuardarVersion(mensaje: string): Promise<void>;
  onActivar(): void;
  activando: boolean;
  extra?: ReactNode;                     // vista previa y versiones
}): JSX.Element | null;

// _components/dialogo-versiones.tsx
export function ListaVersiones(props: {
  versiones: VersionDiseno[];
  versionActual: number;
  ocupado: boolean;
  onRestaurar(version: number): void;
}): JSX.Element;
export function DialogoVersiones(props: {
  slug: string;
  id: number;
  versionActual: number;
  ocupado: boolean;                      // true mientras se guarda (D14)
  onRestaurado(diseno: Diseno): void;
}): JSX.Element;

// _components/vista-previa.tsx
export function VistaPrevia(props: { slug: string; contrato: ContratoPlantilla }): JSX.Element;
```

- La barra lee del store `escena`, `seleccion`, `sucio`, `pasado` y `futuro`. Formato, deshacer, alinear y distribuir son acciones del store; guardar versión y activar los decide `page.tsx`.
- Texto de estado (`data-testid="estado-guardado"`): «Guardando…» › «No se pudo guardar» › «Cambios sin guardar» › «Guardado», en ese orden de prioridad.
- `Badge data-testid="estado-diseno"`: «Publicado», «Borrador» o «Archivado». El botón «Activar» no aparece si el diseño ya está activo.
- Autoguardado solo en `borrador` (D12). En un diseño activo cada cambio se guarda con «Guardar versión», porque el PATCH de un activo cambia lo que se publica.
- Activar guarda primero lo pendiente. Si el guardado falla, no activa.
- Restaurar carga la escena que devuelve el backend con `cargar`, que vacía la historia y deja `sucio` en `false`. Está deshabilitado mientras se guarda (D14).
- La vista previa manda el `aspecto` del formato actual del lienzo, no el de la columna (D13).

- [ ] **Step 1: tipos de `use-disenos.ts`**

En `frontend/hooks/use-disenos.ts`:

1. Cambiar la línea 5 `import type { Layout } from "@/lib/layout";` por:

```ts
import type { Escena } from "@/lib/escena";
```

2. En `interface Diseno`, cambiar `aspecto: string;`, `estado: string;` y `layout: Layout | null;` por:

```ts
  aspecto: Aspecto;
  estado: PlantillaLista["estado"];
  layout: Escena | null;
```

3. Cambiar `type Aspecto = "4:5" | "9:16";` por:

```ts
// Columna brand_templates.aspecto. El plan 1 agrega 1:1.
export type Aspecto = "4:5" | "1:1" | "9:16";
```

4. Reemplazar las cuatro apariciones restantes de `Layout` (en `useCrearDiseno`, `useGuardarDiseno` y `usePreviaDiseno`) por `Escena`:

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
sed -i '' 's/layout?: Layout;/layout?: Escena;/; s/{ layout: Layout;/{ layout: Escena;/g' hooks/use-disenos.ts
grep -n 'Layout' hooks/use-disenos.ts
```

Esperado: el `grep` no imprime nada.

`lib/layout.ts` se queda donde está (no se toca en este plan); después de este task ya nadie lo importa.

- [ ] **Step 2: prueba que falla de la barra superior**

`frontend/app/b/[slug]/templates/[id]/_components/__tests__/barra-superior.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import datos from "@/lib/__fixtures__/ops-casos.json";
import type { Escena } from "@/lib/escena";
import { useEditor } from "@/stores/editor";
import { BarraSuperior } from "../barra-superior";

const base = datos.base as unknown as Escena;
const st = () => useEditor.getState();
const capa = (id: string) => st().escena!.capas.find((c) => c.id === id)!;
const boton = (nombre: string) => screen.getByRole("button", { name: nombre }) as HTMLButtonElement;

type Props = Partial<Parameters<typeof BarraSuperior>[0]>;
function montar(props: Props = {}) {
  const onGuardarVersion = vi.fn<(m: string) => Promise<void>>().mockResolvedValue(undefined);
  const onActivar = vi.fn();
  render(
    <BarraSuperior
      estado="borrador"
      guardando={false}
      onGuardarVersion={onGuardarVersion}
      onActivar={onActivar}
      activando={false}
      {...props}
    />,
  );
  return { onGuardarVersion, onActivar };
}

describe("BarraSuperior", () => {
  beforeEach(() => {
    st().vaciar();
    st().cargar(structuredClone(base));
  });

  it("cambia el formato del lienzo", () => {
    montar();
    expect(boton("4:5").getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(boton("1:1"));
    expect(st().escena!.lienzo.formato).toBe("1x1");
  });

  it("deshacer se habilita con historia", () => {
    montar();
    expect(boton("Deshacer").disabled).toBe(true);
    // El store cambia fuera de React; la barra se suscribe y se vuelve a pintar.
    fireEvent.click(boton("1:1"));
    expect(boton("Deshacer").disabled).toBe(false);
    fireEvent.click(boton("Deshacer"));
    expect(st().escena!.lienzo.formato).toBe("4x5");
  });

  it("alinea una capa al lienzo", () => {
    st().seleccionar(["titulo"]);
    montar();
    fireEvent.click(boton("Alinear abajo"));
    expect(capa("titulo").y).toBe(1050);
  });

  it("distribuir pide tres capas", () => {
    st().seleccionar(["titulo"]);
    montar();
    expect(boton("Distribuir en horizontal").disabled).toBe(true);
    expect(boton("Alinear a la izquierda").disabled).toBe(false);
  });

  it("distribuir con tres se habilita", () => {
    st().seleccionar(["titulo", "caja", "logo"]);
    montar();
    expect(boton("Distribuir en vertical").disabled).toBe(false);
  });

  it("el estado de guardado sigue la prioridad", () => {
    const { rerender } = render(
      <BarraSuperior estado="borrador" guardando={false} onGuardarVersion={vi.fn()} onActivar={vi.fn()} activando={false} />,
    );
    const estado = () => screen.getByTestId("estado-guardado").textContent;
    expect(estado()).toBe("Guardado");
    fireEvent.click(boton("1:1"));
    expect(estado()).toBe("Cambios sin guardar");
    rerender(
      <BarraSuperior estado="borrador" guardando={false} errorGuardado={new Error("500")} onGuardarVersion={vi.fn()} onActivar={vi.fn()} activando={false} />,
    );
    expect(estado()).toBe("No se pudo guardar");
    rerender(
      <BarraSuperior estado="borrador" guardando errorGuardado={new Error("500")} onGuardarVersion={vi.fn()} onActivar={vi.fn()} activando={false} />,
    );
    expect(estado()).toBe("Guardando…");
  });

  it("el badge dice el estado y Activar solo aparece si no está activo", () => {
    const { onActivar } = montar({ estado: "borrador" });
    expect(screen.getByTestId("estado-diseno").textContent).toBe("Borrador");
    fireEvent.click(boton("Activar"));
    expect(onActivar).toHaveBeenCalledTimes(1);
  });

  it("un diseño activo no muestra Activar", () => {
    montar({ estado: "activa" });
    expect(screen.getByTestId("estado-diseno").textContent).toBe("Publicado");
    expect(screen.queryByRole("button", { name: "Activar" })).toBeNull();
  });

  it("guardar versión pide un mensaje y cierra al terminar", async () => {
    const { onGuardarVersion } = montar();
    fireEvent.click(boton("Guardar versión"));
    expect(boton("Guardar").disabled).toBe(true);
    fireEvent.change(screen.getByRole("textbox", { name: "Mensaje de la versión" }), {
      target: { value: "  Portada lista  " },
    });
    fireEvent.click(boton("Guardar"));
    expect(onGuardarVersion).toHaveBeenCalledWith("Portada lista");
    expect(await screen.findByRole("button", { name: "Guardar versión" })).not.toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("si guardar versión falla, el diálogo sigue abierto", async () => {
    const falla = vi.fn<(m: string) => Promise<void>>().mockRejectedValue(new Error("409"));
    montar({ onGuardarVersion: falla });
    fireEvent.click(boton("Guardar versión"));
    fireEvent.change(screen.getByRole("textbox", { name: "Mensaje de la versión" }), { target: { value: "x" } });
    fireEvent.click(boton("Guardar"));
    expect(falla).toHaveBeenCalledWith("x");
    expect(await screen.findByRole("dialog")).not.toBeNull();
    await vi.waitFor(() => expect(boton("Guardar").disabled).toBe(false));
  });
});
```

- [ ] **Step 3: prueba que falla de la lista de versiones**

`frontend/app/b/[slug]/templates/[id]/_components/__tests__/dialogo-versiones.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { VersionDiseno } from "@/hooks/use-disenos";
import { ListaVersiones } from "../dialogo-versiones";

const versiones: VersionDiseno[] = [
  { version: 4, mensaje: null, creado_en: "2026-10-06T12:04:00" },
  { version: 3, mensaje: "Portada lista", creado_en: "2026-10-06T12:03:00" },
  { version: 2, mensaje: null, creado_en: "2026-10-06T12:02:00" },
  { version: 1, mensaje: "Primera", creado_en: "2026-10-06T12:01:00" },
];
const restaurar = (n: number) => screen.queryByRole("button", { name: `Restaurar versión ${n}` }) as HTMLButtonElement | null;

describe("ListaVersiones", () => {
  it("esconde los autoguardados hasta pedirlos", () => {
    render(<ListaVersiones versiones={versiones} versionActual={4} ocupado={false} onRestaurar={vi.fn()} />);
    expect(restaurar(3)).not.toBeNull();
    expect(restaurar(2)).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: "Ver autoguardados" }));
    expect(restaurar(2)).not.toBeNull();
  });

  it("restaura otra versión y no la actual", () => {
    const onRestaurar = vi.fn();
    render(<ListaVersiones versiones={versiones} versionActual={3} ocupado={false} onRestaurar={onRestaurar} />);
    expect(restaurar(3)!.disabled).toBe(true);
    fireEvent.click(restaurar(1)!);
    expect(onRestaurar).toHaveBeenCalledWith(1);
  });

  it("no restaura mientras se guarda", () => {
    render(<ListaVersiones versiones={versiones} versionActual={4} ocupado onRestaurar={vi.fn()} />);
    expect(restaurar(1)!.disabled).toBe(true);
  });
});
```

- [ ] **Step 4: correr y ver que fallan**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test "app/b/[slug]/templates/[id]/_components/__tests__/barra-superior.test.tsx" "app/b/[slug]/templates/[id]/_components/__tests__/dialogo-versiones.test.tsx"
```

Esperado: fallan con `Failed to resolve import "../barra-superior"` y `"../dialogo-versiones"`.

- [ ] **Step 5: implementar `barra-superior.tsx`**

`frontend/app/b/[slug]/templates/[id]/_components/barra-superior.tsx`:

```tsx
"use client";

import { useState, type ReactNode } from "react";
import {
  AlignCenterHorizontal,
  AlignCenterVertical,
  AlignEndHorizontal,
  AlignEndVertical,
  AlignHorizontalDistributeCenter,
  AlignStartHorizontal,
  AlignStartVertical,
  AlignVerticalDistributeCenter,
  Redo2,
  Undo2,
  type LucideIcon,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import type { Diseno } from "@/hooks/use-disenos";
import type { ModoAlinear } from "@/lib/edicion";
import type { Formato } from "@/lib/escena";
import { useEditor } from "@/stores/editor";

const FORMATOS: { valor: Formato; nombre: string }[] = [
  { valor: "4x5", nombre: "4:5" },
  { valor: "1x1", nombre: "1:1" },
  { valor: "9x16", nombre: "9:16" },
];

const ALINEAR: { modo: ModoAlinear; nombre: string; Icono: LucideIcon }[] = [
  { modo: "izq", nombre: "Alinear a la izquierda", Icono: AlignStartVertical },
  { modo: "centro-h", nombre: "Centrar en horizontal", Icono: AlignCenterVertical },
  { modo: "der", nombre: "Alinear a la derecha", Icono: AlignEndVertical },
  { modo: "arriba", nombre: "Alinear arriba", Icono: AlignStartHorizontal },
  { modo: "centro-v", nombre: "Centrar en vertical", Icono: AlignCenterHorizontal },
  { modo: "abajo", nombre: "Alinear abajo", Icono: AlignEndHorizontal },
];

const ETIQUETA_ESTADO: Record<Diseno["estado"], string> = {
  activa: "Publicado",
  borrador: "Borrador",
  archivada: "Archivado",
};

function Icono({ nombre, onClick, disabled, children }: {
  nombre: string;
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <Button type="button" variant="ghost" size="icon" aria-label={nombre} title={nombre} disabled={disabled} onClick={onClick}>
      {children}
    </Button>
  );
}

export function BarraSuperior({
  estado,
  guardando,
  errorGuardado,
  onGuardarVersion,
  onActivar,
  activando,
  extra,
}: {
  estado: Diseno["estado"];
  guardando: boolean;
  errorGuardado?: Error | null;
  onGuardarVersion: (mensaje: string) => Promise<void>;
  onActivar: () => void;
  activando: boolean;
  extra?: ReactNode;
}) {
  const formato = useEditor((s) => s.escena?.lienzo.formato);
  const nSeleccion = useEditor((s) => s.seleccion.length);
  const sucio = useEditor((s) => s.sucio);
  const hayPasado = useEditor((s) => s.pasado.length > 0);
  const hayFuturo = useEditor((s) => s.futuro.length > 0);
  const st = useEditor.getState;

  const [abierto, setAbierto] = useState(false);
  const [mensaje, setMensaje] = useState("");
  const [enviando, setEnviando] = useState(false);

  if (!formato) return null;

  const textoEstado = guardando
    ? "Guardando…"
    : errorGuardado
      ? "No se pudo guardar"
      : sucio
        ? "Cambios sin guardar"
        : "Guardado";

  async function confirmar() {
    const m = mensaje.trim();
    if (!m) return;
    setEnviando(true);
    try {
      await onGuardarVersion(m);
      setAbierto(false);
      setMensaje("");
    } catch {
      // page.tsx ya avisó con un toast; el diálogo sigue abierto para reintentar.
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 border-b pb-2">
      <div className="flex items-center gap-1" role="group" aria-label="Formato">
        {FORMATOS.map((f) => (
          <Button
            key={f.valor}
            type="button"
            size="sm"
            variant={formato === f.valor ? "default" : "outline"}
            aria-pressed={formato === f.valor}
            onClick={() => st().cambiarFormato(f.valor)}
          >
            {f.nombre}
          </Button>
        ))}
      </div>

      <div className="flex items-center">
        <Icono nombre="Deshacer" disabled={!hayPasado} onClick={() => st().deshacer()}>
          <Undo2 className="size-4" />
        </Icono>
        <Icono nombre="Rehacer" disabled={!hayFuturo} onClick={() => st().rehacer()}>
          <Redo2 className="size-4" />
        </Icono>
      </div>

      <div className="flex items-center">
        {ALINEAR.map(({ modo, nombre, Icono: Ico }) => (
          <Icono key={modo} nombre={nombre} disabled={nSeleccion === 0} onClick={() => st().alinear(modo)}>
            <Ico className="size-4" />
          </Icono>
        ))}
        <Icono nombre="Distribuir en horizontal" disabled={nSeleccion < 3} onClick={() => st().distribuir("h")}>
          <AlignHorizontalDistributeCenter className="size-4" />
        </Icono>
        <Icono nombre="Distribuir en vertical" disabled={nSeleccion < 3} onClick={() => st().distribuir("v")}>
          <AlignVerticalDistributeCenter className="size-4" />
        </Icono>
      </div>

      <div className="ml-auto flex items-center gap-2">
        <span data-testid="estado-guardado" aria-live="polite" className="text-xs text-muted-foreground">
          {textoEstado}
        </span>
        <Badge data-testid="estado-diseno" variant={estado === "activa" ? "default" : "secondary"}>
          {ETIQUETA_ESTADO[estado]}
        </Badge>
        {extra}
        <Button type="button" size="sm" variant="outline" onClick={() => setAbierto(true)}>
          Guardar versión
        </Button>
        {estado !== "activa" && (
          <Button type="button" size="sm" disabled={activando} onClick={onActivar}>
            Activar
          </Button>
        )}
      </div>

      <Dialog open={abierto} onOpenChange={(v) => !enviando && setAbierto(v)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Guardar versión</DialogTitle>
            <DialogDescription>Un nombre corto para encontrarla después en el historial.</DialogDescription>
          </DialogHeader>
          <Input
            aria-label="Mensaje de la versión"
            value={mensaje}
            maxLength={120}
            autoFocus
            onChange={(e) => setMensaje(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void confirmar();
            }}
          />
          <DialogFooter>
            <Button type="button" disabled={enviando || mensaje.trim().length === 0} onClick={() => void confirmar()}>
              Guardar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
```

Notas:
- El texto de estado no lleva `role="status"`: sonner también pinta regiones vivas y la e2e chocaría. Se ubica por `data-testid`.
- ⚠️ Los nombres de íconos de lucide (`AlignStartVertical`, `AlignHorizontalDistributeCenter`, etc.) no se verificaron contra la versión instalada. Si alguno no existe, tsc lo marca; se sustituye por el más cercano de `node_modules/lucide-react/dist/lucide-react.d.ts`.

- [ ] **Step 6: implementar `dialogo-versiones.tsx`**

`frontend/app/b/[slug]/templates/[id]/_components/dialogo-versiones.tsx`:

```tsx
"use client";

import { useState } from "react";
import { History } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { useRevertir, useVersiones, type Diseno, type VersionDiseno } from "@/hooks/use-disenos";

const FECHA = new Intl.DateTimeFormat("es-MX", { dateStyle: "medium", timeStyle: "short" });

export function ListaVersiones({
  versiones,
  versionActual,
  ocupado,
  onRestaurar,
}: {
  versiones: VersionDiseno[];
  versionActual: number;
  ocupado: boolean;
  onRestaurar: (version: number) => void;
}) {
  // Cada autoguardado es una versión sin mensaje (D1). Se esconden para que
  // el historial muestre lo que la persona guardó a propósito.
  const [verTodas, setVerTodas] = useState(false);
  const visibles = versiones.filter((v) => verTodas || v.mensaje !== null || v.version === versionActual);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Checkbox id="ver-autoguardados" checked={verTodas} onCheckedChange={(v) => setVerTodas(v === true)} />
        <Label htmlFor="ver-autoguardados" className="text-sm">
          Ver autoguardados
        </Label>
      </div>
      <ul className="max-h-80 divide-y overflow-y-auto rounded-md border">
        {visibles.map((v) => (
          <li key={v.version} className="flex items-center justify-between gap-3 px-3 py-2">
            <div className="min-w-0">
              <p className="truncate text-sm">
                {v.mensaje ?? "Autoguardado"}
                {v.version === versionActual && <span className="text-muted-foreground"> · actual</span>}
              </p>
              <p className="text-xs text-muted-foreground">
                v{v.version} · {FECHA.format(new Date(v.creado_en))}
              </p>
            </div>
            <Button
              type="button"
              size="sm"
              variant="outline"
              aria-label={`Restaurar versión ${v.version}`}
              disabled={ocupado || v.version === versionActual}
              onClick={() => onRestaurar(v.version)}
            >
              Restaurar
            </Button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function DialogoVersiones({
  slug,
  id,
  versionActual,
  ocupado,
  onRestaurado,
}: {
  slug: string;
  id: number;
  versionActual: number;
  ocupado: boolean;
  onRestaurado: (diseno: Diseno) => void;
}) {
  const [abierto, setAbierto] = useState(false);
  const versiones = useVersiones(slug, id);
  const revertir = useRevertir(slug, id);

  return (
    <Dialog open={abierto} onOpenChange={setAbierto}>
      <DialogTrigger asChild>
        <Button type="button" size="sm" variant="ghost">
          <History className="size-4" />
          Versiones
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Versiones</DialogTitle>
          <DialogDescription>Restaurar crea una versión nueva con el contenido de la elegida.</DialogDescription>
        </DialogHeader>
        {versiones.isLoading && <p className="text-sm text-muted-foreground">Cargando…</p>}
        {versiones.isError && <p className="text-sm text-muted-foreground">No se pudo cargar el historial.</p>}
        {versiones.data && (
          <ListaVersiones
            versiones={versiones.data}
            versionActual={versionActual}
            ocupado={ocupado || revertir.isPending}
            onRestaurar={(v) =>
              revertir.mutate(v, {
                onSuccess: (d) => {
                  onRestaurado(d);
                  setAbierto(false);
                  toast.success(`Versión ${v} restaurada`);
                },
                onError: () => toast.error("No se pudo restaurar la versión."),
              })
            }
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 7: implementar `vista-previa.tsx`**

`frontend/app/b/[slug]/templates/[id]/_components/vista-previa.tsx`:

```tsx
"use client";

import { useState } from "react";
import { Eye } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { resultadoDeJob, usePreviaDiseno, type ContratoPlantilla } from "@/hooks/use-disenos";
import { useJob } from "@/hooks/use-job";
import { ASPECTO_DE_FORMATO } from "@/lib/escena";
import { useEditor } from "@/stores/editor";

// Renderiza la escena tal como está en el editor, sin guardarla. El aspecto
// sale del formato del lienzo, no de la columna del diseño (D13).
export function VistaPrevia({ slug, contrato }: { slug: string; contrato: ContratoPlantilla }) {
  const previa = usePreviaDiseno(slug);
  const [jobId, setJobId] = useState<number | null>(null);
  const job = useJob(slug, jobId);
  const url = resultadoDeJob<{ url: string }>(job.data)?.url;
  const fallo = previa.isError || job.data?.estado === "error" || job.data?.estado === "cancelado";

  function pedir() {
    const escena = useEditor.getState().escena;
    if (!escena) return;
    const aspecto = ASPECTO_DE_FORMATO[escena.lienzo.formato];
    setJobId(null);
    previa.mutate(
      { layout: escena, aspecto, contrato: { ...contrato, aspecto } },
      { onSuccess: (r) => setJobId(r.job_id) },
    );
  }

  return (
    <Dialog onOpenChange={(abierto) => abierto && pedir()}>
      <DialogTrigger asChild>
        <Button type="button" size="sm" variant="ghost">
          <Eye className="size-4" />
          Vista previa
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Vista previa</DialogTitle>
        </DialogHeader>
        {fallo ? (
          <p className="text-sm text-muted-foreground">No se pudo generar la vista previa.</p>
        ) : url ? (
          // eslint-disable-next-line @next/next/no-img-element -- PNG servido por la API vía rewrite
          <img src={`/api${url}`} alt="Vista previa del diseño" className="max-h-[70dvh] w-full object-contain" />
        ) : (
          <Skeleton className="aspect-[4/5] w-full" />
        )}
      </DialogContent>
    </Dialog>
  );
}
```

Notas:
- `useJob(slug, jid: number | null)` (`hooks/use-job.ts:37`) no consulta con `null`.
- Sin prueba unitaria: lo que tiene de lógica es el `aspecto` (una línea) y lo demás es la cola de jobs, que ya cubre el backend. La e2e del Task 15 no la abre.

- [ ] **Step 8: reescribir `page.tsx`**

`frontend/app/b/[slug]/templates/[id]/page.tsx`:

```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Lock } from "lucide-react";
import { toast } from "sonner";
import { Skeleton } from "@/components/ui/skeleton";
import { useAtajos } from "@/hooks/use-atajos";
import { useAutoguardado } from "@/hooks/use-autoguardado";
import { useBrand } from "@/hooks/use-brands";
import { useActivarDiseno, useDiseno, useGuardarDiseno } from "@/hooks/use-disenos";
import { useEditor } from "@/stores/editor";
import { BarraSuperior } from "./_components/barra-superior";
import { DialogoVersiones } from "./_components/dialogo-versiones";
import { Lienzo } from "./_components/lienzo";
import { PanelCapas } from "./_components/panel-capas";
import { PanelLateral } from "./_components/panel-lateral";
import { PanelPropiedades } from "./_components/panel-propiedades";
import { VistaPrevia } from "./_components/vista-previa";

export default function DisenoPage() {
  const { slug, id } = useParams<{ slug: string; id: string }>();
  const disenoId = Number(id);

  const disenoQuery = useDiseno(slug, disenoId);
  const marcaQuery = useBrand(slug);
  const guardarMut = useGuardarDiseno(slug, disenoId);
  const activarMut = useActivarDiseno(slug, disenoId);
  const listo = useEditor((s) => s.escena !== null);
  const colorMarca = marcaQuery.data?.color_marca ?? "#000000";

  // Se siembra una sola vez por diseño: un refetch en segundo plano no puede
  // pisar lo que la persona lleva acomodado.
  const sembrado = useRef<number | null>(null);
  const diseno = disenoQuery.data;
  useEffect(() => {
    if (!diseno?.layout || !diseno.editable || sembrado.current === diseno.id) return;
    sembrado.current = diseno.id;
    useEditor.getState().cargar(diseno.layout);
  }, [diseno]);

  // Al salir del editor el store queda vacío para el siguiente diseño. En
  // StrictMode el efecto corre dos veces; `sembrado` en null deja resembrar.
  useEffect(
    () => () => {
      sembrado.current = null;
      useEditor.getState().vaciar();
    },
    [],
  );

  const { guardando, error, guardarAhora } = useAutoguardado({
    activo: diseno?.estado === "borrador" && listo,
    guardar: (escena, mensaje) =>
      guardarMut.mutateAsync(mensaje ? { layout: escena, mensaje } : { layout: escena }),
  });
  useAtajos();
  const [activando, setActivando] = useState(false);

  async function activar() {
    setActivando(true);
    try {
      if (useEditor.getState().sucio) await guardarAhora();
      if (useEditor.getState().sucio) {
        toast.error("No se pudo guardar antes de activar.");
        return;
      }
      await activarMut.mutateAsync();
      toast.success("Diseño publicado");
    } catch {
      toast.error("No se pudo activar el diseño.");
    } finally {
      setActivando(false);
    }
  }

  async function guardarVersion(mensaje: string) {
    try {
      await guardarAhora(mensaje);
      toast.success("Versión guardada");
    } catch (e) {
      toast.error("No se pudo guardar la versión.");
      throw e;
    }
  }

  const volver = (
    <Link
      href={`/b/${slug}/templates`}
      className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="size-4" /> Diseños
    </Link>
  );

  if (disenoQuery.isLoading) {
    return (
      <div className="space-y-3">
        {volver}
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-[560px] w-full max-w-[520px]" />
      </div>
    );
  }

  if (disenoQuery.isError || !diseno) {
    // Un diseño de otra marca contesta 404, nunca 403: desde aquí no se puede
    // ni averiguar que existe.
    const noExiste = disenoQuery.error?.status === 404;
    return (
      <div className="space-y-3">
        {volver}
        <p className="text-sm text-muted-foreground">
          {noExiste
            ? "Ese diseño no existe."
            : "No se pudo cargar el diseño. Intenta de nuevo en un momento."}
        </p>
      </div>
    );
  }

  const encabezado = (
    <div>
      <h1 className="text-xl font-semibold">{diseno.nombre}</h1>
      <p className="text-sm text-muted-foreground">
        {diseno.aspecto === "9:16" ? "Vertical" : "Cuadrada alta"}
      </p>
    </div>
  );

  // Los diseños viejos se hicieron antes del editor y solo tienen su versión
  // ya armada: no hay piezas que mover, así que no se abre el editor.
  if (!diseno.editable || diseno.layout === null) {
    return (
      <div className="space-y-4">
        {volver}
        {encabezado}
        <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed py-14 text-center">
          <Lock className="size-6 text-muted-foreground" />
          <p className="max-w-md text-sm text-muted-foreground">
            Este diseño se hizo antes del editor, así que no se puede acomodar pieza por
            pieza. Duplícalo desde la lista de diseños y edita la copia.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100dvh-7rem)] min-h-[600px] flex-col gap-3">
      <div className="flex flex-wrap items-center gap-4">
        {volver}
        {encabezado}
      </div>
      <BarraSuperior
        estado={diseno.estado}
        guardando={guardando}
        errorGuardado={error}
        onGuardarVersion={guardarVersion}
        onActivar={() => void activar()}
        activando={activando}
        extra={
          <>
            <VistaPrevia slug={slug} contrato={diseno.contrato} />
            <DialogoVersiones
              slug={slug}
              id={disenoId}
              versionActual={diseno.version_actual}
              ocupado={guardando}
              onRestaurado={(d) => {
                if (d.layout) useEditor.getState().cargar(d.layout);
              }}
            />
          </>
        }
      />
      <div className="flex min-h-0 flex-1 gap-3">
        <aside className="w-60 shrink-0 overflow-hidden rounded-lg border">
          <PanelLateral pestanas={[{ id: "capas", etiqueta: "Capas", contenido: <PanelCapas /> }]} />
        </aside>
        <div className="min-w-0 flex-1 overflow-hidden rounded-lg border bg-muted/40">
          <Lienzo slug={slug} colorMarca={colorMarca} />
        </div>
        <aside className="w-72 shrink-0 overflow-y-auto rounded-lg border">
          <PanelPropiedades colorMarca={colorMarca} />
        </aside>
      </div>
    </div>
  );
}
```

Notas:
- `encabezado` deja de ser función porque el botón «Cuadrícula» v1 ya no existe; el texto del aspecto lo generaliza el Task 13.
- `activar` usa `mutateAsync` dentro de `try` en vez de `mutate` con callbacks: así el `finally` apaga `activando` después de las dos llamadas.
- La rejilla v1 no tiene equivalente aquí: las guías y el imán viven en el lienzo (Task 7).

- [ ] **Step 9: borrar el editor v1**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2
git rm -r "frontend/app/b/[slug]/templates/[id]/_components/v1"
grep -rn "_components/v1\|lib/layout" frontend/app frontend/hooks frontend/components
```

Esperado: el `grep` no imprime nada.

- [ ] **Step 10: verde**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test "app/b/[slug]/templates/[id]/_components/__tests__/barra-superior.test.tsx" "app/b/[slug]/templates/[id]/_components/__tests__/dialogo-versiones.test.tsx" && pnpm test && pnpm exec tsc --noEmit && pnpm lint
```

Esperado: `10 passed` y `3 passed`; la corrida completa en verde; tsc y lint limpios.

- [ ] **Step 11: revisión en navegador**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm e2e e2e/lienzo.spec.ts e2e/editor-texto.spec.ts
```

Esperado: verde. Las páginas `app/dev/*` no dependen de `page.tsx`; esto confirma que el borrado del v1 no rompió el lienzo.

- [ ] **Step 12: commit**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2
git add frontend/hooks/use-disenos.ts "frontend/app/b/[slug]/templates/[id]/page.tsx" "frontend/app/b/[slug]/templates/[id]/_components/barra-superior.tsx" "frontend/app/b/[slug]/templates/[id]/_components/dialogo-versiones.tsx" "frontend/app/b/[slug]/templates/[id]/_components/vista-previa.tsx" "frontend/app/b/[slug]/templates/[id]/_components/__tests__/barra-superior.test.tsx" "frontend/app/b/[slug]/templates/[id]/_components/__tests__/dialogo-versiones.test.tsx"
git commit -F - <<'EOF'
editor v2: la pantalla del editor completa y adiós al v1

Barra superior con formato, deshacer, alinear, distribuir, estado de
guardado, versiones, vista previa y activar. El borrador se autoguarda;
el activo solo con «Guardar versión». Se borra el editor v1.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

## Task 13: lista de diseños con «Todos», 1:1 y miniaturas sin recorte

**Files:**
- Create: `frontend/lib/aspecto.ts`
- Create: `frontend/lib/__tests__/aspecto.test.ts`
- Modify: `frontend/hooks/use-disenos.ts` (`useDisenos` acepta `"todas"`)
- Modify: `frontend/hooks/use-templates.ts` (`Plantilla.aspecto` con `"1:1"`)
- Modify: `frontend/app/b/[slug]/templates/page.tsx`
- Modify: `frontend/app/b/[slug]/templates/[id]/page.tsx` (texto del aspecto)
- Modify: `frontend/app/b/[slug]/create/_components/paso-plantilla.tsx` (línea 11)

**Interfaces:**

```ts
// lib/aspecto.ts
export const RELACION_DE_ASPECTO: Record<Aspecto, string>;   // "4/5" | "1/1" | "9/16", para aspect-ratio
export const ETIQUETA_DE_ASPECTO: Record<Aspecto, string>;   // "Cuadrada alta" | "Cuadrada" | "Vertical"

// hooks/use-disenos.ts
export function useDisenos(slug: string, estado?: "activa" | "borrador" | "archivada" | "todas");
```

- `estado=todas` es del plan 1 (índice: «la API … `estado=todas`»). La pestaña «Todos» queda por omisión, porque un diseño recién creado es borrador y hoy no se ve en la vista inicial.
- Las miniaturas pasan a `object-contain`: una 9:16 o 1:1 dentro de la tarjeta 4:5 se ve completa.

- [ ] **Step 1: prueba que falla**

`frontend/lib/__tests__/aspecto.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { ETIQUETA_DE_ASPECTO, RELACION_DE_ASPECTO } from "../aspecto";
import { ASPECTO_DE_FORMATO } from "../escena";

describe("aspecto", () => {
  it("cubre los tres formatos del lienzo", () => {
    const aspectos = Object.values(ASPECTO_DE_FORMATO).sort();
    expect(Object.keys(RELACION_DE_ASPECTO).sort()).toEqual(aspectos);
    expect(Object.keys(ETIQUETA_DE_ASPECTO).sort()).toEqual(aspectos);
  });

  it("la relación es la del aspecto con diagonal", () => {
    expect(RELACION_DE_ASPECTO["9:16"]).toBe("9/16");
    expect(ETIQUETA_DE_ASPECTO["1:1"]).toBe("Cuadrada");
  });
});
```

- [ ] **Step 2: correr y ver que falla**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test lib/__tests__/aspecto.test.ts
```

Esperado: falla con `Failed to resolve import "../aspecto"`.

- [ ] **Step 3: implementar `lib/aspecto.ts`**

`frontend/lib/aspecto.ts`:

```ts
import type { Aspecto } from "@/hooks/use-disenos";

// Para `aspect-ratio` en CSS.
export const RELACION_DE_ASPECTO: Record<Aspecto, string> = {
  "4:5": "4/5",
  "1:1": "1/1",
  "9:16": "9/16",
};

export const ETIQUETA_DE_ASPECTO: Record<Aspecto, string> = {
  "4:5": "Cuadrada alta",
  "1:1": "Cuadrada",
  "9:16": "Vertical",
};
```

- [ ] **Step 4: tipos y usos**

1. `frontend/hooks/use-templates.ts` línea 29: `aspecto: "4:5" | "9:16";` → `aspecto: "4:5" | "1:1" | "9:16";`.

2. `frontend/hooks/use-disenos.ts`, `useDisenos`:

```ts
// GET /brands/{slug}/templates?estado= — por omisión el backend filtra por
// "activa"; se manda solo cuando el llamador pide algo distinto. "todas"
// trae los tres estados (plan 1).
export function useDisenos(slug: string, estado?: PlantillaLista["estado"] | "todas") {
```

3. `frontend/app/b/[slug]/create/_components/paso-plantilla.tsx` línea 11:

```ts
  const relacion = RELACION_DE_ASPECTO[plantilla.aspecto];
```

con `import { RELACION_DE_ASPECTO } from "@/lib/aspecto";` junto a los demás imports.

4. `frontend/app/b/[slug]/templates/[id]/page.tsx`, en `encabezado`:

```tsx
      <p className="text-sm text-muted-foreground">{ETIQUETA_DE_ASPECTO[diseno.aspecto]}</p>
```

con `import { ETIQUETA_DE_ASPECTO } from "@/lib/aspecto";`.

- [ ] **Step 5: la lista de diseños**

En `frontend/app/b/[slug]/templates/page.tsx`:

1. Líneas 28–40: agregar el filtro «Todos» al principio de las pestañas.

```tsx
type EstadoDiseno = "activa" | "borrador" | "archivada";
type Filtro = EstadoDiseno | "todas";

const PESTANAS: { value: Filtro; label: string }[] = [
  { value: "todas", label: "Todos" },
  { value: "activa", label: "Publicados" },
  { value: "borrador", label: "Borradores" },
  { value: "archivada", label: "Archivados" },
];
```

(`ETIQUETA_ESTADO` no cambia: cada tarjeta trae su `estado` real.)

2. Línea 48: `useState<"4:5" | "9:16">("4:5")` → `useState<Aspecto>("4:5")`, con `type Aspecto` agregado al import de `@/hooks/use-disenos`.

3. Líneas 92–107: tres botones con la etiqueta de `lib/aspecto.ts`.

```tsx
            <div className="flex gap-2">
              {(["4:5", "1:1", "9:16"] as const).map((a) => (
                <Button
                  key={a}
                  type="button"
                  variant={aspecto === a ? "default" : "outline"}
                  size="sm"
                  onClick={() => setAspecto(a)}
                >
                  {ETIQUETA_DE_ASPECTO[a]}
                </Button>
              ))}
            </div>
```

con `import { ETIQUETA_DE_ASPECTO } from "@/lib/aspecto";`.

4. Línea 140: `className="size-full object-cover"` → `className="size-full object-contain"`.

5. Líneas 184–185 y 210:

```tsx
  const [estado, setEstado] = useState<Filtro>("todas");
  const disenosQuery = useDisenos(slug, estado);
```

```tsx
      <Tabs value={estado} onValueChange={(v) => setEstado(v as Filtro)}>
```

- [ ] **Step 6: verde**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test lib/__tests__/aspecto.test.ts && pnpm test && pnpm exec tsc --noEmit && pnpm lint
```

Esperado: `2 passed`; la corrida completa en verde; tsc y lint limpios.

- [ ] **Step 7: commit**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2
git add frontend/lib/aspecto.ts frontend/lib/__tests__/aspecto.test.ts frontend/hooks/use-disenos.ts frontend/hooks/use-templates.ts "frontend/app/b/[slug]/templates/page.tsx" "frontend/app/b/[slug]/templates/[id]/page.tsx" "frontend/app/b/[slug]/create/_components/paso-plantilla.tsx"
git commit -F - <<'EOF'
diseños: pestaña «Todos», formato cuadrado y miniaturas completas

La lista abre en «Todos» para que un borrador recién creado se vea. Se
puede crear un diseño 1:1 y las miniaturas ya no recortan los 9:16.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

## Task 14: efectos, borde, tracking y vínculo a datos en el panel de propiedades

**Files:**
- Modify: `frontend/app/b/[slug]/templates/[id]/_components/panel-propiedades.tsx`
- Modify: `frontend/app/b/[slug]/templates/[id]/_components/__tests__/panel-propiedades.test.tsx`
- Modify: `frontend/app/b/[slug]/templates/[id]/page.tsx` (pasa `campos`)

**Interfaces:**

```ts
// _components/panel-propiedades.tsx
export function camposDeContrato(contrato: ContratoPlantilla): { texto: string[]; imagen: string[] };
export function PanelPropiedades(props: {
  colorMarca: string;
  campos?: { texto: string[]; imagen: string[] };   // sin campos no aparece «Dato»
}): JSX.Element | null;
```

- `camposDeContrato`: `texto` son los campos base salvo `imagen`, `logo` y `color_marca`, más los extras que no son `imagen`. `imagen` son `imagen` y `logo` (si están en `base`) más los extras de tipo `imagen`.
- «Dato» (texto, imagen y video): un `select` con «Ninguno» y los campos de su tipo. Va en un solo `aplicar`:
  - al vincular un texto con tramos de color, `estilo.spans` queda en `[]` (el texto lo pone el dato);
  - al desvincular un texto con `resaltar`, `resaltar` queda en `false`;
  - «Ninguno» guarda `campo: null`.
- «Efectos» (imagen, video, svg y forma; D16): «Mezcla» escribe `estilo.mixBlendMode` y «Sombra» escribe `estilo.filter` con uno de cuatro valores fijos.

| Sombra | `estilo.filter` |
|---|---|
| Ninguna | `none` |
| Suave | `drop-shadow(0 8px 16px rgba(0,0,0,.25))` |
| Media | `drop-shadow(0 16px 32px rgba(0,0,0,.3))` |
| Fuerte | `drop-shadow(0 24px 48px rgba(0,0,0,.4))` |

- Un `filter` que no es uno de los cuatro (lo puso el plan 4 o una conversión v1) se muestra como «Personalizada» y no se pisa hasta que se elige otro.
- Forma: «Borde» (`estilo.borderWidth`) y «Color de borde» (`estilo.borderColor`).
- Texto: «Tracking» (`estilo.letterSpacing`) como texto libre: `-0.02em`, `2px` o vacío para quitarlo.

- [ ] **Step 1: pruebas que fallan**

Agregar al final de `frontend/app/b/[slug]/templates/[id]/_components/__tests__/panel-propiedades.test.tsx`, y cambiar sus imports a:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import datos from "@/lib/__fixtures__/ops-casos.json";
import type { CapaForma, CapaTexto, Escena } from "@/lib/escena";
import { useEditor } from "@/stores/editor";
import { camposDeContrato, PanelPropiedades } from "../panel-propiedades";
```

```tsx
const CAMPOS = { texto: ["titular", "handle"], imagen: ["imagen", "logo"] };

function montarConCampos(seleccion: string[]) {
  st().vaciar();
  st().cargar(structuredClone(base));
  st().seleccionar(seleccion);
  render(<PanelPropiedades colorMarca="#ff3366" campos={CAMPOS} />);
}
const combo = (nombre: string) => screen.getByRole("combobox", { name: nombre }) as HTMLSelectElement;

describe("camposDeContrato", () => {
  it("separa texto de imagen y suma los extras por tipo", () => {
    expect(
      camposDeContrato({
        aspecto: "4:5",
        base: ["titular", "imagen", "handle", "logo", "color_marca"],
        extras: [
          { id: "precio", tipo: "numero" },
          { id: "foto2", tipo: "imagen" },
        ],
      }),
    ).toEqual({ texto: ["titular", "handle", "precio"], imagen: ["imagen", "logo", "foto2"] });
  });
});

describe("PanelPropiedades: efectos y datos", () => {
  beforeEach(() => st().vaciar());

  it("sin campos no muestra Dato", () => {
    montar(["titulo"]);
    expect(screen.queryByRole("combobox", { name: "Dato" })).toBeNull();
  });

  it("vincular un texto limpia sus tramos en un paso", () => {
    st().vaciar();
    st().cargar(structuredClone(base));
    st().aplicar([{ op: "set", capa: "titulo", ruta: "estilo.spans", valor: [{ desde: 0, hasta: 4, color: "#ff0000" }] }]);
    st().seleccionar(["titulo"]);
    render(<PanelPropiedades colorMarca="#ff3366" campos={CAMPOS} />);
    const antes = st().pasado.length;
    expect([...combo("Dato").options].map((o) => o.value)).toEqual(["", "titular", "handle"]);
    fireEvent.change(combo("Dato"), { target: { value: "titular" } });
    const t = capa("titulo") as CapaTexto;
    expect(t.campo).toBe("titular");
    expect(t.estilo.spans).toEqual([]);
    expect(st().pasado).toHaveLength(antes + 1);
  });

  it("desvincular apaga resaltar", () => {
    st().vaciar();
    st().cargar(structuredClone(base));
    st().aplicar([
      { op: "set", capa: "titulo", ruta: "campo", valor: "titular" },
      { op: "set", capa: "titulo", ruta: "resaltar", valor: true },
    ]);
    st().seleccionar(["titulo"]);
    render(<PanelPropiedades colorMarca="#ff3366" campos={CAMPOS} />);
    fireEvent.change(combo("Dato"), { target: { value: "" } });
    const t = capa("titulo") as CapaTexto;
    expect(t.campo).toBeNull();
    expect(t.resaltar).toBe(false);
  });

  it("la sombra de una forma escribe estilo.filter", () => {
    montarConCampos(["caja"]);
    expect(combo("Sombra").value).toBe("none");
    fireEvent.change(combo("Sombra"), { target: { value: "drop-shadow(0 16px 32px rgba(0,0,0,.3))" } });
    expect((capa("caja") as CapaForma).estilo.filter).toBe("drop-shadow(0 16px 32px rgba(0,0,0,.3))");
  });

  it("una sombra personalizada se muestra y no se pisa", () => {
    st().vaciar();
    st().cargar(structuredClone(base));
    st().aplicar([{ op: "set", capa: "caja", ruta: "estilo.filter", valor: "blur(2px)" }]);
    st().seleccionar(["caja"]);
    render(<PanelPropiedades colorMarca="#ff3366" />);
    expect(combo("Sombra").value).toBe("blur(2px)");
    expect((capa("caja") as CapaForma).estilo.filter).toBe("blur(2px)");
  });

  it("la mezcla escribe estilo.mixBlendMode", () => {
    montarConCampos(["logo"]);
    fireEvent.change(combo("Mezcla"), { target: { value: "multiply" } });
    expect(capa("logo")).toMatchObject({ estilo: { mixBlendMode: "multiply" } });
  });

  it("el texto no tiene efectos", () => {
    montarConCampos(["titulo"]);
    expect(screen.queryByRole("combobox", { name: "Sombra" })).toBeNull();
  });

  it("el borde de una forma", () => {
    montarConCampos(["caja"]);
    fireEvent.change(campo("Borde"), { target: { value: "4" } });
    fireEvent.blur(campo("Borde"));
    expect((capa("caja") as CapaForma).estilo.borderWidth).toBe(4);
    fireEvent.change(combo("Color de borde"), { target: { value: "token:tinta" } });
    expect((capa("caja") as CapaForma).estilo.borderColor).toBe("token:tinta");
  });

  it("el tracking acepta texto y vacío lo quita", () => {
    montarConCampos(["titulo"]);
    const tracking = screen.getByRole("textbox", { name: "Tracking" });
    fireEvent.change(tracking, { target: { value: "2px" } });
    fireEvent.blur(tracking);
    expect((capa("titulo") as CapaTexto).estilo.letterSpacing).toBe("2px");
    fireEvent.change(tracking, { target: { value: "" } });
    fireEvent.blur(tracking);
    expect((capa("titulo") as CapaTexto).estilo.letterSpacing).toBeUndefined();
  });
});
```

Notas:
- `CampoColor` (Task 10) expone el `select` de tokens con `aria-label={etiqueta}`; por eso «Color de borde» se opera como combobox, igual que «Fondo».
- ⚠️ `set` con `valor: undefined` deja la clave en `undefined` (no la borra). `toBeUndefined()` pasa igual; el JSON que va al backend la omite.

- [ ] **Step 2: correr y ver que falla**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test "app/b/[slug]/templates/[id]/_components/__tests__/panel-propiedades.test.tsx"
```

Esperado: los 9 casos del Task 10 pasan y los nuevos fallan; el primero con `camposDeContrato is not a function`.

- [ ] **Step 3: implementar**

En `frontend/app/b/[slug]/templates/[id]/_components/panel-propiedades.tsx`:

1. Imports y constantes, debajo de `PESOS`:

```tsx
import type { ContratoPlantilla } from "@/hooks/use-disenos";
```

```tsx
type Campos = { texto: string[]; imagen: string[] };

const CAMPOS_IMAGEN_BASE = ["imagen", "logo"];
const NO_ES_TEXTO = new Set([...CAMPOS_IMAGEN_BASE, "color_marca"]);

// Qué dato del contrato puede llenar cada tipo de capa.
export function camposDeContrato(contrato: ContratoPlantilla): Campos {
  return {
    texto: [
      ...contrato.base.filter((c) => !NO_ES_TEXTO.has(c)),
      ...contrato.extras.filter((x) => x.tipo !== "imagen").map((x) => x.id),
    ],
    imagen: [
      ...contrato.base.filter((c) => CAMPOS_IMAGEN_BASE.includes(c)),
      ...contrato.extras.filter((x) => x.tipo === "imagen").map((x) => x.id),
    ],
  };
}

// D16: sombra como preset sobre `filter`. Un valor fuera de la lista se
// respeta y se muestra como «Personalizada».
const SOMBRAS = [
  { valor: "none", nombre: "Ninguna" },
  { valor: "drop-shadow(0 8px 16px rgba(0,0,0,.25))", nombre: "Suave" },
  { valor: "drop-shadow(0 16px 32px rgba(0,0,0,.3))", nombre: "Media" },
  { valor: "drop-shadow(0 24px 48px rgba(0,0,0,.4))", nombre: "Fuerte" },
];
const MEZCLAS = [
  { valor: "normal", nombre: "Normal" },
  { valor: "multiply", nombre: "Multiplicar" },
  { valor: "screen", nombre: "Trama" },
  { valor: "overlay", nombre: "Superponer" },
  { valor: "darken", nombre: "Oscurecer" },
  { valor: "lighten", nombre: "Aclarar" },
  { valor: "soft-light", nombre: "Luz suave" },
  { valor: "difference", nombre: "Diferencia" },
];
```

2. `PanelPropiedades` recibe `campos` y lo pasa:

```tsx
export function PanelPropiedades({ colorMarca, campos }: { colorMarca: string; campos?: Campos }) {
```

```tsx
      <PropiedadesDeTipo capa={c} tokens={tokens} colorMarca={colorMarca} set={set} />
      {campos && <Dato capa={c} campos={campos} />}
      <Efectos capa={c} set={set} />
```

3. En `PropiedadesDeTipo`, rama `text`, debajo del `CampoColor` «Color»:

```tsx
        <Label className="flex flex-col items-stretch gap-1 text-xs text-muted-foreground">
          Tracking
          <input
            aria-label="Tracking"
            defaultValue={e.letterSpacing ?? ""}
            placeholder="-0.02em"
            className="h-8 rounded-md border border-input bg-background px-2 text-sm text-foreground"
            onBlur={(ev) => {
              const v = ev.target.value.trim();
              if (v !== (e.letterSpacing ?? "")) set("estilo.letterSpacing", v || undefined);
            }}
          />
        </Label>
```

4. Rama `shape`, debajo de «Radio»:

```tsx
        <CampoNumero
          etiqueta="Borde"
          valor={c.estilo.borderWidth ?? 0}
          min={0}
          max={100}
          onCommit={(n) => set("estilo.borderWidth", n)}
        />
        <CampoColor
          etiqueta="Color de borde"
          valor={c.estilo.borderColor ?? "#000000"}
          tokens={tokens}
          colorMarca={colorMarca}
          onCommit={(v) => set("estilo.borderColor", v)}
        />
```

5. Componentes nuevos al final del archivo:

```tsx
function Dato({ capa: c, campos }: { capa: Capa; campos: Campos }) {
  if (c.tipo !== "text" && c.tipo !== "image" && c.tipo !== "video") return null;
  const lista = c.tipo === "text" ? campos.texto : campos.imagen;
  const actual = c.campo ?? "";
  // Un campo que ya no está en el contrato se sigue mostrando para no perderlo.
  const opciones = [
    { valor: "", nombre: "Ninguno" },
    ...lista.map((x) => ({ valor: x, nombre: x })),
    ...(actual && !lista.includes(actual) ? [{ valor: actual, nombre: `${actual} (no está en el contrato)` }] : []),
  ];

  function cambiar(v: string) {
    const ops: Op[] = [{ op: "set", capa: c.id, ruta: "campo", valor: v || null }];
    if (c.tipo === "text" && v && (c.estilo.spans?.length ?? 0) > 0) {
      ops.push({ op: "set", capa: c.id, ruta: "estilo.spans", valor: [] });
    }
    if (c.tipo === "text" && !v && c.resaltar) {
      ops.push({ op: "set", capa: c.id, ruta: "resaltar", valor: false });
    }
    useEditor.getState().aplicar(ops, "Dato");
  }

  return (
    <Seccion titulo="Dato">
      <Selector etiqueta="Dato" valor={actual} opciones={opciones} onCambio={cambiar} />
    </Seccion>
  );
}

function Efectos({ capa: c, set }: { capa: Capa; set: (ruta: string, valor: unknown, etiqueta?: string) => void }) {
  if (c.tipo !== "image" && c.tipo !== "video" && c.tipo !== "svg" && c.tipo !== "shape") return null;
  const filtro = c.estilo.filter ?? "none";
  const sombras = SOMBRAS.some((s) => s.valor === filtro) ? SOMBRAS : [...SOMBRAS, { valor: filtro, nombre: "Personalizada" }];
  return (
    <Seccion titulo="Efectos">
      <Selector
        etiqueta="Mezcla"
        valor={c.estilo.mixBlendMode ?? "normal"}
        opciones={MEZCLAS}
        onCambio={(v) => set("estilo.mixBlendMode", v, "Mezcla")}
      />
      <Selector etiqueta="Sombra" valor={filtro} opciones={sombras} onCambio={(v) => set("estilo.filter", v, "Sombra")} />
    </Seccion>
  );
}
```

Notas:
- `Dato` aplica con `useEditor.getState().aplicar` y no con `set`, porque son hasta tres ops en un paso.
- `Selector` llama `onCambio` con el valor de la opción; elegir «Personalizada» de nuevo no cambia nada.
- `Efectos` usa el `estilo` de cada tipo: `EstiloMedio`, el de `svg` y el de `shape` declaran `filter?` y `mixBlendMode?` (Task 2). `EstiloTexto` no, y por eso el texto no tiene la sección (D16).

6. En `frontend/app/b/[slug]/templates/[id]/page.tsx`:

```tsx
import { camposDeContrato, PanelPropiedades } from "./_components/panel-propiedades";
```

```tsx
          <PanelPropiedades colorMarca={colorMarca} campos={camposDeContrato(diseno.contrato)} />
```

- [ ] **Step 4: verde**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test "app/b/[slug]/templates/[id]/_components/__tests__/panel-propiedades.test.tsx" && pnpm exec tsc --noEmit && pnpm lint
```

Esperado: `19 passed` (9 del Task 10 + 10 nuevos); tsc y lint limpios.

- [ ] **Step 5: commit**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2
git add "frontend/app/b/[slug]/templates/[id]/_components/panel-propiedades.tsx" "frontend/app/b/[slug]/templates/[id]/_components/__tests__/panel-propiedades.test.tsx" "frontend/app/b/[slug]/templates/[id]/page.tsx"
git commit -F - <<'EOF'
editor v2: efectos, borde, tracking y vínculo a datos

Sombra y mezcla para imagen, video, svg y forma; borde de forma; tracking
de texto. «Dato» vincula una capa a un campo del contrato filtrado por
tipo, y vincular o desvincular limpia lo que deja de aplicar.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

## Task 15: e2e contra el backend real (`sembrar.py`, `editor.spec.ts`)

**Files:**
- Create: `frontend/e2e/sembrar.py`
- Create: `frontend/e2e/editor.spec.ts`
- Modify: `frontend/playwright.config.ts` (segundo `webServer` y comentario)

**Interfaces:**

```ts
// e2e/.datos/sembrado.json (lo escribe sembrar.py; .gitignore ya cubre /e2e/.datos/)
type Sembrado = { token: string; slug: "gdlscene"; id: number };
```

- El backend de e2e corre en 8102 con una base SQLite propia en `frontend/e2e/.datos/e2e.db`, que `sembrar.py` borra y vuelve a crear en cada corrida. No toca `data/gdlscene.db` ni nada de producción.
- `sembrar.py` usa solo funciones que ya existen: `db.connect`, `db.init_db`, `users.crear_usuario`, `users.asignar_marca`, `users.crear_sesion`, `normalizar` (plan 1) y `plantillas.crear`.
- La e2e no renderiza PNG ni abre la vista previa: no depende de Playwright del lado Python ni de fuentes instaladas.

- [ ] **Step 1: el sembrador**

`frontend/e2e/sembrar.py`:

```python
"""Base de datos desechable para la e2e del editor.

Crea un usuario manager de gdlscene, su sesión y un diseño borrador v2 con
un texto sin vincular. Escribe lo que la e2e necesita en
e2e/.datos/sembrado.json. Se corre desde la raíz del worktree.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from src import db, plantillas, users  # noqa: E402
from src.plantillas.contrato import CAMPOS_BASE  # noqa: E402
from src.plantillas.escena import normalizar  # noqa: E402

DATOS = Path(__file__).resolve().parent / ".datos"


def main() -> None:
    ruta = Path(os.environ["DB_PATH"]).resolve()
    if DATOS not in ruta.parents:
        sys.exit(f"DB_PATH debe vivir en {DATOS}; llegó {ruta}")
    DATOS.mkdir(parents=True, exist_ok=True)
    for sufijo in ("", "-wal", "-shm"):
        Path(f"{ruta}{sufijo}").unlink(missing_ok=True)

    cx = db.connect(str(ruta))
    db.init_db(cx)
    uid = users.crear_usuario(cx, "e2e@instagod.test")
    users.asignar_marca(cx, uid, 1, "manager")
    token = users.crear_sesion(cx, uid)

    escena = normalizar(None, "4:5")
    texto = next((c for c in escena["capas"] if c["tipo"] == "text"), None)
    assert texto is not None, "normalizar(None, '4:5') no trae una capa de texto; ajusta el sembrador"
    texto.update(id="e2e_titulo", texto="Hola e2e", campo=None)
    texto.pop("resaltar", None)

    contrato = {"aspecto": "4:5", "base": list(CAMPOS_BASE), "extras": []}
    tid = plantillas.crear(cx, 1, "E2E", "", contrato, layout=escena)
    cx.commit()

    (DATOS / "sembrado.json").write_text(json.dumps({"token": token, "slug": "gdlscene", "id": tid}))
    print(f"sembrado: diseño {tid} en {ruta}")


if __name__ == "__main__":
    main()
```

Notas:
- La guarda de `DB_PATH` impide que un `DB_PATH` heredado del shell borre otra base.
- `texto.update(id=…)`: si la capa de texto está dentro de un grupo, el `id` viejo queda en `hijos`. ⚠️ No verificado qué devuelve `normalizar(None, "4:5")`. Si trae grupos, cambiar también el id en el `hijos` del padre.

- [ ] **Step 2: correr el sembrador a mano**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2
DB_PATH="$PWD/frontend/e2e/.datos/e2e.db" /Users/ricardo/Work/personal/instagod/.venv/bin/python frontend/e2e/sembrar.py
cat frontend/e2e/.datos/sembrado.json
```

Esperado: `sembrado: diseño 1 en …/frontend/e2e/.datos/e2e.db` y un JSON con `token`, `slug` e `id`. Si `plantillas.crear` levanta `ContratoInvalido`, el mensaje dice qué capa o fuente no pasa la validación del plan 1; se corrige el sembrador, no el validador.

- [ ] **Step 3: el backend de e2e en Playwright**

En `frontend/playwright.config.ts`:

1. Agregar `import path from "node:path";` arriba.

2. Cambiar el comentario:

```ts
// El frontend de prueba corre en 3100 para no chocar con un `pnpm dev` en 3000.
// API_URL apunta al backend de e2e (Task 15), que corre en 8102 con su propia
// base en e2e/.datos/.
```

3. Agregar como primer elemento de `webServer` (Playwright los arranca en orden):

```ts
    {
      // Siembra una base desechable y levanta la API sobre ella. Nunca se
      // reutiliza un servidor: la base se recrea en cada corrida.
      command:
        "/Users/ricardo/Work/personal/instagod/.venv/bin/python frontend/e2e/sembrar.py && exec /Users/ricardo/Work/personal/instagod/.venv/bin/uvicorn api.app:app --host 127.0.0.1 --port 8102",
      cwd: "..",
      url: "http://127.0.0.1:8102/health",
      reuseExistingServer: false,
      timeout: 60_000,
      env: { DB_PATH: path.resolve(__dirname, "e2e/.datos/e2e.db"), ENV: "dev" },
    },
```

- [ ] **Step 4: la e2e que falla**

`frontend/e2e/editor.spec.ts`:

```ts
import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { cookieFalsa } from "./sesion";

type Sembrado = { token: string; slug: string; id: number };
const sembrado = (): Sembrado =>
  JSON.parse(readFileSync(path.join(__dirname, ".datos", "sembrado.json"), "utf8")) as Sembrado;

test("editar, autoguardar, recargar y activar", async ({ page, context }) => {
  const { token, slug, id } = sembrado();
  await cookieFalsa(context, token);

  const patches: number[] = [];
  page.on("response", (r) => {
    if (r.request().method() === "PATCH" && r.url().includes(`/api/brands/${slug}/templates/${id}`)) {
      patches.push(r.status());
    }
  });

  await page.goto(`/b/${slug}/templates/${id}`);
  const estado = page.getByTestId("estado-guardado");
  await expect(estado).toHaveText("Guardado");

  // Arrastrar el título 60 px a la derecha.
  const titulo = page.locator('#marco .capa[data-id="e2e_titulo"]');
  await titulo.click();
  const x0 = Number(await page.getByRole("spinbutton", { name: "X" }).inputValue());
  const caja = (await titulo.boundingBox())!;
  const cx = caja.x + caja.width / 2;
  const cy = caja.y + caja.height / 2;
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.mouse.move(cx + 30, cy, { steps: 5 });
  await page.mouse.move(cx + 60, cy, { steps: 5 });
  await page.mouse.up();
  const x1 = Number(await page.getByRole("spinbutton", { name: "X" }).inputValue());
  expect(x1).toBeGreaterThan(x0);

  // Cambiar el texto. Escape confirma (Task 8).
  await titulo.dblclick();
  const ta = page.locator("[data-editor-texto]");
  await ta.fill("Hola desde e2e");
  await ta.press("Escape");
  await expect(estado).toHaveText("Cambios sin guardar");
  await expect(estado).toHaveText("Guardado", { timeout: 15_000 });
  expect(patches.length).toBeGreaterThan(0);
  expect(patches.every((s) => s === 200)).toBe(true);

  // Lo guardado sobrevive a la recarga.
  await page.reload();
  await expect(estado).toHaveText("Guardado");
  await expect(titulo).toContainText("Hola desde e2e");
  await titulo.click();
  const x2 = Number(await page.getByRole("spinbutton", { name: "X" }).inputValue());
  expect(Math.abs(x2 - x1)).toBeLessThanOrEqual(2);

  // Activar y verlo en la lista.
  await page.getByRole("button", { name: "Activar" }).click();
  await expect(page.getByTestId("estado-diseno")).toHaveText("Publicado");
  await expect(page.getByRole("button", { name: "Activar" })).toHaveCount(0);

  await page.goto(`/b/${slug}/templates`);
  await expect(page.getByAltText("Vista previa del diseño E2E")).toBeVisible();
  await expect(page.getByText("Publicado", { exact: true })).toBeVisible();
});
```

Notas:
- Un `PATCH` puede salir después del arrastre y otro después del texto; la prueba exige que todos contesten 200 y que el estado termine en «Guardado».
- `x1 > x0` y no `x1 === x0 + 60`: el desplazamiento en px de lienzo depende del zoom de ajuste.
- `getByText("Publicado", { exact: true })` no choca con la pestaña «Publicados».

- [ ] **Step 5: correr la e2e**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm e2e e2e/editor.spec.ts
```

Esperado: `1 passed`. Si falla antes de verde, el orden de diagnóstico es:
1. La API no arranca: correr el `command` del `webServer` a mano desde la raíz del worktree con `DB_PATH` exportado y leer el error.
2. 401 en `/api/...`: el rewrite de Next no reenvía la cookie. Revisar `next.config.ts` y la respuesta de `GET /api/me` en el trace (`pnpm exec playwright show-trace test-results/**/trace.zip`).
3. El PATCH contesta 422: `escena.validar` del plan 1 rechaza lo que manda el editor. El cuerpo de la respuesta dice qué ruta.

- [ ] **Step 6: toda la suite**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm test && pnpm exec tsc --noEmit && pnpm lint && pnpm e2e
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/ frontend/e2e/sembrar.py
```

Esperado: vitest, tsc, lint, todas las e2e (`moveable`, `lienzo`, `editor-texto`, `editor`) y ruff en verde.

- [ ] **Step 7: commit**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2
git add frontend/e2e/sembrar.py frontend/e2e/editor.spec.ts frontend/playwright.config.ts
git commit -F - <<'EOF'
editor v2: e2e contra la API real con base desechable

sembrar.py crea una base SQLite en e2e/.datos con un manager de
gdlscene y un borrador v2. La e2e arrastra, cambia el texto, espera el
autoguardado, recarga, activa y lo ve publicado en la lista.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---
