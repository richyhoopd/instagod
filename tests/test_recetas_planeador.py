"""Recetas por marca + planeador multimarca (peso, cooldown, nuevas primero)."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta

import pytest

from src import db, entidades, feeds, recetas
from tests.fixtures.feed_mwrs import item

T0 = datetime(2026, 11, 2, 1, 0)  # naive UTC


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    aid = db.insert(cx, "accounts", slug="melaquecapital", ig_handle="mc",
                    nombre="MWRS", ciudad="Melaque")
    recetas.sembrar(cx, aid, recetas.SEMILLA_MELAQUECAPITAL)
    return cx, aid


def _slots(n, cada_h=24):
    return [T0 + timedelta(hours=cada_h * i) for i in range(n)]


def test_sembrar_es_idempotente_y_no_pisa_ediciones(tmp_path):
    cx, aid = _cx(tmp_path)
    r = recetas.por_slug(cx, aid, "ficha-carrusel")
    db.update(cx, "brand_recipes", r["id"], peso=9)
    assert recetas.sembrar(cx, aid, recetas.SEMILLA_MELAQUECAPITAL) == 0
    assert recetas.por_slug(cx, aid, "ficha-carrusel")["peso"] == 9
    slugs = {r["slug"]: r for r in recetas.listar(cx, aid)}
    assert set(slugs) == {"ficha-carrusel", "tip-con-ejemplo", "tip-con-ejemplo-9x16"}
    assert slugs["tip-con-ejemplo-9x16"]["formato"] == "carrusel 9:16"
    assert slugs["ficha-carrusel"]["item_types"] == ["property", "lot"]


def test_marcas_seed_siembra_recetas_de_melaque(tmp_path):
    from src import marcas_seed
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    marcas_seed.sembrar(cx)
    aid = db.rows(cx, "SELECT id FROM accounts WHERE slug='melaquecapital'")[0]["id"]
    assert len(recetas.listar(cx, aid)) == 3
    marcas_seed.sembrar(cx)
    assert len(recetas.listar(cx, aid, solo_activas=False)) == 3


def test_render_prompt_lista_facts_y_sin_confirmar(tmp_path):
    cx, aid = _cx(tmp_path)
    eid, _ = feeds.upsert_item(cx, aid, 1, item())
    it = recetas.item_de(entidades.obtener(cx, eid))
    assert it["title"] == "Lote esquina en Melaque" and it["type"] == "lot"
    texto = recetas.render_prompt(recetas.por_slug(cx, aid, "ficha-carrusel"), it)
    assert "$1,450,000 MXN" in texto and "m2: 300" in texto
    assert "SIN CONFIRMAR" in texto and "regimen" in texto
    assert item()["url"] in texto and "{{" not in texto


def test_item_de_prefiere_cdn(tmp_path):
    cx, aid = _cx(tmp_path)
    eid, _ = feeds.upsert_item(cx, aid, 1, item(),
                               subir=lambda u, public_id: f"https://cdn/{public_id}.jpg")
    media = recetas.item_de(entidades.obtener(cx, eid))["media"]
    assert len(media) == 2 and all(u.startswith("https://cdn/feed_") for u in media)


def test_planear_reparte_por_peso(tmp_path):
    cx, aid = _cx(tmp_path)
    for i in range(30):
        entidades.crear(cx, aid, f"Lote {i}", "lot", slug=f"l{i}")
    plan = recetas.planear(cx, aid, _slots(12), ahora=T0)
    cuenta = Counter(p["receta"] for p in plan)
    assert cuenta == {"ficha-carrusel": 6, "tip-con-ejemplo": 4, "tip-con-ejemplo-9x16": 2}


def test_planear_respeta_cooldown_por_receta(tmp_path):
    cx, aid = _cx(tmp_path)
    for slug in ("tip-con-ejemplo", "tip-con-ejemplo-9x16"):
        db.update(cx, "brand_recipes", recetas.por_slug(cx, aid, slug)["id"], activa=0)
    eid = entidades.crear(cx, aid, "Único", "lot", slug="unico")
    plan = recetas.planear(cx, aid, _slots(3, cada_h=24 * 20), ahora=T0)
    # cooldown ficha = 30 días: día 0 sí, día 20 no, día 40 sí.
    assert [p["entidad_id"] for p in plan] == [eid, None, eid]
    assert plan[1]["motivo"]


def test_cooldown_lee_historial_de_content_queue_y_jobs(tmp_path):
    cx, aid = _cx(tmp_path)
    for slug in ("tip-con-ejemplo", "tip-con-ejemplo-9x16"):
        db.update(cx, "brand_recipes", recetas.por_slug(cx, aid, slug)["id"], activa=0)
    a = entidades.crear(cx, aid, "A", "lot", slug="a")
    b = entidades.crear(cx, aid, "B", "lot", slug="b")
    c = entidades.crear(cx, aid, "C", "lot", slug="c")
    hace = (T0 - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
    db.insert(cx, "content_queue", account_id=aid, tipo="slideshow", entity_id=a,
              formato_patron="receta:ficha-carrusel")
    # Rechazada en Telegram: no bloquea la entidad.
    db.insert(cx, "content_queue", account_id=aid, tipo="slideshow", entity_id=c,
              formato_patron="receta:ficha-carrusel", aprobacion="rechazado")
    cx.execute("UPDATE content_queue SET created_at = ?", (hace,))
    db.insert(cx, "jobs", tipo="receta.generar", account_id=aid,
              payload_json=json.dumps({"receta": "ficha-carrusel", "entidad_id": b,
                                       "scheduled_datetime": T0.isoformat()}))
    plan = recetas.planear(cx, aid, _slots(1), ahora=T0)
    assert plan[0]["entidad_id"] == c


def test_prefiere_nuevas_y_luego_la_mas_reciente(tmp_path):
    cx, aid = _cx(tmp_path)
    vieja = entidades.crear(cx, aid, "Vieja", "lot", slug="vieja")
    nueva = entidades.crear(cx, aid, "Nueva", "property", slug="nueva")
    plan = recetas.planear(cx, aid, _slots(3), ahora=T0)
    # 1º la más nueva (id mayor), 2º la otra nunca usada, 3º la menos usada.
    assert [p["entidad_id"] for p in plan[:2]] == [nueva, vieja]


def test_filtra_tipo_e_inactivas(tmp_path):
    cx, aid = _cx(tmp_path)
    entidades.crear(cx, aid, "Post del blog", "post", slug="blog")
    arch = entidades.crear(cx, aid, "Vendida", "lot", slug="vendida")
    entidades.archivar(cx, arch)
    plan = recetas.planear(cx, aid, _slots(2), ahora=T0)
    assert all(p["receta"] is None for p in plan)


def test_multimarca_no_cruza_cuentas(tmp_path):
    cx, aid = _cx(tmp_path)
    entidades.crear(cx, 1, "Banda", "lot", slug="banda-gdl")   # gdlscene = 1
    assert all(p["receta"] is None for p in recetas.planear(cx, aid, _slots(2), ahora=T0))
    # gdlscene no tiene recetas: el planeador no le asigna nada.
    assert all(p["receta"] is None for p in recetas.planear(cx, 1, _slots(2), ahora=T0))


def test_slots_mes_reparte_en_horarios_de_la_marca():
    s = recetas.slots_mes(["10:00", "18:00"], 2026, 11, 12)
    assert len(s) == 12 and s[0].day == 1 and s[0].hour == 10
    assert all(x.month == 11 for x in s) and s == sorted(s)


def test_encolar_plan_crea_jobs(tmp_path):
    cx, aid = _cx(tmp_path)
    entidades.crear(cx, aid, "A", "lot", slug="a")
    plan = recetas.planear(cx, aid, _slots(2), ahora=T0)
    ids = recetas.encolar_plan(cx, aid, plan)
    assert len(ids) == sum(1 for p in plan if p["receta"])
    # Los jobs encolados cuentan para el cooldown del siguiente plan.
    assert all(p["receta"] is None or p["entidad_id"] is not None
               for p in recetas.planear(cx, aid, _slots(2), ahora=T0))


# ----------------------------------------------------- generar desde entidad

def test_generar_desde_entidad_pasa_facts_media_y_aspecto(tmp_path):
    cx, aid = _cx(tmp_path)
    eid, _ = feeds.upsert_item(cx, aid, 1, item())
    llamadas = []

    def generar(cx_, tema, **kw):
        llamadas.append((tema, kw))
        return 77

    qid = recetas.generar_desde_entidad(cx, aid, "tip-con-ejemplo-9x16", eid,
                                        generar=generar,
                                        scheduled_datetime="2026-11-02T01:00:00")
    tema, kw = llamadas[0]
    assert qid == 77 and tema == "Lote esquina en Melaque"
    assert kw["marca"] == "melaquecapital" and kw["aspect"] == "9:16"
    assert kw["hechos"]["m2"] == 300 and kw["no_verificados"] == ["regimen"]
    assert kw["entity_id"] == eid and kw["receta"] == "tip-con-ejemplo-9x16"
    assert len(kw["imagenes_preferidas"]) == 2
    assert "RECETA tip-con-ejemplo" in kw["contexto"]


def test_generar_rechaza_entidad_ajena_inactiva_o_de_otro_tipo(tmp_path):
    cx, aid = _cx(tmp_path)
    ajena = entidades.crear(cx, 1, "Ajena", "lot", slug="ajena")
    post = entidades.crear(cx, aid, "Post", "post", slug="post")
    vendida, _ = feeds.upsert_item(cx, aid, 1, item("v", status="sold"))
    for eid in (ajena, post, vendida):
        with pytest.raises(ValueError):
            recetas.generar_desde_entidad(cx, aid, "ficha-carrusel", eid,
                                          generar=lambda *a, **k: 1)
