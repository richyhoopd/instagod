"""Task 4 (Fase 2): operaciones de cola para la API (src/cola.py).

`estado_de` deriva el estado que ve el portal a partir de las columnas
crudas de `content_queue` (status + aprobacion + error). El resto de
funciones son las mutaciones que expondrá el router de cola (Task 7):
listar/filtrar, detalle, reprogramar, editar caption y descartar.
"""
from __future__ import annotations

import pytest

from src import cola, db


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def _fila(cx, **overrides):
    """Inserta una fila mínima en content_queue con overrides."""
    campos = {
        "tipo": "meme",
        "status": "borrador",
        "account_id": 1,
    }
    campos.update(overrides)
    return db.insert(cx, "content_queue", **campos)


# ---------- estado_de: matriz de los 7 estados (filas sintéticas) ----------

def test_estado_de_descartado():
    assert cola.estado_de({"status": "descartado", "aprobacion": "pendiente"}) == "descartado"
    assert cola.estado_de({"status": "descartado", "aprobacion": None}) == "descartado"


def test_estado_de_rechazado():
    assert cola.estado_de({"status": "listo", "aprobacion": "rechazado"}) == "rechazado"


def test_estado_de_rechazado_gana_a_descartado():
    # aprobacion=rechazado manda aunque status ya sea descartado (eliminar un
    # rechazado no le "borra" la etiqueta de rechazo).
    assert cola.estado_de({"status": "descartado", "aprobacion": "rechazado"}) == "rechazado"


def test_estado_de_publicado():
    assert cola.estado_de({"status": "publicado", "aprobacion": "aprobado"}) == "publicado"


def test_estado_de_publicado_gana_a_error():
    assert cola.estado_de(
        {"status": "publicado", "aprobacion": "aprobado", "error": "boom"}
    ) == "publicado"


def test_estado_de_error():
    assert cola.estado_de(
        {"status": "listo", "aprobacion": "pendiente", "error": "fallo del espejo"}
    ) == "error"


def test_estado_de_error_no_aplica_en_sheet():
    # en_sheet queda excluido del chequeo de error: el legacy ya llegó al Sheet.
    fila = {"status": "en_sheet", "aprobacion": "aprobado", "error": "algo viejo"}
    assert cola.estado_de(fila) == "programado"


def test_estado_de_programado():
    assert cola.estado_de({"status": "programado", "aprobacion": "aprobado"}) == "programado"
    assert cola.estado_de({"status": "en_sheet", "aprobacion": "aprobado"}) == "programado"


def test_estado_de_pendiente():
    assert cola.estado_de({"status": "listo", "aprobacion": "pendiente"}) == "pendiente"


def test_estado_de_generando():
    # "generando" es EXCLUSIVO del flujo API (worker generando un slideshow):
    # requiere origen='api' además de status='borrador'/aprobacion None.
    assert cola.estado_de(
        {"status": "borrador", "aprobacion": None, "origen": "api"}
    ) == "generando"


def test_estado_de_borrador_legacy():
    # G5: filas del plan mensual (origen != 'api') en borrador/listo sin
    # aprobación NO son "generando" (nadie está generando nada ahí) — son
    # 'borrador': visibles en el portal pero NO aprobables (la compuerta de
    # aprobar/rechazar del router sigue exigiendo 'pendiente').
    assert cola.estado_de(
        {"status": "borrador", "aprobacion": None, "origen": "legacy"}
    ) == "borrador"
    assert cola.estado_de(
        {"status": "listo", "aprobacion": None, "origen": "legacy"}
    ) == "borrador"
    # Sin columna "origen" (fila sintética/legacy vieja): mismo trato que 'legacy'.
    assert cola.estado_de({"status": "borrador", "aprobacion": None}) == "borrador"


def test_estado_de_fallback_pendiente():
    # aprobacion None, status "listo", origen 'api': no matchea "generando"
    # (exige status='borrador') ni "borrador" (exige origen != 'api') → cae
    # al fallback histórico "pendiente".
    assert cola.estado_de(
        {"status": "listo", "aprobacion": None, "origen": "api"}
    ) == "pendiente"
    # aprobacion aprobado pero status fuera de en_sheet/programado.
    assert cola.estado_de({"status": "borrador", "aprobacion": "aprobado"}) == "pendiente"


def test_estados_expuestos():
    assert cola.ESTADOS == (
        "generando", "borrador", "pendiente", "programado", "publicado",
        "rechazado", "error", "descartado",
    )


# ---------- listar ----------

def test_listar_nunca_devuelve_de_otro_account(tmp_path):
    cx = _cx(tmp_path)
    db.insert(cx, "accounts", slug="otra", ig_handle="otra", nombre="Otra", ciudad="X")
    _fila(cx, account_id=1, aprobacion="pendiente")
    _fila(cx, account_id=2, aprobacion="pendiente")

    resultado = cola.listar(cx, 1)

    assert len(resultado) == 1
    assert all(f["account_id"] == 1 for f in resultado)
    assert "estado" in resultado[0]


def test_listar_filtra_por_rango_scheduled_datetime(tmp_path):
    cx = _cx(tmp_path)
    _fila(cx, aprobacion="aprobado", status="programado",
          scheduled_datetime="2026-06-10T19:00:00")
    _fila(cx, aprobacion="aprobado", status="programado",
          scheduled_datetime="2026-06-20T19:00:00")

    resultado = cola.listar(cx, 1, desde="2026-06-15", hasta="2026-06-30")

    assert len(resultado) == 1
    assert resultado[0]["scheduled_datetime"] == "2026-06-20T19:00:00"


def test_listar_filtra_por_rango_created_at_si_no_hay_scheduled(tmp_path):
    cx = _cx(tmp_path)
    qid = _fila(cx, aprobacion="pendiente")
    db.update(cx, "content_queue", qid, tema_semilla="x")
    fila = db.get(cx, "content_queue", qid)
    creado = fila["created_at"]

    dentro = cola.listar(cx, 1, desde=creado[:10], hasta=creado[:10] + "T23:59:59")
    fuera = cola.listar(cx, 1, desde="2099-01-01", hasta="2099-12-31")

    assert len(dentro) == 1
    assert len(fuera) == 0


def test_listar_filtra_por_estado(tmp_path):
    cx = _cx(tmp_path)
    _fila(cx, aprobacion="pendiente")  # -> pendiente
    _fila(cx, aprobacion=None, status="borrador")  # -> generando

    resultado = cola.listar(cx, 1, estado="pendiente")

    assert len(resultado) == 1
    assert resultado[0]["estado"] == "pendiente"


# ---------- detalle ----------

def test_detalle_inexistente_devuelve_none(tmp_path):
    cx = _cx(tmp_path)
    assert cola.detalle(cx, 999) is None


def test_detalle_incluye_estado_y_slides_data(tmp_path):
    cx = _cx(tmp_path)
    qid = _fila(cx, aprobacion="pendiente", slideshow_json='{"slides": [1, 2]}')

    d = cola.detalle(cx, qid)

    assert d["estado"] == "pendiente"
    assert d["slides_data"] == {"slides": [1, 2]}


def test_detalle_slides_data_none_si_falta_o_es_invalido(tmp_path):
    cx = _cx(tmp_path)
    sin_json = _fila(cx, aprobacion="pendiente")
    malformado = _fila(cx, aprobacion="pendiente", slideshow_json="{no es json")

    assert cola.detalle(cx, sin_json)["slides_data"] is None
    assert cola.detalle(cx, malformado)["slides_data"] is None


# ---------- reprogramar ----------

def test_reprogramar_ok_actualiza_scheduled_datetime(tmp_path):
    cx = _cx(tmp_path)
    qid = _fila(cx, aprobacion="aprobado", status="programado",
                scheduled_datetime="2026-06-10T19:00:00")

    cola.reprogramar(cx, qid, "2026-06-11T19:00:00")

    assert db.get(cx, "content_queue", qid)["scheduled_datetime"] == "2026-06-11T19:00:00"


def test_reprogramar_choque_misma_cuenta(tmp_path):
    cx = _cx(tmp_path)
    _fila(cx, aprobacion="aprobado", status="programado",
          scheduled_datetime="2026-06-11T19:00:00")
    qid = _fila(cx, aprobacion="aprobado", status="programado",
                scheduled_datetime="2026-06-10T19:00:00")

    with pytest.raises(ValueError, match="choque"):
        cola.reprogramar(cx, qid, "2026-06-11T19:00:00")


def test_reprogramar_choque_normaliza_a_minuto(tmp_path):
    cx = _cx(tmp_path)
    _fila(cx, aprobacion="aprobado", status="programado",
          scheduled_datetime="2026-06-11T19:00:00")
    qid = _fila(cx, aprobacion="aprobado", status="programado",
                scheduled_datetime="2026-06-10T19:00:00")

    # nueva_iso trae segundos distintos del ocupado, pero mismo minuto.
    with pytest.raises(ValueError, match="choque"):
        cola.reprogramar(cx, qid, "2026-06-11T19:00:59")


def test_reprogramar_no_choca_con_otro_account(tmp_path):
    cx = _cx(tmp_path)
    db.insert(cx, "accounts", slug="otra", ig_handle="otra", nombre="Otra", ciudad="X")
    db.insert(cx, "content_queue", tipo="meme", account_id=2, status="programado",
              aprobacion="aprobado", scheduled_datetime="2026-06-11T19:00:00")
    qid = _fila(cx, aprobacion="aprobado", status="programado",
                scheduled_datetime="2026-06-10T19:00:00")

    cola.reprogramar(cx, qid, "2026-06-11T19:00:00")

    assert db.get(cx, "content_queue", qid)["scheduled_datetime"] == "2026-06-11T19:00:00"


def test_reprogramar_no_choca_con_ella_misma(tmp_path):
    cx = _cx(tmp_path)
    qid = _fila(cx, aprobacion="aprobado", status="programado",
                scheduled_datetime="2026-06-10T19:00:00")

    cola.reprogramar(cx, qid, "2026-06-10T19:00:00")

    assert db.get(cx, "content_queue", qid)["scheduled_datetime"] == "2026-06-10T19:00:00"


def test_reprogramar_fila_publicada_lanza_estado(tmp_path):
    cx = _cx(tmp_path)
    qid = _fila(cx, aprobacion="aprobado", status="publicado",
                scheduled_datetime="2026-06-10T19:00:00")

    with pytest.raises(ValueError, match="estado"):
        cola.reprogramar(cx, qid, "2026-06-11T19:00:00")


def test_reprogramar_permite_estado_pendiente(tmp_path):
    cx = _cx(tmp_path)
    qid = _fila(cx, aprobacion="pendiente", status="listo")

    cola.reprogramar(cx, qid, "2026-06-11T19:00:00")

    assert db.get(cx, "content_queue", qid)["scheduled_datetime"] == "2026-06-11T19:00:00"


def test_reprogramar_iso_invalido_lanza_formato(tmp_path):
    """G4: valida el ISO ANTES de tocar la DB — "mañana" no es una fecha."""
    cx = _cx(tmp_path)
    qid = _fila(cx, aprobacion="pendiente", status="listo")

    with pytest.raises(ValueError, match="formato"):
        cola.reprogramar(cx, qid, "mañana")


def test_reprogramar_revive_fila_atorada_reseteando_intentos_y_error(tmp_path):
    """Fix round 1 (revisión Task 6): una fila que el publisher marcó con
    error (marcador "[publicando]" de un crash, o ya topada en MAX_INTENTOS)
    queda visible como estado 'error'; reprogramar es la vía del operador
    para revivirla — debe limpiar intentos/error, no solo el horario."""
    cx = _cx(tmp_path)
    qid = _fila(cx, aprobacion="aprobado", status="programado",
                scheduled_datetime="2026-06-10T19:00:00",
                error="[publicando]", intentos=5)

    cola.reprogramar(cx, qid, "2026-06-11T19:00:00")

    fila = db.get(cx, "content_queue", qid)
    assert fila["scheduled_datetime"] == "2026-06-11T19:00:00"
    assert fila["intentos"] == 0
    assert fila["error"] is None


# ---------- editar_caption ----------

def test_editar_caption_pendiente(tmp_path):
    cx = _cx(tmp_path)
    qid = _fila(cx, aprobacion="pendiente", status="listo", caption="viejo")

    cola.editar_caption(cx, qid, "nuevo")

    assert db.get(cx, "content_queue", qid)["caption"] == "nuevo"


def test_editar_caption_programado(tmp_path):
    cx = _cx(tmp_path)
    qid = _fila(cx, aprobacion="aprobado", status="programado", caption="viejo")

    cola.editar_caption(cx, qid, "nuevo")

    assert db.get(cx, "content_queue", qid)["caption"] == "nuevo"


def test_editar_caption_publicado_lanza_estado(tmp_path):
    cx = _cx(tmp_path)
    qid = _fila(cx, aprobacion="aprobado", status="publicado", caption="viejo")

    with pytest.raises(ValueError, match="estado"):
        cola.editar_caption(cx, qid, "nuevo")


# ---------- eliminar ----------

@pytest.mark.parametrize("overrides", [
    {"aprobacion": "pendiente", "status": "listo"},
    {"aprobacion": "rechazado", "status": "listo"},
    {"aprobacion": "pendiente", "status": "listo", "error": "fallo"},
])
def test_eliminar_permite_estados_validos(tmp_path, overrides):
    cx = _cx(tmp_path)
    qid = _fila(cx, **overrides)

    cola.eliminar(cx, qid)

    assert db.get(cx, "content_queue", qid)["status"] == "descartado"


def test_eliminar_fila_programada_lanza(tmp_path):
    cx = _cx(tmp_path)
    qid = _fila(cx, aprobacion="aprobado", status="programado")

    with pytest.raises(ValueError, match="estado"):
        cola.eliminar(cx, qid)


def test_eliminar_fila_publicada_lanza(tmp_path):
    cx = _cx(tmp_path)
    qid = _fila(cx, aprobacion="aprobado", status="publicado")

    with pytest.raises(ValueError, match="estado"):
        cola.eliminar(cx, qid)


# ---------- editar_slides (Fase 4: edición slide por slide) ----------

def _show_json(n=2, con_foto=False):
    import json
    slides = []
    for i in range(n):
        slides.append({
            "image_urls": (["https://res.cloudinary.com/d/x.jpg"] if con_foto else []),
            "image_layout": "single",
            "text_items": [{"text": f"texto {i}", "font_size": "large"}],
            "is_cta": False, "background_opacity": 0.35,
            "duration": 3.0, "source": "manual",
        })
    return json.dumps({"title": "t", "aspect_ratio": "4:5", "slides": slides,
                       "caption": "cap", "language": "es",
                       "brief": {"tema": "t", "estilo": "tiktok_bold"},
                       "formato": "listicle", "account_slug": "gdlscene"})


def _fila_slideshow(cx, **overrides):
    campos = dict(tipo="slideshow", status="programado", aprobacion="aprobado",
                  account_id=1, slideshow_json=_show_json())
    campos.update(overrides)
    return db.insert(cx, "content_queue", **campos)


def test_editar_slides_cambia_textos_y_fondo(tmp_path):
    import json
    cx = _cx(tmp_path)
    qid = _fila_slideshow(cx)
    cola.editar_slides(cx, qid, [
        {"texts": ["hook nuevo"], "image_url": "https://cdn.example.com/a.jpg"},
        {"texts": ["texto 1"], "image_url": None},
    ])
    show = json.loads(db.get(cx, "content_queue", qid)["slideshow_json"])
    assert show["slides"][0]["text_items"][0]["text"] == "hook nuevo"
    assert show["slides"][0]["image_urls"] == ["https://cdn.example.com/a.jpg"]
    assert show["slides"][1]["image_urls"] == []
    # el resto del estilo del text_item no se toca
    assert show["slides"][0]["text_items"][0]["font_size"]


def test_editar_slides_estado_no_editable(tmp_path):
    cx = _cx(tmp_path)
    qid = _fila_slideshow(cx, status="publicado")
    with pytest.raises(ValueError, match="estado"):
        cola.editar_slides(cx, qid, [{"texts": ["a"], "image_url": None},
                                     {"texts": ["b"], "image_url": None}])


def test_editar_slides_solo_slideshow(tmp_path):
    cx = _cx(tmp_path)
    qid = _fila(cx, tipo="meme", status="borrador", aprobacion="pendiente")
    with pytest.raises(ValueError, match="tipo"):
        cola.editar_slides(cx, qid, [{"texts": ["a"], "image_url": None}])


def test_editar_slides_estructura_debe_coincidir(tmp_path):
    cx = _cx(tmp_path)
    qid = _fila_slideshow(cx)
    # número de slides distinto
    with pytest.raises(ValueError, match="estructura"):
        cola.editar_slides(cx, qid, [{"texts": ["a"], "image_url": None}])
    # número de textos distinto en un slide
    with pytest.raises(ValueError, match="estructura"):
        cola.editar_slides(cx, qid, [{"texts": ["a", "b"], "image_url": None},
                                     {"texts": ["c"], "image_url": None}])


def test_editar_slides_texto_vacio_invalido(tmp_path):
    cx = _cx(tmp_path)
    qid = _fila_slideshow(cx)
    with pytest.raises(ValueError, match="estructura"):
        cola.editar_slides(cx, qid, [{"texts": ["   "], "image_url": None},
                                     {"texts": ["b"], "image_url": None}])


def test_editar_slides_url_insegura_rechazada(tmp_path):
    cx = _cx(tmp_path)
    qid = _fila_slideshow(cx)
    with pytest.raises(ValueError, match="url"):
        cola.editar_slides(cx, qid, [
            {"texts": ["a"], "image_url": "http://127.0.0.1/x.jpg"},
            {"texts": ["b"], "image_url": None},
        ])
    with pytest.raises(ValueError, match="url"):
        cola.editar_slides(cx, qid, [
            {"texts": ["a"], "image_url": "file:///etc/passwd"},
            {"texts": ["b"], "image_url": None},
        ])


def test_editar_slides_valor_actual_pasa_sin_validar(tmp_path):
    # Re-mandar el valor ya guardado (p. ej. ruta local elegida por carpeta)
    # nunca falla, aunque no sea una URL http.
    import json
    cx = _cx(tmp_path)
    qid = _fila_slideshow(cx)
    show = json.loads(db.get(cx, "content_queue", qid)["slideshow_json"])
    show["slides"][0]["image_urls"] = ["data/brands/x/fotos/local.jpg"]
    db.update(cx, "content_queue", qid, slideshow_json=json.dumps(show))
    cola.editar_slides(cx, qid, [
        {"texts": ["a"], "image_url": "data/brands/x/fotos/local.jpg"},
        {"texts": ["b"], "image_url": None},
    ])
    fila = json.loads(db.get(cx, "content_queue", qid)["slideshow_json"])
    assert fila["slides"][0]["image_urls"] == ["data/brands/x/fotos/local.jpg"]


def test_editar_slides_foto_del_banco_se_traduce_a_ruta_local(tmp_path, monkeypatch):
    import json

    from src import image_sources
    cx = _cx(tmp_path)
    db.insert(cx, "accounts", slug="pmas", ig_handle="@p", nombre="P", ciudad="X")
    cuenta = db.rows(cx, "SELECT id FROM accounts WHERE slug='pmas'")[0]["id"]
    qid = _fila_slideshow(cx, account_id=cuenta)
    monkeypatch.setattr(image_sources, "BRANDS_DIR", tmp_path / "brands")
    fotos = tmp_path / "brands" / "pmas" / "fotos"
    fotos.mkdir(parents=True)
    (fotos / "playa.jpg").write_bytes(b"x")
    cola.editar_slides(cx, qid, [
        {"texts": ["a"], "image_url": "/brands/pmas/files/fotos/playa.jpg"},
        {"texts": ["b"], "image_url": None},
    ])
    show = json.loads(db.get(cx, "content_queue", qid)["slideshow_json"])
    assert show["slides"][0]["image_urls"] == [str(fotos / "playa.jpg")]


def test_editar_slides_foto_del_banco_inexistente(tmp_path, monkeypatch):
    from src import image_sources
    cx = _cx(tmp_path)
    db.insert(cx, "accounts", slug="pmas", ig_handle="@p", nombre="P", ciudad="X")
    cuenta = db.rows(cx, "SELECT id FROM accounts WHERE slug='pmas'")[0]["id"]
    qid = _fila_slideshow(cx, account_id=cuenta)
    monkeypatch.setattr(image_sources, "BRANDS_DIR", tmp_path / "brands")
    with pytest.raises(ValueError, match="foto"):
        cola.editar_slides(cx, qid, [
            {"texts": ["a"], "image_url": "/brands/pmas/files/fotos/no-existe.jpg"},
            {"texts": ["b"], "image_url": None},
        ])
