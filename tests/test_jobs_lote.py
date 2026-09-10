"""Handler del job `lote.enviar` (memes de banda de gdlscene)."""
import pytest

from src import db, jobs
from src.jobs import handlers


@pytest.fixture()
def cx(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def sin_pausa(monkeypatch):
    """El anti-flood de Telegram no tiene por qué frenar los tests."""
    monkeypatch.setattr(handlers.time, "sleep", lambda *_: None)


def _job(cx, mes, account_id=1):
    jid = jobs.crear(cx, "lote.enviar", account_id, {"mes": mes})
    fila = jobs.tomar(cx, "w-test")
    assert fila and fila["id"] == jid
    return fila


def _borrador(cx, nombre="Banda", cuando="2026-10-03T11:00"):
    bid = db.insert(cx, "bands", nombre=nombre, prioridad=1, activa=1, tipo="banda")
    pid = db.insert(cx, "photos", band_id=bid, path=f"{nombre}.jpg", usable_meme=1)
    return db.insert(cx, "content_queue", band_id=bid, photo_id=pid, tipo="meme",
                     status=db.QUEUE_BORRADOR, scheduled_datetime=cuando)


def test_manda_cada_borrador_del_mes(cx, monkeypatch):
    _borrador(cx, "Uno", "2026-10-03T11:00")
    _borrador(cx, "Dos", "2026-10-04T15:00")
    _borrador(cx, "Fuera", "2026-11-01T11:00")  # otro mes
    mandadas = []
    monkeypatch.setattr(handlers.send_plan, "_componer_y_enviar",
                        lambda _cx, f: mandadas.append(f["nombre"]))

    res = handlers.lote_enviar(cx, _job(cx, "2026-10"))

    assert res == {"enviadas": 2, "fallidas": 0, "errores": []}
    assert sorted(mandadas) == ["Dos", "Uno"]


def test_una_pieza_caida_no_tumba_el_lote(cx, monkeypatch):
    _borrador(cx, "Buena", "2026-10-03T11:00")
    _borrador(cx, "Mala", "2026-10-04T15:00")

    def enviar(_cx, f):
        if f["nombre"] == "Mala":
            raise RuntimeError("telegram 400")

    monkeypatch.setattr(handlers.send_plan, "_componer_y_enviar", enviar)

    res = handlers.lote_enviar(cx, _job(cx, "2026-10"))

    assert res["enviadas"] == 1 and res["fallidas"] == 1
    assert "Mala" in res["errores"][0]


def test_si_todo_falla_el_job_queda_en_error(cx, monkeypatch):
    _borrador(cx, "Uno", "2026-10-03T11:00")
    monkeypatch.setattr(handlers.send_plan, "_componer_y_enviar",
                        lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="las 1 piezas fallaron"):
        handlers.lote_enviar(cx, _job(cx, "2026-10"))


def test_mes_vacio_no_es_error(cx, monkeypatch):
    monkeypatch.setattr(handlers.send_plan, "_componer_y_enviar",
                        lambda *_: pytest.fail("no debió mandar nada"))
    assert handlers.lote_enviar(cx, _job(cx, "2026-10")) == {"enviadas": 0, "fallidas": 0}


def test_mes_invalido(cx):
    with pytest.raises(ValueError, match="mes inválido"):
        handlers.lote_enviar(cx, _job(cx, "octubre"))


def test_otra_marca_no_manda_memes(cx):
    aid = db.insert(cx, "accounts", slug="pensionmas", ig_handle="@pensionmas",
                    nombre="Pensión+", ciudad="CDMX")
    with pytest.raises(ValueError, match="solo existen para gdlscene"):
        handlers.lote_enviar(cx, _job(cx, "2026-10", account_id=aid))
