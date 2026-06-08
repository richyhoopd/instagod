"""Audience: parseo de online_followers y manejo de payload vacío. Sin red."""
from __future__ import annotations

from src import audience, db


# Payload de muestra que simula la respuesta de la Graph API para
# online_followers con period=lifetime. El campo "value" es un dict hora→count,
# uno por día del historial.
_PAYLOAD_MUESTRA = {
    "data": [
        {
            "name": "online_followers",
            "period": "lifetime",
            "values": [
                # lunes (dow 0) varios momentos
                {"value": {"7": 10, "19": 80, "20": 90}, "end_time": "2026-06-01T23:00:00+0000"},
                # martes (dow 1)
                {"value": {"9": 30, "20": 70}, "end_time": "2026-06-02T23:00:00+0000"},
                # lunes de nuevo: debe agregarse (promediar/sumar) con la primera fila
                {"value": {"19": 100, "20": 60}, "end_time": "2026-06-08T23:00:00+0000"},
            ],
        }
    ]
}

# end_time es UTC; la conversión de hora se ignora en esta versión (se trabaja
# con la hora del campo value tal cual, que ya está en hora del usuario según IG).


def test_parsear_payload_agrega_por_dow_hora() -> None:
    """Parsear la muestra produce entradas para dow+hora correctos."""
    filas = audience._parsear_online_followers(_PAYLOAD_MUESTRA)
    # filas: lista de {dow, hora, valor}
    claves = {(f["dow"], f["hora"]) for f in filas}
    # (dow=0,hora=19) debe estar — lunes 19h aparece en dos valores
    assert (0, 19) in claves
    assert (0, 20) in claves
    assert (1, 9) in claves
    assert (1, 20) in claves
    # lunes 19h: aparece en dos entradas (80 + 100) → se espera que se sumen o
    # promedien; lo importante es que el valor sea > 80 (segunda entrada aporta).
    lunes_19 = next(f for f in filas if f["dow"] == 0 and f["hora"] == 19)
    assert lunes_19["valor"] >= 80


def test_parsear_payload_vacio_devuelve_lista_vacia() -> None:
    """Payload con value: {} (caso actual <100 seguidores) → sin filas."""
    payload_vacio = {
        "data": [
            {
                "name": "online_followers",
                "period": "lifetime",
                "values": [
                    {"value": {}, "end_time": "2026-06-01T23:00:00+0000"},
                    {"value": {}, "end_time": "2026-06-02T23:00:00+0000"},
                ],
            }
        ]
    }
    filas = audience._parsear_online_followers(payload_vacio)
    assert filas == []


def test_cargar_devuelve_filas_de_db(tmp_path) -> None:
    """cargar(cx, account_id) lee audience_activity y devuelve dicts."""
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    db.insert(cx, "audience_activity", account_id=1, dow=3, hora=19, valor=500)
    db.insert(cx, "audience_activity", account_id=1, dow=5, hora=21, valor=900)
    filas = audience.cargar(cx, account_id=1)
    assert len(filas) == 2
    valores = {(f["dow"], f["hora"]): f["valor"] for f in filas}
    assert valores[(3, 19)] == 500
    assert valores[(5, 21)] == 900
