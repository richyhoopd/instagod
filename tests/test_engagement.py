"""Cerebro de engagement: scoring puro de banda y formato + cold-start."""
from __future__ import annotations

from src import db, engagement


def test_score_formatos_cold_start_usa_reglas() -> None:
    # Sin datos suficientes → pesos de Ricardo (absurdo_domestico manda).
    pesos = engagement.score_formatos([], min_posts=2)
    assert pesos["absurdo_domestico"] > pesos["comunicado"]


def test_score_formatos_aprende_de_datos() -> None:
    # absurdo_domestico con reach/shares altos sube por encima de su peso base.
    posts = [
        {"patron": "absurdo_domestico", "reach": 1368, "shares": 30, "saved": 5},
        {"patron": "absurdo_domestico", "reach": 1140, "shares": 10, "saved": 2},
        {"patron": "comunicado", "reach": 200, "shares": 0, "saved": 0},
        {"patron": "comunicado", "reach": 180, "shares": 1, "saved": 0},
    ]
    pesos = engagement.score_formatos(posts, min_posts=2)
    assert pesos["absurdo_domestico"] > pesos["comunicado"] * 2


def test_score_bandas_anti_repeticion() -> None:
    # Misma señal base, pero una publicó ayer → debe quedar debajo.
    bandas = [
        {"band_id": 1, "er": 0.1, "shares": 5, "prioridad": 3, "followers_ig": 1000,
         "n_posts": 3, "dias_desde_ultimo": 1},
        {"band_id": 2, "er": 0.1, "shares": 5, "prioridad": 3, "followers_ig": 1000,
         "n_posts": 3, "dias_desde_ultimo": 60},
    ]
    orden = [b["band_id"] for b in engagement.score_bandas(bandas, min_posts=2)]
    assert orden == [2, 1]


def test_score_bandas_cold_start_por_followers() -> None:
    bandas = [
        {"band_id": 1, "er": None, "shares": 0, "prioridad": 3, "followers_ig": 500,
         "n_posts": 0, "dias_desde_ultimo": None},
        {"band_id": 2, "er": None, "shares": 0, "prioridad": 3, "followers_ig": 5000,
         "n_posts": 0, "dias_desde_ultimo": None},
    ]
    orden = [b["band_id"] for b in engagement.score_bandas(bandas, min_posts=2)]
    assert orden == [2, 1]  # sin datos → más followers primero


# ---------- Capa IO + elegir_candidatos (Step 6, DB tmp) ----------

def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def test_elegir_candidatos_favorece_banda_de_mas_engagement(tmp_path) -> None:
    # Dos bandas cold-start (sin posts): la de más followers debe salir primero
    # y cada candidato trae una foto usable no usada + el patrón de mayor peso.
    cx = _cx(tmp_path)
    chica = db.upsert_band(cx, "Banda Chica", "chica", followers_ig=500, prioridad=3)
    grande = db.upsert_band(cx, "Banda Grande", "grande", followers_ig=5000, prioridad=3)
    f_chica = db.insert(cx, "photos", band_id=chica, path="/tmp/chica.jpg", usable_meme=1)
    f_grande = db.insert(cx, "photos", band_id=grande, path="/tmp/grande.jpg", usable_meme=1)

    cands = engagement.elegir_candidatos(cx, 2, account_id=1)

    assert [c["band_id"] for c in cands] == [grande, chica]
    assert cands[0]["photo_id"] == f_grande and cands[1]["photo_id"] == f_chica
    # cold-start del eje formato: absurdo_domestico es el de mayor peso base.
    assert cands[0]["formato_patron"] == "absurdo_domestico"
    # band_score debe ser float (contrato de rerank_cola)
    assert all(isinstance(c["band_score"], (int, float)) for c in cands)


def test_elegir_candidatos_salta_banda_sin_foto_usable(tmp_path) -> None:
    cx = _cx(tmp_path)
    con = db.upsert_band(cx, "Con Foto", "confoto", followers_ig=5000, prioridad=3)
    db.upsert_band(cx, "Sin Foto", "sinfoto", followers_ig=9000, prioridad=3)
    # banda "Con Foto" tiene foto usable; "Sin Foto" (más followers) no.
    db.insert(cx, "photos", band_id=con, path="/tmp/con.jpg", usable_meme=1)

    cands = engagement.elegir_candidatos(cx, 5, account_id=1)
    assert [c["band_id"] for c in cands] == [con]


# ---------- Task H: rerank dinámico de la cola ----------

def test_rerank_reordena_futuros_por_score() -> None:
    from src import engagement
    # dos items futuros; el de patrón ganador debe quedar en el slot más cercano
    items = [
        {"queue_id": 1, "patron": "comunicado", "band_score": 0.1, "scheduled": "2026-06-10T20:00"},
        {"queue_id": 2, "patron": "absurdo_domestico", "band_score": 0.1, "scheduled": "2026-06-11T20:00"},
    ]
    pesos = {"absurdo_domestico": 2.0, "comunicado": 0.5}
    nuevo = engagement.rerank_cola(items, pesos_formato=pesos)
    # el ganador (2) toma el slot más temprano (10), el otro el 11
    asignado = {r["queue_id"]: r["scheduled"] for r in nuevo}
    assert asignado[2] == "2026-06-10T20:00" and asignado[1] == "2026-06-11T20:00"
