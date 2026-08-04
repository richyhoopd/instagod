from __future__ import annotations

from pathlib import Path

import pytest

from src import db, venues, venues_seed


@pytest.fixture()
def cx(tmp_path: Path):
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    yield conn
    conn.close()


def _evento(cx, band_id, lugar):
    return db.insert(cx, "events", band_id=band_id, tipo="flyer",
                     fecha_evento="2026-08-23", lugar=lugar)


def test_siembra_desde_bands_usa_los_foros_que_ya_sigue(cx) -> None:
    db.insert(cx, "bands", nombre="STADITCHE", ig_handle="staditche",
              tipo="foro", activa=1, ciudad="Guadalajara")
    db.insert(cx, "bands", nombre="Pool Sessions", ig_handle="poolsessions_",
              tipo="evento", activa=1)
    db.insert(cx, "bands", nombre="Kabala", ig_handle="kabala_oficial",
              tipo="banda", activa=1)
    assert venues_seed.sembrar_desde_bands(cx) == 2      # la banda NO entra
    nombres = {v["nombre"] for v in db.rows(cx, "SELECT nombre FROM venues")}
    assert nombres == {"STADITCHE", "Pool Sessions"}
    # El nombre y el handle quedan como alias, así ambos resuelven.
    assert venues.resolver(cx, "@staditche") is not None
    assert venues.resolver(cx, "STADITCHE") is not None


def test_siembra_desde_bands_marca_origen_semilla(cx) -> None:
    """Los alias sembrados desde bands son 'semilla', no 'manual': nadie los
    curó a mano, salieron de una cuenta que Ricardo ya sigue."""
    db.insert(cx, "bands", nombre="Pool Sessions", ig_handle="poolsessions_",
              tipo="evento", activa=1)
    venues_seed.sembrar_desde_bands(cx)
    origenes = {r["origen"] for r in db.rows(cx, "SELECT origen FROM venue_alias")}
    assert origenes == {"semilla"}


def test_siembra_desde_bands_es_idempotente(cx) -> None:
    db.insert(cx, "bands", nombre="Cuerda", ig_handle="cuerdacultura",
              tipo="foro", activa=1)
    venues_seed.sembrar_desde_bands(cx)
    assert venues_seed.sembrar_desde_bands(cx) == 0
    assert len(db.rows(cx, "SELECT * FROM venues")) == 1


def test_agrupar_mecanico_colapsa_las_escrituras_obvias() -> None:
    grupos = venues_seed.agrupar_mecanico([
        "Staditche", "staditche", "@staditche", "Staditche (Espacio Cultural)",
        "Cuerda Cultura",
    ])
    assert set(grupos) == {"staditche", "cuerda cultura"}
    assert len(grupos["staditche"]) == 4


def test_sembrar_resuelve_lo_mecanico_sin_llm(cx) -> None:
    """Lo que la normalización ya colapsa no debe llegar al LLM."""
    db.insert(cx, "bands", nombre="STADITCHE", ig_handle="staditche",
              tipo="foro", activa=1)
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    for texto in ("@staditche", "Staditche (Espacio Cultural)", "STADITCHE"):
        _evento(cx, bid, texto)
    vistos = {}

    def _llm(pendientes):
        vistos["pendientes"] = list(pendientes)
        return []

    venues_seed.sembrar(cx, _llm=_llm)
    assert vistos["pendientes"] == []     # nada ambiguo que consultar


def test_sembrar_aplica_lo_que_propone_el_llm(cx) -> None:
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    _evento(cx, bid, "REY")
    _evento(cx, bid, "Hake al Rey")

    def _llm(pendientes):
        return [{"canonico": "Hake Al Rey", "alias": ["REY", "Hake al Rey"]}]

    res = venues_seed.sembrar(cx, _llm=_llm)
    assert res["venues"] >= 1
    assert venues.resolver(cx, "REY") == venues.resolver(cx, "Hake al Rey")


def test_sembrar_no_pisa_lo_curado(cx) -> None:
    """Un alias asignado a mano sobrevive aunque el LLM proponga otra cosa."""
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    _evento(cx, bid, "REY")
    mio = db.insert(cx, "venues", nombre="Mi Foro")
    venues.asignar_alias(cx, mio, "REY")

    def _llm(pendientes):
        return [{"canonico": "Otro Foro", "alias": ["REY"]}]

    venues_seed.sembrar(cx, _llm=_llm)
    assert venues.resolver(cx, "REY") == mio


def test_sembrar_no_pisa_lo_sembrado_desde_bands(cx) -> None:
    """Un alias con origen='semilla' tampoco lo pisa una propuesta del LLM.

    Debe fallar si el chequeo de protección se reduce a solo 'manual'.
    """
    db.insert(cx, "bands", nombre="STADITCHE", ig_handle="staditche",
              tipo="foro", activa=1)

    def _llm(pendientes):
        return [{"canonico": "Otro Foro", "alias": ["staditche"]}]

    venues_seed.sembrar(cx, _llm=_llm)
    foro = db.rows(cx, "SELECT id FROM venues WHERE nombre = 'STADITCHE'")[0]["id"]
    assert venues.resolver(cx, "staditche") == foro


def test_sembrar_no_revive_lo_marcado_como_no_es_lugar(cx) -> None:
    """Lo descartado a mano no vuelve, y sobre todo NO se liga a un foro real:
    ligarlo fusionaría en la agenda un evento con otro que no tiene que ver."""
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    _evento(cx, bid, "siamesasperdidas")
    aid = venues.registrar_desconocido(cx, "siamesasperdidas")
    venues.marcar_no_es_lugar(cx, aid)

    def _llm(pendientes):
        return [{"canonico": "Hake Al Rey", "alias": ["siamesasperdidas"]}]

    venues_seed.sembrar(cx, _llm=_llm)
    fila = db.get(cx, "venue_alias", aid)
    assert fila["origen"] == "no_es_lugar"
    assert fila["venue_id"] is None
    assert venues.huerfanos(cx) == []


def test_sembrar_no_le_pregunta_al_llm_por_lo_ya_curado(cx) -> None:
    """Ni tokens ni ruido: lo descartado y lo desasignado a mano no son pendientes."""
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    _evento(cx, bid, "siamesasperdidas")
    _evento(cx, bid, "C3 Rooftop")
    _evento(cx, bid, "Foro Desconocido")
    venues.marcar_no_es_lugar(cx, venues.registrar_desconocido(cx, "siamesasperdidas"))
    venues.desasignar_alias(cx, venues.registrar_desconocido(cx, "C3 Rooftop"))
    vistos = {}

    def _llm(pendientes):
        vistos["pendientes"] = list(pendientes)
        return []

    venues_seed.sembrar(cx, _llm=_llm)
    assert vistos["pendientes"] == ["Foro Desconocido"]


def test_sembrar_no_pisa_un_alias_desasignado_a_mano(cx) -> None:
    """Desasignar es una decisión humana: el batch no puede deshacerla."""
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    _evento(cx, bid, "C3 Rooftop")
    aid = venues.registrar_desconocido(cx, "C3 Rooftop")
    venues.desasignar_alias(cx, aid)

    venues_seed.sembrar(cx, _llm=lambda p: [{"canonico": "C3 Stage",
                                             "alias": ["C3 Rooftop"]}])
    assert db.get(cx, "venue_alias", aid)["venue_id"] is None


def test_sembrar_descarta_grupo_que_no_es_dict(cx) -> None:
    """Si el LLM devuelve una lista de strings en vez de objetos, la siembra
    termina (no truena) y descarta cada elemento mal formado."""
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    _evento(cx, bid, "REY")

    res = venues_seed.sembrar(cx, _llm=lambda pendientes: ["REY", "Hake al Rey"])
    assert res["grupos_invalidos"] == 2
    letras = db.rows(cx, "SELECT alias_norm FROM venue_alias WHERE length(alias_norm) = 1")
    assert letras == []


def test_sembrar_descarta_alias_como_string(cx) -> None:
    """'alias': 'REY' (cadena suelta) no debe fragmentarse en alias de una
    sola letra: es la corrupción silenciosa del catálogo."""
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    _evento(cx, bid, "REY")

    def _llm(pendientes):
        return [{"canonico": "Hake Al Rey", "alias": "REY"}]

    res = venues_seed.sembrar(cx, _llm=_llm)
    assert res["grupos_invalidos"] == 1
    letras = db.rows(cx, "SELECT alias_norm FROM venue_alias WHERE length(alias_norm) = 1")
    assert letras == []


def test_sembrar_descarta_canonico_no_string(cx) -> None:
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    _evento(cx, bid, "REY")

    def _llm(pendientes):
        return [{"canonico": ["Hake", "Al", "Rey"], "alias": ["REY"]}]

    res = venues_seed.sembrar(cx, _llm=_llm)
    assert res["grupos_invalidos"] == 1
    letras = db.rows(cx, "SELECT alias_norm FROM venue_alias WHERE length(alias_norm) = 1")
    assert letras == []


def test_sembrar_completo_es_idempotente(cx) -> None:
    """Correr sembrar() dos veces con el mismo _llm no duplica venues ni alias."""
    db.insert(cx, "bands", nombre="STADITCHE", ig_handle="staditche",
              tipo="foro", activa=1)
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    _evento(cx, bid, "REY")
    _evento(cx, bid, "Hake al Rey")

    def _llm(pendientes):
        return [{"canonico": "Hake Al Rey", "alias": ["REY", "Hake al Rey"]}]

    venues_seed.sembrar(cx, _llm=_llm)
    n_venues = len(db.rows(cx, "SELECT * FROM venues"))
    n_alias = len(db.rows(cx, "SELECT * FROM venue_alias"))

    venues_seed.sembrar(cx, _llm=_llm)
    assert len(db.rows(cx, "SELECT * FROM venues")) == n_venues
    assert len(db.rows(cx, "SELECT * FROM venue_alias")) == n_alias


def _cliente_openai_falso(contenido: str, capturado: dict):
    """Doble del cliente de openai que devuelve `contenido` como respuesta cruda.

    Los demás tests inyectan `_llm=` y por eso nunca ejercitan el parseo de la
    respuesta del modelo — que es exactamente donde vivía el bug de que
    `_llm_agrupar` devolvía [] siempre.
    """
    from types import SimpleNamespace

    def create(**kwargs):
        capturado.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=contenido))])

    return lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_llm_agrupar_parsea_la_respuesta_cruda_del_modelo(monkeypatch) -> None:
    """Un {"grupos": [...]} con DOS grupos devuelve los dos (antes: ninguno)."""
    import openai
    capturado: dict = {}
    crudo = ('```json\n{"grupos": ['
             '{"canonico": "Hake Al Rey", "alias": ["REY"]}, '
             '{"canonico": "Staditche", "alias": ["@staditche"]}]}\n```')
    monkeypatch.setattr(openai, "OpenAI", _cliente_openai_falso(crudo, capturado))

    grupos = venues_seed._llm_agrupar(["REY", "@staditche"])
    assert [g["canonico"] for g in grupos] == ["Hake Al Rey", "Staditche"]
    assert [g["alias"] for g in grupos] == [["REY"], ["@staditche"]]
    # El prompt pide el objeto que el parser sí entiende, y la llamada lo exige.
    assert '"grupos"' in capturado["messages"][0]["content"]
    assert capturado["response_format"] == {"type": "json_object"}
    assert capturado["max_tokens"] >= 2000


def test_llm_agrupar_avisa_si_no_saca_grupos_habiendo_pendientes(monkeypatch, capsys) -> None:
    """Un cero silencioso es lo que hizo que el bug sobreviviera; debe gritar."""
    import openai
    monkeypatch.setattr(openai, "OpenAI", _cliente_openai_falso("no puedo ayudarte", {}))
    assert venues_seed._llm_agrupar(["REY"]) == []
    assert "ADVERTENCIA" in capsys.readouterr().out


def test_llm_agrupar_sin_pendientes_no_llama_al_modelo(monkeypatch) -> None:
    import openai

    def _explota(**_):
        raise AssertionError("no debe construirse el cliente sin pendientes")

    monkeypatch.setattr(openai, "OpenAI", _explota)
    assert venues_seed._llm_agrupar([]) == []


def test_sembrar_deja_huerfano_lo_que_el_llm_no_agrupa(cx) -> None:
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    _evento(cx, bid, "GRAL.MANUEL pm COVER M.DIEGUEZ #71")

    res = venues_seed.sembrar(cx, _llm=lambda pendientes: [])
    assert res["huerfanos"] == 1
    assert len(venues.huerfanos(cx)) == 1


def test_sembrar_ignora_eventos_sin_lugar(cx) -> None:
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    _evento(cx, bid, None)
    _evento(cx, bid, "")
    res = venues_seed.sembrar(cx, _llm=lambda pendientes: [])
    assert res["huerfanos"] == 0


def test_backfill_llena_venue_id(cx) -> None:
    vid = db.insert(cx, "venues", nombre="Hake Al Rey")
    venues.asignar_alias(cx, vid, "Hake al Rey")
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    con = _evento(cx, bid, "HAKE AL REY")
    sin = _evento(cx, bid, "Foro Desconocido")
    assert venues_seed.backfill_eventos(cx) == 1
    assert db.get(cx, "events", con)["venue_id"] == vid
    assert db.get(cx, "events", sin)["venue_id"] is None


def test_backfill_es_idempotente(cx) -> None:
    vid = db.insert(cx, "venues", nombre="Cuerda")
    venues.asignar_alias(cx, vid, "Cuerda Cultura")
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    _evento(cx, bid, "cuerda cultura")
    venues_seed.backfill_eventos(cx)
    assert venues_seed.backfill_eventos(cx) == 1


def test_backfill_deja_huerfano_lo_no_resuelto(cx) -> None:
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    _evento(cx, bid, "Foro Nunca Visto")
    venues_seed.backfill_eventos(cx)
    assert [h["alias_visto"] for h in venues.huerfanos(cx)] == ["Foro Nunca Visto"]


def test_parse_event_resuelve_venue_id(cx, monkeypatch) -> None:
    """Al guardar el lugar, el evento queda ligado al foro si ya se conoce."""
    from src import parse_events
    vid = db.insert(cx, "venues", nombre="Hake Al Rey")
    venues.asignar_alias(cx, vid, "Hake al Rey")
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    eid = db.insert(cx, "events", band_id=bid, tipo="flyer", source_post_id="X")
    # `parse_event` arma el prompt de OCR + caption; sin flyer en disco y sin
    # foto en `photos` no habría texto, así que sembramos el caption.
    db.insert(cx, "photos", band_id=bid, path="p.jpg", source_post_id="X",
              caption_original="tocada el sabado")
    monkeypatch.setattr(parse_events, "_llm_extraer",
                        lambda prompt: {"tipo": "fecha", "fecha": "2026-08-23",
                                        "lugar": "HAKE AL REY", "ciudad": None})
    parse_events.parse_event(cx, db.get(cx, "events", eid))
    assert db.get(cx, "events", eid)["venue_id"] == vid


def test_parse_event_deja_huerfano_lo_no_resuelto(cx, monkeypatch) -> None:
    from src import parse_events
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    eid = db.insert(cx, "events", band_id=bid, tipo="flyer", source_post_id="Y")
    db.insert(cx, "photos", band_id=bid, path="p.jpg", source_post_id="Y",
              caption_original="tocada el sabado")
    monkeypatch.setattr(parse_events, "_llm_extraer",
                        lambda prompt: {"tipo": "fecha", "fecha": "2026-08-23",
                                        "lugar": "Foro Jamás Visto", "ciudad": None})
    parse_events.parse_event(cx, db.get(cx, "events", eid))
    assert db.get(cx, "events", eid)["venue_id"] is None
    assert [h["alias_visto"] for h in venues.huerfanos(cx)] == ["Foro Jamás Visto"]
