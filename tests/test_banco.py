from __future__ import annotations

import config
from src import banco


def _foto(fid: int, nitidez: float, personas: list[int], **kw):
    """Foto con una cara por persona listada."""
    return {"id": fid, "nitidez": nitidez,
            "caras": [{"persona_idx": p, "det_score": kw.get("score", 0.9),
                       "frac_area": kw.get("frac", 0.2)} for p in personas]}


def test_cupo_reparte_por_persona_no_por_banda() -> None:
    """El caso que motiva el diseño: 10 del vocalista no deben tapar al baterista."""
    fotos = [_foto(i, nitidez=100 - i, personas=[0]) for i in range(10)]
    fotos += [_foto(100 + i, nitidez=10, personas=[1]) for i in range(3)]
    dentro = banco.aplicar_cupo(fotos, por_persona=5, grupales=3, minimo_sin_caras=4)
    de_p0 = {f["id"] for f in fotos if f["caras"][0]["persona_idx"] == 0} & dentro
    de_p1 = {f["id"] for f in fotos if f["caras"][0]["persona_idx"] == 1} & dentro
    assert len(de_p0) == 5          # topada, aunque tenga 10 candidatas
    assert len(de_p1) == 3          # todas, aunque sean menos nítidas


def test_cupo_prefiere_cara_grande_y_confiable() -> None:
    """Nitidez alta con cara diminuta al fondo pierde contra un retrato."""
    lejos = _foto(1, nitidez=200, personas=[0], frac=0.01, score=0.65)
    retrato = _foto(2, nitidez=80, personas=[0], frac=0.35, score=0.99)
    dentro = banco.aplicar_cupo([lejos, retrato], por_persona=1, grupales=0,
                                minimo_sin_caras=4)
    assert dentro == {2}


def test_grupales_tienen_su_propio_cupo() -> None:
    grupales = [_foto(i, nitidez=50, personas=[0, 1, 2]) for i in range(6)]
    dentro = banco.aplicar_cupo(grupales, por_persona=5, grupales=3, minimo_sin_caras=4)
    assert len(dentro) == 3


def test_degradacion_sin_caras() -> None:
    """Banda sin material con caras: conserva las más nítidas hasta el mínimo."""
    fotos = [{"id": i, "nitidez": float(i), "caras": []} for i in range(10)]
    dentro = banco.aplicar_cupo(fotos, por_persona=5, grupales=3, minimo_sin_caras=4)
    assert dentro == {9, 8, 7, 6}


def test_banda_con_caras_no_conserva_las_sin_caras() -> None:
    """Comportamiento VIEJO intacto: para una banda la cubeta sin caras es solo
    degradación de último recurso — con una sola foto con cara ya no aplica."""
    fotos = [_foto(1, nitidez=10, personas=[0])]
    fotos += [{"id": 100 + i, "nitidez": 500.0, "caras": []} for i in range(5)]
    dentro = banco.aplicar_cupo(fotos, por_persona=5, grupales=3, minimo_sin_caras=4)
    assert dentro == {1}


def test_foro_conserva_ambas_cubetas() -> None:
    """El bug que vaciaba el banco de foros: 1 foto con cara mataba a las 39 del
    lugar. Con `admite_sin_caras` la cubeta sin caras tiene cupo propio."""
    fotos = [_foto(1, nitidez=10, personas=[0])]
    fotos += [{"id": 100 + i, "nitidez": 500.0, "caras": []} for i in range(39)]
    dentro = banco.aplicar_cupo(fotos, por_persona=5, grupales=3, minimo_sin_caras=4,
                                admite_sin_caras=True, cupo_sin_caras=20)
    assert 1 in dentro                       # la de cara sigue entrando
    assert len(dentro) == 21                 # + las 20 mejores sin cara
    # Se quedan las más nítidas, no las primeras que aparezcan.
    assert dentro - {1} == {100 + i for i in range(20)}


def test_foro_sin_caras_usa_su_cupo_no_el_minimo() -> None:
    """Sin ninguna cara, un foro NO se queda en los 4 de la degradación."""
    fotos = [{"id": i, "nitidez": float(i), "caras": []} for i in range(30)]
    dentro = banco.aplicar_cupo(fotos, por_persona=5, grupales=3, minimo_sin_caras=4,
                                admite_sin_caras=True, cupo_sin_caras=20)
    assert len(dentro) == 20


def test_cupo_sin_caras_default_viene_de_config() -> None:
    fotos = [{"id": i, "nitidez": float(i), "caras": []} for i in range(50)]
    dentro = banco.aplicar_cupo(fotos, por_persona=5, grupales=3, minimo_sin_caras=4,
                                admite_sin_caras=True)
    assert len(dentro) == config.FOTOS_SIN_CARAS


def test_una_sola_persona_no_gasta_cupo_grupal() -> None:
    fotos = [_foto(i, nitidez=50, personas=[0]) for i in range(8)]
    dentro = banco.aplicar_cupo(fotos, por_persona=5, grupales=3, minimo_sin_caras=4)
    assert len(dentro) == 5


def test_sin_fotos() -> None:
    assert banco.aplicar_cupo([], por_persona=5, grupales=3, minimo_sin_caras=4) == set()
