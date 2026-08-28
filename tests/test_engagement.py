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


def test_rerank_no_ignora_band_score_cuando_es_cero() -> None:
    # Una banda SIN señal (score 0) no debe ganar el slot temprano solo porque
    # su formato pese mucho: la banda con engagement real va primero.
    items = [
        {"queue_id": 1, "patron": "absurdo_domestico", "band_score": 0.0,
         "scheduled": "2026-06-10T20:00"},
        {"queue_id": 2, "patron": "comunicado", "band_score": 0.1,
         "scheduled": "2026-06-11T20:00"},
    ]
    pesos = {"absurdo_domestico": 2.0, "comunicado": 0.5}
    nuevo = engagement.rerank_cola(items, pesos_formato=pesos)
    asignado = {r["queue_id"]: r["scheduled"] for r in nuevo}
    assert asignado[2] == "2026-06-10T20:00" and asignado[1] == "2026-06-11T20:00"


# ---------- Fix: recencia real (julianday vs offset `+0000` de la Graph API) ----------

def _post(cx, band_id, *, dias, media_id, likes=50, reach=500, saved=5, shares=10,
          sufijo="+0000"):
    """Inserta un post NUESTRO hace `dias`, con el formato de fecha de la Graph API."""
    from datetime import datetime, timedelta, timezone
    ts = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%S") + sufijo
    return db.insert(cx, "ig_posts", media_id=media_id, band_id=band_id, timestamp=ts,
                     likes=likes, comments=2, saved=saved, reach=reach, shares=shares)


def test_cargar_bandas_calcula_dias_desde_ultimo_con_offset_de_graph_api(tmp_path) -> None:
    """Regresión: `2026-08-24T21:22:15+0000` (offset SIN dos puntos) hacía que
    julianday() devolviera NULL, así que `dias_desde_ultimo` era siempre None y la
    penalización anti-repetición de `_clave_banda` nunca se aplicaba. En prod eran
    las 154 filas de ig_posts, o sea el 100%."""
    cx = _cx(tmp_path)
    bid = db.upsert_band(cx, "Con Historial", "conhistorial", followers_ig=1000, prioridad=3)
    _post(cx, bid, dias=40, media_id="m1")
    _post(cx, bid, dias=10, media_id="m2")  # el más reciente manda

    fila = next(b for b in engagement._cargar_bandas(cx, 1) if b["band_id"] == bid)
    assert fila["dias_desde_ultimo"] == 10, "el offset +0000 debe normalizarse antes de medir"
    assert fila["shares"] == 20  # suma de los dos posts


def test_cargar_bandas_tolera_offset_con_dos_puntos_y_sin_offset(tmp_path) -> None:
    cx = _cx(tmp_path)
    a = db.upsert_band(cx, "Con Colon", "concolon", followers_ig=1000, prioridad=3)
    b = db.upsert_band(cx, "Sin Offset", "sinoffset", followers_ig=1000, prioridad=3)
    _post(cx, a, dias=7, media_id="ma", sufijo="+00:00")
    _post(cx, b, dias=7, media_id="mb", sufijo="")

    filas = {f["band_id"]: f for f in engagement._cargar_bandas(cx, 1)}
    assert filas[a]["dias_desde_ultimo"] == 7
    assert filas[b]["dias_desde_ultimo"] == 7


def test_clave_banda_penaliza_de_verdad_con_recencia_real(tmp_path) -> None:
    """Con el fix, dos bandas de ER idéntico se ordenan por quién lleva más sin
    publicarse. Antes ambas caían con dias_desde_ultimo=None y empataban."""
    cx = _cx(tmp_path)
    ayer = db.upsert_band(cx, "Publicada Ayer", "ayer", followers_ig=1000, prioridad=3)
    vieja = db.upsert_band(cx, "Publicada Hace Mucho", "vieja", followers_ig=1000, prioridad=3)
    for bid, dias, mid in ((ayer, 1, "p1"), (ayer, 2, "p2"), (vieja, 60, "p3"), (vieja, 61, "p4")):
        _post(cx, bid, dias=dias, media_id=mid)

    orden = [b["band_id"] for b in engagement.score_bandas(
        engagement._cargar_bandas(cx, 1), min_posts=2)]
    assert orden.index(vieja) < orden.index(ayer)


# ---------- score_plan: mezcla normalizada de engagement y recencia ----------

def test_score_plan_normaliza_ambos_ejes() -> None:
    """El ER de la cuenta vive en 0.016–0.188 y la penalización de recencia llega
    a 1.0: sin normalizar, la recencia aplasta al engagement. Con ER idéntico debe
    ganar la que lleva más tiempo sin publicarse, y con recencia idéntica la de
    mejor ER — ningún eje puede anular al otro."""
    misma_recencia = [
        {"band_id": 1, "er": 0.18, "shares": 0, "followers_ig": 1000, "dias_desde_ultimo": 30},
        {"band_id": 2, "er": 0.02, "shares": 0, "followers_ig": 1000, "dias_desde_ultimo": 30},
    ]
    s = engagement.score_plan(misma_recencia)
    assert s[1] > s[2]

    mismo_er = [
        {"band_id": 1, "er": 0.10, "shares": 0, "followers_ig": 1000, "dias_desde_ultimo": 5},
        {"band_id": 2, "er": 0.10, "shares": 0, "followers_ig": 1000, "dias_desde_ultimo": 100},
    ]
    s = engagement.score_plan(mismo_er)
    assert s[2] > s[1]


def test_score_plan_coldstart_no_desplaza_a_la_que_ya_funciono() -> None:
    """Una banda sin historial propio, por muchos followers que tenga, no debe
    ganarle a una que ya demostró buen ER en nuestra cuenta con recencia igual."""
    bandas = [
        {"band_id": 1, "er": 0.18, "shares": 30, "followers_ig": 500, "dias_desde_ultimo": 60},
        {"band_id": 2, "er": None, "shares": 0, "followers_ig": 900_000, "dias_desde_ultimo": None},
    ]
    s = engagement.score_plan(bandas)
    assert s[1] > s[2]


def test_score_plan_nunca_publicada_entra_con_recencia_neutra() -> None:
    """`dias_desde_ultimo=None` no es "hace muchísimo que no la publicamos": es
    que no hay historial. Debe quedar entre la recién publicada y la muy vieja."""
    bandas = [
        {"band_id": 1, "er": 0.1, "shares": 0, "followers_ig": 1000, "dias_desde_ultimo": 0},
        {"band_id": 2, "er": 0.1, "shares": 0, "followers_ig": 1000, "dias_desde_ultimo": None},
        {"band_id": 3, "er": 0.1, "shares": 0, "followers_ig": 1000, "dias_desde_ultimo": 999},
    ]
    s = engagement.score_plan(bandas)
    assert s[1] < s[2] < s[3]


def test_score_plan_pondera_shares() -> None:
    bandas = [
        {"band_id": 1, "er": 0.1, "shares": 0, "followers_ig": 1000, "dias_desde_ultimo": 30},
        {"band_id": 2, "er": 0.1, "shares": 80, "followers_ig": 1000, "dias_desde_ultimo": 30},
    ]
    s = engagement.score_plan(bandas)
    assert s[2] > s[1]


def test_score_plan_sin_bandas_no_explota() -> None:
    assert engagement.score_plan([]) == {}
