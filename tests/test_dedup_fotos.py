from __future__ import annotations

import numpy as np

from src import dedup_fotos


def _hash(bits: str) -> np.ndarray:
    """Hash de 64 bits desde una cadena de 0/1 (se rellena con ceros)."""
    v = np.zeros(64, dtype=bool)
    for i, c in enumerate(bits):
        v[i] = c == "1"
    return v


def test_colapsa_casi_identicas_y_elige_la_mas_nitida() -> None:
    fotos = [
        {"id": 1, "hash": _hash("1010"), "nitidez": 50.0},
        {"id": 2, "hash": _hash("1011"), "nitidez": 90.0},  # 1 bit de diferencia
        {"id": 3, "hash": _hash("0101" + "1" * 40), "nitidez": 70.0},
    ]
    grupos = dedup_fotos.agrupar_duplicadas(fotos, umbral=8)
    assert len(grupos) == 2
    grande = next(g for g in grupos if len(g) == 2)
    assert grande[0]["id"] == 2  # la más nítida encabeza el grupo
    assert {f["id"] for f in grande} == {1, 2}


def test_sin_duplicados_cada_una_su_grupo() -> None:
    fotos = [
        {"id": 1, "hash": _hash("1" * 64), "nitidez": 10.0},
        {"id": 2, "hash": _hash("0" * 64), "nitidez": 20.0},
    ]
    assert len(dedup_fotos.agrupar_duplicadas(fotos, umbral=8)) == 2


def test_lista_vacia() -> None:
    assert dedup_fotos.agrupar_duplicadas([], umbral=8) == []


def test_foto_sin_hash_se_conserva_sola() -> None:
    """Imagen ilegible (phash=None): nunca se agrupa, nunca se pierde."""
    fotos = [
        {"id": 1, "hash": None, "nitidez": 10.0},
        {"id": 2, "hash": _hash("1010"), "nitidez": 20.0},
    ]
    grupos = dedup_fotos.agrupar_duplicadas(fotos, umbral=8)
    assert len(grupos) == 2
