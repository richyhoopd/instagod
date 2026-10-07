"""Orquestador de slideshows: dry-run, encolado y envío a Telegram."""
from __future__ import annotations

import json
import json as json_mod
from dataclasses import dataclass

from src import db
from src import db as db_mod
from src import generate_slideshow as gs


@dataclass
class _Img:
    ruta_o_url: str
    source: str = "pexels"


def _guion(n=3):
    return {"tema": "café", "hook": "Gancho", "caption": "pie del post",
            "cta": "Sígueme",
            "slides": [{"text": "Gancho", "rol": "hook", "image_hint": "a"},
                       {"text": "Punto", "rol": "punto", "image_hint": "b"},
                       {"text": "Sígueme", "rol": "cta", "image_hint": "c"}][:n]}


def _preparar(monkeypatch, tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    monkeypatch.setattr(gs.slideshow_script, "generar_guion",
                        lambda tema, **kw: _guion())
    monkeypatch.setattr(gs.image_sources, "resolver",
                        lambda hints, fuentes, **kw: [_Img("/tmp/x.jpg")] * len(hints))
    pngs = iter([tmp_path / f"s{i}.png" for i in range(10)])

    def _render(template_file, ctx, **kw):
        p = next(pngs)
        p.write_bytes(b"png")
        return p

    monkeypatch.setattr(gs.compose, "render_card", _render)
    subidas = []

    def _upload(path, public_id=None):
        subidas.append(public_id)
        return f"https://cdn/{public_id}.jpg"

    monkeypatch.setattr(gs.host, "upload", _upload)
    enviados = []
    monkeypatch.setattr(gs.approval, "enviar_a_telegram",
                        lambda cap, url, qid, **kw: enviados.append((cap, url, qid, kw)))
    return cx, subidas, enviados


def test_dry_run_no_sube_ni_encola(monkeypatch, tmp_path) -> None:
    cx, subidas, enviados = _preparar(monkeypatch, tmp_path)
    out = gs.generar(cx, "café", dry_run=True)
    assert out is None
    assert subidas == [] and enviados == []
    assert db.rows(cx, "SELECT * FROM content_queue") == []


def test_generar_encola_y_envia(monkeypatch, tmp_path) -> None:
    cx, subidas, enviados = _preparar(monkeypatch, tmp_path)
    qid = gs.generar(cx, "café")
    assert qid is not None
    fila = db.get(cx, "content_queue", qid)
    assert fila["tipo"] == "slideshow"
    assert fila["aprobacion"] == "pendiente"
    urls = json.loads(fila["imagen_url"])
    assert len(urls) == 3 and all(u.startswith("https://cdn/") for u in urls)
    contrato = json.loads(fila["slideshow_json"])
    assert len(contrato["slides"]) == 3
    assert enviados and enviados[0][2] == qid
    assert len(subidas) == 3


def test_generar_aborta_si_contrato_invalido(monkeypatch, tmp_path) -> None:
    cx, _, enviados = _preparar(monkeypatch, tmp_path)
    malo = _guion()
    malo["slides"][0]["text"] = "   "
    monkeypatch.setattr(gs.slideshow_script, "generar_guion",
                        lambda tema, **kw: malo)
    import pytest
    with pytest.raises(RuntimeError):
        gs.generar(cx, "café")
    assert enviados == []
    assert db.rows(cx, "SELECT * FROM content_queue") == []


def _alta_marca(cx):
    return db_mod.insert(
        cx, "accounts", slug="pensionmas", ig_handle="@pensionmas",
        nombre="Pensión+", ciudad="CDMX",
        voz="REGLAS: montos estimados.",
        fuentes_imagen=json_mod.dumps(["pinterest", "pexels"]),
        formatos=json_mod.dumps(["libre"]),
        estilos_json=json_mod.dumps({"pensionmas": {
            "texto": "blanco", "fondo": "navy", "background_opacity": 0.3,
            "chrome": {"handle": "@pensionmas", "logo": None},
            "roles": {"hook": {"font": "Erode-Bold", "font_size": "extra_large",
                               "text_style": "background",
                               "text_vertical_anchor": "center"},
                      "punto": {"font": "Erode-Semibold", "font_size": "large",
                                "text_style": "background",
                                "text_vertical_anchor": "center"},
                      "cta": {"font": "Poppins-SemiBold", "font_size": "medium",
                              "text_style": "background",
                              "text_vertical_anchor": "bottom"}}}}))


def test_generar_con_marca_usa_su_perfil(monkeypatch, tmp_path) -> None:
    cx, subidas, enviados = _preparar(monkeypatch, tmp_path)
    mid = _alta_marca(cx)
    capturado = {}

    def _guion_spy(tema, **kw):
        capturado.update(kw)
        return _guion()

    monkeypatch.setattr(gs.slideshow_script, "generar_guion", _guion_spy)
    fuentes_vistas = {}

    def _resolver_spy(hints, fuentes, **kw):
        fuentes_vistas["f"] = fuentes
        return [None] * len(hints)

    monkeypatch.setattr(gs.image_sources, "resolver", _resolver_spy)
    qid = gs.generar(cx, "afore", marca="pensionmas")
    fila = db_mod.get(cx, "content_queue", qid)
    assert fila["account_id"] == mid
    assert capturado["formato"] == "libre"                 # default del perfil
    assert "montos estimados" in capturado["contexto"]     # voz inyectada
    assert fuentes_vistas["f"] == ["pinterest", "pexels"]
    assert enviados[-1][3].get("account_slug") == "pensionmas"
    contrato = json_mod.loads(fila["slideshow_json"])
    assert contrato["brief"]["fondo"] == "navy"            # estilo de marca


def test_generar_formato_no_habilitado(monkeypatch, tmp_path) -> None:
    cx, _, _ = _preparar(monkeypatch, tmp_path)
    _alta_marca(cx)
    import pytest
    with pytest.raises(ValueError, match="formato"):
        gs.generar(cx, "afore", marca="pensionmas", formato="perfil")


def test_generar_sin_marca_sigue_siendo_gdlscene(monkeypatch, tmp_path) -> None:
    cx, _, enviados = _preparar(monkeypatch, tmp_path)
    qid = gs.generar(cx, "café")
    assert db_mod.get(cx, "content_queue", qid)["account_id"] == 1
    assert enviados[-1][3].get("account_slug", "gdlscene") == "gdlscene"


def test_generar_gdlscene_default_sigue_siendo_listicle(monkeypatch, tmp_path) -> None:
    """gdlscene sin --formato explícito conserva el default histórico del motor v1."""
    cx, _, _ = _preparar(monkeypatch, tmp_path)
    capturado = {}

    def _guion_spy(tema, **kw):
        capturado.update(kw)
        return _guion()

    monkeypatch.setattr(gs.slideshow_script, "generar_guion", _guion_spy)
    gs.generar(cx, "café")
    assert capturado["formato"] == "listicle"


def test_generar_pasa_slug_al_sourcing(tmp_path, monkeypatch) -> None:
    """El provider `carpeta` necesita saber de qué marca son las fotos."""
    from src import marcas_seed
    cx, _, _ = _preparar(monkeypatch, tmp_path)
    marcas_seed.sembrar(cx)
    visto = {}

    def _resolver_spy(hints, fuentes, **kw):
        visto.update(kw)
        return [None] * len(hints)
    monkeypatch.setattr(gs.image_sources, "resolver", _resolver_spy)
    gs.generar(cx, "comprar en Melaque", marca="melaquecapital", dry_run=True)
    assert visto.get("slug") == "melaquecapital"


# ---------- Fase 3: brand_sources, prompts por formato, hashtags, topic_id ----------

def test_generar_usa_orden_imagen_de_fuentes_mod_cuando_no_pasan_fuentes(monkeypatch, tmp_path) -> None:
    cx, _, _ = _preparar(monkeypatch, tmp_path)
    from src import fuentes
    fuentes.crear(cx, 1, "imagen", "pinterest")
    fuentes.crear(cx, 1, "imagen", "banco")
    fuentes_vistas = {}

    def _resolver_spy(hints, fuentes_, **kw):
        fuentes_vistas["f"] = fuentes_
        return [None] * len(hints)

    monkeypatch.setattr(gs.image_sources, "resolver", _resolver_spy)
    gs.generar(cx, "café")
    assert fuentes_vistas["f"] == ["pinterest", "banco"]


def test_generar_concatena_prompt_por_formato_en_contexto_del_guion(monkeypatch, tmp_path) -> None:
    cx, _, _ = _preparar(monkeypatch, tmp_path)
    db_mod.update(cx, "accounts", 1, voz="Voz de la marca.",
                  prompts_json=json_mod.dumps(
                      {"por_formato": {"listicle": "Enfócate en precios."}}))
    capturado = {}

    def _guion_spy(tema, **kw):
        capturado.update(kw)
        return _guion()

    monkeypatch.setattr(gs.slideshow_script, "generar_guion", _guion_spy)
    gs.generar(cx, "café", formato="listicle")
    assert "Voz de la marca." in capturado["contexto"]
    assert "Enfócate en precios." in capturado["contexto"]


def test_generar_agrega_caption_extra_y_hashtags_antes_de_encolar(monkeypatch, tmp_path) -> None:
    cx, _, enviados = _preparar(monkeypatch, tmp_path)
    db_mod.update(cx, "accounts", 1, prompts_json=json_mod.dumps(
        {"caption_extra": "Síguenos para más.", "hashtags": ["#gdl", "#escena"]}))
    qid = gs.generar(cx, "café")
    fila = db_mod.get(cx, "content_queue", qid)
    assert "Síguenos para más." in fila["caption"]
    assert "#gdl #escena" in fila["caption"]
    assert enviados[-1][0] == fila["caption"]


def test_generar_marca_topic_usado_al_encolar(monkeypatch, tmp_path) -> None:
    cx, _, _ = _preparar(monkeypatch, tmp_path)
    tid = db_mod.insert(cx, "topic_suggestions", account_id=1, titulo="tema x")
    qid = gs.generar(cx, "café", topic_id=tid)
    fila = db_mod.get(cx, "topic_suggestions", tid)
    assert fila["usado_en_queue_id"] == qid


def test_generar_topic_id_tolera_fila_inexistente(monkeypatch, tmp_path) -> None:
    cx, _, _ = _preparar(monkeypatch, tmp_path)
    qid = gs.generar(cx, "café", topic_id=999999)
    assert qid is not None


def test_notificar_telegram_false_no_envia(monkeypatch, tmp_path) -> None:
    """Con notificar_telegram=False la pieza se encola pero NO va a Telegram,
    y el brief persiste el flag para que regenerar lo respete."""
    cx, _, enviados = _preparar(monkeypatch, tmp_path)
    qid = gs.generar(cx, "café", notificar_telegram=False, creado_por=1)
    assert enviados == []
    fila = db.get(cx, "content_queue", qid)
    assert fila["aprobacion"] == "pendiente" and fila["origen"] == "api"
    brief = json.loads(fila["slideshow_json"])["brief"]
    assert brief["notificar_telegram"] is False


# ------------------------------------------- recetas: cifras contra facts

def _guion_con(texto):
    g = _guion()
    g["slides"][1]["text"] = texto
    return g


def test_cifra_fuera_de_facts_regenera_una_vez_y_pasa(monkeypatch, tmp_path) -> None:
    cx, _, enviados = _preparar(monkeypatch, tmp_path)
    llamadas = []

    def _guion_spy(tema, **kw):
        llamadas.append(kw.get("feedback"))
        return _guion_con("A 5 minutos del mar" if len(llamadas) == 1 else "Mide 300 m2")

    monkeypatch.setattr(gs.slideshow_script, "generar_guion", _guion_spy)
    qid = gs.generar(cx, "lote", hechos={"m2": 300}, entity_id=9, receta="ficha-carrusel")
    assert len(llamadas) == 2 and llamadas[0] is None and "5" in llamadas[1]
    fila = db.get(cx, "content_queue", qid)
    assert fila["entity_id"] == 9 and fila["formato_patron"] == "receta:ficha-carrusel"
    assert not enviados[0][0].startswith("⚠️")


def test_cifra_fuera_dos_veces_descarta(monkeypatch, tmp_path) -> None:
    import pytest
    cx, subidas, enviados = _preparar(monkeypatch, tmp_path)
    monkeypatch.setattr(gs.slideshow_script, "generar_guion",
                        lambda tema, **kw: _guion_con("Desde 2 millones"))
    with pytest.raises(gs.CifrasFueraDeFacts):
        gs.generar(cx, "lote", hechos={"precio": "$1,450,000 MXN"})
    assert subidas == [] and enviados == []
    assert db.rows(cx, "SELECT * FROM content_queue") == []


def test_mencion_no_verificada_pone_alerta_en_tarjeta(monkeypatch, tmp_path) -> None:
    """Nombrar el tema sin afirmar su valor pasa, pero con ⚠️ (afirmar
    "ejidal" ya se rechaza: ver test_unverified_afirmado_*)."""
    cx, _, enviados = _preparar(monkeypatch, tmp_path)
    monkeypatch.setattr(gs.slideshow_script, "generar_guion",
                        lambda tema, **kw: _guion_con("Régimen por confirmar, 300 m2"))
    gs.generar(cx, "lote", hechos={"m2": 300, "regimen": "ejidal"},
               no_verificados=["regimen"])
    assert enviados[0][0].startswith("⚠️ Menciona datos SIN VERIFICAR: regimen")


def test_sin_hechos_no_valida_cifras(monkeypatch, tmp_path) -> None:
    cx, _, enviados = _preparar(monkeypatch, tmp_path)
    monkeypatch.setattr(gs.slideshow_script, "generar_guion",
                        lambda tema, **kw: _guion_con("Top 10 discos de 1999"))
    assert gs.generar(cx, "discos") is not None


def test_916_manda_zip(monkeypatch, tmp_path) -> None:
    import zipfile
    cx, _, _ = _preparar(monkeypatch, tmp_path)
    monkeypatch.setattr(gs.config, "BASE_DIR", tmp_path)
    docs = []
    from src import avisos_marca
    monkeypatch.setattr(avisos_marca, "enviar_documento",
                        lambda slug, ruta, caption="": docs.append(ruta) or True)
    qid = gs.generar(cx, "café", aspect="9:16")
    assert len(docs) == 1 and docs[0].name == f"gdlscene_q{qid}_9x16.zip"
    assert len(zipfile.ZipFile(docs[0]).namelist()) == 3


def test_con_fotos_de_entidad_solo_usa_esas_y_las_repite(monkeypatch, tmp_path) -> None:
    """Ficha de una propiedad: nunca fotos de otro lugar; si faltan, se repiten."""
    from src import marcas_seed
    cx, _, _ = _preparar(monkeypatch, tmp_path)
    marcas_seed.sembrar(cx)
    vistas = {}

    def _resolver_spy(hints, fuentes, **kw):
        vistas["f"] = fuentes
        return [_Img("/e/1.jpg", "entidad"), _Img("/e/2.jpg", "entidad"), None]

    monkeypatch.setattr(gs.image_sources, "resolver", _resolver_spy)
    qid = gs.generar(cx, "casa", marca="melaquecapital",
                     imagenes_preferidas=["https://x/1.jpg", "https://x/2.jpg"])
    contrato = json_mod.loads(db_mod.get(cx, "content_queue", qid)["slideshow_json"])
    assert vistas["f"] == ["entidad"]
    assert [s["image_urls"] for s in contrato["slides"]] == [["/e/1.jpg"], ["/e/2.jpg"], ["/e/1.jpg"]]
    assert {s["source"] for s in contrato["slides"]} == {"entidad"}


# ------------------- recetas: URL de la entidad, unverified, régimen, fotos

URL = "https://melaquecapital.com/es/propiedades/lote-esquina"


def _guion_ficha(textos, caption="Lote frente al mar."):
    """Guion hook + puntos + cta con los textos dados (el último es el cta)."""
    roles = ["hook"] + ["punto"] * (len(textos) - 2) + ["cta"]
    return {"tema": "lote", "hook": textos[0], "caption": caption,
            "cta": textos[-1],
            "slides": [{"text": t, "rol": r, "image_hint": "x"}
                       for t, r in zip(textos, roles)]}


def _contrato(cx, qid):
    return json_mod.loads(db_mod.get(cx, "content_queue", qid)["slideshow_json"])


def _textos(contrato):
    return [" ".join(t["text"] for t in s["text_items"]) for s in contrato["slides"]]


def test_url_inventada_se_reemplaza_por_la_de_la_entidad(monkeypatch, tmp_path) -> None:
    cx, _, _ = _preparar(monkeypatch, tmp_path)
    monkeypatch.setattr(gs.slideshow_script, "generar_guion", lambda tema, **kw: _guion_ficha(
        ["Lote en Melaque", "Más en melaquewcrealestate.com",
         "Ve la ficha en melaquewestcoastrealestate.com"],
        caption="Info: www.melaquewcrealestate.com o ventas@melaquewc.com"))
    qid = gs.generar(cx, "lote", hechos={"m2": 300}, entity_id=1, url_entidad=URL)
    contrato = _contrato(cx, qid)
    textos = _textos(contrato)
    caption = db_mod.get(cx, "content_queue", qid)["caption"]
    assert URL in textos[-1] and URL in caption
    todo = " ".join(textos) + " " + caption
    assert "melaquewc" not in todo and "westcoast" not in todo
    assert URL not in textos[1]                     # slides intermedios: se quita
    assert caption.count(URL) == 1


def test_url_omitida_se_agrega_al_cta_y_caption(monkeypatch, tmp_path) -> None:
    cx, _, _ = _preparar(monkeypatch, tmp_path)
    monkeypatch.setattr(gs.slideshow_script, "generar_guion", lambda tema, **kw: _guion_ficha(
        ["Lote en Melaque", "300 m2", "Ve la ficha completa"]))
    qid = gs.generar(cx, "lote", hechos={"m2": 300}, entity_id=1, url_entidad=URL)
    textos = _textos(_contrato(cx, qid))
    assert textos[-1].startswith("Ve la ficha completa") and textos[-1].endswith(URL)
    assert URL in db_mod.get(cx, "content_queue", qid)["caption"]


def test_url_correcta_no_se_duplica(monkeypatch, tmp_path) -> None:
    cx, _, _ = _preparar(monkeypatch, tmp_path)
    monkeypatch.setattr(gs.slideshow_script, "generar_guion", lambda tema, **kw: _guion_ficha(
        ["Lote", "300 m2", f"Ficha: {URL}"], caption=f"Mira {URL}."))
    qid = gs.generar(cx, "lote", hechos={"m2": 300}, entity_id=1, url_entidad=URL)
    textos = _textos(_contrato(cx, qid))
    assert textos[-1] == f"Ficha: {URL}"
    assert db_mod.get(cx, "content_queue", qid)["caption"].count(URL) == 1


def test_prompt_prohibe_urls_y_oculta_unverified(monkeypatch, tmp_path) -> None:
    cx, _, _ = _preparar(monkeypatch, tmp_path)
    vistos = []
    monkeypatch.setattr(gs.slideshow_script, "generar_guion",
                        lambda tema, **kw: vistos.append(kw) or _guion_ficha(
                            ["Lote", "300 m2", "Ver ficha"]))
    gs.generar(cx, "lote", hechos={"m2": 300, "regimen": "escriturada"},
               no_verificados=["regimen"], entity_id=1, url_entidad=URL)
    ctx = vistos[0]["contexto"]
    assert "No escribas URLs" in ctx
    assert "TEMAS SIN CONFIRMAR: regimen" in ctx
    assert "escriturada" not in ctx                 # el valor no confirmado no llega


def test_unverified_afirmado_regenera_una_vez_y_pasa(monkeypatch, tmp_path) -> None:
    cx, _, enviados = _preparar(monkeypatch, tmp_path)
    llamadas = []

    def _spy(tema, **kw):
        llamadas.append(kw.get("feedback"))
        punto = "Escriturado, 300 m2" if len(llamadas) == 1 else "300 m2"
        return _guion_ficha(["Lote", punto, "Ver ficha"])

    monkeypatch.setattr(gs.slideshow_script, "generar_guion", _spy)
    qid = gs.generar(cx, "lote", hechos={"m2": 300, "regimen": "escriturada"},
                     no_verificados=["regimen"], entity_id=1)
    assert qid is not None and len(llamadas) == 2
    assert llamadas[0] is None and "regimen" in llamadas[1]
    assert not enviados[0][0].startswith("⚠️")


def test_unverified_afirmado_dos_veces_descarta(monkeypatch, tmp_path) -> None:
    import pytest
    cx, subidas, enviados = _preparar(monkeypatch, tmp_path)
    monkeypatch.setattr(gs.slideshow_script, "generar_guion", lambda tema, **kw: _guion_ficha(
        ["Lote", "Con certeza jurídica", "Ver ficha"]))
    with pytest.raises(gs.TextoNoPermitido, match="regimen"):
        gs.generar(cx, "lote", hechos={"m2": 300, "regimen": "escriturada"},
                   no_verificados=["regimen"])
    assert subidas == [] and enviados == []
    assert db.rows(cx, "SELECT * FROM content_queue") == []


def test_cifra_de_clave_unverified_no_es_citable(monkeypatch, tmp_path) -> None:
    import pytest
    cx, _, _ = _preparar(monkeypatch, tmp_path)
    monkeypatch.setattr(gs.slideshow_script, "generar_guion", lambda tema, **kw: _guion_ficha(
        ["Lote", "Mide 450 m2", "Ver ficha"]))
    with pytest.raises(gs.CifrasFueraDeFacts):
        gs.generar(cx, "lote", hechos={"m2": 450}, no_verificados=["m2"])


def test_listo_para_escriturar_regenera_y_descarta(monkeypatch, tmp_path) -> None:
    import pytest
    cx, _, _ = _preparar(monkeypatch, tmp_path)
    llamadas = []

    def _spy(tema, **kw):
        llamadas.append(kw)
        return _guion_ficha(["Lote", "Escriturado y listo para escriturar", "Ver ficha"])

    monkeypatch.setattr(gs.slideshow_script, "generar_guion", _spy)
    with pytest.raises(gs.TextoNoPermitido, match="listo para escritur"):
        gs.generar(cx, "lote", hechos={"regimen": "escriturada"})
    assert len(llamadas) == 2
    assert "UNA sola vez" in llamadas[0]["contexto"] and "«escriturada»" in llamadas[0]["contexto"]
    assert "listo para escritur" in llamadas[1]["feedback"]


def test_regimen_verificado_textual_pasa(monkeypatch, tmp_path) -> None:
    cx, _, _ = _preparar(monkeypatch, tmp_path)
    monkeypatch.setattr(gs.slideshow_script, "generar_guion", lambda tema, **kw: _guion_ficha(
        ["Lote", "Régimen: escriturada", "Ver ficha"]))
    assert gs.generar(cx, "lote", hechos={"regimen": "escriturada"}) is not None


def test_tipo_sin_confirmar_prompt_dice_propiedad_y_valida(monkeypatch, tmp_path) -> None:
    import pytest
    cx, _, _ = _preparar(monkeypatch, tmp_path)
    vistos = []
    monkeypatch.setattr(gs.slideshow_script, "generar_guion",
                        lambda tema, **kw: vistos.append(kw) or _guion_ficha(
                            ["Departamento en Melaque", "300 m2", "Ver ficha"]))
    with pytest.raises(gs.TextoNoPermitido, match="tipo"):
        gs.generar(cx, "lote", hechos={"m2": 300, "tipo": "departamento"},
                   no_verificados=["tipo"])
    assert "«propiedad»" in vistos[0]["contexto"]
    assert "departamento" not in vistos[0]["contexto"].split("REGLAS DE LA FICHA")[0]


def _fotos_spy(monkeypatch, vistas):
    def _resolver_spy(hints, fuentes, **kw):
        vistas["f"] = fuentes
        provider = kw["providers"]["entidad"]
        urls = list(dict.fromkeys(provider.urls))
        return [_Img(urls[k], "entidad") if k < len(urls) else None
                for k in range(len(hints))]
    monkeypatch.setattr(gs.image_sources, "resolver", _resolver_spy)


def test_fotos_suficientes_no_se_repiten_y_recorta_slides(monkeypatch, tmp_path) -> None:
    """4 fotos distintas y 6 slides pedidos → 4 slides, una foto cada uno."""
    from src import marcas_seed
    cx, _, _ = _preparar(monkeypatch, tmp_path)
    marcas_seed.sembrar(cx)
    pedidos = []
    monkeypatch.setattr(gs.slideshow_script, "generar_guion",
                        lambda tema, **kw: pedidos.append(kw["n_slides"]) or _guion_ficha(
                            ["Casa", "Uno", "Dos", "Ver"][:kw["n_slides"]]))
    vistas = {}
    _fotos_spy(monkeypatch, vistas)
    fotos = [f"/e/{i}.jpg" for i in range(4)] + ["/e/0.jpg"]   # duplicada en la media
    qid = gs.generar(cx, "casa", marca="melaquecapital", n_slides=6,
                     imagenes_preferidas=fotos)
    contrato = _contrato(cx, qid)
    assert pedidos == [4] and vistas["f"] == ["entidad"]
    usadas = [s["image_urls"][0] for s in contrato["slides"]]
    assert len(usadas) == len(set(usadas)) == 4


def test_pocas_fotos_repite_lo_minimo_para_tres(monkeypatch, tmp_path) -> None:
    from src import marcas_seed
    cx, _, _ = _preparar(monkeypatch, tmp_path)
    marcas_seed.sembrar(cx)
    pedidos = []
    monkeypatch.setattr(gs.slideshow_script, "generar_guion",
                        lambda tema, **kw: pedidos.append(kw["n_slides"]) or _guion_ficha(
                            ["Casa", "Uno", "Ver"]))
    vistas = {}
    _fotos_spy(monkeypatch, vistas)
    qid = gs.generar(cx, "casa", marca="melaquecapital", n_slides=6,
                     imagenes_preferidas=["/e/1.jpg", "/e/2.jpg"])
    contrato = _contrato(cx, qid)
    assert pedidos == [3]
    usadas = [s["image_urls"][0] for s in contrato["slides"]]
    assert usadas == ["/e/1.jpg", "/e/2.jpg", "/e/1.jpg"]
    assert {s["source"] for s in contrato["slides"]} == {"entidad"}
