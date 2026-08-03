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


def test_frontera_umbral_exacto_agrupa() -> None:
    """Diferencia exacta de umbral bits: debe agrupar (por <=)."""
    fotos = [
        {"id": 1, "hash": _hash("1" * 64), "nitidez": 10.0},
        {"id": 2, "hash": _hash("0" * 8 + "1" * 56), "nitidez": 20.0},  # 8 bits de diferencia
    ]
    grupos = dedup_fotos.agrupar_duplicadas(fotos, umbral=8)
    assert len(grupos) == 1
    assert len(grupos[0]) == 2


def test_frontera_umbral_mas_uno_no_agrupa() -> None:
    """Diferencia de umbral+1 bits: no debe agrupar."""
    fotos = [
        {"id": 1, "hash": _hash("1" * 64), "nitidez": 10.0},
        {"id": 2, "hash": _hash("0" * 9 + "1" * 55), "nitidez": 20.0},  # 9 bits de diferencia
    ]
    grupos = dedup_fotos.agrupar_duplicadas(fotos, umbral=8)
    assert len(grupos) == 2


def test_deriva_gradual_muestra_no_transitividad() -> None:
    """Racha con deriva gradual: acumulación de cambios pequeños.

    Con agrupamiento greedy (solo contra cabeza), las fotos se dividen en
    múltiples grupos cuando la acumulación supera el umbral. Esto es
    consecuencia del diseño: cada foto se compara contra la fundadora del
    grupo (grupo[0]), no contra todos los miembros. Si A~B y B~C, pero
    A distante de C, entonces C puede acabar en grupo aparte aunque sea
    casi idéntica a su vecina B. Es no-transitivo pero conservador: nunca
    pierde fotos ni fusiona indebidamente, solo deduplica de menos.
    """
    # Crear 10 fotos donde cada una acumula más flips que la anterior.
    # Foto 1: 0 flips (base)
    # Foto 2: 1 flip (bit 0)
    # Foto 3: 2 flips (bits 0-1)
    # ...
    # Foto 9: 8 flips (bits 0-7) - agrupa porque 8 <= umbral
    # Foto 10: 9 flips (bits 0-8) - no agrupa porque 9 > umbral
    fotos = []
    base_str = "1" * 64
    for i in range(10):
        base_list = list(base_str)
        for j in range(i):  # Flip los primeros i bits (0, 1, 2, ..., 9)
            base_list[j] = "0"
        fotos.append({
            "id": i + 1,
            "hash": _hash("".join(base_list)),
            "nitidez": float(i),
        })

    grupos = dedup_fotos.agrupar_duplicadas(fotos, umbral=8)
    # Con el agrupamiento greedy contra la cabeza (foto 1 = "1"*64):
    # - Fotos 2-9 difieren 1-8 bits de foto 1 => agrupan
    # - Foto 10 difiere 9 bits de foto 1 => no agrupa
    # Resultado: 2 grupos (grupo grande + foto 10 sola)
    assert len(grupos) == 2, f"Esperaba 2 grupos, obtuvo {len(grupos)}"
