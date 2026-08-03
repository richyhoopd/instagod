from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

import config
from src import faces

_FIXTURE = Path(__file__).parent / "fixtures" / "caras" / "dos_personas.jpg"


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


@pytest.mark.skipif(not _FIXTURE.exists(), reason="falta el fixture de caras")
def test_detectar_encuentra_las_caras() -> None:
    img = cv2.imread(str(_FIXTURE))
    caras = faces.detectar(img)
    assert len(caras) == 2
    for c in caras:
        assert c.det_score >= 0.6
        assert 0 < c.frac_area < 1
        x, y, w, h = c.bbox
        assert w > 0 and h > 0


@pytest.mark.skipif(not _FIXTURE.exists(), reason="falta el fixture de caras")
def test_firma_normalizada_y_estable() -> None:
    img = cv2.imread(str(_FIXTURE))
    cara = faces.detectar(img)[0]
    f1 = faces.firma(img, cara)
    assert f1.shape == (128,) and f1.dtype == np.float32
    assert np.linalg.norm(f1) == pytest.approx(1.0, abs=1e-5)
    # Determinista: la misma entrada da la misma firma.
    assert faces.similitud(f1, faces.firma(img, cara)) == pytest.approx(1.0, abs=1e-5)


@pytest.mark.skipif(not _FIXTURE.exists(), reason="falta el fixture de caras")
def test_dos_personas_distintas_no_se_agrupan() -> None:
    img = cv2.imread(str(_FIXTURE))
    caras = faces.detectar(img)
    firmas = [faces.firma(img, c) for c in caras]
    # Umbral desde config, no literal: este test sigue la calibración.
    # Medido: estas dos caras dan similitud 0.388 — con el 0.363 del sample de
    # OpenCV se fundirían en una sola persona, que es justo el fallo que el
    # banco no puede permitirse.
    assert len(faces.agrupar(firmas, config.FACE_COS_MISMA_PERSONA)) == 2


def test_detectar_imagen_sin_caras() -> None:
    assert faces.detectar(np.zeros((200, 200, 3), dtype=np.uint8)) == []


# ---------- Descarga de modelos: validar antes de cachear ----------

class _RespFalsa:
    def __init__(self, contenido: bytes) -> None:
        self.content = contenido

    def raise_for_status(self) -> None:
        pass


def _fake_get(contenido: bytes):
    def get(url, timeout=None):  # noqa: ARG001
        return _RespFalsa(contenido)
    return get


@pytest.fixture()
def modelos_dir(tmp_path: Path, monkeypatch):
    d = tmp_path / "models"
    d.mkdir()
    monkeypatch.setattr(faces.config, "resolve_models_dir", lambda: d)
    return d


def test_bajar_rechaza_html_y_no_cachea_nada(modelos_dir, monkeypatch) -> None:
    """Un 200 con HTML (portal cautivo, página de error) NO debe quedar en cache:
    el early-return por `exists()` lo reusaría en cada corrida futura y el
    síntoma sería un error de cv2 sin relación aparente."""
    monkeypatch.setattr(faces.requests, "get",
                        _fake_get(b"<!DOCTYPE html><html>404</html>" + b"x" * 200_000))
    with pytest.raises(RuntimeError) as exc:
        faces._bajar("m.onnx", "http://x/m.onnx", 1000)
    assert "m.onnx" in str(exc.value)
    assert list(modelos_dir.iterdir()) == []


def test_bajar_rechaza_cuerpo_truncado(modelos_dir, monkeypatch) -> None:
    """Cabecera ONNX correcta pero descarga cortada a la mitad → tampoco cachea."""
    monkeypatch.setattr(faces.requests, "get", _fake_get(b"\x08\x06" + b"\x00" * 50))
    with pytest.raises(RuntimeError) as exc:
        faces._bajar("m.onnx", "http://x/m.onnx", 100_000)
    assert "100000" in str(exc.value).replace("_", "")
    assert list(modelos_dir.iterdir()) == []


def test_bajar_guarda_un_onnx_valido(modelos_dir, monkeypatch) -> None:
    bueno = b"\x08\x06" + b"\x00" * 5000
    monkeypatch.setattr(faces.requests, "get", _fake_get(bueno))
    destino = faces._bajar("m.onnx", "http://x/m.onnx", 1000)
    assert destino.read_bytes() == bueno
    assert not (modelos_dir / "m.onnx.part").exists()


def test_bajar_reusa_el_cacheado_sin_red(modelos_dir, monkeypatch) -> None:
    (modelos_dir / "m.onnx").write_bytes(b"\x08\x06" + b"\x00" * 5000)

    def explota(*a, **k):
        raise AssertionError("no debe tocar la red si el cache es válido")

    monkeypatch.setattr(faces.requests, "get", explota)
    assert faces._bajar("m.onnx", "http://x/m.onnx", 1000).exists()


def test_bajar_rebaja_un_cache_corrupto_previo(modelos_dir, monkeypatch) -> None:
    """Recuperación sin intervención manual: un ONNX corrupto de una corrida
    vieja (antes de esta validación) se re-baja solo."""
    (modelos_dir / "m.onnx").write_bytes(b"<html>error</html>")
    bueno = b"\x08\x06" + b"\x00" * 5000
    monkeypatch.setattr(faces.requests, "get", _fake_get(bueno))
    assert faces._bajar("m.onnx", "http://x/m.onnx", 1000).read_bytes() == bueno


def test_modelos_declarados_traen_nombre_url_y_minimo() -> None:
    for nombre, url, minimo in (faces._YUNET, faces._SFACE):
        assert nombre.endswith(".onnx") and url.startswith("https://")
        assert minimo > 0
