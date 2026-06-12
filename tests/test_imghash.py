"""pHash compartido: igual↔igual, distinto↔distinto, ilegible→None."""
from __future__ import annotations

import numpy as np

from src import imghash


def _img(path, seed: int) -> None:
    import cv2
    rng = np.random.default_rng(seed)
    cv2.imwrite(str(path), rng.integers(0, 255, (64, 64, 3), dtype=np.uint8))


def test_misma_imagen_es_duplicado(tmp_path) -> None:
    _img(tmp_path / "a.jpg", seed=1)
    _img(tmp_path / "b.jpg", seed=1)
    ha, hb = imghash.phash(tmp_path / "a.jpg"), imghash.phash(tmp_path / "b.jpg")
    assert imghash.es_duplicado(ha, [hb])


def test_imagen_distinta_no_es_duplicado(tmp_path) -> None:
    _img(tmp_path / "a.jpg", seed=1)
    _img(tmp_path / "b.jpg", seed=2)
    assert not imghash.es_duplicado(imghash.phash(tmp_path / "a.jpg"),
                                    [imghash.phash(tmp_path / "b.jpg")])


def test_ilegible_regresa_none(tmp_path) -> None:
    (tmp_path / "x.jpg").write_bytes(b"no soy imagen")
    assert imghash.phash(tmp_path / "x.jpg") is None
