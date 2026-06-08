# Endurecer clasificación de eventos: el caption manda, nada se escapa

**Fecha:** 2026-06-09
**Estado:** Aprobado

## Diagnóstico (review de hoy)

Causa raíz común: los eventos/releases nacían de la IMAGEN (`classify.score_flyer`
/ `es_grafico`), frágil con pósters gráficos (OCR no lee tipografía estilizada,
MSER bajo umbral, regex de fecha falla). El CAPTION siempre lo decía pero no era
la autoridad. Resultado: 34 posts (últimos 30 días) con foto + caption de
fecha/release y SIN evento. Dos huecos vivos:
- "Correr pipeline" ingiere posts nuevos pero NO corre la detección por caption
  (solo el orquestador `novedades` lo hacía).
- El backfill re-llamaría al LLM sobre los mismos posts "sin evento" cada día.

Principio rector: **el caption es la fuente autoritativa de eventos/releases; la
imagen es señal secundaria.**

## 1. Migración `photos.evento_analizado` (db.py)

- `INTEGER NOT NULL DEFAULT 0` vía `_MIGRATIONS["photos"]` + whitelist.
- Se marca a 1 cuando el caption de un post pasa por el detector (cualquier
  resultado). Hace el backfill idempotente y barato (nunca re-LLM lo ya visto).

## 2. `detect_releases_ig.detectar` marca evento_analizado

- Tras procesar cada post (sea release, show, o nada), marca
  `evento_analizado=1` en TODAS las fotos de ese `source_post_id` de la banda.
- Sin caption → también se marca (no hay nada que re-analizar).

## 3. Detección por caption en TODAS las rutas

- `src/novedades.py`: ya corre `detectar` sobre `posts_nuevos`. Sin cambio salvo
  el backfill (abajo).
- `src/pipeline.py`: tras ingerir (ingest+novedades), corre `detect_releases_ig`
  sobre los posts nuevos devueltos por `ingest_ig.novedades()` y sobre las
  bandas nuevas. Un post nuevo SIEMPRE pasa por el detector, sin importar la
  imagen. (Hoy el pipeline no lo hacía.)

## 4. Backfill robusto — `backfill_eventos`

- Selecciona posts con foto + caption + `evento_analizado=0` y sin evento, en
  ventana `dias`. Marca `evento_analizado` al procesar. Acotado por el flag →
  no re-LLM. En `novedades` se llama con ventana amplia (30 días) ya sin costo
  repetido.

## 5. Monitor de completitud (novedades)

- Tras todo, cuenta posts con foto + caption con señales de evento
  (fecha/release: junio|julio|pm|sencillo|estreno|disponible|en vivo|toca…) y
  SIN evento. Lo agrega al aviso de Telegram: "⚠️ N posts con caption de evento
  sin detectar" (debería ser 0). Sirve de alarma temprana.

## 6. Clasificador de flyer como red secundaria (classify.py)

- Hoy un póster gráfico sin fecha legible en OCR → "gráfico/póster descartado"
  (silencioso). Cambio: un gráfico (MSER alto) cuyo CAPTION sugiere evento
  (`caption_sugiere_evento`) se registra como flyer→events aunque el OCR no lea
  la fecha (la fecha la pone luego el caption-LLM/parse). No descarta pósters de
  evento en silencio. Sin caption-evento, sigue descartado (evita falsos de arte
  de álbum).

## 7. Tests + recuperación

- Tests: migración; `detectar` marca evento_analizado (con y sin caption);
  backfill ignora analizados (no re-LLM); pipeline corre detección por caption;
  monitor cuenta correctamente; clasificador registra póster-con-caption-evento.
- Correr el backfill (30 días) sobre la DB real → recupera los 34 escapados.

## Fuera de alcance

- Reentrenar/afinar umbrales finos de OCR/MSER (el caption ya es la red robusta).
- Tocar la lógica de meme-usabilidad de fotos (no relacionado).
