# Motor: criterio de frescura + fix de carrusel en aprobación

> Ejecutar con subagent-driven-development. Decisiones de Ricardo (8-jun-2026):
> SEMANAL = solo fresco (excluye lo ya anunciado); si queda vacío NO genera (silencio).
> MENSUAL = recap deliberado del mes (puede repetir), con mínimo. Bug: el carrusel
> llegaba como links de texto, debe llegar como álbum + botones.

**Reglas de sesión:** `git config user.email`==theilluminatiduck@gmail.com antes de commitear; paths explícitos; `.venv/bin/python`; comentarios español; no romper `main()` manual de generate_agenda; el daemon está corriendo (no correr bot.py/generate_* a mano).

---

### Task X1: Fix carrusel en `enviar_a_telegram` (álbum + botones)

**Problema:** `approval.enviar_a_telegram` hace un solo `sendMessage` con la lista JSON de URLs como texto → Telegram solo previsualiza el primer link. Debe mandar las slides como **media group** (fotos) y un **mensaje aparte** con caption + botones (Telegram no permite botones inline pegados a un media group).

**Files:** Modify `src/approval.py`; Test `tests/test_approval.py`.

- [ ] **Step 1: Pure helper test (failing)** — agregar a tests/test_approval.py:
```python
def test_parse_imagen_url():
    from src import approval
    import json
    assert approval._urls_de_imagen(json.dumps(["a","b","c"])) == ["a","b","c"]
    assert approval._urls_de_imagen("http://x/y.jpg") == ["http://x/y.jpg"]
    assert approval._urls_de_imagen("") == []
```

- [ ] **Step 2: verificar falla**, luego implementar:
- `_urls_de_imagen(imagen_url) -> list[str]` PURO: intenta `json.loads`; si es lista → la devuelve; si es string no-JSON → `[imagen_url]`; vacío → `[]`.
- Reescribir `enviar_a_telegram(caption, imagen_url, queue_id)` con `requests` (NO urllib):
  - `urls = _urls_de_imagen(imagen_url)`
  - Si `len(urls) >= 2`: `POST sendMediaGroup` con `media=[{type:photo, media:url} for url in urls[:10]]` (IG/TG topan en 10). Luego `POST sendMessage` con `text=caption` (recortado a 4000 chars si excede) + `reply_markup` con `construir_botones(queue_id)`.
  - Si `len(urls) == 1`: `POST sendPhoto` con `photo=urls[0]`, `caption=caption[:1000]`, `reply_markup=construir_botones(queue_id)`.
  - Si `0`: `sendMessage` solo texto + botones (fallback).
  - Todas con `r.raise_for_status()`, `timeout=20`.

- [ ] **Step 3: tests** `tests/test_approval.py -q` PASS (el test pure + los 6 existentes). Commit `motor: enviar_a_telegram manda carrusel como album + botones (no links de texto)`.

- [ ] **Step 4: prueba real** (controlada): el controlador re-dispara un segmento y verifica en Telegram que llegan las fotos como álbum.

---

### Task X2: Criterio de frescura (semanal solo-fresco, mensual recap) + marcar anunciado en async

**Objetivo:** el semanal de releases solo incluye lo NO anunciado; si queda por debajo del mínimo, NO genera (silencio). El mensual es recap (incluye todo) con mínimo. Al APROBAR (daemon), los releases del carrusel se marcan `anunciado` (hoy solo pasa en main() manual).

**Files:** Modify `src/db.py`+`src/schema.sql` (migración), `src/generate_agenda.py`, `src/approval.py`, `config.py`; Tests nuevos.

- [ ] **Step 1: Migración** — `content_queue` gana `evento_ids TEXT` (JSON list de ids de events incluidos, para marcarlos al aprobar). Agregar a `_MIGRATIONS["content_queue"]` y a la whitelist de columnas escribibles de content_queue en `TABLES`. Test en tests/test_motor_migraciones.py: insertar con `evento_ids='[1,2]'` y leerlo.

- [ ] **Step 2: config** — mínimos:
```python
SEGMENT_MIN_RELEASES_SEMANAL = 3   # < esto fresco → no se genera el semanal
SEGMENT_MIN_RELEASES_MENSUAL = 3   # recap del mes solo si hay al menos esto
```

- [ ] **Step 3: releases_ventana con filtro** — `releases_ventana(cx, dias, *, hoy=None, solo_frescos=False)`: cuando `solo_frescos`, agregar `AND e.status != 'anunciado'` al WHERE. Test: 2 releases en ventana, uno 'anunciado' → solo_frescos devuelve 1, sin filtro devuelve 2.

- [ ] **Step 4: build_releases_carousel devuelve ids** — cambiar firma a `build_releases_carousel(periodo, *, hoy=None, solo_frescos=False) -> tuple[str, list[str], list[int]]` (caption, pngs, evento_ids de los releases incluidos). Pasar `solo_frescos` a `releases_ventana`. ACTUALIZAR los 2 callers: `main()` (desempaqueta 3, ignora ids o los usa para _marcar_anunciados) y `generar_segmento_agenda`. OJO `main()` para releases usa `_MODO[...]["ventana"]` arriba y luego build — mantener consistencia; main() es el flujo manual, que siga marcando como hoy.

- [ ] **Step 5: generar_segmento_agenda con gate** — en la rama releases:
  - `solo_frescos = (periodo == "semanal")`.
  - `caption, pngs, evento_ids = build_releases_carousel(periodo, solo_frescos=solo_frescos)`.
  - mínimo: `min_req = config.SEGMENT_MIN_RELEASES_SEMANAL if periodo=="semanal" else config.SEGMENT_MIN_RELEASES_MENSUAL`. Si `len(evento_ids) < min_req` → `print(...sin contenido fresco suficiente...)` y `return` (silencio, no encola, no manda TG).
  - pasar `evento_ids=json.dumps(evento_ids)` a `encolar_pendiente`.
  - shows: igual que hoy (skip si <2 pngs); no cambia.

- [ ] **Step 6: marcar anunciado al aprobar** — `approval.encolar_pendiente` acepta `evento_ids: str | None`; `approval.aprobar`, tras aprobar, si la fila tiene `evento_ids`, hace `for eid in json.loads(evento_ids): db.update(cx,"events",eid,status="anunciado")`. Test: encolar con evento_ids=[E1,E2], aprobar (con _escribir_sheet doble), verificar events E1/E2 quedan status='anunciado'.

- [ ] **Step 7:** suite verde; commits separados por sub-paso lógico (migración / generador+config / approval). 

---

## Verificación final (controlador, inline)
- Re-disparar `generar_segmento_agenda` releases SEMANAL → debe SALTAR (todo está anunciado tras la prueba de hoy) o mandar solo lo fresco.
- Re-disparar MENSUAL → manda recap como álbum (carrusel real en Telegram).
- Confirmar que aprobar marca los events 'anunciado' (consulta DB).
