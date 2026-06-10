# Agenda: split en partes + unificar aprobación en el motor

> Ejecutar con subagent-driven-development. Causa raíz: el botón "generar post" de la
> GUI corre el flujo VIEJO (`generate_agenda.main` → `request_carousel_approval`) que
> abre su PROPIO poller (choca con el daemon) y usa callbacks `approve:c` que el daemon
> captura como si fueran memes → error "no caption to edit". Fix: unificar la GUI en el
> camino no-bloqueante del motor; agendas se publican de inmediato; >10 imágenes se
> parten en Parte 1/2.

**Reglas de sesión:** `git config user.email`==theilluminatiduck@gmail.com antes de commitear; paths explícitos; `.venv/bin/python`; comentarios español; el daemon está corriendo (no correr bot.py/generate_* a mano). Flujos vivos — cuidado.

---

### Task 1: Daemon robusto al editar + aprobación con publicación inmediata

**Files:** `src/approval.py`, `src/approval_daemon.py`, `tests/test_approval.py`.

**Contexto:** hoy `approval.aprobar` siempre agenda en slot de alto tráfico. Las agendas/anuncios deben publicarse DE INMEDIATO (regla editorial). El daemon hace `edit_message_text` que truena si el mensaje es una foto-con-caption.

- [ ] **Step 1 (test, failing)** en tests/test_approval.py:
```python
def test_aprobar_inmediato_publica_ahora(tmp_path, monkeypatch):
    from src import approval, db
    cx = db.connect(tmp_path / "t.db"); db.init_db(cx)
    qid = approval.encolar_pendiente(cx, tipo="anuncio", caption="x", imagen_url="u")
    llamado = {}
    slot = approval.aprobar(cx, qid, ahora=__import__("datetime").datetime(2026,6,9,2,0),
                            _escribir_sheet=lambda **k: 5,
                            _publicar=lambda: llamado.setdefault("pub", True))
    fila = db.get(cx, "content_queue", qid)
    assert fila["aprobacion"] == "aprobado" and fila["status"] == "en_sheet"
    # tipo 'anuncio' → scheduled = ahora (inmediato) y se llamó _publicar
    assert slot.year == 2026 and slot.hour == 2 and llamado.get("pub")
```

- [ ] **Step 2:** verificar falla. Implementar en `approval.py`:
  - `aprobar(cx, queue_id, *, ahora=None, ventana_trafico="meme", audiencia=None, _escribir_sheet=None, _publicar=None)`:
    - `fila = db.get(...)`. `inmediato = fila.get("tipo") == "anuncio"`.
    - si `inmediato`: `slot = ahora` (publica ya); si no: `slot = timing.elegir_slot(ventana_trafico, ahora, audiencia=audiencia or [])`.
    - escribe Sheet (igual que hoy) con `scheduled=slot.isoformat()`; update content_queue aprobado/en_sheet/sheet_row_id/scheduled.
    - marca eventos anunciado (lógica de evento_ids existente, sin cambios).
    - si `inmediato`: llamar `(_publicar or _publicar_ahora)()` — dispara `publish.py` ya.
    - return slot.
  - `_publicar_ahora()` en approval.py: `subprocess.Popen([sys.executable, str(config.BASE_DIR/"publish.py")], cwd=...)` **detached** (no espera), para no bloquear el callback. (importar sys, subprocess, config dentro de la función.)

- [ ] **Step 3:** en `approval_daemon.py`, helper robusto de edición:
```python
async def _resolver_msg(query, texto):
    """Edita el mensaje del callback sea texto o caption; si no se puede, ignora."""
    from telegram.error import BadRequest
    try:
        await query.edit_message_text(texto)
    except BadRequest:
        try:
            await query.edit_message_caption(caption=texto)
        except BadRequest:
            pass
```
  Usar `_resolver_msg(query, ...)` en lugar de `query.edit_message_text(...)` en `on_aprobacion`. El mensaje de confirmación: si fue inmediato (tipo anuncio) "✅ Aprobado — publicando ahora"; si slot, el actual "se publica el {slot}". (El daemon puede leer el tipo: que `_aprobar_sync` devuelva (slot, inmediato) o que el texto lo arme aprobar — simplest: `aprobar` devuelve el slot y el daemon arma "publicando ahora" si slot≈ahora; mejor: `_aprobar_sync` devuelve dict {slot, inmediato}.) Implementar limpio.

- [ ] **Step 4:** tests verdes; commit `agenda: aprobar publica inmediato anuncios + daemon edita texto/caption robusto`.

---

### Task 2: Split de la agenda en Parte 1/Parte 2 (≤10 slides c/u)

**Files:** `src/generate_agenda.py`, `templates/agenda_cover.html` (marca pt k/n), `tests/test_agenda.py`.

**Contexto:** `build_agenda_carousel` corta los flyers a `_IG_CAROUSEL_MAX-2` (8) y descarta el resto. Hay que PARTIR en bloques de 8 flyers → cada parte = portada(pt k/n) + ≤8 flyers + CTA.

- [ ] **Step 1 (test, failing):** `build_agenda_partes(periodo, *, hoy=None) -> list[dict]` donde cada dict = {caption, pngs, evento_ids, parte, partes}. Test con DB tmp sembrada con, p.ej., 10 flyers con imagen → debe devolver 2 partes (8 + 2), cada una con pngs<=10, parte/partes correctos, y la unión de evento_ids = todos. (Sembrar flyer_path a archivos reales pequeños o monkeypatch _phash/Path.exists para no depender de imágenes; lo más simple: crear PNGs dummy en tmp y apuntar flyer_path a ellos.)

- [ ] **Step 2:** verificar falla. Implementar `build_agenda_partes`:
  - Reusa la lógica de dedup visual de `build_agenda_carousel` para obtener `unicos` (todos, SIN cortar a 8).
  - `from src.generate_agenda import _chunks`; `bloques = _chunks(unicos, _IG_CAROUSEL_MAX - 2)` (8 por parte). `partes_n = len(bloques)`.
  - Para cada bloque k (1-based): render portada con `{kicker, rango, parte: k, partes: partes_n}` (la plantilla muestra "pt k/N" si partes>1), render cada flyer (pagina/paginas dentro de la parte), render CTA. caption = encabezado (con "(Parte k/N)" si partes>1) + líneas de los eventos de ESA parte + tags de esa parte. evento_ids = ids de los eventos del bloque.
  - Devuelve lista de dicts.
  - Mantener `build_agenda_carousel` como está (no romper main() ni callers); `build_agenda_partes` es nuevo y aparte.

- [ ] **Step 3:** `templates/agenda_cover.html`: aceptar `parte`/`partes` opcionales; si `partes>1`, mostrar "Parte {{parte}}/{{partes}}" en el kicker o un badge. Cambio mínimo, no romper el render sin esos campos (default).

- [ ] **Step 4:** tests verdes; commit `agenda: build_agenda_partes parte el carrusel en bloques de <=10`.

---

### Task 3: Unificar la GUI y el cron en el camino del motor (no más main bloqueante)

**Files:** `src/generate_agenda.py` (CLI `--segmento` + `generar_segmento_agenda` usa partes), `web/app.py` (ruta), `tests/` smoke.

- [ ] **Step 1:** en `generar_segmento_agenda(cx, account_id, *, periodo, modo)`:
  - shows: usar `build_agenda_partes(periodo)`; si lista vacía → log y return. Para cada parte: subir sus pngs a host (mismo patrón), `imagen = urls[0] if 1 else json.dumps(urls)`, `approval.encolar_pendiente(cx, tipo="anuncio", caption=parte["caption"], imagen_url=imagen, tema_semilla=f"shows {periodo} pt{parte['parte']}", evento_ids=json.dumps(parte["evento_ids"]), account_id=account_id)` + `approval.enviar_a_telegram(...)`. Log "parte k/N enviada".
  - releases: igual que hoy (build_releases_carousel + gate de frescura; ya OK). tipo="anuncio" (publica inmediato).
  - (encolar_pendiente ya guarda tipo; aprobar usa tipo='anuncio' → inmediato.)

- [ ] **Step 2:** CLI: agregar flag `--segmento` a `generate_agenda` que corra `generar_segmento_agenda` (no `main()`), para que la GUI lo invoque como subproceso sin poller:
```python
    parser.add_argument("--segmento", action="store_true",
                        help="modo motor: encola y manda a Telegram (no bloquea)")
    ...
    if args.segmento:
        cx = db.connect(); db.init_db(cx)
        try: generar_segmento_agenda(cx, 1, periodo=args.periodo, modo=args.modo)
        finally: cx.close()
    else:
        asyncio.run(main(args.periodo, args.modo))
```

- [ ] **Step 3:** `web/app.py` ruta `/eventos/agenda/{modo}/{periodo}`: cambiar `_lanzar_sesion("src.generate_agenda", "--modo", modo, "--periodo", periodo)` → `_lanzar_sesion("src.generate_agenda", "--segmento", "--modo", modo, "--periodo", periodo)`. Actualizar el texto de respuesta ("…en camino a Telegram; al aprobar se publica de inmediato. Si hay muchos flyers llegará en partes.").

- [ ] **Step 4:** smoke: `python -c "import src.generate_agenda, web.app"` ok; `python -m src.generate_agenda --segmento --modo shows --periodo mensual` (REAL: sube a Cloudinary + manda a Telegram en partes) — lo corre el CONTROLADOR, no el subagente (red). Subagente solo deja el código + tests unitarios de build_agenda_partes y del CLI flag (que --segmento no llama main).

- [ ] **Step 5:** commit `agenda: GUI y cron usan el motor (no-bloqueante); fin del choque con el daemon`.

---

## Verificación final (controlador, en vivo)
- Reiniciar daemon con código nuevo.
- `python -m src.generate_agenda --segmento --modo shows --periodo mensual` → deben llegar 1-2 partes a Telegram como álbum + botones.
- Aprobar una parte → se publica de inmediato (publish.py), el mensaje se edita "✅ publicando ahora" sin error.
- Confirmar en DB: filas en_sheet con scheduled≈ahora.
