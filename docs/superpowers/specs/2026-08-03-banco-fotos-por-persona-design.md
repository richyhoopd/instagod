# Banco de fotos por persona

Fecha: 2026-08-03
Estado: diseño aprobado, pendiente de plan de implementación

## Problema

El banco de fotos tiene 7,712 fotos (3.1 GB) de las que **101 han llegado a un post**: 76 bajadas por cada una usada. Pero el desperdicio de disco no es el costo real — con 3,772 fotos usables y ~60 posts al mes hay cinco años de material. El costo real es otro:

1. **No se puede garantizar variedad de caras.** El clasificador actual (Haar + Laplaciano + MSER + OCR) sabe si *hay* una cara, no *de quién* es. Una banda puede salir diez veces seguidas con el vocalista y nunca con el baterista.
2. **La selección premia lo equivocado.** `planner.seleccionar()` toma la foto más nítida de cada banda. Nítida no es buena: un flyer es nitidísimo.
3. **La identidad nunca se materializó.** `members` tiene 14 filas y exactamente 1 foto con `member_id` asignado.

Criterio editorial de Ricardo: al menos una foto de cada integrante (≈4 caras distintas por banda) más al menos una grupal; y fotos en vivo. Cuando un integrante tiene nombre y rol capturados, es prioritario hacer el meme con integrante + nombre + rol.

## Alcance

Este spec cubre **solo el banco de fotos**. El caption que ve la foto (visión al generar el meme) es un proyecto independiente y va en su propio spec — cada uno funciona sin el otro.

Fuera de alcance explícito:
- Podar el acervo existente. Decisión de Ricardo: no se borra nada de lo ya registrado; el criterio nuevo rige hacia adelante y sobre lo viejo solo marca `usable_meme`.
- Categorización por "situación" mediante palabras clave del caption: descartada por frágil.
- Corte temprano durante la descarga: 50 fotos son ~10 MB; la complejidad no se paga.

## Restricciones

- **Python 3.14 sin PyTorch.** Precedente: `pytesseract` y PyTorch ya fallaron; por eso el OCR vive en RapidOCR/ONNX.
- **Sin dependencias nuevas.** Verificado en vivo: OpenCV 4.13.0 ya expone `FaceDetectorYN_create` y `FaceRecognizerSF_create`, y `onnxruntime` 1.26 ya está instalado por RapidOCR.
- Los modelos ONNX (YuNet ~340 KB, SFace ~37 MB) se bajan una vez a `data/models/`.

## Arquitectura

Tres módulos nuevos, cada uno con una responsabilidad:

### `src/dedup_fotos.py`
Colapsa near-duplicados dentro de cada banda. Reusa `src/imghash.py`, ya en producción para flyers. Agrupa por distancia de Hamming ≤ `DEDUP_HAMMING_MAX` y conserva la más nítida del grupo.

Es lo más barato con más retorno del diseño: el problema de variedad no es que falten fotos, es que hay diez casi idénticas de la misma sesión.

### `src/faces.py`
Detección y firma facial.

- `detectar(img) -> list[Cara]` — YuNet. Devuelve bbox, `det_score`, landmarks. Reemplaza los cascades de Haar (`_FRONTAL`, `_PERFIL`, `_UPPER`) de `classify.py`, que se caen con perfiles y poca luz.
- `firma(img, cara) -> np.ndarray[128]` — SFace.
- `similitud(a, b) -> float` — coseno. **Puro.**
- `agrupar(firmas, umbral) -> list[list[int]]` — aglomerativo. **Puro.**

Umbral de "misma persona": 0.363 coseno, el valor que documenta OpenCV para SFace. No hay que calibrarlo a ciegas.

Los modelos se cachean con el mismo patrón de descarga-valida-escritura-atómica que `src/covers.py` usa para las portadas.

### `src/banco.py`
La política de cupo. **Puro, sin IO:** recibe fotos con sus caras ya agrupadas, devuelve cuáles entran. Vive solo porque es la pieza que se va a ajustar con el tiempo y debe poder probarse sin imágenes.

## Modelo de datos

Dos tablas nuevas vía `db._MIGRATIONS` (idempotentes, sin `REFERENCES` en `ADD COLUMN` — restricción conocida de SQLite bajo `foreign_keys=ON`):

```
face_signatures   id, photo_id, bbox, det_score, embedding (BLOB 128×float32),
                  persona_id (nullable), created_at
personas          id, band_id, member_id (nullable), etiqueta_auto, created_at
```

`personas` es el grupo automático ("persona A de Kabala"). Al nombrarlo en la GUI se liga a `members`, que ya tiene `nombre` y `rol`. Así el caption pide "el baterista" cuando hay nombre y cae a la banda cuando no.

Guardar el embedding permite **reagrupar sin reprocesar imágenes**: cambiar el umbral cuesta segundos, no horas. `photos.es_grupal` ya existe y se reusa.

## Política de cupo

**5 fotos por persona + 3 grupales.** Parametrizado por persona, no por banda: "40 fotos de la P1" puede dar 40 del vocalista y cero del baterista, que es justo el problema a resolver. Una banda de cuatro aterriza en ~23, una solista en ~8.

Orden dentro de cada persona: `nitidez × det_score × fracción del área que ocupa la cara`. Una cara de 20 píxeles al fondo no cuenta como retrato.

### Degradación sin caras
Foros, eventos, colectivos y paisajes: si la banda no alcanza 2 grupos de caras, conserva las 3-4 más nítidas que no sean flyer ni gráfico. Ricardo pidió intentar primero el criterio de caras (los que llevan el lugar salen repetido en sus fotos) y caer a esto solo si no alcanza.

## Flujo de datos

**Cuentas nuevas**
```
Business Discovery (50 posts, 1 llamada)
  → descarga a temporal
  → dedup pHash
  → detección YuNet + firma SFace
  → agrupamiento por banda
  → cupo por persona
  → solo lo seleccionado se registra en `photos`
  → los temporales no seleccionados se borran (nunca existieron en la DB)
```

Pedir 50 posts cuesta lo mismo en cuota que pedir 12: Business Discovery devuelve las URLs en la misma llamada. Lo caro es descargar y guardar, no consultar. De ahí "mirar mucho, guardar poco".

**Acervo existente**
El mismo pipeline sin descarga y **sin borrar archivos**: solo marca `usable_meme=0` lo que no entra al cupo. Se corre perezoso —  sobre las mejores ~40 por banda ya deduplicadas, no sobre las 7,712— porque analizar todo es gastar CPU en fotos que nunca van a salir.

## Dónde se nota

`planner.seleccionar()` deja de pedir "la más nítida" y pasa a pedir **"una foto de una persona que no haya salido en los últimos N días"**. La anti-repetición pasa de ser por archivo a ser por cara. Es el cambio más pequeño del diseño y el más visible.

Misma lógica en `generate_relleno.candidatas()`.

## GUI

Vista nueva `/banda/{id}/caras`: los grupos con sus miniaturas y, por grupo, poner nombre y rol (crea o liga `members`), descartar el grupo, fusionar dos grupos, y fijar la foto principal.

No bloquea nada: el contenido fluye automático y la pantalla existe para corregir cuando el agrupamiento se equivoque (fotos oscuras, de perfil) y para capturar los nombres.

Recordatorio operativo: las rutas nuevas en `web/app.py` exigen reiniciar uvicorn.

## Errores

| Caso | Comportamiento |
|---|---|
| Sin caras detectadas | Degradación a las más nítidas no-flyer |
| Modelo ONNX no descargable | Falla ruidosa con instrucción; nunca silenciosa |
| Agrupamiento ambiguo | Grupo propio; la GUI permite fusionar |
| Foto corrupta | Se salta y se loguea; no tumba el lote |

## Pruebas

Sobre las funciones puras, sin red y sin imágenes reales:
- `agrupar()` con firmas sintéticas (vectores construidos a distancia conocida)
- `cupo()` — reparto por persona, tope de grupales, degradación sin caras
- `dedup()` — colapso por Hamming, elección del representante
- Selección con anti-repetición temporal

Un par de fixtures pequeños para el detector, que sí necesita imagen real.

## Configuración

```
FACE_DET_SCORE_MIN        0.6    confianza mínima de YuNet
FACE_CARA_MIN_FRAC        0.01   fracción mínima del área que debe ocupar la cara
FACE_COS_MISMA_PERSONA    0.45   similitud coseno para "misma persona" (mayor = más parecido)
FOTOS_POR_PERSONA         5
FOTOS_GRUPALES            3
DEDUP_HAMMING_MAX         8      sobre hash de 64 bits
BD_POSTS_A_MIRAR          50
ANTI_REPETICION_DIAS      45     días que una persona no se repite en un post
```

`FACE_CARA_MIN_FRAC` bajó de 0.05 a 0.01 al medirlo sobre el acervo real
(3-ago, 120 fotos de bandas): las caras de este corpus son chicas — con 0.05
solo 4 de 120 fotos conservaban alguna cara. Con 0.01 quedan 34.

`FACE_COS_MISMA_PERSONA` subió de 0.363 (el valor del sample de OpenCV,
calibrado para verificación 1-a-1 en LFW) a 0.45 en la Task 3, midiendo sobre
90 pares de caras distintas en la misma foto y 75 pares de la misma cara de
este acervo: 0.363 fundía a dos personas distintas el 7.8% de las veces
contra 3.3% en 0.45. La Task 11 lo confirmó corriendo el banco sobre 9
bandas reales y barriendo el umbral sobre las firmas guardadas — ver
"Estado de la calibración" abajo para los números.

Los dos errores no cuestan igual: fundir integrantes deja a uno sin
cobertura (el objetivo del banco), mientras que partir a uno en dos grupos
solo produce personas de más, que la GUI fusiona con un botón. Ante la duda,
el umbral sube, no baja.

`ANTI_REPETICION_DIAS` en 45 sale del ritmo actual: 2 posts/día sobre 144 cuentas hace que una banda salga cada ~2 meses, así que 45 días no restringe casi nada hoy y sí protege a las P1, que salen hasta 5 veces al mes.

## Estado de la calibración (Task 11, 3-ago)

`scripts/calibrar_caras.py` corrió el banco (`python -m src.banco`, `--limite
40`) sobre 9 bandas reales contra la DB de producción (respaldada antes en
`data/gdlscene.backup-pre-banco-20260803.db`) y barrió `FACE_COS_MISMA_PERSONA`
de 0.25 a 0.65 sobre las firmas ya guardadas de cada una: `dsplusmx` y
`eterealetal` (banda), `elmalilla_` (solista), `kabala_oficial` y
`los_baxters` (banda, tamaño real conocido: 3-5 integrantes),
`fotografoamarillo` (colectivo), `hakealrey`, `staditche` y `cuerdacultura`
(foro).

**0.45 se confirma.** Es el umbral más bajo que deshace las fusiones
catastróficas que sí se ven con datos reales a ≤0.363 (mega-clusters de
5-25 caras en una sola "persona" en eterealetal, los_baxters y
kabala_oficial — poco creíble que sean literalmente la misma cara). Subir
más allá de 0.45 no deshace ninguna fusión adicional, solo fragmenta más.

**Hallazgo, no bug:** con este acervo, ningún umbral acerca a `kabala_oficial`
ni a `los_baxters` a su tamaño real de banda (3-5 integrantes) sin volver a
provocar las fusiones catastróficas de arriba en otras bandas. En 0.45:

- `kabala_oficial`: 8 personas de 8 caras — cero agrupamiento.
- `los_baxters`: 16 personas de 19 caras.
- `elmalilla_` (solista, debería dominar 1 persona): 10 personas de 10
  caras — y ni el umbral más bajo probado (0.25 → 5 personas) lo arregla sin
  fundir a distintos en otras bandas.

Esto no es un problema de dónde cortar la similitud: es calidad de firma —
caras chicas, mala luz de escenario, crops marginales que YuNet apenas
detecta. El umbral está en el mejor punto disponible dado este acervo; la
fragmentación restante la absorbe el botón de fusionar de la GUI, que existe
precisamente para esto. Quien retome esto en el futuro no debería intentar
"arreglarlo" bajando el umbral — bajarlo vuelve a fundir integrantes
distintos, que es el error que el banco no puede permitirse.

Detalle completo del barrido (las 9 bandas, 10 umbrales cada una) en
`.superpowers/sdd/2026-08-03-banco-fotos-por-persona/task-11-report.md`.

## Trabajo previo (no es parte de este spec)

Antes de abrir este frente conviene cerrar lo que está a medias:
- `IG_ACCESS_TOKEN` expirado desde el 1-ago: no se publica en Instagram, solo en Facebook.
- 32 cuentas seguidas pendientes de traer (`data/nuevas_seguidas_pendientes.txt`).
- 1,119 fotos recién bajadas sin clasificar.
