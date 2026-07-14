"""Tests de la lógica de salud del approval-daemon (watchdog anti-zombie)."""
from datetime import datetime, timedelta

import pytz

from src import daemon_health as dh

TZ = pytz.timezone("America/Mexico_City")


def _ahora():
    return TZ.localize(datetime(2026, 7, 14, 12, 0, 0))


def test_sin_latido_necesita_reinicio():
    assert dh.necesita_reinicio(None, _ahora(), umbral_seg=300) is True


def test_latido_ilegible_necesita_reinicio():
    assert dh.necesita_reinicio("no-es-fecha", _ahora(), umbral_seg=300) is True


def test_latido_fresco_no_reinicia():
    fresco = (_ahora() - timedelta(seconds=60)).isoformat()
    assert dh.necesita_reinicio(fresco, _ahora(), umbral_seg=300) is False


def test_latido_viejo_necesita_reinicio():
    viejo = (_ahora() - timedelta(seconds=301)).isoformat()
    assert dh.necesita_reinicio(viejo, _ahora(), umbral_seg=300) is True


def test_latido_naive_se_asume_tz_escena():
    # Un ISO sin tzinfo no debe reventar; se interpreta en la tz de la escena.
    fresco_naive = (_ahora().replace(tzinfo=None) - timedelta(seconds=30)).isoformat()
    assert dh.necesita_reinicio(fresco_naive, _ahora(), umbral_seg=300) is False


def test_escribir_y_leer_latido_roundtrip(tmp_path):
    p = tmp_path / "hb"
    dh.escribir_latido(_ahora(), path=p)
    assert dh.leer_latido(path=p) == _ahora().isoformat()


def test_leer_latido_inexistente_es_none(tmp_path):
    assert dh.leer_latido(path=tmp_path / "no-existe") is None


def test_escritura_atomica_no_deja_tmp(tmp_path):
    p = tmp_path / "hb"
    dh.escribir_latido(_ahora(), path=p)
    sobrantes = [f.name for f in tmp_path.iterdir() if f.name != "hb"]
    assert sobrantes == []
