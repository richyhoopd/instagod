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
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok-gdl")
    monkeypatch.setattr(
        ig_token, "refresh_long_lived_token",
        lambda token=None: (_ for _ in ()).throw(
            RuntimeError("Refresh falló 400: less than 24 hours old")),
    )
    assert ig_token.refrescar_y_aplicar() is False


def test_refrescar_y_aplicar_propaga_fallas_reales(monkeypatch):
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok-gdl")
    monkeypatch.setattr(
        ig_token, "refresh_long_lived_token",
        lambda token=None: (_ for _ in ()).throw(RuntimeError("Refresh falló 190: token muerto")),
    )
    with pytest.raises(RuntimeError, match="190"):
        ig_token.refrescar_y_aplicar()


def test_refrescar_y_aplicar_exige_access_token(monkeypatch):
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok-gdl")
    monkeypatch.setattr(ig_token, "refresh_long_lived_token", lambda token=None: {"raro": 1})
    with pytest.raises(RuntimeError, match="sin access_token"):
        ig_token.refrescar_y_aplicar()


def test_refrescar_y_aplicar_aplica(monkeypatch):
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok-gdl")
    monkeypatch.setattr(
        ig_token, "refresh_long_lived_token",
        lambda token=None: {"access_token": "tok-fresco", "expires_in": 60 * 86400},
    )
    aplicados = []
    monkeypatch.setattr(ig_token, "aplicar_token",
                        lambda t, slug="gdlscene": aplicados.append(t))
    assert ig_token.refrescar_y_aplicar() is True
    assert aplicados == ["tok-fresco"]


# --- Multi-marca: cada marca refresca y persiste SU token con sufijo ---

def test_aplicar_token_de_marca_usa_var_con_sufijo(tmp_path):
    env = tmp_path / ".env"
    env.write_text("IG_ACCESS_TOKEN=gdl\nIG_ACCESS_TOKEN__MELAQUECAPITAL=viejo\n")
    llamadas = []
    ig_token.aplicar_token("nuevo", slug="melaquecapital", env_path=env,
                           _run=lambda cmd, **kw: llamadas.append(cmd))
    contenido = env.read_text()
    assert "IG_ACCESS_TOKEN=gdl" in contenido          # el de gdlscene intacto
    assert "IG_ACCESS_TOKEN__MELAQUECAPITAL=" in contenido and "viejo" not in contenido
    (cmd,) = llamadas
    assert cmd[1:4] == ["secret", "set", "IG_ACCESS_TOKEN__MELAQUECAPITAL"]


def test_refrescar_marca_usa_su_token_y_aplica_con_su_slug(monkeypatch):
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok-gdl")
    monkeypatch.setenv("IG_ACCESS_TOKEN__MELAQUECAPITAL", "tok-mwrs")
    vistos, aplicados = [], []
    monkeypatch.setattr(ig_token, "refresh_long_lived_token",
                        lambda token=None: (vistos.append(token) or
                                            {"access_token": "fresco", "expires_in": 5e6}))
    monkeypatch.setattr(ig_token, "aplicar_token",
                        lambda t, slug="gdlscene": aplicados.append((slug, t)))
    assert ig_token.refrescar_y_aplicar(slug="melaquecapital") is True
    assert vistos == ["tok-mwrs"]
    assert aplicados == [("melaquecapital", "fresco")]


def test_refrescar_marca_sin_token_no_es_falla(monkeypatch):
    monkeypatch.delenv("IG_ACCESS_TOKEN__NADIE", raising=False)
    assert ig_token.refrescar_y_aplicar(slug="nadie") is False


def test_refrescar_todas_itera_marcas_del_env_y_no_para_por_una(monkeypatch):
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok-gdl")
    monkeypatch.setenv("IG_ACCESS_TOKEN__MELAQUECAPITAL", "tok-mwrs")
    monkeypatch.delenv("IG_ACCESS_TOKEN__PENSIONMAS", raising=False)

    def _refrescar(slug="gdlscene"):
        if slug == "gdlscene":
            raise RuntimeError("Refresh falló 190: muerto")
        return True
    monkeypatch.setattr(ig_token, "refrescar_y_aplicar", _refrescar)
    with pytest.raises(RuntimeError, match="gdlscene"):
        ig_token.refrescar_todas()
    # y las marcas se derivan del ENTORNO (sufijos IG_ACCESS_TOKEN__*)
    assert ig_token.marcas_con_token() == ["gdlscene", "melaquecapital"]
