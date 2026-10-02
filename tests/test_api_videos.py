"""Reels desde el portal: encolar `video.generar`, editar el preset de video y
subir el personaje. El motor (render, TTS, LLM) no se toca aquí: estas pruebas
verifican la capa de API; el último (lento) corre el render real."""
from __future__ import annotations

import json
import shutil

import pytest

from src import db

# 1x1 PNG transparente válido.
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)
_CUERPO = " ".join(["palabra"] * 30)


def _marca(cx, slug="pensionmas", **campos):
    base = dict(slug=slug, ig_handle="@p", nombre="P", ciudad="CDMX")
    base.update(campos)
    return db.insert(cx, "accounts", **base)


def _topic(cx, account_id, **campos):
    base = dict(account_id=account_id, titulo="Mi vecino y la gallina",
               resumen="Historia larga de reddit sobre un vecino", url="https://reddit.com/r/x",
               fuente="reddit")
    base.update(campos)
    return db.insert(cx, "topic_suggestions", **base)


def _payload(cx, job_id) -> dict:
    job = db.get(cx, "jobs", job_id)
    assert job["tipo"] == "video.generar"
    return json.loads(job["payload_json"])


# ---------- POST /videos ----------

def test_video_con_topic_encola_video_generar(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    tid = _topic(cx, pid)
    uid = H.usuario("e@x.com", marcas=[(pid, "editor")])
    H.login(uid)
    r = cli.post("/brands/pensionmas/videos", json={"topic_id": tid})
    assert r.status_code == 202
    job = db.get(cx, "jobs", r.json()["job_id"])
    assert job["account_id"] == pid and job["creado_por"] == uid and job["estado"] == "cola"
    assert _payload(cx, job["id"]) == {"topic_id": tid}


def test_video_a_mano_con_titulo_y_cuerpo(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.post("/brands/pensionmas/videos",
                 json={"titulo": "Una historia", "cuerpo": "algo que pasó ayer"})
    assert r.status_code == 202
    assert _payload(cx, r.json()["job_id"]) == {"titulo": "Una historia",
                                                "cuerpo": "algo que pasó ayer"}


def test_video_sin_llm_va_en_el_payload(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.post("/brands/pensionmas/videos",
                 json={"titulo": "Una historia", "cuerpo": _CUERPO, "sin_llm": True})
    assert r.status_code == 202
    assert _payload(cx, r.json()["job_id"])["sin_llm"] is True


def test_video_sin_historia_422(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.post("/brands/pensionmas/videos", json={})
    assert r.status_code == 422 and r.json()["campo"] == "titulo"
    r = cli.post("/brands/pensionmas/videos", json={"titulo": "Solo título"})
    assert r.status_code == 422 and r.json()["campo"] == "cuerpo"


def test_video_topic_y_texto_a_la_vez_422(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    tid = _topic(cx, pid)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.post("/brands/pensionmas/videos",
                 json={"topic_id": tid, "titulo": "x y z", "cuerpo": "otra cosa"})
    assert r.status_code == 422 and r.json()["campo"] == "topic_id"


def test_video_topic_descartado_422(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    tid = _topic(cx, pid, descartado=1)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.post("/brands/pensionmas/videos", json={"topic_id": tid})
    assert r.status_code == 422
    assert r.json()["detalle"] == "Ese tema ya fue descartado"


def test_video_topic_sin_resumen_422(api_cliente) -> None:
    """El motor narra `resumen`: sin él revienta en el worker ("Falta la
    historia"). Se rechaza al encolar para no fallar al final."""
    cli, cx, H = api_cliente
    pid = _marca(cx)
    tid = _topic(cx, pid, resumen=None)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.post("/brands/pensionmas/videos", json={"topic_id": tid})
    assert r.status_code == 422 and r.json()["campo"] == "topic_id"


def test_video_topic_de_otra_marca_404(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    otra = _marca(cx, slug="otra")
    tid = _topic(cx, otra)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.post("/brands/pensionmas/videos", json={"topic_id": tid})
    assert r.status_code == 404


def test_video_sin_llm_con_cuerpo_corto_422(api_cliente) -> None:
    """Sin LLM el cuerpo se narra tal cual y el contrato pide ≥20 palabras."""
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.post("/brands/pensionmas/videos",
                 json={"titulo": "Una historia", "cuerpo": "muy corto", "sin_llm": True})
    assert r.status_code == 422 and r.json()["campo"] == "cuerpo"


def test_video_marca_sin_preset_genera_igual(api_cliente) -> None:
    """gdlscene no tiene video_json y genera con los defaults del motor."""
    cli, cx, H = api_cliente
    pid = _marca(cx, video_json=None)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.post("/brands/pensionmas/videos", json={"titulo": "Algo", "cuerpo": "pasó algo"})
    assert r.status_code == 202


def test_video_marca_ajena_403_o_404(api_cliente) -> None:
    cli, cx, H = api_cliente
    _marca(cx)
    otra = _marca(cx, slug="otra")
    H.login(H.usuario("e@x.com", marcas=[(otra, "editor")]))
    r = cli.post("/brands/pensionmas/videos", json={"titulo": "Algo", "cuerpo": "pasó"})
    assert r.status_code in (403, 404)


# ---------- preset de video ----------

def test_get_preset_sin_configurar_devuelve_defaults(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.get("/brands/pensionmas/video")
    assert r.status_code == 200
    d = r.json()
    assert d["configurado"] is False and d["tiene_personaje"] is False
    assert d["preset"]["voz"] == "es-MX-JorgeNeural"
    assert "es-MX-DaliaNeural" in d["voces"] and "mosaico" in d["fondos"]


def test_put_preset_guarda_y_conserva_lo_no_editable(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx, video_json=json.dumps({"personaje_path": "data/brands/p/personaje.png",
                                            "voz_formantes": 0.9}))
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    r = cli.put("/brands/pensionmas/video", json={
        "voz": "es-MX-DaliaNeural", "cta_texto": "síguenos", "cta_marca": "@p",
        "cta_hablado": "", "etiqueta_tarjeta": "r/x", "autor_tarjeta": "anónimo",
        "color_acento": "#00FF00", "color_fondo": "#000000", "fondos": ["mosaico", "espejo"],
        "palabras_subtitulo": 2, "palabras_min": 60, "palabras_max": 120,
        "max_duracion_s": 60})
    assert r.status_code == 200, r.text
    assert r.json()["configurado"] is True
    guardado = json.loads(db.get(cx, "accounts", pid)["video_json"])
    assert guardado["voz"] == "es-MX-DaliaNeural" and guardado["palabras_subtitulo"] == 2
    assert guardado["fondos"] == ["mosaico", "espejo"]
    # Lo que el formulario no edita se conserva.
    assert guardado["personaje_path"] == "data/brands/p/personaje.png"
    assert guardado["voz_formantes"] == 0.9


def test_put_preset_incoherente_422(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    base = {"voz": "es-MX-JorgeNeural", "color_acento": "#FFE600", "color_fondo": "#3B2414",
            "fondos": ["mosaico"], "palabras_subtitulo": 3, "palabras_min": 90,
            "palabras_max": 170, "max_duracion_s": 90}
    for malo, campo in (({"palabras_min": 200, "palabras_max": 100}, "palabras_min"),
                        ({"color_acento": "amarillo"}, "color_acento"),
                        ({"fondos": ["no_existe"]}, "fondos"),
                        ({"fondos": []}, "fondos"),
                        ({"palabras_subtitulo": 9}, "palabras_subtitulo")):
        r = cli.put("/brands/pensionmas/video", json={**base, **malo})
        assert r.status_code == 422, malo
        assert r.json().get("campo") == campo, (malo, r.json())


def test_put_preset_editor_403(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.put("/brands/pensionmas/video", json={"voz": "es-MX-JorgeNeural"})
    assert r.status_code == 403


# ---------- personaje ----------

def test_subir_personaje_png(api_cliente, tmp_path, monkeypatch) -> None:
    from api.routers import perfil
    monkeypatch.setattr(perfil, "BRANDS_DIR", tmp_path / "brands")
    cli, cx, H = api_cliente
    pid = _marca(cx, video_json=json.dumps({"voz": "es-MX-DaliaNeural"}))
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    r = cli.post("/brands/pensionmas/video/personaje",
                 files={"archivo": ("pajaro.png", _PNG, "image/png")})
    assert r.status_code == 200, r.text
    assert (tmp_path / "brands" / "pensionmas" / "personaje.png").read_bytes() == _PNG
    guardado = json.loads(db.get(cx, "accounts", pid)["video_json"])
    assert guardado["personaje_path"] == "data/brands/pensionmas/personaje.png"
    assert guardado["voz"] == "es-MX-DaliaNeural"
    assert cli.get("/brands/pensionmas/video").json()["tiene_personaje"] is True
    r = cli.get("/brands/pensionmas/files/personaje")
    assert r.status_code == 200 and r.content == _PNG


def test_subir_personaje_no_png_422(api_cliente, tmp_path, monkeypatch) -> None:
    from api.routers import perfil
    monkeypatch.setattr(perfil, "BRANDS_DIR", tmp_path / "brands")
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    r = cli.post("/brands/pensionmas/video/personaje",
                 files={"archivo": ("x.jpg", b"\xff\xd8\xff", "image/jpeg")})
    assert r.status_code == 422
    # Extensión .png pero contenido que no es PNG.
    r = cli.post("/brands/pensionmas/video/personaje",
                 files={"archivo": ("x.png", b"no soy png", "image/png")})
    assert r.status_code == 422


def test_quitar_personaje(api_cliente, tmp_path, monkeypatch) -> None:
    from api.routers import perfil
    monkeypatch.setattr(perfil, "BRANDS_DIR", tmp_path / "brands")
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    cli.post("/brands/pensionmas/video/personaje",
             files={"archivo": ("p.png", _PNG, "image/png")})
    r = cli.delete("/brands/pensionmas/video/personaje")
    assert r.status_code == 204
    assert not (tmp_path / "brands" / "pensionmas" / "personaje.png").exists()
    guardado = json.loads(db.get(cx, "accounts", pid)["video_json"])
    assert guardado.get("personaje_path") is None


# ---------- punta a punta (lento) ----------

_HISTORIA_REAL = (
    "Mi vecino del Centro le canta serenatas a su tortuga cada domingo. "
    "Empezó como un ruido que nadie entendía y los vecinos se quejaban. "
    "Un día bajamos a reclamarle y lo encontramos con guitarra y café. "
    "La tortuga salía de su caja solo cuando él tocaba boleros viejos. "
    "Ahora medio edificio baja los domingos a escuchar y la tortuga ya tiene nombre."
)


@pytest.mark.lento
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="requiere ffmpeg")
def test_reel_del_portal_punta_a_punta(api_cliente, tmp_path, monkeypatch) -> None:
    """POST /videos → handler `video.generar` con TTS y ffmpeg reales → fila en
    la cola. Solo Cloudinary y Telegram son dobles; sin preset ni personaje."""
    from src import generate_video
    from src.jobs import handlers

    subidos: list[str] = []
    monkeypatch.setattr(generate_video, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(generate_video.host, "upload_video",
                        lambda ruta, public_id: subidos.append(ruta) or
                        f"https://cdn.test/{public_id}.mp4")
    telegram: list = []
    monkeypatch.setattr(generate_video.approval, "enviar_a_telegram",
                        lambda *a, **k: telegram.append((a, k)))

    cli, cx, H = api_cliente
    pid = _marca(cx)
    uid = H.usuario("e@x.com", marcas=[(pid, "editor")])
    H.login(uid)
    r = cli.post("/brands/pensionmas/videos",
                 json={"titulo": "Serenata a la tortuga", "cuerpo": _HISTORIA_REAL,
                       "sin_llm": True})
    assert r.status_code == 202
    job = db.get(cx, "jobs", r.json()["job_id"])

    res = handlers.generar_video(cx, job)

    fila = db.get(cx, "content_queue", res["queue_id"])
    assert fila["tipo"] == "video" and fila["account_id"] == pid
    assert fila["origen"] == "api" and fila["creado_por"] == uid
    assert fila["imagen_url"].startswith("https://cdn.test/reel") and len(subidos) == 1
    video = json.loads(fila["video_json"])
    assert video["duracion_s"] > 10
    assert len(telegram) == 1  # paridad con slideshows del portal
