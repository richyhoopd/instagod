"""Importación de un plan externo: manifiesto (dedup de subidas) y carga idempotente."""
from __future__ import annotations

import json

from src import db, plan_import, publisher


def _plan(tmp_path):
    p = tmp_path / "plan"
    (p).mkdir()
    (p / "calendario.csv").write_text(
        "fecha,tipo,formato,etapa,tema,id,slides\n"
        '2026-11-01,feed,post,TOFU,"Día de Muertos",muertos,2\n'
        '2026-11-02,historia,story,BOFU,"Encuesta",enc,1\n'
        '2026-11-02,historia,story,BOFU,"Especial",esp,1\n'
        '2026-11-03,feed,reel,MOFU,"Reel",r1,3\n', encoding="utf-8")
    for pl in plan_import.PLATAFORMAS:
        d = p / pl / "post" / "2026-11-01_muertos"
        d.mkdir(parents=True)
        (d / "01.png").write_bytes(b"A")
        (d / "02.png").write_bytes(b"B")
        (d / "caption.txt").write_text(f"pie {pl}", encoding="utf-8")
        for hid in ("enc", "esp"):
            h = p / pl / "historia" / f"2026-11-02_{hid}"
            h.mkdir(parents=True)
            (h / "01.png").write_bytes(hid.encode())
            (h / "notas.txt").write_text("nota", encoding="utf-8")
        r = p / pl / "reel" / "2026-11-03_r1"
        r.mkdir(parents=True)
        (r / "reel.mp4").write_bytes(b"MP4")
        (r / "caption.txt").write_text("reel", encoding="utf-8")
    return p


def test_manifiesto_sube_cada_archivo_una_vez_y_arma_filas(tmp_path) -> None:
    plan = _plan(tmp_path)
    subidas = []
    sube = lambda ruta, pid: subidas.append(pid) or f"https://cdn/{pid}"  # noqa: E731
    filas = plan_import.manifiesto(plan, tz="America/Mexico_City",
                                   subir_imagen=sube, subir_video=sube)
    assert len(filas) == 4 * 3
    assert len(subidas) == 5  # A, B, enc, esp, MP4: iguales entre plataformas
    post_fb = next(f for f in filas if f["plataforma"] == "facebook" and f["formato"] == "post")
    assert post_fb["caption"] == "pie facebook" and len(json.loads(post_fb["imagen_url"])) == 2
    assert post_fb["scheduled_datetime"] == "2026-11-01T19:00:00-06:00"
    horas = sorted(f["scheduled_datetime"] for f in filas
                   if f["formato"] == "historia" and f["plataforma"] == "tiktok")
    assert horas == ["2026-11-02T10:00:00-06:00", "2026-11-02T13:00:00-06:00"]
    reel = next(f for f in filas if f["formato"] == "reel")
    assert reel["tipo"] == "video" and reel["aspecto"] == "9:16"
    # Segunda corrida: todo sale de la caché, cero subidas nuevas.
    plan_import.manifiesto(plan, tz="America/Mexico_City", subir_imagen=sube, subir_video=sube)
    assert len(subidas) == 5


def test_cargar_es_idempotente_y_el_publisher_no_toca_nada(tmp_path) -> None:
    plan = _plan(tmp_path)
    filas = plan_import.manifiesto(plan, tz="America/Mexico_City",
                                   subir_imagen=lambda r, pid: pid, subir_video=lambda r, pid: pid)
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    mid = db.insert(cx, "accounts", slug="m", ig_handle="@m", nombre="m", ciudad="X")
    assert plan_import.cargar(cx, mid, filas) == (12, 0)
    assert plan_import.cargar(cx, mid, filas) == (0, 12)
    estados = {r["status"] for r in cx.execute("SELECT status FROM content_queue")}
    assert estados == {"borrador"}
    assert publisher.filas_due(cx, mid, "2099-01-01T00:00:00-06:00") == []
