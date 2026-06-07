"""Tests del modelo por TIPO de actor: prompt, filtro de fotos y triage."""
from __future__ import annotations

from src import db
from src.caption import _build_user_prompt
from src.classify import decidir_usable
from src.triage_candidates import clasificar


def test_prompt_banda_no_cambia() -> None:
    """La voz base de banda no se altera: sin bloque de tipo, con integrante/rol."""
    p = _build_user_prompt("Kabala", "Cesar", "guitarrista", None, None, "banda")
    assert "TIPO DE SUJETO" not in p
    assert "- Banda: Kabala" in p
    assert "- Integrante: Cesar" in p


def test_prompt_foro_redefine_sujeto_y_omite_integrante() -> None:
    p = _build_user_prompt("Pulque Degollado", "algo", "algo", None, None, "foro")
    assert "TIPO DE SUJETO: FORO" in p
    assert "- Foro: Pulque Degollado" in p
    assert "Integrante" not in p  # un foro no tiene integrantes
    assert "no le inventes integrantes" in p


def test_prompt_evento_y_colectivo() -> None:
    assert "TIPO DE SUJETO: EVENTO" in _build_user_prompt("Pool Sessions", "", "", None, None, "evento")
    assert "comunicado" in _build_user_prompt("Cuerda Cultura", "", "", None, None, "colectivo")


def test_prompt_solista_individual() -> None:
    p = _build_user_prompt("Roverplancken", "", "", None, None, "solista")
    assert "SOLISTA" in p and "singular" in p


def test_filtro_fotos_por_tipo() -> None:
    arriba = 100.0  # nitidez sobre umbral
    # banda/solista exigen cara
    assert decidir_usable(0, arriba, flyer=False, tipo="banda") is False
    assert decidir_usable(1, arriba, flyer=False, tipo="banda") is True
    # foro/evento/colectivo NO exigen cara
    for t in ("foro", "evento", "colectivo"):
        assert decidir_usable(0, arriba, flyer=False, tipo=t) is True
    # pero un flyer o foto borrosa nunca es usable, sea cual sea el tipo
    assert decidir_usable(0, arriba, flyer=True, tipo="foro") is False
    assert decidir_usable(3, 1.0, flyer=False, tipo="banda") is False


def test_triage_clasifica_tipos() -> None:
    assert clasificar("Musician/band", "") == ("banda", "activar", "categoría IG: Musician/band")
    assert clasificar("Bar", "")[0] == "foro"
    assert clasificar("Live music venue", "")[0] == "foro"
    assert clasificar("Festival", "")[0] == "evento"
    assert clasificar("Record label", "")[0] == "colectivo"
    assert clasificar("Community", "")[0] == "colectivo"
    # fotógrafo/tienda → recomendar borrar
    assert clasificar("Photographer", "")[1] == "borrar"
    # sin categoría → dudosa
    assert clasificar(None, "")[1] == "dudosa"
    # sin categoría pero bio de foro → dudosa con tipo tentativo foro
    assert clasificar(None, "foro cultural en el centro")[0] == "foro"


def test_tipo_de_actor_default_banda(tmp_path) -> None:
    p = tmp_path / "t.db"
    cx = db.connect(p)
    db.init_db(cx)
    db.insert(cx, "bands", nombre="Pulque Degollado", tipo="foro")
    cx.close()
    assert db.tipo_de_actor("Pulque Degollado", p) == "foro"
    assert db.tipo_de_actor("No Existe", p) == "banda"  # default
    assert db.tipo_de_actor(None, p) == "banda"
