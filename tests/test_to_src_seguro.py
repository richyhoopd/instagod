"""compose._to_src no deja pasar caracteres que rompan style="..." o url('...')."""
from __future__ import annotations

import pytest

from src import compose


@pytest.mark.parametrize("url", [
    "https://cdn.x.com/a/b-c_d.png?w=1080&q=80#f",
    "http://a/x%20y.png",
    "data:image/png;base64,AAAA+/==",
])
def test_url_normal_queda_identica(url):
    assert compose._to_src(url) == url


@pytest.mark.parametrize("url", [
    'http://a/x.png" onmouseover="alert(1)',
    "http://a/x.png');}</style><script>alert(1)</script>",
    "http://a/x.png\nz",
    "http://a/x.png\\",
])
def test_url_de_ataque_se_neutraliza(url):
    salida = compose._to_src(url)
    assert not any(c in salida for c in "\"'()\\<> \n\r")
