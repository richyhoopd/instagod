# Catálogo de foros canónicos

Fecha: 2026-08-03
Estado: diseño aprobado, pendiente de plan de implementación

## Problema

En la agenda de la escena aparece el mismo evento varias veces. La causa que se suponía —varios artistas subiendo el mismo cartel— ya está resuelta: `_unicos_flyers` deduplica por pHash y `agrupar_por_evento` fusiona por fecha + foro.

El duplicado que sobrevive tiene otra raíz: **`events.lugar` es texto libre que un LLM extrae del OCR y del caption, y el mismo foro aparece con media docena de escrituras distintas.** Medido sobre la DB real (3-ago-2026):

| Foro real | Cómo está guardado |
|---|---|
| Staditche | `Staditche`, `staditche`, `@staditche`, `Staditche (Espacio Cultural)`, `Staditche (Centro Cultural)` |
| Hake Al Rey | `Hake al Rey`, `Hakealrey`, `HAKE AL REY`, `@hakealrey`, `REY`, `Hake Al Rey · Libertad 1482, Col. Americana` |
| Anexo Independencia | `Anexo Independencia`, `Anexo Foro Independencia`, `Anexo independencia GDL` |

Más basura: nombres de banda en el campo de lugar (`siamesasperdidas`, `barragan_kun`), direcciones sueltas (`GRAL.MANUEL pm COVER M.DIEGUEZ #71 EL ROSARIO`) y OCR ilegible (`CENTRO TEULTRAL VNNERSTTARIO`).

`_norm_venue` quita acentos, puntuación y **un** prefijo genérico de tipo de local. Resuelve "Foro Anexo" vs "Anexo" pero ninguno de los casos de arriba.

Caso concreto que se está publicando mal: el **23-ago-2026** hay dos flyers, uno con `lugar='REY'` (SilentNoir) y otro con `lugar='Hake al Rey'`. Son el mismo show y salen como dos slides.

### Cifras

- **237** strings distintos de `lugar`, que corresponden a unos 40-60 foros reales.
- **612** eventos con fecha (`tipo` flyer o fecha); **todos** tienen `flyer_path`, así que todos pueden volverse slide.
- **109** de ellos no tienen lugar. Sin lugar `agrupar_por_evento` no fusiona, a propósito.
- **12** foros y eventos ya existen en `bands` con su handle (STADITCHE, Hake Al Rey, Cuerda, Pulque Degollado, Ummagumma, Solaz, Pool Sessions, catsufest, La Bestia Radio, Psiquia-tetrico, A VI SO, Batalla de las Bandas). El catálogo no arranca de cero.

## Alcance

Este spec cubre **solo el catálogo de foros**. La detección por coincidencia de lineup —fusionar dos flyers porque listan las mismas bandas en la misma fecha— es un proyecto independiente que se apoyará en éste, y va en su propio spec. Es lo que atenderá los 109 eventos sin lugar.

Decisiones de Ricardo que acotan el alcance:

- **Se ataca la fuente, no la presentación.** El campo `lugar` sucio afecta a la web y a cualquier consumidor futuro, no solo a la agenda.
- **Siembra automática + curación humana.** Un mapeo equivocado funde dos foros y desaparece un evento de la agenda sin que nadie se entere; por eso nada se auto-aplica sin que Ricardo pueda corregirlo.
- **Salas distintas son foros distintos.** `C3 Stage` y `C3 Rooftop` son dos entradas del catálogo. Nunca se fusionan dos shows de salas distintas; sí se colapsan todas las escrituras de cada sala.

Fuera de alcance explícito:
- Pasarle al LLM de `parse_events` la lista cerrada de foros para que devuelva un id en vez de texto. Es buena idea pero no sustituye al catálogo (no arregla los 612 eventos ya guardados) y cuesta una llamada por evento. `resolver()` cubre el caso con normalización determinista.
- Sugerencias por LLM en la curación: se usa similitud de texto de la librería estándar, que es instantánea, gratis y determinista.

## Restricciones

- Python 3.14, sin dependencias nuevas.
- Migraciones idempotentes: tablas nuevas en `src/schema.sql` con `CREATE TABLE IF NOT EXISTS`; columnas nuevas en `db._MIGRATIONS`, sin cláusula `REFERENCES` en `ADD COLUMN`.
- Toda tabla nueva se registra en `db.TABLES`.
- **El batch nunca pisa lo curado**: un alias asignado a mano no lo reescribe la siembra. Misma regla que `bands.generos_fuente`.

## Modelo de datos

```
venues        id, nombre, ciudad, ig_handle (nullable), activa, created_at, updated_at
venue_alias   id, venue_id (nullable), alias_norm (UNIQUE), alias_visto,
              origen ('semilla' | 'llm' | 'manual' | 'no_es_lugar'), created_at
events.venue_id  INTEGER (nullable), vía _MIGRATIONS
```

`venue_alias.venue_id` en NULL significa **alias huérfano**: un texto que se vio en un flyer y todavía no está asignado a ningún foro. Es la cola de curación.

`alias_visto` guarda el texto crudo tal como llegó. Cuando Ricardo cure en la GUI necesita ver lo que decía el flyer, no la versión normalizada.

`venues.ig_handle` liga el foro a la cuenta que ya sigue, cuando existe.

`events.lugar` **no se modifica**: se conserva como texto crudo, rastro de auditoría y fallback. `venue_id` es una capa nueva encima.

## `src/venues.py`

**`normalizar(s) -> str`** — PURA, es el corazón del módulo. En orden: quita acentos, baja a minúsculas, quita `@`, **elimina paréntesis y su contenido** (`Staditche (Espacio Cultural)` → `staditche`), convierte puntuación en espacio, quita **como máximo un prefijo y como máximo un sufijo** genéricos de tipo de local (`foro`, `el foro`, `centro cultural`, `espacio cultural`, `salon`, `sala`, `bar`, `concert room`), colapsa espacios.

Se lleva la lógica que hoy vive en `generate_agenda._norm_venue`, que se elimina de ahí.

**Lo que la normalización NO resuelve, y hay que decirlo:** el caso que motiva este spec, `REY` contra `Hake al Rey`, **no se colapsa solo**. `normalizar("REY")` da `rey` y `normalizar("Hake al Rey")` da `hake al rey`: son cadenas distintas y ninguna regla de texto razonable las une sin unir también cosas que no debe. `REY` es un OCR truncado, y solo queda resuelto cuando alguien —el LLM en la siembra, o Ricardo en la GUI— lo registra como alias de Hake Al Rey.

Eso es exactamente el punto del catálogo: la normalización barre el 80% mecánico (mayúsculas, arrobas, paréntesis, prefijos) y **el catálogo de alias captura el resto de forma permanente**. Una vez asignado, `REY` queda resuelto para siempre sin volver a pensarlo.

**`resolver(cx, lugar) -> int | None`** — busca `normalizar(lugar)` en `venue_alias` y devuelve `venue_id` o None. **Solo lectura.**

**`registrar_desconocido(cx, lugar) -> int`** — inserta el alias huérfano para que aparezca en la cola de curación. Separada de `resolver` a propósito: una función que consulta no debe escribir, y quien llama decide si quiere dejar rastro.

**`asignar_alias(cx, venue_id, texto)`** y **`fusionar(cx, dst_id, src_id)`** — operaciones de curación. `fusionar` mueve los alias y reapunta `events.venue_id` antes de borrar el foro absorbido; nunca deja ids colgando.

**`sugerencias(nombre, candidatos) -> list[tuple[str, float]]`** — PURA. Similitud con `difflib.SequenceMatcher` contra los nombres canónicos, para la GUI.

## Siembra y backfill

Script de una sola corrida:

1. Siembra `venues` con los 12 foros y eventos de `bands` (nombre canónico + `ig_handle`), y registra su nombre y su handle como alias.
2. Toma los strings distintos de `events.lugar`, los pasa por `normalizar()` —que ya colapsa mayúsculas, arrobas y paréntesis sin ayuda— y los que caen sobre un alias existente quedan resueltos.
3. Lo que quede ambiguo va al LLM en **una sola llamada** (237 strings caben de sobra) por el proveedor configurado en `LLM_PROVIDER` —hoy DeepSeek—, que propone agrupamientos y nombres canónicos. Lo que proponga se marca `origen='llm'`: queda usable de inmediato pero distinguible de lo curado a mano.
4. Escribe `venues` y `venue_alias`; lo dudoso queda huérfano para curación.
5. Backfill: `events.venue_id = resolver(lugar)` para los 612 eventos.

**Idempotente**: correrlo dos veces no duplica ni reescribe alias ya asignados a mano.

## Dónde se nota

`agrupar_por_evento` cambia su clave de `(fecha, _norm_venue(lugar))` a `(fecha, venue_id)`. Con `venue_id` NULL no fusiona — el comportamiento conservador de hoy. Es todo el cambio en la agenda.

## GUI

Vista `/venues`:
- Los foros del catálogo con sus alias.
- Arriba, los **alias huérfanos pendientes**, cada uno con `alias_visto` y una sugerencia de a qué foro se parece.
- Acciones: asignar alias a foro, crear foro nuevo, fusionar dos foros, y marcar un alias como **"no es un lugar"** para que la basura (nombres de banda, direcciones) no vuelva a aparecer en la cola.

Recordatorio operativo: las rutas nuevas en `web/app.py` exigen reiniciar uvicorn.

## Errores

| Caso | Comportamiento |
|---|---|
| Lugar que no resuelve | `venue_id` NULL, no fusiona, entra a la cola de curación. Nunca bloquea la agenda |
| String multi-foro (`C3 STAGE & C3 ROOFTOP`) | Queda huérfano a propósito: con salas separadas, adivinar cuál es sería peor que no adivinar |
| Basura en `lugar` (banda, dirección) | Huérfano; la GUI permite marcarlo "no es un lugar" |
| Fusionar dos foros | Mueve alias y reapunta `events.venue_id` antes de borrar; sin ids colgando |
| Alias duplicado | `UNIQUE` en `alias_norm`; la inserción es idempotente |

## Pruebas

Sobre las funciones puras, sin red ni LLM:
- `normalizar()` con los casos reales de la DB: `@staditche`, `Staditche (Espacio Cultural)`, `HAKE AL REY`, `Foro Anexo` vs `Anexo`, `Hake Al Rey · Libertad 1482, Col. Americana`.
- `resolver()`: alias conocido, desconocido, vacío, None.
- `sugerencias()`: orden por similitud descendente.
- `agrupar_por_evento` con la clave nueva: fusiona mismo `venue_id`, no fusiona NULL, no fusiona ids distintos.
- Siembra: idempotente y sin pisar lo curado.
- Un test de regresión del caso real del 23-ago (`REY` y `Hake al Rey` → un solo grupo).

## Trabajo previo (no es parte de este spec)

- El `IG_ACCESS_TOKEN` sigue expirado desde el 1-ago: no se publica en Instagram, solo en Facebook.
- 32 cuentas seguidas pendientes de traer (`data/nuevas_seguidas_pendientes.txt`).
