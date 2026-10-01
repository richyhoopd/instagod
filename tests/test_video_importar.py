"""Importación de mp4 ya renderizados a la cola (reels del prototipo)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src import db, generate_video, video_model


def _mp4(tmp_path: Path, nombre: str = "01-historia.mp4", segundos: float = 5.0) -> Path:
    """mp4 real y mínimo: el import mide duración con ffprobe, no acepta un stub."""
    salida = tmp_path / nombre
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi",
         "-i", f"color=c=black:s=120x214:d={segundos}", "-f", "lavfi",
         "-i", f"anullsrc=r=44100:cl=mono:d={segundos}", "-shortest",
         "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", str(salida), "-y"],
        check=True, capture_output=True)
    return salida


@pytest.fixture
def cx(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    cn = db.connect(str(tmp_path / "t.db"))
    db.init_db(cn)
    db.insert(cn, "accounts", slug="shitbook", ig_handle="@shit.book",
              nombre="shit.book", ciudad="Guadalajara",
              video_json='{"max_duracion_s": 90.0, "cta_marca": "@shit.book"}')
    yield cn
    cn.close()


def test_historia_hermana_lee_title_source_y_cuerpo(tmp_path) -> None:
    mp4 = tmp_path / "01-taco-bell.mp4"
    mp4.write_bytes(b"x")
    (tmp_path / "01-taco-bell.txt").write_text(
        "TITLE: Me encerré en el baño equivocado\n"
        "SOURCE: https://reddit.com/r/AskReddit/comments/abc\n"
        "\nEstuve veinte minutos ahí.\nNadie me avisó.\n", encoding="utf-8")

    meta = generate_video._historia_hermana(mp4)
    assert meta["titulo"] == "Me encerré en el baño equivocado"
    assert meta["url"] == "https://reddit.com/r/AskReddit/comments/abc"
    assert meta["cuerpo"] == "Estuve veinte minutos ahí.\nNadie me avisó."


def test_historia_hermana_busca_en_stories_del_prototipo(tmp_path) -> None:
    """Layout real: out/x.mp4 junto a stories/x.txt, un nivel arriba."""
    (tmp_path / "out").mkdir()
    (tmp_path / "stories").mkdir()
    mp4 = tmp_path / "out" / "02-caca-voladora.mp4"
    mp4.write_bytes(b"x")
    (tmp_path / "stories" / "02-caca-voladora.txt").write_text(
        "TITLE: Una caca salió volando\n\nPasó en taekwondo.\n", encoding="utf-8")

    assert generate_video._historia_hermana(mp4)["titulo"] == "Una caca salió volando"


def test_historia_hermana_sin_txt_devuelve_vacio(tmp_path) -> None:
    mp4 = tmp_path / "huerfano.mp4"
    mp4.write_bytes(b"x")
    assert generate_video._historia_hermana(mp4) == {}


def test_importar_encola_sin_renderizar_ni_llamar_al_llm(cx, tmp_path, monkeypatch) -> None:
    mp4 = _mp4(tmp_path)
    monkeypatch.setattr(generate_video.host, "upload_video",
                        lambda ruta, public_id=None: "https://cdn/x/video/upload/v1/r.mp4")
    # Si el render se llamara, el test reventaría aquí en vez de pasar en silencio.
    monkeypatch.setattr(generate_video.video_render, "render",
                        lambda *a, **k: pytest.fail("importar NO debe re-renderizar"))
    monkeypatch.setattr(generate_video.video_script, "generar_caption",
                        lambda *a, **k: "¿te pasó algo así?")

    qid = generate_video.importar(cx, mp4, marca="shitbook",
                                  titulo="Mi título", cuerpo="La historia completa.",
                                  fuente_url="https://reddit.com/x",
                                  notificar_telegram=False)

    fila = db.rows(cx, "SELECT * FROM content_queue WHERE id = ?", (qid,))[0]
    assert fila["tipo"] == "video"
    assert fila["imagen_url"] == "https://cdn/x/video/upload/v1/r.mp4"
    assert fila["tema_semilla"] == "Mi título"
    assert "¿te pasó algo así?" in fila["caption"]

    guardado = video_model.desde_json(fila["video_json"])
    assert guardado.titulo == "Mi título"
    assert guardado.fuente_url == "https://reddit.com/x"
    assert 4.0 < (guardado.duracion_s or 0) < 6.0, "duración medida con ffprobe"


def test_importar_rechaza_un_video_mas_largo_que_el_tope(cx, tmp_path, monkeypatch) -> None:
    mp4 = _mp4(tmp_path, "largo.mp4", segundos=3.0)
    monkeypatch.setattr(generate_video.video_render, "duracion", lambda p: 200.0)
    subido: list[str] = []
    monkeypatch.setattr(generate_video.host, "upload_video",
                        lambda ruta, public_id=None: subido.append(ruta) or "u")

    with pytest.raises(ValueError, match="200s.*90s"):
        generate_video.importar(cx, mp4, marca="shitbook", titulo="T",
                                usar_llm=False, notificar_telegram=False)
    assert subido == [], "no debe gastar la subida en una pieza que se rechaza"


def test_importar_falla_claro_si_no_existe_el_archivo(cx) -> None:
    with pytest.raises(FileNotFoundError):
        generate_video.importar(cx, "/no/existe.mp4", marca="shitbook")


def test_importar_sin_llm_deja_el_caption_vacio(cx, tmp_path, monkeypatch) -> None:
    mp4 = _mp4(tmp_path)
    monkeypatch.setattr(generate_video.host, "upload_video",
                        lambda ruta, public_id=None: "https://cdn/v/video/upload/r.mp4")
    monkeypatch.setattr(generate_video.video_script, "generar_caption",
                        lambda *a, **k: pytest.fail("usar_llm=False no debe llamar al LLM"))

    qid = generate_video.importar(cx, mp4, marca="shitbook", titulo="T",
                                  cuerpo="historia", usar_llm=False,
                                  notificar_telegram=False)
    assert (db.rows(cx, "SELECT caption FROM content_queue WHERE id = ?",
                    (qid,))[0]["caption"] or "") == ""
