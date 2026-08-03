from __future__ import annotations

import numpy as np
import pytest

from src import faces


def _vec(*componentes: float) -> np.ndarray:
    """Vector L2-normalizado de 128 dims a partir de sus primeras componentes."""
    v = np.zeros(128, dtype=np.float32)
    v[:len(componentes)] = componentes
    return v / np.linalg.norm(v)


def test_similitud_identica_es_uno() -> None:
    a = _vec(1, 0, 0)
    assert faces.similitud(a, a) == pytest.approx(1.0, abs=1e-6)


def test_similitud_ortogonal_es_cero() -> None:
    assert faces.similitud(_vec(1, 0), _vec(0, 1)) == pytest.approx(0.0, abs=1e-6)


def test_agrupar_junta_parecidas_y_separa_distintas() -> None:
    # a1 y a2 casi idénticas; b claramente distinta.
    a1, a2, b = _vec(1, 0.02), _vec(1, 0.05), _vec(0, 1)
    grupos = faces.agrupar([a1, a2, b], umbral=0.363)
    assert sorted(len(g) for g in grupos) == [1, 2]
    juntos = next(g for g in grupos if len(g) == 2)
    assert set(juntos) == {0, 1}


def test_agrupar_es_transitivo() -> None:
    """Encadenamiento: a~b, b~c, pero a y c apenas por debajo del umbral."""
    a, b, c = _vec(1, 0), _vec(1, 1), _vec(0, 1)
    grupos = faces.agrupar([a, b, c], umbral=0.7)
    assert len(grupos) == 1 and len(grupos[0]) == 3


def test_agrupar_sin_firmas() -> None:
    assert faces.agrupar([], umbral=0.363) == []


def test_agrupar_ordena_por_tamano() -> None:
    a1, a2, a3, b = _vec(1, 0.01), _vec(1, 0.02), _vec(1, 0.03), _vec(0, 1)
    grupos = faces.agrupar([a1, b, a2, a3], umbral=0.363)
    assert len(grupos[0]) == 3  # el grupo grande va primero
