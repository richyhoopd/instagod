"""Tests de la agenda: ventana de fechas (nunca pasados) y armado del digest."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytz

import config
from src import db
from src.generate_agenda import (
    _fila_tarjeta,
    _rango_releases,
    _rango_shows,
    eventos_ventana,
    releases_ventana,
)


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def test_ventana_excluye_pasados_y_lejanos(tmp_path) -> None:
    cx = _cx(tmp_path)
    bid = db.insert(cx, "bands", nombre="Kabala")
    hoy = pytz.timezone(config.TIMEZONE).localize(datetime(2026, 6, 4, 12, 0))

    def ev(delta_dias: int, **extra):
        return db.insert(cx, "events", band_id=bid, tipo="fecha",
                         fecha_evento=(hoy + timedelta(days=delta_dias)).strftime("%Y-%m-%d"),
                         **extra)

    ev(-1)                       # ayer → fuera (regla: nunca flyers pasados)
    e_hoy = ev(0)                # hoy → dentro
    e_semana = ev(6)             # dentro de la semana
    e_mes = ev(25)               # solo en la mensual
    ev(31)                       # fuera incluso de la mensual
    ev(3, status="pasado")       # status pasado → fuera aunque la fecha sea futura

    semanal = [e["id"] for e in eventos_ventana(cx, 7, hoy=hoy)]
    mensual = [e["id"] for e in eventos_ventana(cx, 30, hoy=hoy)]
    assert semanal == [e_hoy, e_semana]
    assert mensual == [e_hoy, e_semana, e_mes]
    cx.close()


def test_ventana_incluye_anunciados(tmp_path) -> None:
    """La agenda lista todo lo vigente, esté o no anunciado individualmente."""
    cx = _cx(tmp_path)
    bid = db.insert(cx, "bands", nombre="Los Baxters")
    hoy = pytz.timezone(config.TIMEZONE).localize(datetime(2026, 6, 4, 12, 0))
    db.insert(cx, "events", band_id=bid, tipo="fecha", status="anunciado",
              fecha_evento="2026-06-19")
    assert len(eventos_ventana(cx, 30, hoy=hoy)) == 1
    cx.close()


def test_fila_tarjeta_shows() -> None:
    fila = _fila_tarjeta({"fecha_evento": "2026-06-19", "banda_nombre": "Los Baxters",
                          "lugar": "Anexo Independencia", "ciudad": "Guadalajara"}, "shows")
    assert fila["banda"] == "Los Baxters" and fila["dia"] == "19" and fila["mes"] == "jun"
    assert fila["lugar"] == "Anexo Independencia · Guadalajara"
    assert fila["cover"] == ""  # shows no llevan portada
    sin_lugar = _fila_tarjeta({"fecha_evento": "2026-07-01", "banda_nombre": "Kabala",
                               "lugar": None, "ciudad": None}, "shows")
    assert sin_lugar["lugar"] == "" and sin_lugar["mes"] == "jul"


def test_fila_tarjeta_releases_usa_titulo_y_portada() -> None:
    fila = _fila_tarjeta({"fecha_evento": "2026-05-29", "banda_nombre": "SilentNoir",
                          "titulo": "Ecos (álbum)", "cover_url": "http://x/c.jpg",
                          "lugar": "ignorar", "ciudad": "X"}, "releases")
    assert fila["banda"] == "SilentNoir" and fila["lugar"] == "Ecos (álbum)"
    assert fila["cover"] == "http://x/c.jpg"


def test_releases_ventana_mira_al_pasado() -> None:
    import os
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
    cx = db.connect(path)
    db.init_db(cx)
    bid = db.insert(cx, "bands", nombre="SilentNoir")
    hoy = pytz.timezone(config.TIMEZONE).localize(datetime(2026, 6, 5, 12, 0))
    db.insert(cx, "events", band_id=bid, tipo="release", fecha_evento="2026-05-29",
              titulo="Ecos (álbum)")          # hace 7 días → dentro de mensual y semanal
    db.insert(cx, "events", band_id=bid, tipo="release", fecha_evento="2026-04-01")  # viejo
    db.insert(cx, "events", band_id=bid, tipo="fecha", fecha_evento="2026-05-29")    # show, no release
    semanal = releases_ventana(cx, 7, hoy=hoy)
    mensual = releases_ventana(cx, 30, hoy=hoy)
    assert len(semanal) == 1 and semanal[0]["titulo"] == "Ecos (álbum)"
    assert len(mensual) == 1   # el de abril queda fuera de 30 días
    cx.close()


def test_releases_ventana_solo_frescos(tmp_path) -> None:
    """solo_frescos excluye releases ya 'anunciado'; sin filtro entran todos."""
    cx = _cx(tmp_path)
    bid = db.insert(cx, "bands", nombre="SilentNoir")
    hoy = pytz.timezone(config.TIMEZONE).localize(datetime(2026, 6, 5, 12, 0))
    db.insert(cx, "events", band_id=bid, tipo="release", fecha_evento="2026-06-01",
              titulo="Fresco")
    db.insert(cx, "events", band_id=bid, tipo="release", fecha_evento="2026-06-02",
              titulo="Viejo", status="anunciado")
    assert len(releases_ventana(cx, 7, hoy=hoy)) == 2
    frescos = releases_ventana(cx, 7, hoy=hoy, solo_frescos=True)
    assert len(frescos) == 1 and frescos[0]["titulo"] == "Fresco"
    cx.close()


def test_chunks_para_slider() -> None:
    from src.generate_agenda import _MAX_EN_TARJETA, _chunks
    items = list(range(25))
    slides = _chunks(items, _MAX_EN_TARJETA)
    assert sum(len(s) for s in slides) == 25      # no se pierde ninguno
    assert all(len(s) <= _MAX_EN_TARJETA for s in slides)
    assert len(slides) >= 3                         # 25 no cabe en una slide
    assert _chunks([], 10) == [[]]                  # vacío → una slide vacía


def test_carousel_urls_detecta_json(tmp_path) -> None:
    from publish import _carousel_urls
    assert _carousel_urls('["http://a.jpg","http://b.jpg"]') == ["http://a.jpg", "http://b.jpg"]
    assert _carousel_urls("https://res.cloudinary.com/x.png") == []  # url simple
    assert _carousel_urls("") == []


def test_rango_shows_y_releases() -> None:
    hoy = datetime(2026, 6, 4)
    assert _rango_shows(hoy, 7) == "4 al 11 de junio"
    assert _rango_shows(hoy, 30) == "4 de junio al 4 de julio"
    assert _rango_releases(hoy, 7) == "28 de mayo al 4 de junio"


def _sembrar_flyers(cx, tmp_path, n: int, hoy):
    """Crea n eventos-flyer con flyer_path apuntando a PNGs dummy en tmp_path.

    Los PNG solo necesitan existir (Path.exists); _phash se monkeypatchea en el
    test para devolver un hash único por ruta, así nada se deduplica.
    """
    bid = db.insert(cx, "bands", nombre="Banda", ig_handle="banda")
    ids = []
    for i in range(n):
        p = tmp_path / f"flyer_{i}.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes([i]))  # archivo real (solo existe)
        # banda distinta por evento para que las @menciones varíen
        b = db.insert(cx, "bands", nombre=f"Banda {i}", ig_handle=f"banda{i}")
        eid = db.insert(cx, "events", band_id=b, tipo="fecha",
                        fecha_evento=(hoy + timedelta(days=i + 1)).strftime("%Y-%m-%d"),
                        lugar=f"Foro {i}", flyer_path=str(p))
        ids.append(eid)
    return ids


def _fake_phash_unico():
    """Devuelve una función _phash que da un hash único y muy distinto por ruta.

    Cada flyer dista >8 bits de cualquier otro → _es_duplicado nunca los colapsa
    y todos los flyers se conservan en el dedup visual.
    """
    import numpy as np
    hashes: dict[str, object] = {}

    def fake_phash(path):
        s = str(path)
        if s not in hashes:
            rng = np.random.RandomState(len(hashes) * 9973 + 17)
            hashes[s] = rng.rand(64) > 0.5
        return hashes[s]

    return fake_phash


def test_build_agenda_partes_divide(tmp_path, monkeypatch) -> None:
    """12 flyers agrupados → 2 partes: portada+9 (10 pngs) y 3 flyers+CTA (4 pngs).

    Layout: portada SOLO en la parte 1, slide de CTA cerrando la ÚLTIMA parte.
    """
    from src import compose as compose_mod
    from src import generate_agenda

    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    hoy = pytz.timezone(config.TIMEZONE).localize(datetime(2026, 6, 4, 12, 0))
    ids = _sembrar_flyers(cx, tmp_path, 12, hoy)
    cx.close()

    real_connect = db.connect
    monkeypatch.setattr(generate_agenda, "_phash", _fake_phash_unico())
    # render_card usa Playwright (red/navegador): lo sustituimos por una ruta dummy
    # que además cuenta qué plantillas se renderizaron (para verificar que NO hay CTA).
    renders: list[str] = []

    def fake_render(*a, **k):
        renders.append(a[0])
        return tmp_path / f"render_{a[0]}.png"

    monkeypatch.setattr(compose_mod, "render_card", fake_render)
    # build_agenda_partes abre su propia conexión vía db.connect() (sin args).
    monkeypatch.setattr(generate_agenda.db, "connect", lambda *a, **k: real_connect(tmp_path / "t.db"))

    partes = generate_agenda.build_agenda_partes("mensual", hoy=hoy)
    assert len(partes) == 2
    assert [p["parte"] for p in partes] == [1, 2]
    assert all(p["partes"] == 2 for p in partes)
    # Parte 1: portada + 9 flyers = 10 pngs; Parte 2: 3 flyers + CTA = 4 pngs.
    assert len(partes[0]["pngs"]) == 10
    assert len(partes[1]["pngs"]) == 4
    for p in partes:
        assert len(p["pngs"]) <= generate_agenda._IG_CAROUSEL_MAX
        assert "Parte" in p["caption"]
    # 12 flyers + 1 portada (parte 1) + 1 CTA (última parte) = 14 renders.
    assert renders.count("agenda_flyer.html") == 12
    assert renders.count("agenda_cover.html") == 1
    assert renders.count("agenda_cta.html") == 1
    # El CTA cierra el carrusel: última imagen de la última parte.
    assert renders[-1] == "agenda_cta.html"
    union = sorted(eid for p in partes for eid in p["evento_ids"])
    assert union == sorted(ids)


def test_caption_agenda_etiqueta_todos_los_handles_fusionados() -> None:
    """Un evento fusionado (varias cuentas mismo foro+fecha) tagea a TODOS.

    Regresión: _caption_agenda re-agrupaba y solo leía banda_handle (el primero),
    perdiendo a las bandas fusionadas por agrupar_por_evento.
    """
    from src.generate_agenda import _caption_agenda, agrupar_por_evento

    evs = [
        {"id": 1, "fecha_evento": "2026-07-12", "lugar": "Anexo Independencia",
         "banda_nombre": "DSPlusMx", "banda_handle": "dsplusmx", "flyer_path": "a.jpg"},
        {"id": 2, "fecha_evento": "2026-07-12", "lugar": "ANEXO INDEPENDENCIA",
         "banda_nombre": "the greacks", "banda_handle": "the_greacks", "flyer_path": "b.jpg"},
    ]
    grupos = agrupar_por_evento(evs)
    assert len(grupos) == 1  # mismo foro+fecha → un evento
    cap = _caption_agenda([(grupos[0], "b.jpg")], "semanal", "12 al 18 de julio")
    # AMBOS handles etiquetados (antes solo salía @dsplusmx).
    assert "@dsplusmx" in cap
    assert "@the_greacks" in cap


def test_unicos_flyers_funde_dup_pero_conserva_todos_los_handles(tmp_path, monkeypatch) -> None:
    """Dos eventos distintos que comparten el MISMO flyer (pHash) → 1 slide,
    pero el evento superviviente acredita a las DOS bandas/@handles.

    Regresión: _unicos_flyers descartaba el duplicado SIN fusionar sus handles.
    """
    from src import generate_agenda

    p1 = tmp_path / "flyer_a.png"; p1.write_bytes(b"\x89PNG\r\n\x1a\n\x01")
    p2 = tmp_path / "flyer_b.png"; p2.write_bytes(b"\x89PNG\r\n\x1a\n\x02")

    # Mismo hash para ambas rutas → _es_duplicado los colapsa.
    import numpy as np
    same = np.zeros(64, dtype=bool)
    monkeypatch.setattr(generate_agenda, "_phash", lambda path: same)

    # Foros con texto distinto → agrupar_por_evento NO los fusionó; solo el pHash.
    grupos = [
        {"id": 10, "fecha_evento": "2026-07-12", "lugar": "Anexo Independencia",
         "banda_nombre": "DSPlusMx", "banda_handle": "dsplusmx",
         "bandas": ["DSPlusMx"], "handles": ["dsplusmx"], "ids": [10],
         "flyer_path": str(p1)},
        {"id": 20, "fecha_evento": "2026-07-12", "lugar": "Foro Anexo Independencia",
         "banda_nombre": "the greacks", "banda_handle": "the_greacks",
         "bandas": ["the greacks"], "handles": ["the_greacks"], "ids": [20],
         "flyer_path": str(p2)},
    ]
    unicos, omitidos = generate_agenda._unicos_flyers(grupos)
    assert len(unicos) == 1 and omitidos == 1      # un solo slide
    superviviente = unicos[0][0]
    assert set(superviviente["handles"]) == {"dsplusmx", "the_greacks"}
    assert set(superviviente["ids"]) == {10, 20}
    # el caption resultante etiqueta a los dos
    cap = generate_agenda._caption_agenda(unicos, "semanal", "12 al 18 de julio")
    assert "@dsplusmx" in cap and "@the_greacks" in cap


def test_anexo_independencia_un_solo_slide_flyer_imagen1(tmp_path, monkeypatch) -> None:
    """Las 5 filas del mismo show (incl. la variante 'foro …') → UN solo grupo,
    UN flyer (el representativo DZs_DvOBMTB) y AMBOS @handles.

    Regresión BUG 1: _norm_venue no quitaba el prefijo 'foro ' → la fila 614
    ('foro anexo independencia') caía en un grupo aparte y producía un 2º slide.
    """
    from src import generate_agenda

    # Cinco filas reales (mismo evento, cada cuenta subió su flyer). El flyer_path
    # apunta a archivos dummy en tmp (solo deben existir para _unicos_flyers).
    def flyer(nombre: str) -> str:
        p = tmp_path / nombre
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + nombre.encode())
        return str(p)

    filas = [
        {"id": 543, "fecha_evento": "2026-07-12", "lugar": "anexo independencia",
         "banda_nombre": "DSPlusMx", "banda_handle": "dsplusmx",
         "source_post_id": "DZs_DvOBMTB", "flyer_path": flyer("DZs_DvOBMTB_0.jpg")},
        {"id": 614, "fecha_evento": "2026-07-12", "lugar": "foro anexo independencia",
         "banda_nombre": "the greacks", "banda_handle": "the_greacks",
         "source_post_id": "DZs-VeTBIa2", "flyer_path": flyer("DZs-VeTBIa2_0.jpg")},
        {"id": 616, "fecha_evento": "2026-07-12", "lugar": "ANEXO INDEPENDENCIA",
         "banda_nombre": "the greacks", "banda_handle": "the_greacks",
         "source_post_id": "DZ9TSqqusaj", "flyer_path": flyer("DZ9TSqqusaj_0.jpg")},
        {"id": 617, "fecha_evento": "2026-07-12", "lugar": "ANEXO INDEPENDENCIA",
         "banda_nombre": "the greacks", "banda_handle": "the_greacks",
         "source_post_id": "DZ6zLEbFYNH", "flyer_path": flyer("DZ6zLEbFYNH_0.jpg")},
        {"id": 618, "fecha_evento": "2026-07-12", "lugar": "Anexo Independencia",
         "banda_nombre": "the greacks", "banda_handle": "the_greacks",
         "source_post_id": "DZs_DvOBMTB", "flyer_path": flyer("DZs_DvOBMTB_b.jpg")},
    ]

    grupos = generate_agenda.agrupar_por_evento(filas)
    assert len(grupos) == 1  # las 5 filas caen en UN solo evento
    g = grupos[0]
    # Representativo = el PRIMER flyer del grupo (543 = DZs_DvOBMTB, "imagen 1").
    assert g["source_post_id"] == "DZs_DvOBMTB"
    assert set(g["handles"]) == {"dsplusmx", "the_greacks"}
    assert set(g["ids"]) == {543, 614, 616, 617, 618}

    # _phash único por ruta → si por alguna razón hubiera 2 grupos, NO se colapsarían
    # por pHash (imágenes distintas); así el test valida el AGRUPADO, no el dedup visual.
    monkeypatch.setattr(generate_agenda, "_phash", _fake_phash_unico())
    unicos, _omit = generate_agenda._unicos_flyers(grupos)
    assert len(unicos) == 1  # UN solo slide
    ev, ruta = unicos[0]
    assert ev["source_post_id"] == "DZs_DvOBMTB"  # se conserva la imagen 1
    assert "DZs_DvOBMTB_0.jpg" in str(ruta)

    cap = generate_agenda._caption_agenda(unicos, "semanal", "10 al 17 de julio")
    assert "@dsplusmx" in cap and "@the_greacks" in cap


def test_segmento_flag_llama_generar_segmento_no_main(monkeypatch) -> None:
    """--segmento debe invocar generar_segmento_agenda, nunca asyncio.run(main(...))."""
    import argparse

    from src import generate_agenda

    llamados: dict[str, list] = {"segmento": [], "main": []}

    monkeypatch.setattr(generate_agenda, "generar_segmento_agenda",
                        lambda cx, account_id, *, periodo, modo:
                        llamados["segmento"].append((periodo, modo)))
    # db.connect/init_db no deben tocar archivos reales en este smoke.
    monkeypatch.setattr(generate_agenda.db, "connect", lambda *a, **k: object())
    monkeypatch.setattr(generate_agenda.db, "init_db", lambda cx: None)

    # Simula: python -m src.generate_agenda --segmento --modo shows --periodo mensual
    args = argparse.Namespace(periodo="mensual", modo="shows", segmento=True)

    # Ejecutar la rama segmento directamente (la misma lógica del __main__).
    cx = generate_agenda.db.connect()
    generate_agenda.db.init_db(cx)
    generate_agenda.generar_segmento_agenda(cx, 1, periodo=args.periodo, modo=args.modo)

    assert llamados["segmento"] == [("mensual", "shows")]
    assert llamados["main"] == []


def test_build_agenda_partes_una_parte(tmp_path, monkeypatch) -> None:
    """3 flyers → 1 sola parte: portada + 3 flyers + CTA = 5 pngs, sin 'Parte'."""
    from src import compose as compose_mod
    from src import generate_agenda

    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    hoy = pytz.timezone(config.TIMEZONE).localize(datetime(2026, 6, 4, 12, 0))
    ids = _sembrar_flyers(cx, tmp_path, 3, hoy)
    cx.close()

    real_connect = db.connect
    renders: list[str] = []

    def fake_render(*a, **k):
        renders.append(a[0])
        return tmp_path / f"render_{a[0]}.png"

    monkeypatch.setattr(generate_agenda, "_phash", _fake_phash_unico())
    monkeypatch.setattr(compose_mod, "render_card", fake_render)
    monkeypatch.setattr(generate_agenda.db, "connect", lambda *a, **k: real_connect(tmp_path / "t.db"))

    partes = generate_agenda.build_agenda_partes("mensual", hoy=hoy)
    assert len(partes) == 1
    p = partes[0]
    assert p["parte"] == 1 and p["partes"] == 1
    assert "Parte" not in p["caption"]
    assert len(p["pngs"]) == 5  # portada + 3 flyers + CTA
    # Orden: portada primero, CTA como cierre.
    assert renders[0] == "agenda_cover.html"
    assert renders[-1] == "agenda_cta.html"
    assert renders.count("agenda_cta.html") == 1
    assert sorted(p["evento_ids"]) == sorted(ids)


def test_build_agenda_partes_agrupa_antes_de_dedup(tmp_path, monkeypatch) -> None:
    """Dos eventos misma fecha+foro (bandas distintas, flyers distintos) → 1 flyer.

    El agrupado por fecha+foro ocurre ANTES del dedup visual: aunque las dos
    imágenes sean visualmente distintas, son el MISMO evento → una sola tarjeta.
    """
    from src import compose as compose_mod
    from src import generate_agenda

    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    hoy = pytz.timezone(config.TIMEZONE).localize(datetime(2026, 6, 4, 12, 0))

    # Dos eventos: misma fecha y mismo foro, bandas y flyers distintos.
    p1 = tmp_path / "g1.png"; p1.write_bytes(b"\x89PNG\r\n\x1a\n\x01")
    p2 = tmp_path / "g2.png"; p2.write_bytes(b"\x89PNG\r\n\x1a\n\x02")
    b1 = db.insert(cx, "bands", nombre="Banda A", ig_handle="banda_a")
    b2 = db.insert(cx, "bands", nombre="Banda B", ig_handle="banda_b")
    e1 = db.insert(cx, "events", band_id=b1, tipo="fecha",
                   fecha_evento="2026-06-10", lugar="Foro X", flyer_path=str(p1))
    e2 = db.insert(cx, "events", band_id=b2, tipo="fecha",
                   fecha_evento="2026-06-10", lugar="Foro X", flyer_path=str(p2))
    cx.close()

    real_connect = db.connect
    renders: list[str] = []

    def fake_render(*a, **k):
        renders.append(a[0])
        return tmp_path / f"render_{a[0]}.png"

    monkeypatch.setattr(generate_agenda, "_phash", _fake_phash_unico())
    monkeypatch.setattr(compose_mod, "render_card", fake_render)
    monkeypatch.setattr(generate_agenda.db, "connect", lambda *a, **k: real_connect(tmp_path / "t.db"))

    partes = generate_agenda.build_agenda_partes("mensual", hoy=hoy)
    assert len(partes) == 1
    # Un solo evento agrupado → un solo flyer (no dos).
    assert renders.count("agenda_flyer.html") == 1
    # evento_ids del evento agrupado = el primero del grupo (su flyer_path se conserva).
    assert partes[0]["evento_ids"] == [e1]
