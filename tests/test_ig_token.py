"""El refresh --aplicar debe persistir el token en .env y en el secret del repo."""
import pytest

from src import ig_token


def test_aplicar_token_escribe_env_y_secret(tmp_path):
    env = tmp_path / ".env"
    env.write_text("OTRA=cosa\nIG_ACCESS_TOKEN=viejo\nMAS=si\n")

    llamadas = []

    def run_falso(cmd, **kwargs):
        llamadas.append(cmd)

    ig_token.aplicar_token("nuevo-token", env_path=env, _run=run_falso)

    contenido = env.read_text()
    assert "viejo" not in contenido
    assert "nuevo-token" in contenido
    assert "OTRA=cosa" in contenido  # no pisa el resto del .env

    (cmd,) = llamadas
    assert cmd[1:4] == ["secret", "set", "IG_ACCESS_TOKEN"]
    assert "nuevo-token" in cmd


def test_refrescar_y_aplicar_token_joven_no_es_falla(monkeypatch):
    monkeypatch.setattr(
        ig_token, "refresh_long_lived_token",
        lambda: (_ for _ in ()).throw(
            RuntimeError("Refresh falló 400: less than 24 hours old")),
    )
    assert ig_token.refrescar_y_aplicar() is False


def test_refrescar_y_aplicar_propaga_fallas_reales(monkeypatch):
    monkeypatch.setattr(
        ig_token, "refresh_long_lived_token",
        lambda: (_ for _ in ()).throw(RuntimeError("Refresh falló 190: token muerto")),
    )
    with pytest.raises(RuntimeError, match="190"):
        ig_token.refrescar_y_aplicar()


def test_refrescar_y_aplicar_exige_access_token(monkeypatch):
    monkeypatch.setattr(ig_token, "refresh_long_lived_token", lambda: {"raro": 1})
    with pytest.raises(RuntimeError, match="sin access_token"):
        ig_token.refrescar_y_aplicar()


def test_refrescar_y_aplicar_aplica(monkeypatch):
    monkeypatch.setattr(
        ig_token, "refresh_long_lived_token",
        lambda: {"access_token": "tok-fresco", "expires_in": 60 * 86400},
    )
    aplicados = []
    monkeypatch.setattr(ig_token, "aplicar_token", lambda t: aplicados.append(t))
    assert ig_token.refrescar_y_aplicar() is True
    assert aplicados == ["tok-fresco"]
