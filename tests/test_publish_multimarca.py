"""publish.py multi-marca: cada Sheet con sus creds; marcas desde el ENV."""
from __future__ import annotations

import config
import publish
from src import instagram, sheets


def test_marcas_en_env(monkeypatch) -> None:
    monkeypatch.setenv("SHEET_ID__PENSIONMAS", "S2")
    monkeypatch.setenv("SHEET_ID__TELCO", "S3")
    ms = config.marcas_en_env()
    assert ms[0] == "gdlscene"
    assert set(ms) == {"gdlscene", "pensionmas", "telco"}
    assert len(ms) == len(set(ms))


def test_instagram_publish_usa_creds_inyectadas(monkeypatch) -> None:
    posts = []

    class _Resp:
        status_code = 200

        def json(self):
            return {"id": "post1", "status_code": "FINISHED"}

    def _post(url, data=None, timeout=None):
        posts.append((url, data))
        return _Resp()

    monkeypatch.setattr(instagram.requests, "post", _post)
    monkeypatch.setattr(instagram.requests, "get", lambda *a, **kw: _Resp())
    out = instagram.publish("https://cdn/x.jpg", "hola",
                            creds={"user_id": "UP", "token": "TP"})
    assert out == "post1"
    assert all("/UP/" in url for url, _ in posts)
    assert all(d["access_token"] == "TP" for _, d in posts)


def test_publicar_marca_pasa_sheet_y_creds(monkeypatch) -> None:
    monkeypatch.setenv("SHEET_ID__PENSIONMAS", "S2")
    monkeypatch.setenv("IG_USER_ID__PENSIONMAS", "UP")
    monkeypatch.setenv("IG_ACCESS_TOKEN__PENSIONMAS", "TP")
    filas = [{"id": 9, "imagen_compuesta_url": "https://cdn/a.jpg",
              "caption_final": "c", "status": "approved",
              "ig_post_id": "", "tw_post_id": "", "fb_post_id": ""}]
    vistos = {}
    monkeypatch.setattr(sheets, "get_due_rows",
                        lambda now=None, sheet_id=None:
                        filas if sheet_id == "S2" else [])
    monkeypatch.setattr(sheets, "update_row",
                        lambda rid, sheet_id=None, **kw:
                        vistos.setdefault("update", (rid, sheet_id, kw)))
    monkeypatch.setattr(instagram, "publish",
                        lambda url, cap, creds=None:
                        vistos.setdefault("creds", creds) or "ig9")
    publish.publicar_marca("pensionmas")
    assert vistos["creds"] == {"user_id": "UP", "token": "TP"}
    assert vistos["update"][1] == "S2"


def test_marca_sin_ig_no_publica_y_avisa(monkeypatch, capsys) -> None:
    monkeypatch.setenv("SHEET_ID__PENSIONMAS", "S2")
    monkeypatch.delenv("IG_ACCESS_TOKEN__PENSIONMAS", raising=False)
    publish.publicar_marca("pensionmas")
    assert "IG_ACCESS_TOKEN__PENSIONMAS" in capsys.readouterr().out


def test_crosspost_solo_gdlscene(monkeypatch) -> None:
    plat = publish._plataformas_de("pensionmas")
    assert [p[1] for p in plat] == ["ig"]
    etiquetas = [p[1] for p in publish._plataformas_de("gdlscene")]
    assert "ig" in etiquetas          # fb/x según flags, ig siempre
